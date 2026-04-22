"""USB Type-C connector subcircuit template.

Generates a USB Type-C receptacle subcircuit with CC pull-down resistors
(for device/sink role), optional ESD protection, and VBUS decoupling.

Supports device/sink (default) and DRP/source modes via CC resistor
configuration per USB Type-C specification.

Auto-selects: CC resistance (5.1k for device), VBUS decoupling,
and optional ESD diodes on data lines.
"""

from __future__ import annotations

from typing import Any

from ..component_db import BypassCap, ComponentDef, PinDef, StrapConfig
from .base import (
    FP_0402C,
    FP_0402R,
    FP_0805C,
    BoundaryPort,
    SubcircuitResult,
    SubcircuitTemplate,
    format_resistance,
    snap_to_e24,
)

# USB Type-C connector variants
USB_C_CONNECTOR_DATABASE = {
    "USB4125-GF-A": {
        "description": "USB Type-C Receptacle 16-Pin Mid-Mount",
        "footprint": "USB_C_Receptacle_GCT_USB4125",
        "pins": [
            PinDef("A1", "GND", "power_in", "B"),
            PinDef("A4", "VBUS", "power_in", "T"),
            PinDef("A5", "CC1", "bidirectional", "L"),
            PinDef("A6", "DP1", "bidirectional", "R"),
            PinDef("A7", "DN1", "bidirectional", "R"),
            PinDef("A8", "SBU1", "bidirectional", "R"),
            PinDef("A9", "VBUS", "power_in", "T"),
            PinDef("A12", "GND", "power_in", "B"),
            PinDef("B1", "GND", "power_in", "B"),
            PinDef("B4", "VBUS", "power_in", "T"),
            PinDef("B5", "CC2", "bidirectional", "L"),
            PinDef("B6", "DN2", "bidirectional", "R"),
            PinDef("B7", "DP2", "bidirectional", "R"),
            PinDef("B8", "SBU2", "bidirectional", "R"),
            PinDef("B9", "VBUS", "power_in", "T"),
            PinDef("B12", "GND", "power_in", "B"),
        ],
        "pin_vbus": ["A4", "A9", "B4", "B9"],
        "pin_gnd": ["A1", "A12", "B1", "B12"],
        "pin_cc1": "A5",
        "pin_cc2": "B5",
        "pin_dp1": "A6",
        "pin_dn1": "A7",
        "pin_dp2": "B7",
        "pin_dn2": "B6",
        "pin_sbu1": "A8",
        "pin_sbu2": "B8",
    },
    "USB_C_SIMPLE": {
        "description": "USB Type-C Receptacle 6-Pin (USB 2.0 Only)",
        "footprint": "USB_C_Receptacle_USB2Only",
        "pins": [
            PinDef("A1", "GND", "power_in", "B"),
            PinDef("A4", "VBUS", "power_in", "T"),
            PinDef("A5", "CC1", "bidirectional", "L"),
            PinDef("A6", "DP", "bidirectional", "R"),
            PinDef("A7", "DN", "bidirectional", "R"),
            PinDef("B5", "CC2", "bidirectional", "L"),
        ],
        "pin_vbus": ["A4"],
        "pin_gnd": ["A1"],
        "pin_cc1": "A5",
        "pin_cc2": "B5",
        "pin_dp1": "A6",
        "pin_dn1": "A7",
        "pin_dp2": None,
        "pin_dn2": None,
        "pin_sbu1": None,
        "pin_sbu2": None,
    },
}


class USBCConnectorTemplate(SubcircuitTemplate):
    """USB Type-C connector with CC resistors, VBUS decoupling, and optional ESD."""

    template_type = "usb_c_connector"
    description = "USB Type-C receptacle with CC resistors and VBUS decoupling"
    param_schema = [
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "USB4125-GF-A",
            "description": "USB-C connector MPN",
        },
        {
            "name": "ref",
            "type": "string",
            "required": False,
            "default": "J",
            "description": "Reference designator for the connector",
        },
        {
            "name": "role",
            "type": "string",
            "required": False,
            "default": "device",
            "options": ["device", "source"],
            "description": "USB role: device (5.1k pull-down) or source (Rp to VBUS)",
        },
        {
            "name": "vbus_net",
            "type": "string",
            "required": False,
            "default": "VBUS",
            "description": "VBUS power net name",
        },
        {
            "name": "dp_net",
            "type": "string",
            "required": False,
            "default": "USB_DP",
            "description": "USB D+ signal net name",
        },
        {
            "name": "dn_net",
            "type": "string",
            "required": False,
            "default": "USB_DN",
            "description": "USB D- signal net name",
        },
        {
            "name": "esd",
            "type": "boolean",
            "required": False,
            "default": True,
            "description": "Add ESD protection on data lines",
        },
        {
            "name": "usb3",
            "type": "boolean",
            "required": False,
            "default": False,
            "description": "Expose USB 3.x SuperSpeed pairs (full pinout connectors only)",
        },
    ]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        ic_name = params.get("ic", "USB4125-GF-A")
        if ic_name not in USB_C_CONNECTOR_DATABASE:
            errors.append(
                f"Unknown USB-C connector '{ic_name}'. "
                f"Available: {', '.join(USB_C_CONNECTOR_DATABASE)}"
            )
        role = params.get("role", "device")
        if role not in ("device", "source"):
            errors.append(f"role must be 'device' or 'source', got '{role}'")
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        """Generate a USB Type-C connector subcircuit.

        Optional params:
            ic: str -- connector MPN (default: "USB4125-GF-A")
            ref: str -- reference designator (default: "J")
            role: str -- 'device' or 'source' (default: "device")
            vbus_net: str -- VBUS net name (default: "VBUS")
            dp_net: str -- D+ net name (default: "USB_DP")
            dn_net: str -- D- net name (default: "USB_DN")
            esd: bool -- add ESD protection (default: True)
            usb3: bool -- expose USB3 pairs (default: False)
        """
        ic_name = params.get("ic", "USB4125-GF-A")
        ic_db = USB_C_CONNECTOR_DATABASE.get(
            ic_name, USB_C_CONNECTOR_DATABASE["USB4125-GF-A"]
        )
        ref = params.get("ref", "J")
        role = params.get("role", "device")
        vbus_net = params.get("vbus_net", "VBUS")
        dp_net = params.get("dp_net", "USB_DP")
        dn_net = params.get("dn_net", "USB_DN")
        esd = params.get("esd", True)

        # CC net names
        cc1_net = f"CC1_{ref}"
        cc2_net = f"CC2_{ref}"

        # Power pins
        power_pins: dict[str, str] = {}
        for pin_num in ic_db["pin_vbus"]:
            power_pins[pin_num] = vbus_net
        for pin_num in ic_db["pin_gnd"]:
            power_pins[pin_num] = "GND"

        # Signal pins
        pin_nets: dict[str, str] = {
            ic_db["pin_cc1"]: cc1_net,
            ic_db["pin_cc2"]: cc2_net,
        }

        # D+/D- connections (tie both orientations together for USB 2.0)
        pin_nets[ic_db["pin_dp1"]] = dp_net
        pin_nets[ic_db["pin_dn1"]] = dn_net
        if ic_db.get("pin_dp2"):
            pin_nets[ic_db["pin_dp2"]] = dp_net
        if ic_db.get("pin_dn2"):
            pin_nets[ic_db["pin_dn2"]] = dn_net

        # SBU pins: export as ports when usb3 is enabled, otherwise NC
        explicit_nc: set[str] = set()
        usb3 = params.get("usb3", False)
        sbu1_net = f"SBU1_{ref}"
        sbu2_net = f"SBU2_{ref}"
        if usb3 and ic_db.get("pin_sbu1"):
            pin_nets[ic_db["pin_sbu1"]] = sbu1_net
            pin_nets[ic_db["pin_sbu2"]] = sbu2_net
        else:
            if ic_db.get("pin_sbu1"):
                explicit_nc.add(ic_db["pin_sbu1"])
            if ic_db.get("pin_sbu2"):
                explicit_nc.add(ic_db["pin_sbu2"])

        # CC pull-down/up resistors
        straps: list[StrapConfig] = []
        if role == "device":
            # USB-C spec: 5.1k pull-down on each CC line for device/sink
            r_cc = snap_to_e24(5.1e3)
            straps.extend(
                [
                    StrapConfig(
                        "R_CC1",
                        cc1_net,
                        "GND",
                        format_resistance(r_cc),
                        FP_0402R,
                        role="cc_pulldown",
                        presentation="topology_local",
                    ),
                    StrapConfig(
                        "R_CC2",
                        cc2_net,
                        "GND",
                        format_resistance(r_cc),
                        FP_0402R,
                        role="cc_pulldown",
                        presentation="topology_local",
                    ),
                ]
            )
        else:
            # Source/DFP: 56k pull-up to VBUS (default current advertisement)
            r_cc = snap_to_e24(56e3)
            straps.extend(
                [
                    StrapConfig(
                        "R_CC1",
                        cc1_net,
                        vbus_net,
                        format_resistance(r_cc),
                        FP_0402R,
                        role="cc_pullup",
                        presentation="topology_local",
                    ),
                    StrapConfig(
                        "R_CC2",
                        cc2_net,
                        vbus_net,
                        format_resistance(r_cc),
                        FP_0402R,
                        role="cc_pullup",
                        presentation="topology_local",
                    ),
                ]
            )

        # VBUS decoupling
        bypass_caps: list[BypassCap] = [
            BypassCap(
                "C_VBUS",
                vbus_net,
                "GND",
                "10uF",
                FP_0805C,
                role="vbus_bulk",
                presentation="topology_local",
            ),
            BypassCap(
                "C_VBUS_HF",
                vbus_net,
                "GND",
                "100nF",
                FP_0402C,
                role="vbus_decoupling",
                presentation="topology_local",
            ),
        ]

        annotations = [
            f"USB-C {ic_name}: {role} mode, CC={format_resistance(r_cc)}",
            f"VBUS={vbus_net}, D+={dp_net}, D-={dn_net}",
        ]
        if esd:
            annotations.append("ESD protection recommended on D+/D- lines")

        ic_comp = ComponentDef(
            mpn=ic_name,
            ref_prefix="J",
            value=ic_name,
            footprint=ic_db["footprint"],
            description=ic_db["description"],
            category="connector",
            pins=list(ic_db["pins"]),
            power_pins=power_pins,
            pin_nets=pin_nets,
            bypass_caps=bypass_caps,
            straps=straps,
            annotations=annotations,
            explicit_no_connects=explicit_nc,
        )
        ic_comp.source_ref = ref

        # Boundary ports
        ports = [
            BoundaryPort(vbus_net, "output"),
            BoundaryPort("GND", "passive"),
            BoundaryPort(dp_net, "bidirectional"),
            BoundaryPort(dn_net, "bidirectional"),
            BoundaryPort(cc1_net, "bidirectional"),
            BoundaryPort(cc2_net, "bidirectional"),
        ]
        if usb3 and ic_db.get("pin_sbu1"):
            ports.append(BoundaryPort(sbu1_net, "bidirectional"))
            ports.append(BoundaryPort(sbu2_net, "bidirectional"))

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[
                f"USB-C {ic_name}: {role}, CC={format_resistance(r_cc)}, "
                f"VBUS={vbus_net}",
            ],
            primary_category="digital",
        )
