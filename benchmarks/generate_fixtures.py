"""Generate 15 compliant GB/T drawings with ezdxf.

Every sample here must pass `GB_T_TIER1` **and** every generic geometry check —
if one does not, the false-positive rate in `false_positives.csv` is polluted by
a generator bug rather than by a gatekeeper decision. The script therefore
verifies each file as soon as it writes it and exits non-zero on any failure.

Coverage, per the benchmark design:

* A0–A4, both orientations (GB/T 14689 via ISO 216)
* two boundary tolerance samples at ±1.5 mm inside the 2 mm allowance
* closed rings where `closed=False` but the last vertex sits on the first —
  the way SolidWorks and NX actually export a closed contour
* the seven semantic layer roles, with matching linetypes
* an attributed title block (INSERT + 图名/图号/比例) plus a stated 比例 1:2

All coordinates are millimetres and `$INSUNITS = 4`.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import ezdxf
except ImportError:  # pragma: no cover
    sys.exit("ezdxf is required to generate fixtures: pip install ezdxf")

ROOT = Path(__file__).resolve().parent
GEN_DIR = ROOT / "fixtures" / "gen"

# name, paper width, paper height, closed flag on the outline ring
# Widths/heights are portrait values except where noted; orientation is decided by
# the tuple itself, so ("A3", 420, 297) is landscape.
SAMPLES = [
    ("gen_01_a4_portrait",   210.0,  297.0, True),
    ("gen_02_a4_landscape",  297.0,  210.0, False),
    ("gen_03_a3_portrait",   297.0,  420.0, True),
    ("gen_04_a3_landscape",  420.0,  297.0, True),
    ("gen_05_a2_portrait",   420.0,  594.0, False),
    ("gen_06_a2_landscape",  594.0,  420.0, True),
    ("gen_07_a1_portrait",   594.0,  841.0, True),
    ("gen_08_a1_landscape",  841.0,  594.0, False),
    ("gen_09_a0_portrait",   841.0, 1189.0, True),
    ("gen_10_a0_landscape", 1189.0,  841.0, True),
    # Inside the ±2 mm allowance: 1.5 mm off nominal on both edges.
    ("gen_11_a3_tol_plus",   298.5,  421.5, True),
    ("gen_12_a4_tol_minus",  208.5,  295.5, False),
    # The SolidWorks/NX signature: flag off, ends joined.
    ("gen_13_a3_flag_off",   297.0,  420.0, False),
    ("gen_14_a2_tol_plus",   421.5,  595.5, True),
    ("gen_15_a1_flag_off",   841.0,  594.0, False),
]

LAYER_SPECS = {
    # name:       lineweight, linetype, colour
    "粗实线": (50, "CONTINUOUS", 7),
    "细实线": (13, "CONTINUOUS", 3),
    "中心线": (13, "CENTER", 1),
    "虚线":   (13, "DASHED", 2),
    "标注":   (13, "CONTINUOUS", 4),
    "文字":   (13, "CONTINUOUS", 5),
    "图框":   (18, "CONTINUOUS", 7),
}

TITLE_BLOCK = "GB-TITLE"


def build(path: Path, paper_w: float, paper_h: float, closed_flag: bool) -> None:
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4

    for name, (weight, linetype, color) in LAYER_SPECS.items():
        layer = doc.layers.add(name)
        layer.dxf.lineweight = weight
        layer.dxf.color = color
        if linetype in doc.linetypes:
            layer.dxf.linetype = linetype

    # A CJK-capable style. The drawer check looks for a GB font name, not for the
    # font file, so this works on a machine that does not have 仿宋 installed.
    doc.styles.add("GB", font="fangsong.ttf")

    # An explicit dimstyle with dimlfac=1: the ezdxf templates ship 100, which
    # would make every measured value look like it disagrees with the geometry.
    doc.dimstyles.new(
        "GB",
        dxfattribs={
            "dimlfac": 1.0,
            "dimtxt": 3.5,
            "dimasz": 3.0,
            "dimexe": 1.5,
            "dimexo": 1.0,
            "dimgap": 1.0,
        },
    )

    # ---- model space ---------------------------------------------------
    msp = doc.modelspace()

    # The part, sized to the sheet so the sample looks like a real drawing.
    scale = min(paper_w, paper_h) / 297.0
    w = 180.0 * scale
    h = 110.0 * scale
    x0, y0 = 40.0 * scale, 60.0 * scale

    if closed_flag:
        msp.add_lwpolyline(
            [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)],
            close=True,
            dxfattribs={"layer": "粗实线"},
        )
    else:
        # Last vertex on the first, flag left off — the real-export signature.
        msp.add_lwpolyline(
            [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h), (x0, y0)],
            close=False,
            dxfattribs={"layer": "粗实线"},
        )

    # A hole, so the part is not a plain rectangle.
    msp.add_circle(
        (x0 + w * 0.5, y0 + h * 0.5),
        radius=min(w, h) * 0.18,
        dxfattribs={"layer": "粗实线"},
    )

    # Centre lines through the hole.
    msp.add_line(
        (x0 + w * 0.5, y0 - 8 * scale),
        (x0 + w * 0.5, y0 + h + 8 * scale),
        dxfattribs={"layer": "中心线"},
    )
    msp.add_line(
        (x0 - 8 * scale, y0 + h * 0.5),
        (x0 + w + 8 * scale, y0 + h * 0.5),
        dxfattribs={"layer": "中心线"},
    )

    # A hidden edge, so the HIDDEN_DASHED role is exercised.
    msp.add_line(
        (x0 + w * 0.2, y0 + h * 0.15),
        (x0 + w * 0.8, y0 + h * 0.15),
        dxfattribs={"layer": "虚线"},
    )

    # Dimensions: two, far enough apart that their texts cannot overlap.
    dim = msp.add_linear_dim(
        base=(x0, y0 - 18 * scale),
        p1=(x0, y0),
        p2=(x0 + w, y0),
        dimstyle="GB",
        dxfattribs={"layer": "标注"},
    )
    dim.render()
    dim2 = msp.add_linear_dim(
        base=(x0 + w + 18 * scale, y0),
        p1=(x0 + w, y0),
        p2=(x0 + w, y0 + h),
        angle=90,
        dimstyle="GB",
        dxfattribs={"layer": "标注"},
    )
    dim2.render()

    # Notes with Chinese text, on the annotation layer with the GB style.
    msp.add_text(
        "技术要求：未注倒角 C1",
        height=3.5 * scale,
        dxfattribs={"layer": "文字", "style": "GB"},
    ).set_placement((x0, y0 - 30 * scale))

    # ---- title block block definition ----------------------------------
    if TITLE_BLOCK not in doc.blocks:
        blk = doc.blocks.new(TITLE_BLOCK)
        blk.add_attdef("图名", insert=(4, 18), dxfattribs={"height": 3.5, "style": "GB"})
        blk.add_attdef("图号", insert=(4, 12), dxfattribs={"height": 3.5, "style": "GB"})
        blk.add_attdef("比例", insert=(4, 6), dxfattribs={"height": 3.5, "style": "GB"})
        blk.add_lwpolyline(
            [(0, 0), (70, 0), (70, 24), (0, 24)], close=True,
            dxfattribs={"layer": "图框"},
        )

    # ---- paper space ---------------------------------------------------
    layout = doc.layouts.get("Layout1")
    layout.dxf.paper_width = paper_w
    layout.dxf.paper_height = paper_h

    margin = 10.0
    layout.add_lwpolyline(
        [(margin, margin), (paper_w - margin, margin),
         (paper_w - margin, paper_h - margin), (margin, paper_h - margin)],
        close=True,
        dxfattribs={"layer": "图框"},
    )

    ref = layout.add_blockref(
        TITLE_BLOCK, (paper_w - margin - 72, margin + 2), dxfattribs={"layer": "图框"}
    )
    ref.add_auto_attribs({"图名": "轴承座", "图号": "GB-0001", "比例": "1:2"})

    # The stated scale, in paper space: this is what drawing.scale looks for.
    layout.add_text(
        "比例 1:2",
        height=4.0,
        dxfattribs={"layer": "图框", "style": "GB"},
    ).set_placement((margin + 4, margin + 4))

    doc.saveas(path)


def verify(path: Path) -> tuple[bool, list[str]]:
    sys.path.insert(0, str(ROOT.parent / "src"))
    from cad_deliver.pipeline import verify_file

    verdict = verify_file(str(path), "GB_T_TIER1")
    problems = []
    for check in verdict.checks:
        if not check.ok and check.severity in ("error", "blocked"):
            problems.append(f"{check.ident}: {check.detail}")
    for rule in verdict.rules:
        if not rule.ok and rule.severity.value in ("error", "blocked"):
            problems.append(f"{rule.code}: {rule.detail}")
    return (verdict.verdict.value == "PASS"), problems


def main() -> int:
    GEN_DIR.mkdir(parents=True, exist_ok=True)
    for old in GEN_DIR.glob("*.dxf"):
        old.unlink()

    failures = 0
    for name, w, h, closed_flag in SAMPLES:
        path = GEN_DIR / f"{name}.dxf"
        build(path, w, h, closed_flag)
        ok, problems = verify(path)
        flag = "flag-off" if not closed_flag else "closed  "
        if ok:
            print(f"  ok   {name:24} {w:6.0f}x{h:<6.0f} {flag}  {path.stat().st_size:>6} B")
        else:
            failures += 1
            print(f"  FAIL {name:24} {w:6.0f}x{h:<6.0f} {flag}")
            for problem in problems:
                print(f"         {problem}")

    total = len(SAMPLES)
    print(f"\ngenerate: {total - failures}/{total} compliant, {failures} failing")
    print(f"samples : {GEN_DIR}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())