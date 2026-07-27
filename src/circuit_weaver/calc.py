"""Deterministic, unit-explicit calculation records for passive design rules.

This module is deliberately a pure calculation substrate: it neither selects an
E-series value nor writes evidence.  Those policy/producer concerns are layered
on top of the immutable :class:`CalculationRecord` in later T246 slices.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final, Mapping

if TYPE_CHECKING:
    from .evidence import EvidenceLedger

_TARGET_RE: Final = re.compile(r"^param:[A-Za-z][A-Za-z0-9_]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
_FAMILY_RE: Final = re.compile(r"^[a-z][a-z0-9_]*$")
_EQUATION_VERSION: Final = "v1"
E_SERIES_VALUES: Final = {
    "E6": (1.0, 1.5, 2.2, 3.3, 4.7, 6.8),
    "E12": (1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2),
    "E24": (
        1.0,
        1.1,
        1.2,
        1.3,
        1.5,
        1.6,
        1.8,
        2.0,
        2.2,
        2.4,
        2.7,
        3.0,
        3.3,
        3.6,
        3.9,
        4.3,
        4.7,
        5.1,
        5.6,
        6.2,
        6.8,
        7.5,
        8.2,
        9.1,
    ),
    "E96": (
        1.00,
        1.02,
        1.05,
        1.07,
        1.10,
        1.13,
        1.15,
        1.18,
        1.21,
        1.24,
        1.27,
        1.30,
        1.33,
        1.37,
        1.40,
        1.43,
        1.47,
        1.50,
        1.54,
        1.58,
        1.62,
        1.65,
        1.69,
        1.74,
        1.78,
        1.82,
        1.87,
        1.91,
        1.96,
        2.00,
        2.05,
        2.10,
        2.15,
        2.21,
        2.26,
        2.32,
        2.37,
        2.43,
        2.49,
        2.55,
        2.61,
        2.67,
        2.74,
        2.80,
        2.87,
        2.94,
        3.01,
        3.09,
        3.16,
        3.24,
        3.32,
        3.40,
        3.48,
        3.57,
        3.65,
        3.74,
        3.83,
        3.92,
        4.02,
        4.12,
        4.22,
        4.32,
        4.42,
        4.53,
        4.64,
        4.75,
        4.87,
        4.99,
        5.11,
        5.23,
        5.36,
        5.49,
        5.62,
        5.76,
        5.90,
        6.04,
        6.19,
        6.34,
        6.49,
        6.65,
        6.81,
        6.98,
        7.15,
        7.32,
        7.50,
        7.68,
        7.87,
        8.06,
        8.25,
        8.45,
        8.66,
        8.87,
        9.09,
        9.31,
        9.53,
        9.76,
    ),
}
E_SERIES_TOLERANCES: Final = {"E6": 0.20, "E12": 0.10, "E24": 0.05, "E96": 0.01}
_SNAP_DIRECTIONS: Final = frozenset({"nearest", "up", "down"})
_CALCULATION_POLICIES: Final = frozenset({"datasheet", "equation", "bounded_fallback"})
_CALCULATION_CONFIDENCES: Final = frozenset({"verified", "corroborated", "single_source", "heuristic", "stub"})
_WITHHELD_FINDING_ID_RE: Final = re.compile(r"^CW-PSV-00[1-3]-[a-f0-9]{12}$")
_PASSIVE_SYNTHESIS_RULES: Final = {
    "missing_basis": ("CW-PSV-001", "provide datasheet recommendation or equation inputs"),
    "out_of_range": ("CW-PSV-002", "choose a value within the declared safe range"),
    "incompatible_network": ("CW-PSV-003", "select a compatible passive network"),
}
_DATASHEET_EVIDENCE_ID_RE: Final = re.compile(r"^EV-DATASHEET-[a-f0-9]{12}$")
_FALLBACK_VERSION: Final = "bounded-fallback/v1"


@dataclass(frozen=True)
class CalculationInput:
    """One SI-valued calculation input and the evidence that backs it."""

    name: str
    value: float
    unit: str
    evidence_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "evidence_id": self.evidence_id,
        }


@dataclass(frozen=True)
class CalculationValue:
    """A scalar SI value retained with its unit."""

    value: float
    unit: str

    def to_dict(self) -> dict[str, object]:
        return {"value": self.value, "unit": self.unit}


@dataclass(frozen=True)
class ChosenValue:
    """A future E-series-selected value; absent during pure calculation."""

    value: float
    unit: str
    e_series: str | None = None
    tolerance: float | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "value": self.value,
            "unit": self.unit,
            "e_series": self.e_series,
            "tolerance": self.tolerance,
        }


@dataclass(frozen=True)
class SnapPolicy:
    """The declared future selection policy, never an implicit rounding guess."""

    series: str
    direction: str

    def to_dict(self) -> dict[str, str]:
        return {"series": self.series, "direction": self.direction}


@dataclass(frozen=True)
class CalculationMargin:
    """A checked bound and whether the selected value satisfies it."""

    kind: str
    value: float
    unit: str
    ok: bool

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "value": self.value, "unit": self.unit, "ok": self.ok}


@dataclass(frozen=True)
class CalculationRecord:
    """Frozen calculation contract shared by synthesis and validation.

    ``chosen_value``, ``snap_policy``, ``margin``, and ``emits_evidence`` remain
    ``None`` for this pure-equation slice.  Their explicit null representation
    keeps the record shape stable for later policy and ledger producers.
    """

    id: str
    equation_id: str
    equation_version: str
    target: str
    inputs: tuple[CalculationInput, ...]
    equation_str: str
    raw_result: CalculationValue
    chosen_value: ChosenValue | None = None
    snap_policy: SnapPolicy | None = None
    margin: CalculationMargin | None = None
    policy: str = "equation"
    confidence: str = "single_source"
    emits_evidence: str | None = None
    withheld_finding_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe, contract-shaped representation."""

        return {
            "id": self.id,
            "equation_id": self.equation_id,
            "equation_version": self.equation_version,
            "target": self.target,
            "inputs": [calculation_input.to_dict() for calculation_input in self.inputs],
            "equation_str": self.equation_str,
            "raw_result": self.raw_result.to_dict(),
            "chosen_value": None if self.chosen_value is None else self.chosen_value.to_dict(),
            "snap_policy": None if self.snap_policy is None else self.snap_policy.to_dict(),
            "margin": None if self.margin is None else self.margin.to_dict(),
            "policy": self.policy,
            "confidence": self.confidence,
            "emits_evidence": self.emits_evidence,
            "withheld_finding_id": self.withheld_finding_id,
        }


@dataclass(frozen=True)
class PassiveSynthesisFinding:
    """Frozen fail-closed finding that explains why a passive value was withheld."""

    id: str
    rule_id: str
    calculation_id: str
    target: str
    reason: str
    observed: CalculationValue | None
    expected_min: float | None
    expected_max: float | None
    expected_unit: str
    evidence_ids: tuple[str, ...]
    remediation: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "rule_id": self.rule_id,
            "calculation_id": self.calculation_id,
            "target": self.target,
            "reason": self.reason,
            "observed": None if self.observed is None else self.observed.to_dict(),
            "expected": {"min": self.expected_min, "max": self.expected_max, "unit": self.expected_unit},
            "evidence_ids": list(self.evidence_ids),
            "remediation": self.remediation,
        }


@dataclass(frozen=True)
class PassiveSelectionDecision:
    """A selection record plus the finding that makes a failed selection explicit."""

    calculation: CalculationRecord
    finding: PassiveSynthesisFinding | None = None


@dataclass(frozen=True)
class DividerPairSelection:
    """A jointly selected feedback-divider pair and its realized output error."""

    top: CalculationRecord
    bottom: CalculationRecord
    target_vout_v: float
    realized_vout_v: float
    relative_error: float
    max_scale_factor: float


def _valid_bound(value: float | None, field: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(f"{field} must be a finite number or null")
    return float(value)


def passive_synthesis_finding(
    calculation: CalculationRecord,
    *,
    reason: str,
    expected_min: float | None = None,
    expected_max: float | None = None,
    expected_unit: str | None = None,
    observed_value: float | None = None,
    evidence_ids: tuple[str, ...] = (),
    remediation: str | None = None,
) -> PassiveSynthesisFinding:
    """Build a deterministic, self-describing passive-synthesis violation."""

    if reason not in _PASSIVE_SYNTHESIS_RULES:
        raise ValueError(f"unsupported passive synthesis reason: {reason!r}")
    lower = _valid_bound(expected_min, "expected_min")
    upper = _valid_bound(expected_max, "expected_max")
    if (lower is None) != (upper is None):
        raise ValueError("expected_min and expected_max must be supplied together")
    if lower is not None and lower > upper:
        raise ValueError("expected_min must not exceed expected_max")
    if reason == "out_of_range" and lower is None:
        raise ValueError("out_of_range findings require bounded expected values")
    unit = calculation.raw_result.unit if expected_unit is None else expected_unit
    if not isinstance(unit, str) or not unit:
        raise ValueError("expected_unit must be non-empty")
    if unit != calculation.raw_result.unit:
        raise ValueError("expected_unit must match the calculation result unit")
    observed = (
        calculation.raw_result
        if observed_value is None
        else CalculationValue(_finite_positive(observed_value, "observed_value"), unit)
    )
    if reason == "out_of_range" and lower <= observed.value <= upper:  # type: ignore[operator]
        raise ValueError("out_of_range finding requires an observed value outside the expected range")
    rule_id, default_remediation = _PASSIVE_SYNTHESIS_RULES[reason]
    sorted_evidence_ids = tuple(sorted(set(evidence_ids)))
    payload = {
        "calculation_id": calculation.id,
        "target": calculation.target,
        "reason": reason,
        "observed": observed.to_dict(),
        "expected_min": lower,
        "expected_max": upper,
        "expected_unit": unit,
        "evidence_ids": sorted_evidence_ids,
        "remediation": default_remediation if remediation is None else remediation,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()[:12]
    return PassiveSynthesisFinding(
        id=f"{rule_id}-{digest}",
        rule_id=rule_id,
        calculation_id=calculation.id,
        target=calculation.target,
        reason=reason,
        observed=observed,
        expected_min=lower,
        expected_max=upper,
        expected_unit=unit,
        evidence_ids=sorted_evidence_ids,
        remediation=default_remediation if remediation is None else remediation,
    )


def withhold_calculation(
    calculation: CalculationRecord,
    *,
    reason: str,
    expected_min: float | None = None,
    expected_max: float | None = None,
    expected_unit: str | None = None,
    observed_value: float | None = None,
    evidence_ids: tuple[str, ...] = (),
    remediation: str | None = None,
    policy: str | None = None,
    confidence: str | None = None,
) -> tuple[CalculationRecord, PassiveSynthesisFinding]:
    """Fail closed by withholding a calculation value before netlist emission."""

    selected_policy = calculation.policy if policy is None else policy
    selected_confidence = calculation.confidence if confidence is None else confidence
    if selected_policy not in _CALCULATION_POLICIES:
        raise ValueError(f"unsupported calculation policy: {selected_policy!r}")
    if selected_confidence not in _CALCULATION_CONFIDENCES:
        raise ValueError(f"unsupported calculation confidence: {selected_confidence!r}")
    if selected_policy == "bounded_fallback" and selected_confidence != "heuristic":
        raise ValueError("bounded_fallback policy requires heuristic confidence")
    finding = passive_synthesis_finding(
        calculation,
        reason=reason,
        expected_min=expected_min,
        expected_max=expected_max,
        expected_unit=expected_unit,
        observed_value=observed_value,
        evidence_ids=evidence_ids,
        remediation=remediation,
    )
    margin_value = 0.0
    if finding.expected_min is not None:
        margin_value = min(
            finding.observed.value - finding.expected_min,  # type: ignore[union-attr]
            finding.expected_max - finding.observed.value,  # type: ignore[union-attr]
        )
    withheld = replace(
        calculation,
        chosen_value=None,
        margin=CalculationMargin(kind=f"withheld:{reason}", value=margin_value, unit=finding.expected_unit, ok=False),
        policy=selected_policy,
        confidence=selected_confidence,
        emits_evidence=None,
        withheld_finding_id=finding.id,
    )
    return withheld, finding


def validate_passive_synthesis_finding(finding: PassiveSynthesisFinding, calculation: CalculationRecord) -> None:
    """Reject a finding whose deterministic identity is not bound to ``calculation``."""

    expected = passive_synthesis_finding(
        calculation,
        reason=finding.reason,
        expected_min=finding.expected_min,
        expected_max=finding.expected_max,
        expected_unit=finding.expected_unit,
        observed_value=None if finding.observed is None else finding.observed.value,
        evidence_ids=finding.evidence_ids,
        remediation=finding.remediation,
    )
    if finding != expected:
        raise ValueError("passive synthesis finding does not match its deterministic calculation association")


def is_selection_eligible(calculation: CalculationRecord) -> bool:
    """Return whether a value may be emitted to a synthesized netlist."""

    return calculation.withheld_finding_id is None and calculation.chosen_value is not None


def require_selection(calculation: CalculationRecord) -> ChosenValue:
    """Return the selected value or fail closed before a producer emits it."""

    if calculation.withheld_finding_id is not None:
        raise ValueError(f"calculation value is withheld by {calculation.withheld_finding_id}")
    if calculation.chosen_value is None:
        raise ValueError("calculation has no selected value")
    return calculation.chosen_value


def _validate_withheld_state(calculation: CalculationRecord) -> None:
    if calculation.withheld_finding_id is None:
        return
    if not _WITHHELD_FINDING_ID_RE.fullmatch(calculation.withheld_finding_id):
        raise ValueError("calculation withheld_finding_id is malformed")
    if calculation.chosen_value is not None:
        raise ValueError("withheld calculation must not contain a chosen value")
    if calculation.margin is None or calculation.margin.ok:
        raise ValueError("withheld calculation must have a failed margin")


def _require_datasheet_evidence(evidence_id: str) -> str:
    if not _DATASHEET_EVIDENCE_ID_RE.fullmatch(evidence_id):
        raise ValueError("datasheet selection requires an EV-DATASHEET evidence ID")
    return evidence_id


def _scalar_selection_record(
    *,
    target: str,
    equation_id: str,
    equation_version: str,
    equation_str: str,
    inputs: tuple[CalculationInput, ...],
    raw_value: float,
    unit: str,
    chosen_value: ChosenValue | None,
    snap_policy: SnapPolicy | None,
    margin: CalculationMargin | None,
    policy: str,
    confidence: str,
) -> CalculationRecord:
    if policy not in _CALCULATION_POLICIES or confidence not in _CALCULATION_CONFIDENCES:
        raise ValueError("invalid calculation policy or confidence")
    return CalculationRecord(
        id=calculation_id(target, equation_id, inputs, equation_version),
        equation_id=equation_id,
        equation_version=equation_version,
        target=target,
        inputs=inputs,
        equation_str=equation_str,
        raw_result=CalculationValue(_finite_positive(raw_value, "raw_value"), unit),
        chosen_value=chosen_value,
        snap_policy=snap_policy,
        margin=margin,
        policy=policy,
        confidence=confidence,
    )


def datasheet_selected_scalar(
    *,
    target: str,
    value: float,
    unit: str,
    evidence_id: str,
    tolerance: float | None = None,
) -> CalculationRecord:
    """Create a traceable scalar selected directly from a datasheet recommendation."""

    evidence_id = _require_datasheet_evidence(evidence_id)
    if not isinstance(unit, str) or not unit:
        raise ValueError("unit must be non-empty")
    selected = _finite_positive(value, "value")
    if tolerance is not None:
        tolerance = _finite_positive(tolerance, "tolerance")
    inputs = (CalculationInput("datasheet_value", selected, unit, evidence_id),)
    return _scalar_selection_record(
        target=target,
        equation_id="datasheet_selection",
        equation_version="v1",
        equation_str="datasheet-recommended value",
        inputs=inputs,
        raw_value=selected,
        unit=unit,
        chosen_value=ChosenValue(selected, unit, None, tolerance),
        snap_policy=None,
        margin=CalculationMargin("datasheet_selection", 0.0, unit, True),
        policy="datasheet",
        confidence="single_source",
    )


def bounded_fallback_scalar(
    *,
    target: str,
    value: float,
    minimum: float,
    maximum: float,
    unit: str,
    series: str | None = None,
    direction: str = "nearest",
    tolerance: float | None = None,
) -> PassiveSelectionDecision:
    """Select a declared bounded fallback or explicitly withhold it before emission."""

    raw_value = _finite_positive(value, "value")
    minimum = _finite_positive(minimum, "minimum")
    maximum = _finite_positive(maximum, "maximum")
    if minimum > maximum:
        raise ValueError("minimum must not exceed maximum")
    if not isinstance(unit, str) or not unit:
        raise ValueError("unit must be non-empty")
    inputs = (
        CalculationInput("fallback_value", raw_value, unit),
        CalculationInput("minimum", minimum, unit),
        CalculationInput("maximum", maximum, unit),
        CalculationInput("policy_version", 1.0, "version"),
    )
    record = _scalar_selection_record(
        target=target,
        equation_id="bounded_fallback",
        equation_version=_FALLBACK_VERSION,
        equation_str="declared bounded fallback",
        inputs=inputs,
        raw_value=raw_value,
        unit=unit,
        chosen_value=None,
        snap_policy=None,
        margin=None,
        policy="bounded_fallback",
        confidence="heuristic",
    )
    if series is None:
        chosen = raw_value
        chosen_tolerance = tolerance
        snap_policy = None
    else:
        chosen = select_e_series(raw_value, series=series, direction=direction)
        chosen_tolerance = (
            E_SERIES_TOLERANCES[series] if tolerance is None else _finite_positive(tolerance, "tolerance")
        )
        snap_policy = SnapPolicy(series, direction)
    if not minimum <= chosen <= maximum:
        withheld, finding = withhold_calculation(
            record,
            reason="out_of_range",
            expected_min=minimum,
            expected_max=maximum,
            expected_unit=unit,
            observed_value=chosen,
            policy="bounded_fallback",
            confidence="heuristic",
        )
        return PassiveSelectionDecision(withheld, finding)
    return PassiveSelectionDecision(
        replace(
            record,
            chosen_value=ChosenValue(chosen, unit, series, chosen_tolerance),
            snap_policy=snap_policy,
            margin=CalculationMargin("fallback_headroom", min(chosen - minimum, maximum - chosen), unit, True),
        )
    )


def termination_resistor_match(
    *,
    target: str,
    impedance_ohm: float,
    evidence_id: str | None = None,
    series: str = "E24",
    direction: str = "nearest",
    tolerance: float | None = None,
) -> CalculationRecord:
    """Represent the direct termination rule ``Rterm = Z0`` and its declared snap."""

    impedance_ohm = _finite_positive(impedance_ohm, "impedance_ohm")
    inputs = (CalculationInput("impedance_ohm", impedance_ohm, "ohm", evidence_id),)
    raw = _scalar_selection_record(
        target=target,
        equation_id="term_resistor",
        equation_version="v1",
        equation_str="Rterm = Z0",
        inputs=inputs,
        raw_value=impedance_ohm,
        unit="ohm",
        chosen_value=None,
        snap_policy=None,
        margin=None,
        policy="equation",
        confidence="single_source",
    )
    return apply_e_series_selection(raw, series=series, direction=direction, tolerance=tolerance)


def ldo_minimum_capacitor(
    *,
    target: str,
    minimum_capacitance_f: float,
    evidence_id: str,
    series: str = "E24",
    tolerance: float | None = None,
) -> PassiveSelectionDecision:
    """Select an upward-snapped LDO minimum capacitor from a datasheet-backed limit."""

    evidence_id = _require_datasheet_evidence(evidence_id)
    minimum_capacitance_f = _finite_positive(minimum_capacitance_f, "minimum_capacitance_f")
    raw = _scalar_selection_record(
        target=target,
        equation_id="ldo_io_cap",
        equation_version="v1",
        equation_str="Cselected >= Cminimum",
        inputs=(CalculationInput("minimum_capacitance_f", minimum_capacitance_f, "F", evidence_id),),
        raw_value=minimum_capacitance_f,
        unit="F",
        chosen_value=None,
        snap_policy=None,
        margin=None,
        policy="datasheet",
        confidence="single_source",
    )
    selected = apply_capacitor_selection(raw, series=series, tolerance=tolerance)
    return PassiveSelectionDecision(
        replace(
            selected,
            policy="datasheet",
            confidence="single_source",
            margin=CalculationMargin(
                "minimum_cap_headroom",
                selected.chosen_value.value - minimum_capacitance_f,  # type: ignore[union-attr]
                "F",
                True,
            ),
        )
    )


def _calculation_claim(calculation: CalculationRecord) -> str:
    """Return the deterministic, self-contained evidence claim for a calculation."""

    canonical_inputs = sorted(
        (calculation_input.to_dict() for calculation_input in calculation.inputs),
        key=lambda calculation_input: str(calculation_input["name"]),
    )
    payload = {
        "calculation_id": calculation.id,
        "confidence": calculation.confidence,
        "equation_id": calculation.equation_id,
        "equation_str": calculation.equation_str,
        "equation_version": calculation.equation_version,
        "input_evidence_ids": sorted(
            calculation_input.evidence_id
            for calculation_input in calculation.inputs
            if calculation_input.evidence_id is not None
        ),
        "inputs": canonical_inputs,
        "margin": None if calculation.margin is None else calculation.margin.to_dict(),
        "policy": calculation.policy,
        "raw_result": calculation.raw_result.to_dict(),
        "snap_policy": None if calculation.snap_policy is None else calculation.snap_policy.to_dict(),
        "chosen_value": None if calculation.chosen_value is None else calculation.chosen_value.to_dict(),
        "withheld_finding_id": calculation.withheld_finding_id,
    }
    return "calculation=" + json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def emit_calculation_evidence(calculation: CalculationRecord, ledger: "EvidenceLedger") -> CalculationRecord:
    """Append one deterministic calculation record to ``ledger`` without mutating ``calculation``.

    The input evidence IDs must already resolve in the supplied ledger.  This
    producer therefore never upgrades a dangling reference into provenance.
    """

    from .evidence import EvidenceLedger, EvidenceSource, evidence_id

    if not isinstance(ledger, EvidenceLedger):
        raise TypeError("ledger must be an EvidenceLedger")
    expected_calculation_id = calculation_id(
        calculation.target,
        calculation.equation_id,
        calculation.inputs,
        calculation.equation_version,
    )
    if calculation.id != expected_calculation_id:
        raise ValueError("calculation ID does not match its deterministic inputs")
    _validate_withheld_state(calculation)
    if not math.isfinite(calculation.raw_result.value):
        raise ValueError("calculation raw result must be finite")
    unresolved = sorted(
        {
            calculation_input.evidence_id
            for calculation_input in calculation.inputs
            if calculation_input.evidence_id is not None and ledger.get(calculation_input.evidence_id) is None
        }
    )
    if unresolved:
        raise ValueError(f"calculation input evidence does not resolve: {', '.join(unresolved)}")

    source = EvidenceSource(extraction_method="circuit-weaver-calc")
    claim = _calculation_claim(calculation)
    expected_evidence_id = evidence_id(calculation.target, claim, "calculation", source)
    if calculation.emits_evidence is not None and calculation.emits_evidence != expected_evidence_id:
        raise ValueError("calculation emits_evidence does not match emitted evidence")
    evidence_id = ledger.record(
        subject_ref=calculation.target,
        claim=claim,
        kind="calculation",
        source=source,
        confidence=calculation.confidence,
        freshness="unknown",
    )
    return replace(calculation, emits_evidence=evidence_id)


def _input_value(
    value: float, *, name: str, unit: str, evidence_ids: Mapping[str, str | None] | None
) -> CalculationInput:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return CalculationInput(name=name, value=float(value), unit=unit, evidence_id=(evidence_ids or {}).get(name))


def _positive_input(
    value: float, *, name: str, unit: str, evidence_ids: Mapping[str, str | None] | None
) -> CalculationInput:
    calculation_input = _input_value(value, name=name, unit=unit, evidence_ids=evidence_ids)
    if calculation_input.value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return calculation_input


def _nonnegative_input(
    value: float, *, name: str, unit: str, evidence_ids: Mapping[str, str | None] | None
) -> CalculationInput:
    calculation_input = _input_value(value, name=name, unit=unit, evidence_ids=evidence_ids)
    if calculation_input.value < 0:
        raise ValueError(f"{name} must not be negative")
    return calculation_input


def _input_token(calculation_input: CalculationInput) -> str:
    return f"{calculation_input.name}:{format(calculation_input.value, '.17g')}:{calculation_input.unit}"


def calculation_id(
    target: str,
    equation_id: str,
    inputs: tuple[CalculationInput, ...],
    equation_version: str = _EQUATION_VERSION,
) -> str:
    """Return the frozen deterministic ID for a calculation's semantic inputs."""

    if not _TARGET_RE.fullmatch(target):
        raise ValueError(f"invalid calculation target: {target!r}")
    if not _FAMILY_RE.fullmatch(equation_id):
        raise ValueError(f"invalid equation_id: {equation_id!r}")
    if not equation_version:
        raise ValueError("equation_version must be non-empty")
    if len({calculation_input.name for calculation_input in inputs}) != len(inputs):
        raise ValueError("calculation input names must be unique")
    payload = "|".join((target, equation_id, *sorted(_input_token(item) for item in inputs), equation_version))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"CALC-{equation_id.upper()}-{digest}"


def _finite_positive(value: float, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{field} must be a finite number greater than zero")
    return float(value)


def _series_values_near(value: float, series: str, *, decades: int = 1) -> tuple[float, ...]:
    """Return deterministic E-series candidates around a positive SI value."""

    value = _finite_positive(value, "value")
    if series not in E_SERIES_VALUES:
        raise ValueError(f"unsupported E-series: {series!r}")
    decade = math.floor(math.log10(value))
    return tuple(
        base * (10.0**power)
        for power in range(decade - decades, decade + decades + 1)
        for base in E_SERIES_VALUES[series]
    )


def select_e_series(value: float, *, series: str = "E24", direction: str = "nearest") -> float:
    """Select a deterministic standard value across E-series decades.

    Exact midpoint ties for ``nearest`` select the lower standard value.  That
    stable tie-break prevents a platform-dependent rounding decision.
    """

    value = _finite_positive(value, "value")
    if direction not in _SNAP_DIRECTIONS:
        raise ValueError(f"unsupported E-series snap direction: {direction!r}")
    candidates = _series_values_near(value, series)
    if direction == "nearest":
        return min(candidates, key=lambda candidate: (abs(candidate - value), candidate))
    if direction == "up":
        return min(candidate for candidate in candidates if candidate >= value)
    return max(candidate for candidate in candidates if candidate <= value)


def apply_e_series_selection(
    calculation: CalculationRecord,
    *,
    series: str = "E24",
    direction: str = "nearest",
    tolerance: float | None = None,
) -> CalculationRecord:
    """Return an immutable record with a declared scalar E-series selection."""

    chosen = select_e_series(calculation.raw_result.value, series=series, direction=direction)
    chosen_tolerance = E_SERIES_TOLERANCES[series] if tolerance is None else _finite_positive(tolerance, "tolerance")
    relative_error = (chosen - calculation.raw_result.value) / calculation.raw_result.value
    return replace(
        calculation,
        chosen_value=ChosenValue(chosen, calculation.raw_result.unit, series, chosen_tolerance),
        snap_policy=SnapPolicy(series, direction),
        margin=CalculationMargin(kind="snap_error", value=relative_error, unit="ratio", ok=True),
        emits_evidence=None,
    )


def apply_capacitor_selection(
    calculation: CalculationRecord,
    *,
    series: str = "E24",
    tolerance: float | None = None,
) -> CalculationRecord:
    """Round a capacitance requirement upward so a minimum-cap margin is retained."""

    if calculation.raw_result.unit != "F":
        raise ValueError("capacitor selection requires a farad-valued calculation")
    return apply_e_series_selection(calculation, series=series, direction="up", tolerance=tolerance)


def apply_ratio_preserving_divider_selection(
    top: CalculationRecord,
    bottom: CalculationRecord,
    *,
    target_vout_v: float,
    vref_v: float,
    series: str = "E96",
    tolerance: float | None = None,
    max_scale_factor: float = 2.0,
) -> DividerPairSelection:
    """Jointly snap a feedback-divider pair to minimize realized output error.

    The pair is searched together rather than independently rounded.  Ties
    first prefer values closest to the raw pair, then the numerically smaller
    pair, yielding a deterministic and ratio-preserving policy.
    """

    if top.raw_result.unit != "ohm" or bottom.raw_result.unit != "ohm":
        raise ValueError("divider selection requires ohm-valued top and bottom calculations")
    target_vout_v = _finite_positive(target_vout_v, "target_vout_v")
    vref_v = _finite_positive(vref_v, "vref_v")
    raw_top = _finite_positive(top.raw_result.value, "top raw result")
    raw_bottom = _finite_positive(bottom.raw_result.value, "bottom raw result")
    if target_vout_v <= vref_v:
        raise ValueError("target_vout_v must be greater than vref_v")
    max_scale_factor = _finite_positive(max_scale_factor, "max_scale_factor")
    if max_scale_factor < 1.0:
        raise ValueError("max_scale_factor must be at least 1.0")
    if series not in E_SERIES_VALUES:
        raise ValueError(f"unsupported E-series: {series!r}")
    chosen_tolerance = E_SERIES_TOLERANCES[series] if tolerance is None else _finite_positive(tolerance, "tolerance")

    candidates_top = tuple(
        candidate
        for candidate in _series_values_near(raw_top, series)
        if raw_top / max_scale_factor <= candidate <= raw_top * max_scale_factor
    )
    candidates_bottom = tuple(
        candidate
        for candidate in _series_values_near(raw_bottom, series)
        if raw_bottom / max_scale_factor <= candidate <= raw_bottom * max_scale_factor
    )
    if not candidates_top or not candidates_bottom:
        raise ValueError("no E-series divider pair satisfies the declared impedance scale window")
    selections = (
        (
            abs(vref_v * (1.0 + candidate_top / candidate_bottom) - target_vout_v),
            abs(math.log(candidate_top / raw_top)) + abs(math.log(candidate_bottom / raw_bottom)),
            candidate_top,
            candidate_bottom,
        )
        for candidate_top in candidates_top
        for candidate_bottom in candidates_bottom
    )
    _, _, selected_top, selected_bottom = min(selections)
    realized_vout = vref_v * (1.0 + selected_top / selected_bottom)
    relative_error = (realized_vout - target_vout_v) / target_vout_v
    margin = CalculationMargin(
        kind=f"vout_error_within_{max_scale_factor:g}x_leg_scale",
        value=realized_vout - target_vout_v,
        unit="V",
        ok=True,
    )
    selected_top_record = replace(
        top,
        chosen_value=ChosenValue(selected_top, "ohm", series, chosen_tolerance),
        snap_policy=SnapPolicy(series, "ratio_preserving"),
        margin=margin,
        emits_evidence=None,
    )
    selected_bottom_record = replace(
        bottom,
        chosen_value=ChosenValue(selected_bottom, "ohm", series, chosen_tolerance),
        snap_policy=SnapPolicy(series, "ratio_preserving"),
        margin=margin,
        emits_evidence=None,
    )
    return DividerPairSelection(
        top=selected_top_record,
        bottom=selected_bottom_record,
        target_vout_v=target_vout_v,
        realized_vout_v=realized_vout,
        relative_error=relative_error,
        max_scale_factor=max_scale_factor,
    )


def _record(
    *,
    target: str,
    equation_id: str,
    inputs: tuple[CalculationInput, ...],
    equation_str: str,
    result: float,
    unit: str,
    equation_version: str = _EQUATION_VERSION,
) -> CalculationRecord:
    if not math.isfinite(result):
        raise ValueError(f"{equation_id} result must be finite")
    return CalculationRecord(
        id=calculation_id(target, equation_id, inputs, equation_version),
        equation_id=equation_id,
        equation_version=equation_version,
        target=target,
        inputs=inputs,
        equation_str=equation_str,
        raw_result=CalculationValue(value=result, unit=unit),
    )


def buck_inductor(
    *,
    target: str,
    vin_v: float,
    vout_v: float,
    switching_frequency_hz: float,
    output_current_a: float,
    ripple_ratio: float = 0.3,
    evidence_ids: Mapping[str, str | None] | None = None,
) -> CalculationRecord:
    """Size an ideal continuous-conduction buck inductor from output-current ripple."""

    inputs = (
        _positive_input(vin_v, name="vin_v", unit="V", evidence_ids=evidence_ids),
        _positive_input(vout_v, name="vout_v", unit="V", evidence_ids=evidence_ids),
        _positive_input(
            switching_frequency_hz,
            name="switching_frequency_hz",
            unit="Hz",
            evidence_ids=evidence_ids,
        ),
        _positive_input(output_current_a, name="output_current_a", unit="A", evidence_ids=evidence_ids),
        _positive_input(ripple_ratio, name="ripple_ratio", unit="ratio", evidence_ids=evidence_ids),
    )
    if inputs[0].value <= inputs[1].value:
        raise ValueError("ideal buck sizing requires vin_v greater than vout_v")
    duty_cycle = inputs[1].value / inputs[0].value
    ripple_current = inputs[4].value * inputs[3].value
    result = (inputs[0].value - inputs[1].value) * duty_cycle / (inputs[2].value * ripple_current)
    return _record(
        target=target,
        equation_id="buck_inductor",
        equation_version="ideal-ccm-buck/v1",
        inputs=inputs,
        equation_str="L = (Vin - Vout)*(Vout/Vin)/(fsw*ripple_ratio*Iout) [ideal CCM buck]",
        result=result,
        unit="H",
    )


def buck_output_cap(
    *,
    target: str,
    ripple_current_a: float,
    switching_frequency_hz: float,
    output_ripple_v: float = 0.020,
    evidence_ids: Mapping[str, str | None] | None = None,
) -> CalculationRecord:
    """Size ideal buck output capacitance from triangular ripple, excluding ESR."""

    inputs = (
        _positive_input(ripple_current_a, name="ripple_current_a", unit="A", evidence_ids=evidence_ids),
        _positive_input(
            switching_frequency_hz,
            name="switching_frequency_hz",
            unit="Hz",
            evidence_ids=evidence_ids,
        ),
        _positive_input(output_ripple_v, name="output_ripple_v", unit="V", evidence_ids=evidence_ids),
    )
    result = inputs[0].value / (8.0 * inputs[1].value * inputs[2].value)
    return _record(
        target=target,
        equation_id="buck_output_cap",
        equation_version="ideal-triangular-ripple-no-esr/v1",
        inputs=inputs,
        equation_str="Cout = delta_IL/(8*fsw*delta_Vout) [ideal triangular ripple; ESR excluded]",
        result=result,
        unit="F",
    )


def _ideal_boost_inductor_result(
    vin_v: float, vout_v: float, fsw_hz: float, iout_a: float, ripple_ratio: float
) -> float:
    duty_cycle = 1.0 - vin_v / vout_v
    input_current = iout_a / (1.0 - duty_cycle)
    ripple_current = ripple_ratio * input_current
    return vin_v * duty_cycle / (fsw_hz * ripple_current)


def boost_inductor(
    *,
    target: str,
    vin_v: float,
    vout_v: float,
    switching_frequency_hz: float,
    output_current_a: float,
    ripple_ratio: float = 0.3,
    evidence_ids: Mapping[str, str | None] | None = None,
) -> CalculationRecord:
    """Size an ideal CCM boost inductor, treating input current as Iout/(1-D)."""

    inputs = (
        _positive_input(vin_v, name="vin_v", unit="V", evidence_ids=evidence_ids),
        _positive_input(vout_v, name="vout_v", unit="V", evidence_ids=evidence_ids),
        _positive_input(
            switching_frequency_hz,
            name="switching_frequency_hz",
            unit="Hz",
            evidence_ids=evidence_ids,
        ),
        _positive_input(output_current_a, name="output_current_a", unit="A", evidence_ids=evidence_ids),
        _positive_input(ripple_ratio, name="ripple_ratio", unit="ratio", evidence_ids=evidence_ids),
    )
    if inputs[1].value <= inputs[0].value:
        raise ValueError("ideal boost sizing requires vout_v greater than vin_v")
    result = _ideal_boost_inductor_result(*(calculation_input.value for calculation_input in inputs))
    return _record(
        target=target,
        equation_id="boost_inductor",
        equation_version="ideal-ccm-boost/v1",
        inputs=inputs,
        equation_str="L = Vin*(1-Vin/Vout)/(fsw*ripple_ratio*(Iout/(Vin/Vout))) [ideal CCM boost]",
        result=result,
        unit="H",
    )


def buck_boost_inductor(
    *,
    target: str,
    vin_min_v: float,
    vout_v: float,
    switching_frequency_hz: float,
    output_current_a: float,
    ripple_ratio: float = 0.3,
    evidence_ids: Mapping[str, str | None] | None = None,
) -> CalculationRecord:
    """Size a buck-boost inductor using its worst-case ideal boost mode at minimum input."""

    inputs = (
        _positive_input(vin_min_v, name="vin_min_v", unit="V", evidence_ids=evidence_ids),
        _positive_input(vout_v, name="vout_v", unit="V", evidence_ids=evidence_ids),
        _positive_input(
            switching_frequency_hz,
            name="switching_frequency_hz",
            unit="Hz",
            evidence_ids=evidence_ids,
        ),
        _positive_input(output_current_a, name="output_current_a", unit="A", evidence_ids=evidence_ids),
        _positive_input(ripple_ratio, name="ripple_ratio", unit="ratio", evidence_ids=evidence_ids),
    )
    if inputs[1].value <= inputs[0].value:
        raise ValueError("buck-boost worst-case boost sizing requires vout_v greater than vin_min_v")
    result = _ideal_boost_inductor_result(*(calculation_input.value for calculation_input in inputs))
    return _record(
        target=target,
        equation_id="buck_boost_inductor",
        equation_version="ideal-ccm-worst-boost/v1",
        inputs=inputs,
        equation_str="L = Vin_min*(1-Vin_min/Vout)/(fsw*ripple_ratio*(Iout/(Vin_min/Vout))) [worst boost mode]",
        result=result,
        unit="H",
    )


def feedback_divider_top(
    *,
    target: str,
    vout_v: float,
    vref_v: float,
    r_bottom_ohm: float,
    evidence_ids: Mapping[str, str | None] | None = None,
) -> CalculationRecord:
    """Solve ``Rtop = Rbottom*(Vout/Vref - 1)`` in ohms."""

    inputs = (
        _positive_input(vout_v, name="vout_v", unit="V", evidence_ids=evidence_ids),
        _positive_input(vref_v, name="vref_v", unit="V", evidence_ids=evidence_ids),
        _positive_input(r_bottom_ohm, name="r_bottom_ohm", unit="ohm", evidence_ids=evidence_ids),
    )
    if inputs[0].value <= inputs[1].value:
        raise ValueError("vout must be greater than vref for a positive feedback divider top resistor")
    result = inputs[2].value * (inputs[0].value / inputs[1].value - 1.0)
    return _record(
        target=target,
        equation_id="feedback_divider",
        inputs=inputs,
        equation_str="Rtop = Rbottom*(Vout/Vref - 1)",
        result=result,
        unit="ohm",
    )


def feedback_divider_vout(
    *,
    target: str,
    r_top_ohm: float,
    r_bottom_ohm: float,
    vref_v: float,
    evidence_ids: Mapping[str, str | None] | None = None,
) -> CalculationRecord:
    """Solve ``Vout = Vref*(1 + Rtop/Rbottom)`` in volts."""

    inputs = (
        _positive_input(r_top_ohm, name="r_top_ohm", unit="ohm", evidence_ids=evidence_ids),
        _positive_input(r_bottom_ohm, name="r_bottom_ohm", unit="ohm", evidence_ids=evidence_ids),
        _positive_input(vref_v, name="vref_v", unit="V", evidence_ids=evidence_ids),
    )
    result = inputs[2].value * (1.0 + inputs[0].value / inputs[1].value)
    return _record(
        target=target,
        equation_id="feedback_divider",
        inputs=inputs,
        equation_str="Vout = Vref*(1 + Rtop/Rbottom)",
        result=result,
        unit="V",
    )


def rc_cutoff(
    *, target: str, resistance_ohm: float, capacitance_f: float, evidence_ids: Mapping[str, str | None] | None = None
) -> CalculationRecord:
    """Solve ``fc = 1/(2*pi*R*C)`` in hertz."""

    inputs = (
        _positive_input(resistance_ohm, name="resistance_ohm", unit="ohm", evidence_ids=evidence_ids),
        _positive_input(capacitance_f, name="capacitance_f", unit="F", evidence_ids=evidence_ids),
    )
    result = 1.0 / (2.0 * math.pi * inputs[0].value * inputs[1].value)
    return _record(
        target=target,
        equation_id="rc_cutoff",
        inputs=inputs,
        equation_str="fc = 1/(2*pi*R*C)",
        result=result,
        unit="Hz",
    )


def rc_capacitance_for_cutoff(
    *,
    target: str,
    resistance_ohm: float,
    cutoff_hz: float,
    evidence_ids: Mapping[str, str | None] | None = None,
) -> CalculationRecord:
    """Solve ``C = 1/(2*pi*R*fc)`` in farads."""
    inputs = (
        _positive_input(resistance_ohm, name="resistance_ohm", unit="ohm", evidence_ids=evidence_ids),
        _positive_input(cutoff_hz, name="cutoff_hz", unit="Hz", evidence_ids=evidence_ids),
    )
    result = 1.0 / (2.0 * math.pi * inputs[0].value * inputs[1].value)
    return _record(
        target=target,
        equation_id="rc_cutoff",
        inputs=inputs,
        equation_str="C = 1/(2*pi*R*fc)",
        result=result,
        unit="F",
    )


def rc_resistance_for_cutoff(
    *,
    target: str,
    capacitance_f: float,
    cutoff_hz: float,
    evidence_ids: Mapping[str, str | None] | None = None,
) -> CalculationRecord:
    """Solve ``R = 1/(2*pi*C*fc)`` in ohms."""
    inputs = (
        _positive_input(capacitance_f, name="capacitance_f", unit="F", evidence_ids=evidence_ids),
        _positive_input(cutoff_hz, name="cutoff_hz", unit="Hz", evidence_ids=evidence_ids),
    )
    result = 1.0 / (2.0 * math.pi * inputs[0].value * inputs[1].value)
    return _record(
        target=target,
        equation_id="rc_cutoff",
        inputs=inputs,
        equation_str="R = 1/(2*pi*C*fc)",
        result=result,
        unit="ohm",
    )


def lc_cutoff(
    *, target: str, inductance_h: float, capacitance_f: float, evidence_ids: Mapping[str, str | None] | None = None
) -> CalculationRecord:
    """Solve ``fc = 1/(2*pi*sqrt(L*C))`` in hertz."""

    inputs = (
        _positive_input(inductance_h, name="inductance_h", unit="H", evidence_ids=evidence_ids),
        _positive_input(capacitance_f, name="capacitance_f", unit="F", evidence_ids=evidence_ids),
    )
    result = 1.0 / (2.0 * math.pi * math.sqrt(inputs[0].value * inputs[1].value))
    return _record(
        target=target,
        equation_id="lc_cutoff",
        inputs=inputs,
        equation_str="fc = 1/(2*pi*sqrt(L*C))",
        result=result,
        unit="Hz",
    )


def crystal_external_load_cap(
    *,
    target: str,
    load_capacitance_f: float,
    stray_capacitance_f: float,
    evidence_ids: Mapping[str, str | None] | None = None,
) -> CalculationRecord:
    """Solve the symmetric crystal-cap equation ``Cext = 2*(CL - Cstray)``."""

    inputs = (
        _positive_input(load_capacitance_f, name="load_capacitance_f", unit="F", evidence_ids=evidence_ids),
        _nonnegative_input(stray_capacitance_f, name="stray_capacitance_f", unit="F", evidence_ids=evidence_ids),
    )
    if inputs[0].value <= inputs[1].value:
        raise ValueError("load_capacitance must exceed stray_capacitance")
    result = 2.0 * (inputs[0].value - inputs[1].value)
    return _record(
        target=target,
        equation_id="crystal_load_cap",
        inputs=inputs,
        equation_str="Cext = 2*(CL - Cstray)",
        result=result,
        unit="F",
    )


def crystal_effective_load(
    *,
    target: str,
    capacitance_1_f: float,
    capacitance_2_f: float,
    stray_capacitance_f: float,
    evidence_ids: Mapping[str, str | None] | None = None,
) -> CalculationRecord:
    """Solve ``CL = (C1*C2)/(C1+C2) + Cstray`` in farads."""

    inputs = (
        _positive_input(capacitance_1_f, name="capacitance_1_f", unit="F", evidence_ids=evidence_ids),
        _positive_input(capacitance_2_f, name="capacitance_2_f", unit="F", evidence_ids=evidence_ids),
        _nonnegative_input(stray_capacitance_f, name="stray_capacitance_f", unit="F", evidence_ids=evidence_ids),
    )
    result = (inputs[0].value * inputs[1].value) / (inputs[0].value + inputs[1].value) + inputs[2].value
    return _record(
        target=target,
        equation_id="crystal_load_cap",
        inputs=inputs,
        equation_str="CL = (C1*C2)/(C1+C2) + Cstray",
        result=result,
        unit="F",
    )
