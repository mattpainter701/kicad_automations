"""CLI dispatcher and workflow engine for circuit-weaver.

Routes subcommands to handlers, orchestrates validation, artifact generation,
and semantic diffing. Provides the design IR abstraction, patch application,
grouped validation, and PCB constraint feedback on top of the schematic engine.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
import logging
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import warnings
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping
from xml.etree import ElementTree as ET

from .component_db import ComponentDef, PresentationWiringPolicy
from .design_ir import (
    DesignBlock,
    DesignInterface,
    DesignIR,
    design_ir_to_spec,
    normalize_design_spec,
    semantic_diff,
)
from .design_loader import (
    CompiledDesign,
    compile_design_ir,
)
from .design_logger import DesignLogger
from .generator import _contained_output_path, _validate_project_name, generate_from_components
from .project_spec import _parse_yaml
from .subcircuits.base import BoundaryPort, DataDrivenTemplate, get_default_registry
from .validator import run_validation_checks

_STANDARD_PROFILE = "standard"
_PROFILE_ALIASES = {"mvp_strict": _STANDARD_PROFILE}
_DESIGN_PATCH_KEYS = frozenset(
    {
        "set_metadata",
        "remove_blocks",
        "upsert_blocks",
        "upsert_interfaces",
        "remove_interfaces",
        "approved_overrides",
        "pcb_constraints",
    }
)
_DESIGN_PATCH_ALIASES = {"add": "upsert_blocks", "remove": "remove_blocks"}
_POWER_NET_PREFIXES = (
    "GND",
    "AGND",
    "DGND",
    "PGND",
    "VDD",
    "VCC",
    "VBAT",
    "VBUS",
    "VIN",
    "VDDA",
    "VSS",
    "MGT",
    "VCCO",
)
_PRESENTATION_SVG_MARGIN = 0.5
_GENERATION_LOCK_FILENAME = ".circuit-weaver.lock"
_GENERATION_PROCESS_LOCK = threading.RLock()

_ANSI = {
    "red": "\x1b[31m",
    "yellow": "\x1b[33m",
    "blue": "\x1b[34m",
    "bold": "\x1b[1m",
    "reset": "\x1b[0m",
}

_logger = logging.getLogger(__name__)


def _normalize_wizard_experience(raw: str) -> str:
    cleaned = raw.strip().lower()
    if not cleaned:
        return "Intermediate"
    aliases = {
        "1": "Beginner",
        "beginner": "Beginner",
        "new": "Beginner",
        "novice": "Beginner",
        "2": "Intermediate",
        "intermediate": "Intermediate",
        "mid": "Intermediate",
        "3": "Advanced",
        "advanced": "Advanced",
        "senior": "Advanced",
        "4": "Professional",
        "pro": "Professional",
        "professional": "Professional",
        "professional ee": "Professional",
        "expert": "Professional",
    }
    return aliases.get(cleaned, cleaned.title())


def _wizard_requirement_prompt_plan(experience_level: str) -> list[tuple[str, str, str]]:
    level = _normalize_wizard_experience(experience_level)
    if level == "Beginner":
        return [
            (
                "purpose",
                "In plain language, what are you building? (e.g., sensor node, motor controller) [Custom circuit]: ",
                "Custom circuit",
            ),
            (
                "form_factor",
                "Any size, enclosure, or connector-placement constraints? [No constraint]: ",
                "No constraint",
            ),
            (
                "input_power",
                "Where does power come from? (e.g., USB 5V, LiPo, wall adapter) [3.3V]: ",
                "3.3V",
            ),
            (
                "output_rails",
                "What rails/current do you expect to need? (rough is fine) [3.3V, 500mA]: ",
                "3.3V, 500mA",
            ),
            (
                "interfaces",
                "What does it need to connect to? (USB, WiFi, I2C sensors, buttons, motors, etc.) [I2C, UART]: ",
                "I2C, UART",
            ),
            (
                "mcu",
                "Do you already want a main MCU/processor, or should it be selected later? [to be selected]: ",
                "to be selected",
            ),
            (
                "components",
                "Any must-have sensors, connectors, or other key parts? [to be added]: ",
                "to be added",
            ),
            ("special_reqs", "Any special goals like low power, low noise, or ruggedness? []: ", ""),
        ]
    if level == "Advanced":
        return [
            (
                "purpose",
                "Compact design brief (what it does + key power, interfaces, constraints) [Custom circuit]: ",
                "Custom circuit",
            ),
            (
                "form_factor",
                "Mechanical constraints / size / enclosure [No constraint]: ",
                "No constraint",
            ),
            ("input_power", "Input power source [3.3V]: ", "3.3V"),
            ("output_rails", "Output rails / current budget [3.3V, 500mA]: ", "3.3V, 500mA"),
            ("interfaces", "Key interfaces / buses [I2C, UART]: ", "I2C, UART"),
            ("mcu", "Preferred MCU / main processor [to be selected]: ", "to be selected"),
            ("components", "Key components / preferred parts [to be added]: ", "to be added"),
            ("special_reqs", "Special requirements (low power, high speed, SI, thermal) []: ", ""),
        ]
    if level == "Professional":
        return [
            (
                "purpose",
                "Design brief or spec fragment "
                "(use: purpose; input power; rails/current; interfaces; constraints) "
                "[Custom circuit]: ",
                "Custom circuit",
            ),
            ("form_factor", "Mechanical constraints / enclosure / size [No constraint]: ", "No constraint"),
            ("input_power", "Input power source [3.3V]: ", "3.3V"),
            ("output_rails", "Output rails / current budget [3.3V, 500mA]: ", "3.3V, 500mA"),
            ("interfaces", "Key interfaces / buses [I2C, UART]: ", "I2C, UART"),
            ("mcu", "Preferred MCU / main IC [to be selected]: ", "to be selected"),
            ("components", "Preferred key parts / must-use / avoid [to be added]: ", "to be added"),
            ("special_reqs", "Special requirements (compliance, cost, schedule, thermal, SI) []: ", ""),
        ]
    return [
        ("purpose", "Purpose (e.g., WiFi sensor, motor controller) [Custom circuit]: ", "Custom circuit"),
        ("form_factor", "Size/constraints (e.g., 50x30mm, SMD only) [No constraint]: ", "No constraint"),
        ("input_power", "Input power source (e.g., 3.7V LiPo, 5V USB) [3.3V]: ", "3.3V"),
        ("output_rails", "Output rails (e.g., 3.3V, 500mA; 5V, 100mA) [3.3V, 500mA]: ", "3.3V, 500mA"),
        ("interfaces", "Interfaces (I2C, SPI, UART, USB, WiFi, etc.) [I2C, UART]: ", "I2C, UART"),
        ("mcu", "Main processor/MCU (e.g., ESP32, STM32L0) [to be selected]: ", "to be selected"),
        ("components", "Key components (comma-separated) [to be added]: ", "to be added"),
        ("special_reqs", "Special requirements (e.g., low power, high speed) []: ", ""),
    ]


def _color_support(mode: str) -> bool:
    """Check if ANSI color output is supported.

    Args:
        mode: "auto" (detect), "always", or "never"

    Returns:
        True if colors should be used, False otherwise
    """
    if mode == "always":
        return True
    if mode == "never":
        return False
    # auto: check if stdout is a TTY
    if not sys.stdout.isatty():
        return False
    # On Windows, check for WT_SESSION (Windows Terminal) or TERM env var
    if sys.platform == "win32":
        import os

        return bool(os.environ.get("WT_SESSION") or os.environ.get("TERM"))
    return True


def _print_validation_report(report: ValidationReport, *, use_color: bool, verbose: bool) -> None:
    """Print a validation report with optional colors and verbosity.

    Args:
        report: ValidationReport object to print
        use_color: Whether to use ANSI color codes
        verbose: Whether to include category and code in output
    """
    def _supports_stdout_text(text: str) -> bool:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        try:
            text.encode(encoding)
        except (LookupError, UnicodeEncodeError):
            return False
        return True

    pass_suffix = " ✓" if _supports_stdout_text("✓") else ""
    fail_suffix = " ✗" if _supports_stdout_text("✗") else ""

    # Header
    status_str = (
        f"{_ANSI['bold'] if use_color else ''}PASS{pass_suffix}{_ANSI['reset'] if use_color else ''}"
        if report.valid
        else f"{_ANSI['red'] if use_color else ''}FAIL{fail_suffix}{_ANSI['reset'] if use_color else ''}"
    )
    project = report.metadata.get("project", "design")
    print(f"{status_str} {project}")

    # Issues by category
    for category in sorted(report.categories.keys()):
        messages = report.categories[category]
        for msg in messages:
            # Level prefix (colored if enabled)
            if msg.level == "error":
                level_str = f"{_ANSI['red'] if use_color else ''}[ERROR]{_ANSI['reset'] if use_color else ''}"
            elif msg.level == "warning":
                level_str = f"{_ANSI['yellow'] if use_color else ''}[WARN]{_ANSI['reset'] if use_color else ''}"
            else:
                level_str = f"[{msg.level.upper()}]"

            print(f"{level_str} {msg.message}")

            if verbose:
                print(f"    category: {msg.category}, code: {msg.code}")

            if msg.suggestion:
                suggestion_str = (
                    f"{_ANSI['blue'] if use_color else ''}  → {msg.suggestion}{_ANSI['reset'] if use_color else ''}"
                )
                print(suggestion_str)


@dataclass(frozen=True)
class ValidationMessage:
    category: str
    code: str
    level: str
    subject: str
    message: str
    suggestion: str = ""


@dataclass
class ValidationReport:
    profile: str
    valid: bool
    categories: dict[str, list[ValidationMessage]] = field(default_factory=dict)
    summary: dict[str, int] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "valid": self.valid,
            "categories": {key: [asdict(item) for item in values] for key, values in self.categories.items()},
            "summary": dict(self.summary),
            "metadata": copy.deepcopy(self.metadata),
        }


@dataclass
class ConstraintFeedbackReport:
    accepted_constraints: int
    accepted_overrides: int
    rejected: list[dict[str, Any]] = field(default_factory=list)
    updated_spec: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted_constraints": self.accepted_constraints,
            "accepted_overrides": self.accepted_overrides,
            "rejected": copy.deepcopy(self.rejected),
            "updated_spec": copy.deepcopy(self.updated_spec),
        }




def _ensure_profile(profile: str) -> str:
    normalized = (profile or _STANDARD_PROFILE).strip().lower()
    if normalized in _PROFILE_ALIASES:
        replacement = _PROFILE_ALIASES[normalized]
        warnings.warn(
            f"Validation profile '{normalized}' is deprecated; use '{replacement}'",
            DeprecationWarning,
            stacklevel=2,
        )
        normalized = replacement
    if normalized != _STANDARD_PROFILE:
        raise ValueError(f"Unsupported MVP validation profile '{profile}'")
    return normalized


def _normalize_design_patch(patch: dict[str, Any]) -> dict[str, Any]:
    """Return a validated patch with deprecated operation aliases expanded."""
    if not isinstance(patch, dict):
        raise TypeError("Design patch must be a mapping")

    normalized = copy.deepcopy(patch)
    for alias, canonical in _DESIGN_PATCH_ALIASES.items():
        if alias not in normalized:
            continue
        if canonical in normalized:
            raise ValueError(f"Patch cannot contain both '{alias}' and '{canonical}'")
        warnings.warn(
            f"Patch operation '{alias}' is deprecated; use '{canonical}'",
            DeprecationWarning,
            stacklevel=3,
        )
        normalized[canonical] = normalized.pop(alias)

    unknown = sorted(set(normalized) - _DESIGN_PATCH_KEYS)
    if unknown:
        supported = ", ".join(sorted(_DESIGN_PATCH_KEYS))
        raise ValueError(f"Unsupported design patch operation(s): {', '.join(unknown)}. Supported: {supported}")
    return normalized


def _is_power_net(name: str) -> bool:
    net = str(name or "").upper()
    return any(net == prefix or net.startswith(f"{prefix}_") for prefix in _POWER_NET_PREFIXES)


def _block_primary_key(block: DesignBlock) -> str:
    return block.ref or block.id


def _group_components_by_block_key(components: list[ComponentDef]) -> dict[str, list[ComponentDef]]:
    groups: dict[str, list[ComponentDef]] = {}
    for comp in components:
        key = comp.source_ref or ""
        if not key:
            continue
        groups.setdefault(key, []).append(comp)
    return groups


def _derive_required_support(group: list[ComponentDef]) -> dict[str, Any]:
    boundary_ports = 0
    local_wires = 0
    bypass_caps = 0
    straps = 0
    power_reqs = 0
    for comp in group:
        boundary_ports += len(comp.template_boundary_ports)
        local_wires += len(comp.template_local_wires)
        bypass_caps += len(comp.bypass_caps)
        straps += len(comp.straps)
        power_reqs += len(comp.power_reqs)
    return {
        "bypass_caps": bypass_caps,
        "straps": straps,
        "power_reqs": power_reqs,
        "boundary_ports": boundary_ports,
        "local_wires": local_wires,
    }


def _derive_part_bindings(primary: ComponentDef) -> dict[str, Any]:
    return {
        "mpn": primary.source_mpn or primary.mpn,
        "value": primary.source_value or primary.value,
        "footprint": primary.footprint,
        "manufacturer": primary.source_manufacturer,
    }


def _apply_block_attributes(ir: DesignIR, components: list[ComponentDef]) -> None:
    groups = _group_components_by_block_key(components)
    for block in ir.blocks:
        group = groups.get(_block_primary_key(block))
        if not group:
            continue
        primary = group[0]
        if block.interfaces:
            primary.template_boundary_ports = [BoundaryPort(iface.name, iface.direction) for iface in block.interfaces]
        if block.presentation_group:
            for comp in group:
                comp.presentation_group = block.presentation_group
        if block.part_bindings:
            footprint = str(block.part_bindings.get("footprint", "")).strip()
            mpn = str(block.part_bindings.get("mpn", "")).strip()
            value = str(block.part_bindings.get("value", "")).strip()
            if footprint:
                primary.footprint = footprint
            if mpn:
                primary.source_mpn = mpn
                primary.mpn = mpn
            if value:
                primary.value = value
                primary.source_value = value


def _apply_approved_overrides(ir: DesignIR, components: list[ComponentDef]) -> None:
    groups = _group_components_by_block_key(components)
    for override in ir.approved_overrides:
        target = str(override.get("target", "")).strip()
        kind = str(override.get("kind", "")).strip().lower()
        value = override.get("value")
        group = groups.get(target)
        if not group:
            continue
        primary = group[0]
        if kind == "annotation_append" and value:
            primary.annotations.append(str(value))
        elif kind == "footprint_override" and value:
            primary.footprint = str(value)
        elif kind == "presentation_group" and value:
            for comp in group:
                comp.presentation_group = str(value)
        elif kind == "part_binding" and isinstance(value, dict):
            footprint = str(value.get("footprint", "")).strip()
            mpn = str(value.get("mpn", "")).strip()
            part_value = str(value.get("value", "")).strip()
            if footprint:
                primary.footprint = footprint
            if mpn:
                primary.source_mpn = mpn
                primary.mpn = mpn
            if part_value:
                primary.value = part_value
                primary.source_value = part_value
        elif kind == "support_passives" and value:
            primary.presentation_wiring_policy = PresentationWiringPolicy(support_passives=str(value))


def _hydrate_ir_from_components(ir: DesignIR, components: list[ComponentDef]) -> DesignIR:
    groups = _group_components_by_block_key(components)
    hydrated_blocks = []
    for block in ir.blocks:
        group = groups.get(_block_primary_key(block))
        interfaces = list(block.interfaces)
        required_support = copy.deepcopy(block.required_support or {})
        part_bindings = copy.deepcopy(block.part_bindings or {})
        if group:
            primary = group[0]
            if not interfaces and primary.template_boundary_ports:
                interfaces = [
                    DesignInterface(
                        block_id=block.id,
                        name=port.name,
                        direction=port.direction,
                    ).normalized()
                    for port in primary.template_boundary_ports
                ]
            if not required_support:
                required_support = _derive_required_support(group)
            if not part_bindings:
                part_bindings = _derive_part_bindings(primary)
        hydrated_blocks.append(
            DesignBlock(
                id=block.id,
                section=block.section,
                kind=block.kind,
                ref=block.ref,
                template_type=block.template_type,
                ic=block.ic,
                params=copy.deepcopy(block.params),
                value=block.value,
                description=block.description,
                mpn=block.mpn,
                required_support=required_support,
                part_bindings=part_bindings,
                presentation_group=block.presentation_group,
                interfaces=interfaces,
            ).normalized()
        )

    all_interfaces = []
    for block in hydrated_blocks:
        all_interfaces.extend(block.interfaces)

    return DesignIR(
        metadata=copy.deepcopy(ir.metadata),
        blocks=hydrated_blocks,
        interfaces=all_interfaces,
        approved_overrides=copy.deepcopy(ir.approved_overrides),
        pcb_constraints=copy.deepcopy(ir.pcb_constraints),
    )




def _validate_block_definitions(ir: DesignIR) -> tuple[list[ValidationMessage], list[ValidationMessage]]:
    structural: list[ValidationMessage] = []
    electrical: list[ValidationMessage] = []
    registry = get_default_registry()

    seen_ids: set[str] = set()
    seen_refs: set[str] = set()
    for block in ir.blocks:
        if block.id in seen_ids:
            structural.append(
                ValidationMessage(
                    category="structural",
                    code="duplicate-block-id",
                    level="error",
                    subject=block.id,
                    message=f"Block id '{block.id}' is duplicated",
                )
            )
        seen_ids.add(block.id)

        if not block.ref:
            structural.append(
                ValidationMessage(
                    category="structural",
                    code="missing-ref",
                    level="error",
                    subject=block.id,
                    message="Every MVP block must declare a stable reference designator",
                )
            )
        elif block.ref in seen_refs:
            structural.append(
                ValidationMessage(
                    category="structural",
                    code="duplicate-ref",
                    level="error",
                    subject=block.ref,
                    message=f"Reference '{block.ref}' is duplicated across blocks",
                )
            )
        seen_refs.add(block.ref)

        if block.kind == "template":
            if not block.template_type:
                structural.append(
                    ValidationMessage(
                        category="structural",
                        code="missing-template-type",
                        level="error",
                        subject=block.id,
                        message="Template blocks must declare a template type",
                    )
                )
                continue
            template = registry.get(block.template_type)
            if template is None:
                structural.append(
                    ValidationMessage(
                        category="structural",
                        code="unknown-template",
                        level="error",
                        subject=block.template_type,
                        message=f"Unknown subcircuit template '{block.template_type}'",
                    )
                )
                continue
            params = copy.deepcopy(block.params)
            if block.ref:
                params.setdefault("ref", block.ref)
            # Run template-specific validation + schema-driven validation
            custom_errors = template.validate_params(params)
            schema_errors = template._validate_params_from_schema(params)
            unknown_errors = template._validate_unknown_params(params)
            # Deduplicate (custom validators may overlap with schema checks)
            seen: set[str] = set()
            for error in custom_errors + schema_errors + unknown_errors:
                if error not in seen:
                    seen.add(error)
                    electrical.append(
                        ValidationMessage(
                            category="electrical",
                            code="template-param",
                            level="error",
                            subject=block.ref or block.id,
                            message=error,
                        )
                    )
        else:
            if not block.ic:
                structural.append(
                    ValidationMessage(
                        category="structural",
                        code="missing-ic",
                        level="error",
                        subject=block.id,
                        message="Component blocks must declare an IC/part identifier",
                    )
                )
    return structural, electrical


def _validate_component_resolution(
    compiled: CompiledDesign,
) -> tuple[list[ValidationMessage], list[ValidationMessage]]:
    structural: list[ValidationMessage] = []
    implementation: list[ValidationMessage] = []
    groups = _group_components_by_block_key(compiled.components)
    try:
        from .footprint_lib import KiCadFootprintLibrary

        fp_lib = KiCadFootprintLibrary()
    except Exception:
        fp_lib = None

    for block in compiled.ir.blocks:
        group = groups.get(_block_primary_key(block), [])
        if not group:
            structural.append(
                ValidationMessage(
                    category="structural",
                    code="unresolved-block",
                    level="error",
                    subject=block.ref or block.id,
                    message="Block did not resolve into any schematic components",
                )
            )
            continue
        primary = group[0]
        if any("UNRESOLVED" in a for a in primary.annotations):
            structural.append(
                ValidationMessage(
                    category="structural",
                    code="unresolved-component",
                    level="error",
                    subject=block.ref or block.id,
                    message=next(
                        (a for a in primary.annotations if "UNRESOLVED" in a),
                        "Component could not be resolved",
                    ),
                )
            )
            continue
        if not primary.pins and not primary.lib_symbol_sexpr:
            implementation.append(
                ValidationMessage(
                    category="implementation",
                    code="missing-symbol-definition",
                    level="error",
                    subject=block.ref or block.id,
                    message="Resolved block has neither pins nor an embedded symbol definition",
                )
            )
        # Some template types (e.g. PULLUPS_ONLY) are virtual — they expand into
        # discrete passives and carry no physical footprint by design. The block
        # ref inherits a 'U' prefix from the YAML field, not from the template,
        # so ref_prefix alone cannot distinguish these; use the MPN instead.
        _VIRTUAL_MPNS: frozenset[str] = frozenset({"PULLUPS_ONLY"})
        if not primary.footprint and primary.mpn not in _VIRTUAL_MPNS:
            implementation.append(
                ValidationMessage(
                    category="implementation",
                    code="missing-footprint",
                    level="error",
                    subject=block.ref or block.id,
                    message="Resolved block has no footprint binding",
                )
            )
        elif primary.footprint and fp_lib and fp_lib.roots and not fp_lib.footprint_exists(primary.footprint):
            from .footprint_lib import custom_footprint_suggestion, official_kicad_footprint_url

            roots = ", ".join(str(root) for root in fp_lib.roots[:2])
            if len(fp_lib.roots) > 2:
                roots += ", ..."
            url = official_kicad_footprint_url(primary.footprint)
            implementation.append(
                ValidationMessage(
                    category="implementation",
                    code="footprint-library-missing",
                    level="warning",
                    subject=block.ref or block.id,
                    message=(
                        f"Footprint '{primary.footprint}' is not present in local KiCad footprint libraries; "
                        f"searched {roots}. Check the official KiCad footprint library at {url}, "
                        "import the manufacturer .pretty library, or choose a standard KiCad footprint"
                    ),
                    suggestion=custom_footprint_suggestion(primary.mpn, primary.footprint, fp_lib),
                )
            )
        # Pin count sanity: IC with very few pins is suspicious
        if primary.pins and primary.ref_prefix.upper() in ("U", "IC"):
            pin_count = len(primary.pins)
            if pin_count < 3:
                implementation.append(
                    ValidationMessage(
                        category="implementation",
                        code="low-pin-count",
                        level="warning",
                        subject=block.ref or block.id,
                        message=f"IC has only {pin_count} pin(s) — verify symbol is complete",
                    )
                )
        # Footprint-to-pin consistency: extract expected pad count from footprint name
        if primary.footprint and primary.pins:
            fp = primary.footprint
            fp_pin_match = re.search(r"(\d+)(?:[-_]Pin|pad|Pad|P(?:\d|$))", fp)
            if not fp_pin_match:
                # Try common patterns: QFN-48, SOIC-8, TSSOP-20, BGA-121
                fp_pin_match = re.search(r"(?:QFN|SOIC|TSSOP|LQFP|BGA|DIP|SOP|MSOP|LFCSP)[-_]?(\d+)", fp)
            if fp_pin_match:
                fp_pins = int(fp_pin_match.group(1))
                sym_pins = len(primary.pins)
                if abs(fp_pins - sym_pins) > max(2, sym_pins * 0.1):
                    implementation.append(
                        ValidationMessage(
                            category="implementation",
                            code="pin-footprint-mismatch",
                            level="warning",
                            subject=block.ref or block.id,
                            message=(
                                f"Symbol has {sym_pins} pins but footprint '{fp}' implies {fp_pins} pads — verify match"
                            ),
                        )
                    )
        if block.kind == "component":
            support = block.required_support or {}
            has_contract = bool(block.interfaces or support or block.part_bindings)
            if not has_contract:
                structural.append(
                    ValidationMessage(
                        category="structural",
                        code="component-block-missing-contract",
                        level="error",
                        subject=block.ref or block.id,
                        message=(
                            "Atomic component blocks must declare interfaces, required support, "
                            "or part bindings before they can become canonical MVP blocks"
                        ),
                    )
                )
    return structural, implementation


def _validate_shared_net_interfaces(compiled: CompiledDesign) -> list[ValidationMessage]:
    issues: list[ValidationMessage] = []
    groups = _group_components_by_block_key(compiled.components)
    declared_ports: dict[str, set[str]] = {}
    nets_to_blocks: dict[str, set[str]] = {}

    for block in compiled.ir.blocks:
        block_key = _block_primary_key(block)
        group = groups.get(block_key, [])
        if not group:
            continue
        declared = {iface.name for iface in block.interfaces}
        if not declared:
            for comp in group:
                declared.update(port.name for port in comp.template_boundary_ports)
        declared_ports[block_key] = declared

        for comp in group:
            for net in comp.pin_nets.values():
                if net and not _is_power_net(net):
                    nets_to_blocks.setdefault(net, set()).add(block_key)
            for net in comp.power_pins.values():
                if net and not _is_power_net(net):
                    nets_to_blocks.setdefault(net, set()).add(block_key)

    for net, block_keys in sorted(nets_to_blocks.items()):
        if len(block_keys) < 2:
            continue
        for block_key in sorted(block_keys):
            if net in declared_ports.get(block_key, set()):
                continue
            issues.append(
                ValidationMessage(
                    category="structural",
                    code="undeclared-shared-net",
                    level="error",
                    subject=block_key,
                    message=f"Shared signal '{net}' crosses blocks without an explicit interface declaration",
                )
            )
    return issues


def _validate_required_support(compiled: CompiledDesign) -> list[ValidationMessage]:
    issues: list[ValidationMessage] = []
    groups = _group_components_by_block_key(compiled.components)
    for block in compiled.ir.blocks:
        group = groups.get(_block_primary_key(block))
        if not group or not block.required_support:
            continue
        actual = _derive_required_support(group)
        for key, required in block.required_support.items():
            if not isinstance(required, (int, float)):
                continue
            if actual.get(key, 0) < required:
                issues.append(
                    ValidationMessage(
                        category="electrical",
                        code="required-support-missing",
                        level="error",
                        subject=block.ref or block.id,
                        message=(
                            f"Required support '{key}' expects >= {required}, but only {actual.get(key, 0)} resolved"
                        ),
                    )
                )
    return issues


def _validate_power_domains(compiled: CompiledDesign) -> list[ValidationMessage]:
    issues: list[ValidationMessage] = []
    for comp in compiled.components:
        if comp.ref_prefix.upper() != "U":
            continue
        for pin_num, net in comp.power_pins.items():
            if not net:
                issues.append(
                    ValidationMessage(
                        category="electrical",
                        code="missing-power-net",
                        level="error",
                        subject=comp.source_ref or comp.mpn,
                        message=f"Power pin {pin_num} has no resolved rail assignment",
                    )
                )
    return issues


_NC_PIN_NAME_RE = re.compile(r"^(~|NC|DNC|N\.?C\.?|NO.?CONNECT|RESERVED)$", re.IGNORECASE)


def _validate_pin_coverage(compiled: CompiledDesign) -> list[ValidationMessage]:
    """Check that every pin on every IC is explicitly handled.

    Pins must be in pin_nets, power_pins, explicit_no_connects, or have
    an NC-like name.  Unhandled pins are flagged by electrical type:
      - power_in  → error  (must be connected to a rail)
      - input / bidirectional → warning (likely needs a driver or pull)
      - output / passive / other → info-level (usually safe to NC)
    """
    issues: list[ValidationMessage] = []
    for comp in compiled.components:
        # Only check ICs — passives, connectors, etc. are wired differently
        if comp.ref_prefix.upper() not in ("U", "IC"):
            continue

        handled = set(comp.pin_nets) | set(comp.power_pins) | comp.explicit_no_connects
        # Also count pins that have straps (the strap wires them)
        for strap in comp.straps:
            handled.add(strap.pin)

        subject = comp.source_ref or comp.mpn

        floating_power: list[str] = []
        floating_input: list[str] = []

        for pin in comp.pins:
            if pin.number in handled:
                continue
            if _NC_PIN_NAME_RE.match(pin.name):
                continue

            etype = pin.electrical_type or "unspecified"

            if etype == "power_in":
                floating_power.append(f"{pin.number} ({pin.name})")
            elif etype in ("input", "bidirectional", "tri_state"):
                floating_input.append(f"{pin.number} ({pin.name})")

        # Power pins floating is always an error (per pin)
        for desc in floating_power:
            issues.append(
                ValidationMessage(
                    category="electrical",
                    code="floating-power-pin",
                    level="error",
                    subject=subject,
                    message=f"Power pin {desc} is not connected to any rail",
                )
            )

        # For input/bidirectional: summarize if many (MCUs with 20+ unused GPIOs)
        if len(floating_input) > 8:
            issues.append(
                ValidationMessage(
                    category="electrical",
                    code="floating-input-pin",
                    level="warning",
                    subject=subject,
                    message=(
                        f"{len(floating_input)} input/bidirectional pins unconnected "
                        f"(e.g., {', '.join(floating_input[:3])}, ...) — "
                        f"add to explicit_no_connects or wire as needed"
                    ),
                )
            )
        else:
            for desc in floating_input:
                issues.append(
                    ValidationMessage(
                        category="electrical",
                        code="floating-input-pin",
                        level="warning",
                        subject=subject,
                        message=(
                            f"Pin {desc} is unconnected — may need a pull-up/down, driver, or explicit no-connect"
                        ),
                    )
                )
    return issues


_VOLTAGE_PATTERN = re.compile(r"(\d+)[PV](\d+)|(\d+)V")


def _infer_rail_voltage(net: str) -> float | None:
    """Attempt to extract a voltage from a power net name (e.g., VDD_3P3 → 3.3)."""
    known = {
        "VDD_3P3": 3.3,
        "VDD_1P8": 1.8,
        "VDD_1P2": 1.2,
        "VDD_2P5": 2.5,
        "VBUS_5V": 5.0,
        "VCCAUX": 1.8,
        "VCCINT": 1.0,
        "VDD_DDR": 1.35,
    }
    upper = (net or "").upper()
    if upper in known:
        return known[upper]
    m = _VOLTAGE_PATTERN.search(upper)
    if m:
        if m.group(1) and m.group(2):
            return float(f"{m.group(1)}.{m.group(2)}")
        if m.group(3):
            return float(m.group(3))
    return None


def _validate_power_domain_consistency(compiled: CompiledDesign) -> list[ValidationMessage]:
    """Cross-check power domain assignments for consistency.

    1. Collect all (net_name → voltage) assignments across all components.
    2. Flag if the same net has conflicting voltage expectations.
    3. Flag power_in pins where the assigned rail voltage doesn't match the
       component's declared power_reqs voltage.
    """
    issues: list[ValidationMessage] = []

    # Collect voltage expectations per net across all components
    net_voltages: dict[str, list[tuple[str, float]]] = {}
    for comp in compiled.components:
        subject = comp.source_ref or comp.mpn
        for req in comp.power_reqs:
            if req.net and req.voltage > 0:
                net_voltages.setdefault(req.net, []).append((subject, req.voltage))

    # Check for conflicting voltage expectations on the same net
    for net, sources in net_voltages.items():
        voltages = {v for _, v in sources}
        if len(voltages) > 1:
            details = ", ".join(f"{src}={v}V" for src, v in sources)
            issues.append(
                ValidationMessage(
                    category="electrical",
                    code="power-domain-voltage-conflict",
                    level="error",
                    subject=net,
                    message=f"Power net '{net}' has conflicting voltage requirements: {details}",
                )
            )

    # Check that each component's power_reqs voltage matches what the rail name implies
    for comp in compiled.components:
        subject = comp.source_ref or comp.mpn
        for req in comp.power_reqs:
            if not req.net or req.voltage <= 0:
                continue
            implied_v = _infer_rail_voltage(req.net)
            if implied_v is not None and abs(implied_v - req.voltage) / max(req.voltage, 0.1) > 0.10:
                issues.append(
                    ValidationMessage(
                        category="electrical",
                        code="power-domain-voltage-mismatch",
                        level="warning",
                        subject=subject,
                        message=(
                            f"Component requires {req.voltage}V on '{req.net}', but rail name implies {implied_v}V"
                        ),
                    )
                )

    # Check that every non-GND power pin has a bypass cap somewhere
    for comp in compiled.components:
        if comp.ref_prefix.upper() != "U":
            continue
        subject = comp.source_ref or comp.mpn
        cap_nets = {bc.net for bc in comp.bypass_caps}
        for req in comp.power_reqs:
            if req.net and not any(n.upper().startswith("GND") for n in [req.net]):
                if req.net not in cap_nets:
                    issues.append(
                        ValidationMessage(
                            category="electrical",
                            code="missing-bypass-cap-for-rail",
                            level="warning",
                            subject=subject,
                            message=f"Power rail '{req.net}' ({req.voltage}V) has no bypass cap declared",
                        )
                    )

    return issues


def _kicad_cli_path() -> Path | None:
    from_path = shutil.which("kicad-cli")
    if from_path:
        return Path(from_path)
    for ver in ("10.0", "9.0", "8.0"):
        candidate = Path(f"C:/Program Files/KiCad/{ver}/bin/kicad-cli.exe")
        if candidate.exists():
            return candidate
    return None


def _find_root_schematic(files: list[str], project_name: str) -> Path | None:
    sch_files = [Path(path) for path in files if str(path).endswith(".kicad_sch")]
    for path in sch_files:
        if path.stem == project_name:
            return path
    return sch_files[0] if sch_files else None


def _generate_compiled_artifacts(
    compiled: CompiledDesign,
    output_dir: Path,
    *,
    export_svg: bool,
    score: bool = False,
    readiness_gate: bool = True,
) -> tuple[list[str], Path | None]:
    output_dir.mkdir(parents=True, exist_ok=True)
    profile = compiled.metadata.get("presentation_profile", "default")
    pwp = PresentationWiringPolicy(support_passives="topology_local") if profile == "review" else None
    # Deep-copy components so that in-place mutations from auto_generate_bypass_caps
    # and annotation appends in the generator don't bleed between validation runs
    # that reuse the same CompiledDesign object (e.g. the determinism check).
    components = copy.deepcopy(compiled.components)
    files = generate_from_components(
        components,
        str(output_dir),
        project_name=compiled.metadata.get("project", "project"),
        company=compiled.metadata.get("company", ""),
        description=compiled.metadata.get("description", ""),
        stable_uuids=True,
        validate=True,
        pcb=True,
        hierarchical=True,
        interface_policy="explicit",
        presentation_wiring_policy=pwp,
        score=score,
        compiled_ir=compiled.ir,
        readiness_gate=readiness_gate,
    )
    root = _find_root_schematic(files, compiled.metadata.get("project", "project"))
    if export_svg and root is not None:
        cli = _kicad_cli_path()
        if cli is not None:
            svg_dir = _contained_output_path(output_dir, "svg")
            svg_dir.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [str(cli), "sch", "export", "svg", "-o", str(svg_dir), str(root)],
                check=True,
                capture_output=True,
                text=True,
            )
    return files, root


def _kicad_text_map(output_dir: Path) -> dict[str, str]:
    result = {}
    for path in sorted(output_dir.glob("*.kicad_sch")):
        result[path.name] = path.read_text(encoding="utf-8")
    return result


def _svg_content_metrics(svg_path: Path) -> dict[str, float]:
    svg_text = svg_path.read_text(encoding="utf-8")
    # Guard against XML entity expansion on untrusted SVGs
    try:
        from defusedxml.ElementTree import fromstring as safe_fromstring

        root = safe_fromstring(svg_text)
    except ImportError:
        root = ET.fromstring(svg_text)  # noqa: S314 — SVGs are generated by KiCad CLI, not user-uploaded
    view_box = root.attrib.get("viewBox", "")
    _vx, _vy, page_w, page_h = [float(part) for part in view_box.split()]

    coords = []
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "path":
            nums = [float(n) for n in __import__("re").findall(r"-?\d+(?:\.\d+)?", element.attrib.get("d", ""))]
            if len(nums) < 4:
                continue
            xs = nums[0::2]
            ys = nums[1::2]
            if (max(xs) - min(xs)) > page_w * 0.98 and (max(ys) - min(ys)) > page_h * 0.98:
                continue
            coords.extend(zip(xs, ys))
        elif tag == "rect":
            x = float(element.attrib.get("x", 0))
            y = float(element.attrib.get("y", 0))
            w = float(element.attrib.get("width", 0))
            h = float(element.attrib.get("height", 0))
            if w > page_w * 0.98 and h > page_h * 0.98:
                continue
            coords.extend([(x, y), (x + w, y + h)])
        elif tag == "text":
            x = float(element.attrib.get("x", 0))
            y = float(element.attrib.get("y", 0))
            coords.append((x, y))

    if not coords:
        return {
            "page_w": page_w,
            "page_h": page_h,
            "min_x": page_w,
            "min_y": page_h,
            "max_x": 0.0,
            "max_y": 0.0,
        }
    xs = [x for x, _ in coords]
    ys = [y for _, y in coords]
    return {
        "page_w": page_w,
        "page_h": page_h,
        "min_x": min(xs),
        "min_y": min(ys),
        "max_x": max(xs),
        "max_y": max(ys),
    }


def _presentation_issues(output_dir: Path) -> list[ValidationMessage]:
    svg_dir = output_dir / "svg"
    issues: list[ValidationMessage] = []
    for svg_path in sorted(svg_dir.glob("*.svg")):
        metrics = _svg_content_metrics(svg_path)
        if metrics["min_x"] < -_PRESENTATION_SVG_MARGIN:
            issues.append(
                ValidationMessage(
                    category="presentation",
                    code="svg-left-overflow",
                    level="error",
                    subject=svg_path.name,
                    message=f"SVG content exceeds the left page bound ({metrics['min_x']:.2f}mm)",
                )
            )
        if metrics["min_y"] < -_PRESENTATION_SVG_MARGIN:
            issues.append(
                ValidationMessage(
                    category="presentation",
                    code="svg-top-overflow",
                    level="error",
                    subject=svg_path.name,
                    message=f"SVG content exceeds the top page bound ({metrics['min_y']:.2f}mm)",
                )
            )
        if metrics["max_x"] > metrics["page_w"] + _PRESENTATION_SVG_MARGIN:
            issues.append(
                ValidationMessage(
                    category="presentation",
                    code="svg-right-overflow",
                    level="error",
                    subject=svg_path.name,
                    message=(
                        f"SVG content exceeds the right page bound "
                        f"({metrics['max_x']:.2f}mm > {metrics['page_w']:.2f}mm)"
                    ),
                )
            )
        if metrics["max_y"] > metrics["page_h"] + _PRESENTATION_SVG_MARGIN:
            issues.append(
                ValidationMessage(
                    category="presentation",
                    code="svg-bottom-overflow",
                    level="error",
                    subject=svg_path.name,
                    message=(
                        f"SVG content exceeds the bottom page bound "
                        f"({metrics['max_y']:.2f}mm > {metrics['page_h']:.2f}mm)"
                    ),
                )
            )
    return issues


def validate_design(
    spec: dict[str, Any],
    *,
    profile: str = _STANDARD_PROFILE,
    enrich_parts: bool = False,
    strict: bool = False,
    check_determinism: bool = True,
) -> ValidationReport:
    """Validate a design spec against the strict MVP profile.

    When *strict* is True, warnings also count as failures (not just errors).

    When *check_determinism* is True (default), the validator runs the
    artifact generation pipeline twice in temp directories and asserts the
    output bytes match — the only way to catch non-deterministic UUID /
    placement drift before it ships. Callers like ``generate_artifacts``
    that are about to generate real artifacts anyway pass
    ``check_determinism=False`` to avoid the redundant 2x generation
    overhead (Sprint 45 Bug 3 — was 3 generations per CLI invocation).
    """
    profile = _ensure_profile(profile)
    compiled = compile_design_ir(spec, enrich_parts=enrich_parts)

    categories: dict[str, list[ValidationMessage]] = {
        "structural": [],
        "electrical": [],
        "implementation": [],
        "presentation": [],
        "placement_readiness": [],
    }

    structural, electrical = _validate_block_definitions(compiled.ir)
    categories["structural"].extend(structural)
    categories["electrical"].extend(electrical)

    structural, implementation = _validate_component_resolution(compiled)
    categories["structural"].extend(structural)
    categories["implementation"].extend(implementation)
    categories["structural"].extend(_validate_shared_net_interfaces(compiled))
    categories["electrical"].extend(_validate_required_support(compiled))
    categories["electrical"].extend(_validate_power_domains(compiled))
    categories["electrical"].extend(_validate_pin_coverage(compiled))
    categories["electrical"].extend(_validate_power_domain_consistency(compiled))

    validator_results = list(run_validation_checks(compiled.components))
    for result in validator_results:
        for issue in result.issues:
            categories["electrical"].append(
                ValidationMessage(
                    category="electrical",
                    code=result.code,
                    level=issue.level,
                    subject=issue.ref or issue.mpn,
                    message=issue.message,
                )
            )

    # Sprint 41 — placement-readiness gate. Re-categorize validator
    # findings that block PCB placement into a hard-error category,
    # and append orphan-interface detections derived from the IR.
    from .placement_readiness import placement_readiness_issues

    for issue in placement_readiness_issues(validator_results, compiled.ir, compiled.components):
        categories["placement_readiness"].append(
            ValidationMessage(
                category="placement_readiness",
                code=issue.code,
                level=issue.level,
                subject=issue.ref or issue.mpn,
                message=issue.message,
                suggestion=issue.suggestion,
            )
        )

    def _has_errors(msgs: list[ValidationMessage]) -> bool:
        return any(m.level == "error" for m in msgs)

    can_check_artifacts = (
        not _has_errors(categories["structural"])
        and not _has_errors(categories["electrical"])
        and not _has_errors(categories["implementation"])
        and not _has_errors(categories["placement_readiness"])
    )
    if can_check_artifacts:
        with tempfile.TemporaryDirectory(prefix="schematic_mvp_validate_a_") as tmp_a:
            try:
                files_a, root_a = _generate_compiled_artifacts(compiled, Path(tmp_a), export_svg=True)
                if root_a is None:
                    categories["implementation"].append(
                        ValidationMessage(
                            category="implementation",
                            code="missing-root-schematic",
                            level="error",
                            subject=compiled.metadata.get("project", "project"),
                            message="Artifact generation did not produce a root schematic",
                        )
                    )

                # Sprint 45 Bug 3 — only run the second generation pass when
                # determinism checking is requested. generate_artifacts() skips
                # this because it will produce the real artifact immediately
                # afterward; running validate's dual-pass + generate's real pass
                # was 3 generations per CLI invoke. With the flag default-on,
                # direct ``validate`` callers still get full coverage.
                if check_determinism:
                    with tempfile.TemporaryDirectory(prefix="schematic_mvp_validate_b_") as tmp_b:
                        _files_b, _root_b = _generate_compiled_artifacts(
                            compiled, Path(tmp_b), export_svg=False
                        )
                        if _kicad_text_map(Path(tmp_a)) != _kicad_text_map(Path(tmp_b)):
                            categories["implementation"].append(
                                ValidationMessage(
                                    category="implementation",
                                    code="nondeterministic-generation",
                                    level="error",
                                    subject=compiled.metadata.get("project", "project"),
                                    message=(
                                        "Repeated stable-UUID generation produced different "
                                        "KiCad schematic text"
                                    ),
                                )
                            )

                categories["presentation"].extend(_presentation_issues(Path(tmp_a)))
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or exc.stdout or str(exc)).strip()
                categories["implementation"].append(
                    ValidationMessage(
                        category="implementation",
                        code="kicad-export-failed",
                        level="error",
                        subject=compiled.metadata.get("project", "project"),
                        message=f"KiCad CLI load/export smoke failed: {detail}",
                    )
                )
            except Exception as exc:
                categories["implementation"].append(
                    ValidationMessage(
                        category="implementation",
                        code="artifact-generation-failed",
                        level="error",
                        subject=compiled.metadata.get("project", "project"),
                        message=f"Derived artifact generation failed: {exc}",
                    )
                )

    summary = {key: len(value) for key, value in categories.items()}
    error_count = sum(1 for msgs in categories.values() for m in msgs if m.level == "error")
    warning_count = sum(1 for msgs in categories.values() for m in msgs if m.level == "warning")
    if strict:
        valid = (error_count + warning_count) == 0
    else:
        valid = error_count == 0
    return ValidationReport(
        profile=profile,
        valid=valid,
        categories=categories,
        summary=summary,
        metadata={
            "project": compiled.metadata.get("project", "project"),
            "component_count": len(compiled.components),
            "block_count": len(compiled.ir.blocks),
        },
    )


def generate_design_checklist(report: ValidationReport, components=None) -> str:
    """Generate a human-readable pre-fabrication design checklist.

    Returns a Markdown string summarizing the design health and actionable items.
    """
    lines = ["# Design Validation Checklist", ""]
    proj = report.metadata.get("project", "project")
    lines.append(f"**Project:** {proj}")
    lines.append(f"**Status:** {'PASS' if report.valid else 'FAIL'}")
    lines.append(f"**Components:** {report.metadata.get('component_count', '?')}")
    lines.append(f"**Blocks:** {report.metadata.get('block_count', '?')}")
    lines.append("")

    # Checklist items derived from validation categories. Sprint 41
    # placement-blocking items (dangling nets, missing pull-ups,
    # floating enables, orphan interfaces) now live under the
    # ``placement_readiness`` category and are hard-gated at
    # ``generate_artifacts`` time.
    checklist = [
        ("All power pins connected", "placement_readiness", "floating-power-pin", "missing-power-net"),
        ("All bypass caps placed", "electrical", "decoupling"),
        ("All enable pins driven", "placement_readiness", "floating-enable"),
        ("No floating inputs", "electrical", "floating-input-pin"),
        ("Bus pull-ups present", "placement_readiness", "i2c-missing-pullup"),
        ("No output conflicts", "electrical", "output-conflict"),
        ("No dangling nets", "placement_readiness", "single-pin-net"),
        ("No orphan interfaces", "placement_readiness", "orphan-interface"),
        ("Crystal load caps matched", "electrical", "crystal-load"),
        ("Feedback dividers correct", "electrical", "feedback-divider"),
        ("All blocks resolved", "structural", "unresolved-block", "unresolved-component"),
        ("Footprints assigned", "implementation", "missing-footprint"),
    ]

    lines.append("## Checklist")
    lines.append("")
    for label, category, *codes in checklist:
        msgs = report.categories.get(category, [])
        has_issue = any(m.code in codes for m in msgs)
        mark = "x" if not has_issue else " "
        lines.append(f"- [{mark}] {label}")

    # Issues summary
    all_issues = [m for msgs in report.categories.values() for m in msgs]
    errors = [m for m in all_issues if m.level == "error"]
    warnings = [m for m in all_issues if m.level == "warning"]

    if errors:
        lines.append("")
        lines.append(f"## Errors ({len(errors)})")
        lines.append("")
        for m in errors:
            lines.append(f"- **{m.subject}**: {m.message}")

    if warnings:
        lines.append("")
        lines.append(f"## Warnings ({len(warnings)})")
        lines.append("")
        for m in warnings[:20]:  # Cap at 20 to avoid overwhelming output
            lines.append(f"- {m.subject}: {m.message}")
        if len(warnings) > 20:
            lines.append(f"- ... and {len(warnings) - 20} more")

    lines.append("")
    return "\n".join(lines)


def apply_design_patch(
    spec: dict[str, Any],
    patch: dict[str, Any],
    *,
    profile: str = _STANDARD_PROFILE,
    enrich_parts: bool = False,
) -> dict[str, Any]:
    """Apply a design patch transactionally and validate before acceptance."""
    profile = _ensure_profile(profile)
    patch = _normalize_design_patch(patch)
    original_ir = normalize_design_spec(spec)
    working_ir = normalize_design_spec(spec)

    metadata_updates = patch.get("set_metadata") or {}
    if isinstance(metadata_updates, dict):
        for key, value in metadata_updates.items():
            if value is None:
                working_ir.metadata.pop(key, None)
            else:
                working_ir.metadata[key] = value

    remove_blocks = {str(item).strip() for item in (patch.get("remove_blocks") or []) if str(item).strip()}
    if remove_blocks:
        filtered = []
        for block in working_ir.blocks:
            if block.id in remove_blocks or block.ref in remove_blocks:
                continue
            filtered.append(block)
        working_ir.blocks = filtered

    upsert_blocks = patch.get("upsert_blocks") or []
    if upsert_blocks:
        block_map = {block.id: block for block in working_ir.blocks}
        ref_map = {block.ref: block.id for block in working_ir.blocks if block.ref}
        for raw_block in upsert_blocks:
            candidate = normalize_design_spec(
                {
                    **working_ir.metadata,
                    "blocks": [raw_block],
                    "interfaces": [],
                    "approved_overrides": [],
                    "pcb_constraints": [],
                }
            ).blocks[0]
            existing = block_map.get(candidate.id)
            if existing is None and candidate.ref and candidate.ref in ref_map:
                existing = block_map.get(ref_map[candidate.ref])
            if existing is not None:
                block_map.pop(existing.id, None)
            block_map[candidate.id] = candidate
        working_ir.blocks = [block_map[key] for key in sorted(block_map)]

    current_ref_map = {block.ref: block.id for block in working_ir.blocks if block.ref}
    interfaces_map: dict[tuple[str, str], DesignInterface] = {
        (iface.block_id, iface.name): iface for iface in working_ir.interfaces
    }
    for raw_iface in patch.get("upsert_interfaces") or []:
        if not isinstance(raw_iface, dict):
            continue
        raw_block_id = str(raw_iface.get("block_id") or raw_iface.get("ref") or "").strip()
        resolved_block_id = current_ref_map.get(raw_block_id, raw_block_id)
        iface = DesignInterface(
            block_id=resolved_block_id,
            name=str(raw_iface.get("name", "")).strip(),
            direction=str(raw_iface.get("direction", "bidirectional")).strip(),
            description=str(raw_iface.get("description", "")).strip(),
        ).normalized()
        interfaces_map[(iface.block_id, iface.name)] = iface

    for raw_iface in patch.get("remove_interfaces") or []:
        if isinstance(raw_iface, str):
            block_id, _, name = raw_iface.partition(":")
            key = (current_ref_map.get(block_id.strip(), block_id.strip()), name.strip())
        elif isinstance(raw_iface, dict):
            key = (
                current_ref_map.get(
                    str(raw_iface.get("block_id") or raw_iface.get("ref") or "").strip(),
                    str(raw_iface.get("block_id") or raw_iface.get("ref") or "").strip(),
                ),
                str(raw_iface.get("name", "")).strip(),
            )
        else:
            continue
        interfaces_map.pop(key, None)

    block_interfaces: dict[str, list[DesignInterface]] = {}
    for iface in interfaces_map.values():
        block_interfaces.setdefault(iface.block_id, []).append(iface)

    working_ir.blocks = [
        DesignBlock(
            id=block.id,
            section=block.section,
            kind=block.kind,
            ref=block.ref,
            template_type=block.template_type,
            ic=block.ic,
            params=copy.deepcopy(block.params),
            value=block.value,
            description=block.description,
            mpn=block.mpn,
            required_support=copy.deepcopy(block.required_support),
            part_bindings=copy.deepcopy(block.part_bindings),
            presentation_group=block.presentation_group,
            interfaces=block_interfaces.get(block.id, []),
        ).normalized()
        for block in working_ir.blocks
    ]
    working_ir.interfaces = [iface for block in working_ir.blocks for iface in block.interfaces]

    if "approved_overrides" in patch:
        updated = copy.deepcopy(working_ir.to_dict())
        updated["approved_overrides"] = patch.get("approved_overrides") or []
        working_ir = normalize_design_spec(updated)
    if "pcb_constraints" in patch:
        updated = copy.deepcopy(working_ir.to_dict())
        updated["pcb_constraints"] = patch.get("pcb_constraints") or []
        working_ir = normalize_design_spec(updated)

    updated_spec = design_ir_to_spec(working_ir)
    report = validate_design(updated_spec, profile=profile, enrich_parts=enrich_parts)
    if not report.valid:
        return {
            "accepted": False,
            "updated_spec": None,
            "report": report.to_dict(),
            "diff": semantic_diff(design_ir_to_spec(original_ir), updated_spec),
        }

    return {
        "accepted": True,
        "updated_spec": updated_spec,
        "report": report.to_dict(),
        "diff": semantic_diff(design_ir_to_spec(original_ir), updated_spec),
    }


def _auto_source_report(
    components: list[Any],
    spec: dict[str, Any],
    spec_path: Path | None = None,
    update_spec: bool = False,
) -> dict[str, Any]:
    """Auto-discover MPNs/LCSC for unresolved components via DigiKey/Mouser APIs.

    Returns dict with resolution summary:
    {
        "resolved": count,
        "total": count,
        "by_source": {"digikey": N, "mouser": N, "lcsc": N},
        "unresolved_count": N,
        "unresolved": [{"mpn": "", "tried": [...], "suggestions": [...]}]
    }
    """
    from .parts_lookup import PartsLookup
    from .symbol_cache import SymbolCache
    from .symbol_resolver import SymbolResolver

    resolved = 0
    unresolved = []
    by_source = {"digikey": 0, "mouser": 0, "lcsc": 0}

    # Initialize resolvers
    cache = SymbolCache()
    resolver = SymbolResolver(cache=cache, use_digikey=True, use_mouser=True, use_easyeda=True)
    lookup = PartsLookup()

    # Track which components need sourcing
    sourced_data = {}

    for comp in components:
        mpn = comp.mpn or comp.value or ""
        if not mpn:
            continue

        # Skip if already has LCSC or DigiKey PN
        if comp.lcsc_pn or comp.digikey_pn:
            resolved += 1
            continue

        # Try PartsLookup first (existing local database)
        lookup_result = lookup.lookup(mpn)
        if lookup_result:
            sourced_data[mpn] = lookup_result
            resolved += 1
            by_source["lcsc"] += 1
            continue

        # Try SymbolResolver (DigiKey → Mouser tiers)
        comp_def, source = resolver.resolve(mpn)
        if comp_def and source != "unresolved":
            sourced_data[mpn] = {
                "mpn": mpn,
                "source": source,
                "footprint": comp_def.footprint,
                "description": comp_def.description,
                "digikey_pn": comp_def.digikey_pn,
                "lcsc_pn": comp_def.lcsc_pn,
            }
            resolved += 1
            if source in by_source:
                by_source[source] += 1
        else:
            unresolved.append(
                {
                    "mpn": mpn,
                    "tried": ["PartsLookup", "DigiKey", "Mouser"],
                    "suggestions": [],
                }
            )

    # Write back to spec if requested
    if update_spec and spec_path and sourced_data:
        from .project_spec import update_spec_with_sourced_data

        update_spec_with_sourced_data(spec_path, sourced_data)

    return {
        "resolved": resolved,
        "total": len(components),
        "by_source": by_source,
        "unresolved_count": len(unresolved),
        "unresolved": unresolved,
    }


def _export_placement_artifact(
    components: list[ComponentDef],
    output_path: Path,
    project_name: str,
) -> Path:
    """Export an editable placement SVG backed by the compiled components."""
    from .placement_optimizer import PlacementConfig, optimize_placement
    from .svg_placement import export_placement_svg

    component_dicts = [
        {
            "ref": comp.source_ref,
            "value": comp.value or comp.mpn,
            "footprint": comp.footprint,
            "category": comp.category,
        }
        for comp in components
        if comp.source_ref
    ]
    placement = optimize_placement(components, config=PlacementConfig(strategy="simple"))
    placements = placement.get("placements", {})
    if component_dicts and not placements:
        raise ValueError("Placement SVG requested, but no compiled component placements were produced")

    svg_path = _contained_output_path(output_path, "placement.svg")
    export_placement_svg(
        component_dicts,
        placements,
        float(placement.get("board_width_mm", 100.0)),
        float(placement.get("board_height_mm", 80.0)),
        output_path=svg_path,
        title=f"PCB Placement — {project_name}",
    )
    return svg_path


def _artifact_kind(path: Path) -> str:
    """Return a stable coarse type for an artifact-manifest entry."""
    if path.suffix == ".kicad_sch":
        return "schematic"
    if path.suffix == ".kicad_pcb":
        return "pcb"
    if path.suffix == ".svg":
        return "preview"
    if path.suffix in {".json", ".yaml", ".yml", ".csv", ".md", ".html"}:
        return "report"
    if path.suffix in {".log", ".jsonl"}:
        return "log"
    return "artifact"


def _acquire_generation_fd(fd: int) -> None:
    """Acquire one byte of *fd* exclusively without waiting."""
    os.lseek(fd, 0, os.SEEK_SET)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release_generation_fd(fd: int) -> None:
    """Release the advisory lock held on *fd*."""
    os.lseek(fd, 0, os.SEEK_SET)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(fd, fcntl.LOCK_UN)


@contextlib.contextmanager
def _generation_output_lock(output_path: Path) -> Iterator[Path]:
    """Exclusively lease an artifact directory for one generation run.

    The lock file intentionally remains in place after release.  Advisory
    locks are released by the operating system if a process crashes, while a
    persistent inode prevents a later process from bypassing an active lock by
    racing an unlink/recreate cleanup scheme.
    """
    lock_path = _contained_output_path(output_path, _GENERATION_LOCK_FILENAME)
    if lock_path.is_symlink():
        raise ValueError(f"Generation lock path must not be a symlink: {lock_path}")
    if lock_path.exists() and not lock_path.is_file():
        raise ValueError(f"Generation lock path must be a regular file: {lock_path}")

    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise ValueError(f"Could not open generation lock file '{lock_path}': {exc}") from exc

    acquired = False
    try:
        os.set_inheritable(fd, False)
        opened_stat = os.fstat(fd)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise ValueError(f"Generation lock path must be a regular file: {lock_path}")
        try:
            path_stat = lock_path.stat()
        except OSError as exc:
            raise ValueError(f"Generation lock path changed while it was opened: {lock_path}") from exc
        if lock_path.is_symlink() or not os.path.samestat(opened_stat, path_stat):
            raise ValueError(f"Generation lock path changed while it was opened: {lock_path}")

        # Windows byte-range locks require a lockable byte.  Initializing the
        # persistent file before acquisition is benign even when two first-time
        # callers race: both write the same byte, then exactly one gets the lock.
        if opened_stat.st_size == 0:
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, b"\0")
            os.fsync(fd)

        try:
            _acquire_generation_fd(fd)
        except OSError as exc:
            raise ValueError(
                f"Artifact generation is already in progress for output directory '{output_path}'"
            ) from exc
        acquired = True

        # Re-check the directory entry after acquiring so a pre-open swap never
        # turns the lease into a lock on an unrelated inode.
        try:
            path_stat = lock_path.stat()
        except OSError as exc:
            raise ValueError(f"Generation lock path changed during acquisition: {lock_path}") from exc
        if lock_path.is_symlink() or not os.path.samestat(os.fstat(fd), path_stat):
            raise ValueError(f"Generation lock path changed during acquisition: {lock_path}")

        yield lock_path
    finally:
        if acquired:
            with contextlib.suppress(OSError):
                _release_generation_fd(fd)
        os.close(fd)


def _output_file_snapshot(output_path: Path) -> dict[str, tuple[int, int]]:
    """Return a lightweight snapshot used to isolate one generation run.

    Output directories are intentionally reusable and may contain user-owned
    notes or artifacts from an older design.  Recording their size and
    nanosecond timestamp lets the current run include newly written files
    without claiming unchanged pre-existing files as its own.
    """
    snapshot: dict[str, tuple[int, int]] = {}
    for path in output_path.rglob("*"):
        if not path.is_file():
            continue
        if path.relative_to(output_path).as_posix() == _GENERATION_LOCK_FILENAME:
            continue
        stat = path.stat()
        snapshot[path.relative_to(output_path).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


def _path_in_output(output_path: Path, path: str | Path) -> Path | None:
    """Return *path* in the output directory, rejecting paths outside it."""
    output_resolved = output_path.resolve()
    candidate = Path(path).resolve()
    try:
        relative = candidate.relative_to(output_resolved)
    except ValueError:
        return None
    return output_path / relative


def _current_run_artifacts(
    output_path: Path,
    baseline: Mapping[str, tuple[int, int]],
    explicit_paths: Iterable[str | Path] = (),
) -> list[Path]:
    """Collect only files produced or explicitly claimed by this invocation."""
    explicit_relative: set[str] = set()
    for value in explicit_paths:
        path = _path_in_output(output_path, value)
        if path is not None:
            explicit_relative.add(path.relative_to(output_path).as_posix())

    current: list[Path] = []
    for path in output_path.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(output_path).as_posix()
        if relative == _GENERATION_LOCK_FILENAME:
            continue
        stat = path.stat()
        signature = (stat.st_size, stat.st_mtime_ns)
        if relative in explicit_relative or baseline.get(relative) != signature:
            current.append(path)
    return sorted(current, key=lambda item: item.relative_to(output_path).as_posix())


def _manifest_relative_path(output_path: Path, path: str | Path | None) -> str:
    """Return a portable output-root-relative identity for a manifest path."""
    if path is None or str(path) == "":
        return ""
    candidate = _path_in_output(output_path, path)
    if candidate is None:
        return ""
    return candidate.relative_to(output_path).as_posix()


def _invalidate_artifact_manifest(output_path: Path) -> Path:
    """Remove any prior success manifest before this run mutates its output."""
    manifest_path = _contained_output_path(output_path, "artifact_manifest.json")
    if not (manifest_path.exists() or manifest_path.is_symlink()):
        return manifest_path
    if manifest_path.is_dir() and not manifest_path.is_symlink():
        raise ValueError(
            f"Reserved artifact manifest path is a directory and cannot be replaced: {manifest_path}"
        )
    try:
        manifest_path.unlink()
    except OSError as exc:
        raise ValueError(f"Could not invalidate prior artifact manifest: {manifest_path}") from exc
    if manifest_path.exists() or manifest_path.is_symlink():
        raise ValueError(f"Prior artifact manifest still exists after removal: {manifest_path}")
    return manifest_path


def _write_artifact_manifest(
    output_path: Path,
    project_name: str,
    root: Path | None,
    *,
    artifact_paths: Iterable[Path] | None = None,
    valid: bool | None = None,
    kicad_verified: bool | None = None,
    verification_status: str | None = None,
    erc: Mapping[str, Any] | None = None,
) -> Path:
    """Write a portable machine-readable inventory for this generation run."""
    manifest_path = _contained_output_path(output_path, "artifact_manifest.json")
    artifacts = []
    candidates = artifact_paths
    if candidates is None:
        candidates = (item for item in output_path.rglob("*") if item.is_file())
    unique_candidates: dict[str, Path] = {}
    for value in candidates:
        path = _path_in_output(output_path, value)
        if path is None or not path.is_file() or path == manifest_path:
            continue
        relative = path.relative_to(output_path).as_posix()
        if relative == _GENERATION_LOCK_FILENAME:
            continue
        unique_candidates[relative] = path
    for relative, path in sorted(unique_candidates.items()):
        artifacts.append(
            {
                "path": relative,
                "relative_path": relative,
                "kind": _artifact_kind(path),
                "size_bytes": path.stat().st_size,
            }
        )

    root_identity = _manifest_relative_path(output_path, root)
    erc_payload = copy.deepcopy(dict(erc or {}))
    erc_payload.setdefault("status", "not-applicable" if root is None else "not-run")
    erc_payload.setdefault("schematic", root_identity)
    erc_payload.setdefault("errors", 0)
    erc_payload.setdefault("warnings", 0)
    erc_payload.setdefault("skip_reason", "")
    erc_payload.setdefault("violations", [])
    # ERC runners naturally report the host path they inspected.  That path is
    # dead as soon as an API temporary directory is zipped, so the manifest
    # carries the same root-relative identity as the rest of the archive.
    erc_payload["schematic"] = root_identity if root is not None else ""
    payload = {
        "schema_version": 2,
        "project": project_name,
        "root_schematic": root_identity,
        "valid": valid,
        "kicad_verified": kicad_verified,
        "verification_status": verification_status,
        "erc": erc_payload,
        "artifacts": artifacts,
    }
    serialized = json.dumps(payload, indent=2)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=output_path,
            prefix=".artifact_manifest.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(manifest_path)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
    return manifest_path


def generate_artifacts(
    spec: dict[str, Any],
    *,
    output_dir: str | Path,
    profile: str = _STANDARD_PROFILE,
    require_valid: bool = True,
    enrich_parts: bool = False,
    export_svg: bool = True,
    score: bool = False,
    auto_source: bool = False,
    update_spec: bool = False,
    spec_path: Path | None = None,
    svg_placement: bool = False,
    export_pinout: bool = False,
    readiness_gate: bool = True,
    require_kicad: bool = False,
) -> dict[str, Any]:
    """Generate artifacts while exclusively leasing the output directory."""
    if not isinstance(spec, dict):
        raise TypeError("Design spec must be a mapping")
    raw_project: Any = spec.get("project")
    if raw_project is None and isinstance(spec.get("engine"), dict):
        raw_project = spec["engine"].get("project")
    if raw_project is None and isinstance(spec.get("metadata"), dict):
        raw_project = spec["metadata"].get("project_name")
    _validate_project_name(raw_project if raw_project is not None else "project")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    # Reject escaped fixed targets before creating the persistent lock file.
    # The same checks are repeated while locked before any artifact write.
    manifest_path = _contained_output_path(output_path, "artifact_manifest.json")
    _contained_output_path(output_path, "circuit-weaver.log")
    _contained_output_path(output_path, "design.log")
    if manifest_path.is_dir() and not manifest_path.is_symlink():
        raise ValueError(
            f"Reserved artifact manifest path is a directory and cannot be replaced: {manifest_path}"
        )
    # Design logging is process-global, so different output directories cannot
    # safely generate concurrently within one interpreter.  Serialize the
    # engine/logging lifetime, then acquire the cross-process per-output lease.
    with _GENERATION_PROCESS_LOCK, _generation_output_lock(output_path):
        return _generate_artifacts_locked(
            spec,
            output_dir=output_path,
            profile=profile,
            require_valid=require_valid,
            enrich_parts=enrich_parts,
            export_svg=export_svg,
            score=score,
            auto_source=auto_source,
            update_spec=update_spec,
            spec_path=spec_path,
            svg_placement=svg_placement,
            export_pinout=export_pinout,
            readiness_gate=readiness_gate,
            require_kicad=require_kicad,
        )


def _generate_artifacts_locked(
    spec: dict[str, Any],
    *,
    output_dir: str | Path,
    profile: str = _STANDARD_PROFILE,
    require_valid: bool = True,
    enrich_parts: bool = False,
    export_svg: bool = True,
    score: bool = False,
    auto_source: bool = False,
    update_spec: bool = False,
    spec_path: Path | None = None,
    svg_placement: bool = False,
    export_pinout: bool = False,
    readiness_gate: bool = True,
    require_kicad: bool = False,
) -> dict[str, Any]:
    """Generate derived artifacts from a validated design spec."""
    if not isinstance(spec, dict):
        raise TypeError("Design spec must be a mapping")
    raw_project: Any = spec.get("project")
    if raw_project is None and isinstance(spec.get("engine"), dict):
        raw_project = spec["engine"].get("project")
    if raw_project is None and isinstance(spec.get("metadata"), dict):
        raw_project = spec["metadata"].get("project_name")
    _validate_project_name(raw_project if raw_project is not None else "project")

    profile = _ensure_profile(profile)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    # Preflight every logger/manifest target before any handler can follow a
    # pre-existing symlink.  The helpers called below construct these same
    # names internally, so resolved containment here is the write boundary.
    _contained_output_path(output_path, "artifact_manifest.json")
    circuit_log_path = _contained_output_path(output_path, "circuit-weaver.log")
    design_log_path = _contained_output_path(output_path, "design.log")
    _invalidate_artifact_manifest(output_path)
    output_baseline = _output_file_snapshot(output_path)
    tracked_artifacts: list[str | Path] = [circuit_log_path, design_log_path]

    # Set up logging: use unified bridge if not already initialized, else fallback
    from .logging_bridge import cleanup_logging, get_design_logger, init_logging

    _owned_logging = False
    if get_design_logger() is None:
        init_logging(output_path)
        _owned_logging = True
    else:
        # Bridge already active -- still write circuit-weaver.log to output dir
        _local_fh = logging.FileHandler(circuit_log_path, mode="w", encoding="utf-8")
        _local_fh.setLevel(logging.DEBUG)
        _local_fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.getLogger("circuit_weaver").addHandler(_local_fh)

    try:
        # Sprint 45 Bug 3 — skip the determinism dual-pass here because
        # the real generation immediately follows; validate's smoke pass
        # is enough to catch structural / KiCad-load failures, and we
        # don't want 3 generations per CLI invoke.
        report = validate_design(
            spec,
            profile=profile,
            enrich_parts=enrich_parts,
            check_determinism=False,
        )

        # Sprint 40 Task 173 + Sprint 41 — generate enforcement is
        # deterministic regardless of the ``require_valid`` flag.
        # Structural and implementation errors always block here.
        # Placement-readiness is enforced one layer lower inside
        # generator.generate_from_components so direct generator callers
        # inherit the same guarantee, and a single readiness_gate flag can
        # intentionally bypass it for debug/diff workflows.
        #
        # ``--no-require-valid`` only bypasses soft
        # electrical warnings (crystal-load tolerance, rc/lc-filter
        # tuning, cap-voltage derating, power-budget hints) — it cannot
        # paper over a schematic that is physically unfinished.
        _HARD_ERROR_CATEGORIES = ("structural", "implementation")
        hard_errors = [
            msg
            for category in _HARD_ERROR_CATEGORIES
            for msg in report.categories.get(category, [])
            if getattr(msg, "level", "") == "error"
        ]
        if hard_errors:
            _logger.error(
                "Design has %d hard validation error(s) in %s categories — blocking generation: %s",
                len(hard_errors),
                "/".join(_HARD_ERROR_CATEGORIES),
                report.summary,
            )
            raise ValueError(
                f"Design has {len(hard_errors)} structural/implementation "
                "error(s) — fix these before generation (these are not bypassable via "
                "--no-require-valid)"
            )
        if require_valid and not report.valid:
            _logger.error("Design failed standard validation: %s", report.summary)
            raise ValueError("Design failed standard validation")
        if not require_valid and not report.valid:
            _logger.warning(
                "--no-require-valid: proceeding despite soft validation warnings: %s",
                report.summary,
            )

        compiled = compile_design_ir(spec, enrich_parts=enrich_parts)
        files, root = _generate_compiled_artifacts(
            compiled,
            output_path,
            export_svg=export_svg,
            score=score,
            readiness_gate=readiness_gate,
        )
        tracked_artifacts.extend(files)
    except Exception:
        _logger.exception("Artifact generation failed for output directory %s", output_path)
        raise
    finally:
        if _owned_logging:
            cleanup_logging()
        elif "_local_fh" in dir():
            logging.getLogger("circuit_weaver").removeHandler(_local_fh)  # type: ignore[possibly-undefined]
            _local_fh.close()  # type: ignore[possibly-undefined]

    # Resolve all fixed report targets before opening the first one so a
    # pre-existing symlink cannot redirect any post-generation write.
    canonical_spec_path = _contained_output_path(output_path, "canonical_spec.yaml")
    ir_path = _contained_output_path(output_path, "design_ir.json")
    report_path = _contained_output_path(output_path, "validation_report.json")
    placement_ready_path = _contained_output_path(output_path, "placement_readiness.json")
    canonical_spec_path.write_text(spec_to_yaml_text(compiled.ir.to_dict()), encoding="utf-8", newline="")
    ir_path.write_text(json.dumps(compiled.ir.to_dict(), indent=2), encoding="utf-8", newline="")
    report_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8", newline="")
    tracked_artifacts.extend((canonical_spec_path, ir_path, report_path))

    # Sprint 41 — placement readiness report. Shape is stable; consumed
    # by the placement pipeline and downstream agents to decide whether
    # the schematic is ready for forward-annotation.
    pr_category = report.categories.get("placement_readiness", [])
    repair_actions = list(getattr(compiled, "repair_actions", []) or [])
    pr_summary = {
        "errors": sum(1 for m in pr_category if m.level == "error"),
        "warnings": sum(1 for m in pr_category if m.level == "warning"),
        "repairs_applied": len(repair_actions),
    }
    placement_ready_payload = {
        "ready": pr_summary["errors"] == 0,
        "blocking": [asdict(m) for m in pr_category if m.level == "error"],
        "auto_repaired": repair_actions,
        "summary": pr_summary,
    }
    placement_ready_path.write_text(
        json.dumps(placement_ready_payload, indent=2), encoding="utf-8", newline=""
    )
    tracked_artifacts.append(placement_ready_path)

    project_name = _validate_project_name(compiled.metadata.get("project", "project"))
    result = {
        "output_dir": str(output_path),
        "project": project_name,
        "root_schematic": str(root) if root else "",
        "files": [str(path) for path in files],
        "validation_report": str(report_path),
        "design_ir": str(ir_path),
        "canonical_spec": str(canonical_spec_path),
        "placement_readiness": str(placement_ready_path),
        "valid": report.valid,
    }

    # Test-point annotations are a report artifact, not electrical connectivity.
    # Keep the final KiCad schematic immutable after generation so validation and
    # downstream users always inspect the same bytes.
    from .test_point_gen import generate_test_point_artifacts

    _contained_output_path(output_path, f"{project_name}_test_points.csv")
    tp_result = generate_test_point_artifacts(
        compiled.ir,
        output_path,
        project_name=project_name,
        schematic_path=None,
    )
    result["test_points"] = tp_result
    csv_path = tp_result.get("csv_path")
    if csv_path:
        tracked_artifacts.append(csv_path)

    if svg_placement:
        placement_svg = _export_placement_artifact(compiled.components, output_path, project_name)
        result["placement_svg"] = str(placement_svg)
        tracked_artifacts.append(placement_svg)

    # Task 120: Emit pinout CSV for MCU components (auto when MCUs present, or forced via flag)
    from .firmware_export import export_esp32_sdkconfig, export_pinout_csv, export_stm32_ioc, is_mcu

    has_mcu = any(is_mcu(c) for c in compiled.components)
    if export_pinout or has_mcu:
        pinout_path = _contained_output_path(output_path, f"{project_name}_pinout.csv")
        written = export_pinout_csv(compiled.components, pinout_path, mcu_only=not export_pinout)
        if written:
            result["pinout_csv"] = str(written)
            tracked_artifacts.append(written)

    # Tasks 121 + 122: MCU-specific config stubs
    for comp in compiled.components:
        if comp.mpn.upper().startswith("STM32"):
            ioc_path = _contained_output_path(output_path, f"{project_name}.ioc")
            written_ioc = export_stm32_ioc(comp, project_name, ioc_path)
            if written_ioc:
                result["stm32_ioc"] = str(written_ioc)
                tracked_artifacts.append(written_ioc)
        if comp.mpn.upper().startswith("ESP32"):
            sdk_path = _contained_output_path(output_path, "sdkconfig.defaults")
            written_sdk = export_esp32_sdkconfig(comp, project_name, sdk_path)
            if written_sdk:
                result["esp32_sdkconfig"] = str(written_sdk)
                tracked_artifacts.append(written_sdk)

    # Task 86: Auto-source MPNs/LCSC for unresolved components
    if auto_source:
        auto_source_result = _auto_source_report(
            compiled.components,
            spec,
            spec_path=spec_path if update_spec else None,
            update_spec=update_spec,
        )
        result["auto_source_summary"] = auto_source_result

    # Validate the exact final schematic bytes after all post-processing.  This
    # is deliberately separate from the source-spec validator.
    from .sexpr_builder import validate_sexpr_balance

    current_artifacts = _current_run_artifacts(output_path, output_baseline, tracked_artifacts)
    invalid_schematics = [
        path
        for path in current_artifacts
        if path.suffix == ".kicad_sch"
        if not validate_sexpr_balance(path.read_text(encoding="utf-8"), str(path))
    ]
    if invalid_schematics:
        names = ", ".join(path.name for path in invalid_schematics)
        raise ValueError(f"Generated schematic S-expression validation failed: {names}")

    result["kicad_verified"] = False
    result["verification_status"] = "not-applicable" if root is None else "unverified"
    result["erc"] = {
        "status": "not-applicable",
        "schematic": "",
        "errors": 0,
        "warnings": 0,
        "skip_reason": "",
        "violations": [],
    }
    if root is None:
        if require_kicad:
            raise ValueError("KiCad verification was required, but no root schematic was generated")
    else:
        from .erc_runner import run_erc

        erc_result = run_erc(root)
        result["erc"] = erc_result.to_dict()
        if erc_result.status == "ok" and erc_result.errors == 0:
            result["kicad_verified"] = True
            result["verification_status"] = "verified"
        elif erc_result.status == "skipped":
            if require_kicad:
                raise ValueError(f"KiCad verification was required but skipped: {erc_result.skip_reason}")
        elif erc_result.status == "failed":
            result["valid"] = False
            result["verification_status"] = "failed"
            raise ValueError(f"Final KiCad verification failed: {erc_result.skip_reason}")
        else:
            result["valid"] = False
            result["verification_status"] = "failed"
            raise ValueError(f"Final KiCad ERC found {erc_result.errors} error(s)")

    current_artifacts = _current_run_artifacts(output_path, output_baseline, tracked_artifacts)
    manifest_path = _write_artifact_manifest(
        output_path,
        project_name,
        root,
        artifact_paths=current_artifacts,
        valid=result["valid"],
        kicad_verified=result["kicad_verified"],
        verification_status=result["verification_status"],
        erc=result["erc"],
    )
    result["artifact_manifest"] = str(manifest_path)
    result["files"] = [str(path) for path in [*current_artifacts, manifest_path]]

    return result


def ingest_pcb_feedback(
    spec: dict[str, Any],
    feedback: dict[str, Any],
) -> ConstraintFeedbackReport:
    """Merge PCB-derived constraints/approved substitutions into canonical spec."""
    ir = normalize_design_spec(spec)
    accepted_constraints = 0
    accepted_overrides = 0
    rejected: list[dict[str, Any]] = []

    for item in feedback.get("constraints", []) or []:
        if not isinstance(item, dict) or not item.get("kind") or not item.get("target"):
            rejected.append({"item": copy.deepcopy(item), "reason": "Constraint must declare kind and target"})
            continue
        ir.pcb_constraints.append(copy.deepcopy(item))
        accepted_constraints += 1

    for section_name, kind in (
        ("placement_constraints", "placement"),
        ("keepouts", "keepout"),
        ("length_constraints", "length_match"),
        ("net_classes", "net_class"),
        ("route_channels", "route_channel"),
    ):
        for item in feedback.get(section_name, []) or []:
            if not isinstance(item, dict) or not item.get("target"):
                rejected.append({"item": copy.deepcopy(item), "reason": f"{section_name} entries must declare target"})
                continue
            constraint = {"kind": kind, **copy.deepcopy(item)}
            ir.pcb_constraints.append(constraint)
            accepted_constraints += 1

    for item in feedback.get("approved_substitutions", []) or []:
        if not isinstance(item, dict) or not item.get("target"):
            rejected.append({"item": copy.deepcopy(item), "reason": "Approved substitutions must declare target"})
            continue
        override = {
            "kind": "part_binding",
            "target": str(item["target"]),
            "value": {key: item[key] for key in ("mpn", "value", "footprint") if item.get(key)},
            "source": "pcb_feedback",
        }
        ir.approved_overrides.append(override)
        accepted_overrides += 1

    for item in feedback.get("footprint_substitutions", []) or []:
        if not isinstance(item, dict) or not item.get("target") or not item.get("footprint"):
            rejected.append(
                {
                    "item": copy.deepcopy(item),
                    "reason": "Footprint substitutions must declare target and footprint",
                }
            )
            continue
        ir.approved_overrides.append(
            {
                "kind": "footprint_override",
                "target": str(item["target"]),
                "value": str(item["footprint"]),
                "source": "pcb_feedback",
            }
        )
        accepted_overrides += 1

    updated_spec = design_ir_to_spec(ir)
    return ConstraintFeedbackReport(
        accepted_constraints=accepted_constraints,
        accepted_overrides=accepted_overrides,
        rejected=rejected,
        updated_spec=updated_spec,
    )


def diff_designs(old_spec: dict[str, Any], new_spec: dict[str, Any]) -> dict[str, Any]:
    return semantic_diff(old_spec, new_spec)


def _simple_yaml_dump(value: Any, indent: int = 0) -> str:
    prefix = " " * indent
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.append(_simple_yaml_dump(item, indent + 2))
            else:
                if item is None:
                    rendered = "null"
                elif isinstance(item, bool):
                    rendered = "true" if item else "false"
                elif isinstance(item, str) and (":" in item or "#" in item):
                    rendered = json.dumps(item)
                else:
                    rendered = str(item)
                lines.append(f"{prefix}{key}: {rendered}")
        return "\n".join(lines)
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                dumped = _simple_yaml_dump(item, indent + 2).splitlines()
                if dumped:
                    lines.append(f"{prefix}- {dumped[0].lstrip()}")
                    for line in dumped[1:]:
                        lines.append(f"{' ' * (indent + 2)}{line.lstrip()}")
            else:
                if item is None:
                    rendered = "null"
                elif isinstance(item, bool):
                    rendered = "true" if item else "false"
                elif isinstance(item, str) and (":" in item or "#" in item):
                    rendered = json.dumps(item)
                else:
                    rendered = str(item)
                lines.append(f"{prefix}- {rendered}")
        return "\n".join(lines)
    return f"{prefix}{value}"


def spec_to_yaml_text(spec: dict[str, Any]) -> str:
    import yaml

    return yaml.safe_dump(spec, sort_keys=False, allow_unicode=False)


def _load_spec_file(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    return _parse_yaml(path)


def _load_patch_file(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        import yaml

        parsed = yaml.safe_load(text) or {}
        if not isinstance(parsed, dict):
            raise ValueError("Patch file must contain a top-level mapping")
        return parsed
    return json.loads(text)


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2))


def _run_with_stderr_capture(func: Any) -> Any:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = func()
    captured = buffer.getvalue()
    if captured:
        sys.stderr.write(captured)
        if not captured.endswith("\n"):
            sys.stderr.write("\n")
        sys.stderr.flush()
    return result


def _log_cli_call(
    logger: DesignLogger | None, command: str, args: list[str], func: Any, generated_files: list[str] | None = None
) -> tuple[Any, bool]:
    """Run a CLI operation and log it if a logger is available.

    Args:
        logger: DesignLogger instance (or None to skip logging)
        command: Command name (validate, generate, scaffold, etc.)
        args: Command arguments (spec file, etc.)
        func: Callable that performs the operation
        generated_files: List of files generated by this operation

    Returns:
        Tuple of (result, success) where success is True if no errors occurred
    """
    start_time = time.time()
    try:
        result = func()
        duration = time.time() - start_time
        success = result is not None and not (isinstance(result, dict) and result.get("status") == "error")

        if logger:
            logger.log_cli_call(
                command, args, 0 if success else 1, duration_sec=duration, generated_files=generated_files
            )

        return result, success
    except Exception as e:
        duration = time.time() - start_time
        if logger:
            logger.log_cli_call(command, args, 1, stderr=str(e), duration_sec=duration, generated_files=generated_files)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Transactional MVP workflow for circuit_weaver")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_p = subparsers.add_parser("validate", help="Validate a canonical/legacy design spec")
    validate_p.add_argument("spec", help="Path to YAML/JSON design spec")
    validate_p.add_argument(
        "--strict", action="store_true", default=False, help="Treat warnings as errors (fail on any warning)"
    )
    validate_p.add_argument("--enrich-parts", action="store_true", default=False)
    validate_p.add_argument(
        "--color",
        choices=["auto", "always", "never"],
        default="auto",
        help="Enable/disable ANSI colors (default: auto-detect)",
    )
    validate_p.add_argument(
        "--verbose", action="store_true", default=False, help="Print category and code for each issue"
    )
    validate_p.add_argument(
        "--detailed-score",
        action="store_true",
        default=False,
        help="Include detailed design quality scoring (power, signal, placement, thermal, mfg)",
    )
    validate_p.add_argument(
        "--enhanced",
        action="store_true",
        default=False,
        help="Run enhanced validation with cross-reference audit (thermal, SI, power budget)",
    )

    patch_p = subparsers.add_parser("apply-patch", help="Apply a transactional patch to a design spec")
    patch_p.add_argument("spec", help="Path to YAML/JSON design spec")
    patch_p.add_argument("patch", help="Path to JSON/YAML patch payload")
    patch_p.add_argument("--output", help="Write accepted updated spec to this YAML path")
    patch_p.add_argument("--enrich-parts", action="store_true", default=False)

    gen_p = subparsers.add_parser("generate", help="Generate derived KiCad artifacts from a spec")
    gen_p.add_argument("spec", help="Path to YAML/JSON design spec")
    gen_p.add_argument("--output", "-o", required=True, help="Artifact output directory")
    gen_p.add_argument("--no-require-valid", dest="require_valid", action="store_false")
    gen_p.add_argument("--no-readiness-gate", dest="readiness_gate", action="store_false")
    gen_p.add_argument("--no-svg", dest="export_svg", action="store_false")
    gen_p.add_argument("--enrich-parts", action="store_true", default=False)
    gen_p.add_argument(
        "--pinout",
        dest="export_pinout",
        action="store_true",
        default=False,
        help="Emit pinout CSV (and MCU-specific stubs) even for non-MCU designs",
    )
    gen_p.add_argument(
        "--presentation-profile",
        choices=["default", "review"],
        default=None,
        help="Override the presentation profile (default | review)",
    )
    gen_p.add_argument("--score", action="store_true", default=False, help="Run aesthetics scorer on generated layouts")
    gen_p.add_argument(
        "--auto-source",
        action="store_true",
        default=False,
        help="Auto-populate blank MPN/LCSC fields via DigiKey and Mouser lookups (Task 86)",
    )
    gen_p.add_argument(
        "--update-spec",
        action="store_true",
        default=False,
        help="Write discovered MPNs/LCSC back to YAML spec (requires --auto-source)",
    )
    gen_p.add_argument(
        "--svg-placement",
        action="store_true",
        default=False,
        help="Export SVG placement diagram after PCB generation (Task 93)",
    )
    gen_p.add_argument(
        "--require-kicad",
        action="store_true",
        default=False,
        help="Fail unless final schematics pass a real kicad-cli ERC run",
    )
    gen_p.set_defaults(require_valid=True, readiness_gate=True, export_svg=True)

    review_p = subparsers.add_parser("review-report", help="Generate comprehensive HTML design review report")
    review_p.add_argument("spec", help="Path to YAML/JSON design spec")
    review_p.add_argument("--output", "-o", required=True, help="Path to write HTML report")
    review_p.add_argument("--kicad-pcb", help="Optional path to .kicad_pcb file for DFM analysis")
    review_p.add_argument("--schematic", help="Optional path to generated .kicad_sch file for ERC status")
    review_p.add_argument("--enrich-parts", action="store_true", default=False)

    diff_p = subparsers.add_parser("diff", help="Compare two design specs — structural diff + optional SVG visual")
    diff_p.add_argument("old_spec", help="Path to the original YAML/JSON spec")
    diff_p.add_argument("new_spec", help="Path to the updated YAML/JSON spec")
    diff_p.add_argument(
        "--svg",
        action="store_true",
        default=False,
        help="Generate SVG schematics for visual comparison (requires KiCad CLI)",
    )
    diff_p.add_argument("--output", "-o", help="Write HTML diff report to file")

    pcb_p = subparsers.add_parser("ingest-pcb-feedback", help="Merge PCB feedback into a design spec")
    pcb_p.add_argument("spec", help="Path to YAML/JSON design spec")
    pcb_p.add_argument("feedback", help="Path to PCB feedback JSON/YAML")
    pcb_p.add_argument("--output", help="Write updated spec to this YAML path")

    import_placement_p = subparsers.add_parser(
        "import-placement", help="Import SVG placement edits back into .kicad_pcb and CPL"
    )
    import_placement_p.add_argument("svg", help="Path to edited SVG placement file")
    import_placement_p.add_argument("kicad_pcb", help="Path to .kicad_pcb file")
    import_placement_p.add_argument(
        "--output-pcb", "-o", help="Write updated .kicad_pcb to this path (default: overwrite)"
    )
    import_placement_p.add_argument("--output-cpl", help="Write updated CPL to this path")
    import_placement_p.add_argument(
        "--dry-run", action="store_true", default=False, help="Preview changes without writing"
    )

    list_p = subparsers.add_parser("list-templates", help="List all available subcircuit templates")
    list_p.add_argument(
        "--json", dest="json_output", action="store_true", default=False, help="Machine-readable JSON output"
    )
    list_p.add_argument("--verbose", action="store_true", default=False, help="Show full parameter schema")
    list_p.add_argument(
        "--include-data-driven",
        action="store_true",
        default=False,
        help="Also list ICs available via data-driven JSON (ic_data/)",
    )

    scaffold_p = subparsers.add_parser("scaffold", help="Generate a YAML design spec stub from a template")
    scaffold_p.add_argument("--template", "-t", help="Template type (e.g., buck, ldo, opamp)")
    scaffold_p.add_argument("--ref", default="U1", help="Reference designator (default: U1)")
    scaffold_p.add_argument("--output", "-o", help="Write to file instead of stdout")

    register_ic_p = subparsers.add_parser("register-ic", help="Register a new IC in the data-driven template system")
    register_ic_p.add_argument("--file", "-f", help="JSON file with IC data (or read from stdin)")
    register_ic_p.add_argument("--mpn", help="IC MPN (required when reading from --file with a single IC object)")

    jlcpcb_p = subparsers.add_parser("export-jlcpcb", help="Export JLCPCB BOM and CPL files for assembly ordering")
    jlcpcb_p.add_argument("spec", help="Design spec YAML file")
    jlcpcb_p.add_argument("--output", "-o", required=True, help="Output directory for BOM/CPL files")

    gerber_p = subparsers.add_parser("export-gerbers", help="Export Gerber and drill files from KiCad PCB")
    gerber_p.add_argument("kicad_pcb", help="KiCad PCB file (.kicad_pcb)")
    gerber_p.add_argument("--output", "-o", required=True, help="Output directory for Gerber/drill files")

    cost_bom_p = subparsers.add_parser("cost-bom", help="Show costed BOM with LCSC pricing at volume breaks")
    cost_bom_p.add_argument("spec", help="Design spec YAML file")
    cost_bom_p.add_argument(
        "--qty",
        default="1,10,100,1000",
        help="Comma-separated build quantities (default: 1,10,100,1000)",
    )
    cost_bom_p.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        default=False,
        help="Output raw JSON instead of formatted table",
    )

    wizard_p = subparsers.add_parser(
        "design-wizard",
        help="Interactive circuit design wizard (offline, self-contained — no agents/APIs required)",
    )
    wizard_p.add_argument(
        "--output",
        "-o",
        help="Save final design.yaml to this file (default: design.yaml in current directory)",
    )
    wizard_p.add_argument(
        "--resume",
        metavar="YAML",
        default=None,
        help="Resume from a partially-completed design.yaml spec",
    )
    wizard_p.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Run wizard without prompting (use for testing; all prompts use defaults)",
    )
    wizard_p.add_argument(
        "--research-backend",
        dest="research_backend",
        choices=["auto", "sonar-pro", "standard"],
        default="auto",
        help=(
            "Which research backend to use for the IC research workflow. "
            "'auto' (default) picks sonar-pro when PERPLEXITY_API_KEY is set, "
            "else standard WebSearch. Env var: CIRCUIT_WEAVER_RESEARCH_BACKEND."
        ),
    )
    wizard_p.add_argument(
        "--research-depth",
        dest="research_depth",
        choices=["fast", "normal"],
        default=None,
        help=(
            "How much IC research to do for downstream agent workflows. "
            "'fast' keeps the query budget small for lower latency; "
            "'normal' does the fuller pass. Env var: CIRCUIT_WEAVER_RESEARCH_DEPTH."
        ),
    )

    log_status_p = subparsers.add_parser(
        "log-status",
        help="Show workflow log status for a design project (helps troubleshoot issues and resume designs)",
    )
    log_status_p.add_argument("project_dir", help="Path to the design project directory (contains design.log)")

    log_view_p = subparsers.add_parser(
        "log-view",
        help="View recent design log entries (JSON format for debugging)",
    )
    log_view_p.add_argument("project_dir", help="Path to the design project directory")
    log_view_p.add_argument(
        "--lines",
        "-n",
        type=int,
        default=10,
        help="Number of recent entries to show (default: 10)",
    )
    log_view_p.add_argument(
        "--type",
        choices=["all", "wizard_step", "cli_call", "validation", "research"],
        default="all",
        help="Filter by entry type (default: all)",
    )

    autoroute_p = subparsers.add_parser(
        "autoroute", help="Route PCB using Freerouting (optional; requires Freerouting JAR)"
    )
    autoroute_p.add_argument("kicad_pcb", help="Path to .kicad_pcb file")
    autoroute_p.add_argument(
        "--output",
        "-o",
        help="Output routed session/PCB (default: <name>.ses via kicad-cli, else <name>_routed.kicad_pcb)",
    )
    autoroute_p.add_argument(
        "--effort",
        choices=["fast", "medium", "high"],
        default="medium",
        help="Freerouting optimization-pass budget (default: medium)",
    )
    autoroute_p.add_argument(
        "--timeout",
        type=float,
        default=300,
        help="Routing timeout in seconds (default: 300)",
    )

    install_p = subparsers.add_parser(
        "install-skills",
        help="Install Circuit Weaver skills to detected AI platforms (Claude Code, Codex, OpenCode, Kilo)",
    )
    install_p.add_argument(
        "--platform",
        nargs="+",
        choices=["claude", "codex", "opencode", "kilo", "all"],
        default=None,
        help="Platforms to install to (default: all supported platforms)",
    )
    install_p.add_argument(
        "--skills",
        nargs="+",
        default=None,
        help="Skill names to install (default: all available)",
    )
    install_p.add_argument(
        "--list",
        action="store_true",
        help="List detected platforms without installing",
    )
    install_p.add_argument(
        "--force",
        action="store_true",
        help="Resolve managed-file provenance conflicts by replacing local files",
    )
    install_p.add_argument(
        "--backup",
        action="store_true",
        help="With --force, preserve every replaced file as a timestamped .bak copy",
    )
    install_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be installed without modifying any files",
    )

    schema_p = subparsers.add_parser("schema", help="Print JSON schema for the DesignIR format")
    schema_p.add_argument(
        "--format",
        choices=["json", "yaml", "markdown"],
        default="json",
        help="Output format (default: json)",
    )

    # Sprint 15: Spec harvesting & datasheet automation
    harvest_p = subparsers.add_parser(
        "harvest-specs", help="Download datasheets and extract structured specs for all BOM components"
    )
    harvest_p.add_argument("spec", help="Design spec YAML file")
    harvest_p.add_argument("--output", "-o", default=".", help="Project output directory (default: current dir)")
    harvest_p.add_argument(
        "--skip-download",
        action="store_true",
        default=False,
        help="Extract specs from API data only, skip PDF downloads",
    )
    harvest_p.add_argument("--delay", type=float, default=0.5, help="Seconds between API calls (default: 0.5)")
    harvest_p.add_argument("--json", dest="json_output", action="store_true", default=False, help="Output raw JSON")

    extract_p = subparsers.add_parser(
        "extract-specs", help="Parse downloaded PDF datasheets and extract structured metadata to JSON"
    )
    extract_p.add_argument("datasheets_dir", help="Directory containing PDF datasheets")
    extract_p.add_argument("--output", "-o", default="specs", help="Output directory for spec JSON files")
    extract_p.add_argument("--json", dest="json_output", action="store_true", default=False, help="Output raw JSON")

    spice_p = subparsers.add_parser(
        "fetch-spice", help="Download SPICE models and S-parameter files for analog/RF components"
    )
    spice_p.add_argument("spec", help="Design spec YAML file")
    spice_p.add_argument("--output", "-o", default=".", help="Project output directory (default: current dir)")
    spice_p.add_argument("--with-s-params", action="store_true", default=False, help="Also fetch S-parameter files")
    spice_p.add_argument("--delay", type=float, default=0.5, help="Seconds between download attempts (default: 0.5)")
    spice_p.add_argument("--json", dest="json_output", action="store_true", default=False, help="Output raw JSON")

    # Task 85: Symbol cache management
    cache_p = subparsers.add_parser("cache", help="Manage the symbol and parts cache")
    cache_sub = cache_p.add_subparsers(dest="cache_action", required=True)
    cache_stats_p = cache_sub.add_parser("stats", help="Show cache statistics")
    cache_stats_p.add_argument("--json", dest="json_output", action="store_true", default=False)
    cache_clear_p = cache_sub.add_parser("clear", help="Clear the symbol cache")
    cache_clear_p.add_argument(
        "--stale-only", action="store_true", default=False, help="Only remove entries older than 30 days"
    )

    # Sprint 16: Placement optimizer + interactive viewer
    opt_p = subparsers.add_parser("optimize-placement", help="Run simulated annealing placement optimizer")
    opt_p.add_argument("spec", help="Design spec YAML file")
    opt_p.add_argument("--output", "-o", help="Write placement JSON to file")
    opt_p.add_argument("--board-width", type=float, default=100.0, help="Board width in mm (default: 100)")
    opt_p.add_argument("--board-height", type=float, default=80.0, help="Board height in mm (default: 80)")
    opt_p.add_argument(
        "--strategy",
        choices=["simple", "thermal", "si", "cost", "balanced"],
        default="balanced",
        help="Placement strategy (default: balanced)",
    )
    opt_p.add_argument("--specs-dir", help="Path to specs/ directory with thermal/SI JSON")
    opt_p.add_argument("--iterations", type=int, default=5000, help="SA iterations (default: 5000)")
    opt_p.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    opt_p.add_argument("--json", dest="json_output", action="store_true", default=False, help="Output raw JSON")

    viewer_p = subparsers.add_parser("placement-viewer", help="Generate interactive HTML PCB placement viewer")
    viewer_p.add_argument("spec", help="Design spec YAML file")
    viewer_p.add_argument("--output", "-o", required=True, help="Output HTML file path")
    viewer_p.add_argument("--board-width", type=float, default=100.0, help="Board width in mm (default: 100)")
    viewer_p.add_argument("--board-height", type=float, default=80.0, help="Board height in mm (default: 80)")
    viewer_p.add_argument("--specs-dir", help="Path to specs/ directory for thermal overlay")
    viewer_p.add_argument("--strategy", choices=["simple", "thermal", "si", "cost", "balanced"], default="balanced")

    # Sprint 16 P1/P2: SI constraints, thermal analysis, dual-sided CPL, panelization
    si_p = subparsers.add_parser(
        "si-constraints", help="Analyze signal integrity constraints (impedance, length matching)"
    )
    si_p.add_argument("spec", help="Design spec YAML file")
    si_p.add_argument("--json", dest="json_output", action="store_true", default=False, help="Output raw JSON")

    thermal_p = subparsers.add_parser("thermal-analysis", help="Analyze thermal performance and generate heatmap")
    thermal_p.add_argument("spec", help="Design spec YAML file")
    thermal_p.add_argument("--specs-dir", help="Path to specs/ directory with thermal data")
    thermal_p.add_argument("--ambient", type=float, default=25.0, help="Ambient temperature in °C (default: 25)")
    thermal_p.add_argument("--heatmap", help="Output thermal heatmap SVG to this path")
    thermal_p.add_argument("--board-width", type=float, default=100.0, help="Board width in mm (default: 100)")
    thermal_p.add_argument("--board-height", type=float, default=80.0, help="Board height in mm (default: 80)")
    thermal_p.add_argument("--json", dest="json_output", action="store_true", default=False, help="Output raw JSON")

    dual_cpl_p = subparsers.add_parser("export-dual-cpl", help="Export dual-sided CPL files (top + bottom)")
    dual_cpl_p.add_argument("spec", help="Design spec YAML file")
    dual_cpl_p.add_argument("--output", "-o", required=True, help="Output directory for CPL files")
    dual_cpl_p.add_argument(
        "--assembly-mode",
        choices=["single-sided", "dual-sided-simultaneous", "dual-sided-sequential"],
        default="dual-sided-sequential",
        help="Assembly mode (default: dual-sided-sequential)",
    )

    panel_p = subparsers.add_parser("panelize", help="Suggest panel layout for small boards")
    panel_p.add_argument("--board-width", type=float, required=True, help="Single board width in mm")
    panel_p.add_argument("--board-height", type=float, required=True, help="Single board height in mm")
    panel_p.add_argument("--qty", type=int, default=100, help="Total boards needed (default: 100)")
    panel_p.add_argument("--panel-width", type=float, default=100.0, help="Max panel width in mm (default: 100)")
    panel_p.add_argument("--panel-height", type=float, default=100.0, help="Max panel height in mm (default: 100)")
    panel_p.add_argument(
        "--breakaway", choices=["v-cut", "mouse-bite"], default="v-cut", help="Breakaway type (default: v-cut)"
    )
    panel_p.add_argument("--json", dest="json_output", action="store_true", default=False, help="Output raw JSON")

    enclosure_p = subparsers.add_parser(
        "design-enclosure", help="Generate parametric OpenSCAD enclosure from PCB dimensions"
    )
    enclosure_p.add_argument("--board-width", type=float, required=True, help="PCB width in mm")
    enclosure_p.add_argument("--board-height", type=float, required=True, help="PCB height in mm")
    enclosure_p.add_argument("--board-thickness", type=float, default=1.6, help="PCB thickness in mm (default: 1.6)")
    enclosure_p.add_argument(
        "--component-height", type=float, default=12, help="Max component height above PCB in mm (default: 12)"
    )
    enclosure_p.add_argument(
        "--wall-thickness", type=float, default=2.5, help="Enclosure wall thickness in mm (default: 2.5)"
    )
    enclosure_p.add_argument("--clearance", type=float, default=2, help="Clearance around PCB in mm (default: 2)")
    enclosure_p.add_argument(
        "-o", "--output", type=str, default="enclosure.scad", help="Output OpenSCAD file (default: enclosure.scad)"
    )
    enclosure_p.add_argument(
        "--render-stl", action="store_true", default=False, help="Render STL file (requires OpenSCAD CLI)"
    )
    enclosure_p.add_argument("--stl-output", type=str, help="Output STL file path (default: enclosure.stl)")
    enclosure_p.add_argument("--vents", action="store_true", default=False, help="Include vent holes in lid")

    check_dfm_p = subparsers.add_parser("check-dfm", help="Check PCB design for DFM violations")
    check_dfm_p.add_argument("kicad_pcb", type=str, help="Path to .kicad_pcb file")
    check_dfm_p.add_argument(
        "--profile",
        choices=["jlcpcb", "jlcpcb_4layer", "pcbway"],
        default="jlcpcb",
        help="Fab profile (default: jlcpcb)",
    )

    gen_docs_p = subparsers.add_parser("generate-docs", help="Generate assembly guide and design documentation")
    gen_docs_p.add_argument("spec", type=str, help="Design spec file (YAML)")
    gen_docs_p.add_argument(
        "-o", "--output", type=str, default="docs", help="Output directory for documentation (default: docs)"
    )
    gen_docs_p.add_argument(
        "--datasheets-dir",
        type=str,
        default=None,
        help="Optional directory with downloaded datasheets for datasheet index",
    )

    erc_p = subparsers.add_parser("erc", help="Run ERC on a generated .kicad_sch file via kicad-cli")
    erc_p.add_argument("schematic", type=str, help="Path to .kicad_sch file")
    erc_p.add_argument("--json", dest="json_output", action="store_true", help="Output results as JSON")

    doctor_p = subparsers.add_parser("doctor", help="Check environment: installed tools, dependencies, versions")
    doctor_p.add_argument("--json", dest="json_output", action="store_true", help="Output as JSON")

    conf_p = subparsers.add_parser("confidence", help="Generate design confidence report")
    conf_p.add_argument("spec", help="Path to YAML/JSON design spec")
    conf_p.add_argument("--output", "-o", default=None, help="Write HTML dashboard to file")
    conf_p.add_argument("--pcb", default=None, help="Path to .kicad_pcb for DFM analysis")
    conf_p.add_argument(
        "--run-sims",
        action="store_true",
        default=False,
        help="Run simulations as part of confidence check",
    )
    conf_p.add_argument("--json", dest="json_output", action="store_true", help="Output as JSON")
    conf_p.add_argument("--enrich-parts", action="store_true", default=False)

    simulate_p = subparsers.add_parser("simulate", help="Run SPICE simulations on a design")
    simulate_p.add_argument("spec", help="Path to YAML/JSON design spec")
    simulate_p.add_argument("--output", "-o", default="./sims", help="Simulation output directory")
    simulate_p.add_argument("--model-dir", default=None, help="Directory with SPICE models (default: auto-detect)")
    simulate_p.add_argument(
        "--type",
        dest="sim_scope",
        choices=["all", "power", "signal", "thermal"],
        default="all",
        help="Scope of simulations to run",
    )
    simulate_p.add_argument("--json", dest="json_output", action="store_true", help="Output as JSON")

    discover_p = subparsers.add_parser("discover", help="Discover existing circuit projects in current directory")
    discover_p.add_argument("--root", default=".", help="Root directory to search (default: current dir)")
    discover_p.add_argument("--depth", type=int, default=2, help="Maximum search depth (default: 2)")
    discover_p.add_argument("--json", dest="json_output", action="store_true", help="Output as JSON")

    save_research_p = subparsers.add_parser(
        "save-research",
        help="Persist a research result to {project_dir}/research/ (JSON + Markdown + summary)",
    )
    save_research_p.add_argument(
        "--project-dir",
        dest="output",
        required=True,
        help="Project output directory — results land in {project_dir}/research/",
    )
    save_research_p.add_argument("--file", default=None, help="Read JSON payload from this file (default: stdin)")
    save_research_p.add_argument("--topic", default=None, help="Override topic slug (otherwise taken from JSON)")
    save_research_p.add_argument("--backend", default=None, help="Override backend label (sonar-pro|standard|...)")
    save_research_p.add_argument(
        "--json", dest="json_output", action="store_true", help="Print the saved record path as JSON"
    )

    log_event_p = subparsers.add_parser("log-event", help="Log a structured event to the project design.log")
    log_event_p.add_argument("project_dir", help="Project directory containing design.log")
    log_event_p.add_argument(
        "--type",
        required=True,
        choices=[
            "wizard_step",
            "cli_call",
            "validation",
            "research",
            "part_lookup",
            "symbol_resolution",
            "simulation",
            "thermal",
            "erc_drc",
            "scoring",
            "sourcing",
            "generation",
            "error",
        ],
        help="Event type to log",
    )
    log_event_p.add_argument("--message", required=True, help="Event description")
    log_event_p.add_argument("--data", default=None, help="JSON string with additional event data")

    args = parser.parse_args()

    # Task 159: every CLI subcommand gets a circuit-weaver.log in the
    # project directory (unless it's a read-only/administrative command
    # listed in _NO_LOG_COMMANDS). Workflow-step markers are emitted at
    # the top of each handler below so users can trace the run.
    from .logging_bridge import (
        cleanup_logging as _cw_cleanup_logging,
    )
    from .logging_bridge import (
        init_logging_for_cli as _cw_init_logging_for_cli,
    )
    from .logging_bridge import (
        log_workflow_step as _cw_log_workflow_step,
    )

    _cw_owned_log_dir = _cw_init_logging_for_cli(args.command, args)
    if _cw_owned_log_dir is not None:
        _cw_log_workflow_step(
            args.command,
            "start",
            f"CLI invoked: circuit-weaver {args.command}",
            details={"log_dir": str(_cw_owned_log_dir)},
        )

    try:
        _cw_dispatch_result = _main_dispatch(args, _cw_log_workflow_step)
    except SystemExit:
        if _cw_owned_log_dir is not None:
            _cw_log_workflow_step(args.command, "end", "CLI exited via SystemExit")
            _cw_cleanup_logging()
        raise
    except Exception as exc:
        if _cw_owned_log_dir is not None:
            _logger.exception("CLI command '%s' failed: %s", args.command, exc)
            _cw_log_workflow_step(args.command, "error", f"Unhandled exception: {exc}")
            _cw_cleanup_logging()
        raise
    else:
        if _cw_owned_log_dir is not None:
            _cw_log_workflow_step(args.command, "end", "CLI completed")
            _cw_cleanup_logging()
        return _cw_dispatch_result


def _main_dispatch(args, log_workflow_step):  # noqa: C901  # large CLI dispatcher
    """Original body of main(). Split out so the outer main() can wrap it
    with unified workflow-logging setup/teardown.
    """
    if args.command == "validate":
        strict = getattr(args, "strict", False)
        color = getattr(args, "color", "auto")
        verbose = getattr(args, "verbose", False)
        detailed_score = getattr(args, "detailed_score", False)
        log_workflow_step(
            "validate",
            "load-spec",
            f"Loading design spec from {args.spec}",
            details={"spec": str(args.spec), "strict": strict},
        )
        spec = _load_spec_file(args.spec)
        report = _run_with_stderr_capture(
            lambda: validate_design(
                spec,
                enrich_parts=args.enrich_parts,
                strict=strict,
            )
        )
        from .logging_bridge import get_design_logger

        dl = get_design_logger()
        if dl is not None:
            error_msgs = []
            warning_msgs = []
            for messages in report.categories.values():
                for msg in messages:
                    rendered = f"[{msg.category}:{msg.code}] {msg.message}"
                    if msg.level == "error":
                        error_msgs.append(rendered)
                    elif msg.level == "warning":
                        warning_msgs.append(rendered)
            dl.log_validation(
                spec_file=str(args.spec),
                passed=report.valid,
                errors=error_msgs[:5],
                warnings=warning_msgs[:5],
                scope="final_report",
                error_count=len(error_msgs),
                warning_count=len(warning_msgs),
            )
        # Print as colored text only if --verbose or if color is always/auto with TTY support
        if verbose or (color in ("always", "auto") and _color_support(color)):
            use_color = _color_support(color)
            _print_validation_report(report, use_color=use_color, verbose=verbose)
        else:
            _print_json(report.to_dict())

        # Add detailed design scoring if requested
        if detailed_score:
            from .design_scorer import score_design_comprehensive

            compiled = compile_design_ir(spec, enrich_parts=args.enrich_parts)
            score_result = score_design_comprehensive(compiled.ir)
            print("\n" + "=" * 60)
            print(score_result.summary_with_gaps())
            print("=" * 60)

        # Enhanced validation: cross-reference audit
        enhanced = getattr(args, "enhanced", False)
        if enhanced:
            from .cross_reference_validator import run_cross_reference_audit

            compiled = compile_design_ir(spec, enrich_parts=args.enrich_parts)
            xref_results = run_cross_reference_audit(compiled.components, spec=spec)
            print("\n" + "=" * 60)
            print("Cross-Reference Audit")
            print("=" * 60)
            for xr in xref_results:
                status_sym = "PASS" if xr.status == "pass" else ("SKIP" if xr.status == "skipped" else "WARN")
                print(f"  [{status_sym}] {xr.pass_name} ({xr.checked_items} items)")
                for issue in xr.issues[:5]:
                    prefix = "ERROR" if issue.level == "error" else "WARN "
                    print(f"    [{prefix}] {issue.message}")
            print("=" * 60)

            # Factor cross-reference errors into exit code
            xref_errors = sum(sum(1 for i in xr.issues if i.level == "error") for xr in xref_results)
            if xref_errors > 0:
                raise SystemExit(2)

        raise SystemExit(0 if report.valid else 2)

    if args.command == "apply-patch":
        result = _run_with_stderr_capture(
            lambda: apply_design_patch(
                _load_spec_file(args.spec),
                _load_patch_file(args.patch),
                enrich_parts=args.enrich_parts,
            )
        )
        if result["accepted"] and args.output:
            Path(args.output).write_text(spec_to_yaml_text(result["updated_spec"]), encoding="utf-8", newline="")
        _print_json(result)
        raise SystemExit(0 if result["accepted"] else 2)

    if args.command == "generate":
        log_workflow_step(
            "generate",
            "load-spec",
            f"Loading design spec from {args.spec}",
            details={"spec": str(args.spec), "output_dir": str(args.output)},
        )
        spec = _load_spec_file(args.spec)
        if args.presentation_profile:
            spec["presentation_profile"] = args.presentation_profile
        auto_source = getattr(args, "auto_source", False)
        update_spec = getattr(args, "update_spec", False)
        svg_placement = getattr(args, "svg_placement", False)
        spec_path = Path(args.spec) if update_spec else None
        try:
            result = _run_with_stderr_capture(
                lambda: generate_artifacts(
                    spec,
                    output_dir=args.output,
                    require_valid=args.require_valid,
                    readiness_gate=getattr(args, "readiness_gate", True),
                    enrich_parts=args.enrich_parts or auto_source,
                    export_svg=args.export_svg,
                    score=args.score,
                    auto_source=auto_source,
                    update_spec=update_spec,
                    spec_path=spec_path,
                    svg_placement=svg_placement,
                    export_pinout=getattr(args, "export_pinout", False),
                    require_kicad=getattr(args, "require_kicad", False),
                )
            )
        except ValueError as exc:
            message = str(exc)
            _print_json({"status": "error", "valid": False, "message": message})
            raise SystemExit(2) from None
        if auto_source and "auto_source_summary" in result:
            s = result["auto_source_summary"]
            print(
                f"Auto-sourced {s['resolved']}/{s['total']} parts "
                f"(DigiKey: {s['by_source']['digikey']}, "
                f"Mouser: {s['by_source']['mouser']}, "
                f"LCSC: {s['by_source']['lcsc']})",
                file=sys.stderr,
            )
            if s["unresolved_count"] > 0:
                print(f"Warning: {s['unresolved_count']} parts could not be auto-sourced", file=sys.stderr)

        _print_json(result)
        raise SystemExit(0)

    if args.command == "review-report":
        from .erc_runner import run_erc
        from .review_report import generate_review_report_html

        spec = _load_spec_file(args.spec)
        compiled = compile_design_ir(spec, enrich_parts=args.enrich_parts)
        kicad_pcb_path = getattr(args, "kicad_pcb", None)
        schematic_path = getattr(args, "schematic", None)
        erc_result = run_erc(schematic_path) if schematic_path else None

        report_path = _run_with_stderr_capture(
            lambda: generate_review_report_html(
                compiled.ir,
                args.output,
                kicad_pcb_path=kicad_pcb_path,
                erc_result=erc_result,
            )
        )
        print(f"Design review report generated: {report_path}", file=sys.stderr)
        _print_json({"report": str(report_path), "status": "success"})
        raise SystemExit(0)

    if args.command == "diff":
        old_spec = _load_spec_file(args.old_spec)
        new_spec = _load_spec_file(args.new_spec)
        use_svg = getattr(args, "svg", False)
        output_path = getattr(args, "output", None)
        if use_svg or output_path:
            from .diff_renderer import diff_designs as visual_diff

            result = _run_with_stderr_capture(lambda: visual_diff(old_spec, new_spec, svg=use_svg, output=output_path))
        else:
            result = diff_designs(old_spec, new_spec)
        _print_json(result)
        raise SystemExit(0)

    if args.command == "ingest-pcb-feedback":
        result = _run_with_stderr_capture(
            lambda: ingest_pcb_feedback(_load_spec_file(args.spec), _load_patch_file(args.feedback))
        )
        if args.output and result.updated_spec is not None:
            Path(args.output).write_text(spec_to_yaml_text(result.updated_spec), encoding="utf-8", newline="")
        _print_json(result.to_dict())
        raise SystemExit(0 if not result.rejected else 2)

    if args.command == "import-placement":
        from .kicad_placement_api import check_kicad_available
        from .svg_placement import (
            import_placement_from_svg,
            update_cpl_placements,
            update_kicad_pcb_placements,
        )

        # Check if KiCad API is available
        kicad_available, kicad_msg = check_kicad_available()
        if not kicad_available:
            print(f"[!] KiCad API not available. Using regex-based fallback.\n    {kicad_msg}", file=sys.stderr)
            use_api = False
        else:
            use_api = True

        svg_placements = import_placement_from_svg(args.svg)

        # Update .kicad_pcb
        output_pcb = getattr(args, "output_pcb", None) or args.kicad_pcb
        pcb_result = update_kicad_pcb_placements(
            args.kicad_pcb,
            svg_placements,
            output_path=output_pcb if not args.dry_run else None,
            use_api=use_api,
        )

        # Try to update CPL file (optional)
        cpl_result = {"updated": 0}
        cpl_path = Path(args.kicad_pcb).parent / f"{Path(args.kicad_pcb).stem}_cpl.csv"
        if cpl_path.exists():
            output_cpl = getattr(args, "output_cpl", None) or str(cpl_path)
            cpl_count = update_cpl_placements(
                cpl_path, svg_placements, output_path=output_cpl if not args.dry_run else None
            )
            cpl_result = {"updated": cpl_count}

        result = {
            "kicad_pcb": {
                "file": str(output_pcb),
                "updated": len(pcb_result.get("updated", [])),
                "not_found": pcb_result.get("not_found", []),
                "errors": pcb_result.get("errors", []),
                "message": pcb_result.get("message", ""),
                "dry_run": args.dry_run,
                "api_used": use_api,
            },
            "cpl": cpl_result,
        }

        if pcb_result.get("errors"):
            print(f"[!] Placement import had errors: {pcb_result['message']}", file=sys.stderr)

        _print_json(result)
        raise SystemExit(0 if pcb_result.get("success", True) else 1)

    if args.command == "list-templates":
        registry = get_default_registry()
        templates_info = []
        for ttype in sorted(registry.available_types()):
            tmpl = registry.get(ttype)
            info = {
                "type": ttype,
                "description": tmpl.description,
                "source": "data-driven" if isinstance(tmpl, DataDrivenTemplate) else "legacy",
                "params": [
                    {k: v for k, v in spec.items() if k in ("name", "type", "required", "default", "options")}
                    for spec in tmpl.param_schema
                ]
                if args.verbose or args.json_output
                else [{"name": s["name"], "required": s.get("required", False)} for s in tmpl.param_schema],
            }
            templates_info.append(info)

        if args.include_data_driven:
            from .ic_data import get_all_ics, list_topologies

            for topo in sorted(list_topologies()):
                ics = get_all_ics(topo)
                for mpn, ic_data in ics.items():
                    templates_info.append(
                        {
                            "type": topo,
                            "ic": mpn,
                            "description": ic_data.get("description", ""),
                            "source": "data-driven",
                        }
                    )

        if args.json_output:
            _print_json(templates_info)
        else:
            for info in templates_info:
                source_tag = f" [{info['source']}]" if info.get("source") == "data-driven" else ""
                ic_tag = f" (ic: {info['ic']})" if "ic" in info else ""
                print(f"  {info['type']:25s} {info['description']}{ic_tag}{source_tag}")
                if args.verbose and "params" in info:
                    for p in info["params"]:
                        default = f" (default: {p['default']})" if "default" in p else ""
                        options = f" [{', '.join(str(o) for o in p['options'])}]" if "options" in p else ""
                        req = " REQUIRED" if p.get("required") else ""
                        print(f"    {p['name']:20s} {p.get('type', ''):10s}{req}{default}{options}")
                elif "params" in info:
                    params = ", ".join(p["name"] + ("*" if p.get("required") else "") for p in info["params"])
                    print(f"    params: {params}")
        raise SystemExit(0)

    if args.command == "scaffold":
        registry = get_default_registry()
        if not args.template:
            # No template specified — list available templates
            print("Available templates (use --template <name>):\n")
            for ttype in sorted(registry.available_types()):
                tmpl = registry.get(ttype)
                print(f"  {ttype:25s} {tmpl.description}")
            raise SystemExit(0)

        tmpl = registry.get(args.template)
        if tmpl is None:
            print(f"Unknown template '{args.template}'. Use 'list-templates' to see available types.", file=sys.stderr)
            raise SystemExit(1)

        # Build a scaffold YAML spec with the template's params
        block = {"type": args.template, "ref": args.ref}
        for spec in tmpl.param_schema:
            name = spec["name"]
            if name in ("ref",):
                continue
            if "default" in spec:
                block[name] = spec["default"]
            elif spec.get("required"):
                if spec.get("type") == "number":
                    block[name] = 0.0
                elif spec.get("type") == "integer":
                    block[name] = 0
                elif spec.get("type") == "boolean":
                    block[name] = False
                elif "options" in spec:
                    block[name] = spec["options"][0]
                else:
                    block[name] = f"<{name}>"

        section = tmpl.generate.__doc__ or ""
        category = "power" if "power" in (tmpl.description + section).lower() else "digital"
        scaffold_spec = {
            "project": f"my_{args.template}_design",
            category: [block],
        }
        yaml_text = spec_to_yaml_text(scaffold_spec)

        if args.output:
            Path(args.output).write_text(yaml_text, encoding="utf-8")
            print(f"Wrote scaffold to {args.output}")
        else:
            print(yaml_text)
        raise SystemExit(0)

    if args.command == "register-ic":
        import json as _json_mod

        from .ic_data import register_ic

        if args.file:
            ic_json = Path(args.file).read_text(encoding="utf-8")
        else:
            ic_json = sys.stdin.read()

        data = _json_mod.loads(ic_json)

        if not isinstance(data, dict):
            print("Error: expected JSON object with IC data", file=sys.stderr)
            raise SystemExit(1)

        is_single_ic = ("topology" in data or "template_type" in data) and not all(
            isinstance(value, dict) for value in data.values()
        )

        if is_single_ic:
            mpn = args.mpn or str(data.get("mpn") or "").strip()
            if not mpn:
                print("Error: --mpn required when input is a single IC object without an mpn field", file=sys.stderr)
                raise SystemExit(1)
            if "topology" not in data and "template_type" in data:
                data = {**data, "topology": data["template_type"]}
            register_ic(mpn, data, persist=True)
            print(f"Registered IC: {mpn} (topology: {data.get('topology', 'unknown')})")
        else:
            count = 0
            for mpn, ic_data in data.items():
                if not isinstance(ic_data, dict):
                    print(f"Error: IC entry {mpn!r} must be an object", file=sys.stderr)
                    raise SystemExit(1)
                if "topology" not in ic_data and "template_type" in ic_data:
                    ic_data = {**ic_data, "topology": ic_data["template_type"]}
                register_ic(mpn, ic_data, persist=True)
                count += 1
            print(f"Registered {count} IC(s)")
        raise SystemExit(0)

    if args.command == "export-jlcpcb":
        from .jlcpcb_export import export_jlcpcb

        result = _run_with_stderr_capture(
            lambda: export_jlcpcb(
                _load_spec_file(args.spec),
                args.output,
            )
        )
        _print_json(result)
        raise SystemExit(0 if result["status"] == "ok" else 1)

    if args.command == "export-gerbers":
        import zipfile

        cli = _kicad_cli_path()
        if not cli:
            _print_json(
                {
                    "status": "error",
                    "message": "KiCad CLI not found. Install KiCad 8+ and ensure kicad-cli is on PATH.",
                }
            )
            raise SystemExit(1)

        out = Path(args.output)
        out.mkdir(parents=True, exist_ok=True)

        # Export gerbers
        result = subprocess.run(
            [str(cli), "pcb", "export", "gerbers", "-o", str(out), args.kicad_pcb],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            _print_json(
                {
                    "status": "error",
                    "message": f"kicad-cli gerber export failed: {result.stderr}",
                }
            )
            raise SystemExit(1)

        # Export drill files
        result = subprocess.run(
            [str(cli), "pcb", "export", "drill", "-o", str(out), args.kicad_pcb],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            _print_json(
                {
                    "status": "error",
                    "message": f"kicad-cli drill export failed: {result.stderr}",
                }
            )
            raise SystemExit(1)

        # ZIP the output files (gerbers + drills)
        gerber_files = list(out.glob("*.gbr")) + list(out.glob("*.drl"))
        zip_path = out / f"{Path(args.kicad_pcb).stem}_gerbers.zip"

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in gerber_files:
                zf.write(f, arcname=f.name)

        _print_json(
            {
                "status": "ok",
                "message": f"Exported Gerbers and drills to {zip_path}",
                "zip": str(zip_path),
                "file_count": len(gerber_files),
            }
        )
        raise SystemExit(0)

    if args.command == "cost-bom":
        from .cost_bom import cost_bom

        qty_breaks = [int(q.strip()) for q in args.qty.split(",")]
        result = _run_with_stderr_capture(
            lambda: cost_bom(
                _load_spec_file(args.spec),
                qty_breaks=qty_breaks,
            )
        )

        if args.json_output:
            _print_json(result)
        else:
            _print_cost_bom_table(result)

        raise SystemExit(0 if result["status"] == "ok" else 1)

    if args.command == "install-skills":
        from .skill_installer import detect_platforms, install_skills

        if getattr(args, "list", False):
            _print_json({"platforms": detect_platforms()})
            raise SystemExit(0)

        platforms = None
        if args.platform and "all" not in args.platform:
            platforms = args.platform

        result = install_skills(
            platforms=platforms,
            skills=getattr(args, "skills", None),
            force=getattr(args, "force", False),
            backup=getattr(args, "backup", False),
            dry_run=getattr(args, "dry_run", False),
        )
        _print_json(result)

        conflicts = result.get("skills_conflicted") or result.get("skills_skipped") or []
        if conflicts:
            print(
                f"[!] Found {len(conflicts)} managed skill conflict(s); local files were preserved.",
                file=sys.stderr,
            )
            for entry in conflicts:
                print(
                    f"    {entry['platform']}/{entry['skill']} → {entry['dest']}",
                    file=sys.stderr,
                )
            print(
                "    Resolve the conflicts or re-run with --force "
                "(add --backup to preserve replaced files).",
                file=sys.stderr,
            )

        raise SystemExit(0 if result["status"] == "ok" else 1)

    if args.command == "schema":
        from .schema import get_design_ir_schema

        schema = get_design_ir_schema()
        fmt = getattr(args, "format", "json")

        if fmt == "json":
            _print_json(schema)
        elif fmt == "yaml":
            try:
                import yaml

                print(yaml.dump(schema, default_flow_style=False, sort_keys=False))
            except ImportError:
                print("[!] PyYAML not installed. Install with: pip install pyyaml", file=sys.stderr)
                raise SystemExit(1)
        elif fmt == "markdown":
            # Convert schema to markdown table
            md = (
                "# Design IR Schema\n\n"
                "| Field | Type | Required | Description |\n"
                "|-------|------|----------|-------------|\n"
            )
            props = schema.get("properties", {})
            required = schema.get("required", [])
            for field_name, field_schema in props.items():
                field_type = field_schema.get("type", "unknown")
                is_required = "Yes" if field_name in required else "No"
                desc = field_schema.get("description", "")
                md += f"| {field_name} | {field_type} | {is_required} | {desc} |\n"
            print(md)

        raise SystemExit(0)

    if args.command == "design-wizard":
        resume_spec = getattr(args, "resume", None)
        dry_run = getattr(args, "dry_run", False)
        effective_backend = None
        effective_depth = None
        if getattr(args, "research_backend", None) is not None:
            from .research import resolve_backend, resolve_depth

            effective_backend = resolve_backend(args.research_backend)
            effective_depth = resolve_depth(getattr(args, "research_depth", None))
        _handle_design_workflow(
            resume=resume_spec,
            dry_run=dry_run,
            research_backend=effective_backend,
            research_depth=effective_depth,
        )
        raise SystemExit(0)

    if args.command == "log-status":
        try:
            logger = DesignLogger(args.project_dir)
            logger.print_summary()
            raise SystemExit(0)
        except Exception as e:
            print(f"[!] Error reading project log: {e}", file=sys.stderr)
            raise SystemExit(1)

    if args.command == "log-view":
        try:
            logger = DesignLogger(args.project_dir)
            if not logger.entries:
                print("[!] No log entries found.")
                raise SystemExit(1)

            # Filter entries by type
            entries = logger.entries
            if args.type != "all":
                entries = [e for e in entries if e.get("type") == args.type]

            # Show last N entries
            entries = entries[-args.lines :]

            print(f"\n>>> Recent Log Entries ({len(entries)} shown):\n")
            for i, entry in enumerate(entries, 1):
                entry_type = entry.get("type", "unknown")
                timestamp = entry.get("timestamp", "")[:19]  # YYYY-MM-DD HH:MM:SS

                if entry_type == "wizard_step":
                    step = entry.get("step", 0)
                    desc = entry.get("description", "")
                    print(f"  [{i}] {timestamp} [WIZARD] Step {step}: {desc}")

                elif entry_type == "cli_call":
                    cmd = entry.get("command", "")
                    success = entry.get("success", False)
                    status = "OK" if success else "FAIL"
                    print(f"  [{i}] {timestamp} [CLI] {status}: {cmd}")

                elif entry_type == "validation":
                    passed = entry.get("passed", False)
                    status = "PASS" if passed else "FAIL"
                    print(f"  [{i}] {timestamp} [VALIDATION] {status}")

                elif entry_type == "research":
                    phase = entry.get("phase", "")
                    status = entry.get("status", "")
                    print(f"  [{i}] {timestamp} [RESEARCH] {phase}: {status}")

            print(f"\nLog file: {logger.log_path}\n")
            raise SystemExit(0)

        except Exception as e:
            print(f"[!] Error reading project log: {e}", file=sys.stderr)
            raise SystemExit(1)

    if args.command == "autoroute":
        from .autoroute import autoroute_pcb

        result = _run_with_stderr_capture(
            lambda: autoroute_pcb(
                args.kicad_pcb,
                output_path=args.output,
                effort=args.effort,
                timeout_seconds=args.timeout,
            )
        )

        _print_json(result)
        raise SystemExit(0 if result["status"] == "ok" else 1)

    if args.command == "harvest-specs":
        from .spec_harvester import harvest_specs

        result = _run_with_stderr_capture(
            lambda: harvest_specs(
                _load_spec_file(args.spec),
                output_dir=args.output,
                skip_download=args.skip_download,
                delay=args.delay,
            )
        )

        if args.json_output:
            _print_json(result)
        else:
            status = result.get("status", "error")
            if status == "ok":
                print(f"Project: {result['project']}")
                print(f"Components processed: {result['components_processed']}")
                print(f"Datasheets downloaded: {result['datasheets_downloaded']}")
                print(f"Datasheets skipped:    {result['datasheets_skipped']}")
                print(f"Datasheets failed:     {result['datasheets_failed']}")
                print(f"Specs extracted:       {result['specs_extracted']}")
                print(f"Datasheets dir: {result['datasheets_dir']}")
                print(f"Specs dir:      {result['specs_dir']}")
                for w in result.get("warnings", []):
                    print(f"  [!] {w}")
            else:
                print(f"[!] {result.get('message', 'Unknown error')}", file=sys.stderr)

        raise SystemExit(0 if result.get("status") == "ok" else 1)

    if args.command == "extract-specs":
        from .datasheet_parser import extract_specs

        result = _run_with_stderr_capture(
            lambda: extract_specs(
                args.datasheets_dir,
                args.output,
            )
        )

        if args.json_output:
            _print_json(result)
        else:
            status = result.get("status", "error")
            if status == "ok":
                print(f"PDFs processed: {result['processed']}")
                print(f"Specs extracted: {result['extracted']}")
                print(f"Failed:          {result['failed']}")
                print(f"Skipped:         {result['skipped']}")
                if result.get("output_file"):
                    print(f"Output: {result['output_file']}")
                for w in result.get("warnings", []):
                    print(f"  [!] {w}")
            else:
                print(f"[!] {result.get('message', 'Unknown error')}", file=sys.stderr)

        raise SystemExit(0 if result.get("status") == "ok" else 1)

    if args.command == "fetch-spice":
        from .spice_fetcher import fetch_spice_models

        result = _run_with_stderr_capture(
            lambda: fetch_spice_models(
                _load_spec_file(args.spec),
                output_dir=args.output,
                include_s_params=args.with_s_params,
                delay=args.delay,
            )
        )

        if args.json_output:
            _print_json(result)
        else:
            status = result.get("status", "error")
            if status == "ok":
                print(f"Project: {result['project']}")
                print(f"Components checked:  {result['components_checked']}")
                print(f"SPICE downloaded:    {result['spice_downloaded']}")
                print(f"SPICE not found:     {result['spice_not_found']}")
                if result.get("sparam_dir"):
                    print(f"S-params downloaded: {result['sparam_downloaded']}")
                    print(f"S-params not found:  {result['sparam_not_found']}")
                print(f"SPICE dir: {result['spice_dir']}")
                for w in result.get("warnings", []):
                    print(f"  [!] {w}")
            else:
                print(f"[!] {result.get('message', 'Unknown error')}", file=sys.stderr)

        raise SystemExit(0 if result.get("status") == "ok" else 1)

    if args.command == "cache":
        from .symbol_cache import SymbolCache

        sc = SymbolCache()
        if args.cache_action == "stats":
            result = sc.stats()
            if getattr(args, "json_output", False):
                _print_json(result)
            else:
                if "error" in result:
                    print(f"[!] Cache stats error: {result['error']}", file=sys.stderr)
                else:
                    total = result["total"]
                    fresh = result["fresh"]
                    stale = result["stale"]
                    size_kb = result["size_bytes"] // 1024 if result["size_bytes"] else 0
                    print(f"Symbol cache: {total} entries ({fresh} fresh, {stale} stale), {size_kb} KB")
            raise SystemExit(0)

        if args.cache_action == "clear":
            stale_only = getattr(args, "stale_only", False)
            n = sc.clear(stale_only=stale_only)
            if stale_only:
                print(f"Cleared {n} stale cache entries (older than 30 days).")
            else:
                print(f"Cleared {n} cache entries.")
            raise SystemExit(0)

    if args.command == "optimize-placement":
        from .placement_optimizer import PlacementConfig, optimize_placement

        spec = _load_spec_file(args.spec)
        compiled = compile_design_ir(spec)
        cfg = PlacementConfig(
            board_width_mm=args.board_width,
            board_height_mm=args.board_height,
            strategy=args.strategy,
            iterations=args.iterations,
            seed=args.seed,
        )
        result = _run_with_stderr_capture(
            lambda: optimize_placement(compiled.components, config=cfg, specs_dir=args.specs_dir)
        )

        if args.json_output:
            _print_json(result)
        else:
            print(f"Strategy: {result['strategy']}")
            print(f"Board: {result['board_width_mm']}x{result['board_height_mm']} mm")
            print(f"Components placed: {len(result['placements'])}")
            print(f"Iterations: {result['iterations']}")
            print(f"Cost: {result['initial_cost']} -> {result['final_cost']}")
            for w in result.get("thermal_warnings", []):
                print(f"  [!] {w}")

        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(
                json.dumps(result["placements"], indent=2, ensure_ascii=False), encoding="utf-8"
            )
            print(f"Placement written to {args.output}")

        raise SystemExit(0 if result.get("status") == "ok" else 1)

    if args.command == "placement-viewer":
        from .placement_optimizer import PlacementConfig, optimize_placement
        from .placement_viewer import generate_viewer

        spec = _load_spec_file(args.spec)
        compiled = compile_design_ir(spec)
        cfg = PlacementConfig(
            board_width_mm=args.board_width,
            board_height_mm=args.board_height,
            strategy=args.strategy,
        )
        opt_result = optimize_placement(compiled.components, config=cfg, specs_dir=args.specs_dir)
        placements = opt_result["placements"]

        thermal_data = None
        if args.specs_dir:
            thermal_path = Path(args.specs_dir) / "ic_thermal.json"
            if thermal_path.exists():
                try:
                    thermal_data = json.loads(thermal_path.read_text(encoding="utf-8"))
                except Exception:
                    pass

        generate_viewer(
            compiled.components,
            placements,
            board_width_mm=args.board_width,
            board_height_mm=args.board_height,
            thermal_data=thermal_data,
            title=spec.get("project", "PCB Placement"),
            output_path=args.output,
        )
        print(f"Viewer written to {args.output}")
        raise SystemExit(0)

    if args.command == "si-constraints":
        from .si_constraints import analyze_si_constraints

        spec = _load_spec_file(args.spec)
        compiled = compile_design_ir(spec)
        result = analyze_si_constraints(compiled.components)

        if args.json_output:
            _print_json(result)
        else:
            print(result["summary"])
            for bus in result["buses_detected"]:
                print(f"  {bus['description']} on {bus['component']} ({bus['net_count']} nets)")
            for ic in result["impedance_constraints"]:
                print(f"  Impedance: {ic['description']}")
            for lg in result["length_groups"]:
                print(f"  Length match: {lg['description']} ({len(lg['nets'])} nets)")
            for rr in result["routing_rules"]:
                print(f"  Rule: {rr['description']}")

        raise SystemExit(0)

    if args.command == "thermal-analysis":
        from .placement_optimizer import PlacementConfig, optimize_placement
        from .thermal_analysis import analyze_thermal, generate_heatmap_svg

        spec = _load_spec_file(args.spec)
        compiled = compile_design_ir(spec)

        cfg = PlacementConfig(board_width_mm=args.board_width, board_height_mm=args.board_height)
        opt = optimize_placement(compiled.components, config=cfg, specs_dir=args.specs_dir)
        placements = opt["placements"]

        result = analyze_thermal(
            compiled.components,
            placements,
            specs_dir=args.specs_dir,
            ambient_temp_c=args.ambient,
        )

        if args.json_output:
            _print_json(result)
        else:
            print(result["summary"])
            for c in result["components"]:
                status_icon = {"ok": "  ", "warning": "! ", "critical": "!!"}[c["status"]]
                tj_line = (
                    f"  {status_icon}{c['ref']:6s} {c['pdiss_w']:6.3f}W  "
                    f"Tj={c['tj_calculated']:.0f}°C  "
                    f"max={c['tj_max']:.0f}°C  "
                    f"margin={c['margin_c']:.0f}°C"
                )
                print(tj_line)
                if c["suggestion"]:
                    print(f"         {c['suggestion']}")
            for w in result["proximity_warnings"]:
                print(
                    f"  [!] {w['ref_a']} + {w['ref_b']}: {w['distance_mm']}mm apart, {w['combined_heat_w']}W combined"
                )
            print()
            for rec in result["recommendations"]:
                print(f"  -> {rec}")

        if args.heatmap:
            generate_heatmap_svg(
                compiled.components,
                placements,
                board_width_mm=args.board_width,
                board_height_mm=args.board_height,
                specs_dir=args.specs_dir,
                ambient_temp_c=args.ambient,
                output_path=args.heatmap,
            )
            print(f"Heatmap written to {args.heatmap}")

        raise SystemExit(0)

    if args.command == "export-dual-cpl":
        from .jlcpcb_export import write_dual_sided_cpl
        from .placement_optimizer import PlacementConfig, optimize_placement

        spec = _load_spec_file(args.spec)
        compiled = compile_design_ir(spec)

        cfg = PlacementConfig()
        opt = optimize_placement(compiled.components, config=cfg)
        # Convert placement dict format to tuple format for CPL writer
        tuple_placements = {}
        for ref, p in opt["placements"].items():
            layer = "top" if p.get("layer", "front") in ("front", "top") else "bottom"
            tuple_placements[ref] = (p["x"], p["y"], p.get("rotation", 0), layer)

        result = write_dual_sided_cpl(
            compiled.components,
            tuple_placements,
            Path(args.output),
            assembly_mode=args.assembly_mode,
        )

        print(f"Top CPL:    {result['top_file']} ({result['top_count']} components)")
        print(f"Bottom CPL: {result['bottom_file']} ({result['bottom_count']} components)")
        print(f"Mode:       {result['assembly_mode']}")
        for w in result["warnings"]:
            print(f"  [!] {w}")

        raise SystemExit(0)

    if args.command == "panelize":
        from .panelizer import PanelConfig, suggest_panel

        pcfg = PanelConfig(
            max_panel_width_mm=args.panel_width,
            max_panel_height_mm=args.panel_height,
            breakaway_type=args.breakaway,
        )
        result = suggest_panel(args.board_width, args.board_height, qty=args.qty, config=pcfg)

        if args.json_output:
            _print_json(result)
        else:
            print(f"Board: {args.board_width}x{args.board_height} mm, Qty: {args.qty}")
            for i, opt in enumerate(result["panel_options"]):
                rec = " (recommended)" if i == result["recommended"] else ""
                print(
                    f"  Option {i + 1}{rec}: {opt['cols']}x{opt['rows']} = {opt['boards_per_panel']}/panel "
                    f"({opt['panel_width_mm']}x{opt['panel_height_mm']} mm, {opt['utilization_pct']}% util, "
                    f"{opt['panels_needed']} panels, {opt['waste_boards']} waste)"
                )
            ce = result.get("cost_estimate", {})
            if ce:
                print(
                    f"  Cost: panelized ${ce['panelized']['estimated_cost']:.2f} "
                    f"(${ce['panelized']['per_board']:.4f}/board) vs "
                    f"single ${ce['single_boards']['estimated_cost']:.2f} "
                    f"(${ce['single_boards']['per_board']:.4f}/board) "
                    f"— {ce['savings_pct']:.0f}% savings"
                )
            for w in result["warnings"]:
                print(f"  [!] {w}")
            for rule in result["design_rules"]:
                print(f"  Rule: {rule}")

        raise SystemExit(0)

    if args.command == "design-enclosure":
        from .enclosure_designer import generate_enclosure_scad, render_enclosure_stl

        scad_code = generate_enclosure_scad(
            board_width_mm=args.board_width,
            board_height_mm=args.board_height,
            board_thickness_mm=args.board_thickness,
            component_height_mm=args.component_height,
            wall_thickness_mm=args.wall_thickness,
            clearance_mm=args.clearance,
            vents=args.vents,
        )

        output_path = Path(args.output)
        output_path.write_text(scad_code, encoding="utf-8")
        print(f"OpenSCAD enclosure written to {output_path}")

        if args.render_stl:
            stl_path = Path(args.stl_output) if args.stl_output else output_path.with_suffix(".stl")
            result = render_enclosure_stl(output_path, output_path=stl_path)
            if result:
                print(f"STL rendered to {result}")
            else:
                print("STL rendering skipped (OpenSCAD CLI not available)")

        raise SystemExit(0)

    if args.command == "check-dfm":
        from .dfm_checker import check_dfm, dfm_report

        violations = check_dfm(
            args.kicad_pcb,
            profile=args.profile or "jlcpcb",
        )

        # Print human-readable report to stderr, JSON to stdout
        print(dfm_report(violations), file=sys.stderr)
        _print_json(
            {
                "status": "ok",
                "violations_count": len(violations),
                "critical_count": len([v for v in violations if v.severity == "critical"]),
                "warnings_count": len([v for v in violations if v.severity == "warning"]),
                "violations": [v.to_dict() for v in violations],
            }
        )
        raise SystemExit(0 if not any(v.severity == "critical" for v in violations) else 1)

    if args.command == "generate-docs":
        from .design_docs import generate_all_docs

        spec = _load_spec_file(args.spec)
        compiled = _run_with_stderr_capture(lambda: compile_design_ir(spec))

        datasheets_dir = Path(args.datasheets_dir) if args.datasheets_dir else None

        results = generate_all_docs(
            compiled,
            output_dir=args.output,
            datasheets_dir=datasheets_dir,
        )

        file_summary = {name: str(path) for name, path in results.items()}
        _print_json(
            {
                "status": "ok",
                "message": f"Design documentation generated in {args.output}",
                "output_dir": str(args.output),
                "files": file_summary,
            }
        )
        raise SystemExit(0)

    if args.command == "erc":
        from .erc_runner import run_erc

        erc_result = run_erc(args.schematic)
        payload = erc_result.to_dict()
        exit_code = 1 if erc_result.status == "failed" or erc_result.errors > 0 else 0

        if getattr(args, "json_output", False):
            _print_json(payload)
        else:
            status = erc_result.status
            if status == "skipped":
                print(f"ERC: skipped — {erc_result.skip_reason}", file=sys.stderr)
            elif status == "failed":
                print(f"ERC: failed — {erc_result.skip_reason}", file=sys.stderr)
            else:
                if erc_result.errors == 0 and erc_result.warnings == 0:
                    print("ERC: PASS 0 errors, 0 warnings")
                else:
                    print(f"ERC: {erc_result.errors} error(s), {erc_result.warnings} warning(s)")
                    for v in erc_result.violations:
                        prefix = "ERROR" if v.severity == "error" else "WARN "
                        print(f"  [{prefix}] {v.type}: {v.description}")

        raise SystemExit(exit_code)

    if args.command == "doctor":
        from .doctor import run_doctor

        report = run_doctor()
        if getattr(args, "json_output", False):
            _print_json(report.to_dict())
        else:
            print(report.to_terminal())
        raise SystemExit(0 if report.all_ok else 1)

    if args.command == "confidence":
        try:
            from .confidence_dashboard import generate_confidence_report
            from .cross_reference_validator import run_cross_reference_audit

            spec = _load_spec_file(args.spec)
            compiled = _run_with_stderr_capture(
                lambda: compile_design_ir(spec, enrich_parts=getattr(args, "enrich_parts", False))
            )

            # Run validation
            report = _run_with_stderr_capture(
                lambda: validate_design(spec, enrich_parts=getattr(args, "enrich_parts", False))
            )

            # Run cross-reference audit
            xref_results = run_cross_reference_audit(compiled.components, spec=spec)

            # Optional: run simulations
            sim_report = None
            if getattr(args, "run_sims", False):
                from .simulation import run_design_simulations

                sim_report = run_design_simulations(
                    compiled.components,
                    output_dir=Path(args.spec).parent / "sims",
                    spec=spec,
                )

            # Optional: DFM check
            dfm_violations = None
            pcb_path = getattr(args, "pcb", None)
            if pcb_path:
                from .dfm_checker import check_dfm

                dfm_violations = check_dfm(pcb_path)

            # Optional: ERC
            erc_result = None
            output_dir = Path(args.spec).parent / "output"
            sch_files = list(output_dir.glob("*.kicad_sch")) if output_dir.exists() else []
            if sch_files:
                from .erc_runner import run_erc

                erc_result = run_erc(sch_files[0])

            # Optional: thermal
            thermal_result = None
            try:
                from .thermal_analysis import analyze_thermal

                thermal_result = analyze_thermal(compiled.components)
            except Exception as thermal_exc:
                print(f"  Thermal analysis skipped: {thermal_exc}", file=sys.stderr)

            confidence = generate_confidence_report(
                components=compiled.components,
                project=spec.get("project", "Unknown"),
                validation_report=report,
                sim_report=sim_report,
                thermal_result=thermal_result,
                dfm_violations=dfm_violations,
                erc_result=erc_result,
                xref_results=xref_results,
                spec=spec,
            )

            if getattr(args, "json_output", False):
                _print_json(confidence.to_dict())
            else:
                print(confidence.to_terminal())

            # Write HTML if requested
            output_path = getattr(args, "output", None)
            if output_path:
                Path(output_path).write_text(confidence.to_html(), encoding="utf-8")
                print(f"\nHTML report written to: {output_path}", file=sys.stderr)

            raise SystemExit(0)
        except SystemExit:
            raise
        except Exception as exc:
            print(f"Error running confidence report: {exc}", file=sys.stderr)
            print("  Hint: Ensure the spec file is valid YAML and can be compiled.", file=sys.stderr)
            raise SystemExit(1)

    if args.command == "simulate":
        try:
            from .simulation import plan_simulations, run_design_simulations

            spec = _load_spec_file(args.spec)
            compiled = _run_with_stderr_capture(lambda: compile_design_ir(spec))
            plan = plan_simulations(compiled.components, spec=spec)

            # Filter plan by scope
            sim_scope = getattr(args, "sim_scope", "all")
            if sim_scope == "power":
                plan.signal_sims = []
                plan.thermal_sims = []
            elif sim_scope == "signal":
                plan.power_sims = []
                plan.thermal_sims = []
            elif sim_scope == "thermal":
                plan.power_sims = []
                plan.signal_sims = []

            model_dir = getattr(args, "model_dir", None)
            if model_dir is None:
                # Auto-detect: look for spice_models/ in spec directory
                spec_dir = Path(args.spec).parent
                candidate = spec_dir / "spice_models"
                if candidate.exists():
                    model_dir = str(candidate)

            report = run_design_simulations(
                compiled.components,
                plan=plan,
                output_dir=args.output,
                model_dir=model_dir,
                spec=spec,
            )

            if getattr(args, "json_output", False):
                _print_json(report.to_dict())
            else:
                print(f"\n{report.summary}")
                if report.recommendations:
                    print("\nRecommendations:")
                    for rec in report.recommendations:
                        print(f"  - {rec}")
                print(f"\nSimulation output: {args.output}", file=sys.stderr)
            raise SystemExit(0)
        except SystemExit:
            raise
        except Exception as exc:
            print(f"Error running simulations: {exc}", file=sys.stderr)
            print("  Hint: Ensure the spec file is valid and can be compiled.", file=sys.stderr)
            raise SystemExit(1)

    if args.command == "discover":
        try:
            from .project_discovery import discover_projects, format_project_table

            root = Path(getattr(args, "root", "."))
            depth = getattr(args, "depth", 2)
            projects = discover_projects(root, max_depth=depth)

            if getattr(args, "json_output", False):
                _print_json([p.to_dict() for p in projects])
            else:
                if projects:
                    print(f"\nFound {len(projects)} circuit project(s):\n")
                    print(format_project_table(projects))
                    print()
                else:
                    print("\nNo circuit projects found in this directory.\n")
            raise SystemExit(0)
        except SystemExit:
            raise
        except Exception as exc:
            print(f"Error discovering projects: {exc}", file=sys.stderr)
            raise SystemExit(1)

    if args.command == "save-research":
        import json as _json_mod

        from .research_store import save_research_from_dict

        project_dir = Path(args.output)
        project_dir.mkdir(parents=True, exist_ok=True)
        log_workflow_step(
            "save-research",
            "start",
            f"Persisting research result to {project_dir}/research/",
        )
        try:
            if args.file:
                raw = Path(args.file).read_text(encoding="utf-8")
            else:
                raw = sys.stdin.read()
            if not raw.strip():
                print("Error: no JSON payload provided (use --file or stdin)", file=sys.stderr)
                raise SystemExit(2)
            payload = _json_mod.loads(raw)
            if not isinstance(payload, dict):
                print("Error: research payload must be a JSON object", file=sys.stderr)
                raise SystemExit(2)
            if args.topic:
                payload["topic"] = args.topic
            if args.backend:
                payload["backend"] = args.backend
            saved_path = save_research_from_dict(project_dir, payload)
        except SystemExit:
            raise
        except _json_mod.JSONDecodeError as exc:
            print(f"Error: invalid JSON payload: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
        except Exception as exc:
            print(f"Error saving research: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc

        if getattr(args, "json_output", False):
            print(_json_mod.dumps({"path": str(saved_path)}, indent=2))
        else:
            print(f"Saved research → {saved_path}", file=sys.stderr)
        raise SystemExit(0)

    if args.command == "log-event":
        try:
            project_dir = Path(args.project_dir)
            if not project_dir.exists():
                project_dir.mkdir(parents=True, exist_ok=True)
            dl = DesignLogger(project_dir)
            event_type = args.type
            message = args.message
            data: dict[str, Any] = {}
            if args.data:
                try:
                    data = json.loads(args.data)
                except json.JSONDecodeError as exc:
                    print(f"Error: --data must be valid JSON: {exc}", file=sys.stderr)
                    raise SystemExit(1)

            if event_type == "wizard_step":
                dl.log_step(step=data.get("step", 0), description=message, user_input=data.get("user_input"))
            elif event_type == "cli_call":
                dl.log_cli_call(
                    command=data.get("command", "unknown"),
                    args=data.get("args", []),
                    return_code=data.get("return_code", 0),
                    stdout=data.get("stdout", ""),
                    stderr=data.get("stderr", ""),
                    duration_sec=data.get("duration_sec", 0.0),
                    generated_files=data.get("generated_files"),
                )
            elif event_type == "validation":
                dl.log_validation(
                    spec_file=data.get("spec_file", ""),
                    passed=data.get("passed", True),
                    errors=data.get("errors"),
                    warnings=data.get("warnings"),
                )
            elif event_type == "research":
                dl.log_research(
                    query_phase=data.get("phase", ""),
                    query=message,
                    status=data.get("status", "ok"),
                    result_count=data.get("result_count", 0),
                    backend=data.get("backend", ""),
                    artifact_path=data.get("artifact_path", ""),
                )
            elif event_type == "part_lookup":
                dl.log_part_lookup(
                    mpn=data.get("mpn", ""),
                    source=data.get("source", ""),
                    status=data.get("status", "ok"),
                    details=data.get("details"),
                )
            elif event_type == "symbol_resolution":
                dl.log_symbol_resolution(
                    ref=data.get("ref", ""),
                    mpn=data.get("mpn", ""),
                    status=data.get("status", "ok"),
                    pinout_source=data.get("pinout_source", ""),
                )
            elif event_type == "simulation":
                dl.log_simulation(
                    sim_type=data.get("sim_type", ""),
                    target=data.get("target", ""),
                    status=data.get("status", "ok"),
                    metrics=data.get("metrics"),
                    duration_sec=data.get("duration_sec", 0.0),
                )
            elif event_type == "thermal":
                dl.log_thermal(
                    ref=data.get("ref", ""),
                    tj_calc=data.get("tj_calc", 0.0),
                    tj_max=data.get("tj_max", 0.0),
                    status=data.get("status", "ok"),
                )
            elif event_type == "erc_drc":
                dl.log_erc_drc(
                    check_type=data.get("check_type", ""),
                    file=data.get("file", ""),
                    errors=data.get("errors", 0),
                    warnings=data.get("warnings", 0),
                    details=data.get("details"),
                )
            elif event_type == "scoring":
                dl.log_scoring(
                    dimension=data.get("dimension", ""),
                    score=data.get("score", 0.0),
                    grade=data.get("grade", ""),
                    gaps=data.get("gaps"),
                )
            elif event_type == "sourcing":
                dl.log_sourcing(
                    mpn=data.get("mpn", ""),
                    supplier=data.get("supplier", ""),
                    status=data.get("status", "ok"),
                    price=data.get("price"),
                    stock=data.get("stock"),
                )
            elif event_type == "generation":
                dl.log_generation(
                    artifact_type=data.get("artifact_type", ""),
                    path=data.get("path", ""),
                    status=data.get("status", "ok"),
                    duration_sec=data.get("duration_sec", 0.0),
                )
            elif event_type == "error":
                dl.log_error(
                    operation=data.get("operation", "unknown"),
                    error=message,
                    traceback=data.get("traceback", ""),
                )
            print(f"Logged {event_type} event to {dl.log_path}", file=sys.stderr)
            raise SystemExit(0)
        except SystemExit:
            raise
        except Exception as exc:
            print(f"Error logging event: {exc}", file=sys.stderr)
            raise SystemExit(1)


def _wizard_input(prompt: str, *, dry_run: bool = False, default: str = "", max_retries: int = 3) -> str:
    """Get user input with dry-run support.

    Args:
        prompt: The prompt to display
        dry_run: If True, return default without prompting
        default: Default value if user enters empty or dry-run is True
        max_retries: Number of times to re-prompt on empty input

    Returns:
        User-provided value or default
    """
    if dry_run:
        print(f"{prompt} [dry-run: '{default}']")
        return default

    for attempt in range(max_retries):
        val = input(prompt).strip()
        if val:
            return val
        if attempt < max_retries - 1:
            print(f"  (empty — please enter a value, or press Enter again to use default: '{default}')")
    return default


def _find_existing_circuits(root_dir: Path = None) -> list[Path]:
    """Find all circuit project directories.

    Uses the project_discovery module for enhanced detection of
    design.yaml, .kicad_pro, and .kicad_sch projects.

    Args:
        root_dir: Directory to search in (default: current working directory)

    Returns:
        List of Path objects to project directories, sorted by name
    """
    from .project_discovery import discover_projects

    projects = discover_projects(root_dir, max_depth=1)
    return [p.path for p in projects]


def _handle_design_workflow(
    resume: str | None = None,
    dry_run: bool = False,
    research_backend: str | None = None,
    research_depth: str | None = None,
) -> None:
    """Orchestrate new or existing circuit design workflow.

    Args:
        resume: Path to a partially-completed design.yaml to resume from
        dry_run: If True, use default answers for all prompts
        research_backend: Effective backend for downstream agent research steps
        research_depth: Effective research depth profile for downstream agent research steps

    Prompts user to choose:
    1. Create a new circuit (captures name, creates folder, runs wizard)
    2. Open an existing circuit (lists available, loads and shows status)
    """
    # If resume is specified, load and continue from that spec
    if resume:
        print(f"\n[Resuming from {resume}]")
        spec = _load_spec_file(resume)
        print(f"Project: {spec.get('project', 'unnamed')}")
        # For now, just show the spec and exit (full resume logic would continue wizard from step N)
        print("\n[Resume support: load spec and continue wizard from current step]")
        print("(Full implementation in future sprints)")
        return

    print("\n" + "=" * 72)
    print("Circuit Weaver — Design Workflow")
    print("=" * 72)
    print("\nWhat would you like to do?\n")
    print("  [1] Design a new circuit")
    print("  [2] Open an existing circuit\n")

    choice = _wizard_input("Your choice (1 or 2): ", dry_run=dry_run, default="1")

    if choice == "2":
        # EXISTING CIRCUIT FLOW
        root = Path.cwd()
        projects = _find_existing_circuits(root)

        if not projects:
            print("[!] No existing circuits found in current directory.")
            print("    Tip: Create a new circuit first.\n")
            raise SystemExit(1)

        print("\nAvailable circuits:\n")
        for i, proj in enumerate(projects, 1):
            print(f"  [{i}] {proj.name}")
        print()

        try:
            proj_choice = int(input(f"Select (1-{len(projects)}): ").strip())
            if proj_choice < 1 or proj_choice > len(projects):
                raise ValueError
            selected_project = projects[proj_choice - 1]
        except (ValueError, IndexError):
            print("[!] Invalid choice.\n")
            raise SystemExit(1)

        # Load and show status
        logger = DesignLogger(selected_project)
        print()
        logger.print_summary()

        print("\nNext steps:")
        spec_path = selected_project / "design.yaml"
        output_path = selected_project / "output"
        print(f"  1. Validate: circuit-weaver validate {spec_path}")
        print(f"  2. Generate: circuit-weaver generate {spec_path} -o {output_path}")
        print(f"  3. Modify: Edit {spec_path} and re-validate\n")

        raise SystemExit(0)

    elif choice == "1":
        # NEW CIRCUIT FLOW
        print("\n--- New Circuit ---\n")

        # Capture project name FIRST
        project_name = input("Project name (folder will be created with this name): ").strip()
        if not project_name:
            project_name = "MyCircuit_v1"

        # Create project directory
        project_dir = Path.cwd() / project_name
        if project_dir.exists():
            response = input(f"\nFolder '{project_name}' already exists. Continue? (y/n): ").strip().lower()
            if response != "y":
                print("[!] Cancelled.\n")
                raise SystemExit(1)
        else:
            project_dir.mkdir(parents=True, exist_ok=True)
            print(f"\n[+] Created folder: {project_dir.absolute()}\n")

        # Run wizard in that directory
        spec, logger = _run_design_wizard(
            project_dir,
            project_name_override=project_name,
            research_backend=research_backend,
            research_depth=research_depth,
        )

        if spec and logger:
            output_file = project_dir / "design.yaml"
            output_file.write_text(spec_to_yaml_text(spec), encoding="utf-8", newline="")
            print(f"\n[+] Design saved to {output_file.absolute()}")
            print(f"[+] Workflow log saved to {logger.log_path}")
            logger.log_step(
                0, "design-wizard completed", {"output_file": str(output_file), "project_name": project_name}
            )
            logger.print_summary()

            print("\nWorkflow commands:")
            print(f"  circuit-weaver log-view {project_dir}     # View log entries")
            print(f"  circuit-weaver log-status {project_dir}   # Show workflow summary\n")
            print("Next steps:")
            print(f"  1. Review the spec: cat {output_file}")
            print(f"  2. Validate: circuit-weaver validate {output_file}")
            print(f"  3. Generate: circuit-weaver generate {output_file} -o {project_dir / 'output'}")
            print()

            raise SystemExit(0)
        else:
            raise SystemExit(1)

    else:
        print("[!] Invalid choice. Please enter 1 or 2.\n")
        raise SystemExit(1)


def _run_design_wizard(
    project_dir: Path | str = ".",
    project_name_override: str | None = None,
    research_backend: str | None = None,
    research_depth: str | None = None,
) -> tuple[dict[str, Any] | None, DesignLogger | None]:
    """Interactive offline design wizard — capture requirements, scaffold spec (no hardcoded options).

    For interactive UI with buttons/checkboxes, use the /circuit-weaver skill in Claude Code.
    This CLI mode uses plain input() for terminal compatibility.

    Args:
        project_dir: Directory to write design.log to
        project_name_override: If provided, use this project name instead of asking
        research_backend: Effective backend for downstream agent research steps
        research_depth: Effective research depth profile for downstream agent research steps

    Returns:
        Tuple of (spec dict, logger) or (None, None) if cancelled
    """
    if research_backend is None or research_depth is None:
        from .research import resolve_backend, resolve_depth

        if research_backend is None:
            research_backend = resolve_backend(None)
        if research_depth is None:
            research_depth = resolve_depth(None)

    project_dir = Path(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    from .logging_bridge import get_design_logger as _get_design_logger
    from .logging_bridge import init_logging as _init_logging

    _init_logging(project_dir)
    logger = _get_design_logger()

    print("\n" + "=" * 80)
    print("Circuit Weaver Design Wizard")
    print("=" * 80)
    print("\nI'll scaffold a design spec from your requirements.")
    print("Press Enter to use defaults.\n")

    # ===== STEP 1a: PROJECT NAME (FIRST - creates folder + log immediately) =====
    print("-" * 80)
    print("STEP 1a: PROJECT NAME")
    print("-" * 80)

    if project_name_override:
        project_name = project_name_override
        print(f"Project: {project_name}\n")
    else:
        project_name = input("Project name [MyDesign_v1]: ").strip()
        if not project_name:
            project_name = "MyDesign_v1"

    # Create project folder + initialize logger IMMEDIATELY
    project_dir = Path(project_name)
    project_dir.mkdir(parents=True, exist_ok=True)
    from .logging_bridge import get_design_logger, init_logging

    init_logging(project_dir)
    logger = get_design_logger()
    assert logger is not None

    print(f"✓ Project folder created: {project_dir.resolve()}")
    print(f"✓ Logfile created: {project_dir / 'design.log'}")
    if research_backend:
        print(f"✓ Downstream research backend: {research_backend} (used by agent workflows)")
    if research_depth:
        print(f"✓ Downstream research depth: {research_depth} (used by agent workflows)")
    print()
    project_context = {"project_name": project_name}
    if research_backend:
        project_context["research_backend"] = research_backend
    if research_depth:
        project_context["research_depth"] = research_depth
    logger.log_step(1, "Project created", project_context)

    # ===== STEP 1b: EXPERIENCE LEVEL =====
    print("-" * 80)
    print("STEP 1b: EXPERIENCE LEVEL")
    print("-" * 80)
    experience = input("Experience (Beginner/Intermediate/Advanced/Professional) [Intermediate]: ").strip()
    experience = _normalize_wizard_experience(experience)

    logger.log_step(2, "Step 1b: Experience level captured", {"experience": experience})

    # ===== STEP 1c: REQUIREMENTS INTAKE =====
    print("\n" + "-" * 80)
    print("STEP 1c: REQUIREMENTS INTAKE")
    print("-" * 80)
    if experience == "Beginner":
        print("Beginner mode: we'll go one concept at a time and keep the prompts plain-language.")
    elif experience == "Advanced":
        print("Advanced mode: start with a compact design brief, then fill only the missing fields.")
    elif experience == "Professional":
        print("Professional mode: give me a compact design brief or spec fragment first.")
        print("I'll keep the follow-up prompts short and only collect what the YAML still needs.")
    else:
        print("Intermediate mode: guided prompts with defaults and short examples.")

    responses: dict[str, str] = {}
    for key, prompt, default in _wizard_requirement_prompt_plan(experience):
        value = input(prompt).strip()
        responses[key] = value or default

    purpose = responses["purpose"]
    form_factor = responses["form_factor"]
    input_power = responses["input_power"]
    output_rails = responses["output_rails"]
    interfaces = responses["interfaces"]
    mcu = responses["mcu"]
    components = responses["components"]
    special_reqs = responses["special_reqs"]

    logger.log_step(3, "Step 1c: Basic info captured", {"purpose": purpose})
    logger.log_step(4, "Step 1d: Form factor captured", {"form_factor": form_factor})
    logger.log_step(
        5, "Step 1e: Power requirements captured", {"input_power": input_power, "output_rails": output_rails}
    )

    logger.log_step(
        6,
        "Step 1f: Interfaces & components captured",
        {"interfaces": interfaces, "mcu": mcu, "components": components, "special_reqs": special_reqs},
    )

    # Build a minimal, editable spec scaffold
    spec: dict[str, Any] = {
        "metadata": {
            "title": project_name,
            "version": "1.0",
            "description": f"{purpose}. Created via circuit-weaver design-wizard (offline).",
            "research_backend": research_backend or "standard",
            "research_depth": research_depth or "normal",
        },
        "interfaces": {
            "power_in": {
                "purpose": f"Input: {input_power}",
                "voltage": 3.3,  # placeholder
                "current_budget_ma": 500,
            },
        },
        "blocks": {
            "U1_power": {
                "ref": "U1",
                "section": "power",
                "kind": "template",
                "template_type": "ldo",  # user to customize: ldo, buck, boost, etc.
                "params": {
                    "vin": 3.3,  # user to customize
                    "vout": 3.3,  # user to customize
                    "iout_ma": 500,  # user to customize
                },
            },
        },
    }

    # Print summary in form-like table
    print("\n" + "=" * 80)
    print("[DESIGN SPEC CAPTURED]")
    print("=" * 80)

    print("\nPROJECT")
    print(f"  Name:       {project_name}")
    print(f"  Logfile:    {project_dir.resolve() / 'design.log'}")

    print("\nBASIC INFO")
    print(f"  Purpose:    {purpose}")
    print(f"  Experience: {experience}")
    print(f"  Form Factor:{form_factor}")

    print("\nPOWER SUPPLY")
    print(f"  Input:      {input_power}")
    print(f"  Output:     {output_rails}")

    print("\nCOMPONENTS & INTERFACES")
    print(f"  Interfaces: {interfaces}")
    print(f"  MCU:        {mcu}")
    print(f"  Components: {components}")
    if special_reqs:
        print(f"  Special:    {special_reqs}")

    logger.log_step(
        7,
        "Step 1g: Requirements summary confirmed",
        {
            "project_name": project_name,
            "purpose": purpose,
            "experience": experience,
            "form_factor": form_factor,
            "input_power": input_power,
            "output_rails": output_rails,
            "interfaces": interfaces,
            "mcu": mcu,
            "components": components,
            "special_reqs": special_reqs,
        },
    )

    log_file = project_dir / "design.log"
    print("\n" + "-" * 80)
    print("NEXT STEPS")
    print("-" * 80)
    print(f"  1. Design log: {log_file}")
    print("  2. View progress: circuit-weaver log-status <project_dir>")
    print("  3. View recent entries: circuit-weaver log-view <project_dir>")
    print("  4. Edit the YAML file to add your components and customize the power supply")
    print("  5. Use 'circuit-weaver list-templates' to see available circuit templates")
    print("  6. Use 'circuit-weaver scaffold --template <name>' to add templates")
    print("  7. Validate: circuit-weaver validate <file>")
    print("  8. Generate: circuit-weaver generate <file> -o ./output")
    print("\n  Tip: Use the /circuit-weaver skill in Claude Code for automatic IC research")
    print("=" * 80 + "\n")

    return spec, logger


def _print_cost_bom_table(result: dict) -> None:
    """Print a costed BOM result as a formatted table (stdlib only, no tabulate)."""
    if result["status"] != "ok":
        print(f"[!] Error: {result.get('message', 'Unknown error')}")
        return

    project = result.get("project", "Unknown")
    qty_breaks = result.get("qty_breaks", [])
    rows = result.get("rows", [])
    totals = result.get("totals", {})
    warnings = result.get("warnings", [])

    # Print header
    print()
    print(f"=== Costed BOM: {project} ===")
    print()

    # Compute column widths
    ref_width = max(10, max((len(r.get("ref", "")) for r in rows), default=10))
    mpn_width = max(10, max((len(r.get("mpn", "")) for r in rows), default=10))
    lcsc_width = 10
    qty_width = 4
    unit_widths = {str(q): max(7, len(f"${0.00}")) for q in qty_breaks}

    # Print column headers
    header = f"{'Ref':<{ref_width}} {'MPN':<{mpn_width}} {'LCSC':<{lcsc_width}} {'Qty':<{qty_width}}"
    for q in qty_breaks:
        header += f"  {'$' + str(q):<{unit_widths[str(q)]}}"
    print(header)
    print("-" * len(header))

    # Print rows
    for row in rows:
        ref = row.get("ref", "")
        mpn = row.get("mpn", "")
        lcsc = row.get("lcsc_pn", "")
        qty = row.get("qty_per_board", 0)
        prices = row.get("prices", {})

        line = f"{ref:<{ref_width}} {mpn:<{mpn_width}} {lcsc:<{lcsc_width}} {qty:<{qty_width}}"
        for q in qty_breaks:
            unit_price = prices.get(str(q), {}).get("unit", 0)
            line += f"  ${unit_price:<{unit_widths[str(q)] - 1}}"
        print(line)

    # Print separator and totals
    print("-" * len(header))
    line = f"{'Total':<{ref_width + mpn_width + lcsc_width + qty_width + 1}}"
    for q in qty_breaks:
        total = totals.get(str(q), {}).get("component_cost", 0)
        line += f"  ${total:<{unit_widths[str(q)] - 1}}"
    print(line)
    print()

    # Print warnings
    if warnings:
        for warning in warnings:
            print(f"[!] {warning}")
        print()


if __name__ == "__main__":
    main()
