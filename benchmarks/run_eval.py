"""Four-arm evaluation over the benchmark set, and the three result tables.

    G1    no gate: always PASS
    G2    file exists and is non-empty
    G2.5  ezdxf opens it, model space has entities, $INSUNITS != 0
    G3    this package, profile GB_T_TIER1

G2.5 is the arm that matters. Comparing only against G1 and G2 invites the
objection that the baseline was never credible; G2.5 is what a competent
engineer would write in an afternoon without a rule layer.

Scale is dynamic. With `fixtures/real/` empty the set is 35 tasks (15 generated
+ 20 mutated). Drop 15 real exports in and the same command evaluates 50 (30
compliant + 20 mutated) with no other change.

Outputs, all written to `results/`:

    recall_by_defect.csv    per class, per layer, and overall, for all four arms
    false_positives.csv     false positives on compliant samples, with an exact
                            Clopper-Pearson 95% one-sided upper bound
    latency.csv             per-call p50 and p95 in milliseconds
    tasks.json              the manifest every number above refers to

The upper bound is computed here rather than by scipy: `math.comb` and a
bisection on the binomial CDF is exact for these n, and it keeps the evaluation
reproducible on a machine with nothing installed.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"
RESULTS = ROOT / "results"

sys.path.insert(0, str(ROOT.parent / "src"))

PROFILE = "GB_T_TIER1"
ARMS = ("G1", "G2", "G2.5", "G3")


# ------------------------------------------------------------------ statistics

def clopper_pearson_upper(k: int, n: int, alpha: float = 0.05) -> float:
    """One-sided upper bound on the true rate, given k events in n trials.

    Solved from P(X <= k | p) = alpha by bisection on the binomial CDF. With
    k = 0 and n = 30 this returns 0.0951 — the number a reviewer expects to see
    instead of a bare "0%". Pure Python, so the figure can be reproduced without
    scipy.
    """
    if n <= 0:
        return 1.0
    if k >= n:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        cdf = sum(math.comb(n, i) * mid**i * (1.0 - mid) ** (n - i) for i in range(k + 1))
        if cdf > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return ordered[int(pos)]
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


# ------------------------------------------------------------------ the arms

def arm_g1(path: Path) -> str:
    return "PASS"


def arm_g2(path: Path) -> str:
    try:
        return "PASS" if path.is_file() and path.stat().st_size > 0 else "FAIL"
    except OSError:
        return "FAIL"


def arm_g2_5(path: Path) -> str:
    """Static syntax: opens, has entities, declares a unit."""
    try:
        import ezdxf

        doc = ezdxf.readfile(str(path))
        msp = doc.modelspace()
        if len(list(msp)) == 0:
            return "FAIL"
        if doc.header.get("$INSUNITS", 0) == 0:
            return "FAIL"
        return "PASS"
    except Exception:
        return "FAIL"


def arm_g3(path: Path) -> str:
    from cad_deliver.pipeline import verify_file

    return verify_file(str(path), PROFILE).verdict.value


ARMS_IMPL = {"G1": arm_g1, "G2": arm_g2, "G2.5": arm_g2_5, "G3": arm_g3}


def arm_legacy(path: Path) -> str:
    """G2.5 plus the compatible profile: what dsh-sw-cad 2.2.0 would have said."""
    from cad_deliver.pipeline import verify_file

    return verify_file(path, "LEGACY_COMPAT").verdict.value


# ------------------------------------------------------------------ the tasks

DEFECT_LABELS = {
    "E_BBOX_DEGENERATE": "degenerate bbox",
    "E_PROFILE_OPEN": "open profile",
    "E_SHEET_SIZE": "non-standard sheet",
    "E_TITLE_BLOCK": "missing title block",
    "E_TITLE_BLOCK_BLANK": "blank title block field",
    "E_DIM_ON_WRONG_LAYER": "dimension on wrong layer",
    "E_CONTOUR_ON_ZERO": "outline on layer 0",
}


def defect_class(expected: str) -> str:
    """Group the two title-block codes into one class for reporting."""
    if expected in ("E_TITLE_BLOCK", "E_TITLE_BLOCK_BLANK"):
        return "missing title block"
    return DEFECT_LABELS.get(expected, expected)


def build_tasks() -> dict:
    tasks: list[dict] = []

    gen = sorted((FIXTURES / "gen").glob("*.dxf")) if (FIXTURES / "gen").is_dir() else []
    real = sorted((FIXTURES / "real").glob("*.dxf")) if (FIXTURES / "real").is_dir() else []
    mutated = sorted((FIXTURES / "mutated").glob("*.dxf")) if (FIXTURES / "mutated").is_dir() else []

    for path in gen:
        tasks.append(
            {
                "name": path.stem,
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "kind": "compliant",
                "group": "gen",
                "defect_class": "",
                "expected_code": "",
                "expected_layer": "",
            }
        )

    for path in real:
        tasks.append(
            {
                "name": path.stem,
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "kind": "compliant",
                "group": "real",
                "defect_class": "",
                "expected_code": "",
                "expected_layer": "",
            }
        )

    manifest = {}
    manifest_path = ROOT / "mutations.json"
    if manifest_path.is_file():
        manifest = {item["name"]: item for item in json.loads(manifest_path.read_text(encoding="utf-8"))}

    for path in mutated:
        meta = manifest.get(path.stem, {})
        expected = meta.get("expected_code", "")
        tasks.append(
            {
                "name": path.stem,
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "kind": "defective",
                "group": "mutated",
                "defect_class": defect_class(expected),
                "expected_code": expected,
                "expected_layer": meta.get("expected_layer", ""),
            }
        )

    return {
        "profile": PROFILE,
        "scale": {
            "real": len(real),
            "generated": len(gen),
            "mutated": len(mutated),
            "compliant": len(gen) + len(real),
            "total": len(tasks),
            "complete_50": len(real) >= 15,
        },
        "tasks": tasks,
    }


# ------------------------------------------------------------------ the run

def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    plan = build_tasks()
    tasks = plan["tasks"]

    if not tasks:
        print("no fixtures found; run generate_fixtures.py then mutate.py")
        return 1

    (ROOT / "tasks.json").write_text(
        json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    scale = plan["scale"]
    print(f"tasks: {scale['total']}  "
          f"(compliant {scale['compliant']} = gen {scale['generated']} + real {scale['real']}, "
          f"mutated {scale['mutated']})")
    if not scale["complete_50"]:
        print("note : fixtures/real/ holds fewer than 15 exports, so this is the 35-task run")
        print("       drop real DXFs in and re-run for the full 50-task set")

    # verdicts[arm][task name], plus latency and the legacy comparison
    verdicts: dict[str, dict[str, str]] = {arm: {} for arm in ARMS}
    latency: dict[str, list[float]] = {arm: [] for arm in (*ARMS, "LEGACY_COMPAT")}
    legacy: dict[str, str] = {}
    # The codes G3 actually emitted, so "did it name the defect we injected"
    # can be answered without re-running the gate.
    g3_codes: dict[str, list[str]] = {}

    from cad_deliver.pipeline import verify_file

    for task in tasks:
        path = ROOT / task["path"]
        for arm in ARMS:
            started = time.perf_counter()
            if arm == "G3":
                verdict = verify_file(path, PROFILE)
                verdicts["G3"][task["name"]] = verdict.verdict.value
                g3_codes[task["name"]] = [r.code for r in verdict.rules if not r.ok]
            else:
                verdicts[arm][task["name"]] = ARMS_IMPL[arm](path)
            latency[arm].append((time.perf_counter() - started) * 1000.0)
        started = time.perf_counter()
        legacy[task["name"]] = verify_file(path, "LEGACY_COMPAT").verdict.value
        latency["LEGACY_COMPAT"].append((time.perf_counter() - started) * 1000.0)

    # ---- recall by defect ------------------------------------------
    classes: dict[tuple[str, str], list[dict]] = {}
    for task in tasks:
        if task["kind"] != "defective":
            continue
        key = (task["defect_class"], task["expected_layer"])
        classes.setdefault(key, []).append(task)

    recall_rows = []
    for (klass, layer), items in sorted(classes.items()):
        row = {"defect_class": klass, "layer": layer, "n": len(items)}
        for arm in (*ARMS, "LEGACY_COMPAT"):
            source = legacy if arm == "LEGACY_COMPAT" else verdicts[arm]
            hits = sum(1 for item in items if source[item["name"]] != "PASS")
            row[f"{arm}_hits"] = hits
            row[f"{arm}_recall"] = round(hits / len(items), 4)
        exact = sum(1 for item in items if item["expected_code"] in g3_codes.get(item["name"], []))
        row["G3_exact"] = exact
        recall_rows.append(row)

    # per-layer summary and overall
    for layer in ("geometry", "standard"):
        items = [t for t in tasks if t["kind"] == "defective" and t["expected_layer"] == layer]
        if not items:
            continue
        row = {"defect_class": f"ALL ({layer})", "layer": layer, "n": len(items)}
        for arm in (*ARMS, "LEGACY_COMPAT"):
            source = legacy if arm == "LEGACY_COMPAT" else verdicts[arm]
            hits = sum(1 for item in items if source[item["name"]] != "PASS")
            row[f"{arm}_hits"] = hits
            row[f"{arm}_recall"] = round(hits / len(items), 4)
        row["G3_exact"] = ""
        recall_rows.append(row)

    defective = [t for t in tasks if t["kind"] == "defective"]
    overall = {"defect_class": "ALL", "layer": "both", "n": len(defective)}
    for arm in (*ARMS, "LEGACY_COMPAT"):
        source = legacy if arm == "LEGACY_COMPAT" else verdicts[arm]
        hits = sum(1 for t in defective if source[t["name"]] != "PASS")
        overall[f"{arm}_hits"] = hits
        overall[f"{arm}_recall"] = round(hits / len(defective), 4) if defective else 0.0
    overall["G3_exact"] = ""
    recall_rows.append(overall)

    fields = ["defect_class", "layer", "n"] + [
        f"{arm}_{suffix}" for arm in (*ARMS, "LEGACY_COMPAT") for suffix in ("hits", "recall")
    ] + ["G3_exact"]
    with open(RESULTS / "recall_by_defect.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(recall_rows)

    # ---- false positives -------------------------------------------
    compliant = [t for t in tasks if t["kind"] == "compliant"]
    n_compliant = len(compliant)
    fp_rows = []
    for arm in ARMS:
        fp = sum(1 for t in compliant if verdicts[arm][t["name"]] != "PASS")
        upper = clopper_pearson_upper(fp, n_compliant)
        fp_rows.append(
            {
                "arm": arm,
                "n_compliant": n_compliant,
                "false_positives": fp,
                "fp_rate": round(fp / n_compliant, 4) if n_compliant else 0.0,
                "cp_upper95": round(upper, 4),
            }
        )
    legacy_fp = sum(1 for t in compliant if legacy[t["name"]] != "PASS")
    fp_rows.append(
        {
            "arm": "LEGACY_COMPAT",
            "n_compliant": n_compliant,
            "false_positives": legacy_fp,
            "fp_rate": round(legacy_fp / n_compliant, 4) if n_compliant else 0.0,
            "cp_upper95": round(clopper_pearson_upper(legacy_fp, n_compliant), 4),
        }
    )
    with open(RESULTS / "false_positives.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["arm", "n_compliant", "false_positives", "fp_rate", "cp_upper95"],
        )
        writer.writeheader()
        writer.writerows(fp_rows)

    # ---- latency ----------------------------------------------------
    lat_rows = []
    for arm in ARMS + ("LEGACY_COMPAT",):
        samples = latency.get(arm, [])
        lat_rows.append(
            {
                "arm": arm,
                "n": len(samples),
                "p50_ms": round(percentile(samples, 0.50), 3),
                "p95_ms": round(percentile(samples, 0.95), 3),
                "mean_ms": round(statistics.fmean(samples), 3) if samples else 0.0,
            }
        )
    with open(RESULTS / "latency.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["arm", "n", "p50_ms", "p95_ms", "mean_ms"])
        writer.writeheader()
        writer.writerows(lat_rows)

    # ---- console summary -------------------------------------------
    print()
    print("## Recall by defect class")
    print()
    print("| defect class | layer | n | G1 | G2 | G2.5 | G3 | LEGACY |")
    print("|---|---|---:|---:|---:|---:|---:|---:|")
    for row in recall_rows:
        print(
            f"| {row['defect_class']} | {row['layer']} | {row['n']} | "
            + " | ".join(f"{row[f'{arm}_hits']}/{row['n']}" for arm in (*ARMS, "LEGACY_COMPAT"))
            + " |"
        )

    print()
    print("## False positives on compliant samples")
    print()
    print("| arm | n | FP | rate | CP 95% upper |")
    print("|---|---:|---:|---:|---:|")
    for row in fp_rows:
        print(
            f"| {row['arm']} | {row['n_compliant']} | {row['false_positives']} | "
            f"{row['fp_rate']:.1%} | {row['cp_upper95']:.1%} |"
        )

    print()
    print("## Latency per call (ms)")
    print()
    print("| arm | n | p50 | p95 |")
    print("|---|---:|---:|---:|")
    for row in lat_rows:
        print(f"| {row['arm']} | {row['n']} | {row['p50_ms']:.3f} | {row['p95_ms']:.3f} |")

    print()
    print(f"results: {RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())