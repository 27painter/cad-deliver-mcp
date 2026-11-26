"""Stable machine codes.

`Check.ident` (drawing.sheet, step.bbox) is the human-facing contract of
delivery.json and must not change. These codes sit beside it: they are what a
benchmark counts, what a severity profile overrides, and what a paper table
lists. One rule may emit several codes, which is the whole reason codes exist
separately from rule ids.

Naming: `E_` is an error, `W_` a warning. The prefix is part of the identifier
because a profile may reclassify a code, and the prefix keeps the original
intent visible when it does.
"""

from __future__ import annotations

from enum import Enum


class Code(str, Enum):
    # --- sheet / frame ---------------------------------------------------
    SHEET_SIZE = "E_SHEET_SIZE"                    # not an ISO 216 sheet
    SHEET_SIZE_UNKNOWN = "E_SHEET_SIZE_UNKNOWN"    # no sheet size to judge
    SHEET_NOT_ISO_A = "W_SHEET_NOT_ISO_A"          # right size class, wrong series

    # --- title block -----------------------------------------------------
    TITLE_BLOCK = "E_TITLE_BLOCK"                  # missing entirely
    TITLE_BLOCK_BLANK = "E_TITLE_BLOCK_BLANK"      # present, required field empty
    TITLE_BLOCK_NO_ATTR = "W_TITLE_BLOCK_NO_ATTR"  # block has no attributes at all

    # --- layer taxonomy --------------------------------------------------
    LAYER_UNCLASSIFIED = "W_LAYER_UNCLASSIFIED"    # layer name matches no role
    LAYER_AMBIGUOUS = "W_LAYER_AMBIGUOUS"          # matches two roles
    DIM_ON_WRONG_LAYER = "E_DIM_ON_WRONG_LAYER"    # dimension not on a dimension layer
    CONTOUR_ON_ZERO = "E_CONTOUR_ON_ZERO"          # main outline left on layer 0
    CENTER_LINETYPE = "W_CENTER_LINETYPE"          # centre layer without a centre linetype
    NO_CONTOUR_LAYER = "W_NO_CONTOUR_LAYER"        # nothing classified as outline

    # --- outline closure -------------------------------------------------
    PROFILE_OPEN = "E_PROFILE_OPEN"                # outline leaves a dangling end

    # --- geometry integrity ----------------------------------------------
    BBOX_DEGENERATE = "E_BBOX_DEGENERATE"          # geometry collapsed to a point or a line


# The identifiers a rule emits must be these values, not free strings, so a
# profile can override one without guessing at spelling.
ALL_CODES = {c.value for c in Code}