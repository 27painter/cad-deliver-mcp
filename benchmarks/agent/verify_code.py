"""Code-only view of a verification, for the control arm of the repair experiment.

The experiment compares a model that is told *what* failed against one that is
told what failed *and* where and how to fix it. The control arm must therefore be
unable to see the detail — otherwise the two arms collapse into one.

This prints the machine codes and nothing else: no detail text, no evidence, no
coordinates, no fix. It is the honest version of "you get the error name".
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: verify_code.py <file.dxf>")
        return 64

    from cad_deliver.pipeline import verify_file

    verdict = verify_file(argv[0], "GB_T_TIER1")
    codes = [c.ident for c in verdict.checks if not c.ok and c.severity == "error"]
    codes += [c.ident for c in verdict.checks if not c.ok and c.severity == "blocked"]
    codes += [r.code for r in verdict.rules if not r.ok]

    if verdict.verdict.value == "PASS":
        print("PASS")
        return 0
    if not codes:
        print(f"{verdict.verdict.value} (no code available)")
        return 1
    print(f"{verdict.verdict.value}: " + ", ".join(dict.fromkeys(codes)))
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))