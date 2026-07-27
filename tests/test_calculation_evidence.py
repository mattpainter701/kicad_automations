"""T246.2 contracts for deterministic calculation-to-ledger evidence."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from circuit_weaver.calc import emit_calculation_evidence, rc_cutoff
from circuit_weaver.evidence import EvidenceLedger, EvidenceSource


def _input_evidence(ledger: EvidenceLedger) -> str:
    return ledger.record(
        subject_ref="comp:R1",
        claim="resistance is 1000 ohm",
        kind="datasheet",
        source=EvidenceSource(doc_id="R1-datasheet", extraction_method="table"),
    )


def _calculation(evidence_id: str | None = None):
    evidence_ids = None if evidence_id is None else {"resistance_ohm": evidence_id}
    return rc_cutoff(
        target="param:U1.filter.cutoff",
        resistance_ohm=1_000,
        capacitance_f=1e-6,
        evidence_ids=evidence_ids,
    )


def test_calculation_emits_canonical_round_trippable_evidence_without_mutating_input():
    ledger = EvidenceLedger()
    calculation = _calculation(_input_evidence(ledger))

    emitted = emit_calculation_evidence(calculation, ledger)

    assert calculation.emits_evidence is None
    assert emitted is not calculation
    assert emitted.emits_evidence is not None
    evidence = ledger.get(emitted.emits_evidence)
    assert evidence is not None
    assert evidence.subject_ref == calculation.target
    assert evidence.kind == "calculation"
    payload = json.loads(evidence.claim.removeprefix("calculation="))
    assert payload["calculation_id"] == calculation.id
    assert payload["equation_id"] == calculation.equation_id
    assert payload["equation_version"] == calculation.equation_version
    assert payload["raw_result"] == calculation.raw_result.to_dict()
    assert payload["input_evidence_ids"] == [calculation.inputs[0].evidence_id]
    assert EvidenceLedger.from_manifest(ledger.to_manifest()).to_json() == ledger.to_json()


def test_calculation_emission_is_idempotent_and_has_stable_evidence_id():
    ledger = EvidenceLedger()
    calculation = _calculation(_input_evidence(ledger))

    first = emit_calculation_evidence(calculation, ledger)
    manifest = ledger.to_json()
    second = emit_calculation_evidence(first, ledger)

    assert first.emits_evidence == second.emits_evidence
    assert ledger.to_json() == manifest
    assert len(ledger.for_subject(calculation.target)) == 1


def test_calculation_evidence_rejects_unresolved_input_provenance_and_tampered_identity():
    with pytest.raises(ValueError, match="does not resolve"):
        emit_calculation_evidence(_calculation("EV-DATASHEET-aaaaaaaaaaaa"), EvidenceLedger())

    with pytest.raises(ValueError, match="does not match its deterministic inputs"):
        emit_calculation_evidence(replace(_calculation(), id="CALC-RC_CUTOFF-000000000000"), EvidenceLedger())


def test_calculation_evidence_rejects_a_predeclared_different_evidence_id():
    ledger = EvidenceLedger()
    calculation = replace(_calculation(), emits_evidence="EV-CALCULATION-000000000000")

    with pytest.raises(ValueError, match="emits_evidence"):
        emit_calculation_evidence(calculation, ledger)
