"""RS-485 transceiver subcircuit template.

Generates a complete RS-485 half-duplex transceiver subcircuit with VCC
decoupling, DE/RE_N control, optional 120R termination, and optional
failsafe bias resistors.

Supports SP3485EN-L/TR (3.3V) and MAX485ESA+ (5V).
"""

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
    format_resistance,
    snap_to_e24,
    snap_to_e96,
)

# Known RS-485 transceiver ICs
RS485_TRANSCEIVER_IC_DATABASE = {
    "SP3485EN-L/TR": {
        "description": "RS-485 Transceiver 3.3V 10Mbps SOIC-8",
        "footprint": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
        "vdd": 3.3,
        "speed_mbps": 10,
        "pins": [
            PinDef("1", "RO", "output", "L"),
            PinDef("2", "RE_N", "input", "L"),
            PinDef("3", "DE", "input", "L"),
            PinDef("4", "DI", "input", "L"),
            PinDef("5", "GND", "power_in", "B"),
            PinDef("6", "A", "bidirectional", "R"),
            PinDef("7", "B", "bidirectional", "R"),
            PinDef("8", "VCC", "power_in", "T"),
        ],
        "pin_ro": "1",
        "pin_re_n": "2",
        "pin_de": "3",
        "pin_di": "4",
        "pin_gnd": "5",
        "pin_a": "6",
        "pin_b": "7",
        "pin_vcc": "8",
    },
    "MAX485ESA+": {
        "description": "RS-485 Transceiver 5V 2.5Mbps SOIC-8",
        "footprint": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
        "vdd": 5.0,
        "speed_mbps": 2.5,
        "pins": [
            PinDef("1", "RO", "output", "L"),
            PinDef("2", "RE_N", "input", "L"),
            PinDef("3", "DE", "input", "L"),
            PinDef("4", "DI", "input", "L"),
            PinDef("5", "GND", "power_in", "B"),
            PinDef("6", "A", "bidirectional", "R"),
            PinDef("7", "B", "bidirectional", "R"),
            PinDef("8", "VCC", "power_in", "T"),
        ],
        "pin_ro": "1",
        "pin_re_n": "2",
        "pin_de": "3",
        "pin_di": "4",
        "pin_gnd": "5",
        "pin_a": "6",
        "pin_b": "7",
        "pin_vcc": "8",
    },
}


class RS485TransceiverTemplate(SubcircuitTemplate):
    """RS-485 half-duplex transceiver with decoupling, bias, and optional termination."""

    template_type = "rs485_transceiver"
    description = "RS-485 half-duplex transceiver with failsafe bias and optional termination"
    param_schema = [
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "SP3485EN-L/TR",
            "description": "RS-485 transceiver IC MPN",
        },
        {
            "name": "ref",
            "type": "string",
            "required": False,
            "default": "U",
            "description": "Reference designator for the transceiver",
        },
        {
            "name": "vdd_net",
            "type": "string",
            "required": False,
            "default": "VDD_3P3",
            "description": "Supply rail net name",
        },
        {
            "name": "txd_net",
            "type": "string",
            "required": False,
            "description": "TXD signal net from MCU (connects to DI)",
        },
        {
            "name": "rxd_net",
            "type": "string",
            "required": False,
            "description": "RXD signal net to MCU (connects to RO)",
        },
        {
            "name": "de_net",
            "type": "string",
            "required": False,
            "description": "Driver enable net (active high, shared with RE_N for half-duplex)",
        },
        {
            "name": "bus_net_prefix",
            "type": "string",
            "required": False,
            "default": "RS485",
            "description": "Prefix for A/B bus nets",
        },
        {
            "name": "termination",
            "type": "boolean",
            "required": False,
            "default": False,
            "description": "Enable 120R termination between A and B",
        },
        {
            "name": "failsafe_bias",
            "type": "boolean",
            "required": False,
            "default": True,
            "description": "Enable failsafe bias resistors (A pull-up, B pull-down)",
        },
    ]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        ic_name = params.get("ic", "SP3485EN-L/TR")
        if ic_name not in RS485_TRANSCEIVER_IC_DATABASE:
            errors.append(
                f"Unknown RS-485 transceiver '{ic_name}'. Supported: {', '.join(RS485_TRANSCEIVER_IC_DATABASE)}"
            )
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        """Generate an RS-485 transceiver subcircuit.

        Required params: (none -- all have defaults)

        Optional params:
            ic: str -- IC MPN (default: "SP3485EN-L/TR")
            ref: str -- reference designator (default: "U")
            vdd_net: str -- supply rail (default: "VDD_3P3")
            txd_net: str -- TXD net from MCU
            rxd_net: str -- RXD net to MCU
            de_net: str -- driver enable net (shared DE/RE_N for half-duplex)
            bus_net_prefix: str -- prefix for bus nets (default: "RS485")
            termination: bool -- 120R termination (default: False)
            failsafe_bias: bool -- failsafe bias resistors (default: True)
        """
        ic_name = params.get("ic", "SP3485EN-L/TR")
        ic_db = RS485_TRANSCEIVER_IC_DATABASE.get(ic_name, RS485_TRANSCEIVER_IC_DATABASE["SP3485EN-L/TR"])
        ref = params.get("ref", "U")
        vdd_net = params.get("vdd_net", "VDD_3P3")
        txd_net = params.get("txd_net", f"RS485_TXD_{ref}")
        rxd_net = params.get("rxd_net", f"RS485_RXD_{ref}")
        de_net = params.get("de_net", f"RS485_DE_{ref}")
        bus_prefix = params.get("bus_net_prefix", "RS485")
        termination = params.get("termination", False)
        failsafe_bias = params.get("failsafe_bias", True)

        # ---- Net names (unique per instance) ----
        a_net = f"{bus_prefix}_A_{ref}"
        b_net = f"{bus_prefix}_B_{ref}"

        # ---- Power pins ----
        power_pins = {
            ic_db["pin_vcc"]: vdd_net,
            ic_db["pin_gnd"]: "GND",
        }

        # ---- Signal pin nets ----
        # Half-duplex: DE and RE_N share the same control net
        pin_nets = {
            ic_db["pin_di"]: txd_net,
            ic_db["pin_ro"]: rxd_net,
            ic_db["pin_de"]: de_net,
            ic_db["pin_re_n"]: de_net,
            ic_db["pin_a"]: a_net,
            ic_db["pin_b"]: b_net,
        }

        # ---- Bypass capacitors ----
        bypass_caps = [
            BypassCap(
                "C_VCC",
                vdd_net,
                "GND",
                format_capacitance(100e-9),
                FP_0402C,
                role="decoupling",
                presentation="topology_local",
            ),
        ]

        # ---- Strap resistors ----
        straps = []

        # Termination: 120R between A and B
        if termination:
            straps.append(
                StrapConfig(
                    "RT",
                    a_net,
                    b_net,
                    format_resistance(snap_to_e96(120)),
                    FP_0402R,
                    role="termination",
                    presentation="topology_local",
                )
            )

        # Failsafe bias: pull A high, pull B low to ensure idle = logic 1
        if failsafe_bias:
            straps.append(
                StrapConfig(
                    "RBIAS_A",
                    a_net,
                    vdd_net,
                    format_resistance(snap_to_e24(390)),
                    FP_0402R,
                    role="bias",
                    presentation="topology_local",
                )
            )
            straps.append(
                StrapConfig(
                    "RBIAS_B",
                    b_net,
                    "GND",
                    format_resistance(snap_to_e24(390)),
                    FP_0402R,
                    role="bias",
                    presentation="topology_local",
                )
            )

        # ---- Annotations ----
        annotations = [
            f"RS-485 {ic_name}: {ic_db['vdd']}V half-duplex, {ic_db['speed_mbps']}Mbps",
            f"Failsafe bias: {'390R pull-up A, 390R pull-down B' if failsafe_bias else 'none'}",
            f"Termination: {'120R A-B' if termination else 'none'}",
        ]

        # ---- Build IC component ----
        ic_comp = ComponentDef(
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

        # ---- Boundary ports ----
        ports = [
            BoundaryPort(vdd_net, "input"),
            BoundaryPort("GND", "passive"),
            BoundaryPort(txd_net, "input"),
            BoundaryPort(rxd_net, "output"),
            BoundaryPort(de_net, "input"),
            BoundaryPort(a_net, "bidirectional"),
            BoundaryPort(b_net, "bidirectional"),
        ]

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[
                f"RS-485 {ic_name}: {vdd_net} ({ic_db['vdd']}V) half-duplex, "
                f"{'failsafe biased' if failsafe_bias else 'no bias'}, "
                f"{'terminated' if termination else 'unterminated'}",
            ],
            primary_category="digital",
        )
