"""The drawing has no extent.

A collapsed bounding box means the model-space geometry occupies a point or a
line: a rectangle exported with every vertex at the origin, a part scaled to
zero, an export that lost its geometry but kept its layers. It plots as a blank
sheet with a filled title block, which reads as "done" to anyone not measuring.

This is a geometry fact, not a drafting standard, so the rule id carries `geo.`
rather than `gb.` — but it still funnels through the rule layer, because that is
where a finding gets its severity and where a profile decides whether it blocks.
"""

from __future__ import annotations

from ..models import ParsedDrawing, Severity
from .base import BaseStandardRule, Evidence, RuleContext, RuleResult, register_rule
from .codes import Code

# Below this the extent is rounding noise rather than a dimension. One micron.
MIN_EXTENT_MM = 1e-3


@register_rule
class BBoxDegenerateRule(BaseStandardRule):
    rule_id = "geo.bbox_degenerate"
    gb_ref = None
    layer = "geometry"
    default_severity = Severity.ERROR

    def check(self, drawing: ParsedDrawing, ctx: RuleContext) -> list[RuleResult]:
        code = Code.BBOX_DEGENERATE.value

        # No extent recorded: the parser could not compute one, which says
        # nothing about the geometry. Staying silent is correct here — a
        # checker that guesses is worse than one that abstains.
        if drawing.extents is None:
            return []

        minx, miny, maxx, maxy = drawing.extents
        width = maxx - minx
        height = maxy - miny

        # Both dimensions must have extent for the drawing to be plottable. An
        # export that kept a 120 mm height but has zero width is a line, not a
        # drawing — so this is `and`, not `or`.
        if width > MIN_EXTENT_MM and height > MIN_EXTENT_MM:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    code=code,
                    ok=True,
                    severity=ctx.severity(code, self.default_severity),
                    detail=f"model-space extent {width:.1f} x {height:.1f} mm",
                    evidence=[
                        Evidence("measured", "bbox", f"({minx:.2f}, {miny:.2f})–({maxx:.2f}, {maxy:.2f})"),
                        Evidence("measured", "size", f"{width:.3f} x {height:.3f} mm"),
                    ],
                )
            ]

        if width <= MIN_EXTENT_MM and height <= MIN_EXTENT_MM:
            shape = "a single point"
        elif width <= MIN_EXTENT_MM:
            shape = "a vertical line"
        else:
            shape = "a horizontal line"

        return [
            RuleResult(
                rule_id=self.rule_id,
                code=code,
                ok=False,
                severity=ctx.severity(code, self.default_severity),
                detail=(
                    f"model-space geometry collapses to {shape}: "
                    f"{width:.3f} x {height:.3f} mm"
                ),
                evidence=[
                    Evidence("measured", "bbox", f"({minx:.2f}, {miny:.2f})–({maxx:.2f}, {maxy:.2f})"),
                    Evidence("measured", "size", f"{width:.3f} x {height:.3f} mm"),
                    Evidence("count", "entities", str(sum(drawing.entities.values()))),
                ],
                fix=(
                    "re-export the geometry: the model space has no extent, so nothing "
                    "would plot. Check that the part was not scaled to zero and that the "
                    "export did not drop the solids"
                ),
            )
        ]