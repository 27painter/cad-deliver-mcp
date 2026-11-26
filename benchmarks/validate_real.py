"""Pre-check the real SolidWorks/NX exports one file at a time.

Drop a `.dxf` into `benchmarks/fixtures/real/` and run this: it judges that file
under `GB_T_TIER1` and, when it does not pass, prints the code, the detail and
the fix. The point is to accept a real drawing the moment it lands rather than
discovering at evaluation time that eleven of fifteen fail for one reason.

Real exports are expected to fail sometimes — a production drawing may genuinely
use a non-ISO sheet or leave a title-block field blank. This script is for
telling "my exporter is wrong" apart from "this drawing really is non-compliant".
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REAL_DIR = ROOT / "fixtures" / "real"

sys.path.insert(0, str(ROOT.parent / "src"))


def main() -> int:
    from cad_deliver.pipeline import verify_file

    files = sorted(REAL_DIR.glob("*.dxf")) if REAL_DIR.is_dir() else []
    if not files:
        print(f"No real exports yet: {REAL_DIR}")
        print("Drop the .dxf files there and run this again. The benchmark falls back to")
        print("the 35-task set (15 generated + 20 mutated) until then.")
        return 0

    passed = 0
    for path in files:
        verdict = verify_file(str(path), "GB_T_TIER1")
        if verdict.verdict.value == "PASS":
            passed += 1
            print(f"  ok   {path.name:32} PASS")
            continue

        print(f"  FAIL {path.name:32} {verdict.verdict.value.upper()}")
        for check in verdict.checks:
            if not check.ok and check.severity in ("error", "blocked"):
                print(f"         check {check.ident}: {check.detail}")
        for rule in verdict.rules:
            if rule.ok:
                continue
            print(f"         {rule.code} [{rule.severity.value}] {rule.detail}")
            if rule.fix:
                print(f"           fix: {rule.fix}")

    total = len(files)
    rate = passed / total if total else 0.0
    print(f"\nreal: {passed}/{total} pass ({rate:.0%})")
    if passed < total:
        print("A failure here is either an exporter problem or a genuine drafting-rule")
        print("violation. Read the fix line: it says which.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())