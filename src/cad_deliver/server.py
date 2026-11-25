"""MCP server: stage, verify offline, commit.

Transport note — read this before adding a log line anywhere in this package.

MCP over stdio uses **stdout for JSON-RPC frames**. Anything else written there
corrupts the stream and the client disconnects with a parse error that says
nothing about the real cause. So this module, at import time:

  * points `print` at stderr for the whole process, and
  * configures `logging` to stderr.

`sys.stdout` itself is left alone, because the MCP transport writes the protocol
through it. A stray `print("debug")` then lands in the server's stderr log
instead of in the middle of a JSON-RPC frame. That is the isolation the whole
server depends on, and it is done first, before anything else is imported.
"""

from __future__ import annotations

import builtins
import logging
import os
import shutil
import sys

# --------------------------------------------------------------------------
# stdout guard — must run before the MCP transport grabs sys.stdout.
# --------------------------------------------------------------------------
_ORIGINAL_PRINT = builtins.print


def _print_to_stderr(*args, **kwargs):  # pragma: no cover - trivial shim
    kwargs.setdefault("file", sys.stderr)
    _ORIGINAL_PRINT(*args, **kwargs)


builtins.print = _print_to_stderr

logging.basicConfig(
    stream=sys.stderr,
    level=os.environ.get("CAD_DELIVER_LOG_LEVEL", "INFO").upper(),
    format="[cad-deliver] %(levelname)s %(message)s",
)
log = logging.getLogger("cad_deliver.server")

# --------------------------------------------------------------------------

import json  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

from .models import StageState, Verdict  # noqa: E402
from .pipeline import verify_file  # noqa: E402
from .rules import DEFAULT_PROFILE, available_profiles  # noqa: E402
from .state_machine import StagingStore  # noqa: E402

SERVER_NAME = "cad-deliver-mcp"

INSTRUCTIONS = """\
Pre-delivery gatekeeper for CAD artefacts. Three calls, in this order:

  deliver_stage(paths)                  copy the files and record their SHA-256
  deliver_verify(staging_id)            judge the staged copies offline
  deliver_commit(staging_id, target)    release them only if verification passed

Rules that matter:
  * commit refuses anything that is not VERIFIED, and refuses if the staged bytes
    changed since staging. Do not try to work around it; stage again.
  * commit never overwrites an existing file unless overwrite=true is passed
    explicitly. A name collision is a version question for a human, not something
    this tool resolves by appending a suffix.
  * a verdict of UNKNOWN means a reader was missing, not that the file is good.
    Install the dependency and verify again rather than reporting success.
"""


# ------------------------------------------------------------------ helpers


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _expand(paths: str | list[str]) -> list[str]:
    """Accept one file, several files, or a folder, and return the files."""
    items = [paths] if isinstance(paths, str) else list(paths)
    out: list[str] = []
    for item in items:
        target = Path(item)
        if target.is_dir():
            out.extend(str(p) for p in sorted(target.rglob("*")) if p.is_file())
        elif target.is_file():
            out.append(str(target))
        else:
            raise FileNotFoundError(f"nothing at {item}")
    # Never stage our own bookkeeping.
    return [p for p in out if ".deliver-staging" not in p.replace("\\", "/")]


def _atomic_place(source: Path, destination: Path) -> None:
    """Put a file at its final name in one step.

    The copy lands as `<name>.partial` in the *destination* folder, is flushed to
    disk, and only then renamed. A crash therefore leaves either the old state or
    a .partial file — never a half-written file under the real name. Doing the
    rename inside the destination folder also keeps it atomic across drives,
    where `os.replace` between two folders would not be.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".partial")
    shutil.copy2(source, partial)
    with open(partial, "rb+") as handle:
        os.fsync(handle.fileno())
    os.replace(partial, destination)


# ------------------------------------------------------------------ server


def create_server(store: StagingStore | None = None) -> "FastMCP":
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise SystemExit(
            "the MCP SDK is not installed; install it with: pip install 'cad-deliver-mcp[mcp]'"
        ) from exc

    store = store or StagingStore(os.environ.get("CAD_DELIVER_STAGING"))
    mcp = FastMCP(SERVER_NAME, instructions=INSTRUCTIONS)

    @mcp.tool()
    def deliver_stage(paths: str, profile: str = DEFAULT_PROFILE) -> dict[str, Any]:
        """Copy files into a staging area and record their SHA-256.

        `paths` is a file, a folder, or a comma-separated list. `profile` chooses
        the standard rule set used later by deliver_verify: GB_T_TIER1 (default),
        ISO_216_TIER1, or LEGACY_COMPAT (no standard rules, file checks only).
        Nothing is judged here — this only records what is being delivered.
        """
        if profile not in available_profiles():
            return {
                "ok": False,
                "code": "E_UNKNOWN_PROFILE",
                "reason": f"unknown profile {profile!r}",
                "known": available_profiles(),
            }

        try:
            files = _expand(paths)
        except FileNotFoundError as exc:
            return {"ok": False, "code": "E_NO_INPUT", "reason": str(exc)}

        if not files:
            return {"ok": False, "code": "E_NO_INPUT", "reason": "no file to stage"}

        record = store.create(files, profile)
        log.info("staged %s with %d file(s) under profile %s", record.staging_id, len(files), profile)
        return {
            "ok": True,
            "staging_id": record.staging_id,
            "profile": record.profile,
            "state": record.state,
            "files": [
                {"name": f.name, "bytes": f.bytes, "sha256": f.sha256, "source": f.source}
                for f in record.files
            ],
            "next": "deliver_verify",
        }

    @mcp.tool()
    def deliver_verify(staging_id: str) -> dict[str, Any]:
        """Judge the staged copies offline: file checks, then the profile's rules.

        Runs no CAD application. A verdict of PASS means the files hold up;
        FAIL means they do not; UNKNOWN means a reader was missing. The staged
        bytes are re-hashed first, so a file edited after staging is caught here.
        """
        try:
            record = store.load(staging_id)
        except (KeyError, json.JSONDecodeError):
            return {"ok": False, "code": "E_UNKNOWN_STAGING", "reason": f"no staging record {staging_id}"}

        if record.state == StageState.EXPIRED.value:
            return {
                "ok": False,
                "code": "E_STAGING_EXPIRED",
                "reason": "the staging record is past its time to live; stage the files again",
            }

        record.attempts += 1
        record.touch(f"verify attempt {record.attempts}")

        changed = store.verify_hashes(record)
        if changed:
            record.state = StageState.FAILED.value
            record.reason = "staged bytes changed before verification: " + ", ".join(changed)
            record.code = "E_HASH_CHANGED"
            store.save(record)
            return {
                "ok": False,
                "staging_id": staging_id,
                "state": record.state,
                "verdict": Verdict.FAIL.value,
                "code": record.code,
                "reason": record.reason,
                "changed": changed,
            }

        files = []
        rules: list[dict] = []
        checks: list[dict] = []
        fixes: list[str] = []
        for item in record.files:
            staged_path = store.files_dir(staging_id) / item.rel
            verdict = verify_file(staged_path, record.profile)
            files.append(verdict.as_dict())
            for check in verdict.checks:
                entry = check.as_dict()
                entry["file"] = item.name
                checks.append(entry)
            for rule in verdict.rules:
                entry = rule.as_dict()
                entry["file"] = item.name
                rules.append(entry)
            fixes.extend(verdict.fixes())

        errors = [c for c in checks if not c["ok"] and c["severity"] == "error"]
        errors += [r for r in rules if not r["ok"] and r["severity"] == "error"]
        blocked = [c for c in checks if not c["ok"] and c["severity"] == "blocked"]
        blocked += [r for r in rules if not r["ok"] and r["severity"] == "blocked"]

        if errors:
            overall = Verdict.FAIL
        elif blocked:
            overall = Verdict.UNKNOWN
        else:
            overall = Verdict.PASS

        record.verdict = overall.value
        record.checks = checks
        record.rules = rules
        record.counts = {
            "files": len(record.files),
            "errors": len(errors),
            "blocked": len(blocked),
            "warnings": len([c for c in checks if not c["ok"] and c["severity"] == "warning"])
            + len([r for r in rules if not r["ok"] and r["severity"] == "warning"]),
        }
        if overall is Verdict.PASS:
            record.state = StageState.VERIFIED.value
            record.code = None
            record.reason = None
        else:
            # Both FAIL and UNKNOWN leave the gate closed. They are reported
            # differently because "the drawing is wrong" and "I could not read
            # it" call for different actions from the caller.
            record.state = StageState.FAILED.value
            if overall is Verdict.UNKNOWN:
                record.code = "E_NOT_JUDGED"
                record.reason = "a reader was missing, so the delivery was not judged"
        record.touch(f"verify -> {overall.value}")
        store.save(record)

        log.info("verify %s -> %s (errors=%d blocked=%d)", staging_id, overall.value,
                 len(errors), len(blocked))
        return {
            "ok": overall is not Verdict.FAIL,
            "staging_id": staging_id,
            "state": record.state,
            "verdict": overall.value,
            "profile": record.profile,
            "counts": record.counts,
            "files": files,
            "checks": checks,
            "rules": rules,
            "fixes": fixes,
            "code": record.code,
            "reason": record.reason,
        }

    @mcp.tool()
    def deliver_commit(
        staging_id: str, target_dir: str, overwrite: bool = False
    ) -> dict[str, Any]:
        """Release verified files into the delivery folder.

        Refuses unless the record is VERIFIED and the staged bytes still match
        the hashes taken at stage time. Refuses to overwrite an existing file
        unless `overwrite` is passed explicitly: a name collision is a version
        decision, so no suffix is invented here.
        """
        try:
            record = store.load(staging_id)
        except (KeyError, json.JSONDecodeError):
            return {"ok": False, "code": "E_UNKNOWN_STAGING", "reason": f"no staging record {staging_id}"}

        if record.state == StageState.EXPIRED.value:
            return {"ok": False, "code": "E_STAGING_EXPIRED", "reason": "the staging record expired"}

        if record.state != StageState.VERIFIED.value:
            return {
                "ok": False,
                "code": "E_NOT_VERIFIED",
                "state": record.state,
                "reason": (
                    f"state is {record.state}, not VERIFIED"
                    + (f": {record.reason}" if record.reason else "")
                ),
            }

        changed = store.verify_hashes(record)
        if changed:
            record.state = StageState.FAILED.value
            record.code = "E_HASH_CHANGED"
            record.reason = "staged bytes changed after verification: " + ", ".join(changed)
            store.save(record)
            return {
                "ok": False,
                "code": record.code,
                "state": record.state,
                "reason": record.reason,
                "changed": changed,
            }

        target = Path(target_dir)
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return {"ok": False, "code": "E_TARGET_UNWRITABLE", "reason": str(exc)}

        collisions = [item.name for item in record.files if (target / item.name).exists()]
        if collisions and not overwrite:
            return {
                "ok": False,
                "code": "E_TARGET_EXISTS",
                "reason": (
                    "the delivery folder already contains "
                    + ", ".join(sorted(collisions))
                    + "; pass overwrite=true only if replacing them is intended"
                ),
                "collisions": sorted(collisions),
            }

        placed = []
        try:
            for item in record.files:
                source = store.files_dir(staging_id) / item.rel
                destination = target / item.name
                _atomic_place(source, destination)
                placed.append(
                    {"path": str(destination), "bytes": destination.stat().st_size, "sha256": item.sha256}
                )
        except OSError as exc:
            record.state = StageState.FAILED.value
            record.reason = f"commit failed after placing {len(placed)} file(s): {exc}"
            record.code = "E_COMMIT_FAILED"
            store.save(record)
            return {
                "ok": False,
                "code": record.code,
                "reason": record.reason,
                "placed": placed,
            }

        record.state = StageState.COMMITTED.value
        record.committed_to = str(target.resolve())
        record.code = None
        record.reason = None
        record.touch(f"committed {len(placed)} file(s) to {target}")
        store.save(record)

        log.info("commit %s -> %s (%d file(s))", staging_id, target, len(placed))
        return {
            "ok": True,
            "staging_id": staging_id,
            "state": record.state,
            "target_dir": str(target.resolve()),
            "committed": placed,
            "committed_at": _now(),
        }

    @mcp.resource("deliver://audit/{staging_id}")
    def audit(staging_id: str) -> str:
        """Full audit record: hashes, every verify attempt, findings and fixes."""
        try:
            return json.dumps(store.audit(staging_id), indent=2, ensure_ascii=False)
        except (KeyError, json.JSONDecodeError):
            return json.dumps({"error": f"no staging record {staging_id}"}, ensure_ascii=False)

    return mcp


def main(argv: list[str] | None = None) -> int:
    """Run the stdio server. Diagnostics go to stderr; stdout is the protocol."""
    store_root = os.environ.get("CAD_DELIVER_STAGING")
    log.info("starting %s (staging root: %s)", SERVER_NAME, store_root or "<temp>")
    server = create_server(StagingStore(store_root))
    try:
        server.run("stdio")
    except KeyboardInterrupt:  # pragma: no cover
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())