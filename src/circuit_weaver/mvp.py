"""Transactional MVP workflow for the schematic engine.

This module layers a canonical Design IR, patch application, strict grouped
validation, derived artifact generation, semantic diffing, and PCB constraint
feedback on top of the existing schematic engine.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .component_db import ComponentDef, PresentationWiringPolicy
from .design_ir import (
    DesignBlock,
    DesignInterface,
    DesignIR,
    design_ir_to_engine_spec,
    design_ir_to_spec,
    normalize_design_spec,
    semantic_diff,
)
from .generator import generate_from_components
from .project_spec import _parse_yaml, _simple_yaml_parse, resolve_project_spec
from .subcircuits.base import BoundaryPort, get_default_registry
from .validator import run_validation_checks

_MVP_PROFILE = "mvp_strict"
_POWER_NET_PREFIXES = ("GND", "VDD", "VCC", "VBUS", "VIN", "VDDA", "MGT", "VCCO")
_PRESENTATION_SVG_MARGIN = 0.5


@dataclass(frozen=True)
class ValidationMessage:
    category: str
    code: str
    level: str
    subject: str
    message: str


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


@dataclass
class CompiledDesign:
    ir: DesignIR
    components: list[ComponentDef]
    metadata: dict[str, Any]
    engine_spec: dict[str, Any]


def _ensure_profile(profile: str) -> str:
    normalized = (profile or _MVP_PROFILE).strip().lower()
    if normalized != _MVP_PROFILE:
        raise ValueError(f"Unsupported MVP validation profile '{profile}'")
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


def compile_design_ir(
    spec: dict[str, Any],
    *,
    enrich_parts: bool = False,
) -> CompiledDesign:
    """Compile a design spec into normalized IR + resolved engine components."""
    ir = normalize_design_spec(spec)
    engine_spec = design_ir_to_engine_spec(ir)
    components, metadata = resolve_project_spec(engine_spec, enrich_parts=enrich_parts)
    components = copy.deepcopy(components)
    _apply_block_attributes(ir, components)
    _apply_approved_overrides(ir, components)
    hydrated_ir = _hydrate_ir_from_components(ir, components)
    metadata.update(
        {
            "project": hydrated_ir.metadata.get("project", metadata.get("project", "project")),
            "company": hydrated_ir.metadata.get("company", metadata.get("company", "")),
            "version": hydrated_ir.metadata.get("version", metadata.get("version", "")),
            "description": hydrated_ir.metadata.get("description", metadata.get("description", "")),
        }
    )
    return CompiledDesign(
        ir=hydrated_ir,
        components=components,
        metadata=metadata,
        engine_spec=engine_spec,
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
            # Deduplicate (custom validators may overlap with schema checks)
            seen: set[str] = set()
            for error in custom_errors + schema_errors:
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
        if not primary.footprint:
            implementation.append(
                ValidationMessage(
                    category="implementation",
                    code="missing-footprint",
                    level="error",
                    subject=block.ref or block.id,
                    message="Resolved block has no footprint binding",
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
                                f"Symbol has {sym_pins} pins but footprint '{fp}' "
                                f"implies {fp_pins} pads — verify match"
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

        for pin in comp.pins:
            if pin.number in handled:
                continue
            # NC-named pins are fine
            if _NC_PIN_NAME_RE.match(pin.name):
                continue

            etype = pin.electrical_type or "unspecified"

            if etype == "power_in":
                issues.append(
                    ValidationMessage(
                        category="electrical",
                        code="floating-power-pin",
                        level="error",
                        subject=subject,
                        message=(
                            f"Power pin {pin.number} ({pin.name}) is not connected to any rail"
                        ),
                    )
                )
            elif etype in ("input", "bidirectional", "tri_state"):
                issues.append(
                    ValidationMessage(
                        category="electrical",
                        code="floating-input-pin",
                        level="warning",
                        subject=subject,
                        message=(
                            f"{etype.capitalize()} pin {pin.number} ({pin.name}) is unconnected "
                            f"— may need a pull-up/down, driver, or explicit no-connect"
                        ),
                    )
                )
    return issues


_VOLTAGE_PATTERN = re.compile(r"(\d+)[PV](\d+)|(\d+)V")


def _infer_rail_voltage(net: str) -> float | None:
    """Attempt to extract a voltage from a power net name (e.g., VDD_3P3 → 3.3)."""
    known = {
        "VDD_3P3": 3.3, "VDD_1P8": 1.8, "VDD_1P2": 1.2, "VDD_2P5": 2.5,
        "VBUS_5V": 5.0, "VCCAUX": 1.8, "VCCINT": 1.0, "VDD_DDR": 1.35,
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
                            f"Component requires {req.voltage}V on '{req.net}', "
                            f"but rail name implies {implied_v}V"
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
) -> tuple[list[str], Path | None]:
    output_dir.mkdir(parents=True, exist_ok=True)
    profile = compiled.metadata.get("presentation_profile", "default")
    pwp = PresentationWiringPolicy(support_passives="topology_local") if profile == "review" else None
    files = generate_from_components(
        compiled.components,
        str(output_dir),
        project_name=compiled.metadata.get("project", "project"),
        company=compiled.metadata.get("company", ""),
        stable_uuids=True,
        validate=True,
        pcb=True,
        hierarchical=True,
        interface_policy="explicit",
        presentation_wiring_policy=pwp,
        score=score,
    )
    root = _find_root_schematic(files, compiled.metadata.get("project", "project"))
    if export_svg and root is not None:
        cli = _kicad_cli_path()
        if cli is None:
            raise RuntimeError("KiCad CLI is required for strict artifact export smoke")
        svg_dir = output_dir / "svg"
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
    profile: str = _MVP_PROFILE,
    enrich_parts: bool = False,
    strict: bool = False,
) -> ValidationReport:
    """Validate a design spec against the strict MVP profile.

    When *strict* is True, warnings also count as failures (not just errors).
    """
    profile = _ensure_profile(profile)
    compiled = compile_design_ir(spec, enrich_parts=enrich_parts)

    categories: dict[str, list[ValidationMessage]] = {
        "structural": [],
        "electrical": [],
        "implementation": [],
        "presentation": [],
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

    for result in run_validation_checks(compiled.components):
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

    def _has_errors(msgs: list[ValidationMessage]) -> bool:
        return any(m.level == "error" for m in msgs)

    can_check_artifacts = (
        not _has_errors(categories["structural"])
        and not _has_errors(categories["electrical"])
        and not _has_errors(categories["implementation"])
    )
    if can_check_artifacts:
        with (
            tempfile.TemporaryDirectory(prefix="schematic_mvp_validate_a_") as tmp_a,
            tempfile.TemporaryDirectory(prefix="schematic_mvp_validate_b_") as tmp_b,
        ):
            try:
                files_a, root_a = _generate_compiled_artifacts(compiled, Path(tmp_a), export_svg=True)
                _files_b, _root_b = _generate_compiled_artifacts(compiled, Path(tmp_b), export_svg=False)
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
                if _kicad_text_map(Path(tmp_a)) != _kicad_text_map(Path(tmp_b)):
                    categories["implementation"].append(
                        ValidationMessage(
                            category="implementation",
                            code="nondeterministic-generation",
                            level="error",
                            subject=compiled.metadata.get("project", "project"),
                            message="Repeated stable-UUID generation produced different KiCad schematic text",
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

    # Checklist items derived from validation categories
    checklist = [
        ("All power pins connected", "electrical", "floating-power-pin", "missing-power-net"),
        ("All bypass caps placed", "electrical", "decoupling"),
        ("All enable pins driven", "electrical", "floating-enable"),
        ("No floating inputs", "electrical", "floating-input-pin"),
        ("Bus pull-ups present", "electrical", "i2c-missing-pullup"),
        ("No output conflicts", "electrical", "output-conflict"),
        ("No dangling nets", "electrical", "single-pin-net"),
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
    profile: str = _MVP_PROFILE,
    enrich_parts: bool = False,
) -> dict[str, Any]:
    """Apply a design patch transactionally and validate before acceptance."""
    profile = _ensure_profile(profile)
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


def generate_artifacts(
    spec: dict[str, Any],
    *,
    output_dir: str | Path,
    profile: str = _MVP_PROFILE,
    require_valid: bool = True,
    enrich_parts: bool = False,
    export_svg: bool = True,
    score: bool = False,
) -> dict[str, Any]:
    """Generate derived artifacts from a validated design spec."""
    profile = _ensure_profile(profile)
    report = validate_design(spec, profile=profile, enrich_parts=enrich_parts)
    if require_valid and not report.valid:
        raise ValueError("Design failed mvp_strict validation")

    compiled = compile_design_ir(spec, enrich_parts=enrich_parts)
    output_path = Path(output_dir)
    files, root = _generate_compiled_artifacts(compiled, output_path, export_svg=export_svg, score=score)

    spec_path = output_path / "canonical_spec.yaml"
    spec_path.write_text(spec_to_yaml_text(compiled.ir.to_dict()), encoding="utf-8", newline="")
    ir_path = output_path / "design_ir.json"
    ir_path.write_text(json.dumps(compiled.ir.to_dict(), indent=2), encoding="utf-8", newline="")
    report_path = output_path / "validation_report.json"
    report_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8", newline="")

    return {
        "output_dir": str(output_path),
        "project": compiled.metadata.get("project", "project"),
        "root_schematic": str(root) if root else "",
        "files": [str(path) for path in files],
        "validation_report": str(report_path),
        "design_ir": str(ir_path),
        "canonical_spec": str(spec_path),
        "valid": report.valid,
    }


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
    try:
        import yaml

        return yaml.safe_dump(spec, sort_keys=False, allow_unicode=False)
    except ImportError:
        return _simple_yaml_dump(spec) + "\n"


def _load_spec_file(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    return _parse_yaml(path)


def _load_patch_file(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml

            return yaml.safe_load(text) or {}
        except ImportError:
            return _simple_yaml_parse(text)
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Transactional MVP workflow for circuit_weaver")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_p = subparsers.add_parser("validate", help="Validate a canonical/legacy design spec")
    validate_p.add_argument("spec", help="Path to YAML/JSON design spec")
    validate_p.add_argument("--strict", action="store_true", default=False,
                            help="Treat warnings as errors (fail on any warning)")
    validate_p.add_argument("--enrich-parts", action="store_true", default=False)

    patch_p = subparsers.add_parser("apply-patch", help="Apply a transactional patch to a design spec")
    patch_p.add_argument("spec", help="Path to YAML/JSON design spec")
    patch_p.add_argument("patch", help="Path to JSON/YAML patch payload")
    patch_p.add_argument("--output", help="Write accepted updated spec to this YAML path")
    patch_p.add_argument("--enrich-parts", action="store_true", default=False)

    gen_p = subparsers.add_parser("generate", help="Generate derived KiCad artifacts from a spec")
    gen_p.add_argument("spec", help="Path to YAML/JSON design spec")
    gen_p.add_argument("--output", "-o", required=True, help="Artifact output directory")
    gen_p.add_argument("--no-require-valid", dest="require_valid", action="store_false")
    gen_p.add_argument("--no-svg", dest="export_svg", action="store_false")
    gen_p.add_argument("--enrich-parts", action="store_true", default=False)
    gen_p.add_argument(
        "--presentation-profile",
        choices=["default", "review"],
        default=None,
        help="Override the presentation profile (default | review)",
    )
    gen_p.add_argument("--score", action="store_true", default=False, help="Run aesthetics scorer on generated layouts")
    gen_p.set_defaults(require_valid=True, export_svg=True)

    diff_p = subparsers.add_parser("diff", help="Semantic diff between two design specs")
    diff_p.add_argument("old_spec", help="Path to the original YAML/JSON spec")
    diff_p.add_argument("new_spec", help="Path to the updated YAML/JSON spec")

    pcb_p = subparsers.add_parser("ingest-pcb-feedback", help="Merge PCB feedback into a design spec")
    pcb_p.add_argument("spec", help="Path to YAML/JSON design spec")
    pcb_p.add_argument("feedback", help="Path to PCB feedback JSON/YAML")
    pcb_p.add_argument("--output", help="Write updated spec to this YAML path")

    args = parser.parse_args()

    if args.command == "validate":
        strict = getattr(args, "strict", False)
        report = _run_with_stderr_capture(
            lambda: validate_design(
                _load_spec_file(args.spec), enrich_parts=args.enrich_parts, strict=strict,
            )
        )
        _print_json(report.to_dict())
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
        spec = _load_spec_file(args.spec)
        if args.presentation_profile:
            spec["presentation_profile"] = args.presentation_profile
        result = _run_with_stderr_capture(
            lambda: generate_artifacts(
                spec,
                output_dir=args.output,
                require_valid=args.require_valid,
                enrich_parts=args.enrich_parts,
                export_svg=args.export_svg,
                score=args.score,
            )
        )
        _print_json(result)
        raise SystemExit(0)

    if args.command == "diff":
        _print_json(diff_designs(_load_spec_file(args.old_spec), _load_spec_file(args.new_spec)))
        raise SystemExit(0)

    if args.command == "ingest-pcb-feedback":
        result = _run_with_stderr_capture(
            lambda: ingest_pcb_feedback(_load_spec_file(args.spec), _load_patch_file(args.feedback))
        )
        if args.output and result.updated_spec is not None:
            Path(args.output).write_text(spec_to_yaml_text(result.updated_spec), encoding="utf-8", newline="")
        _print_json(result.to_dict())
        raise SystemExit(0 if not result.rejected else 2)


if __name__ == "__main__":
    main()
