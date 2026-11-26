"""Export one SolidWorks part, with a hard deadline.

Run as a subprocess per part so a hung SolidWorks session cannot block the batch:
the parent kills this process after N seconds and moves on.

    python scripts/export_one_sw.py <part> <out.dxf> <template>
"""

from __future__ import annotations

import os
import sys
import time

import pythoncom
import win32com.client as win32
from win32com.client import VARIANT

UNIT_LINEAR, MM, A3 = 47, 0, 8
ENTIRE_MODEL = 0


def main() -> int:
    part, out, template = sys.argv[1], sys.argv[2], sys.argv[3]

    sw = win32.Dispatch("SldWorks.Application")
    for _ in range(20):
        try:
            sw.RevisionNumber
            break
        except Exception:  # noqa: BLE001
            time.sleep(0.5)

    try:
        sw.CloseAllDocuments(True)
    except Exception:  # noqa: BLE001
        pass
    time.sleep(0.3)

    errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    model = None
    for _ in range(4):
        model = sw.OpenDoc6(os.path.abspath(part), 1, 1, "", errors, warnings)
        if model is not None:
            break
        time.sleep(2)
    if model is None:
        print("open failed")
        return 1
    time.sleep(0.4)

    sw.NewDocument(template, A3, 0, 0)
    time.sleep(0.5)
    drawing = sw.ActiveDoc
    if drawing is None:
        print("no drawing")
        return 1

    drawing.Extension.SetUserPreferenceInteger(UNIT_LINEAR, 0, MM)
    drawing.Create1stAngleViews2(model.GetPathName)
    time.sleep(0.4)
    try:
        drawing.InsertModelAnnotations3(ENTIRE_MODEL, -1, True, True, True, True)
    except Exception:  # noqa: BLE001
        pass
    time.sleep(0.3)

    if os.path.isfile(out):
        os.remove(out)
    saved = drawing.SaveAs(out)
    size = os.path.getsize(out) if os.path.isfile(out) else 0
    print(f"saved={saved} bytes={size}")
    try:
        sw.CloseAllDocuments(True)
    except Exception:  # noqa: BLE001
        pass
    return 0 if size else 1


if __name__ == "__main__":
    raise SystemExit(main())
