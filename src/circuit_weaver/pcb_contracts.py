"""Frozen Epic C contracts shared by PCB handoff, constraints, and DRC.

This module deliberately contains no board-producing workflow.  It defines the
shapes and fail-closed boundaries that producer code must satisfy before the
first authoritative pad is emitted.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Final

from .validator import ValidationIssue

PREVIEW_FILENAME_SUFFIX: Final = "_placement_preview.kicad_pcb"
PREVIEW_BANNER: Final = "schematic_engine placement_preview"
AUTHORITATIVE_GENERATOR: Final = "circuit-weaver pcb_handoff"
DRC_EVIDENCE_KIND: Final = "tool_result"

_PAD_RE = re.compile(r"\(pad(?=[\s(\"])")
_FOOTPRINT_RE = re.compile(r"\(footprint(?=[\s\"])")
_TARGET_RE = re.compile(r"^(?:net:[^\s]+|comp:[A-Za-z][A-Za-z0-9_]*|net_class:[^\s]+)$")
_CONSTRAINT_ID_RE = re.compile(r"^PCBC-[A-Z_]+-[0-9a-f]{12}$")
_EVIDENCE_ID_RE = re.compile(r"^EV-[A-Z_]+-[0-9a-f]{12}$")

PCB_CONSTRAINT_CLASSES: Final = frozenset(
    {"net_class", "diff_pair", "width", "clearance", "via", "impedance", "length", "keepout", "placement"}
)
PCB_CONSTRAINT_ORIGINS: Final = frozenset({"calculated", "user", "manufacturer", "fab_profile"})


class PcbContractError(ValueError):
    """A PCB artifact or frozen contract violates an Epic C safety boundary."""


class PcbArtifactKind(str, Enum):
    """Structurally distinct PCB artifact classes; there is no upgrade state."""

    PREVIEW = "preview"
    AUTHORITATIVE = "authoritative"


@dataclass(frozen=True)
class PcbArtifactInspection:
    """Result of enforcing pads XOR preview-banner separation."""

    kind: PcbArtifactKind
    path: str
    has_preview_banner: bool
    pad_count: int
    footprint_count: int

    @property
    def has_pads(self) -> bool:
        return self.pad_count > 0


def inspect_pcb_artifact(path: str | Path, text: str | None = None) -> PcbArtifactInspection:
    """Classify a board only when exactly one frozen artifact contract holds.

    Preview artifacts carry the preview banner, use the preview filename, and
    contain zero pads.  Authoritative artifacts carry real footprints and at
    least one pad, never the banner, and never the preview filename.
    """

    board_path = Path(path)
    payload = board_path.read_text(encoding="utf-8") if text is None else text
    has_banner = PREVIEW_BANNER in payload
    pad_count = len(_PAD_RE.findall(payload))
    footprint_count = len(_FOOTPRINT_RE.findall(payload))
    preview_name = board_path.name.endswith(PREVIEW_FILENAME_SUFFIX)

    if has_banner:
        if pad_count:
            raise PcbContractError("preview banner and pads are mutually exclusive")
        if not preview_name:
            raise PcbContractError("preview artifact must use the frozen preview filename")
        kind = PcbArtifactKind.PREVIEW
    else:
        if preview_name:
            raise PcbContractError("preview filename cannot be relabeled as authoritative")
        if pad_count == 0 or footprint_count == 0:
            raise PcbContractError("authoritative board requires real footprints and pads")
        kind = PcbArtifactKind.AUTHORITATIVE

    if (pad_count > 0) == has_banner:
        raise PcbContractError("PCB artifact must satisfy pads XOR preview banner")
    return PcbArtifactInspection(
        kind=kind,
        path=str(board_path),
        has_preview_banner=has_banner,
        pad_count=pad_count,
        footprint_count=footprint_count,
    )


def require_fresh_authoritative_target(preview_path: str | Path | None, output_path: str | Path) -> Path:
    """Reject every in-place or preview-named authoritative-board target."""

    target = Path(output_path)
    if preview_path is not None and Path(preview_path).resolve() == target.resolve():
        raise PcbContractError("preview artifacts cannot be upgraded in place")
    if target.name.endswith(PREVIEW_FILENAME_SUFFIX):
        raise PcbContractError("authoritative board cannot use the preview filename")
    return target


def _canonical_params(params: Mapping[str, Any]) -> str:
    if not isinstance(params, Mapping) or not params:
        raise PcbContractError("PcbConstraint params must be a non-empty mapping")

    def normalize(value: Any, path: str) -> Any:
        if isinstance(value, Mapping):
            if set(value) == {"value", "unit"}:
                number = value["value"]
                unit = value["unit"]
                if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(float(number)):
                    raise PcbContractError(f"{path}.value must be a finite number")
                if not isinstance(unit, str) or not unit.strip():
                    raise PcbContractError(f"{path}.unit must be non-empty")
                return {"unit": unit.strip(), "value": number}
            return {str(key): normalize(nested, f"{path}.{key}") for key, nested in sorted(value.items())}
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [normalize(item, f"{path}[]") for item in value]
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)):
            raise PcbContractError(f"{path} numeric values must carry explicit units")
        raise PcbContractError(f"{path} contains an unsupported value")

    normalized = {str(key): normalize(value, f"params.{key}") for key, value in sorted(params.items())}
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@dataclass(frozen=True)
class PcbConstraint:
    """Evidence-linked, deterministic PCB intent compiled before mutation."""

    id: str
    klass: str
    target: str
    params: Mapping[str, Any]
    origin: str
    evidence_ids: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()

    @classmethod
    def create(
        cls,
        *,
        klass: str,
        target: str,
        params: Mapping[str, Any],
        origin: str,
        evidence_ids: Sequence[str] = (),
        conflicts: Sequence[str] = (),
    ) -> "PcbConstraint":
        canonical = _canonical_params(params)
        digest = hashlib.sha256(f"{target}|{klass}|{canonical}".encode()).hexdigest()[:12]
        record = cls(
            id=f"PCBC-{klass.upper()}-{digest}",
            klass=klass,
            target=target,
            params=json.loads(canonical),
            origin=origin,
            evidence_ids=tuple(sorted(set(evidence_ids))),
            conflicts=tuple(sorted(set(conflicts))),
        )
        validate_pcb_constraint(record)
        return record

    def to_dict(self) -> dict[str, object]:
        validate_pcb_constraint(self)
        return {
            "id": self.id,
            "klass": self.klass,
            "target": self.target,
            "params": json.loads(_canonical_params(self.params)),
            "origin": self.origin,
            "evidence_ids": list(self.evidence_ids),
            "conflicts": list(self.conflicts),
        }


def validate_pcb_constraint(constraint: PcbConstraint) -> None:
    """Validate the frozen record without normalizing an untrusted ID."""

    if constraint.klass not in PCB_CONSTRAINT_CLASSES:
        raise PcbContractError(f"unsupported PcbConstraint class: {constraint.klass!r}")
    if constraint.origin not in PCB_CONSTRAINT_ORIGINS:
        raise PcbContractError(f"unsupported PcbConstraint origin: {constraint.origin!r}")
    if not _TARGET_RE.fullmatch(constraint.target):
        raise PcbContractError("PcbConstraint target must be net:, comp:, or net_class:")
    canonical = _canonical_params(constraint.params)
    identity = f"{constraint.target}|{constraint.klass}|{canonical}"
    expected = f"PCBC-{constraint.klass.upper()}-{hashlib.sha256(identity.encode()).hexdigest()[:12]}"
    if constraint.id != expected or not _CONSTRAINT_ID_RE.fullmatch(constraint.id):
        raise PcbContractError("PcbConstraint ID does not match canonical content")
    if tuple(sorted(set(constraint.evidence_ids))) != constraint.evidence_ids or any(
        not _EVIDENCE_ID_RE.fullmatch(item) for item in constraint.evidence_ids
    ):
        raise PcbContractError("PcbConstraint evidence_ids must be sorted evidence IDs")
    if tuple(sorted(set(constraint.conflicts))) != constraint.conflicts or any(
        not _CONSTRAINT_ID_RE.fullmatch(item) for item in constraint.conflicts
    ):
        raise PcbContractError("PcbConstraint conflicts must be sorted constraint IDs")
    if constraint.id in constraint.conflicts:
        raise PcbContractError("PcbConstraint cannot conflict with itself")


def drc_validation_issue(
    *,
    rule_number: int,
    message: str,
    severity: str,
    evidence_ids: Sequence[str],
    ref: str = "",
    net: str = "",
    observed_value: str,
    expected_constraint: str,
    safest_next_action: str,
) -> ValidationIssue:
    """Return a DRC violation as T248's existing finding type, never a fork."""

    if not isinstance(rule_number, int) or not 1 <= rule_number <= 999:
        raise PcbContractError("DRC rule number must be between 1 and 999")
    rule_id = f"CW-DRC-{rule_number:03d}"
    return ValidationIssue(
        code=rule_id,
        ref=ref,
        net=net,
        message=message,
        suggestion=safest_next_action,
        detection_confidence="verified",
        severity=severity,
        rule_id=rule_id,
        observed_value=observed_value,
        expected_constraint=expected_constraint,
        evidence_ids=tuple(evidence_ids),
        safest_next_action=safest_next_action,
    )
