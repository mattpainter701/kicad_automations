"""USB interface subcircuit templates.

Generates USB controller and hub subcircuits with decoupling,
boot mode straps, and bias/filter components.

USBControllerTemplate: USB controller ICs (FX3, USB-UART bridges)
USBHubTemplate: USB hub ICs (USB2514B)
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
    cap_footprint,
    format_capacitance,
    format_resistance,
)

# ================================================================
# USB Controller IC Database
# ================================================================

USB_CONTROLLER_IC_DATABASE: dict[str, dict] = {}  # Migrated to ic_data/*.json (Task 178)


# ================================================================
# USB Hub IC Database
# ================================================================

USB_HUB_IC_DATABASE = LegacyDBProxy("usb_hub")  # backed by ic_data/*.json (Task 178)


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

    @classmethod
    def _ic_db(cls) -> dict[str, dict[str, Any]]:
        """Hardcoded DB merged with ic_data 'usb_controller' entries so
        parts registered via ``circuit-weaver register-ic`` are accepted
        by :meth:`validate_params` / :meth:`generate`. Legacy hardcoded
        entries win on collision (per :func:`merge_into_legacy_db`).
        """
        from ..ic_data import merge_into_legacy_db

        return merge_into_legacy_db(USB_CONTROLLER_IC_DATABASE, "usb_controller")

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        ic_name = params.get("ic")
        db = self._ic_db()
        if ic_name and ic_name not in db:
            errors.append(f"Unknown USB controller IC '{ic_name}'. Available: {', '.join(db.keys())}")
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
        db = self._ic_db()
        ic_db = db.get(ic_name, db["CYUSB3014"])
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
        # USB D+/D- connections. Prefer explicit pin_usb_dp / pin_usb_dm
        # number fields (what ic_data entries and `circuit-weaver register-ic`
        # produce), then fall back to name matching on D_P/D_N or USB_DP/
        # USB_DM so both hardcoded legacy entries and JSON-sourced entries
        # wire correctly.
        dp_pin = str(ic_db.get("pin_usb_dp", "")).strip()
        dm_pin = str(ic_db.get("pin_usb_dm", "")).strip()
        if dp_pin:
            pin_nets[dp_pin] = usb_dp_net
        if dm_pin:
            pin_nets[dm_pin] = usb_dm_net
        for pin in ic_db["pins"]:
            if pin.number in pin_nets:
                continue
            if pin.name in ("D_P", "USB_DP"):
                pin_nets[pin.number] = usb_dp_net
            elif pin.name in ("D_N", "USB_DM"):
                pin_nets[pin.number] = usb_dm_net

        # Wire all remaining non-power, non-boot-mode signal pins to named nets.
        # These become boundary ports for the user to connect externally.
        _skip_prefixes = ("PMODE",)
        for pin in ic_db["pins"]:
            if pin.number in pin_nets or pin.number in power_pins:
                continue
            if any(pin.name.startswith(p) for p in _skip_prefixes):
                continue
            if pin.electrical_type in ("power_in", "power_out"):
                continue
            if pin.name in ("NC", "~"):
                continue
            pin_nets[pin.number] = f"{pin.name}_{ref}"

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
                        role="bootstrap_strap",
                        presentation="topology_local",
                    )
                )

        # ---- Identify boot-mode pins intentionally left floating ----
        explicit_nc: set[str] = set()
        if boot_config:
            boot_mode_name = "spi_slave"
            boot_pins = boot_config.get(boot_mode_name, {})
            strapped_names = set(boot_pins.keys())
            # Any PMODE pin NOT strapped is intentionally floating (tri-state boot config)
            for pin in ic_db["pins"]:
                if pin.name.startswith("PMODE") and pin.name not in strapped_names:
                    explicit_nc.add(pin.number)

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
            explicit_no_connects=explicit_nc,
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

        # Mark unused input pins (TEST, XTALIN when using internal osc) as explicit NC
        hub_explicit_nc: set[str] = set()
        hub_handled = set(pin_nets) | set(power_pins) | {s.pin for s in straps}
        for pin in ic_db["pins"]:
            if pin.number in hub_handled:
                continue
            if pin.electrical_type in ("output", "power_out", "power_in"):
                continue
            if pin.name in ("NC", "~"):
                continue
            hub_explicit_nc.add(pin.number)

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
            explicit_no_connects=hub_explicit_nc,
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
