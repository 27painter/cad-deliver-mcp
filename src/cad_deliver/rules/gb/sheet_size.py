"""GB/T 14689 sheet sizes (A4–A0), which are ISO 216 with a Chinese label.

The rule reads the paper size a layout declares and asks whether it is a
standard sheet. It does not care how the geometry is scaled: a drawing modelled
1:1 on an A3 sheet and one modelled 2:1 on the same sheet are both A3 sheets.
Scale is a separate question (drawing.scale in the geometry layer).
"""

from __future__ import annotations

from ...core import SHEETS, SHEET_TOLERANCE_MM
from ...models import ParsedDrawing, Severity
from ..base import BaseStandardRule, Evidence, RuleContext, RuleResult, register_rule
from ..codes import Code


def _match_sheet(width_mm: float, height_mm: float) -> tuple[str, bool] | None:
    """Return (name, rotated) for a standard sheet, or None.

    Landscape is the same sheet turned 90°, so both orientations match.
    """
    tol = SHEET_TOLERANCE_MM
    for name, (w, h) in SHEETS.items():
        if abs(width_mm - w) <= tol and abs(height_mm - h) <= tol:
            return name, False
        if abs(width_mm - h) <= tol and abs(height_mm - w) <= tol:
            return name, True
    return None


@register_rule
class SheetSizeRule(BaseStandardRule):
    rule_id = "gb.sheet_size"
    gb_ref = "GB/T 14689-2008"
    layer = "standard"
    default_severity = Severity.ERROR

    def check(self, drawing: ParsedDrawing, ctx: RuleContext) -> list[RuleResult]:
        results: list[RuleResult] = []

        sized = [
            layout
            for layout in drawing.layouts
            if layout.paper_width > 0 and layout.paper_height > 0
        ]

        if not sized:
            code = Code.SHEET_SIZE_UNKNOWN.value
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    code=code,
                    ok=False,
                    severity=ctx.severity(code, self.default_severity),
                    detail="no layout declares a paper size, so the sheet cannot be judged",
                    evidence=[
                        Evidence("count", "layouts", str(len(drawing.layouts))),
                        Evidence("expected", "standard sheets", ", ".join(sorted(SHEETS))),
                    ],
                    fix="set the plot paper size on the layout (A4–A0 per GB/T 14689)",
                )
            )
            return results

        # Only a layout that carries content can be a sheet someone plots. And when
        # a paper-space layout holds content, the `Model` layout is not a sheet at
        # all: a DXF keeps it around with the application's default paper (Letter
        # on a US install), which would report a defect about a layout nothing is
        # printed from. Prefer paper space; fall back to any occupied layout; then
        # to every layout that declares a size.
        paper_space = [
            layout
            for layout in sized
            if layout.name.lower() != "model" and layout.entity_count > 0
        ]
        if paper_space:
            targets = paper_space
        else:
            occupied = [layout for layout in sized if layout.entity_count > 0]
            targets = occupied or sized

        for layout in targets:
            hit = _match_sheet(layout.paper_width, layout.paper_height)
            measured = f"{layout.paper_width:g} x {layout.paper_height:g} mm"
            if hit is None:
                code = Code.SHEET_SIZE.value
                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        code=code,
                        ok=False,
                        severity=ctx.severity(code, self.default_severity),
                        detail=(
                            f"layout '{layout.name}' is {measured}, which is not a GB/T 14689 "
                            f"(ISO 216) sheet"
                        ),
                        evidence=[
                            Evidence("measured", "paper", measured),
                            Evidence("expected", "one of", ", ".join(sorted(SHEETS))),
                            Evidence("name", "layout", layout.name),
                        ],
                        fix=(
                            f"set the layout paper to A4/A3/A2/A1/A0 "
                            f"(±{SHEET_TOLERANCE_MM:g} mm), or fix the plot scale"
                        ),
                    )
                )
            else:
                name, rotated = hit
                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        code=Code.SHEET_SIZE.value,
                        ok=True,
                        severity=ctx.severity(Code.SHEET_SIZE.value, self.default_severity),
                        detail=(
                            f"layout '{layout.name}' is {name}"
                            + (" (landscape)" if rotated else "")
                            + f" at {measured}"
                        ),
                        evidence=[
                            Evidence("measured", "paper", measured),
                            Evidence("expected", "sheet", name),
                        ],
                    )
                )

        return results