"""Layer naming and entity-layer consistency.

Two different assertions live here and they are worth keeping apart:

  naming        does every layer name say what it carries?
  consistency   is every entity on the layer its type belongs to?

The second is the one a shop complains about. A drawing can have a perfect
layer table and still put every dimension on the outline layer, which is exactly
what an agent that does not understand the convention will do.

Severity is not decided here: a profile does that, so the same finding can warn
in one profile and block in another.
"""

from __future__ import annotations

from collections import Counter

from ...models import ParsedDrawing, Severity
from ..base import BaseStandardRule, Evidence, RuleContext, RuleResult, register_rule
from ..codes import Code
from ..taxonomy import LayerRole, classify, is_structural, linetype_matches

# Entity types that make up the visible outline of a part.
CONTOUR_TYPES = frozenset(
    {"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "SPLINE", "ELLIPSE"}
)
DIMENSION_TYPES = frozenset({"DIMENSION", "LEADER", "MLEADER"})
TEXT_TYPES = frozenset({"TEXT", "MTEXT", "ATTRIB"})

ZERO_LAYERS = frozenset({"0"})


def _preview(names: list[str], limit: int = 5) -> str:
    head = ", ".join(sorted(names)[:limit])
    return head + (f" (+{len(names) - limit} more)" if len(names) > limit else "")


@register_rule
class LayerTaxonomyRule(BaseStandardRule):
    rule_id = "gb.layer_taxonomy"
    gb_ref = "GB/T 4457.2-2003"
    layer = "standard"
    default_severity = Severity.WARNING

    def check(self, drawing: ParsedDrawing, ctx: RuleContext) -> list[RuleResult]:
        results: list[RuleResult] = []

        unclassified: list[str] = []
        ambiguous: list[str] = []
        by_role: dict[LayerRole, list[str]] = {}

        for layer in drawing.layers:
            name = layer.name
            if is_structural(name):
                continue
            match = classify(name)
            if match.role is LayerRole.UNCLASSIFIED:
                unclassified.append(name)
                continue
            by_role.setdefault(match.role, []).append(name)
            if match.ambiguous:
                ambiguous.append(f"{name} -> {match.role.value} (via {match.via})")

        # --- naming -------------------------------------------------------
        code = Code.LAYER_UNCLASSIFIED.value
        results.append(
            RuleResult(
                rule_id=self.rule_id,
                code=code,
                ok=not unclassified,
                severity=ctx.severity(code, self.default_severity),
                detail=(
                    f"{len(unclassified)} layer(s) match no drafting role: {_preview(unclassified)}"
                    if unclassified
                    else f"all {len(by_role)} named layer(s) map to a drafting role"
                ),
                evidence=[
                    Evidence("count", "unclassified", str(len(unclassified))),
                    Evidence("name", "layers", _preview(unclassified, 8) or "-"),
                ],
                fix=(
                    "rename these layers to carry their role (轮廓线/中心线/虚线/标注/文字/图框)"
                    if unclassified
                    else None
                ),
            )
        )

        if ambiguous:
            code = Code.LAYER_AMBIGUOUS.value
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    code=code,
                    ok=False,
                    severity=ctx.severity(code, self.default_severity),
                    detail=f"{len(ambiguous)} layer name(s) match two roles: {_preview(ambiguous, 3)}",
                    evidence=[Evidence("name", "ambiguous", _preview(ambiguous, 8))],
                    fix="rename so the layer names exactly one role",
                )
            )

        code = Code.NO_CONTOUR_LAYER.value
        has_contour = LayerRole.CONTOUR_THICK in by_role
        results.append(
            RuleResult(
                rule_id=self.rule_id,
                code=code,
                ok=has_contour,
                severity=ctx.severity(code, self.default_severity),
                detail=(
                    "no layer carries the visible outline"
                    if not has_contour
                    else f"outline layer(s): {_preview(by_role[LayerRole.CONTOUR_THICK])}"
                ),
                evidence=[
                    Evidence("count", "roles seen", str(len(by_role))),
                    Evidence("name", "outline", _preview(by_role.get(LayerRole.CONTOUR_THICK, [])) or "-"),
                ],
                fix="put the visible outline on a 粗实线/轮廓线 layer" if not has_contour else None,
            )
        )

        # --- centre / hidden linetypes ------------------------------------
        wrong_linetype: list[str] = []
        for layer in drawing.layers:
            if is_structural(layer.name):
                continue
            role = classify(layer.name).role
            if role in (LayerRole.CENTERLINE, LayerRole.HIDDEN_DASHED):
                if not linetype_matches(layer.linetype, role):
                    wrong_linetype.append(f"{layer.name} ({layer.linetype or 'BYLAYER'})")
        if wrong_linetype:
            code = Code.CENTER_LINETYPE.value
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    code=code,
                    ok=False,
                    severity=ctx.severity(code, self.default_severity),
                    detail=(
                        f"{len(wrong_linetype)} centre/hidden layer(s) carry a linetype that does not "
                        f"match the role: {_preview(wrong_linetype, 4)}"
                    ),
                    evidence=[Evidence("name", "layers", _preview(wrong_linetype, 8))],
                    fix="set the layer linetype to CENTER/DASHDOT (centre) or HIDDEN/DASHED (hidden)",
                )
            )

        # --- entity-layer consistency -------------------------------------
        results.extend(self._dimensions_off_layer(drawing, ctx))
        results.extend(self._contour_on_zero(drawing, ctx))

        return results

    # ------------------------------------------------------------------
    def _dimensions_off_layer(
        self, drawing: ParsedDrawing, ctx: RuleContext
    ) -> list[RuleResult]:
        """A dimension belongs on a dimension layer, not on 0 and not on the outline."""
        misplaced: Counter[str] = Counter()
        for dim in drawing.dimensions:
            layer = dim.layer or "0"
            if layer in ZERO_LAYERS:
                misplaced[layer] += 1
                continue
            role = classify(layer).role
            if role is not LayerRole.DIMENSION:
                misplaced[f"{layer} ({role.value})"] += 1

        if not misplaced:
            return []

        total = sum(misplaced.values())
        code = Code.DIM_ON_WRONG_LAYER.value
        detail = "; ".join(f"{name}: {count}" for name, count in misplaced.most_common(4))
        return [
            RuleResult(
                rule_id=self.rule_id,
                code=code,
                ok=False,
                severity=ctx.severity(code, Severity.ERROR),
                detail=(
                    f"{total} of {len(drawing.dimensions)} dimension(s) sit on a layer that is not a "
                    f"dimension layer ({detail})"
                ),
                evidence=[
                    Evidence("count", "misplaced", str(total)),
                    Evidence("name", "layers", detail),
                ],
                fix="move these DIMENSION entities to the 标注/DIM layer",
            )
        ]

    def _contour_on_zero(
        self, drawing: ParsedDrawing, ctx: RuleContext
    ) -> list[RuleResult]:
        """Model-space outline geometry left on layer 0.

        Layer 0 is special: entities inside a block live there by design, and they
        are not in `entity_layers` (that map is model space only), so this cannot
        be triggered by a block definition.
        """
        zero = drawing.entity_layers.get("0") or {}
        contour_count = sum(count for kind, count in zero.items() if kind in CONTOUR_TYPES)
        if not contour_count:
            return []

        total_contour = sum(
            count
            for layer_map in drawing.entity_layers.values()
            for kind, count in layer_map.items()
            if kind in CONTOUR_TYPES
        )
        share = contour_count / total_contour if total_contour else 0.0
        if share < 0.5:
            # A few strays on 0 are normal; most of the outline being there is not.
            return []

        code = Code.CONTOUR_ON_ZERO.value
        return [
            RuleResult(
                rule_id=self.rule_id,
                code=code,
                ok=False,
                severity=ctx.severity(code, Severity.ERROR),
                detail=(
                    f"{contour_count} of {total_contour} outline entities ({share:.0%}) are on layer 0"
                ),
                evidence=[
                    Evidence("count", "on layer 0", str(contour_count)),
                    Evidence("count", "outline entities", str(total_contour)),
                    Evidence("measured", "share", f"{share:.0%}"),
                ],
                fix="move the outline to the 轮廓线/粗实线 layer",
            )
        ]