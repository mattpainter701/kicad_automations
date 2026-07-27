"""Evidence contracts for typed power envelopes and calculations."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from circuit_weaver.dispatcher import validate_design
from circuit_weaver.evidence import (
    EvidenceLedger,
    collect_component_evidence,
    collect_power_domain_evidence,
    collect_validation_evidence,
)


def test_sparse_power_envelope_does_not_record_absent_values_as_facts():
    ledger = EvidenceLedger()
    component = SimpleNamespace(
        source_ref="U1",
        source_mpn="LOAD-IC",
        mpn="LOAD-IC",
        footprint="",
        pinout_source="explicit",
        datasheet_url="",
        pins=[],
        power_reqs=[
            SimpleNamespace(
                net="VDD_3P3",
                voltage=3.3,
                max_current_ma=None,
                v_min=None,
                v_nominal=3.3,
                v_max=None,
                i_steady_ma=None,
                i_peak_ma=None,
                direction="load",
                tolerance=None,
            )
        ],
    )

    collect_component_evidence(ledger, [component])
    power_records = [
        record for record in ledger.to_manifest()["records"] if record["subject_ref"].startswith("param:")
    ]

    assert len(power_records) == 1
    assert "nominal voltage=3.3 V" in power_records[0]["claim"]
    assert "direction=load" in power_records[0]["claim"]
    assert "None" not in power_records[0]["claim"]


def test_structured_power_finding_creates_calculation_evidence(monkeypatch):
    from circuit_weaver import benchmark_runner

    monkeypatch.setitem(benchmark_runner.RULE_ID_BY_VALIDATOR_CODE, "power-over-voltage", "CW-PWR-001")
    ledger = EvidenceLedger()
    message = SimpleNamespace(
        category="electrical",
        code="power-over-voltage",
        level="error",
        subject="U1",
        message="Observed maximum exceeds the permitted rail voltage.",
        evidence_ids=["EV-DATASHEET-000000000000"],
        calculation={
            "rule_id": "CW-PWR-001",
            "equation": "source.v_max <= load.v_max",
            "observed": {"value": 3.6, "unit": "V"},
            "expected": {"maximum": 3.3, "unit": "V"},
            "margin": {"value": -0.3, "unit": "V"},
            "version": "1",
        },
    )
    report = SimpleNamespace(categories={"electrical": [message]}, evidence_ids=[])

    collected = collect_validation_evidence(ledger, report)
    records = ledger.to_manifest()["records"]

    assert collected == message.evidence_ids
    assert len(records) == 1
    assert records[0]["kind"] == "calculation"
    assert records[0]["subject_ref"] == "calc:CW-PWR-001@U1"
    assert '"margin":{"unit":"V","value":-0.3}' in records[0]["claim"]
    assert "EV-DATASHEET-000000000000" not in message.evidence_ids


def test_declared_power_domain_provenance_becomes_a_resolvable_ledger_record():
    ledger = EvidenceLedger()
    evidence_by_net = collect_power_domain_evidence(
        ledger,
        [
            SimpleNamespace(
                net="VBAT",
                v_min=3.0,
                v_nominal=3.7,
                v_max=4.2,
                direction="source",
                i_steady_ma=None,
                i_peak_ma=700,
                sequence_order=1,
                sequence_dependency=None,
                tolerance=None,
                evidence_id="EV-DATASHEET-aaaaaaaaaaaa",
            )
        ],
    )

    evidence_id = evidence_by_net["VBAT"][0]
    record = ledger.get(evidence_id)

    assert record is not None
    assert record.subject_ref == "net:VBAT"
    assert record.kind == "user"
    assert record.source.doc_id == "EV-DATASHEET-aaaaaaaaaaaa"
    assert "None" not in record.claim


def test_power_calculation_references_resolve_to_component_and_rail_evidence():
    fixture = (
        Path(__file__).resolve().parents[1]
        / "benchmarks"
        / "electrical"
        / "negative"
        / "power"
        / "multi_rail_over_voltage"
        / "design.json"
    )
    report = validate_design(json.loads(fixture.read_text(encoding="utf-8")), check_determinism=False)
    payload = report.to_dict()
    records = payload["metadata"]["evidence_manifest"]["records"]
    records_by_id = {record["id"]: record for record in records}
    finding = next(
        item for item in payload["categories"]["electrical"] if item["code"] == "power-over-voltage"
    )

    assert set(payload["evidence_ids"]) <= set(records_by_id)
    assert set(finding["evidence_ids"]) <= set(records_by_id)
    provenance = finding["calculation"]["provenance_ids"]
    assert {records_by_id[evidence_id]["subject_ref"] for evidence_id in provenance} == {
        "net:VDD_3P3",
        "param:U1.power.VDD_3P3",
    }
    assert any(
        records_by_id[evidence_id]["kind"] == "calculation" for evidence_id in finding["evidence_ids"]
    )
