"""Draw the repair-experiment chart as a standalone SVG.

No plotting library: the figure is a handful of rectangles and text, and a
dependency-free generator means the paper's figure can be rebuilt anywhere the
repository runs. Reads `results.json`, writes `repair_chart.svg`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WIDTH, HEIGHT = 640, 400
PLOT_LEFT, PLOT_RIGHT = 90, 600
PLOT_TOP, PLOT_BOTTOM = 70, 320

A_COLOR = "#9aa5b1"
B_COLOR = "#2f6feb"


def bar(x: float, y: float, w: float, h: float, fill: str, label: str) -> str:
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
        f'fill="{fill}" rx="2"/>'
        f'<text x="{x + w / 2:.1f}" y="{y - 8:.1f}" text-anchor="middle" '
        f'font-family="Segoe UI, Arial, sans-serif" font-size="13" fill="#1f2933">{label}</text>'
    )


def main() -> int:
    data = json.loads((HERE / "results.json").read_text(encoding="utf-8"))
    summary = data["summary"]

    metrics = [("Pass@1", "pass_at_1"), ("Pass@3", "pass_at_3")]
    arms = [("A", "control: error code only", A_COLOR), ("B", "treatment: full fix_plan", B_COLOR)]

    group_width = (PLOT_RIGHT - PLOT_LEFT) / len(metrics)
    bar_width = group_width / (len(arms) + 1)
    plot_height = PLOT_BOTTOM - PLOT_TOP

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}">',
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="#ffffff"/>',
        '<text x="20" y="34" font-family="Segoe UI, Arial, sans-serif" font-size="17" '
        'font-weight="600" fill="#1f2933">Closed-loop repair: does the fix_plan help?</text>',
        '<text x="20" y="54" font-family="Segoe UI, Arial, sans-serif" font-size="12" '
        'fill="#52606d">6 defect samples x 2 arms, up to 3 repair attempts each</text>',
    ]

    # y axis
    for tick in range(0, 101, 25):
        y = PLOT_BOTTOM - plot_height * tick / 100
        parts.append(
            f'<line x1="{PLOT_LEFT}" y1="{y:.1f}" x2="{PLOT_RIGHT}" y2="{y:.1f}" '
            f'stroke="#e4e7eb" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{PLOT_LEFT - 10}" y="{y + 4:.1f}" text-anchor="end" '
            f'font-family="Segoe UI, Arial, sans-serif" font-size="11" fill="#7b8794">{tick}%</text>'
        )

    for gi, (title, key) in enumerate(metrics):
        group_x = PLOT_LEFT + gi * group_width
        for ai, (arm, _label, colour) in enumerate(arms):
            n = summary[arm]["n"]
            value = summary[arm][key]
            pct = value / n if n else 0.0
            h = plot_height * pct
            x = group_x + bar_width * (ai + 1) - bar_width * 0.05
            w = bar_width * 0.76
            parts.append(bar(x, PLOT_BOTTOM - h, w, h, colour, f"{value}/{n}"))
            parts.append(
                f'<text x="{x + w / 2:.1f}" y="{PLOT_BOTTOM + 16:.1f}" text-anchor="middle" '
                f'font-family="Segoe UI, Arial, sans-serif" font-size="11" fill="#52606d">{arm}</text>'
            )
        parts.append(
            f'<text x="{group_x + group_width / 2:.1f}" y="{PLOT_BOTTOM + 40:.1f}" '
            f'text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" font-size="13" '
            f'font-weight="600" fill="#1f2933">{title}</text>'
        )

    # legend
    legend_y = PLOT_BOTTOM + 64
    for ai, (arm, label, colour) in enumerate(arms):
        x = PLOT_LEFT + ai * 250
        parts.append(f'<rect x="{x}" y="{legend_y}" width="12" height="12" fill="{colour}" rx="2"/>')
        parts.append(
            f'<text x="{x + 18}" y="{legend_y + 11}" font-family="Segoe UI, Arial, sans-serif" '
            f'font-size="12" fill="#52606d">{arm} — {label}</text>'
        )

    parts.append(
        f'<text x="20" y="{HEIGHT - 12}" font-family="Segoe UI, Arial, sans-serif" font-size="11" '
        f'fill="#9aa5b1">No difference: the control arm could read the DXF and diagnose the defect '
        f'itself. See results.json for why this design cannot isolate the fix_plan.</text>'
    )
    parts.append("</svg>")

    out = HERE / "repair_chart.svg"
    out.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {out}")
    for arm, *_ in arms:
        print(f"  {arm}: Pass@1 {summary[arm]['pass_at_1']}/{summary[arm]['n']}  "
              f"Pass@3 {summary[arm]['pass_at_3']}/{summary[arm]['n']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())