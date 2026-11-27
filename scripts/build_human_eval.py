"""Build the human-evaluation kit: anonymised cases, score sheet, protocol.

Two conditions, because they answer different questions:

  * **CAD condition** — the reviewer opens the DXF in their own CAD software, exactly as
    they work. This measures the human ceiling, including everything a person can check
    that a picture cannot (layer names, entity properties, sheet size).
  * **PNG condition** — the reviewer sees only the rendered image, which is what the
    vision model saw. This is the like-for-like comparison with §16.

Filenames carry no hint of the defect: `mut_01_bbox_point.dxf` announces its own answer,
so every case is renamed and the order is shuffled with a fixed seed.

Samples: all 20 defective + 10 randomly chosen compliant (stratified, not the full 30,
to keep the session under an hour), plus 4 practice cases at the front that are excluded
from scoring.
"""

from __future__ import annotations

import csv
import json
import random
import shutil
from pathlib import Path

ROOT = Path(r"D:\dsh_plugins\cad-deliver-mcp")
FIXTURES = ROOT / "benchmarks" / "fixtures"
RENDERS = ROOT / "benchmarks" / "renders"
OUT = ROOT / "benchmarks" / "human_eval"
SEED = 20261127
PRACTICE = 4
COMPLIANT_SAMPLE = 10
CONDITION = "cad"  # 'cad' or 'png'


def main() -> int:
    folder = OUT / CONDITION
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)

    mutations = json.loads((ROOT / "benchmarks" / "mutations.json").read_text(encoding="utf-8"))
    records = mutations["records"] if isinstance(mutations, dict) else mutations
    by_stem = {Path(r["path"]).stem: r for r in records}

    defective = sorted(by_stem)
    compliant = sorted(
        p.stem
        for group in ("real", "gen")
        for p in (FIXTURES / group).iterdir()
        if p.suffix.lower() == ".dxf"
    )
    rng = random.Random(SEED)
    compliant_pick = sorted(rng.sample(compliant, COMPLIANT_SAMPLE))

    # practice cases: 2 defective + 2 compliant, drawn from outside the scored set
    practice_defective = rng.sample(defective[2:], 2)
    practice_compliant = [c for c in compliant if c not in compliant_pick]
    practice = practice_defective + rng.sample(practice_compliant, 2)

    scored = [(s, "defective") for s in defective if s not in practice] + [
        (s, "compliant") for s in compliant_pick
    ]
    rng.shuffle(scored)

    answer_key = []
    practice_kind = {s: ("defective" if s in practice_defective else "compliant") for s in practice}
    order = [("practice", s, practice_kind[s]) for s in practice] + [
        ("scored", s, k) for s, k in scored
    ]
    for index, (bucket, stem, kind) in enumerate(order, start=1):
        case = f"CASE-{index:02d}"
        if CONDITION == "cad":
            source = next(FIXTURES.rglob(stem + ".dxf"), None)
            if source is None:
                source = next(FIXTURES.rglob(stem + ".DXF"), None)
            target = folder / f"{case}.dxf"
        else:
            source = next(RENDERS.rglob(stem + ".png"), None)
            target = folder / f"{case}.png"
        if source is None:
            print(f"  missing: {stem}")
            continue
        shutil.copy2(source, target)

        meta = by_stem.get(stem, {})
        answer_key.append(
            {
                "case": case,
                "bucket": bucket,
                "source_file": source.name,
                "ground_truth": kind,
                "expected_code": meta.get("expected_code", ""),
                "defect_class": meta.get("label", ""),
            }
        )
        print(f"  {case}  {'(practice)' if bucket == 'practice' else '           '}")

    with open(OUT / f"answer_key_{CONDITION}.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(answer_key[0].keys()))
        writer.writeheader()
        writer.writerows(answer_key)

    # score sheet: one row per case, reviewer fills the last four columns
    sheet = [
        {
            "case": row["case"],
            "practice": "yes" if row["bucket"] == "practice" else "",
            "verdict": "",
            "suspected_code": "",
            "confidence": "",
            "note": "",
        }
        for row in answer_key
    ]
    with open(OUT / f"score_sheet_{CONDITION}.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(sheet[0].keys()))
        writer.writeheader()
        writer.writerows(sheet)

    print()
    print(f"condition : {CONDITION}")
    print(f"cases     : {len(answer_key)} ({PRACTICE} practice + {len(answer_key) - PRACTICE} scored)")
    print(f"written   : {folder.relative_to(ROOT)}")
    print(f"answer key: answer_key_{CONDITION}.csv  (do not show the reviewer)")
    print(f"sheet     : score_sheet_{CONDITION}.csv  (one row per case)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())