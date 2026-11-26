"""Which rules run, and what a finding costs.

Two tables, deliberately separate:

    PROFILES         profile -> rule ids to run
    SEVERITY_PROFILES  profile -> code -> severity

Splitting them means "add a standard" and "make this finding block the release"
are independent changes, which is what makes the architecture extensible rather
than merely layered.

LEGACY_COMPAT runs no GB rule at all. That is not an oversight: delivery.json is
a published contract, and dsh-sw-cad 2.2.0 produced it before these rules
existed. Keeping the compatible profile empty is what lets
tests/golden_compare.py demand field-for-field parity. Its severity entries are
still listed, because they document what the same finding would cost if the
profile enabled it — that is the comparison a reader switching profiles wants.
"""

from __future__ import annotations

from ..models import ParsedDrawing, Severity
from .base import BaseStandardRule, RuleContext, RuleResult, all_rules, get_rule
from .codes import Code

PROFILES: dict[str, list[str]] = {
    # No GB rules: byte-compatible with dsh-sw-cad 2.2.0.
    "LEGACY_COMPAT": [],
    # Generic checks only, no standard. Behaviourally identical to LEGACY_COMPAT
    # today — the distinction is intent, and it is the name to hang future
    # geometry rules on (closed profiles, zero-length entities) so that callers
    # asking for "geometry only" do not accidentally inherit a standard.
    "GEOMETRY_ONLY": [],
    # The Tier-1 drafting baseline: sheet size, layer taxonomy, title block.
    "GB_T_TIER1": [
        "geo.bbox_degenerate",
        "gb.sheet_size",
        "gb.layer_taxonomy",
        "gb.closed_profile",
        "gb.title_block",
    ],
    # Same sheet rule, different standard: proof that a rule is reusable and
    # only the profile decides what runs.
    "ISO_216_TIER1": [
        "gb.sheet_size",
    ],
}

DEFAULT_PROFILE = "GB_T_TIER1"


SEVERITY_PROFILES: dict[str, dict[str, Severity]] = {
    "LEGACY_COMPAT": {
        # Nothing runs, so these never appear. The values state the intent: in
        # the compatible profile these findings would not block a release.
        Code.SHEET_SIZE.value: Severity.WARNING,
        Code.TITLE_BLOCK.value: Severity.WARNING,
        Code.DIM_ON_WRONG_LAYER.value: Severity.WARNING,
        Code.CONTOUR_ON_ZERO.value: Severity.WARNING,
        Code.LAYER_UNCLASSIFIED.value: Severity.WARNING,
    },
    "GB_T_TIER1": {
        # A drawing that cannot be plotted on the right sheet is not a delivery.
        Code.SHEET_SIZE.value: Severity.ERROR,
        Code.SHEET_SIZE_UNKNOWN.value: Severity.ERROR,
        # Same for a drawing with no title block: nobody can trace it.
        Code.TITLE_BLOCK.value: Severity.ERROR,
        Code.TITLE_BLOCK_BLANK.value: Severity.ERROR,
        # A dimension on the outline layer is the thing a shop actually
        # complains about, so it blocks. An unclassified layer name only warns.
        Code.DIM_ON_WRONG_LAYER.value: Severity.ERROR,
        Code.CONTOUR_ON_ZERO.value: Severity.ERROR,
        Code.LAYER_UNCLASSIFIED.value: Severity.WARNING,
        Code.LAYER_AMBIGUOUS.value: Severity.WARNING,
        Code.CENTER_LINETYPE.value: Severity.WARNING,
        Code.NO_CONTOUR_LAYER.value: Severity.WARNING,
        # A drawing with no extent plots blank; nothing else on it matters.
        Code.BBOX_DEGENERATE.value: Severity.ERROR,
        # An outline that does not close is a plotting defect a shop rejects.
        Code.PROFILE_OPEN.value: Severity.ERROR,
        Code.TITLE_BLOCK_NO_ATTR.value: Severity.WARNING,
        Code.SHEET_NOT_ISO_A.value: Severity.WARNING,
    },
    "ISO_216_TIER1": {
        Code.SHEET_SIZE.value: Severity.ERROR,
        Code.SHEET_SIZE_UNKNOWN.value: Severity.ERROR,
        Code.SHEET_NOT_ISO_A.value: Severity.WARNING,
    },
}


def available_profiles() -> list[str]:
    return sorted(PROFILES)


def context_for(profile: str) -> RuleContext:
    if profile not in PROFILES:
        raise KeyError(f"unknown profile {profile!r}; known: {', '.join(available_profiles())}")
    return RuleContext(profile=profile, severities=dict(SEVERITY_PROFILES.get(profile, {})))


def run_profile(
    drawing: ParsedDrawing, profile: str = DEFAULT_PROFILE
) -> list[RuleResult]:
    """Run every rule the profile selects. One failing rule never stops the rest."""
    ctx = context_for(profile)
    results: list[RuleResult] = []
    for rule_id in PROFILES[profile]:
        rule: BaseStandardRule = get_rule(rule_id)
        try:
            results.extend(rule.check(drawing, ctx))
        except Exception as exc:  # a broken rule must not take the gate down
            results.append(
                RuleResult(
                    rule_id=rule_id,
                    code=f"E_RULE_CRASHED",
                    ok=False,
                    severity=Severity.BLOCKED,
                    detail=f"{rule_id} raised {type(exc).__name__}: {exc}",
                    fix="report this rule as unusable; do not treat the delivery as passed",
                )
            )
    return results


def registry_snapshot() -> list[dict]:
    """What the rules declare about themselves, for docs and the paper table."""
    rows = []
    for rule_id, cls in sorted(all_rules().items()):
        rows.append(
            {
                "rule_id": rule_id,
                "gb_ref": cls.gb_ref,
                "layer": cls.layer,
                "default_severity": cls.default_severity.value,
                "profiles": [p for p, ids in PROFILES.items() if rule_id in ids],
            }
        )
    return rows