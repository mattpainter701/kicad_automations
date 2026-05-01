#!/usr/bin/env python3
"""Extract IC databases from template Python files into JSON.

Imports each template module, reads its IC database dict, and serializes
pin definitions and all parameters to JSON files grouped by topology.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from circuit_weaver.component_db import PinDef


def _pin_to_dict(pin: PinDef) -> dict:
    return {
        "number": pin.number,
        "name": pin.name,
        "type": pin.electrical_type,
        "side": pin.side,
    }


def _serialize_db(db: dict, topology: str, extra_fields: dict | None = None) -> dict:
    """Convert an IC database dict to JSON-serializable form."""
    result = {}
    for mpn, entry in db.items():
        ic = {"topology": topology}
        for k, v in entry.items():
            if k == "pins":
                ic["pins"] = [_pin_to_dict(p) for p in v]
            elif isinstance(v, PinDef):
                ic[k] = _pin_to_dict(v)
            elif isinstance(v, (list, tuple)) and v and isinstance(v[0], PinDef):
                ic[k] = [_pin_to_dict(p) for p in v]
            else:
                ic[k] = v
        if extra_fields:
            ic.update(extra_fields)
        result[mpn] = ic
    return result


def main():
    out_dir = Path(__file__).resolve().parent.parent / "src" / "circuit_weaver" / "ic_data"
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- Switching regulators ---
    # buck, boost, buck_boost data already in switching_regulator.json (Sprint 41)
    switching = {}
    _write(out_dir / "switching_regulator.json", switching)

    # --- Linear regulators ---
    # ldo data already in linear_regulator.json (Sprint 41)
    from circuit_weaver.subcircuits.charge_pump import CHARGE_PUMP_IC_DATABASE
    from circuit_weaver.subcircuits.voltage_reference import VREF_IC_DATABASE
    from circuit_weaver.subcircuits.battery_charger import CHARGER_IC_DATABASE

    linear = {}
    linear.update(_serialize_db(CHARGE_PUMP_IC_DATABASE, "charge_pump"))
    linear.update(_serialize_db(VREF_IC_DATABASE, "voltage_reference"))
    linear.update(_serialize_db(CHARGER_IC_DATABASE, "battery_charger"))
    _write(out_dir / "linear_regulator.json", linear)

    # --- Amplifiers ---
    from circuit_weaver.subcircuits.opamp import OPAMP_IC_DATABASE
    from circuit_weaver.subcircuits.sensor_frontend import SENSOR_FRONTEND_IC_DATABASE
    from circuit_weaver.subcircuits.audio_amplifier import AUDIO_AMP_IC_DATABASE

    amps = {}
    amps.update(_serialize_db(OPAMP_IC_DATABASE, "opamp"))
    amps.update(_serialize_db(SENSOR_FRONTEND_IC_DATABASE, "sensor_frontend"))
    amps.update(_serialize_db(AUDIO_AMP_IC_DATABASE, "audio_amplifier"))
    _write(out_dir / "amplifier.json", amps)

    # --- Bus interfaces ---
    from circuit_weaver.subcircuits.i2c_bus import I2C_BUS_IC_DATABASE
    from circuit_weaver.subcircuits.spi_bus import SPI_BUS_IC_DATABASE
    from circuit_weaver.subcircuits.rs485_transceiver import RS485_TRANSCEIVER_IC_DATABASE
    from circuit_weaver.subcircuits.driver import LEVEL_SHIFTER_DATABASE

    bus = {}
    bus.update(_serialize_db(I2C_BUS_IC_DATABASE, "i2c_bus"))
    bus.update(_serialize_db(SPI_BUS_IC_DATABASE, "spi_bus"))
    bus.update(_serialize_db(RS485_TRANSCEIVER_IC_DATABASE, "rs485_transceiver"))
    bus.update(_serialize_db(LEVEL_SHIFTER_DATABASE, "level_shifter"))
    _write(out_dir / "bus_interface.json", bus)

    # --- Converters (ADC/DAC) ---
    from circuit_weaver.subcircuits.adc import ADC_IC_DATABASE
    from circuit_weaver.subcircuits.dac import DAC_IC_DATABASE
    from circuit_weaver.subcircuits.current_sense import CURRENT_SENSE_IC_DATABASE

    converters = {}
    converters.update(_serialize_db(ADC_IC_DATABASE, "adc"))
    converters.update(_serialize_db(DAC_IC_DATABASE, "dac"))
    converters.update(_serialize_db(CURRENT_SENSE_IC_DATABASE, "current_sense"))
    _write(out_dir / "converter.json", converters)

    # --- Oscillators ---
    from circuit_weaver.subcircuits.crystal_oscillator import CRYSTAL_IC_DATABASE
    from circuit_weaver.subcircuits.clock import CLOCK_IC_DATABASE

    osc = {}
    osc.update(_serialize_db(CRYSTAL_IC_DATABASE, "crystal_oscillator"))
    osc.update(_serialize_db(CLOCK_IC_DATABASE, "clock_synth"))
    _write(out_dir / "oscillator.json", osc)

    # --- Connectors ---
    from circuit_weaver.subcircuits.connector import CONNECTOR_DATABASE
    from circuit_weaver.subcircuits.usb_c_connector import USB_C_CONNECTOR_DATABASE

    conn = {}
    conn.update(_serialize_db(CONNECTOR_DATABASE, "connector"))
    conn.update(_serialize_db(USB_C_CONNECTOR_DATABASE, "usb_c_connector"))
    _write(out_dir / "connector.json", conn)

    # --- Misc ---
    from circuit_weaver.subcircuits.rtc import RTC_IC_DATABASE
    from circuit_weaver.subcircuits.display_driver import DISPLAY_DRIVER_IC_DATABASE
    from circuit_weaver.subcircuits.motor_driver import MOTOR_DRIVER_IC_DATABASE
    from circuit_weaver.subcircuits.wireless_module import WIRELESS_MODULE_IC_DATABASE
    from circuit_weaver.subcircuits.mosfet_switch import MOSFET_IC_DATABASE
    from circuit_weaver.subcircuits.relay_driver import RELAY_DRIVER_IC_DATABASE
    from circuit_weaver.subcircuits.driver import GATE_DRIVER_DATABASE
    from circuit_weaver.subcircuits.led_driver import LED_DRIVER_IC_DATABASE
    from circuit_weaver.subcircuits.power_mux import POWER_MUX_IC_DATABASE
    from circuit_weaver.subcircuits.battery_monitor import BATTERY_MONITOR_IC_DATABASE
    from circuit_weaver.subcircuits.ethernet import ETHERNET_PHY_IC_DATABASE
    from circuit_weaver.subcircuits.usb import USB_CONTROLLER_IC_DATABASE, USB_HUB_IC_DATABASE

    misc = {}
    misc.update(_serialize_db(RTC_IC_DATABASE, "rtc"))
    misc.update(_serialize_db(DISPLAY_DRIVER_IC_DATABASE, "display_driver"))
    misc.update(_serialize_db(MOTOR_DRIVER_IC_DATABASE, "motor_driver"))
    misc.update(_serialize_db(WIRELESS_MODULE_IC_DATABASE, "wireless_module"))
    misc.update(_serialize_db(MOSFET_IC_DATABASE, "mosfet_switch"))
    misc.update(_serialize_db(RELAY_DRIVER_IC_DATABASE, "relay_driver"))
    misc.update(_serialize_db(GATE_DRIVER_DATABASE, "gate_driver"))
    misc.update(_serialize_db(LED_DRIVER_IC_DATABASE, "led_driver"))
    misc.update(_serialize_db(POWER_MUX_IC_DATABASE, "power_mux"))
    misc.update(_serialize_db(BATTERY_MONITOR_IC_DATABASE, "battery_monitor"))
    misc.update(_serialize_db(ETHERNET_PHY_IC_DATABASE, "ethernet_phy"))
    misc.update(_serialize_db(USB_CONTROLLER_IC_DATABASE, "usb_controller"))
    misc.update(_serialize_db(USB_HUB_IC_DATABASE, "usb_hub"))
    _write(out_dir / "misc.json", misc)

    # --- Custom (agent-populated, starts empty) ---
    _write(out_dir / "custom.json", {})

    print("Done. IC data extracted to", out_dir)


def _write(path: Path, data: dict):
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    print(f"  {path.name}: {len(data)} ICs")


if __name__ == "__main__":
    main()
