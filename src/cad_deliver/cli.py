"""Command line entry point.

This module contains no verification logic on purpose. Every judgement comes
from `pipeline.verify_file`, so the CLI and the MCP server cannot drift apart:
there is one definition of "verified" and both call it.

Exit codes:

    0  PASS     every check ran and passed
    1  FAIL     something ran and failed
    2  UNKNOWN  something could not run, so the delivery was not judged

Two meanings share `--profile`, and they are resolved here rather than in the
kernel:

    LEGACY_COMPAT / GB_T_TIER1 / GEOMETRY_ONLY   which standard rules run
    normal / half                                the half-delivery value table

`normal` and `half` are kept because `dsh-sw-cad deliver --profile half` is a
published interface; they select the legacy rule set plus the value-table check,
which is exactly what that command meant before the rule layer existed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

from . import standards
from .core import KIND_BY_EXT
from .models import Verdict
from .pipeline import verify_file
from .rules import available_profiles

# Rules first, then the two delivery modes kept for compatibility.
PROFILE_CHOICES = [
    "LEGACY_COMPAT",
    "GB_T_TIER1",
    "GEOMETRY_ONLY",
    "normal",
    "half",
]
DEFAULT_PROFILE = "LEGACY_COMPAT"
DELIVERY_MODES = {"normal", "half"}

EXIT_CODES = {Verdict.PASS: 0, Verdict.FAIL: 1, Verdict.UNKNOWN: 2}


def resolve_profile(value: str) -> tuple[str, str]:
    """Split the CLI value into (rule profile, delivery mode).

    `normal` / `half` predate the rule layer and mean "legacy rules, with or
    without the value table". Keeping the mapping here means the kernel never
    has to know about a historical spelling.
    """
    if value in DELIVERY_MODES:
        return "LEGACY_COMPAT", value
    if value not in available_profiles():
        raise SystemExit(
            f"unknown profile {value!r}; choose from {', '.join(PROFILE_CHOICES)}"
        )
    return value, "normal"


def classify(path: str) -> str | None:
    name = os.path.basename(path).lower()
    if name.endswith("review_report.json") or name == "review.json":
        return "report"
    return KIND_BY_EXT.get(os.path.splitext(name)[1])


def collect(targets: list[str]) -> list[str]:
    files: list[str] = []
    for target in targets:
        if os.path.isdir(target):
            for root, _dirs, names in os.walk(target):
                for name in names:
                    files.append(os.path.join(root, name))
        elif os.path.isfile(target):
            files.append(target)
        else:
            raise SystemExit(f"nothing at {target}")
    return sorted(set(files))


def build_report(
    verdicts,
    profile_value: str,
    rule_profile: str,
    delivery_mode: str,
    targets: list[str],
    required: list[str],
) -> dict:
    """Assemble the delivery.json shape dsh-sw-cad 2.2.0 produced, plus rules.

    The legacy keys keep their names and meanings (`failures` is still the count
    of error-severity findings, `blocked` still the count of checks that could
    not run) because reports already saved elsewhere must stay readable.
    """
    failures = sum(len(v.errors) for v in verdicts)
    warnings = sum(len(v.warnings) for v in verdicts)
    blocked = sum(len(v.blocked) for v in verdicts)

    present = {v.kind for v in verdicts if v.kind != "other"}
    missing = [kind for kind in required if kind not in present]
    failures += len(missing)

    empty = not any(v.kind != "other" for v in verdicts)
    if empty:
        # A job that produced nothing must never report success.
        failures += 1

    crashed = [v for v in verdicts if v.crashed]
    if failures or crashed:
        verdict = Verdict.FAIL
    elif blocked:
        verdict = Verdict.UNKNOWN
    else:
        verdict = Verdict.PASS

    rules = []
    for file_verdict in verdicts:
        for result in file_verdict.rules:
            entry = result.as_dict()
            entry["file"] = os.path.basename(file_verdict.path)
            rules.append(entry)

    not_checked = (
        ["审签（设计/校对/审核/批准）", "尺寸链闭合", "零件可加工性"]
        if delivery_mode == "half"
        else []
    )

    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "profile": profile_value,
        "rule_profile": rule_profile,
        "delivery_mode": delivery_mode,
        "targets": [os.path.abspath(t) for t in targets],
        "verdict": verdict.value.lower(),
        "required": required,
        "missing": missing,
        "not_checked": not_checked,
        "counts": {
            "files": len(verdicts),
            "checked": sum(1 for v in verdicts if v.kind != "other"),
            "failures": failures,
            "warnings": warnings,
            "blocked": blocked,
        },
        "blocked": [
            {"path": v.path, "id": check.ident, "detail": check.detail}
            for v in verdicts
            for check in v.checks
            if not check.ok and check.severity == "blocked"
        ],
        "rules": rules,
        "files": [
            {
                "path": v.path,
                "kind": v.kind,
                "bytes": v.bytes,
                "sha256": v.sha256,
                "checks": [c.as_dict() for c in v.checks],
            }
            for v in verdicts
        ],
    }


def _print_report(report: dict, verdicts, quiet: bool) -> None:
    if quiet:
        pass
    else:
        for file_verdict in verdicts:
            if file_verdict.kind == "other":
                continue
            print(f"{file_verdict.kind:<8} {os.path.basename(file_verdict.path)}  {file_verdict.bytes} B")
            for check in file_verdict.checks:
                mark = "ok  "
                if not check.ok:
                    mark = {"warning": "warn", "blocked": "BLOCK"}.get(check.severity, "FAIL")
                print(f"  {mark} {check.ident:<22} {check.detail}")
            for result in file_verdict.rules:
                mark = "ok  " if result.ok else result.severity.value.upper()
                print(f"  {mark} {result.code:<22} {result.detail}")

        if report["missing"]:
            print(f"\nmissing: {', '.join(report['missing'])}")

    # The profile line is always printed, including for `normal`: it is part of
    # the output dsh-sw-cad already emits, and dropping it would break anything
    # that greps the verdict block.
    profile_line = f"profile: {report['delivery_mode']}"
    if report["delivery_mode"] == "half":
        profile_line += (
            "  (values must come from lib/standards.json; 审签 and 尺寸链 still need a human)"
        )
    print(profile_line)
    counts = report["counts"]
    print(
        f"verdict: {report['verdict']}  ({counts['failures']} failure(s), "
        f"{counts['warnings']} warning(s), {counts['blocked']} not checked)  -> {report['_out']}"
    )
    if report["verdict"] == "unknown":
        print(
            "unknown is not a pass: a reader this check needs was missing, so part of the "
            "delivery was never examined. Install the dependency (or run deliver with the venv "
            "interpreter) and judge again."
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check a CAD delivery and write the evidence.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "profiles:\n"
            "  LEGACY_COMPAT  default; file checks only, no standard rules\n"
            "  GB_T_TIER1     adds GB/T 14689 sheet, layer taxonomy and title block\n"
            "  GEOMETRY_ONLY  generic geometry checks, no standard\n"
            "  normal / half  legacy spelling: LEGACY_COMPAT with or without the value table\n"
            "\n"
            "exit codes: 0 pass, 1 fail, 2 could not judge (never a pass)\n"
        ),
    )
    parser.add_argument("targets", nargs="+", help="folder(s) or file(s) to check")
    parser.add_argument(
        "--profile",
        default=DEFAULT_PROFILE,
        choices=PROFILE_CHOICES,
        help=f"which rule set to run (default: {DEFAULT_PROFILE})",
    )
    parser.add_argument("--out", default="delivery.json", help="where to write the report")
    parser.add_argument(
        "--require",
        default="",
        help="comma-separated kinds that must be present, e.g. drawing,pdf or step",
    )
    parser.add_argument("--json", action="store_true", help="print the report to stdout as well")
    parser.add_argument("--quiet", action="store_true", help="only the verdict line")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    rule_profile, delivery_mode = resolve_profile(args.profile)
    # The half-delivery value table is consulted by the geometry layer, not by
    # the rules, so it is set once here before any file is verified.
    standards.PROFILE = delivery_mode

    files = collect(args.targets)
    verdicts = [verify_file(path, rule_profile) for path in files]

    required = [item.strip() for item in args.require.split(",") if item.strip()]
    report = build_report(
        verdicts,
        profile_value=args.profile,
        rule_profile=rule_profile,
        delivery_mode=delivery_mode,
        targets=args.targets,
        required=required,
    )

    out = args.out if os.path.isabs(args.out) else os.path.abspath(args.out)
    report["_out"] = out
    with open(out, "w", encoding="utf-8", newline="\n") as handle:
        payload = {k: v for k, v in report.items() if k != "_out"}
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    _print_report(report, verdicts, args.quiet)
    if args.json:
        print(json.dumps({k: v for k, v in report.items() if k != "_out"}, indent=2, ensure_ascii=False))

    return EXIT_CODES[Verdict(report["verdict"].upper())]


if __name__ == "__main__":
    raise SystemExit(main())