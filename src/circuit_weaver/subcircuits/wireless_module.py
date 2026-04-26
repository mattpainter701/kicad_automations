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

from ..component_db import BypassCap, ComponentDef, StrapConfig
from .base import (
    FP_0402C,
    FP_0402R,
    FP_0805C,
    BoundaryPort,
    LegacyDBProxy,
    SubcircuitResult,
    SubcircuitTemplate,
    format_resistance,
    snap_to_e24,
)

WIRELESS_MODULE_IC_DATABASE = LegacyDBProxy("wireless_module")  # backed by ic_data/*.json (Task 178)


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
                "EN=10k pull-up + 1uF, IO0=10k pull-up (normal boot)",
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
