"""Part of cad-deliver-mcp. Moved from dsh-sw-cad/lib/deliver.py."""

from __future__ import annotations

import atexit
import glob
import os
import shutil
import subprocess
import tempfile

# ------------------------------------------------------------------ DWG input
#
# A DWG cannot be parsed here: the format needs a converter we will not bundle.
# What we can do is drive one that is already on the machine, so a DWG gets the
# same treatment as a DXF instead of being waved through on its header.
#
# Order: an explicit override first (so a site can point at their own tool),
# then LibreDWG's dwg2dxf, then an ODA File Converter installation.

_CONVERT_TEMP = []


def _cleanup_temp():
    for folder in _CONVERT_TEMP:
        shutil.rmtree(folder, ignore_errors=True)


atexit.register(_cleanup_temp)


def find_dwg_converter():
    """Return (kind, command) for something that can turn a DWG into a DXF."""
    override = os.environ.get("DSH_SW_CAD_DWG_CONVERTER", "").strip()
    if override:
        return ("configured", override)

    dwg2dxf = shutil.which("dwg2dxf")
    if dwg2dxf:
        return ("libredwg", dwg2dxf)

    for pattern in (
        r"C:\Program Files\ODA\*\ODAFileConverter.exe",
        r"C:\Program Files (x86)\ODA\*\ODAFileConverter.exe",
        "/opt/ODA/ODAFileConverter/ODAFileConverter",
        "/usr/bin/ODAFileConverter",
    ):
        hits = sorted(glob.glob(pattern))
        if hits:
            return ("oda", hits[-1])
    return None


def convert_dwg(path, converter):
    """Convert one DWG to a DXF in a temporary folder. None when it fails."""
    kind, command = converter
    workdir = tempfile.mkdtemp(prefix="dsh-sw-cad-dwg-")
    _CONVERT_TEMP.append(workdir)
    source = os.path.join(workdir, "in")
    outdir = os.path.join(workdir, "out")
    os.makedirs(source)
    os.makedirs(outdir)
    stem = os.path.splitext(os.path.basename(path))[0]
    copied = os.path.join(source, stem + ".dwg")
    try:
        shutil.copy2(path, copied)
    except OSError:
        return None

    try:
        if kind == "libredwg":
            target = os.path.join(outdir, stem + ".dxf")
            res = subprocess.run(
                [command, copied, "-o", target],
                capture_output=True, text=True, timeout=180,
            )
        elif kind == "oda":
            res = subprocess.run(
                [command, source, outdir, "ACAD2018", "DXF", "0", "1", "*.DWG"],
                capture_output=True, text=True, timeout=300,
            )
        else:
            # "configured": a command template, {in} and {out} substituted.
            target = os.path.join(outdir, stem + ".dxf")
            line = command.replace("{in}", copied).replace("{out}", target)
            res = subprocess.run(line, shell=True, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        return None

    candidates = sorted(
        os.path.join(outdir, name)
        for name in os.listdir(outdir)
        if name.lower().endswith(".dxf")
    )
    if candidates and os.path.getsize(candidates[0]) > 0:
        return candidates[0]
    # A converter that exits 0 but writes nothing is still a failure.
    _ = res
    return None


# ------------------------------------------------------------------ checks
