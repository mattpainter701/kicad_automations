"""Charge pump subcircuit template.

Generates a complete inverting charge pump subcircuit from design parameters:
input rail, output current, target ripple.

Auto-calculates: flying capacitor, output capacitor, input decoupling.
All values snapped to standard capacitor series.

Supports LM2776 (SOT-23-5, default) and ICL7660 (SOIC-8).
"""

from __future__ import annotations

from typing import Any

from ..component_db import BypassCap, ComponentDef, PinDef
from .base import (
    BoundaryPort,
    SubcircuitResult,
    SubcircuitTemplate,
    cap_footprint,
    format_capacitance,
    snap_cap,
)

# Known charge pump ICs and their parameters
CHARGE_PUMP_IC_DATABASE = {
    "LM2776": {
        "description": "Inverting Charge Pump -VIN 100mA SOT-23-5",
        "footprint": "SOT-23-5",
        "vin_min": 2.7,
        "vin_max": 5.5,
        "iout_max": 0.100,
        "fsw": 1e6,  # 1 MHz fixed
        "pins": [
            PinDef("1", "VIN", "power_in", "L"),
            PinDef("2", "GND", "power_in", "B"),
            PinDef("3", "VOUT", "power_out", "R"),
            PinDef("4", "C_FLY_N", "passive", "T"),
            PinDef("5", "C_FLY_P", "passive", "T"),
        ],
        "pin_vin": "1",
        "pin_gnd": "2",
        "pin_vout": "3",
        "pin_cfn": "4",
        "pin_cfp": "5",
    },
    "ICL7660": {
        "description": "Inverting/Doubling Charge Pump -VIN 10mA SOIC-8",
        "footprint": "SOIC-8",
        "vin_min": 1.5,
        "vin_max": 10.0,
        "iout_max": 0.010,
        "fsw": 10e3,  # 10 kHz internal oscillator
        "pins": [
            PinDef("1", "NC", "passive", "L"),
            PinDef("2", "C_FLY_P", "passive", "T"),
            PinDef("3", "GND", "power_in", "B"),
            PinDef("4", "C_FLY_N", "passive", "T"),
            PinDef("5", "VOUT", "power_out", "R"),
            PinDef("6", "LV", "input", "L"),
            PinDef("7", "OSC", "input", "L"),
            PinDef("8", "VIN", "power_in", "T"),
        ],
        "pin_vin": "8",
        "pin_gnd": "3",
        "pin_vout": "5",
        "pin_cfp": "2",
        "pin_cfn": "4",
    },
}


class ChargePumpTemplate(SubcircuitTemplate):
    """Inverting charge pump with auto-calculated flying and output caps."""

    template_type = "charge_pump"
    description = "Inverting charge pump with flying cap and output cap"
    param_schema = [
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "LM2776",
            "description": "Charge pump IC MPN",
        },
        {
            "name": "ref",
            "type": "string",
            "required": False,
            "default": "U",
            "description": "Reference designator for the IC",
        },
        {
            "name": "vin_net",
            "type": "string",
            "required": False,
            "default": "VDD_3P3",
            "description": "Input rail net name",
        },
        {
            "name": "rail_name",
            "type": "string",
            "required": False,
            "default": "VNEG",
            "description": "Output rail net name (negative rail)",
        },
        {
            "name": "iout",
            "type": "number",
            "required": False,
            "default": 0.050,
            "description": "Output current in amps (default 50mA)",
        },
    ]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        ic_name = params.get("ic", "LM2776")
        if ic_name not in CHARGE_PUMP_IC_DATABASE:
            errors.append(f"Unknown charge pump IC '{ic_name}'. Available: {', '.join(CHARGE_PUMP_IC_DATABASE)}")
        iout = params.get("iout", 0.050)
        if iout is not None and iout <= 0:
            errors.append(f"iout ({iout}A) must be positive")
        ic_db = CHARGE_PUMP_IC_DATABASE.get(ic_name, CHARGE_PUMP_IC_DATABASE["LM2776"])
        if iout is not None and iout > ic_db["iout_max"]:
            errors.append(f"iout ({iout}A) exceeds {ic_name} max ({ic_db['iout_max']}A)")
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        """Generate a charge pump subcircuit.

        Optional params:
            ic: str — IC MPN (default: "LM2776")
            ref: str — reference designator (default: "U")
            vin_net: str — input rail net name (default: "VDD_3P3")
            rail_name: str — output rail net name (default: "VNEG")
            iout: float — output current in amps (default: 0.050)
        """
        ic_name = params.get("ic", "LM2776")
        ic_db = CHARGE_PUMP_IC_DATABASE.get(ic_name, CHARGE_PUMP_IC_DATABASE["LM2776"])
        ref = params.get("ref", "U")
        vin_net = params.get("vin_net", "VDD_3P3")
        rail_name = params.get("rail_name", "VNEG")
        iout = params.get("iout", 0.050)

        fsw = ic_db["fsw"]
        v_ripple = 0.050  # 50mV target ripple

        # ---- Calculate passive values ----

        # Flying cap: C_fly = Iout / (fsw * V_ripple)
        c_fly_raw = iout / (fsw * v_ripple) if fsw > 0 and v_ripple > 0 else 1e-6
        c_fly = snap_cap(c_fly_raw)

        # Output cap: same formula (Cout = Iout / (fsw * V_ripple))
        c_out_raw = iout / (fsw * v_ripple) if fsw > 0 and v_ripple > 0 else 1e-6
        c_out = snap_cap(c_out_raw)

        # Input decoupling: 1uF
        c_in = 1e-6

        # ---- Net names (unique per instance) ----
        cfp_net = f"CFP_{ref}"
        cfn_net = f"CFN_{ref}"

        # ---- Power pins ----
        power_pins: dict[str, str] = {
            ic_db["pin_vin"]: vin_net,
            ic_db["pin_gnd"]: "GND",
        }

        # ---- Signal pin nets ----
        pin_nets: dict[str, str] = {
            ic_db["pin_vout"]: rail_name,
            ic_db["pin_cfp"]: cfp_net,
            ic_db["pin_cfn"]: cfn_net,
        }

        # ICL7660: LV and OSC pins — leave NC/unconnected for default operation
        # Pin 1 (NC) and pins 6 (LV), 7 (OSC) are not connected for standard
        # inverting operation. Only pin_vin, pin_gnd, pin_vout, pin_cfp, pin_cfn
        # are wired.

        # ---- Bypass capacitors ----
        bypass_caps: list[BypassCap] = []

        # Flying cap between C_FLY_P and C_FLY_N
        bypass_caps.append(
            BypassCap(
                "C_FLY",
                cfp_net,
                cfn_net,
                format_capacitance(c_fly),
                cap_footprint(c_fly),
                role="flying_cap",
                presentation="topology_local",
            )
        )

        # Output cap between VOUT and GND
        bypass_caps.append(
            BypassCap(
                "COUT",
                rail_name,
                "GND",
                format_capacitance(c_out),
                cap_footprint(c_out),
                role="output_cap",
                presentation="topology_local",
            )
        )

        # Input decoupling: 1uF
        bypass_caps.append(
            BypassCap(
                "CIN",
                vin_net,
                "GND",
                format_capacitance(c_in),
                cap_footprint(c_in),
                role="decoupling",
                presentation="topology_local",
            )
        )

        # ---- Annotations ----
        actual_ripple_out = iout / (fsw * c_out) * 1e3 if fsw > 0 and c_out > 0 else 0

        annotations = [
            f"Charge pump {ic_name}: {vin_net} -> {rail_name} (-VIN), {iout * 1e3:.0f}mA",
            (f"C_fly={format_capacitance(c_fly)}, Cout={format_capacitance(c_out)}, Cin={format_capacitance(c_in)}"),
            f"fsw={fsw / 1e3:.0f}kHz, ripple ~{actual_ripple_out:.0f}mV @ {iout * 1e3:.0f}mA",
        ]

        # ---- Build IC component ----
        ic_comp = ComponentDef(
            mpn=ic_name,
            ref_prefix="U",
            value=ic_name,
            footprint=ic_db["footprint"],
            description=ic_db["description"],
            category="power",
            pins=list(ic_db["pins"]),
            power_pins=power_pins,
            pin_nets=pin_nets,
            bypass_caps=bypass_caps,
            annotations=annotations,
        )
        ic_comp.source_ref = ref

        # ---- Boundary ports ----
        ports = [
            BoundaryPort(vin_net, "input"),
            BoundaryPort(rail_name, "output"),
            BoundaryPort("GND", "passive"),
        ]

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[
                f"Charge pump {ic_name}: {vin_net} -> {rail_name} (-VIN), {iout * 1e3:.0f}mA",
            ],
            primary_category="power",
        )
