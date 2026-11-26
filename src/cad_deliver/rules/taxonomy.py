"""Layer semantics, re-exported from the package root.

The ontology is domain knowledge, not a rule: the geometry layer needs it to
decide which entities are outline geometry at all, and the rule layer needs it to
judge layer naming. It therefore lives at `cad_deliver.taxonomy` and this module
only keeps the old import path working.
"""

from ..taxonomy import (  # noqa: F401
    ALIASES,
    CENTER_LINETYPES,
    HIDDEN_LINETYPES,
    NON_OUTLINE_ROLES,
    PREFIXES,
    ROLE_PRIORITY,
    STRUCTURAL_LAYERS,
    LayerRole,
    Match,
    classify,
    is_outline_layer,
    is_structural,
    linetype_matches,
    normalise,
)

__all__ = [
    "ALIASES",
    "CENTER_LINETYPES",
    "HIDDEN_LINETYPES",
    "NON_OUTLINE_ROLES",
    "PREFIXES",
    "ROLE_PRIORITY",
    "STRUCTURAL_LAYERS",
    "LayerRole",
    "Match",
    "classify",
    "is_outline_layer",
    "is_structural",
    "linetype_matches",
    "normalise",
]