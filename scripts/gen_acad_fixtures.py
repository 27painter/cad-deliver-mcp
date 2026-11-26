"""Generate 15 GB-compliant engineering drawings through AutoCAD's own API.

Uses `AutoCADSession` from the installed autocad-automation skill: that class wraps
every COM call this needs, including the SAFEARRAY conversion and the
RPC_E_CALL_REJECTED back-off. Reimplementing them here produced
DISP_E_BADPARAMCOUNT ("invalid number of arguments") on every call, because these
ActiveX signatures do not survive pywin32 late binding the way the argument counts
suggest.

AutoCAD's own Document.Export writes each DXF through `session.export_dxf`.
Nothing here writes a DXF by hand or edits one afterwards.

The title block needs ATTDEF entities and COM exposes no attribute-definition call
under late binding, so the block is defined with an entmake sequence sent through
the command line - AutoCAD executing LISP, not this program writing a file.

    python scripts/gen_acad_fixtures.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pythoncom
from win32com.client import VARIANT

SKILL = Path(
    r"C:\Users\27painter\.dsh\skills\solidworks-automation\subskills\autocad-automation\scripts"
)
sys.path.insert(0, str(SKILL))

from acad_session import AutoCADSession  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "benchmarks" / "fixtures" / "real"

PAPERS = {
    "A4": ("psk:ISOA4", 297.0, 210.0),
    "A3": ("psk:ISOA3", 420.0, 297.0),
    "A2": ("psk:ISOA2", 594.0, 420.0),
}

PARTS = [
    (210, 130, 25, 12, "A4", "轴承座", "GB-0001", "1:1"),
    (240, 150, 30, 14, "A3", "端盖", "GB-0002", "1:2"),
    (180, 110, 20, 10, "A3", "法兰盘", "GB-0003", "1:1"),
    (300, 180, 35, 16, "A3", "连接板", "GB-0004", "1:2"),
    (160, 100, 18, 9, "A4", "支架", "GB-0005", "2:1"),
    (270, 160, 32, 15, "A3", "衬套", "GB-0006", "1:1"),
    (200, 120, 22, 11, "A4", "压板", "GB-0007", "1:2"),
    (350, 210, 40, 18, "A2", "导轨", "GB-0008", "1:2"),
    (190, 115, 21, 10, "A3", "定位销", "GB-0009", "2:1"),
    (230, 140, 28, 13, "A4", "过渡块", "GB-0010", "1:1"),
    (260, 155, 30, 14, "A3", "底座", "GB-0011", "1:2"),
    (170, 105, 19, 9, "A2", "轴套", "GB-0012", "2:1"),
    (290, 175, 34, 16, "A3", "盖板", "GB-0013", "1:1"),
    (220, 135, 26, 12, "A4", "固定架", "GB-0014", "1:2"),
    (310, 190, 36, 17, "A2", "齿轮坯", "GB-0015", "1:2"),
]

LAYERS = (
    ("粗实线", 7, "Continuous"),
    ("虚线", 2, "HIDDEN"),
    ("中心线", 1, "CENTER"),
    ("标注", 3, "Continuous"),
    ("文字", 7, "Continuous"),
    ("图框", 7, "Continuous"),
)


def dbl(values):
    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, tuple(float(v) for v in values))


def define_title_block(session, fw, fh, title, drawing_no, scale):
    """Define GB-TITLE holding only the three attributed fields.

    The frame lines already sit in paper space as plain entities, so the block does
    not need them. Keeping it this small matters: a single (progn ...) sent through
    the command line works, while the same sequence with a dozen shapes is silently
    truncated and no block is created at all.
    """
    tb_w = 180.0
    bx = fw - 25.0 - tb_w
    by = 5.0
    parts = ['(entmake (list (cons 0 "BLOCK") (cons 2 "GB-TITLE") (cons 70 0) (cons 10 (list 0.0 0.0 0.0))))']
    for tag, dx, default in (("图名", 4.0, title), ("图号", 64.0, drawing_no), ("比例", 124.0, scale)):
        parts.append(
            f'(entmake (list (cons 0 "ATTDEF") (cons 8 "文字") '
            f'(cons 10 (list {bx + dx} {by + 8.0} 0.0)) (cons 40 4.0) '
            f'(cons 1 "{default}") (cons 2 "{tag}") (cons 3 "{tag}") (cons 70 0)))'
        )
    parts.append('(entmake (list (cons 0 "ENDBLK")))')
    session.send_command("(progn " + " ".join(parts) + ")")
    time.sleep(0.6)


def build_one(session, index, spec):
    width, height, r1, r2, paper_key, title, drawing_no, scale = spec
    paper_name, fw, fh = PAPERS[paper_key]

    session.new_document()
    time.sleep(0.5)
    for name, color, linetype in LAYERS:
        session.create_layer(name, color=color, linetype=linetype)

    x0, y0 = 40.0, 40.0
    x1, y1 = x0 + width, y0 + height
    session.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], closed=True, layer="粗实线")
    session.add_circle((x0 + width * 0.3, y0 + height / 2), float(r1), layer="粗实线")
    session.add_circle((x0 + width * 0.75, y0 + height / 2), float(r2), layer="粗实线")
    session.add_line((x0 - 5, y0 + height / 2), (x1 + 5, y0 + height / 2), layer="中心线")
    session.add_line((x0 + width / 2, y0 - 5), (x0 + width / 2, y1 + 5), layer="中心线")
    session.add_dim_rotated((x0, y0), (x1, y0), (x0 + width / 2, y0 - 15), 0.0, layer="标注")
    session.add_dim_rotated((x1, y0), (x1, y1), (x1 + 15, y0 + height / 2), 0.0, layer="标注")

    doc = session.active_document()
    try:
        doc.ActiveLayout = doc.Layouts.Item("布局1")
    except Exception:
        pass
    psp = doc.PaperSpace
    for pts in (
        [(0, 0), (fw, 0), (fw, fh), (0, fh)],
        [(25, 5), (fw - 5, 5), (fw - 5, fh - 5), (25, fh - 5)],
    ):
        poly = psp.AddLightWeightPolyline(dbl([c for p in pts for c in p]))
        poly.Closed = True
        poly.Layer = "图框"

    for label, dx in (("图名", 4.0), ("图号", 64.0), ("比例", 124.0)):
        tag_text = psp.AddText(
            label, dbl([fw - 25.0 - 180.0 + dx, 5.0 + 44.0, 0.0]), 3.5
        )
        tag_text.Layer = "文字"

    define_title_block(session, fw, fh, title, drawing_no, scale)

    # IAcadPaperSpace exposes no InsertBlock through late binding (AttributeError),
    # so the reference is inserted with entmake. Group code 66=1 on the INSERT is
    # what tells AutoCAD attributes follow; without it the ATTRIBs are written but
    # never bound to the reference, and the export carries a block with no fields.
    tb_w = 180.0
    bx = fw - 25.0 - tb_w
    by = 5.0
    attrs = " ".join(
        f'(entmake (list (cons 0 "ATTRIB") (cons 8 "文字") '
        f'(cons 10 (list {bx + dx} {by + 8.0} 0.0)) (cons 40 4.0) '
        f'(cons 1 "{value}") (cons 2 "{tag}") (cons 70 0)))'
        for tag, dx, value in (
            ("图名", 4.0, title),
            ("图号", 64.0, drawing_no),
            ("比例", 124.0, scale),
        )
    )
    session.send_command(
        '(progn (entmake (list (cons 0 "INSERT") (cons 8 "图框") (cons 2 "GB-TITLE") '
        '(cons 66 1) (cons 10 (list 0.0 0.0 0.0)))) '
        + attrs
        + ' (entmake (list (cons 0 "SEQEND") (cons 8 "图框"))))'
    )
    time.sleep(0.5)

    scale_text = psp.AddText("比例 " + scale, dbl([fw - 130.0, fh - 80.0, 0.0]), 3.5)
    scale_text.Layer = "文字"

    try:
        doc.ActiveLayout.CanonicalMediaName = paper_name
    except Exception as exc:
        print(f"      paper: {type(exc).__name__}")

    target = OUT / ("PART-%03d.dxf" % index)
    if target.exists():
        target.unlink()
    session.export_dxf(str(target))
    session.close_document(save_changes=False)
    return target


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    session = AutoCADSession()
    session.connect()
    session.ensure_visible()
    print("AutoCAD connected")

    made = 0
    for index, spec in enumerate(PARTS, start=1):
        try:
            target = build_one(session, index, spec)
            size = target.stat().st_size if target.exists() else 0
            print(f"  PART-{index:03d}  {spec[5]:6}  {spec[4]}  {spec[7]:4}  {size:>7} B")
            made += 1
        except Exception as exc:
            print(f"  PART-{index:03d}  FAILED: {type(exc).__name__}: {exc}")
            try:
                session.close_document(save_changes=False)
            except Exception:
                pass

    print(f"\ngenerated {made}/{len(PARTS)}")
    return 0 if made == len(PARTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
