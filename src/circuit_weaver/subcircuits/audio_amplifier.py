"""Audio amplifier subcircuit template.

Generates a complete audio amplifier subcircuit from design parameters:
speaker impedance, low-frequency cutoff, VDD rail.

Auto-calculates: input coupling capacitor (analog ICs), VDD bulk decoupling,
shutdown pull-up. All values snapped to standard series.

Supports PAM8302AASCR (analog Class-D, default) and MAX98357AETE+T (I2S Class-D).
"""

from __future__ import annotations

import math
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

# Known audio amplifier ICs and their parameters
AUDIO_AMP_IC_DATABASE: dict[str, dict] = {}  # Migrated to ic_data/*.json (Task 178)


class AudioAmplifierTemplate(SubcircuitTemplate):
    """Audio amplifier with auto-calculated coupling cap and decoupling."""

    template_type = "audio_amplifier"
    description = "Class-D audio amplifier with input coupling and decoupling"
    param_schema = [
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "PAM8302AASCR",
            "description": "Audio amplifier IC MPN",
        },
        {
            "name": "ref",
            "type": "string",
            "required": False,
            "default": "U",
            "description": "Reference designator for the IC",
        },
        {
            "name": "vdd_net",
            "type": "string",
            "required": False,
            "default": "VDD_3P3",
            "description": "Supply rail net name",
        },
        {
            "name": "audio_in_net",
            "type": "string",
            "required": False,
            "default": "AUDIO_IN",
            "description": "Audio input net name (analog ICs only)",
        },
        {
            "name": "f_low",
            "type": "number",
            "required": False,
            "default": 100,
            "description": "Low-frequency cutoff in Hz for input coupling cap",
        },
        {
            "name": "speaker_impedance",
            "type": "number",
            "required": False,
            "default": 8,
            "description": "Speaker impedance in ohms",
        },
    ]

    @staticmethod
    def _ic_db() -> dict[str, dict[str, Any]]:
        """Return the hardcoded DB merged with ic_data entries for 'audio_amplifier'.

        Sprint 37 Task 158: lets users register_ic() new audio amps and have
        them work with the legacy template path too, not just the data-driven
        fallback registered in SubcircuitRegistry.
        """
        from ..ic_data import merge_into_legacy_db

        return merge_into_legacy_db(AUDIO_AMP_IC_DATABASE, "audio_amplifier")

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        ic_name = params.get("ic", "PAM8302AASCR")
        db = self._ic_db()
        if ic_name not in db:
            errors.append(f"Unknown audio amp IC '{ic_name}'. Available: {', '.join(db)}")
        f_low = params.get("f_low", 100)
        if f_low is not None and f_low <= 0:
            errors.append(f"f_low ({f_low} Hz) must be positive")
        speaker_z = params.get("speaker_impedance", 8)
        if speaker_z is not None and speaker_z <= 0:
            errors.append(f"speaker_impedance ({speaker_z} ohm) must be positive")
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        """Generate an audio amplifier subcircuit.

        Optional params:
            ic: str — IC MPN (default: "PAM8302AASCR")
            ref: str — reference designator (default: "U")
            vdd_net: str — supply rail net name (default: "VDD_3P3")
            audio_in_net: str — audio input net (default: "AUDIO_IN")
            f_low: float — low-frequency cutoff Hz (default: 100)
            speaker_impedance: float — speaker impedance ohms (default: 8)
        """
        ic_name = params.get("ic", "PAM8302AASCR")
        db = self._ic_db()
        ic_db = db.get(ic_name, db["PAM8302AASCR"])
        ref = params.get("ref", "U")
        vdd_net = params.get("vdd_net", "VDD_3P3")
        audio_in_net = params.get("audio_in_net", "AUDIO_IN")
        f_low = params.get("f_low", 100)
        speaker_impedance = params.get("speaker_impedance", 8)

        interface = ic_db.get("interface", "analog")
        gain_db = ic_db["gain_db"]

        # ---- Net names (unique per instance) ----
        inp_net = f"AMP_INP_{ref}"
        spkr_p_net = f"SPKR_P_{ref}"
        spkr_n_net = f"SPKR_N_{ref}"
        sd_net = f"AMP_SD_{ref}"

        # ---- Power pins ----
        power_pins: dict[str, str] = {
            ic_db["pin_vdd"]: vdd_net,
            ic_db["pin_gnd"]: "GND",
        }
        # PAM8302 has two GND pins (2 and 7)
        if ic_name == "PAM8302AASCR":
            power_pins["7"] = "GND"

        # ---- Signal pin nets ----
        pin_nets: dict[str, str] = {}

        # ---- Bypass capacitors ----
        bypass_caps: list[BypassCap] = []

        # ---- Strap resistors ----
        straps: list[StrapConfig] = []

        # ---- Annotations ----
        annotations: list[str] = []

        # VDD bulk decoupling: 10uF + 100nF (critical for Class-D H-bridge)
        bypass_caps.append(
            BypassCap(
                "C_VDD_BULK",
                vdd_net,
                "GND",
                format_capacitance(10e-6),
                cap_footprint(10e-6),
                role="decoupling",
                presentation="topology_local",
            )
        )
        bypass_caps.append(
            BypassCap(
                "C_VDD_HF",
                vdd_net,
                "GND",
                format_capacitance(100e-9),
                cap_footprint(100e-9),
                role="decoupling",
                presentation="topology_local",
            )
        )

        if interface == "analog":
            # ---- PAM8302 analog path ----
            r_in = ic_db.get("r_in", 20e3)

            # Input coupling cap: C = 1 / (2*pi*f_low*R_in)
            c_couple_raw = 1.0 / (2.0 * math.pi * f_low * r_in)
            c_couple = snap_cap(c_couple_raw)
            actual_f_low = 1.0 / (2.0 * math.pi * r_in * c_couple) if c_couple > 0 else f_low

            # Coupling cap between audio_in_net and inp_net
            bypass_caps.append(
                BypassCap(
                    "C_IN",
                    audio_in_net,
                    inp_net,
                    format_capacitance(c_couple),
                    cap_footprint(c_couple),
                    role="input_coupling",
                    presentation="topology_local",
                )
            )

            # IN_P to the coupling cap output net, IN_N to GND (single-ended input)
            pin_nets[ic_db["pin_inp"]] = inp_net
            power_pins[ic_db["pin_inn"]] = "GND"

            # Shutdown pin: 100k pull-up to VDD (default enabled)
            pin_nets[ic_db["pin_sd"]] = sd_net
            straps.append(
                StrapConfig(
                    "R_SD",
                    sd_net,
                    vdd_net,
                    format_resistance(snap_to_e96(100e3)),
                    FP_0402R,
                    role="shutdown_pullup",
                    presentation="topology_local",
                )
            )

            # Output pins
            pin_nets[ic_db["pin_vop"]] = spkr_p_net
            pin_nets[ic_db["pin_von"]] = spkr_n_net

            annotations.append(f"Audio amp {ic_name}: {gain_db}dB gain, {speaker_impedance}R speaker")
            annotations.append(
                f"Coupling cap: {format_capacitance(c_couple)} "
                f"(f_low={actual_f_low:.0f}Hz, R_in={format_resistance(r_in)})"
            )

        else:
            # ---- MAX98357A I2S path ----
            din_net = f"I2S_DIN_{ref}"
            bclk_net = f"I2S_BCLK_{ref}"
            lrclk_net = f"I2S_LRCLK_{ref}"

            pin_nets[ic_db["pin_din"]] = din_net
            pin_nets[ic_db["pin_bclk"]] = bclk_net
            pin_nets[ic_db["pin_lrclk"]] = lrclk_net

            # SD_MODE: tie to VDD for left channel mono (default)
            power_pins[ic_db["pin_sd_mode"]] = vdd_net
            # GAIN: tie to GND for 9dB gain (default)
            power_pins[ic_db["pin_gain"]] = "GND"

            # Output pins
            pin_nets[ic_db["pin_outp"]] = spkr_p_net
            pin_nets[ic_db["pin_outn"]] = spkr_n_net

            annotations.append(f"Audio amp {ic_name}: I2S input, filterless, {speaker_impedance}R speaker")
            annotations.append("SD_MODE=VDD (left ch mono), GAIN=GND (9dB)")

        annotations.append("VDD decoupling: 10uF + 100nF (Class-D H-bridge supply)")

        # ---- Build IC component ----
        ic_comp = ComponentDef(
            mpn=ic_name,
            ref_prefix="U",
            value=ic_name,
            footprint=ic_db["footprint"],
            description=ic_db["description"],
            category="audio",
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
            BoundaryPort(vdd_net, "input"),
            BoundaryPort("GND", "passive"),
            BoundaryPort(spkr_p_net, "output"),
            BoundaryPort(spkr_n_net, "output"),
        ]

        if interface == "analog":
            ports.append(BoundaryPort(audio_in_net, "input"))
        else:
            ports.append(BoundaryPort(f"I2S_DIN_{ref}", "input"))
            ports.append(BoundaryPort(f"I2S_BCLK_{ref}", "input"))
            ports.append(BoundaryPort(f"I2S_LRCLK_{ref}", "input"))

        summary = (
            f"Audio amp {ic_name}: {gain_db}dB, {speaker_impedance}R speaker"
            if interface == "analog"
            else f"Audio amp {ic_name}: I2S, {speaker_impedance}R speaker"
        )

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[summary],
            primary_category="audio",
        )
