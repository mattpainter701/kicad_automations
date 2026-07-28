"""Single, evidence-gated manufacturing-readiness state machine."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .evidence_policy import EvidencePolicyError, require_fabrication_evidence


class ReadinessContractError(ValueError):
    """A readiness transition is unsupported or lacks required evidence."""


class ManufacturingReadinessState(str, Enum):
    NOT_READY = "not_ready"
    NEEDS_REVIEW = "needs_review"
    DRC_PENDING = "drc_pending"
    DRC_CLEAN = "drc_clean"
    FABRICATION_READY = "fabrication_ready"
    BLOCKED = "blocked"


_ORDER = (
    ManufacturingReadinessState.NOT_READY,
    ManufacturingReadinessState.NEEDS_REVIEW,
    ManufacturingReadinessState.DRC_PENDING,
    ManufacturingReadinessState.DRC_CLEAN,
    ManufacturingReadinessState.FABRICATION_READY,
)


@dataclass(frozen=True)
class ManufacturingReadiness:
    """The one readiness payload returned by every product surface."""

    state: ManufacturingReadinessState = ManufacturingReadinessState.NOT_READY
    blockers: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    next_actions: tuple[str, ...] = ()
    blocked_reason: str | None = None

    def __post_init__(self) -> None:
        if self.state is ManufacturingReadinessState.BLOCKED:
            if not self.blocked_reason or not self.blocked_reason.strip():
                raise ReadinessContractError("blocked readiness requires a reason")
        elif self.blocked_reason is not None:
            raise ReadinessContractError("blocked_reason is valid only for blocked readiness")
        for field_name in ("blockers", "evidence_ids", "next_actions"):
            values = getattr(self, field_name)
            if tuple(sorted(set(values))) != values:
                raise ReadinessContractError(f"{field_name} must be sorted and unique")

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "blockers": list(self.blockers),
            "evidence_ids": list(self.evidence_ids),
            "next_actions": list(self.next_actions),
            "blocked_reason": self.blocked_reason,
        }


def block_manufacturing_readiness(
    reason: str, *, blockers: Iterable[str] = (), evidence_ids: Iterable[str] = (), next_actions: Iterable[str] = ()
) -> ManufacturingReadiness:
    return ManufacturingReadiness(
        state=ManufacturingReadinessState.BLOCKED,
        blockers=tuple(sorted(set(blockers))),
        evidence_ids=tuple(sorted(set(evidence_ids))),
        next_actions=tuple(sorted(set(next_actions))),
        blocked_reason=reason,
    )


def transition_manufacturing_readiness(
    current: ManufacturingReadiness,
    target: ManufacturingReadinessState,
    *,
    evidence_records: Iterable[dict[str, Any]] = (),
    drc_passed: bool = False,
    blockers: Iterable[str] = (),
    next_actions: Iterable[str] = (),
) -> ManufacturingReadiness:
    """Advance exactly one evidence-gated state; blocked is terminal."""

    if current.state is ManufacturingReadinessState.BLOCKED:
        raise ReadinessContractError("blocked manufacturing readiness is terminal")
    if target is ManufacturingReadinessState.BLOCKED:
        raise ReadinessContractError("use block_manufacturing_readiness to supply a reason")
    current_index = _ORDER.index(current.state)
    target_index = _ORDER.index(target)
    if target_index != current_index + 1:
        raise ReadinessContractError("manufacturing readiness transitions must advance exactly one state")

    records = tuple(evidence_records)
    if target is ManufacturingReadinessState.DRC_CLEAN:
        has_verified_drc = any(
            record.get("subject_ref") == "tool:drc"
            and record.get("kind") == "tool_result"
            and record.get("confidence") in {"verified", "corroborated"}
            and not record.get("conflicts")
            for record in records
        )
        if not drc_passed or not has_verified_drc:
            raise ReadinessContractError("drc_clean requires passing verified tool:drc evidence")
    if target is ManufacturingReadinessState.FABRICATION_READY:
        try:
            require_fabrication_evidence(records)
        except EvidencePolicyError as exc:
            raise ReadinessContractError("fabrication_ready requires the T244.4 fabrication-evidence gate") from exc

    evidence_ids = tuple(
        sorted(
            set(current.evidence_ids)
            | {str(record["id"]) for record in records if isinstance(record.get("id"), str)}
        )
    )
    return ManufacturingReadiness(
        state=target,
        blockers=tuple(sorted(set(blockers))),
        evidence_ids=evidence_ids,
        next_actions=tuple(sorted(set(next_actions))),
    )

