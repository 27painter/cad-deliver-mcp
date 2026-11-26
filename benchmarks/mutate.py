"""Inject the five defect classes into compliant samples.

Each mutation is applied to a *different* compliant drawing, so the mutated set
covers the same spread of sheet sizes and orientations as the source set. The
expected code is recorded here rather than guessed later, which is what lets
`recall_by_defect.csv` report per-class recall instead of one aggregate number.

Five classes, four samples each:

| class | injection | expected code | layer |
|---|---|---|---|
| degenerate bbox | geometry collapsed to a point | `E_BBOX_DEGENERATE` | geometry |
| open profile | one side of the outline removed | `E_PROFILE_OPEN` | standard |
| non-standard sheet | paper size 400x280 | `E_SHEET_SIZE` | standard |
| missing title block | INSERT removed / a required ATTRIB blanked | `E_TITLE_BLOCK` | standard |
| wrong layer | DIMENSION onto the outline layer, or outline onto layer 0 | `E_DIM_ON_WRONG_LAYER` / `E_CONTOUR_ON_ZERO` | standard |

The title-block class deliberately keeps the `比例 1:2` text on the sheet. A
keyword-matching checker still sees a title block there; the attribute-level rule
does not. That contrast is the reason this benchmark exists.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import ezdxf
except ImportError:  # pragma: no cover
    sys.exit("ezdxf is required: pip install ezdxf")

ROOT = Path(__file__).resolve().parent
GEN_DIR = ROOT / "fixtures" / "gen"
MUT_DIR = ROOT / "fixtures" / "mutated"
MANIFEST = ROOT / "mutations.json"

OUTLINE_LAYER = "粗实线"
DIM_LAYER = "标注"


# ------------------------------------------------------------------ helpers

def outline_polyline(doc):
    for entity in doc.modelspace():
        if entity.dxftype() == "LWPOLYLINE" and entity.dxf.layer == OUTLINE_LAYER:
            return entity
    raise LookupError("no outline polyline to mutate")


def paper_layout(doc):
    for name in doc.layouts.names():
        if name.lower() != "model":
            return doc.layouts.get(name)
    raise LookupError("no paper-space layout")


# ------------------------------------------------------------------ mutations

def collapse_bbox(doc):
    """Everything into one point: the export kept its layers and lost its geometry."""
    msp = doc.modelspace()
    for entity in list(msp):
        msp.delete_entity(entity)
    msp.add_lwpolyline(
        [(0.0, 0.0), (0.0, 0.0), (0.0, 0.0)],
        close=True,
        dxfattribs={"layer": OUTLINE_LAYER},
    )


def open_profile(doc):
    """Drop one side, leaving two dangling ends."""
    poly = outline_polyline(doc)
    points = [(float(p[0]), float(p[1])) for p in poly.get_points("xy")]
    # A flag-off ring repeats its first vertex; drop that before truncating.
    if len(points) > 2 and abs(points[0][0] - points[-1][0]) < 1e-6 and abs(points[0][1] - points[-1][1]) < 1e-6:
        points = points[:-1]
    poly.set_points(points[:3], format="xy")
    poly.closed = False                          # property, not a set_points argument
    poly.dxf.flags = poly.dxf.flags & ~1         # clear the closed bit in the DXF too


def bad_sheet(doc):
    layout = paper_layout(doc)
    layout.dxf.paper_width = 400.0
    layout.dxf.paper_height = 280.0


def drop_title_block(doc):
    """Remove the INSERT but leave the 比例 text: the keyword heuristic still passes."""
    layout = paper_layout(doc)
    for entity in list(layout):
        if entity.dxftype() == "INSERT":
            layout.delete_entity(entity)


def blank_title_block_attr(doc):
    """Keep the block, empty one required field."""
    layout = paper_layout(doc)
    for entity in list(layout):
        if entity.dxftype() != "INSERT":
            continue
        for attrib in entity.attribs:
            if attrib.dxf.tag in ("图号", "图名", "比例"):
                attrib.dxf.text = ""
                return
    raise LookupError("no title block attributes to blank")


def dim_on_outline_layer(doc):
    for entity in doc.modelspace():
        if entity.dxftype() == "DIMENSION":
            entity.dxf.layer = OUTLINE_LAYER
            return
    raise LookupError("no dimension to move")


def contour_on_layer_zero(doc):
    """Move the whole visible outline onto layer 0, where nothing is classified."""
    moved = 0
    for entity in doc.modelspace():
        if entity.dxftype() in ("LWPOLYLINE", "CIRCLE", "LINE", "ARC") and entity.dxf.layer == OUTLINE_LAYER:
            entity.dxf.layer = "0"
            moved += 1
    if not moved:
        raise LookupError("no outline geometry to move")


# ------------------------------------------------------------------ plan

# (output name, source sample, expected code, layer, mutation)
PLAN = [
    ("mut_01_bbox_point",      "gen_01_a4_portrait",  "E_BBOX_DEGENERATE",     "geometry", collapse_bbox),
    ("mut_02_bbox_point",      "gen_04_a3_landscape", "E_BBOX_DEGENERATE",     "geometry", collapse_bbox),
    ("mut_03_bbox_point",      "gen_07_a1_portrait",  "E_BBOX_DEGENERATE",     "geometry", collapse_bbox),
    ("mut_04_bbox_point",      "gen_10_a0_landscape", "E_BBOX_DEGENERATE",     "geometry", collapse_bbox),

    ("mut_05_profile_open",    "gen_03_a3_portrait",  "E_PROFILE_OPEN",        "standard", open_profile),
    ("mut_06_profile_open",    "gen_06_a2_landscape", "E_PROFILE_OPEN",        "standard", open_profile),
    ("mut_07_profile_open",    "gen_02_a4_landscape", "E_PROFILE_OPEN",        "standard", open_profile),
    ("mut_08_profile_open",    "gen_09_a0_portrait",  "E_PROFILE_OPEN",        "standard", open_profile),

    ("mut_09_sheet_size",      "gen_05_a2_portrait",  "E_SHEET_SIZE",          "standard", bad_sheet),
    ("mut_10_sheet_size",      "gen_08_a1_landscape", "E_SHEET_SIZE",          "standard", bad_sheet),
    ("mut_11_sheet_size",      "gen_11_a3_tol_plus",  "E_SHEET_SIZE",          "standard", bad_sheet),
    ("mut_12_sheet_size",      "gen_13_a3_flag_off",  "E_SHEET_SIZE",          "standard", bad_sheet),

    ("mut_13_titleblock_gone", "gen_01_a4_portrait",  "E_TITLE_BLOCK",         "standard", drop_title_block),
    ("mut_14_titleblock_gone", "gen_06_a2_landscape", "E_TITLE_BLOCK",         "standard", drop_title_block),
    ("mut_15_titleblock_blank","gen_04_a3_landscape", "E_TITLE_BLOCK_BLANK",   "standard", blank_title_block_attr),
    ("mut_16_titleblock_blank","gen_12_a4_tol_minus", "E_TITLE_BLOCK_BLANK",   "standard", blank_title_block_attr),

    ("mut_17_dim_wrong_layer", "gen_03_a3_portrait",  "E_DIM_ON_WRONG_LAYER",  "standard", dim_on_outline_layer),
    ("mut_18_dim_wrong_layer", "gen_09_a0_portrait",  "E_DIM_ON_WRONG_LAYER",  "standard", dim_on_outline_layer),
    ("mut_19_contour_on_zero", "gen_05_a2_portrait",  "E_CONTOUR_ON_ZERO",     "standard", contour_on_layer_zero),
    ("mut_20_contour_on_zero", "gen_14_a2_tol_plus",  "E_CONTOUR_ON_ZERO",     "standard", contour_on_layer_zero),
]


def main() -> int:
    MUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in MUT_DIR.glob("*.dxf"):
        old.unlink()

    sys.path.insert(0, str(ROOT.parent / "src"))
    from cad_deliver.pipeline import verify_file

    records = []
    failures = 0

    for name, source, expected, layer, mutation in PLAN:
        src = GEN_DIR / f"{source}.dxf"
        if not src.is_file():
            print(f"  MISSING source {source}")
            failures += 1
            continue

        doc = ezdxf.readfile(src)
        try:
            mutation(doc)
        except (LookupError, AttributeError, ValueError) as exc:
            print(f"  FAIL {name:22} mutation: {exc}")
            failures += 1
            continue

        dst = MUT_DIR / f"{name}.dxf"
        doc.saveas(dst)

        # Verify the injection actually produces what was intended. A mutation
        # that silently does nothing would show up later as a missing recall
        # point and be blamed on the gatekeeper.
        verdict = verify_file(str(dst), "GB_T_TIER1")
        codes = [r.code for r in verdict.rules if not r.ok]
        intercepted = verdict.verdict.value != "PASS"
        exact = expected in codes

        status = "ok  " if exact else ("part" if intercepted else "MISS")
        if not intercepted:
            failures += 1
        print(
            f"  {status} {name:22} {expected:24} "
            f"verdict={verdict.verdict.value:7} codes={','.join(codes) or '-'}"
        )

        records.append(
            {
                "name": name,
                "path": f"fixtures/mutated/{name}.dxf",
                "source": source,
                "expected_code": expected,
                "expected_layer": layer,
                "observed_codes": codes,
                "intercepted": intercepted,
                "exact_match": exact,
                "size": dst.stat().st_size,
            }
        )

    MANIFEST.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    exact = sum(1 for r in records if r["exact_match"])
    print(f"\nmutate: {len(records)} injected, {exact} exact, {sum(1 for r in records if r['intercepted'])} intercepted")
    print(f"samples: {MUT_DIR}")
    print(f"manifest: {MANIFEST}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())