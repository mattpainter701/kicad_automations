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

TVS_DATABASE: dict[str, dict] = {}  # Migrated to ic_data/*.json (Task 178)


class ProtectionTemplate(SubcircuitTemplate):
    """TVS / ESD / reverse-polarity protection circuit."""

    template_type = "protection"
    description = "Protection circuit (TVS, ESD, reverse polarity)"
    param_schema = [
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "SMBJ5.0A",
            "description": "Protection device MPN",
        },
        {
            "name": "ref",
            "type": "string",
            "required": False,
            "default": "D",
            "description": "Reference designator for the protection device",
        },
        {
            "name": "protect_net",
            "type": "string",
            "required": True,
            "description": "Net to protect (e.g., VBUS_5V, USB_DP)",
        },
        {
            "name": "gnd_net",
            "type": "string",
            "required": False,
            "default": "GND",
            "description": "Ground reference net name",
        },
        {
            "name": "protection_type",
            "type": "string",
            "required": False,
            "default": "tvs",
            "options": ["tvs", "esd"],
            "description": "Protection type: TVS for power lines, ESD for signal lines",
        },
    ]

    @staticmethod
    def _ic_db() -> dict[str, dict[str, Any]]:
        """Hardcoded TVS_DATABASE merged with ic_data 'protection' entries
        so user :func:`register_ic` calls also reach the legacy template.
        Sprint 37 Task 158."""
        from ..ic_data import merge_into_legacy_db

        return merge_into_legacy_db(TVS_DATABASE, "protection")

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        if not params.get("protect_net"):
            errors.append("Missing required param 'protect_net'")
        ic = params.get("ic", "SMBJ5.0A")
        db = self._ic_db()
        if ic not in db:
            errors.append(f"Unknown protection IC '{ic}'. Available: {', '.join(db)}")
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        ic_name = params.get("ic", "SMBJ5.0A")
        db = self._ic_db()
        ic_db = db.get(ic_name, db["SMBJ5.0A"])
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
