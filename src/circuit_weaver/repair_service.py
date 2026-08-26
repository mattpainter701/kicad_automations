"""Safe, bounded repairs for imported KiCad schematics.

The first supported repair is insertion of one explicit ``no_connect`` marker.
Plans are deliberately data-only and carry the source/object hashes needed to
reject stale or tampered approvals at apply time.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import stat
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from . import __version__
from .evidence import EvidenceLedger
from .evidence_policy import EVIDENCE_ID_PATTERN
from .finding_model import (
    FindingLocation,
    FindingObservation,
    RemediationOption,
    UnifiedFinding,
    finding_from_dict,
)
from .layout_quality import analyze_schematic_file
from .parser import (
    ParsedSchematic,
    _extract_blocks,
    _find_matching_close,
    _remove_lib_symbols_section,
    parse_schematic,
)


class RepairRejected(ValueError):
    """A repair was not safe to suggest, preview, or apply."""


_FINDING_RE = re.compile(r"^FND-[0-9a-f]{12}$")
REPAIR_METADATA_SCHEMA_VERSION = "circuit-weaver-repair-metadata/v1"
_NO_CONNECT_CLAIM = "Pin {ref}.{pin} is intentionally unused and should be marked no-connect."


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _source(path: Path) -> tuple[bytes, str]:
    data = path.read_bytes()
    return data, _sha256_bytes(data)


def _resolved(path: str | Path) -> Path:
    return Path(path).resolve()


def _paths_alias(first: str | Path, second: str | Path) -> bool:
    """Return whether paths resolve to the same target, including hardlinks."""

    left = _resolved(first)
    right = _resolved(second)
    if os.path.normcase(str(left)) == os.path.normcase(str(right)):
        return True
    if left.exists() and right.exists():
        try:
            return os.path.samefile(left, right)
        except OSError:
            return False
    return False


def _is_reparse_path(path: Path) -> bool:
    """Return whether an existing path is a symlink or Windows reparse point."""

    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(metadata.st_mode):
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(getattr(metadata, "st_file_attributes", 0) & reparse_flag)


def _open_validated_lock(lock_path: Path, *, purpose: str):
    """Open a single-link regular lock file without mutating aliases."""

    flags = os.O_RDWR | getattr(os, "O_BINARY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock_path, flags | nofollow | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        try:
            descriptor = os.open(lock_path, flags | nofollow)
        except OSError as exc:
            raise RepairRejected(f"{purpose} lock file cannot be opened safely") from exc
    except OSError as exc:
        raise RepairRejected(f"{purpose} lock file cannot be created safely") from exc

    handle = os.fdopen(descriptor, "r+b")
    try:
        opened = os.fstat(handle.fileno())
        named = os.lstat(lock_path)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or opened.st_nlink != 1
            or named.st_nlink != 1
            or not os.path.samestat(opened, named)
            or stat.S_ISLNK(named.st_mode)
            or bool(getattr(named, "st_file_attributes", 0) & reparse_flag)
        ):
            raise RepairRejected(f"{purpose} lock file must be an unaliased regular file")
    except Exception:
        handle.close()
        raise
    return handle


@contextmanager
def _exclusive_file_lock(lock_path: Path, *, purpose: str, blocking: bool = False) -> Iterator[None]:
    """Hold a non-blocking, cross-process lock on one persistent lock file."""

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = _open_validated_lock(lock_path, purpose=purpose)
    acquired = False
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
                msvcrt.locking(handle.fileno(), mode, 1)
            else:
                import fcntl

                mode = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
                fcntl.flock(handle.fileno(), mode)
        except OSError as exc:
            raise RepairRejected(f"{purpose} is locked by another repair process") from exc
        acquired = True
        named = os.lstat(lock_path)
        opened = os.fstat(handle.fileno())
        if named.st_nlink != 1 or opened.st_nlink != 1 or not os.path.samestat(named, opened):
            raise RepairRejected(f"{purpose} lock file changed while it was acquired")
        yield
    finally:
        if acquired:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _source_lock_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.circuit-weaver.lock")


def _validate_single_root(content: bytes) -> str:
    """Require exactly one complete ``kicad_sch`` root and no trailing data."""

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RepairRejected("schematic must be UTF-8") from exc
    start = len(text) - len(text.lstrip())
    if not re.match(r"\(kicad_sch(?=\s|\))", text[start:]):
        raise RepairRejected("schematic must contain one kicad_sch root")
    close = _find_matching_close(text, start)
    if close < 0 or text[close + 1 :].strip():
        raise RepairRejected("schematic has malformed or trailing root content")
    return text


def _semantic_counts(parsed: ParsedSchematic) -> dict[str, int]:
    """Return the bounded structure this operation is allowed to change."""

    return {
        "components": len(parsed.components),
        "wires": len(parsed.wires),
        "labels": len(parsed.global_labels) + len(parsed.hierarchical_labels),
        "no_connects": len(parsed.no_connects),
    }


def _normalized_evidence_ids(evidence_ids: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    values = tuple(evidence_ids)
    if not values or any(not isinstance(item, str) or not EVIDENCE_ID_PATTERN.fullmatch(item) for item in values):
        raise RepairRejected("evidence_ids must contain valid EV-<KIND>-<12hex> identifiers")
    return tuple(sorted(set(values)))


def _metadata_integrity(payload: Mapping[str, Any]) -> str:
    content = dict(payload)
    content.pop("content_integrity", None)
    return _sha256_bytes(_canonical(content).encode("utf-8"))


def no_connect_finding_from_intent(
    schematic: str | Path,
    analysis: Mapping[str, Any],
    evidence_manifest: Mapping[str, Any],
    *,
    ref: str,
    pin: str,
) -> UnifiedFinding:
    """Produce the supported low-risk finding from exact reviewed intent.

    This is the trusted producer for the first repair slice.  It accepts the
    production analyzer component/pin shape, but re-proves identity and
    connectivity against the raw schematic before emitting a repairable
    finding.
    """

    path = _resolved(schematic)
    content, source_hash = _source(path)
    text = _validate_single_root(content)
    parsed = parse_schematic(path)
    component, pin_data = _pin_metadata(dict(analysis), ref, str(pin))
    identity = _component_identity(parsed, ref, component)
    x, y = _coordinates(pin_data)
    _prove_pin(text, ref, identity, str(pin), pin_data, x, y)
    if pin_data.get("net") not in (None, "", False) or pin_data.get("net_name") not in (None, "", False):
        raise RepairRejected(f"{ref}.{pin} already has a net")
    if _wire_touches(parsed, x, y) or _label_touches(text, x, y):
        raise RepairRejected(f"{ref}.{pin} is connected by a wire or label")
    _prove_no_implicit_connection(
        text,
        target_uuid=identity["uuid"],
        target_pin=str(pin),
        x=x,
        y=y,
    )
    if any(_near(item.x, x) and _near(item.y, y) for item in parsed.no_connects):
        raise RepairRejected(f"{ref}.{pin} already has an explicit no-connect marker")
    try:
        records = EvidenceLedger.from_manifest(evidence_manifest).to_manifest()["records"]
    except (TypeError, ValueError) as exc:
        raise RepairRejected(f"invalid repair evidence manifest: {exc}") from exc
    expected_claim = _NO_CONNECT_CLAIM.format(ref=ref, pin=pin)
    evidence_ids = tuple(
        sorted(
            record["id"]
            for record in records
            if record.get("subject_ref") == f"pin:{ref}.{pin}"
            and record.get("claim") == expected_claim
            and record.get("kind") == "user"
            and record.get("confidence") == "verified"
            and record.get("freshness") == "current"
            and not record.get("conflicts")
        )
    )
    if not evidence_ids:
        raise RepairRejected("no current verified user evidence proves the exact no-connect intent")
    location = FindingLocation(
        artifact_kind="schematic",
        artifact_path=path.name,
        object_type="pin",
        object_id=f"{ref}.{pin}",
        ref=ref,
        x_mm=x,
        y_mm=y,
    )
    message = f"{ref}.{pin} is intentionally unused and needs an explicit no-connect marker."
    finding = UnifiedFinding(
        rule_id="CW-ERC-001",
        root_cause_key=f"explicit-no-connect:{identity['uuid']}:{pin}",
        message=message,
        severity="major",
        detection_confidence="verified",
        location=location,
        observations=(
            FindingObservation(
                source="repair.intent",
                source_finding_id=evidence_ids[0],
                message=message,
                severity="major",
                detection_confidence="verified",
                location=location,
                evidence_ids=evidence_ids,
                observed_value="reviewed intentionally-unused pin intent",
            ),
        ),
        evidence_ids=evidence_ids,
        remediation_options=(
            RemediationOption(
                id="REM-explicit-no-connect",
                summary=f"Insert one explicit no-connect marker at {ref}.{pin}.",
                kind="repair_plan",
                risk="low",
                supported=True,
            ),
        ),
    )
    try:
        analyze_schematic_file(path)
    except Exception as exc:
        raise RepairRejected(f"schematic analyzer rejected source: {exc}") from exc
    if _sha256_bytes(path.read_bytes()) != source_hash:
        raise RepairRejected("source changed while producing repair intent")
    return finding


def build_no_connect_metadata(
    schematic: str | Path,
    analysis: Mapping[str, Any],
    finding: UnifiedFinding | Mapping[str, Any],
    evidence_manifest: Mapping[str, Any],
    *,
    ref: str,
    pin: str,
) -> dict[str, Any]:
    """Bind validated analyzer, finding, evidence, and user-intent artifacts.

    The evidence manifest must contain current, verified user evidence with the
    exact claim that ``ref.pin`` is intentionally unused.  The returned v1
    envelope is content-addressed and bound to the exact source bytes.
    """

    path = _resolved(schematic)
    source, source_hash = _source(path)
    _validate_single_root(source)
    normalized_finding = finding if isinstance(finding, UnifiedFinding) else finding_from_dict(dict(finding))
    try:
        ledger = EvidenceLedger.from_manifest(evidence_manifest)
    except (TypeError, ValueError) as exc:
        raise RepairRejected(f"invalid repair evidence manifest: {exc}") from exc
    envelope: dict[str, Any] = {
        "schema_version": REPAIR_METADATA_SCHEMA_VERSION,
        "source": str(path),
        "source_sha256": source_hash,
        "analysis": json.loads(_canonical(dict(analysis))),
        "finding": normalized_finding.to_dict(),
        "evidence_manifest": ledger.to_manifest(),
        "assertion": {
            "kind": "explicit_no_connect",
            "ref": ref,
            "pin": str(pin),
            "intentionally_unused": True,
        },
    }
    envelope["content_integrity"] = _metadata_integrity(envelope)
    _validate_repair_metadata(
        path,
        envelope,
        ref=ref,
        pin=str(pin),
        finding_id=normalized_finding.id,
        evidence_ids=normalized_finding.evidence_ids,
    )
    return envelope


def _validate_repair_metadata(
    path: Path,
    metadata: Mapping[str, Any],
    *,
    ref: str,
    pin: str,
    finding_id: str,
    evidence_ids: tuple[str, ...],
) -> tuple[dict[str, Any], dict[str, Any]]:
    expected_keys = {
        "schema_version",
        "source",
        "source_sha256",
        "analysis",
        "finding",
        "evidence_manifest",
        "assertion",
        "content_integrity",
    }
    if set(metadata) != expected_keys or metadata.get("schema_version") != REPAIR_METADATA_SCHEMA_VERSION:
        raise RepairRejected("repair metadata must use the exact versioned v1 envelope")
    integrity = metadata.get("content_integrity")
    if not isinstance(integrity, str) or integrity != _metadata_integrity(metadata):
        raise RepairRejected("repair metadata content_integrity mismatch")
    try:
        metadata_source = _resolved(str(metadata.get("source", "")))
    except (OSError, ValueError) as exc:
        raise RepairRejected("repair metadata source is invalid") from exc
    if metadata_source != path or metadata.get("source_sha256") != _sha256_bytes(path.read_bytes()):
        raise RepairRejected("repair metadata is not bound to the exact source bytes")

    raw_finding = metadata.get("finding")
    if not isinstance(raw_finding, Mapping):
        raise RepairRejected("repair metadata finding is malformed")
    try:
        finding = finding_from_dict(dict(raw_finding))
    except (TypeError, ValueError) as exc:
        raise RepairRejected(f"repair metadata finding is invalid: {exc}") from exc
    if finding.id != finding_id or finding.suppressed:
        raise RepairRejected("repair finding identity is mismatched or suppressed")
    if tuple(finding.evidence_ids) != evidence_ids or not evidence_ids:
        raise RepairRejected("repair finding must carry the exact approval evidence IDs")
    if not any(
        option.kind == "repair_plan" and option.risk == "low" and option.supported
        for option in finding.remediation_options
    ):
        raise RepairRejected("repair finding has no supported low-risk repair-plan remediation")
    location = finding.location
    if (
        location.artifact_kind != "schematic"
        or location.object_type != "pin"
        or location.object_id != f"{ref}.{pin}"
        or location.ref != ref
        or location.x_mm is None
        or location.y_mm is None
    ):
        raise RepairRejected("repair finding does not identify the exact schematic pin")

    raw_manifest = metadata.get("evidence_manifest")
    if not isinstance(raw_manifest, Mapping):
        raise RepairRejected("repair evidence manifest is malformed")
    try:
        records = EvidenceLedger.from_manifest(raw_manifest).to_manifest()["records"]
    except (TypeError, ValueError) as exc:
        raise RepairRejected(f"repair evidence manifest is invalid: {exc}") from exc
    by_id = {record["id"]: record for record in records}
    if any(evidence_id not in by_id for evidence_id in evidence_ids):
        raise RepairRejected("repair evidence IDs do not resolve in the evidence manifest")
    expected_claim = _NO_CONNECT_CLAIM.format(ref=ref, pin=pin)
    approval_records = [
        by_id[evidence_id]
        for evidence_id in evidence_ids
        if by_id[evidence_id].get("subject_ref") == f"pin:{ref}.{pin}"
        and by_id[evidence_id].get("claim") == expected_claim
        and by_id[evidence_id].get("kind") == "user"
        and by_id[evidence_id].get("confidence") == "verified"
        and by_id[evidence_id].get("freshness") == "current"
        and not by_id[evidence_id].get("conflicts")
    ]
    if not approval_records:
        raise RepairRejected("repair requires current verified user evidence for the exact no-connect intent")

    assertion = metadata.get("assertion")
    if not isinstance(assertion, Mapping) or dict(assertion) != {
        "kind": "explicit_no_connect",
        "ref": ref,
        "pin": pin,
        "intentionally_unused": True,
    }:
        raise RepairRejected("repair metadata has no exact intentionally-unused assertion")
    analysis = metadata.get("analysis")
    if not isinstance(analysis, Mapping):
        raise RepairRejected("repair metadata analysis is malformed")
    component, pin_data = _pin_metadata(dict(analysis), ref, pin)
    x, y = _coordinates(pin_data)
    if not (_near(x, location.x_mm) and _near(y, location.y_mm)):
        raise RepairRejected("repair finding coordinates do not match analyzed pin geometry")
    return component, pin_data


def _marker_present(parsed: ParsedSchematic, operation: dict[str, Any]) -> bool:
    try:
        x = float(operation["x"])
        y = float(operation["y"])
        marker_uuid = str(operation["uuid"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RepairRejected("repair operation has invalid no-connect geometry") from exc
    return any(item.uuid == marker_uuid and _near(item.x, x) and _near(item.y, y) for item in parsed.no_connects)


def _pin_metadata(metadata: dict[str, Any], ref: str, pin: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve a normalized metadata component and exact pin entry.

    The production analyzer's ``reference`` plus pin-list shape is accepted,
    along with the older normalized ``ref`` plus pin-map shape.
    """
    components = metadata.get("components") or metadata.get("normalized_components")
    if isinstance(components, dict):
        component = components.get(ref)
    elif isinstance(components, list):
        matches = [
            item
            for item in components
            if isinstance(item, dict) and str(item.get("ref", item.get("reference", ""))) == ref
        ]
        if len(matches) != 1:
            raise RepairRejected(f"component identity is not unique: {ref}")
        component = matches[0]
    else:
        component = None
    if not isinstance(component, dict):
        raise RepairRejected(f"component {ref!r} is absent from normalized metadata")
    pins = component.get("pins")
    if isinstance(pins, list):
        pin_matches = [item for item in pins if isinstance(item, dict) and str(item.get("number", "")) == pin]
        if len(pin_matches) != 1:
            raise RepairRejected(f"pin {ref}.{pin} is not unique in normalized metadata")
        pin_data = pin_matches[0]
    elif isinstance(pins, dict):
        pin_data = pins.get(pin)
        if pin_data is None:
            pin_data = pins.get(str(pin))
    else:
        raise RepairRejected(f"component {ref!r} has no normalized pin metadata")
    if not isinstance(pin_data, dict):
        raise RepairRejected(f"pin {ref}.{pin} is absent from normalized metadata")
    return component, pin_data


def _component_identity(parsed: ParsedSchematic, ref: str, component: dict[str, Any]) -> dict[str, Any]:
    matches = [item for item in parsed.components if item.ref == ref]
    if len(matches) != 1:
        raise RepairRejected(f"schematic component identity is not unique: {ref}")
    actual = matches[0]
    expected_uuid = str(component.get("uuid", "")).strip()
    expected_lib_id = str(component.get("lib_id", "")).strip()
    if not expected_uuid:
        raise RepairRejected(f"component UUID is mandatory for {ref}")
    if actual.uuid != expected_uuid:
        raise RepairRejected(f"stale component identity for {ref}")
    if not expected_lib_id or actual.lib_id != expected_lib_id:
        raise RepairRejected(f"component library identity mismatch for {ref}")
    return {"ref": ref, "uuid": actual.uuid, "lib_id": actual.lib_id, "unit": actual.unit}


def _coordinates(pin_data: dict[str, Any]) -> tuple[float, float]:
    at = pin_data.get("at") or pin_data.get("position")
    if isinstance(at, (list, tuple)) and len(at) == 2:
        return float(at[0]), float(at[1])
    if isinstance(at, dict) and "x" in at and "y" in at:
        return float(at["x"]), float(at["y"])
    if "x" in pin_data and "y" in pin_data:
        return float(pin_data["x"]), float(pin_data["y"])
    raise RepairRejected("pin metadata must provide exact schematic x/y coordinates")


def _at(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _near(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-5


def _wire_touches(parsed: ParsedSchematic, x: float, y: float) -> bool:
    for wire in parsed.wires:
        dx = wire.x2 - wire.x1
        dy = wire.y2 - wire.y1
        cross = (x - wire.x1) * dy - (y - wire.y1) * dx
        scale = max(1.0, abs(dx), abs(dy))
        within_x = min(wire.x1, wire.x2) - 1e-5 <= x <= max(wire.x1, wire.x2) + 1e-5
        within_y = min(wire.y1, wire.y2) - 1e-5 <= y <= max(wire.y1, wire.y2) + 1e-5
        if abs(cross) <= 1e-5 * scale and within_x and within_y:
            return True
    return False


def _label_touches(content: str, x: float, y: float) -> bool:
    """Reject local/global/hierarchical labels at the candidate coordinate."""
    for keyword in ("label", "global_label", "hierarchical_label"):
        for block in _extract_blocks(content, keyword):
            match = re.search(r"\(at\s+([-\d.]+)\s+([-\d.]+)(?:\s+[-\d.]+)?\)", block)
            if match and _near(float(match.group(1)), x) and _near(float(match.group(2)), y):
                return True
    return False


def _prove_pin(
    content: str,
    ref: str,
    component: dict[str, Any],
    pin: str,
    pin_data: dict[str, Any],
    x: float,
    y: float,
) -> None:
    """Resolve the exact embedded library pin and its placed coordinate."""
    expected_uuid = str(component.get("uuid", "")).strip()
    if not expected_uuid:
        raise RepairRejected("component UUID is mandatory")
    libs = _extract_blocks(content, "symbol")
    lib_id = str(component.get("lib_id", "")).strip()
    placed = [
        block
        for block in _extract_blocks(_remove_lib_symbols_section(content), "symbol")
        if re.search(rf'\(lib_id\s+"{re.escape(lib_id)}"\)', block)
        and re.search(rf'\(property\s+"Reference"\s+"{re.escape(ref)}"', block)
        and re.search(rf'\(uuid\s+"{re.escape(expected_uuid)}"\)', block)
    ]
    if len(placed) != 1:
        raise RepairRejected(f"raw placed symbol identity is not unique: {ref}")
    placed_at = re.search(
        r'\(symbol\s+\(lib_id\s+"[^"]+"\)\s+\(at\s+([\-\d.]+)\s+([\-\d.]+)(?:\s+([\-\d.]+))?', placed[0]
    )
    if not placed_at:
        raise RepairRejected("placed symbol has no position")
    px, py, rotation = float(placed_at.group(1)), float(placed_at.group(2)), float(placed_at.group(3) or 0)
    if abs(rotation) > 1e-6:
        raise RepairRejected("rotated symbols are outside the bounded repair slice")
    if re.search(r"\(mirror\s+", placed[0]):
        raise RepairRejected("mirrored symbols are outside the bounded repair slice")
    library = [block for block in libs if re.search(rf'^\(symbol\s+"{re.escape(lib_id)}"(?:\s|\()', block)]
    if len(library) != 1:
        raise RepairRejected(f"embedded library symbol is not unique: {lib_id}")
    pins = [
        block
        for block in _extract_blocks(library[0], "pin")
        if re.search(rf'\(number\s+"{re.escape(str(pin))}"', block)
    ]
    if len(pins) != 1:
        raise RepairRejected(f"embedded library pin is not unique: {lib_id}.{pin}")
    pin_at = re.search(r"\(at\s+([\-\d.]+)\s+([\-\d.]+)", pins[0])
    if not pin_at:
        raise RepairRejected("library pin has no position")
    computed = (px + float(pin_at.group(1)), py - float(pin_at.group(2)))
    if not (_near(computed[0], x) and _near(computed[1], y)):
        raise RepairRejected(f"pin coordinate does not match embedded library geometry: {computed} != {(x, y)}")
    pin_uuid = str(pin_data.get("pin_uuid", "")).strip()
    if pin_uuid and pin_uuid not in pins[0]:
        raise RepairRejected("pin UUID does not match embedded library pin")


def _library_pins(library: str, unit: int) -> tuple[tuple[str, float, float], ...]:
    """Return pins for one placed unit, including shared unit-zero pins."""

    selected: list[str] = []
    for nested in _extract_blocks(library[1:], "symbol"):
        name_match = re.match(r'^\(symbol\s+"([^"]+)"', nested)
        if not name_match:
            continue
        suffix = re.search(r"_(\d+)_(\d+)$", name_match.group(1))
        if suffix and int(suffix.group(1)) not in {0, unit}:
            continue
        selected.extend(_extract_blocks(nested, "pin"))
    if not selected:
        selected = _extract_blocks(library, "pin")

    pins: set[tuple[str, float, float]] = set()
    for block in selected:
        at_match = re.search(r"\(at\s+([-\d.]+)\s+([-\d.]+)", block)
        if not at_match:
            raise RepairRejected("embedded library pin has no position")
        number_match = re.search(r'\(number\s+"([^"]+)"', block)
        pins.add(
            (
                number_match.group(1) if number_match else "?",
                float(at_match.group(1)),
                float(at_match.group(2)),
            )
        )
    return tuple(sorted(pins))


def _placed_pin_endpoints(content: str) -> tuple[tuple[str, str, str, float, float], ...]:
    libraries: dict[str, str] = {}
    for block in _extract_blocks(content, "symbol"):
        match = re.match(r'^\(symbol\s+"([^"]+)"', block)
        if match:
            libraries[match.group(1)] = block

    endpoints: list[tuple[str, str, str, float, float]] = []
    placed_content = _remove_lib_symbols_section(content)
    for block in _extract_blocks(placed_content, "symbol"):
        placed = re.match(
            r'^\(symbol\s+\(lib_id\s+"([^"]+)"\)\s+\(at\s+([-\d.]+)\s+([-\d.]+)(?:\s+([-\d.]+))?',
            block,
        )
        if not placed:
            raise RepairRejected("placed symbol geometry cannot be proven")
        lib_id = placed.group(1)
        library = libraries.get(lib_id)
        if library is None:
            raise RepairRejected(f"embedded library symbol is missing for {lib_id}")
        px, py = float(placed.group(2)), float(placed.group(3))
        rotation = float(placed.group(4) or 0.0)
        unit_match = re.search(r"\(unit\s+(\d+)\)", block)
        unit = int(unit_match.group(1)) if unit_match else 1
        ref_match = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', block)
        uuid_match = re.search(r'\(uuid\s+"([^"]+)"\)', block)
        ref = ref_match.group(1) if ref_match else lib_id
        symbol_uuid = uuid_match.group(1) if uuid_match else ""
        mirrors = set(re.findall(r"\(mirror\s+([xy])\)", block))
        radians = math.radians(rotation)
        cosine, sine = math.cos(radians), math.sin(radians)
        for number, local_x, local_y in _library_pins(library, unit):
            if "x" in mirrors:
                local_y = -local_y
            if "y" in mirrors:
                local_x = -local_x
            rotated_x = local_x * cosine - local_y * sine
            rotated_y = local_x * sine + local_y * cosine
            endpoints.append((ref, symbol_uuid, number, px + rotated_x, py - rotated_y))
    return tuple(endpoints)


def _prove_no_implicit_connection(
    content: str,
    *,
    target_uuid: str,
    target_pin: str,
    x: float,
    y: float,
) -> None:
    """Reject coincident component/power pins and raw connection primitives."""

    for ref, symbol_uuid, number, pin_x, pin_y in _placed_pin_endpoints(content):
        if symbol_uuid == target_uuid and number == target_pin:
            continue
        if _near(pin_x, x) and _near(pin_y, y):
            raise RepairRejected(f"target pin is implicitly connected to {ref}.{number}")
    for keyword in ("junction", "bus_entry"):
        for block in _extract_blocks(content, keyword):
            at_match = re.search(r"\(at\s+([-\d.]+)\s+([-\d.]+)", block)
            if at_match and _near(float(at_match.group(1)), x) and _near(float(at_match.group(2)), y):
                raise RepairRejected(f"target pin is connected by a {keyword}")
    for sheet in _extract_blocks(content, "sheet"):
        for sheet_pin in _extract_blocks(sheet, "pin"):
            at_match = re.search(r"\(at\s+([-\d.]+)\s+([-\d.]+)", sheet_pin)
            if at_match and _near(float(at_match.group(1)), x) and _near(float(at_match.group(2)), y):
                raise RepairRejected("target pin is connected by a hierarchical sheet pin")


def _object_hash(identity: dict[str, Any], pin: dict[str, Any]) -> str:
    return _sha256_bytes(_canonical({"component": identity, "pin": pin}).encode())


def suggest_no_connect(
    schematic: str | Path,
    metadata: dict[str, Any],
    *,
    ref: str,
    pin: str,
    finding_id: str,
    evidence_ids: tuple[str, ...] | list[str],
) -> dict[str, Any]:
    """Return a safe candidate, or raise ``RepairRejected``."""
    if not isinstance(finding_id, str) or not _FINDING_RE.fullmatch(finding_id):
        raise RepairRejected("finding_id must be FND- followed by 12 lowercase hexadecimal characters")
    normalized_evidence_ids = _normalized_evidence_ids(evidence_ids)
    path = Path(schematic).resolve()
    content, source_hash = _source(path)
    text = _validate_single_root(content)
    parsed = parse_schematic(path)
    component, pin_data = _validate_repair_metadata(
        path,
        metadata,
        ref=ref,
        pin=str(pin),
        finding_id=finding_id,
        evidence_ids=normalized_evidence_ids,
    )
    identity = _component_identity(parsed, ref, component)
    if pin_data.get("net") not in (None, "", False) or pin_data.get("net_name") not in (None, "", False):
        raise RepairRejected(f"{ref}.{pin} already has a net")
    x, y = _coordinates(pin_data)
    _prove_pin(text, ref, identity, str(pin), pin_data, x, y)
    if _wire_touches(parsed, x, y):
        raise RepairRejected(f"{ref}.{pin} is connected by a wire")
    if _label_touches(text, x, y):
        raise RepairRejected(f"{ref}.{pin} is connected by a label")
    _prove_no_implicit_connection(
        text,
        target_uuid=identity["uuid"],
        target_pin=str(pin),
        x=x,
        y=y,
    )
    try:
        analyze_schematic_file(path)
    except Exception as exc:
        raise RepairRejected(f"schematic analyzer rejected source: {exc}") from exc
    if _sha256_bytes(path.read_bytes()) != source_hash:
        raise RepairRejected("source changed during repair preview")
    existing = next((item for item in parsed.no_connects if _near(item.x, x) and _near(item.y, y)), None)
    object_hash = _object_hash(identity, {"pin": str(pin), **pin_data})
    operation = {
        "kind": "insert_no_connect",
        "ref": ref,
        "pin": str(pin),
        "x": x,
        "y": y,
        "uuid": (
            existing.uuid
            if existing is not None
            else str(uuid.uuid5(uuid.NAMESPACE_URL, f"{path}:{ref}:{pin}:{_at(x)}:{_at(y)}"))
        ),
        "object_hash": object_hash,
    }
    pre = _semantic_counts(parsed)
    post = dict(pre)
    if existing is None:
        post["no_connects"] += 1
        post_image = _append_no_connect(content, operation)
    else:
        post_image = content
    plan_body = {
        "version": 1,
        "kind": "no_connect",
        "risk": "low",
        "source": str(path),
        "source_sha256": source_hash,
        "operation": operation,
        "finding_id": finding_id,
        "evidence_ids": list(normalized_evidence_ids),
        "prerequisites": {
            "component_identity": identity,
            "pin_intentionally_unused": True,
            "pin_has_no_net_wire_label_or_implicit_peer": True,
        },
        "affected_objects": [{"ref": ref, "pin": str(pin), "x": x, "y": y}],
        "semantic_pre": pre,
        "semantic_post": post,
        "post_sha256": _sha256_bytes(post_image),
        "expected_postconditions": {
            "explicit_no_connect": True,
            "marker_uuid": operation["uuid"],
            "source_sha256": _sha256_bytes(post_image),
        },
        "rollback": {"strategy": "atomic_restore", "source_sha256": source_hash},
    }
    plan_body["plan_sha256"] = _sha256_bytes(_canonical(plan_body).encode())
    return {**plan_body, "status": "already_applied" if existing is not None else "proposed"}


def preview_no_connect(
    schematic: str | Path,
    metadata: dict[str, Any],
    *,
    ref: str,
    pin: str,
    finding_id: str,
    evidence_ids: tuple[str, ...] | list[str],
) -> dict[str, Any]:
    """Alias for the explicit preview stage."""
    return suggest_no_connect(schematic, metadata, ref=ref, pin=pin, finding_id=finding_id, evidence_ids=evidence_ids)


def _append_no_connect(content: bytes, operation: dict[str, Any]) -> bytes:
    text = _validate_single_root(content)
    marker = (
        f'  (no_connect (at {_at(float(operation["x"]))} {_at(float(operation["y"]))}) (uuid "{operation["uuid"]}"))\n'
    )
    start = len(text) - len(text.lstrip())
    close = _find_matching_close(text, start)
    return (text[:close] + marker + text[close:]).encode("utf-8")


def _audit_lock_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.lock")


def _read_audit_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if not path.is_file():
        raise RepairRejected("repair audit log must be a regular file")
    data = path.read_bytes()
    if data and not data.endswith(b"\n"):
        raise RepairRejected("repair audit log is not valid newline-delimited JSON")
    events: list[dict[str, Any]] = []
    for line in data.splitlines():
        try:
            event = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RepairRejected("repair audit log is not valid newline-delimited JSON") from exc
        if not isinstance(event, dict):
            raise RepairRejected("repair audit log contains a non-object event")
        events.append(event)
    return events


def _append_audit_event(path: Path, record: Mapping[str, Any]) -> None:
    """Atomically extend the logical JSONL log while its lock is held."""

    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_bytes() if path.exists() else b""
    if existing and not existing.endswith(b"\n"):
        raise RepairRejected("repair audit log is not valid newline-delimited JSON")
    updated = existing + (_canonical(dict(record)) + "\n").encode("utf-8")
    with tempfile.NamedTemporaryFile(
        "wb", dir=path.parent, prefix=f".{path.name}.", suffix=".audit-stage", delete=False
    ) as staged:
        staged.write(updated)
        staged.flush()
        os.fsync(staged.fileno())
        staged_path = Path(staged.name)
    try:
        _replace_file_preserving_security(staged_path, path)
    finally:
        staged_path.unlink(missing_ok=True)


def _audit_committed(events: list[dict[str, Any]], plan_hash: str, source: Path) -> bool:
    matching = [
        event
        for event in events
        if event.get("plan_sha256") == plan_hash and event.get("source") == str(source)
    ]
    return bool(matching and matching[-1].get("state") == "committed")


def _windows_security_descriptor(path: Path) -> str:
    """Read owner, group, and DACL metadata for fail-closed Windows checks."""

    import ctypes
    from ctypes import wintypes

    security_information = 0x00000001 | 0x00000002 | 0x00000004
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    get_file_security = advapi32.GetFileSecurityW
    get_file_security.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    get_file_security.restype = wintypes.BOOL
    needed = wintypes.DWORD()
    get_file_security(str(path), security_information, None, 0, ctypes.byref(needed))
    if not needed.value:
        error = ctypes.get_last_error()
        raise OSError(error, f"cannot read Windows security metadata for {path}")
    buffer = ctypes.create_string_buffer(needed.value)
    if not get_file_security(
        str(path), security_information, buffer, needed.value, ctypes.byref(needed)
    ):
        error = ctypes.get_last_error()
        raise OSError(error, f"cannot read Windows security metadata for {path}")
    convert = advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW
    convert.argtypes = [
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(wintypes.DWORD),
    ]
    convert.restype = wintypes.BOOL
    sddl = wintypes.LPWSTR()
    length = wintypes.DWORD()
    if not convert(
        buffer,
        1,
        security_information,
        ctypes.byref(sddl),
        ctypes.byref(length),
    ):
        error = ctypes.get_last_error()
        raise OSError(error, f"cannot normalize Windows security metadata for {path}")
    try:
        return sddl.value or ""
    finally:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
        kernel32.LocalFree.restype = wintypes.HLOCAL
        kernel32.LocalFree(sddl)


def _windows_security_equivalent(before: str, after: str) -> bool:
    """Compare owner/group/DACL access semantics, ignoring inherited-origin tags."""

    def normalize(value: str) -> str:
        if "D:" not in value:
            return value
        prefix, dacl = value.split("D:", 1)
        first_ace = dacl.find("(")
        if first_ace < 0:
            return value
        control = dacl[:first_ace].replace("AI", "")

        def normalize_ace(match: re.Match[str]) -> str:
            fields = match.group(1).split(";")
            if len(fields) > 1:
                fields[1] = fields[1].replace("ID", "")
            return f"({';'.join(fields)})"

        aces = re.sub(r"\(([^()]*)\)", normalize_ace, dacl[first_ace:])
        return f"{prefix}D:{control}{aces}"

    return normalize(before) == normalize(after)


def _replace_file_preserving_security(staged_path: Path, target_path: Path) -> None:
    """Atomically publish a same-directory stage while retaining target security."""

    if os.name != "nt" or not target_path.exists():
        os.replace(staged_path, target_path)
        return

    import ctypes
    from ctypes import wintypes

    before = _windows_security_descriptor(target_path)
    backup_path = target_path.with_name(f".{target_path.name}.{uuid.uuid4().hex}.replace-backup")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    replace_file = kernel32.ReplaceFileW
    replace_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPVOID,
    ]
    replace_file.restype = wintypes.BOOL
    if not replace_file(str(target_path), str(staged_path), str(backup_path), 0, None, None):
        error = ctypes.get_last_error()
        if backup_path.exists():
            try:
                os.replace(backup_path, target_path)
            except OSError as restore_error:
                raise OSError(
                    error,
                    f"atomic Windows replacement failed for {target_path}; "
                    f"recoverable original retained at {backup_path}: {restore_error}",
                ) from restore_error
        raise OSError(error, f"atomic Windows replacement failed for {target_path}")
    try:
        after = _windows_security_descriptor(target_path)
        if not _windows_security_equivalent(before, after):
            raise RepairRejected(f"Windows security metadata changed while replacing {target_path}")
    except BaseException as publication_error:
        try:
            os.replace(backup_path, target_path)
        except OSError as restore_error:
            raise RepairRejected(
                f"replacement failed verification and automatic restore failed; "
                f"recoverable original retained at {backup_path}"
            ) from restore_error
        raise publication_error
    else:
        try:
            backup_path.unlink(missing_ok=True)
        except OSError:
            # Publication is already verified. A retained backup is safer than
            # reporting failure after the caller's rollback state has advanced.
            pass


def _publish_staged(staged_path: Path, source_path: Path) -> None:
    """Small publication seam used by deterministic race tests."""

    _replace_file_preserving_security(staged_path, source_path)


def _create_rollback_link(path: Path) -> Path:
    snapshot = path.with_name(f".{path.name}.{uuid.uuid4().hex}.rollback-link")
    try:
        os.link(path, snapshot)
    except OSError as exc:
        raise RepairRejected("filesystem cannot create the required exact rollback link") from exc
    try:
        if not os.path.samefile(path, snapshot):
            raise RepairRejected("rollback link does not identify the exact source object")
    except Exception:
        snapshot.unlink(missing_ok=True)
        raise
    return snapshot


def _stage_schematic(path: Path, data: bytes) -> Path:
    with tempfile.NamedTemporaryFile(
        "wb", dir=path.parent, prefix=f".{path.name}.", suffix=".stage", delete=False
    ) as staged:
        staged.write(data)
        staged.flush()
        os.fsync(staged.fileno())
        staged_path = Path(staged.name)
    try:
        shutil.copystat(path, staged_path)
    except Exception:
        staged_path.unlink(missing_ok=True)
        raise
    return staged_path


def _repair_audit_path(path: Path, audit_path: str | Path | None) -> Path:
    if audit_path is None:
        sidecar = path.parent / ".circuit-weaver"
        if _is_reparse_path(sidecar):
            raise RepairRejected("default repair audit directory cannot be a symlink or reparse point")
        if sidecar.exists() and not sidecar.is_dir():
            raise RepairRejected("default repair audit directory must be a directory")
        sidecar.mkdir(parents=False, exist_ok=True)
        if _is_reparse_path(sidecar):
            raise RepairRejected("default repair audit directory cannot be a symlink or reparse point")
        lexical_sidecar = Path(os.path.abspath(sidecar))
        if os.path.normcase(str(sidecar.resolve())) != os.path.normcase(str(lexical_sidecar)):
            raise RepairRejected("default repair audit directory must remain inside the project")
        raw = sidecar / "repair-audit.jsonl"
    else:
        raw = Path(audit_path)
    if _is_reparse_path(raw):
        raise RepairRejected("repair audit path cannot be a symlink or reparse point")
    audit = raw.resolve()
    if _paths_alias(path, audit):
        raise RepairRejected("repair audit path cannot alias the source schematic")
    return audit


def apply_no_connect(
    plan: dict[str, Any],
    metadata: dict[str, Any],
    *,
    approved_plan_hash: str,
    reviewer: str,
    finding_id: str,
    evidence_ids: tuple[str, ...] | list[str],
    audit_path: str | Path | None = None,
) -> dict[str, Any]:
    """Apply an approved plan under cross-process source and audit locks."""

    if (
        not isinstance(plan, dict)
        or plan.get("version") != 1
        or plan.get("kind") != "no_connect"
        or not isinstance(plan.get("source"), str)
        or not plan.get("source")
    ):
        raise RepairRejected("unsupported repair plan")
    if not approved_plan_hash or approved_plan_hash != plan.get("plan_sha256"):
        raise RepairRejected("explicit approved_plan_hash is required and must match the plan")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise RepairRejected("a non-empty reviewer is required")
    if not isinstance(finding_id, str) or not _FINDING_RE.fullmatch(finding_id):
        raise RepairRejected("finding_id must be FND- followed by 12 lowercase hexadecimal characters")
    normalized_evidence_ids = _normalized_evidence_ids(evidence_ids)
    if plan.get("finding_id") != finding_id or plan.get("evidence_ids") != list(normalized_evidence_ids):
        raise RepairRejected("approval identifiers do not match the staged plan")
    expected_plan = dict(plan)
    expected_plan.pop("plan_sha256", None)
    expected_plan.pop("status", None)
    if plan.get("plan_sha256") != _sha256_bytes(_canonical(expected_plan).encode()):
        raise RepairRejected("tampered repair plan")
    path = _resolved(plan["source"])
    if not path.is_file():
        raise RepairRejected("repair source does not exist")
    if path.stat().st_nlink > 1:
        raise RepairRejected("repair source must not have pre-existing hardlinks")
    lock_path = _source_lock_path(path)
    if lock_path.exists() and _paths_alias(path, lock_path):
        raise RepairRejected("repair lock path aliases the source schematic")
    with _exclusive_file_lock(lock_path, purpose="repair source"):
        return _apply_no_connect_locked(
            plan,
            metadata,
            approved_plan_hash=approved_plan_hash,
            reviewer=reviewer,
            finding_id=finding_id,
            evidence_ids=evidence_ids,
            audit_path=audit_path,
        )


def _apply_no_connect_locked(
    plan: dict[str, Any],
    metadata: dict[str, Any],
    *,
    approved_plan_hash: str,
    reviewer: str,
    finding_id: str,
    evidence_ids: tuple[str, ...] | list[str],
    audit_path: str | Path | None,
) -> dict[str, Any]:
    if plan.get("version") != 1 or plan.get("kind") != "no_connect":
        raise RepairRejected("unsupported repair plan")
    if not approved_plan_hash or approved_plan_hash != plan.get("plan_sha256"):
        raise RepairRejected("explicit approved_plan_hash is required and must match the plan")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise RepairRejected("a non-empty reviewer is required")
    if not isinstance(finding_id, str) or not _FINDING_RE.fullmatch(finding_id):
        raise RepairRejected("finding_id must be FND- followed by 12 lowercase hexadecimal characters")
    normalized_evidence_ids = _normalized_evidence_ids(evidence_ids)
    if plan.get("finding_id") != finding_id or plan.get("evidence_ids") != list(normalized_evidence_ids):
        raise RepairRejected("approval identifiers do not match the staged plan")
    path = _resolved(plan["source"])
    expected_plan = dict(plan)
    expected_plan.pop("plan_sha256", None)
    expected_plan.pop("status", None)
    if plan.get("plan_sha256") != _sha256_bytes(_canonical(expected_plan).encode()):
        raise RepairRejected("tampered repair plan")
    operation = plan.get("operation")
    if not isinstance(operation, dict) or operation.get("kind") != "insert_no_connect":
        raise RepairRejected("repair plan has no operation")
    if plan.get("risk") != "low" or not isinstance(plan.get("semantic_pre"), dict):
        raise RepairRejected("repair plan is missing bounded risk or semantic prerequisites")
    if not isinstance(plan.get("semantic_post"), dict) or not isinstance(plan.get("post_sha256"), str):
        raise RepairRejected("repair plan is missing expected postconditions")
    audit_file = _repair_audit_path(path, audit_path)
    audit_lock = _audit_lock_path(audit_file)
    if audit_lock.exists() and _paths_alias(path, audit_lock):
        raise RepairRejected("repair audit lock path aliases the source schematic")
    with _exclusive_file_lock(audit_lock, purpose="repair audit", blocking=True):
        return _apply_no_connect_audited(
            path,
            plan,
            metadata,
            approved_plan_hash=approved_plan_hash,
            reviewer=reviewer,
            finding_id=finding_id,
            normalized_evidence_ids=normalized_evidence_ids,
            audit_file=audit_file,
        )


def _apply_no_connect_audited(
    path: Path,
    plan: dict[str, Any],
    metadata: dict[str, Any],
    *,
    approved_plan_hash: str,
    reviewer: str,
    finding_id: str,
    normalized_evidence_ids: tuple[str, ...],
    audit_file: Path,
) -> dict[str, Any]:
    events = _read_audit_events(audit_file)
    current, source_hash = _source(path)
    original_parsed = parse_schematic(path)
    original_semantics = _semantic_counts(original_parsed)
    if source_hash != plan.get("source_sha256"):
        if verify_no_connect(path, plan):
            if not _audit_committed(events, plan["plan_sha256"], path):
                _append_audit_event(
                    audit_file,
                    {
                        "event": "repair_recovered",
                        "state": "committed",
                        "source": str(path),
                        "source_sha256_before": plan["source_sha256"],
                        "source_sha256_after": plan["post_sha256"],
                        "plan_sha256": plan["plan_sha256"],
                        "approved_plan_hash": approved_plan_hash,
                        "reviewer": reviewer,
                        "finding_id": finding_id,
                        "evidence_ids": list(normalized_evidence_ids),
                        "tool": "circuit_weaver.repair_service",
                        "package_version": __version__,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "verification": "passed",
                    },
                )
            return {
                "status": "already_applied",
                "plan_sha256": plan["plan_sha256"],
                "diff": {"added_no_connects": []},
            }
        raise RepairRejected("source changed since preview")
    if original_semantics != plan.get("semantic_pre"):
        raise RepairRejected("source semantic structure changed since preview")
    operation = plan["operation"]
    fresh = suggest_no_connect(
        path,
        metadata,
        ref=str(operation.get("ref", "")),
        pin=str(operation.get("pin", "")),
        finding_id=finding_id,
        evidence_ids=normalized_evidence_ids,
    )
    if fresh["operation"].get("object_hash") != operation.get("object_hash") or fresh["plan_sha256"] != plan.get(
        "plan_sha256"
    ):
        raise RepairRejected("component or pin identity changed since preview")
    parsed = parse_schematic(path)
    if _marker_present(parsed, operation):
        if not verify_no_connect(path, plan):
            raise RepairRejected("existing no-connect does not satisfy the approved plan")
        return {"status": "already_applied", "plan_sha256": plan["plan_sha256"], "diff": {"added_no_connects": []}}

    result_diff = {
        "added_no_connects": [
            {"ref": operation["ref"], "pin": operation["pin"], "x": operation["x"], "y": operation["y"]}
        ]
    }
    updated = _append_no_connect(current, operation)
    audit_base = {
        "source": str(path),
        "source_sha256_before": source_hash,
        "source_sha256_after": plan["post_sha256"],
        "plan_sha256": plan["plan_sha256"],
        "approved_plan_hash": approved_plan_hash,
        "reviewer": reviewer,
        "finding_id": finding_id,
        "evidence_ids": list(normalized_evidence_ids),
        "tool": "circuit_weaver.repair_service",
        "package_version": __version__,
        "diff": result_diff,
    }
    _append_audit_event(
        audit_file,
        {
            **audit_base,
            "event": "repair_prepared",
            "state": "prepared",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
    staged_path = _stage_schematic(path, updated)
    try:
        snapshot_path = _create_rollback_link(path)
    except Exception:
        staged_path.unlink(missing_ok=True)
        raise
    published = False
    try:
        reparsed = parse_schematic(staged_path)
        try:
            analyze_schematic_file(staged_path)
        except Exception as exc:
            raise RepairRejected(f"staged schematic analyzer rejected output: {exc}") from exc
        if _semantic_counts(reparsed) != plan.get("semantic_post"):
            raise RepairRejected("staged schematic does not match approved semantic postconditions")
        if _sha256_bytes(updated) != plan.get("post_sha256"):
            raise RepairRejected("staged post-image hash mismatch")
        if not _marker_present(reparsed, operation):
            raise RepairRejected("staged schematic failed reparse verification")
        if (
            not os.path.samefile(path, snapshot_path)
            or _sha256_bytes(path.read_bytes()) != plan.get("source_sha256")
            or _sha256_bytes(snapshot_path.read_bytes()) != plan.get("source_sha256")
        ):
            raise RepairRejected("source changed concurrently before publication")
        _publish_staged(staged_path, path)
        published = True
        if _sha256_bytes(snapshot_path.read_bytes()) != plan.get("source_sha256"):
            os.replace(snapshot_path, path)
            published = False
            raise RepairRejected("source changed during atomic publication; concurrent bytes were restored")
        try:
            final = parse_schematic(path)
            analyze_schematic_file(path)
            post_hash = _sha256_bytes(path.read_bytes())
            if (
                _semantic_counts(final) != plan.get("semantic_post")
                or post_hash != plan.get("post_sha256")
                or not _marker_present(final, operation)
            ):
                raise RepairRejected("final schematic verification failed")
            if _sha256_bytes(snapshot_path.read_bytes()) != source_hash:
                raise RepairRejected("source changed through a pre-publication handle")
            _append_audit_event(
                audit_file,
                {
                    **audit_base,
                    "event": "repair_committed",
                    "state": "committed",
                    "source_sha256_after": post_hash,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "verification": "passed",
                },
            )
            if not verify_no_connect(path, plan):
                raise RepairRejected("post-audit schematic verification failed")
        except Exception as exc:
            if published and snapshot_path.exists():
                try:
                    current_hash = _sha256_bytes(path.read_bytes())
                except OSError:
                    current_hash = ""
                if current_hash == plan.get("post_sha256"):
                    os.replace(snapshot_path, path)
                    published = False
                    try:
                        _append_audit_event(
                            audit_file,
                            {
                                **audit_base,
                                "event": "repair_rolled_back",
                                "state": "rolled_back",
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "verification": "failed",
                            },
                        )
                    except Exception:
                        pass
                else:
                    try:
                        _append_audit_event(
                            audit_file,
                            {
                                **audit_base,
                                "event": "repair_diverged",
                                "state": "diverged",
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "verification": "concurrent_user_bytes_preserved",
                            },
                        )
                    except Exception:
                        pass
                    raise RepairRejected(
                        "source changed concurrently after publication; user bytes were preserved"
                    ) from exc
            raise
    finally:
        staged_path.unlink(missing_ok=True)
        snapshot_path.unlink(missing_ok=True)
    return {
        "status": "applied",
        "plan_sha256": plan["plan_sha256"],
        "diff": result_diff,
        "audit": str(audit_file),
    }


def verify_no_connect(schematic: str | Path, plan: dict[str, Any]) -> bool:
    """Reparse and verify the operation described by a plan."""
    if not isinstance(plan, dict) or plan.get("version") != 1 or plan.get("kind") != "no_connect":
        return False
    signed = dict(plan)
    signed.pop("plan_sha256", None)
    signed.pop("status", None)
    if plan.get("plan_sha256") != _sha256_bytes(_canonical(signed).encode()):
        return False
    path = Path(schematic).resolve()
    try:
        planned_source = Path(str(plan.get("source", ""))).resolve()
    except (OSError, ValueError):
        return False
    if path != planned_source:
        return False
    if not path.is_file():
        return False
    operation = plan.get("operation") if isinstance(plan, dict) else None
    if not isinstance(operation, dict):
        return False
    try:
        _, hash_before = _source(path)
        parsed = parse_schematic(path)
        analyze_schematic_file(path)
        _, hash_after = _source(path)
    except Exception:
        return False
    if hash_before != hash_after:
        return False
    try:
        return (
            hash_after == plan.get("post_sha256")
            and _semantic_counts(parsed) == plan.get("semantic_post")
            and _marker_present(parsed, operation)
        )
    except RepairRejected:
        return False


__all__ = [
    "REPAIR_METADATA_SCHEMA_VERSION",
    "RepairRejected",
    "no_connect_finding_from_intent",
    "build_no_connect_metadata",
    "suggest_no_connect",
    "preview_no_connect",
    "apply_no_connect",
    "verify_no_connect",
]
