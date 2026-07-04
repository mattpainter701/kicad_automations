#!/usr/bin/env python3
"""Generate docs/templates.md from the subcircuit template registry."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from circuit_weaver.subcircuits.base import get_default_registry

# Realistic example values for required numeric parameters, keyed by param name.
# Falls back to the param's default or a generic value if not listed here.
_EXAMPLE_VALUES: dict[str, object] = {
    "vin": 12,
    "vout": 3.3,
    "iout": 1.0,
    "iload": 0.5,
    "iled": 0.020,
    "imax": 5.0,
    "ichg": 0.5,
    "gain": 10,
    "freq": 8e6,
    "cl_spec": 12,  # pF — matches the param unit, not farads
    "vm": 7.4,
    "imotor": 1.0,
    "vcoil": 12,
    "icoil": 0.05,
    "protect_net": "VBUS_5V",
}

# Per-template overrides for required-param example values, for cases where
# the global defaults would be physically wrong (e.g. a boost must step UP).
_EXAMPLE_OVERRIDES: dict[str, dict[str, object]] = {
    "boost": {"vin": 3.7, "vout": 5, "iout": 1.0},
    "buck_boost": {"vin": 3.7, "vout": 3.3, "iout": 0.5},
}

# Map template_type to the YAML section key used in design specs.
_TYPE_TO_SECTION: dict[str, str] = {
    # Power
    "buck": "power",
    "boost": "power",
    "buck_boost": "power",
    "ldo": "power",
    "charge_pump": "power",
    "power_mux": "power",
    "battery_charger": "power",
    "battery_monitor": "power",
    "led_driver": "power",
    "mosfet_switch": "power",
    "relay_driver": "power",
    "gate_driver": "power",
    # Analog
    "opamp": "analog",
    "adc": "analog",
    "dac": "analog",
    "sensor_frontend": "analog",
    "current_sense": "analog",
    "audio_amplifier": "analog",
    # Digital / interfaces
    "i2c_bus": "interfaces",
    "spi_bus": "interfaces",
    "can_transceiver": "interfaces",
    "rs485_transceiver": "interfaces",
    "usb_controller": "interfaces",
    "usb_hub": "interfaces",
    "usb_c_connector": "interfaces",
    "ethernet_phy": "interfaces",
    "level_shifter": "interfaces",
    "display_driver": "interfaces",
    # Clocking
    "crystal_oscillator": "clocking",
    "clock_synth": "clocking",
    # Protection
    "protection": "protection",
    # Motor
    "motor_driver": "motor",
    # Precision
    "voltage_reference": "power",
    # Digital peripherals
    "rtc": "digital",
    "eeprom": "digital",
    "wireless_module": "digital",
    # Connectors
    "connector": "connectors",
}


def _example_value(spec: dict, ttype: str = "") -> str:
    """Pick a sensible example value for a required parameter."""
    name = spec.get("name", "")

    # Check the per-template overrides, then our curated map
    if name in _EXAMPLE_OVERRIDES.get(ttype, {}) or name in _EXAMPLE_VALUES:
        val = _EXAMPLE_OVERRIDES.get(ttype, {}).get(name, _EXAMPLE_VALUES.get(name))
        if isinstance(val, float) and val == int(val):
            return str(int(val))
        return str(val)

    # Use the first option if available
    if "options" in spec:
        return str(spec["options"][0])

    # Type-based fallback
    ptype = spec.get("type", "")
    if ptype == "number":
        return "1.0"
    if ptype == "integer":
        return "1"
    if ptype == "boolean":
        return "true"

    return "<value>"


def _example_ref(schema: list[dict]) -> str:
    """Build the example reference designator from the template's own ref prefix.

    Templates declare their canonical prefix as the ``ref`` param default
    (U for ICs, J for connectors, D for protection, Y for crystals, Q for
    MOSFETs, RP for resistor packs).
    """
    prefix = "U"
    for spec in schema:
        if spec.get("name") == "ref" and spec.get("default"):
            prefix = str(spec["default"])
            break
    return f"{prefix}1"


def main() -> None:
    registry = get_default_registry()
    lines = [
        "# Template Reference",
        "",
        "Auto-generated from `param_schema` of all registered subcircuit templates.",
        "Regenerate with `python scripts/gen_template_docs.py` — do not edit by hand.",
        "",
        f"**{len(list(registry.available_types()))} templates available.**",
        "",
        "---",
        "",
    ]

    for ttype in sorted(registry.available_types()):
        tmpl = registry.get(ttype)
        lines.append(f"## `{ttype}`")
        lines.append("")
        lines.append(tmpl.description)
        lines.append("")

        schema = tmpl.param_schema
        if schema:
            lines.append("### Parameters")
            lines.append("")
            lines.append("| Name | Type | Required | Default | Description |")
            lines.append("|------|------|----------|---------|-------------|")
            for spec in schema:
                name = spec.get("name", "")
                ptype = spec.get("type", "")
                required = "Yes" if spec.get("required") else ""
                default = str(spec["default"]) if "default" in spec else ""
                desc = spec.get("description", "")
                if "options" in spec:
                    opts = ", ".join(str(o) for o in spec["options"])
                    desc = f"{desc} ({opts})" if desc else f"Options: {opts}"
                lines.append(f"| `{name}` | {ptype} | {required} | {default} | {desc} |")
            lines.append("")

        # Determine the right YAML section for the example
        section = _TYPE_TO_SECTION.get(ttype, "blocks")

        # Example YAML snippet with realistic values
        lines.append("### Example")
        lines.append("")
        lines.append("```yaml")
        lines.append(f"{section}:")
        lines.append(f"  - type: {ttype}")
        lines.append(f"    ref: {_example_ref(schema)}")
        for spec in schema:
            name = spec.get("name", "")
            if name in ("ref",):
                continue
            if spec.get("required"):
                lines.append(f"    {name}: {_example_value(spec, ttype)}")
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")

    output_path = Path(__file__).resolve().parent.parent / "docs" / "templates.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Generated {output_path} ({len(list(registry.available_types()))} templates)")


if __name__ == "__main__":
    main()
