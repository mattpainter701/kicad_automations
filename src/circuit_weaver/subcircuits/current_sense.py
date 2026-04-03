"""Current sense amplifier subcircuit template.

Generates a complete high-side current sensing subcircuit from design
parameters: max current, target sense voltage, IC selection.

Auto-calculates: sense resistor (value, power, footprint), input filter
cap, VDD decoupling, address straps.  All values snapped to E96.

Supports INA219 (I2C digital, default) and INA180A1 (analog output).
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
    snap_to_e96,
)

# Sense resistor footprint selection by power dissipation
_RSENSE_FOOTPRINT_TABLE = [
    # (max_power_w, footprint)
    (0.0625, "Resistor_SMD:R_0402_1005Metric"),
    (0.100, "Resistor_SMD:R_0603_1608Metric"),
    (0.125, "Resistor_SMD:R_0805_2012Metric"),
    (0.250, "Resistor_SMD:R_1206_3216Metric"),
    (1.000, "Resistor_SMD:R_2512_6332Metric"),
]


def _rsense_footprint(power_w: float) -> str:
    """Select sense resistor footprint based on power dissipation."""
    for max_p, fp in _RSENSE_FOOTPRINT_TABLE:
        if power_w <= max_p:
            return fp
    return _RSENSE_FOOTPRINT_TABLE[-1][1]  # largest available


# Known current sense amplifier ICs
CURRENT_SENSE_IC_DATABASE = {
    "INA219": {
        "description": "High-Side Current/Power Monitor I2C MSOP-8",
        "footprint": "Package_SO:MSOP-8_3x3mm_P0.65mm",
        "ref_prefix": "U",
        "vsense_max": 0.320,  # ±320 mV full-scale (PGA=1)
        "gain": 1,  # configurable via PGA register
        "has_i2c": True,
        "has_analog_out": False,
        "pins": [
            PinDef("1", "A1", "input", "L"),
            PinDef("2", "A0", "input", "L"),
            PinDef("3", "SDA", "bidirectional", "R"),
            PinDef("4", "SCL", "input", "R"),
            PinDef("5", "GND", "power_in", "B"),
            PinDef("6", "VS", "power_in", "T"),
            PinDef("7", "IN_N", "input", "L"),
            PinDef("8", "IN_P", "input", "L"),
        ],
        "pin_vs": "6",
        "pin_gnd": "5",
        "pin_inp": "8",
        "pin_inn": "7",
        "pin_sda": "3",
        "pin_scl": "4",
        "pin_a0": "2",
        "pin_a1": "1",
    },
    "INA180A1": {
        "description": "High-Side Current Sense Amp x20 Gain SOT-23-5",
        "footprint": "Package_TO_SOT_SMD:SOT-23-5",
        "ref_prefix": "U",
        "vsense_max": 0.100,  # 100 mV max differential input
        "gain": 20,  # fixed 20 V/V
        "has_i2c": False,
        "has_analog_out": True,
        "pins": [
            PinDef("1", "OUT", "output", "R"),
            PinDef("2", "GND", "power_in", "B"),
            PinDef("3", "VS", "power_in", "T"),
            PinDef("4", "IN_N", "input", "L"),
            PinDef("5", "IN_P", "input", "L"),
        ],
        "pin_vs": "3",
        "pin_gnd": "2",
        "pin_inp": "5",
        "pin_inn": "4",
        "pin_out": "1",
    },
}


class CurrentSenseTemplate(SubcircuitTemplate):
    """High-side current sense amplifier with auto-calculated sense resistor."""

    template_type = "current_sense"
    description = "High-side current sense amplifier with auto-calculated Rsense"
    param_schema = [
        {
            "name": "imax",
            "type": "number",
            "required": True,
            "description": "Maximum current to measure in amps",
        },
        {
            "name": "vsense_target",
            "type": "number",
            "required": False,
            "default": 0.050,
            "description": "Target sense voltage at Imax in volts (default 50mV)",
        },
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "INA219",
            "description": "Current sense amplifier IC MPN",
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
            "description": "Power supply net name",
        },
        {
            "name": "sense_p_net",
            "type": "string",
            "required": False,
            "default": "SENSE_P",
            "description": "High-side sense point net (upstream of Rsense)",
        },
        {
            "name": "sense_n_net",
            "type": "string",
            "required": False,
            "default": "SENSE_N",
            "description": "Low-side sense point net (downstream of Rsense)",
        },
        {
            "name": "sda_net",
            "type": "string",
            "required": False,
            "default": "I2C_SDA",
            "description": "I2C SDA net (INA219 only)",
        },
        {
            "name": "scl_net",
            "type": "string",
            "required": False,
            "default": "I2C_SCL",
            "description": "I2C SCL net (INA219 only)",
        },
        {
            "name": "out_net",
            "type": "string",
            "required": False,
            "description": "Analog output net (INA180A1 only)",
        },
    ]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        imax = params.get("imax")
        if imax is None:
            errors.append("Missing required param 'imax' (max current in A)")
        elif imax <= 0:
            errors.append(f"imax ({imax}A) must be positive")

        vsense_target = params.get("vsense_target", 0.050)
        if vsense_target <= 0:
            errors.append(f"vsense_target ({vsense_target}V) must be positive")

        ic_name = params.get("ic", "INA219")
        if ic_name not in CURRENT_SENSE_IC_DATABASE:
            errors.append(f"Unknown current sense IC '{ic_name}'. Available: {', '.join(CURRENT_SENSE_IC_DATABASE)}")
        else:
            ic_db = CURRENT_SENSE_IC_DATABASE[ic_name]
            if imax is not None and vsense_target > 0:
                vsense_actual = vsense_target  # will be clamped in generate
                if vsense_actual > ic_db["vsense_max"]:
                    errors.append(
                        f"vsense_target ({vsense_target * 1e3:.0f}mV) exceeds "
                        f"{ic_name} max ({ic_db['vsense_max'] * 1e3:.0f}mV)"
                    )
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        """Generate a current sense amplifier subcircuit.

        Required params:
            imax: float -- maximum current to measure (A)

        Optional params:
            vsense_target: float -- target sense voltage at Imax (default: 0.050V)
            ic: str -- IC MPN (default: "INA219")
            ref: str -- reference designator (default: "U")
            vdd_net: str -- supply net (default: "VDD_3P3")
            sense_p_net: str -- high-side sense net (default: "SENSE_P")
            sense_n_net: str -- low-side sense net (default: "SENSE_N")
            sda_net: str -- I2C SDA net (default: "I2C_SDA", INA219 only)
            scl_net: str -- I2C SCL net (default: "I2C_SCL", INA219 only)
            out_net: str -- analog output net (INA180A1 only)
        """
        imax = params["imax"]
        vsense_target = params.get("vsense_target", 0.050)
        ic_name = params.get("ic", "INA219")
        ic_db = CURRENT_SENSE_IC_DATABASE.get(ic_name, CURRENT_SENSE_IC_DATABASE["INA219"])
        ref = params.get("ref", "U")
        vdd_net = params.get("vdd_net", "VDD_3P3")
        sense_p_net = params.get("sense_p_net", "SENSE_P")
        sense_n_net = params.get("sense_n_net", "SENSE_N")

        # ---- Calculate sense resistor ----
        # Clamp vsense to IC's max range
        vsense_eff = min(vsense_target, ic_db["vsense_max"])
        r_sense_raw = vsense_eff / imax
        r_sense = snap_to_e96(r_sense_raw)

        # Power dissipation and footprint
        p_sense = imax * imax * r_sense
        rsense_fp = _rsense_footprint(p_sense)

        # Actual sense voltage at Imax with snapped resistor
        vsense_actual = imax * r_sense

        # ---- Local net for the filtered sense node ----
        inp_filt_net = f"INP_FILT_{ref}"
        inn_filt_net = f"INN_FILT_{ref}"

        # ---- Power pins ----
        power_pins = {
            ic_db["pin_vs"]: vdd_net,
            ic_db["pin_gnd"]: "GND",
        }

        # ---- Signal pin nets ----
        pin_nets = {
            ic_db["pin_inp"]: inp_filt_net,
            ic_db["pin_inn"]: inn_filt_net,
        }

        # ---- Bypass caps ----
        bypass_caps = [
            BypassCap(
                "C_VS",
                vdd_net,
                "GND",
                "100nF",
                FP_0402C,
                role="decoupling",
                presentation="topology_local",
            ),
            BypassCap(
                "C_FILT",
                inp_filt_net,
                inn_filt_net,
                "100nF",
                FP_0402C,
                role="input_filter",
                presentation="topology_local",
            ),
        ]

        # ---- Straps ----
        straps = [
            # Sense resistor between sense_p and sense_n
            StrapConfig(
                "RSENSE",
                sense_p_net,
                sense_n_net,
                format_resistance(r_sense),
                rsense_fp,
                role="sense_resistor",
                presentation="topology_local",
            ),
            # Input filter resistors: sense points to filtered IC inputs
            StrapConfig(
                "R_FILT_P",
                sense_p_net,
                inp_filt_net,
                "10R",
                FP_0402R,
                role="input_filter",
                presentation="topology_local",
            ),
            StrapConfig(
                "R_FILT_N",
                sense_n_net,
                inn_filt_net,
                "10R",
                FP_0402R,
                role="input_filter",
                presentation="topology_local",
            ),
        ]

        # ---- IC-specific wiring ----
        if ic_db["has_i2c"]:
            return self._generate_i2c(
                ic_name,
                ic_db,
                ref,
                params,
                power_pins,
                pin_nets,
                bypass_caps,
                straps,
                r_sense,
                p_sense,
                vsense_actual,
                sense_p_net,
                sense_n_net,
                vdd_net,
            )
        else:
            return self._generate_analog(
                ic_name,
                ic_db,
                ref,
                params,
                power_pins,
                pin_nets,
                bypass_caps,
                straps,
                r_sense,
                p_sense,
                vsense_actual,
                sense_p_net,
                sense_n_net,
                vdd_net,
            )

    # ----------------------------------------------------------------
    # INA219 (I2C digital output)
    # ----------------------------------------------------------------
    def _generate_i2c(
        self,
        ic_name: str,
        ic_db: dict,
        ref: str,
        params: dict[str, Any],
        power_pins: dict,
        pin_nets: dict,
        bypass_caps: list[BypassCap],
        straps: list[StrapConfig],
        r_sense: float,
        p_sense: float,
        vsense_actual: float,
        sense_p_net: str,
        sense_n_net: str,
        vdd_net: str,
    ) -> SubcircuitResult:
        """Generate INA219 I2C current sense subcircuit."""
        imax = params["imax"]
        sda_net = params.get("sda_net", "I2C_SDA")
        scl_net = params.get("scl_net", "I2C_SCL")

        # I2C bus pins
        pin_nets[ic_db["pin_sda"]] = sda_net
        pin_nets[ic_db["pin_scl"]] = scl_net

        # A0/A1 address straps — tie to GND for default address 0x40
        a0_net = f"A0_{ref}"
        a1_net = f"A1_{ref}"
        pin_nets[ic_db["pin_a0"]] = a0_net
        pin_nets[ic_db["pin_a1"]] = a1_net

        straps.extend(
            [
                StrapConfig(
                    "A0",
                    a0_net,
                    "GND",
                    "0R",
                    FP_0402R,
                    role="address_select",
                    presentation="topology_local",
                ),
                StrapConfig(
                    "A1",
                    a1_net,
                    "GND",
                    "0R",
                    FP_0402R,
                    role="address_select",
                    presentation="topology_local",
                ),
            ]
        )

        annotations = [
            f"Current sense: {ic_name} on {sense_p_net}/{sense_n_net}",
            f"Imax={imax}A, Rsense={format_resistance(r_sense)} ({p_sense * 1e3:.0f}mW)",
            f"Vsense={vsense_actual * 1e3:.1f}mV at Imax, I2C addr=0x40 (A0=A1=GND)",
        ]

        ic_comp = ComponentDef(
            mpn=ic_name,
            ref_prefix=ic_db["ref_prefix"],
            value=ic_name,
            footprint=ic_db["footprint"],
            description=ic_db["description"],
            category="sensor",
            pins=list(ic_db["pins"]),
            power_pins=power_pins,
            pin_nets=pin_nets,
            bypass_caps=bypass_caps,
            straps=straps,
            annotations=annotations,
        )
        ic_comp.source_ref = ref

        ports = [
            BoundaryPort(vdd_net, "input"),
            BoundaryPort("GND", "passive"),
            BoundaryPort(sense_p_net, "input"),
            BoundaryPort(sense_n_net, "input"),
            BoundaryPort(sda_net, "bidirectional"),
            BoundaryPort(scl_net, "input"),
        ]

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[
                f"Current sense {ic_name}: Imax={imax}A, Rsense={format_resistance(r_sense)}, I2C 0x40",
            ],
            primary_category="sensor",
        )

    # ----------------------------------------------------------------
    # INA180A1 (analog output)
    # ----------------------------------------------------------------
    def _generate_analog(
        self,
        ic_name: str,
        ic_db: dict,
        ref: str,
        params: dict[str, Any],
        power_pins: dict,
        pin_nets: dict,
        bypass_caps: list[BypassCap],
        straps: list[StrapConfig],
        r_sense: float,
        p_sense: float,
        vsense_actual: float,
        sense_p_net: str,
        sense_n_net: str,
        vdd_net: str,
    ) -> SubcircuitResult:
        """Generate INA180A1 analog-output current sense subcircuit."""
        imax = params["imax"]
        out_net = params.get("out_net", f"ISENSE_OUT_{ref}")
        gain = ic_db["gain"]

        # Analog output pin
        pin_nets[ic_db["pin_out"]] = out_net

        # Output voltage at Imax
        vout_at_imax = vsense_actual * gain

        annotations = [
            f"Current sense: {ic_name} on {sense_p_net}/{sense_n_net}",
            f"Imax={imax}A, Rsense={format_resistance(r_sense)} ({p_sense * 1e3:.0f}mW)",
            f"Gain={gain}V/V, Vout={vout_at_imax:.3f}V at Imax ({out_net})",
        ]

        ic_comp = ComponentDef(
            mpn=ic_name,
            ref_prefix=ic_db["ref_prefix"],
            value=ic_name,
            footprint=ic_db["footprint"],
            description=ic_db["description"],
            category="sensor",
            pins=list(ic_db["pins"]),
            power_pins=power_pins,
            pin_nets=pin_nets,
            bypass_caps=bypass_caps,
            straps=straps,
            annotations=annotations,
        )
        ic_comp.source_ref = ref

        ports = [
            BoundaryPort(vdd_net, "input"),
            BoundaryPort("GND", "passive"),
            BoundaryPort(sense_p_net, "input"),
            BoundaryPort(sense_n_net, "input"),
            BoundaryPort(out_net, "output"),
        ]

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[
                f"Current sense {ic_name}: Imax={imax}A, "
                f"Rsense={format_resistance(r_sense)}, "
                f"Gain={gain}, Vout={vout_at_imax:.3f}V",
            ],
            primary_category="sensor",
        )
