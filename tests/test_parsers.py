"""Parser tests verifying DXF/DWG and PDF extraction into `ParsedDrawing`.

Run: python tests/test_parsers.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cad_deliver.parsers import dxf as dxf_parser, pdf as pdf_parser


def _build_dxf(path: Path) -> None:
    import ezdxf

    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4
    doc.layers.add("粗实线", lineweight=50)
    doc.layers.add("标注", lineweight=13)
    doc.styles.add("GB", font="fangsong.ttf")

    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (100, 0), (100, 60), (0, 60)], close=True, dxfattribs={"layer": "粗实线"})
    msp.add_text("MODEL_NOTE", dxfattribs={"height": 3.5, "style": "GB", "layer": "标注"}).set_placement((5, 5))
    msp.add_linear_dim(base=(0, -12), p1=(0, 0), p2=(100, 0), dxfattribs={"layer": "标注"}).render()

    blk = doc.blocks.new("TITLEBLOCK")
    blk.add_lwpolyline([(0, 0), (180, 0), (180, 40), (0, 40)], close=True)
    blk.add_attdef("MATERIAL", insert=(10, 10), dxfattribs={"height": 3.5, "style": "GB"})

    sheet = doc.layouts.get("Layout1")
    sheet.dxf.paper_width, sheet.dxf.paper_height = 420, 297
    sheet.add_blockref("TITLEBLOCK", (10, 10)).add_auto_attribs({"MATERIAL": "材料 45"})
    sheet.add_text("比例 1:2", dxfattribs={"height": 4, "style": "GB"}).set_placement((20, 20))
    doc.saveas(str(path))


def test_dxf_parser_extracts_plain_facts(root: Path):
    try:
        import ezdxf  # noqa: F401
    except Exception:
        print("parsers.dxf valid DXF: skipped (ezdxf not available)")
        return

    dxf_path = root / "sample.dxf"
    _build_dxf(dxf_path)

    result = dxf_parser.parse(str(dxf_path))
    assert result.drawing is not None
    assert result.checks and result.checks[0].ident == "dxf.parsed" and result.checks[0].ok

    drawing = result.drawing
    assert not hasattr(drawing, "native"), (
        "ParsedDrawing must not carry a live CAD document: the attribute existed "
        "only during the migration and its return would break the layering claim"
    )
    assert drawing.fmt == "dxf"
    assert drawing.units == 4
    assert drawing.entities.get("LWPOLYLINE") == 1
    assert drawing.entities.get("DIMENSION") == 1

    # Modelspace text must appear exactly once, and spaces must be literal "model" / "paper".
    model_texts = [t for t in drawing.texts if t.content == "MODEL_NOTE"]
    assert len(model_texts) == 1, f"expected 1 model text, got {len(model_texts)}"
    assert model_texts[0].space == "model"
    assert model_texts[0].kind == "TEXT"

    paper_texts = [t for t in drawing.texts if t.content == "比例 1:2"]
    assert len(paper_texts) == 1
    assert paper_texts[0].space == "paper"
    assert paper_texts[0].layout == "Layout1"

    attrib_texts = [t for t in drawing.texts if t.kind == "ATTRIB"]
    assert len(attrib_texts) == 1 and attrib_texts[0].content == "材料 45"
    assert attrib_texts[0].space == "paper"

    assert drawing.text_styles.get("GB") == "fangsong.ttf"
    assert len(drawing.dimensions) == 1
    assert drawing.dimensions[0].text_midpoint is not None
    assert drawing.dimensions[0].space == "model"

    layer_map = {layer.name: layer for layer in drawing.layers}
    assert layer_map["粗实线"].entity_count == 1
    assert layer_map["标注"].entity_count == 2


def test_dxf_parser_invalid_and_dwg_without_converter(root: Path):
    bad_dxf = root / "corrupt.dxf"
    bad_dxf.write_text("not a valid dxf file", encoding="utf-8")
    bad_res = dxf_parser.parse(str(bad_dxf))
    assert bad_res.drawing is None
    assert len(bad_res.checks) == 1
    assert bad_res.checks[0].ident == "dxf.parsed" and not bad_res.checks[0].ok

    dwg_path = root / "blank.dwg"
    dwg_path.write_bytes(b"AC1032" + b"\x00" * 4000)
    saved = os.environ.get("DSH_SW_CAD_DWG_CONVERTER")
    try:
        os.environ["DSH_SW_CAD_DWG_CONVERTER"] = ""
        dwg_res = dxf_parser.parse(str(dwg_path))
    finally:
        if saved is None:
            os.environ.pop("DSH_SW_CAD_DWG_CONVERTER", None)
        else:
            os.environ["DSH_SW_CAD_DWG_CONVERTER"] = saved

    assert dwg_res.drawing is None
    assert [c.ident for c in dwg_res.checks] == ["dwg.header", "drawing.entities"]
    assert dwg_res.checks[0].ok
    assert not dwg_res.checks[1].ok and dwg_res.checks[1].severity == "blocked"


def test_pdf_parser_extracts_pages_and_handles_corrupt(root: Path):
    try:
        import pymupdf
    except Exception:
        print("parsers.pdf: skipped (pymupdf not available)")
        return

    # 1. A3 PDF with text
    a3_pdf = root / "a3.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=420.0 * 72.0 / 25.4, height=297.0 * 72.0 / 25.4)
    page.insert_text((72, 72), "PART NO. 001")
    doc.save(str(a3_pdf))
    doc.close()

    res = pdf_parser.parse(str(a3_pdf))
    assert res.drawing is not None
    assert not hasattr(res.drawing, "native"), "no live document on the drawing"
    assert res.drawing.fmt == "pdf"
    assert res.checks[0].ident == "pdf.parsed" and res.checks[0].ok
    assert len(res.drawing.layouts) == 1
    assert abs(res.drawing.layouts[0].paper_width - 420.0) < 0.5
    assert abs(res.drawing.layouts[0].paper_height - 297.0) < 0.5
    assert len(res.drawing.texts) == 1 and "PART NO. 001" in res.drawing.texts[0].content

    # 2. 2-page non-ISO PDF with text only on page 2
    two_page = root / "two_page.pdf"
    doc2 = pymupdf.open()
    doc2.new_page(width=400.0 * 72.0 / 25.4, height=280.0 * 72.0 / 25.4)
    p2 = doc2.new_page(width=420.0 * 72.0 / 25.4, height=297.0 * 72.0 / 25.4)
    p2.insert_text((72, 72), "SECOND PAGE ONLY")
    doc2.save(str(two_page))
    doc2.close()

    res2 = pdf_parser.parse(str(two_page))
    assert res2.drawing is not None
    assert len(res2.drawing.layouts) == 2
    assert res2.drawing.layouts[0].entity_count == 0
    assert res2.drawing.layouts[1].entity_count == 1
    assert len(res2.drawing.texts) == 1
    assert res2.drawing.texts[0].layout == "page-2"

    # 3. Corrupt PDF
    bad_pdf = root / "corrupt.pdf"
    bad_pdf.write_bytes(b"not a pdf at all")
    bad_res = pdf_parser.parse(str(bad_pdf))
    assert bad_res.drawing is None
    assert bad_res.checks[0].ident == "pdf.parsed" and not bad_res.checks[0].ok


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="cad-deliver-parsers-"))
    try:
        test_dxf_parser_extracts_plain_facts(root)
        test_dxf_parser_invalid_and_dwg_without_converter(root)
        test_pdf_parser_extracts_pages_and_handles_corrupt(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("parsers: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
