"""The CLI must not change what `dsh-sw-cad deliver` already meant.

Three things are pinned here:

  1. no --profile  -> LEGACY_COMPAT: a missing title block and a non-standard
     sheet are warnings, and the exit code stays 0
  2. --profile GB_T_TIER1 -> the same two findings become errors and block (1)
  3. an unparsable file -> UNKNOWN (2), never PASS and never "the drawing is bad"

The drawing used below is deliberately "clean except for the two things under
test": every other check passes, so a failure proves the rule layer did it and
not some unrelated finding.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cad_deliver.cli import main

try:
    import ezdxf
except ImportError:  # pragma: no cover
    ezdxf = None


def build_clean_but_untitled(path: Path) -> bool:
    """A3-ish drawing with a real dimension, a stated scale, two line weights —
    but a 400x280 sheet and no title block. Returns False when ezdxf is absent."""
    if ezdxf is None:
        return False

    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4                       # millimetres
    doc.layers.add("粗实线", lineweight=50)
    doc.layers.add("细实线", lineweight=13)
    doc.layers.add("标注", lineweight=13)
    doc.styles.add("GB", font="fangsong.ttf")

    msp = doc.modelspace()
    msp.add_lwpolyline(
        [(0, 0), (100, 0), (100, 60), (0, 60)], close=True, dxfattribs={"layer": "粗实线"}
    )
    dim = msp.add_linear_dim(base=(0, -12), p1=(0, 0), p2=(100, 0))
    dim.render()
    dim.dimension.dxf.layer = "标注"                  # so the layer rule stays quiet

    sheet = doc.layouts.get("Layout1")
    sheet.dxf.paper_width, sheet.dxf.paper_height = 400.0, 280.0   # not an ISO sheet
    sheet.add_lwpolyline(
        [(0, 0), (400, 0), (400, 280), (0, 280)], close=True, dxfattribs={"layer": "细实线"}
    )
    sheet.add_text("比例 1:2", dxfattribs={"height": 4, "style": "GB"}).set_placement((20, 20))
    # No title block on purpose.

    doc.saveas(path)
    return True


def broken_dxf(path: Path) -> None:
    """Enough bytes to pass the size check, but not a DXF."""
    path.write_bytes(b"NOT A DXF AT ALL\n" + b"x" * 3000)


def run_cli(folder: Path, *extra: str) -> tuple[int, dict]:
    out = folder / "delivery.json"
    code = main([str(folder), "--out", str(out), *extra])
    report = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    return code, report


# ---------------------------------------------------------------- case 1

def test_default_profile_is_legacy_compat():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        source = folder / "part.dxf"
        if not build_clean_but_untitled(source):
            print("  skip (ezdxf not installed)")
            return

        code, report = run_cli(folder)

        assert report["profile"] == "LEGACY_COMPAT", f"default must be LEGACY_COMPAT, got {report['profile']}"
        assert report["rule_profile"] == "LEGACY_COMPAT"
        assert not report["rules"], "the compatible profile must run no standard rule"
        assert code == 0, f"warnings must not block: verdict={report['verdict']}"

        ids = {c["id"]: c for c in report["files"][0]["checks"]}

        # Non-standard sheet: noticed, but only as a warning in this profile.
        assert "drawing.sheet" in ids, f"sheet check missing from {sorted(ids)}"
        assert not ids["drawing.sheet"]["ok"]
        assert ids["drawing.sheet"]["severity"] == "warning"

        # The legacy title-block check is satisfied by field-like text on the
        # sheet, so a drawing with 比例 but no block passes it here. That gap is
        # exactly why the rule layer exists — GB_T_TIER1 requires a real block
        # with filled attributes (see the next test). Asserting the gap keeps
        # the behaviour from changing silently in either direction.
        assert ids["drawing.titleblock"]["ok"], (
            "the legacy check passes on field text alone; if this changed, "
            "GB_T_TIER1's added value needs re-measuring"
        )

        assert report["counts"]["failures"] == 0
        assert report["counts"]["warnings"] >= 1


# ---------------------------------------------------------------- case 2

def test_gb_tier1_blocks_on_the_same_drawing():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        source = folder / "part.dxf"
        if not build_clean_but_untitled(source):
            print("  skip (ezdxf not installed)")
            return

        code, report = run_cli(folder, "--profile", "GB_T_TIER1")

        assert report["rule_profile"] == "GB_T_TIER1"
        assert code == 1, f"an error must block: verdict={report['verdict']}"

        codes = {r["code"]: r for r in report["rules"]}
        assert "E_SHEET_SIZE" in codes, f"sheet rule missing from {sorted(codes)}"
        assert "E_TITLE_BLOCK" in codes, f"title block rule missing from {sorted(codes)}"
        assert not codes["E_SHEET_SIZE"]["ok"]
        assert not codes["E_TITLE_BLOCK"]["ok"]
        assert codes["E_SHEET_SIZE"]["severity"] == "error"
        assert codes["E_TITLE_BLOCK"]["severity"] == "error"

        # The rule results must carry their evidence and a concrete fix.
        for code_name in ("E_SHEET_SIZE", "E_TITLE_BLOCK"):
            entry = codes[code_name]
            assert entry["evidence"], f"{code_name} must carry evidence"
            assert entry["fix"], f"{code_name} must carry a concrete fix"
            assert entry["file"] == "part.dxf", "each rule result names the file it came from"


# ---------------------------------------------------------------- case 3

def test_unparsable_file_exits_2():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        broken_dxf(folder / "broken.dxf")

        code, report = run_cli(folder)

        assert code == 2, f"a file that cannot be read is UNKNOWN, got {code} ({report.get('verdict')})"
        assert report["verdict"] == "unknown"
        assert report["counts"]["blocked"] >= 1
        blocked_ids = {b["id"] for b in report["blocked"]}
        assert "dxf.parsed" in blocked_ids, f"expected dxf.parsed among {blocked_ids}"


def test_exit_codes_map_one_to_one():
    """0/1/2 must stay distinct: a script has to tell 'bad' from 'unjudged'."""
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        if not build_clean_but_untitled(folder / "part.dxf"):
            print("  skip (ezdxf not installed)")
            return

        ok, _ = run_cli(folder)
        blocked, _ = run_cli(folder, "--profile", "GB_T_TIER1")
        assert (ok, blocked) == (0, 1)

        broken = folder / "broken"
        broken.mkdir()
        broken_dxf(broken / "broken.dxf")
        unknown, _ = run_cli(broken)
        assert unknown == 2
        assert len({ok, blocked, unknown}) == 3, "the three codes must not collide"


def main_entry() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\nlegacy compat: {len(tests) - failed}/{len(tests)} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main_entry())