"""Rule-layer tests.

Everything here builds a ParsedDrawing by hand. No DXF, no ezdxf, no files: if a
test needed a CAD library to run, the orthogonal split would be a claim rather
than a fact.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cad_deliver.models import (
    AttribItem,
    BlockRef,
    DimInfo,
    LayerInfo,
    LayoutInfo,
    ParsedDrawing,
    Severity,
)
from cad_deliver.rules import (
    PROFILES,
    SEVERITY_PROFILES,
    LayerRole,
    classify,
    normalise,
    run_profile,
)
from cad_deliver.rules.codes import Code


def drawing(**kwargs) -> ParsedDrawing:
    base = dict(fmt="dxf", source_path="memory.dxf")
    base.update(kwargs)
    return ParsedDrawing(**base)


def by_code(results, code) -> list:
    return [r for r in results if r.code == code]


# ---------------------------------------------------------------- taxonomy

def test_normalise_strips_prefixes_and_folds_case():
    assert normalise("M-轮廓线") == "轮廓线"
    assert normalise("SW-MECH-CENTER") == "CENTER"
    assert normalise("  nx-  dim  ") == "DIM"
    assert normalise("粗实线") == "粗实线"


def test_seven_roles_are_reachable():
    cases = {
        "粗实线": LayerRole.CONTOUR_THICK,
        "细实线": LayerRole.THIN_AUX,
        "中心线": LayerRole.CENTERLINE,
        "虚线": LayerRole.HIDDEN_DASHED,
        "标注": LayerRole.DIMENSION,
        "文字": LayerRole.ANNOTATION_TEXT,
        "图框": LayerRole.FRAME_TITLE,
        "OUTLINE": LayerRole.CONTOUR_THICK,
        "HIDDEN": LayerRole.HIDDEN_DASHED,
        "CENTERLINES": LayerRole.CENTERLINE,
        "DIMENSIONS": LayerRole.DIMENSION,
        "FORMAT": LayerRole.FRAME_TITLE,
    }
    for name, expected in cases.items():
        got = classify(name).role
        assert got is expected, f"{name} -> {got}, expected {expected}"


def test_longest_alias_wins_over_shorter_containment():
    """"细实线" contains "实线": the longer alias must decide."""
    assert classify("细实线").role is LayerRole.THIN_AUX
    assert classify("粗实线").role is LayerRole.CONTOUR_THICK
    assert classify("剖面线").role is LayerRole.THIN_AUX


def test_unclassified_and_confidence():
    match = classify("随便画的层")
    assert match.role is LayerRole.UNCLASSIFIED
    assert match.confidence == 0.0


def test_structural_layers_are_not_unclassified():
    d = drawing(layers=[LayerInfo(name="0"), LayerInfo(name="DEFPOINTS")])
    results = run_profile(d, "GB_T_TIER1")
    unclassified = by_code(results, Code.LAYER_UNCLASSIFIED.value)[0]
    assert unclassified.ok, "0 and DEFPOINTS must not be reported as unclassified"


# ---------------------------------------------------------------- sheet size

def test_a3_sheet_passes_in_both_orientations():
    for w, h in ((420.0, 297.0), (297.0, 420.0)):
        d = drawing(layouts=[LayoutInfo(name="Layout1", paper_width=w, paper_height=h)])
        results = by_code(run_profile(d, "GB_T_TIER1"), Code.SHEET_SIZE.value)
        assert results and results[0].ok, f"{w}x{h} should be an A3 sheet"


def test_non_standard_sheet_fails_and_says_the_numbers():
    d = drawing(layouts=[LayoutInfo(name="L", paper_width=400.0, paper_height=280.0)])
    result = by_code(run_profile(d, "GB_T_TIER1"), Code.SHEET_SIZE.value)[0]
    assert not result.ok
    assert "400 x 280" in result.detail
    assert any(e.kind == "expected" for e in result.evidence)
    assert result.fix and "A4/A3" in result.fix


def test_no_paper_size_is_unknown_not_pass():
    d = drawing(layouts=[LayoutInfo(name="L")])
    result = by_code(run_profile(d, "GB_T_TIER1"), Code.SHEET_SIZE_UNKNOWN.value)[0]
    assert not result.ok
    assert "cannot be judged" in result.detail


def test_sheet_rule_is_reused_by_two_profiles():
    assert "gb.sheet_size" in PROFILES["GB_T_TIER1"]
    assert "gb.sheet_size" in PROFILES["ISO_216_TIER1"]
    assert "gb.sheet_size" not in PROFILES["LEGACY_COMPAT"]


# ---------------------------------------------------------------- layers

def test_dimension_on_outline_layer_fails():
    d = drawing(
        layers=[LayerInfo(name="粗实线"), LayerInfo(name="标注")],
        dimensions=[DimInfo(handle="A1", layer="粗实线", dimtype=0, measurement=10.0)],
        entity_layers={"粗实线": {"DIMENSION": 1, "LINE": 4}},
    )
    result = by_code(run_profile(d, "GB_T_TIER1"), Code.DIM_ON_WRONG_LAYER.value)[0]
    assert not result.ok
    assert "1 of 1" in result.detail
    assert result.severity is Severity.ERROR


def test_dimension_on_zero_layer_fails():
    d = drawing(
        layers=[LayerInfo(name="0")],
        dimensions=[DimInfo(handle="A1", layer="0", dimtype=0, measurement=10.0)],
    )
    result = by_code(run_profile(d, "GB_T_TIER1"), Code.DIM_ON_WRONG_LAYER.value)[0]
    assert not result.ok


def test_dimension_on_its_own_layer_passes():
    d = drawing(
        layers=[LayerInfo(name="标注", entity_count=3)],
        dimensions=[DimInfo(handle="A1", layer="标注", dimtype=0, measurement=10.0)],
    )
    assert not by_code(run_profile(d, "GB_T_TIER1"), Code.DIM_ON_WRONG_LAYER.value)


def test_outline_mostly_on_zero_fails_but_a_few_strays_do_not():
    heavy = drawing(
        layers=[LayerInfo(name="0")],
        entity_layers={"0": {"LINE": 9}, "轮廓线": {"LINE": 1}},
    )
    assert by_code(run_profile(heavy, "GB_T_TIER1"), Code.CONTOUR_ON_ZERO.value)[0].ok is False

    light = drawing(
        layers=[LayerInfo(name="0")],
        entity_layers={"0": {"LINE": 1}, "轮廓线": {"LINE": 9}},
    )
    assert not by_code(run_profile(light, "GB_T_TIER1"), Code.CONTOUR_ON_ZERO.value)


def test_missing_outline_layer_warns():
    d = drawing(layers=[LayerInfo(name="标注")])
    result = by_code(run_profile(d, "GB_T_TIER1"), Code.NO_CONTOUR_LAYER.value)[0]
    assert not result.ok
    assert result.severity is Severity.WARNING


# ---------------------------------------------------------------- title block

def _title_block(attrs: list[AttribItem]) -> BlockRef:
    return BlockRef(name="GB-A3", layer="图框", attributes=attrs)


def test_no_title_block_fails():
    d = drawing(layouts=[LayoutInfo(name="Layout1", paper_width=420, paper_height=297)])
    result = by_code(run_profile(d, "GB_T_TIER1"), Code.TITLE_BLOCK.value)[0]
    assert not result.ok
    assert result.severity is Severity.ERROR


def test_title_block_without_attributes_is_called_out():
    d = drawing(
        layouts=[LayoutInfo(name="L", paper_width=420, paper_height=297, blocks=[_title_block([])])]
    )
    result = by_code(run_profile(d, "GB_T_TIER1"), Code.TITLE_BLOCK_NO_ATTR.value)[0]
    assert not result.ok
    assert "no attributes" in result.detail


def test_blank_required_field_fails_even_though_the_block_exists():
    """The whole point: an empty title block still exists."""
    block = _title_block(
        [
            AttribItem(tag="图名", value="轴承座", block="GB-A3"),
            AttribItem(tag="图号", value="", block="GB-A3"),
            AttribItem(tag="比例", value="1:2", block="GB-A3"),
        ]
    )
    d = drawing(
        layouts=[LayoutInfo(name="L", paper_width=420, paper_height=297, blocks=[block])]
    )
    result = by_code(run_profile(d, "GB_T_TIER1"), Code.TITLE_BLOCK_BLANK.value)[0]
    assert not result.ok
    assert "图号" in result.detail


def test_fully_filled_title_block_passes():
    block = _title_block(
        [
            AttribItem(tag="图名", value="轴承座", block="GB-A3"),
            AttribItem(tag="图号", value="GB-2026-001", block="GB-A3"),
            AttribItem(tag="比例", value="1:2", block="GB-A3"),
        ]
    )
    d = drawing(
        layouts=[LayoutInfo(name="L", paper_width=420, paper_height=297, blocks=[block])]
    )
    result = by_code(run_profile(d, "GB_T_TIER1"), Code.TITLE_BLOCK_BLANK.value)[0]
    assert result.ok, result.detail
    assert "轴承座" in result.detail


def test_attribute_lookup_is_case_and_space_insensitive():
    block = _title_block([AttribItem(tag=" SCALE ", value="1:1")])
    found = block.attribute("比例", "scale")
    assert found is not None and found.value == "1:1"


# ---------------------------------------------------------------- profiles

def test_legacy_compat_runs_no_rule():
    """Parity with dsh-sw-cad depends on this being empty."""
    d = drawing(layouts=[LayoutInfo(name="L", paper_width=400, paper_height=280)])
    assert run_profile(d, "LEGACY_COMPAT") == []


def test_profile_escalates_severity_without_touching_the_rule():
    """Same fact, different cost: that separation is what profiles are for."""
    assert SEVERITY_PROFILES["GB_T_TIER1"][Code.TITLE_BLOCK.value] is Severity.ERROR
    assert SEVERITY_PROFILES["LEGACY_COMPAT"][Code.TITLE_BLOCK.value] is Severity.WARNING


def test_every_emitted_code_is_declared():
    """A rule must not invent a code; profiles can only override known ones."""
    d = drawing(
        layers=[LayerInfo(name="随便")],
        layouts=[LayoutInfo(name="L", paper_width=400, paper_height=280, blocks=[_title_block([])])],
        dimensions=[DimInfo(handle="A", layer="随便", dimtype=0, measurement=1.0)],
        entity_layers={"随便": {"LINE": 5}},
    )
    for result in run_profile(d, "GB_T_TIER1"):
        assert result.code in {c.value for c in Code}, f"undeclared code {result.code}"


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
    print(f"\nrules: {len(tests) - failed}/{len(tests)} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())