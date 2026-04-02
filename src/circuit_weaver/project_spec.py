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

from .component_db import BUILTIN_REGISTRY, ComponentDef, ComponentRegistry
from .kicad_lib import KiCadLibrary
from .subcircuits.base import SubcircuitRegistry, get_default_registry


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
    "digital": "mcu",
    "mcu": "mcu",
    "fpga": "fpga",
    "rf": "rf",
    "transceiver": "transceiver",
    "clock": "clock",
    "usb": "usb",
    "ethernet": "ethernet",
    "connectors": "connector",
    "sensors": "sensor",
    "storage": "storage",
    "debug": "debug",
    "communication": "communication",
}


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

    if template_type:
        template = subcircuit_reg.get(template_type)
        if template is None:
            print(f"  WARNING: Unknown subcircuit type '{template_type}', skipping")
            return []

        errors = template.validate_params(item)
        if errors:
            ref = item.get("ref", "?")
            for err in errors:
                print(f"  ERROR [{ref}]: {err}")
            return []

        result = template.generate(item)
        if result.components:
            primary = result.components[0]
            primary.template_annotations.extend(result.annotations)
            primary.template_boundary_ports.extend(copy.deepcopy(result.boundary_ports))
            primary.template_local_wires.extend(copy.deepcopy(result.local_wires))
        # Apply ref and category from spec
        ref = item.get("ref", "")
        for comp in result.components:
            if ref:
                comp.source_ref = ref
            comp.category = section_category
            _maybe_enrich_component(item, comp, parts_lookup)
        return result.components

    # Standalone component — resolve from registries
    ic = item.get("ic", "")
    if not ic:
        print(f"  WARNING: Item in '{section_category}' has no 'type' or 'ic', skipping")
        return []

    comp = component_reg.get(ic)
    if not comp and kicad_lib:
        comp = kicad_lib.get_component(ic, category=section_category)
    if not comp:
        print(f"  WARNING: Unknown component '{ic}', not in registry or KiCad library")
        return []

    instance = copy.deepcopy(comp)
    instance.category = section_category
    if item.get("ref"):
        instance.source_ref = item["ref"]
    if item.get("value"):
        instance.value = item["value"]
    if item.get("description"):
        instance.description = item["description"]
    if item.get("mpn"):
        instance.source_mpn = str(item["mpn"])
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
        if section_key in ("project", "company", "version", "description"):
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
