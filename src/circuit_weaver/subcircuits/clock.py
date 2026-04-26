"""Clock synthesizer subcircuit template.

Generates a complete clock synthesizer subcircuit from design parameters:
reference frequency, PLL bandwidth, IC selection.

Supports AD9528 (JESD204B/C, 14 LVDS outputs, LFCSP-72) and SI5351A
(3-output, MSOP-10).

Auto-calculates: PLL loop filter (R + 2 caps) from target bandwidth
using rc_filter_cutoff() solved for R, VDD/VDDO decoupling caps.
"""

from __future__ import annotations

import math
from typing import Any

from ..component_db import BypassCap, ComponentDef, StrapConfig
from .base import (
    FP_0402C,
    FP_0402R,
    FP_0805C,
    BoundaryPort,
    LegacyDBProxy,
    SubcircuitResult,
    SubcircuitTemplate,
    cap_footprint,
    format_capacitance,
    format_resistance,
    rc_filter_cutoff,
    snap_to_e96,
)

# Known clock synthesizer ICs
CLOCK_IC_DATABASE = LegacyDBProxy("clock_synth")  # backed by ic_data/*.json (Task 178)


def _loop_filter_r(fc: float, c: float) -> float:
    """Solve rc_filter_cutoff for R: R = 1 / (2*pi*fc*C).

    Given target cutoff frequency and capacitor value, returns the
    resistor value needed.
    """
    if fc <= 0 or c <= 0:
        return 1e3  # default 1k
    return 1.0 / (2.0 * math.pi * fc * c)


class ClockSynthTemplate(SubcircuitTemplate):
    """Clock synthesizer with decoupling and PLL loop filter."""

    template_type = "clock_synth"
    description = "Clock synthesizer IC with decoupling and PLL loop filter"
    param_schema = [
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "AD9528",
            "description": "Clock synthesizer IC MPN",
        },
        {
            "name": "ref",
            "type": "string",
            "required": False,
            "default": "U",
            "description": "Reference designator for the IC",
        },
        {
            "name": "ref_freq",
            "type": "number",
            "required": False,
            "default": 30720000.0,
            "description": "Reference input frequency in hertz",
        },
        {
            "name": "pll_bw",
            "type": "number",
            "required": False,
            "default": 20000.0,
            "description": "PLL loop bandwidth in hertz",
        },
        {
            "name": "vdd_net",
            "type": "string",
            "required": False,
            "default": "VDD_1P8",
            "description": "Core supply net name",
        },
        {
            "name": "vddo_net",
            "type": "string",
            "required": False,
            "description": "Output driver supply net name; defaults to vdd_net",
        },
        {
            "name": "ref_net",
            "type": "string",
            "required": False,
            "default": "REF_CLK",
            "description": "Reference clock input net name",
        },
    ]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        ref_freq = params.get("ref_freq")
        if ref_freq is not None and ref_freq <= 0:
            errors.append(f"ref_freq must be positive, got {ref_freq}")
        pll_bw = params.get("pll_bw")
        if pll_bw is not None and pll_bw <= 0:
            errors.append(f"pll_bw must be positive, got {pll_bw}")
        ic_name = params.get("ic", "AD9528")
        if ic_name not in CLOCK_IC_DATABASE:
            errors.append(f"Unknown clock IC '{ic_name}'. Known: {list(CLOCK_IC_DATABASE.keys())}")
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        """Generate a clock synthesizer subcircuit.

        Optional params:
            ic: str -- IC MPN (default: "AD9528")
            ref: str -- reference designator prefix (default: "U")
            ref_freq: float -- reference frequency in Hz (default: 30.72e6)
            pll_bw: float -- PLL loop bandwidth in Hz (default: 20e3)
            vdd_net: str -- core supply net name (default: "VDD_1P8")
            vddo_net: str -- output driver supply net (default: same as vdd_net)
            ref_net: str -- reference clock input net name (default: "REF_CLK")
        """
        ic_name = params.get("ic", "AD9528")
        ic_db = CLOCK_IC_DATABASE.get(ic_name, CLOCK_IC_DATABASE["AD9528"])
        ref = params.get("ref", "U")
        ref_freq = params.get("ref_freq", 30.72e6)
        pll_bw = params.get("pll_bw", 20e3)
        vdd_net = params.get("vdd_net", "VDD_1P8")
        vddo_net = params.get("vddo_net", vdd_net)
        ref_net = params.get("ref_net", "REF_CLK")
        ref_boundary_nets: list[str] = []

        # ---- Power pin mapping ----
        power_pins: dict[str, str] = {}
        for pin_num in ic_db.get("pin_vdd", []):
            power_pins[pin_num] = vdd_net
        for pin_num in ic_db.get("pin_vddo", []):
            power_pins[pin_num] = vddo_net
        for pin_num in ic_db.get("pin_gnd", []):
            power_pins[pin_num] = "GND"

        # ---- Signal pin mapping ----
        pin_nets: dict[str, str] = {}

        # Reference input
        if "pin_ref" in ic_db:
            pin_ref = ic_db["pin_ref"]
            if "refa_p" in pin_ref:
                ref_boundary_nets = [f"{ref_net}_P", f"{ref_net}_N"]
                pin_nets[pin_ref["refa_p"]] = ref_boundary_nets[0]
                pin_nets[pin_ref["refa_n"]] = ref_boundary_nets[1]
        elif ic_name == "SI5351A":
            # SI5351A uses XA/XI pin for crystal/reference
            pin_nets["10"] = ref_net
            ref_boundary_nets = [ref_net]

        if not ref_boundary_nets:
            ref_boundary_nets = [ref_net]

        # SPI interface (AD9528)
        if "pin_spi" in ic_db:
            spi = ic_db["pin_spi"]
            pin_nets[spi["sclk"]] = f"SCLK_{ref}"
            pin_nets[spi["sdio"]] = f"SDIO_{ref}"
            pin_nets[spi["sdo"]] = f"SDO_{ref}"
            pin_nets[spi["csb"]] = f"CSB_{ref}"

        # I2C interface (SI5351A)
        if "pin_i2c" in ic_db:
            i2c = ic_db["pin_i2c"]
            pin_nets[i2c["sda"]] = f"SDA_{ref}"
            pin_nets[i2c["scl"]] = f"SCL_{ref}"

        # Reset (AD9528)
        if "pin_resetb" in ic_db:
            pin_nets[ic_db["pin_resetb"]] = f"RESETB_{ref}"

        # OEB (SI5351A)
        if "pin_oeb" in ic_db:
            pin_nets[ic_db["pin_oeb"]] = f"OEB_{ref}"

        # ---- Bypass caps: 100nF per power domain + 10uF bulk ----
        bypass_caps: list[BypassCap] = []

        # VDD domain decoupling
        vdd_pin_count = len(ic_db.get("pin_vdd", []))
        for i in range(vdd_pin_count):
            bypass_caps.append(
                BypassCap(f"CVDD{i}", vdd_net, "GND", "100nF", FP_0402C),
            )
        # VDD bulk cap
        bypass_caps.append(
            BypassCap("CVDD_BULK", vdd_net, "GND", "10uF", FP_0805C),
        )

        # VDDO domain decoupling (if separate)
        vddo_pin_count = len(ic_db.get("pin_vddo", []))
        if vddo_pin_count > 0:
            for i in range(vddo_pin_count):
                bypass_caps.append(
                    BypassCap(f"CVDDO{i}", vddo_net, "GND", "100nF", FP_0402C),
                )
            # VDDO bulk cap
            bypass_caps.append(
                BypassCap("CVDDO_BULK", vddo_net, "GND", "10uF", FP_0805C),
            )

        # ---- Reference crystal/TCXO bypass cap ----
        bypass_caps.append(
            BypassCap(
                "CREF",
                ref_boundary_nets[0],
                "GND",
                "100nF",
                FP_0402C,
            ),
        )

        # ---- PLL loop filter ----
        straps: list[StrapConfig] = []
        loop_filter_annotations: list[str] = []

        if ic_db.get("has_pll_loop_filter"):
            pin_lf = ic_db["pin_lf"]

            # Use C1 (primary) to derive R from target bandwidth
            c1_val = ic_db.get("pll_filter_c1_default", 100e-9)
            c2_val = ic_db.get("pll_filter_c2_default", 10e-9)

            # Solve R = 1 / (2*pi*fc*C1) for target PLL bandwidth
            r_val_raw = _loop_filter_r(pll_bw, c1_val)
            r_val = snap_to_e96(r_val_raw)

            # Verify actual bandwidth with snapped R
            actual_bw = rc_filter_cutoff(r_val, c1_val)

            # LF1 = C1 to GND, LF2 = R between LF1 and LF3, LF3 = C2 to GND
            lf1_net = f"LF1_{ref}"
            lf2_net = f"LF2_{ref}"
            lf3_net = f"LF3_{ref}"

            pin_nets[pin_lf["lf1"]] = lf1_net
            pin_nets[pin_lf["lf2"]] = lf2_net
            pin_nets[pin_lf["lf3"]] = lf3_net

            # Loop filter caps
            bypass_caps.append(
                BypassCap(
                    "CLF1",
                    lf1_net,
                    "GND",
                    format_capacitance(c1_val),
                    cap_footprint(c1_val),
                    role="loop_filter",
                    presentation="topology_local",
                ),
            )
            bypass_caps.append(
                BypassCap(
                    "CLF2",
                    lf3_net,
                    "GND",
                    format_capacitance(c2_val),
                    cap_footprint(c2_val),
                    role="loop_filter",
                    presentation="topology_local",
                ),
            )

            # Loop filter resistor (between LF1/LF2 junction and LF3)
            straps.append(
                StrapConfig(
                    "RLF",
                    lf2_net,
                    lf1_net,
                    format_resistance(r_val),
                    FP_0402R,
                    role="loop_filter",
                    presentation="topology_local",
                ),
            )

            loop_filter_annotations = [
                f"PLL loop filter: R={format_resistance(r_val)}, "
                f"C1={format_capacitance(c1_val)}, C2={format_capacitance(c2_val)}",
                f"Target BW={pll_bw / 1e3:.1f}kHz, "
                f"Actual BW={actual_bw / 1e3:.1f}kHz "
                f"(R = 1/(2*pi*{pll_bw / 1e3:.1f}kHz*{format_capacitance(c1_val)}) "
                f"= {format_resistance(r_val)})",
            ]

        # ---- Build IC component ----
        annotations = [
            f"Clock synthesizer {ic_name}: {ic_db['output_count']} outputs",
            f"Reference: {ref_freq / 1e6:.2f} MHz",
            f"PLL bandwidth: {pll_bw / 1e3:.1f} kHz",
        ]
        annotations.extend(loop_filter_annotations)

        # ---- Identify unused optional input pins as explicit no-connects ----
        # Pins that are defined but intentionally unused in this configuration
        # (e.g., REFB when only REFA is used, crystal osc pins, PD, SYSREF_REQ).
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
            category="clock",
            pins=list(ic_db["pins"]),
            power_pins=power_pins,
            pin_nets=pin_nets,
            bypass_caps=bypass_caps,
            straps=straps,
            annotations=annotations,
            explicit_no_connects=explicit_nc,
        )

        # ---- Boundary ports ----
        ports = [
            BoundaryPort(vdd_net, "input"),
            BoundaryPort("GND", "passive"),
        ]
        if vddo_net != vdd_net:
            ports.append(BoundaryPort(vddo_net, "input"))
        for ref_boundary_net in ref_boundary_nets:
            ports.append(BoundaryPort(ref_boundary_net, "input"))

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[
                f"Clock {ic_name}: {ref_freq / 1e6:.2f} MHz ref, "
                f"{ic_db['output_count']} outputs, "
                f"PLL BW {pll_bw / 1e3:.1f} kHz",
            ],
            primary_category="clock",
        )
