"""T246.5 fail-closed passive-synthesis contracts."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from circuit_weaver.calc import (
    apply_e_series_selection,
    emit_calculation_evidence,
    is_selection_eligible,
    passive_synthesis_finding,
    rc_capacitance_for_cutoff,
    require_selection,
    validate_passive_synthesis_finding,
    withhold_calculation,
)
from circuit_weaver.evidence import EvidenceLedger


def _calculation():
    return rc_capacitance_for_cutoff(
        target="param:U1.filter.capacitance",
        resistance_ohm=1_000,
        cutoff_hz=1_000,
    )


def test_missing_basis_withholds_immutably_with_deterministic_finding():
    calculation = _calculation()

    withheld, finding = withhold_calculation(calculation, reason="missing_basis")

    assert calculation.chosen_value is None and calculation.withheld_finding_id is None
    assert withheld.chosen_value is None
    assert withheld.margin is not None and withheld.margin.ok is False
    assert withheld.withheld_finding_id == finding.id
    assert finding.rule_id == "CW-PSV-001"
    assert finding.calculation_id == calculation.id
    assert finding.target == calculation.target
    assert finding.observed == calculation.raw_result
    assert withhold_calculation(calculation, reason="missing_basis") == (withheld, finding)


def test_out_of_range_is_withheld_before_emission_and_blocks_selection():
    selected = apply_e_series_selection(_calculation(), series="E24")
    observed = selected.raw_result.value
    withheld, finding = withhold_calculation(
        selected,
        reason="out_of_range",
        expected_min=observed * 2,
        expected_max=observed * 3,
    )

    assert finding.rule_id == "CW-PSV-002"
    assert withheld.chosen_value is None
    assert not is_selection_eligible(withheld)
    with pytest.raises(ValueError, match="withheld"):
        require_selection(withheld)


def test_bounded_fallback_requires_heuristic_confidence_and_bounds_are_fail_closed():
    with pytest.raises(ValueError, match="requires heuristic"):
        withhold_calculation(_calculation(), reason="missing_basis", policy="bounded_fallback")
    with pytest.raises(ValueError, match="supplied together"):
        withhold_calculation(_calculation(), reason="out_of_range", expected_min=0)
    with pytest.raises(ValueError, match="finite"):
        withhold_calculation(_calculation(), reason="out_of_range", expected_min=float("nan"), expected_max=1)

    withheld, _ = withhold_calculation(
        _calculation(), reason="missing_basis", policy="bounded_fallback", confidence="heuristic"
    )
    assert withheld.policy == "bounded_fallback"
    assert withheld.confidence == "heuristic"


def test_finding_identity_is_deterministic_and_tampering_is_rejected():
    calculation = _calculation()
    finding = passive_synthesis_finding(
        calculation,
        reason="incompatible_network",
        evidence_ids=("EV-DATASHEET-bbbbbbbbbbbb", "EV-DATASHEET-aaaaaaaaaaaa"),
    )

    validate_passive_synthesis_finding(finding, calculation)
    assert finding.evidence_ids == ("EV-DATASHEET-aaaaaaaaaaaa", "EV-DATASHEET-bbbbbbbbbbbb")
    with pytest.raises(ValueError, match="deterministic calculation association"):
        validate_passive_synthesis_finding(replace(finding, id="CW-PSV-003-000000000000"), calculation)


def test_withheld_calculation_evidence_has_null_selection_and_finding_id_and_rejects_tampering():
    withheld, finding = withhold_calculation(_calculation(), reason="missing_basis")
    ledger = EvidenceLedger()

    emitted = emit_calculation_evidence(withheld, ledger)

    assert emitted.emits_evidence is not None
    evidence = ledger.get(emitted.emits_evidence)
    assert evidence is not None
    payload = json.loads(evidence.claim.removeprefix("calculation="))
    assert payload["chosen_value"] is None
    assert payload["withheld_finding_id"] == finding.id
    selected_value = require_selection(apply_e_series_selection(_calculation()))
    with pytest.raises(ValueError, match="must not contain a chosen value"):
        emit_calculation_evidence(replace(withheld, chosen_value=selected_value), ledger)
    with pytest.raises(ValueError, match="malformed"):
        emit_calculation_evidence(replace(withheld, withheld_finding_id="CW-PSV-999-bad"), ledger)
