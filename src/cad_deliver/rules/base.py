"""Rule plumbing: the result type, the abstract rule, and the registry.

A rule is a pure function of `ParsedDrawing`. It may not open a file, may not
import a CAD library, and may not know which profile invoked it — the profile
only changes the severity of what the rule reports.

That last part matters for the paper's architecture: rules describe facts
("the sheet is 400x280"), profiles decide what a fact costs ("block the
release"). Keeping the two apart is what makes a new standard a plugin rather
than a fork.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

from ..models import ParsedDrawing, Severity


@dataclass
class Evidence:
    """One checkable fact behind a result.

    A verdict without evidence is a sentence. Every rule result carries the
    measured value, the expected value, and — where it exists — the location, so
    a human can confirm the machine without trusting it.
    """

    kind: Literal["measured", "expected", "location", "handle", "count", "name"]
    label: str
    value: str


@dataclass
class RuleResult:
    rule_id: str
    code: str
    ok: bool
    severity: Severity
    detail: str
    evidence: list[Evidence] = field(default_factory=list)
    fix: str | None = None     # a concrete action, not "please check"
    # False when the rule's precondition does not hold for this artefact. Such a
    # result never blocks: the rule says "this does not apply here", which is
    # neither a pass nor a failure. Collapsing it into either one is what makes a
    # gate produce structural false positives on artefacts it was not designed
    # for — a three-view drawing has open edges by construction, so a closure rule
    # fires on 100% of them, forever, no matter how it is tuned.
    applicable: bool = True

    def as_dict(self) -> dict:
        return {
            "rule": self.rule_id,
            "code": self.code,
            "ok": self.ok,
            "applicable": self.applicable,
            "severity": self.severity.value,
            "detail": self.detail,
            "evidence": [e.__dict__ for e in self.evidence],
            "fix": self.fix,
        }


@dataclass
class RuleContext:
    """Everything a rule needs that is not the drawing itself."""

    profile: str
    # code -> severity, already resolved for this profile. Rules ask for their
    # own severity instead of hard-coding one, so a profile can escalate a
    # finding without the rule knowing.
    severities: dict[str, Severity] = field(default_factory=dict)

    def severity(self, code: str, fallback: Severity = Severity.ERROR) -> Severity:
        return self.severities.get(code, fallback)


class BaseStandardRule(ABC):
    """One standard rule. Stateless: the same instance runs on any drawing."""

    rule_id: str
    gb_ref: str | None = None
    layer: Literal["geometry", "standard"] = "standard"
    default_severity: Severity = Severity.ERROR

    @abstractmethod
    def check(self, drawing: ParsedDrawing, ctx: RuleContext) -> list[RuleResult]:
        """Return one result per assertion. Never raise on bad input."""
        raise NotImplementedError

    def precondition(self, drawing: ParsedDrawing) -> str | None:
        """Return why this rule does not apply here, or None when it does.

        A rule is written for a shape of artefact: a single-view profile drawing,
        a sheet with a title block, a dimension on a dimension layer. When the
        artefact is a different shape, the rule is not wrong — it is irrelevant.
        The difference matters because irrelevance repeats on every such file,
        while a wrong verdict is a bug that can be fixed.
        """
        return None


# We deliberately do not use a decorator that binds a profile to a rule: the
# sheet-size logic serves GB and ISO alike, and a decorator would force the same
# rule to be declared twice. The registry is a pool; profiles are lists into it.
_RULES: dict[str, type[BaseStandardRule]] = {}


def register_rule(cls: type[BaseStandardRule]) -> type[BaseStandardRule]:
    if not getattr(cls, "rule_id", None):
        raise ValueError(f"{cls.__name__} has no rule_id")
    if cls.rule_id in _RULES and _RULES[cls.rule_id] is not cls:
        raise ValueError(f"duplicate rule_id: {cls.rule_id}")
    _RULES[cls.rule_id] = cls
    return cls


def get_rule(rule_id: str) -> BaseStandardRule:
    try:
        return _RULES[rule_id]()
    except KeyError:
        raise KeyError(f"no rule registered as {rule_id!r}") from None


def all_rules() -> dict[str, type[BaseStandardRule]]:
    return dict(_RULES)