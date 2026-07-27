"""Crystal oscillator subcircuit template.

Generates a complete crystal oscillator subcircuit from design parameters:
frequency, load capacitance spec, stray capacitance.

Auto-calculates: external load capacitors (CL1, CL2) from crystal CL spec
and board stray capacitance, feedback resistor (1M for startup bias).

Supports HC-49S (through-hole, 2-pin) and ABM8G (SMD 4-pin) crystals.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .. import calc
from ..component_db import BypassCap, ComponentDef, StrapConfig, emit_and_retain_passive_synthesis
from .base import (
    FP_0402R,
    BoundaryPort,
    LegacyDBProxy,
    SubcircuitResult,
    SubcircuitTemplate,
    cap_footprint,
    format_capacitance,
    format_resistance,
    snap_to_e96,
)

# Known crystal packages and their pin definitions
CRYSTAL_IC_DATABASE = LegacyDBProxy("crystal_oscillator")  # backed by ic_data/*.json (Task 178)


class CrystalOscillatorTemplate(SubcircuitTemplate):
    """Crystal oscillator with auto-calculated load caps and feedback resistor."""

    template_type = "crystal_oscillator"
    description = "Crystal oscillator with load capacitors and feedback resistor"
    param_schema = [
        {
            "name": "freq",
            "type": "number",
            "required": True,
            "description": "Crystal frequency in Hz (e.g. 8e6 for 8 MHz)",
        },
        {
            "name": "cl_spec",
            "type": "number",
            "required": True,
            "description": "Crystal load capacitance spec in pF (e.g. 12 or 20)",
        },
        {
            "name": "c_stray",
            "type": "number",
            "required": False,
            "default": 3e-12,
            "description": "Board stray capacitance in farads (default 3pF)",
        },
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "ABM8G",
            "description": "Crystal package MPN",
        },
        {
            "name": "ref",
            "type": "string",
            "required": False,
            "default": "Y",
            "description": "Reference designator for the crystal",
        },
        {
            "name": "xtal_in_net",
            "type": "string",
            "required": False,
            "default": "XTAL_IN",
            "description": "Crystal input net name (from MCU OSC_IN)",
        },
        {
            "name": "xtal_out_net",
            "type": "string",
            "required": False,
            "default": "XTAL_OUT",
            "description": "Crystal output net name (to MCU OSC_OUT)",
        },
    ]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        freq = params.get("freq")
        cl_spec = params.get("cl_spec")
        if freq is None:
            errors.append("Missing required param 'freq' (crystal frequency in Hz)")
        elif freq <= 0:
            errors.append(f"freq ({freq} Hz) must be positive")
        if cl_spec is None:
            errors.append("Missing required param 'cl_spec' (load capacitance in pF)")
        elif cl_spec <= 0:
            errors.append(f"cl_spec ({cl_spec} pF) must be positive")
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        """Generate a crystal oscillator subcircuit.

        Required params:
            freq: float — crystal frequency (Hz)
            cl_spec: float — crystal load capacitance spec (pF)

        Optional params:
            c_stray: float — board stray capacitance (F, default 3e-12)
            ic: str — crystal package MPN (default "ABM8G")
            ref: str — reference designator (default "Y")
            xtal_in_net: str — crystal input net name (default "XTAL_IN")
            xtal_out_net: str — crystal output net name (default "XTAL_OUT")
        """
        freq = params["freq"]
        cl_spec = params["cl_spec"]
        c_stray = params.get("c_stray", 3e-12)
        ic_name = params.get("ic", "ABM8G")
        ref = params.get("ref", "Y")
        xtal_in_net = params.get("xtal_in_net", "XTAL_IN")
        xtal_out_net = params.get("xtal_out_net", "XTAL_OUT")

        # Look up crystal package
        ic_db = CRYSTAL_IC_DATABASE.get(ic_name, CRYSTAL_IC_DATABASE["ABM8G"])

        # ---- Calculate passive values ----

        # The public template contract is pF.  Older programmatic callers
        # supplied the same value in farads, so normalize that legacy form
        # rather than treating it as an impossible sub-attofarad crystal.
        cl_spec_f = cl_spec if 0 < cl_spec < 1e-9 else cl_spec * 1e-12
        cl_spec_pf = cl_spec_f / 1e-12

        # Load caps: Cext = 2 * (CL - Cstray), selected upward so the
        # specified load is not under-sized by E-series rounding.  The shared
        # calculation record is retained on the generated component and its
        # emitted evidence is carried by each physical load capacitor.
        load_calculation = calc.apply_capacitor_selection(
            calc.crystal_external_load_cap(
                target=f"param:{ref}.crystal.external_load",
                load_capacitance_f=cl_spec_f,
                stray_capacitance_f=c_stray,
            ),
            series="E24",
        )
        cl_val = load_calculation.chosen_value.value

        # Feedback resistor: 1M between xtal_in and xtal_out (startup bias)
        r_fb = snap_to_e96(1e6)

        # Series resistor (drive-level limiting): ~100 ohm, annotation only
        r_series_note = snap_to_e96(100.0)

        # ---- Frequency display ----
        freq_mhz = freq / 1e6

        # ---- Build crystal component ----

        # Power pins: GND pads on 4-pin packages
        power_pins = {}
        for gnd_pin in ic_db["gnd_pins"]:
            power_pins[gnd_pin] = "GND"

        # Signal pins: XTAL1 and XTAL2
        pin_nets = {
            ic_db["pin_xtal1"]: xtal_in_net,
            ic_db["pin_xtal2"]: xtal_out_net,
        }

        # Load capacitors: CL1 on xtal_in side, CL2 on xtal_out side
        bypass_caps = [
            BypassCap(
                "CL1",
                xtal_in_net,
                "GND",
                format_capacitance(cl_val),
                cap_footprint(cl_val),
                role="load_cap",
                presentation="topology_local",
            ),
            BypassCap(
                "CL2",
                xtal_out_net,
                "GND",
                format_capacitance(cl_val),
                cap_footprint(cl_val),
                role="load_cap",
                presentation="topology_local",
            ),
        ]

        # Feedback resistor: 1M between xtal_in and xtal_out
        straps = [
            StrapConfig(
                "RFB",
                xtal_in_net,
                xtal_out_net,
                format_resistance(r_fb),
                FP_0402R,
                role="feedback",
                presentation="topology_local",
            ),
        ]

        # Crystal value string: frequency
        xtal_value = f"{freq_mhz:g}MHz"

        annotations = [
            f"Crystal {freq_mhz:g}MHz, CL={cl_spec_pf:g}pF",
            f"Load caps: 2x {format_capacitance(cl_val)}",
            f"Feedback R: {format_resistance(r_fb)}",
            f"Optional series R for drive-level limiting: ~{format_resistance(r_series_note)} on XTAL_OUT",
        ]

        xtal_comp = ComponentDef(
            mpn=ic_name,
            ref_prefix="Y",
            value=xtal_value,
            footprint=ic_db["footprint"],
            description=ic_db["description"],
            category="clock",
            pins=list(ic_db["pins"]),
            power_pins=power_pins,
            pin_nets=pin_nets,
            bypass_caps=bypass_caps,
            straps=straps,
            annotations=annotations,
        )
        xtal_comp.source_ref = ref
        load_calculation = emit_and_retain_passive_synthesis(xtal_comp, load_calculation)
        for capacitor in xtal_comp.bypass_caps:
            if capacitor.role == "load_cap":
                capacitor.selection_policy = load_calculation.policy
                capacitor.confidence = load_calculation.confidence
                capacitor.calculation_id = load_calculation.id
                capacitor.evidence_ids = (load_calculation.emits_evidence,)
        feedback_decision = calc.bounded_fallback_scalar(
            target=f"param:{ref}.crystal.feedback_bias",
            value=1e6,
            minimum=100e3,
            maximum=10e6,
            unit="ohm",
            series="E96",
        )
        feedback_calculation = emit_and_retain_passive_synthesis(
            xtal_comp,
            feedback_decision.calculation,
            finding=feedback_decision.finding,
        )
        assert isinstance(feedback_calculation, calc.CalculationRecord)
        if calc.is_selection_eligible(feedback_calculation):
            xtal_comp.straps = [
                replace(
                    strap,
                    value=format_resistance(calc.require_selection(feedback_calculation).value),
                    selection_policy=feedback_calculation.policy,
                    confidence=feedback_calculation.confidence,
                    calculation_id=feedback_calculation.id,
                    evidence_ids=(feedback_calculation.emits_evidence,),
                )
                if strap.role == "feedback"
                else strap
                for strap in xtal_comp.straps
            ]

        # ---- Boundary ports ----
        ports = [
            BoundaryPort(xtal_in_net, "bidirectional"),
            BoundaryPort(xtal_out_net, "bidirectional"),
            BoundaryPort("GND", "passive"),
        ]

        return SubcircuitResult(
            components=[xtal_comp],
            boundary_ports=ports,
            annotations=[
                f"Crystal oscillator {ic_name}: {freq_mhz:g}MHz, "
                f"CL={cl_spec_pf:g}pF, load caps 2x {format_capacitance(cl_val)}",
            ],
            primary_category="clock",
        )
