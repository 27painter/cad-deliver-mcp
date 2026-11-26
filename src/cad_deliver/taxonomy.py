"""Layer semantics: seven roles, their names in Chinese and English, and how to
decide which role a layer name means.

This is the knowledge asset the standard rules are built on. Two decisions are
worth stating, because both were forced by real layer names:

1. Longest alias wins, not first match. "细实线" contains "实线", so a naive
   substring scan files thin auxiliary lines as thick contours. Trying longer
   aliases first fixes that without a hand-written exception list.

2. When two roles still match, a fixed priority decides and the result is
   marked ambiguous with lower confidence. The order is not alphabetical: it
   puts the roles whose misclassification costs the most first.

Every function here is pure. No CAD library, no file access.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum


class LayerRole(str, Enum):
    CONTOUR_THICK = "CONTOUR_THICK"
    THIN_AUX = "THIN_AUX"
    CENTERLINE = "CENTERLINE"
    HIDDEN_DASHED = "HIDDEN_DASHED"
    DIMENSION = "DIMENSION"
    ANNOTATION_TEXT = "ANNOTATION_TEXT"
    FRAME_TITLE = "FRAME_TITLE"
    UNCLASSIFIED = "UNCLASSIFIED"


# Chinese names follow GB drafting habit; English names cover the default
# exports of SolidWorks (plural layer names included) and NX.
ALIASES: dict[LayerRole, tuple[str, ...]] = {
    LayerRole.CONTOUR_THICK: (
        "粗实线", "轮廓线", "可见轮廓线", "实体线", "可见轮廓",
        "OUTLINE", "OUTLINES", "VISIBLE", "CONTOUR", "CONTOURS",
        "OBJECT", "OBJECTS", "SOLID", "SOLIDS", "THICK", "PART",
    ),
    LayerRole.THIN_AUX: (
        "细实线", "剖面线", "填充", "辅助线", "螺纹线", "剖面",
        "THIN", "HATCH", "HATCHES", "SECTION", "SECTIONS",
        "AUX", "AUXILIARY", "CONSTRUCTION", "THREAD", "THREADS",
    ),
    LayerRole.CENTERLINE: (
        "中心线", "轴线", "对称线", "点划线",
        "CENTER", "CENTERS", "CENTERLINE", "CENTERLINES",
        "CENTRE", "CENTRES", "AXIS", "AXES", "CL", "CEN",
    ),
    LayerRole.HIDDEN_DASHED: (
        "虚线", "不可见轮廓线", "隐藏线", "不可见轮廓",
        "HIDDEN", "HIDDENS", "DASHED", "HID", "INVISIBLE",
    ),
    LayerRole.DIMENSION: (
        "标注", "尺寸", "尺寸线", "尺寸标注", "标注层",
        "DIM", "DIMS", "DIMENSION", "DIMENSIONS", "ANNO-DIM", "ANNO_DIM",
    ),
    LayerRole.ANNOTATION_TEXT: (
        "文字", "注释", "技术要求", "粗糙度", "形位公差", "符号", "文本",
        "TEXT", "TEXTS", "NOTE", "NOTES", "ANNO", "ANNOTATION",
        "SYMBOL", "SYMBOLS", "TOL", "TOLERANCE", "SURFACE",
    ),
    LayerRole.FRAME_TITLE: (
        "图框", "标题栏", "内框", "外框", "明细栏", "明细表", "图幅",
        "FRAME", "FRAMES", "BORDER", "BORDERS", "TITLE", "TITLES",
        "TITLEBLOCK", "TITLE_BLOCK", "FORMAT", "FORMATS",
        "SHEET", "SHEETS", "BOM",
    ),
}

# Prefixes CAD systems prepend to imported geometry. Stripped repeatedly, so
# "SW-MECH-轮廓线" reduces to "轮廓线".
PREFIXES = ("M-", "MECH-", "SW-", "NX-", "GB-", "CAD-")

# Misclassification cost, highest first. FRAME_TITLE first because a missed
# frame breaks the title-block rule downstream; DIMENSION next because a
# dimension on the wrong layer is what a shop actually complains about.
# CONTOUR_THICK and THIN_AUX sit last because they are the pair most likely to
# swallow each other, so they should lose a tie rather than win it.
ROLE_PRIORITY: tuple[LayerRole, ...] = (
    LayerRole.FRAME_TITLE,
    LayerRole.DIMENSION,
    LayerRole.ANNOTATION_TEXT,
    LayerRole.CENTERLINE,
    LayerRole.HIDDEN_DASHED,
    LayerRole.CONTOUR_THICK,
    LayerRole.THIN_AUX,
)

# Layer names that are structural, not semantic: they always exist and must not
# be reported as "unclassified".
STRUCTURAL_LAYERS = {"0", "DEFPOINTS", "DEFPOINT"}

_SPACE_RE = re.compile(r"\s+")


def normalise(name: str) -> str:
    """Fold a layer name to the form the alias table uses.

    Full-width characters are folded (Chinese CAD exports use them), prefixes
    are stripped repeatedly, and separators become single spaces so that
    "M-轮廓线" and "轮廓线" compare equal.
    """
    text = unicodedata.normalize("NFKC", str(name or ""))
    text = text.replace("_", " ").replace("-", "-").strip().upper()
    text = _SPACE_RE.sub(" ", text)

    changed = True
    while changed:
        changed = False
        for prefix in PREFIXES:
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
                changed = True
    return text


@dataclass(frozen=True)
class Match:
    """What a layer name was taken to mean, and how sure that is."""

    role: LayerRole
    confidence: float
    via: str = ""          # the alias that decided it
    ambiguous: bool = False

    @property
    def is_structural(self) -> bool:
        return self.role is LayerRole.UNCLASSIFIED and self.via in STRUCTURAL_LAYERS


def is_structural(name: str) -> bool:
    return normalise(name) in {normalise(s) for s in STRUCTURAL_LAYERS}


def classify(name: str) -> Match:
    """Decide which role a layer name means.

    Exact alias first, then the longest alias contained in the name, then
    priority order. Confidence drops as the evidence weakens; a rule can use it
    to warn instead of fail.
    """
    folded = normalise(name)
    if not folded:
        return Match(LayerRole.UNCLASSIFIED, 0.0)

    # 1. exact
    for role, aliases in ALIASES.items():
        for alias in aliases:
            if folded == normalise(alias):
                return Match(role, 1.0, alias)

    # 2. longest contained alias wins
    hits: list[tuple[int, LayerRole, str]] = []
    for role, aliases in ALIASES.items():
        for alias in aliases:
            needle = normalise(alias)
            if needle and needle in folded:
                hits.append((len(needle), role, alias))
    if not hits:
        return Match(LayerRole.UNCLASSIFIED, 0.0, folded)

    hits.sort(key=lambda item: item[0], reverse=True)
    longest = hits[0][0]
    roles_at_longest = {role for length, role, _ in hits if length == longest}

    if len(roles_at_longest) == 1:
        role = hits[0][1]
        return Match(role, 0.7, hits[0][2])

    # 3. a tie at the same alias length: settle it by priority, and say so
    for role in ROLE_PRIORITY:
        if role in roles_at_longest:
            via = next(alias for length, r, alias in hits if r is role and length == longest)
            return Match(role, 0.5, via, ambiguous=True)
    role = hits[0][1]
    return Match(role, 0.5, hits[0][2], ambiguous=True)


# Linetype fragments that a centreline layer is expected to carry.
CENTER_LINETYPES = ("CENTER", "CENTRE", "DASHDOT", "DASH_DOT")
HIDDEN_LINETYPES = ("HIDDEN", "DASHED", "DASH")


def linetype_matches(linetype: str, role: LayerRole) -> bool:
    """True when a linetype name is consistent with the role, or when unknown.

    An empty linetype is not a failure here: many templates set it per entity.
    """
    folded = normalise(linetype)
    if not folded:
        return True
    if role is LayerRole.CENTERLINE:
        return any(fragment in folded for fragment in CENTER_LINETYPES)
    if role is LayerRole.HIDDEN_DASHED:
        return any(fragment in folded for fragment in HIDDEN_LINETYPES)
    return True
# ------------------------------------------------ outline membership

# Roles that never carry the visible outline. A centre line crossing the part is
# not part of its contour, and neither is hatching, a dimension line, a note or
# the frame. Counting them as outline geometry dilutes any share-of-outline
# measurement — which is exactly what made `E_CONTOUR_ON_ZERO` under-report.
NON_OUTLINE_ROLES = frozenset(
    {
        LayerRole.CENTERLINE,
        LayerRole.HIDDEN_DASHED,
        LayerRole.THIN_AUX,
        LayerRole.DIMENSION,
        LayerRole.ANNOTATION_TEXT,
        LayerRole.FRAME_TITLE,
    }
)


def is_outline_layer(name: str) -> bool:
    """True when geometry on this layer can be part of the visible outline.

    Layer 0 is included on purpose: an outline mistakenly left there is a
    finding in its own right (`E_CONTOUR_ON_ZERO`), not a reason to ignore the
    geometry when deciding whether a profile closes.
    """
    if is_structural(name):
        return True
    return classify(name).role not in NON_OUTLINE_ROLES
