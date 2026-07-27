"""T246.3-ready pure selection-record factory contracts."""

from __future__ import annotations

import json

import pytest

from circuit_weaver.calc import (
    bounded_fallback_scalar,
    datasheet_selected_scalar,
    emit_calculation_evidence,
    is_selection_eligible,
    ldo_minimum_capacitor,
    require_selection,
    termination_resistor_match,
)
from circuit_weaver.evidence import EvidenceLedger, EvidenceSource

DATASHEET_ID = "EV-DATASHEET-aaaaaaaaaaaa"


def _ledger_with_datasheet() -> tuple[EvidenceLedger, str]:
    ledger = EvidenceLedger()
    evidence_id = ledger.record(
        subject_ref="comp:U1",
        claim="minimum capacitor is 1 uF",
        kind="datasheet",
        source=EvidenceSource(doc_id="U1-datasheet", extraction_method="table"),
    )
    return ledger, evidence_id


def test_datasheet_selection_is_deterministic_traceable_and_not_equation_derived():
    calculation = datasheet_selected_scalar(target="param:U1.ldo.cout", value=1e-6, unit="F", evidence_id=DATASHEET_ID)

    assert calculation == datasheet_selected_scalar(
        target="param:U1.ldo.cout", value=1e-6, unit="F", evidence_id=DATASHEET_ID
    )
    assert calculation.policy == "datasheet"
    assert calculation.confidence == "single_source"
    assert calculation.equation_id == "datasheet_selection"
    assert calculation.chosen_value is not None
    assert calculation.inputs[0].evidence_id == DATASHEET_ID
    with pytest.raises(ValueError, match="EV-DATASHEET"):
        datasheet_selected_scalar(
            target="param:U1.ldo.cout", value=1e-6, unit="F", evidence_id="EV-CATALOG-aaaaaaaaaaaa"
        )


def test_datasheet_selection_requires_real_ledger_evidence_when_emitted():
    calculation = datasheet_selected_scalar(target="param:U1.ldo.cout", value=1e-6, unit="F", evidence_id=DATASHEET_ID)
    with pytest.raises(ValueError, match="does not resolve"):
        emit_calculation_evidence(calculation, EvidenceLedger())

    ledger, resolved_evidence_id = _ledger_with_datasheet()
    calculation = datasheet_selected_scalar(
        target="param:U1.ldo.cout", value=1e-6, unit="F", evidence_id=resolved_evidence_id
    )
    emitted = emit_calculation_evidence(calculation, ledger)
    evidence = ledger.get(emitted.emits_evidence)
    assert evidence is not None
    assert json.loads(evidence.claim.removeprefix("calculation="))["policy"] == "datasheet"


def test_bounded_fallback_is_heuristic_bounded_and_never_silent():
    decision = bounded_fallback_scalar(
        target="param:U1.reset.cap",
        value=105e-9,
        minimum=100e-9,
        maximum=220e-9,
        unit="F",
        series="E24",
        direction="up",
    )

    assert decision.finding is None
    assert decision.calculation.policy == "bounded_fallback"
    assert decision.calculation.confidence == "heuristic"
    assert is_selection_eligible(decision.calculation)
    assert require_selection(decision.calculation).value == pytest.approx(110e-9)
    assert {item.name for item in decision.calculation.inputs} == {
        "fallback_value",
        "minimum",
        "maximum",
        "policy_version",
    }


def test_out_of_range_fallback_is_withheld_before_any_eligible_selection():
    decision = bounded_fallback_scalar(
        target="param:U1.reset.cap",
        value=105e-9,
        minimum=100e-9,
        maximum=105e-9,
        unit="F",
        series="E24",
        direction="up",
    )

    assert decision.finding is not None
    assert decision.finding.rule_id == "CW-PSV-002"
    assert decision.calculation.chosen_value is None
    assert not is_selection_eligible(decision.calculation)
    with pytest.raises(ValueError, match="withheld"):
        require_selection(decision.calculation)


def test_termination_and_ldo_factories_declare_selection_and_headroom():
    termination = termination_resistor_match(target="param:J1.usb.termination", impedance_ohm=92.0, series="E24")
    ldo = ldo_minimum_capacitor(
        target="param:U1.ldo.cout", minimum_capacitance_f=1.04e-6, evidence_id=DATASHEET_ID, series="E24"
    )

    assert termination.equation_str == "Rterm = Z0"
    assert require_selection(termination).value == pytest.approx(91.0)
    assert ldo.finding is None
    assert ldo.calculation.policy == "datasheet"
    assert require_selection(ldo.calculation).value == pytest.approx(1.1e-6)
    assert ldo.calculation.margin is not None
    assert ldo.calculation.margin.kind == "minimum_cap_headroom"
