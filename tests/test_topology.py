"""Outline closure: the three rules that keep it from crying wolf.

Each test corresponds to a way a naive implementation produces false positives on
real SolidWorks / NX exports:

  1. a closed ring exported with the closed flag off
  2. ends that differ only by rounding noise
  3. centre lines, dimensions and frames counted as outline geometry

Pure ParsedDrawing construction: no CAD library, no files.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cad_deliver.geometry.topology import JOIN_TOLERANCE_MM, analyse, is_outline_layer
from cad_deliver.models import LayerInfo, ParsedDrawing, Segment
from cad_deliver.rules import run_profile
from cad_deliver.rules.codes import Code


def drawing(segments=None, closed=0, layers=None) -> ParsedDrawing:
    return ParsedDrawing(
        fmt="dxf",
        source_path="memory.dxf",
        segments=segments or [],
        closed_profiles=closed,
        layers=layers or [LayerInfo(name="轮廓线")],
    )


def line(layer, a, b) -> Segment:
    return Segment(kind="LINE", layer=layer, start=a, end=b)


def rectangle(layer, *, skip=()):
    """Four sides of a 100x60 box. `skip` drops a side, leaving a gap."""
    corners = [(0.0, 0.0), (100.0, 0.0), (100.0, 60.0), (0.0, 60.0)]
    sides = []
    for index in range(4):
        if index in skip:
            continue
        sides.append(line(layer, corners[index], corners[(index + 1) % 4]))
    return sides


# ---------------------------------------------------------------- closure

def test_closed_rectangle_has_no_dangling_end():
    result = analyse(drawing(rectangle("轮廓线")))
    assert result.is_clean, result.open
    assert result.closed == 1
    assert result.segments_considered == 4


def test_missing_side_leaves_two_dangling_ends():
    result = analyse(drawing(rectangle("轮廓线", skip={3})))
    assert not result.is_clean
    assert len(result.open) == 1, "one broken component"
    ends = result.open[0]
    assert len(ends) == 2, f"a missing side leaves two ends, got {ends}"
    assert (0.0, 60.0) in ends, ends
    assert (0.0, 0.0) in ends, ends


def test_two_separate_broken_components_are_reported_separately():
    segments = rectangle("轮廓线", skip={3}) + [
        line("轮廓线", (200.0, 0.0), (300.0, 0.0))
    ]
    result = analyse(drawing(segments))
    assert len(result.open) == 2, result.open


# ---------------------------------------------------------------- tolerance

def test_ends_within_tolerance_are_snapped_together():
    """0.008 mm apart is the same point; a round trip can produce that."""
    segments = [
        line("轮廓线", (0.0, 0.0), (100.0, 0.0)),
        line("轮廓线", (100.0 + 0.008, 0.0), (100.0, 60.0)),   # start is offset
        line("轮廓线", (100.0, 60.0), (0.0, 60.0)),
        line("轮廓线", (0.0, 60.0), (0.0, 0.0)),
    ]
    result = analyse(drawing(segments))
    assert result.is_clean, f"{JOIN_TOLERANCE_MM} mm noise must not open a profile: {result.open}"
    assert result.closed == 1


def test_ends_beyond_tolerance_stay_apart():
    segments = [
        line("轮廓线", (0.0, 0.0), (100.0, 0.0)),
        line("轮廓线", (100.0 + 0.02, 0.0), (100.0, 60.0)),    # a real gap
        line("轮廓线", (100.0, 60.0), (0.0, 60.0)),
        line("轮廓线", (0.0, 60.0), (0.0, 0.0)),
    ]
    result = analyse(drawing(segments))
    assert not result.is_clean, "0.02 mm is a real gap at this tolerance"


# ---------------------------------------------------------------- filtering

def test_circle_is_not_part_of_closure_analysis():
    drawing_with_circle = drawing(
        [Segment(kind="CIRCLE", layer="轮廓线", start=(0.0, 0.0), end=(10.0, 0.0))]
    )
    result = analyse(drawing_with_circle)
    assert result.segments_considered == 0
    assert result.is_clean, "a circle is closed by definition and must not be judged"


def test_non_outline_layers_are_ignored():
    """A centre line crossing the part must not count as an open outline."""
    segments = rectangle("轮廓线") + [
        line("中心线", (-10.0, 30.0), (110.0, 30.0)),
        line("标注", (0.0, -5.0), (0.0, -15.0)),
        line("图框", (0.0, 0.0), (420.0, 0.0)),
    ]
    result = analyse(drawing(segments, layers=[LayerInfo(name=n) for n in ("轮廓线", "中心线", "标注", "图框")]))
    assert result.is_clean, f"filtered lines opened the profile: {result.open}"
    assert result.segments_skipped == 3
    assert result.segments_considered == 4


def test_outline_layer_predicate():
    assert is_outline_layer("轮廓线")
    assert is_outline_layer("粗实线")
    assert is_outline_layer("0"), "layer 0 is a separate finding, not a reason to ignore geometry"
    for skipped in ("中心线", "细实线", "标注", "文字", "图框", "CENTER", "DIM", "TEXT", "FRAME"):
        assert not is_outline_layer(skipped), skipped


# ---------------------------------------------------------------- the rule

def test_rule_reports_open_profile_under_closure_profile():
    """Closure lives in PROFILE_CLOSURE: it does not apply to a multi-view drawing."""

    broken = drawing(rectangle("轮廓线", skip={3}))
    outline = analyse(broken)
    broken.open_profiles = outline.open
    broken.closed_profiles = outline.closed

    results = [r for r in run_profile(broken, "PROFILE_CLOSURE") if r.code == Code.PROFILE_OPEN.value]
    assert results, "the rule must fire on a broken outline"
    result = results[0]
    assert not result.ok
    assert result.severity.value == "error"
    assert "do not close" in result.detail
    assert result.fix and "0.01 mm" in result.fix
    assert any(e.kind == "location" for e in result.evidence)


def test_rule_stays_quiet_when_there_is_no_outline_to_judge():
    """No segments and nothing closed: a claim about nothing is not a pass."""
    empty = drawing()
    outline = analyse(empty)
    empty.open_profiles = outline.open
    empty.closed_profiles = outline.closed
    assert [r for r in run_profile(empty, "PROFILE_CLOSURE") if r.code == Code.PROFILE_OPEN.value] == []


def test_rule_passes_on_closed_outline():
    good = drawing(rectangle("轮廓线"))
    outline = analyse(good)
    good.open_profiles = outline.open
    good.closed_profiles = outline.closed
    results = [r for r in run_profile(good, "PROFILE_CLOSURE") if r.code == Code.PROFILE_OPEN.value]
    assert results and results[0].ok


def test_legacy_profile_does_not_run_the_rule():
    broken = drawing(rectangle("轮廓线", skip={3}))
    outline = analyse(broken)
    broken.open_profiles = outline.open
    broken.closed_profiles = outline.closed
    assert run_profile(broken, "LEGACY_COMPAT") == []


# ---------------------------------------------------------------- real export

def test_polyline_with_closed_flag_off_but_joined_ends_is_closed():
    """The SolidWorks/NX case: flag false, last vertex on the first."""
    try:
        import tempfile

        import ezdxf
    except ImportError:  # pragma: no cover
        print("  skip (ezdxf not installed)")
        return

    from cad_deliver.parsers.dxf import parse

    doc = ezdxf.new("R2018", setup=True)
    doc.layers.add("轮廓线", lineweight=50)
    msp = doc.modelspace()
    msp.add_lwpolyline(
        [(0, 0), (100, 0), (100, 60), (0, 60), (0, 0)],  # last point == first
        close=False,                                     # flag left off
        dxfattribs={"layer": "轮廓线"},
    )

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "flag-off.dxf"
        doc.saveas(path)
        parsed = parse(str(path)).drawing

    assert parsed is not None
    assert parsed.closed_profiles == 1, "the joined ends must be treated as closed"
    assert not parsed.segments, "a closed ring needs no segment record"
    assert analyse(parsed).is_clean


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
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\ntopology: {len(tests) - failed}/{len(tests)} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())