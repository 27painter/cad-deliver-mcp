"""Part of cad-deliver-mcp. Moved from dsh-sw-cad/lib/deliver.py."""

from __future__ import annotations

import hashlib
import os

KIND_BY_EXT = {
    ".dxf": "drawing",
    ".dwg": "drawing",
    ".pdf": "pdf",
    ".step": "step",
    ".stp": "step",
    ".sldprt": "model",
    ".sldasm": "model",
    ".prt": "model",
    ".ipt": "model",
    ".iam": "model",
}

# A drawing this small is a title block or a stray line, not a part drawing.
MIN_BYTES = {
    "drawing": 2 * 1024,
    "pdf": 1 * 1024,
    "step": 1 * 1024,
    "model": 10 * 1024,
}

# ISO 216 / GB/T 14689 sheet sizes, portrait w x h in mm.
SHEETS = {
    "A4": (210.0, 297.0),
    "A3": (297.0, 420.0),
    "A2": (420.0, 594.0),
    "A1": (594.0, 841.0),
    "A0": (841.0, 1189.0),
}
SHEET_TOLERANCE_MM = 2.0

# DWG carries its format version in the first six bytes: AC1015 is 2000,
# AC1032 is 2018, and so on.  A .dwg that does not start with AC is not a DWG
# whatever its name says.
DWG_VERSIONS = {
    "AC1015": "2000",
    "AC1018": "2004",
    "AC1021": "2007",
    "AC1024": "2010",
    "AC1027": "2013",
    "AC1032": "2018",
}

AP_SCHEMAS = {
    "AP203": "AP203 (geometry only, no assembly structure or colour)",
    "AP214": "AP214 (the usual mechanical exchange default)",
    "AP242": "AP242 (carries PMI and tolerances as semantics)",
}

# FILE_SCHEMA carries the schema's name, not its AP number, and exporters use
# several spellings of each.  Matching the name is the only reliable way in.
SCHEMA_NAMES = (
    ("AP242", ("ap242", "managed_model_based_3d_engineering")),
    ("AP214", ("automotive_design",)),
    ("AP203", ("config_control_design",)),
)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 256), b""):
            digest.update(block)
    return digest.hexdigest()
