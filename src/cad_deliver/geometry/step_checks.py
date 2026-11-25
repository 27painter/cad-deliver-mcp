"""Part of cad-deliver-mcp. Moved from dsh-sw-cad/lib/deliver.py."""

from __future__ import annotations

import os
import re

from ..core import AP_SCHEMAS, SCHEMA_NAMES
from ..models import Check


def check_step(path, size):
    checks = []
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        head = handle.read(16384)

    schema = None
    raw_schema = ""
    for line in head.splitlines():
        if "FILE_SCHEMA" in line.upper():
            raw_schema = line.strip()
            lowered = line.lower()
            for key, names in SCHEMA_NAMES:
                if any(name in lowered for name in names):
                    schema = (key, AP_SCHEMAS[key])
                    break
            break
    checks.append(
        Check(
            "step.schema",
            schema is not None,
            f"{schema[1]}  [{raw_schema[:60]}]" if schema else f"unrecognised FILE_SCHEMA: {raw_schema[:80] or 'no FILE_SCHEMA line'}",
        )
    )
    if schema and schema[0] == "AP203":
        checks.append(
            Check(
                "step.pmi",
                False,
                "AP203 drops colour and assembly structure; use AP214 or AP242 for a mechanical handoff",
                severity="warning",
            )
        )

    # Count the geometry rather than trusting the file size.
    points = 0
    entities = 0
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("#"):
                entities += 1
                if "CARTESIAN_POINT" in line:
                    points += 1
    checks.append(Check("step.entities", entities > 100, f"{entities} entities, {points} CARTESIAN_POINTs"))

    # A bounding box from the raw coordinates.  This is not a geometry check —
    # it does not know faces from holes — but it does catch the two things that
    # silently ruin a handoff: the part was scaled, or the export carries no
    # geometry at all.  Reading B-Rep properly needs OCCT and 200 MB of wheels,
    # which is more than this bundle is willing to add for one check.
    pattern = re.compile(
        r"CARTESIAN_POINT\s*\(\s*'[^']*'\s*,\s*\(\s*([-0-9.eE+]+)\s*,\s*([-0-9.eE+]+)\s*,\s*([-0-9.eE+]+)\s*\)"
    )
    xs = []
    ys = []
    zs = []
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            hit = pattern.search(line)
            if hit:
                xs.append(float(hit.group(1)))
                ys.append(float(hit.group(2)))
                zs.append(float(hit.group(3)))
    if xs:
        size = (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
        degenerate = max(size) <= 1e-6
        checks.append(
            Check(
                "step.bbox",
                not degenerate,
                "bounding box %.3f x %.3f x %.3f (approximate, from raw points)" % size
                if not degenerate
                else "every point sits at the same place: the export carries no geometry",
            )
        )
    else:
        checks.append(Check("step.bbox", False, "no CARTESIAN_POINT coordinates could be read", severity="warning"))
    return checks
