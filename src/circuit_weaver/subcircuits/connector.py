"""Connector subcircuit template.

Generates common connector subcircuits with decoupling, protection,
and pin mapping.

Supports barrel jack (DC power, default), pin header (2.54mm),
and JST-PH (battery/sensor) topologies.
"""

from __future__ import annotations

from typing import Any

from ..component_db import BypassCap, ComponentDef, PinDef
from .base import (
    FP_0805C,
    BoundaryPort,
    SubcircuitResult,
    SubcircuitTemplate,
)

CONNECTOR_DATABASE = {
    "BARREL_JACK_2.1MM": {
        "description": "DC Barrel Jack 2.1mm Center-Positive",
        "footprint": "Connector_BarrelJack:BarrelJack_Horizontal",
        "connector_type": "power",
        "pins": [
            PinDef("1", "TIP", "passive", "R"),
            PinDef("2", "RING", "passive", "L"),
            PinDef("3", "SWITCH", "passive", "L"),
        ],
        "pin_positive": "1",
        "pin_negative": "2",
        "pin_switch": "3",
    },
    "PIN_HEADER_2P": {
        "description": "2-Pin 2.54mm Pin Header",
        "footprint": "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
        "connector_type": "generic",
        "pins": [
            PinDef("1", "P1", "passive", "R"),
            PinDef("2", "P2", "passive", "R"),
        ],
    },
    "PIN_HEADER_4P": {
        "description": "4-Pin 2.54mm Pin Header",
        "footprint": "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
        "connector_type": "generic",
        "pins": [
            PinDef("1", "P1", "passive", "R"),
            PinDef("2", "P2", "passive", "R"),
            PinDef("3", "P3", "passive", "R"),
            PinDef("4", "P4", "passive", "R"),
        ],
    },
    "JST_PH_2P": {
        "description": "JST PH 2-Pin Connector (Battery/Sensor)",
        "footprint": "Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical",
        "connector_type": "power",
        "pins": [
            PinDef("1", "P1", "passive", "R"),
            PinDef("2", "P2", "passive", "R"),
        ],
        "pin_positive": "1",
        "pin_negative": "2",
    },
    "JST_PH_4P": {
        "description": "JST PH 4-Pin Connector (I2C Sensor)",
        "footprint": "Connector_JST:JST_PH_B4B-PH-K_1x04_P2.00mm_Vertical",
        "connector_type": "signal",
        "pins": [
            PinDef("1", "VCC", "passive", "R"),
            PinDef("2", "GND", "passive", "R"),
            PinDef("3", "SDA", "passive", "R"),
            PinDef("4", "SCL", "passive", "R"),
        ],
    },
}


class ConnectorTemplate(SubcircuitTemplate):
    """Common connectors: barrel jack, pin header, JST."""

    template_type = "connector"
    description = "Barrel jack, pin header, or JST connector with optional decoupling"
    param_schema = [
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "BARREL_JACK_2.1MM",
            "description": "Connector MPN/type",
        },
        {
            "name": "ref",
            "type": "string",
            "required": False,
            "default": "J",
            "description": "Reference designator for the connector",
        },
        {
            "name": "positive_net",
            "type": "string",
            "required": False,
            "default": "VIN",
            "description": "Positive/power net name (power connectors)",
        },
        {
            "name": "negative_net",
            "type": "string",
            "required": False,
            "default": "GND",
            "description": "Negative/ground net name (power connectors)",
        },
        {
            "name": "signal_nets",
            "type": "string",
            "required": False,
            "description": "Comma-separated net names for signal pins (generic connectors)",
        },
        {
            "name": "decoupling",
            "type": "boolean",
            "required": False,
            "default": True,
            "description": "Add input decoupling capacitor (power connectors)",
        },
    ]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        ic_name = params.get("ic", "BARREL_JACK_2.1MM")
        if ic_name not in CONNECTOR_DATABASE:
            errors.append(
                f"Unknown connector '{ic_name}'. "
                f"Available: {', '.join(CONNECTOR_DATABASE)}"
            )
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        ic_name = params.get("ic", "BARREL_JACK_2.1MM")
        ic_db = CONNECTOR_DATABASE.get(ic_name, CONNECTOR_DATABASE["BARREL_JACK_2.1MM"])
        ref = params.get("ref", "J")
        positive_net = params.get("positive_net", "VIN")
        negative_net = params.get("negative_net", "GND")
        signal_nets_str = params.get("signal_nets", "")
        decoupling = params.get("decoupling", True)

        connector_type = ic_db.get("connector_type", "generic")

        pin_nets: dict[str, str] = {}
        bypass_caps: list[BypassCap] = []
        annotations: list[str] = [f"Connector {ic_name}"]
        ports: list[BoundaryPort] = []

        if connector_type == "power":
            # Power connectors: barrel jack, JST battery
            pin_nets[ic_db["pin_positive"]] = positive_net
            pin_nets[ic_db["pin_negative"]] = negative_net

            # Barrel jack switch pin: tie to negative (unused)
            if "pin_switch" in ic_db:
                pin_nets[ic_db["pin_switch"]] = negative_net

            if decoupling:
                bypass_caps.append(
                    BypassCap(
                        "C_IN",
                        positive_net,
                        negative_net,
                        "10uF",
                        FP_0805C,
                        role="input_bulk",
                        presentation="topology_local",
                    ),
                )
                annotations.append("Input decoupling: 10uF")

            ports.append(BoundaryPort(positive_net, "output"))
            ports.append(BoundaryPort(negative_net, "passive"))
            annotations.append(f"{positive_net} / {negative_net}")

        elif connector_type == "signal":
            # Pre-defined signal connectors (e.g., JST 4P for I2C)
            signal_names = [p.name for p in ic_db["pins"]]
            for pin in ic_db["pins"]:
                if pin.name in ("VCC", "VDD"):
                    pin_nets[pin.number] = positive_net
                    ports.append(BoundaryPort(positive_net, "output"))
                elif pin.name in ("GND", "VSS"):
                    pin_nets[pin.number] = negative_net
                    ports.append(BoundaryPort(negative_net, "passive"))
                else:
                    net = f"{pin.name}_{ref}"
                    pin_nets[pin.number] = net
                    ports.append(BoundaryPort(net, "bidirectional"))
            annotations.append(f"Signals: {', '.join(signal_names)}")

        else:
            # Generic connectors: user provides signal_nets
            signal_list = (
                [s.strip() for s in signal_nets_str.split(",") if s.strip()]
                if signal_nets_str
                else []
            )
            for i, pin in enumerate(ic_db["pins"]):
                if i < len(signal_list):
                    net = signal_list[i]
                else:
                    net = f"P{i + 1}_{ref}"
                pin_nets[pin.number] = net
                ports.append(BoundaryPort(net, "bidirectional"))

        ic_comp = ComponentDef(
            mpn=ic_name,
            ref_prefix="J",
            value=ic_name,
            footprint=ic_db["footprint"],
            description=ic_db["description"],
            category="connector",
            pins=list(ic_db["pins"]),
            pin_nets=pin_nets,
            bypass_caps=bypass_caps,
            annotations=annotations,
        )
        ic_comp.source_ref = ref

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[f"Connector {ic_name}: {ref}"],
            primary_category="connector",
        )
