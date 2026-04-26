"""Sensor front-end subcircuit template.

Generates an instrumentation amplifier front-end from design parameters:
desired gain, sensor input nets, supply rails.

Auto-calculates: gain resistor (Rg), optional anti-alias RC filter on
output, VDD decoupling, REF pin biasing.  All values snapped to standard
E96/E24 series and formatted.

Supports INA128PA (default) and AD8421BRZ topologies.
"""

from __future__ import annotations

import math
from typing import Any

from ..component_db import BypassCap, ComponentDef, StrapConfig
from .base import (
    FP_0402C,
    FP_0402R,
    FP_0805C,
    BoundaryPort,
    LegacyDBProxy,
    SubcircuitResult,
    SubcircuitTemplate,
    cap_footprint,
    format_capacitance,
    format_resistance,
    snap_cap,
    snap_to_e24,
    snap_to_e96,
)

# Known instrumentation amplifier ICs and their parameters
SENSOR_FRONTEND_IC_DATABASE = LegacyDBProxy("sensor_frontend")  # backed by ic_data/*.json (Task 178)


class SensorFrontendTemplate(SubcircuitTemplate):
    """Instrumentation amplifier sensor front-end with auto-calculated gain resistor."""

    template_type = "sensor_frontend"
    description = "Instrumentation amplifier front-end with gain resistor and filtering"
    param_schema = [
        {
            "name": "gain",
            "type": "number",
            "required": True,
            "description": "Desired voltage gain (>=1)",
        },
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "INA128PA",
            "description": "Instrumentation amplifier IC MPN",
        },
        {
            "name": "ref",
            "type": "string",
            "required": False,
            "default": "U",
            "description": "Reference designator for the IC",
        },
        {
            "name": "vdd_net",
            "type": "string",
            "required": False,
            "default": "VDD_3P3",
            "description": "Positive supply rail net name",
        },
        {
            "name": "gnd_net",
            "type": "string",
            "required": False,
            "default": "GND",
            "description": "Ground net name",
        },
        {
            "name": "sensor_p_net",
            "type": "string",
            "required": False,
            "default": "SENSOR_P",
            "description": "Positive sensor input net name",
        },
        {
            "name": "sensor_n_net",
            "type": "string",
            "required": False,
            "default": "SENSOR_N",
            "description": "Negative sensor input net name",
        },
        {
            "name": "output_net",
            "type": "string",
            "required": False,
            "description": "Amplifier output net name; defaults to INA_OUT_{ref}",
        },
        {
            "name": "filter_bw",
            "type": "number",
            "required": False,
            "description": "Anti-alias filter cutoff frequency in Hz (optional)",
        },
    ]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        gain = params.get("gain")
        if gain is None:
            errors.append("Missing required param 'gain' (desired voltage gain)")
        elif gain < 1.0:
            errors.append(f"Gain ({gain}) must be >= 1.0")

        ic_name = params.get("ic", "INA128PA")
        if ic_name not in SENSOR_FRONTEND_IC_DATABASE:
            errors.append(
                f"Unknown sensor frontend IC '{ic_name}'. Available: {', '.join(SENSOR_FRONTEND_IC_DATABASE)}"
            )

        filter_bw = params.get("filter_bw")
        if filter_bw is not None and filter_bw <= 0:
            errors.append(f"filter_bw ({filter_bw} Hz) must be positive")

        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        """Generate a sensor front-end subcircuit.

        Required params:
            gain: float -- desired voltage gain (>=1)

        Optional params:
            ic: str -- IC MPN (default: "INA128PA")
            ref: str -- reference designator (default: "U")
            vdd_net: str -- positive supply net (default: "VDD_3P3")
            gnd_net: str -- ground net (default: "GND")
            sensor_p_net: str -- positive sensor input (default: "SENSOR_P")
            sensor_n_net: str -- negative sensor input (default: "SENSOR_N")
            output_net: str -- amplifier output net (default: "INA_OUT_{ref}")
            filter_bw: float -- anti-alias filter cutoff Hz (optional)
        """
        gain = params["gain"]
        ic_name = params.get("ic", "INA128PA")
        ref = params.get("ref", "U")
        vdd_net = params.get("vdd_net", "VDD_3P3")
        gnd_net = params.get("gnd_net", "GND")
        sensor_p_net = params.get("sensor_p_net", "SENSOR_P")
        sensor_n_net = params.get("sensor_n_net", "SENSOR_N")
        output_net = params.get("output_net", f"INA_OUT_{ref}")
        filter_bw = params.get("filter_bw")

        # Look up IC parameters
        ic_db = SENSOR_FRONTEND_IC_DATABASE.get(ic_name, SENSOR_FRONTEND_IC_DATABASE["INA128PA"])
        r_internal = ic_db["r_internal"]
        gain_formula_name = ic_db["gain_formula"]

        # ---- Local net names (unique per instance) ----
        rg_p_net = f"RG_P_{ref}"
        rg_n_net = f"RG_N_{ref}"
        ref_pin_net = f"REF_{ref}"
        vout_raw_net = f"VOUT_RAW_{ref}" if filter_bw else output_net

        # ---- Power pins ----
        power_pins = {
            ic_db["pin_vpos"]: vdd_net,
            ic_db["pin_vneg"]: gnd_net,
        }

        # ---- Signal pin nets ----
        pin_nets = {
            ic_db["pin_inp"]: sensor_p_net,
            ic_db["pin_inn"]: sensor_n_net,
            ic_db["pin_vout"]: vout_raw_net,
            ic_db["pin_ref"]: ref_pin_net,
            ic_db["pin_rg_p"]: rg_p_net,
            ic_db["pin_rg_n"]: rg_n_net,
        }

        # ---- Bypass caps ----
        bypass_caps = [
            BypassCap(
                "C_DEC1",
                vdd_net,
                gnd_net,
                "100nF",
                FP_0402C,
                role="decoupling",
                presentation="topology_local",
            ),
            BypassCap(
                "C_DEC2",
                vdd_net,
                gnd_net,
                "10uF",
                FP_0805C,
                role="bulk_decoupling",
                presentation="topology_local",
            ),
            # REF pin bypass to GND for single-supply operation
            BypassCap(
                "C_REF",
                ref_pin_net,
                gnd_net,
                "100nF",
                FP_0402C,
                role="ref_bypass",
                presentation="topology_local",
            ),
        ]

        # ---- Straps ----
        straps: list[StrapConfig] = []
        annotations: list[str] = []

        # ---- Gain resistor calculation ----
        if gain > 1.0:
            # G = 1 + R_internal / Rg  =>  Rg = R_internal / (G - 1)
            rg_raw = r_internal / (gain - 1.0)
            rg_snapped = snap_to_e96(rg_raw)
            actual_gain = 1.0 + r_internal / rg_snapped

            straps.append(
                StrapConfig(
                    "RG",
                    rg_p_net,
                    rg_n_net,
                    format_resistance(rg_snapped),
                    FP_0402R,
                    role="gain_resistor",
                    presentation="topology_local",
                ),
            )

            if gain_formula_name == "ina128":
                formula_str = f"G = 1 + 50k/{format_resistance(rg_snapped)}"
            else:
                formula_str = f"G = 1 + 9.9k/{format_resistance(rg_snapped)}"

            annotations.append(f"INA gain: {formula_str} = {actual_gain:.3f}")
            annotations.append(f"Rg = {format_resistance(rg_snapped)} (target gain {gain})")
        else:
            # Unity gain: no Rg needed, leave RG pins open
            actual_gain = 1.0
            # Remove RG pins from pin_nets so they float (open)
            del pin_nets[ic_db["pin_rg_p"]]
            del pin_nets[ic_db["pin_rg_n"]]
            annotations.append("INA gain: G = 1 (unity, no Rg installed)")

        # ---- Anti-alias RC filter on output (optional) ----
        if filter_bw:
            r_filter = snap_to_e24(1e3)  # 1k series resistor
            # C = 1 / (2 * pi * R * fc)
            c_filter_raw = 1.0 / (2.0 * math.pi * r_filter * filter_bw)
            c_filter = snap_cap(c_filter_raw)
            actual_fc = 1.0 / (2.0 * math.pi * r_filter * c_filter) if c_filter > 0 else 0

            # Filter resistor: VOUT_RAW -> FILT -> output
            straps.append(
                StrapConfig(
                    "RFILT",
                    vout_raw_net,
                    output_net,
                    format_resistance(r_filter),
                    FP_0402R,
                    role="filter_resistor",
                    presentation="topology_local",
                ),
            )

            # Filter cap: output -> GND
            bypass_caps.append(
                BypassCap(
                    "CFILT",
                    output_net,
                    gnd_net,
                    format_capacitance(c_filter),
                    cap_footprint(c_filter),
                    role="filter_cap",
                    presentation="topology_local",
                ),
            )

            annotations.append(
                f"Anti-alias filter: R={format_resistance(r_filter)}, "
                f"C={format_capacitance(c_filter)}, fc={actual_fc:.1f}Hz"
            )

        annotations.insert(0, f"Sensor frontend {ic_name}: gain={actual_gain:.3f}")
        annotations.append(f"REF pin bypassed to {gnd_net} (single-supply midpoint ref)")

        # Mark unused input pins (e.g., RG gain-set pins at unity gain) as explicit NC
        explicit_nc: set[str] = set()
        handled_pins = set(pin_nets) | set(power_pins) | {s.pin for s in straps}
        for pin in ic_db["pins"]:
            if pin.number in handled_pins:
                continue
            if pin.electrical_type in ("output", "power_out", "power_in"):
                continue
            if pin.name in ("NC", "~"):
                continue
            explicit_nc.add(pin.number)

        # ---- Build IC component ----
        ic_comp = ComponentDef(
            mpn=ic_name,
            ref_prefix="U",
            value=ic_name,
            footprint=ic_db["footprint"],
            description=ic_db["description"],
            category="sensor",
            pins=list(ic_db["pins"]),
            power_pins=power_pins,
            pin_nets=pin_nets,
            bypass_caps=bypass_caps,
            straps=straps,
            annotations=annotations,
            explicit_no_connects=explicit_nc,
        )
        ic_comp.source_ref = ref

        # ---- Boundary ports ----
        ports = [
            BoundaryPort(vdd_net, "input"),
            BoundaryPort(gnd_net, "passive"),
            BoundaryPort(sensor_p_net, "input"),
            BoundaryPort(sensor_n_net, "input"),
            BoundaryPort(output_net, "output"),
        ]

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[
                f"Sensor frontend {ic_name}: {sensor_p_net}/{sensor_n_net} -> "
                f"{output_net}, gain={actual_gain:.2f}"
                f"{f', fc={actual_fc:.0f}Hz' if filter_bw else ''}",
            ],
            primary_category="sensor",
        )
