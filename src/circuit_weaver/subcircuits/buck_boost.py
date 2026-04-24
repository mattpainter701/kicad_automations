"""Buck-Boost converter subcircuit template (4-switch topology).

Generates a complete buck-boost regulator subcircuit from design parameters:
VIN, VOUT, IOUT. Handles both step-up and step-down from a single topology.

Auto-calculates: feedback divider (R_FBT/R_FBB), inductor, input/output
caps. All values snapped to standard E96/E24 series.

Supports TPS63020 (default) and TPS63000 topologies.
"""

from __future__ import annotations

from typing import Any

from ..component_db import BypassCap, ComponentDef, PinDef, StrapConfig
from .base import (
    BoundaryPort,
    FP_0402R,
    LegacyDBProxy,
    SubcircuitResult,
    SubcircuitTemplate,
    buck_boost_inductor,
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

# Known buck-boost converter ICs and their parameters
BUCK_BOOST_IC_DATABASE = LegacyDBProxy("buck_boost")  # backed by ic_data/*.json (Task 178)


class BuckBoostConverterTemplate(SubcircuitTemplate):
    """Buck-Boost DC-DC converter with auto-calculated passives."""

    template_type = "buck_boost"
    description = "Buck-Boost DC-DC converter with feedback divider"
    param_schema = [
        {
            "name": "vin",
            "type": "number",
            "required": True,
            "description": "Nominal input voltage in volts",
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
            "name": "vin_min",
            "type": "number",
            "required": False,
            "description": "Minimum input voltage (for inductor sizing); defaults to vin",
        },
        {
            "name": "vin_max",
            "type": "number",
            "required": False,
            "description": "Maximum input voltage",
        },
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "TPS63020",
            "description": "Buck-boost regulator IC MPN",
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
            "default": "VBAT",
            "description": "Input rail net name",
        },
        {
            "name": "en_net",
            "type": "string",
            "required": False,
            "description": "Enable net name; defaults to vin_net",
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
        if iout is not None and iout <= 0:
            errors.append(f"iout ({iout}A) must be positive")

        ic_name = params.get("ic", "TPS63020")
        if ic_name not in BUCK_BOOST_IC_DATABASE:
            errors.append(f"Unknown buck-boost IC '{ic_name}'. Available: {', '.join(BUCK_BOOST_IC_DATABASE)}")
            return errors

        ic_db = BUCK_BOOST_IC_DATABASE[ic_name]
        if vin is not None:
            vin_min_spec, vin_max_spec = ic_db["vin_range"]
            vin_min = params.get("vin_min", vin)
            vin_max = params.get("vin_max", vin)
            if vin_min < vin_min_spec:
                errors.append(f"vin_min ({vin_min}V) below {ic_name} minimum ({vin_min_spec}V)")
            if vin_max > vin_max_spec:
                errors.append(f"vin_max ({vin_max}V) above {ic_name} maximum ({vin_max_spec}V)")
        if vout is not None:
            vout_min, vout_max = ic_db["vout_range"]
            if vout < vout_min or vout > vout_max:
                errors.append(f"vout ({vout}V) outside {ic_name} output range ({vout_min}-{vout_max}V)")
        if iout is not None and iout > ic_db["iout_max_buck"]:
            errors.append(f"iout ({iout}A) exceeds {ic_name} buck-mode rating ({ic_db['iout_max_buck']}A)")
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        """Generate a buck-boost converter subcircuit.

        Required params:
            vin: float -- nominal input voltage (V)
            vout: float -- output voltage (V)
            iout: float -- max output current (A)

        Optional params:
            vin_min: float -- minimum input voltage (V); defaults to vin
            vin_max: float -- maximum input voltage (V)
            ic: str -- IC MPN (default: "TPS63020")
            ref: str -- reference designator (default: "U")
            rail_name: str -- output rail net name
            vin_net: str -- input rail net name (default: "VBAT")
            en_net: str -- enable net name; defaults to vin_net
            r_fbb: float -- bottom feedback resistor override (Ohm)
        """
        vin = params["vin"]
        vout = params["vout"]
        iout = params["iout"]
        vin_min = params.get("vin_min", vin)
        ic_name = params.get("ic", "TPS63020")
        ref = params.get("ref", "U")
        rail_name = params.get("rail_name") or f"VDD_{vout:.1f}V".replace(".", "P")
        vin_net = params.get("vin_net", "VBAT")
        en_net = params.get("en_net", vin_net)

        # Look up IC parameters
        ic_db = BUCK_BOOST_IC_DATABASE.get(ic_name, BUCK_BOOST_IC_DATABASE["TPS63020"])
        vref = ic_db["vref"]
        fsw = ic_db["fsw"]
        r_fbb = params.get("r_fbb", ic_db["r_fbb_default"])

        # ---- Calculate passive values ----

        # Feedback divider: R_FBT = R_FBB * (Vout/Vref - 1)
        r_fbt_raw = feedback_divider_top(vout, vref, r_fbb)
        r_fbt = snap_to_e96(r_fbt_raw)
        r_fbb_snapped = snap_to_e96(r_fbb)
        actual_vout = feedback_divider_vout(r_fbt, r_fbb_snapped, vref)

        # Inductor: sized for worst-case boost at Vin_min
        l_raw = buck_boost_inductor(vin_min, vout, fsw, iout)
        l_val = snap_ind(l_raw)

        # Input caps: 10uF bulk + 100nF HF
        cin_bulk = 10e-6
        cin_hf = 100e-9

        # Output caps: 22uF bulk + 100nF HF
        cout_bulk = 22e-6
        cout_hf = 100e-9

        # VAUX cap (TPS63020 internal LDO): 10uF
        c_vaux = 10e-6

        # ---- Net names (unique per instance) ----
        fb_net = f"FB_{ref}"
        l1_net = f"L1_{ref}"
        l2_net = f"L2_{ref}"
        pg_net = f"PG_{ref}"
        vaux_net = f"VAUX_{ref}"

        # ---- Build IC component ----
        power_pins = {
            ic_db["pin_vin"]: vin_net,
            ic_db["pin_gnd"]: "GND",
            ic_db["pin_vout"]: rail_name,
        }
        # Connect duplicate power pins
        if ic_db.get("pin_vin2"):
            power_pins[ic_db["pin_vin2"]] = vin_net
        if ic_db.get("pin_vout2"):
            power_pins[ic_db["pin_vout2"]] = rail_name
        if ic_db.get("pin_gnd2"):
            power_pins[ic_db["pin_gnd2"]] = "GND"
        if ic_db.get("pin_epad"):
            power_pins[ic_db["pin_epad"]] = "GND"

        pin_nets = {
            ic_db["pin_fb"]: fb_net,
            ic_db["pin_en"]: en_net,
            ic_db["pin_l1"]: l1_net,
            ic_db["pin_l2"]: l2_net,
            ic_db["pin_ps_sync"]: "GND",  # Auto PFM/PWM mode
        }
        if ic_db.get("pin_pg"):
            pin_nets[ic_db["pin_pg"]] = pg_net
        if ic_db.get("pin_vaux"):
            pin_nets[ic_db["pin_vaux"]] = vaux_net

        bypass_caps = [
            BypassCap(
                "CIN_BULK",
                vin_net,
                "GND",
                format_capacitance(cin_bulk),
                cap_footprint(cin_bulk),
                role="input_cap",
                presentation="topology_local",
            ),
            BypassCap(
                "CIN_HF",
                vin_net,
                "GND",
                format_capacitance(cin_hf),
                cap_footprint(cin_hf),
                role="input_cap",
                presentation="topology_local",
            ),
            BypassCap(
                "COUT_BULK",
                rail_name,
                "GND",
                format_capacitance(cout_bulk),
                cap_footprint(cout_bulk),
                role="output_cap",
                presentation="topology_local",
            ),
            BypassCap(
                "COUT_HF",
                rail_name,
                "GND",
                format_capacitance(cout_hf),
                cap_footprint(cout_hf),
                role="output_cap",
                presentation="topology_local",
            ),
            BypassCap(
                "L",
                l1_net,
                l2_net,
                format_inductance(l_val),
                ind_footprint(l_val, iout),
                role="inductor",
                presentation="topology_local",
            ),
        ]

        # VAUX decoupling (TPS63020 internal LDO)
        if ic_db.get("has_vaux"):
            bypass_caps.append(
                BypassCap(
                    "CVAUX",
                    vaux_net,
                    "GND",
                    format_capacitance(c_vaux),
                    cap_footprint(c_vaux),
                    role="decoupling",
                    presentation="topology_local",
                )
            )

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

        # Determine operating mode for annotation
        if vin_min < vout:
            mode = "buck-boost"
        elif vin > vout:
            mode = "buck"
        else:
            mode = "boost"

        annotations = [
            f"{rail_name}: {vout}V from {vin_net} ({mode} mode) at {iout}A",
            (
                f"Vout = {vref}V * (1 + {format_resistance(r_fbt)}/"
                f"{format_resistance(r_fbb_snapped)}) = {actual_vout:.3f}V"
            ),
            f"L={format_inductance(l_val)} (sized for Vin_min={vin_min}V)",
            f"Cin={format_capacitance(cin_bulk)}+{format_capacitance(cin_hf)}, "
            f"Cout={format_capacitance(cout_bulk)}+{format_capacitance(cout_hf)}",
            f"fsw={fsw / 1e6:.1f}MHz",
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
        if ic_db.get("pin_pg"):
            ports.append(BoundaryPort(pg_net, "output"))

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[
                f"Buck-Boost {ic_name}: {vin_net} ({vin_min}-{vin}V) -> {rail_name} ({actual_vout:.2f}V) at {iout}A",
            ],
            primary_category="power",
        )
