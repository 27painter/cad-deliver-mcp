"""Render DXF samples to PNG, at a size and palette a vision model can read.

Why this needs care: a default ezdxf render draws on white with black lines, so layer
colours — which carry the drafting meaning — disappear, and the sheet boundary is not
drawn at all, so nobody can judge the paper size from the image. Both are configured
here explicitly.

The frame comes from each layout's declared paper size, not from the geometry extent,
so a wrong sheet reads as a wrong sheet in the picture.

    python scripts/render_dxf_png.py            # both groups
    python scripts/render_dxf_png.py --group real
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

# Chinese labels are the whole point of the title-block judgement. Without a CJK font
# matplotlib draws tofu boxes and the field names become unreadable, which silently
# turns one of the five prompt questions into an unanswerable one.
matplotlib.rcParams["font.sans-serif"] = [
    "Microsoft YaHei",
    "SimHei",
    "SimSun",
    "Noto Sans CJK SC",
    "DejaVu Sans",
]
matplotlib.rcParams["axes.unicode_minus"] = False
import ezdxf  # noqa: E402
from ezdxf.addons.drawing import RenderContext, Frontend  # noqa: E402
from ezdxf.addons.drawing.config import (  # noqa: E402
    BackgroundPolicy,
    ColorPolicy,
    Configuration,
    TextPolicy,
)
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend  # noqa: E402

RENDERS = ROOT / "benchmarks" / "renders"
FIXTURES = ROOT / "benchmarks" / "fixtures"
GROUPS = ("real", "real_sw", "mutated", "gen")
DPI = 150


def render(path: Path, out: Path) -> tuple[int, int]:
    doc = ezdxf.readfile(path)

    # Paper size from the layout that actually carries content; fall back to A3.
    width_mm, height_mm = 420.0, 297.0
    for layout in doc.layouts:
        if layout.name.lower() != "model" and layout.dxf.get("paper_width", 0):
            width_mm = float(layout.dxf.paper_width)
            height_mm = float(layout.dxf.paper_height)
            break

    fig = plt.figure(figsize=(width_mm / 25.4, height_mm / 25.4), dpi=DPI)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()

    config = Configuration(
        background_policy=BackgroundPolicy.WHITE,
        color_policy=ColorPolicy.COLOR,
        lineweight_scaling=1.4,     # thin/hidden/centre must stay distinguishable
        min_lineweight=0.35,
        # Text is drawn separately: ezdxf resolves it through the DXF font name (`txt`,
        # an SHX stroke font with no CJK glyphs) and renders Chinese as boxes. Asked to
        # ignore text, it still draws dimensions and leaders, leaving only the labels to
        # us.
        # IGNORE, not FILLING: with FILLING ezdxf draws tofu boxes for CJK and the
        # white patch meant to cover them misses, producing 删盖 instead of 端盖.
        # Absent glyphs are safer for a reader than garbled ones.
        text_policy=TextPolicy.IGNORE,
    )
    backend = MatplotlibBackend(ax, adjust_figure=False)
    frontend = Frontend(RenderContext(doc), backend, config=config)

    # Draw exactly one space. An engineering drawing keeps geometry in model space and
    # the frame plus title block in a paper-space layout, but the layout's VIEWPORT
    # already renders the model content — so drawing both puts every part on the sheet
    # twice, superimposed. Prefer the layout; fall back to model space only when no
    # layout carries anything.
    target = None
    for layout in doc.layouts:
        if layout.name.lower() == "model":
            continue
        if len(list(layout)):
            target = layout
            break

    if target is None:
        frontend.draw_layout(doc.modelspace(), finalize=True)
    else:
        entities = list(target)
        # A VIEWPORT renders the model content itself, so drawing model space as well
        # would put every part on the sheet twice. Without one - the ezdxf-generated
        # drawings - the layout is only frame and title block, and the part lives
        # nowhere unless model space is drawn too.
        has_viewport = any(e.dxftype() == "VIEWPORT" for e in entities)
        frontend.draw_layout(target, finalize=False)
        if not has_viewport:
            frontend.draw_layout(doc.modelspace(), finalize=False)
        backend.finalize()

    # Text, placed with matplotlib's own font stack. Groups (title-block inserts) are
    # walked too, because that is where 图名 / 图号 / 比例 live.
    for entity in _iter_text(layout if layout is not None else doc.modelspace()):
        _draw_text(ax, entity)

    # Sheet boundary, so the paper size is visible rather than implied.
    ax.set_xlim(0, width_mm)
    ax.set_ylim(0, height_mm)
    ax.set_aspect("equal")
    ax.add_patch(
        plt.Rectangle((0, 0), width_mm, height_mm, fill=False, edgecolor="#999999", linewidth=0.8)
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=DPI, facecolor="white")
    plt.close(fig)
    return width_mm, height_mm



# 1 mm in points, for converting a DXF text height to a matplotlib font size. The
# figure is sized in millimetres, so the two scales line up exactly.
PT_PER_MM = 72.0 / 25.4


def _iter_text(space):
    """Yield TEXT, MTEXT and ATTRIB entities, descending into block references.

    ATTRIB matters: the title-block field values sit on the INSERT, not inside the block
    definition. `virtual_entities()` expands ATTDEF (the template) but not ATTRIB (the
    filled value), so a walk that only follows virtual geometry renders the labels and
    leaves the fields looking blank.
    """
    for entity in space:
        kind = entity.dxftype()
        if kind in ("TEXT", "MTEXT"):
            yield entity
        elif kind == "INSERT":
            for attrib in getattr(entity, "attribs", ()):
                yield attrib
            try:
                yield from _iter_text(entity.virtual_entities())
            except Exception:  # noqa: BLE001 - a broken block must not kill the render
                continue


def _has_cjk(content: str) -> bool:
    return any("\u3000" <= ch <= "\u9fff" or "\uff00" <= ch <= "\uffef" for ch in content)


def _draw_text(ax, entity) -> None:
    """Place one text entity with a CJK-capable font.

    Only strings containing CJK are redrawn. ezdxf already rendered the ASCII ones
    correctly through the SHX font, and redrawing them would double-print.
    """
    doc = entity.doc
    if entity.dxftype() in ("TEXT", "ATTRIB", "ATTDEF"):
        content = entity.dxf.get("text", "")
        insert = entity.dxf.get("insert", (0, 0, 0))
        height = float(entity.dxf.get("height", 2.5) or 2.5)
        rotation = float(entity.dxf.get("rotation", 0.0) or 0.0)
        align = "left"
    else:
        content = entity.text
        insert = entity.dxf.get("insert", (0, 0, 0))
        height = float(entity.dxf.get("char_height", 2.5) or 2.5)
        rotation = float(entity.dxf.get("rotation", 0.0) or 0.0)
        align = "left"

    content = content.replace("\\P", "\n")
    if not content.strip():
        return

    layer_name = entity.dxf.get("layer", "0")
    try:
        rgb = doc.layers.get(layer_name).color
    except Exception:  # noqa: BLE001
        rgb = 7
    colour = "#000000"
    if isinstance(rgb, int) and rgb not in (7, 0):
        from ezdxf.colors import int2rgb

        r, g, b = int2rgb(rgb)
        colour = f"#{r:02x}{g:02x}{b:02x}"

    ax.text(
        float(insert[0]),
        float(insert[1]),
        content,
        fontsize=max(height * PT_PER_MM, 1.0),
        color=colour,
        rotation=rotation,
        ha=align,
        va="baseline",
        family="sans-serif",
        clip_on=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=GROUPS, default=None)
    args = parser.parse_args()

    groups = (args.group,) if args.group else GROUPS
    total = 0
    for group in groups:
        folder = FIXTURES / group
        if not folder.is_dir():
            continue
        files = sorted(p for p in folder.iterdir() if p.suffix.lower() == ".dxf")
        if not files:
            continue
        print(f"{group}: {len(files)} file(s)")
        for path in files:
            out = RENDERS / group / (path.stem + ".png")
            try:
                w, h = render(path, out)
                size = out.stat().st_size if out.exists() else 0
                print(f"  {path.name:32} {w:.0f}x{h:.0f} mm  {size // 1024:>4} KB")
                total += 1
            except Exception as exc:  # noqa: BLE001
                print(f"  {path.name:32} FAILED: {type(exc).__name__}: {exc}")

    print()
    print(f"rendered {total} image(s) into {RENDERS.relative_to(ROOT)}")
    return 0 if total else 1


if __name__ == "__main__":
    raise SystemExit(main())