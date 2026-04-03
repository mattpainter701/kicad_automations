"""MOSFET switch subcircuit template.

Generates a complete low-side or high-side MOSFET switch subcircuit from
design parameters: load current, drive voltage, polarity.

Auto-calculates: gate resistor, pull-down/pull-up default-off resistor,
optional snubber RC for inductive loads. All values snapped and formatted.

Supports BSS138 (default), AO3400A, AO3401A topologies.
"""

from __future__ import annotations

from typing import Any

from ..component_db import BypassCap, ComponentDef, PinDef, StrapConfig
from .base import (
    FP_0402R,
    BoundaryPort,
    SubcircuitResult,
    SubcircuitTemplate,
    cap_footprint,
    format_capacitance,
    format_resistance,
    snap_cap,
    snap_to_e96,
)

# Known MOSFET ICs and their parameters
MOSFET_IC_DATABASE = {
    "BSS138": {
        "description": "N-Channel MOSFET 50V 200mA SOT-23",
        "footprint": "Package_TO_SOT_SMD:SOT-23",
        "vds": 50,
        "id_max": 0.2,
        "rdson": 3.5,
        "vgs_th_min": 0.8,
        "vgs_th_max": 1.5,
        "polarity": "n",
        "topology": "low_side",
        "pins": [
            PinDef("1", "G", "input", "L"),
            PinDef("2", "S", "passive", "B"),
            PinDef("3", "D", "passive", "T"),
        ],
        "pin_g": "1",
        "pin_s": "2",
        "pin_d": "3",
    },
    "AO3400A": {
        "description": "N-Channel MOSFET 30V 5.7A SOT-23",
        "footprint": "Package_TO_SOT_SMD:SOT-23",
        "vds": 30,
        "id_max": 5.7,
        "rdson": 0.026,
        "vgs_th_min": 0.65,
        "vgs_th_max": 1.45,
        "polarity": "n",
        "topology": "low_side",
        "pins": [
            PinDef("1", "G", "input", "L"),
            PinDef("2", "S", "passive", "B"),
            PinDef("3", "D", "passive", "T"),
        ],
        "pin_g": "1",
        "pin_s": "2",
        "pin_d": "3",
    },
    "AO3401A": {
        "description": "P-Channel MOSFET -30V -4A SOT-23",
        "footprint": "Package_TO_SOT_SMD:SOT-23",
        "vds": -30,
        "id_max": -4.0,
        "rdson": 0.044,
        "vgs_th_min": -0.5,
        "vgs_th_max": -1.3,
        "polarity": "p",
        "topology": "high_side",
        "pins": [
            PinDef("1", "G", "input", "L"),
            PinDef("2", "S", "passive", "T"),
            PinDef("3", "D", "passive", "B"),
        ],
        "pin_g": "1",
        "pin_s": "2",
        "pin_d": "3",
    },
}


class MOSFETSwitchTemplate(SubcircuitTemplate):
    """MOSFET switch with gate resistor and default-off bias."""

    template_type = "mosfet_switch"
    description = "Low-side or high-side MOSFET switch with gate protection"
    param_schema = [
        {
            "name": "iload",
            "type": "number",
            "required": True,
            "description": "Load current in amps",
        },
        {
            "name": "vdrive",
            "type": "number",
            "required": False,
            "default": 3.3,
            "description": "GPIO drive voltage in volts",
        },
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "BSS138",
            "description": "MOSFET MPN",
        },
        {
            "name": "ref",
            "type": "string",
            "required": False,
            "default": "Q",
            "description": "Reference designator for the MOSFET",
        },
        {
            "name": "vdd_net",
            "type": "string",
            "required": False,
            "default": "VDD_3P3",
            "description": "Supply rail net name (used for P-ch pull-up)",
        },
        {
            "name": "load_net",
            "type": "string",
            "required": False,
            "description": "Load connection net name; defaults to LOAD_{ref}",
        },
        {
            "name": "gate_net",
            "type": "string",
            "required": False,
            "description": "Gate drive net name; defaults to GATE_{ref}",
        },
        {
            "name": "inductive",
            "type": "boolean",
            "required": False,
            "default": False,
            "description": "True for inductive loads (relay, solenoid, motor) — adds snubber RC",
        },
    ]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        iload = params.get("iload")
        if iload is None:
            errors.append("Missing required param 'iload' (load current in A)")
        elif iload <= 0:
            errors.append(f"iload ({iload}A) must be positive")

        ic_name = params.get("ic", "BSS138")
        if ic_name not in MOSFET_IC_DATABASE:
            errors.append(f"Unknown MOSFET '{ic_name}'. Available: {', '.join(MOSFET_IC_DATABASE)}")
            return errors

        ic_db = MOSFET_IC_DATABASE[ic_name]
        id_max = abs(ic_db["id_max"])
        if iload is not None and iload > id_max:
            errors.append(f"iload ({iload}A) exceeds {ic_name} max drain current ({id_max}A)")

        vdrive = params.get("vdrive", 3.3)
        if vdrive <= 0:
            errors.append(f"vdrive ({vdrive}V) must be positive")
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        """Generate a MOSFET switch subcircuit.

        Required params:
            iload: float -- load current (A)

        Optional params:
            vdrive: float -- GPIO drive voltage (V, default: 3.3)
            ic: str -- MOSFET MPN (default: "BSS138")
            ref: str -- reference designator (default: "Q")
            vdd_net: str -- supply rail net name (default: "VDD_3P3")
            load_net: str -- load net name (default: LOAD_{ref})
            gate_net: str -- gate drive net name (default: GATE_{ref})
            inductive: bool -- adds snubber RC for inductive loads (default: False)
        """
        iload = params["iload"]
        vdrive = params.get("vdrive", 3.3)
        ic_name = params.get("ic", "BSS138")
        ref = params.get("ref", "Q")
        vdd_net = params.get("vdd_net", "VDD_3P3")
        load_net = params.get("load_net", f"LOAD_{ref}")
        gate_net = params.get("gate_net", f"GATE_{ref}")
        inductive = params.get("inductive", False)

        # Look up MOSFET parameters
        ic_db = MOSFET_IC_DATABASE.get(ic_name, MOSFET_IC_DATABASE["BSS138"])
        polarity = ic_db["polarity"]
        topology = ic_db["topology"]

        # ---- Local net names (unique per instance) ----
        gate_internal_net = f"GINT_{ref}"

        # ---- Gate resistor: 100R standard EMI limiting ----
        r_gate = snap_to_e96(100.0)

        # ---- Default-off bias resistor: 100k ----
        r_bias = snap_to_e96(100e3)

        # ---- Power pins ----
        power_pins: dict[str, str] = {}
        if polarity == "n":
            # N-channel low-side: source to GND
            power_pins[ic_db["pin_s"]] = "GND"
        else:
            # P-channel high-side: source to VDD
            power_pins[ic_db["pin_s"]] = vdd_net

        # ---- Signal pin nets ----
        pin_nets = {
            ic_db["pin_g"]: gate_internal_net,
            ic_db["pin_d"]: load_net,
        }

        # ---- Straps ----
        straps = [
            # Gate resistor: gate_net -> gate_internal_net
            StrapConfig(
                "RGATE",
                gate_net,
                gate_internal_net,
                format_resistance(r_gate),
                FP_0402R,
                role="gate_resistor",
                presentation="topology_local",
            ),
        ]

        if polarity == "n":
            # N-ch pull-down: gate to GND (default off)
            straps.append(
                StrapConfig(
                    "RBIAS",
                    gate_internal_net,
                    "GND",
                    format_resistance(r_bias),
                    FP_0402R,
                    role="gate_pulldown",
                    presentation="topology_local",
                ),
            )
        else:
            # P-ch pull-up: gate to VDD (default off)
            straps.append(
                StrapConfig(
                    "RBIAS",
                    gate_internal_net,
                    vdd_net,
                    format_resistance(r_bias),
                    FP_0402R,
                    role="gate_pullup",
                    presentation="topology_local",
                ),
            )

        # ---- Bypass caps (snubber only, no IC decoupling needed) ----
        bypass_caps: list[BypassCap] = []

        if inductive:
            # Snubber RC across drain-source for inductive load
            r_snub = snap_to_e96(10.0)
            c_snub = snap_cap(100e-9)
            snub_mid_net = f"SNUB_{ref}"

            # Snubber resistor: load_net -> snub_mid_net
            straps.append(
                StrapConfig(
                    "RSNUB",
                    load_net,
                    snub_mid_net,
                    format_resistance(r_snub),
                    FP_0402R,
                    role="snubber_resistor",
                    presentation="topology_local",
                ),
            )

            if polarity == "n":
                # N-ch: snubber cap from snub_mid_net to GND (source)
                bypass_caps.append(
                    BypassCap(
                        "CSNUB",
                        snub_mid_net,
                        "GND",
                        format_capacitance(c_snub),
                        cap_footprint(c_snub),
                        role="snubber_cap",
                        presentation="topology_local",
                    ),
                )
            else:
                # P-ch: snubber cap from snub_mid_net to VDD (source)
                bypass_caps.append(
                    BypassCap(
                        "CSNUB",
                        snub_mid_net,
                        vdd_net,
                        format_capacitance(c_snub),
                        cap_footprint(c_snub),
                        role="snubber_cap",
                        presentation="topology_local",
                    ),
                )

        # ---- Annotations ----
        rdson_str = f"{ic_db['rdson'] * 1000:.0f}m\u03a9" if ic_db["rdson"] < 1.0 else f"{ic_db['rdson']:.1f}\u03a9"
        pdiss = iload * iload * ic_db["rdson"]
        annotations = [
            f"{'P' if polarity == 'p' else 'N'}-ch {topology.replace('_', '-')} switch: {ic_name}, Rds(on)={rdson_str}",
            f"Iload={iload}A, Vdrive={vdrive}V, Pdiss={pdiss:.3f}W",
            f"Gate: {format_resistance(r_gate)} series, "
            f"{format_resistance(r_bias)} {'pull-down' if polarity == 'n' else 'pull-up'}",
        ]
        if inductive:
            annotations.append(
                f"Inductive snubber: {format_resistance(r_snub)} + {format_capacitance(c_snub)} across D-S"
            )

        # ---- Build MOSFET component ----
        mosfet_comp = ComponentDef(
            mpn=ic_name,
            ref_prefix="Q",
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
        mosfet_comp.source_ref = ref

        # ---- Boundary ports ----
        ports = [
            BoundaryPort(gate_net, "input"),
            BoundaryPort(load_net, "output"),
        ]
        if polarity == "n":
            ports.append(BoundaryPort("GND", "passive"))
        if polarity == "p":
            ports.append(BoundaryPort(vdd_net, "input"))

        return SubcircuitResult(
            components=[mosfet_comp],
            boundary_ports=ports,
            annotations=[
                f"MOSFET switch {ic_name}: {'P' if polarity == 'p' else 'N'}-ch "
                f"{topology.replace('_', '-')}, {iload}A, Rds(on)={rdson_str}"
                f"{', snubber' if inductive else ''}",
            ],
            primary_category="power",
        )
