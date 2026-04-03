"""YAML project specification parser.

Parses a YAML project file into a list of ComponentDefs ready for the
schematic engine. Subcircuit templates are resolved from the registry,
standalone components from the component registry or KiCad library.

Example project.yaml:
    project: MyBoard
    company: Acme Corp
    power:
      - type: buck
        ic: AP62300
        ref: U1
        vin: 5
        vout: 3.3
        iout: 2
        vin_net: VBUS_5V
        en_net: VBUS_5V
      - type: ldo
        ic: TLV75518
        ref: U2
        vin: 3.3
        vout: 1.8
    digital:
      - ic: ESP32-WROOM-32E
        ref: U3
    connectors:
      - ic: USB-C-PWR
        ref: J1

Usage:
    from circuit_weaver.project_spec import load_project
    components = load_project("project.yaml")
    generate_from_components(components, output_dir="output/", project_name="MyBoard")
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from .component_db import (
    BUILTIN_REGISTRY,
    ComponentDef,
    ComponentRegistry,
    PinDef,
)
from .kicad_lib import KiCadLibrary
from .subcircuits.base import SubcircuitRegistry, get_default_registry


def _make_stub_component(name: str, category: str, ref: str = "", reason: str = "") -> ComponentDef:
    """Create a minimal stub ComponentDef for an unresolved component.

    The stub renders as a visible placeholder in the schematic with a
    warning annotation so the issue is never silently hidden.
    """
    annotation = f"UNRESOLVED: {reason}" if reason else f"UNRESOLVED: '{name}' not found"
    return ComponentDef(
        mpn=name or "UNKNOWN",
        ref_prefix=ref[:1].upper() if ref else "U",
        value=name or "UNKNOWN",
        footprint="",
        description="Unresolved component — verify manually",
        category=category,
        source_ref=ref,
        annotations=[annotation],
        pins=[
            PinDef("1", "~", "passive", "L"),
            PinDef("2", "~", "passive", "R"),
        ],
    )


def _parse_yaml(path: str | Path) -> dict:
    """Load YAML file. Supports PyYAML or falls back to simple parser."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    try:
        import yaml

        return yaml.safe_load(text)
    except ImportError:
        return _simple_yaml_parse(text)


def _simple_yaml_parse(text: str) -> dict:
    """Minimal YAML-subset parser for when PyYAML is not installed.

    Handles: top-level keys, string/number values, lists of dicts (one indent level).
    Does NOT handle: nested dicts, multi-line strings, anchors, tags.
    """
    result: dict[str, Any] = {}
    current_key = None
    current_list: list[dict] | None = None
    current_item: dict[str, Any] | None = None

    for raw_line in text.split("\n"):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip())

        # Top-level key: "project: MyBoard"
        if indent == 0 and ":" in stripped:
            # Flush current list
            if current_key and current_list is not None:
                if current_item:
                    current_list.append(current_item)
                result[current_key] = current_list

            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip()
            if val:
                result[key] = _coerce_value(val)
                current_key = None
                current_list = None
                current_item = None
            else:
                current_key = key
                current_list = []
                current_item = None
            continue

        # List item start: "  - type: buck"
        if stripped.startswith("- ") and current_list is not None:
            if current_item:
                current_list.append(current_item)
            current_item = {}
            item_content = stripped[2:].strip()
            if ":" in item_content:
                k, _, v = item_content.partition(":")
                current_item[k.strip()] = _coerce_value(v.strip())
            continue

        # List item continuation: "    vin: 5"
        if indent >= 4 and current_item is not None and ":" in stripped:
            k, _, v = stripped.partition(":")
            current_item[k.strip()] = _coerce_value(v.strip())
            continue

    # Flush final list
    if current_key and current_list is not None:
        if current_item:
            current_list.append(current_item)
        result[current_key] = current_list

    return result


def _coerce_value(val: str) -> Any:
    """Coerce a YAML value string to int, float, bool, or str."""
    if not val:
        return ""
    low = val.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low == "null" or low == "~":
        return None
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    # Strip quotes
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
        return val[1:-1]
    return val


# ================================================================
# Section categories -> sheet categories
# ================================================================

_SECTION_CATEGORY_MAP = {
    "power": "power",
    "power_distribution": "power",
    "digital": "mcu",
    "mcu": "mcu",
    "fpga": "fpga",
    "rf": "rf",
    "rf_frontend": "rf",
    "transceiver": "transceiver",
    "clock": "clock",
    "usb": "usb",
    "ethernet": "ethernet",
    "connectors": "connector",
    "sensors": "sensor",
    "storage": "storage",
    "debug": "debug",
    "communication": "communication",
    "analog": "analog",
    "discrete": "misc",
    "motor": "power",
    "motor_control": "power",
    "protection": "misc",
    "audio": "analog",
    "display": "mcu",
    "misc": "misc",
}


# ================================================================
# Net name handling for KiCad-imported components
# ================================================================

# Default power pin name → project rail name mapping
_DEFAULT_POWER_MAP = {
    "VCC": "VDD_3P3",
    "VDD": "VDD_3P3",
    "VIN": "VIN",
    "VBUS": "VBUS_5V",
    "V+": "VDD_3P3",
    "V-": "GND",
    "GND": "GND",
    "VSS": "GND",
    "AGND": "GND",
    "DGND": "GND",
    "GNDA": "GND",
    "GNDD": "GND",
    "VSSA": "GND",
}

# Signal pin names that should remain global (shared across instances)
_GLOBAL_SIGNAL_NAMES = frozenset(
    {
        "SDA",
        "SCL",
        "MOSI",
        "MISO",
        "SCLK",
        "SCK",
        "COPI",
        "CIPO",
        "TX",
        "RX",
        "TXD",
        "RXD",
        "CTS",
        "RTS",
        "D+",
        "D-",
        "USB_DP",
        "USB_DM",
        "CAN_H",
        "CAN_L",
        "CANH",
        "CANL",
        "SWDIO",
        "SWCLK",
        "SWO",
        "NRST",
        "RESET",
        "RESET_N",
    }
)

# Short/generic pin names that must be prefixed with ref to avoid collisions
_GENERIC_PIN_NAMES = frozenset(
    {
        "A",
        "B",
        "C",
        "D",
        "E",
        "G",
        "S",
        "IN",
        "OUT",
        "IN+",
        "IN-",
        "OUT+",
        "OUT-",
        "FB",
        "EN",
        "SW",
        "BST",
        "PG",
        "SS",
        "COMP",
        "RT",
        "SYNC",
        "NC",
        "~",
    }
)


def _apply_power_map(item: dict, comp: ComponentDef) -> None:
    """Remap KiCad-imported power pin net names to project rail names.

    Uses an explicit ``power_map`` from the YAML item first, then falls
    back to ``_DEFAULT_POWER_MAP`` for common power pin name conventions.
    """
    if not comp.power_pins:
        return
    explicit_map = item.get("power_map") or {}
    if not isinstance(explicit_map, dict):
        explicit_map = {}
    updated = {}
    for pin_num, net in comp.power_pins.items():
        if net in explicit_map:
            updated[pin_num] = explicit_map[net]
        elif net.upper() in _DEFAULT_POWER_MAP:
            updated[pin_num] = _DEFAULT_POWER_MAP[net.upper()]
        else:
            updated[pin_num] = net
    comp.power_pins = updated


def _apply_net_prefix(item: dict, comp: ComponentDef) -> None:
    """Prefix generic signal pin names with the instance ref to avoid collisions.

    KiCad symbols use short names like ``G``, ``S``, ``D`` that would
    create global nets shared between all instances of the same symbol.
    This prefixes those names with the component's ref designator while
    leaving actual bus signals (SDA, SCL, TX, RX, ...) as global nets.
    """
    ref = comp.source_ref or ""
    if not ref or not comp.pin_nets:
        return
    updated = {}
    for pin_num, net in comp.pin_nets.items():
        if net in _GLOBAL_SIGNAL_NAMES:
            updated[pin_num] = net
        elif net.upper() in _GENERIC_PIN_NAMES or len(net) <= 3:
            updated[pin_num] = f"{ref}_{net}"
        else:
            updated[pin_num] = net
    comp.pin_nets = updated


def _try_easyeda_resolve(item: dict, ic_name: str, parts_lookup=None) -> ComponentDef | None:
    """Attempt to resolve a component via EasyEDA/LCSC (4th-tier fallback).

    Tries two paths:
    1. Explicit ``lcsc:`` key in the YAML item → fetch directly by LCSC ID
    2. MPN lookup via parts_lookup → get LCSC code → fetch from EasyEDA
    """
    from .easyeda_api import fetch_easyeda_component
    from .easyeda_parser import easyeda_to_component_def

    # Path 1: Explicit LCSC part number in YAML
    lcsc_id = str(item.get("lcsc", "")).strip()

    # Path 2: Look up MPN → LCSC code via parts_lookup
    if not lcsc_id and parts_lookup:
        lookup_mpn = str(item.get("mpn") or ic_name).strip()
        if lookup_mpn:
            try:
                data = parts_lookup.lookup(lookup_mpn)
                if data:
                    lcsc_id = data.get("lcsc", "")
            except Exception:
                pass

    if not lcsc_id:
        return None

    try:
        ee_data = fetch_easyeda_component(lcsc_id)
    except Exception as exc:
        print(f"  WARNING: EasyEDA fetch failed for {lcsc_id}: {exc}")
        return None

    if not ee_data:
        return None

    comp = easyeda_to_component_def(ee_data)
    if comp:
        comp.lcsc_pn = lcsc_id
        print(f"  → Resolved '{ic_name}' from EasyEDA ({lcsc_id}): {len(comp.pins)} pins")
    return comp


def _resolve_component(
    item: dict,
    section_category: str,
    subcircuit_reg: SubcircuitRegistry,
    component_reg: ComponentRegistry,
    kicad_lib: KiCadLibrary | None,
    parts_lookup=None,
) -> list[ComponentDef]:
    """Resolve a single project spec item into ComponentDef(s).

    If the item has a 'type' key, it's a subcircuit template.
    Otherwise it's a standalone component resolved from registries.
    """
    template_type = item.get("type")

    ref = item.get("ref", "")

    if template_type:
        template = subcircuit_reg.get(template_type)
        if template is None:
            print(f"  WARNING: Unknown subcircuit type '{template_type}', creating stub")
            return [
                _make_stub_component(
                    template_type,
                    section_category,
                    ref,
                    reason=f"Unknown subcircuit type '{template_type}'",
                )
            ]

        errors = template.validate_params(item)
        if errors:
            for err in errors:
                print(f"  ERROR [{ref or '?'}]: {err}")
            return [
                _make_stub_component(
                    item.get("ic", template_type),
                    section_category,
                    ref,
                    reason=f"Template validation failed: {'; '.join(errors)}",
                )
            ]

        result = template.generate(item)
        if result.components:
            primary = result.components[0]
            primary.template_annotations.extend(result.annotations)
            primary.template_boundary_ports.extend(copy.deepcopy(result.boundary_ports))
            primary.template_local_wires.extend(copy.deepcopy(result.local_wires))
        for comp in result.components:
            if ref:
                comp.source_ref = ref
            comp.category = section_category
            _maybe_enrich_component(item, comp, parts_lookup)
        return result.components

    # Standalone component — resolve from registries
    ic = item.get("ic", "")
    if not ic:
        # Try passive inference: {value: "10k", ref: "R1"}
        value = str(item.get("value", "")).strip()
        if value and ref:
            from .component_db import infer_passive_component

            passive = infer_passive_component(ref, value, str(item.get("footprint", "")))
            if passive:
                passive.source_ref = ref
                passive.category = section_category
                return [passive]
        print(f"  WARNING: Item in '{section_category}' has no 'type' or 'ic', creating stub")
        return [_make_stub_component("", section_category, ref, reason="No 'type' or 'ic' specified")]

    comp = component_reg.get(ic)
    if not comp and kicad_lib:
        comp = kicad_lib.get_component(ic, category=section_category)
    if not comp:
        # Tier 4: EasyEDA/LCSC — try by explicit lcsc: key or by MPN lookup
        comp = _try_easyeda_resolve(item, ic, parts_lookup)
    if not comp:
        print(f"  WARNING: Unknown component '{ic}', not in registry, KiCad library, or EasyEDA, creating stub")
        return [
            _make_stub_component(ic, section_category, ref, reason=f"'{ic}' not in registry, KiCad library, or EasyEDA")
        ]

    instance = copy.deepcopy(comp)
    instance.category = section_category
    if ref:
        instance.source_ref = ref
    if item.get("value"):
        instance.value = item["value"]
    if item.get("description"):
        instance.description = item["description"]
    if item.get("mpn"):
        instance.source_mpn = str(item["mpn"])
    _apply_power_map(item, instance)
    _apply_net_prefix(item, instance)
    _maybe_enrich_component(item, instance, parts_lookup)
    return [instance]


def _maybe_enrich_component(item: dict, comp: ComponentDef, parts_lookup) -> None:
    """Optionally fill distributor metadata on a resolved component instance."""
    if parts_lookup is None:
        return

    lookup_mpn = str(item.get("mpn") or comp.source_mpn or comp.mpn or "").strip()
    if not lookup_mpn:
        return

    if not comp.source_mpn:
        comp.source_mpn = lookup_mpn

    try:
        data = parts_lookup.lookup(lookup_mpn)
    except Exception as exc:
        print(f"  WARNING: Part lookup failed for '{lookup_mpn}': {exc}")
        return

    if not data:
        return

    from .parts_lookup import enrich_component

    enrich_component(comp, data)


def resolve_project_spec(
    spec: dict,
    subcircuit_reg: SubcircuitRegistry | None = None,
    component_reg: ComponentRegistry | None = None,
    kicad_lib: KiCadLibrary | None = None,
    parts_lookup=None,
    enrich_parts: bool = False,
) -> tuple[list[ComponentDef], dict]:
    """Resolve a parsed project spec dict into component instances + metadata."""
    if subcircuit_reg is None:
        subcircuit_reg = get_default_registry()
    if component_reg is None:
        component_reg = BUILTIN_REGISTRY
    # Load project-local component database (JSON) if specified or auto-detected
    components_db = spec.get("components_db", "")
    if components_db:
        from pathlib import Path as _P

        p = _P(str(components_db))
        if p.is_file():
            n = component_reg.load_json(str(p))
            print(f"  Loaded {n} components from {p}")
        elif p.is_dir():
            n = component_reg.load_json_dir(str(p))
            print(f"  Loaded {n} components from {p}/")
    if kicad_lib is None:
        kicad_lib = KiCadLibrary()
    if enrich_parts and parts_lookup is None:
        from .parts_lookup import PartsLookup

        parts_lookup = PartsLookup()

    project_name = spec.get("project", "project")
    company = spec.get("company", "")

    metadata = {
        "project": project_name,
        "company": company,
        "version": spec.get("version", ""),
        "description": spec.get("description", ""),
    }

    components: list[ComponentDef] = []

    for section_key, items in spec.items():
        if section_key in (
            "project",
            "company",
            "version",
            "description",
            "spec_version",
            "presentation_profile",
            "components_db",
        ):
            continue

        if not isinstance(items, list):
            continue

        category = _SECTION_CATEGORY_MAP.get(section_key, section_key)
        for item in items:
            if not isinstance(item, dict):
                continue
            resolved = _resolve_component(
                item,
                category,
                subcircuit_reg,
                component_reg,
                kicad_lib,
                parts_lookup=parts_lookup,
            )
            components.extend(resolved)

    return components, metadata


def load_project(
    yaml_path: str | Path,
    subcircuit_reg: SubcircuitRegistry | None = None,
    component_reg: ComponentRegistry | None = None,
    kicad_lib: KiCadLibrary | None = None,
    parts_lookup=None,
    enrich_parts: bool = False,
) -> tuple[list[ComponentDef], dict]:
    """Load a YAML project spec and resolve all components.

    Returns (components, metadata) where metadata has project name, company, etc.
    """
    spec = _parse_yaml(yaml_path)
    components, metadata = resolve_project_spec(
        spec,
        subcircuit_reg=subcircuit_reg,
        component_reg=component_reg,
        kicad_lib=kicad_lib,
        parts_lookup=parts_lookup,
        enrich_parts=enrich_parts,
    )
    metadata["spec_path"] = str(yaml_path)

    print(f"Project '{metadata['project']}': {len(components)} component(s) from {yaml_path}")
    return components, metadata
