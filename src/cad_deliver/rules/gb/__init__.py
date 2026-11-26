"""GB/T rules. Importing this module registers all three.

Tier-1 drafting baseline (GB_T_TIER1):
    gb.sheet_size      GB/T 14689  sheet size
    gb.layer_taxonomy  GB/T 4457.2 layer roles and entity-layer consistency
    gb.title_block     GB/T 10609.1 title block and its required fields

Extensible hooks, not implemented yet and listed in the architecture figure:
    gb.line_width      GB/T 17450  line widths by role
    gb.typography      GB/T 14691  text height and font class
"""

from . import closed_profile, dim_text, layer_taxonomy, sheet_size, title_block  # noqa: F401

__all__ = ["closed_profile", "dim_text", "layer_taxonomy", "sheet_size", "title_block"]