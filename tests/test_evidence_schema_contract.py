"""Focused contracts for the frozen evidence manifest substrate."""

from __future__ import annotations

import json

import pytest

from circuit_weaver.evidence import MANIFEST_SCHEMA_VERSION, EvidenceLedger, EvidenceSource


def _source() -> EvidenceSource:
    return EvidenceSource(
        uri="https://example.test/datasheet.pdf",
        doc_id="ACME-123-datasheet-revA",
        content_hash="a" * 64,
        retrieved_at="2026-07-25T12:00:00Z",
        extraction_method="table-2",
    )


def test_manifest_is_deterministic_idempotent_and_copy_safe(tmp_path):
    ledger = EvidenceLedger()
    first = ledger.record(subject_ref="comp:U1", claim="MPN is ACME-123", kind="datasheet", source=_source())
    second = ledger.record(subject_ref="comp:U1", claim="MPN is ACME-123", kind="datasheet", source=_source())
    assert first == second
    assert ledger.get(first) is not ledger.get(first)
    manifest = ledger.to_manifest()
    manifest["records"].clear()  # type: ignore[union-attr]
    assert len(ledger.to_manifest()["records"]) == 1  # type: ignore[arg-type]
    written = ledger.write(tmp_path)
    assert json.loads(written.read_text(encoding="utf-8"))["schema_version"] == MANIFEST_SCHEMA_VERSION


def test_id_ignores_retrieval_time_and_producer_order():
    source_a = _source()
    source_b = EvidenceSource(**{**source_a.__dict__, "retrieved_at": "2026-08-01T00:00:00Z"})
    first = EvidenceLedger()
    second = EvidenceLedger()
    first_id = first.record(subject_ref="pin:U1.1", claim="Pin is VDD", kind="symbol_lib", source=source_a)
    second.record(
        subject_ref="tool:kicad-cli",
        claim="version is 9.0",
        kind="tool_result",
        source=EvidenceSource(extraction_method="--version"),
    )
    second_id = second.record(subject_ref="pin:U1.1", claim="Pin is VDD", kind="symbol_lib", source=source_b)
    assert first_id == second_id


@pytest.mark.parametrize(
    ("subject_ref", "kind"),
    [
        ("comp:U1", "catalog"),
        ("pin:U1.1", "symbol_lib"),
        ("footprint:QFN-32", "footprint_lib"),
        ("param:U1.power.v_max", "datasheet"),
        ("calc:CW-PWR-006@U1", "calculation"),
        ("calc:feedback_divider@U1", "calculation"),
        ("tool:kicad-cli", "tool_result"),
    ],
)
def test_builder_representative_subjects(subject_ref, kind):
    evidence_id = EvidenceLedger().record(subject_ref=subject_ref, claim="observed value", kind=kind, source=_source())
    assert evidence_id.startswith(f"EV-{kind.upper()}-")


@pytest.mark.parametrize(
    "unsafe", ["C:\\private\\secret.pdf", "/home/user/secret.pdf", "https://x.test/?api_key=secret"]
)
def test_credentials_and_absolute_paths_are_rejected(unsafe):
    with pytest.raises(ValueError):
        EvidenceLedger().record(
            subject_ref="comp:U1",
            claim="identity",
            kind="datasheet",
            source=EvidenceSource(uri=unsafe),
        )


def test_fail_closed_heuristics_and_conflicts():
    ledger = EvidenceLedger()
    with pytest.raises(ValueError, match="cannot be upgraded"):
        ledger.record(
            subject_ref="footprint:QFN-32",
            claim="footprint selected",
            kind="heuristic",
            confidence="verified",
        )
    with pytest.raises(ValueError, match="unresolved conflicts"):
        ledger.record(
            subject_ref="comp:U1",
            claim="MPN is ACME-123",
            kind="catalog",
            conflicts=["EV-CATALOG-123456789abc"],
        )


def test_corroborated_confidence_requires_another_agreeing_source():
    ledger = EvidenceLedger()
    with pytest.raises(ValueError, match="second agreeing"):
        ledger.record(
            subject_ref="comp:U1",
            claim="MPN is ACME-123",
            kind="catalog",
            source=EvidenceSource(doc_id="catalog-A", extraction_method="row-1"),
            confidence="corroborated",
        )
    ledger.record(
        subject_ref="comp:U1",
        claim="MPN is ACME-123",
        kind="catalog",
        source=EvidenceSource(doc_id="catalog-A", extraction_method="row-1"),
    )
    assert ledger.record(
        subject_ref="comp:U1",
        claim="MPN is ACME-123",
        kind="distributor",
        source=EvidenceSource(doc_id="distributor-B", extraction_method="page"),
        confidence="corroborated",
    ).startswith("EV-DISTRIBUTOR-")
