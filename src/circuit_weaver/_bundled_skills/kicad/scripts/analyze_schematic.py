#!/usr/bin/env python3
"""
KiCad Schematic Analyzer — comprehensive single-pass extraction.

Parses a .kicad_sch file and outputs structured JSON with:
- Component inventory (BOM data, properties, positions)
- Net connectivity (wires, labels, junctions, no-connects, power symbols)
- Pin-level connectivity map (which pin connects to which net)
- Subcircuit identification hints
- Design statistics

Usage:
    python analyze_schematic.py <file.kicad_sch> [--output file.json]

Output is JSON to stdout (or file if --output specified).
"""

import json
import math
import re
import sys
from pathlib import Path

# Add scripts dir to path for sexp_parser
sys.path.insert(0, str(Path(__file__).parent))
from sexp_parser import (
    find_all,
    find_deep,
    find_first,
    get_at,
    get_property,
    get_value,
    parse_file,
)


# Coordinate matching tolerance (mm) — used across net building and connectivity analysis
COORD_EPSILON = 0.01

# Regulator Vref lookup table — maps part number prefixes to their internal
# reference voltage.  Used by the feedback divider Vout estimator instead of
# guessing from a list.  Entries are checked in order; first prefix match wins.
# When a part isn't found here the analyzer falls back to the heuristic sweep.
_REGULATOR_VREF: dict[str, float] = {
    # TI switching regulators (verified against datasheets)
    "TPS6100": 0.6,    "TPS6102": 0.6,    "TPS6103": 0.6,   # TPS61023 FB = 0.6V
    "TPS5430": 1.221,  "TPS5450": 1.221,                     # TPS5430 Vref = 1.221V
    "TPS54160": 0.8,   "TPS54260": 0.8,   "TPS54360": 0.8,   # TPS5436x FB = 0.8V
    "TPS542": 0.6,     "TPS543": 0.6,     "TPS544": 0.6,
    "TPS54040": 0.8,   "TPS54060": 0.8,                       # TPS54040 Vref = 0.8V
    "TPS5410": 1.221,
    "TPS56": 0.6,      "TPS55": 0.6,
    "TPS6208": 0.6,    "TPS6209": 0.6,
    "TPS6211": 0.6,    "TPS6212": 0.6,
    "TPS6213": 0.6,    "TPS6215": 0.6,
    "TPS6300": 0.5,    "TPS6301": 0.5,
    "TPS40": 0.6,
    "LMR514": 0.8,     "LMR516": 0.8,                         # LMR51450 Vref = 0.8V
    "LMR336": 1.0,     "LMR338": 1.0,                         # LMR33630 Vref = 1.0V
    "LM516": 0.8,      "LM258": 1.285,   "LM259": 1.285,
    "LM260": 1.21,     "LM261": 1.21,
    "LM340": 1.25,
    "LMZ3": 0.8,       "LMZ2": 0.795,
    "TLV620": 0.5,     "TLV621": 0.5,
    # TI LDOs
    "TLV759": 0.55,                                            # TLV759P (adjustable) FB = 0.55V
    "TPS7A": 1.19,     "TPS7B": 1.21,
    # Analog Devices / Linear Tech (verified against datasheets)
    "LT361": 0.8,      "LT362": 0.8,
    "LT364": 1.22,     "LT365": 1.22,
    "LT801": 0.8,      "LT802": 0.8,
    "LT810": 0.97,     "LT811": 0.97,                         # LT8610 VFB = 0.970V typ
    "LT860": 0.97,     "LT862": 0.97,                         # LT8640/LT8620 VFB = 0.970V typ
    "LT871": 1.0,      "LT872": 1.0,
    "LTC34": 0.8,
    "LTM46": 0.6,       "LTM82": 0.6,
    # Richtek
    "RT5": 0.6,         "RT6": 0.6,
    "RT2875": 0.8,
    # MPS
    "MP1": 0.8,         "MP2": 0.8,         "MP8": 0.8,
    # Microchip
    "MIC29": 1.24,      "MIC55": 1.24,
    "MCP170": 1.21,
    # Diodes Inc
    "AP6": 0.6,         "AP73": 0.6,
    "AP2112": 0.8,                                              # AP2112 adjustable Vref = 0.8V
    # ST
    "LD1117": 1.25,                                             # LD1117 Vref = 1.25V
    "LDL1117": 1.25,
    "LD33": 1.25,
    # ON Semi
    "NCP1": 0.8,        "NCV4": 0.8,
    # SY
    "SY8": 0.6,                                                # SY8089 FB = 0.6V typ
    # Maxim
    "MAX5035": 1.22,    "MAX5033": 1.22,                         # MAX5035 VFB = 1.221V typ (datasheet)
    "MAX1771": 1.5,     "MAX1709": 1.24,                         # MAX1771 Vref = 1.5V, MAX1709 VFB = 1.24V (datasheet)
    "MAX17760": 0.8,                                              # MAX17760 FB = 0.8V (datasheet, min Vout = 0.8V)
    # ISL (Renesas/Intersil)
    "ISL854": 0.6,      "ISL850": 0.6,                           # ISL854102 FB = 0.6V (datasheet)
    # LM6x4xx (TI)
    "LM614": 1.0,       "LM619": 1.0,                            # LM61495 VFB = 1.0V (datasheet, 0.99/1.0/1.01)
    # Diodes Inc (BCD Semiconductor)
    "AP3015": 1.23,                                               # AP3015A VFB = 1.23V (datasheet, 1.205/1.23/1.255)
    # Generic (well-established values)
    "LM317": 1.25,     "LM337": 1.25,
    "AMS1117": 1.25,   "AMS1085": 1.25,
    "LM78": 1.25,      "LM79": 1.25,
    "LM1117": 1.25,
    # NOTE: Parts without feedback dividers are intentionally excluded:
    # LT3080 (uses 10uA SET current source), LTC3649 (uses 50uA ISET),
    # TLV713 (fixed output only), XC6206 (fixed output only, no FB pin),
    # AP2210 (unverified Vref).
}

# Keywords for classifying MOSFET/BJT load type from net names.
# Used by _classify_load() for transistor analysis and by net classification
# for the "output_drive" net class.  Keys are load type names, values are
# keyword tuples matched as substrings of the uppercased net name.
# Avoid short prefixes that appear inside unrelated words:
#   "SOL" matches MISO_LEVEL, ISOL → use SOLENOID only
#   "MOT" matches REMOTE → use MOTOR only
_LOAD_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "motor": ("MOTOR",),
    "heater": ("HEAT", "HTR", "HEATER"),
    "fan": ("FAN",),
    "solenoid": ("SOLENOID",),
    "valve": ("VALVE",),
    "pump": ("PUMP",),
    "relay": ("RELAY", "RLY"),
    "speaker": ("SPEAK", "SPK"),
    "buzzer": ("BUZZ", "BZR", "BUZZER"),
    "lamp": ("LAMP", "BULB"),
}

# Flattened keyword set for net classification (output_drive class).
# Includes LED/PWM which aren't load types but are output drive signals.
_OUTPUT_DRIVE_KEYWORDS: tuple[str, ...] = (
    "LED", "PWM",
    *{kw for kws in _LOAD_TYPE_KEYWORDS.values() for kw in kws},
)


def _lookup_regulator_vref(value: str, lib_id: str) -> tuple[float | None, str]:
    """Look up a regulator's internal Vref from its value or lib_id.

    Returns (vref, source) where source is "lookup" if found, or (None, "")
    if not.  Tries the value field first (usually the part number), then the
    lib_id part name after the colon.
    """
    candidates = [value.upper()]
    if ":" in lib_id:
        candidates.append(lib_id.split(":")[-1].upper())
    for candidate in candidates:
        for prefix, vref in _REGULATOR_VREF.items():
            if candidate.startswith(prefix.upper()):
                return vref, "lookup"
    return None, ""


def _parse_voltage_from_net_name(net_name: str) -> float | None:
    """Try to extract a voltage value from a power net name.

    Examples: '+3V3' → 3.3, '+5V' → 5.0, '+12V' → 12.0, '+1V8' → 1.8,
    'VCC_3V3' → 3.3, '+2.5V' → 2.5, 'VBAT' → None
    """
    if not net_name:
        return None
    # Pattern: digits V digits  (e.g. 3V3 → 3.3, 1V8 → 1.8)
    m = re.search(r'(\d+)V(\d+)', net_name, re.IGNORECASE)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    # Pattern: digits.digits V  or  digits V  (e.g. 3.3V, 5V, 12V)
    m = re.search(r'(\d+\.?\d*)V', net_name, re.IGNORECASE)
    if m:
        return float(m.group(1))
    return None


def _format_frequency(hz: float) -> str:
    """Format a frequency in Hz to a human-readable string with SI prefix."""
    if hz >= 1e9:
        return f"{hz / 1e9:.2f} GHz"
    elif hz >= 1e6:
        return f"{hz / 1e6:.2f} MHz"
    elif hz >= 1e3:
        return f"{hz / 1e3:.2f} kHz"
    else:
        return f"{hz:.2f} Hz"


def extract_lib_symbols(root: list) -> dict:
    """Extract library symbol definitions (pin positions, types).

    For multi-unit symbols (e.g., STM32 with separate GPIO and power units),
    pins are stored per unit so compute_pin_positions can use the correct
    offsets for each placed unit instance.
    """
    lib_symbols_node = find_first(root, "lib_symbols")
    if not lib_symbols_node:
        return {}

    def _extract_pins_from_node(node):
        """Extract pin definitions directly from a symbol node (not recursing into sub-symbols)."""
        pins = []
        for child in node:
            if not isinstance(child, list) or len(child) < 3:
                continue
            if child[0] == "pin":
                pin = child
                pin_type = pin[1] if len(pin) > 1 else "unknown"
                pin_shape = pin[2] if len(pin) > 2 else "unknown"
                at = get_at(pin)
                pin_name_node = find_first(pin, "name")
                pin_num_node = find_first(pin, "number")
                pin_name = str(pin_name_node[1]) if pin_name_node and len(pin_name_node) > 1 and pin_name_node[1] is not None else ""
                pin_num = str(pin_num_node[1]) if pin_num_node and len(pin_num_node) > 1 and pin_num_node[1] is not None else ""
                pins.append({
                    "number": pin_num,
                    "name": pin_name,
                    "type": pin_type,
                    "shape": pin_shape,
                    "offset": list(at) if at else None,
                })
        return pins

    symbols = {}
    for sym in find_all(lib_symbols_node, "symbol"):
        name = sym[1] if len(sym) > 1 else "unknown"
        # Skip sub-unit symbols (e.g., "Device:C_0_1", "Device:C_1_1")
        if "_" in name.split(":")[-1] and name.split(":")[-1].split("_")[-1].isdigit():
            continue

        # Collect pins from sub-unit symbols, keyed by unit number.
        # Sub-symbols named like "SymName_U_V" where U is the unit number.
        # Unit 0 sub-symbols (_0_1) contain pins/graphics shared by all units.
        unit_pins: dict[int, list] = {}
        all_pins = []

        for child in sym:
            if not isinstance(child, list) or len(child) < 2 or child[0] != "symbol":
                continue
            sub_name = child[1] if isinstance(child[1], str) else ""
            # Parse unit number from sub-symbol name: "Name_U_V"
            parts = sub_name.rsplit("_", 2)
            if len(parts) >= 3 and parts[-1].isdigit() and parts[-2].isdigit():
                unit_num = int(parts[-2])
                sub_pins = _extract_pins_from_node(child)
                if sub_pins:
                    unit_pins.setdefault(unit_num, []).extend(sub_pins)
                    all_pins.extend(sub_pins)

        # If no sub-unit pins found, fall back to find_deep on the whole symbol
        if not all_pins:
            all_pins = []
            for pin in find_deep(sym, "pin"):
                if len(pin) < 3:
                    continue
                pin_type = pin[1] if len(pin) > 1 else "unknown"
                pin_shape = pin[2] if len(pin) > 2 else "unknown"
                at = get_at(pin)
                pin_name_node = find_first(pin, "name")
                pin_num_node = find_first(pin, "number")
                pin_name = str(pin_name_node[1]) if pin_name_node and len(pin_name_node) > 1 and pin_name_node[1] is not None else ""
                pin_num = str(pin_num_node[1]) if pin_num_node and len(pin_num_node) > 1 and pin_num_node[1] is not None else ""
                all_pins.append({
                    "number": pin_num,
                    "name": pin_name,
                    "type": pin_type,
                    "shape": pin_shape,
                    "offset": list(at) if at else None,
                })

        # Get symbol properties
        desc = get_property(sym, "Description") or ""
        ki_keywords = get_property(sym, "ki_keywords") or ""
        ki_fp_filters = get_property(sym, "ki_fp_filters") or ""

        # Check for (power) flag — marks this as a power symbol regardless of lib name
        is_power = any(
            isinstance(child, list) and len(child) == 1 and child[0] == "power"
            for child in sym
        )

        # Extract alternate pin definitions (dual-function pins, e.g., GPIO/SPI/UART)
        alternates = {}
        for pin in find_deep(sym, "pin"):
            pin_num_node = find_first(pin, "number")
            pin_num = pin_num_node[1] if pin_num_node and len(pin_num_node) > 1 else ""
            alts = []
            for child in pin:
                if isinstance(child, list) and len(child) >= 2 and child[0] == "alternate":
                    alt_name = child[1] if len(child) > 1 else ""
                    alt_type = child[2] if len(child) > 2 else ""
                    alt_shape = child[3] if len(child) > 3 else ""
                    alts.append({"name": alt_name, "type": alt_type, "shape": alt_shape})
            if alts:
                alternates[pin_num] = alts

        symbols[name] = {
            "pins": all_pins,
            "unit_pins": unit_pins if unit_pins else None,
            "description": desc,
            "keywords": ki_keywords,
            "is_power": is_power,
            "ki_fp_filters": ki_fp_filters,
            "alternates": alternates if alternates else None,
        }

    return symbols


def apply_rotation(px: float, py: float, angle_deg: float) -> tuple[float, float]:
    """Apply rotation to a pin offset. KiCad uses degrees, CCW positive."""
    if angle_deg == 0:
        return px, py
    rad = math.radians(angle_deg)
    cos_a = round(math.cos(rad), 10)
    sin_a = round(math.sin(rad), 10)
    return (px * cos_a - py * sin_a, px * sin_a + py * cos_a)


def compute_pin_positions(component: dict, lib_symbols: dict) -> list[dict]:
    """Compute absolute pin positions for a placed component."""
    lib_id = component.get("lib_id", "")
    sym_def = lib_symbols.get(lib_id)
    if not sym_def:
        return []

    cx = component["x"]
    cy = component["y"]
    angle = component["angle"]
    mirror_x = component.get("mirror_x", False)
    mirror_y = component.get("mirror_y", False)

    # For multi-unit symbols, use pins from this unit PLUS unit 0 (shared pins).
    # In KiCad, sub-symbol _0_1 contains pins shared by all units (e.g., power pins).
    unit_num = component.get("unit")
    unit_pins_map = sym_def.get("unit_pins")
    if unit_num and unit_pins_map and unit_num in unit_pins_map:
        pins = list(unit_pins_map[unit_num])
        # Also include unit 0 (shared/common) pins if they exist
        if 0 in unit_pins_map:
            pins.extend(unit_pins_map[0])
    else:
        pins = sym_def["pins"]

    pin_positions = []
    for pin in pins:
        if not pin["offset"]:
            continue
        px, py = pin["offset"][0], pin["offset"][1]

        # Apply mirroring before rotation
        if mirror_x:
            py = -py
        if mirror_y:
            px = -px

        # Apply rotation to pin offset
        rpx, rpy = apply_rotation(px, py, angle)

        # Absolute position: Y-axis inversion (symbol coords are math-up, schematic is screen-down)
        abs_x = round(cx + rpx, 4)
        abs_y = round(cy - rpy, 4)

        # Ensure pin number and name are never None — coerce to string with fallback
        pin_num = pin.get("number")
        pin_name = pin.get("name")
        if pin_num is None:
            pin_num = ""
        else:
            pin_num = str(pin_num)
        if pin_name is None:
            pin_name = ""
        else:
            pin_name = str(pin_name)

        pin_positions.append({
            "number": pin_num,
            "name": pin_name,
            "type": pin["type"],
            "x": abs_x,
            "y": abs_y,
        })

    return pin_positions


def extract_symbol_instances(root: list) -> dict:
    """Extract (symbol_instances ...) from root schematic.

    Returns a dict mapping path string -> {reference, unit, value, footprint}.
    Path format: "/sheet_uuid/symbol_uuid" or "/sheet_uuid/child_uuid/symbol_uuid".
    """
    result = {}
    si_node = find_first(root, "symbol_instances")
    if not si_node:
        return result
    for path_node in si_node[1:]:
        if not isinstance(path_node, list) or path_node[0] != "path":
            continue
        if len(path_node) < 2:
            continue
        path_str = path_node[1]
        ref = get_value(path_node, "reference") or ""
        unit_val = get_value(path_node, "unit")
        try:
            unit = int(unit_val) if unit_val else 1
        except (ValueError, TypeError):
            unit = 1
        result[path_str] = {
            "reference": ref,
            "unit": unit,
        }
    return result


def extract_components(root: list, lib_symbols: dict, instance_uuid: str = "",
                       symbol_instances: dict | None = None) -> list[dict]:
    """Extract all placed component instances.

    If instance_uuid is provided, remap references from the (instances) block
    for the specified sheet instance (supports multi-instance hierarchical sheets).

    If symbol_instances is provided (from root schematic), use it as a fallback
    when a symbol has no inline (instances) block (common in older KiCad projects).
    """
    components = []

    # Placed symbols are direct children of root with (symbol (lib_id ...))
    for sym in root:
        if not isinstance(sym, list) or len(sym) == 0 or sym[0] != "symbol":
            continue
        # Skip if this is in lib_symbols (those have string name as [1], not a sub-list)
        if len(sym) > 1 and isinstance(sym[1], str):
            continue

        lib_id = get_value(sym, "lib_id")
        if not lib_id:
            continue

        at = get_at(sym)
        x, y, angle = at if at else (0, 0, 0)

        # Check for mirror
        mirror_node = find_first(sym, "mirror")
        mirror_x = mirror_node is not None and "x" in mirror_node if mirror_node else False
        mirror_y = mirror_node is not None and "y" in mirror_node if mirror_node else False

        # Extract unit number for multi-unit symbols
        unit_node = find_first(sym, "unit")
        unit_num = int(unit_node[1]) if unit_node and len(unit_node) > 1 else None

        ref = get_property(sym, "Reference") or ""
        value = get_property(sym, "Value") or ""
        footprint = get_property(sym, "Footprint") or ""
        datasheet = get_property(sym, "Datasheet") or ""
        description = get_property(sym, "Description") or ""
        uuid_val = get_value(sym, "uuid") or ""

        # Remap reference from (instances) block for multi-instance sheets.
        # Two sources: inline (instances) in each symbol (KiCad 7+), or
        # centralized (symbol_instances) in the root schematic (KiCad 6/older projects).
        if instance_uuid:
            remapped = False
            instances_node = find_first(sym, "instances")
            if instances_node:
                for proj in instances_node[1:]:
                    if not isinstance(proj, list) or proj[0] != "project":
                        continue
                    for path_node in proj[2:]:
                        if not isinstance(path_node, list) or path_node[0] != "path":
                            continue
                        path_str = path_node[1] if len(path_node) > 1 else ""
                        if instance_uuid in path_str:
                            inst_ref = get_value(path_node, "reference")
                            if inst_ref:
                                ref = inst_ref
                                remapped = True
                            inst_unit = get_value(path_node, "unit")
                            if inst_unit:
                                try:
                                    unit_num = int(inst_unit)
                                except (ValueError, TypeError):
                                    pass
                            break

            # Fallback: use centralized symbol_instances from root schematic
            if not remapped and symbol_instances and uuid_val:
                # Build the lookup path: instance_uuid is a full hierarchical
                # path like "/sheet1_uuid" or "/sheet1_uuid/sheet2_uuid".
                # Append the symbol's own UUID to form the full path.
                lookup_path = instance_uuid + "/" + uuid_val
                si_entry = symbol_instances.get(lookup_path)
                if si_entry:
                    if si_entry["reference"]:
                        ref = si_entry["reference"]
                    if si_entry.get("unit"):
                        unit_num = si_entry["unit"]
        mpn = (get_property(sym, "MPN") or get_property(sym, "Mfg Part")
               or get_property(sym, "PartNumber") or get_property(sym, "Part Number")
               or get_property(sym, "Manufacturer_Part_Number") or get_property(sym, "Mfr No.")
               or get_property(sym, "Mfr_No") or get_property(sym, "ManufacturerPartNumber")
               or get_property(sym, "mpn") or "")
        manufacturer = (get_property(sym, "Manufacturer") or get_property(sym, "Mfr")
                        or get_property(sym, "MFR") or "")
        digikey = (get_property(sym, "Digi-Key Part Number") or get_property(sym, "Digi-Key_PN")
                   or get_property(sym, "DigiKey") or get_property(sym, "DigiKey Part")
                   or get_property(sym, "Digikey Part Number") or get_property(sym, "Digi-Key PN")
                   or get_property(sym, "DigiKey_Part_Number") or get_property(sym, "DigiKey Part Number")
                   or get_property(sym, "DK") or "")
        mouser = (get_property(sym, "Mouser") or get_property(sym, "Mouser Part Number")
                  or get_property(sym, "Mouser Part") or get_property(sym, "Mouser_PN")
                  or get_property(sym, "Mouser PN") or "")
        lcsc = (get_property(sym, "LCSC") or get_property(sym, "LCSC Part #")
                or get_property(sym, "LCSC Part Number") or get_property(sym, "LCSC Part")
                or get_property(sym, "LCSCStockCode") or get_property(sym, "JLCPCB")
                or get_property(sym, "JLCPCB Part") or get_property(sym, "JLC") or "")
        element14 = (get_property(sym, "Newark") or get_property(sym, "Newark Part Number")
                     or get_property(sym, "Newark_PN") or get_property(sym, "Newark PN")
                     or get_property(sym, "Farnell") or get_property(sym, "Farnell Part Number")
                     or get_property(sym, "Farnell_PN") or get_property(sym, "Farnell PN")
                     or get_property(sym, "element14") or get_property(sym, "element14 Part Number")
                     or get_property(sym, "element14_PN") or "")

        in_bom = get_value(sym, "in_bom") != "no"
        dnp = get_value(sym, "dnp") == "yes"
        on_board = get_value(sym, "on_board") != "no"

        # Get pin UUIDs for connectivity
        pin_uuids = {}
        for pin_node in find_all(sym, "pin"):
            if len(pin_node) >= 2:
                pin_num = pin_node[1]
                pin_uuid_node = find_first(pin_node, "uuid")
                if pin_uuid_node and len(pin_uuid_node) > 1:
                    pin_uuids[pin_num] = pin_uuid_node[1]

        comp = {
            "reference": ref,
            "value": value,
            "lib_id": lib_id,
            "footprint": footprint,
            "datasheet": datasheet,
            "description": description,
            "mpn": mpn,
            "manufacturer": manufacturer,
            "digikey": digikey,
            "mouser": mouser,
            "lcsc": lcsc,
            "element14": element14,
            "x": x,
            "y": y,
            "angle": angle,
            "mirror_x": mirror_x,
            "mirror_y": mirror_y,
            "unit": unit_num,
            "uuid": uuid_val,
            "in_bom": in_bom,
            "dnp": dnp,
            "on_board": on_board,
            "pin_uuids": pin_uuids,
        }

        # Determine component type from reference prefix, lib_id, and lib_symbol flags
        sym_def = lib_symbols.get(lib_id, {})
        is_power_sym = sym_def.get("is_power", False)
        comp["type"] = classify_component(ref, lib_id, value, is_power_sym)
        # Store ki_keywords for downstream analysis (e.g., P-channel detection)
        comp["keywords"] = sym_def.get("keywords", "")

        # Compute absolute pin positions
        comp["pins"] = compute_pin_positions(comp, lib_symbols)

        components.append(comp)

    return components


def classify_component(ref: str, lib_id: str, value: str, is_power: bool = False) -> str:
    """Classify component type from reference designator and library."""
    if is_power or lib_id.startswith("power:"):
        return "power_symbol"

    prefix = ""
    for c in ref:
        if c.isalpha() or c == "#":
            prefix += c
        else:
            break

    type_map = {
        # Passive components
        "R": "resistor", "RS": "resistor", "RN": "resistor_network",
        "RM": "resistor_network", "RA": "resistor_network",
        "C": "capacitor", "L": "inductor",
        "D": "diode", "TVS": "diode", "V": "varistor",
        # Semiconductors
        "Q": "transistor", "FET": "transistor",
        "U": "ic", "IC": "ic",
        # Connectors and mechanical
        "J": "connector", "P": "connector",
        "SW": "switch", "S": "switch", "BUT": "switch",
        "K": "relay",
        "F": "fuse", "FUSE": "fuse",
        "Y": "crystal",
        "BT": "battery",
        "BZ": "buzzer", "LS": "speaker", "SP": "speaker",
        "OK": "optocoupler", "OC": "optocoupler",
        "NTC": "thermistor", "TH": "thermistor", "RT": "thermistor",
        "PTC": "thermistor",
        "VAR": "varistor", "RV": "varistor",
        "SAR": "surge_arrester",
        "NT": "net_tie",
        "MOV": "varistor",
        "A": "ic",
        "TP": "test_point",
        "MH": "mounting_hole", "H": "mounting_hole",
        "FB": "ferrite_bead", "FL": "filter",
        "LED": "led",
        "T": "transformer", "TR": "transformer",
        # Mechanical/manufacturing
        "FID": "fiducial",
        "MK": "fiducial",
        "JP": "jumper", "SJ": "jumper",
        "LOGO": "graphic",
        "MP": "mounting_hole",
        "#PWR": "power_flag", "#FLG": "flag",
    }

    result = type_map.get(prefix)
    if result:
        # Override prefix-based heuristics when lib_id provides better info
        val_low = value.lower() if value else ""
        lib_low = lib_id.lower() if lib_id else ""
        if result == "varistor" and ("r_pot" in lib_low or "potentiometer" in lib_low
                                     or "potentiometer" in val_low):
            return "resistor"
        if result == "transformer" and any(x in lib_low or x in val_low
                                           for x in ("mosfet", "fet", "transistor",
                                                     "amplifier", "rf_amp", "mmic")):
            return "ic"
        if result == "thermistor" and any(x in lib_low or x in val_low
                                          for x in ("fuse", "polyfuse", "pptc",
                                                    "reset fuse", "ptc fuse")):
            return "fuse"
        if result == "thermistor" and any(x in lib_low or x in val_low
                                          for x in ("mov", "varistor")):
            return "varistor"
        if result == "diode" and ("led" in lib_low or "led" in val_low):
            return "led"
        return result

    # Fallback: check value/lib_id for common patterns
    val_lower = value.lower() if value else ""
    lib_lower = lib_id.lower() if lib_id else ""

    if any(x in val_lower for x in ["mountinghole", "mounting_hole"]):
        return "mounting_hole"
    if any(x in val_lower for x in ["fiducial"]):
        return "fiducial"
    if any(x in val_lower for x in ["testpad", "test_pad"]):
        return "test_point"
    if any(x in lib_lower for x in ["mounting_hole", "mountinghole"]):
        return "mounting_hole"
    if any(x in lib_lower for x in ["fiducial"]):
        return "fiducial"
    if any(x in lib_lower for x in ["test_point", "testpoint"]):
        return "test_point"

    # X prefix: crystal or oscillator if value/lib suggests it, otherwise connector
    # Distinguish passive crystals (need load caps) from active MEMS/IC oscillators
    if prefix == "X":
        # Active oscillator ICs (MEMS, TCXO, VCXO) — have VCC/GND/OUT, no load caps
        if any(x in lib_lower for x in ["oscillator"]) and not any(x in lib_lower for x in ["crystal", "xtal"]):
            return "oscillator"
        if any(x in val_lower for x in ["dsc6", "si5", "sg-", "asfl", "sit8", "asco"]):
            return "oscillator"
        # Passive crystals
        if any(x in val_lower for x in ["xtal", "crystal", "mhz", "khz", "osc"]):
            return "crystal"
        if any(x in lib_lower for x in ["crystal", "xtal", "osc", "clock"]):
            return "crystal"
        return "connector"

    # MX key switches (keyboard projects)
    if prefix == "MX" or "cherry" in val_lower or "kailh" in val_lower:
        return "switch"

    # Common prefixes that are context-dependent
    if prefix in ("RST", "RESET", "PHYRST"):
        return "switch"  # reset buttons/circuits
    if prefix == "BAT" or prefix == "BATSENSE":
        return "connector"  # battery connector
    if prefix == "RGB" or prefix == "PWRLED":
        return "led"

    # Library-based fallback for non-standard reference prefixes
    if "thermistor" in lib_lower or "thermistor" in val_lower or "ntc" in val_lower:
        return "thermistor"
    if "varistor" in lib_lower or "varistor" in val_lower:
        return "varistor"
    if "optocoupler" in lib_lower or "opto" in lib_lower:
        return "optocoupler"
    lib_prefix = lib_lower.split(":")[0] if ":" in lib_lower else lib_lower
    if lib_prefix == "led" or val_lower.startswith("led/") or val_lower == "led":
        return "led"
    if "ws2812" in val_lower or "neopixel" in val_lower or "sk6812" in val_lower:
        return "led"
    if "jumper" in lib_lower or val_lower in ("opened", "closed") or val_lower.startswith("opened("):
        return "jumper"
    # Connector detection: lib names and common connector part number patterns
    if "connector" in lib_lower or "conn_" in val_lower:
        return "connector"
    if any(x in val_lower for x in ["usb_micro", "usb_c", "usb-c", "rj45", "rj11",
                                     "pin_header", "pin_socket", "barrel_jack"]):
        return "connector"
    # JST and similar connector part numbers in value
    if any(value.startswith(p) for p in ["S3B-", "S4B-", "S6B-", "S8B-", "SM0",
                                        "B2B-", "BM0", "MISB-", "ZL2", "ZL3",
                                        "HN1x", "NH1x", "NS(HN", "NS(NH",
                                        "FL40", "FL20", "FPV-", "SCJ3",
                                        "TFC-", "68020-", "RJP-", "RJ45"]):
        return "connector"
    # Common non-standard connector prefixes (OLIMEX, etc.)
    if prefix in ("CON", "USB", "USBUART", "MICROSD", "UEXT", "LAN",
                   "HDMI", "EXT", "GPIO", "CAN", "SWD", "JTAG",
                   "ANT", "RJ", "SUPPLY"):
        return "connector"
    if "switch" in lib_lower:
        return "switch"
    if "relay" in lib_lower:
        return "relay"
    if "nettie" in lib_lower or "net_tie" in val_lower or "nettie" in val_lower:
        return "net_tie"
    if "led" in lib_lower and "diode" in lib_lower:
        return "led"
    if "transistor" in lib_lower or "mosfet" in lib_lower:
        return "transistor"
    if "diode" in lib_lower:
        return "diode"
    if "fuse" in lib_lower or "polyfuse" in lib_lower:
        return "fuse"
    if "inductor" in lib_lower or "choke" in lib_lower:
        return "inductor"
    if "capacitor" in lib_lower:
        return "capacitor"
    if "resistor" in lib_lower:
        return "resistor"

    return "other"


def parse_value(value_str: str) -> float | None:
    """Parse an engineering-notation component value to a float.

    Handles: 10K, 4.7u, 100n, 220p, 1M, 2.2m, 47R, 0R1, 4K7, 1R0, etc.
    Returns None if unparseable.
    """
    if not value_str:
        return None

    # Strip tolerance, voltage rating, package, and other suffixes
    # Common formats: "680K 1%", "220k/R0402", "22uF/6.3V/20%/X5R/C0603"
    s = value_str.strip().split("/")[0].split()[0]  # take part before first "/" or space
    # Strip trailing unit words (mOhm, Ohm, ohm, ohms) before single-char stripping
    s = re.sub(r'[Oo]hms?$', '', s)
    s = s.rstrip("FHΩVfhv%")         # strip trailing unit letters

    if not s:
        return None

    # Multiplier map (SI prefixes used in EE)
    multipliers = {
        "p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3,
        "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9,
        "R": 1, "r": 1,  # "R" as decimal point: 4R7 = 4.7, 0R1 = 0.1
    }

    # Handle embedded multiplier: "4K7" -> 4.7e3, "0R1" -> 0.1, "1R0" -> 1.0
    for suffix, mult in multipliers.items():
        if suffix in s and not s.endswith(suffix):
            idx = s.index(suffix)
            before = s[:idx]
            after = s[idx + 1:]
            if before.replace(".", "").isdigit() and after.isdigit():
                try:
                    return float(f"{before}.{after}") * mult
                except ValueError:
                    pass

    # Handle trailing multiplier: "10K", "100n", "4.7u"
    if s[-1] in multipliers:
        mult = multipliers[s[-1]]
        try:
            return float(s[:-1]) * mult
        except ValueError:
            return None

    # Plain number: "100", "47", "0.1"
    try:
        return float(s)
    except ValueError:
        return None


def _is_power_net_name(net_name: str | None, power_rails: set[str] | None = None) -> bool:
    """Check if a net name looks like a power rail by naming convention.

    Covers both power-symbol-defined rails (via power_rails set) and nets that
    look like power from their name alone — including local/hierarchical labels
    like VDD_nRF, VBATT_MCU, V_BATT that lack an explicit power: symbol.
    """
    if not net_name:
        return False
    if power_rails and net_name in power_rails:
        return True
    nu = net_name.upper()
    # Explicit known names
    if nu in ("GND", "VSS", "AGND", "DGND", "PGND", "GNDPWR", "GNDA", "GNDD",
              "VCC", "VDD", "AVCC", "AVDD", "DVCC", "DVDD", "VBUS",
              "VAA", "VIO", "VMAIN", "VPWR", "VSYS", "VBAT", "VCORE",
              "VIN", "VOUT", "VREG", "VBATT",
              "V3P3", "V1P8", "V1P2", "V2P5", "V5P0", "V12P0",
              "VCCA", "VCCD", "VCCIO", "VDDA", "VDDD", "VDDIO"):
        return True
    # Pattern-based detection
    if nu.startswith("+") or nu.startswith("V+"):
        return True
    # Vnn, VnnV patterns (V3V3, V1V8, V5V0)
    if len(nu) >= 3 and nu[0] == "V" and nu[1].isdigit():
        return True
    # PWRnVn patterns (PWR3V3, PWR1V8, PWR5V0)
    if re.match(r'^PWR\d', nu):
        return True
    # VDD_xxx, VCC_xxx, VBAT_xxx, VBATT_xxx variants (local label power nets)
    # Split on _ and check if first segment is a known power prefix
    first_seg = nu.split("_")[0] if "_" in nu else ""
    if first_seg in ("VDD", "VCC", "AVDD", "AVCC", "DVDD", "DVCC", "VBAT",
                      "VBATT", "VSYS", "VBUS", "VMAIN", "VPWR", "VCORE",
                      "VDDIO", "VCCIO", "VIN", "VOUT", "VREG", "POW",
                      "PWR", "VMOT", "VHEAT"):
        return True
    return False


def _is_ground_name(net_name: str | None) -> bool:
    """Check if a net name looks like a ground rail."""
    if not net_name:
        return False
    nu = net_name.upper()
    # Exact matches
    if nu in ("GND", "VSS", "AGND", "DGND", "PGND", "GNDPWR", "GNDA", "GNDD"):
        return True
    # Prefix/suffix patterns: GND_ISO, GND_SEC, GNDISO, etc.
    if nu.startswith("GND") or nu.endswith("GND"):
        return True
    # VSS variants
    if nu.startswith("VSS"):
        return True
    return False


def analyze_signal_paths(components: list[dict], nets: dict, lib_symbols: dict | None = None, pin_net: dict | None = None) -> dict:
    """Analyze signal processing circuits: filters, dividers, feedback networks.

    Identifies common analog building blocks by tracing passive component
    topologies through the net graph. For each identified circuit, computes
    relevant parameters (cutoff frequency, gain, time constant, etc.).

    Returns a dict with:
    - voltage_dividers: resistive dividers with ratio and output voltage
    - rc_filters: RC low-pass and high-pass filters with cutoff frequency
    - lc_filters: LC filters with resonant frequency
    - feedback_networks: resistor divider feedback for regulators
    - crystal_circuits: crystal oscillators with load capacitance
    - snubbers: RC snubber circuits
    """
    if pin_net is None:
        pin_net = build_pin_to_net_map(nets)
    if lib_symbols is None:
        lib_symbols = {}
    comp_lookup = {c["reference"]: c for c in components}

    # Pre-parse all component values
    parsed_values = {}
    for c in components:
        val = parse_value(c.get("value", ""))
        if val is not None:
            parsed_values[c["reference"]] = val

    results = {
        "voltage_dividers": [],
        "rc_filters": [],
        "lc_filters": [],
        "feedback_networks": [],
        "crystal_circuits": [],
        "snubbers": [],
        "decoupling_analysis": [],
    }

    # Helper: get the two nets a 2-pin component connects to
    def get_two_pin_nets(ref: str) -> tuple[str | None, str | None]:
        n1, _ = pin_net.get((ref, "1"), (None, None))
        n2, _ = pin_net.get((ref, "2"), (None, None))
        return n1, n2

    # Build set of known power rail names from nets that came from power symbols
    known_power_rails = set()
    for net_name, net_info in nets.items():
        for p in net_info.get("pins", []):
            if p["component"].startswith("#PWR") or p["component"].startswith("#FLG"):
                known_power_rails.add(net_name)
                break

    def is_power_net(net_name: str | None) -> bool:
        return _is_power_net_name(net_name, known_power_rails)

    def is_ground(net_name: str | None) -> bool:
        return _is_ground_name(net_name)

    # ---- Voltage Dividers ----
    # Two resistors in series between different nets, with a mid-point net
    resistors = [c for c in components if c["type"] == "resistor" and c["reference"] in parsed_values]

    # Index resistors by their nets for O(n) pair-finding instead of O(n²)
    resistor_nets = {}  # ref -> (net1, net2)
    net_to_resistors = {}  # net_name -> [refs]
    for r in resistors:
        n1, n2 = get_two_pin_nets(r["reference"])
        if not n1 or not n2 or n1 == n2:
            continue
        resistor_nets[r["reference"]] = (n1, n2)
        net_to_resistors.setdefault(n1, []).append(r["reference"])
        net_to_resistors.setdefault(n2, []).append(r["reference"])

    # Check pairs of resistors that share a net (potential dividers)
    vd_seen = set()  # track (r1, r2) pairs to avoid duplicates
    for net_name, refs in net_to_resistors.items():
        if len(refs) < 2:
            continue
        for i, r1_ref in enumerate(refs):
            r1_n1, r1_n2 = resistor_nets[r1_ref]
            r1 = comp_lookup[r1_ref]
            for r2_ref in refs[i + 1:]:
                pair_key = (min(r1_ref, r2_ref), max(r1_ref, r2_ref))
                if pair_key in vd_seen:
                    continue
                vd_seen.add(pair_key)

                r2_n1, r2_n2 = resistor_nets[r2_ref]
                r2 = comp_lookup[r2_ref]

                # Find shared net (mid-point)
                r1_nets = {r1_n1, r1_n2}
                r2_nets = {r2_n1, r2_n2}
                shared = r1_nets & r2_nets
                if len(shared) != 1:
                    continue

                mid_net = shared.pop()
                top_net = (r1_nets - {mid_net}).pop()
                bot_net = (r2_nets - {mid_net}).pop()

                # Reject if mid-point is a power rail with many connections —
                # that's a power bus, not a divider output. Real divider mid-points
                # connect to 2 resistors + maybe an IC input (≤4 connections).
                if is_power_net(mid_net) or is_ground(mid_net):
                    mid_pin_count = len(nets.get(mid_net, {}).get("pins", []))
                    if mid_pin_count > 4:
                        continue

                # One end should be power, other should be ground (or another power)
                # Determine orientation: top is higher voltage, bottom is lower
                if is_ground(top_net) and is_power_net(bot_net):
                    top_net, bot_net = bot_net, top_net
                    r1, r2 = r2, r1
                elif not (is_power_net(top_net) and (is_ground(bot_net) or is_power_net(bot_net))):
                    # Also catch feedback dividers: output -> mid -> ground
                    if not is_ground(bot_net):
                        continue

                r1_val = parsed_values[r1["reference"]]
                r2_val = parsed_values[r2["reference"]]
                if r1_val <= 0 or r2_val <= 0:
                    continue

                # Determine which is top/bottom based on net position
                if is_ground(bot_net):
                    # r_top connects top_net to mid, r_bot connects mid to gnd
                    # Re-derive nets from current r1/r2 (may have been swapped above)
                    r1_nets_cur = set(get_two_pin_nets(r1["reference"]))
                    if top_net in r1_nets_cur:
                        r_top, r_bot = r1_val, r2_val
                        r_top_ref, r_bot_ref = r1["reference"], r2["reference"]
                    else:
                        r_top, r_bot = r2_val, r1_val
                        r_top_ref, r_bot_ref = r2["reference"], r1["reference"]

                    ratio = r_bot / (r_top + r_bot)

                    divider = {
                        "r_top": {"ref": r_top_ref, "value": comp_lookup[r_top_ref]["value"], "ohms": r_top},
                        "r_bottom": {"ref": r_bot_ref, "value": comp_lookup[r_bot_ref]["value"], "ohms": r_bot},
                        "top_net": top_net,
                        "mid_net": mid_net,
                        "bottom_net": bot_net,
                        "ratio": round(ratio, 6),
                    }

                    # Check if mid-point connects to a known feedback pin
                    if mid_net in nets:
                        mid_pins = [p for p in nets[mid_net]["pins"]
                                    if p["component"] != r_top_ref
                                    and p["component"] != r_bot_ref
                                    and not p["component"].startswith("#")]
                        if mid_pins:
                            divider["mid_point_connections"] = mid_pins
                            # If connected to an IC FB pin, this is likely a feedback network
                            for mp in mid_pins:
                                if "FB" in mp.get("pin_name", "").upper():
                                    divider["is_feedback"] = True
                                    results["feedback_networks"].append(divider)
                                    break

                    results["voltage_dividers"].append(divider)

    # ---- RC Filters ----
    # R and C must share a SIGNAL net (not power/ground) to form a real filter.
    # If they only share GND, every R and C in the circuit would match.
    # Exclude resistors that are part of voltage dividers — pairing a feedback
    # divider resistor with an output decoupling cap is a common false positive.
    vd_resistor_refs = set()
    for vd in results["voltage_dividers"]:
        vd_resistor_refs.add(vd["r_top"]["ref"])
        vd_resistor_refs.add(vd["r_bottom"]["ref"])

    capacitors = [c for c in components if c["type"] == "capacitor" and c["reference"] in parsed_values]

    # Index capacitors by net for O(n) RC pair-finding instead of O(R*C)
    cap_nets = {}  # ref -> (net1, net2)
    net_to_caps = {}  # net_name -> [refs]
    for cap in capacitors:
        cn1, cn2 = get_two_pin_nets(cap["reference"])
        if not cn1 or not cn2 or cn1 == cn2:
            continue
        cap_nets[cap["reference"]] = (cn1, cn2)
        net_to_caps.setdefault(cn1, []).append(cap["reference"])
        net_to_caps.setdefault(cn2, []).append(cap["reference"])

    for res in resistors:
        if res["reference"] in vd_resistor_refs:
            continue  # Skip voltage divider resistors
        if res["reference"] not in resistor_nets:
            continue
        r_n1, r_n2 = resistor_nets[res["reference"]]
        r_nets = {r_n1, r_n2}

        # Only check capacitors that share a net with this resistor
        candidate_caps = set()
        for rn in (r_n1, r_n2):
            if not is_power_net(rn) and not is_ground(rn):
                for cref in net_to_caps.get(rn, ()):
                    candidate_caps.add(cref)

        for cap_ref in candidate_caps:
            c_n1, c_n2 = cap_nets[cap_ref]
            c_nets = {c_n1, c_n2}

            shared = r_nets & c_nets
            if len(shared) != 1:
                continue

            shared_net = shared.pop()

            # The shared net must NOT be a power/ground rail — those create
            # false matches between every R and C on the board.
            if is_power_net(shared_net) or is_ground(shared_net):
                continue

            # Reject if shared net has too many connections — a real RC filter
            # node typically has 2-3 connections (R + C + maybe one IC pin).
            # High-fanout nets (>6 pins) are likely buses or IC rails where
            # R and C happen to share a node but don't form a filter.
            shared_pin_count = len(nets.get(shared_net, {}).get("pins", []))
            if shared_pin_count > 6:
                continue

            r_other = (r_nets - {shared_net}).pop()
            c_other = (c_nets - {shared_net}).pop()

            r_val = parsed_values[res["reference"]]
            c_val = parsed_values[cap_ref]

            # Compute cutoff frequency: fc = 1 / (2π·R·C)
            if r_val > 0 and c_val > 0:
                fc = 1.0 / (2.0 * math.pi * r_val * c_val)
                tau = r_val * c_val

                # Classify filter type
                if is_ground(c_other):
                    filter_type = "low-pass"
                elif is_ground(r_other):
                    filter_type = "high-pass"
                else:
                    filter_type = "RC-network"

                # Skip if R is very small — likely series termination or current
                # sense shunt, not an intentional filter
                if r_val < 10:
                    continue

                rc_entry = {
                    "type": filter_type,
                    "resistor": {"ref": res["reference"], "value": comp_lookup[res["reference"]]["value"], "ohms": r_val},
                    "capacitor": {"ref": cap_ref, "value": comp_lookup[cap_ref]["value"], "farads": c_val},
                    "cutoff_hz": round(fc, 2),
                    "time_constant_s": tau,
                    "input_net": r_other if filter_type == "low-pass" else shared_net,
                    "output_net": shared_net if filter_type == "low-pass" else r_other,
                    "ground_net": c_other if is_ground(c_other) else r_other,
                }

                rc_entry["cutoff_formatted"] = _format_frequency(fc)

                results["rc_filters"].append(rc_entry)

    # Merge RC filters where the same resistor pairs with multiple caps on
    # the same shared net (parallel caps = one effective filter, not N filters).
    _rc_groups: dict[tuple[str, str, str], list[dict]] = {}
    for rc in results["rc_filters"]:
        key = (rc["resistor"]["ref"], rc.get("input_net", ""), rc.get("output_net", ""))
        _rc_groups.setdefault(key, []).append(rc)
    merged_rc: list[dict] = []
    for key, entries in _rc_groups.items():
        if len(entries) == 1:
            merged_rc.append(entries[0])
        else:
            total_c = sum(e["capacitor"]["farads"] for e in entries)
            r_val = entries[0]["resistor"]["ohms"]
            fc = 1.0 / (2.0 * math.pi * r_val * total_c)
            tau = r_val * total_c
            cap_refs = [e["capacitor"]["ref"] for e in entries]
            base = entries[0].copy()
            base["capacitor"] = {
                "ref": cap_refs[0],
                "value": f"{len(entries)} caps parallel",
                "farads": total_c,
                "parallel_caps": cap_refs,
            }
            base["cutoff_hz"] = round(fc, 2)
            base["time_constant_s"] = tau
            base["cutoff_formatted"] = _format_frequency(fc)
            merged_rc.append(base)
    results["rc_filters"] = merged_rc

    # ---- LC Filters ----
    inductors = [c for c in components if c["type"] in ("inductor", "ferrite_bead")
                 and c["reference"] in parsed_values]

    # Collect LC pairs grouped by (inductor, shared_net). Multiple caps on
    # the same inductor output node are parallel decoupling, not separate
    # filters — merge them into one entry with summed capacitance.
    _lc_groups: dict[tuple[str, str], list[dict]] = {}

    for ind in inductors:
        l_n1, l_n2 = get_two_pin_nets(ind["reference"])
        if not l_n1 or not l_n2:
            continue

        for cap in capacitors:
            c_n1, c_n2 = get_two_pin_nets(cap["reference"])
            if not c_n1 or not c_n2:
                continue

            l_nets = {l_n1, l_n2}
            c_nets = {c_n1, c_n2}
            # Skip components with both pins on the same net (shorted)
            if len(l_nets) < 2 or len(c_nets) < 2:
                continue
            shared = l_nets & c_nets
            if len(shared) != 1:
                continue

            shared_net_lc = shared.pop()
            # Skip if shared net is power/ground (would match all L-C pairs)
            if is_power_net(shared_net_lc) or is_ground(shared_net_lc):
                continue

            l_val = parsed_values[ind["reference"]]
            c_val = parsed_values[cap["reference"]]

            if l_val > 0 and c_val > 0:
                f0 = 1.0 / (2.0 * math.pi * math.sqrt(l_val * c_val))
                z0 = math.sqrt(l_val / c_val)  # characteristic impedance

                lc_entry = {
                    "inductor": {"ref": ind["reference"], "value": comp_lookup[ind["reference"]]["value"], "henries": l_val},
                    "capacitor": {"ref": cap["reference"], "value": comp_lookup[cap["reference"]]["value"], "farads": c_val},
                    "resonant_hz": round(f0, 2),
                    "impedance_ohms": round(z0, 2),
                    "shared_net": shared_net_lc,
                }

                lc_entry["resonant_formatted"] = _format_frequency(f0)

                _lc_groups.setdefault((ind["reference"], shared_net_lc), []).append(lc_entry)

    # Merge parallel caps per inductor-net pair
    for (_ind_ref, _shared_net), entries in _lc_groups.items():
        if len(entries) == 1:
            results["lc_filters"].append(entries[0])
        else:
            total_c = sum(e["capacitor"]["farads"] for e in entries)
            l_val = entries[0]["inductor"]["henries"]
            f0 = 1.0 / (2.0 * math.pi * math.sqrt(l_val * total_c))
            z0 = math.sqrt(l_val / total_c)
            cap_refs = [e["capacitor"]["ref"] for e in entries]
            merged = {
                "inductor": entries[0]["inductor"],
                "capacitor": {
                    "ref": cap_refs[0],
                    "value": f"{len(entries)} caps parallel",
                    "farads": total_c,
                    "parallel_caps": cap_refs,
                },
                "resonant_hz": round(f0, 2),
                "impedance_ohms": round(z0, 2),
                "shared_net": _shared_net,
            }
            merged["resonant_formatted"] = _format_frequency(f0)
            results["lc_filters"].append(merged)

    # ---- Crystal Oscillator Circuits ----
    crystals = [c for c in components if c["type"] == "crystal"]
    for xtal in crystals:
        xtal_pins = xtal.get("pins", [])
        if len(xtal_pins) < 2:
            continue

        # Find capacitors connected to crystal signal pins (not power/ground)
        xtal_nets = set()
        for pin in xtal_pins:
            net_name, _ = pin_net.get((xtal["reference"], pin["number"]), (None, None))
            if net_name and not is_power_net(net_name) and not is_ground(net_name):
                xtal_nets.add(net_name)

        load_caps = []
        for net_name in xtal_nets:
            if net_name not in nets:
                continue
            for p in nets[net_name]["pins"]:
                if p["component"] != xtal["reference"] and comp_lookup.get(p["component"], {}).get("type") == "capacitor":
                    cap_ref = p["component"]
                    cap_val = parsed_values.get(cap_ref)
                    if cap_val:
                        # Check if other end of cap goes to ground
                        cap_n1, cap_n2 = get_two_pin_nets(cap_ref)
                        other_net = cap_n2 if cap_n1 == net_name else cap_n1
                        if is_ground(other_net):
                            load_caps.append({
                                "ref": cap_ref,
                                "value": comp_lookup[cap_ref]["value"],
                                "farads": cap_val,
                                "net": net_name,
                            })

        xtal_entry = {
            "reference": xtal["reference"],
            "value": xtal.get("value", ""),
            "frequency": parse_value(xtal.get("value", "")),
            "load_caps": load_caps,
        }

        # Compute effective load capacitance: CL = (C1 * C2) / (C1 + C2) + C_stray
        if len(load_caps) >= 2:
            c1 = load_caps[0]["farads"]
            c2 = load_caps[1]["farads"]
            c_stray = 3e-12  # typical stray capacitance estimate
            cl_eff = (c1 * c2) / (c1 + c2) + c_stray
            xtal_entry["effective_load_pF"] = round(cl_eff * 1e12, 2)
            xtal_entry["note"] = f"CL_eff = ({load_caps[0]['value']} * {load_caps[1]['value']}) / ({load_caps[0]['value']} + {load_caps[1]['value']}) + ~3pF stray"

        results["crystal_circuits"].append(xtal_entry)

    # ---- Decoupling Analysis ----
    # For each power rail, compute total decoupling capacitance and frequency coverage
    power_nets = {}
    for net_name, net_info in nets.items():
        if net_name.startswith("__unnamed_"):
            continue
        if is_ground(net_name):
            continue
        if is_power_net(net_name):
            power_nets[net_name] = net_info

    for rail_name, rail_info in power_nets.items():
        rail_caps = []
        for p in rail_info["pins"]:
            comp = comp_lookup.get(p["component"])
            if comp and comp["type"] == "capacitor":
                cap_val = parsed_values.get(p["component"])
                if cap_val:
                    # Check if other pin goes to ground
                    c_n1, c_n2 = get_two_pin_nets(p["component"])
                    other = c_n2 if c_n1 == rail_name else c_n1
                    if is_ground(other):
                        self_resonant = 1.0 / (2.0 * math.pi * math.sqrt(1e-9 * cap_val))  # ~1nH ESL estimate
                        rail_caps.append({
                            "ref": p["component"],
                            "value": comp["value"],
                            "farads": cap_val,
                            "self_resonant_hz": round(self_resonant, 0),
                        })

        if rail_caps:
            total_cap = sum(c["farads"] for c in rail_caps)
            results["decoupling_analysis"].append({
                "rail": rail_name,
                "capacitors": rail_caps,
                "total_capacitance_uF": round(total_cap * 1e6, 3),
                "cap_count": len(rail_caps),
            })

    # ---- Current Sense Circuits ----
    # Pattern: low-value shunt resistor (<=0.5 ohm) with an IC connected to both
    # sides of the shunt (sense amp inputs like INP/INM, VIN+/VIN-, etc.)
    results["current_sense"] = []
    shunt_candidates = [
        c for c in components
        if c["type"] == "resistor" and c["reference"] in parsed_values
        and 0 < parsed_values[c["reference"]] <= 0.5
    ]

    for shunt in shunt_candidates:
        # Support both 2-pin and 4-pin Kelvin shunts (R_Shunt: pins 1,4=current; 2,3=sense)
        sense_n1, sense_n2 = None, None
        # Check for 4-pin Kelvin first (pins 1,4=current path; 2,3=sense)
        n1, _ = pin_net.get((shunt["reference"], "1"), (None, None))
        n4, _ = pin_net.get((shunt["reference"], "4"), (None, None))
        n3, _ = pin_net.get((shunt["reference"], "3"), (None, None))
        if n1 and n4 and n3:
            # 4-pin Kelvin shunt
            n2, _ = pin_net.get((shunt["reference"], "2"), (None, None))
            s_n1, s_n2 = n1, n4
            sense_n1, sense_n2 = n2, n3
        else:
            s_n1, s_n2 = get_two_pin_nets(shunt["reference"])
            if not s_n1 or not s_n2:
                continue
        if s_n1 == s_n2:
            continue
        # Skip if both nets are power/ground (bulk decoupling, not sensing)
        if is_ground(s_n1) and is_ground(s_n2):
            continue

        shunt_ohms = parsed_values[shunt["reference"]]

        # Find ICs connected to BOTH sides of the shunt (via current or sense pins)
        comps_on_n1 = set()
        comps_on_n2 = set()
        check_nets_1 = [s_n1] + ([sense_n1] if sense_n1 else [])
        check_nets_2 = [s_n2] + ([sense_n2] if sense_n2 else [])
        for nn in check_nets_1:
            if nn in nets:
                for p in nets[nn]["pins"]:
                    if p["component"] != shunt["reference"]:
                        comps_on_n1.add(p["component"])
        for nn in check_nets_2:
            if nn in nets:
                for p in nets[nn]["pins"]:
                    if p["component"] != shunt["reference"]:
                        comps_on_n2.add(p["component"])

        sense_ics = comps_on_n1 & comps_on_n2
        # 1-hop: if no IC on both sides directly, look through filter resistors
        # (e.g., shunt -> R_filter -> sense IC is a common BMS pattern)
        if not any(comp_lookup.get(c, {}).get("type") == "ic" for c in sense_ics):
            for nn in check_nets_1:
                if nn not in nets:
                    continue
                for p in nets[nn]["pins"]:
                    r_comp = comp_lookup.get(p["component"])
                    if r_comp and r_comp["type"] == "resistor" and p["component"] != shunt["reference"]:
                        r_other = get_two_pin_nets(p["component"])
                        if r_other[0] and r_other[1]:
                            hop_net = r_other[1] if r_other[0] == nn else r_other[0]
                            if hop_net in nets:
                                for hp in nets[hop_net]["pins"]:
                                    comps_on_n1.add(hp["component"])
            for nn in check_nets_2:
                if nn not in nets:
                    continue
                for p in nets[nn]["pins"]:
                    r_comp = comp_lookup.get(p["component"])
                    if r_comp and r_comp["type"] == "resistor" and p["component"] != shunt["reference"]:
                        r_other = get_two_pin_nets(p["component"])
                        if r_other[0] and r_other[1]:
                            hop_net = r_other[1] if r_other[0] == nn else r_other[0]
                            if hop_net in nets:
                                for hp in nets[hop_net]["pins"]:
                                    comps_on_n2.add(hp["component"])
            sense_ics = comps_on_n1 & comps_on_n2
        for ic_ref in sense_ics:
            ic_comp = comp_lookup.get(ic_ref)
            if not ic_comp:
                continue
            # Only consider ICs (sense amplifiers, MCUs with ADC)
            if ic_comp["type"] not in ("ic",):
                continue

            results["current_sense"].append({
                "shunt": {
                    "ref": shunt["reference"],
                    "value": shunt["value"],
                    "ohms": shunt_ohms,
                },
                "sense_ic": {
                    "ref": ic_ref,
                    "value": ic_comp.get("value", ""),
                    "type": ic_comp.get("type", ""),
                },
                "high_net": s_n1,
                "low_net": s_n2,
                "max_current_50mV_A": round(0.05 / shunt_ohms, 3) if shunt_ohms > 0 else None,
                "max_current_100mV_A": round(0.1 / shunt_ohms, 3) if shunt_ohms > 0 else None,
            })

    # ---- Power Regulator Topology ----
    # Detect switching regulators by finding ICs with:
    #   - FB/feedback pin connected to a voltage divider (already detected above)
    #   - EN/enable pin
    #   - SW/switch or BOOT/bootstrap pin connected to an inductor
    #   - VIN/input and VOUT/output power pins
    # Also detect LDOs (no inductor, just VIN -> IC -> VOUT with caps)
    results["power_regulators"] = []

    for ic in [c for c in components if c["type"] == "ic"]:
        ref = ic["reference"]
        ic_pins = {}  # pin_name -> (net_name, pin_number)
        for pkey, (net_name, _) in pin_net.items():
            if pkey[0] == ref:
                # Find pin name from net info
                pin_num = pkey[1]
                pin_name = ""
                if net_name in nets:
                    for p in nets[net_name]["pins"]:
                        if p["component"] == ref and p["pin_number"] == pin_num:
                            pin_name = p.get("pin_name", "").upper()
                            break
                ic_pins[pin_name] = (net_name, pin_num)

        # Look for regulator pin patterns
        fb_pin = None
        sw_pin = None
        en_pin = None
        vin_pin = None
        vout_pin = None
        boot_pin = None

        for pname, (net, pnum) in ic_pins.items():
            # Use startswith for pins that may have numeric suffixes (FB1, SW2, etc.)
            pn_base = pname.rstrip("0123456789")  # Strip trailing digits
            # Split composite pin names like "FB/VOUT" into parts
            pn_parts = {p.strip() for p in pname.split("/")} | {pn_base}
            if pn_parts & {"FB", "VFB", "ADJ", "VADJ"}:
                if not fb_pin:
                    fb_pin = (pname, net)
                # Composite names like "FB/VOUT" also set vout_pin
                if not vout_pin and pn_parts & {"VOUT", "VO", "OUT", "OUTPUT"}:
                    vout_pin = (pname, net)
            elif pn_parts & {"SW", "PH", "LX"}:
                if not sw_pin:
                    sw_pin = (pname, net)
            elif pname in ("EN", "ENABLE", "ON", "~{SHDN}", "SHDN", "~{EN}") or \
                 (pn_base == "EN" and len(pname) <= 3):
                en_pin = (pname, net)
            elif pn_parts & {"VIN", "VI", "IN", "PVIN", "AVIN", "INPUT"}:
                vin_pin = (pname, net)
            elif pn_parts & {"VOUT", "VO", "OUT", "OUTPUT"}:
                vout_pin = (pname, net)
            elif pn_parts & {"BOOT", "BST", "BOOTSTRAP", "CBST"}:
                boot_pin = (pname, net)

        if not fb_pin and not sw_pin and not vout_pin:
            continue  # Not a regulator

        # Early lib_id check: ICs with only VOUT (no FB/SW/BOOT) must have
        # regulator keywords in lib_id/value. ICs with SW pin but no inductor
        # on the SW net and no regulator keywords are also rejected — many
        # analog ICs (AFEs, codecs) have pins named "SW" for other purposes.
        # Build a combined search string from lib_id, value, and description.
        # For custom libraries (e.g. "AADuffy:AP2210K-5.0TRG1"), also extract
        # the part name after the colon for better keyword matching.
        lib_id_raw = ic.get("lib_id", "")
        lib_part_name = lib_id_raw.split(":")[-1] if ":" in lib_id_raw else ""
        desc_lower = ic.get("description", "").lower()
        lib_val_lower = (lib_id_raw + " " + ic.get("value", "") + " " + lib_part_name).lower()
        reg_lib_keywords = ("regulator", "regul", "ldo", "vreg", "buck", "boost",
                           "converter", "dc-dc", "dc_dc", "linear_regulator",
                           "switching_regulator",
                           "ams1117", "lm317", "lm78", "lm79", "ld1117", "ld33",
                           "ap6", "tps5", "tps6", "tlv7", "rt5", "mp1", "mp2",
                           "sy8", "max150", "max170", "ncp1", "xc6", "mcp170",
                           "mic29", "mic55", "ap2112", "ap2210", "ap73",
                           "ncv4", "lm26", "lm11", "78xx",
                           "79xx", "lt308", "lt36", "ltc36", "lt86", "ltc34")
        has_reg_keyword = (any(k in lib_val_lower for k in reg_lib_keywords) or
                          any(k in desc_lower for k in ("regulator", "ldo", "vreg",
                                                        "voltage regulator")))

        if not fb_pin and not boot_pin:
            if not sw_pin and not has_reg_keyword:
                # Only VOUT pin, no regulator keywords → check if VIN+VOUT
                # both connect to distinct power nets (custom-lib LDOs like TC1185)
                if vin_pin and vout_pin:
                    in_net = vin_pin[1]
                    out_net = vout_pin[1]
                    if not (is_power_net(in_net) and is_power_net(out_net)
                            and in_net != out_net):
                        continue
                else:
                    continue
            if sw_pin and not has_reg_keyword:
                # SW pin but check if inductor is connected
                sw_has_inductor = False
                sw_net_name = sw_pin[1]
                if sw_net_name in nets:
                    for p in nets[sw_net_name]["pins"]:
                        comp_c = comp_lookup.get(p["component"])
                        if comp_c and comp_c["type"] == "inductor":
                            sw_has_inductor = True
                            break
                if not sw_has_inductor:
                    continue

        reg_info = {
            "ref": ref,
            "value": ic["value"],
            "lib_id": ic.get("lib_id", ""),
        }

        # Determine topology
        if sw_pin:
            # Check if SW pin connects to an inductor
            sw_net = sw_pin[1]
            has_inductor = False
            inductor_ref = None
            if sw_net in nets:
                for p in nets[sw_net]["pins"]:
                    comp = comp_lookup.get(p["component"])
                    if comp and comp["type"] == "inductor":
                        has_inductor = True
                        inductor_ref = p["component"]
                        break
            if has_inductor:
                reg_info["topology"] = "switching"
                reg_info["inductor"] = inductor_ref
                if boot_pin:
                    reg_info["has_bootstrap"] = True
            else:
                reg_info["topology"] = "switching"  # SW pin but no inductor found
        elif vout_pin and not sw_pin:
            reg_info["topology"] = "LDO"
        elif fb_pin and not sw_pin:
            reg_info["topology"] = "unknown"

        # Detect inverting topology from part name/description or output net name
        inverting_kw = ("invert", "inv_", "_inv", "negative output", "neg_out")
        is_inverting = any(k in lib_val_lower for k in inverting_kw) or \
                       any(k in desc_lower for k in inverting_kw)

        # Extract input/output rails
        if vin_pin:
            reg_info["input_rail"] = vin_pin[1]
        if vout_pin:
            reg_info["output_rail"] = vout_pin[1]
            # Also check if output rail name suggests negative voltage
            out_net_u = vout_pin[1].upper()
            if re.search(r'[-](\d)', out_net_u) or "NEG" in out_net_u or out_net_u.startswith("-"):
                is_inverting = True
        if is_inverting:
            reg_info["inverting"] = True

        # Check feedback divider for output voltage estimation
        if fb_pin:
            fb_net = fb_pin[1]
            reg_info["fb_net"] = fb_net
            # Try part-specific Vref lookup first, fall back to heuristic sweep
            known_vref, vref_source = _lookup_regulator_vref(
                ic.get("value", ""), ic.get("lib_id", ""))
            # Find matching voltage divider
            for vd in results["voltage_dividers"]:
                if vd["mid_net"] == fb_net:
                    ratio = vd["ratio"]
                    if known_vref is not None:
                        # Use the known Vref from the lookup table
                        v_out = known_vref / ratio if ratio > 0 else 0
                        if 0.5 < v_out < 60:
                            reg_info["estimated_vout"] = round(v_out, 3)
                            reg_info["assumed_vref"] = known_vref
                            reg_info["vref_source"] = "lookup"
                            reg_info["feedback_divider"] = {
                                "r_top": vd["r_top"]["ref"],
                                "r_bottom": vd["r_bottom"]["ref"],
                                "ratio": ratio,
                            }
                    else:
                        # Heuristic: try common Vref values
                        for vref in [0.6, 0.8, 1.0, 1.22, 1.25]:
                            v_out = vref / ratio if ratio > 0 else 0
                            if 0.5 < v_out < 60:
                                reg_info["estimated_vout"] = round(v_out, 3)
                                reg_info["assumed_vref"] = vref
                                reg_info["vref_source"] = "heuristic"
                                reg_info["feedback_divider"] = {
                                    "r_top": vd["r_top"]["ref"],
                                    "r_bottom": vd["r_bottom"]["ref"],
                                    "ratio": ratio,
                                }
                                break
                    break

        # Negate Vout for inverting regulators
        if reg_info.get("inverting") and "estimated_vout" in reg_info:
            reg_info["estimated_vout"] = -abs(reg_info["estimated_vout"])

        # Only add if we found meaningful regulator features
        # Filter out false positives: require FB pin, or recognized power rail on IN/OUT,
        # or regulator-related keywords in lib/value
        is_regulator = False
        if fb_pin or sw_pin or boot_pin:
            is_regulator = True
        elif vin_pin or vout_pin:
            # Only consider as regulator if at least one rail is a named power net
            in_net = vin_pin[1] if vin_pin else ""
            out_net = vout_pin[1] if vout_pin else ""
            if is_power_net(in_net) or is_power_net(out_net):
                is_regulator = True
            if has_reg_keyword:
                is_regulator = True

        if is_regulator and any(k in reg_info for k in ("topology", "input_rail", "output_rail", "estimated_vout")):
            results["power_regulators"].append(reg_info)

    # ---- Protection Circuits ----
    # Detect TVS/varistor/ESD protection on signal lines, plus Schottky
    # reverse-polarity protection diodes and PTC/polyfuses.
    results["protection_devices"] = []
    protection_types = ("diode", "varistor", "surge_arrester")
    tvs_keywords = ("tvs", "esd", "pesd", "prtr", "usblc", "sp0", "tpd", "ip4", "rclamp",
                     "smaj", "smbj", "p6ke", "1.5ke", "lesd", "nup")
    # Schottky diodes used for reverse-polarity protection connect between a
    # power rail and ground/another rail.  Detect by lib_id containing "schottky".
    schottky_keywords = ("schottky", "d_schottky")

    for comp in components:
        if comp["type"] not in protection_types:
            continue
        val = comp.get("value", "").lower()
        lib = comp.get("lib_id", "").lower()
        desc = comp.get("description", "").lower()

        is_tvs = comp["type"] == "diode" and any(k in val or k in lib for k in tvs_keywords)
        is_schottky = comp["type"] == "diode" and any(k in lib or k in desc for k in schottky_keywords)
        is_non_diode_protection = comp["type"] in ("varistor", "surge_arrester")

        if comp["type"] == "diode" and not is_tvs and not is_schottky:
            continue

        # Multi-pin protection diodes (PRTR5V0U2X, etc.) — handle like ESD ICs
        comp_pins = comp.get("pins", [])
        if len(comp_pins) > 2 and is_tvs:
            if any(p["ref"] == comp["reference"] for p in results["protection_devices"]):
                continue
            protected = []
            for pin in comp_pins:
                net_name, _ = pin_net.get((comp["reference"], pin["number"]), (None, None))
                if net_name and not is_power_net(net_name) and not is_ground(net_name):
                    protected.append(net_name)
            for net_name in set(protected):
                results["protection_devices"].append({
                    "ref": comp["reference"],
                    "value": comp.get("value", ""),
                    "type": "esd_ic",
                    "protected_net": net_name,
                    "clamp_net": None,
                })
            continue

        d_n1, d_n2 = get_two_pin_nets(comp["reference"])
        if not d_n1 or not d_n2:
            continue

        protected_net = None
        prot_type = comp["type"]

        if is_schottky and not is_tvs:
            # Schottky reverse-polarity protection: one pin on power, one on
            # ground or another power rail.  The protected net is the power rail.
            if is_power_net(d_n1) and (is_ground(d_n2) or is_power_net(d_n2)):
                protected_net = d_n1
                prot_type = "reverse_polarity"
            elif is_power_net(d_n2) and (is_ground(d_n1) or is_power_net(d_n1)):
                protected_net = d_n2
                prot_type = "reverse_polarity"
        else:
            # TVS/varistor/surge arrester: one pin on signal, one on ground/power
            if is_ground(d_n1) and not is_ground(d_n2):
                protected_net = d_n2
            elif is_ground(d_n2) and not is_ground(d_n1):
                protected_net = d_n1
            elif is_power_net(d_n1) and not is_power_net(d_n2):
                protected_net = d_n2
            elif is_power_net(d_n2) and not is_power_net(d_n1):
                protected_net = d_n1

        if protected_net:
            results["protection_devices"].append({
                "ref": comp["reference"],
                "value": comp.get("value", ""),
                "type": prot_type,
                "protected_net": protected_net,
                "clamp_net": d_n1 if protected_net == d_n2 else d_n2,
            })

    # Also detect varistors and surge arresters (already typed correctly)
    for comp in components:
        if comp["type"] in ("varistor", "surge_arrester"):
            d_n1, d_n2 = get_two_pin_nets(comp["reference"])
            if not d_n1 or not d_n2:
                continue
            # Avoid duplicates
            if any(p["ref"] == comp["reference"] for p in results["protection_devices"]):
                continue
            protected_net = d_n1 if not is_ground(d_n1) else d_n2
            results["protection_devices"].append({
                "ref": comp["reference"],
                "value": comp.get("value", ""),
                "type": comp["type"],
                "protected_net": protected_net,
                "clamp_net": d_n1 if protected_net == d_n2 else d_n2,
            })

    # PTC fuses / polyfuses used as overcurrent protection
    for comp in components:
        if comp["type"] != "fuse":
            continue
        if any(p["ref"] == comp["reference"] for p in results["protection_devices"]):
            continue
        d_n1, d_n2 = get_two_pin_nets(comp["reference"])
        if not d_n1 or not d_n2:
            continue
        # Fuses protect the net on the load side; if one side is a power
        # rail, the other side is the protected (downstream) net
        protected_net = None
        if is_power_net(d_n1) and not is_power_net(d_n2) and not is_ground(d_n2):
            protected_net = d_n2
        elif is_power_net(d_n2) and not is_power_net(d_n1) and not is_ground(d_n1):
            protected_net = d_n1
        elif is_power_net(d_n1) and is_power_net(d_n2):
            # Both sides are power — common for input protection fuses
            protected_net = d_n2
        if protected_net:
            results["protection_devices"].append({
                "ref": comp["reference"],
                "value": comp.get("value", ""),
                "type": "fuse",
                "protected_net": protected_net,
                "clamp_net": d_n1 if protected_net == d_n2 else d_n2,
            })

    # ---- IC-based ESD Protection ----
    # Multi-pin ESD protection ICs (USBLC6, TPD4E, PRTR5V0, IP4220, etc.)
    esd_ic_keywords = ("usblc", "tpd", "prtr", "ip42", "sp05", "esda",
                       "pesd", "nup4", "sn65220", "dtc11", "sp72")
    for comp in components:
        if comp["type"] != "ic":
            continue
        val = comp.get("value", "").lower()
        lib = comp.get("lib_id", "").lower()
        if not any(k in val or k in lib for k in esd_ic_keywords):
            continue
        if any(p["ref"] == comp["reference"] for p in results["protection_devices"]):
            continue
        # Find signal nets (non-power, non-ground) connected to this IC
        protected = []
        for pin in comp.get("pins", []):
            net_name, _ = pin_net.get((comp["reference"], pin["number"]), (None, None))
            if net_name and not is_power_net(net_name) and not is_ground(net_name):
                protected.append(net_name)
        for net_name in set(protected):
            results["protection_devices"].append({
                "ref": comp["reference"],
                "value": comp.get("value", ""),
                "type": "esd_ic",
                "protected_net": net_name,
                "clamp_net": None,
            })

    # ---- Op-Amp Gain Stage Detection ----
    # Detect op-amp configurations: inverting, non-inverting, buffer, differential.
    # Pattern: op-amp IC with feedback resistor from output to inverting input.
    results["opamp_circuits"] = []
    opamp_lib_keywords = ("amplifier_operational", "op_amp", "opamp")
    # INA1xx split: INA10x-INA13x are instrumentation amps (op-amp-like);
    # INA18x/INA19x are fixed-gain current sense amps (not op-amps);
    # INA2xx/INA3xx are digital power monitors (not op-amps)
    opamp_value_keywords = ("opa", "lm358", "lm324", "mcp6", "ad8", "tl07", "tl08",
                            "ne5532", "lf35", "lt623", "ths", "ada4",
                            "ina10", "ina11", "ina12", "ina13",
                            "ncs3", "lmc7", "lmv3", "max40", "max44",
                            "tsc10", "mcp60", "mcp61", "mcp65")

    seen_opamp_units = set()  # (ref, unit) to avoid multi-unit duplicates
    for ic in [c for c in components if c["type"] == "ic"]:
        lib = ic.get("lib_id", "").lower()
        val = ic.get("value", "").lower()
        desc = ic.get("description", "").lower()
        # For custom libraries (e.g. "AADuffy:MCP6S28-I/SL"), extract part name
        # after the colon and use it as an additional value match source
        lib_part = lib.split(":")[-1] if ":" in lib else ""
        match_sources = [val, lib_part]  # check both value and lib part name
        if not (any(k in lib for k in opamp_lib_keywords) or
                any(s.startswith(k) for k in opamp_value_keywords for s in match_sources) or
                any(k in desc for k in ("opamp", "op-amp", "op amp", "operational amplifier"))):
            continue

        ref = ic["reference"]
        unit = ic.get("unit", 1)
        if (ref, unit) in seen_opamp_units:
            continue
        seen_opamp_units.add((ref, unit))

        # For multi-unit op-amps (e.g., LM324 quad), restrict to this unit's pins.
        # Get pin numbers for this unit from the lib_symbol's unit_pins map.
        unit_pin_nums = None
        lib_id = ic.get("lib_id", "")
        sym_def = lib_symbols.get(lib_id)
        if sym_def and sym_def.get("unit_pins") and unit in sym_def["unit_pins"]:
            unit_pin_nums = {p["number"] for p in sym_def["unit_pins"][unit]}
            # Also include shared pins (unit 0)
            if 0 in sym_def["unit_pins"]:
                unit_pin_nums |= {p["number"] for p in sym_def["unit_pins"][0]}

        # Find op-amp pins: +IN, -IN, OUT (pin names vary by library)
        pos_in = None   # non-inverting input
        neg_in = None   # inverting input
        out_pin = None
        for (pref, pnum), (net, _) in pin_net.items():
            if pref != ref or not net:
                continue
            # Skip pins not belonging to this unit (multi-unit symbols)
            if unit_pin_nums is not None and pnum not in unit_pin_nums:
                continue
            pin_name = ""
            if net in nets:
                for p in nets[net]["pins"]:
                    if p["component"] == ref and p["pin_number"] == pnum:
                        pin_name = p.get("pin_name", "").upper()
                        break
            if not pin_name:
                continue
            # Standard op-amp pin names (various libraries use different conventions)
            pn = pin_name.replace(" ", "")
            if pn in ("+", "+IN", "IN+", "INP", "V+IN", "NONINVERTING") or \
               (pn.startswith("+") and "IN" in pn):
                pos_in = (pin_name, net, pnum)
            elif pn in ("-", "-IN", "IN-", "INM", "V-IN", "INVERTING") or \
                 (pn.startswith("-") and "IN" in pn):
                neg_in = (pin_name, net, pnum)
            elif pn in ("OUT", "OUTPUT", "VOUT", "VO"):
                out_pin = (pin_name, net, pnum)
            # Skip power pins (V+, V-, VCC, VEE, etc.)
            elif pn in ("V+", "V-", "VCC", "VDD", "VEE", "VSS", "VS+", "VS-"):
                continue
            # Also match by pin type for unlabeled pins
            else:
                pin_type = ""
                if net in nets:
                    for p in nets[net]["pins"]:
                        if p["component"] == ref and p["pin_number"] == pnum:
                            pin_type = p.get("pin_type", "")
                            break
                if pin_type == "output" and not out_pin:
                    out_pin = (pin_name, net, pnum)
                elif pin_type == "input":
                    if not pos_in:
                        pos_in = (pin_name, net, pnum)
                    elif not neg_in:
                        neg_in = (pin_name, net, pnum)

        if not out_pin or not neg_in:
            continue

        out_net = out_pin[1]
        neg_net = neg_in[1]
        pos_net = pos_in[1] if pos_in else None

        # Find feedback resistor: resistor between output and inverting input
        # First try direct: R with one pin on out_net and other on neg_net
        # Then try 2-hop: R on out_net → intermediate net → R/C on neg_net
        rf_ref = None
        rf_val = None
        if out_net in nets and neg_net != out_net:
            out_comps = {p["component"] for p in nets[out_net]["pins"] if p["component"] != ref}
            neg_comps = {p["component"] for p in nets[neg_net]["pins"] if p["component"] != ref}
            fb_resistors = out_comps & neg_comps
            for fb_ref in fb_resistors:
                comp = comp_lookup.get(fb_ref)
                if comp and comp["type"] == "resistor" and fb_ref in parsed_values:
                    rf_ref = fb_ref
                    rf_val = parsed_values[fb_ref]
                    break

            # 2-hop feedback: R/C from output → intermediate → R/C to inverting input
            if not rf_ref:
                for out_comp_ref in out_comps:
                    oc = comp_lookup.get(out_comp_ref)
                    if not oc or oc["type"] not in ("resistor", "capacitor"):
                        continue
                    # Find the other net of this component
                    o_n1, o_n2 = get_two_pin_nets(out_comp_ref)
                    if not o_n1 or not o_n2:
                        continue
                    mid = o_n2 if o_n1 == out_net else o_n1
                    if mid == out_net or is_ground(mid) or is_power_net(mid):
                        continue
                    # Check if any component on mid also connects to neg_net
                    if mid in nets:
                        mid_comps = {p["component"] for p in nets[mid]["pins"]
                                    if p["component"] != out_comp_ref}
                        fb_via_mid = mid_comps & neg_comps
                        for fb2 in fb_via_mid:
                            c2 = comp_lookup.get(fb2)
                            if c2 and c2["type"] in ("resistor", "capacitor"):
                                # Found a 2-hop feedback path
                                # Use the output-side component as Rf if it's a resistor
                                if oc["type"] == "resistor" and out_comp_ref in parsed_values:
                                    rf_ref = out_comp_ref
                                    rf_val = parsed_values[out_comp_ref]
                                elif c2["type"] == "resistor" and fb2 in parsed_values:
                                    rf_ref = fb2
                                    rf_val = parsed_values[fb2]
                                break
                    if rf_ref:
                        break

        # Find input resistor: resistor on inverting input (other end not output)
        ri_ref = None
        ri_val = None
        if neg_net in nets:
            for p in nets[neg_net]["pins"]:
                if p["component"] == ref or p["component"] == rf_ref:
                    continue
                comp = comp_lookup.get(p["component"])
                if comp and comp["type"] == "resistor" and p["component"] in parsed_values:
                    # Verify other end isn't output
                    r_n1, r_n2 = get_two_pin_nets(p["component"])
                    other = r_n2 if r_n1 == neg_net else r_n1
                    if other != out_net:
                        ri_ref = p["component"]
                        ri_val = parsed_values[p["component"]]
                        break

        # Determine configuration
        config = "unknown"
        gain = None
        if out_net == neg_net:
            config = "buffer"
            gain = 1.0
        elif rf_ref and ri_ref and ri_val and rf_val:
            # Check if signal enters non-inverting or inverting input
            if pos_net and pos_net != neg_net:
                # Check if non-inverting input connects to signal (not just power/ground)
                pos_has_signal = pos_net and not is_power_net(pos_net) and not is_ground(pos_net)
                neg_has_signal = ri_ref is not None  # has input resistor
                if pos_has_signal and not neg_has_signal:
                    config = "non_inverting"
                    gain = 1.0 + rf_val / ri_val
                else:
                    config = "inverting"
                    gain = -rf_val / ri_val
            else:
                config = "inverting"
                gain = -rf_val / ri_val
        elif rf_ref and not ri_ref:
            config = "transimpedance_or_buffer"
        elif not rf_ref:
            config = "comparator_or_open_loop"

        entry = {
            "reference": ref,
            "unit": unit,
            "value": ic["value"],
            "lib_id": ic.get("lib_id", ""),
            "configuration": config,
            "output_net": out_net,
            "inverting_input_net": neg_net,
            "non_inverting_input_net": pos_net,
        }
        if gain is not None:
            entry["gain"] = round(gain, 3)
            entry["gain_dB"] = round(20 * math.log10(abs(gain)), 1) if gain != 0 else None
        if rf_ref:
            entry["feedback_resistor"] = {"ref": rf_ref, "ohms": rf_val}
        if ri_ref:
            entry["input_resistor"] = {"ref": ri_ref, "ohms": ri_val}
        # Dedup: skip if we already have this ref+output_net (multi-unit instances)
        dedup_key = (ref, out_net, neg_net)
        if dedup_key not in seen_opamp_units:
            seen_opamp_units.add(dedup_key)
            results["opamp_circuits"].append(entry)

    # ---- Gate Driver / Bridge Topology ----
    # Detect half-bridge / H-bridge / 3-phase configurations:
    # Pattern: transistor pairs where one drain connects to the other's source (mid-point),
    # high-side drain on power rail, low-side source on ground/sense.
    # Works across hierarchical sheets because components and nets are the
    # fully-flattened design — sheet pin stubs ensure nets crossing sheet
    # boundaries share the same unified net name.
    results["bridge_circuits"] = []
    transistors = [c for c in components if c["type"] == "transistor"]

    # Build transistor pin map: ref -> {GATE: net, DRAIN: net, SOURCE: net}
    fet_pins = {}
    for t in transistors:
        ref = t["reference"]
        pins = {}
        for (pref, pnum), (net, _) in pin_net.items():
            if pref != ref:
                continue
            # Find pin name
            if net in nets:
                for p in nets[net]["pins"]:
                    if p["component"] == ref and p["pin_number"] == pnum:
                        pn = p.get("pin_name", "").upper()
                        pn_base = pn.rstrip("0123456789")  # G1→G, D2→D
                        if "GATE" in pn or pn_base == "G":
                            pins["gate"] = net
                        elif "DRAIN" in pn or pn_base == "D":
                            pins.setdefault("drain", net)  # take first (multi-pin packages)
                        elif "SOURCE" in pn or pn_base == "S":
                            pins.setdefault("source", net)
                        break
        if "gate" in pins and "drain" in pins and "source" in pins:
            fet_pins[ref] = {**pins, "value": t["value"], "lib_id": t.get("lib_id", "")}

    # Find half-bridge pairs: high-side source == low-side drain (shared mid-point)
    matched = set()
    half_bridges = []
    for hi_ref, hi in fet_pins.items():
        if hi_ref in matched:
            continue
        for lo_ref, lo in fet_pins.items():
            if lo_ref == hi_ref or lo_ref in matched:
                continue
            # High-side source connects to low-side drain (mid-point/output)
            if hi["source"] == lo["drain"]:
                mid_net = hi["source"]
                # Verify high-side drain is on power and low-side source is on ground/sense
                if is_power_net(hi["drain"]) or is_ground(lo["source"]):
                    half_bridges.append({
                        "high_side": hi_ref,
                        "low_side": lo_ref,
                        "output_net": mid_net,
                        "power_net": hi["drain"],
                        "ground_net": lo["source"],
                        "high_gate": hi["gate"],
                        "low_gate": lo["gate"],
                    })
                    matched.add(hi_ref)
                    matched.add(lo_ref)
                    break

    if half_bridges:
        # Determine topology: 1=half-bridge, 2=H-bridge, 3+=3-phase
        n = len(half_bridges)
        if n == 1:
            topology = "half_bridge"
        elif n == 2:
            topology = "h_bridge"
        elif n == 3:
            topology = "three_phase"
        else:
            topology = f"{n}_phase"

        # Find gate driver IC: IC connected to gate nets
        gate_nets = set()
        for hb in half_bridges:
            gate_nets.add(hb["high_gate"])
            gate_nets.add(hb["low_gate"])
        driver_ics = set()
        for gn in gate_nets:
            if gn in nets:
                for p in nets[gn]["pins"]:
                    comp = comp_lookup.get(p["component"])
                    if comp and comp["type"] == "ic":
                        driver_ics.add(p["component"])

        results["bridge_circuits"].append({
            "topology": topology,
            "half_bridges": half_bridges,
            "driver_ics": list(driver_ics),
            "driver_values": {ref: comp_lookup[ref]["value"] for ref in driver_ics if ref in comp_lookup},
            "fet_values": {hb["high_side"]: fet_pins[hb["high_side"]]["value"] for hb in half_bridges},
        })

    # ---- Transistor Circuit Analysis ----
    # For each transistor, extract surrounding circuit context:
    # - Gate/base drive: resistor, pull-down, driver IC
    # - Drain/collector load: what's connected (inductive, resistive, LED, etc.)
    # - Source/emitter: ground, sense resistor, or signal
    # - Protection: flyback diode, snubber, ESD
    # This is a data extraction layer — Claude uses datasheets to evaluate Vgs/Vbe adequacy.
    results["transistor_circuits"] = []

    # Build BJT pin map too (base/collector/emitter)
    bjt_pins = {}
    for t in transistors:
        ref = t["reference"]
        if ref in fet_pins:
            continue  # Already mapped as FET
        pins = {}
        for (pref, pnum), (net, _) in pin_net.items():
            if pref != ref:
                continue
            if net in nets:
                for p in nets[net]["pins"]:
                    if p["component"] == ref and p["pin_number"] == pnum:
                        pn = p.get("pin_name", "").upper()
                        if pn in ("B", "BASE"):
                            pins["base"] = net
                        elif pn in ("C", "COLLECTOR"):
                            pins["collector"] = net
                        elif pn in ("E", "EMITTER"):
                            pins["emitter"] = net
                        break
        if len(pins) >= 2:
            bjt_pins[ref] = {**pins, "value": t["value"], "lib_id": t.get("lib_id", "")}

    def _get_net_components(net_name, exclude_ref):
        """Get components on a net excluding the transistor itself."""
        if net_name not in nets:
            return []
        result_comps = []
        for p in nets[net_name]["pins"]:
            if p["component"] == exclude_ref:
                continue
            comp = comp_lookup.get(p["component"])
            if comp:
                result_comps.append({
                    "reference": p["component"],
                    "type": comp["type"],
                    "value": comp["value"],
                    "pin_name": p.get("pin_name", ""),
                    "pin_number": p["pin_number"],
                })
        return result_comps

    def _classify_load(net_name, exclude_ref):
        """Classify what's on a net as a load type.

        Checks net name keywords first (motor, heater, fan, solenoid, valve,
        pump, relay, speaker, buzzer, lamp) for cases where the net name
        reveals the load type better than the connected components.
        Falls back to component-type classification.
        """
        # Net name keyword classification — catches loads driven through
        # connectors or across sheet boundaries where component type alone
        # would just show "connector" or "other"
        if net_name:
            nu = net_name.upper()
            for load_type, keywords in _LOAD_TYPE_KEYWORDS.items():
                if any(kw in nu for kw in keywords):
                    return load_type

        comps = _get_net_components(net_name, exclude_ref)
        types = {c["type"] for c in comps}
        if "inductor" in types:
            return "inductive"
        if "led" in types:
            return "led"
        if types == {"resistor"} or types == {"resistor", "capacitor"}:
            return "resistive"
        if "connector" in types:
            return "connector"
        if "ic" in types:
            return "ic"
        if "transistor" in types:
            return "transistor"  # cascaded
        return "other"

    # Analyze each FET
    for ref, pins in fet_pins.items():
        if ref in matched:
            continue  # Skip bridge FETs, handled above
        comp = comp_lookup.get(ref, {})
        gate_net = pins.get("gate")
        drain_net = pins.get("drain")
        source_net = pins.get("source")

        # Detect P-channel vs N-channel from lib_id, ki_keywords, and value
        lib_lower = comp.get("lib_id", "").lower()
        val_lower = comp.get("value", "").lower()
        kw_lower = comp.get("keywords", "").lower()
        # Lib_id is most reliable: Q_PMOS_*, PMOS, p-channel in library name
        is_pchannel = any(k in lib_lower for k in
                         ("pmos", "p-channel", "p_channel", "pchannel", "q_pmos"))
        # ki_keywords from lib_symbol (e.g., "P-Channel MOSFET") — very reliable
        if not is_pchannel:
            is_pchannel = "p-channel" in kw_lower or "pchannel" in kw_lower
        # Value-based: only unambiguous P-channel families (DMP is Diodes Inc P-ch)
        # Avoid part number prefixes that span both N/P families (ao34, irf93, si23, etc.)
        if not is_pchannel:
            is_pchannel = any(k in val_lower for k in
                             ("pmos", "p-channel", "p_channel", "pchannel", "dmp"))

        # Gate drive analysis — also check 1-hop through resistor to find
        # gate resistors that connect indirectly (R between IC/signal → gate)
        gate_comps = _get_net_components(gate_net, ref) if gate_net else []
        gate_resistors = [c for c in gate_comps if c["type"] == "resistor"]
        gate_ics = [c for c in gate_comps if c["type"] == "ic"]

        # If no resistors directly on gate net, check 1-hop: gate net connects
        # to a resistor whose other end has an IC or signal source
        if not gate_resistors and gate_net and gate_net in nets:
            gate_pin_count = len(nets[gate_net].get("pins", []))
            if gate_pin_count <= 3:  # Low-fanout gate net
                for gc in gate_comps:
                    if gc["type"] == "resistor":
                        gate_resistors.append(gc)

        gate_pulldown = None
        for gr in gate_resistors:
            # Check if resistor's other pin goes to ground (N-ch) or power (P-ch)
            r_n1, r_n2 = get_two_pin_nets(gr["reference"])
            other_net = r_n2 if r_n1 == gate_net else r_n1
            if is_ground(other_net) or (is_pchannel and is_power_net(other_net)):
                gate_pulldown = {
                    "reference": gr["reference"],
                    "value": gr["value"],
                }
                break

        # Drain load analysis
        drain_comps = _get_net_components(drain_net, ref) if drain_net else []

        # P-channel: source=power, drain=load (high-side switch)
        # N-channel: drain=load/power, source=ground
        if is_pchannel and is_power_net(source_net):
            load_type = _classify_load(drain_net, ref) if drain_net else "unknown"
            if load_type == "other" and drain_net:
                # P-channel with source on power → high-side switch
                load_type = "high_side_switch"
        else:
            load_type = _classify_load(drain_net, ref) if drain_net else "unknown"

        # Flyback diode check: diode with anode on source_net and cathode on drain_net
        # (or vice versa — across drain-source)
        has_flyback = False
        flyback_ref = None
        for dc in drain_comps:
            if dc["type"] == "diode":
                d_n1, d_n2 = get_two_pin_nets(dc["reference"])
                if (d_n1 == source_net and d_n2 == drain_net) or \
                   (d_n1 == drain_net and d_n2 == source_net):
                    has_flyback = True
                    flyback_ref = dc["reference"]
                    break

        # Snubber check: RC across drain-source
        # A real snubber has a dedicated RC mid-node, not a power rail with decoupling caps.
        has_snubber = False
        for dc in drain_comps:
            if dc["type"] == "resistor":
                r_n1, r_n2 = get_two_pin_nets(dc["reference"])
                other = r_n2 if r_n1 == drain_net else r_n1
                # Check if a cap bridges from other to source
                # Exclude power rails as mid-nodes (decoupling caps, not snubbers)
                if other and other != source_net and not is_power_net(other):
                    for sc in _get_net_components(other, dc["reference"]):
                        if sc["type"] == "capacitor":
                            c_n1, c_n2 = get_two_pin_nets(sc["reference"])
                            c_other = c_n2 if c_n1 == other else c_n1
                            if c_other == source_net:
                                has_snubber = True
                                break

        # Source sense resistor
        source_sense = None
        if source_net and not is_ground(source_net):
            source_comps = _get_net_components(source_net, ref)
            for sc in source_comps:
                if sc["type"] == "resistor":
                    r_n1, r_n2 = get_two_pin_nets(sc["reference"])
                    other = r_n2 if r_n1 == source_net else r_n1
                    if is_ground(other):
                        pv = parse_value(sc["value"])
                        if pv is not None and pv <= 1.0:
                            source_sense = {
                                "reference": sc["reference"],
                                "value": sc["value"],
                                "ohms": pv,
                            }
                            break

        circuit = {
            "reference": ref,
            "value": comp.get("value", ""),
            "lib_id": comp.get("lib_id", ""),
            "type": "mosfet",
            "is_pchannel": is_pchannel,
            "gate_net": gate_net,
            "drain_net": drain_net,
            "source_net": source_net,
            "drain_is_power": is_power_net(drain_net) or (is_pchannel and is_power_net(source_net)),
            "source_is_ground": is_ground(source_net),
            "source_is_power": is_power_net(source_net),
            "load_type": load_type,
            "gate_resistors": [{"reference": r["reference"], "value": r["value"]} for r in gate_resistors],
            "gate_driver_ics": [{"reference": ic["reference"], "value": ic["value"]} for ic in gate_ics],
            "gate_pulldown": gate_pulldown,
            "has_flyback_diode": has_flyback,
            "flyback_diode": flyback_ref,
            "has_snubber": has_snubber,
            "source_sense_resistor": source_sense,
        }
        results["transistor_circuits"].append(circuit)

    # Analyze each BJT
    for ref, pins in bjt_pins.items():
        comp = comp_lookup.get(ref, {})
        base_net = pins.get("base")
        collector_net = pins.get("collector")
        emitter_net = pins.get("emitter")

        # Base drive analysis
        base_comps = _get_net_components(base_net, ref) if base_net else []
        base_resistors = [c for c in base_comps if c["type"] == "resistor"]
        base_ics = [c for c in base_comps if c["type"] == "ic"]
        base_pulldown = None
        for br in base_resistors:
            r_n1, r_n2 = get_two_pin_nets(br["reference"])
            other_net = r_n2 if r_n1 == base_net else r_n1
            if is_ground(other_net) or other_net == emitter_net:
                base_pulldown = {
                    "reference": br["reference"],
                    "value": br["value"],
                }
                break

        # Collector load
        load_type = _classify_load(collector_net, ref) if collector_net else "unknown"

        # Emitter resistor (degeneration)
        emitter_resistor = None
        if emitter_net and not is_ground(emitter_net):
            emitter_comps = _get_net_components(emitter_net, ref)
            for ec in emitter_comps:
                if ec["type"] == "resistor":
                    r_n1, r_n2 = get_two_pin_nets(ec["reference"])
                    other = r_n2 if r_n1 == emitter_net else r_n1
                    if is_ground(other):
                        emitter_resistor = {
                            "reference": ec["reference"],
                            "value": ec["value"],
                        }
                        break

        circuit = {
            "reference": ref,
            "value": comp.get("value", ""),
            "lib_id": comp.get("lib_id", ""),
            "type": "bjt",
            "base_net": base_net,
            "collector_net": collector_net,
            "emitter_net": emitter_net,
            "collector_is_power": is_power_net(collector_net),
            "emitter_is_ground": is_ground(emitter_net),
            "load_type": load_type,
            "base_resistors": [{"reference": r["reference"], "value": r["value"]} for r in base_resistors],
            "base_driver_ics": [{"reference": ic["reference"], "value": ic["value"]} for ic in base_ics],
            "base_pulldown": base_pulldown,
            "emitter_resistor": emitter_resistor,
        }
        results["transistor_circuits"].append(circuit)

    # ---- Post-filter: remove voltage dividers on transistor gate/base nets ----
    # Gate pull-down resistors (gate-to-GND) paired with gate series resistors
    # (signal-to-gate) look like voltage dividers but are gate biasing networks.
    # Remove any VD whose mid-point is a known MOSFET gate or BJT base net.
    _gate_base_nets = set()
    for tc in results["transistor_circuits"]:
        if tc["type"] == "mosfet" and tc.get("gate_net"):
            _gate_base_nets.add(tc["gate_net"])
        elif tc["type"] == "bjt" and tc.get("base_net"):
            _gate_base_nets.add(tc["base_net"])
    if _gate_base_nets:
        results["voltage_dividers"] = [
            vd for vd in results["voltage_dividers"]
            if vd["mid_net"] not in _gate_base_nets
        ]
        results["feedback_networks"] = [
            fn for fn in results["feedback_networks"]
            if fn["mid_net"] not in _gate_base_nets
        ]

    # ---- Post-filter: deduplicate voltage dividers by network topology ----
    # When multiple physical resistors form parallel copies of the same logical
    # divider (same top/mid/bottom nets), keep one representative entry.
    # Common in motor controllers with redundant BEMF sensing networks.
    _vd_groups: dict[tuple[str, str, str], list[dict]] = {}
    for vd in results["voltage_dividers"]:
        key = (vd["top_net"], vd["mid_net"], vd["bottom_net"])
        _vd_groups.setdefault(key, []).append(vd)
    deduped_vds: list[dict] = []
    for key, entries in _vd_groups.items():
        # Keep the first entry as representative
        rep = entries[0]
        if len(entries) > 1:
            rep["parallel_count"] = len(entries)
        deduped_vds.append(rep)
    results["voltage_dividers"] = deduped_vds

    # Also deduplicate feedback_networks the same way
    _fn_groups: dict[tuple[str, str, str], list[dict]] = {}
    for fn in results["feedback_networks"]:
        key = (fn["top_net"], fn["mid_net"], fn["bottom_net"])
        _fn_groups.setdefault(key, []).append(fn)
    deduped_fns: list[dict] = []
    for key, entries in _fn_groups.items():
        rep = entries[0]
        if len(entries) > 1:
            rep["parallel_count"] = len(entries)
        deduped_fns.append(rep)
    results["feedback_networks"] = deduped_fns

    # ---- LED Driver Chain Linking ----
    # Enrich transistor circuits: if a transistor's drain/collector connects through
    # a resistor to an LED, record it as a complete LED driver subcircuit.
    for tc in results["transistor_circuits"]:
        is_mosfet = tc.get("type") == "mosfet"
        is_bjt = tc.get("type") == "bjt"
        if not is_mosfet and not is_bjt:
            continue
        load_net = tc.get("drain_net") if is_mosfet else tc.get("collector_net")
        if not load_net:
            continue
        # Look at components on the load net for a resistor
        load_comps = _get_net_components(load_net, tc["reference"])
        for dc in load_comps:
            if dc["type"] != "resistor":
                continue
            # Follow the resistor to its other net
            r_n1, r_n2 = get_two_pin_nets(dc["reference"])
            other_net = r_n2 if r_n1 == load_net else r_n1
            if not other_net or other_net == load_net:
                continue
            # Check if an LED is on that net (type already set by classify_component)
            other_comps = _get_net_components(other_net, dc["reference"])
            for oc in other_comps:
                if oc["type"] == "led":
                    led_comp = comp_lookup.get(oc["reference"], {})
                    # Find what power rail the LED's other pin connects to
                    led_n1, led_n2 = get_two_pin_nets(oc["reference"])
                    led_other = led_n2 if led_n1 == other_net else led_n1
                    led_power = led_other if led_other and is_power_net(led_other) else None
                    tc["led_driver"] = {
                        "led_ref": oc["reference"],
                        "led_value": led_comp.get("value", ""),
                        "current_resistor": dc["reference"],
                        "current_resistor_value": dc.get("value", ""),
                        "power_rail": led_power,
                    }
                    ohms = parsed_values.get(dc["reference"])
                    if ohms and led_power:
                        tc["led_driver"]["resistor_ohms"] = ohms
                    break
            if "led_driver" in tc:
                break

    # ---- Buzzer/Speaker Driver Detection ----
    # Detect patterns: IC/GPIO → (optional resistor) → buzzer/speaker
    # or IC/GPIO → transistor → buzzer/speaker
    results["buzzer_speaker_circuits"] = []
    # Build index: net → transistor circuits that drive it
    tc_by_output_net: dict[str, list[dict]] = {}
    for tc in results["transistor_circuits"]:
        for key in ("drain_net", "collector_net"):
            n = tc.get(key)
            if n:
                tc_by_output_net.setdefault(n, []).append(tc)
    buzzer_speaker_types = ("buzzer", "speaker")
    for comp in components:
        if comp["type"] not in buzzer_speaker_types:
            continue
        ref = comp["reference"]
        # Find signal nets via direct pin lookup (buzzers/speakers are 2-pin)
        n1, n2 = get_two_pin_nets(ref)
        signal_net = None
        for net in (n1, n2):
            if net and not is_ground(net) and not is_power_net(net):
                signal_net = net
                break
        if not signal_net:
            continue
        net_comps = _get_net_components(signal_net, ref)
        driver_ic_ref = None
        series_resistor = None
        has_transistor_driver = False
        for nc in net_comps:
            if nc["type"] == "ic":
                driver_ic_ref = nc["reference"]
            elif nc["type"] == "resistor":
                series_resistor = nc
                # Follow resistor to see if IC is on the other side
                r_n1, r_n2 = get_two_pin_nets(nc["reference"])
                r_other = r_n2 if r_n1 == signal_net else r_n1
                if r_other:
                    for rc in _get_net_components(r_other, nc["reference"]):
                        if rc["type"] == "ic":
                            driver_ic_ref = rc["reference"]
            elif nc["type"] == "transistor":
                has_transistor_driver = True
        # Check indexed transistor circuits for this net
        for tc in tc_by_output_net.get(signal_net, []):
            has_transistor_driver = True
            if not driver_ic_ref and tc.get("gate_driver_ics"):
                driver_ic_ref = tc["gate_driver_ics"][0].get("reference", "")
        entry = {
            "reference": ref,
            "value": comp.get("value", ""),
            "type": comp["type"],
            "signal_net": signal_net,
            "has_transistor_driver": has_transistor_driver,
        }
        if driver_ic_ref:
            entry["driver_ic"] = driver_ic_ref
        if series_resistor:
            entry["series_resistor"] = {
                "reference": series_resistor["reference"],
                "value": series_resistor.get("value", ""),
            }
        if not has_transistor_driver and driver_ic_ref:
            entry["direct_gpio_drive"] = True
        results["buzzer_speaker_circuits"].append(entry)

    # ---- Key Matrix Detection ----
    # Detect keyboard-style switch matrices: diode per key, row/col net naming.
    # Pattern: nets named ROW<N>/COL<N> (or row/col variants), switches and diodes
    # connected in a grid pattern.
    results["key_matrices"] = []
    row_nets = {}
    col_nets = {}
    for net_name in nets:
        nn = net_name.upper().replace("_", "").replace("-", "")
        m_row = re.match(r'^ROW(\d+)$', nn)
        m_col = re.match(r'^COL(\d+)$', nn)
        if not m_row:
            m_row = re.match(r'^ROW(\d+)$', net_name.upper())
        if not m_col:
            m_col = re.match(r'^COL(?:UMN)?(\d+)$', net_name.upper())
        if m_row:
            row_nets[int(m_row.group(1))] = net_name
        elif m_col:
            col_nets[int(m_col.group(1))] = net_name

    if row_nets and col_nets:
        # Count switches and diodes on row/col nets
        switch_count = 0
        diode_count = 0
        for net_name in list(row_nets.values()) + list(col_nets.values()):
            if net_name in nets:
                for p in nets[net_name]["pins"]:
                    comp = comp_lookup.get(p["component"])
                    if comp:
                        if comp["type"] == "switch":
                            switch_count += 1
                        elif comp["type"] == "diode":
                            diode_count += 1
        # Each key has a switch on col + diode on row (or vice versa),
        # so divide by connection count per key
        estimated_keys = max(switch_count, diode_count)
        if estimated_keys > 4:  # minimum viable matrix
            results["key_matrices"].append({
                "rows": len(row_nets),
                "columns": len(col_nets),
                "row_nets": list(row_nets.values()),
                "col_nets": list(col_nets.values()),
                "estimated_keys": estimated_keys,
                "switches_on_matrix": switch_count,
                "diodes_on_matrix": diode_count,
            })

    # ---- Isolation Barrier Detection ----
    # Detect galvanic isolation domains by looking for:
    # 1. Multiple ground domains (GND + GND_ISO, GNDA + GNDB, etc.)
    # 2. Isolation components bridging domains (optocouplers, digital isolators, isolated DC-DC)
    results["isolation_barriers"] = []

    # Find ground domains (include PE/Earth for isolation detection)
    ground_nets = [n for n in nets if is_ground(n)
                   or n.upper() in ("PE", "EARTH", "CHASSIS", "SHIELD")]
    if len(ground_nets) >= 2:
        # Group ground nets into domains
        ground_domains = {}
        for gn in ground_nets:
            gnu = gn.upper()
            # Map PE/Earth/Chassis/Shield to their own domain
            if gnu in ("PE", "EARTH", "CHASSIS", "SHIELD"):
                domain = gnu.lower()
            else:
                # Normalize: strip common prefixes to group related grounds
                domain = gnu.replace("GND", "").replace("_", "").replace("-", "").strip()
                if not domain:
                    domain = "main"
            ground_domains.setdefault(domain, []).append(gn)

        if len(ground_domains) >= 2:
            # Find components that bridge domains (have pins on different ground domains)
            # Also find known isolation component keywords
            iso_keywords = (
                "adum", "iso7", "iso15", "adm268", "adm248",
                "optocoupl", "opto_isolat", "pc817", "tlp",
                "isolated", "isol_dc", "traco", "recom", "murata",
                "dcdc_iso", "r1sx", "am1s", "tmu", "iec",
            )

            isolation_components = []
            for c in components:
                val = (c.get("value", "") + " " + c.get("lib_id", "")).lower()
                if any(k in val for k in iso_keywords) or c["type"] == "optocoupler":
                    isolation_components.append({
                        "reference": c["reference"],
                        "value": c["value"],
                        "type": c["type"],
                        "lib_id": c.get("lib_id", ""),
                    })

            # Map which ground domain each component's pins are on
            ground_domain_map = {}
            for gn in ground_nets:
                domain = gn.upper().replace("GND", "").replace("_", "").replace("-", "").strip()
                if not domain:
                    domain = "main"
                ground_domain_map[gn] = domain

            isolated_power_rails = [
                n for n in nets
                if is_power_net(n) and any(
                    k in n.upper() for k in ("ISO", "ISOL", "_B", "_SEC")
                )
            ]

            # Only report isolation if there's actual evidence of galvanic isolation:
            # - isolation components present (optocouplers, digital isolators)
            # - explicitly isolated power rails (VCC_ISO, etc.)
            # - ground domain names contain "ISO"/"ISOL"
            # This filters out common non-isolated split grounds (GNDPWR, GNDA, etc.)
            has_iso_evidence = (
                isolation_components
                or isolated_power_rails
                or any("ISO" in d.upper() for d in ground_domains if d != "main")
            )
            if has_iso_evidence:
                results["isolation_barriers"].append({
                    "ground_domains": {d: gnets for d, gnets in ground_domains.items()},
                    "isolation_components": isolation_components,
                    "isolated_power_rails": isolated_power_rails,
                })

    # ---- Ethernet / Magnetics Pairing ----
    # Detect Ethernet PHY IC + magnetics transformer + RJ45 connector chains.
    results["ethernet_interfaces"] = []

    eth_phy_keywords = (
        "lan87", "lan91", "lan83", "dp838", "ksz8", "ksz9",
        "rtl81", "rtl83", "rtl88", "w5500", "w5100", "w5200",
        "enc28j60", "enc424", "dm9000", "ip101", "phy",
        "ethernet", "10base", "100base", "1000base",
    )
    magnetics_keywords = (
        "magnetics", "pulse", "transformer", "lan_tr", "rj45_mag",
        "hx1188", "hr601680", "g2406", "h5007",
    )

    eth_phys = []
    eth_magnetics = []
    eth_connectors = []
    seen_eth_refs = set()

    for c in components:
        if c["reference"] in seen_eth_refs:
            continue
        val_lib = (c.get("value", "") + " " + c.get("lib_id", "")).lower()
        if c["type"] == "ic" and any(k in val_lib for k in eth_phy_keywords):
            eth_phys.append(c)
            seen_eth_refs.add(c["reference"])
        elif c["type"] == "transformer" and any(k in val_lib for k in magnetics_keywords):
            eth_magnetics.append(c)
            seen_eth_refs.add(c["reference"])
        elif c["type"] == "connector":
            if any(k in val_lib for k in ("rj45", "8p8c", "ethernet", "magjack")):
                eth_connectors.append(c)
                seen_eth_refs.add(c["reference"])

    if eth_phys:
        for phy in eth_phys:
            results["ethernet_interfaces"].append({
                "phy_reference": phy["reference"],
                "phy_value": phy["value"],
                "phy_lib_id": phy.get("lib_id", ""),
                "magnetics": [
                    {"reference": m["reference"], "value": m["value"]}
                    for m in eth_magnetics
                ],
                "connectors": [
                    {"reference": c["reference"], "value": c["value"]}
                    for c in eth_connectors
                ],
            })

    # ---- Memory Interface Detection ----
    # Detect memory ICs (DDR/SRAM/flash/EEPROM) paired with MCUs/FPGAs.
    # Pattern: memory IC with data/address bus connected to processor.
    results["memory_interfaces"] = []

    memory_keywords = (
        "sram", "dram", "ddr", "sdram", "psram", "flash", "eeprom",
        "w25q", "at25", "mx25", "is62", "is66", "cy62", "as4c",
        "mt41", "mt48", "k4b", "hy57", "is42", "25lc", "24lc",
        "at24", "fram", "fm25", "mb85", "s27k", "hyperram",
        "aps6404", "aps1604", "ly68",  # HyperRAM/OctaSPI PSRAM
    )
    processor_types = ("ic",)  # MCU/FPGA are classified as IC
    processor_keywords = (
        "stm32", "esp32", "rp2040", "atmega", "atsamd", "pic", "nrf5",
        "ice40", "ecp5", "artix", "spartan", "cyclone", "max10",
        "fpga", "mcu", "cortex", "risc",
    )

    memory_ics = []
    processor_ics = []
    seen_mem_refs = set()
    seen_proc_refs = set()
    for c in components:
        val_lib = (c.get("value", "") + " " + c.get("lib_id", "")).lower()
        if c["type"] == "ic":
            if any(k in val_lib for k in memory_keywords):
                if c["reference"] not in seen_mem_refs:
                    memory_ics.append(c)
                    seen_mem_refs.add(c["reference"])
            elif any(k in val_lib for k in processor_keywords):
                if c["reference"] not in seen_proc_refs:
                    processor_ics.append(c)
                    seen_proc_refs.add(c["reference"])

    for mem in memory_ics:
        # Find which processors share nets with this memory
        mem_nets = set()
        for (pref, pnum), (net, _) in pin_net.items():
            if pref == mem["reference"]:
                mem_nets.add(net)

        connected_processors = []
        for proc in processor_ics:
            proc_nets = set()
            for (pref, pnum), (net, _) in pin_net.items():
                if pref == proc["reference"]:
                    proc_nets.add(net)
            shared = mem_nets & proc_nets
            # Filter out power/ground shared nets
            signal_shared = [n for n in shared if not is_power_net(n) and not is_ground(n)]
            if signal_shared:
                connected_processors.append({
                    "reference": proc["reference"],
                    "value": proc["value"],
                    "shared_signal_nets": len(signal_shared),
                })

        if connected_processors:
            results["memory_interfaces"].append({
                "memory_reference": mem["reference"],
                "memory_value": mem["value"],
                "memory_lib_id": mem.get("lib_id", ""),
                "connected_processors": connected_processors,
                "total_pins": len(mem_nets),
            })

    # ---- RF Signal Chain Detection ----
    # Detect RF switches, mixers, LNAs, amplifiers, filters, and baluns.
    # Pattern: RF switch/mixer/amplifier ICs interconnected via signal nets + balun transformers.
    results["rf_chains"] = []

    rf_switch_keywords = (
        "sky134", "sky133", "sky131", "pe42", "as179", "as193",
        "hmc19", "hmc54", "hmc34", "bgrf", "rfsw", "spdt", "sp3t", "sp4t",
    )
    rf_mixer_keywords = (
        "rffc50", "ltc5549", "lt5560", "hmc21", "sa612", "ade-", "tuf-",
        "mixer",
    )
    rf_amp_keywords = (
        "mga-", "bga-", "maal", "pga-", "gali-", "maa-", "bfp7", "bfr5",
        "hmc58", "hmc31", "lna", "mmic",
    )
    rf_transceiver_keywords = (
        "max283", "at86rf", "cc1101", "cc2500", "sx127", "sx126",
        "rfm9", "rfm6", "nrf24", "si446",
    )
    rf_filter_keywords = (
        "saw", "baw", "fbar", "highpass", "lowpass", "bandpass",
        "fil-", "sf2", "ta0", "b39",
    )

    rf_switches = []
    rf_mixers = []
    rf_amplifiers = []
    rf_transceivers = []
    rf_filters = []
    rf_baluns = []
    seen_rf_refs = set()

    for c in components:
        if c["reference"] in seen_rf_refs:
            continue
        val_lib = (c.get("value", "") + " " + c.get("lib_id", "")).lower()

        if c["type"] == "ic":
            if any(k in val_lib for k in rf_switch_keywords):
                rf_switches.append(c)
                seen_rf_refs.add(c["reference"])
            elif any(k in val_lib for k in rf_mixer_keywords):
                rf_mixers.append(c)
                seen_rf_refs.add(c["reference"])
            elif any(k in val_lib for k in rf_amp_keywords):
                rf_amplifiers.append(c)
                seen_rf_refs.add(c["reference"])
            elif any(k in val_lib for k in rf_transceiver_keywords):
                rf_transceivers.append(c)
                seen_rf_refs.add(c["reference"])
            elif any(k in val_lib for k in rf_filter_keywords):
                rf_filters.append(c)
                seen_rf_refs.add(c["reference"])
        elif c["type"] == "transformer":
            if any(k in val_lib for k in ("balun", "bal-", "b0310", "bl14")):
                rf_baluns.append(c)
                seen_rf_refs.add(c["reference"])

    rf_component_count = (
        len(rf_switches) + len(rf_mixers) + len(rf_amplifiers)
        + len(rf_transceivers) + len(rf_filters) + len(rf_baluns)
    )

    if rf_component_count >= 2:
        # Build interconnect map: which RF parts share signal nets
        all_rf_refs = seen_rf_refs.copy()
        rf_nets_map = {}  # ref -> set of signal nets
        for ref in all_rf_refs:
            ref_nets = set()
            for (pref, pnum), (net, _) in pin_net.items():
                if pref == ref and net and not is_power_net(net) and not is_ground(net):
                    ref_nets.add(net)
            rf_nets_map[ref] = ref_nets

        # Find signal path connections between RF parts
        connections = []
        rf_ref_list = sorted(all_rf_refs)
        for i, ref_a in enumerate(rf_ref_list):
            for ref_b in rf_ref_list[i+1:]:
                shared = rf_nets_map.get(ref_a, set()) & rf_nets_map.get(ref_b, set())
                signal_shared = [n for n in shared if not n.startswith("__unnamed_")]
                if shared:
                    connections.append({
                        "from": ref_a,
                        "to": ref_b,
                        "shared_nets": len(shared),
                        "named_nets": signal_shared,
                    })

        def _rf_role(ref):
            comp = comp_lookup.get(ref)
            if not comp:
                return "unknown"
            val_lib = (comp.get("value", "") + " " + comp.get("lib_id", "")).lower()
            if any(k in val_lib for k in rf_switch_keywords):
                return "switch"
            if any(k in val_lib for k in rf_mixer_keywords):
                return "mixer"
            if any(k in val_lib for k in rf_amp_keywords):
                return "amplifier"
            if any(k in val_lib for k in rf_transceiver_keywords):
                return "transceiver"
            if any(k in val_lib for k in rf_filter_keywords):
                return "filter"
            if comp["type"] == "transformer":
                return "balun"
            return "unknown"

        results["rf_chains"].append({
            "switches": [
                {"reference": c["reference"], "value": c["value"],
                 "lib_id": c.get("lib_id", "")}
                for c in rf_switches
            ],
            "mixers": [
                {"reference": c["reference"], "value": c["value"],
                 "lib_id": c.get("lib_id", "")}
                for c in rf_mixers
            ],
            "amplifiers": [
                {"reference": c["reference"], "value": c["value"],
                 "lib_id": c.get("lib_id", "")}
                for c in rf_amplifiers
            ],
            "transceivers": [
                {"reference": c["reference"], "value": c["value"],
                 "lib_id": c.get("lib_id", "")}
                for c in rf_transceivers
            ],
            "filters": [
                {"reference": c["reference"], "value": c["value"],
                 "lib_id": c.get("lib_id", "")}
                for c in rf_filters
            ],
            "baluns": [
                {"reference": c["reference"], "value": c["value"],
                 "lib_id": c.get("lib_id", "")}
                for c in rf_baluns
            ],
            "total_rf_components": rf_component_count,
            "connections": connections,
            "component_roles": {
                ref: _rf_role(ref) for ref in all_rf_refs
            },
        })

    # ---- BMS Cell Monitoring Detection ----
    # Detect Battery Management System ICs with cell voltage monitoring.
    # Pattern: BMS IC with VCn cell voltage pins, balance resistors, charge/discharge FETs, NTCs.
    results["bms_systems"] = []

    bms_ic_keywords = (
        "bq769", "bq76920", "bq76930", "bq76940", "bq76952", "bq7694",
        "ltc681", "ltc682", "ltc683", "ltc680",
        "isl9420", "isl9421", "max1726", "max1730",
        "afe", "ip5189", "ip5306", "tp4056", "mp2639",
    )

    bms_ics = []
    seen_bms_refs = set()
    for c in components:
        if c["reference"] in seen_bms_refs:
            continue
        val_lib = (c.get("value", "") + " " + c.get("lib_id", "")).lower()
        if c["type"] == "ic" and any(k in val_lib for k in bms_ic_keywords):
            bms_ics.append(c)
            seen_bms_refs.add(c["reference"])

    for bms_ic in bms_ics:
        ref = bms_ic["reference"]

        # Find cell voltage pins (VCn, CELLn) on the BMS IC
        cell_pins = []
        bms_nets = set()
        for (pref, pnum), (net, _) in pin_net.items():
            if pref == ref:
                bms_nets.add(net)
                if net:
                    nn = net.upper()
                    if re.match(r'^VC\d+$', nn) or re.match(r'^CELL\d+', nn):
                        cell_pins.append({"pin": pnum, "net": net})

        # Detect cell count from VC/CELL net numbering
        cell_numbers = set()
        for cp in cell_pins:
            m = re.match(r'^VC(\d+)$', cp["net"].upper())
            if m:
                cell_numbers.add(int(m.group(1)))
            m = re.match(r'^CELL(\d+)', cp["net"].upper())
            if m:
                cell_numbers.add(int(m.group(1)))

        # Find balance resistors: resistors on cell voltage nets
        balance_resistors = []
        cell_net_names = {cp["net"] for cp in cell_pins}
        for net_name in cell_net_names:
            if net_name not in nets:
                continue
            for p in nets[net_name]["pins"]:
                comp = comp_lookup.get(p["component"])
                if comp and comp["type"] == "resistor" and p["component"] != ref:
                    val = parse_value(comp.get("value", ""))
                    balance_resistors.append({
                        "reference": p["component"],
                        "value": comp["value"],
                        "cell_net": net_name,
                    })

        # Find charge/discharge FETs on the battery power path.
        # BMS designs have power FETs on BAT+/BAT-/PACK+/PACK-/CHG+/DSG+ nets.
        # The BMS IC controls gates indirectly through driver circuits.
        chg_dsg_fets = []
        seen_fet_refs = set()
        power_path_keywords = ("BAT+", "BAT-", "PACK+", "PACK-", "CHG+", "DSG+",
                               "BATT+", "BATT-", "VBAT+", "VBAT-")
        for net_name in nets:
            if net_name.upper() not in power_path_keywords:
                continue
            for p in nets[net_name]["pins"]:
                comp = comp_lookup.get(p["component"])
                if (comp and comp["type"] == "transistor"
                        and p["component"] not in seen_fet_refs):
                    chg_dsg_fets.append({
                        "reference": p["component"],
                        "value": comp["value"],
                        "power_net": net_name,
                    })
                    seen_fet_refs.add(p["component"])

        # Find NTC thermistors connected to BMS IC
        ntc_sensors = []
        for net_name in bms_nets:
            if not net_name or net_name not in nets:
                continue
            for p in nets[net_name]["pins"]:
                comp = comp_lookup.get(p["component"])
                if comp and comp["type"] == "thermistor":
                    ntc_sensors.append({
                        "reference": p["component"],
                        "value": comp["value"],
                        "net": net_name,
                    })

        # Deduplicate NTCs by reference
        seen_ntc = set()
        unique_ntcs = []
        for ntc in ntc_sensors:
            if ntc["reference"] not in seen_ntc:
                unique_ntcs.append(ntc)
                seen_ntc.add(ntc["reference"])

        cell_count = max(cell_numbers) if cell_numbers else 0

        results["bms_systems"].append({
            "bms_reference": ref,
            "bms_value": bms_ic["value"],
            "bms_lib_id": bms_ic.get("lib_id", ""),
            "cell_voltage_pins": len(cell_pins),
            "cell_count": cell_count,
            "cell_nets": sorted(cell_net_names),
            "balance_resistors": len(balance_resistors),
            "charge_discharge_fets": chg_dsg_fets,
            "ntc_sensors": unique_ntcs,
        })

    # ---- Design Review Observations ----
    # Structured facts about the design for higher-level analysis.
    # These are observations, not judgments — the consuming agent (Claude) applies
    # context from datasheets and design intent to determine actual issues.
    results["design_observations"] = []

    # Build helper sets
    decoupled_rails = {d["rail"] for d in results.get("decoupling_analysis", [])}
    connector_nets = set()
    for net_name, net_info in nets.items():
        for p in net_info["pins"]:
            comp = comp_lookup.get(p["component"])
            if comp and comp["type"] in ("connector", "test_point"):
                connector_nets.add(net_name)
    protected_nets = {p["protected_net"] for p in results.get("protection_devices", [])}

    # 1. IC power pin decoupling status
    for ic in [c for c in components if c["type"] == "ic"]:
        ref = ic["reference"]
        ic_power_nets = set()
        for (pref, pnum), (net, _) in pin_net.items():
            if pref != ref:
                continue
            if net and is_power_net(net) and not is_ground(net):
                ic_power_nets.add(net)
        undecoupled = [r for r in ic_power_nets if r not in decoupled_rails]
        if undecoupled:
            results["design_observations"].append({
                "category": "decoupling",
                "component": ref,
                "value": ic["value"],
                "rails_without_caps": undecoupled,
                "rails_with_caps": [r for r in ic_power_nets if r in decoupled_rails],
            })

    # 2. Regulator capacitor status
    for reg in results.get("power_regulators", []):
        in_rail = reg.get("input_rail")
        out_rail = reg.get("output_rail")
        missing = {}
        if in_rail and in_rail not in decoupled_rails:
            missing["input"] = in_rail
        if out_rail and out_rail not in decoupled_rails:
            missing["output"] = out_rail
        if missing:
            results["design_observations"].append({
                "category": "regulator_caps",
                "component": reg["ref"],
                "value": reg["value"],
                "topology": reg.get("topology"),
                "missing_caps": missing,
            })

    # 3. Single-pin signal nets (not connected to connectors, not power/ground, not GPIO)
    single_pin_nets = []
    for net_name, net_info in nets.items():
        if net_name.startswith("__unnamed_"):
            continue
        if is_power_net(net_name) or is_ground(net_name):
            continue
        if net_name in connector_nets:
            continue
        real_pins = [p for p in net_info["pins"] if not p["component"].startswith("#")]
        if len(real_pins) == 1:
            p = real_pins[0]
            comp = comp_lookup.get(p["component"])
            if comp and comp["type"] == "ic":
                pin_name = p.get("pin_name", p["pin_number"])
                pn_upper = pin_name.upper()
                if re.match(r'^P[A-K]\d', pn_upper) or re.match(r'^GPIO', pn_upper):
                    continue
                single_pin_nets.append({
                    "component": p["component"],
                    "pin": pin_name,
                    "net": net_name,
                })
    if single_pin_nets:
        results["design_observations"].append({
            "category": "single_pin_nets",
            "count": len(single_pin_nets),
            "nets": single_pin_nets,
        })

    # 4. I2C bus pull-up status
    for net_name, net_info in nets.items():
        nn = net_name.upper()
        # Match I2C nets: SDA/SCL as standalone or with I2C prefix, but not SPI SCLK
        is_sda = bool(re.search(r'\bSDA\b', nn) or re.search(r'I2C.*SDA|SDA.*I2C', nn))
        is_scl = bool(re.search(r'\bSCL\b', nn) or re.search(r'I2C.*SCL|SCL.*I2C', nn))
        # Exclude SPI clock (SCLK, SCK) which contains "SCL" as substring
        if "SCLK" in nn or "SCK" in nn:
            is_scl = False
        if not (is_sda or is_scl):
            continue
        line = "SDA" if is_sda else "SCL"
        has_pullup = False
        pullup_ref = None
        pullup_to = None
        for p in net_info["pins"]:
            comp = comp_lookup.get(p["component"])
            if comp and comp["type"] == "resistor":
                r_n1, r_n2 = get_two_pin_nets(p["component"])
                other = r_n2 if r_n1 == net_name else r_n1
                if other and is_power_net(other):
                    has_pullup = True
                    pullup_ref = p["component"]
                    pullup_to = other
                    break
        ic_refs = [p["component"] for p in net_info["pins"]
                   if comp_lookup.get(p["component"], {}).get("type") == "ic"]
        if ic_refs:
            results["design_observations"].append({
                "category": "i2c_bus",
                "net": net_name,
                "line": line,
                "devices": ic_refs,
                "has_pullup": has_pullup,
                "pullup_resistor": pullup_ref,
                "pullup_rail": pullup_to,
            })

    # 5. Reset pin configuration
    for ic in [c for c in components if c["type"] == "ic"]:
        ref = ic["reference"]
        for (pref, pnum), (net, _) in pin_net.items():
            if pref != ref or not net or net.startswith("__unnamed_"):
                continue
            pin_name = ""
            if net in nets:
                for p in nets[net]["pins"]:
                    if p["component"] == ref and p["pin_number"] == pnum:
                        pin_name = p.get("pin_name", "").upper()
                        break
            if pin_name not in ("NRST", "~{RESET}", "RESET", "~{RST}", "RST", "~{NRST}", "MCLR", "~{MCLR}"):
                continue
            has_resistor = False
            has_capacitor = False
            connected_to = []
            if net in nets:
                for p in nets[net]["pins"]:
                    comp = comp_lookup.get(p["component"])
                    if not comp or p["component"] == ref:
                        continue
                    if comp["type"] == "resistor":
                        has_resistor = True
                    elif comp["type"] == "capacitor":
                        has_capacitor = True
                    connected_to.append({"ref": p["component"], "type": comp["type"]})
            results["design_observations"].append({
                "category": "reset_pin",
                "component": ref,
                "value": ic["value"],
                "pin": pin_name,
                "net": net,
                "has_pullup": has_resistor,
                "has_filter_cap": has_capacitor,
                "connected_components": connected_to,
            })

    # 6. Regulator feedback voltage estimation
    for reg in results.get("power_regulators", []):
        if "estimated_vout" in reg:
            obs = {
                "category": "regulator_voltage",
                "component": reg["ref"],
                "value": reg["value"],
                "topology": reg.get("topology"),
                "estimated_vout": reg["estimated_vout"],
                "assumed_vref": reg.get("assumed_vref"),
                "vref_source": reg.get("vref_source", "heuristic"),
                "feedback_divider": reg.get("feedback_divider"),
                "input_rail": reg.get("input_rail"),
                "output_rail": reg.get("output_rail"),
            }
            # Cross-check estimated Vout against the output rail net name
            out_rail = reg.get("output_rail", "")
            rail_v = _parse_voltage_from_net_name(out_rail)
            if rail_v is not None and reg["estimated_vout"] > 0:
                pct_diff = abs(reg["estimated_vout"] - rail_v) / rail_v
                if pct_diff > 0.15:
                    obs["vout_net_mismatch"] = {
                        "net_name": out_rail,
                        "net_voltage": rail_v,
                        "estimated_vout": reg["estimated_vout"],
                        "percent_diff": round(pct_diff * 100, 1),
                    }
            results["design_observations"].append(obs)

    # 7. Switching regulator bootstrap status
    for reg in results.get("power_regulators", []):
        if reg.get("topology") == "switching" and reg.get("inductor"):
            results["design_observations"].append({
                "category": "switching_regulator",
                "component": reg["ref"],
                "value": reg["value"],
                "inductor": reg.get("inductor"),
                "has_bootstrap": reg.get("has_bootstrap", False),
                "input_rail": reg.get("input_rail"),
                "output_rail": reg.get("output_rail"),
            })

    # 8. USB data line protection status
    for net_name in nets:
        nn = net_name.upper()
        is_usb = any(x in nn for x in ("USB_D", "USBDP", "USBDM", "USB_DP", "USB_DM"))
        if not is_usb and nn in ("D+", "D-", "DP", "DM"):
            # Confirm USB context
            if net_name in nets:
                for p in nets[net_name]["pins"]:
                    comp = comp_lookup.get(p["component"])
                    if comp:
                        cv = (comp.get("value", "") + " " + comp.get("lib_id", "")).upper()
                        if "USB" in cv:
                            is_usb = True
                            break
        if is_usb:
            results["design_observations"].append({
                "category": "usb_data",
                "net": net_name,
                "has_esd_protection": net_name in protected_nets,
                "devices": [p["component"] for p in nets[net_name]["pins"]
                           if not comp_lookup.get(p["component"], {}).get("type") in (None,)],
            })

    # 9. Crystal load capacitance
    for xtal in results.get("crystal_circuits", []):
        if "effective_load_pF" in xtal:
            results["design_observations"].append({
                "category": "crystal",
                "component": xtal["reference"],
                "value": xtal.get("value"),
                "effective_load_pF": xtal["effective_load_pF"],
                "load_caps": xtal.get("load_caps", []),
                "in_typical_range": 4 <= xtal["effective_load_pF"] <= 30,
            })

    # 10. Decoupling frequency coverage per rail
    for decoup in results.get("decoupling_analysis", []):
        caps = decoup.get("capacitors", [])
        farads_list = [c.get("farads", 0) for c in caps]
        has_bulk = any(f >= 1e-6 for f in farads_list)
        has_bypass = any(10e-9 <= f <= 1e-6 for f in farads_list)
        has_hf = any(f < 10e-9 for f in farads_list)
        results["design_observations"].append({
            "category": "decoupling_coverage",
            "rail": decoup["rail"],
            "cap_count": len(caps),
            "total_uF": decoup.get("total_capacitance_uF"),
            "has_bulk": has_bulk,
            "has_bypass": has_bypass,
            "has_high_freq": has_hf,
        })

    return results


def extract_wires(root: list) -> list[dict]:
    """Extract all wire segments."""
    wires = []
    for wire in find_all(root, "wire"):
        pts = find_first(wire, "pts")
        if not pts:
            continue
        xys = find_all(pts, "xy")
        if len(xys) >= 2:
            wires.append({
                "x1": float(xys[0][1]), "y1": float(xys[0][2]),
                "x2": float(xys[1][1]), "y2": float(xys[1][2]),
            })
    return wires


def extract_labels(root: list) -> list[dict]:
    """Extract all labels (local, global, hierarchical)."""
    labels = []

    for label_type in ["label", "global_label", "hierarchical_label"]:
        for lbl in find_all(root, label_type):
            name = lbl[1] if len(lbl) > 1 else ""
            at = get_at(lbl)
            x, y, angle = at if at else (0, 0, 0)
            # Shape field exists on global_label and hierarchical_label
            # Values: input, output, bidirectional, tri_state, passive
            shape = get_value(lbl, "shape") or ""
            entry = {
                "name": name,
                "type": label_type,
                "x": round(x, 4),
                "y": round(y, 4),
                "angle": angle,
            }
            if shape:
                entry["shape"] = shape
            labels.append(entry)

    return labels


def extract_power_symbols(components: list[dict]) -> list[dict]:
    """Extract power symbols from the component list (they define net names).

    Uses the computed pin positions (not the symbol placement point) so that
    power symbols connect to the correct wire endpoints in the net map.
    """
    power = []
    for comp in components:
        if comp["type"] == "power_symbol":
            # Use pin position if available (more accurate), fall back to symbol position
            pins = comp.get("pins", [])
            if pins:
                # Power symbols typically have one pin — use its position
                px, py = pins[0]["x"], pins[0]["y"]
            else:
                px, py = comp["x"], comp["y"]
            power.append({
                "net_name": comp["value"],
                "x": px,
                "y": py,
                "lib_id": comp["lib_id"],
                "_sheet": comp.get("_sheet", 0),
            })
    return power


def extract_junctions(root: list) -> list[dict]:
    """Extract junction points."""
    junctions = []
    for junc in find_all(root, "junction"):
        at = get_at(junc)
        if at:
            junctions.append({"x": round(at[0], 4), "y": round(at[1], 4)})
    return junctions


def extract_no_connects(root: list) -> list[dict]:
    """Extract no-connect markers."""
    ncs = []
    for nc in find_all(root, "no_connect"):
        at = get_at(nc)
        if at:
            ncs.append({"x": round(at[0], 4), "y": round(at[1], 4)})
    return ncs


def extract_text_annotations(root: list) -> list[dict]:
    """Extract text annotations (non-electrical notes placed on the schematic).

    These are designer notes, TODO comments, revision annotations, etc. placed
    on the schematic sheet as free text objects.
    """
    texts = []
    for txt in find_all(root, "text"):
        content = txt[1] if len(txt) > 1 and isinstance(txt[1], str) else ""
        if not content:
            continue
        at = get_at(txt)
        x, y, angle = at if at else (0, 0, 0)
        texts.append({
            "text": content,
            "x": round(x, 4),
            "y": round(y, 4),
            "angle": angle,
        })
    return texts


def extract_bus_elements(root: list) -> dict:
    """Extract bus wires, bus entries, and bus aliases.

    Buses in KiCad group related signals (e.g., D[0..7]) into a single
    graphical wire. Bus entries connect individual signals to/from the bus.
    Bus aliases define named groups of signals.
    """
    buses = []
    for bus in find_all(root, "bus"):
        pts = find_first(bus, "pts")
        if pts:
            xys = find_all(pts, "xy")
            if len(xys) >= 2:
                buses.append({
                    "x1": float(xys[0][1]), "y1": float(xys[0][2]),
                    "x2": float(xys[1][1]), "y2": float(xys[1][2]),
                })

    bus_entries = []
    for entry in find_all(root, "bus_entry"):
        at = get_at(entry)
        if at:
            size = find_first(entry, "size")
            dx = float(size[1]) if size and len(size) > 1 else 0
            dy = float(size[2]) if size and len(size) > 2 else 0
            bus_entries.append({
                "x": round(at[0], 4), "y": round(at[1], 4),
                "dx": dx, "dy": dy,
            })

    bus_aliases = []
    for alias in find_all(root, "bus_alias"):
        name = alias[1] if len(alias) > 1 and isinstance(alias[1], str) else ""
        members_node = find_first(alias, "members")
        members = []
        if members_node:
            members = [m for m in members_node[1:] if isinstance(m, str)]
        if name:
            bus_aliases.append({"name": name, "members": members})

    return {
        "bus_wires": buses,
        "bus_entries": bus_entries,
        "bus_aliases": bus_aliases,
    }


def extract_title_block(root: list) -> dict:
    """Extract title block metadata (title, date, revision, company, comments).

    The title block is stored in a (title_block ...) node at the top level
    of each schematic sheet.
    """
    tb = find_first(root, "title_block")
    if not tb:
        return {}

    result = {}
    for field in ("title", "date", "rev", "company"):
        val = get_value(tb, field)
        if val:
            result[field] = val

    # Comments are numbered: (comment 1 "text"), (comment 2 "text"), ...
    for child in tb:
        if isinstance(child, list) and len(child) >= 3 and child[0] == "comment":
            try:
                num = int(child[1])
                text = child[2] if isinstance(child[2], str) else ""
                if text:
                    result[f"comment_{num}"] = text
            except (ValueError, TypeError):
                pass

    return result


def build_net_map(components: list[dict], wires: list[dict], labels: list[dict],
                  power_symbols: list[dict], junctions: list[dict]) -> dict:
    """Build a connectivity map using union-find on coordinates.

    Groups all electrically connected points into nets, then names them
    from labels and power symbols.
    """
    EPSILON = COORD_EPSILON

    # Collect all electrical points
    # Each point: (sheet, x, y, source_info)
    # The sheet index keeps each sheet's coordinate space separate so that
    # wires on different sheets at the same (x,y) don't falsely merge.
    parent = {}
    point_info = {}  # key -> list of info dicts

    def key(x, y, sheet=0):
        return (sheet, round(x / EPSILON) * EPSILON, round(y / EPSILON) * EPSILON)

    def find(p):
        while parent.get(p, p) != p:
            parent[p] = parent.get(parent[p], parent[p])
            p = parent[p]
        return p

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    def add_point(x, y, info, sheet=0):
        k = key(x, y, sheet)
        if k not in parent:
            parent[k] = k
        point_info.setdefault(k, []).append(info)
        return k

    # Add component pins (skip PWR_FLAG — it's an ERC marker, not a real connection)
    for comp in components:
        if comp.get("value") == "PWR_FLAG" or comp.get("type") == "power_flag":
            continue
        sheet = comp.get("_sheet", 0)
        for pin in comp.get("pins", []):
            add_point(pin["x"], pin["y"], {
                "source": "pin",
                "component": comp["reference"],
                "pin_number": pin["number"],
                "pin_name": pin["name"],
                "pin_type": pin["type"],
            }, sheet)

    # Add wire endpoints and union them.
    # Also build a list of wire segments so we can detect points that land
    # mid-wire (labels, pins, junctions, power symbols placed on a wire
    # between its endpoints).
    wire_segments = []  # list of (k1, k2, x1, y1, x2, y2, sheet)
    # Spatial grid index for fast wire segment lookup — avoids O(W*P) scans.
    # Grid cell size of 5mm captures typical KiCad schematic wire lengths.
    _WIRE_GRID_SIZE = 5.0
    wire_grid: dict[tuple, list[int]] = {}  # (sheet, gx, gy) -> [index into wire_segments]

    for wire in wires:
        sheet = wire.get("_sheet", 0)
        k1 = add_point(wire["x1"], wire["y1"], {"source": "wire"}, sheet)
        k2 = add_point(wire["x2"], wire["y2"], {"source": "wire"}, sheet)
        union(k1, k2)
        idx = len(wire_segments)
        wire_segments.append((k1, k2, wire["x1"], wire["y1"], wire["x2"], wire["y2"], sheet))
        # Index this segment in all grid cells its bounding box overlaps
        min_x, max_x = min(wire["x1"], wire["x2"]), max(wire["x1"], wire["x2"])
        min_y, max_y = min(wire["y1"], wire["y2"]), max(wire["y1"], wire["y2"])
        gx0 = int(min_x // _WIRE_GRID_SIZE)
        gx1 = int(max_x // _WIRE_GRID_SIZE)
        gy0 = int(min_y // _WIRE_GRID_SIZE)
        gy1 = int(max_y // _WIRE_GRID_SIZE)
        for gx in range(gx0, gx1 + 1):
            for gy in range(gy0, gy1 + 1):
                wire_grid.setdefault((sheet, gx, gy), []).append(idx)

    def point_on_segment(px, py, x1, y1, x2, y2):
        """Check if point (px,py) lies on the wire segment (x1,y1)-(x2,y2)."""
        # Quick bounding box check with tolerance
        tol = 0.05
        if px < min(x1, x2) - tol or px > max(x1, x2) + tol:
            return False
        if py < min(y1, y2) - tol or py > max(y1, y2) + tol:
            return False
        # Cross product to check collinearity
        cross = (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)
        seg_len_sq = (x2 - x1) ** 2 + (y2 - y1) ** 2
        if seg_len_sq < tol * tol:
            return False
        # Distance from point to line, squared
        if abs(cross) / (seg_len_sq ** 0.5) > tol:
            return False
        return True

    def union_with_overlapping_wires(k, px, py, sheet=0):
        """Union point k with any wire segment it lies on (same sheet only)."""
        gx = int(px // _WIRE_GRID_SIZE)
        gy = int(py // _WIRE_GRID_SIZE)
        candidates = wire_grid.get((sheet, gx, gy), ())
        for idx in candidates:
            wk1, wk2, wx1, wy1, wx2, wy2, ws = wire_segments[idx]
            if point_on_segment(px, py, wx1, wy1, wx2, wy2):
                union(k, wk1)
                return  # one match is enough since wire endpoints are already unioned

    # Add labels — in KiCad, labels can be placed anywhere on a wire,
    # not just at endpoints, so we must check for mid-wire placement.
    label_keys: dict[str, list] = {}  # label_name -> list of coordinate keys
    for lbl in labels:
        sheet = lbl.get("_sheet", 0)
        k = add_point(lbl["x"], lbl["y"], {
            "source": "label",
            "name": lbl["name"],
            "label_type": lbl["type"],
        }, sheet)
        # Only global labels and power symbols connect across sheets.
        # Local labels only connect within the same sheet (handled by wire union).
        if lbl["type"] in ("global_label", "hierarchical_label"):
            label_keys.setdefault(lbl["name"], []).append(k)
        else:
            # Local labels: union same-name labels within this sheet only
            local_key = (lbl["name"], sheet)
            label_keys.setdefault(local_key, []).append(k)
        union_with_overlapping_wires(k, lbl["x"], lbl["y"], sheet)

    # Add power symbols — compute actual pin position from lib symbol.
    # PWR_FLAG is a DRC-only marker (tells ERC a net has a power source).
    # It doesn't create real connectivity, so exclude it entirely.
    for ps in power_symbols:
        if ps["net_name"] == "PWR_FLAG":
            continue
        sheet = ps.get("_sheet", 0)
        k = add_point(ps["x"], ps["y"], {
            "source": "power_symbol",
            "net_name": ps["net_name"],
        }, sheet)
        # Power symbols always connect across sheets (they define global nets)
        label_keys.setdefault(ps["net_name"], []).append(k)
        union_with_overlapping_wires(k, ps["x"], ps["y"], sheet)

    # Union global/hierarchical labels and power symbols with the same name.
    # This is what connects nets across different parts of the schematic.
    for lbl_name, keys in label_keys.items():
        for j in range(1, len(keys)):
            union(keys[0], keys[j])

    # Add junctions — also check mid-wire placement
    for junc in junctions:
        sheet = junc.get("_sheet", 0)
        k = add_point(junc["x"], junc["y"], {"source": "junction"}, sheet)
        union_with_overlapping_wires(k, junc["x"], junc["y"], sheet)

    # Union component pins that land mid-wire (rare but possible)
    for comp in components:
        if comp.get("value") == "PWR_FLAG" or comp.get("type") == "power_flag":
            continue
        sheet = comp.get("_sheet", 0)
        for pin in comp.get("pins", []):
            k = key(pin["x"], pin["y"], sheet)
            if k in parent:
                union_with_overlapping_wires(k, pin["x"], pin["y"], sheet)

    # Build net groups
    net_groups: dict[tuple, list[tuple]] = {}
    for k in parent:
        root_k = find(k)
        net_groups.setdefault(root_k, []).append(k)

    # Name the nets
    nets = {}
    net_id = 0
    for root_k, members in net_groups.items():
        # Collect all info for this net
        all_info = []
        for m in members:
            all_info.extend(point_info.get(m, []))

        # Find net name from labels or power symbols
        net_name = None
        for info in all_info:
            if info["source"] == "power_symbol":
                net_name = info["net_name"]
                break
            if info["source"] == "label":
                net_name = info["name"]

        if net_name is None:
            # Only create unnamed nets if they have component pins
            has_pins = any(i["source"] == "pin" for i in all_info)
            if not has_pins:
                continue
            net_name = f"__unnamed_{net_id}"
            net_id += 1

        # Collect pin connections
        pin_connections = []
        for info in all_info:
            if info["source"] == "pin":
                pin_connections.append({
                    "component": info["component"],
                    "pin_number": info["pin_number"],
                    "pin_name": info["pin_name"],
                    "pin_type": info["pin_type"],
                })

        # Keep nets that have pin connections, OR named nets (from labels/power symbols)
        # even without pins — this supports legacy files where pin positions aren't available
        if pin_connections or not net_name.startswith("__unnamed_"):
            if net_name in nets:
                # Merge into existing net (can happen when a local label shares a
                # name with a power symbol or global label on a disconnected wire
                # network — e.g., a "GND" label on a connector that isn't wired
                # to the main GND power symbol network).
                nets[net_name]["pins"].extend(pin_connections)
                nets[net_name]["point_count"] += len(members)
            else:
                nets[net_name] = {
                    "name": net_name,
                    "pins": pin_connections,
                    "point_count": len(members),
                }

    return nets


def generate_bom(components: list[dict]) -> list[dict]:
    """Generate grouped BOM from components."""
    groups: dict[tuple, dict] = {}

    # Deduplicate multi-unit symbols — only count each reference once
    seen_refs = set()

    for comp in components:
        if comp["type"] in ("power_symbol", "power_flag", "flag"):
            continue
        if not comp["in_bom"]:
            continue
        if comp["reference"] in seen_refs:
            continue
        seen_refs.add(comp["reference"])

        # Group key: value + footprint + MPN (or just value + footprint if no MPN)
        group_key = (comp["value"], comp["footprint"], comp["mpn"])

        if group_key not in groups:
            groups[group_key] = {
                "value": comp["value"],
                "footprint": comp["footprint"],
                "mpn": comp["mpn"],
                "manufacturer": comp["manufacturer"],
                "digikey": comp["digikey"],
                "mouser": comp["mouser"],
                "lcsc": comp["lcsc"],
                "element14": comp["element14"],
                "datasheet": comp["datasheet"],
                "description": comp["description"],
                "references": [],
                "quantity": 0,
                "dnp": comp["dnp"],
                "type": comp["type"],
            }

        groups[group_key]["references"].append(comp["reference"])
        groups[group_key]["quantity"] += 1

    # Sort by reference
    bom = sorted(groups.values(), key=lambda g: g["references"][0] if g["references"] else "")
    return bom


def compute_statistics(components: list[dict], nets: dict, bom: list[dict],
                       wires: list[dict], no_connects: list[dict]) -> dict:
    """Compute summary statistics."""
    # Deduplicate multi-unit symbols by reference
    seen_refs = set()
    non_power = []
    for c in components:
        if c["type"] in ("power_symbol", "power_flag", "flag"):
            continue
        if c["reference"] in seen_refs:
            continue
        seen_refs.add(c["reference"])
        non_power.append(c)
    bom_items = [b for b in bom if not b["dnp"]]
    dnp_items = [b for b in bom if b["dnp"]]

    type_counts = {}
    for comp in non_power:
        t = comp["type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    # Power rails
    power_rails = sorted(set(
        comp["value"] for comp in components if comp["type"] == "power_symbol"
    ))

    # Missing properties
    missing_mpn = [c["reference"] for c in non_power
                   if c["type"] not in ("test_point", "mounting_hole")
                   and not c["mpn"] and not c["dnp"] and c["in_bom"]]
    missing_footprint = [c["reference"] for c in non_power
                         if not c["footprint"] and c["in_bom"] and not c["dnp"]]

    return {
        "total_components": len(non_power),
        "unique_parts": len(bom_items),
        "dnp_parts": len(dnp_items),
        "total_nets": len(nets),
        "total_wires": len(wires),
        "total_no_connects": len(no_connects),
        "component_types": type_counts,
        "power_rails": power_rails,
        "missing_mpn": missing_mpn,
        "missing_footprint": missing_footprint,
    }


def build_pin_to_net_map(nets: dict) -> dict:
    """Build a reverse map: (component, pin_number) -> (net_name, net_info)."""
    pin_net = {}
    for net_name, net_info in nets.items():
        for p in net_info["pins"]:
            pin_net[(p["component"], p["pin_number"])] = (net_name, net_info)
    return pin_net


def get_net_neighbors(net_info: dict, exclude_ref: str) -> list[dict]:
    """Get all components on a net except the given reference, with their details."""
    neighbors = []
    for p in net_info["pins"]:
        if p["component"] != exclude_ref and not p["component"].startswith("#"):
            neighbors.append({
                "component": p["component"],
                "pin_number": p["pin_number"],
                "pin_name": p["pin_name"],
                "pin_type": p["pin_type"],
            })
    return neighbors


def analyze_ic_pinouts(components: list[dict], nets: dict, no_connects: list[dict], pin_net: dict | None = None) -> list[dict]:
    """Analyze each IC's pinout for datasheet cross-referencing.

    For every IC, produces a detailed per-pin analysis showing:
    - What net each pin connects to
    - What other components are on that net (with their values)
    - Whether power pins have decoupling capacitors
    - Whether input pins have pull-up/pull-down resistors
    - Pins that are unconnected (and whether they should be)
    """
    EPSILON = COORD_EPSILON
    if pin_net is None:
        pin_net = build_pin_to_net_map(nets)

    # Build component lookup for values/types
    comp_lookup = {}
    for c in components:
        comp_lookup[c["reference"]] = c

    # Build no-connect position set
    nc_positions = set()
    for nc in no_connects:
        nc_positions.add((round(nc["x"] / EPSILON) * EPSILON,
                          round(nc["y"] / EPSILON) * EPSILON))

    results = []

    # Analyze ICs and other complex components (connectors, crystals, oscillators, etc.)
    target_types = {"ic", "connector", "crystal", "oscillator"}
    target_components = [c for c in components if c["type"] in target_types]

    for ic in target_components:
        ref = ic["reference"]
        pin_analysis = []
        decap_summary = {}  # net_name -> list of capacitor refs
        unconnected = []
        power_pins_detail = []
        signal_pins_detail = []

        for pin in ic.get("pins", []):
            # Ensure pin number and name are never null in output
            pin_number = pin.get("number") or ""
            pin_name = pin.get("name") or ""
            if not pin_number:
                # Fallback: use pin UUID if available, otherwise "unknown"
                pin_number = ic.get("pin_uuids", {}).get("", "unknown") if not pin_number else pin_number
                if not pin_number or pin_number == "unknown":
                    pin_number = f"unknown_{pin.get('x', 0):.0f}_{pin.get('y', 0):.0f}"

            pin_key = (ref, pin_number)
            net_name, net_info = pin_net.get(pin_key, (None, None))

            # Check if pin has a no-connect marker
            pin_pos = (round(pin["x"] / EPSILON) * EPSILON,
                       round(pin["y"] / EPSILON) * EPSILON)
            has_no_connect = pin_pos in nc_positions

            # Get components sharing this net
            neighbors = []
            neighbor_summary = []
            if net_info:
                neighbors = get_net_neighbors(net_info, ref)
                for nb in neighbors:
                    nb_comp = comp_lookup.get(nb["component"])
                    if nb_comp:
                        neighbor_summary.append({
                            "ref": nb["component"],
                            "value": nb_comp.get("value", ""),
                            "type": nb_comp.get("type", ""),
                            "pin": nb["pin_number"],
                            "pin_name": nb["pin_name"],
                        })

            # Classify what's connected
            connected_caps = [n for n in neighbor_summary if n["type"] == "capacitor"]
            connected_resistors = [n for n in neighbor_summary if n["type"] == "resistor"]
            connected_inductors = [n for n in neighbor_summary if n["type"] == "inductor"]

            pin_entry = {
                "pin_number": pin_number,
                "pin_name": pin_name,
                "pin_type": pin["type"],
                "net": net_name or ("NO_CONNECT" if has_no_connect else "UNCONNECTED"),
                "connected_to": neighbor_summary,
            }

            # Determine if this is functionally a power pin based on type OR net name.
            # Many lib symbols mark power pins as "input" or "passive", so also check
            # if the net is a known power rail.
            is_power_pin = pin["type"] in ("power_in", "power_out")
            if not is_power_pin and net_name:
                # Check net name against common power rail patterns
                net_upper = net_name.upper()
                is_power_pin = (
                    net_upper in ("GND", "VSS", "AGND", "DGND", "PGND",
                                  "VCC", "VDD", "AVCC", "AVDD", "DVCC", "DVDD",
                                  "VBUS", "V_USB")
                    or net_upper.startswith("+")
                    or net_upper.startswith("V+")
                )
            # Also check pin name for power pin hints
            if not is_power_pin and pin["name"]:
                pname = pin["name"].upper()
                is_power_pin = pname in (
                    "VCC", "VDD", "VSS", "GND", "AVCC", "AVDD", "DVCC", "DVDD",
                    "VIN", "VOUT", "PGND", "AGND", "DGND", "VBUS",
                )

            if is_power_pin:
                # For decoupling cap detection, only list caps directly on THIS net
                # (not the entire GND net which connects everything)
                net_is_ground = net_name and net_name.upper() in (
                    "GND", "VSS", "AGND", "DGND", "PGND")
                if net_is_ground:
                    # Don't list decoupling caps for ground pins — they're shared globally
                    pin_entry["has_decoupling_cap"] = True  # ground is always decoupled
                    pin_entry["decoupling_caps"] = []
                    pin_entry["note"] = "Ground net — decoupling caps listed on VCC/VDD pins"
                else:
                    pin_entry["has_decoupling_cap"] = len(connected_caps) > 0
                    pin_entry["decoupling_caps"] = [
                        {"ref": c["ref"], "value": c["value"]} for c in connected_caps
                    ]
                    if net_name and connected_caps:
                        decap_summary.setdefault(net_name, []).extend(
                            {"ref": c["ref"], "value": c["value"]} for c in connected_caps
                        )
                power_pins_detail.append(pin_entry)

            elif pin["type"] in ("input", "bidirectional", "open_collector", "open_emitter"):
                # Check for pull-up/pull-down resistors
                pull_resistors = []
                for r in connected_resistors:
                    r_comp = comp_lookup.get(r["ref"])
                    if r_comp:
                        # Check where the other end of the resistor goes
                        other_pin = "1" if r["pin"] == "2" else "2"
                        other_key = (r["ref"], other_pin)
                        other_net, _ = pin_net.get(other_key, (None, None))
                        if other_net in ("GND", "VSS"):
                            pull_resistors.append({
                                "ref": r["ref"], "value": r_comp["value"],
                                "direction": "pull-down", "to_net": other_net,
                            })
                        elif other_net and any(kw in other_net.upper()
                                               for kw in ("VCC", "VDD", "+3", "+5", "VBUS")):
                            pull_resistors.append({
                                "ref": r["ref"], "value": r_comp["value"],
                                "direction": "pull-up", "to_net": other_net,
                            })
                        else:
                            pull_resistors.append({
                                "ref": r["ref"], "value": r_comp["value"],
                                "direction": "series", "to_net": other_net,
                            })
                if pull_resistors:
                    pin_entry["resistors"] = pull_resistors
                signal_pins_detail.append(pin_entry)

            else:
                signal_pins_detail.append(pin_entry)

            if not net_name and not has_no_connect:
                unconnected.append(pin_entry)

            pin_analysis.append(pin_entry)

        # Deduplicate decoupling caps per net
        unique_decaps = {}
        for net_name, caps in decap_summary.items():
            seen = set()
            unique = []
            for c in caps:
                if c["ref"] not in seen:
                    seen.add(c["ref"])
                    unique.append(c)
            unique_decaps[net_name] = unique

        # Build IC analysis summary
        ic_result = {
            "reference": ref,
            "value": ic["value"],
            "type": ic["type"],
            "lib_id": ic["lib_id"],
            "mpn": ic.get("mpn", ""),
            "description": ic.get("description", ""),
            "datasheet": ic.get("datasheet", ""),
            "total_pins": len(pin_analysis),
            "unconnected_pins": len(unconnected),
            "pins": sorted(pin_analysis, key=lambda p: _pin_sort_key(p["pin_number"])),
            "power_pins": power_pins_detail,
            "signal_pins": signal_pins_detail,
            "decoupling_caps_by_rail": unique_decaps,
        }

        if unconnected:
            ic_result["unconnected_pin_list"] = unconnected

        results.append(ic_result)

    return results


def _pin_sort_key(pin_num: str):
    """Sort pin numbers numerically when possible, alphabetically otherwise."""
    try:
        return (0, int(pin_num))
    except ValueError:
        return (1, pin_num)


def identify_subcircuits(components: list[dict], nets: dict, pin_net: dict | None = None) -> list[dict]:
    """Identify potential subcircuit groupings around ICs."""
    if pin_net is None:
        pin_net = build_pin_to_net_map(nets)
    comp_lookup = {c["reference"]: c for c in components}
    subcircuits = []

    ics = [c for c in components if c["type"] == "ic"]

    for ic in ics:
        ref = ic["reference"]

        # Find all nets this IC connects to
        ic_nets = set()
        for pin in ic.get("pins", []):
            net_name, _ = pin_net.get((ref, pin["number"]), (None, None))
            if net_name:
                ic_nets.add(net_name)

        # Find all components that share nets with this IC (1-hop neighbors)
        neighbors = set()
        for net_name in ic_nets:
            if net_name in nets:
                for p in nets[net_name]["pins"]:
                    r = p["component"]
                    if r != ref and not r.startswith("#"):
                        neighbors.add(r)

        # Build neighbor details with values
        neighbor_details = []
        for nb_ref in sorted(neighbors):
            nb_comp = comp_lookup.get(nb_ref)
            if nb_comp:
                neighbor_details.append({
                    "ref": nb_ref,
                    "value": nb_comp.get("value", ""),
                    "type": nb_comp.get("type", ""),
                })

        subcircuits.append({
            "center_ic": ref,
            "ic_value": ic["value"],
            "ic_mpn": ic.get("mpn", ""),
            "ic_lib_id": ic["lib_id"],
            "neighbor_components": neighbor_details,
            "description": ic.get("description", ""),
        })

    return subcircuits


def _parse_legacy_single_sheet(path: str) -> tuple:
    """Parse a single legacy .sch file and return raw extracted data.

    Returns: (components, wires, labels, junctions, no_connects, sub_sheet_paths)
    where sub_sheet_paths is a list of resolved Path strings for $Sheet references.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    components = []
    wires = []
    labels = []
    junctions = []
    no_connects = []
    sub_sheet_paths = []

    MIL_TO_MM = 0.0254
    base_dir = Path(path).parent

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Component block
        if line == "$Comp":
            comp = {
                "reference": "", "value": "", "lib_id": "", "footprint": "",
                "datasheet": "", "description": "", "mpn": "", "manufacturer": "",
                "digikey": "", "mouser": "", "lcsc": "", "element14": "",
                "x": 0, "y": 0, "angle": 0,
                "mirror_x": False, "mirror_y": False,
                "uuid": "", "in_bom": True, "dnp": False, "on_board": True,
                "pin_uuids": {}, "pins": [], "type": "other",
            }
            i += 1
            while i < len(lines) and lines[i].strip() != "$EndComp":
                cl = lines[i].strip()

                # L Library:Symbol Reference
                if cl.startswith("L "):
                    parts = cl.split()
                    if len(parts) >= 3:
                        comp["lib_id"] = parts[1]
                        comp["reference"] = parts[2]

                # U unit mm_part timestamp
                elif cl.startswith("U "):
                    parts = cl.split()
                    if len(parts) >= 4:
                        comp["uuid"] = parts[3]
                        try:
                            comp["unit"] = int(parts[1])
                        except (ValueError, IndexError):
                            pass

                # P x y
                elif cl.startswith("P "):
                    parts = cl.split()
                    if len(parts) >= 3:
                        comp["x"] = round(int(parts[1]) * MIL_TO_MM, 4)
                        comp["y"] = round(int(parts[2]) * MIL_TO_MM, 4)

                # F N "value" orientation x y size flags visibility hjustify [font [italic bold]]
                elif cl.startswith("F "):
                    # Parse field: F N "value" ...
                    fm = re.match(r'F\s+(\d+)\s+"([^"]*)"', cl)
                    if fm:
                        field_num = int(fm.group(1))
                        field_val = fm.group(2)
                        if field_num == 0:
                            comp["reference"] = field_val
                        elif field_num == 1:
                            comp["value"] = field_val
                        elif field_num == 2:
                            comp["footprint"] = field_val
                        elif field_num == 3:
                            comp["datasheet"] = field_val
                        # Fields 4+ are custom — try to capture them
                        elif field_num >= 4 and field_val:
                            # Check if the field has a name after the positional data
                            # Format: F N "value" H x y size flags visibility hjustify "FieldName"
                            name_match = re.search(r'"([^"]*)"[^"]*$', cl[fm.end():])
                            if name_match:
                                fname = name_match.group(1)
                                fu = fname.upper()
                                if fu in ("MPN", "MFG PART", "MFGPART", "MANF#",
                                          "MPN#", "PART#", "MANUFACTURER_PART_NUMBER"):
                                    comp["mpn"] = field_val
                                elif fu in ("MANUFACTURER", "MFG", "MANF", "MFR"):
                                    comp["manufacturer"] = field_val
                                elif fu in ("DIGIKEY", "DIGIKEY#", "DIGI-KEY",
                                           "DIGI-KEY PART NUMBER", "DIGI-KEY_PN",
                                           "DIGIKEY PART NUMBER", "DIGIKEY_PART_NUMBER",
                                           "DIGI-KEY PN", "DIGIKEY PART", "DK"):
                                    comp["digikey"] = field_val
                                elif fu in ("MOUSER", "MOUSER#", "MOUSER PART NUMBER",
                                           "MOUSER PART", "MOUSER_PN", "MOUSER PN"):
                                    comp["mouser"] = field_val
                                elif fu in ("LCSC", "LCSC#", "JLC#", "JLCPCB#",
                                           "LCSC PART #", "LCSC PART NUMBER",
                                           "LCSC PART", "LCSCSTKCODE", "LCSCSTOCKCODE",
                                           "JLCPCB", "JLCPCB PART", "JLC"):
                                    comp["lcsc"] = field_val
                                elif fu in ("NEWARK", "NEWARK PART NUMBER", "NEWARK_PN",
                                           "NEWARK PN", "FARNELL", "FARNELL PART NUMBER",
                                           "FARNELL_PN", "FARNELL PN", "ELEMENT14",
                                           "ELEMENT14 PART NUMBER", "ELEMENT14_PN"):
                                    comp["element14"] = field_val
                                elif fu == "DNP":
                                    comp["dnp"] = field_val.strip() not in ("", "0", "false")

                # Orientation matrix line (after position line)
                # Format: unit x y orientation_matrix
                elif cl and cl[0].isdigit() and len(cl.split()) == 4:
                    parts = cl.split()
                    try:
                        mat = [int(p) for p in parts]
                        # Matrix: [a b c d] where rotation/mirror encoded
                        # 1 0 0 -1 = normal, 0 1 1 0 = 90deg, etc.
                        if mat == [0, 1, 1, 0] or mat == [0, -1, -1, 0]:
                            comp["angle"] = 90
                        elif mat == [-1, 0, 0, 1] or mat == [-1, 0, 0, -1]:
                            comp["angle"] = 180
                        elif mat == [0, -1, 1, 0] or mat == [0, 1, -1, 0]:
                            comp["angle"] = 270
                    except ValueError:
                        pass

                i += 1
            # Legacy power symbol detection: #PWR/#FLG refs or library named "power"
            lib_prefix = comp["lib_id"].split(":")[0].lower()
            is_power = (comp["reference"].startswith("#PWR")
                        or comp["reference"].startswith("#FLG")
                        or lib_prefix == "power"
                        or lib_prefix.endswith("_power"))
            comp["type"] = classify_component(comp["reference"], comp["lib_id"], comp["value"], is_power)
            components.append(comp)

        # Hierarchical sheet block — extract subsheet filename
        elif line == "$Sheet":
            sheet_file = None
            i += 1
            while i < len(lines) and lines[i].strip() != "$EndSheet":
                sl = lines[i].strip()
                # F1 "filename.sch" size — the sheet filename field
                sm = re.match(r'F1\s+"([^"]+\.sch)"', sl)
                if sm:
                    sheet_file = sm.group(1)
                i += 1
            if sheet_file:
                sub_path = base_dir / sheet_file
                if sub_path.exists():
                    sub_sheet_paths.append(str(sub_path.resolve()))

        # Wire
        elif line == "Wire Wire Line":
            i += 1
            if i < len(lines):
                parts = lines[i].strip().split()
                if len(parts) >= 4:
                    wires.append({
                        "x1": round(int(parts[0]) * MIL_TO_MM, 4),
                        "y1": round(int(parts[1]) * MIL_TO_MM, 4),
                        "x2": round(int(parts[2]) * MIL_TO_MM, 4),
                        "y2": round(int(parts[3]) * MIL_TO_MM, 4),
                    })

        # Junction / Connection
        elif line.startswith("Connection ~"):
            parts = line.split()
            if len(parts) >= 4:
                junctions.append({
                    "x": round(int(parts[2]) * MIL_TO_MM, 4),
                    "y": round(int(parts[3]) * MIL_TO_MM, 4),
                })

        # No-connect
        elif line.startswith("NoConn ~"):
            parts = line.split()
            if len(parts) >= 4:
                no_connects.append({
                    "x": round(int(parts[2]) * MIL_TO_MM, 4),
                    "y": round(int(parts[3]) * MIL_TO_MM, 4),
                })

        # Labels
        elif line.startswith("Text Label "):
            parts = line.split()
            if len(parts) >= 5:
                x = round(int(parts[2]) * MIL_TO_MM, 4)
                y = round(int(parts[3]) * MIL_TO_MM, 4)
                # Next line is the label text
                i += 1
                if i < len(lines):
                    name = lines[i].strip()
                    labels.append({"name": name, "type": "label", "x": x, "y": y, "angle": 0})

        elif line.startswith("Text GLabel "):
            parts = line.split()
            if len(parts) >= 5:
                x = round(int(parts[2]) * MIL_TO_MM, 4)
                y = round(int(parts[3]) * MIL_TO_MM, 4)
                i += 1
                if i < len(lines):
                    name = lines[i].strip()
                    labels.append({"name": name, "type": "global_label", "x": x, "y": y, "angle": 0})

        elif line.startswith("Text HLabel "):
            parts = line.split()
            if len(parts) >= 5:
                x = round(int(parts[2]) * MIL_TO_MM, 4)
                y = round(int(parts[3]) * MIL_TO_MM, 4)
                i += 1
                if i < len(lines):
                    name = lines[i].strip()
                    labels.append({"name": name, "type": "hierarchical_label", "x": x, "y": y, "angle": 0})

        i += 1

    return components, wires, labels, junctions, no_connects, sub_sheet_paths


def parse_legacy_schematic(path: str) -> dict:
    """Parse a KiCad 5 legacy .sch file and return the same structure as analyze_schematic.

    Legacy format uses line-oriented text with $Comp/$EndComp blocks, coordinates
    in mils (1/1000 inch), and positional field numbering (F0=ref, F1=value, etc.).

    For hierarchical designs, recursively parses all subsheets referenced by
    $Sheet blocks and merges connectivity across sheets.
    """
    all_components = []
    all_wires = []
    all_labels = []
    all_junctions = []
    all_no_connects = []
    sheets_parsed = []

    to_parse = [str(Path(path).resolve())]
    parsed = set()

    while to_parse:
        sheet_path = to_parse.pop(0)
        if sheet_path in parsed:
            continue
        parsed.add(sheet_path)

        components, wires, labels, junctions, no_connects, sub_sheets = \
            _parse_legacy_single_sheet(sheet_path)

        # Tag elements with sheet index to keep coordinate spaces separate
        sheet_idx = len(sheets_parsed)
        for c in components:
            c["_sheet"] = sheet_idx
        for w in wires:
            w["_sheet"] = sheet_idx
        for lbl in labels:
            lbl["_sheet"] = sheet_idx
        for j in junctions:
            j["_sheet"] = sheet_idx

        all_components.extend(components)
        all_wires.extend(wires)
        all_labels.extend(labels)
        all_junctions.extend(junctions)
        all_no_connects.extend(no_connects)
        sheets_parsed.append(sheet_path)

        for sub_path in sub_sheets:
            if sub_path not in parsed:
                to_parse.append(sub_path)

    # Extract power symbols (preserve _sheet so build_net_map keeps coordinate
    # spaces separate — without it, power symbols from sub-sheets all land in
    # sheet 0's coordinate space and fail to connect to their actual wires).
    power_symbols = []
    for comp in all_components:
        if comp["type"] == "power_symbol":
            ps = {
                "net_name": comp["value"],
                "x": comp["x"],
                "y": comp["y"],
                "lib_id": comp["lib_id"],
            }
            if "_sheet" in comp:
                ps["_sheet"] = comp["_sheet"]
            power_symbols.append(ps)

    # Generate BOM
    bom = generate_bom(all_components)

    # Build nets from wires + labels + power symbols using union-find.
    # Legacy files don't have pin position data (that's in separate .lib files),
    # so nets won't have component pin associations, but we still get the wire
    # topology and net names from labels and power symbols.
    nets = build_net_map(all_components, all_wires, all_labels, power_symbols, all_junctions)

    stats = compute_statistics(all_components, nets, bom, all_wires, all_no_connects)

    # Filter to real components (non-power) for annotation check
    real_components = [
        c for c in all_components
        if c["type"] not in ("power_symbol", "power_flag", "flag")
    ]
    annotation_issues = check_annotation_completeness(real_components)

    return {
        "file": str(path),
        "kicad_version": "5 (legacy)",
        "file_version": "4",
        "sheets_parsed": len(sheets_parsed),
        "sheet_files": sheets_parsed,
        "statistics": stats,
        "bom": bom,
        "components": [
            {k: v for k, v in c.items() if k != "pins"}
            for c in real_components
        ],
        "nets": nets,
        "subcircuits": [],
        "labels": all_labels,
        "no_connects": all_no_connects,
        "power_symbols": power_symbols,
        "annotation_issues": annotation_issues,
        "note": "Legacy KiCad 5 format — net names from labels/power symbols are available but component pin-to-net mapping requires the .lib library files which are not parsed.",
    }


def parse_single_sheet(path: str, instance_uuid: str = "",
                       symbol_instances: dict | None = None) -> tuple:
    """Parse a single .kicad_sch file and return raw extracted data.

    If instance_uuid is provided, remap component references from the
    (instances) block for this specific sheet instance.

    If symbol_instances is provided, use it as fallback for remapping when
    inline (instances) blocks are absent.

    Returns: (root, components, wires, labels, junctions, no_connects,
              sub_sheet_paths, lib_symbols, text_annotations, bus_elements, title_block)
    """
    root = parse_file(path)
    lib_symbols = extract_lib_symbols(root)
    components = extract_components(root, lib_symbols, instance_uuid=instance_uuid,
                                    symbol_instances=symbol_instances)
    wires = extract_wires(root)
    labels = extract_labels(root)
    junctions = extract_junctions(root)
    no_connects = extract_no_connects(root)
    text_annotations = extract_text_annotations(root)
    bus_elements = extract_bus_elements(root)
    title_block = extract_title_block(root)

    # Find sub-sheet references, including UUIDs for multi-instance support.
    # Also extract sheet pin stubs — these are the parent-side endpoints of
    # hierarchical connections.  Each (pin "NAME" direction (at X Y ANGLE))
    # inside a (sheet) block acts like a hierarchical_label at that position,
    # connecting the parent sheet's wires to the child sheet's matching
    # hierarchical_label via the label name union in build_net_map().
    sub_sheet_paths = []
    base_dir = Path(path).parent
    for sheet in find_all(root, "sheet"):
        # Sheet file property name varies by KiCad version:
        # KiCad 6+: (property "Sheetfile" "filename.kicad_sch")
        # KiCad 7+: (property "Sheet file" "filename.kicad_sch")
        sheet_file = get_property(sheet, "Sheetfile") or get_property(sheet, "Sheet file")
        if sheet_file:
            sub_path = base_dir / sheet_file
            if sub_path.exists():
                sheet_uuid = get_value(sheet, "uuid") or ""
                sub_sheet_paths.append((str(sub_path), sheet_uuid))

        # Extract sheet pin stubs as hierarchical labels so parent-sheet wires
        # connecting to the sheet symbol get unioned with the child sheet's nets.
        for pin in find_all(sheet, "pin"):
            if len(pin) < 2:
                continue
            pin_name = pin[1]
            at = get_at(pin)
            if at:
                labels.append({
                    "name": pin_name,
                    "type": "hierarchical_label",
                    "x": round(at[0], 4),
                    "y": round(at[1], 4),
                    "angle": at[2] if len(at) > 2 else 0,
                })

    return (root, components, wires, labels, junctions, no_connects,
            sub_sheet_paths, lib_symbols, text_annotations, bus_elements, title_block)


def analyze_connectivity(components: list[dict], nets: dict, no_connects: list[dict]) -> dict:
    """Analyze the connectivity graph for potential issues.

    Returns a dict with:
    - unconnected_pins: pins not on any net (and not marked no-connect)
    - single_pin_nets: nets with only one pin (likely unfinished connections)
    - multi_driver_nets: nets with multiple output/bidirectional drivers
    - power_net_summary: per power rail, which components connect
    """
    EPSILON = COORD_EPSILON

    # Build set of no-connect positions for quick lookup
    nc_positions = set()
    for nc in no_connects:
        nc_positions.add((round(nc["x"] / EPSILON) * EPSILON,
                          round(nc["y"] / EPSILON) * EPSILON))

    # Build set of all pins that appear in any net
    connected_pins = set()
    for net_info in nets.values():
        for p in net_info["pins"]:
            connected_pins.add((p["component"], p["pin_number"]))

    # Find unconnected pins
    unconnected_pins = []
    for comp in components:
        if comp["type"] in ("power_symbol", "power_flag", "flag"):
            continue
        for pin in comp.get("pins", []):
            pin_key = (comp["reference"], pin["number"])
            if pin_key not in connected_pins:
                # Check if there's a no-connect marker at this pin
                pin_pos = (round(pin["x"] / EPSILON) * EPSILON,
                           round(pin["y"] / EPSILON) * EPSILON)
                if pin_pos not in nc_positions:
                    unconnected_pins.append({
                        "component": comp["reference"],
                        "pin_number": pin["number"],
                        "pin_name": pin["name"],
                        "pin_type": pin["type"],
                    })

    # Find single-pin nets (likely unfinished wiring)
    single_pin_nets = []
    for net_name, net_info in nets.items():
        if len(net_info["pins"]) == 1 and not net_name.startswith("__unnamed_"):
            single_pin_nets.append({
                "net": net_name,
                "pin": net_info["pins"][0],
            })

    # Find multi-driver nets (multiple outputs driving the same net)
    # Exclude power flags (#FLG, #PWR) — they're virtual, not real drivers
    multi_driver_nets = []
    output_types = {"output", "tri_state", "power_out"}
    for net_name, net_info in nets.items():
        drivers = [p for p in net_info["pins"]
                   if p["pin_type"] in output_types
                   and not p["component"].startswith("#")]
        if len(drivers) > 1:
            multi_driver_nets.append({
                "net": net_name,
                "drivers": drivers,
            })

    # Power net summary — for each named power rail, which real components connect
    power_net_summary = {}
    for net_name, net_info in nets.items():
        if net_name.startswith("__unnamed_"):
            continue
        is_power = any(p["pin_type"] in ("power_in", "power_out") for p in net_info["pins"])
        if is_power or net_name in ("GND", "VCC", "VDD", "+3V3", "+3.3V", "+5V", "+12V", "VBUS"):
            real_components = sorted(set(
                p["component"] for p in net_info["pins"]
                if not p["component"].startswith("#")
            ))
            power_net_summary[net_name] = {
                "pin_count": len([p for p in net_info["pins"] if not p["component"].startswith("#")]),
                "components": real_components,
            }

    return {
        "unconnected_pins": unconnected_pins,
        "single_pin_nets": single_pin_nets,
        "multi_driver_nets": multi_driver_nets,
        "power_net_summary": power_net_summary,
    }


def analyze_design_rules(components: list[dict], nets: dict, no_connects: list[dict],
                         results_in: dict | None = None, pin_net: dict | None = None) -> dict:
    """Deep EE analysis: power domains, bus protocols, differential pairs, ERC checks.

    Returns:
    - power_domains: which ICs are on which voltage rails
    - cross_domain_signals: signals crossing between different power domains
    - bus_analysis: I2C pull-ups, SPI CS assignments, UART TX/RX pairs
    - differential_pairs: USB, CAN, LVDS with termination checks
    - erc_warnings: input-to-input, output-to-output, undriven inputs
    - net_classification: every net tagged by type (power/gnd/clock/data/analog/etc.)
    """
    if results_in is None:
        results_in = {}
    if pin_net is None:
        pin_net = build_pin_to_net_map(nets)
    comp_lookup = {c["reference"]: c for c in components}
    parsed_values = {}
    for c in components:
        pv = parse_value(c.get("value", ""))
        if pv is not None:
            parsed_values[c["reference"]] = pv

    # Build set of known power rail names from nets that came from power symbols
    known_power_rails = set()
    for net_name, net_info in nets.items():
        for p in net_info.get("pins", []):
            if p["component"].startswith("#PWR") or p["component"].startswith("#FLG"):
                known_power_rails.add(net_name)
                break

    def is_ground(net_name: str | None) -> bool:
        return _is_ground_name(net_name)

    def is_power_net(net_name: str | None) -> bool:
        return _is_power_net_name(net_name, known_power_rails)

    # ---- Net Classification ----
    net_classes = {}
    for net_name, net_info in nets.items():
        if net_name.startswith("__unnamed_"):
            # Classify unnamed nets by pin types
            pin_types = set(p["pin_type"] for p in net_info["pins"])
            has_power = bool(pin_types & {"power_in", "power_out"})
            if has_power:
                net_classes[net_name] = "power_internal"
            else:
                net_classes[net_name] = "signal"
            continue

        nu = net_name.upper()
        if is_ground(net_name):
            net_classes[net_name] = "ground"
        elif is_power_net(net_name):
            net_classes[net_name] = "power"
        elif any(kw in nu for kw in ("SCL", "SCK", "CLK", "MCLK", "SCLK", "XTAL", "OSC")):
            net_classes[net_name] = "clock"
        elif any(kw in nu for kw in ("SDA", "MOSI", "MISO", "SDI", "SDO", "UART", "TX", "RX")):
            net_classes[net_name] = "data"
        elif any(kw in nu for kw in ("USB", "CAN", "LVDS", "ETH")):
            net_classes[net_name] = "high_speed"
        elif any(kw in nu for kw in ("ADC", "AIN", "VREF", "VSENSE", "ISENSE")):
            net_classes[net_name] = "analog"
        elif any(kw in nu for kw in ("RESET", "NRST", "RST", "EN", "ENABLE")):
            net_classes[net_name] = "control"
        elif any(kw in nu for kw in ("CS", "SS", "NSS", "CE", "SEL")):
            net_classes[net_name] = "chip_select"
        elif any(kw in nu for kw in ("INT", "IRQ", "ALERT", "DRDY")):
            net_classes[net_name] = "interrupt"
        elif any(kw in nu for kw in _OUTPUT_DRIVE_KEYWORDS):
            net_classes[net_name] = "output_drive"
        elif any(kw in nu for kw in ("SWD", "SWCLK", "SWDIO", "SWO", "JTAG", "TCK", "TMS", "TDI", "TDO")):
            net_classes[net_name] = "debug"
        elif any(kw in nu for kw in ("BOOT", "TEST")):
            net_classes[net_name] = "config"
        else:
            net_classes[net_name] = "signal"

    # ---- Power Domain Mapping ----
    # For each IC, determine which power rails it connects to
    # Track IO-level reference pins (VDDIO, VIO) separately from internal supplies
    # (VCC, VDD) — for cross-domain analysis, the IO rail determines signal levels
    _io_pin_names = {"VDDIO", "VIO", "VCCA", "VCCB", "VREF", "VLOGIC",
                     "DVDD", "DVCC", "IOVDD", "IOVCC"}
    power_domains = {}
    ics = [c for c in components if c["type"] == "ic"]
    for ic in ics:
        ref = ic["reference"]
        rails = set()
        io_rails = set()
        for pin in ic.get("pins", []):
            net_name, _ = pin_net.get((ref, pin["number"]), (None, None))
            if not net_name:
                continue
            pname_upper = pin["name"].upper()
            is_pwr = is_power_net(net_name) and not is_ground(net_name)
            is_named_pwr = pname_upper in ("VCC", "VDD", "AVCC", "AVDD", "VBUS",
                                           "VIN", "VOUT", "VDDIO", "VIO", "VCCA",
                                           "VCCB", "VREF", "VLOGIC", "DVDD", "DVCC",
                                           "IOVDD", "IOVCC", "VCCREG", "VREG")
            if is_pwr or is_named_pwr:
                rails.add(net_name)
                if pname_upper in _io_pin_names:
                    io_rails.add(net_name)
        if rails:
            power_domains[ref] = {
                "value": ic["value"],
                "power_rails": sorted(rails),
                "io_rails": sorted(io_rails) if io_rails else None,
            }

    # Group ICs by power domain
    domain_groups = {}
    for ref, info in power_domains.items():
        for rail in info["power_rails"]:
            domain_groups.setdefault(rail, []).append(ref)

    # ---- Cross-Domain Signal Detection ----
    # Find signal nets that connect ICs from different power domains
    cross_domain = []
    # Build set of ESD protection IC references for cross-domain filtering
    esd_ic_refs = set()
    for pd in results_in.get("protection_devices", []):
        if pd.get("type") == "esd_ic":
            esd_ic_refs.add(pd["ref"])

    # Detect level translator ICs — these bridge domains intentionally so
    # signals through them don't need additional level shifting.
    level_translator_keywords = (
        "leveltranslator", "level_translator", "levelshift", "level_shift",
        "txb0", "txs0", "tca9", "lsf0", "sn74lvc", "sn74avc",
        "sn74cb3", "sn74cbt", "nlsx", "nts0", "fxl", "adg320",
        "max395", "gtl2", "pca960", "tca641",
    )
    level_translator_desc_keywords = (
        "level translator", "level shifter", "level-shifting",
        "voltage translator", "voltage level",
    )
    level_translator_refs = set()
    for ic in components:
        if ic["type"] != "ic":
            continue
        val_low = ic.get("value", "").lower()
        lib_low = ic.get("lib_id", "").lower()
        desc_low = ic.get("description", "").lower()
        kw_low = ic.get("keywords", "").lower()
        if (any(k in val_low or k in lib_low for k in level_translator_keywords) or
                any(k in desc_low or k in kw_low for k in level_translator_desc_keywords)):
            level_translator_refs.add(ic["reference"])
    for net_name, net_info in nets.items():
        if is_power_net(net_name) or is_ground(net_name):
            continue
        # Find all ICs on this net
        ic_refs = set()
        for p in net_info["pins"]:
            if p["component"] in power_domains and not p["component"].startswith("#"):
                ic_refs.add(p["component"])
        if len(ic_refs) < 2:
            continue

        # Check if they're on different power domains
        def _get_power_domains(refs: set) -> set:
            domains = set()
            for r in refs:
                for rail in power_domains.get(r, {}).get("power_rails", []):
                    if not is_ground(rail):
                        domains.add(rail)
            return domains

        def _get_io_domains(refs: set) -> set:
            """Get I/O-level domains for cross-domain comparison.

            When an IC has a dedicated IO-level pin (VDDIO, VIO, etc.),
            use that rail for signal-level comparison instead of all power
            rails.  This avoids false positives where internal supplies
            (VCC charge pump, analog VDD) differ but the actual I/O
            voltage matches the other IC.
            """
            domains = set()
            for r in refs:
                info = power_domains.get(r, {})
                io = info.get("io_rails")
                if io:
                    for rail in io:
                        domains.add(rail)
                else:
                    # No dedicated IO pin — use all power rails
                    for rail in info.get("power_rails", []):
                        if not is_ground(rail):
                            domains.add(rail)
            return domains

        domains_on_net = _get_power_domains(ic_refs)
        if len(domains_on_net) > 1:
            # Don't flag as needing level shifter when the only cross-domain
            # connection is through an ESD/protection IC — those clamp voltage
            # but don't change signal levels (e.g., USBLC6 on USB D+/D-)
            non_esd_refs = ic_refs - esd_ic_refs
            non_esd_domains = _get_power_domains(non_esd_refs)

            # Check if a level translator is on this net — if so, it already
            # handles the voltage translation
            translators_on_net = ic_refs & level_translator_refs
            has_translator = len(translators_on_net) > 0

            if len(non_esd_domains) > 1:
                if has_translator:
                    # Level translator present — shifting is handled
                    needs_shifter = False
                else:
                    # Use IO-level domains for the level shifter decision.
                    # Check pairwise: every pair of ICs must share at least one
                    # common IO rail. A multi-rail SoC (e.g., +3.3V + VDDA)
                    # connecting to a simple IC on +3.3V shares +3.3V, so no
                    # level shifter is needed despite different rail counts.
                    # Also treat rails at the same voltage as equivalent (e.g.,
                    # +3V3 and VCC_3V3 are both 3.3V).
                    def _rails_voltage_compatible(rails_a: set, rails_b: set) -> bool:
                        """Check if two sets of rails share a rail or voltage."""
                        if rails_a & rails_b:
                            return True
                        # Parse voltages from net names and check overlap
                        va = {_parse_voltage_from_net_name(r) for r in rails_a} - {None}
                        vb = {_parse_voltage_from_net_name(r) for r in rails_b} - {None}
                        return bool(va & vb)

                    functional_refs = non_esd_refs - level_translator_refs
                    ic_list = sorted(functional_refs) if functional_refs else sorted(non_esd_refs)
                    needs_shifter = False
                    for i_idx in range(len(ic_list)):
                        for j_idx in range(i_idx + 1, len(ic_list)):
                            a_io = _get_io_domains({ic_list[i_idx]})
                            b_io = _get_io_domains({ic_list[j_idx]})
                            if not _rails_voltage_compatible(a_io, b_io):
                                needs_shifter = True
                                break
                        if needs_shifter:
                            break
            else:
                needs_shifter = False
            entry = {
                "net": net_name,
                "ics": sorted(ic_refs),
                "power_domains": sorted(domains_on_net),
                "needs_level_shifter": needs_shifter,
            }
            if has_translator:
                entry["level_translators"] = sorted(translators_on_net)
            cross_domain.append(entry)

    # ---- Bus Protocol Analysis ----
    buses = {"i2c": [], "spi": [], "uart": [], "can": []}

    # I2C: look for SDA/SCL net pairs by net name
    i2c_nets = {}
    for net_name in nets:
        nu = net_name.upper()
        if "SDA" in nu or "SCL" in nu or "I2C" in nu:
            # Skip SPI signals (MISO contains no I2C keywords, but SCLK/SCK match SCL)
            if "SCLK" in nu or nu.endswith("SCK") or "SPI" in nu:
                continue
            bus_id = nu.replace("SDA", "").replace("SCL", "").replace("I2C", "").replace("_", "").strip()
            i2c_nets.setdefault(bus_id, {})[nu] = net_name

    # Generate I2C bus entries from net-name matches
    i2c_seen_nets = set()
    for bus_id, net_map in i2c_nets.items():
        for nu_key, net_name in net_map.items():
            if net_name in i2c_seen_nets:
                continue
            i2c_seen_nets.add(net_name)
            net_info = nets.get(net_name, {})
            line = "SDA" if "SDA" in nu_key else "SCL"
            devices = [p["component"] for p in net_info.get("pins", [])
                       if comp_lookup.get(p["component"], {}).get("type") == "ic"]
            # Find pull-up resistors
            pullups = []
            for p in net_info.get("pins", []):
                comp = comp_lookup.get(p["component"])
                if comp and comp["type"] == "resistor":
                    r_val = parsed_values.get(p["component"])
                    if r_val:
                        other_pin = "1" if p["pin_number"] == "2" else "2"
                        other_net, _ = pin_net.get((p["component"], other_pin), (None, None))
                        if other_net and is_power_net(other_net) and not is_ground(other_net):
                            pullups.append({
                                "ref": p["component"],
                                "value": comp["value"],
                                "ohms": r_val,
                                "to_rail": other_net,
                            })
            buses["i2c"].append({
                "net": net_name,
                "line": line,
                "devices": devices,
                "pull_ups": pullups,
                "has_pull_up": len(pullups) > 0,
            })

    # Also detect I2C from pin names (for nets without SDA/SCL in their name)
    for net_name, net_info in nets.items():
        if net_name in i2c_seen_nets:
            continue  # Already found by net name
        sda_pins = [p for p in net_info["pins"] if "SDA" in p.get("pin_name", "").upper()]
        # Exclude SPI clock pins (SCLK, SCK) which contain "SCL" as substring
        scl_pins = [p for p in net_info["pins"]
                    if "SCL" in p.get("pin_name", "").upper()
                    and "SCLK" not in p.get("pin_name", "").upper()
                    and p.get("pin_name", "").upper() not in ("SCK",)]
        if sda_pins or scl_pins:
            # Find pull-up resistors on this net
            pullups = []
            for p in net_info["pins"]:
                comp = comp_lookup.get(p["component"])
                if comp and comp["type"] == "resistor":
                    r_val = parsed_values.get(p["component"])
                    if r_val:
                        # Check if other end goes to a power rail
                        other_pin = "1" if p["pin_number"] == "2" else "2"
                        other_net, _ = pin_net.get((p["component"], other_pin), (None, None))
                        if other_net and is_power_net(other_net) and not is_ground(other_net):
                            pullups.append({
                                "ref": p["component"],
                                "value": comp["value"],
                                "ohms": r_val,
                                "to_rail": other_net,
                            })

            bus_type = "SDA" if sda_pins else "SCL"
            devices = [p["component"] for p in net_info["pins"]
                       if comp_lookup.get(p["component"], {}).get("type") == "ic"]

            buses["i2c"].append({
                "net": net_name,
                "line": bus_type,
                "devices": devices,
                "pull_ups": pullups,
                "has_pull_up": len(pullups) > 0,
            })

    # SPI: look for MOSI/MISO/SCK/CS patterns (and newer COPI/CIPO/SDI/SDO)
    # Build a set of nets already identified as SPI to guard I2C pin-name
    # detection against false positives (SCL substring matches on SCLK).
    _spi_net_kw = ("MOSI", "MISO", "SCK", "SCLK", "COPI", "CIPO", "SDI", "SDO")
    _spi_canon = {  # normalize alternative names to canonical SPI signals
        "COPI": "MOSI", "SDO": "MOSI", "SDI": "MISO", "CIPO": "MISO",
        "SCLK": "SCK",
    }
    spi_signals = {}
    spi_nets: set[str] = set()
    for net_name, net_info in nets.items():
        nu = net_name.upper()
        for kw in _spi_net_kw:
            if kw in nu:
                canon = _spi_canon.get(kw, kw)
                bus_id = nu.replace(kw, "").replace("_", "").strip() or "0"
                spi_signals.setdefault(bus_id, {})[canon] = {
                    "net": net_name,
                    "devices": [p["component"] for p in net_info["pins"]
                                if comp_lookup.get(p["component"], {}).get("type") == "ic"],
                }
                spi_nets.add(net_name)
        # Also check pin names
        for p in net_info["pins"]:
            pn = p.get("pin_name", "").upper()
            for kw in _spi_net_kw:
                if pn == kw:
                    canon = _spi_canon.get(kw, kw)
                    bus_id = "pin_" + p["component"]
                    spi_signals.setdefault(bus_id, {})[canon] = {
                        "net": net_name,
                        "devices": [pp["component"] for pp in net_info["pins"]
                                    if comp_lookup.get(pp["component"], {}).get("type") == "ic"],
                    }
                    spi_nets.add(net_name)

    for bus_id, signals in spi_signals.items():
        if len(signals) >= 2:  # At least 2 SPI signals to count as a bus
            buses["spi"].append({
                "bus_id": bus_id,
                "signals": signals,
            })

    # UART: look for TX/RX pairs (exclude CAN/SPI/I2C signals that happen to contain TX/RX)
    uart_nets = {}
    for net_name, net_info in nets.items():
        nu = net_name.upper()
        # Skip nets that belong to other bus types
        if any(kw in nu for kw in ("CAN", "SPI", "I2C", "MOSI", "MISO", "SCL", "SDA")):
            continue
        if any(kw in nu for kw in ("UART", "TX", "RX", "TXD", "RXD")):
            # Identify which devices connect
            devices = [p["component"] for p in net_info["pins"]
                       if comp_lookup.get(p["component"], {}).get("type") == "ic"]
            uart_nets[net_name] = {
                "net": net_name,
                "devices": devices,
                "pin_count": len(net_info["pins"]),
            }
    if uart_nets:
        buses["uart"] = list(uart_nets.values())

    # CAN: look for CAN_TX/CAN_RX nets, CANH/CANL, or CAN transceiver ICs
    can_keywords = ("can_tx", "can_rx", "cantx", "canrx", "canh", "canl", "can_h", "can_l")
    # SN65HVD2xx/10xx are CAN; SN65HVD7x are RS-485 — use specific prefixes
    can_transceiver_kw = ("sn65hvd2", "sn65hvd10", "mcp2551", "mcp2562", "mcp251",
                          "tja10", "tja11", "iso1050", "max3051", "ata6561",
                          "mcp2561", "iso1042")
    can_nets_found = {}
    for net_name, net_info in nets.items():
        nu = net_name.upper()
        if any(kw in nu.lower() for kw in can_keywords):
            devices = [p["component"] for p in net_info["pins"]
                       if comp_lookup.get(p["component"], {}).get("type") == "ic"]
            can_nets_found[net_name] = {"net": net_name, "devices": devices}
    # Also detect by CAN transceiver IC presence — add transceiver info to bus
    for comp in components:
        if comp["type"] != "ic":
            continue
        val = comp.get("value", "").lower()
        lib = comp.get("lib_id", "").lower()
        if any(k in val or k in lib for k in can_transceiver_kw):
            if not can_nets_found:
                # No CAN nets found by name — add a placeholder entry
                can_nets_found["__can_transceiver__"] = {
                    "net": "CAN",
                    "transceiver": comp["reference"],
                    "devices": [comp["reference"]],
                }
    if can_nets_found:
        buses["can"] = list(can_nets_found.values())

    # ---- Differential Pair Detection ----
    diff_pairs = []

    # Suffix pair table: (positive_suffix, negative_suffix) → protocol guess
    _diff_suffix_pairs = [
        # USB
        ("_DP", "_DM"), ("_D+", "_D-"), ("_D_P", "_D_N"), ("DP", "DM"),
        # Generic differential
        ("_P", "_N"), ("+", "-"),
        # LVDS / Ethernet
        ("_TX+", "_TX-"), ("_RX+", "_RX-"),
        ("_TXP", "_TXN"), ("_RXP", "_RXN"),
        ("_TD+", "_TD-"), ("_RD+", "_RD-"),
        ("_TDP", "_TDN"), ("_RDP", "_RDN"),
    ]

    def _guess_diff_protocol(net_name: str) -> str:
        """Guess the protocol from a differential pair net name."""
        nu = net_name.upper()
        if "USB" in nu:
            return "USB"
        if "LVDS" in nu:
            return "LVDS"
        if "ETH" in nu or "MDIO" in nu or "RGMII" in nu or "SGMII" in nu:
            return "Ethernet"
        if "HDMI" in nu or "TMDS" in nu:
            return "HDMI"
        if "MIPI" in nu or "DSI" in nu or "CSI" in nu:
            return "MIPI"
        if "PCIE" in nu or "PCI" in nu:
            return "PCIe"
        if "SATA" in nu:
            return "SATA"
        if "CAN" in nu:
            return "CAN"
        if "RS485" in nu or "RS-485" in nu:
            return "RS-485"
        return "differential"

    # Net-name-based detection: find matching suffix pairs
    net_names_upper = {n.upper(): n for n in nets}
    found_pairs: set[tuple[str, str]] = set()  # track to avoid duplicates

    for pos_sfx, neg_sfx in _diff_suffix_pairs:
        for nu, real_name in net_names_upper.items():
            if nu.endswith(pos_sfx.upper()):
                base = nu[:-len(pos_sfx)]
                neg_candidate = base + neg_sfx.upper()
                if neg_candidate in net_names_upper:
                    pos_real = real_name
                    neg_real = net_names_upper[neg_candidate]
                    pair_key = (min(pos_real, neg_real), max(pos_real, neg_real))
                    if pair_key in found_pairs:
                        continue
                    found_pairs.add(pair_key)

                    protocol = _guess_diff_protocol(pos_real)
                    entry: dict = {
                        "type": protocol,
                        "positive": pos_real,
                        "negative": neg_real,
                    }

                    # Find shared ICs (connected to both nets)
                    pos_comps = {p["component"] for p in nets[pos_real]["pins"]
                                 if not p["component"].startswith("#")}
                    neg_comps = {p["component"] for p in nets[neg_real]["pins"]
                                 if not p["component"].startswith("#")}
                    shared = pos_comps & neg_comps
                    if shared:
                        entry["shared_ics"] = sorted(shared)

                    # Check for ESD protection
                    esd_chips = [c for c in shared
                                 if comp_lookup.get(c, {}).get("type") == "ic"]
                    entry["has_esd"] = len(esd_chips) > 0
                    if esd_chips:
                        entry["esd_protection"] = esd_chips

                    # CAN-specific: check for termination resistor
                    if protocol == "CAN":
                        term_resistors = []
                        for c in components:
                            if c["type"] == "resistor":
                                r_n1 = pin_net.get((c["reference"], "1"), (None, None))[0]
                                r_n2 = pin_net.get((c["reference"], "2"), (None, None))[0]
                                if r_n1 and r_n2:
                                    if ({r_n1, r_n2} == {pos_real, neg_real}):
                                        term_resistors.append({
                                            "ref": c["reference"],
                                            "value": c["value"],
                                            "ohms": parsed_values.get(c["reference"]),
                                        })
                        entry["termination"] = term_resistors
                        entry["has_termination"] = len(term_resistors) > 0

                    # Series resistors on either net
                    series_res = []
                    for net_r in (pos_real, neg_real):
                        for p in nets[net_r]["pins"]:
                            comp = comp_lookup.get(p["component"])
                            if comp and comp["type"] == "resistor":
                                series_res.append(p["component"])
                    if series_res:
                        entry["series_resistors"] = sorted(set(series_res))

                    diff_pairs.append(entry)

    # ---- ERC-Style Warnings ----
    erc_warnings = []

    for net_name, net_info in nets.items():
        if is_power_net(net_name) or is_ground(net_name):
            continue
        if net_name.startswith("__unnamed_"):
            continue

        pin_types = [p["pin_type"] for p in net_info["pins"] if not p["component"].startswith("#")]
        type_set = set(pin_types)

        # Input-only net: all pins are inputs, no driver
        outputs = {"output", "tri_state", "power_out", "open_collector", "open_emitter"}
        drivers = {"output", "tri_state", "power_out", "open_collector", "open_emitter", "bidirectional"}
        has_driver = bool(type_set & drivers)
        has_input = bool(type_set & {"input", "power_in"})

        if has_input and not has_driver and len(pin_types) > 1:
            erc_warnings.append({
                "type": "no_driver",
                "net": net_name,
                "message": f"Net '{net_name}' has input pins but no output driver",
                "pins": [p for p in net_info["pins"] if not p["component"].startswith("#")],
            })

        # Multiple outputs on same net (non-tristate)
        hard_outputs = [p for p in net_info["pins"]
                        if p["pin_type"] == "output" and not p["component"].startswith("#")]
        if len(hard_outputs) > 1:
            # Suppress when all drivers are from the same component (paralleled pins)
            driver_components = {p["component"] for p in hard_outputs}
            if len(driver_components) > 1:
                erc_warnings.append({
                    "type": "output_conflict",
                    "net": net_name,
                    "message": f"Net '{net_name}' has {len(hard_outputs)} output drivers (potential conflict)",
                    "drivers": hard_outputs,
                })

    # ---- Passive Ratings Check ----
    # Flag components that might be under-rated based on rail voltage
    passive_warnings = []
    for c in components:
        if c["type"] == "capacitor" and c.get("value"):
            # Check if capacitor voltage rating is in the value string
            val_str = c["value"]
            # Common pattern: "100n/16V", "10u 25V", "22uF 6.3V"
            v_match = re.search(r'(\d+(?:\.\d+)?)\s*[Vv]', val_str)
            if v_match:
                rated_v = float(v_match.group(1))
                # Check which rails this cap connects to
                c_n1, _ = pin_net.get((c["reference"], "1"), (None, None))
                c_n2, _ = pin_net.get((c["reference"], "2"), (None, None))
                # Rough rail voltage estimation from name
                for net in [c_n1, c_n2]:
                    if net:
                        v_est = _estimate_rail_voltage(net)
                        if v_est and rated_v < v_est * 1.5:
                            passive_warnings.append({
                                "component": c["reference"],
                                "value": c["value"],
                                "rated_voltage": rated_v,
                                "rail": net,
                                "estimated_rail_v": v_est,
                                "warning": f"Voltage derating margin < 50% ({rated_v}V rated on ~{v_est}V rail)",
                            })

    return {
        "net_classification": net_classes,
        "power_domains": {
            "ic_power_rails": power_domains,
            "domain_groups": domain_groups,
        },
        "cross_domain_signals": cross_domain,
        "bus_analysis": buses,
        "differential_pairs": diff_pairs,
        "erc_warnings": erc_warnings,
        "passive_warnings": passive_warnings,
    }


def _estimate_rail_voltage(net_name: str) -> float | None:
    """Estimate voltage of a power rail from its name."""
    if not net_name:
        return None
    nu = net_name.upper()
    if nu in ("GND", "VSS", "AGND", "DGND"):
        return 0
    # Parse voltage from name: +3.3V, +5V, +12V, +3V3, +1V8, etc.
    m = re.match(r'\+?(\d+)V(\d+)', nu)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    m = re.match(r'\+?(\d+\.?\d*)V?$', nu)
    if m:
        return float(m.group(1))
    # Common names
    if "3.3" in nu or "3V3" in nu:
        return 3.3
    if "5V" in nu or nu == "+5":
        return 5.0
    if "12V" in nu:
        return 12.0
    if "1.8" in nu or "1V8" in nu:
        return 1.8
    if "2.5" in nu or "2V5" in nu:
        return 2.5
    if "VBUS" in nu or "USB" in nu:
        return 5.0
    return None


def check_annotation_completeness(components: list[dict]) -> dict:
    """Check for annotation issues: duplicate references, unannotated ('?') refs, missing values.

    These are common pre-fabrication mistakes that KiCad's ERC should also catch,
    but detecting them in the script output helps catch them earlier in the workflow.
    """
    # Skip power symbols and flags
    real_components = [c for c in components
                       if c["type"] not in ("power_symbol", "power_flag", "flag")]

    # Duplicate references (same ref, different UUID — not multi-unit which share refs)
    ref_uuids: dict[str, list[str]] = {}
    for c in real_components:
        ref_uuids.setdefault(c["reference"], []).append(c["uuid"])
    # Multi-unit symbols legitimately share a reference, so only flag if the
    # UUIDs come from symbols with unit=None (single-unit) or if there are
    # more instances than expected units
    duplicates = []
    for ref, uuids in ref_uuids.items():
        if len(uuids) > 1:
            # Check if these are multi-unit instances (different unit numbers)
            units = [c.get("unit") for c in real_components if c["reference"] == ref]
            unique_units = set(u for u in units if u is not None)
            if len(unique_units) < len(uuids):
                duplicates.append(ref)

    # Unannotated references (contain '?')
    unannotated = sorted(set(
        c["reference"] for c in real_components if "?" in c["reference"]
    ))

    # Missing values (empty or "~" which KiCad uses as placeholder)
    missing_value = sorted(set(
        c["reference"] for c in real_components
        if c["type"] not in ("test_point", "mounting_hole", "fiducial", "graphic")
        and (not c["value"] or c["value"] == "~")
    ))

    # References that don't follow standard numbering (e.g., R0, C0 — unusual starting point)
    zero_indexed = sorted(set(
        c["reference"] for c in real_components
        if re.match(r'^[A-Z]+0$', c["reference"])
    ))

    result = {}
    if duplicates:
        result["duplicate_references"] = sorted(duplicates)
    if unannotated:
        result["unannotated"] = unannotated
    if missing_value:
        result["missing_value"] = missing_value
    if zero_indexed:
        result["zero_indexed_refs"] = zero_indexed
    return result


def validate_label_shapes(labels: list[dict], nets: dict) -> list[dict]:
    """Validate global/hierarchical label shapes against net signal direction.

    Label shapes (input, output, bidirectional, tri_state, passive) should be
    consistent for the same net name and should match the electrical direction
    of the signals on that net.
    """
    warnings = []

    # Group labels by net name
    net_labels: dict[str, list[dict]] = {}
    for lbl in labels:
        if lbl["type"] in ("global_label", "hierarchical_label") and lbl.get("shape"):
            net_labels.setdefault(lbl["name"], []).append(lbl)

    # Check for shape inconsistency within the same net
    for net_name, lbls in net_labels.items():
        shapes = set(l["shape"] for l in lbls)
        if len(shapes) > 1:
            warnings.append({
                "type": "inconsistent_shape",
                "net": net_name,
                "shapes": sorted(shapes),
                "message": f"Net '{net_name}' has labels with different shapes: {sorted(shapes)}",
            })

    # Check for input-shaped labels on nets driven only by other inputs (no source)
    for net_name, lbls in net_labels.items():
        shapes = set(l["shape"] for l in lbls)
        if shapes == {"input"} and net_name in nets:
            net_info = nets[net_name]
            pin_types = set(p["pin_type"] for p in net_info["pins"]
                           if not p["component"].startswith("#"))
            drivers = {"output", "tri_state", "power_out", "open_collector", "open_emitter", "bidirectional"}
            if not (pin_types & drivers):
                warnings.append({
                    "type": "undriven_input_label",
                    "net": net_name,
                    "message": f"Net '{net_name}' has input-shaped label(s) but no driver pins on the net",
                })

    return warnings


def audit_pwr_flags(components: list[dict], nets: dict, known_power_rails: set) -> list[dict]:
    """Audit power rails for missing PWR_FLAG symbols.

    KiCad requires PWR_FLAG on power nets that are only driven by power_in pins
    (e.g., a connector supplying power). Without PWR_FLAG, ERC reports "power pin
    not driven" errors.
    """
    warnings = []

    # Find nets with PWR_FLAG
    flagged_nets = set()
    for c in components:
        if c["type"] == "power_flag" or (c["type"] == "flag" and "PWR_FLAG" in c.get("lib_id", "")):
            # PWR_FLAG connects to whatever net its pin is on
            for pin in c.get("pins", []):
                px, py = pin["x"], pin["y"]
                # Find which net this pin is on
                for net_name, net_info in nets.items():
                    for p in net_info["pins"]:
                        if p["component"] == c["reference"]:
                            flagged_nets.add(net_name)

    # Check each power rail
    for net_name in known_power_rails:
        if net_name in flagged_nets:
            continue
        if net_name not in nets:
            continue
        net_info = nets[net_name]
        pin_types = set(p["pin_type"] for p in net_info["pins"])

        # If the net has only power_in pins (no power_out), it needs PWR_FLAG
        has_power_out = "power_out" in pin_types
        has_power_in = "power_in" in pin_types

        if has_power_in and not has_power_out:
            warnings.append({
                "net": net_name,
                "message": f"Power rail '{net_name}' has power_in pins but no power_out or PWR_FLAG — ERC will flag this",
                "pin_types": sorted(pin_types),
            })

    return warnings


def validate_footprint_filters(components: list[dict], lib_symbols: dict) -> list[dict]:
    """Validate assigned footprints against library symbol ki_fp_filters.

    If a symbol defines footprint filter patterns (ki_fp_filters), the assigned
    footprint should match at least one pattern. Mismatches suggest wrong footprint
    assignment (e.g., through-hole resistor assigned to SMD symbol).
    """
    import fnmatch
    warnings = []

    for c in components:
        if c["type"] in ("power_symbol", "power_flag", "flag", "test_point",
                          "mounting_hole", "fiducial", "graphic"):
            continue
        if not c["footprint"]:
            continue

        sym_def = lib_symbols.get(c["lib_id"], {})
        fp_filters_str = sym_def.get("ki_fp_filters", "")
        if not fp_filters_str:
            continue

        # ki_fp_filters is a space-separated list of glob patterns
        patterns = fp_filters_str.split()
        if not patterns:
            continue

        # Extract just the footprint name (after the library prefix)
        fp_name = c["footprint"].split(":")[-1] if ":" in c["footprint"] else c["footprint"]
        fp_full = c["footprint"]

        # Check if any pattern matches
        matched = False
        for pat in patterns:
            if fnmatch.fnmatch(fp_name, pat) or fnmatch.fnmatch(fp_full, pat):
                matched = True
                break

        if not matched:
            # Check if the footprint is from a custom/project-local library.
            # Standard KiCad libraries use well-known prefixes; anything else
            # is project-local and mismatches are intentional.
            _STANDARD_FP_LIBS = {
                "Capacitor_SMD", "Capacitor_THT", "Resistor_SMD", "Resistor_THT",
                "Inductor_SMD", "Inductor_THT", "Package_SO", "Package_QFP",
                "Package_DFN_QFN", "Package_BGA", "Package_TO_SOT_SMD",
                "Package_TO_SOT_THT", "Connector_PinHeader", "Connector_PinSocket",
                "Connector_USB", "Crystal", "LED_SMD", "LED_THT", "Diode_SMD",
                "Diode_THT", "RF_Module", "Button_Switch_SMD", "Button_Switch_THT",
                "Fuse", "TestPoint", "Buzzer_Beeper", "Relay_SMD", "Relay_THT",
                "Transformer_SMD", "Transformer_THT", "Varistor", "Jumper",
                "MountingHole", "Fiducial", "Heatsink",
            }
            sym_lib = c["lib_id"].split(":")[0] if ":" in c["lib_id"] else ""
            fp_lib = c["footprint"].split(":")[0] if ":" in c["footprint"] else ""
            custom_library = bool(fp_lib and (
                (sym_lib and sym_lib.lower() == fp_lib.lower())
                or fp_lib not in _STANDARD_FP_LIBS
            ))

            warnings.append({
                "component": c["reference"],
                "footprint": c["footprint"],
                "filters": patterns,
                "custom_library": custom_library,
                "message": f"{c['reference']}: footprint '{fp_name}' doesn't match any filter pattern {patterns}",
            })

    return warnings


def audit_sourcing_fields(components: list[dict]) -> dict:
    """Audit component sourcing completeness: MPN, distributor part numbers.

    For manufacturing readiness, every BOM component needs at minimum an MPN.
    Distributor PNs (DigiKey, Mouser, LCSC) accelerate ordering.
    """
    real = [c for c in components
            if c["type"] not in ("power_symbol", "power_flag", "flag", "test_point",
                                  "mounting_hole", "fiducial", "graphic")
            and c["in_bom"] and not c["dnp"]]

    # Deduplicate by reference (multi-unit symbols)
    seen = set()
    unique = []
    for c in real:
        if c["reference"] not in seen:
            seen.add(c["reference"])
            unique.append(c)

    missing_mpn = [c["reference"] for c in unique if not c.get("mpn")]
    missing_digikey = [c["reference"] for c in unique if not c.get("digikey")]
    missing_mouser = [c["reference"] for c in unique if not c.get("mouser")]
    missing_lcsc = [c["reference"] for c in unique if not c.get("lcsc")]

    total = len(unique)
    result = {
        "total_bom_components": total,
        "mpn_coverage": f"{total - len(missing_mpn)}/{total}",
    }
    if missing_mpn:
        result["missing_mpn"] = sorted(missing_mpn)
    if missing_digikey:
        result["missing_digikey"] = sorted(missing_digikey)
    if missing_lcsc:
        result["missing_lcsc"] = sorted(missing_lcsc)

    # Compute readiness score
    if total > 0:
        mpn_pct = (total - len(missing_mpn)) / total * 100
        result["mpn_percent"] = round(mpn_pct, 1)
    return result


# Generic transistor symbol prefixes that encode assumed pin order
_GENERIC_TRANSISTOR_PREFIXES = ("Q_NPN_", "Q_PNP_", "Q_NMOS_", "Q_PMOS_")

# Map prefix to human-readable type
_GENERIC_TYPE_LABELS = {
    "Q_NPN_": "NPN",
    "Q_PNP_": "PNP",
    "Q_NMOS_": "NMOS",
    "Q_PMOS_": "PMOS",
}

# Map single-letter pin abbreviations to full names
_PIN_LETTER_NAMES = {
    "B": "Base", "C": "Collector", "E": "Emitter",
    "G": "Gate", "S": "Source", "D": "Drain",
}


def check_generic_transistor_symbols(components: list[dict],
                                     schematic_path: str = "") -> list[dict]:
    """Flag transistors using generic KiCad symbols instead of device-specific ones.

    Generic symbols (Q_NPN_BCE, Q_NMOS_GSD, etc.) encode an assumed pin order
    that may not match the actual part. SOT-23 pin mapping varies by manufacturer:
    BCE vs BEC vs CBE for BJTs, GSD vs GDS vs SGD for MOSFETs. Using a generic
    symbol with the wrong pin order produces a board that silently doesn't work.

    Device-specific symbols (MMBT3904, AO3400A) encode the correct pinout for
    that particular part and are always safer.

    If a datasheets/index.json exists next to the schematic, the check also notes
    whether a datasheet is available for manual pinout verification.
    """
    warnings = []

    # Load datasheet index if available
    ds_index: dict[str, dict] = {}
    if schematic_path:
        sch_dir = Path(schematic_path).parent
        idx_path = sch_dir / "datasheets" / "index.json"
        if idx_path.is_file():
            try:
                ds_index = json.loads(idx_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass

    # Deduplicate by reference (multi-unit symbols)
    seen: set[str] = set()

    for c in components:
        if c["type"] != "transistor":
            continue
        ref = c["reference"]
        if ref in seen:
            continue
        seen.add(ref)

        lib_id = c.get("lib_id", "")
        # Extract symbol name (part after the colon)
        sym_name = lib_id.split(":")[-1] if ":" in lib_id else lib_id

        # Check if this is a generic transistor symbol
        matched_prefix = None
        for prefix in _GENERIC_TRANSISTOR_PREFIXES:
            if sym_name.startswith(prefix):
                matched_prefix = prefix
                break

        if matched_prefix is None:
            continue

        # Extract pin order suffix (e.g., "GSD" from "Q_NMOS_GSD")
        pin_suffix = sym_name[len(matched_prefix):]
        sym_type = _GENERIC_TYPE_LABELS.get(matched_prefix, "transistor")

        # Expand pin abbreviations for the message
        pin_names = "-".join(
            _PIN_LETTER_NAMES.get(ch, ch) for ch in pin_suffix
        ) if pin_suffix else pin_suffix

        mpn = c.get("mpn", "")
        value = c.get("value", "")
        footprint = c.get("footprint", "")
        fp_name = footprint.split(":")[-1] if ":" in footprint else footprint

        # Check datasheet availability by MPN
        has_datasheet = False
        if mpn and ds_index:
            # index.json keys may be MPN strings or nested under "components"
            if isinstance(ds_index, dict):
                if mpn in ds_index:
                    has_datasheet = True
                elif "components" in ds_index:
                    comps = ds_index["components"]
                    if isinstance(comps, dict) and mpn in comps:
                        has_datasheet = True
                    elif isinstance(comps, list):
                        has_datasheet = any(
                            e.get("mpn") == mpn for e in comps
                            if isinstance(e, dict)
                        )

        # Build human-readable part identifier
        part_id = mpn or value or "unknown part"

        # Build message
        if has_datasheet:
            action = f"Verify pinout against the {part_id} datasheet (available in datasheets/) or switch to a device-specific symbol."
        elif mpn:
            action = f"Verify pinout against the {part_id} datasheet or switch to a device-specific symbol."
        else:
            action = "Add an MPN and verify pinout against the datasheet, or switch to a device-specific symbol."

        msg = (
            f"{ref}: Generic {sym_type} symbol ({sym_name}) used"
            f"{' for ' + part_id if part_id != 'unknown part' else ''}"
            f"{' in ' + fp_name if fp_name else ''}."
            f" Pin order ({pin_names}) may not match the actual part."
            f" {action}"
        )

        warnings.append({
            "component": ref,
            "lib_id": lib_id,
            "value": value,
            "mpn": mpn,
            "footprint": footprint,
            "symbol_pin_order": pin_suffix,
            "symbol_type": sym_type,
            "has_datasheet": has_datasheet,
            "severity": "warning",
            "message": msg,
        })

    return warnings


def summarize_alternate_pins(lib_symbols: dict) -> list[dict]:
    """Summarize symbols that have alternate pin definitions (dual-function pins).

    Alternate pins are common on MCUs where GPIO pins can serve as SPI/I2C/UART/PWM
    peripherals. This summary helps understand the pin multiplexing capabilities.
    """
    results = []
    for name, sym in lib_symbols.items():
        alts = sym.get("alternates")
        if not alts:
            continue

        pin_summary = []
        for pin_num, alt_list in sorted(alts.items()):
            # Find the primary pin name
            primary_name = ""
            for p in sym["pins"]:
                if p["number"] == pin_num:
                    primary_name = p["name"]
                    break
            pin_summary.append({
                "pin": pin_num,
                "primary": primary_name,
                "alternates": [a["name"] for a in alt_list],
            })

        results.append({
            "symbol": name,
            "pins_with_alternates": len(alts),
            "total_pins": len(sym["pins"]),
            "details": pin_summary,
        })

    return results


def classify_ground_domains(nets: dict, components: list[dict]) -> dict:
    """Classify ground nets into domains: signal, analog, digital, earth, chassis, power.

    Multiple ground domains in a design need careful management — star grounding,
    proper domain separation, and single-point connections between domains.
    """
    ground_nets = {}
    for net_name, net_info in nets.items():
        if not _is_ground_name(net_name):
            continue

        nu = net_name.upper()
        if any(x in nu for x in ("AGND", "GNDA", "VSS_A", "VSSA")):
            domain = "analog"
        elif any(x in nu for x in ("DGND", "GNDD", "VSS_D", "VSSD")):
            domain = "digital"
        elif any(x in nu for x in ("PGND", "GNDPWR", "VSS_P")):
            domain = "power"
        elif any(x in nu for x in ("EARTH", "PE", "FG", "CHASSIS", "SHIELD")):
            domain = "earth/chassis"
        else:
            domain = "signal"

        pin_count = len([p for p in net_info["pins"] if not p["component"].startswith("#")])
        connected_components = sorted(set(
            p["component"] for p in net_info["pins"] if not p["component"].startswith("#")
        ))
        ground_nets[net_name] = {
            "domain": domain,
            "connections": pin_count,
            "components": connected_components,
        }

    domains = {}
    for net_name, info in ground_nets.items():
        d = info["domain"]
        domains.setdefault(d, []).append(net_name)

    result = {"ground_nets": ground_nets}
    if len(domains) > 1:
        result["multiple_domains"] = True
        result["domains"] = domains
        result["note"] = "Multiple ground domains detected — verify proper star/single-point connection between domains"
    else:
        result["multiple_domains"] = False
    return result


def analyze_bus_topology(bus_elements: dict, labels: list[dict], nets: dict) -> dict:
    """Analyze bus structure: which signals are grouped, naming consistency, member coverage.

    Checks that bus aliases have corresponding labels for all members, and that
    bus naming follows consistent patterns (e.g., D[0..7] has labels D0..D7).
    """
    result = {
        "bus_wire_count": len(bus_elements.get("bus_wires", [])),
        "bus_entry_count": len(bus_elements.get("bus_entries", [])),
    }

    aliases = bus_elements.get("bus_aliases", [])
    if aliases:
        alias_info = []
        all_label_names = set(l["name"] for l in labels)
        for alias in aliases:
            members = alias["members"]
            present = [m for m in members if m in all_label_names]
            missing = [m for m in members if m not in all_label_names]
            entry = {
                "name": alias["name"],
                "member_count": len(members),
                "present_labels": len(present),
            }
            if missing:
                entry["missing_labels"] = missing
            alias_info.append(entry)
        result["aliases"] = alias_info

    # Detect bus-like label patterns (D0..D7, ADDR0..ADDR15, etc.)
    bus_patterns: dict[str, list[str]] = {}
    for lbl in labels:
        m = re.match(r'^([A-Za-z_]+)(\d+)$', lbl["name"])
        if m:
            prefix = m.group(1)
            bus_patterns.setdefault(prefix, []).append(lbl["name"])

    detected_buses = []
    for prefix, members in sorted(bus_patterns.items()):
        if len(members) >= 3:  # At least 3 signals to be bus-like
            nums = sorted(int(re.search(r'\d+$', m).group()) for m in members)
            expected = list(range(nums[0], nums[-1] + 1))
            missing_nums = [n for n in expected if n not in nums]
            entry = {
                "prefix": prefix,
                "width": len(members),
                "range": f"{prefix}{nums[0]}..{prefix}{nums[-1]}",
            }
            if missing_nums:
                entry["missing"] = [f"{prefix}{n}" for n in missing_nums]
            detected_buses.append(entry)

    if detected_buses:
        result["detected_bus_signals"] = detected_buses

    return result


def analyze_wire_geometry(wires: list[dict]) -> dict:
    """Analyze wire routing geometry for schematic cleanliness.

    Flags non-orthogonal wires (diagonal), very short wires (possible stubs),
    and computes overall wire statistics.
    """
    if not wires:
        return {"total_wires": 0}

    diagonal = []
    short_wires = []
    total_length = 0.0

    for w in wires:
        dx = abs(w["x2"] - w["x1"])
        dy = abs(w["y2"] - w["y1"])
        length = math.sqrt(dx * dx + dy * dy)
        total_length += length

        # Non-orthogonal: neither horizontal nor vertical (with tolerance)
        is_h = dy < 0.01
        is_v = dx < 0.01
        if not is_h and not is_v and length > 0.1:
            diagonal.append({
                "from": [round(w["x1"], 2), round(w["y1"], 2)],
                "to": [round(w["x2"], 2), round(w["y2"], 2)],
                "length": round(length, 2),
            })

        # Very short wires (< 1mm) — possible stubs or misclicks
        if 0 < length < 1.0:
            short_wires.append({
                "from": [round(w["x1"], 2), round(w["y1"], 2)],
                "to": [round(w["x2"], 2), round(w["y2"], 2)],
                "length": round(length, 3),
            })

    result = {
        "total_wires": len(wires),
        "total_length_mm": round(total_length, 1),
        "avg_length_mm": round(total_length / len(wires), 1) if wires else 0,
    }
    if diagonal:
        result["diagonal_wires"] = diagonal[:20]  # Cap output
        result["diagonal_count"] = len(diagonal)
    if short_wires:
        result["short_wires"] = short_wires[:20]
        result["short_wire_count"] = len(short_wires)
    return result


def check_simulation_readiness(components: list[dict], lib_symbols: dict) -> dict:
    """Check if components have SPICE simulation models assigned.

    KiCad's built-in NGSPICE simulator requires each component to have a
    simulation model (Sim.Type, Sim.Params, etc.) for the circuit to simulate.
    """
    real = [c for c in components
            if c["type"] not in ("power_symbol", "power_flag", "flag",
                                  "test_point", "mounting_hole", "fiducial", "graphic")]

    # Check for Sim_* properties which indicate SPICE model assignment
    # These are stored as component properties but we extracted only standard ones.
    # We can at least check lib_symbol descriptions for SPICE-related keywords.
    has_model_hint = []
    no_model = []

    for c in real:
        sym = lib_symbols.get(c["lib_id"], {})
        desc = (sym.get("description", "") + " " + sym.get("keywords", "")).lower()
        ctype = c["type"]

        # Passives (R, C, L) have built-in SPICE models
        if ctype in ("resistor", "capacitor", "inductor"):
            has_model_hint.append(c["reference"])
        elif "spice" in desc or "simulation" in desc or "sim_" in desc:
            has_model_hint.append(c["reference"])
        elif ctype in ("diode", "led", "transistor"):
            # Common discrete parts — may have models
            has_model_hint.append(c["reference"])
        else:
            no_model.append(c["reference"])

    total = len(real)
    modeled = len(has_model_hint)

    result = {
        "total_components": total,
        "likely_simulatable": modeled,
        "needs_model": len(no_model),
    }
    if no_model:
        result["components_without_model"] = sorted(set(no_model))[:30]
    if total > 0:
        result["simulatable_percent"] = round(modeled / total * 100, 1)
    return result


def audit_property_patterns(components: list[dict]) -> dict:
    """Audit property naming consistency across components.

    Checks that MPN, manufacturer, and distributor fields use consistent
    property names (e.g., not a mix of "MPN" vs "Mfg Part" vs "Part Number").
    Also checks for common data entry issues.
    """
    real = [c for c in components
            if c["type"] not in ("power_symbol", "power_flag", "flag")]

    issues = []

    # Check for value field anomalies
    for c in real:
        val = c.get("value", "")
        ref = c["reference"]

        # Reference designator accidentally used as value
        if val == ref:
            issues.append({
                "component": ref,
                "issue": "value_equals_reference",
                "message": f"{ref}: value is same as reference designator (likely placeholder)",
            })

        # Lib_id used as value (forgot to set value)
        if val and ":" in val and val == c.get("lib_id", ""):
            issues.append({
                "component": ref,
                "issue": "value_is_lib_id",
                "message": f"{ref}: value appears to be the library ID '{val}' (not a real value)",
            })

        # Footprint in the value field
        if val and ("_SMD:" in val or "_THT:" in val or "Resistor_SMD" in val):
            issues.append({
                "component": ref,
                "issue": "value_looks_like_footprint",
                "message": f"{ref}: value '{val}' looks like a footprint, not a component value",
            })

    # Check for MPN/value inconsistency within same BOM group
    # (same value + footprint should have same MPN)
    bom_groups: dict[tuple, list] = {}
    for c in real:
        if c["in_bom"] and not c["dnp"] and c.get("value"):
            key = (c["value"], c["footprint"])
            bom_groups.setdefault(key, []).append(c)

    for key, group in bom_groups.items():
        mpns = set(c["mpn"] for c in group if c["mpn"])
        if len(mpns) > 1:
            refs = sorted(c["reference"] for c in group)
            issues.append({
                "components": refs,
                "issue": "inconsistent_mpn",
                "message": f"Components with value '{key[0]}' / footprint '{key[1]}' have different MPNs: {sorted(mpns)}",
            })

    result = {}
    if issues:
        result["issues"] = issues
        result["issue_count"] = len(issues)
    return result


def spatial_clustering(components: list[dict]) -> dict:
    """Analyze component placement clustering to identify functional groups.

    Groups components by proximity to help identify subcircuit boundaries
    and check for spatial organization of the schematic.
    """
    real = [c for c in components
            if c["type"] not in ("power_symbol", "power_flag", "flag")]

    if not real:
        return {"clusters": []}

    # Simple grid-based clustering: divide the schematic into regions
    xs = [c["x"] for c in real]
    ys = [c["y"] for c in real]

    if not xs or not ys:
        return {"clusters": []}

    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    x_range = x_max - x_min or 1
    y_range = y_max - y_min or 1

    # Use quadrant-based grouping (4x4 grid)
    grid_cols = min(4, max(1, int(x_range / 40)))
    grid_rows = min(4, max(1, int(y_range / 30)))

    cell_w = x_range / grid_cols if grid_cols > 1 else x_range + 1
    cell_h = y_range / grid_rows if grid_rows > 1 else y_range + 1

    grid: dict[tuple, list] = {}
    for c in real:
        col = min(int((c["x"] - x_min) / cell_w), grid_cols - 1)
        row = min(int((c["y"] - y_min) / cell_h), grid_rows - 1)
        grid.setdefault((row, col), []).append(c)

    clusters = []
    for (row, col), members in sorted(grid.items()):
        type_counts: dict[str, int] = {}
        for c in members:
            type_counts[c["type"]] = type_counts.get(c["type"], 0) + 1

        refs = sorted(c["reference"] for c in members)
        clusters.append({
            "region": f"row{row}_col{col}",
            "component_count": len(members),
            "types": type_counts,
            "references": refs if len(refs) <= 20 else refs[:20] + [f"... +{len(refs)-20} more"],
        })

    # Component density and spread statistics
    result = {
        "bounding_box": {
            "x_min": round(x_min, 1), "y_min": round(y_min, 1),
            "x_max": round(x_max, 1), "y_max": round(y_max, 1),
            "width_mm": round(x_range, 1), "height_mm": round(y_range, 1),
        },
        "clusters": clusters,
        "grid_size": f"{grid_rows}x{grid_cols}",
    }
    return result


def verify_pin_coverage(components: list[dict], lib_symbols: dict) -> list[dict]:
    """Verify that all non-NC library pins are accounted for on placed symbols.

    Checks if a placed symbol has fewer pins connected than the library definition
    expects, which could indicate missing connections or wrong unit placement.
    """
    warnings = []

    # Group components by reference (multi-unit symbols)
    ref_components: dict[str, list[dict]] = {}
    for c in components:
        if c["type"] in ("power_symbol", "power_flag", "flag"):
            continue
        ref_components.setdefault(c["reference"], []).append(c)

    for ref, comp_list in ref_components.items():
        c = comp_list[0]  # Use first instance for lib_id lookup
        sym_def = lib_symbols.get(c["lib_id"])
        if not sym_def:
            continue

        lib_pins = sym_def["pins"]
        if not lib_pins:
            continue

        # Count placed pins across all units
        placed_pin_nums = set()
        for comp in comp_list:
            for pin in comp.get("pins", []):
                placed_pin_nums.add(pin.get("number", ""))

        # Count expected pins from library (excluding no-connect type pins)
        expected_pins = set()
        for p in lib_pins:
            if p["type"] != "no_connect":
                expected_pins.add(p["number"])

        missing = expected_pins - placed_pin_nums
        if missing and len(missing) > len(expected_pins) * 0.3:
            # More than 30% of pins missing — likely a real issue
            warnings.append({
                "component": ref,
                "lib_id": c["lib_id"],
                "expected_pins": len(expected_pins),
                "placed_pins": len(placed_pin_nums),
                "missing_count": len(missing),
                "message": f"{ref}: {len(missing)}/{len(expected_pins)} library pins not placed (may need more units or check symbol)",
            })

    return warnings


def check_instance_consistency(components: list[dict]) -> list[dict]:
    """Check multi-unit and multi-instance symbol consistency.

    For multi-unit symbols (e.g., quad op-amp), verify all expected units are placed.
    For multi-instance sheets, verify reference numbering doesn't collide.
    """
    warnings = []

    # Group by lib_id to find multi-unit symbols
    lib_groups: dict[str, list[dict]] = {}
    for c in components:
        if c["type"] in ("power_symbol", "power_flag", "flag"):
            continue
        lib_groups.setdefault(c["lib_id"], []).append(c)

    # Check for partial unit placement
    for lib_id, comp_list in lib_groups.items():
        # Group by reference
        ref_units: dict[str, set[int]] = {}
        for c in comp_list:
            if c["unit"] is not None:
                ref_units.setdefault(c["reference"], set()).add(c["unit"])

        for ref, units in ref_units.items():
            if not units:
                continue
            max_unit = max(units)
            expected = set(range(1, max_unit + 1))
            missing = expected - units
            if missing:
                warnings.append({
                    "component": ref,
                    "lib_id": lib_id,
                    "placed_units": sorted(units),
                    "missing_units": sorted(missing),
                    "message": f"{ref}: units {sorted(missing)} not placed (of {max_unit} total)",
                })

    # Check for reference collisions across sheets
    ref_sheets: dict[str, set] = {}
    for c in components:
        if c["type"] in ("power_symbol", "power_flag", "flag"):
            continue
        sheet = c.get("_sheet", 0)
        ref_sheets.setdefault(c["reference"], set()).add(sheet)

    for ref, sheets in ref_sheets.items():
        if len(sheets) > 1:
            # Same reference on different sheets with different UUIDs
            instances = [c for c in components if c["reference"] == ref]
            uuids = set(c["uuid"] for c in instances)
            units = set(c["unit"] for c in instances if c["unit"] is not None)
            # Multi-unit on different sheets is OK (unit != None and different units)
            if len(uuids) > len(units) and len(units) > 0:
                pass  # Multi-unit, different units — fine
            elif len(uuids) > 1 and not units:
                warnings.append({
                    "component": ref,
                    "sheets": sorted(sheets),
                    "message": f"{ref}: appears on {len(sheets)} sheets with different UUIDs (reference collision?)",
                })

    return warnings


def validate_hierarchical_labels(labels: list[dict], nets: dict) -> dict:
    """Validate hierarchical label usage for cross-sheet connectivity.

    Checks for orphaned hierarchical labels (no matching sheet pin), hierarchical
    labels that don't connect to any net, and naming consistency.
    """
    hier_labels = [l for l in labels if l["type"] == "hierarchical_label"]
    global_labels = [l for l in labels if l["type"] == "global_label"]

    result = {
        "hierarchical_label_count": len(hier_labels),
        "global_label_count": len(global_labels),
    }

    # Check for hierarchical labels that don't appear in any net
    hier_names = set(l["name"] for l in hier_labels)
    global_names = set(l["name"] for l in global_labels)
    net_names = set(nets.keys())

    unconnected_hier = sorted(hier_names - net_names)
    if unconnected_hier:
        result["unconnected_hierarchical"] = unconnected_hier

    # Check for naming conflicts between global and hierarchical labels
    conflicts = sorted(hier_names & global_names)
    if conflicts:
        result["global_hier_name_conflicts"] = conflicts
        result["conflict_warning"] = "Same name used as both global and hierarchical label — may cause unexpected connections"

    # Group global labels by name and check for single-instance labels
    # (a global label used only once is suspicious — it should connect to something)
    global_name_counts: dict[str, int] = {}
    for l in global_labels:
        global_name_counts[l["name"]] = global_name_counts.get(l["name"], 0) + 1

    single_use = sorted(n for n, c in global_name_counts.items() if c == 1)
    if single_use:
        result["single_use_global_labels"] = single_use

    return result


# ---------------------------------------------------------------------------
# Tier 3: High-level design analysis functions
# ---------------------------------------------------------------------------


def analyze_pdn_impedance(components: list[dict], nets: dict, pin_net: dict) -> dict:
    """PDN impedance profiling per power rail.

    Groups all capacitors by power rail, estimates ESR/ESL from package size,
    computes combined impedance at frequency points (1 kHz to 1 GHz), and flags
    frequency gaps and anti-resonances.
    """
    # Package-dependent parasitics
    esl_by_pkg = {
        "0201": 0.2e-9, "0402": 0.3e-9, "0603": 0.5e-9,
        "0805": 0.8e-9, "1206": 1.2e-9, "1210": 1.5e-9,
        "1812": 2.0e-9, "2220": 2.5e-9,
    }
    esr_base_by_pkg = {
        "0201": 0.020, "0402": 0.015, "0603": 0.012,
        "0805": 0.010, "1206": 0.010, "1210": 0.010,
        "1812": 0.010, "2220": 0.010,
    }

    def _extract_package_code(footprint: str) -> str | None:
        if not footprint:
            return None
        # Match common patterns like C_0402_1005Metric, R_0805_...
        m = re.search(r'(\d{4})_\d{4}Metric', footprint)
        if m:
            return m.group(1)
        # Direct 4-digit codes
        m = re.search(r'\b(0201|0402|0603|0805|1206|1210|1812|2220)\b', footprint)
        if m:
            return m.group(1)
        return None

    def _is_electrolytic_or_tantalum(comp: dict) -> bool:
        fp = comp.get("footprint", "").lower()
        val = comp.get("value", "").lower()
        lib = comp.get("lib_id", "").lower()
        combined = fp + " " + val + " " + lib
        if any(k in combined for k in ("electrolytic", "tantalum", "cp_", "c_radial", "c_axial")):
            return True
        # Large THT caps or large values without SMD footprint
        if "tht" in fp or "radial" in fp or "axial" in fp:
            return True
        return False

    def _cap_impedance(f: float, c_farads: float, esr: float, esl: float) -> float:
        x_c = 1.0 / (2.0 * math.pi * f * c_farads) if c_farads > 0 else 1e12
        x_l = 2.0 * math.pi * f * esl
        return math.sqrt(esr ** 2 + (x_l - x_c) ** 2)

    comp_lookup = {c["reference"]: c for c in components}

    # Build power rail -> caps mapping
    rail_caps: dict[str, list[dict]] = {}
    for net_name, net_info in nets.items():
        if net_name.startswith("__unnamed_"):
            continue
        if _is_ground_name(net_name):
            continue
        if not _is_power_net_name(net_name):
            continue

        for p in net_info["pins"]:
            comp = comp_lookup.get(p["component"])
            if not comp or comp["type"] != "capacitor":
                continue
            cap_val = parse_value(comp.get("value", ""))
            if not cap_val or cap_val <= 0:
                continue
            # Check other pin goes to ground
            n1, _ = pin_net.get((p["component"], "1"), (None, None))
            n2, _ = pin_net.get((p["component"], "2"), (None, None))
            other = n2 if n1 == net_name else n1
            if not _is_ground_name(other):
                continue

            pkg = _extract_package_code(comp.get("footprint", ""))
            is_elec = _is_electrolytic_or_tantalum(comp)
            if is_elec:
                esr = max(0.1, 0.5 / math.sqrt(cap_val * 1e6)) if cap_val > 0 else 0.5
                esl = 7.5e-9  # typical 5-10 nH
            elif pkg and pkg in esl_by_pkg:
                esl = esl_by_pkg[pkg]
                base_esr = esr_base_by_pkg.get(pkg, 0.015)
                # ESR scales roughly with 1/sqrt(C in uF), clamped
                c_uf = cap_val * 1e6
                esr = max(0.005, base_esr / math.sqrt(max(c_uf, 0.001)))
            else:
                # Unknown package — assume 0603 MLCC defaults
                esl = 0.5e-9
                c_uf = cap_val * 1e6
                esr = max(0.005, 0.012 / math.sqrt(max(c_uf, 0.001)))

            srf = 1.0 / (2.0 * math.pi * math.sqrt(esl * cap_val)) if esl > 0 and cap_val > 0 else 0

            cap_entry = {
                "ref": p["component"],
                "value": comp["value"],
                "farads": cap_val,
                "package": pkg,
                "esr_ohm": round(esr, 4),
                "esl_nH": round(esl * 1e9, 2),
                "srf_hz": round(srf),
                "srf_formatted": _format_frequency(srf) if srf > 0 else "N/A",
            }
            cap_entry["type"] = "electrolytic/tantalum" if is_elec else "MLCC"

            rail_caps.setdefault(net_name, []).append(cap_entry)

    if not rail_caps:
        return {}

    # Frequency sweep points: 1 kHz to 1 GHz, 10 points per decade
    freq_points = []
    f = 1e3
    while f <= 1.01e9:
        freq_points.append(f)
        f *= 10 ** 0.1  # 10 points per decade

    rails_result = {}
    observations = []

    for rail_name, caps in rail_caps.items():
        # Compute combined impedance at each frequency point
        impedance_profile = []
        for f in freq_points:
            z_parallel_inv = 0.0
            for cap in caps:
                z_i = _cap_impedance(f, cap["farads"], cap["esr_ohm"], cap["esl_nH"] * 1e-9)
                if z_i > 0:
                    z_parallel_inv += 1.0 / z_i
            z_total = 1.0 / z_parallel_inv if z_parallel_inv > 0 else 1e12
            impedance_profile.append({
                "freq_hz": round(f),
                "freq_formatted": _format_frequency(f),
                "impedance_ohm": round(z_total, 6),
            })

        # Find anti-resonance peaks (local maxima in impedance)
        anti_resonances = []
        for i in range(1, len(impedance_profile) - 1):
            z_prev = impedance_profile[i - 1]["impedance_ohm"]
            z_curr = impedance_profile[i]["impedance_ohm"]
            z_next = impedance_profile[i + 1]["impedance_ohm"]
            if z_curr > z_prev and z_curr > z_next:
                anti_resonances.append({
                    "freq_formatted": impedance_profile[i]["freq_formatted"],
                    "freq_hz": impedance_profile[i]["freq_hz"],
                    "impedance_ohm": z_curr,
                })

        # Find min impedance
        min_z = min(impedance_profile, key=lambda x: x["impedance_ohm"])

        rail_result = {
            "capacitors": caps,
            "cap_count": len(caps),
            "total_capacitance_uF": round(sum(c["farads"] for c in caps) * 1e6, 3),
            "impedance_profile": impedance_profile,
            "min_impedance": {
                "freq_formatted": min_z["freq_formatted"],
                "impedance_ohm": min_z["impedance_ohm"],
            },
        }
        if anti_resonances:
            rail_result["anti_resonances"] = anti_resonances
            for ar in anti_resonances:
                if ar["impedance_ohm"] > 1.0:
                    observations.append(
                        f"{rail_name}: anti-resonance at {ar['freq_formatted']} "
                        f"({ar['impedance_ohm']:.3f} ohm) — consider adding cap with SRF near this frequency"
                    )

        # Check for frequency gaps: if all cap SRFs are below 100 MHz,
        # high-frequency decoupling may be lacking
        max_srf = max((c["srf_hz"] for c in caps), default=0)
        if max_srf < 100e6 and len(caps) > 0:
            observations.append(
                f"{rail_name}: highest SRF is {_format_frequency(max_srf)} — "
                f"consider adding small (100pF-1nF) MLCC for >100 MHz coverage"
            )

        rails_result[rail_name] = rail_result

    result = {"rails": rails_result}
    if observations:
        result["observations"] = observations
    return result


def analyze_sleep_current(components: list[dict], nets: dict, pin_net: dict,
                          signal_analysis: dict | None = None) -> dict:
    """Sleep/quiescent current audit.

    Finds all always-on current paths: resistive dividers between power and
    ground, pull-up/pull-down resistors to power rails, LED indicators, and
    regulator quiescent currents (estimated from part family).
    """
    comp_lookup = {c["reference"]: c for c in components}
    rail_currents: dict[str, list[dict]] = {}

    def _get_two_pin_nets(ref: str) -> tuple[str | None, str | None]:
        n1, _ = pin_net.get((ref, "1"), (None, None))
        n2, _ = pin_net.get((ref, "2"), (None, None))
        return n1, n2

    # --- Resistors between power and ground ---
    for comp in components:
        if comp["type"] != "resistor":
            continue
        r_val = parse_value(comp.get("value", ""))
        if not r_val or r_val <= 0:
            continue
        n1, n2 = _get_two_pin_nets(comp["reference"])
        if not n1 or not n2:
            continue

        pwr_net = None
        gnd_net = None
        if _is_power_net_name(n1) and not _is_ground_name(n1) and _is_ground_name(n2):
            pwr_net, gnd_net = n1, n2
        elif _is_power_net_name(n2) and not _is_ground_name(n2) and _is_ground_name(n1):
            pwr_net, gnd_net = n2, n1

        if pwr_net and gnd_net:
            v_rail = _estimate_rail_voltage(pwr_net)
            if v_rail and v_rail > 0:
                current_a = v_rail / r_val
                entry = {
                    "ref": comp["reference"],
                    "value": comp["value"],
                    "type": "resistor_to_gnd",
                    "resistance_ohm": r_val,
                    "rail_voltage": v_rail,
                    "current_uA": round(current_a * 1e6, 2),
                }
                # Check if this is part of a voltage divider (second resistor on the non-gnd side)
                if pwr_net in nets:
                    other_resistors = [
                        p["component"] for p in nets[pwr_net]["pins"]
                        if p["component"] != comp["reference"]
                        and comp_lookup.get(p["component"], {}).get("type") == "resistor"
                    ]
                    if other_resistors:
                        entry["note"] = f"part of divider with {', '.join(other_resistors)}"
                rail_currents.setdefault(pwr_net, []).append(entry)
            continue

        # Pull-up resistor: one side to power rail, other side to a signal net
        if _is_power_net_name(n1) and not _is_ground_name(n1) and not _is_power_net_name(n2):
            pwr_net = n1
        elif _is_power_net_name(n2) and not _is_ground_name(n2) and not _is_power_net_name(n1):
            pwr_net = n2
        else:
            continue

        v_rail = _estimate_rail_voltage(pwr_net)
        if v_rail and v_rail > 0:
            # Pull-up: worst case current is V/R (pin driven low)
            current_a = v_rail / r_val
            rail_currents.setdefault(pwr_net, []).append({
                "ref": comp["reference"],
                "value": comp["value"],
                "type": "pull_up",
                "resistance_ohm": r_val,
                "rail_voltage": v_rail,
                "current_uA": round(current_a * 1e6, 2),
                "note": "worst-case (signal driven low)",
            })

    # --- LEDs with series resistors ---
    for comp in components:
        if comp["type"] != "led":
            continue
        ref = comp["reference"]
        # Find nets connected to LED pins
        led_nets = []
        for pkey, (net_name, _) in pin_net.items():
            if pkey[0] == ref:
                led_nets.append(net_name)

        for net_name in led_nets:
            if not net_name or net_name not in nets:
                continue
            # Find series resistor on same net
            for p in nets[net_name]["pins"]:
                if p["component"] == ref:
                    continue
                r_comp = comp_lookup.get(p["component"])
                if not r_comp or r_comp["type"] != "resistor":
                    continue
                r_val = parse_value(r_comp.get("value", ""))
                if not r_val or r_val <= 0:
                    continue
                # Find what power rail this LED circuit connects to
                r_n1, r_n2 = _get_two_pin_nets(r_comp["reference"])
                for rn in (r_n1, r_n2):
                    if rn and rn != net_name and _is_power_net_name(rn) and not _is_ground_name(rn):
                        v_rail = _estimate_rail_voltage(rn)
                        if v_rail and v_rail > 0:
                            # LED forward voltage ~2V typical
                            v_led = 2.0
                            if v_rail > v_led:
                                current_a = (v_rail - v_led) / r_val
                                rail_currents.setdefault(rn, []).append({
                                    "ref": ref,
                                    "value": comp.get("value", "LED"),
                                    "type": "led_indicator",
                                    "series_resistor": r_comp["reference"],
                                    "resistance_ohm": r_val,
                                    "rail_voltage": v_rail,
                                    "current_uA": round(current_a * 1e6, 2),
                                    "note": "assuming ~2V forward drop, always-on if no switch",
                                })

    # --- Regulator quiescent current estimates ---
    # Use detected regulators from signal analysis to estimate Iq per output rail.
    # These are rough estimates based on part family — actual values depend on
    # load current, switching frequency, and mode (PFM vs PWM).
    _iq_estimates_uA: dict[str, float] = {
        # Part prefix → typical Iq in uA (from datasheets, sleep/shutdown mode)
        "TPS6": 15,      # TPS61xxx/62xxx — ~15-25 uA typical
        "TPS5": 100,     # TPS54xxx — ~100-300 uA typical (not ultra-low-power)
        "LMR51": 24,     # LMR514xx — 24 uA typical
        "LMR33": 25,     # LMR336xx — 24-30 uA
        "RT5": 20,       # Richtek RT56xx — ~20-40 uA
        "AP2112": 55,    # Diodes AP2112 LDO — 55 uA
        "AP6": 20,       # Diodes AP6xxx — ~20 uA
        "MIC29": 500,    # Microchip MIC29xxx — ~500 uA (older LDO)
        "MIC55": 100,    # Microchip MIC55xx — ~100 uA
        "LM317": 5000,   # LM317 — ~5 mA Iq
        "AMS1117": 5000, # AMS1117 — ~5 mA Iq
        "LD1117": 5000,  # LD1117 — ~5 mA Iq
        "XC6": 1,        # Torex XC6xxx — ~0.5-8 uA (ultra low power)
        "TLV71": 3.4,    # TI TLV713/715 — ~3.4 uA
        "TLV75": 18,     # TI TLV757 — ~18 uA
        "NCP1": 50,      # ON Semi NCP1xxx — ~50 uA
    }
    if signal_analysis:
        for reg in signal_analysis.get("power_regulators", []):
            out_rail = reg.get("output_rail", "")
            if not out_rail:
                continue
            # Look up Iq by part prefix
            reg_value = reg.get("value", "").upper()
            reg_lib = reg.get("lib_id", "").split(":")[-1].upper() if ":" in reg.get("lib_id", "") else ""
            iq_ua = None
            for prefix, iq in _iq_estimates_uA.items():
                if reg_value.startswith(prefix.upper()) or reg_lib.startswith(prefix.upper()):
                    iq_ua = iq
                    break
            if iq_ua is None:
                # Default estimate based on topology
                topo = reg.get("topology", "")
                if topo == "LDO":
                    iq_ua = 100  # generic LDO
                elif topo == "switching":
                    iq_ua = 50  # generic switcher
                else:
                    continue

            # Check if regulator has an EN pin that could disable it
            has_en = False
            for comp in components:
                if comp["reference"] == reg["ref"]:
                    for pin in comp.get("pins", []):
                        pn_upper = pin.get("name", "").upper()
                        if pn_upper in ("EN", "ENABLE", "ON/OFF", "ON", "SHDN", "CE"):
                            has_en = True
                            break
                    break

            rail_currents.setdefault(out_rail, []).append({
                "ref": reg["ref"],
                "value": reg.get("value", ""),
                "type": "regulator_iq",
                "current_uA": round(iq_ua, 2),
                "has_enable_pin": has_en,
                "note": f"estimated Iq ({'can be disabled via EN' if has_en else 'always-on, no EN pin detected'})",
            })

    if not rail_currents:
        return {}

    # Summarize per rail
    result_rails = {}
    total_sleep_uA = 0.0
    for rail, entries in rail_currents.items():
        rail_total_uA = sum(e["current_uA"] for e in entries)
        total_sleep_uA += rail_total_uA
        result_rails[rail] = {
            "current_paths": entries,
            "total_uA": round(rail_total_uA, 2),
        }

    return {
        "rails": result_rails,
        "total_estimated_sleep_uA": round(total_sleep_uA, 2),
        "observations": [
            f"Total estimated always-on current: {total_sleep_uA:.1f} uA ({total_sleep_uA / 1000:.2f} mA)"
        ],
    }


def analyze_voltage_derating(components: list[dict], nets: dict,
                             signal_analysis: dict, pin_net: dict) -> dict:
    """Check capacitor voltage ratings against applied rail voltage.

    Parses voltage rating from cap value string (e.g. '100nF/25V' -> 25V),
    compares against the power rail voltage, and flags caps with insufficient
    derating margin.
    """

    def _parse_voltage_rating(value_str: str) -> float | None:
        """Extract voltage rating from value string."""
        if not value_str:
            return None
        # Patterns: "100nF/25V", "10uF 16V", "4.7u/10V/X5R", "100n 50V 0805"
        # Also: "25V", "16V" as standalone segments
        for part in re.split(r'[/\s]+', value_str):
            m = re.match(r'^(\d+\.?\d*)\s*[Vv]$', part.strip())
            if m:
                return float(m.group(1))
        return None

    derating_issues = []
    caps_checked = 0

    for comp in components:
        if comp["type"] != "capacitor":
            continue
        rated_v = _parse_voltage_rating(comp.get("value", ""))
        if not rated_v:
            continue

        ref = comp["reference"]
        # Find which power rail this cap is on
        n1, _ = pin_net.get((ref, "1"), (None, None))
        n2, _ = pin_net.get((ref, "2"), (None, None))

        pwr_net = None
        if n1 and _is_power_net_name(n1) and not _is_ground_name(n1):
            pwr_net = n1
        elif n2 and _is_power_net_name(n2) and not _is_ground_name(n2):
            pwr_net = n2

        if not pwr_net:
            continue

        # Get rail voltage — first try regulators, then name-based estimate
        v_rail = None
        for reg in signal_analysis.get("power_regulators", []):
            if reg.get("output_rail") == pwr_net:
                v_rail = reg.get("estimated_vout")
                break
        if v_rail is None:
            v_rail = _estimate_rail_voltage(pwr_net)
        if v_rail is None or v_rail <= 0:
            continue

        caps_checked += 1
        margin_pct = ((rated_v - v_rail) / rated_v) * 100 if rated_v > 0 else 0
        severity = None
        if v_rail > rated_v:
            severity = "critical"
        elif margin_pct < 20:
            severity = "warning"

        if severity:
            derating_issues.append({
                "ref": ref,
                "value": comp["value"],
                "rail": pwr_net,
                "rail_voltage": v_rail,
                "rated_voltage": rated_v,
                "margin_pct": round(margin_pct, 1),
                "severity": severity,
            })

    if not derating_issues and caps_checked == 0:
        return {}

    result: dict = {
        "caps_checked": caps_checked,
        "issues": derating_issues,
    }
    observations = []
    critical = [i for i in derating_issues if i["severity"] == "critical"]
    warnings = [i for i in derating_issues if i["severity"] == "warning"]
    if critical:
        observations.append(
            f"{len(critical)} cap(s) exceed rated voltage — risk of failure"
        )
    if warnings:
        observations.append(
            f"{len(warnings)} cap(s) have <20% voltage derating margin"
        )
    if observations:
        result["observations"] = observations
    return result


def analyze_power_budget(components: list[dict], nets: dict,
                         signal_analysis: dict, pin_net: dict) -> dict:
    """Power budget estimation per rail.

    Identifies each rail's regulator and max current, counts ICs per rail with
    rough current estimation by type, and estimates thermal dissipation for LDOs.
    """
    comp_lookup = {c["reference"]: c for c in components}

    # Rough current estimates by IC type keywords (mA)
    ic_current_estimates = {
        "esp32": 240, "esp8266": 170, "esp": 200,
        "nrf52": 15, "nrf51": 12, "nrf53": 20, "nrf91": 50,
        "stm32f4": 100, "stm32f1": 50, "stm32l4": 20, "stm32l0": 10,
        "stm32h7": 200, "stm32f7": 150, "stm32": 80,
        "atmega": 20, "attiny": 10, "atsamd": 30, "samd": 30,
        "rp2040": 50, "rp2350": 60,
        "wifi": 250, "wlan": 250, "bluetooth": 50, "ble": 15,
        "lora": 120, "sx127": 120, "sx126": 50,
        "ethernet": 150, "phy": 100, "lan87": 80, "ksz": 100,
        "sensor": 5, "bme": 3, "bmp": 3, "lis": 2, "mpu": 5,
        "flash": 25, "eeprom": 5, "sram": 10,
        "adc": 10, "dac": 10,
        "codec": 30, "amplifier": 20, "opamp": 5,
        "usb": 50, "uart": 5, "spi": 5, "i2c": 5,
    }

    # Build power domain mapping: rail -> list of ICs
    rail_ics: dict[str, list[dict]] = {}
    for comp in components:
        if comp["type"] != "ic":
            continue
        ref = comp["reference"]
        for pkey, (net_name, _) in pin_net.items():
            if pkey[0] != ref:
                continue
            if net_name and _is_power_net_name(net_name) and not _is_ground_name(net_name):
                # Check if this is a power pin (by pin type or name)
                if net_name in nets:
                    for p in nets[net_name]["pins"]:
                        if p["component"] == ref:
                            ptype = p.get("pin_type", "")
                            pname = p.get("pin_name", "").upper()
                            if ptype == "power_in" or pname in (
                                "VCC", "VDD", "AVCC", "AVDD", "VDDIO", "DVDD",
                                "VIN", "VCCA", "VCCB", "VDDQ", "VBUS"
                            ):
                                ic_entry = {
                                    "ref": ref,
                                    "value": comp["value"],
                                }
                                # Estimate current
                                val_lower = comp.get("value", "").lower()
                                lib_lower = comp.get("lib_id", "").lower()
                                search_str = val_lower + " " + lib_lower
                                est_ma = 10  # default
                                for kw, ma in ic_current_estimates.items():
                                    if kw in search_str:
                                        est_ma = ma
                                        break
                                ic_entry["estimated_mA"] = est_ma
                                rail_ics.setdefault(net_name, []).append(ic_entry)
                            break

    # Deduplicate ICs per rail (an IC may have multiple power pins on same rail)
    for rail in rail_ics:
        seen_refs = set()
        deduped = []
        for ic in rail_ics[rail]:
            if ic["ref"] not in seen_refs:
                seen_refs.add(ic["ref"])
                deduped.append(ic)
        rail_ics[rail] = deduped

    # Map regulators to output rails
    reg_by_rail: dict[str, dict] = {}
    for reg in signal_analysis.get("power_regulators", []):
        out_rail = reg.get("output_rail")
        if out_rail:
            reg_by_rail[out_rail] = reg

    if not rail_ics and not reg_by_rail:
        return {}

    # All rails of interest
    all_rails = set(rail_ics.keys()) | set(reg_by_rail.keys())

    rails_result = {}
    observations = []

    for rail in sorted(all_rails):
        ics = rail_ics.get(rail, [])
        total_ic_mA = sum(ic["estimated_mA"] for ic in ics)

        rail_info: dict = {
            "ic_count": len(ics),
            "ics": ics,
            "estimated_load_mA": total_ic_mA,
        }

        reg = reg_by_rail.get(rail)
        if reg:
            rail_info["regulator"] = {
                "ref": reg["ref"],
                "value": reg["value"],
                "topology": reg.get("topology", "unknown"),
            }
            v_out = reg.get("estimated_vout")
            v_in_rail = reg.get("input_rail")
            if v_out:
                rail_info["regulator"]["output_voltage"] = v_out

            # LDO thermal dissipation
            if reg.get("topology") == "LDO" and v_in_rail and v_out:
                v_in = _estimate_rail_voltage(v_in_rail)
                if v_in and v_in > v_out:
                    v_drop = v_in - v_out
                    power_w = v_drop * (total_ic_mA / 1000.0)
                    rail_info["ldo_dissipation"] = {
                        "input_voltage": v_in,
                        "dropout": round(v_drop, 2),
                        "power_mW": round(power_w * 1000, 1),
                    }
                    if power_w > 0.5:
                        observations.append(
                            f"{rail}: LDO {reg['ref']} dissipates ~{power_w * 1000:.0f} mW "
                            f"({v_drop:.1f}V drop x {total_ic_mA} mA) — verify thermal rating"
                        )

        rails_result[rail] = rail_info

    result: dict = {"rails": rails_result}
    if observations:
        result["observations"] = observations
    return result


def analyze_power_sequencing(components: list[dict], nets: dict,
                             signal_analysis: dict, pin_net: dict) -> dict:
    """Power sequencing dependency analysis.

    For each regulator, finds what drives its EN pin and PG (power-good) output,
    builds a dependency graph, and flags floating EN pins.
    """
    comp_lookup = {c["reference"]: c for c in components}
    regulators = signal_analysis.get("power_regulators", [])
    if not regulators:
        return {}

    dependencies = []
    floating_en = []
    pg_connections = []

    for reg in regulators:
        ref = reg["ref"]
        out_rail = reg.get("output_rail", "")
        ic = comp_lookup.get(ref)
        if not ic:
            continue

        # Gather all pins for this IC
        ic_pins: dict[str, tuple[str, str]] = {}  # pin_name -> (net_name, pin_number)
        for pkey, (net_name, _) in pin_net.items():
            if pkey[0] == ref:
                pin_num = pkey[1]
                pin_name = ""
                if net_name in nets:
                    for p in nets[net_name]["pins"]:
                        if p["component"] == ref and p["pin_number"] == pin_num:
                            pin_name = p.get("pin_name", "").upper()
                            break
                ic_pins[pin_name] = (net_name, pin_num)

        # Find EN pin
        en_net = None
        en_pin_name = None
        for pname, (net, pnum) in ic_pins.items():
            pn_base = pname.rstrip("0123456789")
            if pname in ("EN", "ENABLE", "ON", "~{SHDN}", "SHDN", "~{EN}",
                         "CE", "CHIP_ENABLE") or pn_base == "EN":
                en_net = net
                en_pin_name = pname
                break

        if en_net:
            dep_entry: dict = {
                "regulator": ref,
                "output_rail": out_rail,
                "en_pin": en_pin_name,
                "en_net": en_net,
            }

            # Determine what drives EN
            if _is_power_net_name(en_net):
                dep_entry["en_source"] = "always_on"
                dep_entry["en_driven_by"] = en_net
            elif _is_ground_name(en_net):
                dep_entry["en_source"] = "disabled"
                dep_entry["en_driven_by"] = en_net
            elif en_net in nets:
                en_pins = nets[en_net]["pins"]
                # Filter out power symbols and the regulator itself
                drivers = [
                    p for p in en_pins
                    if p["component"] != ref
                    and not p["component"].startswith("#PWR")
                    and not p["component"].startswith("#FLG")
                ]
                if not drivers:
                    dep_entry["en_source"] = "floating"
                    floating_en.append({
                        "regulator": ref,
                        "output_rail": out_rail,
                        "en_pin": en_pin_name,
                        "warning": f"{ref} EN pin ({en_pin_name}) appears unconnected",
                    })
                else:
                    # Check if driven by another regulator's output rail or PG
                    driver_refs = [d["component"] for d in drivers]
                    driver_types = []
                    for dr in drivers:
                        dc = comp_lookup.get(dr["component"])
                        if dc:
                            driver_types.append(dc["type"])
                    # Check if EN is connected to a power rail via resistor
                    has_pull_up = any(
                        comp_lookup.get(d["component"], {}).get("type") == "resistor"
                        for d in drivers
                    )
                    dep_entry["en_source"] = "controlled"
                    dep_entry["en_driven_by"] = driver_refs
                    if has_pull_up:
                        dep_entry["has_pull_up"] = True

            dependencies.append(dep_entry)

        # Find PG/PGOOD pin (exclude ground pads like PGND, AGND, EP/GND)
        for pname, (net, pnum) in ic_pins.items():
            pn_upper = pname.upper()
            # Skip ground/pad pins that false-match on "PG" substring
            if any(g in pn_upper for g in ("GND", "GROUND", "PAD", "EP")):
                continue
            if any(k in pn_upper for k in ("PG", "PGOOD", "POWER_GOOD", "POK")):
                pg_entry: dict = {
                    "regulator": ref,
                    "output_rail": out_rail,
                    "pg_pin": pname,
                    "pg_net": net,
                }
                # Find what PG connects to
                if net in nets:
                    pg_targets = [
                        p["component"] for p in nets[net]["pins"]
                        if p["component"] != ref
                        and not p["component"].startswith("#PWR")
                        and not p["component"].startswith("#FLG")
                    ]
                    if pg_targets:
                        pg_entry["connected_to"] = pg_targets
                        # Check if PG drives another regulator's EN
                        for dep in dependencies:
                            if dep.get("en_net") == net:
                                dep["sequenced_after"] = ref
                                dep["sequence_signal"] = "power_good"
                pg_connections.append(pg_entry)
                break

    if not dependencies and not floating_en and not pg_connections:
        return {}

    result: dict = {}
    if dependencies:
        result["dependencies"] = dependencies
    if floating_en:
        result["floating_en_warnings"] = floating_en
    if pg_connections:
        result["power_good_signals"] = pg_connections

    observations = []
    always_on = [d for d in dependencies if d.get("en_source") == "always_on"]
    controlled = [d for d in dependencies if d.get("en_source") == "controlled"]
    if always_on:
        observations.append(
            f"{len(always_on)} regulator(s) always enabled: "
            + ", ".join(d["regulator"] for d in always_on)
        )
    if controlled:
        observations.append(
            f"{len(controlled)} regulator(s) with controlled enable"
        )
    if floating_en:
        observations.append(
            f"{len(floating_en)} regulator(s) with floating EN pin — may not start"
        )
    if observations:
        result["observations"] = observations

    return result


def analyze_bom_optimization(components: list[dict]) -> dict:
    """BOM consolidation and optimization suggestions.

    Groups components by type, finds near-value resistors that could be
    consolidated, identifies capacitors with same value but different footprints,
    and flags single-use values.
    """
    # Filter to real components
    real = [c for c in components
            if c["type"] not in ("power_symbol", "power_flag", "flag")]

    if not real:
        return {}

    # Group by type
    by_type: dict[str, list[dict]] = {}
    for c in real:
        by_type.setdefault(c["type"], []).append(c)

    unique_counts: dict[str, int] = {}
    consolidation_suggestions = []

    # --- Resistors: find values within 5% of each other ---
    resistors = by_type.get("resistor", [])
    r_values: dict[float, list[str]] = {}  # parsed_value -> [refs]
    for r in resistors:
        val = parse_value(r.get("value", ""))
        if val and val > 0:
            r_values.setdefault(val, []).append(r["reference"])

    unique_counts["resistor"] = len(r_values)

    sorted_r_vals = sorted(r_values.keys())
    for i, v1 in enumerate(sorted_r_vals):
        for v2 in sorted_r_vals[i + 1:]:
            if v2 > v1 * 1.06:
                break  # sorted, so no more within 5%
            pct_diff = abs(v2 - v1) / v1 * 100
            if pct_diff <= 5.0 and pct_diff > 0:
                # Only suggest if consolidating saves a unique value
                refs1 = r_values[v1]
                refs2 = r_values[v2]
                # Suggest the more commonly used value
                keep_val = v1 if len(refs1) >= len(refs2) else v2
                replace_val = v2 if keep_val == v1 else v1
                replace_refs = refs2 if keep_val == v1 else refs1
                consolidation_suggestions.append({
                    "type": "resistor",
                    "suggestion": f"Consolidate {len(replace_refs)} resistor(s) "
                                  f"({', '.join(replace_refs)}) from "
                                  f"{replace_val:.4g} to {keep_val:.4g} ohm "
                                  f"({pct_diff:.1f}% difference)",
                    "current_values": [v1, v2],
                    "refs_to_change": replace_refs,
                })

    # --- Capacitors: same value, different footprints ---
    capacitors = by_type.get("capacitor", [])
    cap_by_value: dict[str, dict[str, list[str]]] = {}  # value_str -> {footprint -> [refs]}
    c_values: dict[float, list[str]] = {}
    for c in capacitors:
        val_str = c.get("value", "")
        fp = c.get("footprint", "") or "unknown"
        cap_by_value.setdefault(val_str, {}).setdefault(fp, []).append(c["reference"])
        val = parse_value(val_str)
        if val and val > 0:
            c_values.setdefault(val, []).append(c["reference"])

    unique_counts["capacitor"] = len(c_values)

    for val_str, fp_map in cap_by_value.items():
        if len(fp_map) > 1:
            total_refs = sum(len(refs) for refs in fp_map.values())
            if total_refs > 1:
                fp_summary = {fp: len(refs) for fp, refs in fp_map.items()}
                consolidation_suggestions.append({
                    "type": "capacitor",
                    "suggestion": f"Capacitor value '{val_str}' used with "
                                  f"{len(fp_map)} different footprints — consider standardizing",
                    "value": val_str,
                    "footprint_breakdown": fp_summary,
                })

    # --- Single-use values (across all passive types) ---
    single_use_values = []
    for comp_type in ("resistor", "capacitor", "inductor"):
        vals: dict[str, int] = {}
        for c in by_type.get(comp_type, []):
            v = c.get("value", "")
            if v:
                vals[v] = vals.get(v, 0) + 1
        for v, count in vals.items():
            if count == 1:
                single_use_values.append({"type": comp_type, "value": v})

    # --- Count unique footprints ---
    all_footprints = set()
    for c in real:
        fp = c.get("footprint", "")
        if fp:
            all_footprints.add(fp)

    result: dict = {
        "unique_value_counts": unique_counts,
        "total_unique_footprints": len(all_footprints),
        "single_use_passive_values": len(single_use_values),
    }
    if consolidation_suggestions:
        result["consolidation_suggestions"] = consolidation_suggestions
    observations = []
    if len(single_use_values) > 5:
        observations.append(
            f"{len(single_use_values)} single-use passive values — "
            f"consider standardizing to reduce BOM line items"
        )
    if consolidation_suggestions:
        observations.append(
            f"{len(consolidation_suggestions)} potential consolidation(s) identified"
        )
    if observations:
        result["observations"] = observations
    return result


def analyze_test_coverage(components: list[dict], nets: dict, pin_net: dict) -> dict:
    """Test point and debug interface coverage analysis.

    Finds test points, checks which key nets have them, and identifies
    debug connectors (SWD, JTAG, UART headers).
    """
    # Find test points
    test_points = []
    tp_nets = set()
    for comp in components:
        ref = comp["reference"]
        fp = comp.get("footprint", "").lower()
        is_tp = (ref.startswith("TP") or
                 "testpoint" in fp or "test_point" in fp or
                 comp.get("value", "").lower() in ("testpoint", "test_point", "tp"))
        if is_tp:
            # Find what net it's on
            for pkey, (net_name, _) in pin_net.items():
                if pkey[0] == ref and net_name:
                    test_points.append({
                        "ref": ref,
                        "net": net_name,
                        "value": comp.get("value", ""),
                    })
                    tp_nets.add(net_name)
                    break

    # Find debug connectors
    debug_connectors = []
    debug_keywords = {
        "swd": ["SWDIO", "SWCLK", "SWO", "NRST"],
        "jtag": ["TDI", "TDO", "TCK", "TMS", "TRST"],
        "uart": ["TX", "RX", "TXD", "RXD"],
    }
    for comp in components:
        if comp["type"] != "connector":
            continue
        ref = comp["reference"]
        val = comp.get("value", "").lower()
        fp = comp.get("footprint", "").lower()
        lib = comp.get("lib_id", "").lower()
        combined = val + " " + fp + " " + lib

        # Collect connected net names for this connector (try pin_net first, fall back to nets dict)
        conn_nets = []
        for pkey, (net_name, _) in pin_net.items():
            if pkey[0] == ref and net_name:
                conn_nets.append(net_name)
        # Fallback: if pin_net gave few results (e.g., pin number collisions with "?"),
        # also scan the nets dict for this connector's connections
        if len(conn_nets) < 3:
            for net_name, net_info in nets.items():
                for p in net_info.get("pins", []):
                    if p["component"] == ref and net_name not in conn_nets:
                        conn_nets.append(net_name)
        conn_nets_upper = [n.upper() for n in conn_nets]

        for iface, expected_pins in debug_keywords.items():
            # Match on connector name/footprint/lib_id OR on connected net names
            name_match = iface in combined or any(p.lower() in combined for p in expected_pins)
            net_match = sum(1 for p in expected_pins if any(p in n for n in conn_nets_upper)) >= 2
            if name_match or net_match:
                debug_connectors.append({
                    "ref": ref,
                    "value": comp.get("value", ""),
                    "interface": iface,
                    "connected_nets": conn_nets,
                })
                break

    # Check key nets without test points
    key_net_patterns = {
        "power_rails": [],
        "i2c": ["SDA", "SCL"],
        "spi": ["MOSI", "MISO", "SCK", "SCLK", "SDI", "SDO"],
        "uart": ["TX", "RX", "TXD", "RXD", "UART"],
        "reset": ["RESET", "RST", "NRST", "~{RST}", "~{RESET}"],
    }

    uncovered_key_nets = []
    for net_name in nets:
        if net_name.startswith("__unnamed_"):
            continue
        if net_name in tp_nets:
            continue

        is_key = False
        category = ""

        # Power rails
        if _is_power_net_name(net_name) and not _is_ground_name(net_name):
            is_key = True
            category = "power_rail"

        # Signal patterns
        if not is_key:
            nu = net_name.upper()
            for cat, patterns in key_net_patterns.items():
                if cat == "power_rails":
                    continue
                for pat in patterns:
                    if pat in nu:
                        is_key = True
                        category = cat
                        break
                if is_key:
                    break

        if is_key:
            uncovered_key_nets.append({
                "net": net_name,
                "category": category,
            })

    result: dict = {
        "test_points": test_points,
        "test_point_count": len(test_points),
        "covered_nets": sorted(tp_nets),
    }
    if debug_connectors:
        result["debug_connectors"] = debug_connectors
    if uncovered_key_nets:
        result["uncovered_key_nets"] = uncovered_key_nets

    observations = []
    if not test_points:
        observations.append("No test points found in design")
    else:
        observations.append(f"{len(test_points)} test point(s) covering {len(tp_nets)} net(s)")
    if not debug_connectors:
        observations.append("No debug connectors (SWD/JTAG/UART) identified")
    if uncovered_key_nets:
        by_cat: dict[str, int] = {}
        for u in uncovered_key_nets:
            by_cat[u["category"]] = by_cat.get(u["category"], 0) + 1
        parts = [f"{count} {cat}" for cat, count in sorted(by_cat.items())]
        observations.append(f"Key nets without test points: {', '.join(parts)}")
    if observations:
        result["observations"] = observations
    return result


def analyze_assembly_complexity(components: list[dict]) -> dict:
    """Assembly complexity scoring.

    Counts components by package type, scores difficulty, and flags
    fine-pitch components.
    """
    real = [c for c in components
            if c["type"] not in ("power_symbol", "power_flag", "flag")]
    if not real:
        return {}

    # Package classification
    hard_smd = {"0201", "01005"}
    medium_hard_smd = {"0402"}
    medium_smd = {"0603", "0805"}
    easy_smd = {"1206", "1210", "1812", "2220", "2512"}

    # IC package patterns
    hard_ic_patterns = ["bga", "wlcsp", "ucsp", "flip_chip"]
    medium_hard_ic_patterns = ["qfn", "dfn", "mlp", "son", "vson", "wson", "udfn"]
    medium_ic_patterns = ["tssop", "msop", "ssop", "lqfp", "tqfp", "qfp"]
    easy_ic_patterns = ["soic", "sop", "sot-23", "sot23", "sot-223", "sot223",
                        "sot-89", "sot89", "sc-70", "sc70", "to-252", "dpak",
                        "to-263", "d2pak", "to-220", "to-92"]

    difficulty_counts: dict[str, int] = {"hard": 0, "medium": 0, "easy": 0}
    package_breakdown: dict[str, int] = {}
    fine_pitch_components = []
    tht_count = 0
    smd_count = 0

    def _extract_package_info(footprint: str) -> tuple[str, str]:
        """Returns (package_name, difficulty)."""
        if not footprint:
            return ("unknown", "medium")
        fp_lower = footprint.lower()

        # Check for THT
        if any(k in fp_lower for k in ("tht", "through_hole", "dip", "to-220", "to-92")):
            return ("THT", "easy")

        # Check SMD passive packages
        m = re.search(r'(\d{4,5})_\d{4,5}Metric', footprint)
        if m:
            pkg = m.group(1)
            if pkg in hard_smd:
                return (pkg, "hard")
            elif pkg in medium_hard_smd:
                return (pkg, "hard")
            elif pkg in medium_smd:
                return (pkg, "medium")
            elif pkg in easy_smd:
                return (pkg, "easy")
            return (pkg, "medium")

        # Check IC packages
        for pat in hard_ic_patterns:
            if pat in fp_lower:
                return (pat.upper(), "hard")
        for pat in medium_hard_ic_patterns:
            if pat in fp_lower:
                return (pat.upper(), "hard")
        for pat in medium_ic_patterns:
            if pat in fp_lower:
                return (pat.upper(), "medium")
        for pat in easy_ic_patterns:
            if pat in fp_lower:
                return (pat.upper(), "easy")

        return ("other_SMD", "medium")

    for comp in real:
        fp = comp.get("footprint", "")
        pkg_name, difficulty = _extract_package_info(fp)

        package_breakdown[pkg_name] = package_breakdown.get(pkg_name, 0) + 1
        difficulty_counts[difficulty] = difficulty_counts.get(difficulty, 0) + 1

        if pkg_name == "THT":
            tht_count += 1
        else:
            smd_count += 1

        # Check for fine pitch (<= 0.5mm)
        if fp:
            fp_lower = fp.lower()
            m = re.search(r'pitch[_\-]?(\d+\.?\d*)', fp_lower)
            if m:
                pitch = float(m.group(1))
                if pitch <= 0.5:
                    fine_pitch_components.append({
                        "ref": comp["reference"],
                        "value": comp.get("value", ""),
                        "footprint": fp,
                        "pitch_mm": pitch,
                    })
            # BGA/QFN often fine pitch
            elif any(k in fp_lower for k in ("bga", "wlcsp")):
                fine_pitch_components.append({
                    "ref": comp["reference"],
                    "value": comp.get("value", ""),
                    "footprint": fp,
                    "pitch_mm": None,
                    "note": "BGA/WLCSP — likely fine pitch",
                })

    # Compute complexity score (0-100)
    total = len(real)
    if total == 0:
        return {}
    score = 0
    score += (difficulty_counts["hard"] / total) * 80
    score += (difficulty_counts["medium"] / total) * 40
    score += (difficulty_counts["easy"] / total) * 10
    # Unique footprint penalty
    unique_fps = len(package_breakdown)
    if unique_fps > 15:
        score += min(20, (unique_fps - 15) * 2)
    score = min(100, round(score))

    result: dict = {
        "total_components": total,
        "smd_count": smd_count,
        "tht_count": tht_count,
        "complexity_score": score,
        "difficulty_breakdown": difficulty_counts,
        "package_breakdown": dict(sorted(package_breakdown.items(), key=lambda x: -x[1])),
        "unique_footprints": unique_fps,
    }
    if fine_pitch_components:
        result["fine_pitch_components"] = fine_pitch_components

    observations = []
    if score >= 70:
        observations.append(f"High assembly complexity (score {score}/100) — professional assembly recommended")
    elif score >= 40:
        observations.append(f"Moderate assembly complexity (score {score}/100)")
    else:
        observations.append(f"Low assembly complexity (score {score}/100) — hand assembly feasible")
    if difficulty_counts["hard"] > 0:
        observations.append(f"{difficulty_counts['hard']} hard-to-solder component(s) (0201/0402/BGA/QFN)")
    if fine_pitch_components:
        observations.append(f"{len(fine_pitch_components)} fine-pitch component(s) requiring stencil/reflow")
    if observations:
        result["observations"] = observations
    return result


def analyze_usb_compliance(components: list[dict], nets: dict,
                           signal_analysis: dict, pin_net: dict) -> dict:
    """USB spec compliance checks.

    Checks USB-C CC pull-downs, D+/D- series resistors, VBUS protection
    and decoupling, and ESD protection ICs.
    """
    comp_lookup = {c["reference"]: c for c in components}

    # Find USB connectors
    usb_connectors = []
    for comp in components:
        if comp["type"] != "connector":
            continue
        val = comp.get("value", "").upper()
        fp = comp.get("footprint", "").upper()
        lib = comp.get("lib_id", "").upper()
        combined = val + " " + fp + " " + lib
        if "USB" in combined:
            is_type_c = any(k in combined for k in ("USB_C", "USBC", "TYPE-C", "TYPE_C", "TYPEC"))
            usb_connectors.append({
                "ref": comp["reference"],
                "value": comp.get("value", ""),
                "is_type_c": is_type_c,
            })

    if not usb_connectors:
        return {}

    checklist = []

    for conn in usb_connectors:
        ref = conn["ref"]
        conn_checks: dict = {
            "connector": ref,
            "value": conn["value"],
            "is_type_c": conn["is_type_c"],
            "checks": {},
        }

        # Gather connector pin nets
        conn_pin_nets: dict[str, str] = {}  # pin_name -> net_name
        for pkey, (net_name, _) in pin_net.items():
            if pkey[0] == ref and net_name:
                # Find pin name
                if net_name in nets:
                    for p in nets[net_name]["pins"]:
                        if p["component"] == ref and p["pin_number"] == pkey[1]:
                            pname = p.get("pin_name", "").upper()
                            conn_pin_nets[pname] = net_name
                            break

        # --- CC1/CC2 pull-down check (Type-C only) ---
        if conn["is_type_c"]:
            cc1_ok = False
            cc2_ok = False
            for pname, net_name in conn_pin_nets.items():
                if "CC1" not in pname and "CC2" not in pname:
                    continue
                is_cc1 = "CC1" in pname
                # Check for 5.1k pull-down to GND on this net
                if net_name in nets:
                    for p in nets[net_name]["pins"]:
                        rc = comp_lookup.get(p["component"])
                        if not rc or rc["type"] != "resistor":
                            continue
                        r_val = parse_value(rc.get("value", ""))
                        if r_val and 4800 <= r_val <= 5600:
                            # Check other side goes to GND
                            rn1, _ = pin_net.get((rc["reference"], "1"), (None, None))
                            rn2, _ = pin_net.get((rc["reference"], "2"), (None, None))
                            other = rn2 if rn1 == net_name else rn1
                            if _is_ground_name(other):
                                if is_cc1:
                                    cc1_ok = True
                                else:
                                    cc2_ok = True
            conn_checks["checks"]["cc1_pulldown_5k1"] = "pass" if cc1_ok else "fail"
            conn_checks["checks"]["cc2_pulldown_5k1"] = "pass" if cc2_ok else "fail"

        # --- D+/D- series resistors ---
        dp_net = None
        dm_net = None
        for pname, net_name in conn_pin_nets.items():
            if pname in ("D+", "DP", "D_P", "USB_DP"):
                dp_net = net_name
            elif pname in ("D-", "DM", "D_M", "USB_DM", "DN", "D_N"):
                dm_net = net_name

        dp_series_r = False
        dm_series_r = False
        for data_net, is_dp in [(dp_net, True), (dm_net, False)]:
            if not data_net or data_net not in nets:
                continue
            for p in nets[data_net]["pins"]:
                rc = comp_lookup.get(p["component"])
                if not rc or rc["type"] != "resistor":
                    continue
                r_val = parse_value(rc.get("value", ""))
                if r_val and 20 <= r_val <= 33:
                    if is_dp:
                        dp_series_r = True
                    else:
                        dm_series_r = True

        if dp_net or dm_net:
            conn_checks["checks"]["dp_series_resistor"] = "pass" if dp_series_r else "info"
            conn_checks["checks"]["dm_series_resistor"] = "pass" if dm_series_r else "info"

        # --- VBUS protection and decoupling ---
        vbus_net = None
        for pname, net_name in conn_pin_nets.items():
            if pname in ("VBUS", "V+", "VCC", "VUSB"):
                vbus_net = net_name
                break

        if vbus_net and vbus_net in nets:
            # ESD/TVS on VBUS
            has_esd = False
            has_decoupling = False
            for p in nets[vbus_net]["pins"]:
                pc = comp_lookup.get(p["component"])
                if not pc:
                    continue
                if pc["type"] == "diode":
                    val_lower = pc.get("value", "").lower()
                    lib_lower = pc.get("lib_id", "").lower()
                    if any(k in val_lower or k in lib_lower
                           for k in ("tvs", "esd", "smaj", "smbj", "p6ke")):
                        has_esd = True
                if pc["type"] == "capacitor":
                    has_decoupling = True

            conn_checks["checks"]["vbus_esd_protection"] = "pass" if has_esd else "fail"
            conn_checks["checks"]["vbus_decoupling"] = "pass" if has_decoupling else "fail"

        # --- USB ESD protection ICs ---
        esd_ic_found = False
        esd_keywords = ("usblc", "prtr5v", "ip4", "sp0", "tpd", "esd", "pesd",
                        "rclamp", "nup", "lesd")
        for comp_c in components:
            if comp_c["type"] not in ("ic", "diode"):
                continue
            combined_lower = (comp_c.get("value", "") + " " + comp_c.get("lib_id", "")).lower()
            if any(k in combined_lower for k in esd_keywords):
                # Check if it's connected to a USB data net
                for pkey, (net_name, _) in pin_net.items():
                    if pkey[0] == comp_c["reference"]:
                        if net_name in (dp_net, dm_net, vbus_net):
                            esd_ic_found = True
                            break
                if esd_ic_found:
                    break

        conn_checks["checks"]["usb_esd_ic"] = "pass" if esd_ic_found else "info"

        checklist.append(conn_checks)

    # Summarize
    all_checks: dict[str, int] = {"pass": 0, "fail": 0, "info": 0}
    for conn_c in checklist:
        for status in conn_c["checks"].values():
            all_checks[status] = all_checks.get(status, 0) + 1

    observations = []
    if all_checks["fail"] > 0:
        observations.append(f"{all_checks['fail']} USB compliance check(s) failed")
    if all_checks["pass"] > 0:
        observations.append(f"{all_checks['pass']} USB compliance check(s) passed")
    if all_checks["info"] > 0:
        observations.append(f"{all_checks['info']} USB check(s) informational (optional)")

    result: dict = {
        "connectors": checklist,
        "summary": all_checks,
    }
    if observations:
        result["observations"] = observations
    return result


def analyze_inrush_current(components: list[dict], nets: dict,
                           signal_analysis: dict, pin_net: dict) -> dict:
    """Inrush current estimation.

    For each regulator, finds total output capacitance and estimates inrush
    current. Flags rails where output capacitance may cause startup issues.
    """
    comp_lookup = {c["reference"]: c for c in components}
    regulators = signal_analysis.get("power_regulators", [])
    if not regulators:
        return {}

    rails_result = []
    observations = []

    for reg in regulators:
        out_rail = reg.get("output_rail")
        if not out_rail or out_rail not in nets:
            continue

        # Find total output capacitance on this rail
        total_cap_f = 0.0
        output_caps = []
        for p in nets[out_rail]["pins"]:
            comp = comp_lookup.get(p["component"])
            if not comp or comp["type"] != "capacitor":
                continue
            cap_val = parse_value(comp.get("value", ""))
            if not cap_val or cap_val <= 0:
                continue
            # Check other pin goes to ground
            n1, _ = pin_net.get((comp["reference"], "1"), (None, None))
            n2, _ = pin_net.get((comp["reference"], "2"), (None, None))
            other = n2 if n1 == out_rail else n1
            if _is_ground_name(other):
                total_cap_f += cap_val
                output_caps.append({
                    "ref": comp["reference"],
                    "value": comp["value"],
                    "farads": cap_val,
                })

        if not output_caps:
            continue

        v_out = reg.get("estimated_vout") or _estimate_rail_voltage(out_rail)
        if not v_out or v_out <= 0:
            continue

        rail_entry: dict = {
            "regulator": reg["ref"],
            "output_rail": out_rail,
            "output_voltage": v_out,
            "topology": reg.get("topology", "unknown"),
            "output_caps": output_caps,
            "total_output_capacitance_uF": round(total_cap_f * 1e6, 2),
        }

        # Estimate inrush: I = C * dV/dt
        # For a typical soft-start time of ~1ms for switching regs, ~0.5ms for LDOs
        if reg.get("topology") == "LDO":
            soft_start_s = 0.5e-3
        else:
            soft_start_s = 1.0e-3

        inrush_a = total_cap_f * v_out / soft_start_s
        rail_entry["estimated_inrush_A"] = round(inrush_a, 3)
        rail_entry["assumed_soft_start_ms"] = round(soft_start_s * 1e3, 1)

        # Flag if inrush is high
        if inrush_a > 1.0:
            rail_entry["concern"] = "high_inrush"
            observations.append(
                f"{out_rail}: estimated inrush {inrush_a:.2f}A with "
                f"{total_cap_f * 1e6:.0f}uF output capacitance — "
                f"verify regulator can handle, consider soft-start"
            )
        elif inrush_a > 0.5:
            rail_entry["concern"] = "moderate_inrush"
            observations.append(
                f"{out_rail}: moderate inrush {inrush_a:.2f}A with "
                f"{total_cap_f * 1e6:.0f}uF output capacitance"
            )

        rails_result.append(rail_entry)

    if not rails_result:
        return {}

    result: dict = {"rails": rails_result}
    if observations:
        result["observations"] = observations
    return result


def analyze_schematic(path: str) -> dict:
    """Main analysis function. Returns complete structured data.

    For hierarchical designs (multi-sheet), recursively parses all sub-sheets
    and merges connectivity. Global and hierarchical labels connect nets across sheets.
    """
    # Detect legacy format
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        first_line = f.readline().strip()

    if first_line.startswith("EESchema"):
        return parse_legacy_schematic(path)

    # Parse root sheet and all sub-sheets recursively.
    # Multi-instance support: a sub-sheet file can be referenced multiple times
    # by the parent (e.g., 3 identical half-bridge phases). Each instance has a
    # unique UUID in the parent's (sheet) block. Component references are
    # remapped per instance via the (instances) block in each symbol, OR via
    # the centralized (symbol_instances) section in the root schematic.
    all_components = []
    all_wires = []
    all_labels = []
    all_junctions = []
    all_no_connects = []
    all_lib_symbols = {}
    all_text_annotations = []
    all_bus_elements = []
    root_title_block = {}
    sheets_parsed = []

    # Pre-parse root schematic's (symbol_instances) for fallback remapping.
    # Some KiCad projects (especially migrated ones) store instance-to-reference
    # mappings only here, not inline in each symbol's (instances) block.
    root_tree = parse_file(path)
    root_symbol_instances = extract_symbol_instances(root_tree)

    # Queue items are (file_path, instance_path). instance_path is the
    # hierarchical path prefix matching (symbol_instances) format:
    #   "" for root sheet (symbols have path "/<sym_uuid>")
    #   "/<sheet_uuid>" for direct child sheets
    #   "/<sheet_uuid>/<child_uuid>" for nested sheets
    to_parse = [(str(Path(path).resolve()), "")]
    parsed = set()  # Track (file_path, instance_path) pairs

    while to_parse:
        sheet_path, inst_path = to_parse.pop(0)
        parse_key = (sheet_path, inst_path)
        if parse_key in parsed:
            continue
        parsed.add(parse_key)

        (root, components, wires, labels, junctions, no_connects,
         sub_sheets, lib_symbols, text_annotations, bus_elements, title_block) = \
            parse_single_sheet(sheet_path, instance_uuid=inst_path,
                               symbol_instances=root_symbol_instances)

        # Tag elements with sheet index so coordinate-based net building
        # keeps each sheet's coordinate space separate (prevents false merges
        # when different sheets have wires at the same coordinates).
        sheet_idx = len(sheets_parsed)
        for c in components:
            c["_sheet"] = sheet_idx
        for w in wires:
            w["_sheet"] = sheet_idx
        for l in labels:
            l["_sheet"] = sheet_idx
        for j in junctions:
            j["_sheet"] = sheet_idx

        all_components.extend(components)
        all_wires.extend(wires)
        all_labels.extend(labels)
        all_junctions.extend(junctions)
        all_no_connects.extend(no_connects)
        all_lib_symbols.update(lib_symbols)
        all_text_annotations.extend(text_annotations)
        all_bus_elements.append(bus_elements)
        if sheet_idx == 0:
            root_title_block = title_block
        sheets_parsed.append(sheet_path)

        for sub_path, sub_uuid in sub_sheets:
            sub_resolved = str(Path(sub_path).resolve())
            # Build full hierarchical path for the child sheet
            child_path = inst_path + "/" + sub_uuid if sub_uuid else inst_path
            if (sub_resolved, child_path) not in parsed:
                to_parse.append((sub_resolved, child_path))

    # Merge bus elements across sheets
    merged_bus = {"bus_wires": [], "bus_entries": [], "bus_aliases": []}
    for be in all_bus_elements:
        merged_bus["bus_wires"].extend(be.get("bus_wires", []))
        merged_bus["bus_entries"].extend(be.get("bus_entries", []))
        merged_bus["bus_aliases"].extend(be.get("bus_aliases", []))

    power_symbols = extract_power_symbols(all_components)

    # Build net map across all sheets
    nets = build_net_map(all_components, all_wires, all_labels, power_symbols, all_junctions)

    # Generate BOM
    bom = generate_bom(all_components)

    # Build pin-to-net map once, shared by all analysis functions
    pin_net = build_pin_to_net_map(nets)

    # Identify subcircuits
    subcircuits = identify_subcircuits(all_components, nets, pin_net=pin_net)

    # Detailed IC pinout analysis for datasheet cross-referencing
    ic_analysis = analyze_ic_pinouts(all_components, nets, all_no_connects, pin_net=pin_net)

    # Analyze connectivity for issues
    connectivity_issues = analyze_connectivity(all_components, nets, all_no_connects)

    # Signal path and filter analysis
    signal_analysis = analyze_signal_paths(all_components, nets, all_lib_symbols, pin_net=pin_net)

    # Deep EE analysis: power domains, buses, differential pairs, ERC
    design_analysis = analyze_design_rules(all_components, nets, all_no_connects, signal_analysis, pin_net=pin_net)

    # ---- New Tier 1 + Tier 2 analyses ----

    # Build known_power_rails for PWR_FLAG audit (same logic as in analyze_design_rules)
    known_power_rails = set()
    for net_name, net_info in nets.items():
        for p in net_info.get("pins", []):
            if p["component"].startswith("#PWR") or p["component"].startswith("#FLG"):
                known_power_rails.add(net_name)
                break

    annotation_issues = check_annotation_completeness(all_components)
    label_shape_warnings = validate_label_shapes(all_labels, nets)
    pwr_flag_warnings = audit_pwr_flags(all_components, nets, known_power_rails)
    fp_filter_warnings = validate_footprint_filters(all_components, all_lib_symbols)
    sourcing_audit = audit_sourcing_fields(all_components)
    alternate_pins = summarize_alternate_pins(all_lib_symbols)
    ground_domains = classify_ground_domains(nets, all_components)
    bus_topology = analyze_bus_topology(merged_bus, all_labels, nets)
    wire_geometry = analyze_wire_geometry(all_wires)
    sim_readiness = check_simulation_readiness(all_components, all_lib_symbols)
    property_issues = audit_property_patterns(all_components)
    placement = spatial_clustering(all_components)
    pin_coverage = verify_pin_coverage(all_components, all_lib_symbols)
    instance_issues = check_instance_consistency(all_components)
    hier_label_analysis = validate_hierarchical_labels(all_labels, nets)
    generic_sym_warnings = check_generic_transistor_symbols(all_components, str(path))

    # ---- Tier 3: High-level design analyses ----
    pdn_analysis = analyze_pdn_impedance(all_components, nets, pin_net)
    sleep_current = analyze_sleep_current(all_components, nets, pin_net, signal_analysis)
    voltage_derating = analyze_voltage_derating(all_components, nets, signal_analysis, pin_net)
    power_budget = analyze_power_budget(all_components, nets, signal_analysis, pin_net)
    power_sequencing = analyze_power_sequencing(all_components, nets, signal_analysis, pin_net)
    bom_optimization = analyze_bom_optimization(all_components)
    test_coverage = analyze_test_coverage(all_components, nets, pin_net)
    assembly_complexity = analyze_assembly_complexity(all_components)
    usb_compliance = analyze_usb_compliance(all_components, nets, signal_analysis, pin_net)
    inrush_analysis = analyze_inrush_current(all_components, nets, signal_analysis, pin_net)

    # Add parsed numeric values to all passive components
    for comp in all_components:
        if comp["type"] in ("resistor", "capacitor", "inductor", "ferrite_bead", "crystal"):
            pv = parse_value(comp.get("value", ""))
            if pv is not None:
                comp["parsed_value"] = pv

    # Statistics
    stats = compute_statistics(all_components, nets, bom, all_wires, all_no_connects)

    # Version info from root sheet (already parsed above)
    version = get_value(root_tree, "version") or "unknown"
    generator_version = get_value(root_tree, "generator_version") or "unknown"

    result = {
        "file": str(path),
        "kicad_version": generator_version,
        "file_version": version,
        "title_block": root_title_block,
        "statistics": stats,
        "bom": bom,
        "components": [
            {k: v for k, v in c.items() if k != "pins"}
            for c in all_components
            if c["type"] not in ("power_symbol", "power_flag", "flag")
        ],
        "nets": nets,
        "subcircuits": subcircuits,
        "ic_pin_analysis": ic_analysis,
        "signal_analysis": signal_analysis,
        "design_analysis": design_analysis,
        "connectivity_issues": connectivity_issues,
        "labels": all_labels,
        "no_connects": all_no_connects,
        "power_symbols": power_symbols,
        "annotation_issues": annotation_issues,
        "label_shape_warnings": label_shape_warnings,
        "pwr_flag_warnings": pwr_flag_warnings,
        "footprint_filter_warnings": fp_filter_warnings,
        "sourcing_audit": sourcing_audit,
        "ground_domains": ground_domains,
        "bus_topology": bus_topology,
        "wire_geometry": wire_geometry,
        "simulation_readiness": sim_readiness,
        "property_issues": property_issues,
        "placement_analysis": placement,
        "hierarchical_labels": hier_label_analysis,
    }

    # Only include non-empty optional sections
    if all_text_annotations:
        result["text_annotations"] = all_text_annotations
    if alternate_pins:
        result["alternate_pin_summary"] = alternate_pins
    if pin_coverage:
        result["pin_coverage_warnings"] = pin_coverage
    if instance_issues:
        result["instance_consistency_warnings"] = instance_issues
    if generic_sym_warnings:
        result["generic_symbol_warnings"] = generic_sym_warnings
    if pdn_analysis:
        result["pdn_impedance"] = pdn_analysis
    if sleep_current:
        result["sleep_current_audit"] = sleep_current
    if voltage_derating:
        result["voltage_derating"] = voltage_derating
    if power_budget:
        result["power_budget"] = power_budget
    if power_sequencing:
        result["power_sequencing"] = power_sequencing
    if bom_optimization:
        result["bom_optimization"] = bom_optimization
    if test_coverage:
        result["test_coverage"] = test_coverage
    if assembly_complexity:
        result["assembly_complexity"] = assembly_complexity
    if usb_compliance:
        result["usb_compliance"] = usb_compliance
    if inrush_analysis:
        result["inrush_analysis"] = inrush_analysis

    if len(sheets_parsed) > 1:
        result["sheets"] = sheets_parsed

    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="KiCad Schematic Analyzer")
    parser.add_argument("schematic", help="Path to .kicad_sch file")
    parser.add_argument("--output", "-o", help="Output JSON file (default: stdout)")
    parser.add_argument("--compact", action="store_true", help="Compact JSON output")
    args = parser.parse_args()

    result = analyze_schematic(args.schematic)

    indent = None if args.compact else 2
    output = json.dumps(result, indent=indent, default=str)

    if args.output:
        Path(args.output).write_text(output)
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
