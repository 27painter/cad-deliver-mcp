"""The verification kernel: one path in, one structured verdict out.

Both entry points sit on top of this — the MCP server now, the CLI after phase 3
— so the two can never disagree about what "verified" means. Nothing here writes
files: verification is a read of what is already on disk.

Three verdicts, and the third is the one that matters:

    PASS     every check ran and passed
    FAIL     something ran and failed
    UNKNOWN  something could not run (no reader), so the delivery was not judged

UNKNOWN is not a soft PASS. A skipped check must never be reported as a success,
because the caller stops looking at "PASS".
"""

from __future__ import annotations

import os
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from .core import KIND_BY_EXT, MIN_BYTES, sha256
from .geometry import dxf_checks, model_checks, pdf_checks, review_checks, step_checks, topology
from .models import Check, ParsedDrawing, Severity, Verdict
from .parsers import dxf as dxf_parser
from .parsers import pdf as pdf_parser
from .rules import DEFAULT_PROFILE, RuleResult, run_profile


def classify(path: str) -> str | None:
    name = os.path.basename(path).lower()
    if name.endswith("review_report.json") or name == "review.json":
        return "report"
    return KIND_BY_EXT.get(os.path.splitext(name)[1])


# A failure without an action is a complaint. The rule layer carries its own
# `fix` on every RuleResult; the geometry layer was written before that idea, so
# its check ids get a hint here rather than being left as "something is wrong".
FIX_HINTS: dict[str, str] = {
    "file.size": "the file is too small to be the artefact it claims to be; re-export it",
    "dxf.parsed": "install ezdxf, or run deliver with the interpreter that has it",
    "drawing.entities": "the drawing has no geometry in model space; re-export the drawing",
    "drawing.dimensions": "add real DIMENSION entities — text plus a leader is not a dimension",
    "drawing.units": "set $INSUNITS to the drawing unit (4 = mm) before saving",
    "drawing.sheets": "put the view and a title block on a paper-space layout",
    "drawing.sheet": "set the layout paper to an ISO 216 sheet (A4–A0)",
    "drawing.scale": "write 比例 1:x on the sheet, or set the plot scale",
    "drawing.titleblock": "insert a title block on the sheet",
    "drawing.lineweights": "give the outline and the thin lines different layer lineweights",
    "drawing.fonts": "point the text style at a CJK font (仿宋/宋体) before plotting",
    "drawing.dim_overlap": "move dimension texts apart — overlapping values cannot be read",
    "drawing.dim_values": "fix the dimension text, or fix the geometry it annotates, so the two agree",
    "step.schema": "re-export as AP214 or AP242",
    "step.entities": "the export carries almost no geometry; re-export the solid",
    "step.bbox": "the exported points have no extent; the part may have been scaled or empty",
    "pdf.parsed": "install pymupdf, or run deliver with the interpreter that has it",
    "pdf.pages": "the PDF has no pages; re-plot the drawing",
    "review.status": "re-run the review until it passes, or read its issues",
    "review.issues": "resolve the issues the review reported",
    "review.checks": "produce the review report with its checks block, not just a verdict",
    "review.previews": "export the preview views and confirm they are not blank",
    "review.outputs": "confirm the expected output files were actually written",
    "review.previews_on_disk": "keep the preview images next to the review report",
}


def fix_for(check: Check) -> str | None:
    if check.ok:
        return None
    return FIX_HINTS.get(check.ident)


# Rules whose abstention leaves a compliance dimension unverified. A file that on
# one of these says "does not apply" cannot be called compliant — only "not shown
# to be wrong", which is the UNKNOWN verdict.
CRITICAL_RULES = frozenset(
    {
        "gb.title_block",
        "gb.sheet_size",
        "gb.layer_taxonomy",
        "gb.closed_profile",
    }
)


@dataclass
class FileVerdict:
    path: str
    kind: str
    bytes: int
    sha256: str
    checks: list[Check] = field(default_factory=list)
    rules: list[RuleResult] = field(default_factory=list)
    drawing: ParsedDrawing | None = None
    crashed: str | None = None

    # -------------------------------------------------------------- verdict

    @property
    def not_applicable(self) -> list:
        """Rules that stepped aside because their precondition did not hold."""
        return [r for r in self.rules if not r.applicable]

    @property
    def errors(self) -> list:
        bad = [c for c in self.checks if not c.ok and c.severity == Severity.ERROR.value]
        bad += [r for r in self.rules if not r.ok and r.severity is Severity.ERROR and r.applicable]
        return bad

    @property
    def blocked(self) -> list:
        bad = [c for c in self.checks if not c.ok and c.severity == Severity.BLOCKED.value]
        bad += [r for r in self.rules if not r.ok and r.severity is Severity.BLOCKED and r.applicable]
        return bad

    @property
    def warnings(self) -> list:
        bad = [c for c in self.checks if not c.ok and c.severity == Severity.WARNING.value]
        bad += [r for r in self.rules if not r.ok and r.severity is Severity.WARNING and r.applicable]
        return bad

    @property
    def verdict(self) -> Verdict:
        if self.crashed:
            return Verdict.FAIL
        if self.errors:
            return Verdict.FAIL
        if self.blocked:
            return Verdict.UNKNOWN
        # A pass means the checks that matter were run and came back clean. When a
        # rule stepped aside, that dimension of compliance was not verified at all —
        # and for the dimensions below, unverified is not the same as compliant: a
        # drawing with no sheet format and one layer has "no title block problem"
        # only in the sense that nobody looked.
        skipped = [r for r in self.rules if not r.applicable]
        if any(r.rule_id in CRITICAL_RULES for r in skipped):
            return Verdict.UNKNOWN
        if self.rules and all(not r.applicable for r in self.rules):
            return Verdict.UNKNOWN
        return Verdict.PASS

    def fixes(self) -> list[str]:
        """Concrete actions, most blocking first. Not "please check"."""
        blocking = [
            fix_for(c) for c in self.checks if not c.ok and c.severity == Severity.ERROR.value
        ]
        out = [fix for fix in blocking if fix]
        out += [r.fix for r in self.rules if not r.ok and r.fix and r.applicable]
        # Keep the order, drop duplicates: two failures often share one action.
        seen: set[str] = set()
        unique = []
        for fix in out:
            if fix not in seen:
                seen.add(fix)
                unique.append(fix)
        return unique

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "kind": self.kind,
            "bytes": self.bytes,
            "sha256": self.sha256,
            "verdict": self.verdict.value,
            "checks": [c.as_dict() for c in self.checks],
            "rules": [r.as_dict() for r in self.rules],
            "counts": {
                "errors": len(self.errors),
                "warnings": len(self.warnings),
                "blocked": len(self.blocked),
            },
            "fixes": self.fixes(),
            "crashed": self.crashed,
        }


@dataclass
class DeliveryVerdict:
    verdict: Verdict
    profile: str
    files: list[FileVerdict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def counts(self) -> dict:
        return {
            "files": len(self.files),
            "errors": sum(len(f.errors) for f in self.files),
            "warnings": sum(len(f.warnings) for f in self.files),
            "blocked": sum(len(f.blocked) for f in self.files),
        }

    def as_dict(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "profile": self.profile,
            "counts": self.counts,
            "files": [f.as_dict() for f in self.files],
            "fixes": [fix for f in self.files for fix in f.fixes()],
            "notes": self.notes,
        }


# ---------------------------------------------------------------- one file


def verify_file(path: str | os.PathLike, profile: str = DEFAULT_PROFILE) -> FileVerdict:
    """Read one file and judge it. Never raises: a crash becomes a failed check."""
    path = str(path)
    kind = classify(path) or "other"
    size = os.path.getsize(path)
    verdict = FileVerdict(path=os.path.abspath(path), kind=kind, bytes=size, sha256=sha256(path))

    if kind == "other":
        return verdict

    minimum = MIN_BYTES.get(kind, 1)
    verdict.checks.append(
        Check("file.size", size >= minimum, f"{size} bytes (minimum {minimum})")
    )

    try:
        drawing: ParsedDrawing | None = None
        if kind == "drawing":
            outcome = dxf_parser.parse(path)
            verdict.checks.extend(outcome.checks)
            drawing = outcome.drawing
            if drawing is not None:
                verdict.checks.extend(dxf_checks.check_drawing(drawing))
        elif kind == "pdf":
            outcome = pdf_parser.parse(path)
            verdict.checks.extend(outcome.checks)
            drawing = outcome.drawing
            if drawing is not None:
                verdict.checks.extend(pdf_checks.check_pdf(drawing))
        elif kind == "step":
            verdict.checks.extend(step_checks.check_step(path, size))
        elif kind == "model":
            verdict.checks.extend(model_checks.check_model(path, size))
        elif kind == "report":
            verdict.checks.extend(review_checks.check_review_report(path, size))

        verdict.drawing = drawing

        # Closure is analysed once, here, and written back onto the drawing so
        # the rule layer reads a fact instead of recomputing the same graph.
        if drawing is not None:
            outline = topology.analyse(drawing)
            drawing.open_profiles = outline.open
            drawing.closed_profiles = outline.closed

        # Standard rules only make sense on a parsed drawing. A STEP header has
        # no layers or title block to classify.
        if drawing is not None:
            verdict.rules.extend(run_profile(drawing, profile))
    except Exception:
        verdict.crashed = traceback.format_exc(limit=2).strip().splitlines()[-1]

    return verdict


# ---------------------------------------------------------------- many files


def verify_paths(paths: list[str] | list[os.PathLike], profile: str = DEFAULT_PROFILE) -> DeliveryVerdict:
    files = [verify_file(path, profile) for path in paths]
    notes: list[str] = []

    if not files:
        notes.append("no file was verified: the delivery is empty")

    errors = sum(len(f.errors) for f in files)
    blocked = sum(len(f.blocked) for f in files)
    crashed = [f for f in files if f.crashed]

    if errors or crashed:
        verdict = Verdict.FAIL
    elif blocked or not files:
        verdict = Verdict.UNKNOWN
    else:
        verdict = Verdict.PASS

    return DeliveryVerdict(verdict=verdict, profile=profile, files=files, notes=notes)


def verdict_from(checks: list[Check], rules: list[RuleResult] | None = None) -> Verdict:
    """Shared rule for turning findings into a three-state answer."""
    rules = rules or []
    if any((not c.ok and c.severity == Severity.ERROR.value) for c in checks):
        return Verdict.FAIL
    if any((not r.ok and r.severity is Severity.ERROR) for r in rules):
        return Verdict.FAIL
    if any((not c.ok and c.severity == Severity.BLOCKED.value) for c in checks):
        return Verdict.UNKNOWN
    if any((not r.ok and r.severity is Severity.BLOCKED) for r in rules):
        return Verdict.UNKNOWN
    # Nothing was verified when every rule stepped aside; see FileVerdict.verdict.
    if rules and all(not r.applicable for r in rules):
        return Verdict.UNKNOWN
    return Verdict.PASS