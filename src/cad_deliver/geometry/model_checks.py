"""Part of cad-deliver-mcp. Moved from dsh-sw-cad/lib/deliver.py."""

from __future__ import annotations

import os

from ..core import MIN_BYTES
from ..models import Check


def check_model(path, size):
    """Native parts cannot be read without the application, so this is a
    presence check with the format tag where one exists."""
    checks = []
    ext = os.path.splitext(path)[1].lower()
    if ext in (".sldprt", ".sldasm"):
        with open(path, "rb") as handle:
            head = handle.read(16)
        checks.append(
            Check(
                "model.header",
                b"SolidWorks" in head or head.startswith(b"\xd0\xcf\x11\xe0") or head.startswith(b"PK"),
                "SolidWorks file signature present",
            )
        )
    checks.append(
        Check(
            "model.unchecked",
            True,
            "geometry not verified: reading a native part needs the application, so only presence and size were checked",
            severity="warning",
        )
    )
    return checks
