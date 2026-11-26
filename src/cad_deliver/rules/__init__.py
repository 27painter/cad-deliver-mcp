"""Pluggable standard rules.

Importing this package registers every rule, so a caller only needs

    from cad_deliver.rules import run_profile
    results = run_profile(drawing, "GB_T_TIER1")
"""

from .base import (
    BaseStandardRule,
    Evidence,
    RuleContext,
    RuleResult,
    all_rules,
    get_rule,
    register_rule,
)
from .codes import ALL_CODES, Code
from .registry import (
    DEFAULT_PROFILE,
    PROFILES,
    SEVERITY_PROFILES,
    available_profiles,
    context_for,
    registry_snapshot,
    run_profile,
)
from .taxonomy import ALIASES, ROLE_PRIORITY, LayerRole, Match, classify, normalise

# Importing the subpackage is what runs the @register_rule decorators.
from . import bbox, gb  # noqa: F401,E402  (after the names it depends on)

__all__ = [
    "ALIASES",
    "ALL_CODES",
    "BaseStandardRule",
    "Code",
    "DEFAULT_PROFILE",
    "Evidence",
    "LayerRole",
    "Match",
    "PROFILES",
    "ROLE_PRIORITY",
    "RuleContext",
    "RuleResult",
    "SEVERITY_PROFILES",
    "all_rules",
    "available_profiles",
    "classify",
    "context_for",
    "get_rule",
    "normalise",
    "register_rule",
    "registry_snapshot",
    "run_profile",
]