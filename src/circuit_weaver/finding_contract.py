"""T248 finding and suppression contracts.

This module is deliberately presentation-independent: a renderer may decorate a
finding, but it may not turn an incomplete finding into a confirmed one or make
a suppression disappear from accounting.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .evidence_policy import EVIDENCE_ID_PATTERN

SUPPRESSION_SCHEMA_VERSION = "circuit-weaver-suppressions/v1"
RULE_ID_PATTERN = re.compile(r"^CW-[A-Z0-9]+-[0-9]{3}$")
_UNIT_VALUE_PATTERN = re.compile(r"^\s*[-+]?\d+(?:\.\d+)?\s*[A-Za-z%Ωµ]+(?:\b|$)")
_ACTIONABLE_SEVERITIES = frozenset({"blocker", "major", "minor"})
_WEAK_CONFIDENCES = frozenset({"heuristic", "stub", "conflicting"})
_SCOPES = frozenset({"ref", "net", "design"})


class FindingContractError(ValueError):
    """A finding or suppression cannot pass the release contract."""


@dataclass(frozen=True)
class Suppression:
    """A reviewed, narrow, expiring exception to one stable rule."""

    id: str
    rule_id: str
    scope: Mapping[str, str]
    owner: str
    reason: str
    created_at: str
    expires_at: str
    approved_by: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "rule_id": self.rule_id,
            "scope": dict(self.scope),
            "owner": self.owner,
            "reason": self.reason,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "approved_by": self.approved_by,
        }


def _timestamp(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise FindingContractError(f"suppression {field} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FindingContractError(f"suppression {field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise FindingContractError(f"suppression {field} must include a timezone")
    return parsed.astimezone(UTC)


def validate_suppression(suppression: Suppression, *, now: datetime | None = None) -> None:
    """Reject broad, anonymous, malformed, and expired suppressions."""

    if not isinstance(suppression.id, str) or not re.fullmatch(r"SUP-[a-z0-9][a-z0-9-]{2,63}", suppression.id):
        raise FindingContractError("suppression id must be a stable SUP- identifier")
    if not isinstance(suppression.rule_id, str) or not RULE_ID_PATTERN.fullmatch(suppression.rule_id):
        raise FindingContractError("suppression rule_id must be a stable CW-<DOMAIN>-<NNN> ID")
    if not isinstance(suppression.scope, Mapping) or set(suppression.scope) - _SCOPES:
        raise FindingContractError("suppression scope must contain only ref, net, or design")
    if len(suppression.scope) != 1:
        raise FindingContractError("suppression scope must target exactly one ref, net, or design")
    scope_name, scope_value = next(iter(suppression.scope.items()))
    if scope_name not in _SCOPES or not isinstance(scope_value, str) or not scope_value.strip():
        raise FindingContractError("suppression scope must name one non-empty target")
    if any(token in scope_value for token in ("*", "?", "[", "]")):
        raise FindingContractError("suppression scope may not contain wildcards")
    for field in ("owner", "reason", "approved_by"):
        value = getattr(suppression, field)
        if not isinstance(value, str) or not value.strip():
            raise FindingContractError(f"suppression {field} is required")
    created = _timestamp(suppression.created_at, "created_at")
    expires = _timestamp(suppression.expires_at, "expires_at")
    if expires <= created:
        raise FindingContractError("suppression expires_at must be after created_at")
    current = (now or datetime.now(UTC)).astimezone(UTC)
    if expires <= current:
        raise FindingContractError("suppression has expired")


def validate_suppressions(
    suppressions: Iterable[Suppression], *, now: datetime | None = None
) -> tuple[Suppression, ...]:
    """Validate the versioned suppression set used by a release gate."""

    materialized = tuple(suppressions)
    ids = [item.id for item in materialized]
    if len(ids) != len(set(ids)):
        raise FindingContractError("suppression ids must be unique")
    for item in materialized:
        validate_suppression(item, now=now)
    return materialized


def load_suppressions(path: str | Path, *, now: datetime | None = None) -> tuple[Suppression, ...]:
    """Read the checked-in JSON suppression artifact and validate it strictly."""

    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FindingContractError(f"{source}: invalid suppression JSON") from exc
    if not isinstance(payload, Mapping) or set(payload) != {"schema_version", "suppressions"}:
        raise FindingContractError("suppression artifact has an invalid top-level shape")
    if payload.get("schema_version") != SUPPRESSION_SCHEMA_VERSION:
        raise FindingContractError("unsupported suppression schema_version")
    raw = payload.get("suppressions")
    if not isinstance(raw, list):
        raise FindingContractError("suppressions must be a list")
    allowed = {"id", "rule_id", "scope", "owner", "reason", "created_at", "expires_at", "approved_by"}
    parsed: list[Suppression] = []
    for item in raw:
        if not isinstance(item, Mapping) or set(item) != allowed:
            raise FindingContractError("each suppression must use the frozen schema")
        parsed.append(Suppression(**dict(item)))
    return validate_suppressions(parsed, now=now)


def finding_contract_violations(
    issue: Any,
    *,
    known_evidence_ids: Iterable[str] = (),
) -> tuple[str, ...]:
    """Return release-blocking omissions for an actionable finding.

    Legacy findings remain serializable during migration, but this function is
    the single gate that makes their incompleteness visible and non-shippable.
    """

    if getattr(issue, "severity", "") not in _ACTIONABLE_SEVERITIES:
        return ()
    violations: list[str] = []
    rule_id = getattr(issue, "rule_id", None)
    if not isinstance(rule_id, str) or not RULE_ID_PATTERN.fullmatch(rule_id):
        violations.append("rule_id must be CW-<DOMAIN>-<NNN>")
    observed = getattr(issue, "observed_value", None)
    if not isinstance(observed, str) or not _UNIT_VALUE_PATTERN.fullmatch(observed.strip()):
        violations.append("observed_value must be numeric and unit-labelled")
    expected = getattr(issue, "expected_constraint", None)
    if not isinstance(expected, str) or not expected.strip():
        violations.append("expected_constraint is required")
    action = getattr(issue, "safest_next_action", None)
    if not isinstance(action, str) or not action.strip():
        violations.append("safest_next_action is required")
    evidence_ids = tuple(getattr(issue, "evidence_ids", ()) or ())
    if not evidence_ids:
        violations.append("evidence_ids are required")
    known = set(known_evidence_ids)
    for evidence_id in evidence_ids:
        if not isinstance(evidence_id, str) or not EVIDENCE_ID_PATTERN.fullmatch(evidence_id):
            violations.append("evidence_ids contain a malformed ID")
            break
        if evidence_id not in known:
            violations.append("evidence_ids must resolve in the evidence ledger")
            break
    if getattr(issue, "detection_confidence", "") in _WEAK_CONFIDENCES and getattr(
        issue, "is_confirmed_blocker", False
    ):
        violations.append("weak evidence cannot be presented as a confirmed blocker")
    return tuple(violations)


def require_finding_contract(issues: Iterable[Any], *, known_evidence_ids: Iterable[str] = ()) -> None:
    """Raise a release-gate error when any actionable finding is incomplete."""

    problems: list[str] = []
    for issue in issues:
        violations = finding_contract_violations(issue, known_evidence_ids=known_evidence_ids)
        if violations:
            problems.append(f"{getattr(issue, 'code', '<unknown>')}: {', '.join(violations)}")
    if problems:
        raise FindingContractError("finding contract failed: " + "; ".join(problems))


def matching_suppression(
    issue: Any, suppressions: Iterable[Suppression], *, design_id: str | None = None
) -> Suppression | None:
    """Return the exact matching suppression, without removing the finding."""

    for suppression in suppressions:
        if suppression.rule_id != getattr(issue, "rule_id", None):
            continue
        scope_name, target = next(iter(suppression.scope.items()))
        actual = {"ref": getattr(issue, "ref", ""), "net": getattr(issue, "net", ""), "design": design_id or ""}[
            scope_name
        ]
        if target == actual:
            return suppression
    return None


def apply_suppressions(
    issues: Iterable[Any], suppressions: Iterable[Suppression], *, design_id: str | None = None
) -> tuple[Any, ...]:
    """Mark matching findings, retaining every item for reports and denominators."""

    checked = validate_suppressions(suppressions)
    marked: list[Any] = []
    for issue in issues:
        match = matching_suppression(issue, checked, design_id=design_id)
        marked.append(issue.marked_suppressed(match.id) if match is not None else issue)
    return tuple(marked)
