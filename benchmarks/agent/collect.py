"""Collect both regimes into one dataset and emit the comparison tables.

Data source notes, because two of these numbers are weaker than they look:

* `tool_calls` is self-reported by each agent. It is a proxy, not instrumentation.
* `tokens` is **not observable** through this harness. It is `null` everywhere,
  and the CSV says so rather than printing a made-up number.
* Two simple-regime agents returned no report although their files ended up
  passing. Their outcome is taken from re-running the gate; their cost is
  recorded as unknown rather than guessed.

    python benchmarks/agent/collect.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

# (regime, arm, sample, passed_at_1, passed_at_3, rounds, tool_calls, elapsed_s)
ROWS = [
    # ---- simple regime: 8 entities, one defect each -------------------
    ("simple", "A", "mut_01_bbox_point",      True,  True, 1,   15, 82),
    ("simple", "A", "mut_05_profile_open",    True,  True, 1,    5, 26),
    ("simple", "A", "mut_09_sheet_size",      True,  True, None, None, None),   # report lost
    ("simple", "A", "mut_13_titleblock_gone", True,  True, 1,   10, 71),
    ("simple", "A", "mut_17_dim_wrong_layer", True,  True, 1,    9, 45),
    ("simple", "A", "mut_19_contour_on_zero", True,  True, 1,    9, 43),
    ("simple", "B", "mut_01_bbox_point",      True,  True, 1,   16, 158),
    ("simple", "B", "mut_05_profile_open",    True,  True, 1,    6, 33),
    ("simple", "B", "mut_09_sheet_size",      True,  True, 1,    7, 37),
    ("simple", "B", "mut_13_titleblock_gone", False, True, 2,    7, 66),   # needed 2 rounds
    ("simple", "B", "mut_17_dim_wrong_layer", True,  True, 1,    5, 19),
    ("simple", "B", "mut_19_contour_on_zero", True,  True, None, None, None),  # report lost

    # ---- complex regime: 516 entities, hidden defects -----------------
    ("complex", "A", "complex_01_profile_open",   True, True, 1, 14, 55),
    ("complex", "A", "complex_02_dim_layer",      True, True, 1,  5, 18),
    ("complex", "A", "complex_03_dim_text",       True, True, 1, 10, 40),
    ("complex", "A", "complex_04_title_blank",    True, True, 1,  6, 41),
    ("complex", "A", "complex_05_two_defects",    True, True, 1, 11, 45),
    ("complex", "A", "complex_06_all_four",       True, True, 1, 12, 74),
    ("complex", "B", "complex_01_profile_open",   True, True, 1,  9, 58),
    ("complex", "B", "complex_02_dim_layer",      True, True, 1,  5, 19),
    ("complex", "B", "complex_03_dim_text",       True, True, 1,  6, 29),
    ("complex", "B", "complex_04_title_blank",    True, True, 1,  6, 27),
    ("complex", "B", "complex_05_two_defects",    True, True, 1,  9, 52),
    ("complex", "B", "complex_06_all_four",       True, True, 1, 10, 58),
]

COLUMNS = [
    "regime", "arm", "sample", "passed_at_1", "passed_at_3",
    "rounds", "tool_calls", "elapsed_s", "tokens",
]


def mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def main() -> int:
    rows = []
    for regime, arm, sample, at1, at3, rounds, calls, elapsed in ROWS:
        rows.append(
            {
                "regime": regime,
                "arm": arm,
                "sample": sample,
                "passed_at_1": at1,
                "passed_at_3": at3,
                "rounds": "" if rounds is None else rounds,
                "tool_calls": "" if calls is None else calls,
                "elapsed_s": "" if elapsed is None else elapsed,
                "tokens": "",          # not observable in this harness
            }
        )

    per_sample = HERE / "repair_all.csv"
    with open(per_sample, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    summary = []
    for regime in ("simple", "complex"):
        for arm in ("A", "B"):
            group = [r for r in rows if r["regime"] == regime and r["arm"] == arm]
            calls = [r["tool_calls"] for r in group if r["tool_calls"] != ""]
            times = [r["elapsed_s"] for r in group if r["elapsed_s"] != ""]
            summary.append(
                {
                    "regime": regime,
                    "arm": arm,
                    "n": len(group),
                    "pass_at_1": sum(1 for r in group if r["passed_at_1"]),
                    "pass_at_3": sum(1 for r in group if r["passed_at_3"]),
                    "mean_tool_calls": mean(calls),
                    "mean_elapsed_s": mean(times),
                    "tokens": "",
                    "cost_cases": len(calls),
                }
            )

    summary_path = HERE / "complex_repair_results.csv"
    with open(summary_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0].keys()))
        writer.writeheader()
        writer.writerows(summary)

    (HERE / "repair_all.json").write_text(
        json.dumps({"rows": rows, "summary": summary}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("Simple vs Complex — closed-loop repair\n")
    header = f"| {'regime':8} | {'arm':3} | {'n':>2} | {'Pass@1':>7} | {'Pass@3':>7} | {'mean calls':>10} | {'mean sec':>8} |"
    print(header)
    print("|" + "-" * 10 + "|" + "-" * 5 + "|" + "-" * 4 + "|" + "-" * 9 + "|" + "-" * 9 + "|" + "-" * 12 + "|" + "-" * 10 + "|")
    for row in summary:
        calls = "n/a" if row["mean_tool_calls"] is None else f"{row['mean_tool_calls']:.1f}"
        secs = "n/a" if row["mean_elapsed_s"] is None else f"{row['mean_elapsed_s']:.0f}"
        print(
            f"| {row['regime']:8} | {row['arm']:3} | {row['n']:2} | "
            f"{row['pass_at_1']}/{row['n']:>2}    | {row['pass_at_3']}/{row['n']:>2}    | "
            f"{calls:>10} | {secs:>8} |"
        )

    print("\ncost delta (B vs A, over cases with a recorded cost):")
    for regime in ("simple", "complex"):
        a = next(r for r in summary if r["regime"] == regime and r["arm"] == "A")
        b = next(r for r in summary if r["regime"] == regime and r["arm"] == "B")
        if a["mean_tool_calls"] and b["mean_tool_calls"]:
            dc = (b["mean_tool_calls"] - a["mean_tool_calls"]) / a["mean_tool_calls"]
            dt = (b["mean_elapsed_s"] - a["mean_elapsed_s"]) / a["mean_elapsed_s"]
            print(f"  {regime:8} tool calls {dc:+.0%}   wall time {dt:+.0%}")

    print(f"\nwrote {per_sample.name}, {summary_path.name}, repair_all.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())