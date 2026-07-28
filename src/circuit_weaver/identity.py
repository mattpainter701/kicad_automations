"""Immutable, exact part-identity records for the pre-routing safety gate.

This T247.1 substrate deliberately records only asserted identifiers and explicit
pin-to-pad joins.  It performs no package, pin-name, or alias heuristics.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Final, Iterable, Mapping

IDENTITY_STATUSES: Final = frozenset({"resolved", "unresolved"})
RECONCILIATION_STATES: Final = frozenset({"agree", "conflict", "missing", "human-approved"})
_IDENTIFIER_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+\-/]*$")
_EVIDENCE_ID_RE: Final = re.compile(r"^EV-[A-Z_]+-[a-f0-9]{12}$", re.IGNORECASE)


def _exact_identifier(value: str, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{field} must be a non-empty exact identifier")
    return value


def _exact_text(value: str, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"{field} must be non-empty exact text")
    return value


@dataclass(frozen=True, order=True)
class PinPadMap:
    """One explicit symbol pin-number to footprint pad-number correspondence."""

    symbol_pin: str
    footprint_pad: str


@dataclass(frozen=True, order=True)
class DistributorAlias:
    """A distributor name and its exact orderable part-number alias."""

    distributor: str
    part_number: str


@dataclass(frozen=True)
class IdentityRecord:
    """Canonical identity join consumed by later reconciliation and routing guards."""

    id: str
    status: str
    manufacturer: str | None
    mpn: str | None
    package_suffix: str | None
    symbol_ref: str | None = None
    footprint_ref: str | None = None
    symbol_pins: tuple[str, ...] = ()
    footprint_pads: tuple[str, ...] = ()
    pin_pad_map: tuple[PinPadMap, ...] = ()
    distributor_aliases: tuple[DistributorAlias, ...] = ()
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class IdentitySourceAssertion:
    """An immutable identity assertion from one independently attributable source."""

    id: str
    source_family: str
    source_uri: str | None
    source_doc_id: str | None
    identity: IdentityRecord
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class IdentityFieldDisagreement:
    """Exact asserted values that disagree for one identity field."""

    field: str
    assertions: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class HumanIdentityApproval:
    """An attributable human decision; it never rewrites source assertions."""

    id: str
    owner: str
    reason: str
    approved_identity_id: str | None = None
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class IdentityReconciliation:
    """T247.2 outcome, with unapproved source state retained under an approval."""

    id: str
    state: str
    source_state: str
    assertion_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    missing_coverage: tuple[str, ...] = ()
    disagreements: tuple[IdentityFieldDisagreement, ...] = ()
    approval: HumanIdentityApproval | None = None


@dataclass(frozen=True)
class IdentityHandoffResult:
    id: str
    ready: bool
    blocker_codes: tuple[str, ...]
    blocker_messages: tuple[str, ...]


@dataclass(frozen=True)
class IdentityHandoffBundle:
    assertions: tuple[IdentitySourceAssertion, ...]
    reconciliation: IdentityReconciliation
    manufacturer: str
    mpn: str
    package_suffix: str
    symbol_ref: str
    footprint_ref: str

    def evaluate(self) -> IdentityHandoffResult:
        return evaluate_identity_handoff(
            self.assertions,
            self.reconciliation,
            manufacturer=self.manufacturer,
            mpn=self.mpn,
            package_suffix=self.package_suffix,
            symbol_ref=self.symbol_ref,
            footprint_ref=self.footprint_ref,
        )


def identity_handoff_bundle_to_dict(bundle: IdentityHandoffBundle) -> dict[str, object]:
    """Serialize only validated nested identity data; no ready flag is trusted."""
    return {
        "assertions": [identity_source_assertion_to_dict(item) for item in bundle.assertions],
        "reconciliation": identity_reconciliation_to_dict(bundle.reconciliation),
        "manufacturer": bundle.manufacturer,
        "mpn": bundle.mpn,
        "package_suffix": bundle.package_suffix,
        "symbol_ref": bundle.symbol_ref,
        "footprint_ref": bundle.footprint_ref,
    }


def identity_handoff_bundle_from_dict(raw: Mapping[str, object]) -> IdentityHandoffBundle:
    required = {"assertions", "reconciliation", "manufacturer", "mpn", "package_suffix", "symbol_ref", "footprint_ref"}
    if (
        set(raw) != required
        or not isinstance(raw["assertions"], list)
        or not isinstance(raw["reconciliation"], Mapping)
    ):
        raise ValueError("malformed identity handoff bundle")
    if not all(isinstance(item, Mapping) for item in raw["assertions"]):
        raise ValueError("malformed identity handoff bundle")
    bundle = IdentityHandoffBundle(
        assertions=tuple(identity_source_assertion_from_dict(item) for item in raw["assertions"]),
        reconciliation=identity_reconciliation_from_dict(raw["reconciliation"]),
        manufacturer=raw["manufacturer"],
        mpn=raw["mpn"],
        package_suffix=raw["package_suffix"],
        symbol_ref=raw["symbol_ref"],
        footprint_ref=raw["footprint_ref"],
    )
    # Evaluate both validates nested links and prevents a forged success field.
    bundle.evaluate()
    return bundle


class IdentityHandoffBlocked(ValueError):
    """Raised with the complete deterministic blocker result for callers to render."""

    def __init__(self, result: IdentityHandoffResult) -> None:
        self.result = result
        super().__init__("; ".join(result.blocker_codes))


def _canonical_payload(
    *,
    status: str,
    manufacturer: str | None,
    mpn: str | None,
    package_suffix: str | None,
    symbol_ref: str | None,
    footprint_ref: str | None,
    symbol_pins: tuple[str, ...],
    footprint_pads: tuple[str, ...],
    pin_pad_map: tuple[PinPadMap, ...],
    distributor_aliases: tuple[DistributorAlias, ...],
    evidence_ids: tuple[str, ...],
) -> dict[str, object]:
    return {
        "status": status,
        "manufacturer": manufacturer,
        "mpn": mpn,
        "package_suffix": package_suffix,
        "symbol_ref": symbol_ref,
        "footprint_ref": footprint_ref,
        "symbol_pins": list(symbol_pins),
        "footprint_pads": list(footprint_pads),
        "pin_pad_map": [{"symbol_pin": item.symbol_pin, "footprint_pad": item.footprint_pad} for item in pin_pad_map],
        "distributor_aliases": [
            {"distributor": item.distributor, "part_number": item.part_number} for item in distributor_aliases
        ],
        "evidence_ids": list(evidence_ids),
    }


def _canonical_json_fields(**kwargs: object) -> str:
    payload = _canonical_payload(**kwargs)  # type: ignore[arg-type]
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def canonical_json(record: IdentityRecord) -> str:
    """Return the stable JSON representation used for deterministic identity IDs."""

    validate_identity_record(record)
    return _canonical_json_fields(
        status=record.status,
        manufacturer=record.manufacturer,
        mpn=record.mpn,
        package_suffix=record.package_suffix,
        symbol_ref=record.symbol_ref,
        footprint_ref=record.footprint_ref,
        symbol_pins=record.symbol_pins,
        footprint_pads=record.footprint_pads,
        pin_pad_map=record.pin_pad_map,
        distributor_aliases=record.distributor_aliases,
        evidence_ids=record.evidence_ids,
    )


def identity_id(**kwargs: object) -> str:
    """Return a deterministic ID for canonical identity content (not evidence order)."""

    payload = _canonical_json_fields(**kwargs)
    return f"IDN-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:12]}"


def validate_identity_record(record: IdentityRecord) -> None:
    """Fail closed on omitted, ambiguous, or non-canonical exact identity fields."""

    if record.status not in IDENTITY_STATUSES:
        raise ValueError(f"unsupported identity status: {record.status!r}")
    for field in ("manufacturer", "mpn", "package_suffix", "symbol_ref", "footprint_ref"):
        value = getattr(record, field)
        if value is not None:
            (_exact_identifier if field == "mpn" else _exact_text)(value, field)
    required_identity_fields = ("manufacturer", "mpn", "package_suffix")
    if record.status == "resolved" and any(getattr(record, field) is None for field in required_identity_fields):
        raise ValueError("resolved identity requires manufacturer, exact MPN, and package_suffix")
    for field in ("symbol_pins", "footprint_pads"):
        values = getattr(record, field)
        if tuple(sorted(values)) != values or len(set(values)) != len(values):
            raise ValueError(f"{field} must be sorted and unique")
        for value in values:
            _exact_identifier(value, field)
    if tuple(sorted(record.pin_pad_map)) != record.pin_pad_map:
        raise ValueError("pin_pad_map must be sorted")
    pins = [item.symbol_pin for item in record.pin_pad_map]
    pads = [item.footprint_pad for item in record.pin_pad_map]
    if len(set(pins)) != len(pins) or len(set(pads)) != len(pads):
        raise ValueError("pin_pad_map cannot contain ambiguous duplicate symbol pins or footprint pads")
    for item in record.pin_pad_map:
        _exact_identifier(item.symbol_pin, "symbol_pin")
        _exact_identifier(item.footprint_pad, "footprint_pad")
        if item.symbol_pin not in record.symbol_pins or item.footprint_pad not in record.footprint_pads:
            raise ValueError("pin_pad_map entries must be declared symbol pins and footprint pads")
    if tuple(sorted(record.distributor_aliases)) != record.distributor_aliases:
        raise ValueError("distributor_aliases must be sorted")
    distributors = [item.distributor for item in record.distributor_aliases]
    if len(set(distributors)) != len(distributors):
        raise ValueError("distributor aliases must not be ambiguous per distributor")
    for item in record.distributor_aliases:
        _exact_text(item.distributor, "distributor")
        _exact_identifier(item.part_number, "distributor part_number")
    if tuple(sorted(record.evidence_ids)) != record.evidence_ids or len(set(record.evidence_ids)) != len(
        record.evidence_ids
    ):
        raise ValueError("evidence_ids must be sorted and unique")
    if any(not _EVIDENCE_ID_RE.fullmatch(item) for item in record.evidence_ids):
        raise ValueError("evidence_ids must contain evidence IDs")
    expected = identity_id(
        status=record.status,
        manufacturer=record.manufacturer,
        mpn=record.mpn,
        package_suffix=record.package_suffix,
        symbol_ref=record.symbol_ref,
        footprint_ref=record.footprint_ref,
        symbol_pins=record.symbol_pins,
        footprint_pads=record.footprint_pads,
        pin_pad_map=record.pin_pad_map,
        distributor_aliases=record.distributor_aliases,
        evidence_ids=record.evidence_ids,
    )
    if record.id != expected:
        raise ValueError("identity ID does not match canonical record content")


def build_identity_record(
    *,
    status: str,
    manufacturer: str | None = None,
    mpn: str | None = None,
    package_suffix: str | None = None,
    symbol_ref: str | None = None,
    footprint_ref: str | None = None,
    symbol_pins: Iterable[str] = (),
    footprint_pads: Iterable[str] = (),
    pin_pad_map: Iterable[PinPadMap | Mapping[str, str]] = (),
    distributor_aliases: Iterable[DistributorAlias | Mapping[str, str]] = (),
    evidence_ids: Iterable[str] = (),
) -> IdentityRecord:
    """Build a normalized record without inferring any missing identifier or mapping."""

    maps = tuple(sorted(item if isinstance(item, PinPadMap) else PinPadMap(**dict(item)) for item in pin_pad_map))
    aliases = tuple(
        sorted(
            item if isinstance(item, DistributorAlias) else DistributorAlias(**dict(item))
            for item in distributor_aliases
        )
    )
    record_fields = dict(
        status=status,
        manufacturer=manufacturer,
        mpn=mpn,
        package_suffix=package_suffix,
        symbol_ref=symbol_ref,
        footprint_ref=footprint_ref,
        symbol_pins=tuple(sorted(symbol_pins)),
        footprint_pads=tuple(sorted(footprint_pads)),
        pin_pad_map=maps,
        distributor_aliases=aliases,
        evidence_ids=tuple(sorted(evidence_ids)),
    )
    record = IdentityRecord(id=identity_id(**record_fields), **record_fields)
    validate_identity_record(record)
    return record


def identity_to_dict(record: IdentityRecord) -> dict[str, object]:
    """Return a JSON-safe exact representation suitable for a later manifest."""

    validate_identity_record(record)
    return {"id": record.id, **json.loads(canonical_json(record))}


def identity_from_dict(raw: Mapping[str, object]) -> IdentityRecord:
    """Rehydrate and validate a JSON identity record without normalizing its ID."""

    try:
        record = build_identity_record(
            status=str(raw["status"]),
            manufacturer=raw.get("manufacturer"),
            mpn=raw.get("mpn"),
            package_suffix=raw.get("package_suffix"),
            symbol_ref=raw.get("symbol_ref"),
            footprint_ref=raw.get("footprint_ref"),
            symbol_pins=raw.get("symbol_pins", ()),  # type: ignore[arg-type]
            footprint_pads=raw.get("footprint_pads", ()),  # type: ignore[arg-type]
            pin_pad_map=raw.get("pin_pad_map", ()),  # type: ignore[arg-type]
            distributor_aliases=raw.get("distributor_aliases", ()),  # type: ignore[arg-type]
            evidence_ids=raw.get("evidence_ids", ()),  # type: ignore[arg-type]
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("malformed identity record") from exc
    if raw.get("id") != record.id:
        raise ValueError("identity ID does not match canonical record content")
    return record


def _stable_id(prefix: str, payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"{prefix}-{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:12]}"


def build_identity_source_assertion(
    *,
    source_family: str,
    source_uri: str | None,
    source_doc_id: str | None,
    identity: IdentityRecord,
    evidence_ids: Iterable[str] = (),
) -> IdentitySourceAssertion:
    """Create a source assertion without treating similarly named sources as independent."""

    _exact_identifier(source_family, "source_family")
    if source_uri is None and source_doc_id is None:
        raise ValueError("source assertion requires source_uri or source_doc_id")
    if source_uri is not None:
        if not isinstance(source_uri, str) or not source_uri or source_uri != source_uri.strip():
            raise ValueError("source_uri must be a non-empty exact value")
    if source_doc_id is not None:
        _exact_text(source_doc_id, "source_doc_id")
    validate_identity_record(identity)
    ids = tuple(sorted(evidence_ids))
    if len(set(ids)) != len(ids) or any(not _EVIDENCE_ID_RE.fullmatch(item) for item in ids):
        raise ValueError("evidence_ids must contain sorted unique evidence IDs")
    payload = {
        "source_family": source_family,
        "source_uri": source_uri,
        "source_doc_id": source_doc_id,
        "identity_id": identity.id,
        "evidence_ids": list(ids),
    }
    assertion = IdentitySourceAssertion(
        id=_stable_id("IAS", payload),
        source_family=source_family,
        source_uri=source_uri,
        source_doc_id=source_doc_id,
        identity=identity,
        evidence_ids=ids,
    )
    validate_identity_source_assertion(assertion)
    return assertion


def build_human_identity_approval(
    *, owner: str, reason: str, approved_identity_id: str, evidence_ids: Iterable[str] = ()
) -> HumanIdentityApproval:
    """Create an explicit, attributable exception without changing source evidence."""

    _exact_text(owner, "approval owner")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("approval reason must be non-empty")
    ids = tuple(sorted(evidence_ids))
    if len(set(ids)) != len(ids) or any(not _EVIDENCE_ID_RE.fullmatch(item) for item in ids):
        raise ValueError("evidence_ids must contain sorted unique evidence IDs")
    if not isinstance(approved_identity_id, str) or not approved_identity_id.startswith("IDN-"):
        raise ValueError("approved_identity_id must be an identity ID")
    approval = HumanIdentityApproval(
        id=_stable_id(
            "IAP",
            {"owner": owner, "reason": reason, "approved_identity_id": approved_identity_id, "evidence_ids": list(ids)},
        ),
        owner=owner,
        reason=reason,
        approved_identity_id=approved_identity_id,
        evidence_ids=ids,
    )
    validate_human_identity_approval(approval)
    return approval


def validate_identity_source_assertion(assertion: IdentitySourceAssertion) -> None:
    """Validate a source assertion built outside the public constructor."""

    from .evidence_policy import validate_evidence_text

    _exact_identifier(assertion.source_family, "source_family")
    if assertion.source_uri is None and assertion.source_doc_id is None:
        raise ValueError("source assertion requires source_uri or source_doc_id")
    for field in ("source_uri", "source_doc_id"):
        value = getattr(assertion, field)
        if value is not None:
            _exact_text(value, field)
            validate_evidence_text(value)
    validate_identity_record(assertion.identity)
    if tuple(sorted(assertion.evidence_ids)) != assertion.evidence_ids or len(set(assertion.evidence_ids)) != len(
        assertion.evidence_ids
    ):
        raise ValueError("evidence_ids must contain sorted unique evidence IDs")
    if any(not _EVIDENCE_ID_RE.fullmatch(item) for item in assertion.evidence_ids):
        raise ValueError("evidence_ids must contain evidence IDs")
    expected = _stable_id(
        "IAS",
        {
            "source_family": assertion.source_family,
            "source_uri": assertion.source_uri,
            "source_doc_id": assertion.source_doc_id,
            "identity_id": assertion.identity.id,
            "evidence_ids": list(assertion.evidence_ids),
        },
    )
    if assertion.id != expected:
        raise ValueError("identity source assertion ID does not match canonical content")


def validate_human_identity_approval(approval: HumanIdentityApproval) -> None:
    """Validate a direct, frozen approval instance and its deterministic ID."""

    _exact_text(approval.owner, "approval owner")
    if not isinstance(approval.reason, str) or not approval.reason.strip():
        raise ValueError("approval reason must be non-empty")
    if tuple(sorted(approval.evidence_ids)) != approval.evidence_ids or len(set(approval.evidence_ids)) != len(
        approval.evidence_ids
    ):
        raise ValueError("evidence_ids must contain sorted unique evidence IDs")
    if any(not _EVIDENCE_ID_RE.fullmatch(item) for item in approval.evidence_ids):
        raise ValueError("evidence_ids must contain evidence IDs")
    if not isinstance(approval.approved_identity_id, str) or not approval.approved_identity_id.startswith("IDN-"):
        raise ValueError("approved_identity_id must be an identity ID")
    expected = _stable_id(
        "IAP",
        {
            "owner": approval.owner,
            "reason": approval.reason,
            "approved_identity_id": approval.approved_identity_id,
            "evidence_ids": list(approval.evidence_ids),
        },
    )
    if approval.id != expected:
        raise ValueError("human identity approval ID does not match canonical content")


def identity_source_assertion_to_dict(assertion: IdentitySourceAssertion) -> dict[str, object]:
    validate_identity_source_assertion(assertion)
    return {
        "id": assertion.id,
        "source_family": assertion.source_family,
        "source_uri": assertion.source_uri,
        "source_doc_id": assertion.source_doc_id,
        "identity": identity_to_dict(assertion.identity),
        "evidence_ids": list(assertion.evidence_ids),
    }


def identity_source_assertion_from_dict(raw: Mapping[str, object]) -> IdentitySourceAssertion:
    if set(raw) != {"id", "source_family", "source_uri", "source_doc_id", "identity", "evidence_ids"}:
        raise ValueError("malformed identity source assertion")
    if not isinstance(raw["identity"], Mapping) or not isinstance(raw["evidence_ids"], list):
        raise ValueError("malformed identity source assertion")
    assertion = IdentitySourceAssertion(
        id=raw["id"],
        source_family=raw["source_family"],
        source_uri=raw["source_uri"],
        source_doc_id=raw["source_doc_id"],
        identity=identity_from_dict(raw["identity"]),
        evidence_ids=tuple(raw["evidence_ids"]),
    )
    validate_identity_source_assertion(assertion)
    return assertion


def human_identity_approval_to_dict(approval: HumanIdentityApproval) -> dict[str, object]:
    validate_human_identity_approval(approval)
    return {
        "id": approval.id,
        "owner": approval.owner,
        "reason": approval.reason,
        "approved_identity_id": approval.approved_identity_id,
        "evidence_ids": list(approval.evidence_ids),
    }


def human_identity_approval_from_dict(raw: Mapping[str, object]) -> HumanIdentityApproval:
    if set(raw) != {"id", "owner", "reason", "approved_identity_id", "evidence_ids"} or not isinstance(
        raw.get("evidence_ids"), list
    ):
        raise ValueError("malformed human identity approval")
    approval = HumanIdentityApproval(
        id=raw["id"],
        owner=raw["owner"],
        reason=raw["reason"],
        approved_identity_id=raw["approved_identity_id"],
        evidence_ids=tuple(raw["evidence_ids"]),
    )
    validate_human_identity_approval(approval)
    return approval


def _source_key(assertion: IdentitySourceAssertion) -> tuple[str, str, str]:
    """Same URI, document, or source family is deliberately non-independent."""

    return (assertion.source_family, assertion.source_uri or "", assertion.source_doc_id or "")


def _field_value(identity: IdentityRecord, field: str) -> object:
    return getattr(identity, field)


def reconcile_identity_assertions(
    assertions: Iterable[IdentitySourceAssertion],
    *,
    approval: HumanIdentityApproval | None = None,
) -> IdentityReconciliation:
    """Reconcile exact source assertions, retaining uncertainty and disagreement verbatim."""

    ordered = tuple(sorted(assertions, key=lambda item: item.id))
    if not ordered:
        raise ValueError("at least one identity source assertion is required")
    if len({item.id for item in ordered}) != len(ordered):
        raise ValueError("identity source assertion IDs must be unique")
    for item in ordered:
        validate_identity_source_assertion(item)
    if approval is not None:
        validate_human_identity_approval(approval)
        if approval.approved_identity_id not in {item.identity.id for item in ordered}:
            raise ValueError("approval must target one reconciled identity")
    # An independently attributable source must differ in every provenance anchor;
    # sharing even one anchor could be a mirrored/repackaged assertion.
    independent: list[IdentitySourceAssertion] = []
    used_families: set[str] = set()
    used_uris: set[str] = set()
    used_docs: set[str] = set()
    for item in ordered:
        if (
            item.source_family in used_families
            or (item.source_uri and item.source_uri in used_uris)
            or (item.source_doc_id and item.source_doc_id in used_docs)
        ):
            continue
        independent.append(item)
        used_families.add(item.source_family)
        if item.source_uri:
            used_uris.add(item.source_uri)
        if item.source_doc_id:
            used_docs.add(item.source_doc_id)

    fields = (
        "manufacturer",
        "mpn",
        "package_suffix",
        "symbol_ref",
        "footprint_ref",
        "symbol_pins",
        "footprint_pads",
        "pin_pad_map",
    )
    missing: list[str] = []
    disagreements: list[IdentityFieldDisagreement] = []
    if len(independent) < 2:
        missing.append("independent_source")
    for field in fields:
        values = [(item.id, _field_value(item.identity, field)) for item in independent]
        absent = [value for _assertion_id, value in values if value is None or value == ()]
        if absent:
            missing.append(field)
        present = [(assertion_id, value) for assertion_id, value in values if value is not None and value != ()]
        if len({repr(value) for _assertion_id, value in present}) > 1:
            disagreements.append(
                IdentityFieldDisagreement(
                    field=field,
                    assertions=tuple((assertion_id, repr(value)) for assertion_id, value in present),
                )
            )
    source_state = "conflict" if disagreements else "missing" if missing else "agree"
    state = "human-approved" if approval is not None else source_state
    approval_evidence = () if approval is None else approval.evidence_ids
    source_evidence = {evidence for item in ordered for evidence in item.evidence_ids}
    evidence_ids = tuple(sorted({*source_evidence, *approval_evidence}))
    payload = {
        "state": state,
        "source_state": source_state,
        "assertion_ids": [item.id for item in ordered],
        "evidence_ids": list(evidence_ids),
        "missing_coverage": sorted(set(missing)),
        "disagreements": [
            {"field": item.field, "assertions": [list(value) for value in item.assertions]} for item in disagreements
        ],
        "approval_id": approval.id if approval else None,
    }
    result = IdentityReconciliation(
        id=_stable_id("IRC", payload),
        state=state,
        source_state=source_state,
        assertion_ids=tuple(item.id for item in ordered),
        evidence_ids=evidence_ids,
        missing_coverage=tuple(sorted(set(missing))),
        disagreements=tuple(disagreements),
        approval=approval,
    )
    validate_identity_reconciliation(result)
    return result


def validate_identity_reconciliation(result: IdentityReconciliation) -> None:
    """Validate a rehydrated reconciliation without reconstructing source assertions."""

    if result.state not in RECONCILIATION_STATES or result.source_state not in {"agree", "conflict", "missing"}:
        raise ValueError("unsupported reconciliation state")
    if result.state == "human-approved" and result.approval is None:
        raise ValueError("human-approved reconciliation requires an approval")
    if result.state != "human-approved" and result.approval is not None:
        raise ValueError("approval may only accompany human-approved reconciliation")
    if tuple(sorted(result.assertion_ids)) != result.assertion_ids or len(set(result.assertion_ids)) != len(
        result.assertion_ids
    ):
        raise ValueError("assertion_ids must be sorted and unique")
    if tuple(sorted(result.evidence_ids)) != result.evidence_ids or any(
        not _EVIDENCE_ID_RE.fullmatch(item) for item in result.evidence_ids
    ):
        raise ValueError("evidence_ids must contain sorted evidence IDs")
    if tuple(sorted(result.missing_coverage)) != result.missing_coverage:
        raise ValueError("missing_coverage must be sorted")
    if result.approval is not None:
        validate_human_identity_approval(result.approval)
    payload = {
        "state": result.state,
        "source_state": result.source_state,
        "assertion_ids": list(result.assertion_ids),
        "evidence_ids": list(result.evidence_ids),
        "missing_coverage": list(result.missing_coverage),
        "disagreements": [
            {"field": item.field, "assertions": [list(value) for value in item.assertions]}
            for item in result.disagreements
        ],
        "approval_id": result.approval.id if result.approval else None,
    }
    if result.id != _stable_id("IRC", payload):
        raise ValueError("identity reconciliation ID does not match canonical content")


def identity_reconciliation_to_dict(result: IdentityReconciliation) -> dict[str, object]:
    validate_identity_reconciliation(result)
    return {
        "id": result.id,
        "state": result.state,
        "source_state": result.source_state,
        "assertion_ids": list(result.assertion_ids),
        "evidence_ids": list(result.evidence_ids),
        "missing_coverage": list(result.missing_coverage),
        "disagreements": [
            {"field": item.field, "assertions": [list(value) for value in item.assertions]}
            for item in result.disagreements
        ],
        "approval": None if result.approval is None else human_identity_approval_to_dict(result.approval),
    }


def identity_reconciliation_from_dict(raw: Mapping[str, object]) -> IdentityReconciliation:
    required = {
        "id",
        "state",
        "source_state",
        "assertion_ids",
        "evidence_ids",
        "missing_coverage",
        "disagreements",
        "approval",
    }
    if set(raw) != required or not all(
        isinstance(raw[field], list) for field in ("assertion_ids", "evidence_ids", "missing_coverage", "disagreements")
    ):
        raise ValueError("malformed identity reconciliation")
    approval_raw = raw["approval"]
    if approval_raw is not None and not isinstance(approval_raw, Mapping):
        raise ValueError("malformed identity reconciliation")
    disagreements: list[IdentityFieldDisagreement] = []
    for item in raw["disagreements"]:
        if (
            not isinstance(item, Mapping)
            or set(item) != {"field", "assertions"}
            or not isinstance(item["assertions"], list)
        ):
            raise ValueError("malformed identity reconciliation")
        pairs = tuple(tuple(pair) for pair in item["assertions"])
        if any(len(pair) != 2 or not all(isinstance(value, str) for value in pair) for pair in pairs):
            raise ValueError("malformed identity reconciliation")
        disagreements.append(IdentityFieldDisagreement(field=item["field"], assertions=pairs))
    result = IdentityReconciliation(
        id=raw["id"],
        state=raw["state"],
        source_state=raw["source_state"],
        assertion_ids=tuple(raw["assertion_ids"]),
        evidence_ids=tuple(raw["evidence_ids"]),
        missing_coverage=tuple(raw["missing_coverage"]),
        disagreements=tuple(disagreements),
        approval=None if approval_raw is None else human_identity_approval_from_dict(approval_raw),
    )
    validate_identity_reconciliation(result)
    return result


def evaluate_identity_handoff(
    assertions: Iterable[IdentitySourceAssertion],
    reconciliation: IdentityReconciliation,
    *,
    manufacturer: str,
    mpn: str,
    package_suffix: str,
    symbol_ref: str,
    footprint_ref: str,
) -> IdentityHandoffResult:
    """Fail closed before any pad-emitting board handoff."""
    records = tuple(assertions)
    validate_identity_reconciliation(reconciliation)
    if not records:
        raise ValueError("identity handoff requires source assertions")
    for assertion in records:
        validate_identity_source_assertion(assertion)
    if tuple(sorted(item.id for item in records)) != reconciliation.assertion_ids:
        raise ValueError("identity handoff assertions do not match the reconciliation")
    recomputed = reconcile_identity_assertions(records, approval=reconciliation.approval)
    if recomputed != reconciliation:
        raise ValueError("identity reconciliation does not match its source assertions")
    codes: list[str] = []
    selected = [
        item.identity
        for item in records
        if item.identity.manufacturer == manufacturer
        and item.identity.mpn == mpn
        and item.identity.package_suffix == package_suffix
        and item.identity.symbol_ref == symbol_ref
        and item.identity.footprint_ref == footprint_ref
    ]
    if not selected:
        codes.append("CW-ID-001")
    for identity in selected:
        if set(item.symbol_pin for item in identity.pin_pad_map) != set(identity.symbol_pins) or set(
            item.footprint_pad for item in identity.pin_pad_map
        ) != set(identity.footprint_pads):
            codes.append("CW-ID-002")
    approved = reconciliation.approval is not None and any(
        item.id == reconciliation.approval.approved_identity_id for item in selected
    )
    if "independent_source" in reconciliation.missing_coverage and not approved:
        codes.append("CW-ID-004")
    elif reconciliation.source_state != "agree" and not approved:
        codes.append("CW-ID-003")
    codes = sorted(set(codes))
    messages = tuple(
        {
            "CW-ID-001": "selected exact identity is unsupported",
            "CW-ID-002": "pin-to-pad coverage is incomplete",
            "CW-ID-003": "identity source conflict or missing coverage is unapproved",
            "CW-ID-004": "fewer than two independent agreeing selected sources",
        }[code]
        for code in codes
    )
    payload = {"ready": not codes, "blocker_codes": codes, "blocker_messages": list(messages)}
    return IdentityHandoffResult(
        id=_stable_id("IHR", payload), ready=not codes, blocker_codes=tuple(codes), blocker_messages=messages
    )


def require_identity_handoff(*args: object, **kwargs: object) -> IdentityHandoffResult:
    result = evaluate_identity_handoff(*args, **kwargs)  # type: ignore[arg-type]
    if not result.ready:
        raise IdentityHandoffBlocked(result)
    return result


def identity_handoff_to_dict(result: IdentityHandoffResult) -> dict[str, object]:
    payload = {
        "ready": result.ready,
        "blocker_codes": list(result.blocker_codes),
        "blocker_messages": list(result.blocker_messages),
    }
    if result.id != _stable_id("IHR", payload):
        raise ValueError("identity handoff ID does not match canonical content")
    return {"id": result.id, **payload}


def identity_handoff_from_dict(raw: Mapping[str, object]) -> IdentityHandoffResult:
    if (
        set(raw) != {"id", "ready", "blocker_codes", "blocker_messages"}
        or not isinstance(raw.get("ready"), bool)
        or not isinstance(raw.get("blocker_codes"), list)
        or not isinstance(raw.get("blocker_messages"), list)
    ):
        raise ValueError("malformed identity handoff result")
    result = IdentityHandoffResult(
        id=raw["id"],
        ready=raw["ready"],
        blocker_codes=tuple(raw["blocker_codes"]),
        blocker_messages=tuple(raw["blocker_messages"]),
    )
    identity_handoff_to_dict(result)
    return result
