"""Gate driver and level shifter subcircuit templates."""

from __future__ import annotations

from typing import Any

from ..component_db import BypassCap, ComponentDef, PinDef, StrapConfig
from .base import (
    FP_0402C,
    FP_0402R,
    BoundaryPort,
    SubcircuitResult,
    SubcircuitTemplate,
    format_capacitance,
)

GATE_DRIVER_DATABASE = {
    "IR2110": {
        "description": "High/Low Side Gate Driver DIP-14",
        "footprint": "Package_DIP:DIP-14_W7.62mm",
        "pins": [
            PinDef("1", "LO", "output", "R"),
            PinDef("2", "COM", "power_in", "B"),
            PinDef("3", "VCC", "power_in", "L"),
            PinDef("4", "NC", "passive", "R"),
            PinDef("5", "VS", "power_in", "R"),
            PinDef("6", "VB", "power_in", "T"),
            PinDef("7", "HO", "output", "R"),
            PinDef("8", "NC2", "passive", "R"),
            PinDef("9", "VDD", "power_in", "L"),
            PinDef("10", "HIN", "input", "L"),
            PinDef("11", "SD", "input", "L"),
            PinDef("12", "LIN", "input", "L"),
            PinDef("13", "NC3", "passive", "R"),
            PinDef("14", "NC4", "passive", "R"),
        ],
        "pin_vcc": "3",
        "pin_vdd": "9",
        "pin_vb": "6",
        "pin_vs": "5",
        "pin_com": "2",
        "pin_ho": "7",
        "pin_lo": "1",
        "pin_hin": "10",
        "pin_lin": "12",
        "pin_sd": "11",
        "cbst": 100e-9,
    },
    "UCC27524": {
        "description": "Dual 5A Low-Side Gate Driver SOIC-8",
        "footprint": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
        "pins": [
            PinDef("1", "INA", "input", "L"),
            PinDef("2", "INB", "input", "L"),
            PinDef("3", "GND", "power_in", "B"),
            PinDef("4", "GND2", "power_in", "B"),
            PinDef("5", "OUTB", "output", "R"),
            PinDef("6", "OUTA", "output", "R"),
            PinDef("7", "VDD", "power_in", "T"),
            PinDef("8", "VDD2", "power_in", "T"),
        ],
        "pin_vdd": "7",
        "pin_com": "3",
        "pin_ho": "6",
        "pin_lo": "5",
        "pin_hin": "1",
        "pin_lin": "2",
    },
}

LEVEL_SHIFTER_DATABASE = {
    "TXB0108": {
        "description": "8-bit Bidirectional Level Shifter TSSOP-20",
        "footprint": "Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm",
        "channels": 8,
        "pins": [
            PinDef("1", "VCCA", "power_in", "L"),
            PinDef("2", "A1", "bidirectional", "L"),
            PinDef("3", "A2", "bidirectional", "L"),
            PinDef("4", "A3", "bidirectional", "L"),
            PinDef("5", "A4", "bidirectional", "L"),
            PinDef("6", "A5", "bidirectional", "L"),
            PinDef("7", "A6", "bidirectional", "L"),
            PinDef("8", "A7", "bidirectional", "L"),
            PinDef("9", "A8", "bidirectional", "L"),
            PinDef("10", "GND", "power_in", "B"),
            PinDef("11", "OE", "input", "L"),
            PinDef("12", "B8", "bidirectional", "R"),
            PinDef("13", "B7", "bidirectional", "R"),
            PinDef("14", "B6", "bidirectional", "R"),
            PinDef("15", "B5", "bidirectional", "R"),
            PinDef("16", "B4", "bidirectional", "R"),
            PinDef("17", "B3", "bidirectional", "R"),
            PinDef("18", "B2", "bidirectional", "R"),
            PinDef("19", "B1", "bidirectional", "R"),
            PinDef("20", "VCCB", "power_in", "R"),
        ],
        "pin_vcca": "1",
        "pin_vccb": "20",
        "pin_gnd": "10",
        "pin_oe": "11",
    },
    "TXS0102": {
        "description": "2-bit Bidirectional Level Shifter SOT-23-8",
        "footprint": "Package_TO_SOT_SMD:SOT-23-8",
        "channels": 2,
        "pins": [
            PinDef("1", "B1", "bidirectional", "R"),
            PinDef("2", "GND", "power_in", "B"),
            PinDef("3", "VCCA", "power_in", "L"),
            PinDef("4", "A1", "bidirectional", "L"),
            PinDef("5", "A2", "bidirectional", "L"),
            PinDef("6", "VCCB", "power_in", "R"),
            PinDef("7", "OE", "input", "L"),
            PinDef("8", "B2", "bidirectional", "R"),
        ],
        "pin_vcca": "3",
        "pin_vccb": "6",
        "pin_gnd": "2",
        "pin_oe": "7",
    },
}


class GateDriverTemplate(SubcircuitTemplate):
    """Gate driver with bootstrap cap and decoupling."""

    template_type = "gate_driver"
    description = "Gate driver IC with bootstrap and decoupling"
    param_schema = [
        {"name": "ic", "type": "string", "required": False, "default": "UCC27524"},
        {"name": "ref", "type": "string", "required": False, "default": "U"},
        {"name": "vdd_net", "type": "string", "required": False, "default": "VDD_12V"},
        {"name": "gnd_net", "type": "string", "required": False, "default": "GND"},
        {"name": "hin_net", "type": "string", "required": False},
        {"name": "lin_net", "type": "string", "required": False},
    ]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        ic = params.get("ic", "UCC27524")
        if ic not in GATE_DRIVER_DATABASE:
            errors.append(f"Unknown gate driver '{ic}'. Available: {', '.join(GATE_DRIVER_DATABASE)}")
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        ic_name = params.get("ic", "UCC27524")
        ic_db = GATE_DRIVER_DATABASE.get(ic_name, GATE_DRIVER_DATABASE["UCC27524"])
        ref = params.get("ref", "U")
        vdd_net = params.get("vdd_net", "VDD_12V")
        gnd_net = params.get("gnd_net", "GND")
        hin_net = params.get("hin_net", f"HIN_{ref}")
        lin_net = params.get("lin_net", f"LIN_{ref}")

        power_pins = {ic_db["pin_vdd"]: vdd_net, ic_db["pin_com"]: gnd_net}
        if "pin_vcc" in ic_db:
            power_pins[ic_db["pin_vcc"]] = vdd_net

        pin_nets = {
            ic_db["pin_hin"]: hin_net,
            ic_db["pin_lin"]: lin_net,
            ic_db["pin_ho"]: f"HO_{ref}",
            ic_db["pin_lo"]: f"LO_{ref}",
        }
        if "pin_sd" in ic_db:
            pin_nets[ic_db["pin_sd"]] = vdd_net  # SD tied high = enabled

        bypass_caps = [
            BypassCap("C_VDD", vdd_net, gnd_net, "100nF", FP_0402C),
            BypassCap("C_VDD_BULK", vdd_net, gnd_net, "10uF", "Capacitor_SMD:C_0805_2012Metric"),
        ]

        # Bootstrap cap for high-side drivers
        straps = []
        if "pin_vb" in ic_db and "pin_vs" in ic_db:
            vs_net = f"VS_{ref}"
            power_pins[ic_db["pin_vs"]] = vs_net
            power_pins[ic_db["pin_vb"]] = f"VB_{ref}"
            cbst_val = ic_db.get("cbst", 100e-9)
            bypass_caps.append(
                BypassCap(
                    "C_BST",
                    f"VB_{ref}",
                    vs_net,
                    format_capacitance(cbst_val),
                    FP_0402C,
                    role="bootstrap",
                    presentation="topology_local",
                ),
            )

        annotations = [
            f"Gate driver: {ic_name}",
            f"HO={f'HO_{ref}'}, LO={f'LO_{ref}'}",
        ]

        comp = ComponentDef(
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

        ports = [
            BoundaryPort(vdd_net, "input"),
            BoundaryPort(gnd_net, "passive"),
            BoundaryPort(hin_net, "input"),
            BoundaryPort(lin_net, "input"),
            BoundaryPort(f"HO_{ref}", "output"),
            BoundaryPort(f"LO_{ref}", "output"),
        ]

        return SubcircuitResult(
            components=[comp],
            boundary_ports=ports,
            annotations=[f"Gate driver {ic_name}"],
            primary_category="power",
        )


class LevelShifterTemplate(SubcircuitTemplate):
    """Bidirectional level shifter with decoupling."""

    template_type = "level_shifter"
    description = "Bidirectional voltage level shifter"
    param_schema = [
        {"name": "ic", "type": "string", "required": False, "default": "TXS0102"},
        {"name": "ref", "type": "string", "required": False, "default": "U"},
        {"name": "vcca_net", "type": "string", "required": False, "default": "VDD_1P8"},
        {"name": "vccb_net", "type": "string", "required": False, "default": "VDD_3P3"},
        {"name": "gnd_net", "type": "string", "required": False, "default": "GND"},
    ]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        ic = params.get("ic", "TXS0102")
        if ic not in LEVEL_SHIFTER_DATABASE:
            errors.append(f"Unknown level shifter '{ic}'. Available: {', '.join(LEVEL_SHIFTER_DATABASE)}")
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        ic_name = params.get("ic", "TXS0102")
        ic_db = LEVEL_SHIFTER_DATABASE.get(ic_name, LEVEL_SHIFTER_DATABASE["TXS0102"])
        ref = params.get("ref", "U")
        vcca_net = params.get("vcca_net", "VDD_1P8")
        vccb_net = params.get("vccb_net", "VDD_3P3")
        gnd_net = params.get("gnd_net", "GND")

        power_pins = {
            ic_db["pin_vcca"]: vcca_net,
            ic_db["pin_vccb"]: vccb_net,
            ic_db["pin_gnd"]: gnd_net,
        }

        pin_nets = {ic_db["pin_oe"]: vcca_net}  # OE tied to VCCA = always enabled
        # Map A/B channel pins
        for pin in ic_db["pins"]:
            if pin.name.startswith("A") and pin.name[1:].isdigit():
                ch = pin.name[1:]
                pin_nets[pin.number] = f"LS_A{ch}_{ref}"
            elif pin.name.startswith("B") and pin.name[1:].isdigit():
                ch = pin.name[1:]
                pin_nets[pin.number] = f"LS_B{ch}_{ref}"

        bypass_caps = [
            BypassCap("C_VCCA", vcca_net, gnd_net, "100nF", FP_0402C),
            BypassCap("C_VCCB", vccb_net, gnd_net, "100nF", FP_0402C),
        ]

        straps = [
            StrapConfig(
                ic_db["pin_oe"], f"OE_{ref}", vcca_net, "10k", FP_0402R, role="pull_up", presentation="topology_local"
            ),
        ]

        annotations = [
            f"Level shifter: {ic_name} ({ic_db['channels']}ch)",
            f"VCCA={vcca_net}, VCCB={vccb_net}",
        ]

        comp = ComponentDef(
            mpn=ic_name,
            ref_prefix="U",
            value=ic_name,
            footprint=ic_db["footprint"],
            description=ic_db["description"],
            category="digital",
            pins=list(ic_db["pins"]),
            power_pins=power_pins,
            pin_nets=pin_nets,
            bypass_caps=bypass_caps,
            straps=straps,
            annotations=annotations,
        )

        ports = [
            BoundaryPort(vcca_net, "input"),
            BoundaryPort(vccb_net, "input"),
            BoundaryPort(gnd_net, "passive"),
        ]
        for i in range(1, ic_db["channels"] + 1):
            ports.append(BoundaryPort(f"LS_A{i}_{ref}", "bidirectional"))
            ports.append(BoundaryPort(f"LS_B{i}_{ref}", "bidirectional"))

        return SubcircuitResult(
            components=[comp],
            boundary_ports=ports,
            annotations=[f"Level shifter {ic_name}: {vcca_net} <-> {vccb_net}"],
            primary_category="digital",
        )
