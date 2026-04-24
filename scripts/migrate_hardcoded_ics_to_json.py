"""One-shot migration (Sprint 41 Task 178): push every entry in every
legacy `*_IC_DATABASE` dict in `src/circuit_weaver/subcircuits/` into
the canonical `ic_data/*.json` store, tagged with the correct
`topology` so each template's `merge_into_legacy_db()` merged view
picks it up.

Rules:
- Hardcoded is the source of truth. If a JSON entry diverges on a
  scalar field, the hardcoded value wins (Bucket B).
- If a JSON entry exists under a wrong topology ("component",
  "low_side"/"high_side", "series"/"shunt", "buck"/"linear_sink" for
  LED drivers, etc.), rewrite `topology` to the template's
  `template_type` and stash the original value in `topology_subtype`
  (Bucket C). Nothing consults `topology_subtype` today but it
  preserves data for humans reading the JSON.
- PinDef objects are converted to `{number, name, type, side}` dicts.
- Tuples become lists (JSON-compatible).

Usage: ``py scripts/migrate_hardcoded_ics_to_json.py`` from the repo
root. Safe to re-run; idempotent.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

# template_module_name, db_variable_name, template_type, target_json_filename
MIGRATIONS: list[tuple[str, str, str, str]] = [
    ("adc", "ADC_IC_DATABASE", "adc", "converter.json"),
    ("audio_amplifier", "AUDIO_AMP_IC_DATABASE", "audio_amplifier", "amplifier.json"),
    ("battery_charger", "CHARGER_IC_DATABASE", "battery_charger", "linear_regulator.json"),
    ("battery_monitor", "BATTERY_MONITOR_IC_DATABASE", "battery_monitor", "misc.json"),
    ("boost", "BOOST_IC_DATABASE", "boost", "switching_regulator.json"),
    ("buck", "BUCK_IC_DATABASE", "buck", "switching_regulator.json"),
    ("buck_boost", "BUCK_BOOST_IC_DATABASE", "buck_boost", "switching_regulator.json"),
    ("can_transceiver", "CAN_TRANSCEIVER_IC_DATABASE", "can_transceiver", "bus_interface.json"),
    ("charge_pump", "CHARGE_PUMP_IC_DATABASE", "charge_pump", "linear_regulator.json"),
    ("clock", "CLOCK_IC_DATABASE", "clock_synth", "oscillator.json"),
    ("connector", "CONNECTOR_DATABASE", "connector", "connector.json"),
    ("crystal_oscillator", "CRYSTAL_IC_DATABASE", "crystal_oscillator", "oscillator.json"),
    ("current_sense", "CURRENT_SENSE_IC_DATABASE", "current_sense", "converter.json"),
    ("dac", "DAC_IC_DATABASE", "dac", "converter.json"),
    ("display_driver", "DISPLAY_DRIVER_IC_DATABASE", "display_driver", "misc.json"),
    ("driver", "GATE_DRIVER_DATABASE", "gate_driver", "misc.json"),
    ("driver", "LEVEL_SHIFTER_DATABASE", "level_shifter", "bus_interface.json"),
    ("eeprom", "EEPROM_IC_DATABASE", "eeprom", "memory.json"),
    ("ethernet", "ETHERNET_PHY_IC_DATABASE", "ethernet_phy", "misc.json"),
    ("i2c_bus", "I2C_BUS_IC_DATABASE", "i2c_bus", "bus_interface.json"),
    ("ldo", "LDO_IC_DATABASE", "ldo", "linear_regulator.json"),
    ("led_driver", "LED_DRIVER_IC_DATABASE", "led_driver", "misc.json"),
    ("mosfet_switch", "MOSFET_IC_DATABASE", "mosfet_switch", "misc.json"),
    ("motor_driver", "MOTOR_DRIVER_IC_DATABASE", "motor_driver", "misc.json"),
    ("opamp", "OPAMP_IC_DATABASE", "opamp", "amplifier.json"),
    ("power_mux", "POWER_MUX_IC_DATABASE", "power_mux", "misc.json"),
    ("protection", "TVS_DATABASE", "protection", "protection.json"),
    ("relay_driver", "RELAY_DRIVER_IC_DATABASE", "relay_driver", "misc.json"),
    ("rs485_transceiver", "RS485_TRANSCEIVER_IC_DATABASE", "rs485_transceiver", "bus_interface.json"),
    ("rtc", "RTC_IC_DATABASE", "rtc", "misc.json"),
    ("sensor_frontend", "SENSOR_FRONTEND_IC_DATABASE", "sensor_frontend", "amplifier.json"),
    ("spi_bus", "SPI_BUS_IC_DATABASE", "spi_bus", "bus_interface.json"),
    ("usb", "USB_CONTROLLER_IC_DATABASE", "usb_controller", "misc.json"),
    ("usb", "USB_HUB_IC_DATABASE", "usb_hub", "misc.json"),
    ("usb_c_connector", "USB_C_CONNECTOR_DATABASE", "usb_c_connector", "connector.json"),
    ("voltage_reference", "VREF_IC_DATABASE", "voltage_reference", "linear_regulator.json"),
    ("wireless_module", "WIRELESS_MODULE_IC_DATABASE", "wireless_module", "misc.json"),
]

IC_DATA_DIR = REPO / "src" / "circuit_weaver" / "ic_data"


def _pindef_to_dict(p):
    """Convert a PinDef (or dict) to its canonical JSON shape."""
    if isinstance(p, dict):
        return {
            "number": str(p.get("number", "")),
            "name": str(p.get("name", "")),
            "type": str(p.get("type", "passive")),
            "side": str(p.get("side", "L")),
        }
    # PinDef dataclass
    return {
        "number": str(p.number),
        "name": str(p.name),
        "type": str(p.electrical_type),
        "side": str(p.side),
    }


def _jsonable(value):
    """Recursively convert a hardcoded-dict value to JSON-serializable form."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    # Anything else — best-effort stringify
    return str(value)


def _load_json_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"WARN: {path.name} not valid JSON ({e}); treating as empty")
        return {}


def _write_json_file(path: Path, data: dict) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    path.write_text(text + "\n", encoding="utf-8")


def _build_json_entry(hard: dict, topology: str, existing: dict | None) -> dict:
    """Shape one MPN for JSON: topology + hardcoded fields (overriding
    any JSON divergence). Pins are normalized to dict form.
    """
    merged: dict = {}
    # Start from the existing JSON entry so we preserve fields that
    # aren't in the hardcoded dict (harmless extras).
    if existing:
        merged.update(existing)
        old_topology = existing.get("topology")
        if old_topology and old_topology != topology:
            merged["topology_subtype"] = old_topology

    # Overlay hardcoded data — hardcoded wins on divergence.
    for key, value in hard.items():
        if key == "pins":
            merged["pins"] = [_pindef_to_dict(p) for p in value]
        else:
            merged[key] = _jsonable(value)

    # Force canonical topology.
    merged["topology"] = topology

    # Put topology keys first for readability.
    ordered_keys = ["topology"]
    if "topology_subtype" in merged:
        ordered_keys.append("topology_subtype")
    ordered_keys.extend(k for k in merged if k not in ordered_keys)
    return {k: merged[k] for k in ordered_keys}


def main() -> int:
    # Pre-load every target JSON file once so multiple templates
    # writing to the same file accumulate correctly.
    json_files: dict[str, dict] = {}
    for _, _, _, fname in MIGRATIONS:
        if fname not in json_files:
            json_files[fname] = _load_json_file(IC_DATA_DIR / fname)

    summary: list[tuple[str, str, str, str]] = []  # (topology, mpn, file, action)
    for mod_name, db_name, topology, target_file in MIGRATIONS:
        module = __import__(f"circuit_weaver.subcircuits.{mod_name}", fromlist=["*"])
        hard_db = getattr(module, db_name, {})
        if not hard_db:
            continue

        target = json_files[target_file]
        # Ensure no duplicate MPN in a different topic file — if an
        # MPN is already in another JSON file we leave it alone but
        # report; the expected clean state has each MPN in exactly
        # one place.
        for mpn, hard in hard_db.items():
            existing = target.get(mpn)
            # Look for the MPN in other JSON files too.
            if existing is None:
                for other_name, other_data in json_files.items():
                    if other_name == target_file:
                        continue
                    if mpn in other_data:
                        # Move it to target. Remove from other.
                        existing = other_data.pop(mpn)
                        summary.append((topology, mpn, other_name, f"-> {target_file}"))
                        break

            new_entry = _build_json_entry(hard, topology, existing)
            if target.get(mpn) == new_entry:
                summary.append((topology, mpn, target_file, "unchanged"))
            else:
                target[mpn] = new_entry
                action = "updated" if existing else "added"
                summary.append((topology, mpn, target_file, action))

    # Persist every modified JSON file.
    for fname, data in json_files.items():
        _write_json_file(IC_DATA_DIR / fname, data)

    # Report.
    by_action: dict[str, int] = {}
    for _, _, _, act in summary:
        by_action[act.split()[0]] = by_action.get(act.split()[0], 0) + 1
    print("=== Migration summary ===")
    for action, count in sorted(by_action.items()):
        print(f"  {action:12s} {count}")
    print(f"  total        {len(summary)}")
    print()
    for topology, mpn, file, action in summary:
        print(f"  [{topology:22s}] {mpn:30s} -> {file:30s} {action}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
