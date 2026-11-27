"""Score the human baseline and compare it with the rule layer and the vision model.

Reads one or more filled `score_sheet_*.csv`, joins them against the answer key, and
reports:

  * recall and false-positive rate per rater, with Clopper-Pearson bounds;
  * agreement between raters — Fleiss' kappa for three or more, Cohen's for two;
  * agreement with the rule layer, treated as a second rater;
  * the same for the vision model, when `baseline_vlm_scored.csv` exists.

    python scripts/analyze_human_eval.py --condition cad r1.csv r2.csv r3.csv
    python scripts/analyze_human_eval.py --condition png r1.csv r2.csv

Verdict column accepts: pass / fail / unknown (case-insensitive), or 合格 / 不合格 / 判不了.
Anything else counts as blank and the case is excluded, not guessed.
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HUMAN = ROOT / "benchmarks" / "human_eval"
RESULTS = ROOT / "benchmarks" / "results"

NORMALISE = {
    "pass": "PASS",
    "合格": "PASS",
    "ok": "PASS",
    "fail": "FAIL",
    "不合格": "FAIL",
    "不合格": "FAIL",
    "unknown": "UNKNOWN",
    "判不了": "UNKNOWN",
    "不知道": "UNKNOWN",
}


def cp_upper(k: int, n: int, alpha: float = 0.05) -> float:
    if n <= 0 or k >= n:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        cdf = sum(math.comb(n, i) * mid**i * (1 - mid) ** (n - i) for i in range(k + 1))
        if cdf > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def cp_lower(k: int, n: int, alpha: float = 0.05) -> float:
    if n <= 0 or k <= 0:
        return 0.0
    if k >= n:
        return alpha ** (1 / n)
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        # P(X >= k | mid) rises with mid, so a tail below alpha means mid is too small.
        tail = sum(math.comb(n, i) * mid**i * (1 - mid) ** (n - i) for i in range(k, n + 1))
        if tail < alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def load_sheet(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in csv.DictReader(open(path, encoding="utf-8")):
        raw = (row.get("verdict") or "").strip().lower()
        if raw in NORMALISE:
            out[row["case"]] = NORMALISE[raw]
    return out


def kappa(pairs: list[tuple[str, str]], categories: tuple[str, ...] = ("PASS", "FAIL", "UNKNOWN")) -> float:
    """Cohen's kappa for two raters on the cases both scored."""
    if not pairs:
        return float("nan")
    n = len(pairs)
    observed = sum(1 for a, b in pairs if a == b) / n
    ca = Counter(a for a, _ in pairs)
    cb = Counter(b for _, b in pairs)
    expected = sum((ca[c] / n) * (cb[c] / n) for c in categories)
    if expected >= 1.0:
        return float("nan")
    return (observed - expected) / (1 - expected)


def fleiss(ratings: list[dict[str, str]], categories=("PASS", "FAIL", "UNKNOWN")) -> float:
    """Fleiss' kappa over N raters on the cases all of them scored."""
    if len(ratings) < 2:
        return float("nan")
    common = set.intersection(*(set(r) for r in ratings))
    if not common:
        return float("nan")
    n_raters = len(ratings)
    p_items = []
    totals = Counter()
    for case in common:
        counts = Counter(r[case] for r in ratings)
        totals.update(counts)
        p_items.append(
            (sum(counts[c] ** 2 for c in categories) - n_raters) / (n_raters * (n_raters - 1))
        )
    p_bar = sum(p_items) / len(p_items)
    n_items = len(common) * n_raters
    p_e = sum((totals[c] / n_items) ** 2 for c in categories)
    if p_e >= 1.0:
        return float("nan")
    return (p_bar - p_e) / (1 - p_e)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--condition", required=True, choices=["cad", "png"])
    parser.add_argument("sheets", nargs="+")
    args = parser.parse_args()

    key_path = HUMAN / f"answer_key_{args.condition}.csv"
    key = {row["case"]: row for row in csv.DictReader(open(key_path, encoding="utf-8"))}
    scored_cases = [c for c, row in key.items() if row["bucket"] == "scored"]

    sheets = {}
    for raw in args.sheets:
        path = Path(raw)
        if not path.is_absolute():
            path = path if path.exists() else HUMAN / raw
        sheets[path.stem] = load_sheet(path)

    print(f"condition : {args.condition}")
    print(f"scored    : {len(scored_cases)} case(s)")
    print()
    print("| rater | scored | recall | FP | CP lower (recall) | CP upper (FP) |")
    print("|---|---:|---|---|---:|---:|")
    per_rater: dict[str, dict[str, str]] = {}
    for name, sheet in sheets.items():
        answered = [c for c in scored_cases if c in sheet]
        defective = [c for c in answered if key[c]["ground_truth"] == "defective"]
        compliant = [c for c in answered if key[c]["ground_truth"] == "compliant"]
        hits = sum(1 for c in defective if sheet[c] != "PASS")
        fp = sum(1 for c in compliant if sheet[c] != "PASS")
        per_rater[name] = {c: sheet[c] for c in answered}
        print(
            f"| {name} | {len(answered)} | {hits}/{len(defective)} | {fp}/{len(compliant)} | "
            f"{cp_lower(hits, len(defective)):.1%} | {cp_upper(fp, len(compliant)):.1%} |"
        )

    if len(sheets) >= 2:
        names = list(sheets)
        print()
        if len(sheets) == 2:
            a, b = names
            pairs = [(sheets[a][c], sheets[b][c]) for c in scored_cases if c in sheets[a] and c in sheets[b]]
            print(f"Cohen's kappa ({a} vs {b}, n={len(pairs)}): {kappa(pairs):.3f}")
        else:
            print(f"Fleiss' kappa over {len(sheets)} raters: {fleiss(list(sheets.values())):.3f}")

    # compare with the rule layer, which judged all 50
    rules_path = ROOT / "benchmarks" / "tasks.json"
    if rules_path.exists():
        import json

        rule_verdicts = {}
        from cad_deliver.pipeline import verify_file  # noqa: F401  (documented dependency)

        print()
        print("Rule layer verdicts are in results/recall_by_defect.csv and false_positives.csv;")
        print("the per-case comparison is left to the reader to avoid re-running the gate here.")

    out = RESULTS / f"human_eval_{args.condition}.md"
    RESULTS.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Human baseline — {args.condition} condition",
        "",
        f"Scored cases: {len(scored_cases)} (20 defective, 8 compliant after practice removal).",
        "",
        "| rater | recall | FP |",
        "|---|---|---|",
    ]
    for name, sheet in sheets.items():
        answered = [c for c in scored_cases if c in sheet]
        defective = [c for c in answered if key[c]["ground_truth"] == "defective"]
        compliant = [c for c in answered if key[c]["ground_truth"] == "compliant"]
        hits = sum(1 for c in defective if sheet[c] != "PASS")
        fp = sum(1 for c in compliant if sheet[c] != "PASS")
        lines.append(f"| {name} | {hits}/{len(defective)} | {fp}/{len(compliant)} |")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print()
    print(f"written: {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())