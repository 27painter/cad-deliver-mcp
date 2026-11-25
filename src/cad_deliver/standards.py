"""Part of cad-deliver-mcp. Moved from dsh-sw-cad/lib/deliver.py."""

from __future__ import annotations

import json
import os
import re

from .models import Check, ParsedDrawing


PROFILE = "normal"

STANDARDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "standards.json")


def load_standards():
    with open(STANDARDS_FILE, "r", encoding="utf-8") as handle:
        return json.load(handle)


def drawing_text(drawing: ParsedDrawing) -> str:
    """Every string the drawing carries, wherever it sits."""
    parts = [item.content for item in drawing.texts]
    for dim in drawing.dimensions:
        if dim.text_is_overridden:
            parts.append(dim.text)
    return "\n".join(parts)


def check_standards(drawing: ParsedDrawing) -> list[Check]:
    """Half-delivery checks: the values must come from the table, not from the
    model's imagination. A value outside the table is a fail, because the point
    of the table is that a reviewer can look the value up."""
    table = load_standards()
    text = drawing_text(drawing)
    checks = []

    material_names = [name for group, values in table["materials"].items() if not group.startswith("_") for name in values]
    # A material is stated either as 材料: 45 or by naming the grade outright.
    hit = next((name for name in material_names if re.search(r"(?<![0-9A-Za-z])" + re.escape(name) + r"(?![0-9A-Za-z])", text)), None)
    checks.append(
        Check(
            "standards.material",
            hit is not None,
            f"材料 {hit}" if hit else "no material from lib/standards.json appears on the drawing",
        )
    )

    stated = re.search(r"(?:材料|MATERIAL)\s*[:：]?\s*([^\s,，;；]{1,20})", text, re.I)
    if stated and hit is None:
        checks.append(
            Check(
                "standards.material_table",
                False,
                f"材料栏写的是 {stated.group(1)!r}, which is not in lib/standards.json — add it to the table or use a listed grade",
            )
        )

    # No leading \b: in "φ40H7/g6" the H follows a digit, so a word boundary
    # never appears there and the code would go unnoticed.
    fits = set(re.findall(r"([A-Z]{1,2}\d{1,2}/[a-z]{1,2}\d{1,2})(?![0-9A-Za-z])", text))
    known_fits = {item for group, values in table["fits"].items() if not group.startswith("_") for item in values}
    if fits:
        unknown = sorted(fits - known_fits)
        checks.append(
            Check(
                "standards.fit",
                not unknown,
                f"{', '.join(sorted(fits))}" if not unknown else f"not in the table: {', '.join(unknown)}",
            )
        )
    else:
        checks.append(Check("standards.fit", True, "no fit code on the drawing", severity="warning"))

    rough = set(re.findall(r"Ra\s*([0-9]+(?:\.[0-9]+)?)", text, re.I))
    if rough:
        allowed = {f"{value:g}" for value in table["roughness_ra"]["values"]}
        unknown = sorted(value for value in rough if value not in allowed)
        checks.append(
            Check(
                "standards.roughness",
                not unknown,
                "Ra " + ", ".join(sorted(rough)) if not unknown else f"Ra {', '.join(unknown)} not in the preferred series",
            )
        )
    else:
        checks.append(
            Check("standards.roughness", False, "no Ra value anywhere; a half-delivery drawing states surface finish")
        )

    return checks


# ------------------------------------------------------------------ driver
