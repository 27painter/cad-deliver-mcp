"""Full verification output, for the treatment arm of the repair experiment.

This is what an agent actually gets from `cad-deliver-mcp`: every finding with its
code, severity, evidence (coordinates, counts, measured values) and a concrete
fix instruction. The experiment measures whether that extra information changes
how often a model repairs the drawing, and on which attempt.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: verify_full.py <file.dxf>")
        return 64

    from cad_deliver.pipeline import verify_file

    verdict = verify_file(argv[0], "GB_T_TIER1")
    payload = {
        "verdict": verdict.verdict.value,
        "findings": [
            {
                "code": r.code,
                "severity": r.severity.value,
                "detail": r.detail,
                "fix": r.fix,
                "evidence": [{"kind": e.kind, "label": e.label, "value": e.value} for e in r.evidence],
            }
            for r in verdict.rules
            if not r.ok
        ]
        + [
            {"code": c.ident, "severity": c.severity, "detail": c.detail, "fix": None, "evidence": []}
            for c in verdict.checks
            if not c.ok and c.severity in ("error", "blocked")
        ],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if verdict.verdict.value == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))