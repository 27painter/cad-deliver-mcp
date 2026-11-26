"""A dimension whose text disagrees with the geometry it annotates.

Worse than a missing dimension: the drawing names a number the part does not
have, and it looks authoritative while doing it. A shop cuts to the number.

Only an *overridden* text can disagree. `""` and `"<>"` both make the CAD
application print the measured value, so there is nothing to compare there — that
is the normal, correct case and this rule stays silent about it.

A dimension style with `dimlfac != 1` is skipped: with a measurement factor in
play, the printed value is the geometry times that factor, and from the file
alone there is no way to tell a wrong text from a wrong factor. `drawing.scale`
reports the factor instead, which is where a human can see it.
"""

from __future__ import annotations

import re

from ...models import ParsedDrawing, Severity
from ..base import BaseStandardRule, Evidence, RuleContext, RuleResult, register_rule
from ..codes import Code

_NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")
# Angular (2), ordinate (5, 6) annotations report quantities that are not a
# straight distance, so a numeric comparison would be meaningless.
_NON_LINEAR_TYPES = (2, 5, 6)

# 0.2% of the measured value, with a 0.01 mm floor: a hand-typed value that
# rounds differently is not a defect, an order-of-magnitude lie is.
RELATIVE_TOLERANCE = 0.002
ABSOLUTE_TOLERANCE_MM = 0.01


@register_rule
class DimTextRule(BaseStandardRule):
    rule_id = "gb.dim_text"
    gb_ref = "GB/T 4458.4-2003"
    layer = "standard"
    default_severity = Severity.ERROR

    def check(self, drawing: ParsedDrawing, ctx: RuleContext) -> list[RuleResult]:
        code = Code.DIM_TEXT_MISMATCH.value
        compared = 0
        skipped_factor = 0
        mismatched: list[tuple[str, float, float]] = []

        for dim in drawing.dimensions:
            if dim.space != "model" or not dim.text_is_overridden:
                continue
            if dim.dimtype in _NON_LINEAR_TYPES or dim.measurement is None:
                continue
            if abs(dim.dimlfac - 1.0) > 1e-9:
                skipped_factor += 1
                continue

            cleaned = dim.text.replace("<>", "").replace("%%c", "").replace("±", "")
            numbers = _NUMBER_RE.findall(cleaned)
            if not numbers:
                continue
            try:
                shown = float(numbers[0].replace(",", "."))
            except ValueError:
                continue

            expected = dim.measurement
            tolerance = max(ABSOLUTE_TOLERANCE_MM, abs(expected) * RELATIVE_TOLERANCE)
            compared += 1
            if abs(shown - expected) > tolerance:
                mismatched.append((dim.handle, shown, expected))

        if not compared:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    code=code,
                    ok=True,
                    severity=ctx.severity(code, self.default_severity),
                    detail="no dimension text was overridden, so every value comes from the geometry",
                    evidence=[Evidence("count", "skipped (dimlfac)", str(skipped_factor))],
                )
            ]

        if not mismatched:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    code=code,
                    ok=True,
                    severity=ctx.severity(code, self.default_severity),
                    detail=(
                        f"{compared} overridden dimension text(s), all within "
                        f"{RELATIVE_TOLERANCE:.1%} of the measured geometry"
                    ),
                    evidence=[Evidence("count", "compared", str(compared))],
                )
            ]

        preview = "; ".join(
            f"handle {handle}: text says {shown:g}, geometry measures {expected:g}"
            for handle, shown, expected in mismatched[:4]
        )
        worst = max(mismatched, key=lambda item: abs(item[1] - item[2]) / (abs(item[2]) or 1.0))
        deviation = abs(worst[1] - worst[2]) / (abs(worst[2]) or 1.0)

        return [
            RuleResult(
                rule_id=self.rule_id,
                code=code,
                ok=False,
                severity=ctx.severity(code, self.default_severity),
                detail=(
                    f"{len(mismatched)} of {compared} overridden dimension text(s) disagree with "
                    f"the geometry: {preview}"
                ),
                evidence=[
                    Evidence("count", "mismatched", str(len(mismatched))),
                    Evidence("count", "compared", str(compared)),
                    Evidence("measured", "worst deviation", f"{deviation:.2%}"),
                    Evidence("location", "handles", ", ".join(h for h, _, _ in mismatched[:4])),
                ],
                fix=(
                    f"correct the dimension text on handle {worst[0]} to {worst[2]:g}, "
                    "or restore the geometry it annotates; do not leave a value the part does not have"
                ),
            )
        ]