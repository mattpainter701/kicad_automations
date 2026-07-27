"""Safety and trust policy shared by future evidence-manifest builders.

The policy is intentionally independent of an evidence collector: callers may
validate an in-progress record before storing it, then apply the same
fabrication-critical trust gate to a ledger's serialized records.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

EVIDENCE_ID_PATTERN = re.compile(r"EV-[A-Z_]+-[0-9a-f]{12}$", re.IGNORECASE)
CONFIDENCE_LADDER = ("stub", "heuristic", "single_source", "corroborated", "verified")
_CONFIDENCE_RANK = {value: index for index, value in enumerate(CONFIDENCE_LADDER)}
_SECRET_PATTERN = re.compile(
    r"(?:\b(?:api[_-]?key|token|secret|password|client[_-]?secret|authorization)\b\s*[=:]|\bbearer\s+|\bAKIA[0-9A-Z]{16}\b|\bsk-[A-Za-z0-9_-]{16,})",
    re.IGNORECASE,
)
# These patterns deliberately search rather than match: evidence claims and
# subject strings frequently prefix a path with useful context (for example,
# ``footprint:C:\\Users\\...``).  HTTP(S) URL spans are stripped only before
# POSIX-slash scanning so their ordinary slash-delimited paths do not become
# local-path false positives.  Windows/UNC/home patterns are still checked on
# the original value because they can leak inside a URL query or fragment.
_HTTP_URL = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_FILE_URL = re.compile(r"file://", re.IGNORECASE)
_WINDOWS_ABSOLUTE = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/]+")
_UNC_ABSOLUTE = re.compile(r"(?<![A-Za-z0-9_])[\\]{2,}")
_HOME_ABSOLUTE = re.compile(r"~[\\/]+")
_POSIX_ABSOLUTE = re.compile(r"(?<![A-Za-z0-9_.-])/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*")


class EvidencePolicyError(ValueError):
    """A record is unsafe, malformed, or insufficiently trustworthy."""


def validate_evidence_safety(record: Mapping[str, Any], *, known_ids: Iterable[str] = ()) -> None:
    """Reject secrets, local absolute paths, and malformed evidence links.

    ``known_ids`` contains IDs already stored in the ledger. Conflict and
    supersession references must resolve there before a record is admitted.
    """

    _reject_sensitive_values(record)
    record_id = record.get("id")
    if not isinstance(record_id, str) or not EVIDENCE_ID_PATTERN.fullmatch(record_id):
        raise EvidencePolicyError("evidence record has an invalid id")
    conflicts = record.get("conflicts", [])
    if not isinstance(conflicts, list) or any(not isinstance(item, str) for item in conflicts):
        raise EvidencePolicyError("evidence conflicts must be a list of evidence IDs")
    if len(conflicts) != len(set(conflicts)) or record_id in conflicts:
        raise EvidencePolicyError("evidence conflicts must be unique and cannot self-reference")
    supersedes = record.get("supersedes")
    if supersedes is not None and not isinstance(supersedes, str):
        raise EvidencePolicyError("evidence supersedes must be an evidence ID or null")
    if supersedes == record_id:
        raise EvidencePolicyError("evidence supersedes cannot self-reference")
    links = [*conflicts, *([supersedes] if supersedes else [])]
    for link in links:
        if not EVIDENCE_ID_PATTERN.fullmatch(link):
            raise EvidencePolicyError(f"malformed evidence link: {link!r}")
    known = set(known_ids)
    if any(link not in known for link in links):
        raise EvidencePolicyError("evidence links must reference existing records")


def is_fabrication_critical_subject(subject_ref: str) -> bool:
    """Return whether an evidence subject belongs to the fail-closed set."""

    return (
        subject_ref.startswith(("comp:", "pin:", "footprint:"))
        or subject_ref.startswith("param:")
        and ".power." in subject_ref
        or subject_ref.startswith("calc:CW-")
        or subject_ref.startswith("tool:")
        and any(term in subject_ref.lower() for term in ("drc", "route"))
    )


def validate_output_relative_evidence_manifest(reference: str) -> str:
    """Return a safe output-relative evidence-manifest reference or raise.

    Empty is the backward-compatible no-evidence default. A manifest reference
    is data intended for an output directory, never a local source path.
    """

    if not isinstance(reference, str):
        raise EvidencePolicyError("evidence_manifest must be a string")
    if not reference:
        return ""
    if _is_machine_absolute_path(reference) or ".." in Path(reference).parts:
        raise EvidencePolicyError("evidence_manifest must be output-relative")
    return reference.replace("\\", "/")


def require_backing(
    subject_ref: str,
    records: Iterable[Mapping[str, Any]],
    *,
    min_confidence: str = "single_source",
    acknowledged_heuristic_ids: Iterable[str] = (),
) -> Mapping[str, Any]:
    """Return acceptable backing evidence or fail closed for a critical subject.

    A stub never supports fabrication readiness. A heuristic supports it only
    when its exact ID is explicitly acknowledged by the caller. Any unresolved
    conflict for the subject is a hard failure, even if another record appears
    stronger. The chosen record must meet the requested confidence floor.
    """

    if min_confidence not in _CONFIDENCE_RANK:
        raise EvidencePolicyError(f"unknown minimum confidence: {min_confidence!r}")
    materialized = list(records)
    superseded_ids = {
        str(record["supersedes"])
        for record in materialized
        if isinstance(record.get("supersedes"), str)
    }
    subject_records = [
        record
        for record in materialized
        if record.get("subject_ref") == subject_ref and record.get("id") not in superseded_ids
    ]
    if not subject_records:
        raise EvidencePolicyError(f"no evidence backs fabrication-critical subject {subject_ref!r}")
    if any(record.get("conflicts") for record in subject_records):
        raise EvidencePolicyError(f"unresolved evidence conflicts for {subject_ref!r}")

    acknowledged = set(acknowledged_heuristic_ids)
    accepted: list[Mapping[str, Any]] = []
    for record in subject_records:
        kind = record.get("kind")
        confidence = record.get("confidence")
        record_id = record.get("id")
        if confidence == "conflicting" or kind == "stub":
            continue
        if kind == "heuristic" and record_id not in acknowledged:
            continue
        if confidence not in _CONFIDENCE_RANK:
            continue
        if _CONFIDENCE_RANK[confidence] >= _CONFIDENCE_RANK[min_confidence]:
            accepted.append(record)
    if not accepted:
        raise EvidencePolicyError(f"insufficient trustworthy evidence for {subject_ref!r}")
    return max(accepted, key=lambda record: _CONFIDENCE_RANK[record["confidence"]])


def require_fabrication_evidence(
    records: Iterable[Mapping[str, Any]],
    *,
    acknowledged_heuristic_ids: Iterable[str] = (),
) -> dict[str, Mapping[str, Any]]:
    """Fail closed unless every represented critical subject has real backing."""

    materialized = list(records)
    critical_subjects = sorted(
        {
            str(record.get("subject_ref"))
            for record in materialized
            if is_fabrication_critical_subject(str(record.get("subject_ref", "")))
        }
    )
    if not critical_subjects:
        raise EvidencePolicyError("fabrication readiness requires critical-subject evidence")
    return {
        subject: require_backing(
            subject,
            materialized,
            acknowledged_heuristic_ids=acknowledged_heuristic_ids,
        )
        for subject in critical_subjects
    }


def _reject_sensitive_values(value: Any) -> None:
    if isinstance(value, Mapping):
        for nested in (*value.keys(), *value.values()):
            _reject_sensitive_values(nested)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for nested in value:
            _reject_sensitive_values(nested)
    elif isinstance(value, str):
        validate_evidence_text(value)


def validate_evidence_text(value: str) -> None:
    """Reject one unsafe evidence string using the shared leak detector."""

    if _SECRET_PATTERN.search(value) or _contains_http_userinfo(value):
        raise EvidencePolicyError("evidence records must not contain credentials or secrets")
    if contains_machine_absolute_path(value):
        raise EvidencePolicyError("evidence records must not contain machine-local absolute paths")


def contains_machine_absolute_path(value: str) -> bool:
    """Return whether text contains a machine-local absolute path or file URL."""

    if any(pattern.search(value) for pattern in (_FILE_URL, _WINDOWS_ABSOLUTE, _UNC_ABSOLUTE, _HOME_ABSOLUTE)):
        return True
    remote_urls_removed = _HTTP_URL.sub("", value)
    return bool(_POSIX_ABSOLUTE.search(remote_urls_removed))


def _contains_http_userinfo(value: str) -> bool:
    return any(urlparse(match.group()).username is not None for match in _HTTP_URL.finditer(value))


def _is_machine_absolute_path(value: str) -> bool:
    """Backward-compatible private wrapper for output-relative validation."""

    return contains_machine_absolute_path(value)
