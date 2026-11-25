"""The contract between parsing and judging.

Everything a rule is allowed to know about a file lives in `ParsedDrawing`.
The point is testability and the orthogonal split the architecture claims:

    parsers/   know about file formats
    geometry/  know about parsed facts, no standard
    rules/     know about parsed facts, one standard each

A rule that imports `ezdxf` breaks that split, so `tests/test_layering.py`
fails the build if one does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class Severity(str, Enum):
    """How bad a failed check is.

    `blocked` is deliberately separate from `error`: it means the check could
    not run at all (no reader for this format), which must never be reported as
    a pass. A delivery with blocked checks and no errors is UNKNOWN, not PASS.
    """

    ERROR = "error"
    WARNING = "warning"
    BLOCKED = "blocked"


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class StageState(str, Enum):
    STAGED = "STAGED"
    VERIFIED = "VERIFIED"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


@dataclass
class Check:
    """One assertion about one file, with the reason written next to it.

    `ident` stays a dotted string on purpose: it is already the public contract
    of delivery.json (drawing.dimensions, step.bbox, ...), and renaming it would
    invalidate every report anybody has kept. Stable machine codes live in
    rules/codes.py and map onto these.
    """

    ident: str
    ok: bool
    detail: str
    severity: str = Severity.ERROR.value

    def as_dict(self) -> dict:
        return {"id": self.ident, "ok": self.ok, "detail": self.detail, "severity": self.severity}


# ---------------------------------------------------------------- parsed facts
#
# These are plain values, not ezdxf or PyMuPDF objects. Parsers produce
# `ParseResult` containing `ParsedDrawing` and parse-stage `Check` items;
# geometry/ and rules/ read only `ParsedDrawing`.


@dataclass
class LayerInfo:
    name: str
    lineweight: int = -3
    linetype: str = ""
    entity_count: int = 0

    @property
    def has_explicit_weight(self) -> bool:
        return self.lineweight >= 0


@dataclass
class LayoutInfo:
    name: str
    paper_width: float = 0.0
    paper_height: float = 0.0
    entity_count: int = 0
    # Names only, kept for callers that just want "is anything inserted here".
    block_refs: list[str] = field(default_factory=list)
    # Full references including their attributes. A title block is only useful
    # if its fields can be read, so this is what a rule should use.
    blocks: list["BlockRef"] = field(default_factory=list)


@dataclass
class TextItem:
    content: str
    layer: str = ""
    style: str = ""
    height: float = 0.0
    insert: tuple[float, float] = (0.0, 0.0)
    space: Literal["model", "paper"] = "model"
    layout: str = ""
    kind: Literal["TEXT", "MTEXT", "ATTRIB"] = "TEXT"


@dataclass
class AttribItem:
    """One attribute of one block reference.

    A title block is a block whose attributes carry 图名 / 图号 / 材料 / 比例.
    Checking that the block exists proves nothing — an empty title block still
    exists. What matters is whether the attribute values are filled in, and that
    needs `tag` and `block`, which a plain TextItem cannot express.
    """

    tag: str
    value: str
    block: str = ""
    layer: str = ""
    space: Literal["model", "paper"] = "paper"
    layout: str = ""

    @property
    def is_blank(self) -> bool:
        return not self.value.strip()


@dataclass
class BlockRef:
    """One INSERT: which block, where, and the attributes it carries."""

    name: str
    layer: str = ""
    space: Literal["model", "paper"] = "paper"
    layout: str = ""
    attributes: list[AttribItem] = field(default_factory=list)

    def attribute(self, *tags: str) -> AttribItem | None:
        """First attribute whose tag matches any of `tags`, case-insensitively."""
        wanted = {t.strip().upper() for t in tags}
        for item in self.attributes:
            if item.tag.strip().upper() in wanted:
                return item
        return None


@dataclass
class DimInfo:
    handle: str
    layer: str
    dimtype: int
    measurement: float | None = None
    text: str = ""
    dimlfac: float = 1.0
    style: str = "Standard"
    text_midpoint: tuple[float, float] | None = None
    space: Literal["model", "paper"] = "model"

    @property
    def text_is_overridden(self) -> bool:
        """Only an overridden text can disagree with the geometry.

        "" and "<>" both make the application print the measured value, so
        there is nothing to compare there.
        """
        return self.text not in ("", "<>")

    @property
    def kind(self) -> int:
        """Dimension type without the flag bits."""
        return self.dimtype & 7


@dataclass
class Segment:
    """One straight-ish piece of the outline, as two endpoints.

    A parser records these for LINE, ARC and open POLYLINE chains. Curves are
    reduced to their endpoints on purpose: closure is decided by whether
    endpoints meet, and an arc that ends where the next line starts closes the
    profile regardless of its shape between the two.
    """

    kind: str                  # LINE / ARC / LWPOLYLINE / POLYLINE
    layer: str
    start: tuple[float, float]
    end: tuple[float, float]


@dataclass
class ParsedDrawing:
    """What a rule is allowed to know. Built by a parser, never by a rule."""

    fmt: Literal["dxf", "dwg-converted", "step", "pdf"]
    source_path: str
    dxfversion: str | None = None
    units: int = 0
    entities: dict[str, int] = field(default_factory=dict)
    extents: tuple[float, float, float, float] | None = None
    extent_point_count: int = 0
    layers: list[LayerInfo] = field(default_factory=list)
    # layer name -> {entity type: count}. The consistency checks need to know
    # that a DIMENSION sits on the outline layer, which a per-layer total
    # cannot answer.
    entity_layers: dict[str, dict[str, int]] = field(default_factory=dict)
    layouts: list[LayoutInfo] = field(default_factory=list)
    texts: list[TextItem] = field(default_factory=list)
    dimensions: list[DimInfo] = field(default_factory=list)
    text_styles: dict[str, str] = field(default_factory=dict)
    # Flattened view of every attribute in the file, so a rule can ask
    # "is there a 材料 attribute anywhere, and is it blank?" without walking
    # layouts itself. Blocks are in `layouts[].blocks` when the grouping matters.
    attributes: list[AttribItem] = field(default_factory=list)
    # Outline pieces for closure analysis. Populated by the parser, judged by
    # geometry/topology.py — the parser does not decide whether they close.
    segments: list[Segment] = field(default_factory=list)
    closed_profiles: int = 0
    # One entry per broken component: the endpoints that go nowhere.
    open_profiles: list[list[tuple[float, float]]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    # There is deliberately no field for the live CAD document. An escape hatch
    # for one existed during the migration and it was removed once the last
    # check stopped needing it: as long as it exists, "geometry/ and rules/ read
    # only parsed facts" is a promise nobody can verify. `test_parsers.py`
    # asserts the attribute stays gone.

    @property
    def degenerate(self) -> bool:
        """True when the geometry has no extent: every point in one place."""
        if self.extents is None:
            return True
        minx, miny, maxx, maxy = self.extents
        return (maxx - minx) <= 1e-9 and (maxy - miny) <= 1e-9


@dataclass
class ParseResult:
    """Outcome of parsing one file into plain facts."""

    drawing: ParsedDrawing | None
    checks: list[Check] = field(default_factory=list)