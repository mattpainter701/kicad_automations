"""Gate driver and level shifter subcircuit templates."""

from __future__ import annotations

from typing import Any

from ..component_db import BypassCap, ComponentDef, StrapConfig
from .base import (
    FP_0402C,
    FP_0402R,
    BoundaryPort,
    LegacyDBProxy,
    SubcircuitResult,
    SubcircuitTemplate,
    format_capacitance,
)

GATE_DRIVER_DATABASE = LegacyDBProxy("gate_driver")  # backed by ic_data/*.json (Task 178)

LEVEL_SHIFTER_DATABASE = LegacyDBProxy("level_shifter")  # backed by ic_data/*.json (Task 178)


class GateDriverTemplate(SubcircuitTemplate):
    """Gate driver with bootstrap cap and decoupling."""

    template_type = "gate_driver"
    description = "Gate driver IC with bootstrap and decoupling"
    param_schema = [
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "UCC27524",
            "description": "Gate driver IC MPN",
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
            "default": "VDD_12V",
            "description": "Driver supply rail net name",
        },
        {"name": "gnd_net", "type": "string", "required": False, "default": "GND", "description": "Ground net name"},
        {
            "name": "hin_net",
            "type": "string",
            "required": False,
            "description": "High-side PWM input net name; defaults to HIN_{ref}",
        },
        {
            "name": "lin_net",
            "type": "string",
            "required": False,
            "description": "Low-side PWM input net name; defaults to LIN_{ref}",
        },
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
        for pin_num in ic_db.get("pin_vdd_extra", []):
            power_pins[pin_num] = vdd_net
        for pin_num in ic_db.get("pin_com_extra", []):
            power_pins[pin_num] = gnd_net
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
                    role="bootstrap_cap",
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
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "TXS0102",
            "description": "Level shifter IC MPN",
        },
        {
            "name": "ref",
            "type": "string",
            "required": False,
            "default": "U",
            "description": "Reference designator for the IC",
        },
        {
            "name": "vcca_net",
            "type": "string",
            "required": False,
            "default": "VDD_1P8",
            "description": "Low-voltage side supply rail net name (A port)",
        },
        {
            "name": "vccb_net",
            "type": "string",
            "required": False,
            "default": "VDD_3P3",
            "description": "High-voltage side supply rail net name (B port)",
        },
        {"name": "gnd_net", "type": "string", "required": False, "default": "GND", "description": "Ground net name"},
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
        oe_net = f"OE_{ref}"

        power_pins = {
            ic_db["pin_vcca"]: vcca_net,
            ic_db["pin_vccb"]: vccb_net,
            ic_db["pin_gnd"]: gnd_net,
        }

        pin_nets = {ic_db["pin_oe"]: oe_net}  # OE pulled high = always enabled
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
                ic_db["pin_oe"], oe_net, vcca_net, "10k", FP_0402R, role="pull_up", presentation="topology_local"
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
