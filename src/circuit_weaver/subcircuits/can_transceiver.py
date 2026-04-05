"""CAN bus transceiver subcircuit template.

Generates a complete CAN transceiver subcircuit with VCC decoupling,
VREF bypass, RS slope control, and optional split termination.

Supports SN65HVD230 (3.3V) and MCP2551 (5V).
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
    cap_footprint,
    format_capacitance,
    format_resistance,
    snap_cap,
    snap_to_e24,
    snap_to_e96,
)

# Known CAN transceiver ICs
CAN_TRANSCEIVER_IC_DATABASE = {
    "SN65HVD230": {
        "description": "CAN Transceiver 3.3V 1Mbps SOIC-8",
        "footprint": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
        "vdd": 3.3,
        "speed_mbps": 1,
        "pins": [
            PinDef("1", "D", "input", "L"),
            PinDef("2", "GND", "power_in", "B"),
            PinDef("3", "VCC", "power_in", "T"),
            PinDef("4", "R", "output", "L"),
            PinDef("5", "VREF", "output", "R"),
            PinDef("6", "CANL", "bidirectional", "R"),
            PinDef("7", "CANH", "bidirectional", "R"),
            PinDef("8", "RS", "input", "L"),
        ],
        "pin_txd": "1",
        "pin_gnd": "2",
        "pin_vcc": "3",
        "pin_rxd": "4",
        "pin_vref": "5",
        "pin_canl": "6",
        "pin_canh": "7",
        "pin_rs": "8",
        "rs_highspeed_to_gnd": True,
    },
    "MCP2551-I/SN": {
        "description": "CAN Transceiver 5V 1Mbps SOIC-8",
        "footprint": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
        "vdd": 5.0,
        "speed_mbps": 1,
        "pins": [
            PinDef("1", "TXD", "input", "L"),
            PinDef("2", "VSS", "power_in", "B"),
            PinDef("3", "VDD", "power_in", "T"),
            PinDef("4", "RXD", "output", "L"),
            PinDef("5", "VREF", "output", "R"),
            PinDef("6", "CANL", "bidirectional", "R"),
            PinDef("7", "CANH", "bidirectional", "R"),
            PinDef("8", "RS", "input", "L"),
        ],
        "pin_txd": "1",
        "pin_gnd": "2",
        "pin_vcc": "3",
        "pin_rxd": "4",
        "pin_vref": "5",
        "pin_canl": "6",
        "pin_canh": "7",
        "pin_rs": "8",
        "rs_highspeed_to_gnd": True,
    },
}


class CANTransceiverTemplate(SubcircuitTemplate):
    """CAN bus transceiver with decoupling, VREF bypass, and optional termination."""

    template_type = "can_transceiver"
    description = "CAN bus transceiver with decoupling and optional split termination"
    param_schema = [
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "SN65HVD230",
            "description": "CAN transceiver IC MPN",
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
            "description": "TXD signal net from MCU",
        },
        {
            "name": "rxd_net",
            "type": "string",
            "required": False,
            "description": "RXD signal net to MCU",
        },
        {
            "name": "bus_net_prefix",
            "type": "string",
            "required": False,
            "default": "CAN",
            "description": "Prefix for CANH/CANL bus nets",
        },
        {
            "name": "termination",
            "type": "boolean",
            "required": False,
            "default": False,
            "description": "Enable split termination (2x60R + 4.7nF)",
        },
        {
            "name": "slope_control",
            "type": "boolean",
            "required": False,
            "default": False,
            "description": "Enable slope control via 10k on RS pin (otherwise RS to GND)",
        },
    ]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        ic_name = params.get("ic", "SN65HVD230")
        if ic_name not in CAN_TRANSCEIVER_IC_DATABASE:
            errors.append(f"Unknown CAN transceiver '{ic_name}'. Supported: {', '.join(CAN_TRANSCEIVER_IC_DATABASE)}")
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        """Generate a CAN transceiver subcircuit.

        Required params: (none -- all have defaults)

        Optional params:
            ic: str -- IC MPN (default: "SN65HVD230")
            ref: str -- reference designator (default: "U")
            vdd_net: str -- supply rail (default: "VDD_3P3")
            txd_net: str -- TXD net from MCU
            rxd_net: str -- RXD net to MCU
            bus_net_prefix: str -- prefix for bus nets (default: "CAN")
            termination: bool -- split termination (default: False)
            slope_control: bool -- RS slope control resistor (default: False)
        """
        ic_name = params.get("ic", "SN65HVD230")
        ic_db = CAN_TRANSCEIVER_IC_DATABASE.get(ic_name, CAN_TRANSCEIVER_IC_DATABASE["SN65HVD230"])
        ref = params.get("ref", "U")
        vdd_net = params.get("vdd_net", "VDD_3P3")
        txd_net = params.get("txd_net", f"CAN_TXD_{ref}")
        rxd_net = params.get("rxd_net", f"CAN_RXD_{ref}")
        bus_prefix = params.get("bus_net_prefix", "CAN")
        termination = params.get("termination", False)
        slope_control = params.get("slope_control", False)

        # ---- Net names (unique per instance) ----
        canh_net = f"{bus_prefix}_H_{ref}"
        canl_net = f"{bus_prefix}_L_{ref}"
        vref_net = f"CAN_VREF_{ref}"

        # ---- Power pins ----
        power_pins = {
            ic_db["pin_vcc"]: vdd_net,
            ic_db["pin_gnd"]: "GND",
        }

        # ---- Signal pin nets ----
        pin_nets = {
            ic_db["pin_txd"]: txd_net,
            ic_db["pin_rxd"]: rxd_net,
            ic_db["pin_canh"]: canh_net,
            ic_db["pin_canl"]: canl_net,
            ic_db["pin_vref"]: vref_net,
        }

        # RS pin: high-speed mode ties to GND; slope control uses strap resistor
        if slope_control:
            rs_net = f"CAN_RS_{ref}"
            pin_nets[ic_db["pin_rs"]] = rs_net
        elif ic_db["rs_highspeed_to_gnd"]:
            pin_nets[ic_db["pin_rs"]] = "GND"

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
            BypassCap(
                "C_VREF",
                vref_net,
                "GND",
                format_capacitance(100e-9),
                FP_0402C,
                role="decoupling",
                presentation="topology_local",
            ),
        ]

        # ---- Strap resistors ----
        straps = []

        # Slope control: 10k from RS to GND
        if slope_control:
            straps.append(
                StrapConfig(
                    "RS",
                    rs_net,
                    "GND",
                    format_resistance(snap_to_e24(10e3)),
                    FP_0402R,
                    role="slope_control",
                    presentation="topology_local",
                )
            )

        # ---- Split termination (if enabled) ----
        if termination:
            term_mid_net = f"CAN_TERM_MID_{ref}"
            # RT1: 60R from CANH to midpoint
            straps.append(
                StrapConfig(
                    "RT1",
                    canh_net,
                    term_mid_net,
                    format_resistance(snap_to_e96(60)),
                    FP_0402R,
                    role="termination",
                    presentation="topology_local",
                )
            )
            # RT2: 60R from midpoint to CANL
            straps.append(
                StrapConfig(
                    "RT2",
                    term_mid_net,
                    canl_net,
                    format_resistance(snap_to_e96(60)),
                    FP_0402R,
                    role="termination",
                    presentation="topology_local",
                )
            )
            # CT: 4.7nF from midpoint to GND
            bypass_caps.append(
                BypassCap(
                    "CT",
                    term_mid_net,
                    "GND",
                    format_capacitance(snap_cap(4.7e-9)),
                    cap_footprint(4.7e-9),
                    role="termination",
                    presentation="topology_local",
                )
            )

        # ---- Annotations ----
        annotations = [
            f"CAN transceiver {ic_name}: {ic_db['vdd']}V, {ic_db['speed_mbps']}Mbps",
            f"Termination: {'split 2x60R + 4.7nF' if termination else 'none'}",
        ]
        if slope_control:
            annotations.append("Slope control: 10k to GND")
        else:
            annotations.append("RS to GND: high-speed mode")

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
            BoundaryPort(canh_net, "bidirectional"),
            BoundaryPort(canl_net, "bidirectional"),
        ]

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[
                f"CAN transceiver {ic_name}: {vdd_net} ({ic_db['vdd']}V), "
                f"{'terminated' if termination else 'unterminated'}",
            ],
            primary_category="digital",
        )
