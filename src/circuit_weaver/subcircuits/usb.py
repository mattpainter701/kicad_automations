"""USB interface subcircuit templates.

Generates USB controller and hub subcircuits with decoupling,
boot mode straps, and bias/filter components.

USBControllerTemplate: USB controller ICs (FX3, USB-UART bridges)
USBHubTemplate: USB hub ICs (USB2514B)
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
    cap_footprint,
    format_capacitance,
    format_resistance,
)

# ================================================================
# USB Controller IC Database
# ================================================================

USB_CONTROLLER_IC_DATABASE = {
    "CYUSB3014": {
        "description": "USB 3.0 SuperSpeed Controller (FX3) 121-BGA",
        "footprint": "BGA-121",
        "power_rails": {
            "VDD": 1.2,  # core supply
            "VBUS": 5.0,  # USB bus power
            "DVDDIO": 1.8,  # digital I/O supply
            "AVDD": 1.2,  # analog supply
        },
        "pins": [
            # Power
            PinDef("A1", "VDD", "power_in", "L"),
            PinDef("A2", "DVDDIO", "power_in", "L"),
            PinDef("A11", "GND", "power_in", "B"),
            PinDef("B1", "AVDD", "power_in", "L"),
            PinDef("B11", "VBUS", "power_in", "L"),
            # USB 3.0 SS
            PinDef("K1", "SSRX_P", "input", "R"),
            PinDef("K2", "SSRX_N", "input", "R"),
            PinDef("K3", "SSTX_P", "output", "R"),
            PinDef("K4", "SSTX_N", "output", "R"),
            # USB 2.0
            PinDef("J1", "D_P", "bidirectional", "R"),
            PinDef("J2", "D_N", "bidirectional", "R"),
            # GPIF II bus (directly exposed as data bus)
            PinDef("C1", "GPIF_D0", "bidirectional", "T"),
            PinDef("C2", "GPIF_D1", "bidirectional", "T"),
            PinDef("C3", "GPIF_CLK", "output", "T"),
            PinDef("C4", "GPIF_CTL0", "output", "T"),
            # Boot mode pins
            PinDef("H1", "PMODE0", "input", "L"),
            PinDef("H2", "PMODE1", "input", "L"),
            PinDef("H3", "PMODE2", "input", "L"),
            # SPI
            PinDef("G1", "SPI_CLK", "output", "R"),
            PinDef("G2", "SPI_SSN", "output", "R"),
            PinDef("G3", "SPI_MISO", "input", "R"),
            PinDef("G4", "SPI_MOSI", "output", "R"),
            # Reset
            PinDef("F1", "RESET_N", "input", "L"),
            # Clock
            PinDef("E1", "XTALIN", "input", "L"),
            PinDef("E2", "XTALOUT", "output", "L"),
        ],
        "pin_vdd": ["A1"],
        "pin_power_rails": {
            "VDD": ["A1"],
            "DVDDIO": ["A2"],
            "AVDD": ["B1"],
            "VBUS": ["B11"],
        },
        "pin_gnd": ["A11"],
        "boot_straps": {
            # SPI slave boot: PMODE[2:0] = 1,0,Z (VDD, GND, float)
            "spi_slave": {
                "PMODE2": ("VDD", "pull_up"),  # 10k to VDD
                "PMODE1": ("GND", "pull_down"),  # 10k to GND
                # PMODE0 left floating (no strap)
            },
        },
        "data_buses": ["GPIF", "SPI"],
    },
    "CH340G": {
        "description": "USB-UART Bridge SOP-16",
        "footprint": "SOP-16",
        "power_rails": {
            "VCC": 3.3,  # supply
        },
        "pins": [
            PinDef("1", "GND", "power_in", "B"),
            PinDef("2", "TXD", "output", "R"),
            PinDef("3", "RXD", "input", "R"),
            PinDef("4", "V3", "power_out", "R"),
            PinDef("5", "D_P", "bidirectional", "L"),
            PinDef("6", "D_N", "bidirectional", "L"),
            PinDef("7", "XI", "input", "L"),
            PinDef("8", "XO", "output", "L"),
            PinDef("9", "CTS_N", "input", "R"),
            PinDef("10", "DSR_N", "input", "R"),
            PinDef("11", "RI_N", "input", "R"),
            PinDef("12", "DCD_N", "input", "R"),
            PinDef("13", "DTR_N", "output", "R"),
            PinDef("14", "RTS_N", "output", "R"),
            PinDef("15", "R232", "input", "L"),
            PinDef("16", "VCC", "power_in", "L"),
        ],
        "pin_vdd": ["16"],
        "pin_gnd": ["1"],
        "boot_straps": {},
        "data_buses": ["UART"],
    },
}


# ================================================================
# USB Hub IC Database
# ================================================================

USB_HUB_IC_DATABASE = {
    "USB2514B": {
        "description": "4-Port USB 2.0 Hub Controller QFN-36",
        "footprint": "QFN-36",
        "power_rails": {
            "VDD33": 3.3,  # 3.3V core + I/O
        },
        "pins": [
            # Power
            PinDef("1", "VDD33", "power_in", "L"),
            PinDef("36", "GND", "power_in", "B"),
            # Upstream port
            PinDef("2", "USBDM0", "bidirectional", "L"),
            PinDef("3", "USBDP0", "bidirectional", "L"),
            # Downstream port 1
            PinDef("4", "USBDM1", "bidirectional", "R"),
            PinDef("5", "USBDP1", "bidirectional", "R"),
            # Downstream port 2
            PinDef("6", "USBDM2", "bidirectional", "R"),
            PinDef("7", "USBDP2", "bidirectional", "R"),
            # Downstream port 3
            PinDef("8", "USBDM3", "bidirectional", "R"),
            PinDef("9", "USBDP3", "bidirectional", "R"),
            # Downstream port 4
            PinDef("10", "USBDM4", "bidirectional", "R"),
            PinDef("11", "USBDP4", "bidirectional", "R"),
            # Bias and PLL
            PinDef("12", "RBIAS", "passive", "B"),
            PinDef("13", "PLLFILT", "passive", "B"),
            # Reset
            PinDef("14", "RESET_N", "input", "L"),
            # Config
            PinDef("15", "TEST", "input", "B"),
            PinDef("16", "XTALIN", "input", "L"),
            PinDef("17", "XTALOUT", "output", "L"),
        ],
        "pin_vdd": ["1"],
        "pin_gnd": ["36"],
        "rbias_value": 12e3,  # 12k to GND (datasheet requirement)
        "pllfilt_value": 1e-6,  # 1uF PLL filter cap to GND
        "max_ports": 4,
    },
}


class USBControllerTemplate(SubcircuitTemplate):
    """USB controller IC with decoupling and boot mode straps."""

    template_type = "usb_controller"
    description = "USB controller with decoupling, boot straps, and data bus"
    param_schema = [
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "CYUSB3014",
            "description": "USB controller IC MPN",
        },
        {
            "name": "ref",
            "type": "string",
            "required": False,
            "default": "U",
            "description": "Reference designator for the controller",
        },
        {
            "name": "mode",
            "type": "string",
            "required": False,
            "default": "device",
            "description": "USB operating mode",
            "options": ["device", "host"],
        },
        {
            "name": "data_bus",
            "type": "string",
            "required": False,
            "description": "Data bus type such as GPIF or UART",
        },
        {
            "name": "vdd_net",
            "type": "string",
            "required": False,
            "description": "Primary controller supply net name",
        },
        {
            "name": "usb_dp_net",
            "type": "string",
            "required": False,
            "description": "USB D+ net name",
        },
        {
            "name": "usb_dm_net",
            "type": "string",
            "required": False,
            "description": "USB D- net name",
        },
    ]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        ic_name = params.get("ic")
        if ic_name and ic_name not in USB_CONTROLLER_IC_DATABASE:
            errors.append(
                f"Unknown USB controller IC '{ic_name}'. Available: {', '.join(USB_CONTROLLER_IC_DATABASE.keys())}"
            )
        mode = params.get("mode", "device")
        if mode not in ("device", "host"):
            errors.append(f"Invalid mode '{mode}'. Must be 'device' or 'host'.")
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        """Generate a USB controller subcircuit.

        Required params: (none — defaults to CYUSB3014 in device mode)

        Optional params:
            ic: str — IC MPN (default: "CYUSB3014")
            ref: str — reference designator for IC (default: "U")
            mode: str — "device" or "host" (default: "device")
            data_bus: str — data bus type, e.g. "GPIF" or "UART" (default: first in IC's list)
            vdd_net: str — VDD power net name (default: derived from IC rails)
            usb_dp_net: str — USB D+ net (default: "USB_DP_{ref}")
            usb_dm_net: str — USB D- net (default: "USB_DM_{ref}")
        """
        ic_name = params.get("ic", "CYUSB3014")
        ic_db = USB_CONTROLLER_IC_DATABASE.get(ic_name, USB_CONTROLLER_IC_DATABASE["CYUSB3014"])
        ref = params.get("ref", "U")
        mode = params.get("mode", "device")
        data_bus = params.get("data_bus")
        if data_bus is None:
            data_bus = ic_db["data_buses"][0] if ic_db["data_buses"] else "GPIF"

        # ---- Net names (unique per instance) ----
        usb_dp_net = params.get("usb_dp_net", f"USB_DP_{ref}")
        usb_dm_net = params.get("usb_dm_net", f"USB_DM_{ref}")

        # ---- Power net assignments ----
        # Use the first power rail as the primary VDD
        primary_rail = list(ic_db["power_rails"].keys())[0]
        vdd_net = params.get("vdd_net", primary_rail)
        power_rail_nets = {
            rail_name: params.get(
                f"{rail_name.lower()}_net",
                vdd_net if rail_name == primary_rail else rail_name,
            )
            for rail_name in ic_db["power_rails"]
        }

        power_pins = {}
        for rail_name, pin_numbers in ic_db.get("pin_power_rails", {primary_rail: ic_db["pin_vdd"]}).items():
            rail_net = power_rail_nets.get(rail_name, vdd_net)
            for pin_num in pin_numbers:
                power_pins[pin_num] = rail_net
        for pin_num in ic_db["pin_gnd"]:
            power_pins[pin_num] = "GND"

        # ---- Signal pin assignments ----
        pin_nets = {}
        # USB D+/D- connections
        for pin in ic_db["pins"]:
            if pin.name == "D_P":
                pin_nets[pin.number] = usb_dp_net
            elif pin.name == "D_N":
                pin_nets[pin.number] = usb_dm_net

        # ---- Bypass caps: 100nF + 10uF per rail ----
        bypass_caps = []
        for rail_name, voltage in ic_db["power_rails"].items():
            rail_net = power_rail_nets[rail_name]
            # 100nF high-frequency decoupling
            bypass_caps.append(
                BypassCap(
                    f"C_HF_{rail_name}",
                    rail_net,
                    "GND",
                    format_capacitance(100e-9),
                    FP_0402C,
                    presentation="topology_local",
                )
            )
            # 10uF bulk decoupling
            bypass_caps.append(
                BypassCap(
                    f"C_BULK_{rail_name}",
                    rail_net,
                    "GND",
                    format_capacitance(10e-6),
                    FP_0805C,
                    presentation="topology_local",
                )
            )

        # ---- Boot mode straps ----
        straps = []
        boot_config = ic_db.get("boot_straps", {})
        if boot_config:
            # Default to SPI slave boot for CYUSB3014
            boot_mode_name = "spi_slave"
            boot_pins = boot_config.get(boot_mode_name, {})
            for pin_name, (rail, strap_type) in boot_pins.items():
                # Find the actual pin number for this pin name
                pin_number = None
                for pin in ic_db["pins"]:
                    if pin.name == pin_name:
                        pin_number = pin.number
                        break
                if pin_number is None:
                    continue

                strap_rail = "GND" if rail == "GND" else power_rail_nets.get(rail, rail)
                straps.append(
                    StrapConfig(
                        pin_number,
                        f"{pin_name}_{ref}",
                        strap_rail,
                        format_resistance(10e3),
                        FP_0402R,
                        role="boot_strap",
                        presentation="topology_local",
                    )
                )

        # ---- Annotations ----
        boot_desc = "SPI slave boot (PMODE[2:0]=1,0,Z)" if boot_config else "default boot"
        annotations = [
            f"USB {mode} controller: {ic_name}",
            f"Bus: {data_bus}, Boot: {boot_desc}",
        ]
        for rail_name, voltage in ic_db["power_rails"].items():
            annotations.append(f"Decoupling {rail_name}: 100nF + 10uF ({voltage}V)")

        # ---- Build ComponentDef ----
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

        # ---- Boundary ports ----
        ports = [
            BoundaryPort(power_rail_nets[primary_rail], "input"),
            BoundaryPort("GND", "passive"),
        ]
        for rail_name, rail_net in power_rail_nets.items():
            if rail_name == primary_rail or rail_net == "GND":
                continue
            ports.append(BoundaryPort(rail_net, "input"))
        ports.extend(
            [
                BoundaryPort(usb_dp_net, "bidirectional"),
                BoundaryPort(usb_dm_net, "bidirectional"),
            ]
        )

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[
                f"USB Controller {ic_name}: {mode} mode, {data_bus} bus, {boot_desc}",
            ],
            primary_category="digital",
        )


class USBHubTemplate(SubcircuitTemplate):
    """USB hub IC with decoupling, RBIAS, PLL filter, and reset pull-up."""

    template_type = "usb_hub"
    description = "USB hub with bias resistor, PLL filter, and port configuration"
    param_schema = [
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "USB2514B",
            "description": "USB hub IC MPN",
        },
        {
            "name": "ref",
            "type": "string",
            "required": False,
            "default": "U",
            "description": "Reference designator for the hub",
        },
        {
            "name": "ports",
            "type": "integer",
            "required": False,
            "default": 4,
            "description": "Number of downstream ports",
        },
        {
            "name": "vdd_net",
            "type": "string",
            "required": False,
            "description": "Primary hub supply net name",
        },
    ]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        ic_name = params.get("ic")
        if ic_name and ic_name not in USB_HUB_IC_DATABASE:
            errors.append(f"Unknown USB hub IC '{ic_name}'. Available: {', '.join(USB_HUB_IC_DATABASE.keys())}")
        ports = params.get("ports", 4)
        if not isinstance(ports, int) or ports < 1:
            errors.append(f"Invalid port count '{ports}'. Must be a positive integer.")
        ic_db = USB_HUB_IC_DATABASE.get(ic_name or "USB2514B")
        if ic_db and ports > ic_db.get("max_ports", 4):
            errors.append(f"Port count {ports} exceeds max {ic_db['max_ports']} for {ic_name or 'USB2514B'}")
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        """Generate a USB hub subcircuit.

        Optional params:
            ic: str — IC MPN (default: "USB2514B")
            ref: str — reference designator for IC (default: "U")
            ports: int — number of downstream ports (default: 4)
            vdd_net: str — VDD power net name (default: "VDD33")
        """
        ic_name = params.get("ic", "USB2514B")
        ic_db = USB_HUB_IC_DATABASE.get(ic_name, USB_HUB_IC_DATABASE["USB2514B"])
        ref = params.get("ref", "U")
        ports = params.get("ports", 4)
        primary_rail = list(ic_db["power_rails"].keys())[0]
        vdd_net = params.get("vdd_net", primary_rail)

        # ---- Power pins ----
        power_pins = {}
        for pin_num in ic_db["pin_vdd"]:
            power_pins[pin_num] = vdd_net
        for pin_num in ic_db["pin_gnd"]:
            power_pins[pin_num] = "GND"

        # ---- Signal pins ----
        pin_nets = {}
        # Upstream port
        pin_nets["2"] = f"HUB_DM_{ref}"
        pin_nets["3"] = f"HUB_DP_{ref}"

        # ---- Bypass caps: 100nF + 10uF per rail ----
        bypass_caps = []
        for rail_name, voltage in ic_db["power_rails"].items():
            rail_net = vdd_net if rail_name == primary_rail else rail_name
            bypass_caps.append(
                BypassCap(
                    f"C_HF_{rail_name}",
                    rail_net,
                    "GND",
                    format_capacitance(100e-9),
                    FP_0402C,
                    presentation="topology_local",
                )
            )
            bypass_caps.append(
                BypassCap(
                    f"C_BULK_{rail_name}",
                    rail_net,
                    "GND",
                    format_capacitance(10e-6),
                    FP_0805C,
                    presentation="topology_local",
                )
            )

        # ---- RBIAS: 12k to GND ----
        rbias_value = ic_db.get("rbias_value", 12e3)
        rbias_net = f"RBIAS_{ref}"
        pin_nets["12"] = rbias_net
        straps = [
            StrapConfig(
                "12",
                rbias_net,
                "GND",
                format_resistance(rbias_value),
                FP_0402R,
                role="bias",
                presentation="topology_local",
            ),
        ]

        # ---- PLLFILT: 1uF to GND ----
        pllfilt_value = ic_db.get("pllfilt_value", 1e-6)
        pllfilt_net = f"PLLFILT_{ref}"
        pin_nets["13"] = pllfilt_net
        bypass_caps.append(
            BypassCap(
                "C_PLLFILT",
                pllfilt_net,
                "GND",
                format_capacitance(pllfilt_value),
                cap_footprint(pllfilt_value),
                role="pll_filter",
                presentation="topology_local",
            )
        )

        # ---- Reset: 10k pull-up to VDD ----
        reset_net = f"RESET_N_{ref}"
        pin_nets["14"] = reset_net
        straps.append(
            StrapConfig(
                "14",
                reset_net,
                vdd_net,
                format_resistance(10e3),
                FP_0402R,
                role="pull_up",
                presentation="topology_local",
            )
        )

        # ---- Annotations ----
        annotations = [
            f"USB 2.0 Hub: {ic_name}, {ports} downstream ports",
            f"RBIAS: {format_resistance(rbias_value)} to GND (required)",
            f"PLLFILT: {format_capacitance(pllfilt_value)} to GND",
            f"RESET_N: {format_resistance(10e3)} pull-up to {vdd_net}",
        ]

        # ---- Build ComponentDef ----
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

        # ---- Boundary ports ----
        ports_list = [
            BoundaryPort(vdd_net, "input"),
            BoundaryPort("GND", "passive"),
            BoundaryPort(f"HUB_DP_{ref}", "bidirectional"),
            BoundaryPort(f"HUB_DM_{ref}", "bidirectional"),
        ]
        # Add downstream port boundary labels
        for i in range(1, ports + 1):
            # Find the DM/DP pins for this port
            dm_net = f"USB_DM{i}_{ref}"
            dp_net = f"USB_DP{i}_{ref}"
            # Map downstream pins by port index
            dm_pin = str(4 + (i - 1) * 2)  # pins 4,6,8,10
            dp_pin = str(4 + (i - 1) * 2 + 1)  # pins 5,7,9,11
            pin_nets[dm_pin] = dm_net
            pin_nets[dp_pin] = dp_net
            ports_list.append(BoundaryPort(dp_net, "bidirectional"))
            ports_list.append(BoundaryPort(dm_net, "bidirectional"))

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports_list,
            annotations=[
                f"USB Hub {ic_name}: {ports}-port hub, RBIAS={format_resistance(rbias_value)}, "
                f"PLLFILT={format_capacitance(pllfilt_value)}",
            ],
            primary_category="digital",
        )
