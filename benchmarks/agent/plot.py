"""Draw the Simple-vs-Complex repair chart as a standalone SVG.

Reads `repair_all.json` (written by collect.py) and writes `repair_chart.svg`.
No plotting library: the figure is rectangles and text, so it rebuilds anywhere
the repository runs.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
WIDTH, HEIGHT = 760, 430
LEFT, RIGHT, TOP, BOTTOM = 100, 700, 80, 300

COLORS = {"A": "#9aa5b1", "B": "#2f6feb"}
LABELS = {"A": "A — code only", "B": "B — full fix_plan"}


def main() -> int:
    data = json.loads((HERE / "repair_all.json").read_text(encoding="utf-8"))
    summary = data["summary"]

    groups = [
        ("simple", "A"), ("simple", "B"),
        ("complex", "A"), ("complex", "B"),
    ]
    lookup = {(row["regime"], row["arm"]): row for row in summary}

    slot = (RIGHT - LEFT) / len(groups)
    plot_h = BOTTOM - TOP
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="#ffffff"/>',
        '<text x="24" y="34" font-family="Segoe UI, Arial, sans-serif" font-size="17" '
        'font-weight="600" fill="#1f2933">Closed-loop repair: simple (8 entities) vs complex (516 entities)</text>',
        '<text x="24" y="56" font-family="Segoe UI, Arial, sans-serif" font-size="12" '
        'fill="#52606d">6 samples per cell, up to 3 attempts, identical ezdxf read/write rights in both arms</text>',
    ]

    for tick in range(0, 101, 25):
        y = BOTTOM - plot_h * tick / 100
        parts.append(f'<line x1="{LEFT}" y1="{y:.1f}" x2="{RIGHT}" y2="{y:.1f}" stroke="#e4e7eb"/>')
        parts.append(
            f'<text x="{LEFT - 10}" y="{y + 4:.1f}" text-anchor="end" font-family="Segoe UI, Arial, sans-serif" '
            f'font-size="11" fill="#7b8794">{tick}%</text>'
        )

    for index, (regime, arm) in enumerate(groups):
        row = lookup[(regime, arm)]
        rate = row["pass_at_1"] / row["n"]
        h = plot_h * rate
        x = LEFT + index * slot + slot * 0.2
        w = slot * 0.6
        parts.append(
            f'<rect x="{x:.1f}" y="{BOTTOM - h:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'fill="{COLORS[arm]}" rx="2"/>'
        )
        parts.append(
            f'<text x="{x + w / 2:.1f}" y="{BOTTOM - h - 8:.1f}" text-anchor="middle" '
            f'font-family="Segoe UI, Arial, sans-serif" font-size="13" fill="#1f2933">'
            f'{row["pass_at_1"]}/{row["n"]}</text>'
        )
        calls = row["mean_tool_calls"]
        parts.append(
            f'<text x="{x + w / 2:.1f}" y="{BOTTOM + 18:.1f}" text-anchor="middle" '
            f'font-family="Segoe UI, Arial, sans-serif" font-size="11" fill="#52606d">{arm}</text>'
        )
        parts.append(
            f'<text x="{x + w / 2:.1f}" y="{BOTTOM + 34:.1f}" text-anchor="middle" '
            f'font-family="Segoe UI, Arial, sans-serif" font-size="10" fill="#9aa5b1">'
            f'{calls:.1f} calls</text>'
        )

    for index in range(2):
        centre = LEFT + index * slot * 2 + slot
        parts.append(
            f'<text x="{centre:.1f}" y="{BOTTOM + 58:.1f}" text-anchor="middle" '
            f'font-family="Segoe UI, Arial, sans-serif" font-size="13" font-weight="600" fill="#1f2933">'
            f'{"simple regime" if index == 0 else "complex regime"}</text>'
        )

    legend_y = BOTTOM + 84
    for index, arm in enumerate(("A", "B")):
        x = LEFT + index * 220
        parts.append(f'<rect x="{x}" y="{legend_y}" width="12" height="12" fill="{COLORS[arm]}" rx="2"/>')
        parts.append(
            f'<text x="{x + 18}" y="{legend_y + 11}" font-family="Segoe UI, Arial, sans-serif" '
            f'font-size="12" fill="#52606d">{LABELS[arm]}</text>'
        )

    parts.append(
        f'<text x="24" y="{HEIGHT - 14}" font-family="Segoe UI, Arial, sans-serif" font-size="11" '
        f'fill="#9aa5b1">Pass@3 is 6/6 in all four cells. Complexity bought no separation: an agent '
        f'writes a script, so 516 entities cost it no more than 8.</text>'
    )
    parts.append("</svg>")

    out = HERE / "repair_chart.svg"
    out.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())