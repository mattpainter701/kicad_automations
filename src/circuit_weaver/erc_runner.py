"""ERC runner — invokes kicad-cli sch erc headlessly and parses results.

Degrades gracefully when KiCad CLI is not installed.  All public functions
return an :class:`ErcResult` so callers never need to handle subprocess
exceptions directly.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

_logger = logging.getLogger(__name__)

# Error type substrings that indicate a hard electrical error rather than
# an informational warning. Kept conservative — only well-known categories.
_ERROR_TYPES = frozenset(
    {
        "pin_not_connected",
        "pin_unconnected",
        "no_connect_connected",
        "wire_not_connected",
        "bus_definition_conflict",
        "bus_entry_needed",
        "duplicate_reference",
        "duplicate_sheet_names",
        "power_pin_not_driven",
        "conflicting_netclasses",
        "missing_power_flag",
        "label_dangling",
        "undefined_netclass",
    }
)


@dataclass
class ErcViolation:
    """A single ERC violation from kicad-cli output."""

    type: str
    description: str
    severity: str  # "error" | "warning"
    items: list[dict] = field(default_factory=list)


@dataclass
class ErcResult:
    """Parsed result from a kicad-cli ERC run.

    ``status`` values:
    - ``"ok"``      — ERC ran successfully (violations may still be present).
    - ``"skipped"`` — KiCad CLI not available; no ERC was performed.
    - ``"failed"``  — ERC attempted but could not complete (timeout, parse error).
    """

    status: str
    schematic: str = ""
    errors: int = 0
    warnings: int = 0
    violations: list[ErcViolation] = field(default_factory=list)
    skip_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "schematic": self.schematic,
            "errors": self.errors,
            "warnings": self.warnings,
            "skip_reason": self.skip_reason,
            "violations": [
                {
                    "type": v.type,
                    "description": v.description,
                    "severity": v.severity,
                    "items": v.items,
                }
                for v in self.violations
            ],
        }


def _kicad_cli_path() -> Path | None:
    """Locate kicad-cli on PATH or at known Windows installation paths."""
    from_path = shutil.which("kicad-cli")
    if from_path:
        return Path(from_path)
    for ver in ("10.0", "9.0", "8.0"):
        candidate = Path(f"C:/Program Files/KiCad/{ver}/bin/kicad-cli.exe")
        if candidate.exists():
            return candidate
    return None


def run_erc(schematic: str | Path, *, timeout: int = 60) -> ErcResult:
    """Run KiCad CLI ERC on *schematic* and return structured results.

    Degrades gracefully:
    - Returns ``status="skipped"`` when KiCad CLI is not installed.
    - Returns ``status="failed"`` when the schematic is missing or the
      subprocess times out / produces unparseable output.
    """
    schematic = Path(schematic)

    if not schematic.exists():
        _logger.warning("ERC skipped — schematic not found: %s", schematic)
        return ErcResult(status="failed", skip_reason=f"Schematic not found: {schematic}")

    cli = _kicad_cli_path()
    if cli is None:
        _logger.warning("KiCad CLI not found — ERC skipped. Install KiCad 8+ to enable ERC.")
        return ErcResult(
            status="skipped",
            skip_reason="KiCad CLI not available",
            schematic=str(schematic),
        )

    # Write ERC JSON to a temp file that kicad-cli can overwrite.
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        proc = subprocess.run(
            [str(cli), "sch", "erc", "--output", str(tmp_path), "--format", "json", str(schematic)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if not tmp_path.exists() or tmp_path.stat().st_size == 0:
            _logger.warning("kicad-cli ERC produced no output (exit %d)", proc.returncode)
            return ErcResult(
                status="failed",
                schematic=str(schematic),
                skip_reason=f"kicad-cli exited {proc.returncode} with no output",
            )

        raw = json.loads(tmp_path.read_text(encoding="utf-8"))
        result = _parse_erc_json(raw, str(schematic))
        _logger.info(
            "ERC: %d error(s), %d warning(s) in %s",
            result.errors,
            result.warnings,
            schematic.name,
        )
        return result

    except subprocess.TimeoutExpired:
        _logger.warning("kicad-cli ERC timed out after %ds", timeout)
        return ErcResult(
            status="failed",
            schematic=str(schematic),
            skip_reason=f"kicad-cli ERC timed out after {timeout}s",
        )
    except (json.JSONDecodeError, OSError) as exc:
        _logger.warning("ERC output parse error: %s", exc)
        return ErcResult(
            status="failed",
            schematic=str(schematic),
            skip_reason=f"ERC output parse error: {exc}",
        )
    finally:
        tmp_path.unlink(missing_ok=True)


def _parse_erc_json(raw: dict, schematic: str) -> ErcResult:
    """Parse kicad-cli ERC JSON into :class:`ErcResult`."""
    violations: list[ErcViolation] = []

    for v in raw.get("violations", []) or []:
        vtype = v.get("type", "unknown")
        severity = _classify_severity(vtype, v.get("severity", "warning"))
        violations.append(
            ErcViolation(
                type=vtype,
                description=v.get("description", ""),
                severity=severity,
                items=v.get("items", []),
            )
        )

    errors = sum(1 for v in violations if v.severity == "error")
    warnings = sum(1 for v in violations if v.severity == "warning")

    return ErcResult(
        status="ok",
        schematic=schematic,
        errors=errors,
        warnings=warnings,
        violations=violations,
    )


def _classify_severity(vtype: str, raw_severity: str) -> str:
    """Map a violation type + raw severity to canonical 'error' | 'warning'.

    KiCad's JSON uses strings like ``"error"``, ``"warning"``, ``"ignore"``.
    We also up-classify known error types regardless of what kicad-cli reported,
    since some versions emit them as warnings.
    """
    if raw_severity.lower() in ("error", "err"):
        return "error"
    if vtype.lower() in _ERROR_TYPES:
        return "error"
    return "warning"
