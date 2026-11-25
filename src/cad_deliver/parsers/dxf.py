"""DXF and DWG parser producing plain `ParsedDrawing` facts."""

from __future__ import annotations

import os
from typing import Literal

from ..core import DWG_VERSIONS
from ..models import (
    AttribItem,
    BlockRef,
    Check,
    DimInfo,
    LayerInfo,
    LayoutInfo,
    ParsedDrawing,
    ParseResult,
    Segment,
    TextItem,
)
from .dwg import convert_dwg, find_dwg_converter

# Same tolerance the topology analysis uses: ends within this distance are the
# same point. Kept here as well because a polyline's own closed flag has to be
# second-guessed at parse time.
JOIN_TOLERANCE_MM = 0.01


def _close(a, b, tolerance: float = JOIN_TOLERANCE_MM) -> bool:
    return abs(a[0] - b[0]) <= tolerance and abs(a[1] - b[1]) <= tolerance


def _extract_xy(point: object) -> tuple[float, float]:
    if point is None:
        return (0.0, 0.0)
    try:
        return (float(point[0]), float(point[1]))  # type: ignore[index]
    except (TypeError, IndexError, ValueError):
        return (0.0, 0.0)


def parse(path: str) -> ParseResult:
    """Open a DXF (or convert a DWG first) and return a `ParseResult`.

    No live CAD document leaves this function: the caller gets plain values only,
    which is what lets geometry/ and rules/ stay free of ezdxf.
    """
    checks: list[Check] = []
    notes: list[str] = []
    dxf_path = path
    is_dwg_converted = False

    if path.lower().endswith(".dwg"):
        with open(path, "rb") as handle:
            header = handle.read(6)
        version = header.decode("ascii", "replace")
        known = DWG_VERSIONS.get(version)
        checks.append(
            Check(
                "dwg.header",
                known is not None,
                f"format {version} (AutoCAD {known})"
                if known
                else f"first bytes are {version!r}, not a DWG version tag",
            )
        )
        converter = find_dwg_converter()
        converted = convert_dwg(path, converter) if converter and known else None
        if converted:
            # From here the DWG is parsed like a DXF, because it now is one.
            checks.append(
                Check(
                    "dwg.converted",
                    True,
                    f"converted to DXF with {converter[0]} ({os.path.basename(converter[1])}); "
                    "the checks below read the converted file",
                    severity="warning",
                )
            )
            notes.append(f"converted to DXF with {converter[0]} ({os.path.basename(converter[1])})")
            dxf_path = converted
            is_dwg_converted = True
        else:
            reason = (
                "no DWG-to-DXF converter was found (install LibreDWG's dwg2dxf, "
                "ODA File Converter, or set DSH_SW_CAD_DWG_CONVERTER to a command "
                "using {in} and {out})"
                if not converter
                else "the converter produced no DXF"
            )
            checks.append(
                Check(
                    "drawing.entities",
                    False,
                    f"not checked: {reason}, so entities, units, sheets and dimensions were not examined",
                    severity="blocked",
                )
            )
            return ParseResult(drawing=None, checks=checks)

    try:
        import ezdxf
    except Exception:
        # A missing reader must be reported as blocked, never skipped as a pass.
        checks.append(
            Check(
                "dxf.parsed",
                False,
                "ezdxf is not importable, so this DXF was NOT checked "
                "(install ezdxf, or run deliver with an interpreter that has it)",
                severity="blocked",
            )
        )
        return ParseResult(drawing=None, checks=checks)

    try:
        doc = ezdxf.readfile(dxf_path)
    except Exception as exc:
        # A file the reader cannot parse is not a failed drawing, it is an
        # unjudged one: nothing inside it was examined. Reporting this as an
        # error mixed "your drawing is wrong" with "this is not a drawing",
        # which call for different actions from the caller.
        checks.append(
            Check(
                "dxf.parsed",
                False,
                f"the DXF could not be parsed, so nothing inside it was judged: {exc}",
                severity="blocked",
            )
        )
        return ParseResult(drawing=None, checks=checks)

    checks.append(Check("dxf.parsed", True, f"DXF {doc.dxfversion}"))

    msp = doc.modelspace()
    counts: dict[str, int] = {}
    layer_counts: dict[str, int] = {}
    # layer -> {type: count}. The consistency rules need this: "a DIMENSION sits
    # on the outline layer" cannot be answered from a per-layer total.
    entity_layers: dict[str, dict[str, int]] = {}
    segments: list[Segment] = []
    closed_profiles = 0

    for entity in msp:
        kind = entity.dxftype()
        counts[kind] = counts.get(kind, 0) + 1
        layer_name = entity.dxf.get("layer", "0")
        layer_counts[layer_name] = layer_counts.get(layer_name, 0) + 1
        per_layer = entity_layers.setdefault(layer_name, {})
        per_layer[kind] = per_layer.get(kind, 0) + 1

        # Outline pieces for the closure analysis. Recorded as endpoints only;
        # whether they close is decided in geometry/topology.py, not here.
        if kind == "LINE":
            segments.append(
                Segment(
                    kind="LINE",
                    layer=layer_name,
                    start=_extract_xy(entity.dxf.get("start", None)),
                    end=_extract_xy(entity.dxf.get("end", None)),
                )
            )
        elif kind == "ARC":
            try:
                segments.append(
                    Segment(
                        kind="ARC",
                        layer=layer_name,
                        start=_extract_xy(entity.start_point),
                        end=_extract_xy(entity.end_point),
                    )
                )
            except Exception:
                pass
        elif kind == "LWPOLYLINE":
            points = [(float(p[0]), float(p[1])) for p in entity.get_points("xy")]
            if len(points) >= 2:
                # SolidWorks and NX routinely export a closed ring with the flag
                # off and the last vertex on the first, so the flag alone is not
                # trustworthy in either direction.
                is_closed = bool(entity.closed) or _close(points[0], points[-1])
                if is_closed:
                    closed_profiles += 1
                else:
                    segments.append(
                        Segment(
                            kind="LWPOLYLINE",
                            layer=layer_name,
                            start=points[0],
                            end=points[-1],
                        )
                    )
        elif kind == "POLYLINE":
            try:
                points = [
                    (float(v.dxf.location.x), float(v.dxf.location.y)) for v in entity.vertices
                ]
            except Exception:
                points = []
            if len(points) >= 2:
                is_closed = bool(entity.is_closed) or _close(points[0], points[-1])
                if is_closed:
                    closed_profiles += 1
                else:
                    segments.append(
                        Segment(
                            kind="POLYLINE",
                            layer=layer_name,
                            start=points[0],
                            end=points[-1],
                        )
                    )

    layers = [
        LayerInfo(
            name=layer.dxf.name,
            lineweight=layer.dxf.get("lineweight", -3),
            linetype=layer.dxf.get("linetype", ""),
            entity_count=layer_counts.get(layer.dxf.name, 0),
        )
        for layer in doc.layers
    ]

    text_styles: dict[str, str] = {}
    for style in doc.styles:
        text_styles[style.dxf.name] = style.dxf.get("font", "") or ""

    layouts: list[LayoutInfo] = []
    texts: list[TextItem] = []
    dimensions: list[DimInfo] = []
    attributes: list[AttribItem] = []

    for layout_name in doc.layouts.names():
        layout = doc.layouts.get(layout_name)
        layout_entities = list(layout)
        space: Literal["model", "paper"] = "model" if layout_name.lower() == "model" else "paper"
        block_refs = [
            e.dxf.get("name", "")
            for e in layout_entities
            if e.dxftype() == "INSERT"
        ]

        # INSERTs with their attributes. A title block is only checkable if the
        # field values are carried, not just the block name.
        references: list[BlockRef] = []
        for entity in layout_entities:
            if entity.dxftype() != "INSERT":
                continue
            block_name = entity.dxf.get("name", "")
            items: list[AttribItem] = []
            for attrib in getattr(entity, "attribs", ()):
                item = AttribItem(
                    tag=attrib.dxf.get("tag", ""),
                    value=attrib.dxf.get("text", ""),
                    block=block_name,
                    layer=attrib.dxf.get("layer", ""),
                    space=space,
                    layout=layout_name,
                )
                items.append(item)
                attributes.append(item)
            references.append(
                BlockRef(
                    name=block_name,
                    layer=entity.dxf.get("layer", ""),
                    space=space,
                    layout=layout_name,
                    attributes=items,
                )
            )

        layouts.append(
            LayoutInfo(
                name=layout_name,
                paper_width=float(layout.dxf.get("paper_width", 0) or 0),
                paper_height=float(layout.dxf.get("paper_height", 0) or 0),
                entity_count=len(layout_entities),
                block_refs=block_refs,
                blocks=references,
            )
        )

        for entity in layout_entities:
            kind = entity.dxftype()
            if kind == "TEXT":
                texts.append(
                    TextItem(
                        content=entity.dxf.get("text", ""),
                        layer=entity.dxf.get("layer", ""),
                        style=entity.dxf.get("style", "Standard"),
                        height=float(entity.dxf.get("height", 0) or 0),
                        insert=_extract_xy(entity.dxf.get("insert", None)),
                        space=space,
                        layout=layout_name,
                        kind="TEXT",
                    )
                )
            elif kind == "MTEXT":
                texts.append(
                    TextItem(
                        content=entity.text,
                        layer=entity.dxf.get("layer", ""),
                        style=entity.dxf.get("style", "Standard"),
                        height=float(entity.dxf.get("char_height", 0) or 0),
                        insert=_extract_xy(entity.dxf.get("insert", None)),
                        space=space,
                        layout=layout_name,
                        kind="MTEXT",
                    )
                )
            elif kind == "INSERT":
                for attrib in getattr(entity, "attribs", ()):
                    texts.append(
                        TextItem(
                            content=attrib.dxf.get("text", ""),
                            layer=attrib.dxf.get("layer", ""),
                            style=attrib.dxf.get("style", "Standard"),
                            height=float(attrib.dxf.get("height", 0) or 0),
                            insert=_extract_xy(attrib.dxf.get("insert", None)),
                            space=space,
                            layout=layout_name,
                            kind="ATTRIB",
                        )
                    )
            elif kind == "DIMENSION":
                style = entity.dxf.get("dimstyle", "Standard")
                try:
                    factor = float(doc.dimstyles.get(style).dxf.get("dimlfac", 1.0))
                except Exception:
                    factor = 1.0
                try:
                    measurement: float | None = float(entity.get_measurement())
                except Exception:
                    measurement = None
                mid = entity.dxf.get("text_midpoint", None)
                text_midpoint = _extract_xy(mid) if mid is not None else None
                dimensions.append(
                    DimInfo(
                        handle=entity.dxf.get("handle", "?"),
                        layer=entity.dxf.get("layer", ""),
                        dimtype=int(entity.dimtype),
                        measurement=measurement,
                        text=entity.dxf.get("text", ""),
                        dimlfac=factor,
                        style=style,
                        text_midpoint=text_midpoint,
                        space=space,
                    )
                )

    drawing = ParsedDrawing(
        fmt="dwg-converted" if is_dwg_converted else "dxf",
        source_path=str(path),
        dxfversion=doc.dxfversion,
        units=int(doc.header.get("$INSUNITS", 0) or 0),
        entities=counts,
        layers=layers,
        entity_layers=entity_layers,
        layouts=layouts,
        texts=texts,
        dimensions=dimensions,
        text_styles=text_styles,
        attributes=attributes,
        segments=segments,
        closed_profiles=closed_profiles,
        notes=notes,
    )
    return ParseResult(drawing=drawing, checks=checks)
