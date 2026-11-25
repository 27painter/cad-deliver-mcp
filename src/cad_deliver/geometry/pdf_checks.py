"""Generic PDF checks consuming `ParsedDrawing` without touching PyMuPDF."""

from __future__ import annotations

from ..core import SHEETS, SHEET_TOLERANCE_MM
from ..models import Check, ParsedDrawing


def check_pdf(drawing: ParsedDrawing) -> list[Check]:
    """Check sheet size and extractable text on a parsed PDF drawing."""
    checks: list[Check] = []
    if not drawing.layouts:
        checks.append(Check("pdf.pages", False, "the file has no pages"))
        return checks

    page = drawing.layouts[0]
    short, long = sorted((float(page.paper_width), float(page.paper_height)))
    sheet = None
    for name, (w, h) in SHEETS.items():
        if abs(short - w) <= SHEET_TOLERANCE_MM and abs(long - h) <= SHEET_TOLERANCE_MM:
            sheet = name
            break
    checks.append(
        Check(
            "pdf.sheet",
            sheet is not None,
            f"{short:.0f} x {long:.0f} mm ({sheet or 'not an ISO A-series sheet'})",
        )
    )

    # A vector PDF of a drawing has text; a picture of a drawing does not.
    first_page_texts = [
        item.content
        for item in drawing.texts
        if not item.layout or item.layout == page.name
    ]
    text = "\n".join(first_page_texts).strip()
    checks.append(
        Check(
            "pdf.text",
            len(text) > 0,
            f"{len(text)} characters of extractable text"
            if text
            else "no text layer: dimensions are pixels, not numbers",
        )
    )
    return checks
