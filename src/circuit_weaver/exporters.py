"""Export schematic engine component model to Altium, Eagle, and generic netlist formats.

Generates simplified structural exports that capture components, nets, and
connectivity.  These are importable starting points, not bit-perfect native
files (Altium's binary SchDoc and Eagle's full schema are proprietary).

Usage:
    from circuit_weaver.exporters import (
        export_altium_xml,
        export_eagle_xml,
        export_generic_netlist,
    )
"""

import datetime
import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET

from .component_db import ComponentDef

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_components_data(
    components: list[ComponentDef],
) -> tuple[list[dict], dict[str, list[dict]]]:
    """Walk the component list and build a flat component/net model.

    Returns:
        components_data: list of dicts, one per component with ref, mpn,
            value, footprint, category, pins (list of pin dicts).
        nets: {net_name: [{ref, pin_number, pin_name}, ...]}
    """
    ref_counters: dict[str, int] = {}
    used_refs: set[str] = set()

    def _next_ref(prefix: str) -> str:
        if prefix not in ref_counters:
            ref_counters[prefix] = 0
        while True:
            ref_counters[prefix] += 1
            ref = f"{prefix}{ref_counters[prefix]}"
            if ref not in used_refs:
                used_refs.add(ref)
                return ref

    def _reserve(ref: str) -> None:
        if not ref:
            return
        used_refs.add(ref)
        m = re.match(r"^([A-Za-z]+)(\d+)$", ref)
        if m:
            pfx = m.group(1).upper()
            ref_counters[pfx] = max(ref_counters.get(pfx, 0), int(m.group(2)))

    # Pre-reserve explicit refs so auto-numbering skips them
    for comp in components:
        if comp.source_ref:
            _reserve(comp.source_ref)

    components_data: list[dict] = []
    nets: dict[str, list[dict]] = {}

    for comp in components:
        # Assign reference designator
        if comp.source_ref and comp.source_ref not in {c["ref"] for c in components_data}:
            ref = comp.source_ref
        else:
            ref = _next_ref(comp.ref_prefix)

        # Build pin-to-net mapping
        all_pin_nets: dict[str, str] = {}
        all_pin_nets.update(comp.power_pins)
        all_pin_nets.update(comp.pin_nets)

        # Build a lookup of pin number -> pin name from the ComponentDef
        pin_name_map: dict[str, str] = {}
        pin_type_map: dict[str, str] = {}
        for pdef in comp.pins:
            pin_name_map[pdef.number] = pdef.name
            pin_type_map[pdef.number] = pdef.electrical_type

        pin_records: list[dict] = []
        for pdef in comp.pins:
            net = all_pin_nets.get(pdef.number, "")
            pin_rec = {
                "number": pdef.number,
                "name": pdef.name,
                "type": pdef.electrical_type,
                "net": net,
            }
            pin_records.append(pin_rec)
            if net:
                nets.setdefault(net, []).append(
                    {"ref": ref, "pin_number": pdef.number, "pin_name": pdef.name}
                )

        # Also capture nets from pin_nets/power_pins that reference pins
        # not in the pins list (e.g., BGA balls resolved later)
        known_pin_nums = {p.number for p in comp.pins}
        for pin_num, net in all_pin_nets.items():
            if pin_num not in known_pin_nums:
                pname = pin_name_map.get(pin_num, pin_num)
                ptype = pin_type_map.get(pin_num, "passive")
                pin_rec = {
                    "number": pin_num,
                    "name": pname,
                    "type": ptype,
                    "net": net,
                }
                pin_records.append(pin_rec)
                nets.setdefault(net, []).append(
                    {"ref": ref, "pin_number": pin_num, "pin_name": pname}
                )

        comp_data = {
            "ref": ref,
            "mpn": comp.source_mpn or comp.mpn,
            "value": comp.value,
            "footprint": comp.footprint,
            "description": comp.source_description or comp.description,
            "category": comp.category,
            "ref_prefix": comp.ref_prefix,
            "manufacturer": comp.source_manufacturer,
            "pins": pin_records,
        }
        components_data.append(comp_data)

    return components_data, nets


def _pin_type_to_altium(etype: str) -> str:
    """Map engine electrical types to Altium pin type names."""
    mapping = {
        "input": "Input",
        "output": "Output",
        "bidirectional": "Bidirectional",
        "passive": "Passive",
        "power_in": "PowerIn",
        "power_out": "PowerOut",
        "tri_state": "TriState",
        "open_collector": "OpenCollector",
        "open_emitter": "OpenEmitter",
        "unspecified": "Passive",
    }
    return mapping.get(etype, "Passive")


# ---------------------------------------------------------------------------
# Altium SchDoc XML export
# ---------------------------------------------------------------------------


def export_altium_xml(
    components: list[ComponentDef],
    output_path: str,
    project_name: str = "project",
    company: str = "",
) -> str:
    """Generate an Altium Designer-compatible SchDoc XML file.

    Args:
        components: list of ComponentDef instances.
        output_path: file path for the output XML.
        project_name: project name for the title block.
        company: company name for the title block.

    Returns:
        The output file path as a string.
    """
    components_data, nets = _extract_components_data(components)
    today = datetime.date.today().isoformat()

    root = ET.Element("SchDoc")

    # Header
    header = ET.SubElement(root, "Header")
    ET.SubElement(header, "SchemaVersion").text = "2.0"
    ET.SubElement(header, "Application").text = "SchematicEngine"

    # Components
    comps_el = ET.SubElement(root, "Components")
    # Track placed X/Y using simple grid layout
    x_pos, y_pos = 100, 100
    y_step = 200

    for cdata in components_data:
        comp_el = ET.SubElement(comps_el, "Component")
        comp_el.set("RefDes", cdata["ref"])
        comp_el.set("LibRef", cdata["mpn"])
        comp_el.set("Value", cdata["value"])
        comp_el.set("Footprint", cdata["footprint"])
        comp_el.set("Description", cdata["description"])
        comp_el.set("X", str(x_pos))
        comp_el.set("Y", str(y_pos))

        for pin in cdata["pins"]:
            pin_el = ET.SubElement(comp_el, "Pin")
            pin_el.set("Number", pin["number"])
            pin_el.set("Name", pin["name"])
            pin_el.set("Net", pin["net"])
            pin_el.set("Type", _pin_type_to_altium(pin["type"]))

        y_pos += y_step

    # Wires — one wire per net segment connecting component pins
    wires_el = ET.SubElement(root, "Wires")
    for net_name, connections in nets.items():
        # Chain connections pairwise to form wire segments
        for i in range(len(connections) - 1):
            wire_el = ET.SubElement(wires_el, "Wire")
            wire_el.set("X1", str(100 + i * 50))
            wire_el.set("Y1", str(100))
            wire_el.set("X2", str(100 + (i + 1) * 50))
            wire_el.set("Y2", str(100))
            wire_el.set("Net", net_name)

    # Net Labels
    labels_el = ET.SubElement(root, "NetLabels")
    for net_name in nets:
        label_el = ET.SubElement(labels_el, "Label")
        label_el.set("X", str(100))
        label_el.set("Y", str(100))
        label_el.set("Net", net_name)

    # Title Block
    tb_el = ET.SubElement(root, "TitleBlock")
    ET.SubElement(tb_el, "Title").text = project_name
    ET.SubElement(tb_el, "Company").text = company
    ET.SubElement(tb_el, "Date").text = today

    # Write
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(str(out), encoding="unicode", xml_declaration=True)

    return str(out)


# ---------------------------------------------------------------------------
# Eagle .sch XML export
# ---------------------------------------------------------------------------


def export_eagle_xml(
    components: list[ComponentDef],
    output_path: str,
    project_name: str = "project",
    company: str = "",
) -> str:
    """Generate an Eagle-compatible .sch XML file.

    Args:
        components: list of ComponentDef instances.
        output_path: file path for the output XML.
        project_name: project name for metadata.
        company: company name (unused in Eagle format, kept for API consistency).

    Returns:
        The output file path as a string.
    """
    components_data, nets = _extract_components_data(components)

    root = ET.Element("eagle")
    root.set("version", "9.6.2")

    drawing = ET.SubElement(root, "drawing")
    schematic = ET.SubElement(drawing, "schematic")

    # Libraries (placeholder — Eagle references library symbols)
    ET.SubElement(schematic, "libraries")

    # Parts
    parts_el = ET.SubElement(schematic, "parts")
    for cdata in components_data:
        part_el = ET.SubElement(parts_el, "part")
        part_el.set("name", cdata["ref"])
        part_el.set("library", "schematic_engine")
        part_el.set("deviceset", cdata["mpn"])
        part_el.set("value", cdata["value"])

    # Sheets — single sheet with instances and nets
    sheets_el = ET.SubElement(schematic, "sheets")
    sheet_el = ET.SubElement(sheets_el, "sheet")

    # Instances (placed components)
    instances_el = ET.SubElement(sheet_el, "instances")
    x_pos, y_pos = 100, 100
    y_step = 200

    for cdata in components_data:
        inst_el = ET.SubElement(instances_el, "instance")
        inst_el.set("part", cdata["ref"])
        inst_el.set("x", str(x_pos))
        inst_el.set("y", str(y_pos))
        y_pos += y_step

    # Nets
    nets_el = ET.SubElement(sheet_el, "nets")
    for net_name, connections in nets.items():
        net_el = ET.SubElement(nets_el, "net")
        net_el.set("name", net_name)

        # Each net gets one segment with chained wires and a label
        if connections:
            segment_el = ET.SubElement(net_el, "segment")

            # Symbolic wire coordinates — chain pins
            for i in range(max(1, len(connections) - 1)):
                wire_el = ET.SubElement(segment_el, "wire")
                wire_el.set("x1", str(100 + i * 50))
                wire_el.set("y1", str(100))
                wire_el.set("x2", str(100 + (i + 1) * 50))
                wire_el.set("y2", str(100))

            # Pin references
            for conn in connections:
                pinref_el = ET.SubElement(segment_el, "pinref")
                pinref_el.set("part", conn["ref"])
                pinref_el.set("pin", conn["pin_number"])

            # Label
            label_el = ET.SubElement(segment_el, "label")
            label_el.set("x", str(100))
            label_el.set("y", str(100))

    # Write with Eagle DOCTYPE
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")

    with open(str(out), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n')
        f.write('<!DOCTYPE eagle SYSTEM "eagle.dtd">\n')
        tree.write(f, encoding="unicode", xml_declaration=False)

    return str(out)


# ---------------------------------------------------------------------------
# Generic JSON netlist export
# ---------------------------------------------------------------------------


def export_generic_netlist(
    components: list[ComponentDef],
    output_path: str,
    project_name: str = "project",
) -> str:
    """Generate a generic JSON netlist as a universal interchange format.

    Args:
        components: list of ComponentDef instances.
        output_path: file path for the output JSON.
        project_name: project name for metadata.

    Returns:
        The output file path as a string.
    """
    components_data, nets = _extract_components_data(components)
    today = datetime.date.today().isoformat()

    # Build component entries
    comp_entries = []
    for cdata in components_data:
        pins_dict = {}
        for pin in cdata["pins"]:
            pins_dict[pin["number"]] = {
                "name": pin["name"],
                "type": pin["type"],
                "net": pin["net"],
            }
        comp_entries.append(
            {
                "ref": cdata["ref"],
                "mpn": cdata["mpn"],
                "value": cdata["value"],
                "footprint": cdata["footprint"],
                "description": cdata["description"],
                "category": cdata["category"],
                "manufacturer": cdata["manufacturer"],
                "pins": pins_dict,
            }
        )

    # Build net entries — {net_name: [{ref, pin}, ...]}
    net_entries: dict[str, list[dict]] = {}
    for net_name, connections in nets.items():
        net_entries[net_name] = [{"ref": c["ref"], "pin": c["pin_number"]} for c in connections]

    netlist = {
        "components": comp_entries,
        "nets": net_entries,
        "metadata": {
            "project": project_name,
            "date": today,
            "generator": "schematic_engine",
            "format_version": "1.0",
        },
    }

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(str(out), "w", encoding="utf-8") as f:
        json.dump(netlist, f, indent=2, ensure_ascii=False)

    return str(out)
