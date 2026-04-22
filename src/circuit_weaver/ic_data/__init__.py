"""IC application data store.

Loads IC pin maps, electrical specs, and topology metadata from JSON files.
New ICs can be added via ``register_ic()`` or by editing ``custom.json``.

Persistence lookup order for the user-writable ``custom.json``:

1. **Package directory** (``<install>/circuit_weaver/ic_data/custom.json``) —
   used when the install is editable/writable.
2. **User data directory** (``~/.local/share/circuit-weaver/custom.json`` on
   POSIX, ``%APPDATA%/circuit-weaver/custom.json`` on Windows) — used when
   the package dir is read-only (system Python, containers, multi-user
   installs). Also read on load if present.

This lets `pip install circuit-weaver` in a read-only environment still
support ``register_ic()`` without crashing on ``PermissionError``.

Usage:
    from circuit_weaver.ic_data import get_ic_data, get_all_ics, register_ic

    ic = get_ic_data("AP62300")        # returns dict or None
    ics = get_all_ics("buck")          # all ICs with topology="buck"
    register_ic("NEW_IC", {...})       # add at runtime (persisted atomically)
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)
_DATA_DIR = Path(__file__).parent

_JSON_FILES = [
    "switching_regulator.json",
    "linear_regulator.json",
    "amplifier.json",
    "bus_interface.json",
    "converter.json",
    "oscillator.json",
    "protection.json",
    "connector.json",
    "memory.json",
    "misc.json",
    "custom.json",
]

_ic_database: dict[str, dict[str, Any]] | None = None
_db_lock = threading.Lock()

# Maps topology names to the template_type aliases they can serve.
# When the registry looks up "buck", it finds ICs with topology="buck".
TOPOLOGY_ALIASES: dict[str, str] = {
    "buck": "buck",
    "boost": "boost",
    "buck_boost": "buck_boost",
    "ldo": "ldo",
    "charge_pump": "charge_pump",
    "voltage_reference": "voltage_reference",
    "battery_charger": "battery_charger",
    "opamp": "opamp",
    "sensor_frontend": "sensor_frontend",
    "audio_amplifier": "audio_amplifier",
    "crystal_oscillator": "crystal_oscillator",
    "clock_synth": "clock_synth",
    "i2c_bus": "i2c_bus",
    "spi_bus": "spi_bus",
    "can_transceiver": "can_transceiver",
    "rs485_transceiver": "rs485_transceiver",
    "level_shifter": "level_shifter",
    "adc": "adc",
    "dac": "dac",
    "current_sense": "current_sense",
    "protection": "protection",
    "connector": "connector",
    "usb_c_connector": "usb_c_connector",
    "eeprom": "eeprom",
    "rtc": "rtc",
    "display_driver": "display_driver",
    "motor_driver": "motor_driver",
    "wireless_module": "wireless_module",
    "mosfet_switch": "mosfet_switch",
    "relay_driver": "relay_driver",
    "gate_driver": "gate_driver",
    "led_driver": "led_driver",
    "power_mux": "power_mux",
    "battery_monitor": "battery_monitor",
    "ethernet_phy": "ethernet_phy",
    "usb_controller": "usb_controller",
    "usb_hub": "usb_hub",
}


def _user_data_dir() -> Path:
    """User-writable data directory for overrides (XDG on POSIX, APPDATA on Windows)."""
    if os.name == "nt":
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
        return Path(base) / "circuit-weaver"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "circuit-weaver"
    return Path.home() / ".local" / "share" / "circuit-weaver"


def _user_custom_path() -> Path:
    """Path to the user-data custom.json (may or may not exist)."""
    return _user_data_dir() / "custom.json"


def _load_database() -> dict[str, dict[str, Any]]:
    """Load all bundled JSON files + the user-data custom.json overlay."""
    db: dict[str, dict[str, Any]] = {}
    for fname in _JSON_FILES:
        fpath = _DATA_DIR / fname
        if not fpath.exists():
            continue
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
            db.update(data)
        except (json.JSONDecodeError, OSError) as e:
            _logger.warning("Failed to load %s: %s", fpath, e)

    user_custom = _user_custom_path()
    if user_custom.exists():
        try:
            data = json.loads(user_custom.read_text(encoding="utf-8"))
            db.update(data)
        except (json.JSONDecodeError, OSError) as e:
            _logger.warning("Failed to load user custom.json %s: %s", user_custom, e)
    return db


def _get_db() -> dict[str, dict[str, Any]]:
    global _ic_database
    if _ic_database is None:
        with _db_lock:
            if _ic_database is None:
                _ic_database = _load_database()
    return _ic_database


def reload() -> None:
    """Force reload of all JSON data files on the next access."""
    global _ic_database
    with _db_lock:
        _ic_database = None


def get_ic_data(mpn: str) -> dict[str, Any] | None:
    """Look up IC data by MPN. Returns None if not found."""
    return _get_db().get(mpn)


def get_all_ics(topology: str | None = None) -> dict[str, dict[str, Any]]:
    """Get all ICs, optionally filtered by topology."""
    db = _get_db()
    if topology is None:
        return dict(db)
    return {mpn: data for mpn, data in db.items() if data.get("topology") == topology}


def get_default_ic(topology: str) -> tuple[str, dict[str, Any]] | None:
    """Get the first (default) IC for a given topology."""
    ics = get_all_ics(topology)
    if ics:
        mpn = next(iter(ics))
        return mpn, ics[mpn]
    return None


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON atomically via tmp-file rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _write_custom(mpn: str, data: dict[str, Any]) -> Path:
    """Persist a single IC entry into custom.json, preferring the package dir.

    Returns the path actually written to.

    If the package dir is read-only (``PermissionError`` / ``OSError``),
    falls back to the user data dir. Raises ``OSError`` if both fail.
    """
    for candidate in (_DATA_DIR / "custom.json", _user_custom_path()):
        try:
            if candidate.exists():
                try:
                    existing = json.loads(candidate.read_text(encoding="utf-8"))
                    if not isinstance(existing, dict):
                        existing = {}
                except (json.JSONDecodeError, OSError):
                    existing = {}
            else:
                existing = {}
            existing[mpn] = data
            _atomic_write_json(candidate, existing)
            return candidate
        except (PermissionError, OSError) as e:
            _logger.debug("Could not write %s (%s), trying next location", candidate, e)
            continue
    raise OSError(f"Could not write custom.json to either {_DATA_DIR} or {_user_data_dir()}")


def register_ic(mpn: str, data: dict[str, Any], *, persist: bool = True) -> None:
    """Register a new IC at runtime. If ``persist=True``, writes atomically to
    ``custom.json`` in the package dir (preferred) or user data dir (fallback).
    """
    # Resolve the db reference outside the lock — _get_db() acquires the
    # lock itself for lazy init and holding it here would deadlock.
    db = _get_db()
    with _db_lock:
        db[mpn] = data
    if persist:
        path = _write_custom(mpn, data)
        _logger.info("Registered IC %s to %s", mpn, path)


def list_topologies() -> list[str]:
    """List all unique topology types across all loaded ICs."""
    return sorted({data.get("topology", "") for data in _get_db().values()} - {""})


# Topology → ComponentDef.category mapping for the resolver tier.
_TOPOLOGY_CATEGORY: dict[str, str] = {
    "buck": "power",
    "boost": "power",
    "buck_boost": "power",
    "ldo": "power",
    "charge_pump": "power",
    "voltage_reference": "power",
    "battery_charger": "power",
    "battery_monitor": "power",
    "power_mux": "power",
    "mosfet_switch": "power",
    "relay_driver": "power",
    "gate_driver": "power",
    "led_driver": "power",
    "motor_driver": "power",
    "opamp": "analog",
    "sensor_frontend": "analog",
    "audio_amplifier": "analog",
    "current_sense": "analog",
    "adc": "analog",
    "dac": "analog",
    "sensor": "analog",
    "crystal_oscillator": "rf",
    "clock_synth": "rf",
    "wireless_module": "rf",
    "i2c_bus": "digital",
    "spi_bus": "digital",
    "level_shifter": "digital",
    "rtc": "digital",
    "display_driver": "digital",
    "ethernet_phy": "digital",
    "usb_controller": "digital",
    "usb_hub": "digital",
    "can_transceiver": "digital",
    "rs485_transceiver": "digital",
    "eeprom": "storage",
    "memory": "storage",
    "protection": "protection",
    "connector": "connector",
    "usb_c_connector": "connector",
}


def _ref_prefix_for(topology: str) -> str:
    if topology in ("connector", "usb_c_connector"):
        return "J"
    if topology == "protection":
        return "D"
    if topology == "crystal_oscillator":
        return "Y"
    return "U"


def ic_data_to_component_def(mpn: str, data: dict[str, Any]) -> Any:
    """Convert an ic_data JSON entry into a ComponentDef.

    Imported lazily to avoid circular imports with ``component_db``.

    Pin definitions, power_pins (pins typed ``power_in``), footprint,
    description, manufacturer, and topology-derived category/ref_prefix are
    populated. Fields that require downstream wiring (bypass_caps, straps,
    pin_nets) are left empty — they are generated by topology_builders when
    the IC is instantiated as part of a subcircuit.

    Returns None if the entry lacks a ``pins`` list (unusable for schematic
    generation).
    """
    from ..component_db import ComponentDef, PinDef  # local import — avoid cycles

    pins_raw = data.get("pins")
    if not isinstance(pins_raw, list) or not pins_raw:
        return None

    try:
        pins = [
            PinDef(
                str(p["number"]),
                str(p.get("name", "")),
                str(p.get("type", "passive")),
                str(p.get("side", "L")),
            )
            for p in pins_raw
        ]
    except (KeyError, TypeError) as e:
        _logger.warning("ic_data: bad pin entry for %s: %s", mpn, e)
        return None

    topology = str(data.get("topology", "")).lower()
    category = _TOPOLOGY_CATEGORY.get(topology, "digital")
    ref_prefix = _ref_prefix_for(topology)

    # Power pins: auto-wire any pins typed power_in to a rail guessed from
    # the pin name. This mirrors what ComponentRegistry does for registered
    # ICs. We leave signal pins unconnected — they are wired when the IC is
    # instantiated inside a template/subcircuit.
    power_pins: dict[str, str] = {}
    for p in pins:
        if p.electrical_type == "power_in":
            name = p.name.upper()
            if name in ("GND", "VSS", "AGND", "DGND", "PGND"):
                power_pins[p.number] = "GND"
            elif name.startswith(("VDD", "VCC", "VIN", "VBAT", "AVDD", "DVDD", "VSYS")):
                power_pins[p.number] = name

    manufacturer = str(data.get("manufacturer", ""))
    footprint = str(data.get("footprint", ""))
    description = str(data.get("description", ""))

    return ComponentDef(
        mpn=mpn,
        ref_prefix=ref_prefix,
        value=mpn,
        footprint=footprint,
        description=description,
        category=category,
        source_manufacturer=manufacturer,
        pins=pins,
        pin_nets={},
        power_pins=power_pins,
        power_reqs=[],
        bypass_caps=[],
        straps=[],
        explicit_no_connects=set(),
        pinout_source="explicit",
    )
