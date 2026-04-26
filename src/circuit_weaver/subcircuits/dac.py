"""DAC (Digital-to-Analog Converter) subcircuit template.

Generates a complete DAC subcircuit from design parameters: update rate,
output net, interface bus nets.

Auto-calculates: output RC filter (fc = update_rate / 10), VDD/VREF
decoupling caps, address strap. All values snapped and formatted.

Supports MCP4725A0T (default, I2C 12-bit) and DAC8552IDGK (SPI dual 16-bit).
"""

from __future__ import annotations

import math
from typing import Any

from ..component_db import BypassCap, ComponentDef, StrapConfig
from .base import (
    FP_0402C,
    FP_0402R,
    BoundaryPort,
    LegacyDBProxy,
    SubcircuitResult,
    SubcircuitTemplate,
    cap_footprint,
    format_capacitance,
    format_resistance,
    rc_filter_cutoff,
    snap_cap,
    snap_to_e96,
)

# Known DAC ICs and their parameters
DAC_IC_DATABASE = LegacyDBProxy("dac")  # backed by ic_data/*.json (Task 178)


class DACTemplate(SubcircuitTemplate):
    """DAC with output RC filter and decoupling."""

    template_type = "dac"
    description = "Digital-to-analog converter with output RC filter"
    param_schema = [
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "MCP4725A0T",
            "description": "DAC IC MPN",
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
            "name": "update_rate",
            "type": "number",
            "required": False,
            "default": 1000,
            "description": "DAC update rate in Hz (filter cutoff = rate / 10)",
        },
        {
            "name": "vref",
            "type": "string",
            "required": False,
            "description": "External VREF net name (DAC8552); defaults to vdd_net",
        },
        {
            "name": "output_net",
            "type": "string",
            "required": False,
            "description": "Output net name; defaults to DAC_OUT_{ref}",
        },
        {
            "name": "sda_net",
            "type": "string",
            "required": False,
            "default": "SDA",
            "description": "I2C SDA bus net name (MCP4725)",
        },
        {
            "name": "scl_net",
            "type": "string",
            "required": False,
            "default": "SCL",
            "description": "I2C SCL bus net name (MCP4725)",
        },
        {
            "name": "din_net",
            "type": "string",
            "required": False,
            "default": "MOSI",
            "description": "SPI DIN net name (DAC8552)",
        },
        {
            "name": "sclk_net",
            "type": "string",
            "required": False,
            "default": "SCK",
            "description": "SPI SCLK net name (DAC8552)",
        },
        {
            "name": "sync_net",
            "type": "string",
            "required": False,
            "description": "SPI SYNC_N net name (DAC8552); defaults to SYNC_DAC_{ref}",
        },
        {
            "name": "output_b_net",
            "type": "string",
            "required": False,
            "description": "Second output net for dual DAC (DAC8552); defaults to DAC_OUTB_{ref}",
        },
    ]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        ic_name = params.get("ic", "MCP4725A0T")
        if ic_name not in DAC_IC_DATABASE:
            errors.append(f"Unknown DAC IC '{ic_name}'. Available: {', '.join(DAC_IC_DATABASE)}")
            return errors

        update_rate = params.get("update_rate", 1000)
        if update_rate <= 0:
            errors.append(f"update_rate ({update_rate}Hz) must be positive")
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        """Generate a DAC subcircuit.

        Optional params:
            ic: str -- DAC IC MPN (default: "MCP4725A0T")
            ref: str -- reference designator (default: "U")
            vdd_net: str -- power supply net (default: "VDD_3P3")
            update_rate: float -- update rate in Hz (default: 1000)
            vref: str -- external VREF net for DAC8552 (default: vdd_net)
            output_net: str -- output net name (default: DAC_OUT_{ref})
            sda_net: str -- I2C SDA net (default: "SDA")
            scl_net: str -- I2C SCL net (default: "SCL")
            din_net: str -- SPI DIN net (default: "MOSI")
            sclk_net: str -- SPI SCLK net (default: "SCK")
            sync_net: str -- SPI SYNC_N net (default: SYNC_DAC_{ref})
            output_b_net: str -- second output net for dual DAC (default: DAC_OUTB_{ref})
        """
        ic_name = params.get("ic", "MCP4725A0T")
        ic_db = DAC_IC_DATABASE.get(ic_name, DAC_IC_DATABASE["MCP4725A0T"])
        ref = params.get("ref", "U")
        vdd_net = params.get("vdd_net", "VDD_3P3")
        update_rate = params.get("update_rate", 1000)
        output_net = params.get("output_net", f"DAC_OUT_{ref}")

        if ic_db["interface"] == "i2c":
            return self._generate_i2c(ic_name, ic_db, ref, vdd_net, update_rate, output_net, params)
        else:
            return self._generate_spi(ic_name, ic_db, ref, vdd_net, update_rate, output_net, params)

    def _generate_i2c(
        self,
        ic_name: str,
        ic_db: dict,
        ref: str,
        vdd_net: str,
        update_rate: float,
        output_net: str,
        params: dict[str, Any],
    ) -> SubcircuitResult:
        """Generate I2C DAC (e.g. MCP4725)."""
        sda_net = params.get("sda_net", "SDA")
        scl_net = params.get("scl_net", "SCL")

        # ---- Output RC filter calculation ----
        # fc = update_rate / 10 (one decade below update rate)
        fc_target = update_rate / 10.0
        r_filter = snap_to_e96(1000.0)  # 1k standard output series resistor
        c_filter_raw = 1.0 / (2.0 * math.pi * r_filter * fc_target)
        c_filter = snap_cap(c_filter_raw)
        actual_fc = rc_filter_cutoff(r_filter, c_filter)

        # Local net between DAC VOUT pin and filter resistor
        vout_raw_net = f"VOUT_RAW_{ref}"

        # ---- Power pins ----
        power_pins = {
            ic_db["pin_vdd"]: vdd_net,
            ic_db["pin_gnd"]: "GND",
            # A0 tied to GND for address 0x60
            ic_db["pin_a0"]: "GND",
        }

        # ---- Signal pin nets ----
        pin_nets = {
            ic_db["pin_vout"]: vout_raw_net,
            ic_db["pin_sda"]: sda_net,
            ic_db["pin_scl"]: scl_net,
        }

        # ---- Bypass caps ----
        bypass_caps = [
            BypassCap(
                "C_VDD",
                vdd_net,
                "GND",
                "100nF",
                FP_0402C,
                role="decoupling",
                presentation="topology_local",
            ),
            BypassCap(
                "C_BULK",
                vdd_net,
                "GND",
                "10uF",
                cap_footprint(10e-6),
                role="bulk_cap",
                presentation="topology_local",
            ),
            # Output filter cap: filtered_net to GND
            BypassCap(
                "CFILT",
                output_net,
                "GND",
                format_capacitance(c_filter),
                cap_footprint(c_filter),
                role="output_filter",
                presentation="topology_local",
            ),
        ]

        # ---- Straps: output filter resistor ----
        straps = [
            StrapConfig(
                "RFILT",
                vout_raw_net,
                output_net,
                format_resistance(r_filter),
                FP_0402R,
                role="output_filter",
                presentation="topology_local",
            ),
        ]

        # ---- Annotations ----
        i2c_addr = ic_db.get("i2c_addr_a0_gnd", "0x60")
        annotations = [
            f"DAC {ic_name}: {ic_db['bits']}-bit, filter fc={actual_fc:.0f}Hz",
            f"I2C address: {i2c_addr} (A0=GND)",
            f"Output filter: {format_resistance(r_filter)} + {format_capacitance(c_filter)}, fc={actual_fc:.0f}Hz",
            "I2C pull-ups may be needed on SDA/SCL if not present on bus",
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

        # ---- Boundary ports ----
        ports = [
            BoundaryPort(output_net, "output"),
            BoundaryPort(vdd_net, "input"),
            BoundaryPort("GND", "passive"),
            BoundaryPort(sda_net, "bidirectional"),
            BoundaryPort(scl_net, "input"),
        ]

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[
                f"DAC {ic_name}: {ic_db['bits']}-bit I2C {i2c_addr}, fc={actual_fc:.0f}Hz, out={output_net}",
            ],
            primary_category="digital",
        )

    def _generate_spi(
        self,
        ic_name: str,
        ic_db: dict,
        ref: str,
        vdd_net: str,
        update_rate: float,
        output_net: str,
        params: dict[str, Any],
    ) -> SubcircuitResult:
        """Generate SPI DAC (e.g. DAC8552)."""
        din_net = params.get("din_net", "MOSI")
        sclk_net = params.get("sclk_net", "SCK")
        sync_net = params.get("sync_net", f"SYNC_DAC_{ref}")
        vref_net = params.get("vref", vdd_net)
        output_b_net = params.get("output_b_net", f"DAC_OUTB_{ref}")

        # ---- Output RC filter calculation ----
        fc_target = update_rate / 10.0
        r_filter = snap_to_e96(1000.0)
        c_filter_raw = 1.0 / (2.0 * math.pi * r_filter * fc_target)
        c_filter = snap_cap(c_filter_raw)
        actual_fc = rc_filter_cutoff(r_filter, c_filter)

        # Local nets between DAC output pins and filter resistors
        vouta_raw_net = f"VOUTA_RAW_{ref}"
        voutb_raw_net = f"VOUTB_RAW_{ref}"

        # ---- Power pins ----
        power_pins = {
            ic_db["pin_vdd"]: vdd_net,
            ic_db["pin_gnd"]: "GND",
            ic_db["pin_vref"]: vref_net,
        }

        # ---- Signal pin nets ----
        pin_nets = {
            ic_db["pin_vouta"]: vouta_raw_net,
            ic_db["pin_voutb"]: voutb_raw_net,
            ic_db["pin_din"]: din_net,
            ic_db["pin_sclk"]: sclk_net,
            ic_db["pin_sync"]: sync_net,
        }

        # ---- Bypass caps ----
        bypass_caps = [
            BypassCap(
                "C_VDD",
                vdd_net,
                "GND",
                "100nF",
                FP_0402C,
                role="decoupling",
                presentation="topology_local",
            ),
            BypassCap(
                "C_VDD_BULK",
                vdd_net,
                "GND",
                "10uF",
                cap_footprint(10e-6),
                role="bulk_cap",
                presentation="topology_local",
            ),
            # VREF decoupling
            BypassCap(
                "C_VREF",
                vref_net,
                "GND",
                "100nF",
                FP_0402C,
                role="vref_decoupling",
                presentation="topology_local",
            ),
            BypassCap(
                "C_VREF_BULK",
                vref_net,
                "GND",
                "10uF",
                cap_footprint(10e-6),
                role="vref_bulk",
                presentation="topology_local",
            ),
            # Output A filter cap
            BypassCap(
                "CFILT_A",
                output_net,
                "GND",
                format_capacitance(c_filter),
                cap_footprint(c_filter),
                role="output_filter",
                presentation="topology_local",
            ),
            # Output B filter cap
            BypassCap(
                "CFILT_B",
                output_b_net,
                "GND",
                format_capacitance(c_filter),
                cap_footprint(c_filter),
                role="output_filter",
                presentation="topology_local",
            ),
        ]

        # ---- Straps: output filter resistors ----
        straps = [
            StrapConfig(
                "RFILT_A",
                vouta_raw_net,
                output_net,
                format_resistance(r_filter),
                FP_0402R,
                role="output_filter",
                presentation="topology_local",
            ),
            StrapConfig(
                "RFILT_B",
                voutb_raw_net,
                output_b_net,
                format_resistance(r_filter),
                FP_0402R,
                role="output_filter",
                presentation="topology_local",
            ),
        ]

        # ---- Annotations ----
        annotations = [
            f"DAC {ic_name}: {ic_db['bits']}-bit dual, filter fc={actual_fc:.0f}Hz",
            f"SPI interface: SYNC={sync_net}, SCLK={sclk_net}",
            f"Output filter: {format_resistance(r_filter)} + "
            f"{format_capacitance(c_filter)}, fc={actual_fc:.0f}Hz (per channel)",
            f"External VREF: {vref_net}",
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

        # ---- Boundary ports ----
        ports = [
            BoundaryPort(output_net, "output"),
            BoundaryPort(output_b_net, "output"),
            BoundaryPort(vdd_net, "input"),
            BoundaryPort("GND", "passive"),
            BoundaryPort(din_net, "input"),
            BoundaryPort(sclk_net, "input"),
            BoundaryPort(sync_net, "input"),
        ]
        if vref_net != vdd_net:
            ports.append(BoundaryPort(vref_net, "input"))

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[
                f"DAC {ic_name}: {ic_db['bits']}-bit dual SPI, "
                f"fc={actual_fc:.0f}Hz, outA={output_net}, outB={output_b_net}",
            ],
            primary_category="digital",
        )
