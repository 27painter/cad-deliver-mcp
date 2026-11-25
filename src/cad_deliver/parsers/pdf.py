"""PDF parser producing plain `ParsedDrawing` facts."""

from __future__ import annotations

from ..models import Check, LayoutInfo, ParsedDrawing, ParseResult, TextItem


def parse(path: str) -> ParseResult:
    """Open a PDF with PyMuPDF and extract page sizes and text into `ParsedDrawing`."""
    checks: list[Check] = []
    try:
        import pymupdf as fitz
    except Exception:
        try:
            import fitz
        except Exception:
            checks.append(
                Check(
                    "pdf.parsed",
                    False,
                    "PyMuPDF is not importable, so this PDF was NOT checked "
                    "(install pymupdf, or run deliver with an interpreter that has it)",
                    severity="blocked",
                )
            )
            return ParseResult(drawing=None, checks=checks)

    try:
        doc = fitz.open(path)
    except Exception as exc:
        checks.append(Check("pdf.parsed", False, f"PyMuPDF could not read it: {exc}"))
        return ParseResult(drawing=None, checks=checks)

    try:
        pages = doc.page_count
        producer = (doc.metadata or {}).get("producer") or "unknown"
        checks.append(Check("pdf.parsed", True, f"{pages} page(s), producer {producer}"))

        layouts: list[LayoutInfo] = []
        texts: list[TextItem] = []
        for idx in range(pages):
            page = doc[idx]
            page_name = f"page-{idx + 1}"
            width_mm = page.rect.width * 25.4 / 72.0
            height_mm = page.rect.height * 25.4 / 72.0
            page_text = page.get_text().strip()
            layouts.append(
                LayoutInfo(
                    name=page_name,
                    paper_width=width_mm,
                    paper_height=height_mm,
                    entity_count=1 if page_text else 0,
                )
            )
            if page_text:
                texts.append(TextItem(content=page_text, space="paper", layout=page_name))
    finally:
        doc.close()

    drawing = ParsedDrawing(
        fmt="pdf",
        source_path=str(path),
        layouts=layouts,
        texts=texts,
        notes=[f"producer: {producer}"],
    )
    return ParseResult(drawing=drawing, checks=checks)
