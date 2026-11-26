"""Pure in-memory tests for geometry checks and standards without CAD libraries.

Run: python tests/test_geometry.py
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cad_deliver import standards
from cad_deliver.geometry.dxf_checks import check_drawing
from cad_deliver.geometry.pdf_checks import check_pdf
from cad_deliver.models import DimInfo, LayerInfo, LayoutInfo, ParsedDrawing, TextItem


def _by_id(checks):
    return {c.ident: c for c in checks}


def _valid_drawing() -> ParsedDrawing:
    return ParsedDrawing(
        fmt="dxf",
        source_path="memory://part.dxf",
        dxfversion="AC1032",
        units=4,
        entities={"LWPOLYLINE": 1, "DIMENSION": 1},
        layers=[
            LayerInfo(name="0", lineweight=-3, entity_count=0),
            LayerInfo(name="粗实线", lineweight=50, entity_count=1),
            LayerInfo(name="标注", lineweight=13, entity_count=1),
        ],
        layouts=[
            LayoutInfo(name="Model", entity_count=2),
            LayoutInfo(
                name="Layout1",
                paper_width=420.0,
                paper_height=297.0,
                entity_count=3,
                block_refs=["TITLEBLOCK"],
            ),
        ],
        texts=[
            TextItem(
                content="比例 1:2",
                layer="标注",
                style="GB",
                space="paper",
                layout="Layout1",
                kind="TEXT",
            ),
            TextItem(
                content="图名 端盖",
                layer="标注",
                style="GB",
                space="paper",
                layout="Layout1",
                kind="MTEXT",
            ),
        ],
        dimensions=[
            DimInfo(
                handle="1A",
                layer="标注",
                dimtype=0,
                measurement=100.0,
                text="",
                dimlfac=1.0,
                style="Standard",
                text_midpoint=(50.0, -12.0),
                space="model",
            )
        ],
        text_styles={"GB": "fangsong.ttf", "Standard": "txt"},
    )


def test_valid_drawing_passes():
    checks = _by_id(check_drawing(_valid_drawing()))
    assert all(c.ok for c in checks.values()), checks
    assert checks["drawing.dimensions"].detail == "1 DIMENSION entity in modelspace"
    assert checks["drawing.entities"].detail == "2 entities in modelspace"
    assert checks["drawing.units"].ok and checks["drawing.units"].severity == "warning"
    assert "A3" in checks["drawing.sheet"].detail
    assert checks["drawing.fonts"].ok
    assert checks["drawing.dim_overlap"].ok


def test_missing_dims_and_unitless_and_empty_sheet():
    drawing = ParsedDrawing(
        fmt="dxf",
        source_path="memory://empty_sheet.dxf",
        units=0,
        entities={"LINE": 3},
        layers=[LayerInfo(name="0", lineweight=-3, entity_count=3)],
        layouts=[
            LayoutInfo(name="Model", entity_count=3),
            LayoutInfo(name="Layout1", paper_width=420.0, paper_height=297.0, entity_count=0),
        ],
    )
    checks = _by_id(check_drawing(drawing))
    assert not checks["drawing.dimensions"].ok
    assert checks["drawing.dimensions"].detail == "0 DIMENSION entities in modelspace"
    assert not checks["drawing.units"].ok
    assert checks["drawing.units"].severity == "error"
    assert not checks["drawing.sheets"].ok
    assert not checks["drawing.titleblock"].ok
    assert "drawing.sheet" not in checks
    assert not checks["drawing.scale"].ok
    assert checks["drawing.scale"].severity == "warning"
    assert not checks["drawing.lineweights"].ok


def test_non_iso_sheet_and_missing_scale_on_populated_sheet():
    drawing = _valid_drawing()
    drawing.layouts[1] = LayoutInfo(
        name="Layout1",
        paper_width=400.0,
        paper_height=280.0,
        entity_count=2,
        block_refs=[],
    )
    drawing.texts = []
    checks = _by_id(check_drawing(drawing))
    assert not checks["drawing.sheet"].ok
    assert "not ISO A" in checks["drawing.sheet"].detail
    assert not checks["drawing.scale"].ok
    assert checks["drawing.scale"].severity == "error"


def test_overridden_dimension_cases_and_overlap():
    drawing = _valid_drawing()
    drawing.entities["DIMENSION"] = 4
    drawing.dimensions = [
        # Mismatched linear dimension
        DimInfo(
            handle="A1",
            layer="标注",
            dimtype=0,
            measurement=100.0,
            text="%%c80",
            dimlfac=1.0,
            text_midpoint=(10.0, 10.0),
            space="model",
        ),
        # Skipped because dimlfac != 1
        DimInfo(
            handle="A2",
            layer="标注",
            dimtype=0,
            measurement=50.0,
            text="100",
            dimlfac=2.0,
            style="HALF",
            text_midpoint=(10.5, 10.5),
            space="model",
        ),
        # Skipped because measurement is None
        DimInfo(
            handle="A3",
            layer="标注",
            dimtype=0,
            measurement=None,
            text="50",
            dimlfac=1.0,
            text_midpoint=(40.0, 40.0),
            space="model",
        ),
        # Angular dimension skipped from linear text comparison
        DimInfo(
            handle="A4",
            layer="标注",
            dimtype=2,
            measurement=45.0,
            text="90",
            dimlfac=1.0,
            text_midpoint=(80.0, 80.0),
            space="model",
        ),
    ]
    checks = _by_id(check_drawing(drawing))
    dim_val = checks["drawing.dim_values"]
    assert not dim_val.ok
    assert "1 of 1 overridden dimension text(s) disagree" in dim_val.detail
    assert "handle A1: text says 80, geometry measures 100" in dim_val.detail
    assert "1 more skipped because their style has a dimlfac other than 1" in dim_val.detail
    assert "HALF dimlfac=2" in checks["drawing.scale"].detail
    assert not checks["drawing.dim_overlap"].ok
    assert "1 pair(s)" in checks["drawing.dim_overlap"].detail


def test_cjk_font_warning_when_latin_only():
    drawing = _valid_drawing()
    drawing.text_styles = {"GB": "arial.ttf"}
    checks = _by_id(check_drawing(drawing))
    assert not checks["drawing.fonts"].ok
    assert checks["drawing.fonts"].severity == "warning"
    assert "Chinese text with no CJK font assigned" in checks["drawing.fonts"].detail


def test_standards_half_profile_uses_attrib_and_dim_override():
    drawing = _valid_drawing()
    drawing.texts.extend(
        [
            TextItem(content="材料 45", space="paper", layout="Layout1", kind="ATTRIB"),
            TextItem(content="Ra 1.6", space="paper", layout="Layout1", kind="TEXT"),
        ]
    )
    drawing.dimensions.append(
        DimInfo(
            handle="D2",
            layer="标注",
            dimtype=0,
            measurement=40.0,
            text="φ40H7/g6",
            space="model",
        )
    )
    saved = standards.PROFILE
    try:
        standards.PROFILE = "half"
        checks = _by_id(check_drawing(drawing))
        assert checks["standards.material"].ok
        assert checks["standards.fit"].ok
        assert checks["standards.roughness"].ok

        # Bad material & fit & missing Ra
        bad = _valid_drawing()
        bad.texts.append(
            TextItem(content="材料 40CrMnMoX φ40H7/z9", space="paper", layout="Layout1", kind="TEXT")
        )
        bad_checks = _by_id(check_drawing(bad))
        assert not bad_checks["standards.material"].ok
        assert not bad_checks["standards.material_table"].ok
        assert not bad_checks["standards.fit"].ok
        assert not bad_checks["standards.roughness"].ok
    finally:
        standards.PROFILE = saved


def test_pdf_checks_in_memory():
    valid = ParsedDrawing(
        fmt="pdf",
        source_path="memory://sheet.pdf",
        layouts=[LayoutInfo(name="page-1", paper_width=420.0, paper_height=297.0, entity_count=1)],
        texts=[TextItem(content="SCALE 1:2\n45", space="paper", layout="page-1")],
    )
    ok_checks = _by_id(check_pdf(valid))
    assert ok_checks["pdf.sheet"].ok and "A3" in ok_checks["pdf.sheet"].detail
    assert ok_checks["pdf.text"].ok and "12 characters" in ok_checks["pdf.text"].detail

    empty_pages = ParsedDrawing(fmt="pdf", source_path="memory://zero.pdf", layouts=[], texts=[])
    zero_checks = _by_id(check_pdf(empty_pages))
    assert not zero_checks["pdf.pages"].ok

    # Text on page 2 only: page 1 still fails pdf.text, and non-ISO page fails pdf.sheet
    page2_only = ParsedDrawing(
        fmt="pdf",
        source_path="memory://p2.pdf",
        layouts=[
            LayoutInfo(name="page-1", paper_width=400.0, paper_height=280.0, entity_count=0),
            LayoutInfo(name="page-2", paper_width=420.0, paper_height=297.0, entity_count=1),
        ],
        texts=[TextItem(content="page 2 note", space="paper", layout="page-2")],
    )
    p2_checks = _by_id(check_pdf(page2_only))
    assert not p2_checks["pdf.sheet"].ok and "not an ISO A-series sheet" in p2_checks["pdf.sheet"].detail
    assert not p2_checks["pdf.text"].ok and "no text layer" in p2_checks["pdf.text"].detail


def test_no_cad_libraries_imported():
    """The geometry layer must not import a CAD library.

    Checked against the source rather than `sys.modules`. Under the script runner this
    file is a process on its own, so `"ezdxf" not in sys.modules` happened to hold;
    under pytest every test module shares one interpreter, and `test_parsers.py` imports
    ezdxf legitimately. The architectural claim is about the module's imports, so that
    is what is asserted.
    """
    import ast

    banned = {"ezdxf", "fitz", "pymupdf", "win32com", "comtypes"}
    geometry = Path(__file__).resolve().parent.parent / "src" / "cad_deliver" / "geometry"
    offenders: list[str] = []
    for path in sorted(geometry.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in banned:
                        offenders.append(f"{path.name} imports {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in banned:
                    offenders.append(f"{path.name} imports from {node.module}")
    assert not offenders, f"geometry layer must stay CAD-library free: {offenders}"


if __name__ == "__main__":
    test_valid_drawing_passes()
    test_missing_dims_and_unitless_and_empty_sheet()
    test_non_iso_sheet_and_missing_scale_on_populated_sheet()
    test_overridden_dimension_cases_and_overlap()
    test_cjk_font_warning_when_latin_only()
    test_standards_half_profile_uses_attrib_and_dim_override()
    test_pdf_checks_in_memory()
    test_no_cad_libraries_imported()
    print("geometry: ok (pure ParsedDrawing, zero CAD library imports)")
