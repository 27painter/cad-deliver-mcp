"""The architecture claims two orthogonal layers; this keeps the claim honest.

    parsers/   may import a CAD library
    geometry/  must not — it reads ParsedDrawing, nothing else
    rules/     must not either, for the same reason
    standards  must not either, for the same reason

Phase 2 removed the phase-1 migration debt: neither geometry/, rules/, nor
standards.py may import ezdxf/PyMuPDF or import from parsers/.

Run: python -m pytest tests/test_layering.py   (or: python tests/test_layering.py)
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "cad_deliver"

CAD_LIBRARIES = ("ezdxf", "fitz", "pymupdf")
IMPORT_RE = re.compile(r"^\s*(?:import|from)\s+(%s)\b" % "|".join(CAD_LIBRARIES))
PARSER_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+(?:\.\.|cad_deliver)\s+import\s+.*\bparsers\b"
    r"|from\s+(?:\.\.|cad_deliver\.)parsers\b"
    r"|import\s+cad_deliver\.parsers\b)"
)

# Files allowed to touch a CAD library directly today, with the reason.
KNOWN_DEBT: dict[str, str] = {}


def offenders() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for folder in ("geometry", "rules"):
        for path in sorted((SRC / folder).rglob("*.py")):
            hits = [
                line.strip()
                for line in path.read_text(encoding="utf-8").splitlines()
                if IMPORT_RE.match(line)
            ]
            if hits:
                rel = path.relative_to(SRC).as_posix()
                found[rel] = hits
    return found


def test_no_new_direct_cad_dependencies():
    found = offenders()
    unexpected = {k: v for k, v in found.items() if k not in KNOWN_DEBT}
    assert not unexpected, (
        "geometry/ and rules/ must not import a CAD library. New offenders:\n"
        + "\n".join(f"  {k}: {v}" for k, v in unexpected.items())
    )


def test_known_debt_is_still_accurate():
    """Fail when the debt is paid, so the list gets cleaned instead of rotting."""
    found = offenders()
    paid = [k for k in KNOWN_DEBT if k not in found]
    assert not paid, (
        "these files no longer import a CAD library; remove them from KNOWN_DEBT: "
        + ", ".join(paid)
    )


def test_parsers_are_the_only_openers():
    """A parser is the only place allowed to decide whether a format is readable."""
    dxf_parser = SRC / "parsers" / "dxf.py"
    pdf_parser = SRC / "parsers" / "pdf.py"
    assert dxf_parser.exists()
    assert pdf_parser.exists()
    dxf_text = dxf_parser.read_text(encoding="utf-8")
    pdf_text = pdf_parser.read_text(encoding="utf-8")
    assert "import ezdxf" in dxf_text, "the DXF parser is the module that opens DXF files"
    assert "import pymupdf" in pdf_text, "the PDF parser is the module that opens PDF files"


def test_geometry_and_rules_do_not_import_parsers():
    """Downstream layers must consume ParsedDrawing, never invoke parsers."""
    found: dict[str, list[str]] = {}
    for folder in ("geometry", "rules"):
        for path in sorted((SRC / folder).rglob("*.py")):
            hits = [
                line.strip()
                for line in path.read_text(encoding="utf-8").splitlines()
                if PARSER_IMPORT_RE.match(line)
            ]
            if hits:
                found[path.relative_to(SRC).as_posix()] = hits
    assert not found, (
        "geometry/ and rules/ must not import parsers/. Offenders:\n"
        + "\n".join(f"  {k}: {v}" for k, v in found.items())
    )


def test_standards_has_no_direct_cad_dependencies():
    """standards.py must evaluate ParsedDrawing without importing CAD libraries."""
    standards_path = SRC / "standards.py"
    assert standards_path.exists()
    hits = [
        line.strip()
        for line in standards_path.read_text(encoding="utf-8").splitlines()
        if IMPORT_RE.match(line) or PARSER_IMPORT_RE.match(line)
    ]
    assert not hits, f"standards.py must not import CAD libraries or parsers/: {hits}"


if __name__ == "__main__":
    test_no_new_direct_cad_dependencies()
    test_known_debt_is_still_accurate()
    test_parsers_are_the_only_openers()
    test_geometry_and_rules_do_not_import_parsers()
    test_standards_has_no_direct_cad_dependencies()
    print("layering: ok (0 known debt)")
