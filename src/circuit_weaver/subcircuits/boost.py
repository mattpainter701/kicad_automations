"""Boost step-up converter subcircuit template.

Generates a complete boost regulator subcircuit from design parameters:
VIN, VOUT, IOUT, switching frequency.

Auto-calculates: feedback divider (R_FBT/R_FBB), inductor, input/output
caps. All values snapped to standard E96/E24 series.

Supports TPS61230A (default) and MT3608 topologies.
"""

from __future__ import annotations

from typing import Any

from ..component_db import BypassCap, ComponentDef, StrapConfig
from .base import (
    FP_0402R,
    BoundaryPort,
    LegacyDBProxy,
    SubcircuitResult,
    SubcircuitTemplate,
    boost_inductor,
    cap_footprint,
    feedback_divider_top,
    feedback_divider_vout,
    format_capacitance,
    format_inductance,
    format_resistance,
    ind_footprint,
    snap_ind,
    snap_to_e96,
)

# Known boost converter ICs and their parameters
BOOST_IC_DATABASE = LegacyDBProxy("boost")  # backed by ic_data/*.json (Task 178)


class BoostConverterTemplate(SubcircuitTemplate):
    """Boost step-up converter with auto-calculated passives."""

    template_type = "boost"
    description = "Boost DC-DC step-up converter with feedback divider"
    param_schema = [
        {
            "name": "vin",
            "type": "number",
            "required": True,
            "description": "Input voltage in volts",
        },
        {
            "name": "vout",
            "type": "number",
            "required": True,
            "description": "Output voltage in volts",
        },
        {
            "name": "iout",
            "type": "number",
            "required": True,
            "description": "Maximum output current in amps",
        },
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "TPS61230A",
            "description": "Boost regulator IC MPN",
        },
        {
            "name": "ref",
            "type": "string",
            "required": False,
            "default": "U",
            "description": "Reference designator for the IC",
        },
        {
            "name": "rail_name",
            "type": "string",
            "required": False,
            "description": "Output rail net name",
        },
        {
            "name": "vin_net",
            "type": "string",
            "required": False,
            "default": "VIN",
            "description": "Input rail net name",
        },
        {
            "name": "en_net",
            "type": "string",
            "required": False,
            "description": "Enable net name; defaults to vin_net",
        },
        {
            "name": "fsw",
            "type": "number",
            "required": False,
            "description": "Switching frequency override in hertz",
        },
        {
            "name": "r_fbb",
            "type": "number",
            "required": False,
            "description": "Bottom feedback resistor override in ohms",
        },
    ]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        vin = params.get("vin")
        vout = params.get("vout")
        iout = params.get("iout")
        if vin is None:
            errors.append("Missing required param 'vin' (input voltage in V)")
        if vout is None:
            errors.append("Missing required param 'vout' (output voltage in V)")
        if iout is None:
            errors.append("Missing required param 'iout' (output current in A)")
        if vin is not None and vout is not None and vout <= vin:
            errors.append(f"vout ({vout}V) must be greater than vin ({vin}V) for a boost")
        if iout is not None and iout <= 0:
            errors.append(f"iout ({iout}A) must be positive")
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        """Generate a boost converter subcircuit.

        Required params:
            vin: float — input voltage (V)
            vout: float — output voltage (V)
            iout: float — max output current (A)

        Optional params:
            ic: str — IC MPN (default: "TPS61230A")
            ref: str — reference designator for IC (default: "U")
            rail_name: str — output rail net name (default: derived from vout)
            vin_net: str — input rail net name (default: "VIN")
            en_net: str — enable net name (default: same as vin_net)
            fsw: float — switching frequency override (Hz)
            r_fbb: float — bottom feedback resistor override (Ohm)
        """
        vin = params["vin"]
        vout = params["vout"]
        iout = params["iout"]
        ic_name = params.get("ic", "TPS61230A")
        ref = params.get("ref", "U")
        rail_name = params.get("rail_name") or f"VDD_{vout:.1f}V".replace(".", "P")
        vin_net = params.get("vin_net", "VIN")
        en_net = params.get("en_net", vin_net)

        # Look up IC parameters
        ic_db = BOOST_IC_DATABASE.get(ic_name, BOOST_IC_DATABASE["TPS61230A"])
        vref = ic_db["vref"]
        fsw = params.get("fsw", ic_db["fsw"])
        r_fbb = params.get("r_fbb", ic_db["r_fbb_default"])

        # ---- Calculate passive values ----

        # Feedback divider: R_FBT = R_FBB * (Vout/Vref - 1)
        r_fbt_raw = feedback_divider_top(vout, vref, r_fbb)
        r_fbt = snap_to_e96(r_fbt_raw)
        r_fbb_snapped = snap_to_e96(r_fbb)
        actual_vout = feedback_divider_vout(r_fbt, r_fbb_snapped, vref)

        # Inductor
        l_raw = boost_inductor(vin, vout, fsw, iout)
        l_val = snap_ind(l_raw)

        # Input cap: 10uF typical for boost
        cin_val = 10e-6

        # Output cap: 22uF — boost output has pulsating current, needs more capacitance
        cout_val = 22e-6

        # ---- Net names (unique per instance) ----
        sw_net = f"SW_{ref}"
        fb_net = f"FB_{ref}"

        # ---- Build IC component ----
        power_pins = {
            ic_db["pin_vin"]: vin_net,
            ic_db["pin_gnd"]: "GND",
        }
        if ic_db.get("pin_vout"):
            power_pins[ic_db["pin_vout"]] = rail_name

        pin_nets = {
            ic_db["pin_sw"]: sw_net,
            ic_db["pin_fb"]: fb_net,
            ic_db["pin_en"]: en_net,
        }

        bypass_caps = [
            BypassCap(
                "CIN",
                vin_net,
                "GND",
                format_capacitance(cin_val),
                cap_footprint(cin_val),
                role="input_cap",
                presentation="topology_local",
            ),
            BypassCap(
                "COUT",
                rail_name,
                "GND",
                format_capacitance(cout_val),
                cap_footprint(cout_val),
                role="output_cap",
                presentation="topology_local",
            ),
            BypassCap(
                "L",
                vin_net,
                sw_net,
                format_inductance(l_val),
                ind_footprint(l_val, iout),
                role="inductor",
                presentation="topology_local",
            ),
        ]

        straps = [
            StrapConfig(
                "FBT",
                fb_net,
                rail_name,
                format_resistance(r_fbt),
                FP_0402R,
                role="feedback_top",
                presentation="topology_local",
            ),
            StrapConfig(
                "FBB",
                fb_net,
                "GND",
                format_resistance(r_fbb_snapped),
                FP_0402R,
                role="feedback_bottom",
                presentation="topology_local",
            ),
        ]

        # Compute input current for annotation
        d = 1.0 - vin / vout if vout > 0 else 0
        iin = iout / (1.0 - d) if d < 1.0 else iout

        annotations = [
            f"{rail_name}: {vout}V from {vin_net} at {iout}A",
            (
                f"Vout = {vref}V * (1 + {format_resistance(r_fbt)}/"
                f"{format_resistance(r_fbb_snapped)}) = {actual_vout:.3f}V"
            ),
            f"L={format_inductance(l_val)}, Cin={format_capacitance(cin_val)}, Cout={format_capacitance(cout_val)}",
            f"fsw={fsw / 1e3:.0f}kHz, D={d:.2f}, Iin_avg={iin:.2f}A",
        ]

        ic_comp = ComponentDef(
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
        ic_comp.source_ref = ref

        # ---- Boundary ports ----
        ports = [
            BoundaryPort(vin_net, "input"),
            BoundaryPort(rail_name, "output"),
            BoundaryPort("GND", "passive"),
            BoundaryPort(en_net, "input"),
        ]

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[
                f"Boost {ic_name}: {vin_net} ({vin}V) -> {rail_name} ({actual_vout:.2f}V) at {iout}A",
            ],
            primary_category="power",
        )
