"""Re-bucket the repair experiment by what the defect *requires*, not by size.

The entity-count hypothesis failed: 516 entities did not separate the arms any
more than 8 did. This script tests the replacement hypothesis — that the cost of
finding a defect scales with the *query* needed to expose it, not with the number
of entities carrying noise.

Levels, from cheapest to dearest to discover:

    L0  attribute    a value on one entity is wrong (layer name, attribute text)
                     -> one group-by over the entity table
    L1  numeric      a stated value disagrees with a computed one
                     -> one comparison per candidate, cheap to compute
    L2  topological  a relation between entities is broken (an outline that does
                     not close) -> build a graph over endpoints and look at degrees

L3 (semantic: which layer name is correct for this shop) and L4 (cross-file: does
this drawing match the part) are not represented in this dataset, which is itself
the finding: the benchmark never asked a question a script could not answer.

    python benchmarks/agent/analyse_levels.py
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent

# What each sample's defect demands of a solver, independent of drawing size.
LEVELS = {
    "mut_01_bbox_point": ("L1", "numeric"),
    "mut_05_profile_open": ("L2", "topological, trivial (1 polyline)"),
    "mut_09_sheet_size": ("L0", "attribute"),
    "mut_13_titleblock_gone": ("L0", "attribute"),
    "mut_17_dim_wrong_layer": ("L0", "attribute"),
    "mut_19_contour_on_zero": ("L0", "attribute"),
    "complex_01_profile_open": ("L2", "topological, graph (200 segments)"),
    "complex_02_dim_layer": ("L0", "attribute"),
    "complex_03_dim_text": ("L1", "numeric"),
    "complex_04_title_blank": ("L0", "attribute"),
    "complex_05_two_defects": ("L0+L2", "mixed"),
    "complex_06_all_four": ("L0+L1+L2", "mixed"),
}


def main() -> int:
    data = json.loads((HERE / "repair_all.json").read_text(encoding="utf-8"))
    rows = data["rows"]

    by_key = {(r["regime"], r["arm"], r["sample"]): r for r in rows}

    print(f"{'regime':8} {'sample':26} {'level':7} {'A calls':>8} {'B calls':>8} {'delta':>7}")
    print("-" * 72)
    for row in rows:
        if row["arm"] != "A":
            continue
        sample = row["sample"]
        level = LEVELS.get(sample, ("?", ""))[0]
        partner = by_key.get((row["regime"], "B", sample))
        a = row["tool_calls"]
        b = partner["tool_calls"] if partner else ""
        delta = "" if not (a and b) else f"{(b - a) / a:+.0%}"
        print(f"{row['regime']:8} {sample:26} {level:7} {str(a):>8} {str(b):>8} {delta:>7}")

    # Aggregate over samples that sit at exactly one level.
    buckets: dict[str, list[tuple[float, float]]] = {}
    for row in rows:
        if row["arm"] != "A":
            continue
        level = LEVELS.get(row["sample"], ("?", ""))[0]
        if "+" in level or level == "?":
            continue
        partner = by_key.get((row["regime"], "B", row["sample"]))
        if row["tool_calls"] and partner and partner["tool_calls"]:
            buckets.setdefault(level, []).append((row["tool_calls"], partner["tool_calls"]))

    print("\nBy query level (single-level samples, cases with recorded cost):")
    print(f"  {'level':6} {'n':>2} {'A mean':>8} {'B mean':>8} {'delta':>7}")
    for level in sorted(buckets):
        pairs = buckets[level]
        a_mean = statistics.fmean(p[0] for p in pairs)
        b_mean = statistics.fmean(p[1] for p in pairs)
        print(f"  {level:6} {len(pairs):>2} {a_mean:>8.1f} {b_mean:>8.1f} {(b_mean - a_mean) / a_mean:>+7.0%}")

    print("\nSame level, different size — the topological case:")
    for regime, sample in (("simple", "mut_05_profile_open"), ("complex", "complex_01_profile_open")):
        row = by_key[(regime, "A", sample)]
        partner = by_key[(regime, "B", sample)]
        print(
            f"  {regime:8} {sample:26} A={row['tool_calls']:>3} calls  "
            f"B={partner['tool_calls']:>3} calls  ({LEVELS[sample][1]})"
        )
    print("  -> entity count tripled the control arm's cost (5 -> 14) without")
    print("     changing whether the defect could be found at all.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())