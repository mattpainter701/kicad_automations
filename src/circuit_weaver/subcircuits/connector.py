"""Connector subcircuit template.

Generates common connector subcircuits with decoupling, protection,
and pin mapping.

Supports barrel jack (DC power, default), pin header (2.54mm),
and JST-PH (battery/sensor) topologies.
"""

from __future__ import annotations

from typing import Any

from ..component_db import BypassCap, ComponentDef
from .base import (
    FP_0805C,
    BoundaryPort,
    SubcircuitResult,
    SubcircuitTemplate,
)

CONNECTOR_DATABASE: dict[str, dict] = {}  # Migrated to ic_data/*.json (Task 178)


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

    @classmethod
    def _ic_db(cls) -> dict[str, dict[str, Any]]:
        """Hardcoded DB merged with ic_data 'connector' entries so parts
        registered via ``circuit-weaver register-ic`` are accepted.
        """
        from ..ic_data import merge_into_legacy_db

        return merge_into_legacy_db(CONNECTOR_DATABASE, "connector")

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        ic_name = params.get("ic", "BARREL_JACK_2.1MM")
        db = self._ic_db()
        if ic_name not in db:
            errors.append(f"Unknown connector '{ic_name}'. Available: {', '.join(db)}")
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        ic_name = params.get("ic", "BARREL_JACK_2.1MM")
        db = self._ic_db()
        desc = str(params.get("description", "")).lower()
        if ic_name == "BARREL_JACK_2.1MM" and "2x aa" in desc and ("placeholder" in desc or "replace" in desc):
            ic_name = "BATTERY_HOLDER_2XAA"
        ic_db = db.get(ic_name, db["BARREL_JACK_2.1MM"])
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
            signal_list = [s.strip() for s in signal_nets_str.split(",") if s.strip()] if signal_nets_str else []
            has_power_pair = "positive_net" in params or "negative_net" in params
            signal_idx = 0
            for i, pin in enumerate(ic_db["pins"]):
                if has_power_pair and i == 0:
                    net = positive_net
                elif has_power_pair and i == 1:
                    net = negative_net
                elif signal_idx < len(signal_list):
                    net = signal_list[signal_idx]
                    signal_idx += 1
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
