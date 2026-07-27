"""Traceability and fail-closed contracts for RS-485 support passives."""

from circuit_weaver.dispatcher import ValidationReport
from circuit_weaver.evidence import EvidenceLedger, build_validation_evidence
from circuit_weaver.subcircuits.rs485_transceiver import RS485TransceiverTemplate


def _component(**params: object):
    result = RS485TransceiverTemplate().generate({"ref": "U7", **params})
    return result.components[0]


def test_rs485_default_support_values_are_explicit_bounded_fallbacks() -> None:
    component = _component(termination=True)

    support = [*component.bypass_caps, *component.straps]
    assert {item.pin for item in support} == {"C_VCC", "RT", "RBIAS_A", "RBIAS_B"}
    assert all(item.selection_policy == "bounded_fallback" for item in support)
    assert all(item.confidence == "heuristic" for item in support)
    assert all(item.calculation_id and item.evidence_ids for item in support)
    assert next(item for item in component.straps if item.role == "termination").value == "120R"
    assert len(component.passive_synthesis_calculations) == 4

    ledger, evidence_by_ref = build_validation_evidence(
        [component],
        report=ValidationReport(profile="standard", valid=True),
    )
    known = {record["id"] for record in ledger.to_manifest()["records"]}
    assert {evidence_id for item in support for evidence_id in item.evidence_ids} <= known
    assert set(evidence_by_ref["U7"]) <= known


def test_supplied_bus_impedance_uses_equation_policy() -> None:
    component = _component(termination=True, bus_impedance_ohm=100.0, failsafe_bias=False)

    termination = next(item for item in component.straps if item.role == "termination")
    assert termination.value == "100R"
    assert termination.selection_policy == "equation"
    assert termination.confidence == "single_source"


def test_out_of_range_bus_impedance_is_withheld_before_emission() -> None:
    component = _component(termination=True, bus_impedance_ohm=10.0, failsafe_bias=False)

    assert not [item for item in component.straps if item.role == "termination"]
    assert len(component.passive_synthesis_findings) == 1
    finding = component.passive_synthesis_findings[0]
    assert finding.rule_id == "CW-PSV-002"
    assert finding.expected_min == 80.0
    assert finding.expected_max == 150.0
    assert EvidenceLedger(component.passive_synthesis_evidence).to_manifest()["records"]
