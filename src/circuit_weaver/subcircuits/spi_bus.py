"""SPI bus conditioning subcircuit template.

Generates SPI bus series termination resistors and optional level
shifting for multi-voltage domains.

Auto-calculates: series termination resistance from bus speed and
trace impedance.  All values snapped to E24.

Supports RESISTORS_ONLY (default) and SN74LVC1T45 (single-bit
level shifter, used per line) topologies.
"""

from __future__ import annotations

from typing import Any

from ..component_db import BypassCap, ComponentDef, PinDef, StrapConfig
from .base import (
    BoundaryPort,
    FP_0402C,
    FP_0402R,
    LegacyDBProxy,
    SubcircuitResult,
    SubcircuitTemplate,
    format_resistance,
    snap_to_e24,
)

# Known SPI bus ICs / topologies
SPI_BUS_IC_DATABASE = LegacyDBProxy("spi_bus")  # backed by ic_data/*.json (Task 178)


class SPIBusTemplate(SubcircuitTemplate):
    """SPI bus conditioning with series termination or level shifting."""

    template_type = "spi_bus"
    description = "SPI bus series termination or level shifter"
    param_schema = [
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "RESISTORS_ONLY",
            "description": "SPI bus topology (RESISTORS_ONLY or SN74LVC1T45)",
        },
        {
            "name": "ref",
            "type": "string",
            "required": False,
            "default": "RP",
            "description": "Reference designator",
        },
        {
            "name": "speed_mhz",
            "type": "number",
            "required": False,
            "default": 10,
            "description": "SPI clock speed in MHz",
        },
        {
            "name": "z_trace",
            "type": "number",
            "required": False,
            "default": 50,
            "description": "PCB trace impedance in ohms (for series termination)",
        },
        {
            "name": "vdd_net",
            "type": "string",
            "required": False,
            "default": "VDD_3P3",
            "description": "SPI bus supply net name",
        },
        {
            "name": "mosi_net",
            "type": "string",
            "required": False,
            "default": "SPI_MOSI",
            "description": "MOSI signal net name",
        },
        {
            "name": "miso_net",
            "type": "string",
            "required": False,
            "default": "SPI_MISO",
            "description": "MISO signal net name",
        },
        {
            "name": "sclk_net",
            "type": "string",
            "required": False,
            "default": "SPI_SCLK",
            "description": "SCLK signal net name",
        },
        {
            "name": "cs_net",
            "type": "string",
            "required": False,
            "default": "SPI_CS_N",
            "description": "Chip select net name (directly passed through)",
        },
        {
            "name": "vcca_net",
            "type": "string",
            "required": False,
            "description": "Low-side voltage for level shifter (A side)",
        },
        {
            "name": "vccb_net",
            "type": "string",
            "required": False,
            "description": "High-side voltage for level shifter (B side)",
        },
    ]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        ic_name = params.get("ic", "RESISTORS_ONLY")
        if ic_name not in SPI_BUS_IC_DATABASE:
            errors.append(
                f"Unknown SPI bus IC '{ic_name}'. "
                f"Available: {', '.join(SPI_BUS_IC_DATABASE)}"
            )

        speed = params.get("speed_mhz", 10)
        if speed <= 0:
            errors.append(f"speed_mhz ({speed}) must be positive")

        z_trace = params.get("z_trace", 50)
        if z_trace <= 0:
            errors.append(f"z_trace ({z_trace}) must be positive")

        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        """Generate an SPI bus conditioning subcircuit.

        Optional params:
            ic: str -- topology (default: "RESISTORS_ONLY")
            ref: str -- reference designator (default: "RP")
            speed_mhz: float -- SPI clock speed in MHz (default: 10)
            z_trace: float -- trace impedance in ohms (default: 50)
            vdd_net: str -- supply net (default: "VDD_3P3")
            mosi_net: str -- MOSI net (default: "SPI_MOSI")
            miso_net: str -- MISO net (default: "SPI_MISO")
            sclk_net: str -- SCLK net (default: "SPI_SCLK")
            cs_net: str -- CS net (default: "SPI_CS_N")
            vcca_net: str -- low-side voltage for level shifter
            vccb_net: str -- high-side voltage for level shifter
        """
        ic_name = params.get("ic", "RESISTORS_ONLY")
        ic_db = SPI_BUS_IC_DATABASE.get(ic_name, SPI_BUS_IC_DATABASE["RESISTORS_ONLY"])

        if ic_db["has_level_shift"]:
            return self._generate_level_shifter(ic_name, ic_db, params)
        return self._generate_termination(ic_name, ic_db, params)

    def _generate_termination(
        self,
        ic_name: str,
        ic_db: dict,
        params: dict[str, Any],
    ) -> SubcircuitResult:
        """Generate SPI series termination resistor network."""
        ref = params.get("ref", "RP")
        speed_mhz = params.get("speed_mhz", 10)
        z_trace = params.get("z_trace", 50)
        vdd_net = params.get("vdd_net", "VDD_3P3")
        mosi_net = params.get("mosi_net", "SPI_MOSI")
        miso_net = params.get("miso_net", "SPI_MISO")
        sclk_net = params.get("sclk_net", "SPI_SCLK")
        cs_net = params.get("cs_net", "SPI_CS_N")

        # Series termination: typically 22-33 ohms for impedance matching.
        # For low speeds (<10MHz), 33R is fine. For high speeds, match Z_trace/2.
        if speed_mhz >= 20:
            r_term_raw = z_trace / 2
        else:
            r_term_raw = 33.0
        r_term = snap_to_e24(r_term_raw)

        # Local net names (resistor side)
        mosi_t_net = f"MOSI_T_{ref}"
        sclk_t_net = f"SCLK_T_{ref}"

        power_pins = {
            ic_db["pin_vdd"]: vdd_net,
            ic_db["pin_gnd"]: "GND",
        }
        pin_nets = {
            ic_db["pin_mosi"]: mosi_net,
            ic_db["pin_miso"]: miso_net,
            ic_db["pin_sclk"]: sclk_net,
            ic_db["pin_cs"]: cs_net,
        }

        # Series resistors on MOSI and SCLK (driven outputs from MCU).
        # MISO is input — no termination needed.
        straps = [
            StrapConfig(
                "R_MOSI",
                mosi_net,
                mosi_t_net,
                format_resistance(r_term),
                FP_0402R,
                role="spi_termination",
                presentation="topology_local",
            ),
            StrapConfig(
                "R_SCLK",
                sclk_net,
                sclk_t_net,
                format_resistance(r_term),
                FP_0402R,
                role="spi_termination",
                presentation="topology_local",
            ),
        ]

        annotations = [
            f"SPI bus termination: {format_resistance(r_term)} series on MOSI/SCLK",
            f"Speed: {speed_mhz}MHz, Z_trace: {z_trace}R",
        ]

        ic_comp = ComponentDef(
            mpn=ic_name,
            ref_prefix=ic_db["ref_prefix"],
            value="SPI_TERM",
            footprint=ic_db["footprint"],
            description=ic_db["description"],
            category="communication",
            pins=list(ic_db["pins"]),
            power_pins=power_pins,
            pin_nets=pin_nets,
            straps=straps,
            annotations=annotations,
        )
        ic_comp.source_ref = ref

        ports = [
            BoundaryPort(vdd_net, "input"),
            BoundaryPort("GND", "passive"),
            BoundaryPort(mosi_net, "input"),
            BoundaryPort(miso_net, "output"),
            BoundaryPort(sclk_net, "input"),
            BoundaryPort(cs_net, "input"),
            BoundaryPort(mosi_t_net, "output"),
            BoundaryPort(sclk_t_net, "output"),
        ]

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[
                f"SPI termination: {format_resistance(r_term)} series, "
                f"{speed_mhz}MHz",
            ],
            primary_category="communication",
        )

    def _generate_level_shifter(
        self,
        ic_name: str,
        ic_db: dict,
        params: dict[str, Any],
    ) -> SubcircuitResult:
        """Generate SPI level shifter using per-signal SN74LVC1T45 ICs."""
        ref = params.get("ref", "U")
        vdd_net = params.get("vdd_net", "VDD_3P3")
        vcca_net = params.get("vcca_net") or vdd_net
        vccb_net = params.get("vccb_net", "VDD_5V")
        mosi_net = params.get("mosi_net", "SPI_MOSI")
        miso_net = params.get("miso_net", "SPI_MISO")
        sclk_net = params.get("sclk_net", "SPI_SCLK")
        cs_net = params.get("cs_net", "SPI_CS_N")

        # High-side net names
        mosi_hv = f"MOSI_HV_{ref}"
        miso_hv = f"MISO_HV_{ref}"
        sclk_hv = f"SCLK_HV_{ref}"
        cs_hv = f"CS_HV_{ref}"

        # We model this as a single logical component that represents
        # the 4-channel level shifter (4x SN74LVC1T45).
        # The first IC handles MOSI, others are implicit in annotations.

        power_pins = {
            ic_db["pin_vcca"]: vcca_net,
            ic_db["pin_vccb"]: vccb_net,
            ic_db["pin_gnd"]: "GND",
        }

        # DIR pin: A-to-B for outputs (MOSI, SCLK, CS), B-to-A for inputs (MISO)
        # DIR=HIGH -> A-to-B, DIR=LOW -> B-to-A
        # For the primary component, represent MOSI (A-to-B)
        pin_nets = {
            ic_db["pin_a"]: mosi_net,
            ic_db["pin_b"]: mosi_hv,
            ic_db["pin_dir"]: vcca_net,  # DIR=HIGH for A->B
        }

        bypass_caps = [
            BypassCap(
                "C_VCCA",
                vcca_net,
                "GND",
                "100nF",
                FP_0402C,
                role="decoupling",
                presentation="topology_local",
            ),
            BypassCap(
                "C_VCCB",
                vccb_net,
                "GND",
                "100nF",
                FP_0402C,
                role="decoupling",
                presentation="topology_local",
            ),
        ]

        annotations = [
            f"SPI level shifter: {vcca_net} <-> {vccb_net}",
            f"4x {ic_name} (MOSI, MISO, SCLK, CS)",
            f"Low side: {mosi_net}/{miso_net}/{sclk_net}/{cs_net}",
            f"High side: {mosi_hv}/{miso_hv}/{sclk_hv}/{cs_hv}",
        ]

        ic_comp = ComponentDef(
            mpn=ic_name,
            ref_prefix=ic_db["ref_prefix"],
            value=ic_name,
            footprint=ic_db["footprint"],
            description=ic_db["description"],
            category="communication",
            pins=list(ic_db["pins"]),
            power_pins=power_pins,
            pin_nets=pin_nets,
            bypass_caps=bypass_caps,
            annotations=annotations,
        )
        ic_comp.source_ref = ref

        ports = [
            BoundaryPort(vcca_net, "input"),
            BoundaryPort(vccb_net, "input"),
            BoundaryPort("GND", "passive"),
            BoundaryPort(mosi_net, "input"),
            BoundaryPort(miso_net, "output"),
            BoundaryPort(sclk_net, "input"),
            BoundaryPort(cs_net, "input"),
            BoundaryPort(mosi_hv, "output"),
            BoundaryPort(miso_hv, "input"),
            BoundaryPort(sclk_hv, "output"),
            BoundaryPort(cs_hv, "output"),
        ]

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[
                f"SPI level shifter {ic_name}: {vcca_net} <-> {vccb_net}",
            ],
            primary_category="communication",
        )
