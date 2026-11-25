"""Compare the old implementation with the migrated package field by field.

The 12 behaviour cases prove the verdicts agree. This proves the reports agree
too: same checks, same order, same severity, same detail text. Timestamps,
absolute paths and file digests are normalised away because they legitimately
differ between runs.

**Status: retired baseline.** The frozen legacy copy this compares against was
deleted once the migration was verified, because two copies of a delivery
judgement is the drift this whole refactor set out to remove. The script stays
as the method: point `CAD_DELIVER_LEGACY` at any older copy of
`dsh-sw-cad/lib/deliver.py` to re-run the comparison.

Evidence anchor for the migration itself: 12 cases (good / bad / empty / flat /
hollow / dwg / dxf_ok / dxf_half_ok / dxf_half_bad / dxf_bad_dim / pdf_ok /
pdf_bad) compared field by field, `PARITY OK` on 2026-11-25 before the baseline
was retired.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PY = sys.executable
LEGACY = Path(os.environ.get(
    "CAD_DELIVER_LEGACY",
    r"D:\dsh_plugins\dsh-sw-cad\lib\deliver_legacy.py",
))
NEW_CLI = Path(r"D:\dsh_plugins\cad-deliver-mcp\src\cad_deliver\cli.py")

NORMALISE = [
    (re.compile(r"[A-Za-z]:\\\\?[^\s\"']+"), "<PATH>"),
    (re.compile(r"/tmp/[^\s\"']+"), "<PATH>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}T[\d:+\-]+"), "<TIME>"),
]


def normalise(text: str) -> str:
    for pattern, replacement in NORMALISE:
        text = pattern.sub(replacement, text)
    return text


def step_file(target: Path, schema: str, count: int):
    lines = [
        "ISO-10303-21;", "HEADER;", "FILE_DESCRIPTION((''),'2;1');",
        "FILE_NAME('part.step','2026-11-25T00:00:00',(''),(''),'','','');",
        f"FILE_SCHEMA(('{schema}'));", "ENDSEC;", "DATA;",
    ]
    for i in range(1, count + 1):
        lines.append(f"#{i}=CARTESIAN_POINT('',({i}.0,0.0,0.0));")
    lines += ["ENDSEC;", "END-ISO-10303-21;", ""]
    target.write_text("\n".join(lines), encoding="utf-8")


def _build_dxf(target: Path, notes: list[str], *, bad_dim: bool = False):
    import ezdxf

    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4
    doc.layers.add("粗实线", lineweight=50)
    doc.layers.add("细实线", lineweight=13)
    # Single text style so drawing.fonts ordering is deterministic across processes.
    doc.styles.add("GB", font="fangsong.ttf")

    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (100, 0), (100, 60), (0, 60)], close=True, dxfattribs={"layer": "粗实线"})
    if bad_dim:
        msp.add_linear_dim(
            base=(0, -12),
            p1=(0, 0),
            p2=(100, 0),
            dimstyle="Standard",
            text="80",
            override={"text_midpoint": (50.0, -12.0)},
        ).render()
        msp.add_linear_dim(
            base=(0, -12),
            p1=(0, 0),
            p2=(100, 0),
            dimstyle="Standard",
            text="<>",
            override={"text_midpoint": (50.5, -12.0)},
        ).render()
    else:
        msp.add_linear_dim(base=(0, -12), p1=(0, 0), p2=(100, 0)).render()

    blk = doc.blocks.new("TITLEBLOCK")
    blk.add_lwpolyline([(0, 0), (180, 0), (180, 40), (0, 40)], close=True)
    sheet = doc.layouts.get("Layout1")
    sheet.dxf.paper_width, sheet.dxf.paper_height = 420, 297
    sheet.add_blockref("TITLEBLOCK", (10, 10))
    for i, text in enumerate(notes):
        sheet.add_text(text, dxfattribs={"height": 4, "style": "GB"}).set_placement((20, 34 - i * 8))
    doc.saveas(str(target))


def _build_pdf(target: Path, *, width_mm: float, height_mm: float, text: str | None):
    import pymupdf

    doc = pymupdf.open()
    w_pt = width_mm * 72.0 / 25.4
    h_pt = height_mm * 72.0 / 25.4
    page = doc.new_page(width=w_pt, height=h_pt)
    if text:
        page.draw_rect(pymupdf.Rect(20, 20, w_pt - 20, h_pt - 20))
        for line_idx in range(12):
            page.insert_text((40, 60 + line_idx * 16), f"{text} [{line_idx}]")
    else:
        # Non-empty drawing content without text so the file exceeds MIN_BYTES["pdf"].
        for i in range(60):
            page.draw_line((10, 10 + i * 3), (w_pt - 10, 10 + i * 3))
    doc.save(str(target))
    doc.close()


def build_fixtures(root: Path):
    """Build golden comparison fixtures for STEP, DWG, and available DXF/PDF readers."""
    cases = {}

    good = root / "good"
    good.mkdir()
    step_file(good / "part.step", "AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }", 300)
    (good / "part_review_report.json").write_text(
        json.dumps({
            "evaluation": {"status": "pass", "issues": [], "score": 92},
            "checks": {"previews_created": True, "previews_not_blank": True,
                       "expected_outputs_exist": True},
        }), encoding="utf-8")
    (good / "part_isometric.bmp").write_bytes(b"\x00" * 2048)
    cases["good"] = (good, ["--require", "step"])

    bad = root / "bad"
    bad.mkdir()
    step_file(bad / "part.step", "CONFIG_CONTROL_DESIGN", 40)
    (bad / "part_review_report.json").write_text(
        json.dumps({"evaluation": {"status": "fail", "issues": ["front view empty"]}}),
        encoding="utf-8")
    cases["bad"] = (bad, [])

    empty = root / "empty"
    empty.mkdir()
    cases["empty"] = (empty, [])

    flat = root / "flat"
    flat.mkdir()
    lines = [
        "ISO-10303-21;", "HEADER;", "FILE_DESCRIPTION((''),'2;1');",
        "FILE_NAME('flat.step','2026-11-25T00:00:00',(''),(''),'','','');",
        "FILE_SCHEMA(('AUTOMOTIVE_DESIGN'));", "ENDSEC;", "DATA;",
    ]
    for i in range(1, 201):
        lines.append(f"#{i}=CARTESIAN_POINT('',(0.0,0.0,0.0));")
    lines += ["ENDSEC;", "END-ISO-10303-21;", ""]
    (flat / "flat.step").write_text("\n".join(lines), encoding="utf-8")
    cases["flat"] = (flat, [])

    hollow = root / "hollow"
    hollow.mkdir()
    step_file(hollow / "part.step", "AUTOMOTIVE_DESIGN", 300)
    (hollow / "part_review_report.json").write_text(
        json.dumps({"evaluation": {"status": "pass", "issues": []}}), encoding="utf-8")
    cases["hollow"] = (hollow, [])

    dwg = root / "dwg"
    dwg.mkdir()
    (dwg / "blank.dwg").write_bytes(b"AC1032" + b"\x00" * 4000)
    cases["dwg"] = (dwg, ["--require", "drawing"])

    try:
        import ezdxf  # noqa: F401
        has_ezdxf = True
    except Exception:
        has_ezdxf = False

    if has_ezdxf:
        dxf_ok = root / "dxf_ok"
        dxf_ok.mkdir()
        _build_dxf(dxf_ok / "ok.dxf", ["比例 1:2", "图名 端盖"])
        cases["dxf_ok"] = (dxf_ok, ["--require", "drawing"])

        dxf_half_ok = root / "dxf_half_ok"
        dxf_half_ok.mkdir()
        _build_dxf(dxf_half_ok / "half_ok.dxf", ["比例 1:2", "材料 45", "φ40H7/g6", "Ra 1.6"])
        cases["dxf_half_ok"] = (dxf_half_ok, ["--profile", "half"])

        dxf_half_bad = root / "dxf_half_bad"
        dxf_half_bad.mkdir()
        _build_dxf(dxf_half_bad / "half_bad.dxf", ["比例 1:2", "材料 40CrMnMoX", "φ40H7/z9", "Ra 2.0"])
        cases["dxf_half_bad"] = (dxf_half_bad, ["--profile", "half"])

        dxf_bad_dim = root / "dxf_bad_dim"
        dxf_bad_dim.mkdir()
        _build_dxf(dxf_bad_dim / "bad_dim.dxf", ["比例 1:2", "图名 轴"], bad_dim=True)
        cases["dxf_bad_dim"] = (dxf_bad_dim, [])

    try:
        import pymupdf  # noqa: F401
        has_pymupdf = True
    except Exception:
        has_pymupdf = False

    if has_pymupdf:
        pdf_ok = root / "pdf_ok"
        pdf_ok.mkdir()
        _build_pdf(
            pdf_ok / "ok.pdf",
            width_mm=420.0,
            height_mm=297.0,
            text="PART 001 SCALE 1:2 MATERIAL 45 " + ("0123456789 " * 30),
        )
        cases["pdf_ok"] = (pdf_ok, ["--require", "pdf"])

        pdf_bad = root / "pdf_bad"
        pdf_bad.mkdir()
        _build_pdf(pdf_bad / "bad.pdf", width_mm=400.0, height_mm=280.0, text=None)
        cases["pdf_bad"] = (pdf_bad, ["--require", "pdf"])

    return cases


def run(script: Path, folder: Path, extra, out: Path, as_module: bool = False):
    env = dict(os.environ)
    env["DSH_SW_CAD_DWG_CONVERTER"] = ""       # force the no-converter path
    # The package uses relative imports, so it has to be run as a module. The
    # legacy copy is a standalone script and runs as a file.
    cmd = ([PY, "-m", "cad_deliver.cli"] if as_module else [PY, str(script)])
    res = subprocess.run(
        [*cmd, str(folder), "--out", str(out), *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
    )
    report = None
    if out.exists():
        report = json.loads(out.read_text(encoding="utf-8"))
    return res.returncode, normalise(res.stdout), report, res.stderr


def shape(report):
    """The parts that must be identical, with volatile fields dropped."""
    if report is None:
        return None
    return {
        "verdict": report.get("verdict"),
        "required": report.get("required"),
        "missing": report.get("missing"),
        "not_checked": report.get("not_checked"),
        "counts": {k: v for k, v in (report.get("counts") or {}).items()},
        "blocked": [
            {"id": b.get("id"), "detail": normalise(b.get("detail", ""))}
            for b in report.get("blocked", [])
        ],
        "files": [
            {
                "kind": f.get("kind"),
                "checks": [
                    {
                        "id": c.get("id"),
                        "ok": c.get("ok"),
                        "severity": c.get("severity"),
                        "detail": normalise(c.get("detail", "")),
                    }
                    for c in f.get("checks", [])
                ],
            }
            for f in report.get("files", [])
        ],
    }


def main():
    if not LEGACY.is_file():
        print("baseline retired: no legacy copy at")
        print(f"  {LEGACY}")
        print("Set CAD_DELIVER_LEGACY to an older dsh-sw-cad/lib/deliver.py to compare.")
        print("Parity was proven on 2026-11-25 across 12 cases before the copy was removed.")
        return 0

    root = Path(tempfile.mkdtemp(prefix="cad-deliver-golden-"))
    cases = build_fixtures(root)
    failures = 0

    reports = root / "reports"
    reports.mkdir()

    for name, (folder, extra) in cases.items():
        # The report must land outside the folder being inspected, or the second
        # run sees the first run's output and the file counts never match.
        old_code, old_stdout, old_report, _old_err = run(
            LEGACY, folder, extra, reports / f"{name}-old.json"
        )
        new_code, new_stdout, new_report, new_err = run(
            NEW_CLI, folder, extra, reports / f"{name}-new.json", as_module=True
        )

        old_shape, new_shape = shape(old_report), shape(new_report)
        same_report = old_shape == new_shape
        same_code = old_code == new_code
        same_stdout = old_stdout.strip() == new_stdout.strip()

        status = "SAME" if (same_report and same_code and same_stdout) else "DIFF"
        if status == "DIFF":
            failures += 1
        print(f"{name:<12} exit {old_code}/{new_code}  report={'ok' if same_report else 'DIFF'} "
              f"stdout={'ok' if same_stdout else 'DIFF'}  -> {status}")

        if status == "DIFF":
            if new_err.strip():
                print(f"    new stderr: {new_err.strip().splitlines()[-1]}")
            if not same_code:
                print(f"    exit: legacy={old_code} new={new_code}")
            if not same_report:
                old_ids = [c["id"] for f in (old_shape or {}).get("files", []) for c in f["checks"]]
                new_ids = [c["id"] for f in (new_shape or {}).get("files", []) for c in f["checks"]]
                if old_ids != new_ids:
                    print(f"    check ids differ:\n      legacy={old_ids}\n      new   ={new_ids}")
                else:
                    for fo, fn in zip((old_shape or {}).get("files", []), (new_shape or {}).get("files", [])):
                        for co, cn in zip(fo["checks"], fn["checks"]):
                            if co != cn:
                                print(f"    {co['id']}:\n      legacy={co}\n      new   ={cn}")
                for key in ("verdict", "counts", "missing", "not_checked"):
                    if (old_shape or {}).get(key) != (new_shape or {}).get(key):
                        print(f"    {key}: legacy={(old_shape or {}).get(key)} new={(new_shape or {}).get(key)}")
            if not same_stdout:
                ol, nl = old_stdout.strip().splitlines(), new_stdout.strip().splitlines()
                for i, (a, b) in enumerate(zip(ol, nl)):
                    if a != b:
                        print(f"    stdout line {i}:\n      legacy={a!r}\n      new   ={b!r}")
                        break

    print(f"\n{'PARITY OK' if failures == 0 else f'{failures} case(s) differ'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
