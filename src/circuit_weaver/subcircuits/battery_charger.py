"""Li-Ion/LiPo battery charger subcircuit template.

Generates a complete single-cell Li-Ion/LiPo charger subcircuit from design
parameters: charge current, cell voltage, IC selection.

Auto-calculates: Rprog (charge current programming resistor), input/output
caps. All values snapped to standard E96 series.

Supports MCP73831T (default) and TP4056 topologies.
"""

from __future__ import annotations

from typing import Any

from ..component_db import BypassCap, ComponentDef, PinDef, StrapConfig
from .base import (
    FP_0402R,
    BoundaryPort,
    SubcircuitResult,
    SubcircuitTemplate,
    cap_footprint,
    format_capacitance,
    format_resistance,
    snap_to_e96,
)

# Known battery charger ICs and their parameters
CHARGER_IC_DATABASE = {
    "MCP73831T-2ACI/OT": {
        "description": "500mA Li-Ion/LiPo Charger SOT-23-5",
        "footprint": "SOT-23-5",
        "vcell": 4.2,
        "ichg_max": 0.5,
        "k_prog": 1000,  # Rprog = K_prog / Ichg
        "pins": [
            PinDef("1", "STAT", "output", "R"),
            PinDef("2", "VSS", "power_in", "B"),
            PinDef("3", "VBAT", "power_out", "R"),
            PinDef("4", "VDD", "power_in", "L"),
            PinDef("5", "PROG", "input", "R"),
        ],
        "pin_vdd": "4",
        "pin_gnd": "2",
        "pin_bat": "3",
        "pin_prog": "5",
        "pin_stat": "1",
        "pin_temp": None,
        "pin_ce": None,
        "has_temp_pin": False,
    },
    "TP4056": {
        "description": "1A Li-Ion/LiPo Charger SOP-8",
        "footprint": "SOP-8",
        "vcell": 4.2,
        "ichg_max": 1.0,
        "k_prog": 1200,  # Rprog = K_prog / Ichg
        "pins": [
            PinDef("1", "TEMP", "input", "L"),
            PinDef("2", "PROG", "input", "R"),
            PinDef("3", "GND", "power_in", "B"),
            PinDef("4", "VCC", "power_in", "L"),
            PinDef("5", "STDBY", "output", "R"),
            PinDef("6", "CHRG", "output", "R"),
            PinDef("7", "BAT", "power_out", "R"),
            PinDef("8", "CE", "input", "L"),
        ],
        "pin_vdd": "4",
        "pin_gnd": "3",
        "pin_bat": "7",
        "pin_prog": "2",
        "pin_stat": "6",
        "pin_temp": "1",
        "pin_ce": "8",
        "has_temp_pin": True,
    },
}


class BatteryChargerTemplate(SubcircuitTemplate):
    """Li-Ion/LiPo single-cell charger with programmable charge current."""

    template_type = "battery_charger"
    description = "Li-Ion/LiPo battery charger with programmable charge current"
    param_schema = [
        {
            "name": "ichg",
            "type": "number",
            "required": True,
            "description": "Charge current in amps",
        },
        {
            "name": "vcell",
            "type": "number",
            "required": False,
            "default": 4.2,
            "description": "Cell termination voltage in volts",
        },
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "MCP73831T-2ACI/OT",
            "description": "Charger IC MPN",
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
            "default": "VUSB",
            "description": "Input power net name",
        },
        {
            "name": "bat_net",
            "type": "string",
            "required": False,
            "default": "VBAT",
            "description": "Battery output net name",
        },
        {
            "name": "stat_net",
            "type": "string",
            "required": False,
            "description": "Charge status output net name",
        },
    ]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        ichg = params.get("ichg")
        ic_name = params.get("ic", "MCP73831T-2ACI/OT")
        if ichg is None:
            errors.append("Missing required param 'ichg' (charge current in A)")
        elif ichg <= 0:
            errors.append(f"ichg ({ichg}A) must be positive")
        if ichg is not None and ichg > 0:
            ic_db = CHARGER_IC_DATABASE.get(ic_name, CHARGER_IC_DATABASE["MCP73831T-2ACI/OT"])
            if ichg > ic_db["ichg_max"]:
                errors.append(f"ichg ({ichg}A) exceeds {ic_name} maximum ({ic_db['ichg_max']}A)")
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        """Generate a battery charger subcircuit.

        Required params:
            ichg: float — charge current (A)

        Optional params:
            vcell: float — cell termination voltage (V, default: 4.2)
            ic: str — IC MPN (default: "MCP73831T-2ACI/OT")
            ref: str — reference designator for IC (default: "U")
            vin_net: str — input power net name (default: "VUSB")
            bat_net: str — battery output net name (default: "VBAT")
            stat_net: str — charge status net name (default: "STAT_{ref}")
        """
        ichg = params["ichg"]
        vcell = params.get("vcell", 4.2)
        ic_name = params.get("ic", "MCP73831T-2ACI/OT")
        ref = params.get("ref", "U")
        vin_net = params.get("vin_net", "VUSB")
        bat_net = params.get("bat_net", "VBAT")
        stat_net = params.get("stat_net", f"STAT_{ref}")

        # Look up IC parameters
        ic_db = CHARGER_IC_DATABASE.get(ic_name, CHARGER_IC_DATABASE["MCP73831T-2ACI/OT"])
        k_prog = ic_db["k_prog"]

        # ---- Calculate passive values ----

        # Rprog: sets charge current. Rprog = K_prog / Ichg
        rprog_raw = k_prog / ichg
        rprog = snap_to_e96(rprog_raw)
        actual_ichg = k_prog / rprog

        # Input cap: 4.7uF
        cin_val = 4.7e-6

        # Output cap on VBAT: 4.7uF
        cout_val = 4.7e-6

        # ---- Net names (unique per instance) ----
        prog_net = f"PROG_{ref}"

        # ---- Build IC component ----
        power_pins = {
            ic_db["pin_vdd"]: vin_net,
            ic_db["pin_gnd"]: "GND",
            ic_db["pin_bat"]: bat_net,
        }

        pin_nets = {
            ic_db["pin_prog"]: prog_net,
            ic_db["pin_stat"]: stat_net,
        }

        # CE pin (TP4056): tie to VIN to enable charging
        if ic_db.get("pin_ce"):
            pin_nets[ic_db["pin_ce"]] = vin_net

        bypass_caps = [
            BypassCap(
                "CIN",
                vin_net,
                "GND",
                format_capacitance(cin_val),
                cap_footprint(cin_val),
                role="input_cap",
                presentation="topology_local",
            ),
            BypassCap(
                "CBAT",
                bat_net,
                "GND",
                format_capacitance(cout_val),
                cap_footprint(cout_val),
                role="output_cap",
                presentation="topology_local",
            ),
        ]

        straps = [
            StrapConfig(
                "RPROG",
                prog_net,
                "GND",
                format_resistance(rprog),
                FP_0402R,
                role="current_program",
                presentation="topology_local",
            ),
        ]

        # TEMP pin (TP4056): 10k to GND disables temperature sensing
        if ic_db.get("has_temp_pin") and ic_db.get("pin_temp"):
            temp_net = f"TEMP_{ref}"
            pin_nets[ic_db["pin_temp"]] = temp_net
            straps.append(
                StrapConfig(
                    "RTEMP",
                    temp_net,
                    "GND",
                    format_resistance(snap_to_e96(10e3)),
                    FP_0402R,
                    role="temp_disable",
                    presentation="topology_local",
                ),
            )

        # Thermal dissipation warning
        vin_typical = 5.0  # assume USB 5V input
        pdiss = (vin_typical - vcell) * ichg

        annotations = [
            f"Charge {bat_net}: {ichg}A into {vcell}V cell from {vin_net}",
            f"Rprog = {k_prog} / {ichg}A = {format_resistance(rprog)} (actual {actual_ichg:.3f}A)",
            f"Cin={format_capacitance(cin_val)}, Cbat={format_capacitance(cout_val)}",
            f"Thermal: Pdiss = (Vin - Vbat) * Ichg = ({vin_typical}V - {vcell}V) * {ichg}A = {pdiss:.2f}W",
        ]

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
            straps=straps,
            annotations=annotations,
        )
        ic_comp.source_ref = ref

        # ---- Boundary ports ----
        ports = [
            BoundaryPort(vin_net, "input"),
            BoundaryPort(bat_net, "output"),
            BoundaryPort("GND", "passive"),
            BoundaryPort(stat_net, "output"),
        ]

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[
                f"Charger {ic_name}: {vin_net} -> {bat_net} ({vcell}V) at {ichg}A",
            ],
            primary_category="power",
        )
