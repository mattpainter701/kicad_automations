"""KiCad symbol library parser + downloader.

Parses .kicad_sym files to automatically extract ComponentDef objects
with full pin definitions. Eliminates manual pin entry for any component
in KiCad's 10,000+ symbol library.

Uses kiutils (pip install kiutils) as primary parser for KiCad 10 format.
Falls back to regex-based parser for KiCad 9 or if kiutils is unavailable.

Library sources:
1. Local KiCad install (auto-detected by platform)
2. Local .kicad_sym files (any path)
3. KiCad official GitHub library (downloaded + cached)

Usage:
    from schematic_engine.kicad_lib import KiCadLibrary
    lib = KiCadLibrary()
    lib.add_path("/usr/share/kicad/symbols")           # local KiCad install
    lib.add_file("my_custom.kicad_sym")                 # single file
    lib.download_github_lib("Regulator_Linear")         # from KiCad GitHub

    comp = lib.get_component("AMS1117-3.3")             # → ComponentDef
    comp = lib.get_component("ESP32-WROOM-32E", lib="RF_Module")
"""

import os
import platform
import re
from pathlib import Path

from .component_db import ComponentDef, PinDef

# Try importing kiutils — preferred parser for KiCad 10
try:
    from kiutils.symbol import SymbolLib as _KiUtilsSymbolLib

    _HAS_KIUTILS = True
except ImportError:
    _HAS_KIUTILS = False


# ================================================================
# .kicad_sym parser (dual backend: kiutils preferred, regex fallback)
# ================================================================


def _parse_with_kiutils(filepath: str) -> dict[str, dict]:
    """Parse .kicad_sym using kiutils (handles KiCad 10 format natively)."""
    lib = _KiUtilsSymbolLib.from_file(filepath)
    symbols = {}
    for sym in lib.symbols:
        name = sym.entryName
        # Collect pins from all units
        pins = []
        for unit in sym.units:
            for p in unit.pins:
                side = {0: "L", 180: "R", 90: "B", 270: "T"}.get(int(p.position.angle), "L")
                pins.append(
                    PinDef(
                        number=str(p.number),
                        name=p.name or "~",
                        electrical_type=p.electricalType or "passive",
                        side=side,
                    )
                )
        # Collect properties
        properties = {}
        for prop in sym.properties:
            properties[prop.key] = prop.value
        symbols[name] = {
            "pins": pins,
            "properties": properties,
            "raw": "",  # kiutils doesn't preserve raw text
            "extends": sym.extends if hasattr(sym, "extends") else None,
        }
    return symbols


def parse_kicad_sym_file(filepath: str) -> dict[str, dict]:
    """Parse a .kicad_sym file and extract all symbol definitions.

    Uses kiutils for KiCad 10 format, falls back to regex for KiCad 9
    or if kiutils fails (e.g. on files with unusual bracket nesting).

    Returns: {symbol_name: {"pins": [...], "properties": {...}, "raw": str, "extends": str|None}}
    """
    filepath = Path(filepath)
    if not filepath.exists():
        return {}

    # Try kiutils first (better KiCad 10 support, extracts Description, handles extends)
    if _HAS_KIUTILS:
        try:
            result = _parse_with_kiutils(str(filepath))
            if result:
                return result
        except Exception:
            pass  # Fall through to regex parser

    content = filepath.read_text(encoding="utf-8")
    symbols = {}

    # Find all top-level symbol definitions
    # KiCad 9 uses 2-space indent, KiCad 10 uses tab indent
    pos = 0
    while True:
        match = re.search(r'\n[\t ]+\(symbol "([^"]+)"', content[pos:])
        if not match:
            break

        sym_name = match.group(1)
        # Skip sub-symbols (e.g. "NAME_0_1", "NAME_1_1")
        if re.match(r".+_\d+_\d+$", sym_name):
            pos += match.end()
            continue

        # Extract the full symbol S-expression by matching parentheses
        sym_start = pos + match.start() + 1
        paren_start = content.index("(", sym_start)
        depth = 0
        sym_end = paren_start
        for i, ch in enumerate(content[paren_start:], start=paren_start):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    sym_end = i + 1
                    break

        raw = content[paren_start:sym_end]

        # Check for 'extends' — child symbol inherits pins from parent
        extends_match = re.search(r'\(extends "([^"]+)"\)', raw)

        # Extract pins
        pins = _extract_pins(raw)

        # Extract properties
        properties = _extract_properties(raw)

        symbols[sym_name] = {
            "pins": pins,
            "properties": properties,
            "raw": raw,
            "extends": extends_match.group(1) if extends_match else None,
        }

        pos = sym_end

    return symbols


def _extract_pins(symbol_text: str) -> list[PinDef]:
    """Extract all pin definitions from a symbol's S-expression.

    Handles both KiCad 9 (single-line) and KiCad 10 (multi-line, tab-indented) formats.
    """
    pins = []

    # KiCad 9 format (single-line compressed):
    # (pin TYPE STYLE (at X Y ANGLE) (length L) (name "NAME" ...) (number "NUM" ...))
    pin_pattern_v9 = re.compile(
        r"\(pin\s+(\w+)\s+\w+\s+"
        r"\(at\s+([-\d.]+)\s+([-\d.]+)\s+"
        r"(\d+)\)\s+"
        r"\(length\s+([-\d.]+)\)\s*"
        r'\(name\s+"([^"]*)"\s.*?\)\s*'
        r'\(number\s+"([^"]*)"\s',
        re.DOTALL,
    )

    # KiCad 10 format (multi-line, tab/space indented):
    # (pin TYPE STYLE\n  (at X Y ANGLE)\n  (length L)\n  (name "NAME"\n  ...)\n  (number "NUM"\n  ...))
    pin_pattern_v10 = re.compile(
        r"\(pin\s+(\w+)\s+\w+\s*\n"  # (pin TYPE STYLE
        r"[^)]*?\(at\s+([-\d.]+)\s+"  # (at X
        r"([-\d.]+)\s+"  # Y
        r"(\d+)\)"  # ANGLE)
        r"[^)]*?\(length\s+([-\d.]+)\)"  # (length L)
        r'[^)]*?\(name\s+"([^"]*)"'  # (name "NAME"
        r'[^)]*?\(number\s+"([^"]*)"',  # (number "NUM"
        re.DOTALL,
    )

    # Try both patterns
    matches = list(pin_pattern_v9.finditer(symbol_text))
    if not matches:
        matches = list(pin_pattern_v10.finditer(symbol_text))

    for m in matches:
        elec_type = m.group(1)
        pin_angle = int(m.group(4))
        pin_name = m.group(6)
        pin_number = m.group(7)

        side = {0: "L", 180: "R", 90: "B", 270: "T"}.get(pin_angle, "L")

        pins.append(
            PinDef(
                number=pin_number,
                name=pin_name,
                electrical_type=elec_type,
                side=side,
            )
        )

    return pins


def _extract_properties(symbol_text: str) -> dict[str, str]:
    """Extract property key-value pairs from a symbol."""
    props = {}
    for m in re.finditer(r'\(property\s+"([^"]+)"\s+"([^"]*)"', symbol_text):
        props[m.group(1)] = m.group(2)
    return props


# Library-name prefix → category mapping for KiCad symbol libraries
_LIB_CATEGORY_MAP = {
    "Regulator_Linear": "power",
    "Regulator_Switching": "power",
    "Regulator_Controller": "power",
    "Power_Management": "power",
    "Power_Protection": "protection",
    "Power_Supervisor": "power",
    "Sensor": "sensor",
    "Amplifier": "analog",
    "Comparator": "analog",
    "Transistor": "discrete",
    "Diode": "discrete",
    "Driver": "power",
    "Motor_Driver": "power",
    "LED_Driver": "power",
    "Timer": "analog",
    "Converter": "analog",
    "Interface": "communication",
    "Interface_USB": "usb",
    "Interface_Ethernet": "ethernet",
    "Interface_CAN": "communication",
    "MCU": "mcu",
    "RF_Module": "rf",
    "RF": "rf",
    "Connector": "connector",
    "Memory": "storage",
    "Logic": "digital",
    "Oscillator": "clock",
    "Crystal": "clock",
    "Display": "digital",
    "Relay": "discrete",
    "Switch": "connector",
}


def _infer_category_from_lib(lib_name: str | None) -> str | None:
    """Infer component category from the KiCad library name."""
    if not lib_name:
        return None
    for prefix, cat in _LIB_CATEGORY_MAP.items():
        if lib_name == prefix or lib_name.startswith(prefix + "_"):
            return cat
    return None


def _infer_footprint(name: str, pins: list[PinDef], properties: dict) -> str:
    """Heuristic footprint inference when the symbol has none."""
    fp = properties.get("Footprint", "").strip()
    if fp:
        return fp
    ref = properties.get("Reference", "U")
    n = len(pins)
    name_up = name.upper()
    if ref in ("R", "C", "L"):
        pkg = "0402"
        return {
            "R": f"Resistor_SMD:R_{pkg}_1005Metric",
            "C": f"Capacitor_SMD:C_{pkg}_1005Metric",
            "L": f"Inductor_SMD:L_{pkg}_1005Metric",
        }[ref]
    if n == 3 and ("SOT" in name_up or ref == "Q"):
        return "Package_TO_SOT_SMD:SOT-23"
    if n == 5 and "SOT-23" in name_up:
        return "Package_TO_SOT_SMD:SOT-23-5"
    if n == 8 and any(kw in name_up for kw in ("SOIC", "SOP", "DIP")):
        return "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
    if n == 2 and ref == "D":
        return "Diode_SMD:D_SOD-123"
    return ""


def symbol_to_component_def(
    name: str, sym_data: dict, category: str = "digital", lib_name: str | None = None
) -> ComponentDef:
    """Convert a parsed symbol into a ComponentDef.

    Auto-classifies power pins and signal pins based on electrical type.
    Uses the source library name for better category inference.
    """
    pins = sym_data["pins"]
    properties = sym_data["properties"]

    # Separate power pins from signal pins
    power_pins = {}
    pin_nets = {}
    for pin in pins:
        pname = pin.name.upper()

        # Detect power pins by electrical type OR by name pattern
        is_power_type = pin.electrical_type in ("power_in", "power_out")
        is_gnd_name = bool(re.match(
            r"^(GND|VSS|AVSS|DVSS|AGND|DGND|PGND|EPAD|EP|EXPOSED)$",
            pname,
        ))
        is_vdd_name = bool(re.match(
            r"^(VCC|VDD|VDDIO|AVDD|DVDD|VCCA|VDDA|V_?IN|VBAT|VSYS|VBUS|"
            r"VCC_IO|AVCC|DVCC|VDDCORE|VDDA_\w+|VDD_\w+|VCC_\w+)$",
            pname,
        ))

        if is_power_type or is_gnd_name or is_vdd_name:
            if is_gnd_name:
                power_pins[pin.number] = "GND"
            elif "3V3" in pname or "3.3" in pname or "3P3" in pname:
                power_pins[pin.number] = "VDD_3P3"
            elif "5V" in pname or pname == "VBUS":
                power_pins[pin.number] = "VBUS_5V"
            elif "1V8" in pname or "1.8" in pname or "1P8" in pname:
                power_pins[pin.number] = "VDD_1P8"
            elif "1V2" in pname or "1.2" in pname or "1P2" in pname:
                power_pins[pin.number] = "VDD_1P2"
            elif "2V5" in pname or "2.5" in pname or "2P5" in pname:
                power_pins[pin.number] = "VDD_2P5"
            else:
                power_pins[pin.number] = pin.name
        elif pin.electrical_type != "passive" or pin.name not in ("~", "NC"):
            if pin.name and pin.name not in ("~", "NC"):
                pin_nets[pin.number] = pin.name

    # 1. Library-name-based classification (most reliable)
    lib_cat = _infer_category_from_lib(lib_name)
    if lib_cat:
        category = lib_cat

    # 2. Ref-prefix-based classification
    ref_prefix = properties.get("Reference", "U")
    if not lib_cat:
        if ref_prefix in ("J", "P"):
            category = "connector"
        elif ref_prefix == "D":
            category = "discrete"
        elif ref_prefix == "Q":
            category = "discrete"
        elif ref_prefix in ("C", "R", "L"):
            category = "passive"

    # 3. Description/name keyword classification (lowest priority)
    desc = (properties.get("Description", "") + " " + properties.get("Datasheet", "") + " " + name).lower()
    if not lib_cat:
        if any(kw in desc for kw in ("regulator", "ldo", "buck", "boost", "pmic", "converter")):
            category = "power"
        elif any(kw in desc for kw in ("op amp", "opamp", "amplifier", "comparator")):
            category = "analog"
        elif any(kw in desc for kw in ("mcu", "microcontroller", "soc", "processor")):
            category = "mcu"
        elif any(kw in desc for kw in ("sensor", "imu", "accel", "gyro", "baro", "temp", "humid")):
            category = "sensor"
        elif any(kw in desc for kw in ("mosfet", "bjt", "transistor", "fet", "jfet", "igbt")):
            category = "discrete"
        elif any(kw in desc for kw in ("tvs", "esd", "protection", "fuse", "varistor")):
            category = "protection"
        elif any(kw in desc for kw in ("driver", "gate driver", "half-bridge", "h-bridge")):
            category = "power"

    footprint = _infer_footprint(name, pins, properties)
    description = properties.get("Description", "") or "Imported from KiCad library"

    return ComponentDef(
        mpn=name,
        ref_prefix=ref_prefix,
        value=properties.get("Value", name),
        footprint=footprint,
        description=description,
        category=category,
        pins=pins,
        pin_nets=pin_nets,
        power_pins=power_pins,
    )


# ================================================================
# KiCad library manager
# ================================================================

# Standard KiCad install paths by platform
_KICAD_LIB_PATHS = {
    "Windows": [
        Path("C:/Program Files/KiCad/10.0/share/kicad/symbols"),
        Path("C:/Program Files/KiCad/9.0/share/kicad/symbols"),
        Path("C:/Program Files/KiCad/8.0/share/kicad/symbols"),
    ],
    "Linux": [
        Path("/usr/share/kicad/symbols"),
        Path("/usr/local/share/kicad/symbols"),
    ],
    "Darwin": [
        Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"),
        Path("/usr/local/share/kicad/symbols"),
    ],
}

# KiCad GitLab raw content base URL (moved from GitHub in 2020)
# KiCad 10+ uses .kicad_symdir/ with one file per symbol
KICAD_GITLAB_RAW = "https://gitlab.com/kicad/libraries/kicad-symbols/-/raw/master"
KICAD_GITLAB_API = "https://gitlab.com/api/v4/projects/kicad%2Flibraries%2Fkicad-symbols"

# Common library files and what they contain
KICAD_LIBRARY_INDEX = {
    "Regulator_Linear": "LDO regulators (AMS1117, AP2112, TLV755, MCP1700, etc.)",
    "Regulator_Switching": "Buck/boost converters (TPS63020, AP62300, RT6150, etc.)",
    "MCU_Microchip_ATmega": "ATmega MCUs (ATmega328P, ATmega2560, etc.)",
    "MCU_ST_STM32F1": "STM32F1 series (STM32F103, etc.)",
    "MCU_ST_STM32F4": "STM32F4 series (STM32F401, STM32F411, etc.)",
    "MCU_RaspberryPi_RP2040": "RP2040 and Pico",
    "MCU_Nordic_nRF52": "nRF52 series (nRF52832, nRF52840)",
    "MCU_Espressif_ESP32": "ESP32 modules and chips",
    "RF_Module": "WiFi/BT/LoRa modules (ESP32-WROOM, RFM95, etc.)",
    "Sensor_Motion": "IMUs (MPU6050, BMI160, LSM6DS3, etc.)",
    "Sensor_Pressure": "Barometric (BMP280, BME280, MS5611, etc.)",
    "Sensor_Temperature": "Temperature sensors (TMP36, DS18B20, etc.)",
    "Interface_USB": "USB controllers and PHYs",
    "Interface_Ethernet": "Ethernet PHYs (KSZ9031, DP83848, etc.)",
    "Connector_Generic": "Pin headers, sockets",
    "Connector_USB": "USB connectors",
    "Connector_Card": "SD card slots",
    "Power_Management": "Battery chargers, power switches",
    "Memory_Flash": "SPI/QSPI flash (W25Q, AT25, etc.)",
    "Memory_EEPROM": "I2C/SPI EEPROM (24LC, 25AA, etc.)",
}


class KiCadLibrary:
    """Manages access to KiCad symbol libraries from multiple sources."""

    def __init__(self, cache_dir: str = None):
        self._symbols = {}  # {lib_name: {sym_name: sym_data}}
        self._sym_files = {}  # {lib_name: Path}
        self._symbol_search_cache = {}  # {symbol_name: lib_name}

        # Default cache directory
        if cache_dir:
            self._cache = Path(cache_dir)
        else:
            self._cache = Path.home() / ".cache" / "schematic_engine" / "kicad_symbols"

        # Auto-detect local KiCad install
        self._local_kicad = self._find_local_kicad()
        if self._local_kicad:
            print(f"Found local KiCad symbols: {self._local_kicad}")

    def _find_local_kicad(self) -> Path | None:
        """Auto-detect local KiCad symbol library path."""
        # Check environment variable first
        env_path = os.environ.get("KICAD_SYMBOL_DIR")
        if env_path and Path(env_path).is_dir():
            return Path(env_path)

        # Check platform-specific paths
        system = platform.system()
        for p in _KICAD_LIB_PATHS.get(system, []):
            if p.is_dir():
                return p
        return None

    def add_path(self, path: str):
        """Add a directory of .kicad_sym files to the library."""
        p = Path(path)
        if not p.is_dir():
            print(f"WARNING: {path} is not a directory")
            return
        self._symbol_search_cache.clear()
        for f in p.glob("*.kicad_sym"):
            lib_name = f.stem
            self._sym_files[lib_name] = f

    def add_file(self, filepath: str, lib_name: str = None):
        """Add a single .kicad_sym file."""
        p = Path(filepath)
        if not p.exists():
            print(f"WARNING: {filepath} not found")
            return
        if lib_name is None:
            lib_name = p.stem
        self._symbol_search_cache.clear()
        self._sym_files[lib_name] = p

    def _iter_library_names(self, root: Path | None, include_symdirs: bool = False):
        """Yield candidate library names from a root directory."""
        if not root or not root.is_dir():
            return
        for entry in sorted(root.iterdir()):
            if entry.is_file() and entry.suffix == ".kicad_sym":
                yield entry.stem
            elif entry.is_dir() and include_symdirs:
                if entry.suffix == ".kicad_symdir":
                    yield entry.stem
                elif root == self._cache:
                    # Cached downloads are stored as plain directories per library.
                    yield entry.name

    def _find_symbol_in_symdir_root(self, root: Path | None, symbol_name: str, plain_dirs: bool = False) -> str | None:
        """Quickly find which library directory contains a symbol file."""
        if not root or not root.is_dir():
            return None
        symbol_file = f"{symbol_name}.kicad_sym"
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            if entry.suffix == ".kicad_symdir":
                candidate = entry / symbol_file
                if candidate.is_file():
                    return entry.stem
            elif plain_dirs:
                candidate = entry / symbol_file
                if candidate.is_file():
                    return entry.name
        return None

    def _load_lib(self, lib_name: str) -> dict:
        """Load and cache a library's symbols."""
        if lib_name in self._symbols:
            return self._symbols[lib_name]

        # Try sym_files first (single .kicad_sym file)
        if lib_name in self._sym_files:
            syms = parse_kicad_sym_file(str(self._sym_files[lib_name]))
            self._symbols[lib_name] = syms
            return syms

        # Try local KiCad install — check both .kicad_sym (v9) and .kicad_symdir/ (v10)
        if self._local_kicad:
            local_file = self._local_kicad / f"{lib_name}.kicad_sym"
            if local_file.exists():
                syms = parse_kicad_sym_file(str(local_file))
                self._symbols[lib_name] = syms
                self._sym_files[lib_name] = local_file
                return syms
            local_dir = self._local_kicad / f"{lib_name}.kicad_symdir"
            if local_dir.is_dir():
                syms = self._load_symdir(local_dir)
                self._symbols[lib_name] = syms
                return syms

        # Try cache — single file or directory
        cached_file = self._cache / f"{lib_name}.kicad_sym"
        if cached_file.exists():
            syms = parse_kicad_sym_file(str(cached_file))
            self._symbols[lib_name] = syms
            return syms
        cached_dir = self._cache / lib_name
        if cached_dir.is_dir():
            syms = self._load_symdir(cached_dir)
            self._symbols[lib_name] = syms
            return syms

        return {}

    def _load_symdir(self, dir_path: Path) -> dict:
        """Load all .kicad_sym files from a .kicad_symdir directory."""
        all_syms = {}
        for f in sorted(dir_path.glob("*.kicad_sym")):
            syms = parse_kicad_sym_file(str(f))
            all_syms.update(syms)

        # Resolve 'extends' references — child inherits pins from parent
        for name, data in list(all_syms.items()):
            parent_name = data.get("extends")
            if parent_name and not data["pins"] and parent_name in all_syms:
                parent = all_syms[parent_name]
                data["pins"] = parent["pins"]
                # Merge properties (child overrides parent)
                merged_props = dict(parent.get("properties", {}))
                merged_props.update(data.get("properties", {}))
                data["properties"] = merged_props

        return all_syms

    @staticmethod
    def _sanitize_name(name: str) -> str:
        """Sanitize a library/symbol name to prevent directory traversal."""
        return re.sub(r"[^A-Za-z0-9_\-.]", "_", name).strip(".")

    def download_kicad_lib(self, lib_name: str, symbols: list[str] = None) -> bool:
        """Download KiCad symbol(s) from the official GitLab repository.

        KiCad 10+ stores one symbol per file in .kicad_symdir/ directories.
        If `symbols` is None, lists available symbols and downloads all.
        If `symbols` is a list, downloads only those specific symbols.

        Uses curl as fallback since urllib may fail in some environments.
        """
        import json
        import subprocess

        lib_name = self._sanitize_name(lib_name)
        self._cache.mkdir(parents=True, exist_ok=True)
        lib_cache = self._cache / lib_name
        lib_cache.mkdir(exist_ok=True)
        self._symbol_search_cache.clear()

        # List available symbols via GitLab API
        if symbols is None:
            api_url = f"{KICAD_GITLAB_API}/repository/tree?path={lib_name}.kicad_symdir&per_page=100"
            try:
                result = subprocess.run(["curl", "-sL", api_url], capture_output=True, text=True, timeout=30)
                entries = json.loads(result.stdout)
                symbols = [e["name"].replace(".kicad_sym", "") for e in entries if e["name"].endswith(".kicad_sym")]
                print(f"  {lib_name}: {len(symbols)} symbols available")
            except (json.JSONDecodeError, subprocess.TimeoutExpired, FileNotFoundError):
                print(f"  Could not list symbols in {lib_name}")
                return False

        # Download each symbol file
        loaded = 0
        if lib_name not in self._symbols:
            self._symbols[lib_name] = {}

        for raw_sym_name in symbols:
            sym_name = self._sanitize_name(raw_sym_name)
            dest = lib_cache / f"{sym_name}.kicad_sym"

            if dest.exists() and dest.stat().st_size > 50:
                # Use cached
                syms = parse_kicad_sym_file(str(dest))
                self._symbols[lib_name].update(syms)
                loaded += 1
                continue

            url = f"{KICAD_GITLAB_RAW}/{lib_name}.kicad_symdir/{sym_name}.kicad_sym"
            try:
                result = subprocess.run(["curl", "-sL", url, "-o", str(dest)], capture_output=True, timeout=15)
                if dest.exists() and dest.stat().st_size > 50:
                    syms = parse_kicad_sym_file(str(dest))
                    if syms:
                        self._symbols[lib_name].update(syms)
                        loaded += 1
                    else:
                        # Might be an 'extends' symbol — check for parent
                        content = dest.read_text(encoding="utf-8")
                        extends_m = re.search(r'\(extends "([^"]+)"\)', content)
                        if extends_m:
                            parent = extends_m.group(1)
                            # Download parent if needed
                            parent_dest = lib_cache / f"{parent}.kicad_sym"
                            if not parent_dest.exists():
                                parent_url = f"{KICAD_GITLAB_RAW}/{lib_name}.kicad_symdir/{parent}.kicad_sym"
                                subprocess.run(
                                    ["curl", "-sL", parent_url, "-o", str(parent_dest)],
                                    capture_output=True,
                                    timeout=15,
                                )
                            # Parse parent for pins
                            parent_syms = parse_kicad_sym_file(str(parent_dest))
                            if parent and parent_syms:
                                # Use parent's pins with child's properties
                                parent_data = list(parent_syms.values())[0]
                                props = _extract_properties(content)
                                self._symbols[lib_name][sym_name] = {
                                    "pins": parent_data["pins"],
                                    "properties": {**parent_data.get("properties", {}), **props},
                                    "raw": content,
                                }
                                loaded += 1
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        # Resolve extends — child symbols inherit pins from parent
        # Auto-download parent symbols if not already loaded
        lib_syms = self._symbols.get(lib_name, {})
        for name, data in list(lib_syms.items()):
            parent_name = data.get("extends")
            if parent_name and not data["pins"] and parent_name not in lib_syms:
                # Parent not loaded — download it
                parent_dest = lib_cache / f"{parent_name}.kicad_sym"
                if not parent_dest.exists() or parent_dest.stat().st_size < 50:
                    parent_url = f"{KICAD_GITLAB_RAW}/{lib_name}.kicad_symdir/{parent_name}.kicad_sym"
                    try:
                        subprocess.run(
                            ["curl", "-sL", parent_url, "-o", str(parent_dest)],
                            capture_output=True,
                            timeout=15,
                        )
                    except (subprocess.TimeoutExpired, FileNotFoundError):
                        pass
                if parent_dest.exists() and parent_dest.stat().st_size > 50:
                    parent_syms = parse_kicad_sym_file(str(parent_dest))
                    lib_syms.update(parent_syms)
                    loaded += 1

        for name, data in list(lib_syms.items()):
            parent_name = data.get("extends")
            if parent_name and not data["pins"] and parent_name in lib_syms:
                parent = lib_syms[parent_name]
                data["pins"] = parent["pins"]
                merged = dict(parent.get("properties", {}))
                merged.update(data.get("properties", {}))
                data["properties"] = merged

        if loaded:
            print(f"  → {loaded} symbols loaded from {lib_name}")
        return loaded > 0

    # Keep old name as alias
    download_github_lib = download_kicad_lib

    def list_symbols(self, lib_name: str) -> list[str]:
        """List all symbol names in a library."""
        syms = self._load_lib(lib_name)
        return list(syms.keys())

    def get_symbol_data(self, symbol_name: str, lib_name: str = None) -> dict | None:
        """Get raw parsed symbol data. Searches all loaded libraries if lib_name is None."""
        if lib_name:
            syms = self._load_lib(lib_name)
            return syms.get(symbol_name)

        cached_lib = self._symbol_search_cache.get(symbol_name)
        if cached_lib:
            syms = self._load_lib(cached_lib)
            if symbol_name in syms:
                return syms[symbol_name]
            self._symbol_search_cache.pop(symbol_name, None)

        searched = set()

        # Search all explicitly added libraries first.
        for lname in list(self._sym_files.keys()):
            searched.add(lname)
            syms = self._load_lib(lname)
            if symbol_name in syms:
                self._symbol_search_cache[symbol_name] = lname
                return syms[symbol_name]

        # Fast-path KiCad 10 style per-symbol directories before brute-force loading.
        local_hint = self._find_symbol_in_symdir_root(self._local_kicad, symbol_name)
        if local_hint and local_hint not in searched:
            syms = self._load_lib(local_hint)
            searched.add(local_hint)
            if symbol_name in syms:
                self._symbol_search_cache[symbol_name] = local_hint
                return syms[symbol_name]

        cache_hint = self._find_symbol_in_symdir_root(self._cache, symbol_name, plain_dirs=True)
        if cache_hint and cache_hint not in searched:
            syms = self._load_lib(cache_hint)
            searched.add(cache_hint)
            if symbol_name in syms:
                self._symbol_search_cache[symbol_name] = cache_hint
                return syms[symbol_name]

        # Fall back to scanning any remaining local or cached libraries.
        for lname in self._iter_library_names(self._local_kicad, include_symdirs=True):
            if lname in searched:
                continue
            syms = self._load_lib(lname)
            if symbol_name in syms:
                self._symbol_search_cache[symbol_name] = lname
                return syms[symbol_name]

        for lname in self._iter_library_names(self._cache, include_symdirs=True):
            if lname in searched:
                continue
            syms = self._load_lib(lname)
            if symbol_name in syms:
                self._symbol_search_cache[symbol_name] = lname
                return syms[symbol_name]

        return None

    def get_component(self, symbol_name: str, lib_name: str = None, category: str = "digital") -> ComponentDef | None:
        """Get a ComponentDef for a symbol, auto-parsing from library.

        This is the main API — give it a KiCad symbol name and get back
        a ComponentDef ready for the schematic engine.
        """
        # Resolve the source library name for category inference
        resolved_lib = lib_name
        if not resolved_lib:
            resolved_lib = self._symbol_search_cache.get(symbol_name)
        sym_data = self.get_symbol_data(symbol_name, lib_name)
        if sym_data is None:
            return None
        # After search, the cache knows which library the symbol came from
        if not resolved_lib:
            resolved_lib = self._symbol_search_cache.get(symbol_name)
        return symbol_to_component_def(symbol_name, sym_data, category, lib_name=resolved_lib)

    def available_libraries(self) -> list[str]:
        """List known library categories that can be downloaded."""
        return list(KICAD_LIBRARY_INDEX.keys())

    def search(self, query: str) -> list[tuple[str, str]]:
        """Search all loaded libraries for symbols matching a query.

        Returns list of (lib_name, symbol_name) tuples.
        """
        query_lower = query.lower()
        results = []
        for lib_name in list(self._sym_files.keys()):
            syms = self._load_lib(lib_name)
            for sym_name in syms:
                if query_lower in sym_name.lower():
                    results.append((lib_name, sym_name))
        return results
