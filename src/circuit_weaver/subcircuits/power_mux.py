"""Power mux / ideal diode subcircuit template.

Generates a complete power mux subcircuit from design parameters:
two input rails, output rail, current limit.

Auto-calculates: ILIM resistors, input/output decoupling.
All values snapped to standard E96 series.

Supports TPS2113ADRBR (auto-switching mux, default) and LTC4357CMS8
(ideal diode OR controller).
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
    cap_footprint,
    format_capacitance,
    format_resistance,
    snap_to_e96,
)

# Known power mux ICs and their parameters
POWER_MUX_IC_DATABASE = LegacyDBProxy("power_mux")  # backed by ic_data/*.json (Task 178)


class PowerMuxTemplate(SubcircuitTemplate):
    """Power mux / ideal diode with auto-calculated ILIM resistors."""

    template_type = "power_mux"
    description = "Auto-switching power mux or ideal diode OR controller"
    param_schema = [
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "TPS2113ADRBR",
            "description": "Power mux IC MPN",
        },
        {
            "name": "ref",
            "type": "string",
            "required": False,
            "default": "U",
            "description": "Reference designator for the IC",
        },
        {
            "name": "ilim",
            "type": "number",
            "required": False,
            "default": 1.0,
            "description": "Current limit in amps (TPS2113 only)",
        },
        {
            "name": "vin1_net",
            "type": "string",
            "required": False,
            "default": "VUSB",
            "description": "Primary input rail net name",
        },
        {
            "name": "vin2_net",
            "type": "string",
            "required": False,
            "default": "VBAT",
            "description": "Secondary input rail net name",
        },
        {
            "name": "vout_net",
            "type": "string",
            "required": False,
            "default": "VSYS",
            "description": "Output rail net name",
        },
    ]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        ic_name = params.get("ic", "TPS2113ADRBR")
        if ic_name not in POWER_MUX_IC_DATABASE:
            errors.append(f"Unknown power mux IC '{ic_name}'. Available: {', '.join(POWER_MUX_IC_DATABASE)}")
        ilim = params.get("ilim", 1.0)
        if ilim is not None and ilim <= 0:
            errors.append(f"ilim ({ilim}A) must be positive")
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        """Generate a power mux subcircuit.

        Optional params:
            ic: str — IC MPN (default: "TPS2113ADRBR")
            ref: str — reference designator (default: "U")
            ilim: float — current limit in amps (default: 1.0)
            vin1_net: str — primary input rail (default: "VUSB")
            vin2_net: str — secondary input rail (default: "VBAT")
            vout_net: str — output rail (default: "VSYS")
        """
        ic_name = params.get("ic", "TPS2113ADRBR")
        ic_db = POWER_MUX_IC_DATABASE.get(ic_name, POWER_MUX_IC_DATABASE["TPS2113ADRBR"])
        ref = params.get("ref", "U")
        ilim = params.get("ilim", 1.0)
        vin1_net = params.get("vin1_net", "VUSB")
        vin2_net = params.get("vin2_net", "VBAT")
        vout_net = params.get("vout_net", "VSYS")

        # ---- Net names (unique per instance) ----
        ilim1_net = f"ILIM1_{ref}"
        ilim2_net = f"ILIM2_{ref}"

        # ---- Bypass capacitors ----
        bypass_caps: list[BypassCap] = []

        # ---- Strap resistors ----
        straps: list[StrapConfig] = []

        # ---- Annotations ----
        annotations: list[str] = []

        if ic_name == "TPS2113ADRBR":
            # ---- TPS2113 auto-switching mux ----

            # Power pins
            power_pins: dict[str, str] = {
                ic_db["pin_in1"]: vin1_net,
                ic_db["pin_in2"]: vin2_net,
                ic_db["pin_gnd"]: "GND",
            }

            # D1/D2: tie to GND (default — dead-battery disconnect disabled)
            power_pins[ic_db["pin_d1"]] = "GND"
            power_pins[ic_db["pin_d2"]] = "GND"

            # Signal pin nets
            pin_nets: dict[str, str] = {
                ic_db["pin_out"]: vout_net,
                ic_db["pin_ilim1"]: ilim1_net,
                ic_db["pin_ilim2"]: ilim2_net,
            }

            # ILIM resistors: Rlim(ohm) = 375000 / Ilim(A)
            k = ic_db["ilim_formula_k"]
            rlim_raw = k * 1000.0 / ilim  # 375 * 1000 / ilim
            rlim = snap_to_e96(rlim_raw)
            actual_ilim = k * 1000.0 / rlim if rlim > 0 else ilim

            straps.append(
                StrapConfig(
                    "RILIM1",
                    ilim1_net,
                    "GND",
                    format_resistance(rlim),
                    FP_0402R,
                    role="current_limit",
                    presentation="topology_local",
                )
            )
            straps.append(
                StrapConfig(
                    "RILIM2",
                    ilim2_net,
                    "GND",
                    format_resistance(rlim),
                    FP_0402R,
                    role="current_limit",
                    presentation="topology_local",
                )
            )

            # Input decoupling: 10uF + 100nF on each VIN
            for label, net in [("CIN1", vin1_net), ("CIN2", vin2_net)]:
                bypass_caps.append(
                    BypassCap(
                        f"{label}_BULK",
                        net,
                        "GND",
                        format_capacitance(10e-6),
                        cap_footprint(10e-6),
                        role="decoupling",
                        presentation="topology_local",
                    )
                )
                bypass_caps.append(
                    BypassCap(
                        f"{label}_HF",
                        net,
                        "GND",
                        format_capacitance(100e-9),
                        cap_footprint(100e-9),
                        role="decoupling",
                        presentation="topology_local",
                    )
                )

            # Output decoupling: 10uF + 100nF
            bypass_caps.append(
                BypassCap(
                    "COUT_BULK",
                    vout_net,
                    "GND",
                    format_capacitance(10e-6),
                    cap_footprint(10e-6),
                    role="decoupling",
                    presentation="topology_local",
                )
            )
            bypass_caps.append(
                BypassCap(
                    "COUT_HF",
                    vout_net,
                    "GND",
                    format_capacitance(100e-9),
                    cap_footprint(100e-9),
                    role="decoupling",
                    presentation="topology_local",
                )
            )

            annotations.append(f"Power mux {ic_name}: {vin1_net}+{vin2_net} -> {vout_net}, Ilim={actual_ilim:.2f}A")
            annotations.append(f"RILIM={format_resistance(rlim)} (target {ilim}A, actual {actual_ilim:.2f}A)")
            annotations.append("D1/D2=GND (dead-battery disconnect disabled)")

        else:
            # ---- LTC4357 ideal diode OR ----

            # Power pins: primary VIN + extra VIN pins (all tied to same rail)
            power_pins = {
                ic_db["pin_vin"]: vin1_net,
                ic_db["pin_gnd"]: "GND",
            }
            for pin_num in ic_db.get("pin_vin_extra", []):
                power_pins[pin_num] = vin1_net

            # Signal pin nets
            gate_net = f"GATE_{ref}"
            source_net = f"SOURCE_{ref}"
            shdn_net = f"SHDN_{ref}"

            pin_nets = {
                ic_db["pin_gate"]: gate_net,
                ic_db["pin_source"]: source_net,
                ic_db["pin_shdn"]: shdn_net,
            }

            # SHDN pull-up: 100k to VIN (default enabled)
            straps.append(
                StrapConfig(
                    "R_SHDN",
                    shdn_net,
                    vin1_net,
                    format_resistance(snap_to_e96(100e3)),
                    FP_0402R,
                    role="shutdown_pullup",
                    presentation="topology_local",
                )
            )

            # Input decoupling on VIN
            bypass_caps.append(
                BypassCap(
                    "CIN_BULK",
                    vin1_net,
                    "GND",
                    format_capacitance(10e-6),
                    cap_footprint(10e-6),
                    role="decoupling",
                    presentation="topology_local",
                )
            )
            bypass_caps.append(
                BypassCap(
                    "CIN_HF",
                    vin1_net,
                    "GND",
                    format_capacitance(100e-9),
                    cap_footprint(100e-9),
                    role="decoupling",
                    presentation="topology_local",
                )
            )

            annotations.append(f"Ideal diode OR {ic_name}: {vin1_net} -> {vout_net}")
            annotations.append("SHDN_N pulled high (enabled), requires external P-MOSFET")

        # ---- Build IC component ----
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
            BoundaryPort(vin1_net, "input"),
            BoundaryPort(vin2_net, "input"),
            BoundaryPort(vout_net, "output"),
            BoundaryPort("GND", "passive"),
        ]

        summary = (
            f"Power mux {ic_name}: {vin1_net}+{vin2_net} -> {vout_net}, Ilim={ilim}A"
            if ic_db.get("has_ilim")
            else f"Ideal diode OR {ic_name}: {vin1_net} -> {vout_net}"
        )

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[summary],
            primary_category="power",
        )
