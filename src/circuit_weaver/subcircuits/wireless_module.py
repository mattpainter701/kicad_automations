"""Wireless module subcircuit template.

Generates a wireless module subcircuit with antenna matching, decoupling,
boot/enable strapping, and programming header.

Supports ESP32-S3-WROOM-1 (WiFi+BLE, default) and nRF52840 (BLE 5.0)
module topologies.

These are module-based (not bare-die) — the RF front-end and crystal
are integrated. The template handles power decoupling, enable/boot
strapping, and programming interface.
"""

from __future__ import annotations

from typing import Any

from ..component_db import BypassCap, ComponentDef, PinDef, StrapConfig
from .base import (
    FP_0402C,
    FP_0402R,
    FP_0805C,
    BoundaryPort,
    SubcircuitResult,
    SubcircuitTemplate,
    format_resistance,
    snap_to_e24,
)

WIRELESS_MODULE_IC_DATABASE = {
    "ESP32-S3-WROOM-1": {
        "description": "ESP32-S3 WiFi+BLE5 Module with PCB Antenna",
        "footprint": "ESP32-S3-WROOM-1",
        "vdd_range": (3.0, 3.6),
        "typical_vdd": 3.3,
        "peak_current_ma": 500,
        "interfaces": ["uart", "spi", "i2c", "i2s", "usb"],
        "pins": [
            PinDef("1", "GND", "power_in", "B"),
            PinDef("2", "3V3", "power_in", "T"),
            PinDef("3", "EN", "input", "L"),
            PinDef("4", "IO4", "bidirectional", "R"),
            PinDef("5", "IO5", "bidirectional", "R"),
            PinDef("6", "IO6", "bidirectional", "R"),
            PinDef("7", "IO7", "bidirectional", "R"),
            PinDef("8", "IO15", "bidirectional", "R"),
            PinDef("9", "IO16", "bidirectional", "R"),
            PinDef("10", "IO17", "bidirectional", "R"),
            PinDef("11", "IO18", "bidirectional", "R"),
            PinDef("12", "IO8", "bidirectional", "R"),
            PinDef("13", "IO19", "bidirectional", "R"),
            PinDef("14", "IO20", "bidirectional", "R"),
            PinDef("15", "IO3", "bidirectional", "R"),
            PinDef("16", "IO46", "bidirectional", "R"),
            PinDef("17", "IO9", "bidirectional", "R"),
            PinDef("18", "IO10", "bidirectional", "R"),
            PinDef("19", "IO11", "bidirectional", "R"),
            PinDef("20", "IO12", "bidirectional", "R"),
            PinDef("21", "IO13", "bidirectional", "R"),
            PinDef("22", "IO14", "bidirectional", "R"),
            PinDef("23", "IO21", "bidirectional", "R"),
            PinDef("24", "IO47", "bidirectional", "R"),
            PinDef("25", "IO48", "bidirectional", "R"),
            PinDef("26", "IO45", "bidirectional", "R"),
            PinDef("27", "IO0", "bidirectional", "L"),
            PinDef("28", "IO35", "bidirectional", "R"),
            PinDef("29", "IO36", "bidirectional", "R"),
            PinDef("30", "IO37", "bidirectional", "R"),
            PinDef("31", "IO38", "bidirectional", "R"),
            PinDef("32", "IO39", "bidirectional", "R"),
            PinDef("33", "IO40", "bidirectional", "R"),
            PinDef("34", "IO41", "bidirectional", "R"),
            PinDef("35", "IO42", "bidirectional", "R"),
            PinDef("36", "RXD0", "input", "L"),
            PinDef("37", "TXD0", "output", "L"),
            PinDef("38", "IO2", "bidirectional", "R"),
            PinDef("39", "IO1", "bidirectional", "R"),
            PinDef("40", "GND", "power_in", "B"),
            PinDef("41", "EPAD", "power_in", "B"),
        ],
        "pin_vdd": "2",
        "pin_gnd": ["1", "40", "41"],
        "pin_en": "3",
        "pin_boot": "27",  # IO0 = boot mode select
        "pin_txd": "37",
        "pin_rxd": "36",
    },
    "nRF52840-MODULE": {
        "description": "nRF52840 BLE 5.0 Module with PCB Antenna",
        "footprint": "nRF52840_Module",
        "vdd_range": (1.7, 5.5),
        "typical_vdd": 3.3,
        "peak_current_ma": 50,
        "interfaces": ["uart", "spi", "i2c", "usb"],
        "pins": [
            PinDef("1", "SWDIO", "bidirectional", "L"),
            PinDef("2", "SWDCLK", "input", "L"),
            PinDef("3", "GND", "power_in", "B"),
            PinDef("4", "VDD", "power_in", "T"),
            PinDef("5", "P0.02", "bidirectional", "R"),
            PinDef("6", "P0.03", "bidirectional", "R"),
            PinDef("7", "P0.04", "bidirectional", "R"),
            PinDef("8", "P0.05", "bidirectional", "R"),
            PinDef("9", "P0.06", "bidirectional", "R"),
            PinDef("10", "P0.07", "bidirectional", "R"),
            PinDef("11", "P0.08", "bidirectional", "R"),
            PinDef("12", "RESET_N", "input", "L"),
            PinDef("13", "GND", "power_in", "B"),
            PinDef("14", "P0.11", "bidirectional", "R"),
            PinDef("15", "P0.12", "bidirectional", "R"),
        ],
        "pin_vdd": "4",
        "pin_gnd": ["3", "13"],
        "pin_reset": "12",
        "pin_swdio": "1",
        "pin_swdclk": "2",
    },
}


class WirelessModuleTemplate(SubcircuitTemplate):
    """Wireless module with power decoupling, enable/boot strapping."""

    template_type = "wireless_module"
    description = "WiFi/BLE wireless module with decoupling and boot config"
    param_schema = [
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "ESP32-S3-WROOM-1",
            "description": "Wireless module MPN",
        },
        {
            "name": "ref",
            "type": "string",
            "required": False,
            "default": "U",
            "description": "Reference designator for the module",
        },
        {
            "name": "vdd_net",
            "type": "string",
            "required": False,
            "default": "VDD_3P3",
            "description": "Supply rail net name",
        },
        {
            "name": "txd_net",
            "type": "string",
            "required": False,
            "default": "UART_TXD",
            "description": "UART TXD net name (ESP32 only)",
        },
        {
            "name": "rxd_net",
            "type": "string",
            "required": False,
            "default": "UART_RXD",
            "description": "UART RXD net name (ESP32 only)",
        },
    ]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        ic_name = params.get("ic", "ESP32-S3-WROOM-1")
        if ic_name not in WIRELESS_MODULE_IC_DATABASE:
            errors.append(
                f"Unknown wireless module '{ic_name}'. "
                f"Available: {', '.join(WIRELESS_MODULE_IC_DATABASE)}"
            )
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        ic_name = params.get("ic", "ESP32-S3-WROOM-1")
        ic_db = WIRELESS_MODULE_IC_DATABASE.get(
            ic_name, WIRELESS_MODULE_IC_DATABASE["ESP32-S3-WROOM-1"]
        )
        ref = params.get("ref", "U")
        vdd_net = params.get("vdd_net", "VDD_3P3")

        power_pins: dict[str, str] = {ic_db["pin_vdd"]: vdd_net}
        for gnd_pin in ic_db["pin_gnd"]:
            power_pins[gnd_pin] = "GND"

        pin_nets: dict[str, str] = {}
        straps: list[StrapConfig] = []
        explicit_nc: set[str] = set()

        # Bulk + HF decoupling — wireless modules draw high peak current
        bypass_caps: list[BypassCap] = [
            BypassCap(
                "C_VDD_BULK",
                vdd_net,
                "GND",
                "22uF",
                FP_0805C,
                role="bulk_decoupling",
                presentation="topology_local",
            ),
            BypassCap(
                "C_VDD_HF",
                vdd_net,
                "GND",
                "100nF",
                FP_0402C,
                role="decoupling",
                presentation="topology_local",
            ),
        ]

        annotations: list[str] = [f"Wireless module {ic_name}"]
        ports: list[BoundaryPort] = [
            BoundaryPort(vdd_net, "input"),
            BoundaryPort("GND", "passive"),
        ]

        if ic_name == "ESP32-S3-WROOM-1":
            txd_net = params.get("txd_net", "UART_TXD")
            rxd_net = params.get("rxd_net", "UART_RXD")

            pin_nets[ic_db["pin_txd"]] = txd_net
            pin_nets[ic_db["pin_rxd"]] = rxd_net

            # EN pin: 10k pull-up + 1uF cap for power-on reset delay
            en_net = f"EN_{ref}"
            pin_nets[ic_db["pin_en"]] = en_net
            straps.append(
                StrapConfig(
                    "R_EN",
                    en_net,
                    vdd_net,
                    format_resistance(snap_to_e24(10e3)),
                    FP_0402R,
                    role="enable_pullup",
                    presentation="topology_local",
                ),
            )
            bypass_caps.append(
                BypassCap(
                    "C_EN",
                    en_net,
                    "GND",
                    "1uF",
                    FP_0402C,
                    role="reset_delay",
                    presentation="topology_local",
                ),
            )

            # IO0 (boot mode): 10k pull-up for normal boot
            boot_net = f"BOOT_{ref}"
            pin_nets[ic_db["pin_boot"]] = boot_net
            straps.append(
                StrapConfig(
                    "R_BOOT",
                    boot_net,
                    vdd_net,
                    format_resistance(snap_to_e24(10e3)),
                    FP_0402R,
                    role="boot_pullup",
                    presentation="topology_local",
                ),
            )

            # Mark unused signal pins as explicit NC
            handled = set(pin_nets) | set(power_pins)
            for pin in ic_db["pins"]:
                if pin.number in handled:
                    continue
                if pin.electrical_type in ("bidirectional", "input", "output"):
                    explicit_nc.add(pin.number)

            ports.extend([
                BoundaryPort(txd_net, "output"),
                BoundaryPort(rxd_net, "input"),
                BoundaryPort(en_net, "input"),
                BoundaryPort(boot_net, "input"),
            ])

            annotations.extend([
                f"WiFi + BLE 5.0, peak {ic_db['peak_current_ma']}mA",
                f"EN=10k pull-up + 1uF, IO0=10k pull-up (normal boot)",
                f"UART: TXD={txd_net}, RXD={rxd_net}",
            ])

        elif ic_name == "nRF52840-MODULE":
            # RESET_N: 10k pull-up
            rst_net = f"nRF_RST_{ref}"
            pin_nets[ic_db["pin_reset"]] = rst_net
            straps.append(
                StrapConfig(
                    "R_RST",
                    rst_net,
                    vdd_net,
                    format_resistance(snap_to_e24(10e3)),
                    FP_0402R,
                    role="reset_pullup",
                    presentation="topology_local",
                ),
            )

            # SWD debug port
            swdio_net = f"SWDIO_{ref}"
            swdclk_net = f"SWDCLK_{ref}"
            pin_nets[ic_db["pin_swdio"]] = swdio_net
            pin_nets[ic_db["pin_swdclk"]] = swdclk_net

            # Mark unused signal pins as explicit NC
            handled = set(pin_nets) | set(power_pins)
            for pin in ic_db["pins"]:
                if pin.number in handled:
                    continue
                if pin.electrical_type in ("bidirectional", "input", "output"):
                    explicit_nc.add(pin.number)

            ports.extend([
                BoundaryPort(rst_net, "input"),
                BoundaryPort(swdio_net, "bidirectional"),
                BoundaryPort(swdclk_net, "input"),
            ])

            annotations.extend([
                f"BLE 5.0, peak {ic_db['peak_current_ma']}mA",
                f"SWD: SWDIO={swdio_net}, SWDCLK={swdclk_net}",
            ])

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
            explicit_no_connects=explicit_nc,
        )
        ic_comp.source_ref = ref

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[f"Wireless {ic_name}: {vdd_net}"],
            primary_category="digital",
        )
