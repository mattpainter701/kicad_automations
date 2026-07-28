"""T247.1 exact immutable identity-record contracts."""

from __future__ import annotations

import hashlib
import json

import pytest

from circuit_weaver.identity import (
    DistributorAlias,
    IdentityHandoffBlocked,
    IdentityHandoffBundle,
    IdentityReconciliation,
    PinPadMap,
    build_human_identity_approval,
    build_identity_record,
    build_identity_source_assertion,
    evaluate_identity_handoff,
    identity_from_dict,
    identity_handoff_bundle_from_dict,
    identity_handoff_bundle_to_dict,
    identity_handoff_from_dict,
    identity_handoff_to_dict,
    identity_reconciliation_from_dict,
    identity_reconciliation_to_dict,
    identity_source_assertion_from_dict,
    identity_source_assertion_to_dict,
    identity_to_dict,
    reconcile_identity_assertions,
    require_identity_handoff,
)


def _resolved(**overrides):
    fields = {
        "status": "resolved",
        "manufacturer": "Acme",
        "mpn": "ABC123-QFN32-TR",
        "package_suffix": "QFN32-TR",
        "symbol_ref": "ACME:ABC123",
        "footprint_ref": "Package_QFN:QFN-32-1EP",
        "symbol_pins": ("1", "2", "EP"),
        "footprint_pads": ("1", "2", "EP"),
        "pin_pad_map": (PinPadMap("1", "1"), PinPadMap("2", "2"), PinPadMap("EP", "EP")),
        "distributor_aliases": (DistributorAlias("DigiKey", "ABC123-QFN32-TR-ND"),),
        "evidence_ids": ("EV-DATASHEET-0123456789ab",),
    }
    fields.update(overrides)
    return build_identity_record(**fields)


def test_identity_is_deterministic_and_preserves_package_suffix_exactly():
    first = _resolved()
    second = _resolved()
    assert first.id == second.id
    assert first.mpn == "ABC123-QFN32-TR"
    assert first.package_suffix == "QFN32-TR"


def test_builder_normalizes_input_order_and_json_roundtrips():
    ordered = _resolved()
    reordered = _resolved(
        symbol_pins=("EP", "2", "1"),
        footprint_pads=("EP", "2", "1"),
        pin_pad_map=(PinPadMap("EP", "EP"), PinPadMap("2", "2"), PinPadMap("1", "1")),
    )
    assert ordered.id == reordered.id
    assert identity_from_dict(identity_to_dict(reordered)) == ordered


def test_real_world_manufacturer_package_and_distributor_names_remain_exact():
    record = _resolved(
        manufacturer="Texas Instruments",
        package_suffix="RGE (VQFN-24)",
        distributor_aliases=(DistributorAlias("Mouser Electronics", "595-ABC123-QFN32-TR"),),
    )

    assert record.manufacturer == "Texas Instruments"
    assert record.package_suffix == "RGE (VQFN-24)"
    assert record.distributor_aliases[0].distributor == "Mouser Electronics"


def test_ambiguous_pin_or_pad_mapping_is_rejected():
    with pytest.raises(ValueError, match="ambiguous duplicate"):
        _resolved(pin_pad_map=(PinPadMap("1", "1"), PinPadMap("1", "2")))
    with pytest.raises(ValueError, match="ambiguous duplicate"):
        _resolved(pin_pad_map=(PinPadMap("1", "1"), PinPadMap("2", "1")))


def test_unresolved_identity_is_explicit_and_never_fills_missing_values():
    record = build_identity_record(
        status="unresolved",
        mpn="LOOKALIKE-32",
        symbol_pins=("1",),
        footprint_pads=(),
    )
    assert record.manufacturer is None
    assert record.package_suffix is None
    assert record.pin_pad_map == ()
    assert identity_from_dict(identity_to_dict(record)) == record


@pytest.mark.parametrize("status", ["agree", "conflict", "human-approved", "guessed"])
def test_t247_1_rejects_t247_2_or_unsupported_statuses(status):
    with pytest.raises(ValueError, match="unsupported identity status"):
        _resolved(status=status)


def _assertion(identity, family, doc):
    return build_identity_source_assertion(
        source_family=family,
        source_uri=f"https://example.test/{doc}",
        source_doc_id=doc,
        identity=identity,
        evidence_ids=["EV-DATASHEET-0123456789ab"],
    )


def test_two_independent_exact_sources_agree():
    result = reconcile_identity_assertions(
        [_assertion(_resolved(), "manufacturer", "ds"), _assertion(_resolved(), "distributor", "listing")]
    )
    assert result.state == result.source_state == "agree"
    assert result.disagreements == ()


def test_one_source_is_explicitly_missing_independent_coverage():
    result = reconcile_identity_assertions([_assertion(_resolved(), "manufacturer", "ds")])
    assert result.state == "missing"
    assert "independent_source" in result.missing_coverage


def test_lookalike_suffix_and_swapped_pair_mapping_are_conflicts():
    suffix = _resolved(mpn="ABC123-QFN32-R", package_suffix="QFN32-R")
    suffix_result = reconcile_identity_assertions(
        [_assertion(_resolved(), "manufacturer", "ds"), _assertion(suffix, "distributor", "listing")]
    )
    assert suffix_result.state == "conflict"
    assert {item.field for item in suffix_result.disagreements} >= {"mpn", "package_suffix"}

    swapped = _resolved(pin_pad_map=(PinPadMap("1", "2"), PinPadMap("2", "1"), PinPadMap("EP", "EP")))
    swapped_result = reconcile_identity_assertions(
        [_assertion(_resolved(), "manufacturer", "ds"), _assertion(swapped, "symbol", "lib")]
    )
    assert {item.field for item in swapped_result.disagreements} == {"pin_pad_map"}


def test_same_source_family_is_not_independent_corroboration():
    result = reconcile_identity_assertions(
        [_assertion(_resolved(), "manufacturer", "ds-a"), _assertion(_resolved(), "manufacturer", "ds-b")]
    )
    assert result.state == "missing"
    assert "independent_source" in result.missing_coverage


def test_human_approval_is_attributable_and_retains_underlying_conflict():
    conflicting = _resolved(mpn="ABC123-QFN32-R", package_suffix="QFN32-R")
    approval = build_human_identity_approval(
        owner="reviewer1", reason="Package change verified on approved ECO", approved_identity_id=_resolved().id
    )
    result = reconcile_identity_assertions(
        [_assertion(_resolved(), "manufacturer", "ds"), _assertion(conflicting, "distributor", "listing")],
        approval=approval,
    )
    assert result.state == "human-approved"
    assert result.source_state == "conflict"
    assert result.approval == approval


def test_t247_2_json_roundtrips_and_rejects_tampering():
    assertion = _assertion(_resolved(), "manufacturer", "ds")
    assert identity_source_assertion_from_dict(identity_source_assertion_to_dict(assertion)) == assertion
    tampered = identity_source_assertion_to_dict(assertion)
    tampered["id"] = "IAS-000000000000"
    with pytest.raises(ValueError, match="ID does not match"):
        identity_source_assertion_from_dict(tampered)

    result = reconcile_identity_assertions([assertion])
    assert identity_reconciliation_from_dict(identity_reconciliation_to_dict(result)) == result
    bad_result = identity_reconciliation_to_dict(result)
    bad_result["source_state"] = "agree"
    with pytest.raises(ValueError, match="ID does not match"):
        identity_reconciliation_from_dict(bad_result)


@pytest.mark.parametrize("uri", ["C:\\private\\part.pdf", "/home/me/part.pdf", "https://user:secret@example.test/part"])
def test_source_assertion_rejects_unsafe_uri(uri):
    with pytest.raises(ValueError):
        build_identity_source_assertion(
            source_family="manufacturer", source_uri=uri, source_doc_id="ds", identity=_resolved()
        )


def test_reconciliation_rejects_handcrafted_invalid_source_assertion():
    assertion = _assertion(_resolved(), "manufacturer", "ds")
    invalid = type(assertion)(
        id="IAS-000000000000",
        source_family=assertion.source_family,
        source_uri=assertion.source_uri,
        source_doc_id=assertion.source_doc_id,
        identity=assertion.identity,
        evidence_ids=assertion.evidence_ids,
    )
    with pytest.raises(ValueError, match="ID does not match"):
        reconcile_identity_assertions([invalid])


def _handoff(identity, *others, approval=None):
    assertions = [_assertion(identity, "manufacturer", "ds"), *others]
    reconciliation = reconcile_identity_assertions(assertions, approval=approval)
    return assertions, reconciliation


def _guard(assertions, reconciliation, identity):
    return evaluate_identity_handoff(
        assertions,
        reconciliation,
        manufacturer=identity.manufacturer,
        mpn=identity.mpn,
        package_suffix=identity.package_suffix,
        symbol_ref=identity.symbol_ref,
        footprint_ref=identity.footprint_ref,
    )


def _forged_agree_reconciliation(assertions) -> IdentityReconciliation:
    ordered = tuple(sorted(assertions, key=lambda item: item.id))
    evidence_ids = tuple(sorted({value for item in ordered for value in item.evidence_ids}))
    payload = {
        "state": "agree",
        "source_state": "agree",
        "assertion_ids": [item.id for item in ordered],
        "evidence_ids": list(evidence_ids),
        "missing_coverage": [],
        "disagreements": [],
        "approval_id": None,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return IdentityReconciliation(
        id=f"IRC-{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:12]}",
        state="agree",
        source_state="agree",
        assertion_ids=tuple(payload["assertion_ids"]),
        evidence_ids=evidence_ids,
    )


def test_handoff_guard_agreed_pass_and_roundtrip_tamper():
    identity = _resolved()
    assertions, reconciliation = _handoff(identity, _assertion(identity, "distributor", "listing"))
    result = _guard(assertions, reconciliation, identity)
    assert result.ready
    assert identity_handoff_from_dict(identity_handoff_to_dict(result)) == result
    tampered = identity_handoff_to_dict(result)
    tampered["ready"] = False
    with pytest.raises(ValueError, match="ID does not match"):
        identity_handoff_from_dict(tampered)
    bundle = IdentityHandoffBundle(
        assertions=tuple(assertions),
        reconciliation=reconciliation,
        manufacturer=identity.manufacturer,
        mpn=identity.mpn,
        package_suffix=identity.package_suffix,
        symbol_ref=identity.symbol_ref,
        footprint_ref=identity.footprint_ref,
    )
    assert identity_handoff_bundle_from_dict(identity_handoff_bundle_to_dict(bundle)).evaluate().ready


def test_handoff_recomputes_reconciliation_instead_of_trusting_self_reported_agreement():
    identity = _resolved()
    assertions = [_assertion(identity, "manufacturer", "ds")]
    forged = _forged_agree_reconciliation(assertions)

    with pytest.raises(ValueError, match="does not match its source assertions"):
        _guard(assertions, forged, identity)


def test_handoff_guard_blocks_missing_wrong_selection_and_partial_exposed_pad():
    identity = _resolved()
    assertions, reconciliation = _handoff(identity)
    missing = _guard(assertions, reconciliation, identity)
    assert not missing.ready
    assert "CW-ID-004" in missing.blocker_codes
    wrong = _resolved(footprint_ref="Package_QFN:QFN-24")
    assert not _guard(assertions, reconciliation, wrong).ready
    partial = _resolved(pin_pad_map=(PinPadMap("1", "1"), PinPadMap("2", "2")))
    assertions, reconciliation = _handoff(partial, _assertion(partial, "distributor", "listing"))
    assert "CW-ID-002" in _guard(assertions, reconciliation, partial).blocker_codes


def test_handoff_guard_conflict_and_targeted_approval_behavior():
    identity = _resolved()
    conflicting = _resolved(mpn="ABC123-QFN32-R", package_suffix="QFN32-R")
    assertions = [_assertion(identity, "manufacturer", "ds"), _assertion(conflicting, "distributor", "listing")]
    conflict = reconcile_identity_assertions(assertions)
    assert not _guard(assertions, conflict, identity).ready
    with pytest.raises(ValueError, match="target one reconciled"):
        reconcile_identity_assertions(
            assertions,
            approval=build_human_identity_approval(owner="r", reason="x", approved_identity_id="IDN-000000000000"),
        )
    approval = build_human_identity_approval(owner="r", reason="x", approved_identity_id=identity.id)
    approved = reconcile_identity_assertions(assertions, approval=approval)
    assert approved.source_state == "conflict"
    assert _guard(assertions, approved, identity).ready
    with pytest.raises(IdentityHandoffBlocked) as blocked:
        require_identity_handoff(
            assertions,
            conflict,
            manufacturer=identity.manufacturer,
            mpn=identity.mpn,
            package_suffix=identity.package_suffix,
            symbol_ref=identity.symbol_ref,
            footprint_ref=identity.footprint_ref,
        )
    assert blocked.value.result.ready is False
    assert blocked.value.result.blocker_codes


def test_handoff_rejects_assertions_from_a_different_reconciliation():
    identity = _resolved()
    assertions, reconciliation = _handoff(identity, _assertion(identity, "distributor", "listing"))
    unrelated = _assertion(identity, "symbol", "library")

    with pytest.raises(ValueError, match="do not match"):
        _guard([assertions[0], unrelated], reconciliation, identity)
