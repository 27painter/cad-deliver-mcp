"""Batch-export SolidWorks parts to DXF through the native pipeline.

Every API call below was verified against this SolidWorks 2025 build by reflecting
`SolidWorks.Interop.swconst.dll` and `SolidWorks.Interop.sldworks.dll`, because
late binding hides signatures and several textbook calls silently return None here:

| what | this build requires | the textbook call that fails |
|---|---|---|
| standard views | `Create1stAngleViews2(model)` | `CreateDrawViewFromModelView3(p, "*Front", …)` -> None |
| model dimensions | `InsertModelAnnotations3(Option, Types, AllViews, DupDims, HiddenDims, UsePlacement)` — **6 args** | 7 args -> "invalid number of arguments" |
| import source | `swImportModelItemsFromEntireModel = 0` | 2 means *selected component* |
| units | `IModelDocExtension.SetUserPreferenceInteger(swUnitsLinear=47, 0, swMM=0)` | `ISldWorks.GetUserPreferenceInteger` -> no such member |
| paper size | `ISheet.SetProperties(...)` (parameter order still unresolved) | — |
| geometry location | `swDxfAllSheetsToPaperSpace=456` must be **off**, or every entity moves to the sheet and model space ends up empty |

No post-processing. The DXF is written by SolidWorks' own `SaveAs`.

Prerequisites you may still have to set by hand (see the caveats printed at the end
of a run): DXF layer mapping under Tools > Options > Export > DXF/DWG, and a sheet
format that carries an attributed title block.

    python scripts/batch_export_sw.py --input tmp_sw_parts --output benchmarks/fixtures/real --limit 1
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

try:
    import win32com.client as win32
except ImportError:  # pragma: no cover
    sys.exit("pywin32 is required: pip install pywin32")

# ---- constants, read from SolidWorks.Interop.swconst.dll -------------------
UNIT_LINEAR = 47            # swUserPreferenceIntegerValue_e.swUnitsLinear
MM = 0                      # swLengthUnit_e.swMM
ENTIRE_MODEL = 0            # swImportModelItemsSource_e.swImportModelItemsFromEntireModel
A3 = 8                      # swDwgPaperSizes_e.swDwgPaperA3size
TOG_PAPERSPACE = 456        # swUserPreferenceToggle_e.swDxfAllSheetsToPaperSpace
TOG_VIEWBLOCK = 806         # swUserPreferenceToggle_e.swDxfExportViewAsBlock


def safe_stem(name: str) -> str:
    folded = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()
    return (folded or "part")[:40]


def export_one(sw, part: Path, template: str, target: Path, a3: bool) -> dict:
    record = {"part": part.name, "ok": False, "views": 0, "dims": 0, "bytes": 0, "note": ""}
    try:
        sw.CloseAllDocuments(True)
        time.sleep(0.3)

        # A freshly dispatched instance is still initialising; OpenDoc answers
        # None until it is ready, so retry rather than reporting a false failure.
        model = None
        for attempt in range(6):
            model = sw.OpenDoc(str(part.resolve()), 1)   # swDocPART; absolute, SW has its own cwd
            if model is not None:
                break
            time.sleep(2.0)
        if model is None:
            record["note"] = "OpenDoc returned None after 6 attempts"
            return record
        time.sleep(0.4)

        # Paper size is the second argument of NewDocument; setting it afterwards
        # via ISheet.SetProperties raises BADPARAMCOUNT through late binding, and
        # ISheet.GetSize needs byref arguments so the failure was invisible.
        sw.NewDocument(template, A3 if a3 else 0, 0, 0)
        time.sleep(0.3)
        drawing = sw.ActiveDoc
        # GetType is a property under late binding, not a method.
        if drawing is None or drawing.GetType != 3:        # swDocDRAWING
            record["note"] = "template did not produce a drawing"
            return record

        # mm on the document, not on the application
        try:
            drawing.Extension.SetUserPreferenceInteger(UNIT_LINEAR, 0, MM)
        except Exception:  # noqa: BLE001
            record["note"] = "units not set; "


        # GB/T 17451 uses first-angle projection
        try:
            drawing.Create1stAngleViews2(model.GetPathName)
            time.sleep(0.3)
            record["views"] = drawing.GetViewCount
        except Exception as exc:  # noqa: BLE001
            record["note"] += f"views failed ({type(exc).__name__}); "

        try:
            drawing.InsertModelAnnotations3(ENTIRE_MODEL, -1, True, True, True, True)
            time.sleep(0.3)
            record["dims"] = drawing.GetDimensionCount() if hasattr(drawing, "GetDimensionCount") else -1
        except Exception as exc:  # noqa: BLE001
            record["note"] += f"annotations failed ({type(exc).__name__}); "

        time.sleep(0.2)
        saved = drawing.SaveAs(str(target))
        if saved and target.is_file():
            record["ok"] = True
            record["bytes"] = target.stat().st_size
        else:
            record["note"] += "SaveAs failed"
    except Exception as exc:  # noqa: BLE001 - one part must not stop the batch
        record["note"] += f"{type(exc).__name__}: {exc}"
    finally:
        # True = discard unsaved changes, so no save prompt can block the next part.
        try:
            sw.CloseAllDocuments(True)
        except Exception:  # noqa: BLE001
            pass
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="Export SolidWorks parts to DXF via COM.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--template",
        default=r"D:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\data\templates\gb.drwdot",
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--no-a3", action="store_true", help="keep the template's paper size")
    args = parser.parse_args()

    source = Path(args.input)
    if not source.is_dir():
        print(f"input folder not found: {source}")
        return 1
    if not Path(args.template).is_file():
        print(f"template not found: {args.template}")
        return 1

    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)

    # One glob, not two: on Windows the filesystem is case-insensitive, so adding
    # *.sldprt and *.SLDPRT returned every file twice.
    parts = sorted(p for p in source.iterdir() if p.suffix.lower() == ".sldprt")
    if args.limit:
        parts = parts[: args.limit]
    if not parts:
        print(f"no .sldprt in {source}")
        return 1

    sw = win32.Dispatch("SldWorks.Application")
    sw.Visible = True
    # Give the application a moment: COM hands back the object before the UI is ready.
    for _ in range(10):
        try:
            sw.RevisionNumber
            break
        except Exception:  # noqa: BLE001
            time.sleep(1.0)
    time.sleep(2.0)

    # Geometry must stay in model space or the gate sees an empty drawing.
    try:
        original_paper = sw.GetUserPreferenceToggle(TOG_PAPERSPACE)
        sw.SetUserPreferenceToggle(TOG_PAPERSPACE, False)
    except Exception:  # noqa: BLE001
        original_paper = None

    print(f"template: {args.template}")
    print(f"input   : {source}  ({len(parts)} part(s))")
    print(f"output  : {output}\n")

    records = []
    for index, part in enumerate(parts, start=1):
        target = (output / f"{safe_stem(part.stem)}.dxf")
        if target.exists() and not args.overwrite:
            print(f"  {index:02d} skip  {part.name}  (exists; --overwrite to replace)")
            continue
        record = export_one(sw, part, args.template, target, not args.no_a3)
        records.append(record)
        mark = "ok  " if record["ok"] else "FAIL"
        print(
            f"  {index:02d} {mark} {part.name:34} views={record['views']} "
            f"bytes={record['bytes']:>7} {record['note'][:40]}"
        )

    if original_paper is not None:
        try:
            sw.SetUserPreferenceToggle(TOG_PAPERSPACE, original_paper)
        except Exception:  # noqa: BLE001
            pass

    exported = sum(1 for r in records if r["ok"])
    print(f"\nexported {exported}/{len(records)}")
    print(
        "\nKnown gaps that block a GB_T_TIER1 pass and are NOT fixable from this script:\n"
        "  * layer mapping (Tools > Options > Export > DXF/DWG) - SolidWorks writes\n"
        "    everything on layer 0 otherwise, which trips E_CONTOUR_ON_ZERO.\n"
        "  * sheet format with an attributed title block - without it the paper space\n"
        "    is empty and E_TITLE_BLOCK fires.\n"
        "  * E_PROFILE_OPEN assumes a single closed contour; a multi-view drawing is\n"
        "    made of open edge segments, so it reports dangling ends by construction."
    )
    print("\nNext: python benchmarks/validate_real.py")
    return 0 if exported == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(main())