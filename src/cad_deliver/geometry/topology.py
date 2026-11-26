"""Outline closure: does the visible contour close on itself?

Why this needs care instead of `if entity.closed`: real SolidWorks and NX
exports routinely write a closed ring as a polyline with the closed flag off and
the last vertex sitting on the first. Trusting the flag reports every one of
those as broken, which is worse than not checking at all — a gate that cries
wolf gets switched off.

Three rules, each one written because an earlier version produced false
positives:

1. A polyline closes when `entity.closed` is true **or** its endpoints coincide
   within `JOIN_TOLERANCE_MM`. The parser records the endpoints either way.
2. LINE and ARC pieces are joined by snapping endpoints onto a `JOIN_TOLERANCE_MM`
   grid, then counting how many pieces meet at each snapped vertex. A vertex with
   degree 1 is a dangling end: the outline got there and stopped.
3. Only outline geometry is considered. CIRCLE is closed by definition, and
   centre lines, hatching, dimensions, text and title frames are not outlines —
   counting their endpoints would report a break in every drawing ever made.

The tolerance is 0.01 mm: below plotting resolution, above the rounding noise of
a STEP/DXF round trip.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import math

from ..models import ParsedDrawing
from ..taxonomy import is_outline_layer

JOIN_TOLERANCE_MM = 0.01

# Re-exported: the membership test is domain knowledge, so it lives in
# cad_deliver.taxonomy where the rule layer can use the same definition.
# `test_topology.py` still imports it from here.

# Entity kinds that never take part in closure analysis.
IGNORED_KINDS = frozenset({"CIRCLE", "POINT", "SOLID", "HATCH", "DIMENSION"})


def _grid_key(point: tuple[float, float], tolerance: float) -> tuple[int, int]:
    return (
        math.floor(point[0] / tolerance),
        math.floor(point[1] / tolerance),
    )


class _VertexIndex:
    """Snap points that are within `tolerance` of each other onto one vertex.

    Rounding to a grid is not enough: with a 0.01 mm tolerance, rounding only
    joins points that are within 0.005 mm, so a 0.008 mm gap — well inside the
    tolerance — would still read as two vertices and report a false break. This
    searches the point's own cell plus its eight neighbours and compares real
    distance, which is what "within tolerance" actually means.
    """

    def __init__(self, tolerance: float) -> None:
        self.tolerance = tolerance
        self.points: list[tuple[float, float]] = []
        self._buckets: dict[tuple[int, int], int] = {}

    def locate(self, point: tuple[float, float]) -> int:
        key = _grid_key(point, self.tolerance)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                index = self._buckets.get((key[0] + dx, key[1] + dy))
                if index is None:
                    continue
                other = self.points[index]
                if (
                    abs(other[0] - point[0]) <= self.tolerance
                    and abs(other[1] - point[1]) <= self.tolerance
                ):
                    return index
        self.points.append(point)
        self._buckets[key] = len(self.points) - 1
        return len(self.points) - 1


@dataclass
class Topology:
    """What the closure analysis found."""

    #: number of connected components that close on themselves
    closed: int = 0
    #: one entry per broken component: the endpoints that go nowhere
    open: list[list[tuple[float, float]]] = field(default_factory=list)
    #: how many segments were considered at all
    segments_considered: int = 0
    #: segments dropped because their layer is not outline geometry
    segments_skipped: int = 0

    @property
    def is_clean(self) -> bool:
        return not self.open




def analyse(drawing: ParsedDrawing, tolerance: float = JOIN_TOLERANCE_MM) -> Topology:
    """Decide which outline components close. Pure: no CAD library, no file."""
    topology = Topology(closed=drawing.closed_profiles)

    usable = []
    for segment in drawing.segments:
        if segment.kind.upper() in IGNORED_KINDS or not is_outline_layer(segment.layer):
            topology.segments_skipped += 1
            continue
        usable.append(segment)

    topology.segments_considered = len(usable)
    if not usable:
        return topology

    # Union-find over snapped vertices: two segments that share a vertex belong
    # to the same component, and a component with no degree-1 vertex closes.
    index = _VertexIndex(tolerance)
    parent: dict[int, int] = {}

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    degree: dict[int, int] = defaultdict(int)
    for segment in usable:
        a = index.locate(segment.start)
        b = index.locate(segment.end)
        for node in (a, b):
            parent.setdefault(node, node)
        union(a, b)
        degree[a] += 1
        degree[b] += 1

    # Collapse each component, then look for dangling ends inside it.
    components: dict[int, list[int]] = defaultdict(list)
    for node in parent:
        components[find(node)].append(node)

    for _root, nodes in components.items():
        dangling = [node for node in nodes if degree.get(node, 0) == 1]
        if not dangling:
            topology.closed += 1
            continue
        # Report the snapped positions in millimetres, ordered so the message is
        # stable between runs.
        points = sorted(
            (round(index.points[node][0], 3), round(index.points[node][1], 3))
            for node in dangling
        )
        topology.open.append([(float(x), float(y)) for x, y in points])

    return topology


def summarise(topology: Topology, limit: int = 4) -> str:
    """One line naming the worst break, for a check detail."""
    if topology.is_clean:
        return (
            f"{topology.closed} closed outline component(s), "
            f"{topology.segments_considered} segment(s) considered"
        )
    worst = max(topology.open, key=len)
    preview = ", ".join(f"({x:g}, {y:g})" for x, y in worst[:limit])
    more = f" (+{len(worst) - limit} more)" if len(worst) > limit else ""
    return (
        f"{len(topology.open)} outline component(s) do not close; "
        f"the worst leaves {len(worst)} dangling end(s) at {preview}{more}"
    )