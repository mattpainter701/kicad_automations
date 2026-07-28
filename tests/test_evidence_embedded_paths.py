"""Adversarial embedded local-path safety contracts for evidence policy."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from circuit_weaver.evidence import (
    EvidenceLedger,
    EvidenceRecord,
    EvidenceSource,
    collect_component_evidence,
    validate_record,
)
from circuit_weaver.evidence_policy import EvidencePolicyError, validate_evidence_safety


def _record(**overrides):
    record = {
        "id": "EV-datasheet-0123456789ab",
        "subject_ref": "comp:U1",
        "claim": "identity is TPS62160",
        "kind": "datasheet",
        "confidence": "verified",
        "source": {"uri": "https://example.test/tps62160.pdf"},
        "freshness": "current",
        "conflicts": [],
        "supersedes": None,
    }
    record.update(overrides)
    return record


@pytest.mark.parametrize(
    "overrides",
    [
        {"subject_ref": r"footprint:C:\Users\matt\parts\part.kicad_mod"},
        {"claim": r"extracted from C:\Users\matt\parts\part.kicad_mod"},
        {"source": {"uri": r"notes before \\server\share\part.pdf"}},
        {"source": {"doc_id": "reviewed at /home/matt/project/part.pdf"}},
        {"source": {"doc_id": "reviewed at /build/agent/worktree/part.pdf"}},
        {"source": {"extraction_method": "copied from ~/parts/part.kicad_mod"}},
        {"source": {"nested": [{"location": "prefix /tmp/cw/evidence.json"}]}},
        {"source": {"nested": ("path is file:///C:/Users/matt/part.pdf",)}},
        {"source": {"uri": r"https://example.test/?local=C:\Users\matt\secret.pdf"}},
        {"claim": "build-artifact-/home/ci/secret"},
        {"claim": "cache.v2./home/ci/id_rsa"},
        {"claim": "(https://x.com/ds.pdf)/home/ci/secret"},
    ],
)
def test_embedded_machine_local_paths_are_rejected_recursively(overrides):
    with pytest.raises(EvidencePolicyError, match="machine-local absolute paths"):
        validate_evidence_safety(_record(**overrides))


@pytest.mark.parametrize(
    "uri",
    [
        "https://alice:password@example.test/datasheet.pdf",
        "https://alice%3Apassword@example.test/datasheet.pdf",
    ],
)
def test_http_userinfo_is_rejected_as_a_credential_leak(uri):
    with pytest.raises(EvidencePolicyError, match="credentials or secrets"):
        validate_evidence_safety(_record(source={"uri": uri}))


@pytest.mark.parametrize(
    "claim",
    [
        "datasheet at https://example.test/products/usb-c/connector.pdf",
        "datasheet at (https://example.test/products/usb-c/connector.pdf)",
        'datasheet at "https://example.test/products/usb-c/connector.pdf"',
        "datasheet at https://example.test/?contact=alice@example.test",
        "route / power / enable are checked",
        "pin A/B is differential",
        "reference C / R is a ratio notation, not a path",
    ],
)
def test_remote_urls_and_ordinary_slash_claims_remain_accepted(claim):
    validate_evidence_safety(_record(claim=claim))


@pytest.mark.parametrize(
    "claim",
    [r"loaded from C:\Users\matt\private.pdf", "loaded from /home/matt/private.pdf", "loaded from file:///tmp/x"],
)
def test_direct_record_validation_uses_the_same_embedded_path_policy(claim):
    record = EvidenceRecord(
        id="EV-CATALOG-0123456789ab",
        subject_ref="comp:U1",
        claim=claim,
        kind="catalog",
        source=EvidenceSource(),
        confidence="single_source",
        freshness="unknown",
    )
    with pytest.raises(EvidencePolicyError, match="machine-local absolute paths"):
        validate_record(record)


def test_component_footprint_absolute_path_is_rejected_before_manifest_emission():
    component = SimpleNamespace(
        source_ref="U1",
        source_mpn="ACME-1",
        mpn="ACME-1",
        footprint=r"C:\Users\matt\KiCad\ACME.pretty\ACME.kicad_mod",
        pinout_source="explicit",
        datasheet_url="",
        pins=[],
        power_reqs=[],
    )
    ledger = EvidenceLedger()

    with pytest.raises(EvidencePolicyError, match="machine-local absolute paths"):
        collect_component_evidence(ledger, [component])
    assert "C:\\\\Users" not in ledger.to_json()
