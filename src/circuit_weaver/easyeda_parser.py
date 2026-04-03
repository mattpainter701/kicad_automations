"""EasyEDA symbol parser — convert tilde-delimited shapes to ComponentDef.

Parses the shape strings returned by the EasyEDA API and converts them
into circuit_weaver's internal ComponentDef representation with PinDefs,
power pin classification, and category inference.

The EasyEDA shape format uses tilde (~) delimiters within shapes and
double-caret (^^) delimiters between pin sub-fields.

Reference: https://github.com/jvanderberg/kicad_jlcimport (MIT)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from .component_db import ComponentDef, PinDef

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Intermediate dataclasses
# ---------------------------------------------------------------------------


@dataclass
class EEPin:
    """Parsed EasyEDA pin."""

    name: str
    number: str
    electrical_type: int  # 0=unspecified, 1=input, 2=output, 3=bidirectional, 4=power_in
    x: float
    y: float
    rotation: float  # degrees
    name_visible: bool = True
    number_visible: bool = True


@dataclass
class EESymbol:
    """Parsed EasyEDA symbol (all units combined)."""

    pins: list[EEPin] = field(default_factory=list)
    # Metadata from head.c_para
    prefix: str = "U"
    name: str = ""
    mpn: str = ""
    manufacturer: str = ""
    package: str = ""
    description: str = ""
    lcsc_id: str = ""
    datasheet_url: str = ""


# ---------------------------------------------------------------------------
# EasyEDA electrical type → KiCad type mapping
# ---------------------------------------------------------------------------

_EE_ELEC_TYPE_MAP = {
    0: "unspecified",
    1: "input",
    2: "output",
    3: "bidirectional",
    4: "power_in",
}


# ---------------------------------------------------------------------------
# Pin name → power classification heuristics
# ---------------------------------------------------------------------------

_POWER_PIN_PATTERNS = re.compile(
    r"^(VCC|VDD|VDDIO|AVDD|DVDD|VCCA|VDDA|V_IN|VIN|VBAT|VSYS|VBUS|VCC_IO|AVCC|DVCC)$",
    re.IGNORECASE,
)

_GND_PIN_PATTERNS = re.compile(
    r"^(GND|VSS|AVSS|DVSS|AGND|DGND|PGND|EPAD|EP|EXPOSED)$",
    re.IGNORECASE,
)


def _is_power_pin(name: str, elec_type: int) -> bool:
    """Check if a pin is a power supply pin based on name and type."""
    if elec_type == 4:  # EasyEDA power_in type
        return True
    return bool(_POWER_PIN_PATTERNS.match(name) or _GND_PIN_PATTERNS.match(name))


def _is_gnd_pin(name: str) -> bool:
    return bool(_GND_PIN_PATTERNS.match(name))


# ---------------------------------------------------------------------------
# Shape parsers
# ---------------------------------------------------------------------------


def _parse_pin(shape_str: str) -> EEPin | None:
    """Parse a pin shape string.

    Format: P~show~<elec>~<num>~<x>~<y>~<rot>~<id>~<flags>
            ^^<endpoint_x>~<endpoint_y>
            ^^M <svg_path>~<color>
            ^^<visible>~<name_x>~<name_y>~<name_rot>~<name>~<align>~~~<color>
            ^^<visible>~<num_x>~<num_y>~<num_rot>~<number>~<align>~~~<color>
            ^^...
    """
    parts = shape_str.split("^^")
    if not parts:
        return None

    main = parts[0].split("~")
    if len(main) < 7 or main[0] != "P":
        return None

    try:
        elec_type = int(main[2]) if main[2].isdigit() else 0
        pin_number = main[3]
        x = float(main[4])
        y = float(main[5])
        rotation = float(main[6])
    except (ValueError, IndexError):
        return None

    # Extract pin name and number from sub-fields
    # The sub-fields after the path contain name and number labels
    pin_name = ""
    pin_num_label = ""
    name_visible = True
    number_visible = True

    for sub in parts[1:]:
        fields = sub.split("~")
        # Skip SVG path entries (start with M, L, h, etc.) and color-only entries
        if not fields or len(fields) < 5:
            continue
        # Check if this is a label sub-field: <visible>~<x>~<y>~<rot>~<text>~<align>
        if fields[0] in ("0", "1") and len(fields) >= 6:
            visible = fields[0] == "1"
            text = fields[4]
            align = fields[5] if len(fields) > 5 else ""

            if not text:
                continue

            # Heuristic: "start" align = pin name (left-aligned near symbol body),
            # "end" align = pin number (right-aligned near pin endpoint)
            # But this varies — for right-side pins it's reversed.
            # More reliable: if the text matches the main field pin_number, it's the number.
            if text == pin_number:
                pin_num_label = text
                number_visible = visible
            elif not pin_name:
                pin_name = text
                name_visible = visible
            elif not pin_num_label:
                # Second non-matching text is likely the number
                pin_num_label = text
                number_visible = visible

    # Use the main field pin_number as canonical
    if not pin_name:
        pin_name = "~"  # Unnamed pin

    return EEPin(
        name=pin_name,
        number=pin_number,
        electrical_type=elec_type,
        x=x,
        y=y,
        rotation=rotation,
        name_visible=name_visible,
        number_visible=number_visible,
    )


def _rotation_to_side(rotation: float) -> str:
    """Convert EasyEDA pin rotation to KiCad symbol side.

    EasyEDA rotation: 0=pointing right (pin on right side of body),
    180=pointing left (pin on left side of body),
    90=pointing down (pin on bottom), 270=pointing up (pin on top).

    KiCad side convention: L=pin on left of box, R=pin on right, etc.
    """
    angle = int(rotation) % 360
    # Pin rotation → side of symbol body the pin is on
    # 0° = pin points right → pin is on the RIGHT side of the body
    # 180° = pin points left → pin is on the LEFT side of the body
    return {0: "R", 180: "L", 90: "B", 270: "T"}.get(angle, "L")


# ---------------------------------------------------------------------------
# Symbol assembly
# ---------------------------------------------------------------------------


def parse_symbol_shapes(shapes_per_unit: list[list[str]], metadata: dict | None = None) -> EESymbol:
    """Parse EasyEDA symbol shape strings into an EESymbol.

    Args:
        shapes_per_unit: List of shape string lists, one per symbol unit.
        metadata: Optional dict with keys from EasyEDA head.c_para.

    Returns:
        EESymbol with extracted pins and metadata.
    """
    meta = metadata or {}
    prefix_raw = meta.get("pre", "U?")
    prefix = prefix_raw.rstrip("?")

    symbol = EESymbol(
        prefix=prefix,
        name=meta.get("name", ""),
        mpn=meta.get("Manufacturer Part", "") or meta.get("mpn", ""),
        manufacturer=meta.get("Manufacturer", "") or meta.get("brand", ""),
        package=meta.get("package", ""),
        description=meta.get("des", "") or meta.get("description", ""),
        lcsc_id=meta.get("Supplier Part", "") or meta.get("lcsc", ""),
        datasheet_url=meta.get("link", "") or meta.get("datasheet", ""),
    )

    seen_pins = set()  # Deduplicate by pin number

    for unit_shapes in shapes_per_unit:
        for shape_str in unit_shapes:
            if not shape_str.startswith("P~"):
                continue
            pin = _parse_pin(shape_str)
            if pin and pin.number not in seen_pins:
                symbol.pins.append(pin)
                seen_pins.add(pin.number)

    return symbol


# ---------------------------------------------------------------------------
# EESymbol → ComponentDef conversion
# ---------------------------------------------------------------------------

# Footprint mapping: EasyEDA package string → KiCad footprint
_PACKAGE_FOOTPRINT_MAP = {
    "SOT-23": "Package_TO_SOT_SMD:SOT-23",
    "SOT-23-3": "Package_TO_SOT_SMD:SOT-23",
    "SOT-23-5": "Package_TO_SOT_SMD:SOT-23-5",
    "SOT-23-6": "Package_TO_SOT_SMD:SOT-23-6",
    "SOT-223": "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
    "SOP-8": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
    "SOIC-8": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
    "SOIC-16": "Package_SO:SOIC-16_3.9x9.9mm_P1.27mm",
    "TSSOP-8": "Package_SO:TSSOP-8_3x3mm_P0.65mm",
    "TSSOP-16": "Package_SO:TSSOP-16_4.4x5mm_P0.65mm",
    "MSOP-8": "Package_SO:MSOP-8_3x3mm_P0.65mm",
    "QFN-16": "Package_DFN_QFN:QFN-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm",
    "QFN-20": "Package_DFN_QFN:QFN-20-1EP_4x4mm_P0.5mm_EP2.5x2.5mm",
    "QFN-24": "Package_DFN_QFN:QFN-24-1EP_4x4mm_P0.5mm_EP2.5x2.5mm",
    "QFN-32": "Package_DFN_QFN:QFN-32-1EP_5x5mm_P0.5mm_EP3.5x3.5mm",
    "QFN-48": "Package_DFN_QFN:QFN-48-1EP_7x7mm_P0.5mm_EP5.3x5.3mm",
    "LQFP-48": "Package_QFP:LQFP-48_7x7mm_P0.5mm",
    "LQFP-64": "Package_QFP:LQFP-64_10x10mm_P0.5mm",
    "LQFP-100": "Package_QFP:LQFP-100_14x14mm_P0.5mm",
    "LQFP-144": "Package_QFP:LQFP-144_20x20mm_P0.5mm",
    "DIP-8": "Package_DIP:DIP-8_W7.62mm",
    "DIP-16": "Package_DIP:DIP-16_W7.62mm",
    "TO-220-3": "Package_TO_SOT_THT:TO-220-3_Vertical",
    "TO-252-2": "Package_TO_SOT_SMD:TO-252-2",
    "SC-70-5": "Package_TO_SOT_SMD:SC-70-5",
}

# Passive footprint mapping
_PASSIVE_PACKAGE_MAP = {
    "0201": ("0201", "0603Metric"),
    "0402": ("0402", "1005Metric"),
    "0603": ("0603", "1608Metric"),
    "0805": ("0805", "2012Metric"),
    "1206": ("1206", "3216Metric"),
    "1210": ("1210", "3225Metric"),
    "2010": ("2010", "5025Metric"),
    "2512": ("2512", "6332Metric"),
}


def _infer_footprint_from_package(package: str, prefix: str, pin_count: int) -> str:
    """Map EasyEDA package string to KiCad footprint."""
    if not package:
        return ""

    # Direct match — check longer (more specific) keys first to avoid
    # "SOT-23" matching before "SOT-23-5"
    pkg_upper = package.upper()
    for key, fp in sorted(_PACKAGE_FOOTPRINT_MAP.items(), key=lambda kv: -len(kv[0])):
        if key.upper() in pkg_upper:
            return fp

    # Passive component package (e.g., "C0402", "R0805", "L1206")
    for size_code, (imperial, metric) in _PASSIVE_PACKAGE_MAP.items():
        if size_code in package:
            if prefix == "R":
                return f"Resistor_SMD:R_{imperial}_{metric}"
            elif prefix == "C":
                return f"Capacitor_SMD:C_{imperial}_{metric}"
            elif prefix == "L":
                return f"Inductor_SMD:L_{imperial}_{metric}"
            # Default to resistor-style for unknown prefix
            return f"Resistor_SMD:R_{imperial}_{metric}"

    # QFN/QFP with pin count extraction
    qfn_match = re.search(r"QFN[- ]?(\d+)", pkg_upper)
    if qfn_match:
        n = qfn_match.group(1)
        fp_key = f"QFN-{n}"
        if fp_key in _PACKAGE_FOOTPRINT_MAP:
            return _PACKAGE_FOOTPRINT_MAP[fp_key]

    lqfp_match = re.search(r"LQFP[- ]?(\d+)", pkg_upper)
    if lqfp_match:
        n = lqfp_match.group(1)
        fp_key = f"LQFP-{n}"
        if fp_key in _PACKAGE_FOOTPRINT_MAP:
            return _PACKAGE_FOOTPRINT_MAP[fp_key]

    # SOT-23 variants by pin count
    if "SOT-23" in pkg_upper or "SOT23" in pkg_upper:
        if pin_count == 5:
            return "Package_TO_SOT_SMD:SOT-23-5"
        elif pin_count == 6:
            return "Package_TO_SOT_SMD:SOT-23-6"
        return "Package_TO_SOT_SMD:SOT-23"

    return ""


# Category inference from EasyEDA metadata
_CATEGORY_KEYWORDS = {
    "power": ["regulator", "ldo", "buck", "boost", "pmic", "converter", "charge pump", "power"],
    "mcu": ["mcu", "microcontroller", "soc", "processor", "stm32", "esp32", "rp2040", "nrf52", "atmega"],
    "sensor": ["sensor", "imu", "accel", "gyro", "baro", "temp", "humid", "pressure", "proximity"],
    "analog": ["op amp", "opamp", "amplifier", "comparator", "adc", "dac", "analog"],
    "communication": ["uart", "spi", "i2c", "can", "rs485", "rs232", "transceiver", "interface"],
    "rf": ["wifi", "bluetooth", "ble", "lora", "rf", "wireless", "antenna"],
    "discrete": ["mosfet", "bjt", "transistor", "fet", "diode", "tvs", "esd"],
    "clock": ["oscillator", "crystal", "clock", "timer", "rtc"],
    "storage": ["flash", "eeprom", "sram", "memory", "sd card"],
    "connector": ["connector", "header", "socket", "jack", "usb", "pin"],
    "usb": ["usb hub", "usb controller", "usb phy"],
    "ethernet": ["ethernet", "phy", "rj45", "lan"],
    "protection": ["protection", "tvs", "esd", "fuse", "varistor", "surge"],
    "passive": ["resistor", "capacitor", "inductor", "ferrite"],
}


def _infer_category(prefix: str, name: str, description: str, package: str) -> str:
    """Infer component category from EasyEDA metadata."""
    # Prefix-based (most reliable for passives)
    if prefix in ("R",):
        return "passive"
    if prefix in ("C",):
        return "passive"
    if prefix in ("L",):
        return "passive"
    if prefix in ("J", "P"):
        return "connector"
    if prefix in ("D",):
        return "discrete"
    if prefix in ("Q",):
        return "discrete"
    if prefix == "Y":
        return "clock"

    # Keyword-based from description and name
    search_text = f"{name} {description}".lower()
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in search_text for kw in keywords):
            return cat

    return "digital"  # Default


def easyeda_to_component_def(data: dict) -> ComponentDef | None:
    """Convert EasyEDA API response to a ComponentDef.

    Args:
        data: Dict from fetch_easyeda_component() with symbol_shapes, metadata.

    Returns:
        ComponentDef with pins, power classification, footprint, and category.
        None if parsing fails.
    """
    if not data or not data.get("symbol_shapes"):
        return None

    # Extract metadata — it may be in the top level (from our API client)
    # or nested in head.c_para (from raw EasyEDA response)
    meta = {
        "pre": data.get("prefix", "U"),
        "name": data.get("title", ""),
        "Manufacturer Part": data.get("mpn", ""),
        "Manufacturer": data.get("manufacturer", ""),
        "package": data.get("package", ""),
        "des": data.get("description", ""),
        "Supplier Part": data.get("lcsc_id", ""),
        "link": data.get("datasheet_url", ""),
    }

    # Parse symbol shapes
    symbol = parse_symbol_shapes(data["symbol_shapes"], meta)

    if not symbol.pins:
        log.warning("No pins parsed for %s", data.get("lcsc_id", "?"))
        return None

    prefix = symbol.prefix or "U"
    name = symbol.mpn or symbol.name or data.get("lcsc_id", "UNKNOWN")

    # Convert EEPins to PinDefs and classify power/signal
    pin_defs = []
    power_pins = {}
    pin_nets = {}

    for ee_pin in symbol.pins:
        side = _rotation_to_side(ee_pin.rotation)
        kicad_type = _EE_ELEC_TYPE_MAP.get(ee_pin.electrical_type, "unspecified")

        # Classify power pins by name heuristic (EasyEDA often marks everything as type 0)
        is_power = _is_power_pin(ee_pin.name, ee_pin.electrical_type)

        if is_power:
            kicad_type = "power_in"
            if _is_gnd_pin(ee_pin.name):
                power_pins[ee_pin.number] = "GND"
            else:
                pname = ee_pin.name.upper()
                if "3V3" in pname or "3.3" in pname:
                    power_pins[ee_pin.number] = "VDD_3P3"
                elif "5V" in pname or "VBUS" in pname:
                    power_pins[ee_pin.number] = "VBUS_5V"
                elif "1V8" in pname or "1.8" in pname:
                    power_pins[ee_pin.number] = "VDD_1P8"
                else:
                    power_pins[ee_pin.number] = ee_pin.name
        elif ee_pin.name and ee_pin.name not in ("~", "NC"):
            pin_nets[ee_pin.number] = ee_pin.name

        pin_defs.append(
            PinDef(
                number=ee_pin.number,
                name=ee_pin.name,
                electrical_type=kicad_type,
                side=side,
            )
        )

    # Infer footprint and category
    footprint = _infer_footprint_from_package(symbol.package, prefix, len(pin_defs))
    category = _infer_category(prefix, name, symbol.description, symbol.package)
    description = symbol.description or f"Imported from EasyEDA ({data.get('lcsc_id', '')})"

    return ComponentDef(
        mpn=name,
        ref_prefix=prefix,
        value=data.get("title", name),
        footprint=footprint,
        description=description,
        category=category,
        source_mpn=symbol.mpn,
        source_manufacturer=symbol.manufacturer,
        pins=pin_defs,
        pin_nets=pin_nets,
        power_pins=power_pins,
        features=[f"LCSC:{symbol.lcsc_id}"] if symbol.lcsc_id else [],
        annotations=[f"EasyEDA import ({symbol.lcsc_id})"],
    )
