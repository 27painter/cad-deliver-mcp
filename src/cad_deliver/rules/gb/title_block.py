"""Title block: it has to be there, and its fields have to be filled in.

Checking that a block named "GB-A3" exists proves nothing. An empty title block
still exists, still plots, and still leaves the drawing untraceable — which is
precisely the failure mode this gate is meant to catch.

So the assertions are, in order:

    E_TITLE_BLOCK        no title block reference at all
    W_TITLE_BLOCK_NO_ATTR  a block is there but carries no attributes to read
    E_TITLE_BLOCK_BLANK    required fields exist but are empty
"""

from __future__ import annotations

from ...models import BlockRef, ParsedDrawing, Severity
from ..base import BaseStandardRule, Evidence, RuleContext, RuleResult, register_rule
from ..codes import Code
from ..taxonomy import LayerRole, classify

# Field aliases, checked case-insensitively after folding. Chinese drafting
# practice and the English defaults of SolidWorks / NX exports are both covered.
REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "图名": ("图名", "名称", "零件名称", "TITLE", "NAME", "PARTNAME", "PART NAME", "DESCRIPTION"),
    "图号": ("图号", "图样代号", "DWGNO", "DWG NO", "DRAWINGNO", "DRAWING NO", "NUMBER", "PARTNO"),
    "比例": ("比例", "SCALE"),
}

# Names that mark a block reference as a title block when nobody classified the
# layer it sits on.
TITLE_HINTS = ("TITLE", "图框", "标题", "FRAME", "BORDER", "FORMAT", "GB-", "GB_")


def _looks_like_title_block(block: BlockRef) -> bool:
    folded = (block.name or "").upper()
    if any(hint.upper() in folded for hint in TITLE_HINTS):
        return True
    if block.layer and classify(block.layer).role is LayerRole.FRAME_TITLE:
        return True
    return False


@register_rule
class TitleBlockRule(BaseStandardRule):
    rule_id = "gb.title_block"
    gb_ref = "GB/T 10609.1-2008"
    layer = "standard"
    default_severity = Severity.ERROR

    def precondition(self, drawing: ParsedDrawing) -> str | None:
        """An export that wrote no sheet format cannot be judged for a title block.

        SolidWorks' `SaveAs` to DXF writes the model-space geometry and nothing
        else: the sheet format — frame lines *and* title block — is not exported at
        all, and no preference toggle controls it. Such a file has **no paper-space
        entities whatsoever**.

        That is the signature to test, not the absence of a block. A drawing whose
        title block was deleted still has its frame lines on the sheet, so it must
        be reported as missing a title block; a drawing whose export dropped the
        whole sheet format never had one to lose, and reporting it as missing
        blames the drawing for the exporter's behaviour.
        """
        paper = [l for l in drawing.layouts if l.name.lower() != "model"]
        # Content means entities or block references: a layout can carry a block
        # without the parser having counted entities for it (hand-built drawings in
        # tests do exactly that, and so does any DXF whose INSERT the reader kept
        # but whose entity total it did not recompute).
        has_content = any(
            l.entity_count > 0 or l.block_refs or l.blocks for l in paper
        )
        if not has_content:
            return (
                "the DXF has no paper-space content at all — frame and title block "
                "are both absent, so the exporter did not write the sheet format "
                "(SolidWorks SaveAs→DXF drops it; a sheet format must be exported "
                "explicitly). Nothing here says the drawing lacks a title block."
            )
        return None

    def check(self, drawing: ParsedDrawing, ctx: RuleContext) -> list[RuleResult]:
        results: list[RuleResult] = []

        blocks = [b for layout in drawing.layouts for b in layout.blocks]
        candidates = [b for b in blocks if _looks_like_title_block(b)]

        # A title block drawn as plain geometry, with the fields as TEXT rather
        # than attributes, is common in older drawings. Accept it as "present"
        # but say that the fields could not be read as fields.
        frame_layers = [
            layer.name
            for layer in drawing.layers
            if classify(layer.name).role is LayerRole.FRAME_TITLE
        ]

        if not candidates:
            code = Code.TITLE_BLOCK.value
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    code=code,
                    ok=False,
                    severity=ctx.severity(code, self.default_severity),
                    detail=(
                        "no title block reference on any layout"
                        if not frame_layers
                        else f"no title block reference; a frame layer exists ({', '.join(frame_layers[:3])}) "
                        "but nothing is inserted on it"
                    ),
                    evidence=[
                        Evidence("count", "block references", str(len(blocks))),
                        Evidence("count", "frame layers", str(len(frame_layers))),
                    ],
                    fix="insert the GB title block on the sheet (paper space), not just the frame lines",
                )
            )
            return results

        # Present. Now ask whether its fields can be read.
        blocks_with_attrs = [b for b in candidates if b.attributes]
        if not blocks_with_attrs:
            code = Code.TITLE_BLOCK_NO_ATTR.value
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    code=code,
                    ok=False,
                    severity=ctx.severity(code, self.default_severity),
                    detail=(
                        f"{len(candidates)} title block reference(s) present but carry no attributes, "
                        "so 图名/图号/比例 cannot be verified"
                    ),
                    evidence=[
                        Evidence("name", "blocks", ", ".join(sorted({b.name for b in candidates})[:4])),
                    ],
                    fix="use an attributed title block (ATTDEF) so its fields can be checked",
                )
            )
            return results

        best = max(blocks_with_attrs, key=lambda b: len(b.attributes))
        found: dict[str, str] = {}
        blank: list[str] = []
        missing: list[str] = []

        for label, aliases in REQUIRED_FIELDS.items():
            item = best.attribute(*aliases)
            if item is None:
                missing.append(label)
            elif item.is_blank:
                blank.append(label)
            else:
                found[label] = item.value.strip()

        code = Code.TITLE_BLOCK_BLANK.value
        ok = not blank and not missing
        if ok:
            detail = "title block fields filled: " + ", ".join(f"{k}={v}" for k, v in found.items())
        else:
            parts = []
            if blank:
                parts.append("empty: " + ", ".join(blank))
            if missing:
                parts.append("absent: " + ", ".join(missing))
            detail = f"title block '{best.name}' is missing required field(s) — " + "; ".join(parts)

        results.append(
            RuleResult(
                rule_id=self.rule_id,
                code=code,
                ok=ok,
                severity=ctx.severity(code, self.default_severity),
                detail=detail,
                evidence=[
                    Evidence("name", "block", best.name),
                    Evidence("count", "attributes", str(len(best.attributes))),
                    Evidence("name", "filled", ", ".join(f"{k}={v}" for k, v in found.items()) or "-"),
                    Evidence("name", "blank", ", ".join(blank) or "-"),
                    Evidence("name", "absent", ", ".join(missing) or "-"),
                ],
                fix=(
                    "fill 图名/图号/比例 in the title block attributes"
                    if not ok
                    else None
                ),
            )
        )
        return results