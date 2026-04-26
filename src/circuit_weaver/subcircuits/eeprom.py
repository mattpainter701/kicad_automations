"""EEPROM subcircuit template.

Generates a complete EEPROM subcircuit with decoupling, address strapping,
and write-protect configuration.

Supports 24LC256 (I2C, default) and AT25SF128A (SPI flash).
Auto-configures address pins and write-protect pull-ups.
"""

from __future__ import annotations

from typing import Any

from ..component_db import BypassCap, ComponentDef, StrapConfig
from .base import (
    FP_0402C,
    BoundaryPort,
    SubcircuitResult,
    SubcircuitTemplate,
)

EEPROM_IC_DATABASE: dict[str, dict] = {}  # Migrated to ic_data/*.json (Task 178)


class EEPROMTemplate(SubcircuitTemplate):
    """EEPROM / flash memory with address config, WP, and decoupling."""

    template_type = "eeprom"
    description = "I2C EEPROM or SPI flash with address config and write protect"
    param_schema = [
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "24LC256",
            "description": "EEPROM/flash IC MPN",
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
            "name": "i2c_addr_offset",
            "type": "integer",
            "required": False,
            "default": 0,
            "minimum": 0,
            "maximum": 7,
            "description": "I2C address offset (0-7) set by A0/A1/A2 pins",
        },
        {
            "name": "sda_net",
            "type": "string",
            "required": False,
            "default": "I2C_SDA",
            "description": "I2C SDA net name",
        },
        {
            "name": "scl_net",
            "type": "string",
            "required": False,
            "default": "I2C_SCL",
            "description": "I2C SCL net name",
        },
        {
            "name": "cs_net",
            "type": "string",
            "required": False,
            "description": "SPI chip select net name (SPI flash only)",
        },
        {
            "name": "mosi_net",
            "type": "string",
            "required": False,
            "default": "SPI_MOSI",
            "description": "SPI MOSI net name (SPI flash only)",
        },
        {
            "name": "miso_net",
            "type": "string",
            "required": False,
            "default": "SPI_MISO",
            "description": "SPI MISO net name (SPI flash only)",
        },
        {
            "name": "sclk_net",
            "type": "string",
            "required": False,
            "default": "SPI_SCLK",
            "description": "SPI SCLK net name (SPI flash only)",
        },
        {
            "name": "write_protect",
            "type": "boolean",
            "required": False,
            "default": False,
            "description": "Enable hardware write protection (WP tied high)",
        },
    ]

    @classmethod
    def _ic_db(cls) -> dict[str, dict[str, Any]]:
        """Hardcoded DB merged with ic_data 'eeprom' entries so parts
        registered via ``circuit-weaver register-ic`` are accepted.
        """
        from ..ic_data import merge_into_legacy_db

        return merge_into_legacy_db(EEPROM_IC_DATABASE, "eeprom")

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        ic_name = params.get("ic", "24LC256")
        db = self._ic_db()
        if ic_name not in db:
            errors.append(f"Unknown EEPROM IC '{ic_name}'. Available: {', '.join(db)}")
        addr = params.get("i2c_addr_offset", 0)
        if not isinstance(addr, int) or addr < 0 or addr > 7:
            errors.append(f"i2c_addr_offset must be 0-7, got {addr}")
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        ic_name = params.get("ic", "24LC256")
        db = self._ic_db()
        ic_db = db.get(ic_name, db["24LC256"])

        if ic_db["interface"] == "i2c":
            return self._generate_i2c(ic_name, ic_db, params)
        return self._generate_spi(ic_name, ic_db, params)

    def _generate_i2c(self, ic_name: str, ic_db: dict, params: dict[str, Any]) -> SubcircuitResult:
        ref = params.get("ref", "U")
        vdd_net = params.get("vdd_net", "VDD_3P3")
        sda_net = params.get("sda_net", "I2C_SDA")
        scl_net = params.get("scl_net", "I2C_SCL")
        addr_offset = params.get("i2c_addr_offset", 0)
        write_protect = params.get("write_protect", False)

        power_pins: dict[str, str] = {
            ic_db["pin_vcc"]: vdd_net,
            ic_db["pin_gnd"]: "GND",
        }

        pin_nets: dict[str, str] = {
            ic_db["pin_sda"]: sda_net,
            ic_db["pin_scl"]: scl_net,
        }

        straps: list[StrapConfig] = []

        # Address pin strapping (A0, A1, A2)
        for i, pin_num in enumerate(ic_db["pin_addr"]):
            bit_set = bool(addr_offset & (1 << i))
            rail = vdd_net if bit_set else "GND"
            power_pins[pin_num] = rail

        # WP pin: tie to VDD for write-protect, GND for read/write
        wp_rail = vdd_net if write_protect else "GND"
        power_pins[ic_db["pin_wp"]] = wp_rail

        actual_addr = ic_db["i2c_base_addr"] + addr_offset

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
        ]

        annotations = [
            f"EEPROM {ic_name}: {ic_db['capacity_kbit']}Kbit I2C",
            f"Address: 0x{actual_addr:02X} (offset={addr_offset})",
            f"WP={'enabled' if write_protect else 'disabled'}",
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
            BoundaryPort(vdd_net, "input"),
            BoundaryPort("GND", "passive"),
            BoundaryPort(sda_net, "bidirectional"),
            BoundaryPort(scl_net, "input"),
        ]

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[
                f"EEPROM {ic_name}: {ic_db['capacity_kbit']}Kbit, I2C 0x{actual_addr:02X}",
            ],
            primary_category="digital",
        )

    def _generate_spi(self, ic_name: str, ic_db: dict, params: dict[str, Any]) -> SubcircuitResult:
        ref = params.get("ref", "U")
        vdd_net = params.get("vdd_net", "VDD_3P3")
        cs_net = params.get("cs_net", f"FLASH_CS_{ref}")
        mosi_net = params.get("mosi_net", "SPI_MOSI")
        miso_net = params.get("miso_net", "SPI_MISO")
        sclk_net = params.get("sclk_net", "SPI_SCLK")
        write_protect = params.get("write_protect", False)

        power_pins: dict[str, str] = {
            ic_db["pin_vcc"]: vdd_net,
            ic_db["pin_gnd"]: "GND",
        }

        pin_nets: dict[str, str] = {
            ic_db["pin_cs"]: cs_net,
            ic_db["pin_si"]: mosi_net,
            ic_db["pin_so"]: miso_net,
            ic_db["pin_sck"]: sclk_net,
        }

        straps: list[StrapConfig] = []

        # WP_N: active low — tie to VDD to disable write protection (normal),
        # tie to GND to enable write protection
        wp_rail = "GND" if write_protect else vdd_net
        power_pins[ic_db["pin_wp"]] = wp_rail

        # HOLD_N: active low — tie to VDD to disable hold (normal operation)
        power_pins[ic_db["pin_hold"]] = vdd_net

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
        ]

        cap_mbit = ic_db["capacity_kbit"] // 1024
        annotations = [
            f"Flash {ic_name}: {cap_mbit}Mbit SPI NOR",
            f"WP={'enabled' if write_protect else 'disabled'}, HOLD=disabled",
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
            BoundaryPort(vdd_net, "input"),
            BoundaryPort("GND", "passive"),
            BoundaryPort(cs_net, "input"),
            BoundaryPort(mosi_net, "input"),
            BoundaryPort(miso_net, "output"),
            BoundaryPort(sclk_net, "input"),
        ]

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[
                f"Flash {ic_name}: {cap_mbit}Mbit SPI NOR, CS={cs_net}",
            ],
            primary_category="digital",
        )
