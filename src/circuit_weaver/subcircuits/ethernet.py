"""Ethernet PHY subcircuit template.

Generates a complete Gigabit Ethernet PHY subcircuit with RGMII/RMII/MII
interface, decoupling caps, crystal load caps, ISET bias resistor,
mode strap resistors, and reset pull-up.

Supports KSZ9031 (Microchip, QFN-48) and DP83867 (TI, QFP-48).
"""

from __future__ import annotations

from typing import Any

from ..component_db import BypassCap, ComponentDef, PinDef, StrapConfig
from .base import (
    FP_0402R,
    BoundaryPort,
    SubcircuitResult,
    SubcircuitTemplate,
    cap_footprint,
    crystal_load_caps,
    format_capacitance,
    format_resistance,
    snap_cap,
)

# Known Ethernet PHY ICs and their parameters
ETHERNET_PHY_IC_DATABASE = {
    "KSZ9031": {
        "description": "GigE Ethernet PHY RGMII QFN-48",
        "footprint": "QFN-48-EP_7x7mm_P0.5mm",
        "interface_modes": ["rgmii", "rmii", "mii"],
        "default_mode": "rgmii",
        "crystal_cl": 9e-12,  # 9 pF load capacitance (25 MHz crystal)
        "iset_r": 12.1e3,  # 12.1k bias resistor (datasheet recommended)
        "has_internal_ldo": True,  # internal 1.2V LDO, needs bypass
        "ldo_bypass_cap": 1e-6,  # 1uF bypass for internal 1.2V LDO
        "pins": [
            # Power pins
            PinDef("1", "DVDDH", "power_in", "T"),
            PinDef("2", "DVDDL", "power_in", "T"),
            PinDef("3", "AVDDH", "power_in", "T"),
            PinDef("4", "AVDDL", "power_in", "T"),
            PinDef("5", "GND", "power_in", "B"),
            PinDef("49", "EPAD", "power_in", "B"),
            # RGMII MAC-side interface
            PinDef("6", "TXD0", "input", "L"),
            PinDef("7", "TXD1", "input", "L"),
            PinDef("8", "TXD2", "input", "L"),
            PinDef("9", "TXD3", "input", "L"),
            PinDef("10", "TXCTL", "input", "L"),
            PinDef("11", "TXC", "input", "L"),
            PinDef("12", "RXD0", "output", "L"),
            PinDef("13", "RXD1", "output", "L"),
            PinDef("14", "RXD2", "output", "L"),
            PinDef("15", "RXD3", "output", "L"),
            PinDef("16", "RXCTL", "output", "L"),
            PinDef("17", "RXC", "output", "L"),
            # MDC/MDIO management
            PinDef("18", "MDC", "input", "L"),
            PinDef("19", "MDIO", "bidirectional", "L"),
            # PHY-side (RJ45)
            PinDef("20", "TXP_A", "output", "R"),
            PinDef("21", "TXN_A", "output", "R"),
            PinDef("22", "RXP_B", "input", "R"),
            PinDef("23", "RXN_B", "input", "R"),
            PinDef("24", "TXP_C", "output", "R"),
            PinDef("25", "TXN_C", "output", "R"),
            PinDef("26", "RXP_D", "input", "R"),
            PinDef("27", "RXN_D", "input", "R"),
            # Crystal
            PinDef("28", "XO", "output", "R"),
            PinDef("29", "XI", "input", "R"),
            # Control
            PinDef("30", "ISET", "passive", "R"),
            PinDef("31", "RESET_N", "input", "L"),
            PinDef("32", "INT_N", "output", "L"),
            # Mode strap pins (active during reset)
            PinDef("33", "RXD0_MODE0", "bidirectional", "L"),
            PinDef("34", "RXD1_MODE1", "bidirectional", "L"),
            PinDef("35", "RXD2_MODE2", "bidirectional", "L"),
            PinDef("36", "RXD3_MODE3", "bidirectional", "L"),
            PinDef("37", "RXCTL_CLK", "bidirectional", "L"),
            # Internal LDO output
            PinDef("38", "VDDOL", "power_out", "T"),
            # LED outputs
            PinDef("39", "LED0", "output", "R"),
            PinDef("40", "LED1", "output", "R"),
            PinDef("41", "LED2", "output", "R"),
        ],
        "pin_dvddh": "1",
        "pin_dvddl": "2",
        "pin_avddh": "3",
        "pin_avddl": "4",
        "pin_gnd": "5",
        "pin_epad": "49",
        "pin_iset": "30",
        "pin_reset": "31",
        "pin_int": "32",
        "pin_xo": "28",
        "pin_xi": "29",
        "pin_vddol": "38",
        # RGMII mode straps: RXD0-3 to GND, RXCTL to VDD = RGMII mode
        "mode_straps": {
            "rgmii": [
                {"pin": "33", "net_suffix": "RXD0", "rail": "GND"},
                {"pin": "34", "net_suffix": "RXD1", "rail": "GND"},
                {"pin": "35", "net_suffix": "RXD2", "rail": "GND"},
                {"pin": "36", "net_suffix": "RXD3", "rail": "GND"},
                {"pin": "37", "net_suffix": "RXCTL", "rail": "VDD"},
            ],
        },
        "decoupling": {
            "DVDDH": [100e-9, 10e-6],  # 100nF + 10uF
            "AVDDH": [100e-9],  # 100nF
        },
    },
    "DP83867": {
        "description": "GigE Ethernet PHY RGMII QFP-48",
        "footprint": "QFP-48_7x7mm_P0.5mm",
        "interface_modes": ["rgmii", "rmii", "mii"],
        "default_mode": "rgmii",
        "crystal_cl": 9e-12,  # 9 pF
        "iset_r": None,  # DP83867 has no external ISET
        "has_internal_ldo": False,
        "ldo_bypass_cap": None,
        "pins": [
            # Power pins
            PinDef("1", "DVDD_3P3", "power_in", "T"),
            PinDef("2", "DVDD_1P8", "power_in", "T"),
            PinDef("3", "AVDD_3P3", "power_in", "T"),
            PinDef("4", "AVDD_1P8", "power_in", "T"),
            PinDef("5", "GND", "power_in", "B"),
            PinDef("49", "EPAD", "power_in", "B"),
            # RGMII MAC-side
            PinDef("6", "TXD0", "input", "L"),
            PinDef("7", "TXD1", "input", "L"),
            PinDef("8", "TXD2", "input", "L"),
            PinDef("9", "TXD3", "input", "L"),
            PinDef("10", "TX_CTL", "input", "L"),
            PinDef("11", "TX_CLK", "input", "L"),
            PinDef("12", "RXD0", "output", "L"),
            PinDef("13", "RXD1", "output", "L"),
            PinDef("14", "RXD2", "output", "L"),
            PinDef("15", "RXD3", "output", "L"),
            PinDef("16", "RX_CTL", "output", "L"),
            PinDef("17", "RX_CLK", "output", "L"),
            # MDC/MDIO
            PinDef("18", "MDC", "input", "L"),
            PinDef("19", "MDIO", "bidirectional", "L"),
            # PHY-side
            PinDef("20", "TDP_A", "output", "R"),
            PinDef("21", "TDN_A", "output", "R"),
            PinDef("22", "RDP_B", "input", "R"),
            PinDef("23", "RDN_B", "input", "R"),
            PinDef("24", "TDP_C", "output", "R"),
            PinDef("25", "TDN_C", "output", "R"),
            PinDef("26", "RDP_D", "input", "R"),
            PinDef("27", "RDN_D", "input", "R"),
            # Crystal
            PinDef("28", "XI", "input", "R"),
            PinDef("29", "XO", "output", "R"),
            # Control
            PinDef("30", "RESET_N", "input", "L"),
            PinDef("31", "INT_N", "output", "L"),
            # Mode strap pins
            PinDef("32", "RXD0_STRAP0", "bidirectional", "L"),
            PinDef("33", "RXD1_STRAP1", "bidirectional", "L"),
            PinDef("34", "RXD2_STRAP2", "bidirectional", "L"),
            PinDef("35", "RXD3_STRAP3", "bidirectional", "L"),
            PinDef("36", "RX_CTL_STRAP4", "bidirectional", "L"),
            # LED outputs
            PinDef("37", "LED_0", "output", "R"),
            PinDef("38", "LED_1", "output", "R"),
            PinDef("39", "LED_2", "output", "R"),
        ],
        "pin_dvddh": "1",
        "pin_dvddl": "2",
        "pin_avddh": "3",
        "pin_avddl": "4",
        "pin_gnd": "5",
        "pin_epad": "49",
        "pin_iset": None,
        "pin_reset": "30",
        "pin_int": "31",
        "pin_xi": "28",
        "pin_xo": "29",
        "pin_vddol": None,
        "mode_straps": {
            "rgmii": [
                {"pin": "32", "net_suffix": "RXD0", "rail": "GND"},
                {"pin": "33", "net_suffix": "RXD1", "rail": "GND"},
                {"pin": "34", "net_suffix": "RXD2", "rail": "GND"},
                {"pin": "35", "net_suffix": "RXD3", "rail": "GND"},
                {"pin": "36", "net_suffix": "RX_CTL", "rail": "VDD"},
            ],
        },
        "decoupling": {
            "DVDD_3P3": [100e-9, 10e-6],  # 100nF + 10uF
            "AVDD_3P3": [100e-9],  # 100nF
        },
    },
}


class EthernetPHYTemplate(SubcircuitTemplate):
    """Gigabit Ethernet PHY with decoupling, crystal, bias, mode straps."""

    template_type = "ethernet_phy"
    description = "Gigabit Ethernet PHY with RGMII/RMII/MII interface"
    param_schema = [
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "KSZ9031",
            "description": "Ethernet PHY IC MPN",
        },
        {
            "name": "ref",
            "type": "string",
            "required": False,
            "default": "U",
            "description": "Reference designator for the PHY",
        },
        {
            "name": "mode",
            "type": "string",
            "required": False,
            "default": "rgmii",
            "description": "MAC interface mode",
            "options": ["rgmii", "rmii", "mii"],
        },
        {
            "name": "crystal_cl",
            "type": "number",
            "required": False,
            "default": 9e-12,
            "description": "Crystal load capacitance in farads",
        },
        {
            "name": "vdd_net",
            "type": "string",
            "required": False,
            "default": "VDD_3P3",
            "description": "Digital supply net",
        },
        {
            "name": "gnd_net",
            "type": "string",
            "required": False,
            "default": "GND",
            "description": "Ground net",
        },
        {
            "name": "reset_net",
            "type": "string",
            "required": False,
            "default": "ETH_RESET_N",
            "description": "Reset net name",
        },
        {
            "name": "mdio_net",
            "type": "string",
            "required": False,
            "default": "MDIO",
            "description": "MDIO management bus net",
        },
        {
            "name": "mdc_net",
            "type": "string",
            "required": False,
            "default": "MDC",
            "description": "MDC management clock net",
        },
    ]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        ic_name = params.get("ic", "KSZ9031")
        if ic_name not in ETHERNET_PHY_IC_DATABASE:
            errors.append(
                f"Unknown Ethernet PHY IC '{ic_name}'. "
                f"Supported: {', '.join(ETHERNET_PHY_IC_DATABASE)}"
            )
            return errors

        mode = params.get("mode", "rgmii")
        ic_db = ETHERNET_PHY_IC_DATABASE[ic_name]
        if mode not in ic_db["interface_modes"]:
            errors.append(
                f"Mode '{mode}' not supported by {ic_name}. "
                f"Supported: {', '.join(ic_db['interface_modes'])}"
            )
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        """Generate an Ethernet PHY subcircuit.

        Required params: (none — all have defaults)

        Optional params:
            ic: str — IC MPN (default: "KSZ9031")
            ref: str — reference designator prefix (default: "U")
            mode: str — interface mode: "rgmii", "rmii", "mii" (default: "rgmii")
            crystal_cl: float — crystal load capacitance in F (default: 9e-12)
            vdd_net: str — digital supply net (default: "VDD_3P3")
            gnd_net: str — ground net (default: "GND")
            reset_net: str — reset net (default: "ETH_RESET_N")
            mdio_net: str — MDIO bus net (default: "MDIO")
            mdc_net: str — MDC clock net (default: "MDC")
        """
        ic_name = params.get("ic", "KSZ9031")
        ic_db = ETHERNET_PHY_IC_DATABASE.get(ic_name, ETHERNET_PHY_IC_DATABASE["KSZ9031"])
        ref = params.get("ref", "U")
        mode = params.get("mode", ic_db["default_mode"])
        crystal_cl = params.get("crystal_cl", ic_db["crystal_cl"])
        vdd_net = params.get("vdd_net", "VDD_3P3")
        gnd_net = params.get("gnd_net", "GND")
        reset_net = params.get("reset_net", "ETH_RESET_N")
        mdio_net = params.get("mdio_net", "MDIO")
        mdc_net = params.get("mdc_net", "MDC")

        # ---- Crystal load cap calculation ----
        cl_ext_raw = crystal_load_caps(crystal_cl)
        cl_ext = snap_cap(cl_ext_raw)

        # ---- Net names (unique per instance) ----
        xi_net = f"ETH_XI_{ref}"
        xo_net = f"ETH_XO_{ref}"
        iset_net = f"ETH_ISET_{ref}"
        int_net = f"ETH_INT_N_{ref}"

        # ---- Power pins ----
        power_pins = {
            ic_db["pin_dvddh"]: vdd_net,
            ic_db["pin_gnd"]: gnd_net,
            ic_db["pin_epad"]: gnd_net,
        }
        # Digital low-voltage rail — internal LDO output or external
        if ic_db["has_internal_ldo"] and ic_db.get("pin_vddol"):
            ldo_bypass_net = f"VDDOL_{ref}"
            power_pins[ic_db["pin_dvddl"]] = ldo_bypass_net
            power_pins[ic_db["pin_vddol"]] = ldo_bypass_net
            power_pins[ic_db["pin_avddl"]] = ldo_bypass_net
        else:
            power_pins[ic_db["pin_dvddl"]] = vdd_net
            power_pins[ic_db["pin_avddl"]] = vdd_net

        power_pins[ic_db["pin_avddh"]] = vdd_net

        # ---- Signal pin nets ----
        pin_nets = {
            ic_db["pin_reset"]: reset_net,
            ic_db["pin_int"]: int_net,
        }

        # Crystal pins
        pin_xi = ic_db["pin_xi"]
        pin_xo = ic_db["pin_xo"]
        pin_nets[pin_xi] = xi_net
        pin_nets[pin_xo] = xo_net

        # ISET bias pin
        if ic_db.get("pin_iset"):
            pin_nets[ic_db["pin_iset"]] = iset_net

        # MDIO/MDC
        pin_nets["18"] = mdc_net
        pin_nets["19"] = mdio_net

        # ---- Bypass capacitors ----
        bypass_caps = []
        for rail_label, cap_values in ic_db["decoupling"].items():
            # Determine the actual net for this rail label
            if "DVDDH" in rail_label or "DVDD_3P3" in rail_label:
                rail_net = vdd_net
            elif "AVDDH" in rail_label or "AVDD_3P3" in rail_label:
                rail_net = vdd_net
            else:
                rail_net = vdd_net

            for i, cv in enumerate(cap_values):
                label = f"C_{rail_label}_{i}"
                bypass_caps.append(
                    BypassCap(label, rail_net, gnd_net, format_capacitance(cv), cap_footprint(cv))
                )

        # Internal LDO bypass cap
        if ic_db["has_internal_ldo"] and ic_db.get("ldo_bypass_cap"):
            ldo_cv = ic_db["ldo_bypass_cap"]
            ldo_net = f"VDDOL_{ref}"
            bypass_caps.append(
                BypassCap(
                    "C_LDO", ldo_net, gnd_net, format_capacitance(ldo_cv), cap_footprint(ldo_cv)
                )
            )

        # Crystal load caps (XI and XO to GND)
        bypass_caps.append(
            BypassCap(
                "CL_XI",
                xi_net,
                gnd_net,
                format_capacitance(cl_ext),
                cap_footprint(cl_ext),
                role="crystal_load",
                presentation="topology_local",
            )
        )
        bypass_caps.append(
            BypassCap(
                "CL_XO",
                xo_net,
                gnd_net,
                format_capacitance(cl_ext),
                cap_footprint(cl_ext),
                role="crystal_load",
                presentation="topology_local",
            )
        )

        # ---- Strap resistors ----
        straps = []

        # Reset pull-up (10k to VDD)
        straps.append(StrapConfig("RESET", reset_net, vdd_net, format_resistance(10e3), FP_0402R))

        # ISET bias resistor (to GND)
        if ic_db.get("iset_r"):
            straps.append(
                StrapConfig(
                    "ISET",
                    iset_net,
                    gnd_net,
                    format_resistance(ic_db["iset_r"]),
                    FP_0402R,
                    role="bias",
                    presentation="topology_local",
                )
            )

        # Mode strap resistors
        strap_defs = ic_db["mode_straps"].get(mode, [])
        strap_vdd = vdd_net  # VDD for mode straps that pull high
        for sd in strap_defs:
            strap_rail = gnd_net if sd["rail"] == "GND" else strap_vdd
            strap_net = f"ETH_{sd['net_suffix']}_{ref}"
            straps.append(
                StrapConfig(
                    sd["pin"],
                    strap_net,
                    strap_rail,
                    format_resistance(10e3),
                    FP_0402R,
                )
            )

        # ---- Annotations ----
        cl_ext_pf = cl_ext * 1e12
        annotations = [
            f"Ethernet PHY {ic_name} — {mode.upper()} mode, GigE",
            f"Crystal load caps: CL_spec={crystal_cl * 1e12:.0f}pF -> CL_ext={cl_ext_pf:.0f}pF each (Cstray=4pF)",
        ]
        if ic_db.get("iset_r"):
            annotations.append(
                f"ISET bias: {format_resistance(ic_db['iset_r'])} to GND (datasheet recommended)"
            )
        if ic_db["has_internal_ldo"]:
            annotations.append(
                f"Internal 1.2V LDO — bypass with {format_capacitance(ic_db['ldo_bypass_cap'])}"
            )

        # Mode strap description
        if strap_defs:
            strap_desc_parts = []
            for sd in strap_defs:
                direction = "GND" if sd["rail"] == "GND" else "VDD"
                strap_desc_parts.append(f"{sd['net_suffix']}={direction}")
            annotations.append(f"Mode straps ({mode.upper()}): {', '.join(strap_desc_parts)}")

        # ---- Build IC component ----
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
            BoundaryPort(vdd_net, "input"),
            BoundaryPort(gnd_net, "passive"),
            BoundaryPort(reset_net, "input"),
            BoundaryPort(mdc_net, "input"),
            BoundaryPort(mdio_net, "bidirectional"),
            BoundaryPort(int_net, "output"),
        ]

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[
                f"Ethernet PHY {ic_name}: {mode.upper()} GigE, "
                f"25MHz crystal (CL={crystal_cl * 1e12:.0f}pF)",
            ],
            primary_category="digital",
        )
