"""Turn collected VLM answers into the same CSV the online mode writes.

Input: `benchmarks/vlm_answers.jsonl`, one JSON object per line, each carrying at
least `image` (or `sample`) and the model's answer object. Anything the model returns
as free text is scanned for the first {...} block, the same way `eval_vlm.py` does.

    python scripts/parse_vlm_results.py
    python scripts/parse_vlm_results.py --answers path/to/answers.jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "benchmarks" / "results"

CHECKS = ("sheet_ok", "layers_ok", "title_block_ok", "closed_ok", "dims_ok")


def extract(record: dict) -> dict:
    """Pull the answer object out of whatever shape the client produced."""
    for key in ("answer", "response", "content", "text"):
        value = record.get(key)
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            start, end = value.find("{"), value.rfind("}")
            if start != -1 and end != -1:
                try:
                    return json.loads(value[start : end + 1])
                except json.JSONDecodeError:
                    continue
    return {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--answers", default=str(ROOT / "benchmarks" / "vlm_answers.jsonl"))
    args = parser.parse_args()

    path = Path(args.answers)
    if not path.is_file():
        print(f"no answers file at {path}")
        print("paste one JSON object per line, each with 'image' and the model reply")
        return 1

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    expected = {}
    mutations = ROOT / "benchmarks" / "mutations.json"
    if mutations.is_file():
        data = json.loads(mutations.read_text(encoding="utf-8"))
        for item in data["records"] if isinstance(data, dict) else data:
            expected[Path(item["path"]).stem] = {
                "group": "mutated",
                "expected_code": item.get("expected_code", ""),
                "should_be_clean": False,
            }

    rows = []
    for record in records:
        sample = record.get("sample") or Path(str(record.get("image", ""))).stem
        answer = extract(record)
        meta = expected.get(sample, {})
        passed = bool(answer) and all(answer.get(k, False) for k in CHECKS)
        rows.append(
            {
                "sample": sample,
                "group": record.get("group", meta.get("group", "")),
                "expected_code": record.get("expected_code", meta.get("expected_code", "")),
                "should_be_clean": record.get("should_be_clean", meta.get("should_be_clean", "")),
                "vlm_rejects": "" if not answer else ("no" if passed else "yes"),
                "vlm_sheet": answer.get("sheet", ""),
                "vlm_finding": answer.get("finding", ""),
                "vlm_confidence": answer.get("confidence", ""),
                "raw": json.dumps(answer, ensure_ascii=False)[:400],
            }
        )

    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / "baseline_vlm.csv"
    with open(out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    scored = [r for r in rows if r["vlm_rejects"]]
    hits = sum(1 for r in scored if not r["should_be_clean"] and r["vlm_rejects"] == "yes")
    fp = sum(1 for r in scored if r["should_be_clean"] and r["vlm_rejects"] == "yes")
    print(f"answers  : {len(rows)}")
    print(f"rejects  : {len(scored)}")
    print(f"recall   : {hits}/{sum(1 for r in rows if r['should_be_clean'] is False)}")
    print(f"false pos: {fp}/{sum(1 for r in rows if r['should_be_clean'] is True)}")
    print(f"written  : {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())