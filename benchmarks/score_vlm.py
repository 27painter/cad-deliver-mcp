"""Score the VLM run on whether its *reason* matches the injected defect.

`vlm_rejects` only says the model refused. On this set that is not the same as catching
the defect: the model refused 17 of 30 compliant drawings too, so a refusal is weak
evidence. This script records, per sample, whether the finding actually names the thing
that was broken, and writes `results/baseline_vlm_scored.csv`.

The judgement is manual — it has to be, since it means reading prose — so the verdicts
are listed in `REASON_MATCHES` below, with the phrase each one rests on. Anyone can
dispute them by reading the finding column in `baseline_vlm.csv`.
"""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "benchmarks" / "results"

# sample -> (reason points at the defect?, the phrase that decides it)
REASON_MATCHES: dict[str, tuple[bool, str]] = {
    # bbox: the part vanished. Every one of these says so.
    "mut_01_bbox_point": (True, "no geometry, lines, or dimensions are present"),
    "mut_02_bbox_point": (True, "no geometry, lines, or dimensions are present"),
    "mut_03_bbox_point": (True, "one red dot are visible - no geometry"),
    "mut_04_bbox_point": (True, "no geometry, lines, or dimensions are present"),
    # profile: three describe the gap, one talks about missing dimensions instead.
    "mut_05_profile_open": (True, "outline is open ... leaving a gap"),
    "mut_06_profile_open": (True, "open contour ... does not connect to the vertical line"),
    "mut_07_profile_open": (False, "no visible dimensions or line weights - never mentions the gap"),
    "mut_08_profile_open": (True, "open contour ... the two loose ends are approximately"),
    # sheet size: none of the four identifies a wrong sheet; mut_10 passes outright.
    "mut_09_sheet_size": (False, "reports A3 as if correct; blames the title block"),
    "mut_10_sheet_size": (False, "accepts the drawing"),
    "mut_11_sheet_size": (False, "reports A3 as if correct"),
    "mut_12_sheet_size": (False, "blames a missing title block"),
    # title block absent / blank: both correct.
    "mut_13_titleblock_gone": (True, "no ... complete title block is present"),
    "mut_14_titleblock_gone": (True, "no title block"),
    "mut_15_titleblock_blank": (True, "no visible title block fields filled, only 图名 text present"),
    "mut_16_titleblock_blank": (True, "no visible title block fields filled"),
    # dimension on the wrong layer: neither mentions a layer.
    "mut_17_dim_wrong_layer": (False, "blames the title block, never the layer"),
    "mut_18_dim_wrong_layer": (False, "says no visible dimensions; never mentions the layer"),
    # contour on layer 0: the colour does not change, so neither can see it.
    "mut_19_contour_on_zero": (False, "blames a cropped image and monochrome rendering"),
    "mut_20_contour_on_zero": (False, "blames a gap in the outline and a blank title block"),
}


def main() -> int:
    rows = list(csv.DictReader(open(RESULTS / "baseline_vlm.csv", encoding="utf-8")))
    out_rows = []
    for row in rows:
        sample = row["sample"]
        if row["group"] == "mutated":
            matched, basis = REASON_MATCHES.get(sample, (None, ""))
            caught_by_reason = "yes" if matched else "no"
        else:
            matched, basis, caught_by_reason = None, "", ""
        out_rows.append(
            {
                "sample": sample,
                "group": row["group"],
                "expected_code": row["expected_code"],
                "should_be_clean": row["should_be_clean"],
                "vlm_refused": row["vlm_rejects"],
                "vlm_reported_sheet": row["vlm_sheet"],
                "confidence": row["vlm_confidence"],
                "reason_matches_defect": caught_by_reason,
                "basis": basis,
            }
        )

    out = RESULTS / "baseline_vlm_scored.csv"
    with open(out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(out_rows[0].keys()))
        writer.writeheader()
        writer.writerows(out_rows)

    mutated = [r for r in out_rows if r["group"] == "mutated"]
    compliant = [r for r in out_rows if r["should_be_clean"] == "True"]
    refused = sum(1 for r in mutated if r["vlm_refused"] == "yes")
    caught = sum(1 for r in mutated if r["reason_matches_defect"] == "yes")
    fp = sum(1 for r in compliant if r["vlm_refused"] == "yes")

    print(f"{'defect class':<26}{'refused':>9}{'reason matched':>16}")
    print("-" * 52)
    for code in sorted({r["expected_code"] for r in mutated}):
        group = [r for r in mutated if r["expected_code"] == code]
        print(
            f"{code:<26}{sum(1 for r in group if r['vlm_refused'] == 'yes')}/{len(group):<7}"
            f"{sum(1 for r in group if r['reason_matches_defect'] == 'yes')}/{len(group):>7}"
        )
    print()
    print(f"refused        : {refused}/{len(mutated)}  ({refused / len(mutated):.0%})")
    print(f"reason matched : {caught}/{len(mutated)}  ({caught / len(mutated):.0%})")
    print(f"false positives: {fp}/{len(compliant)}  ({fp / len(compliant):.0%})")
    print()
    print(f"written: {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())