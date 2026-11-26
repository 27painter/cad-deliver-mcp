"""High-complexity repair fixtures: 500+ entities with one hidden defect.

The simple set (8 entities) made the repair experiment useless: a model could see
the whole drawing at once, so a fix instruction added nothing. These drawings are
built so that "look at the file and find it" costs real work:

* a 200-segment outline (120+ is the point: the break is one joint among 199)
* dense HATCH hatching, 45 dimensions, 40 centre lines, 60 hidden lines and
  150 thin construction lines — over 500 entities, most of them irrelevant
* the defect is local and tiny: a 0.02 mm gap (twice the join tolerance, so it is
  real), two dimensions on the wrong layer out of 45, one text override off by
  0.3%, one blank required title-block field out of twelve attributes

Each fixture is verified as it is written: a sample that does not produce exactly
the intended code is a broken fixture, not a hard task.

    python benchmarks/agent/complex_fixtures.py
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import ezdxf
except ImportError:  # pragma: no cover
    sys.exit("ezdxf is required: pip install ezdxf")

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "complex_fixtures"
sys.path.insert(0, str(ROOT / "src"))

PAPER_W, PAPER_H = 594.0, 420.0        # A2 landscape
OUTLINE_SEGMENTS = 200
BREAK_INDEX = 60                        # where the 0.02 mm gap goes
GAP_MM = 0.02                           # twice the 0.01 join tolerance

LAYERS = {
    "粗实线": (50, "CONTINUOUS", 7),
    "细实线": (13, "CONTINUOUS", 3),
    "中心线": (13, "CENTER", 1),
    "虚线":   (13, "DASHED", 2),
    "标注":   (13, "CONTINUOUS", 4),
    "文字":   (13, "CONTINUOUS", 5),
    "图框":   (18, "CONTINUOUS", 7),
}

TITLE_TAGS = ("图名", "图号", "比例", "材料", "重量", "设计", "校对", "审核", "批准", "日期", "版本", "单位")


def ring_points(x0: float, y0: float, w: float, h: float, n: int) -> list[tuple[float, float]]:
    """Uniform samples around a rectangle, so the outline is a chain of n lines."""
    perimeter = 2 * (w + h)
    points: list[tuple[float, float]] = []
    for index in range(n):
        t = perimeter * index / n
        if t < w:
            point = (x0 + t, y0)
        elif t < w + h:
            point = (x0 + w, y0 + t - w)
        elif t < 2 * w + h:
            point = (x0 + w - (t - w - h), y0 + h)
        else:
            point = (x0, y0 + h - (t - 2 * w - h))
        points.append((round(point[0], 6), round(point[1], 6)))
    return points


def build(path: Path, defects: set[str]) -> None:
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4

    for name, (weight, linetype, colour) in LAYERS.items():
        layer = doc.layers.add(name)
        layer.dxf.lineweight = weight
        layer.dxf.color = colour
        if linetype in doc.linetypes:
            layer.dxf.linetype = linetype

    doc.styles.add("GB", font="fangsong.ttf")
    doc.dimstyles.new("GB", dxfattribs={"dimlfac": 1.0, "dimtxt": 3.0, "dimasz": 2.5,
                                        "dimexe": 1.2, "dimexo": 0.8, "dimgap": 0.8})

    msp = doc.modelspace()

    # ---- the part: a 200-segment outline (the defect target) -----------
    x0, y0, w, h = 80.0, 90.0, 430.0, 250.0
    points = ring_points(x0, y0, w, h, OUTLINE_SEGMENTS)
    for index in range(OUTLINE_SEGMENTS):
        start = points[index]
        end = points[(index + 1) % OUTLINE_SEGMENTS]
        if "profile_open" in defects and index == BREAK_INDEX:
            # Push the *start* of one segment off its neighbour: one joint in 200
            # is 0.02 mm apart, which the 0.01 mm join tolerance will not absorb.
            start = (start[0], start[1] + GAP_MM)
        msp.add_line(start, end, dxfattribs={"layer": "粗实线"})

    # holes
    for cx, cy, r in ((180, 180, 22), (300, 180, 28), (400, 180, 14),
                      (200, 300, 12), (360, 300, 18), (260, 250, 10)):
        msp.add_circle((cx, cy), r, dxfattribs={"layer": "粗实线"})

    # ---- dense section hatching (must not read as outline) -------------
    for cx, cy, half in ((180, 180, 26), (300, 180, 32), (360, 300, 22)):
        hatch = msp.add_hatch(dxfattribs={"layer": "细实线", "color": 3})
        hatch.paths.add_polyline_path(
            [(cx - half, cy - half), (cx + half, cy - half),
             (cx + half, cy + half), (cx - half, cy + half)],
            is_closed=True,
        )
        hatch.set_pattern_fill("ANSI31", scale=0.8)

    # ---- 150 thin construction lines -----------------------------------
    for index in range(150):
        column = index % 15
        row = index // 15
        x = x0 + 12 + column * 27
        y = y0 + 8 + row * 24
        msp.add_line((x, y), (x + 18, y + 6), dxfattribs={"layer": "细实线"})

    # ---- 40 centre lines, 60 hidden lines ------------------------------
    for index in range(20):
        x = x0 + 20 + index * 20
        msp.add_line((x, y0 - 12), (x, y0 + h + 12), dxfattribs={"layer": "中心线"})
    for index in range(20):
        y = y0 + 15 + index * 11
        msp.add_line((x0 - 12, y), (x0 + w + 12, y), dxfattribs={"layer": "中心线"})
    for index in range(60):
        y = y0 + 6 + index * 4
        msp.add_line((x0 + 30, y), (x0 + 60, y), dxfattribs={"layer": "虚线"})

    # ---- 45 dimensions -------------------------------------------------
    dimension_handles: list[tuple[object, float]] = []
    placed = 0
    for row in range(9):
        for column in range(5):
            if placed >= 45:
                break
            base_y = y0 - 25 - row * 16
            p1 = (x0 + 40, base_y)
            p2 = (x0 + 40 + 18 + column * 4, base_y)
            dim = msp.add_linear_dim(
                base=(p1[0], base_y - 6), p1=p1, p2=p2,
                dimstyle="GB", dxfattribs={"layer": "标注"},
            )
            dim.render()
            dimension_handles.append((dim.dimension, p2[0] - p1[0]))
            placed += 1

    if "dim_layer" in defects:
        # Two out of forty-five, on the outline layer.
        for entity, _measured in dimension_handles[:2]:
            entity.dxf.layer = "粗实线"

    if "dim_text" in defects:
        entity, measured = dimension_handles[7]
        # 0.3% high: more than the 0.2% allowance, small enough to look typed.
        entity.dxf.text = f"{measured * 1.003:.2f}"

    # ---- notes ---------------------------------------------------------
    for index, note in enumerate(("技术要求", "未注倒角 C1", "未注圆角 R2", "去毛刺",
                                  "调质处理", "表面发黑", "材料 45 钢", "公差按 GB/T 1804-m",
                                  "数量 1 件", "比例 1:2", "日期", "版本")):
        msp.add_text(note, height=3.0, dxfattribs={"layer": "文字", "style": "GB"}).set_placement(
            (x0 + 10, y0 + h + 20 + index * 5)
        )

    # ---- title block: twelve attributes, three of them required ---------
    if "TB-COMPLEX" not in doc.blocks:
        blk = doc.blocks.new("TB-COMPLEX")
        for index, tag in enumerate(TITLE_TAGS):
            blk.add_attdef(tag, insert=(4, 46 - index * 4),
                           dxfattribs={"height": 3.0, "style": "GB"})
        blk.add_lwpolyline([(0, 0), (90, 0), (90, 50), (0, 50)], close=True,
                           dxfattribs={"layer": "图框"})

    layout = doc.layouts.get("Layout1")
    layout.dxf.paper_width = PAPER_W
    layout.dxf.paper_height = PAPER_H
    margin = 10.0
    layout.add_lwpolyline(
        [(margin, margin), (PAPER_W - margin, margin),
         (PAPER_W - margin, PAPER_H - margin), (margin, PAPER_H - margin)],
        close=True, dxfattribs={"layer": "图框"},
    )
    ref = layout.add_blockref("TB-COMPLEX", (PAPER_W - margin - 92, margin + 2),
                              dxfattribs={"layer": "图框"})
    values = {
        "图名": "支架", "图号": "GB-2048", "比例": "1:2", "材料": "45", "重量": "2.4",
        "设计": "张三", "校对": "李四", "审核": "王五", "批准": "赵六",
        "日期": "2026-11-26", "版本": "A", "单位": "mm",
    }
    if "title_blank" in defects:
        values["比例"] = ""            # one blank required field among twelve
    ref.add_auto_attribs(values)

    layout.add_text("比例 1:2", height=4.0,
                    dxfattribs={"layer": "图框", "style": "GB"}).set_placement((margin + 4, margin + 4))

    doc.saveas(path)


CASES = [
    ("complex_01_profile_open", {"profile_open"}, ["E_PROFILE_OPEN"]),
    ("complex_02_dim_layer",    {"dim_layer"},    ["E_DIM_ON_WRONG_LAYER"]),
    ("complex_03_dim_text",     {"dim_text"},     ["E_DIM_TEXT_MISMATCH"]),
    ("complex_04_title_blank",  {"title_blank"},  ["E_TITLE_BLOCK_BLANK"]),
    ("complex_05_two_defects",  {"profile_open", "dim_layer"},
                                ["E_PROFILE_OPEN", "E_DIM_ON_WRONG_LAYER"]),
    ("complex_06_all_four",     {"profile_open", "dim_layer", "dim_text", "title_blank"},
                                ["E_PROFILE_OPEN", "E_DIM_ON_WRONG_LAYER",
                                 "E_DIM_TEXT_MISMATCH", "E_TITLE_BLOCK_BLANK"]),
]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.dxf"):
        old.unlink()

    from cad_deliver.pipeline import verify_file

    failures = 0
    for name, defects, expected in CASES:
        path = OUT / f"{name}.dxf"
        build(path, defects)

        parsed = verify_file(str(path), "GB_T_TIER1")
        drawing = parsed.drawing
        entities = sum(drawing.entities.values()) if drawing else 0
        codes = sorted(r.code for r in parsed.rules if not r.ok)
        ok = codes == sorted(expected)

        if not ok:
            failures += 1
        print(
            f"  {'ok  ' if ok else 'FAIL'} {name:26} entities={entities:4} "
            f"codes={','.join(codes) or '-'}"
        )
        if not ok:
            print(f"         expected {sorted(expected)}")
            for check in parsed.checks:
                if not check.ok and check.severity in ("error", "blocked"):
                    print(f"         check {check.ident}: {check.detail[:80]}")

    print(f"\ncomplex fixtures: {len(CASES) - failures}/{len(CASES)} as intended")
    print(f"output: {OUT}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())