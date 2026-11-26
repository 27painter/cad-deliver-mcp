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
import ezdxf  # noqa: E402
from ezdxf.addons.drawing import RenderContext, Frontend  # noqa: E402
from ezdxf.addons.drawing.config import (  # noqa: E402
    BackgroundPolicy,
    ColorPolicy,
    Configuration,
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
    )
    backend = MatplotlibBackend(ax, adjust_figure=False)
    Frontend(RenderContext(doc), backend, config=config).draw_layout(
        doc.modelspace(), finalize=True
    )

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