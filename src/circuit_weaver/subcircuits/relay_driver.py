"""Relay driver subcircuit template.

Generates a relay driver circuit from design parameters: coil voltage,
coil current, number of channels, MCU drive voltage.

Auto-calculates: base resistor (for discrete NPN), power connections,
channel wiring.  All values snapped to standard E24 series and formatted.

Supports ULN2003A (default, 7-channel Darlington with internal flyback
diodes and base resistors) and DISCRETE_NPN (single-channel BJT requiring
external base resistor and flyback diode).
"""

from __future__ import annotations

from typing import Any

from ..component_db import BypassCap, ComponentDef, PinDef, StrapConfig
from .base import (
    FP_0402C,
    FP_0402R,
    BoundaryPort,
    SubcircuitResult,
    SubcircuitTemplate,
    format_resistance,
    snap_to_e24,
)

# Known relay driver ICs and their parameters
RELAY_DRIVER_IC_DATABASE = {
    "ULN2003A": {
        "description": "7-Channel Darlington Driver SOIC-16",
        "footprint": "Package_SO:SOIC-16_3.9x9.9mm_P1.27mm",
        "channels": 7,
        "has_internal_diode": True,
        "has_internal_base_r": True,
        "vce_sat": 0.9,  # V at 350 mA
        "iout_per_ch": 0.5,  # 500 mA per channel
        "pins": [
            PinDef("1", "IN1", "input", "L"),
            PinDef("2", "IN2", "input", "L"),
            PinDef("3", "IN3", "input", "L"),
            PinDef("4", "IN4", "input", "L"),
            PinDef("5", "IN5", "input", "L"),
            PinDef("6", "IN6", "input", "L"),
            PinDef("7", "IN7", "input", "L"),
            PinDef("8", "GND", "power_in", "B"),
            PinDef("9", "COM", "power_in", "T"),
            PinDef("10", "OUT7", "output", "R"),
            PinDef("11", "OUT6", "output", "R"),
            PinDef("12", "OUT5", "output", "R"),
            PinDef("13", "OUT4", "output", "R"),
            PinDef("14", "OUT3", "output", "R"),
            PinDef("15", "OUT2", "output", "R"),
            PinDef("16", "OUT1", "output", "R"),
        ],
        "pin_gnd": "8",
        "pin_com": "9",
        # Input pins 1-7, output pins 16 down to 10 (OUT1=16, OUT7=10)
        "in_pins": ["1", "2", "3", "4", "5", "6", "7"],
        "out_pins": ["16", "15", "14", "13", "12", "11", "10"],
    },
    "DISCRETE_NPN": {
        "description": "NPN BJT Relay Driver SOT-23 (2N2222 equivalent)",
        "footprint": "Package_TO_SOT_SMD:SOT-23",
        "channels": 1,
        "has_internal_diode": False,
        "has_internal_base_r": False,
        "vce_sat": 0.3,
        "iout_per_ch": 0.8,  # typical small SOT-23 NPN
        "beta_min": 100,
        "pins": [
            PinDef("1", "B", "input", "L"),
            PinDef("2", "E", "passive", "B"),
            PinDef("3", "C", "passive", "T"),
        ],
        "pin_b": "1",
        "pin_e": "2",
        "pin_c": "3",
        "in_pins": ["1"],
        "out_pins": ["3"],
    },
}


class RelayDriverTemplate(SubcircuitTemplate):
    """Relay driver with auto-calculated base resistor and flyback protection."""

    template_type = "relay_driver"
    description = "Relay coil driver with Darlington array or discrete NPN"
    param_schema = [
        {
            "name": "vcoil",
            "type": "number",
            "required": True,
            "description": "Relay coil voltage in volts",
        },
        {
            "name": "icoil",
            "type": "number",
            "required": True,
            "description": "Relay coil current in amps",
        },
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "ULN2003A",
            "description": "Driver IC MPN",
        },
        {
            "name": "ref",
            "type": "string",
            "required": False,
            "default": "U",
            "description": "Reference designator for the IC",
        },
        {
            "name": "vcoil_net",
            "type": "string",
            "required": False,
            "default": "VCOIL",
            "description": "Relay coil supply rail net name",
        },
        {
            "name": "drive_net",
            "type": "string",
            "required": False,
            "default": "RELAY_DRV",
            "description": "MCU drive signal net name (or base name for multi-channel)",
        },
        {
            "name": "channels_used",
            "type": "number",
            "required": False,
            "default": 1,
            "description": "Number of relay channels to wire up",
        },
        {
            "name": "vdrive",
            "type": "number",
            "required": False,
            "default": 3.3,
            "description": "MCU GPIO drive voltage in volts",
        },
    ]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        vcoil = params.get("vcoil")
        icoil = params.get("icoil")
        if vcoil is None:
            errors.append("Missing required param 'vcoil' (relay coil voltage in V)")
        elif vcoil <= 0:
            errors.append(f"vcoil ({vcoil}V) must be positive")
        if icoil is None:
            errors.append("Missing required param 'icoil' (relay coil current in A)")
        elif icoil <= 0:
            errors.append(f"icoil ({icoil}A) must be positive")

        ic_name = params.get("ic", "ULN2003A")
        if ic_name not in RELAY_DRIVER_IC_DATABASE:
            errors.append(f"Unknown relay driver IC '{ic_name}'. Available: {', '.join(RELAY_DRIVER_IC_DATABASE)}")
            return errors

        ic_db = RELAY_DRIVER_IC_DATABASE[ic_name]
        channels_used = int(params.get("channels_used", 1))
        if channels_used < 1:
            errors.append(f"channels_used ({channels_used}) must be >= 1")
        elif channels_used > ic_db["channels"]:
            errors.append(f"channels_used ({channels_used}) exceeds {ic_name} channel count ({ic_db['channels']})")

        if icoil is not None and icoil > ic_db["iout_per_ch"]:
            errors.append(f"icoil ({icoil}A) exceeds {ic_name} max per-channel current ({ic_db['iout_per_ch']}A)")

        vdrive = params.get("vdrive", 3.3)
        if vdrive <= 0:
            errors.append(f"vdrive ({vdrive}V) must be positive")

        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        """Generate a relay driver subcircuit.

        Required params:
            vcoil: float -- relay coil voltage (V)
            icoil: float -- relay coil current (A)

        Optional params:
            ic: str -- driver IC MPN (default: "ULN2003A")
            ref: str -- reference designator (default: "U")
            vcoil_net: str -- coil supply rail net (default: "VCOIL")
            drive_net: str -- MCU drive net base name (default: "RELAY_DRV")
            channels_used: int -- number of channels to wire (default: 1)
            vdrive: float -- MCU GPIO drive voltage (default: 3.3)
        """
        vcoil = params["vcoil"]
        icoil = params["icoil"]
        ic_name = params.get("ic", "ULN2003A")
        ref = params.get("ref", "U")
        vcoil_net = params.get("vcoil_net", "VCOIL")
        drive_net = params.get("drive_net", "RELAY_DRV")
        channels_used = int(params.get("channels_used", 1))
        vdrive = params.get("vdrive", 3.3)

        # Look up IC parameters
        ic_db = RELAY_DRIVER_IC_DATABASE.get(ic_name, RELAY_DRIVER_IC_DATABASE["ULN2003A"])

        if ic_name == "ULN2003A":
            return self._generate_uln2003a(
                ic_db,
                ref,
                vcoil,
                icoil,
                vcoil_net,
                drive_net,
                channels_used,
                vdrive,
                ic_name,
            )
        else:
            return self._generate_discrete_npn(
                ic_db,
                ref,
                vcoil,
                icoil,
                vcoil_net,
                drive_net,
                vdrive,
                ic_name,
            )

    def _generate_uln2003a(
        self,
        ic_db: dict,
        ref: str,
        vcoil: float,
        icoil: float,
        vcoil_net: str,
        drive_net: str,
        channels_used: int,
        vdrive: float,
        ic_name: str,
    ) -> SubcircuitResult:
        """Generate ULN2003A Darlington array driver."""

        # ---- Power pins ----
        power_pins = {
            ic_db["pin_gnd"]: "GND",
            ic_db["pin_com"]: vcoil_net,  # COM pin for flyback current path
        }

        # ---- Signal pin nets: wire used channels ----
        pin_nets: dict[str, str] = {}
        in_pins = ic_db["in_pins"]
        out_pins = ic_db["out_pins"]

        drive_nets: list[str] = []
        load_nets: list[str] = []

        for ch in range(channels_used):
            if channels_used == 1:
                ch_drive = drive_net
                ch_load = f"LOAD_{ref}"
            else:
                ch_drive = f"{drive_net}_{ch + 1}"
                ch_load = f"LOAD_{ref}_{ch + 1}"

            pin_nets[in_pins[ch]] = ch_drive
            pin_nets[out_pins[ch]] = ch_load
            drive_nets.append(ch_drive)
            load_nets.append(ch_load)

        # ---- Bypass caps (VDD decoupling only) ----
        bypass_caps = [
            BypassCap(
                "C_DEC",
                vcoil_net,
                "GND",
                "100nF",
                FP_0402C,
                role="decoupling",
                presentation="topology_local",
            ),
        ]

        # ---- No straps needed: ULN2003A has internal base resistors ----
        straps: list[StrapConfig] = []

        # ---- Annotations ----
        pdiss_per_ch = ic_db["vce_sat"] * icoil
        annotations = [
            f"Relay driver {ic_name}: {vcoil}V/{icoil}A coil, {channels_used} ch used",
            "Internal base resistors (2.7k), internal flyback diodes",
            f"COM pin -> {vcoil_net} (flyback current return path)",
            f"Vce_sat={ic_db['vce_sat']}V, Pdiss/ch={pdiss_per_ch:.3f}W",
            f"Vdrive={vdrive}V (MCU GPIO)",
        ]

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
            BoundaryPort(vcoil_net, "input"),
            BoundaryPort("GND", "passive"),
        ]
        for dn in drive_nets:
            ports.append(BoundaryPort(dn, "input"))
        for ln in load_nets:
            ports.append(BoundaryPort(ln, "output"))

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[
                f"Relay driver {ic_name}: {channels_used}ch, {vcoil}V/{icoil}A coil, internal flyback diodes",
            ],
            primary_category="power",
        )

    def _generate_discrete_npn(
        self,
        ic_db: dict,
        ref: str,
        vcoil: float,
        icoil: float,
        vcoil_net: str,
        drive_net: str,
        vdrive: float,
        ic_name: str,
    ) -> SubcircuitResult:
        """Generate discrete NPN BJT relay driver."""
        beta_min = ic_db["beta_min"]

        # ---- Local net names (unique per instance) ----
        base_net = f"BASE_{ref}"
        load_net = f"LOAD_{ref}"

        # ---- Base resistor calculation ----
        # Ib_required = Icoil / beta_min
        # Overdrive 10x for hard saturation: Ib_drive = 10 * Ib_required
        # Rb = (Vdrive - 0.7) / Ib_drive
        ib_drive = 10.0 * icoil / beta_min
        rb_raw = (vdrive - 0.7) / ib_drive if ib_drive > 0 else 10e3
        rb_snapped = snap_to_e24(rb_raw)
        actual_ib = (vdrive - 0.7) / rb_snapped if rb_snapped > 0 else 0
        actual_overdrive = (actual_ib * beta_min / icoil) if icoil > 0 else 0

        # ---- Power pins ----
        power_pins = {
            ic_db["pin_e"]: "GND",  # Emitter to GND
        }

        # ---- Signal pin nets ----
        pin_nets = {
            ic_db["pin_b"]: base_net,
            ic_db["pin_c"]: load_net,
        }

        # ---- Straps: base resistor ----
        straps = [
            StrapConfig(
                "RB",
                drive_net,
                base_net,
                format_resistance(rb_snapped),
                FP_0402R,
                role="base_resistor",
                presentation="topology_local",
            ),
        ]

        # No bypass caps needed for discrete BJT
        bypass_caps: list[BypassCap] = []

        # ---- Annotations ----
        annotations = [
            f"Relay driver DISCRETE_NPN: {vcoil}V/{icoil}A coil",
            (
                f"Rb = (Vdrive - 0.7) / (10 * Icoil / beta_min) = "
                f"({vdrive} - 0.7) / (10 * {icoil} / {beta_min}) = "
                f"{format_resistance(rb_snapped)}"
            ),
            f"Ib={actual_ib * 1e3:.2f}mA, overdrive={actual_overdrive:.1f}x",
            (f"WARNING: Add 1N4148 flyback diode across relay coil (cathode to {vcoil_net})"),
            f"Vdrive={vdrive}V, Vce_sat={ic_db['vce_sat']}V",
        ]

        # ---- Build BJT component ----
        bjt_comp = ComponentDef(
            mpn="DISCRETE_NPN",
            ref_prefix="Q",
            value="2N2222",
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
        bjt_comp.source_ref = ref

        # ---- Boundary ports ----
        ports = [
            BoundaryPort(vcoil_net, "input"),
            BoundaryPort("GND", "passive"),
            BoundaryPort(drive_net, "input"),
            BoundaryPort(load_net, "output"),
        ]

        return SubcircuitResult(
            components=[bjt_comp],
            boundary_ports=ports,
            annotations=[
                f"Relay driver DISCRETE_NPN: {vcoil}V/{icoil}A coil, "
                f"Rb={format_resistance(rb_snapped)}, "
                f"NEEDS external flyback diode",
            ],
            primary_category="power",
        )
