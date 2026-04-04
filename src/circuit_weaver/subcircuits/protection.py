"""Protection subcircuit templates.

Generates TVS, ESD, and reverse-polarity protection circuits.
"""

from __future__ import annotations

from typing import Any

from ..component_db import ComponentDef, PinDef
from .base import (
    BoundaryPort,
    SubcircuitResult,
    SubcircuitTemplate,
)

TVS_DATABASE = {
    "SMBJ5.0A": {
        "description": "TVS Diode 5V Unidirectional SMB",
        "footprint": "Diode_SMD:D_SMB",
        "vrwm": 5.0,
        "vbr_min": 6.4,
        "vc_max": 9.2,
        "bidirectional": False,
        "pins": [
            PinDef("1", "A", "passive", "L"),
            PinDef("2", "K", "passive", "R"),
        ],
    },
    "SMBJ12A": {
        "description": "TVS Diode 12V Unidirectional SMB",
        "footprint": "Diode_SMD:D_SMB",
        "vrwm": 12.0,
        "vbr_min": 13.3,
        "vc_max": 19.9,
        "bidirectional": False,
        "pins": [
            PinDef("1", "A", "passive", "L"),
            PinDef("2", "K", "passive", "R"),
        ],
    },
    "SMBJ5.0CA": {
        "description": "TVS Diode 5V Bidirectional SMB",
        "footprint": "Diode_SMD:D_SMB",
        "vrwm": 5.0,
        "vbr_min": 6.4,
        "vc_max": 9.2,
        "bidirectional": True,
        "pins": [
            PinDef("1", "A", "passive", "L"),
            PinDef("2", "K", "passive", "R"),
        ],
    },
    "PESD5V0S1BA": {
        "description": "ESD Protection Diode 5V SOD-323",
        "footprint": "Diode_SMD:D_SOD-323",
        "vrwm": 5.0,
        "vbr_min": 6.0,
        "vc_max": 11.0,
        "bidirectional": True,
        "pins": [
            PinDef("1", "A", "passive", "L"),
            PinDef("2", "K", "passive", "R"),
        ],
    },
}


class ProtectionTemplate(SubcircuitTemplate):
    """TVS / ESD / reverse-polarity protection circuit."""

    template_type = "protection"
    description = "Protection circuit (TVS, ESD, reverse polarity)"
    param_schema = [
        {"name": "ic", "type": "string", "required": False, "default": "SMBJ5.0A"},
        {"name": "ref", "type": "string", "required": False, "default": "D"},
        {
            "name": "protect_net",
            "type": "string",
            "required": True,
            "description": "Net to protect (e.g., VBUS_5V, USB_DP)",
        },
        {"name": "gnd_net", "type": "string", "required": False, "default": "GND"},
        {"name": "protection_type", "type": "string", "required": False, "default": "tvs", "options": ["tvs", "esd"]},
    ]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        if not params.get("protect_net"):
            errors.append("Missing required param 'protect_net'")
        ic = params.get("ic", "SMBJ5.0A")
        if ic not in TVS_DATABASE:
            errors.append(f"Unknown protection IC '{ic}'. Available: {', '.join(TVS_DATABASE)}")
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        ic_name = params.get("ic", "SMBJ5.0A")
        ic_db = TVS_DATABASE.get(ic_name, TVS_DATABASE["SMBJ5.0A"])
        ref = params.get("ref", "D")
        protect_net = params["protect_net"]
        gnd_net = params.get("gnd_net", "GND")

        pin_nets = {"1": protect_net, "2": gnd_net}
        if ic_db["bidirectional"]:
            pin_nets = {"1": protect_net, "2": gnd_net}

        direction = "bidirectional" if ic_db["bidirectional"] else "unidirectional"
        annotations = [
            f"Protection: {ic_name} ({direction}) on {protect_net}",
            f"Vrwm={ic_db['vrwm']}V, Vbr={ic_db['vbr_min']}V, Vc={ic_db['vc_max']}V",
        ]

        comp = ComponentDef(
            mpn=ic_name,
            ref_prefix="D",
            value=ic_name,
            footprint=ic_db["footprint"],
            description=ic_db["description"],
            category="protection",
            pins=list(ic_db["pins"]),
            pin_nets=pin_nets,
            annotations=annotations,
        )
        comp.source_ref = ref

        ports = [
            BoundaryPort(protect_net, "bidirectional"),
            BoundaryPort(gnd_net, "passive"),
        ]

        return SubcircuitResult(
            components=[comp],
            boundary_ports=ports,
            annotations=[f"TVS {ic_name} on {protect_net}"],
            primary_category="protection",
        )
