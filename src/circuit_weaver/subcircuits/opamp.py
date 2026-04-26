"""Op-amp subcircuit template.

Generates op-amp circuits with feedback networks, bias resistors,
and decoupling caps for common configurations.
"""

from __future__ import annotations

from typing import Any

from ..component_db import BypassCap, ComponentDef, StrapConfig
from .base import (
    FP_0402C,
    FP_0402R,
    BoundaryPort,
    LegacyDBProxy,
    SubcircuitResult,
    SubcircuitTemplate,
    format_resistance,
    snap_to_e24,
)

OPAMP_IC_DATABASE = LegacyDBProxy("opamp")  # backed by ic_data/*.json (Task 178)


class OpAmpTemplate(SubcircuitTemplate):
    """Op-amp with feedback network and decoupling."""

    template_type = "opamp"
    description = "Op-amp with configurable gain and feedback"
    param_schema = [
        {"name": "ic", "type": "string", "required": False, "default": "LM358"},
        {"name": "ref", "type": "string", "required": False, "default": "U"},
        {
            "name": "config",
            "type": "string",
            "required": False,
            "default": "non_inverting",
            "options": ["non_inverting", "inverting", "follower", "differential"],
        },
        {
            "name": "gain",
            "type": "number",
            "required": False,
            "default": 1.0,
            "description": "Voltage gain (absolute value)",
        },
        {
            "name": "rf",
            "type": "number",
            "required": False,
            "description": "Feedback resistor in ohms (overrides gain calculation)",
        },
        {
            "name": "rin",
            "type": "number",
            "required": False,
            "description": "Input resistor in ohms (overrides gain calculation)",
        },
        {"name": "vdd_net", "type": "string", "required": False, "default": "VDD_3P3"},
        {"name": "gnd_net", "type": "string", "required": False, "default": "GND"},
        {"name": "in_net", "type": "string", "required": False},
        {"name": "out_net", "type": "string", "required": False},
    ]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        ic_name = params.get("ic", "LM358")
        if ic_name not in OPAMP_IC_DATABASE:
            errors.append(f"Unknown op-amp IC '{ic_name}'. Available: {', '.join(OPAMP_IC_DATABASE)}")
        config = params.get("config", "non_inverting")
        if config not in ("non_inverting", "inverting", "follower", "differential"):
            errors.append(f"Invalid config '{config}'")
        gain = params.get("gain", 1.0)
        if gain <= 0:
            errors.append(f"Gain must be positive, got {gain}")
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        ic_name = params.get("ic", "LM358")
        ic_db = OPAMP_IC_DATABASE.get(ic_name, OPAMP_IC_DATABASE["LM358"])
        ref = params.get("ref", "U")
        config = params.get("config", "non_inverting")
        gain = params.get("gain", 1.0)
        vdd_net = params.get("vdd_net", "VDD_3P3")
        gnd_net = params.get("gnd_net", "GND")
        in_net = params.get("in_net", f"OPAMP_IN_{ref}")
        out_net = params.get("out_net", f"OPAMP_OUT_{ref}")

        power_pins = {
            ic_db["pin_vplus"]: vdd_net,
            ic_db["pin_vminus"]: gnd_net,
        }

        bypass_caps = [
            BypassCap("C_DEC", vdd_net, gnd_net, "100nF", FP_0402C),
        ]

        straps = []
        annotations = [f"Op-amp {ic_name}: {config}, gain={gain}"]

        # Signal pin lookups from database
        p_out = ic_db["pin_out_a"]
        p_inm = ic_db["pin_inm_a"]
        p_inp = ic_db["pin_inp_a"]

        # Compute feedback network
        if config == "follower":
            # Unity gain: output tied to inverting input, no resistors needed
            pin_nets = {p_inp: in_net, p_out: out_net, p_inm: out_net}
            annotations.append("Voltage follower (unity gain)")
        elif config == "non_inverting":
            # Gain = 1 + Rf/Rin
            rf_val = params.get("rf")
            rin_val = params.get("rin")
            if rf_val is None and rin_val is None:
                if gain <= 1.0:
                    rf_val = 0
                    rin_val = 1e6  # effectively a follower
                else:
                    rin_val = 10e3
                    rf_val = rin_val * (gain - 1.0)
            elif rf_val is not None and rin_val is None:
                rin_val = rf_val / max(0.001, gain - 1.0)
            elif rin_val is not None and rf_val is None:
                rf_val = rin_val * (gain - 1.0)

            rf_val = snap_to_e24(rf_val)
            rin_val = snap_to_e24(rin_val)
            fb_net = f"FB_{ref}"

            pin_nets = {p_inp: in_net, p_out: out_net, p_inm: fb_net}
            straps.extend(
                [
                    StrapConfig(
                        p_inm,
                        fb_net,
                        out_net,
                        format_resistance(rf_val),
                        FP_0402R,
                        role="feedback",
                        presentation="topology_local",
                    ),
                    StrapConfig(
                        p_inm,
                        fb_net,
                        gnd_net,
                        format_resistance(rin_val),
                        FP_0402R,
                        role="feedback",
                        presentation="topology_local",
                    ),
                ]
            )
            annotations.append(f"Rf={format_resistance(rf_val)}, Rin={format_resistance(rin_val)}")
        elif config == "inverting":
            # Gain = -Rf/Rin
            rf_val = params.get("rf")
            rin_val = params.get("rin")
            if rf_val is None and rin_val is None:
                rin_val = 10e3
                rf_val = rin_val * gain
            elif rf_val is not None and rin_val is None:
                rin_val = rf_val / max(0.001, gain)
            elif rin_val is not None and rf_val is None:
                rf_val = rin_val * gain

            rf_val = snap_to_e24(rf_val)
            rin_val = snap_to_e24(rin_val)
            fb_net = f"FB_{ref}"

            pin_nets = {p_inm: fb_net, p_inp: gnd_net, p_out: out_net}
            straps.extend(
                [
                    StrapConfig(
                        p_inm,
                        fb_net,
                        out_net,
                        format_resistance(rf_val),
                        FP_0402R,
                        role="feedback",
                        presentation="topology_local",
                    ),
                    StrapConfig(
                        p_inm,
                        fb_net,
                        in_net,
                        format_resistance(rin_val),
                        FP_0402R,
                        role="input",
                        presentation="topology_local",
                    ),
                ]
            )
            annotations.append(f"Rf={format_resistance(rf_val)}, Rin={format_resistance(rin_val)}")
        else:
            # Differential — simplified: same gain on both inputs
            rf_val = params.get("rf", 10e3)
            rin_val = params.get("rin", rf_val / max(0.001, gain))
            rf_val = snap_to_e24(rf_val)
            rin_val = snap_to_e24(rin_val)
            in_p_net = params.get("in_net", f"DIFF_P_{ref}")
            in_n_net = f"DIFF_N_{ref}"
            fb_net = f"FB_{ref}"
            pin_nets = {p_inm: fb_net, p_inp: in_p_net, p_out: out_net}
            straps.extend(
                [
                    StrapConfig(
                        p_inm,
                        fb_net,
                        out_net,
                        format_resistance(rf_val),
                        FP_0402R,
                        role="feedback",
                        presentation="topology_local",
                    ),
                    StrapConfig(
                        p_inm,
                        fb_net,
                        in_n_net,
                        format_resistance(rin_val),
                        FP_0402R,
                        role="input",
                        presentation="topology_local",
                    ),
                    StrapConfig(
                        p_inp,
                        in_p_net,
                        gnd_net,
                        format_resistance(rf_val),
                        FP_0402R,
                        role="feedback",
                        presentation="topology_local",
                    ),
                ]
            )
            annotations.append(f"Differential: Rf={format_resistance(rf_val)}, Rin={format_resistance(rin_val)}")

        # Mark unused channel pins as explicit no-connects (e.g., channel B on dual op-amps)
        explicit_nc: set[str] = set()
        handled_pins = set(pin_nets) | set(power_pins) | {s.pin for s in straps}
        for pin in ic_db["pins"]:
            if pin.number in handled_pins:
                continue
            if pin.electrical_type in ("output", "power_out", "power_in"):
                continue
            if pin.name in ("NC", "~"):
                continue
            explicit_nc.add(pin.number)

        ic_comp = ComponentDef(
            mpn=ic_name,
            ref_prefix="U",
            value=ic_name,
            footprint=ic_db["footprint"],
            description=ic_db["description"],
            category="analog",
            pins=list(ic_db["pins"]),
            power_pins=power_pins,
            pin_nets=pin_nets,
            bypass_caps=bypass_caps,
            straps=straps,
            annotations=annotations,
            explicit_no_connects=explicit_nc,
        )

        ports = [
            BoundaryPort(vdd_net, "input"),
            BoundaryPort(gnd_net, "passive"),
            BoundaryPort(in_net, "input"),
            BoundaryPort(out_net, "output"),
        ]

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[f"Op-amp {ic_name}: {config} gain={gain}"],
            primary_category="analog",
        )
