"""Safety and fabrication-critical trust-policy tests."""

from __future__ import annotations

import pytest

from circuit_weaver.delivery_manifest import DeliveryManifest
from circuit_weaver.evidence_policy import (
    EvidencePolicyError,
    is_fabrication_critical_subject,
    require_backing,
    require_fabrication_evidence,
    validate_evidence_safety,
)
from circuit_weaver.manufacturing_readiness import ManufacturingReadiness


def _record(**overrides):
    record = {
        "id": "EV-datasheet-0123456789ab",
        "subject_ref": "comp:U1",
        "claim": "identity is TPS62160",
        "kind": "datasheet",
        "confidence": "verified",
        "source": {
            "uri": "https://example.com/tps62160.pdf",
            "doc_id": "TPS62160",
            "content_hash": "sha256:abc",
            "retrieved_at": "2026-07-25T00:00:00Z",
            "extraction_method": "manual",
        },
        "freshness": "current",
        "conflicts": [],
        "supersedes": None,
    }
    record.update(overrides)
    return record


@pytest.mark.parametrize(
    "value",
    ["API_KEY=top-secret", "Bearer secrettoken", "C:\\Users\\matt\\private.pdf", "/home/matt/private.pdf"],
)
def test_safety_rejects_credentials_and_machine_local_paths(value):
    record = _record(claim=value)

    with pytest.raises(EvidencePolicyError):
        validate_evidence_safety(record)


def test_safety_accepts_remote_source_and_valid_existing_links():
    record = _record(conflicts=["EV-catalog-0123456789ab"], supersedes="EV-user-0123456789ab")

    validate_evidence_safety(record, known_ids={"EV-catalog-0123456789ab", "EV-user-0123456789ab"})


def test_safety_rejects_malformed_or_unresolved_links():
    record = _record(conflicts=["not-an-id"])
    with pytest.raises(EvidencePolicyError, match="malformed"):
        validate_evidence_safety(record)

    record = _record(conflicts=["EV-catalog-0123456789ab"])
    with pytest.raises(EvidencePolicyError, match="existing"):
        validate_evidence_safety(record, known_ids={"EV-user-0123456789ab"})


@pytest.mark.parametrize(
    "subject_ref",
    [
        "comp:U1",
        "pin:U1.1",
        "footprint:QFN-16",
        "param:U1.power.max_current",
        "calc:CW-PWR-006@U1",
        "tool:pcbnew-drc",
    ],
)
def test_fabrication_critical_subject_classes(subject_ref):
    assert is_fabrication_critical_subject(subject_ref)


@pytest.mark.parametrize(
    "kind, confidence, acknowledgements",
    [("stub", "verified", ()), ("heuristic", "heuristic", ())],
)
def test_critical_backing_rejects_stub_and_unacknowledged_heuristic(kind, confidence, acknowledgements):
    record = _record(kind=kind, confidence=confidence)

    with pytest.raises(EvidencePolicyError, match="insufficient trustworthy"):
        require_backing("comp:U1", [record], min_confidence="heuristic", acknowledged_heuristic_ids=acknowledgements)


def test_critical_backing_allows_explicitly_acknowledged_heuristic_at_its_confidence_level():
    record = _record(kind="heuristic", confidence="heuristic")

    assert (
        require_backing(
            "comp:U1",
            [record],
            min_confidence="heuristic",
            acknowledged_heuristic_ids={record["id"]},
        )
        == record
    )


def test_critical_backing_rejects_unresolved_conflicts_even_with_verified_record():
    conflicted = _record(conflicts=["EV-user-0123456789ab"])
    alternate = _record(id="EV-datasheet-fedcba987654")

    with pytest.raises(EvidencePolicyError, match="unresolved evidence conflicts"):
        require_backing("comp:U1", [conflicted, alternate])


def test_critical_backing_uses_strongest_acceptable_record():
    weak = _record(id="EV-user-0123456789ab", kind="user", confidence="single_source")
    strong = _record(id="EV-datasheet-fedcba987654", confidence="verified")

    assert require_backing("comp:U1", [weak, strong]) == strong


def test_superseded_evidence_cannot_remain_authoritative():
    old = _record(id="EV-datasheet-0123456789ab", confidence="verified")
    replacement = _record(
        id="EV-user-0123456789ab",
        kind="user",
        confidence="single_source",
        supersedes=old["id"],
    )

    assert require_backing("comp:U1", [old, replacement]) == replacement


def test_fabrication_gate_rejects_missing_or_stub_only_critical_evidence():
    with pytest.raises(EvidencePolicyError, match="requires critical-subject evidence"):
        require_fabrication_evidence([])
    with pytest.raises(EvidencePolicyError, match="insufficient trustworthy"):
        require_fabrication_evidence([_record(kind="stub", confidence="stub")])


def test_delivery_manifest_cannot_claim_fabrication_ready_without_trusted_evidence():
    ready = ManufacturingReadiness.from_dict(
        {
            "state": "fabrication_ready",
            "blockers": [],
            "evidence_ids": [],
            "next_actions": [],
            "blocked_reason": None,
        }
    )
    with pytest.raises(EvidencePolicyError):
        DeliveryManifest(
            status="ok",
            assembly_ready=True,
            fabrication_ready=True,
            assembly_item_count=1,
            evidence_records=(_record(kind="stub", confidence="stub"),),
            manufacturing_readiness=ready,
        )

    records = (
        _record(),
        _record(
            id="EV-tool_result-0123456789ac",
            subject_ref="tool:pcb_handoff",
            kind="tool_result",
        ),
        _record(
            id="EV-tool_result-0123456789ad",
            subject_ref="tool:drc",
            kind="tool_result",
        ),
    )
    delivery = DeliveryManifest(
        status="ok",
        assembly_ready=True,
        fabrication_ready=True,
        assembly_item_count=1,
        evidence_records=records,
        manufacturing_readiness=ready,
    )
    assert delivery.to_dict()["fabrication_ready"] is True
