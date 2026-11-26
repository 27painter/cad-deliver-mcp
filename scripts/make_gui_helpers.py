"""Generate the two files the SolidWorks GUI needs for a compliant DXF export.

1. `sw_dxf_map.txt` — a layer-mapping table for Tools > Options > Export > DXF/DWG.
   SolidWorks maps *entity classes* (visible edges, hidden edges, dimensions, …) to
   DXF layers, so the table is keyed by class, not by SolidWorks layer name. The
   file is written in the CSV form the mapping dialog reads; if your build wants a
   different column order, save any mapping from the dialog once and compare — the
   structure is two columns.
2. `gb_title_block.dxf` — a GB/T 10609.1 style title block as a *block definition*
   with three attributed fields carrying non-empty defaults, ready to insert into a
   drawing template. Attribute tags are the ones the gate looks for (图名/图号/比例).

Neither file touches any exported drawing: they configure the exporter and the
template, which is where the compliance has to come from.

    python scripts/make_gui_helpers.py
"""

from __future__ import annotations

from pathlib import Path

try:
    import ezdxf
except ImportError:  # pragma: no cover
    raise SystemExit("ezdxf is required: pip install ezdxf")

HERE = Path(__file__).resolve().parent

# Entity class -> target DXF layer. These are the classes SolidWorks exposes in the
# layer-mapping dialog.
MAPPING = [
    ("Visible Edges", "粗实线"),
    ("Hidden Edges", "虚线"),
    ("Centerlines", "中心线"),
    ("Dimensions", "标注"),
    ("Notes", "文字"),
    ("Sketches", "细实线"),
    ("Section Views", "细实线"),
    ("View Arrows", "标注"),
    ("Sheet Format", "图框"),
]


def write_mapping() -> Path:
    path = HERE / "sw_dxf_map.txt"
    lines = [
        "# SolidWorks DXF/DWG layer mapping",
        "#",
        "# Load with: Tools > Options > System Options > Export > DXF/DWG",
        "#            > Layer mapping > Load",
        "#",
        "# Two columns: SolidWorks entity class, target DXF layer.",
        "# The classes are the ones the mapping dialog lists; the layers are the ones",
        "# cad-deliver-mcp recognises as the seven drafting roles.",
        "#",
        "# The gate expects: 粗实线 = outline, 虚线 = hidden, 中心线 = centre,",
        "#                   标注 = dimension, 文字 = annotation, 图框 = frame",
        "",
    ]
    for source, target in MAPPING:
        lines.append(f"{source},{target}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_title_block() -> Path:
    """A 180x56 title block with three attributed fields, as a block definition."""
    path = HERE / "gb_title_block.dxf"
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4          # millimetres

    for name, lineweight in (("图框", 35), ("文字", 25)):
        layer = doc.layers.add(name)
        layer.dxf.lineweight = lineweight

    doc.styles.add("GB", font="fangsong.ttf")

    W, H = 180.0, 56.0
    block = doc.blocks.new("GB-TITLE")

    # outer border and the two dividing rules
    block.add_lwpolyline(
        [(0, 0), (W, 0), (W, H), (0, H)],
        close=True,
        dxfattribs={"layer": "图框"},
    )
    for x in (60.0, 120.0):
        block.add_line((x, 0), (x, H), dxfattribs={"layer": "图框"})
    block.add_line((0, H / 2), (W, H / 2), dxfattribs={"layer": "图框"})
    block.add_line((0, H / 4), (W / 2, H / 4), dxfattribs={"layer": "图框"})

    # field labels
    labels = [
        ("图名", 6, H - 9),
        ("图号", 66, H - 9),
        ("比例", 126, H - 9),
        ("材料", 6, H / 2 - 9),
        ("重量", 66, H / 2 - 9),
        ("设计", 6, H / 4 - 8),
        ("审核", 66, H / 4 - 8),
    ]
    for text, x, y in labels:
        block.add_text(text, height=3.0, dxfattribs={"layer": "文字", "style": "GB"}).set_placement((x, y))

    # The three fields the gate reads, with non-empty defaults so an inserted block
    # is already valid. ATTRIB values override these defaults on insert.
    fields = [
        ("图名", (24, H - 9), "零件名称"),
        ("图号", (84, H - 9), "GB-0001"),
        ("比例", (144, H - 9), "1:1"),
        ("材料", (24, H / 2 - 9), "45"),
        ("重量", (84, H / 2 - 9), "0.00"),
    ]
    for tag, insert, default in fields:
        block.add_attdef(
            tag,
            insert=insert,
            text=default,
            dxfattribs={"height": 3.5, "layer": "文字", "style": "GB"},
        )

    # A sample insertion on the model space, so the file opens showing what it is.
    msp = doc.modelspace()
    ref = msp.add_blockref("GB-TITLE", (0, 0), dxfattribs={"layer": "图框"})
    ref.add_auto_attribs(
        {"图名": "零件名称", "图号": "GB-0001", "比例": "1:1", "材料": "45", "重量": "0.00"}
    )

    doc.saveas(path)
    return path


def main() -> int:
    mapping = write_mapping()
    block = write_title_block()
    print(f"wrote {mapping}  ({len(MAPPING)} mappings)")
    print(f"wrote {block}  (block 'GB-TITLE', {W_TAGS} attributed fields)")
    print("\nNext, in SolidWorks:")
    print("  1. Tools > Options > System Options > Export > DXF/DWG")
    print("       - tick 'Export sheet format'")
    print("       - Layer mapping: Load -> the sw_dxf_map.txt above")
    print("  2. In your .drwdot template: Insert > DXF/DWG or Insert > Block,")
    print("     place the GB-TITLE block on the sheet format, then save the template.")
    return 0


W_TAGS = 5

if __name__ == "__main__":
    raise SystemExit(main())