"""Constant-current LED driver subcircuit template.

Generates a complete LED driver subcircuit from design parameters:
LED current, LED forward voltage, number of LEDs in series, input voltage.

Supports switching buck LED drivers (AL8861Y-13) and linear multi-channel
PWM current sinks (TLC5940NT).

Auto-calculates: current-sense resistor, inductor (switching only),
IREF resistor (TLC5940), input/output caps. All values snapped to E96.
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
    format_inductance,
    format_resistance,
    ind_footprint,
    res_footprint,
    snap_ind,
    snap_to_e96,
)

# Known LED driver ICs and their parameters
LED_DRIVER_IC_DATABASE = LegacyDBProxy("led_driver")  # backed by ic_data/*.json (Task 178)


class LEDDriverTemplate(SubcircuitTemplate):
    """Constant-current LED driver with auto-calculated sense resistor."""

    template_type = "led_driver"
    description = "Constant-current LED driver (buck or linear sink)"
    param_schema = [
        {
            "name": "iled",
            "type": "number",
            "required": True,
            "description": "LED current in amps",
        },
        {
            "name": "vled",
            "type": "number",
            "required": False,
            "default": 3.0,
            "description": "Forward voltage per LED in volts",
        },
        {
            "name": "num_leds",
            "type": "number",
            "required": False,
            "default": 1,
            "description": "Number of LEDs in series",
        },
        {
            "name": "vin",
            "type": "number",
            "required": False,
            "default": 12,
            "description": "Input voltage in volts",
        },
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "AL8861Y-13",
            "description": "LED driver IC MPN",
        },
        {
            "name": "ref",
            "type": "string",
            "required": False,
            "default": "U",
            "description": "Reference designator for the IC",
        },
        {
            "name": "vin_net",
            "type": "string",
            "required": False,
            "default": "VIN",
            "description": "Input rail net name",
        },
    ]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        iled = params.get("iled")
        if iled is None:
            errors.append("Missing required param 'iled' (LED current in A)")
        elif iled <= 0:
            errors.append(f"iled ({iled}A) must be positive")

        ic_name = params.get("ic", "AL8861Y-13")
        if ic_name not in LED_DRIVER_IC_DATABASE:
            errors.append(f"Unknown LED driver IC '{ic_name}'. Available: {', '.join(LED_DRIVER_IC_DATABASE)}")
            return errors

        ic_db = LED_DRIVER_IC_DATABASE[ic_name]
        if ic_db.get("topology_subtype", ic_db.get("topology", "")) == "buck":
            vin = params.get("vin", 12)
            vled = params.get("vled", 3.0)
            num_leds = params.get("num_leds", 1)
            vled_total = vled * num_leds
            if vin <= vled_total:
                errors.append(f"vin ({vin}V) must be greater than total Vled ({vled_total}V = {vled}V x {num_leds})")
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        """Generate an LED driver subcircuit.

        Required params:
            iled: float -- LED current in amps

        Optional params:
            vled: float -- forward voltage per LED (default: 3.0V)
            num_leds: int -- LEDs in series (default: 1)
            vin: float -- input voltage (default: 12V)
            ic: str -- IC MPN (default: "AL8861Y-13")
            ref: str -- reference designator (default: "U")
            vin_net: str -- input rail net name (default: "VIN")
        """
        iled = params["iled"]
        vled = params.get("vled", 3.0)
        num_leds = params.get("num_leds", 1)
        vin = params.get("vin", 12)
        ic_name = params.get("ic", "AL8861Y-13")
        ref = params.get("ref", "U")
        vin_net = params.get("vin_net", "VIN")

        ic_db = LED_DRIVER_IC_DATABASE.get(ic_name, LED_DRIVER_IC_DATABASE["AL8861Y-13"])

        if ic_db.get("topology_subtype", ic_db.get("topology", "")) == "buck":
            return self._generate_buck(ic_name, ic_db, iled, vled, num_leds, vin, ref, vin_net)
        else:
            return self._generate_linear_sink(ic_name, ic_db, iled, ref, vin_net)

    def _generate_buck(
        self,
        ic_name: str,
        ic_db: dict,
        iled: float,
        vled: float,
        num_leds: int,
        vin: float,
        ref: str,
        vin_net: str,
    ) -> SubcircuitResult:
        """Generate switching buck LED driver (e.g. AL8861Y-13)."""
        vsense = ic_db["vsense"]
        fsw = ic_db["fsw"]
        vled_total = vled * num_leds

        # ---- Calculate passive values ----

        # Current sense resistor: Rsense = Vsense / Iled
        rsense_raw = vsense / iled
        rsense = snap_to_e96(rsense_raw)
        actual_iled = vsense / rsense
        rsense_power = iled * iled * rsense

        # Inductor: L = (Vin - Vled_total) * D / (fsw * delta_IL)
        # D = Vled_total / Vin
        d = vled_total / vin if vin > 0 else 0
        ripple_ratio = 0.3
        delta_il = ripple_ratio * iled
        if delta_il > 0 and fsw > 0:
            l_raw = (vin - vled_total) * d / (fsw * delta_il)
        else:
            l_raw = 2.2e-6
        l_val = snap_ind(l_raw)

        # Input cap: 10uF
        cin_val = 10e-6

        # ---- Net names (unique per instance) ----
        sw_net = f"SW_{ref}"
        isense_net = f"ISENSE_{ref}"
        led_anode_net = f"LED_ANODE_{ref}"

        # ---- Build IC component ----
        power_pins = {
            ic_db["pin_vin"]: vin_net,
            ic_db["pin_gnd"]: "GND",
        }

        pin_nets = {
            ic_db["pin_sw"]: sw_net,
            ic_db["pin_isense"]: isense_net,
            ic_db["pin_adj"]: vin_net,  # ADJ tied to VIN for full brightness
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
                "L",
                sw_net,
                led_anode_net,
                format_inductance(l_val),
                ind_footprint(l_val, iled),
                role="inductor",
                presentation="topology_local",
            ),
        ]

        straps = [
            StrapConfig(
                "RSENSE",
                isense_net,
                "GND",
                format_resistance(rsense),
                res_footprint(rsense, rsense_power),
                role="current_sense",
                presentation="topology_local",
            ),
        ]

        annotations = [
            f"LED driver {ic_name}: {iled}A, {num_leds} LED(s)",
            f"Rsense = {vsense}V / {iled}A = {format_resistance(rsense)} (actual {actual_iled:.3f}A)",
            f"L={format_inductance(l_val)}, Cin={format_capacitance(cin_val)}",
            f"fsw={fsw / 1e3:.0f}kHz, Vled_total={vled_total}V, D={d:.2f}",
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

        ports = [
            BoundaryPort(vin_net, "input"),
            BoundaryPort("GND", "passive"),
            BoundaryPort(led_anode_net, "output"),
        ]

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[
                f"Buck LED driver {ic_name}: {vin_net} ({vin}V) -> {num_leds} LED(s) at {actual_iled:.3f}A",
            ],
            primary_category="power",
        )

    def _generate_linear_sink(
        self,
        ic_name: str,
        ic_db: dict,
        iled: float,
        ref: str,
        vin_net: str,
    ) -> SubcircuitResult:
        """Generate linear current sink LED driver (e.g. TLC5940NT)."""
        # IREF resistor: Riref = 1.24 * 31.5 / (Iout * 63) = 0.619 / Iout
        riref_raw = 0.619 / iled
        riref = snap_to_e96(riref_raw)
        actual_iled = 0.619 / riref

        # VCC decoupling
        cdec_val = 100e-9
        cbulk_val = 10e-6

        # ---- Net names ----
        iref_net = f"IREF_{ref}"
        sclk_net = f"SCLK_{ref}"
        sin_net = f"SIN_{ref}"
        blank_net = f"BLANK_{ref}"
        xlat_net = f"XLAT_{ref}"
        gsclk_net = f"GSCLK_{ref}"
        sout_net = f"SOUT_{ref}"

        # ---- Build IC component ----
        power_pins = {
            ic_db["pin_vcc"]: vin_net,
            ic_db["pin_gnd"]: "GND",
        }

        pin_nets = {
            ic_db["pin_iref"]: iref_net,
            ic_db["pin_sclk"]: sclk_net,
            ic_db["pin_sin"]: sin_net,
            ic_db["pin_blank"]: blank_net,
            ic_db["pin_xlat"]: xlat_net,
            ic_db["pin_gsclk"]: gsclk_net,
            ic_db["pin_sout"]: sout_net,
            ic_db["pin_dcprg"]: "GND",  # DCPRG low = use EEPROM dot correction
            ic_db["pin_vprg"]: "GND",  # VPRG low = GS mode
            ic_db["pin_xerr"]: f"XERR_{ref}",
        }

        # Map output pins to local nets
        for i in range(16):
            # OUT0-OUT12 are pins 1-13, OUT13-OUT15 are pins 15-17
            if i <= 12:
                out_pin = str(i + 1)
            else:
                out_pin = str(i + 2)  # skip pin 14 (GND)
            pin_nets[out_pin] = f"LED_CH{i}_{ref}"

        bypass_caps = [
            BypassCap(
                "C_VCC",
                vin_net,
                "GND",
                format_capacitance(cdec_val),
                cap_footprint(cdec_val),
                role="decoupling",
                presentation="topology_local",
            ),
            BypassCap(
                "C_BULK",
                vin_net,
                "GND",
                format_capacitance(cbulk_val),
                cap_footprint(cbulk_val),
                role="bulk_cap",
                presentation="topology_local",
            ),
        ]

        straps = [
            StrapConfig(
                "RIREF",
                iref_net,
                "GND",
                format_resistance(riref),
                FP_0402R,
                role="current_reference",
                presentation="topology_local",
            ),
        ]

        annotations = [
            f"LED driver {ic_name}: 16-channel PWM sink, {iled}A/channel",
            f"Riref = 0.619 / {iled}A = {format_resistance(riref)} (actual {actual_iled:.3f}A/ch)",
            "SPI control: SCLK, SIN, BLANK, XLAT, GSCLK",
            "I2C pull-ups may be needed on SDA/SCL if using daisy-chain",
        ]

        ic_comp = ComponentDef(
            mpn=ic_name,
            ref_prefix="U",
            value=ic_name,
            footprint=ic_db["footprint"],
            description=ic_db["description"],
            category="digital",
            pins=list(ic_db["pins"]),
            power_pins=power_pins,
            pin_nets=pin_nets,
            bypass_caps=bypass_caps,
            straps=straps,
            annotations=annotations,
        )
        ic_comp.source_ref = ref

        ports = [
            BoundaryPort(vin_net, "input"),
            BoundaryPort("GND", "passive"),
            BoundaryPort(sclk_net, "input"),
            BoundaryPort(sin_net, "input"),
            BoundaryPort(blank_net, "input"),
            BoundaryPort(xlat_net, "input"),
            BoundaryPort(gsclk_net, "input"),
            BoundaryPort(sout_net, "output"),
        ]

        # Add output channel ports
        for i in range(16):
            ports.append(BoundaryPort(f"LED_CH{i}_{ref}", "output"))

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[
                f"Linear LED driver {ic_name}: 16 channels at {actual_iled:.3f}A each",
            ],
            primary_category="digital",
        )
