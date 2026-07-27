"""T244.R2 contracts for explicit evidence supersession links."""

from __future__ import annotations

import pytest

from circuit_weaver.evidence import (
    MANIFEST_SCHEMA_VERSION,
    EvidenceLedger,
    EvidenceRecord,
    EvidenceSource,
    evidence_id,
)


def _source(doc_id: str) -> EvidenceSource:
    return EvidenceSource(doc_id=doc_id, extraction_method="test")


def _record(claim: str, *, supersedes: str | None = None) -> EvidenceRecord:
    source = _source(claim)
    return EvidenceRecord(
        id=evidence_id("comp:U1", claim, "catalog", source),
        subject_ref="comp:U1",
        claim=claim,
        kind="catalog",
        source=source,
        confidence="single_source",
        freshness="current",
        supersedes=supersedes,
    )


def test_builder_roundtrip_and_copy_preserve_supersedes():
    ledger = EvidenceLedger()
    original = ledger.record(subject_ref="comp:U1", claim="MPN is OLD", kind="catalog", source=_source("old"))
    replacement = ledger.record(
        subject_ref="comp:U1",
        claim="MPN is NEW",
        kind="catalog",
        source=_source("new"),
        supersedes=original,
    )

    assert ledger.get(replacement).supersedes == original  # type: ignore[union-attr]
    manifest = ledger.to_manifest()
    assert next(item for item in manifest["records"] if item["id"] == replacement)["supersedes"] == original  # type: ignore[index]
    restored = EvidenceLedger.from_manifest(manifest)
    assert restored.get(replacement).supersedes == original  # type: ignore[union-attr]


def test_programmatic_add_rejects_unresolved_or_self_supersedes():
    unresolved = _record("unresolved", supersedes="EV-CATALOG-123456789abc")
    with pytest.raises(ValueError, match="links must reference existing"):
        EvidenceLedger().add(unresolved)

    self_referential = _record("self")
    self_referential = EvidenceRecord(**{**self_referential.__dict__, "supersedes": self_referential.id})
    with pytest.raises(ValueError, match="cannot supersede itself"):
        EvidenceLedger().add(self_referential)


def test_manifest_accepts_forward_supersedes_reference():
    original = _record("old")
    replacement = _record("new", supersedes=original.id)
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "records": [
            {**replacement.__dict__, "source": replacement.source.__dict__, "conflicts": []},
            {**original.__dict__, "source": original.source.__dict__, "conflicts": []},
        ],
    }

    restored = EvidenceLedger.from_manifest(manifest)
    assert restored.get(replacement.id).supersedes == original.id  # type: ignore[union-attr]


def test_manifest_rejects_unresolved_and_cyclic_supersedes():
    unresolved = _record("unresolved", supersedes="EV-CATALOG-123456789abc")
    unresolved_manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "records": [{**unresolved.__dict__, "source": unresolved.source.__dict__, "conflicts": []}],
    }
    with pytest.raises(ValueError, match="unresolved supersedes"):
        EvidenceLedger.from_manifest(unresolved_manifest)

    first = _record("first")
    second = _record("second", supersedes=first.id)
    first = EvidenceRecord(**{**first.__dict__, "supersedes": second.id})
    cyclic_manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "records": [
            {**first.__dict__, "source": first.source.__dict__, "conflicts": []},
            {**second.__dict__, "source": second.source.__dict__, "conflicts": []},
        ],
    }
    with pytest.raises(ValueError, match="cyclic supersedes"):
        EvidenceLedger.from_manifest(cyclic_manifest)


def test_legacy_manifest_without_supersedes_remains_valid():
    record = _record("legacy")
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "records": [{**record.__dict__, "source": record.source.__dict__, "conflicts": []}],
    }
    manifest["records"][0].pop("supersedes")

    restored = EvidenceLedger.from_manifest(manifest)
    assert restored.get(record.id).supersedes is None  # type: ignore[union-attr]


def test_manifest_roundtrip_defers_corroboration_until_agreeing_record_loads():
    ledger = EvidenceLedger()
    user_id = ledger.record(
        subject_ref="comp:U1",
        claim="MPN is ACME-123",
        kind="user",
        source=_source("user-note"),
    )
    catalog_id = ledger.record(
        subject_ref="comp:U1",
        claim="MPN is ACME-123",
        kind="catalog",
        source=_source("catalog-row"),
        confidence="corroborated",
    )

    manifest = ledger.to_manifest()
    assert [item["id"] for item in manifest["records"]] == [catalog_id, user_id]  # type: ignore[index]
    restored = EvidenceLedger.from_manifest(manifest)
    assert restored.get(catalog_id).confidence == "corroborated"  # type: ignore[union-attr]
