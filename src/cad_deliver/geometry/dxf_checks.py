"""Generic DXF/DWG drawing checks consuming `ParsedDrawing` without CAD libraries."""

from __future__ import annotations

import re

from ..core import SHEETS, SHEET_TOLERANCE_MM
from ..models import Check, ParsedDrawing, Severity


_UNIT_NAMES = {0: "unitless", 1: "inch", 4: "mm", 5: "cm", 6: "m"}
_TITLE_HINT = (
    "\u56fe\u540d",
    "\u6bd4\u4f8b",
    "\u6750\u6599",
    "\u5236\u56fe",
    "\u5ba1\u6838",
    "scale",
    "material",
    "drawn",
    "title",
)
_SCALE_PATTERN = re.compile(r"(?:比例|SCALE)\s*[:：]?\s*([0-9]+\s*[:：]\s*[0-9]+)", re.I)
_NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_GB_FONT_RE = re.compile(r"(fangsong|simsun|simhei|song|kai|msyh|yahei)", re.I)


def check_drawing(drawing: ParsedDrawing) -> list[Check]:
    """Run generic drawing checks on an already-parsed `ParsedDrawing`."""
    checks: list[Check] = []

    model_dims = [dim for dim in drawing.dimensions if dim.space == "model"]
    dim_count = drawing.entities.get("DIMENSION", len(model_dims))
    # A dimension is the difference between a drawing and a picture. Text
    # plus a leader is what the skill forbids, and this is where that shows up.
    checks.append(
        Check(
            "drawing.dimensions",
            dim_count > 0,
            f"{dim_count} DIMENSION entit{'y' if dim_count == 1 else 'ies'} in modelspace",
        )
    )

    entity_count = sum(drawing.entities.values())
    checks.append(
        Check("drawing.entities", entity_count > 0, f"{entity_count} entities in modelspace")
    )

    layer_names = [layer.name for layer in drawing.layers]
    checks.append(
        Check(
            "drawing.layers",
            len(layer_names) > 0,
            f"{len(layer_names)} layers: {', '.join(sorted(layer_names)[:8])}",
        )
    )

    insunits = drawing.units
    checks.append(
        Check(
            "drawing.units",
            insunits in (1, 4, 5, 6),
            f"$INSUNITS={insunits} ({_UNIT_NAMES.get(insunits, 'unknown')})",
            severity="error" if insunits == 0 else "warning",
        )
    )

    # A layout that exists but is empty is the default of every new DXF, so
    # counting names proves nothing. What matters is whether anything was
    # actually placed on the sheet.
    paper_layouts = [layout for layout in drawing.layouts if layout.name.lower() != "model"]
    sheets = [
        f"{layout.name} ({layout.entity_count} entities)"
        for layout in paper_layouts
        if layout.entity_count
    ]
    checks.append(
        Check(
            "drawing.sheets",
            len(sheets) > 0,
            "paper space: " + ", ".join(sheets)
            if sheets
            else "no sheet has anything on it; nothing frames the drawing",
            # Warns rather than fails. Whether the sheet format was written is a
            # property of the exporter, not of the drawing: SolidWorks' SaveAs to
            # DXF writes model-space geometry only, so a perfectly good drawing
            # arrives here with an empty sheet. Failing that would blame the file
            # for a behaviour its author never chose, on every such file.
            severity=Severity.WARNING.value,
        )
    )

    # A title block is usually a block reference on the sheet, with the fields
    # filled as text. This is a heuristic, so it warns rather than fails: the
    # block name is the shop's choice, and a DXF may legitimately carry none.
    paper_texts = [
        item
        for item in drawing.texts
        if item.space == "paper" and item.kind in ("TEXT", "MTEXT")
    ]
    found: list[str] = []
    for layout in paper_layouts:
        found.extend(layout.block_refs)
        for item in paper_texts:
            if item.layout == layout.name:
                content = item.content.lower()
                if any(word in content for word in _TITLE_HINT):
                    found.append(content[:24])
    seen_layouts = {layout.name for layout in paper_layouts}
    for item in paper_texts:
        if not item.layout or item.layout not in seen_layouts:
            content = item.content.lower()
            if any(word in content for word in _TITLE_HINT):
                found.append(content[:24])
    checks.append(
        Check(
            "drawing.titleblock",
            len(found) > 0,
            f"found {', '.join(found[:4])}"
            if found
            else "no title block reference or field text on the sheet",
            severity="warning",
        )
    )

    # The sheet the drawing will be plotted on. A DXF leaves this at the A3
    # default until someone sets it, so a mismatch is a warning: the drawing is
    # still readable, it just will not plot at the size the title block claims.
    sheets_seen = []
    for layout in paper_layouts:
        if not layout.entity_count:
            continue
        short, long = sorted((float(layout.paper_width), float(layout.paper_height)))
        matched = None
        for sheet_name, (w, h) in SHEETS.items():
            if abs(short - w) <= SHEET_TOLERANCE_MM and abs(long - h) <= SHEET_TOLERANCE_MM:
                matched = sheet_name
                break
        sheets_seen.append((layout.name, short, long, matched))
    if sheets_seen:
        detail = "; ".join(
            f"{n} {s:.0f}x{l:.0f}mm ({m or 'not ISO A'})" for n, s, l, m in sheets_seen
        )
        checks.append(
            Check(
                "drawing.sheet",
                all(m for *_rest, m in sheets_seen),
                detail,
                severity="warning",
            )
        )

    # 比例 / SCALE, stated on the sheet. dimlfac is not a substitute: it is a
    # measurement factor on a dimension style, and a style left at 100 (as the
    # ezdxf templates are) says nothing about the plot scale. It is reported
    # next to the verdict, not counted as one.
    scale_found = []
    for item in paper_texts:
        hit = _SCALE_PATTERN.search(item.content)
        if hit:
            scale_found.append(hit.group(0))
    factors = [
        f"{dim.style} dimlfac={dim.dimlfac:g}"
        for dim in model_dims
        if abs(dim.dimlfac - 1.0) > 1e-9
    ]
    detail = (
        ", ".join(sorted(set(scale_found))[:3])
        if scale_found
        else "no 比例/SCALE stated on the sheet"
    )
    if factors:
        detail += "  (dimension style factor: " + ", ".join(sorted(set(factors))[:2]) + ")"
    checks.append(
        Check(
            "drawing.scale",
            len(scale_found) > 0,
            detail,
            severity="error" if sheets_seen else "warning",
        )
    )

    # Line weights: a mechanical drawing separates thick outlines from thin
    # dimensions by weight, not only by colour. One weight everywhere means
    # the plot comes out flat.
    distinct = {layer.lineweight for layer in drawing.layers if layer.has_explicit_weight}
    checks.append(
        Check(
            "drawing.lineweights",
            len(distinct) >= 2,
            f"{len(distinct)} explicit line weight(s) across {len(drawing.layers)} layers"
            + ("" if len(distinct) >= 2 else "; thick and thin will plot the same"),
            severity="warning",
        )
    )

    # A dimension whose text disagrees with the geometry is worse than a missing
    # dimension: the drawing names a number the part does not have, and it looks
    # authoritative while doing it. Only an overridden text can disagree — "<>"
    # and an empty string both make the application print the measured value, so
    # there is nothing to compare there.
    mismatched = []
    compared = 0
    skipped_factor = 0
    for dim in model_dims:
        if not dim.text_is_overridden:
            continue
        if dim.kind in (2, 5, 6):  # angular and ordinate report other quantities
            continue
        if dim.measurement is None:
            continue
        # With a measurement factor in play the printed value is the geometry
        # times that factor, and there is no way to tell from the file alone
        # whether a disagreement is a wrong text or a wrong factor. Say so and
        # leave it to drawing.scale, which already reports the factor.
        if abs(dim.dimlfac - 1.0) > 1e-9:
            skipped_factor += 1
            continue
        expected = dim.measurement
        cleaned = dim.text.replace("%%c", "").replace("%%C", "")
        numbers = _NUMBER_RE.findall(cleaned)
        if not numbers:
            continue
        try:
            shown = float(numbers[0].replace(",", "."))
        except ValueError:
            continue
        compared += 1
        tolerance = max(0.01, abs(expected) * 0.002)
        if abs(shown - expected) > tolerance:
            mismatched.append((dim.handle, shown, expected))
    factor_note = (
        f"; {skipped_factor} more skipped because their style has a dimlfac other than 1"
        if skipped_factor
        else ""
    )
    if mismatched:
        preview = "; ".join(
            f"handle {handle}: text says {shown:g}, geometry measures {measured:g}"
            for handle, shown, measured in mismatched[:4]
        )
        more = f" (+{len(mismatched) - 4} more)" if len(mismatched) > 4 else ""
        checks.append(
            Check(
                "drawing.dim_values",
                False,
                f"{len(mismatched)} of {compared} overridden dimension text(s) disagree with the geometry: "
                f"{preview}{more}{factor_note}",
            )
        )
    else:
        checks.append(
            Check(
                "drawing.dim_values",
                True,
                (
                    f"{compared} overridden dimension text(s), all within 0.2% of the measured geometry"
                    if compared
                    else "no dimension text was overridden, so every value comes from the geometry"
                )
                + factor_note,
                severity="warning",
            )
        )

    # Chinese drawings are set in 仿宋 (or 宋体 for headings). If the sheet
    # carries Chinese text and every style points at a Latin font, the plot
    # shows boxes on a machine without that font.
    has_cjk = False
    used_styles: list[str] = []
    seen_styles: set[str] = set()
    for item in drawing.texts:
        if item.kind not in ("TEXT", "MTEXT"):
            continue
        style_name = item.style or "Standard"
        if style_name not in seen_styles:
            seen_styles.add(style_name)
            used_styles.append(style_name)
        if item.content and _CJK_RE.search(item.content):
            has_cjk = True
    if has_cjk:
        style_lookup = {k.lower(): v for k, v in drawing.text_styles.items()}
        fonts = []
        for style_name in used_styles:
            font = drawing.text_styles.get(style_name)
            if font is None:
                font = style_lookup.get(style_name.lower(), "")
            fonts.append(f"{style_name}:{font or 'none'}")
        ok_font = any(_GB_FONT_RE.search(item) for item in fonts)
        checks.append(
            Check(
                "drawing.fonts",
                ok_font,
                ", ".join(fonts[:4])
                + ("" if ok_font else "  — Chinese text with no CJK font assigned"),
                severity="warning",
            )
        )

    # Dimension text that lands on top of other dimension text. Measured from
    # text_midpoint, so it catches the crowded cases a reviewer would circle.
    mids = [dim.text_midpoint for dim in model_dims if dim.text_midpoint is not None]
    close = 0
    for i in range(len(mids)):
        for j in range(i + 1, len(mids)):
            if abs(mids[i][0] - mids[j][0]) < 2.0 and abs(mids[i][1] - mids[j][1]) < 2.0:
                close += 1
    checks.append(
        Check(
            "drawing.dim_overlap",
            close == 0,
            f"{close} pair(s) of dimension texts within 2 mm of each other"
            if close
            else f"{len(mids)} dimension texts, none overlapping",
            severity="warning",
        )
    )

    # The delivery profile is a CLI decision, not a property of the drawing, so
    # it is read from the module that owns it rather than passed down the stack.
    from .. import standards

    if standards.PROFILE == "half":
        checks.extend(standards.check_standards(drawing))
    return checks
