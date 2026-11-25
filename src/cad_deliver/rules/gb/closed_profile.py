"""The visible outline has to close.

An open outline is the classic agent failure: a rectangle built from four lines
where one is missing, or a polyline that stops one vertex short. It plots as an
almost-correct drawing, which is worse than an obviously broken one.

This rule only reads the analysis `geometry/topology.py` already produced (the
pipeline writes it back onto the drawing), so the graph is built once. The rule
decides what an open outline *costs*; the profile decides whether that blocks.
"""

from __future__ import annotations

from ...models import ParsedDrawing, Severity
from ..base import BaseStandardRule, Evidence, RuleContext, RuleResult, register_rule
from ..codes import Code


@register_rule
class ClosedProfileRule(BaseStandardRule):
    rule_id = "gb.closed_profile"
    gb_ref = "GB/T 4457.2-2003"
    layer = "standard"
    default_severity = Severity.ERROR

    def check(self, drawing: ParsedDrawing, ctx: RuleContext) -> list[RuleResult]:
        code = Code.PROFILE_OPEN.value

        # Nothing to judge: no outline pieces reached the analysis, either because
        # the drawing has none or because every one sat on a layer that is not an
        # outline. Saying "closed" there would be a claim about nothing.
        if not drawing.open_profiles and drawing.closed_profiles == 0:
            return []

        if not drawing.open_profiles:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    code=code,
                    ok=True,
                    severity=ctx.severity(code, self.default_severity),
                    detail=f"{drawing.closed_profiles} outline component(s) close",
                    evidence=[
                        Evidence("count", "closed", str(drawing.closed_profiles)),
                        Evidence("count", "segments", str(len(drawing.segments))),
                    ],
                )
            ]

        worst = max(drawing.open_profiles, key=len)
        preview = ", ".join(f"({x:g}, {y:g})" for x, y in worst[:4])
        more = f" (+{len(worst) - 4} more)" if len(worst) > 4 else ""
        total_ends = sum(len(group) for group in drawing.open_profiles)

        return [
            RuleResult(
                rule_id=self.rule_id,
                code=code,
                ok=False,
                severity=ctx.severity(code, self.default_severity),
                detail=(
                    f"{len(drawing.open_profiles)} outline component(s) do not close; "
                    f"{total_ends} dangling end(s), the worst at {preview}{more}"
                ),
                evidence=[
                    Evidence("count", "open components", str(len(drawing.open_profiles))),
                    Evidence("count", "dangling ends", str(total_ends)),
                    Evidence("count", "closed components", str(drawing.closed_profiles)),
                    Evidence("location", "worst break", preview),
                ],
                fix=(
                    "close the outline: extend or add the missing segment so the "
                    f"ends at {preview} meet within 0.01 mm"
                ),
            )
        ]