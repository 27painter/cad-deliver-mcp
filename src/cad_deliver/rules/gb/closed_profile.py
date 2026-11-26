"""The visible outline has to close.

An open outline is the classic agent failure: a rectangle built from four lines
where one is missing, or a polyline that stops one vertex short. It plots as an
almost-correct drawing, which is worse than an obviously broken one.

**Applicability — read this before enabling the rule.**

Closure is a property of a *single-view profile drawing*: one part, drawn as one
contour. It does not hold for a multi-view engineering drawing, where the visible
edges, hidden lines and centre lines are independent segments that each end
somewhere by their own nature. A three-view DXF therefore has dangling endpoints
by construction — sixteen of them in a typical one — and this rule fires on it
every time, at 100%, no matter how it is tuned.

That is why it lives in `PROFILE_CLOSURE` and not in `GB_T_TIER1`. The boundary is
architectural: enabling this rule is a statement that the artefact is a profile
drawing. Applying it to a production drawing is not a stricter check, it is a
category error, and the resulting false positives are structural rather than
occasional.

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

    def precondition(self, drawing: ParsedDrawing) -> str | None:
        """Nothing to judge when no outline geometry reached the analysis."""
        if not drawing.open_profiles and drawing.closed_profiles == 0:
            return "no outline geometry reached the closure analysis"
        return None

    def check(self, drawing: ParsedDrawing, ctx: RuleContext) -> list[RuleResult]:
        code = Code.PROFILE_OPEN.value

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