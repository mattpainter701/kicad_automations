"""LDO regulator subcircuit template.

Generates a complete LDO regulator subcircuit with input/output caps,
dropout/thermal checks, and optional feedback divider for adjustable LDOs.
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
)

# Known LDO ICs
LDO_IC_DATABASE = {
    "TLV75518": {
        "description": "500mA LDO 1.8V Fixed Low-Noise",
        "footprint": "SOT-23-5",
        "vout_fixed": 1.8,
        "adjustable": False,
        "iout_max": 0.5,
        "vdropout": 0.180,
        "iq_ua": 35,
        "cin": 1e-6,
        "cout": 1e-6,
        "pins": [
            PinDef("1", "IN", "power_in", "L"),
            PinDef("2", "GND", "power_in", "B"),
            PinDef("3", "EN", "input", "L"),
            PinDef("4", "NC", "passive", "R"),
            PinDef("5", "OUT", "power_out", "R"),
        ],
        "pin_vin": "1",
        "pin_gnd": "2",
        "pin_out": "5",
        "pin_en": "3",
    },
    "AMS1117-3.3": {
        "description": "1A LDO 3.3V Fixed",
        "footprint": "SOT-223",
        "vout_fixed": 3.3,
        "adjustable": False,
        "iout_max": 1.0,
        "vdropout": 1.1,
        "iq_ua": 5000,
        "cin": 10e-6,
        "cout": 22e-6,
        "pins": [
            PinDef("1", "GND", "power_in", "B"),
            PinDef("2", "OUT", "power_out", "R"),
            PinDef("3", "IN", "power_in", "L"),
            PinDef("4", "OUT", "power_out", "R"),
        ],
        "pin_vin": "3",
        "pin_gnd": "1",
        "pin_out": "2",
        "pin_en": None,
    },
    "AP2112K-3.3": {
        "description": "600mA LDO 3.3V Fixed Low-Noise",
        "footprint": "SOT-23-5",
        "vout_fixed": 3.3,
        "adjustable": False,
        "iout_max": 0.6,
        "vdropout": 0.250,
        "iq_ua": 55,
        "cin": 1e-6,
        "cout": 1e-6,
        "pins": [
            PinDef("1", "OUT", "power_out", "R"),
            PinDef("2", "GND", "power_in", "B"),
            PinDef("3", "EN", "input", "L"),
            PinDef("4", "NC", "passive", "R"),
            PinDef("5", "IN", "power_in", "L"),
        ],
        "pin_vin": "5",
        "pin_gnd": "2",
        "pin_out": "1",
        "pin_en": "3",
    },
    "MCP1700-3302E": {
        "description": "250mA LDO 3.3V Low-Iq",
        "footprint": "SOT-23",
        "vout_fixed": 3.3,
        "adjustable": False,
        "iout_max": 0.250,
        "vdropout": 0.178,
        "iq_ua": 1.6,
        "cin": 1e-6,
        "cout": 1e-6,
        "pins": [
            PinDef("1", "GND", "power_in", "B"),
            PinDef("2", "OUT", "power_out", "R"),
            PinDef("3", "IN", "power_in", "L"),
        ],
        "pin_vin": "3",
        "pin_gnd": "1",
        "pin_out": "2",
        "pin_en": None,
    },
}


class LDOTemplate(SubcircuitTemplate):
    """LDO regulator with input/output caps and thermal checks."""

    template_type = "ldo"
    description = "LDO linear regulator with decoupling"
    param_schema = [
        {
            "name": "vin",
            "type": "number",
            "required": True,
            "description": "Input voltage in volts",
        },
        {
            "name": "vout",
            "type": "number",
            "required": False,
            "description": "Output voltage in volts; inferred from fixed-output ICs when omitted",
        },
        {
            "name": "iout",
            "type": "number",
            "required": False,
            "description": "Maximum output current in amps",
        },
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "TLV75518",
            "description": "LDO IC MPN; fixed-output parts can imply vout",
        },
        {
            "name": "ref",
            "type": "string",
            "required": False,
            "default": "U",
            "description": "Reference designator for the IC",
        },
        {
            "name": "rail_name",
            "type": "string",
            "required": False,
            "description": "Output rail net name",
        },
        {
            "name": "vin_net",
            "type": "string",
            "required": False,
            "default": "VIN",
            "description": "Input rail net name",
        },
        {
            "name": "en_net",
            "type": "string",
            "required": False,
            "description": "Enable net name; defaults to vin_net",
        },
    ]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        if params.get("vin") is None:
            errors.append("Missing required param 'vin'")
        if params.get("vout") is None and params.get("ic") is None:
            errors.append("Need either 'vout' or 'ic' (fixed-output LDO implies vout)")
        vin = params.get("vin", 0)
        vout = params.get("vout", 0)
        if vin > 0 and vout > 0 and vout >= vin:
            errors.append(f"vout ({vout}V) must be less than vin ({vin}V)")
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        """Generate an LDO subcircuit.

        Required params:
            vin: float — input voltage (V)

        Optional params:
            vout: float — output voltage (V, inferred from IC if fixed)
            iout: float — max output current (A, default from IC spec)
            ic: str — IC MPN (default: "TLV75518")
            ref: str — reference designator
            rail_name: str — output rail net name
            vin_net: str — input rail net name
            en_net: str — enable net (default: vin_net)
        """
        ic_name = params.get("ic", "TLV75518")
        ic_db = LDO_IC_DATABASE.get(ic_name, LDO_IC_DATABASE["TLV75518"])

        vin = params["vin"]
        vout = params.get("vout", ic_db.get("vout_fixed", 3.3))
        iout = params.get("iout", ic_db["iout_max"])
        rail_name = params.get("rail_name") or f"VDD_{vout:.1f}V".replace(".", "P")
        vin_net = params.get("vin_net", "VIN")
        en_net = params.get("en_net", vin_net)

        # Dropout and thermal checks
        warnings = []
        vdropout = ic_db["vdropout"]
        if vin - vout < vdropout:
            warnings.append(f"WARNING: Vin-Vout={vin - vout:.2f}V < Vdropout={vdropout:.3f}V")

        pdiss = (vin - vout) * iout
        if pdiss > 0.5:
            warnings.append(f"WARNING: Pdiss={pdiss:.2f}W > 500mW — needs heatsink or copper pour")

        # Cap values from datasheet
        cin_val = ic_db.get("cin", 1e-6)
        cout_val = ic_db.get("cout", 1e-6)

        # Build IC
        power_pins = {
            ic_db["pin_vin"]: vin_net,
            ic_db["pin_gnd"]: "GND",
            ic_db["pin_out"]: rail_name,
        }
        pin_nets = {}
        if ic_db.get("pin_en"):
            pin_nets[ic_db["pin_en"]] = en_net

        bypass_caps = [
            BypassCap("CIN", vin_net, "GND", format_capacitance(cin_val), cap_footprint(cin_val)),
            BypassCap(
                "COUT", rail_name, "GND", format_capacitance(cout_val), cap_footprint(cout_val)
            ),
        ]

        annotations = [
            f"{rail_name}: {vout}V from {vin_net} at {iout}A ({ic_name})",
            f"Dropout: {vdropout:.3f}V, Pdiss: {pdiss:.2f}W, Iq: {ic_db['iq_ua']}uA",
        ]
        annotations.extend(warnings)

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

        ports = [
            BoundaryPort(vin_net, "input"),
            BoundaryPort(rail_name, "output"),
            BoundaryPort("GND", "passive"),
        ]
        if ic_db.get("pin_en"):
            ports.append(BoundaryPort(en_net, "input"))

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[
                f"LDO {ic_name}: {vin_net} ({vin}V) -> {rail_name} ({vout}V) at {iout}A",
            ]
            + warnings,
            primary_category="power",
        )
