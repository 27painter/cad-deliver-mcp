"""Three-phase server tests: stage, verify, commit — including every refusal.

No CAD application and no ezdxf needed: a STEP file carries the whole flow, and
the rule layer is exercised separately in test_rules.py.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cad_deliver.models import StageState
from cad_deliver.server import create_server
from cad_deliver.state_machine import StagingStore, digest


def step_file(target: Path, schema: str = "AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }",
              count: int = 300) -> Path:
    lines = [
        "ISO-10303-21;", "HEADER;", "FILE_DESCRIPTION((''),'2;1');",
        "FILE_NAME('part.step','2026-11-25T00:00:00',(''),(''),'','','');",
        f"FILE_SCHEMA(('{schema}'));", "ENDSEC;", "DATA;",
    ]
    for i in range(1, count + 1):
        lines.append(f"#{i}=CARTESIAN_POINT('',({i}.0,0.0,0.0));")
    lines += ["ENDSEC;", "END-ISO-10303-21;", ""]
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def call(server, name: str, arguments: dict) -> dict:
    """FastMCP tools are async and return (content_blocks, structured_dict)."""
    result = server.call_tool(name, arguments)
    if inspect.isawaitable(result):
        result = asyncio.run(result)
    if isinstance(result, dict):
        return result
    # (Sequence[ContentBlock], dict | None) — the dict is what we assert on.
    if isinstance(result, tuple) and len(result) == 2:
        content, structured = result
        if isinstance(structured, dict):
            return structured
        result = content
    if isinstance(result, (list, tuple)) and result:
        text = getattr(result[0], "text", None)
        if text:
            return json.loads(text)
    raise AssertionError(f"unexpected tool result: {result!r}")


def fresh(tmp: Path):
    store = StagingStore(tmp / "staging")
    return store, create_server(store)


# ---------------------------------------------------------------- happy path

def test_three_phase_happy_path():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        store, server = fresh(base)
        source = step_file(base / "part.step")
        target = base / "delivery"

        staged = call(server, "deliver_stage", {"paths": str(source), "profile": "GB_T_TIER1"})
        assert staged["ok"], staged
        staging_id = staged["staging_id"]
        assert staged["state"] == StageState.STAGED.value
        assert staged["files"][0]["sha256"] == digest(source)

        verified = call(server, "deliver_verify", {"staging_id": staging_id})
        assert verified["verdict"] == "PASS", verified
        assert verified["state"] == StageState.VERIFIED.value

        committed = call(
            server, "deliver_commit", {"staging_id": staging_id, "target_dir": str(target)}
        )
        assert committed["ok"], committed
        assert committed["state"] == StageState.COMMITTED.value
        assert (target / "part.step").is_file()
        assert digest(target / "part.step") == digest(source)
        assert not list(target.glob("*.partial")), "no half-written file may remain"


# ---------------------------------------------------------------- refusals

def test_commit_before_verify_is_refused():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        store, server = fresh(base)
        source = step_file(base / "part.step")
        staging_id = call(server, "deliver_stage", {"paths": str(source)})["staging_id"]

        out = call(
            server, "deliver_commit",
            {"staging_id": staging_id, "target_dir": str(base / "delivery")},
        )
        assert not out["ok"]
        assert out["code"] == "E_NOT_VERIFIED"
        assert not (base / "delivery" / "part.step").exists()


def test_tamper_after_verify_is_refused():
    """The whole reason staging records a hash."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        store, server = fresh(base)
        source = step_file(base / "part.step")
        staging_id = call(server, "deliver_stage", {"paths": str(source)})["staging_id"]
        call(server, "deliver_verify", {"staging_id": staging_id})

        staged_copy = store.files_dir(staging_id) / "part.step"
        staged_copy.write_text("tampered after verification", encoding="utf-8")

        out = call(
            server, "deliver_commit",
            {"staging_id": staging_id, "target_dir": str(base / "delivery")},
        )
        assert not out["ok"]
        assert out["code"] == "E_HASH_CHANGED"
        assert not (base / "delivery" / "part.step").exists()


def test_collision_is_refused_and_overwrite_opt_in_works():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        store, server = fresh(base)
        source = step_file(base / "part.step")
        target = base / "delivery"
        target.mkdir()
        (target / "part.step").write_text("an older version", encoding="utf-8")

        staging_id = call(server, "deliver_stage", {"paths": str(source)})["staging_id"]
        call(server, "deliver_verify", {"staging_id": staging_id})

        blocked = call(
            server, "deliver_commit", {"staging_id": staging_id, "target_dir": str(target)}
        )
        assert not blocked["ok"]
        assert blocked["code"] == "E_TARGET_EXISTS"
        assert (target / "part.step").read_text(encoding="utf-8") == "an older version", \
            "a refused commit must not touch the existing file"
        # No invented suffix may appear either.
        assert not list(target.glob("part_*.step"))

        allowed = call(
            server, "deliver_commit",
            {"staging_id": staging_id, "target_dir": str(target), "overwrite": True},
        )
        assert allowed["ok"], allowed
        assert (target / "part.step").read_text(encoding="utf-8").startswith("ISO-10303-21")


def test_unknown_profile_and_unknown_staging():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        store, server = fresh(base)
        source = step_file(base / "part.step")

        bad = call(server, "deliver_stage", {"paths": str(source), "profile": "NOPE"})
        assert not bad["ok"] and bad["code"] == "E_UNKNOWN_PROFILE"
        assert "GB_T_TIER1" in bad["known"]

        missing = call(server, "deliver_verify", {"staging_id": "does-not-exist"})
        assert not missing["ok"] and missing["code"] == "E_UNKNOWN_STAGING"


def test_failed_verify_does_not_release_the_gate():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        store, server = fresh(base)
        # AP203 with 40 points: wrong schema and too little geometry.
        source = step_file(base / "part.step", schema="CONFIG_CONTROL_DESIGN", count=40)
        staging_id = call(server, "deliver_stage", {"paths": str(source)})["staging_id"]

        verified = call(server, "deliver_verify", {"staging_id": staging_id})
        assert verified["verdict"] == "FAIL"
        assert verified["state"] == StageState.FAILED.value
        assert verified["fixes"], "a failure must carry at least one concrete fix"

        out = call(
            server, "deliver_commit",
            {"staging_id": staging_id, "target_dir": str(base / "delivery")},
        )
        assert not out["ok"] and out["code"] == "E_NOT_VERIFIED"


# ---------------------------------------------------------------- audit

def test_audit_resource_keeps_the_whole_history():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        store, server = fresh(base)
        source = step_file(base / "part.step")
        staging_id = call(server, "deliver_stage", {"paths": str(source)})["staging_id"]
        call(server, "deliver_verify", {"staging_id": staging_id})
        call(server, "deliver_verify", {"staging_id": staging_id})   # a second attempt

        record = store.audit(staging_id)
        assert record["attempts"] == 2
        assert record["state"] == StageState.VERIFIED.value
        assert len(record["history"]) >= 4          # staged + 2 verifies + touch
        assert record["files"][0]["sha256"]

        text = call_resource(server, staging_id)
        assert json.loads(text)["staging_id"] == staging_id


def call_resource(server, staging_id: str) -> str:
    reader = server.read_resource(f"deliver://audit/{staging_id}")
    if inspect.isawaitable(reader):
        reader = asyncio.run(reader)
    # FastMCP may hand back text directly or a list of content items.
    if isinstance(reader, str):
        return reader
    for item in reader:
        text = getattr(item, "content", None) or getattr(item, "text", None)
        if text:
            return text
    raise AssertionError(f"unexpected resource result: {reader!r}")


# ---------------------------------------------------------------- state machine

def test_expiry_marks_records_and_blocks_commit():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        store = StagingStore(base / "staging")
        source = step_file(base / "part.step")
        record = store.create([source], "GB_T_TIER1")
        record.state = StageState.VERIFIED.value
        record.created_at = "2000-01-01T00:00:00+00:00"
        store.save(record)

        assert store.load(record.staging_id).is_expired
        expired = store.expire_old()
        assert record.staging_id in expired
        assert store.load(record.staging_id).state == StageState.EXPIRED.value

        server = create_server(store)
        out = call(
            server, "deliver_commit",
            {"staging_id": record.staging_id, "target_dir": str(base / "delivery")},
        )
        assert not out["ok"] and out["code"] == "E_STAGING_EXPIRED"


# ---------------------------------------------------------------- stdout guard

def test_print_does_not_reach_stdout():
    """stdout is the JSON-RPC channel; a stray print would corrupt it."""
    import io
    import contextlib
    import cad_deliver.server  # noqa: F401  (installs the guard on import)

    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    with contextlib.redirect_stdout(captured_stdout), contextlib.redirect_stderr(captured_stderr):
        print("a diagnostic line")

    assert captured_stdout.getvalue() == "", "print must not write to stdout"
    assert "a diagnostic line" in captured_stderr.getvalue()


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001 - report, do not hide
            failed += 1
            print(f"  ERROR {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\nserver: {len(tests) - failed}/{len(tests)} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())