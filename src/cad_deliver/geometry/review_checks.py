"""Part of cad-deliver-mcp. Moved from dsh-sw-cad/lib/deliver.py."""

from __future__ import annotations

import json
import os

from ..models import Check


def check_review_report(path, size):
    checks = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            report = json.load(handle)
    except Exception as exc:
        checks.append(Check("review.parsed", False, f"not valid JSON: {exc}"))
        return checks

    evaluation = report.get("evaluation") or {}
    status = evaluation.get("status") or report.get("status")
    checks.append(
        Check(
            "review.status",
            str(status).lower() == "pass",
            f"evaluation.status={status!r}",
        )
    )
    issues = evaluation.get("issues") or []
    checks.append(
        Check(
            "review.issues",
            len(issues) == 0,
            f"{len(issues)} issue(s)" + (f": {issues[:3]}" if issues else ""),
        )
    )

    # `evaluation.status` is written by the model that did the work. On its own
    # it is a claim, not evidence: "status": "pass" costs one line and proves
    # nothing. What follows asks for the artefacts behind the claim.
    detail = report.get("checks")
    has_detail = isinstance(detail, dict) and len(detail) > 0
    checks.append(
        Check(
            "review.checks",
            has_detail,
            f"{len(detail)} self-review check(s): {', '.join(sorted(detail)[:4])}"
            if has_detail
            else "no 'checks' block: the report states a verdict but carries no self-review evidence",
        )
    )

    if has_detail:
        created = detail.get("previews_created")
        not_blank = detail.get("previews_not_blank")
        problems = []
        if created is not None and not created:
            problems.append("previews_created=false")
        if not_blank is not None and not not_blank:
            problems.append("previews_not_blank=false")
        if created is not None or not_blank is not None:
            checks.append(
                Check(
                    "review.previews",
                    not problems,
                    "previews_created={!r}, previews_not_blank={!r}".format(created, not_blank)
                    + ("" if not problems else ": " + ", ".join(problems)),
                )
            )

        outputs = detail.get("expected_outputs_exist")
        if outputs is not None:
            checks.append(
                Check(
                    "review.outputs",
                    bool(outputs),
                    f"expected_outputs_exist={outputs!r}",
                )
            )

    # A preview that the report says was created has to exist somewhere. The
    # reviewer writes them next to the report, so an empty folder next to a
    # "previews_created: true" claim is the signature of a report nobody filled
    # by looking at the model.
    if has_detail and detail.get("previews_created"):
        folder = os.path.dirname(os.path.abspath(path))
        try:
            images = [
                name
                for name in os.listdir(folder)
                if name.lower().endswith((".bmp", ".png", ".jpg", ".jpeg"))
            ]
        except OSError:
            images = []
        checks.append(
            Check(
                "review.previews_on_disk",
                len(images) > 0,
                f"{len(images)} preview image(s) beside the report"
                if images
                else "the report claims previews_created=true but there is no image next to it",
            )
        )

    # Upstream sets this on purpose: a structured report cannot replace a human
    # accepting the geometry. It stays a warning because it is a known limit of
    # the reviewer, not a defect in the delivery — but a pass must not be read as
    # "someone looked at this".
    manual = report.get("manual_review_required")
    if manual is None:
        manual = evaluation.get("manual_review_required")
    if manual:
        checks.append(
            Check(
                "review.manual",
                False,
                "the report sets manual_review_required=true: these files read back, but no human has accepted "
                "the geometry",
                severity="warning",
            )
        )

    score = evaluation.get("score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        checks.append(Check("review.score", True, f"evaluation.score={score:g}", severity="warning"))
    return checks
