"""IC application data store.

Loads IC pin maps, electrical specs, and topology metadata from JSON files.
New ICs can be added by writing to custom.json — no Python code changes needed.

Usage:
    from circuit_weaver.ic_data import get_ic_data, get_all_ics, register_ic

    ic = get_ic_data("AP62300")        # returns dict or None
    ics = get_all_ics("buck")          # all ICs with topology="buck"
    register_ic("NEW_IC", {...})       # add at runtime (persisted to custom.json)
"""

from __future__ import annotations

import json
import logging
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


def _load_database() -> dict[str, dict[str, Any]]:
    """Load all JSON files into a single merged dict keyed by MPN."""
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
    return db


def _get_db() -> dict[str, dict[str, Any]]:
    global _ic_database
    if _ic_database is None:
        _ic_database = _load_database()
    return _ic_database


def reload() -> None:
    """Force reload of all JSON data files."""
    global _ic_database
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


def register_ic(mpn: str, data: dict[str, Any], *, persist: bool = True) -> None:
    """Register a new IC at runtime. If persist=True, writes to custom.json."""
    db = _get_db()
    db[mpn] = data
    if persist:
        custom_path = _DATA_DIR / "custom.json"
        try:
            existing = json.loads(custom_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            existing = {}
        existing[mpn] = data
        custom_path.write_text(
            json.dumps(existing, indent=2, default=str), encoding="utf-8"
        )
        _logger.info("Registered IC %s to custom.json", mpn)


def list_topologies() -> list[str]:
    """List all unique topology types across all loaded ICs."""
    return sorted({data.get("topology", "") for data in _get_db().values()} - {""})
