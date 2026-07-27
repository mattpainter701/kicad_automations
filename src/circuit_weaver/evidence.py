"""Frozen, fail-closed provenance records for Circuit Weaver assertions.

This module is intentionally independent of producers and presentation
surfaces.  Producers may only record evidence they actually possess; missing
source fields, heuristic evidence, and conflicts remain visible rather than
being upgraded or filled in by this ledger.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final, Iterable, Mapping

MANIFEST_SCHEMA_VERSION: Final = "circuit-weaver-evidence-manifest/v1"
EVIDENCE_KINDS: Final = frozenset(
    {
        "datasheet",
        "distributor",
        "symbol_lib",
        "footprint_lib",
        "catalog",
        "calculation",
        "tool_result",
        "user",
        "heuristic",
        "stub",
    }
)
CONFIDENCE_LEVELS: Final = frozenset({"verified", "corroborated", "single_source", "heuristic", "stub", "conflicting"})
FRESHNESS_STATES: Final = frozenset({"current", "stale", "unknown"})
_SUBJECT_RE = re.compile(
    r"^(?:comp:[A-Za-z][A-Za-z0-9_]*|pin:[A-Za-z][A-Za-z0-9_]*\.[A-Za-z0-9_+-]+|net:[^\s]+|"
    r"param:[A-Za-z][A-Za-z0-9_]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|footprint:[^\s]+|"
    r"calc:(?:CW-[A-Z0-9]+-[0-9]{3}|[a-z][a-z0-9_]*)@[A-Za-z][A-Za-z0-9_]*|"
    r"tool:[A-Za-z0-9_.-]+)$"
)


@dataclass(frozen=True)
class EvidenceSource:
    """Source metadata; absent facts are represented by ``None``, never guesses."""

    uri: str | None = None
    doc_id: str | None = None
    content_hash: str | None = None
    retrieved_at: str | None = None
    extraction_method: str = "unknown"


@dataclass(frozen=True)
class EvidenceRecord:
    """The frozen evidence-record shape used by all later epics."""

    id: str
    subject_ref: str
    claim: str
    kind: str
    source: EvidenceSource
    confidence: str
    freshness: str
    conflicts: tuple[str, ...] = ()
    supersedes: str | None = None


def _safe_text(value: str, field: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{field} must be non-empty")
    from .evidence_policy import validate_evidence_text

    validate_evidence_text(value)
    return value


def _validate_source(source: EvidenceSource) -> None:
    for field in ("uri", "doc_id", "content_hash", "retrieved_at", "extraction_method"):
        value = getattr(source, field)
        if value is not None:
            _safe_text(value, f"source.{field}")
    if source.content_hash is not None and not re.fullmatch(r"[A-Fa-f0-9]{32,128}", source.content_hash):
        raise ValueError("source.content_hash must be a hexadecimal digest")


def evidence_id(subject_ref: str, claim: str, kind: str, source: EvidenceSource) -> str:
    """Return the frozen deterministic ID, intentionally excluding timestamps."""

    _safe_text(subject_ref, "subject_ref")
    _safe_text(claim, "claim")
    if kind not in EVIDENCE_KINDS:
        raise ValueError(f"invalid evidence kind: {kind!r}")
    _validate_source(source)
    source_key = source.doc_id or source.uri or ""
    payload = "|".join((subject_ref, claim, source_key, source.extraction_method))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"EV-{kind.upper()}-{digest}"


def validate_record(record: EvidenceRecord) -> None:
    """Reject malformed, unsafe, or self-contradictory evidence records."""

    if not _SUBJECT_RE.fullmatch(record.subject_ref):
        raise ValueError(f"invalid subject_ref: {record.subject_ref!r}")
    _safe_text(record.claim, "claim")
    if record.kind not in EVIDENCE_KINDS:
        raise ValueError(f"invalid evidence kind: {record.kind!r}")
    if record.confidence not in CONFIDENCE_LEVELS:
        raise ValueError(f"invalid evidence confidence: {record.confidence!r}")
    if record.freshness not in FRESHNESS_STATES:
        raise ValueError(f"invalid freshness: {record.freshness!r}")
    _validate_source(record.source)
    expected_id = evidence_id(record.subject_ref, record.claim, record.kind, record.source)
    if record.id != expected_id:
        raise ValueError("evidence ID does not match its deterministic inputs")
    if record.id in record.conflicts:
        raise ValueError("evidence record cannot conflict with itself")
    if any(not re.fullmatch(r"EV-[A-Z_]+-[a-f0-9]{12}", conflict) for conflict in record.conflicts):
        raise ValueError("conflicts must contain evidence IDs")
    if record.supersedes is not None:
        if not isinstance(record.supersedes, str) or not re.fullmatch(r"EV-[A-Z_]+-[a-f0-9]{12}", record.supersedes):
            raise ValueError("supersedes must be an evidence ID or None")
        if record.supersedes == record.id:
            raise ValueError("evidence record cannot supersede itself")
    if record.kind == "heuristic" and record.confidence != "heuristic":
        raise ValueError("heuristic evidence cannot be upgraded by the ledger")
    if record.kind == "stub" and record.confidence != "stub":
        raise ValueError("stub evidence cannot be upgraded by the ledger")
    if record.conflicts and record.confidence != "conflicting":
        raise ValueError("unresolved conflicts require conflicting confidence")
    if record.confidence == "conflicting" and not record.conflicts:
        raise ValueError("conflicting confidence requires conflict IDs")


def _record_to_dict(record: EvidenceRecord) -> dict[str, object]:
    data = asdict(record)
    data["conflicts"] = list(record.conflicts)
    return data


def _copy_record(record: EvidenceRecord) -> EvidenceRecord:
    """Copy nested source data instead of exposing a ledger-owned object."""

    return EvidenceRecord(
        id=record.id,
        subject_ref=record.subject_ref,
        claim=record.claim,
        kind=record.kind,
        source=EvidenceSource(**asdict(record.source)),
        confidence=record.confidence,
        freshness=record.freshness,
        conflicts=tuple(record.conflicts),
        supersedes=record.supersedes,
    )


class EvidenceLedger:
    """Idempotent collector for deterministic, JSON-safe evidence manifests."""

    def __init__(self, records: Iterable[EvidenceRecord] = ()) -> None:
        self._records: dict[str, EvidenceRecord] = {}
        for record in records:
            self.add(record)

    def add(self, record: EvidenceRecord) -> str:
        """Validate and add a record, returning its existing/stable ID."""

        return self._add(record)

    def _add(
        self,
        record: EvidenceRecord,
        *,
        allow_forward_supersedes: bool = False,
        allow_forward_corroboration: bool = False,
    ) -> str:
        """Internal admission path used by the order-independent manifest loader."""

        validate_record(record)
        from .evidence_policy import validate_evidence_safety

        known_ids = set(self._records)
        if allow_forward_supersedes and record.supersedes is not None:
            known_ids.add(record.supersedes)
        validate_evidence_safety(_record_to_dict(record), known_ids=known_ids)
        existing = self._records.get(record.id)
        if existing is not None and existing != record:
            raise ValueError(f"conflicting content for deterministic evidence ID {record.id}")
        if record.confidence == "corroborated" and not allow_forward_corroboration:
            agreeing = sum(
                1
                for existing_record in self._records.values()
                if existing_record.subject_ref == record.subject_ref
                and existing_record.claim == record.claim
                and existing_record.id != record.id
                and not existing_record.conflicts
            )
            if agreeing < 1:
                raise ValueError("corroborated confidence requires a second agreeing record")
        self._records[record.id] = record
        return record.id

    def record(
        self,
        *,
        subject_ref: str,
        claim: str,
        kind: str,
        source: EvidenceSource | Mapping[str, str | None] | None = None,
        confidence: str = "single_source",
        freshness: str = "unknown",
        conflicts: Iterable[str] = (),
        supersedes: str | None = None,
    ) -> str:
        """Build and add a record from actual producer-supplied provenance only."""

        source_value = EvidenceSource() if source is None else source
        if isinstance(source_value, Mapping):
            source_value = EvidenceSource(**dict(source_value))
        if not isinstance(source_value, EvidenceSource):
            raise TypeError("source must be EvidenceSource, a mapping, or None")
        conflict_ids = tuple(sorted(set(conflicts)))
        record = EvidenceRecord(
            id=evidence_id(subject_ref, claim, kind, source_value),
            subject_ref=subject_ref,
            claim=claim,
            kind=kind,
            source=source_value,
            confidence=confidence,
            freshness=freshness,
            conflicts=conflict_ids,
            supersedes=supersedes,
        )
        return self.add(record)

    def get(self, evidence_id_value: str) -> EvidenceRecord | None:
        """Return a copy-safe record, or ``None`` when the ID is absent."""

        record = self._records.get(evidence_id_value)
        return None if record is None else _copy_record(record)

    def for_subject(self, subject_ref: str) -> list[EvidenceRecord]:
        """Return copy-safe records for one exact join key, sorted by ID."""

        return [
            _copy_record(record) for _, record in sorted(self._records.items()) if record.subject_ref == subject_ref
        ]

    def to_manifest(self) -> dict[str, object]:
        """Return a copy-safe, deterministically ordered manifest payload."""

        return {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "records": [_record_to_dict(record) for _, record in sorted(self._records.items())],
        }

    def to_json(self) -> str:
        """Serialize a byte-stable manifest suitable for checked-in baselines."""

        return json.dumps(self.to_manifest(), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"

    def write(self, output_dir: str | Path) -> Path:
        """Write ``evidence_manifest.json`` to an explicitly supplied directory."""

        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "evidence_manifest.json"
        if path.is_symlink() or path.is_dir():
            raise ValueError("evidence manifest target must be a regular file path")
        path.write_text(self.to_json(), encoding="utf-8", newline="")
        return path

    @classmethod
    def from_manifest(cls, manifest: Mapping[str, object]) -> EvidenceLedger:
        """Rehydrate a validated ledger from its public manifest shape."""

        if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
            raise ValueError("unsupported evidence manifest schema_version")
        raw_records = manifest.get("records")
        if not isinstance(raw_records, list):
            raise ValueError("evidence manifest records must be a list")
        ledger = cls()
        pending = list(raw_records)
        while pending:
            progressed = False
            for raw in list(pending):
                if not isinstance(raw, Mapping) or not isinstance(raw.get("source"), Mapping):
                    raise ValueError("evidence manifest contains a malformed record")
                conflicts = tuple(str(value) for value in raw.get("conflicts", ()))
                if any(conflict not in ledger._records for conflict in conflicts):
                    continue
                record = EvidenceRecord(
                    id=str(raw.get("id", "")),
                    subject_ref=str(raw.get("subject_ref", "")),
                    claim=str(raw.get("claim", "")),
                    kind=str(raw.get("kind", "")),
                    source=EvidenceSource(**dict(raw["source"])),
                    confidence=str(raw.get("confidence", "")),
                    freshness=str(raw.get("freshness", "")),
                    conflicts=conflicts,
                    supersedes=raw.get("supersedes"),
                )
                ledger._add(record, allow_forward_supersedes=True, allow_forward_corroboration=True)
                pending.remove(raw)
                progressed = True
            if not progressed:
                raise ValueError("evidence manifest contains unresolved or cyclic conflicts")
        ledger._validate_corroborated_records()
        ledger._validate_supersedes_graph()
        return ledger

    def _validate_corroborated_records(self) -> None:
        """Enforce corroboration after all order-independent records are loaded."""

        for record in self._records.values():
            if record.confidence != "corroborated":
                continue
            agreeing = sum(
                1
                for other in self._records.values()
                if other.subject_ref == record.subject_ref
                and other.claim == record.claim
                and other.id != record.id
                and not other.conflicts
            )
            if agreeing < 1:
                raise ValueError("corroborated confidence requires a second agreeing record")

    def _validate_supersedes_graph(self) -> None:
        """Require every supersession target to resolve and the graph to be acyclic."""

        for record in self._records.values():
            if record.supersedes is not None and record.supersedes not in self._records:
                raise ValueError("evidence manifest contains unresolved supersedes reference")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(record_id: str) -> None:
            if record_id in visiting:
                raise ValueError("evidence manifest contains cyclic supersedes references")
            if record_id in visited:
                return
            visiting.add(record_id)
            target = self._records[record_id].supersedes
            if target is not None:
                visit(target)
            visiting.remove(record_id)
            visited.add(record_id)

        for record_id in self._records:
            visit(record_id)


def _component_source(component: Any) -> EvidenceSource:
    """Describe only provenance already carried by a resolved component."""

    datasheet_url = str(getattr(component, "datasheet_url", "") or "").strip()
    mpn = str(getattr(component, "source_mpn", "") or getattr(component, "mpn", "") or "").strip()
    return EvidenceSource(
        uri=datasheet_url or None,
        doc_id=mpn or None,
        extraction_method=str(getattr(component, "pinout_source", "") or "resolved-component-record"),
    )


def collect_component_evidence(
    ledger: EvidenceLedger,
    components: Iterable[Any],
) -> dict[str, list[str]]:
    """Record identity, pinout, footprint, and power facts actually present."""

    evidence_by_ref: dict[str, list[str]] = {}
    for component in components:
        ref = str(getattr(component, "source_ref", "") or "").strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", ref):
            continue
        evidence_by_ref.setdefault(ref, [])
        _merge_passive_synthesis_evidence(ledger, component, evidence_by_ref[ref])
        mpn = str(getattr(component, "source_mpn", "") or getattr(component, "mpn", "") or "").strip()
        pinout_source = str(getattr(component, "pinout_source", "") or "unknown")
        is_stub = pinout_source == "stub" or not mpn
        source = _component_source(component)
        identity_id = ledger.record(
            subject_ref=f"comp:{ref}",
            claim=f"resolved component identity is {mpn or 'unresolved'}",
            kind="stub" if is_stub else ("datasheet" if source.uri else "catalog"),
            source=source,
            confidence="stub" if is_stub else "single_source",
            freshness="unknown",
        )
        evidence_by_ref[ref].append(identity_id)

        footprint = str(getattr(component, "footprint", "") or "").strip()
        if footprint:
            footprint_id = ledger.record(
                subject_ref=f"footprint:{footprint}",
                claim=f"footprint selected for {ref}",
                kind="footprint_lib",
                source=source,
                confidence="single_source",
                freshness="unknown",
            )
            evidence_by_ref[ref].append(footprint_id)

        pin_kind = "stub" if is_stub else "symbol_lib"
        pin_confidence = (
            "stub"
            if is_stub
            else ("verified" if bool(getattr(component, "pinout_verified", False)) else "single_source")
        )
        for pin in getattr(component, "pins", ()) or ():
            number = str(getattr(pin, "number", "") or "").strip()
            name = str(getattr(pin, "name", "") or "").strip()
            if not number or not re.fullmatch(r"[A-Za-z0-9_+-]+", number):
                continue
            pin_id = ledger.record(
                subject_ref=f"pin:{ref}.{number}",
                claim=f"pin {number} is {name or 'unnamed'}",
                kind=pin_kind,
                source=source,
                confidence=pin_confidence,
                freshness="unknown",
            )
            evidence_by_ref[ref].append(pin_id)

        for requirement in getattr(component, "power_reqs", ()) or ():
            net = str(getattr(requirement, "net", "") or "").strip()
            if not net or not re.fullmatch(r"[A-Za-z0-9_-]+", net):
                continue
            facts: list[str] = []
            field_labels = (
                ("v_min", "minimum voltage", "V"),
                ("v_nominal", "nominal voltage", "V"),
                ("v_max", "maximum voltage", "V"),
                ("i_steady_ma", "steady current", "mA"),
                ("i_peak_ma", "peak current", "mA"),
            )
            for field_name, label, unit in field_labels:
                value = getattr(requirement, field_name, None)
                if value is not None:
                    facts.append(f"{label}={value} {unit}")
            if not any(item.startswith("nominal voltage=") for item in facts):
                voltage = getattr(requirement, "voltage", None)
                if voltage is not None:
                    facts.append(f"nominal voltage={voltage} V")
            if not any(item.startswith("peak current=") for item in facts):
                current = getattr(requirement, "max_current_ma", None)
                if current is not None:
                    facts.append(f"peak current={current} mA")
            direction = getattr(requirement, "direction", None)
            if direction:
                facts.append(f"direction={direction}")
            tolerance = getattr(requirement, "tolerance", None)
            if tolerance is not None:
                facts.append(f"tolerance={tolerance}")
            if not facts:
                continue
            parameter_id = ledger.record(
                subject_ref=f"param:{ref}.power.{net}",
                claim=f"power envelope for {net}: " + ", ".join(facts),
                kind="datasheet" if source.uri else "catalog",
                source=source,
                confidence="single_source",
                freshness="unknown",
            )
            evidence_by_ref[ref].append(parameter_id)
    return {ref: sorted(set(ids)) for ref, ids in evidence_by_ref.items()}


def _merge_passive_synthesis_evidence(ledger: EvidenceLedger, component: Any, evidence_ids: list[str]) -> None:
    """Merge producer-retained passive records without recreating provenance."""
    records = list(getattr(component, "passive_synthesis_evidence", ()) or ())
    for record in records:
        if not isinstance(record, EvidenceRecord):
            raise TypeError("passive_synthesis_evidence must contain EvidenceRecord values")
        ledger.add(record)
    known = {record.id for record in records}
    evidence_ids.extend(sorted(known))
    calculations = list(getattr(component, "passive_synthesis_calculations", ()) or ())
    for calculation in calculations:
        emitted = getattr(calculation, "emits_evidence", None)
        if emitted is not None and emitted not in known:
            raise ValueError("passive synthesis calculation has dangling emitted evidence")
        if any(item.evidence_id and item.evidence_id not in known for item in getattr(calculation, "inputs", ())):
            raise ValueError("passive synthesis calculation has dangling input evidence")
        if emitted:
            evidence_ids.append(emitted)
    calculation_ids = {getattr(item, "id", None) for item in calculations}
    for finding in getattr(component, "passive_synthesis_findings", ()) or ():
        if getattr(finding, "calculation_id", None) not in calculation_ids:
            raise ValueError("passive synthesis finding has dangling calculation")
        if any(item not in known for item in getattr(finding, "evidence_ids", ())):
            raise ValueError("passive synthesis finding has dangling evidence")


def collect_power_domain_evidence(
    ledger: EvidenceLedger,
    power_domains: Iterable[Any],
) -> dict[str, list[str]]:
    """Record user-declared rail envelopes with sparse, resolvable provenance."""

    evidence_by_net: dict[str, list[str]] = {}
    for domain in power_domains or ():

        def _value(name: str) -> Any:
            return domain.get(name) if isinstance(domain, Mapping) else getattr(domain, name, None)

        net = str(_value("net") or "").strip()
        if not net or any(character.isspace() for character in net):
            continue
        facts: list[str] = []
        for field_name, label, unit in (
            ("v_min", "minimum voltage", "V"),
            ("v_nominal", "nominal voltage", "V"),
            ("v_max", "maximum voltage", "V"),
            ("i_steady_ma", "steady current", "mA"),
            ("i_peak_ma", "peak current", "mA"),
        ):
            value = _value(field_name)
            if value is not None:
                facts.append(f"{label}={value} {unit}")
        for field_name, label in (
            ("direction", "direction"),
            ("sequence_order", "sequence order"),
            ("sequence_dependency", "sequence dependency"),
            ("tolerance", "tolerance"),
        ):
            value = _value(field_name)
            if value is not None and value != "":
                facts.append(f"{label}={value}")
        if not facts:
            continue
        declared_provenance = str(_value("evidence_id") or "").strip()
        evidence_value = ledger.record(
            subject_ref=f"net:{net}",
            claim=f"declared power envelope for {net}: " + ", ".join(facts),
            kind="user",
            source=EvidenceSource(
                doc_id=declared_provenance or None,
                extraction_method="design-power-domain",
            ),
            confidence="single_source",
            freshness="unknown",
        )
        evidence_by_net.setdefault(net, []).append(evidence_value)
    return {net: sorted(set(ids)) for net, ids in evidence_by_net.items()}


def collect_validation_evidence(
    ledger: EvidenceLedger,
    report: Any,
    evidence_by_ref: Mapping[str, Iterable[str]] | None = None,
) -> list[str]:
    """Attach stable ledger IDs to each emitted validator finding."""

    from .benchmark_runner import RULE_ID_BY_VALIDATOR_CODE

    collected: list[str] = []
    source = EvidenceSource(doc_id="circuit-weaver-validator", extraction_method="validation")
    for messages in getattr(report, "categories", {}).values():
        for message in messages:
            code = str(getattr(message, "code", "") or "unknown")
            subject = str(getattr(message, "subject", "") or "design")
            rule_id = getattr(message, "rule_id", None) or RULE_ID_BY_VALIDATOR_CODE.get(code)
            if rule_id and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", subject):
                subject_ref = f"calc:{rule_id}@{subject}"
            else:
                subject_ref = "tool:circuit-weaver-validator"
            calculation_value = getattr(message, "calculation", None)
            calculation_inputs = calculation_value.get("inputs", {}) if isinstance(calculation_value, Mapping) else {}
            rail = calculation_inputs.get("rail") if isinstance(calculation_inputs, Mapping) else None
            evidence_subjects = [subject]
            if isinstance(rail, str) and rail and rail != subject:
                evidence_subjects.append(rail)
            subject_evidence: list[str] = []
            for evidence_subject in evidence_subjects:
                for candidate_id in (evidence_by_ref or {}).get(evidence_subject, ()):
                    record = ledger.get(str(candidate_id))
                    if record is None:
                        continue
                    if (
                        getattr(message, "is_validator_finding", False)
                        or record.subject_ref == f"net:{evidence_subject}"
                        or record.subject_ref.startswith(f"param:{evidence_subject}.power.")
                    ):
                        subject_evidence.append(str(candidate_id))
            message.evidence_ids[:] = sorted(
                {
                    str(candidate_id)
                    for candidate_id in (*getattr(message, "evidence_ids", ()), *subject_evidence)
                    if ledger.get(str(candidate_id)) is not None
                }
            )
            calculation = calculation_value
            is_calculation = rule_id is not None and isinstance(calculation, Mapping)
            if is_calculation:
                calculation = dict(calculation)
                calculation["provenance_ids"] = list(message.evidence_ids)
                getattr(message, "calculation").clear()
                getattr(message, "calculation").update(calculation)
                calculation_payload = json.dumps(calculation, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
                claim = f"{rule_id}:{code}:calculation={calculation_payload}"
                kind = "calculation"
            else:
                claim = (
                    f"{getattr(message, 'category', '')}:{code}:{getattr(message, 'level', '')}:"
                    f"{subject}:message_sha256="
                    f"{hashlib.sha256(str(getattr(message, 'message', '')).encode('utf-8')).hexdigest()}"
                )
                kind = "tool_result"
            evidence_value = ledger.record(
                subject_ref=subject_ref,
                claim=claim,
                kind=kind,
                source=EvidenceSource(**{**asdict(source), "extraction_method": code}),
                confidence="single_source",
                freshness="current",
            )
            if evidence_value not in message.evidence_ids:
                message.evidence_ids.append(evidence_value)
            collected.append(evidence_value)
    report.evidence_ids = sorted(set(getattr(report, "evidence_ids", ())) | set(collected))
    return sorted(set(collected))


def build_validation_evidence(
    components: Iterable[Any],
    report: Any,
    power_domains: Iterable[Any] = (),
) -> tuple[EvidenceLedger, dict[str, list[str]]]:
    """Build the validation-time evidence ledger without inventing absent facts."""

    ledger = EvidenceLedger()
    evidence_by_ref = collect_component_evidence(ledger, components)
    for net, evidence_ids in collect_power_domain_evidence(ledger, power_domains).items():
        evidence_by_ref.setdefault(net, []).extend(evidence_ids)
    collect_validation_evidence(ledger, report, evidence_by_ref)
    from . import __version__

    tool_id = ledger.record(
        subject_ref="tool:circuit-weaver",
        claim=f"Circuit Weaver version is {__version__}",
        kind="tool_result",
        source=EvidenceSource(doc_id="circuit-weaver", extraction_method="package-version"),
        confidence="verified",
        freshness="current",
    )
    manifest_ids = {str(record["id"]) for record in ledger.to_manifest()["records"]}
    report.evidence_ids = sorted(set(report.evidence_ids) | manifest_ids | {tool_id})
    return ledger, evidence_by_ref
