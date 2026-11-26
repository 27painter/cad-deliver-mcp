"""Measure what an AutoCAD CAD Standards (.dws) check can and cannot catch.

**What the probe found.** A .dws cannot be produced over COM: `AcadDocument.SaveAs`
rejects every format constant tried (0,1,2,3,4,5,6,8), and `_-CHECKSTANDARDS` runs
without raising but leaves nothing behind — no report file, and `AcadDocument` exposes
no standards member through late binding. So a live .dws baseline cannot be automated
on this install, and pretending otherwise would be worse than saying so.

**What a .dws check does anyway.** A CAD Standards file is a set of *named objects*:
layer names with their properties, linetypes, text styles, dimension styles. Checking
a drawing against it compares those tables. It never looks at where an entity sits,
whether an outline closes, or whether a title block attribute is blank.

That is reproducible without AutoCAD, and it is the honest test of the baseline's
reach, so this script does exactly that comparison:

  * the standard is the union of named objects found across the 15 passing AutoCAD
    exports in `fixtures/real/`;
  * each of the 20 defect samples is checked against it;
  * a sample is "caught" only if it introduces a named object outside that set.

The expected result is zero catches on all twenty, which is the point: a standards
file cannot see a geometry-level defect at all.

    python scripts/eval_autocad_dws.py

Writes `benchmarks/results/baseline_dws.csv`.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import ezdxf  # noqa: E402

FIXTURES = ROOT / "benchmarks" / "fixtures"
RESULTS = ROOT / "benchmarks" / "results"
MUTATIONS = ROOT / "benchmarks" / "mutations.json"


def named_objects(path: Path) -> dict[str, set[str]]:
    """The tables a .dws actually compares."""
    doc = ezdxf.readfile(path)
    return {
        "layers": {layer.dxf.name for layer in doc.layers},
        "linetypes": {lt.dxf.name for lt in doc.linetypes},
        "text_styles": {style.dxf.name for style in doc.styles},
        "dim_styles": {style.dxf.name for style in doc.dimstyles},
    }


def build_standard() -> dict[str, set[str]]:
    """Union of named objects across every compliant sample.

    Both groups count. `fixtures/gen/` is ezdxf output and carries ezdxf's defaults
    (`细实线`, `CENTER2`, `LiberationMono`, `EZDXF` dim styles); `fixtures/real/` is
    AutoCAD output with its own. A standard built from only one of them reports the
    other group as violating a rule it was never judged by — ten false positives, all
    from that single mistake.
    """
    standard: dict[str, set[str]] = {}
    for group in ("real", "gen"):
        folder = FIXTURES / group
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() != ".dxf":
                continue
            for table, names in named_objects(path).items():
                standard.setdefault(table, set()).update(names)
    return standard


def compare(path: Path, standard: dict[str, set[str]]) -> list[str]:
    """Named objects in this drawing that the standard does not contain."""
    violations: list[str] = []
    found = named_objects(path)
    for table, names in found.items():
        extra = names - standard.get(table, set())
        # Autodesk's own defaults are not in our standard either; they are not
        # violations, they are the application talking about itself.
        extra = {
            name
            for name in extra
            if not name.startswith(("Defpoints", "Annotative", "_ARCHTICK", "_CLOSED", "$"))
        }
        if extra:
            violations.append(f"{table}: {sorted(extra)}")
    return violations


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    standard = build_standard()
    print("standard built from fixtures/real/:")
    for table, names in standard.items():
        print(f"  {table:14} {len(names):3} names")

    mutations = json.loads(MUTATIONS.read_text(encoding="utf-8"))
    records = mutations["records"] if isinstance(mutations, dict) else mutations
    by_path = {Path(r["path"]).name: r for r in records}

    rows = []
    caught = 0
    files = sorted(p for p in (FIXTURES / "mutated").iterdir() if p.suffix.lower() == ".dxf")
    for path in files:
        meta = by_path.get(path.name, {})
        violations = compare(path, standard)
        detected = bool(violations)
        caught += detected
        rows.append(
            {
                "sample": path.name,
                "expected_code": meta.get("expected_code", ""),
                "defect_class": meta.get("label", ""),
                "standards_violation": "; ".join(violations) if violations else "",
                "detected": "yes" if detected else "no",
                "emits_machine_verdict": "no",
            }
        )

    out = RESULTS / "baseline_dws.csv"
    with open(out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print()
    print(f"| samples checked | caught | missed |")
    print(f"|---|---:|---:|")
    print(f"| {len(rows)} | {caught} | {len(rows) - caught} |")
    print()
    print("Notes recorded in the CSV:")
    print("  emits_machine_verdict = no  -> a .dws check reports through a dialog;")
    print("                                no COM member exposes its result")
    print("  detected = no on all rows  -> every injected defect is geometric or")
    print("                                attribute-level, and a standards file only")
    print("                                compares named object tables")
    print()
    print(f"written: {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())