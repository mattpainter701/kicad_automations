"""Precision ADC with input filter subcircuit template.

Generates a complete ADC subcircuit with per-channel anti-alias RC
filters, decoupling caps, address configuration, and bus interface
wiring.

Supports ADS1115IDGSR (16-bit I2C) and MCP3208-CI/SL (12-bit SPI).
Auto-calculates: filter capacitor from target bandwidth, address strap.
"""

from __future__ import annotations

import math
from typing import Any

from ..component_db import BypassCap, ComponentDef, PinDef, StrapConfig
from .base import (
    BoundaryPort,
    FP_0402C,
    FP_0402R,
    LegacyDBProxy,
    SubcircuitResult,
    SubcircuitTemplate,
    cap_footprint,
    format_capacitance,
    format_resistance,
    rc_filter_cutoff,
    snap_cap,
)

# Known ADC ICs and their parameters
ADC_IC_DATABASE = LegacyDBProxy("adc")  # backed by ic_data/*.json (Task 178)


class ADCTemplate(SubcircuitTemplate):
    """Precision ADC with per-channel anti-alias input filter."""

    template_type = "adc"
    description = "Precision ADC with anti-alias RC input filters"
    param_schema = [
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "ADS1115IDGSR",
            "description": "ADC IC MPN",
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
            "name": "input_filter_bw",
            "type": "number",
            "required": False,
            "default": 1000,
            "description": "Anti-alias filter bandwidth in Hz",
        },
        {
            "name": "channels",
            "type": "number",
            "required": False,
            "default": 4,
            "description": "Number of active input channels",
        },
        {
            "name": "i2c_addr",
            "type": "string",
            "required": False,
            "default": "GND",
            "description": "I2C address select (GND/VDD/SDA/SCL) for ADS1115",
        },
        {
            "name": "sda_net",
            "type": "string",
            "required": False,
            "default": "SDA",
            "description": "I2C SDA bus net name",
        },
        {
            "name": "scl_net",
            "type": "string",
            "required": False,
            "default": "SCL",
            "description": "I2C SCL bus net name",
        },
        {
            "name": "cs_net",
            "type": "string",
            "required": False,
            "description": "SPI chip select net name (MCP3208)",
        },
        {
            "name": "spi_mosi_net",
            "type": "string",
            "required": False,
            "default": "MOSI",
            "description": "SPI MOSI bus net name",
        },
        {
            "name": "spi_miso_net",
            "type": "string",
            "required": False,
            "default": "MISO",
            "description": "SPI MISO bus net name",
        },
        {
            "name": "spi_sck_net",
            "type": "string",
            "required": False,
            "default": "SCK",
            "description": "SPI clock bus net name",
        },
        {
            "name": "vref_net",
            "type": "string",
            "required": False,
            "description": "External VREF net (MCP3208); defaults to vdd_net",
        },
    ]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        ic_name = params.get("ic", "ADS1115IDGSR")
        if ic_name not in ADC_IC_DATABASE:
            errors.append(f"Unknown ADC IC '{ic_name}'. Available: {', '.join(ADC_IC_DATABASE)}")
            return errors

        ic_db = ADC_IC_DATABASE[ic_name]
        channels = params.get("channels", 4)
        if channels < 1 or channels > ic_db["max_channels"]:
            errors.append(f"channels ({channels}) must be 1-{ic_db['max_channels']} for {ic_name}")

        bw = params.get("input_filter_bw", 1000)
        if bw <= 0:
            errors.append(f"input_filter_bw ({bw}Hz) must be positive")

        if ic_db["interface"] == "i2c":
            addr = params.get("i2c_addr", "GND")
            valid_addrs = list(ic_db.get("i2c_addr_map", {}).keys())
            if addr not in valid_addrs:
                errors.append(f"Invalid i2c_addr '{addr}'. Available: {', '.join(valid_addrs)}")
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        """Generate an ADC subcircuit.

        Required params: (none, all have defaults)

        Optional params:
            ic: str -- ADC IC MPN (default: "ADS1115IDGSR")
            ref: str -- reference designator (default: "U")
            vdd_net: str -- power supply net (default: "VDD_3P3")
            input_filter_bw: float -- anti-alias filter cutoff in Hz (default: 1000)
            channels: int -- number of active channels (default: 4)
            i2c_addr: str -- address select for ADS1115 (default: "GND")
            sda_net: str -- I2C SDA net (default: "SDA")
            scl_net: str -- I2C SCL net (default: "SCL")
            cs_net: str -- SPI CS net (default: derived from ref)
            spi_mosi_net: str -- SPI MOSI net (default: "MOSI")
            spi_miso_net: str -- SPI MISO net (default: "MISO")
            spi_sck_net: str -- SPI SCK net (default: "SCK")
            vref_net: str -- external VREF net for MCP3208 (default: vdd_net)
        """
        ic_name = params.get("ic", "ADS1115IDGSR")
        ic_db = ADC_IC_DATABASE.get(ic_name, ADC_IC_DATABASE["ADS1115IDGSR"])
        ref = params.get("ref", "U")
        vdd_net = params.get("vdd_net", "VDD_3P3")
        input_filter_bw = params.get("input_filter_bw", 1000)
        channels = params.get("channels", min(4, ic_db["max_channels"]))
        channels = min(channels, ic_db["max_channels"])

        if ic_db["interface"] == "i2c":
            return self._generate_i2c(ic_name, ic_db, ref, vdd_net, input_filter_bw, channels, params)
        else:
            return self._generate_spi(ic_name, ic_db, ref, vdd_net, input_filter_bw, channels, params)

    def _generate_i2c(
        self,
        ic_name: str,
        ic_db: dict,
        ref: str,
        vdd_net: str,
        input_filter_bw: float,
        channels: int,
        params: dict[str, Any],
    ) -> SubcircuitResult:
        """Generate I2C ADC (e.g. ADS1115)."""
        i2c_addr = params.get("i2c_addr", "GND")
        sda_net = params.get("sda_net", "SDA")
        scl_net = params.get("scl_net", "SCL")

        # ---- Anti-alias RC filter calculation ----
        r_filter = 1000.0  # 1k standard input protection
        c_filter_raw = 1.0 / (2.0 * math.pi * r_filter * input_filter_bw)
        c_filter = snap_cap(c_filter_raw)
        actual_fc = rc_filter_cutoff(r_filter, c_filter)

        # ---- Power pins ----
        power_pins = {
            ic_db["pin_vdd"]: vdd_net,
            ic_db["pin_gnd"]: "GND",
        }

        # ---- Signal pin nets ----
        pin_nets = {
            ic_db["pin_sda"]: sda_net,
            ic_db["pin_scl"]: scl_net,
            ic_db["pin_alert"]: f"ALERT_{ref}",
        }

        # Map input pins to filtered net names
        for i in range(channels):
            filt_net = f"FILT_{ic_db['input_names'][i]}_{ref}"
            pin_nets[ic_db["input_pins"][i]] = filt_net

        # ---- ADDR pin strap ----
        addr_map = ic_db["i2c_addr_map"]
        addr_hex = addr_map.get(i2c_addr, "0x48")
        if i2c_addr == "GND":
            addr_rail = "GND"
        elif i2c_addr == "VDD":
            addr_rail = vdd_net
        elif i2c_addr == "SDA":
            addr_rail = sda_net
        elif i2c_addr == "SCL":
            addr_rail = scl_net
        else:
            addr_rail = "GND"

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
        ]

        # Per-channel filter caps
        for i in range(channels):
            filt_net = f"FILT_{ic_db['input_names'][i]}_{ref}"
            bypass_caps.append(
                BypassCap(
                    f"CFILT_CH{i}",
                    filt_net,
                    "GND",
                    format_capacitance(c_filter),
                    cap_footprint(c_filter),
                    role="input_filter",
                    presentation="topology_local",
                ),
            )

        # ---- Straps: filter resistors + addr ----
        straps = []
        for i in range(channels):
            ch_ext_net = f"CH{i}_{ref}"
            filt_net = f"FILT_{ic_db['input_names'][i]}_{ref}"
            straps.append(
                StrapConfig(
                    f"RFILT_CH{i}",
                    ch_ext_net,
                    filt_net,
                    format_resistance(r_filter),
                    FP_0402R,
                    role="input_filter",
                    presentation="topology_local",
                ),
            )

        # ADDR strap
        straps.append(
            StrapConfig(
                "ADDR",
                f"ADDR_{ref}",
                addr_rail,
                "0R",
                FP_0402R,
                role="address_select",
                presentation="topology_local",
            ),
        )
        pin_nets[ic_db["pin_addr"]] = f"ADDR_{ref}"

        # ---- Annotations ----
        annotations = [
            f"{ic_db['bits']}-bit ADC, {ic_db['sps']} SPS, {channels} channel(s)",
            f"I2C address: {addr_hex} (ADDR -> {i2c_addr})",
            f"Input filter: {format_resistance(r_filter)} + {format_capacitance(c_filter)}, fc={actual_fc:.0f}Hz",
            "I2C pull-ups may be needed on SDA/SCL if not present on bus",
        ]

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
        )
        ic_comp.source_ref = ref

        # ---- Boundary ports ----
        ports = [
            BoundaryPort(vdd_net, "input"),
            BoundaryPort("GND", "passive"),
            BoundaryPort(sda_net, "bidirectional"),
            BoundaryPort(scl_net, "input"),
            BoundaryPort(f"ALERT_{ref}", "output"),
        ]
        for i in range(channels):
            ports.append(BoundaryPort(f"CH{i}_{ref}", "input"))

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[
                f"ADC {ic_name}: {ic_db['bits']}-bit {ic_db['sps']}SPS, "
                f"{channels}ch, I2C {addr_hex}, fc={actual_fc:.0f}Hz",
            ],
            primary_category="analog",
        )

    def _generate_spi(
        self,
        ic_name: str,
        ic_db: dict,
        ref: str,
        vdd_net: str,
        input_filter_bw: float,
        channels: int,
        params: dict[str, Any],
    ) -> SubcircuitResult:
        """Generate SPI ADC (e.g. MCP3208)."""
        cs_net = params.get("cs_net", f"CS_ADC_{ref}")
        spi_mosi_net = params.get("spi_mosi_net", "MOSI")
        spi_miso_net = params.get("spi_miso_net", "MISO")
        spi_sck_net = params.get("spi_sck_net", "SCK")
        vref_net = params.get("vref_net", vdd_net)

        # ---- Anti-alias RC filter calculation ----
        r_filter = 1000.0  # 1k standard input protection
        c_filter_raw = 1.0 / (2.0 * math.pi * r_filter * input_filter_bw)
        c_filter = snap_cap(c_filter_raw)
        actual_fc = rc_filter_cutoff(r_filter, c_filter)

        # ---- Power pins ----
        power_pins = {
            ic_db["pin_vdd"]: vdd_net,
            ic_db["pin_dgnd"]: "GND",
            ic_db["pin_agnd"]: "GND",
            ic_db["pin_vref"]: vref_net,
        }

        # ---- Signal pin nets ----
        pin_nets = {
            ic_db["pin_cs"]: cs_net,
            ic_db["pin_din"]: spi_mosi_net,
            ic_db["pin_dout"]: spi_miso_net,
            ic_db["pin_clk"]: spi_sck_net,
        }

        # Map input pins to filtered net names
        for i in range(channels):
            filt_net = f"FILT_{ic_db['input_names'][i]}_{ref}"
            pin_nets[ic_db["input_pins"][i]] = filt_net

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
        ]

        # VREF decoupling (external reference)
        if ic_db.get("needs_external_vref"):
            bypass_caps.extend(
                [
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
                ]
            )

        # Per-channel filter caps
        for i in range(channels):
            filt_net = f"FILT_{ic_db['input_names'][i]}_{ref}"
            bypass_caps.append(
                BypassCap(
                    f"CFILT_CH{i}",
                    filt_net,
                    "GND",
                    format_capacitance(c_filter),
                    cap_footprint(c_filter),
                    role="input_filter",
                    presentation="topology_local",
                ),
            )

        # ---- Straps: filter resistors ----
        straps = []
        for i in range(channels):
            ch_ext_net = f"CH{i}_{ref}"
            filt_net = f"FILT_{ic_db['input_names'][i]}_{ref}"
            straps.append(
                StrapConfig(
                    f"RFILT_CH{i}",
                    ch_ext_net,
                    filt_net,
                    format_resistance(r_filter),
                    FP_0402R,
                    role="input_filter",
                    presentation="topology_local",
                ),
            )

        # ---- Annotations ----
        annotations = [
            f"{ic_db['bits']}-bit ADC, {ic_db['sps']} SPS, {channels} channel(s)",
            f"SPI interface: CS={cs_net}, CLK={spi_sck_net}",
            f"Input filter: {format_resistance(r_filter)} + {format_capacitance(c_filter)}, fc={actual_fc:.0f}Hz",
        ]
        if ic_db.get("needs_external_vref"):
            annotations.append(f"External VREF: {vref_net}")

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
        )
        ic_comp.source_ref = ref

        # ---- Boundary ports ----
        ports = [
            BoundaryPort(vdd_net, "input"),
            BoundaryPort("GND", "passive"),
            BoundaryPort(cs_net, "input"),
            BoundaryPort(spi_mosi_net, "input"),
            BoundaryPort(spi_miso_net, "output"),
            BoundaryPort(spi_sck_net, "input"),
        ]
        if ic_db.get("needs_external_vref") and vref_net != vdd_net:
            ports.append(BoundaryPort(vref_net, "input"))
        for i in range(channels):
            ports.append(BoundaryPort(f"CH{i}_{ref}", "input"))

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[
                f"ADC {ic_name}: {ic_db['bits']}-bit {ic_db['sps']}SPS, {channels}ch, SPI, fc={actual_fc:.0f}Hz",
            ],
            primary_category="analog",
        )
