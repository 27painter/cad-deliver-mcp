"""Inject the five defect classes into compliant samples.

Two design points that matter for what the numbers mean:

**Sources are mixed.** Mutations are drawn alternately from `fixtures/real/` (real
SolidWorks/NX exports) and `fixtures/gen/` (programmatic drawings) when the real
set exists. Injecting only into generated drawings would invite the objection
that the rules were tuned on clean geometry and never met a real export's noise.
With `real/` empty the plan falls back to generated sources, and says so.

**The bbox mutation keeps every entity.** An earlier version deleted the model
space, which meant `drawing.entities` failed first and the pre-existing check was
credited with the interception. Now all geometry is flattened onto `y = 0`: the
entity count still passes, the model space is still "full", and only the extent
has collapsed. That isolates `geo.bbox_degenerate` from every check that came
before it.

Five classes, four samples each:

| class | injection | expected code | layer |
|---|---|---|---|
| degenerate bbox | y of every coordinate flattened to 0 | `E_BBOX_DEGENERATE` | geometry |
| open profile | one side of the outline removed | `E_PROFILE_OPEN` | standard |
| non-standard sheet | paper size 400x280 | `E_SHEET_SIZE` | standard |
| missing title block | INSERT removed / a required ATTRIB blanked | `E_TITLE_BLOCK` | standard |
| wrong layer | DIMENSION onto the outline layer, or outline onto layer 0 | `E_DIM_ON_WRONG_LAYER` / `E_CONTOUR_ON_ZERO` | standard |

The title-block class deliberately keeps the `比例 1:2` text on the sheet: a
keyword-matching checker still sees a title block there, the attribute-level rule
does not.
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
FIXTURES = ROOT / "fixtures"
GEN_DIR = FIXTURES / "gen"
REAL_DIR = FIXTURES / "real"
MUT_DIR = FIXTURES / "mutated"
MANIFEST = ROOT / "mutations.json"

OUTLINE_LAYER = "粗实线"
DIM_LAYER = "标注"


# ------------------------------------------------------------------ helpers

def outline_polyline(doc):
    for entity in doc.modelspace():
        if entity.dxftype() == "LWPOLYLINE" and entity.dxf.layer == OUTLINE_LAYER:
            return entity
    raise LookupError("no outline polyline on the outline layer")


def paper_layout(doc):
    for name in doc.layouts.names():
        if name.lower() != "model":
            return doc.layouts.get(name)
    raise LookupError("no paper-space layout")


def _flatten(entity) -> bool:
    """Move one entity onto the origin without changing what it is.

    Everything collapses to (0, 0). A first version only zeroed `y`, which left
    circles with their radius intact: y still spanned ±r, the extent never
    collapsed, and the mutation silently did nothing. Curves therefore get a
    near-zero radius rather than a zero one, because a zero-radius circle is not
    a circle and ezdxf refuses to write it.
    """
    kind = entity.dxftype()
    try:
        if kind == "LWPOLYLINE":
            points = [(0.0, 0.0) for _ in entity.get_points("xy")]
            if len(points) < 2:
                return False
            entity.set_points(points, format="xy")
            return True
        if kind == "POLYLINE":
            for vertex in entity.vertices:
                vertex.dxf.location = (0.0, 0.0, 0.0)
            return True
        if kind == "LINE":
            entity.dxf.start = (0.0, 0.0, 0.0)
            entity.dxf.end = (0.0, 0.0, 0.0)
            return True
        if kind in ("CIRCLE", "ARC"):
            entity.dxf.center = (0.0, 0.0, 0.0)
            entity.dxf.radius = 1e-9
            return True
        if kind == "DIMENSION":
            touched = False
            for name in ("defpoint", "defpoint2", "defpoint3", "defpoint4", "defpoint5"):
                if entity.dxf.hasattr(name):
                    entity.dxf.set(name, (0.0, 0.0, 0.0))
                    touched = True
            # A rendered dimension carries its graphics in an anonymous block and
            # the bounding box reads that block, not the def points. Dropping the
            # reference forces the box to be rebuilt from the (now collapsed)
            # definition points.
            if entity.dxf.hasattr("geometry"):
                entity.dxf.discard("geometry")
            return touched
        if kind in ("TEXT", "MTEXT", "ATTRIB"):
            if entity.dxf.hasattr("insert"):
                entity.dxf.insert = (0.0, 0.0, 0.0)
            if entity.dxf.hasattr("align_point"):
                entity.dxf.align_point = (0.0, 0.0, 0.0)
            # Text has extent from its height; collapsing the insert alone leaves
            # a 3.5 mm tall glyph box behind.
            if entity.dxf.hasattr("height"):
                entity.dxf.height = 1e-9
            if entity.dxf.hasattr("char_height"):
                entity.dxf.char_height = 1e-9
            return bool(entity.dxf.hasattr("insert"))
    except Exception:
        return False
    return False


# ------------------------------------------------------------------ mutations

def collapse_bbox(doc):
    """Flatten the drawing onto a line: full of entities, no extent.

    Nothing is deleted. The point is to separate "the export dropped the geometry"
    (empty model space, caught by an old check) from "the geometry is there but
    degenerate" (only the extent rule can see it).
    """
    msp = doc.modelspace()
    flattened = 0
    for entity in msp:
        if _flatten(entity):
            flattened += 1
    if not flattened:
        raise LookupError("nothing could be flattened")


def open_profile(doc):
    """Drop one side, leaving two dangling ends."""
    poly = outline_polyline(doc)
    points = [(float(p[0]), float(p[1])) for p in poly.get_points("xy")]
    cap = len(points)
    if cap > 2 and abs(points[0][0] - points[-1][0]) < 1e-6 and abs(points[0][1] - points[-1][1]) < 1e-6:
        points = points[:-1]
    poly.set_points(points[:3], format="xy")
    poly.closed = False
    poly.dxf.flags = poly.dxf.flags & ~1


def bad_sheet(doc):
    layout = paper_layout(doc)
    layout.dxf.paper_width = 400.0
    layout.dxf.paper_height = 280.0


def drop_title_block(doc):
    """Remove the INSERT but leave the 比例 text: the keyword heuristic still passes."""
    layout = paper_layout(doc)
    removed = 0
    for entity in list(layout):
        if entity.dxftype() == "INSERT":
            layout.delete_entity(entity)
            removed += 1
    if not removed:
        raise LookupError("no INSERT on the sheet")


def blank_title_block_attr(doc):
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
    moved = 0
    for entity in doc.modelspace():
        if entity.dxftype() in ("LWPOLYLINE", "CIRCLE", "LINE", "ARC") and entity.dxf.layer == OUTLINE_LAYER:
            entity.dxf.layer = "0"
            moved += 1
    if not moved:
        raise LookupError("no outline geometry to move")


# (label, mutation, expected code, layer) — four of each
MUTATIONS = [
    ("bbox_point",       collapse_bbox,         "E_BBOX_DEGENERATE",    "geometry"),
    ("bbox_point",       collapse_bbox,         "E_BBOX_DEGENERATE",    "geometry"),
    ("bbox_point",       collapse_bbox,         "E_BBOX_DEGENERATE",    "geometry"),
    ("bbox_point",       collapse_bbox,         "E_BBOX_DEGENERATE",    "geometry"),

    ("profile_open",     open_profile,          "E_PROFILE_OPEN",       "standard"),
    ("profile_open",     open_profile,          "E_PROFILE_OPEN",       "standard"),
    ("profile_open",     open_profile,          "E_PROFILE_OPEN",       "standard"),
    ("profile_open",     open_profile,          "E_PROFILE_OPEN",       "standard"),

    ("sheet_size",       bad_sheet,             "E_SHEET_SIZE",         "standard"),
    ("sheet_size",       bad_sheet,             "E_SHEET_SIZE",         "standard"),
    ("sheet_size",       bad_sheet,             "E_SHEET_SIZE",         "standard"),
    ("sheet_size",       bad_sheet,             "E_SHEET_SIZE",         "standard"),

    ("titleblock_gone",  drop_title_block,      "E_TITLE_BLOCK",        "standard"),
    ("titleblock_gone",  drop_title_block,      "E_TITLE_BLOCK",        "standard"),
    ("titleblock_blank", blank_title_block_attr, "E_TITLE_BLOCK_BLANK", "standard"),
    ("titleblock_blank", blank_title_block_attr, "E_TITLE_BLOCK_BLANK", "standard"),

    ("dim_wrong_layer",  dim_on_outline_layer,  "E_DIM_ON_WRONG_LAYER", "standard"),
    ("dim_wrong_layer",  dim_on_outline_layer,  "E_DIM_ON_WRONG_LAYER", "standard"),
    ("contour_on_zero",  contour_on_layer_zero, "E_CONTOUR_ON_ZERO",    "standard"),
    ("contour_on_zero",  contour_on_layer_zero, "E_CONTOUR_ON_ZERO",    "standard"),
]


def source_pool() -> list[tuple[Path, str]]:
    """Interleave real and generated sources, real first.

    With 15 real exports and 15 generated drawings this yields real, gen, real,
    gen... so the mutated set is half real. With `real/` empty it is all
    generated, and the run says so rather than pretending otherwise.
    """
    real = sorted(REAL_DIR.glob("*.dxf")) if REAL_DIR.is_dir() else []
    gen = sorted(GEN_DIR.glob("*.dxf")) if GEN_DIR.is_dir() else []

    pool: list[tuple[Path, str]] = []
    for index in range(max(len(real), len(gen))):
        if index < len(real) and len(pool) < 10 or not gen:
            pool.append((real[index], "real"))
            continue
        if index < len(real):
            pool.append((real[index], "real"))
        if index < len(gen):
            pool.append((gen[index], "gen"))

    # Alternate so a run of four mutations of one class does not land on one group.
    ordered: list[tuple[Path, str]] = []
    gen_items = [item for item in pool if item[1] == "gen"]
    real_items = [item for item in pool if item[1] == "real"]
    while real_items or gen_items:
        if real_items:
            ordered.append(real_items.pop(0))
        if gen_items:
            ordered.append(gen_items.pop(0))
    return ordered


def main() -> int:
    if not GEN_DIR.is_dir() or not list(GEN_DIR.glob("*.dxf")):
        print("no generated fixtures; run generate_fixtures.py first")
        return 1

    MUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in MUT_DIR.glob("*.dxf"):
        old.unlink()

    sys.path.insert(0, str(ROOT.parent / "src"))
    from cad_deliver.pipeline import verify_file

    pool = source_pool()
    real_count = sum(1 for _, group in pool if group == "real")
    print(f"sources: {len(pool)} ({real_count} real, {len(pool) - real_count} generated)")
    if real_count == 0:
        print("note   : fixtures/real/ is empty, so every mutation starts from a generated")
        print("         drawing. Drop real DXFs in and re-run to mix them in.")

    records = []
    failures = 0
    cursor = 0

    for index, (label, mutation, expected, layer) in enumerate(MUTATIONS, start=1):
        name = f"mut_{index:02d}_{label}"
        applied = None
        # Try successive sources until one accepts this mutation: a real export may
        # lack a layer the mutation needs, and skipping it silently would quietly
        # reduce the effective benchmark.
        for attempt in range(len(pool)):
            source_path, group = pool[(cursor + attempt) % len(pool)]
            doc = ezdxf.readfile(source_path)
            try:
                mutation(doc)
            except (LookupError, AttributeError, ValueError, TypeError):
                continue
            applied = (source_path, group, doc)
            cursor = (cursor + attempt + 1) % len(pool)
            break

        if applied is None:
            print(f"  FAIL {name:24} no source accepted this mutation")
            failures += 1
            continue

        source_path, group, doc = applied
        dst = MUT_DIR / f"{name}.dxf"
        doc.saveas(dst)

        verdict = verify_file(str(dst), "GB_T_TIER1")
        codes = [r.code for r in verdict.rules if not r.ok]
        intercepted = verdict.verdict.value != "PASS"
        exact = expected in codes

        # The bbox class must keep its entities: that is the whole point of the
        # flattening mutation, and it is worth asserting rather than assuming.
        entity_note = ""
        if expected == "E_BBOX_DEGENERATE" and verdict.drawing is not None:
            entity_note = f" entities={sum(verdict.drawing.entities.values())}"

        status = "ok  " if exact else ("part" if intercepted else "MISS")
        if not intercepted:
            failures += 1
        print(
            f"  {status} {name:24} {group:4} {expected:22} "
            f"verdict={verdict.verdict.value:7}{entity_note}"
        )

        records.append(
            {
                "name": name,
                "path": f"fixtures/mutated/{name}.dxf",
                "source": source_path.stem,
                "source_group": group,
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
    intercepted = sum(1 for r in records if r["intercepted"])
    by_group = {}
    for record in records:
        by_group.setdefault(record["source_group"], 0)
        by_group[record["source_group"]] += 1

    print(f"\nmutate: {len(records)} injected, {exact} exact, {intercepted} intercepted")
    print(f"by source: " + ", ".join(f"{k}={v}" for k, v in sorted(by_group.items())))
    print(f"samples: {MUT_DIR}")
    print(f"manifest: {MANIFEST}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())