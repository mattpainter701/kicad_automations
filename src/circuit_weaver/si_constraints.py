"""Signal integrity constraint solver.

Detects high-speed buses (USB, DDR, LVDS, PCIe, MIPI, Ethernet, CAN, RS-485)
from component pin nets, computes impedance targets, and generates length-matching constraints.
"""

from __future__ import annotations

import re

from .component_db import ComponentDef

_BUS_IMPEDANCE: dict[str, dict] = {
    "usb2": {"z_diff": 90, "tolerance_pct": 15, "length_match_mm": 2.5, "description": "USB 2.0 Full/High Speed"},
    "usb3": {"z_diff": 85, "tolerance_pct": 15, "length_match_mm": 1.5, "description": "USB 3.x SuperSpeed"},
    "ddr3": {"z_diff": 67, "tolerance_pct": 10, "length_match_mm": 0.127, "description": "DDR3 DQ/DQS"},
    "ddr4": {"z_diff": 67, "tolerance_pct": 10, "length_match_mm": 0.127, "description": "DDR4 DQ/DQS"},
    "lvds": {"z_diff": 100, "tolerance_pct": 10, "length_match_mm": 2.5, "description": "LVDS"},
    "pcie": {"z_diff": 85, "tolerance_pct": 15, "length_match_mm": 2.5, "description": "PCIe"},
    "mipi_dsi": {"z_diff": 100, "tolerance_pct": 10, "length_match_mm": 2.5, "description": "MIPI DSI"},
    "mipi_csi": {"z_diff": 100, "tolerance_pct": 10, "length_match_mm": 2.5, "description": "MIPI CSI"},
    "ethernet_100": {"z_diff": 100, "tolerance_pct": 10, "length_match_mm": 5.0, "description": "100BASE-TX Ethernet"},
    "ethernet_1g": {"z_diff": 100, "tolerance_pct": 10, "length_match_mm": 2.5, "description": "Gigabit Ethernet"},
    "can": {"z_diff": 120, "tolerance_pct": 10, "length_match_mm": None, "description": "CAN Bus"},
    "rs485": {"z_diff": 120, "tolerance_pct": 10, "length_match_mm": None, "description": "RS-485"},
    "spi_hs": {
        "z_diff": None,
        "z_single": 50,
        "tolerance_pct": 10,
        "length_match_mm": 5.0,
        "description": "High-speed SPI (>25 MHz)",
    },
}

_NET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("usb2", re.compile(r"USB.*?[DP][+-]|USB_D[MP]|DP[12]?|DM[12]?", re.IGNORECASE)),
    ("usb3", re.compile(r"USB3.*?[TR]X|SS[TR]X|SSTX|SSRX", re.IGNORECASE)),
    ("ddr4", re.compile(r"DDR4?_D[QS]|DQ[0-9]|DQS[0-9]|DDR_A[0-9]|DDR_BA", re.IGNORECASE)),
    ("ddr3", re.compile(r"DDR3_D[QS]|DDR3_A[0-9]", re.IGNORECASE)),
    ("lvds", re.compile(r"LVDS.*?[PN]|TX[0-9]+[PN]|RX[0-9]+[PN]", re.IGNORECASE)),
    ("pcie", re.compile(r"PCIE.*?[TR]X|PCI_TX|PCI_RX", re.IGNORECASE)),
    ("mipi_dsi", re.compile(r"DSI.*?[DP][0-9]|MIPI_D[0-9]", re.IGNORECASE)),
    ("mipi_csi", re.compile(r"CSI.*?[DP][0-9]|CAM_D[0-9]", re.IGNORECASE)),
    ("ethernet_1g", re.compile(r"ETH.*?[TR]X[DP]|MDI[0-9]|RGMII", re.IGNORECASE)),
    ("ethernet_100", re.compile(r"ETH.*?[TR]D[+-]|TX[+-]|RX[+-]", re.IGNORECASE)),
    ("can", re.compile(r"CAN[HL_]|CANH|CANL", re.IGNORECASE)),
    ("rs485", re.compile(r"RS485|485_[AB]", re.IGNORECASE)),
]

_DESC_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("usb3", re.compile(r"USB\s*3\.|SuperSpeed", re.IGNORECASE)),
    ("usb2", re.compile(r"USB\s*2?\.|USB\s+PHY|USB\s+Controller", re.IGNORECASE)),
    ("ddr4", re.compile(r"DDR4|LPDDR4", re.IGNORECASE)),
    ("ddr3", re.compile(r"DDR3|LPDDR3", re.IGNORECASE)),
    ("lvds", re.compile(r"LVDS|FPD-Link", re.IGNORECASE)),
    ("pcie", re.compile(r"PCI\s*Express|PCIe", re.IGNORECASE)),
    ("mipi_dsi", re.compile(r"MIPI\s*DSI|Display\s+Serial", re.IGNORECASE)),
    ("mipi_csi", re.compile(r"MIPI\s*CSI|Camera\s+Serial", re.IGNORECASE)),
    ("ethernet_1g", re.compile(r"Gigabit\s+Eth|1000BASE|RGMII|SGMII", re.IGNORECASE)),
    ("ethernet_100", re.compile(r"100BASE|Fast\s+Eth|RMII", re.IGNORECASE)),
]


def _detect_bus_from_nets(comp: ComponentDef) -> dict[str, list[str]]:
    buses: dict[str, list[str]] = {}
    for _pin_num, net in (comp.pin_nets or {}).items():
        if not net:
            continue
        for bus_type, pattern in _NET_PATTERNS:
            if pattern.search(net):
                buses.setdefault(bus_type, []).append(net)
                break
    return buses


def _detect_bus_from_description(comp: ComponentDef) -> str | None:
    combined = f"{comp.description or ''} {comp.mpn or ''}"
    for bus_type, pattern in _DESC_PATTERNS:
        if pattern.search(combined):
            return bus_type
    return None


def _find_diff_pairs(nets: list[str]) -> list[tuple[str, str]]:
    pairs = []
    seen: set[str] = set()
    for net in nets:
        if net in seen:
            continue
        for pos, neg in [("+", "-"), ("P", "N"), ("_P", "_N"), ("DP", "DM"), ("D+", "D-")]:
            if pos in net:
                partner = net.replace(pos, neg, 1)
                if partner in nets and partner not in seen:
                    pairs.append((net, partner))
                    seen.add(net)
                    seen.add(partner)
                    break
    return pairs


def analyze_si_constraints(components: list[ComponentDef]) -> dict:
    """Analyze a design for signal integrity constraints.

    Returns dict with buses_detected, diff_pairs, impedance_constraints,
    length_groups, routing_rules, warnings, summary.
    """
    buses_detected: list[dict] = []
    diff_pairs: list[dict] = []
    impedance_constraints: list[dict] = []
    length_groups: list[dict] = []
    routing_rules: list[dict] = []

    for comp in components:
        ref = comp.source_ref or ""
        if not ref:
            continue

        net_buses = _detect_bus_from_nets(comp)
        if not net_buses:
            desc_bus = _detect_bus_from_description(comp)
            if desc_bus:
                net_buses = {desc_bus: []}

        for bus_type, nets in net_buses.items():
            bus_info = _BUS_IMPEDANCE.get(bus_type, {})

            buses_detected.append(
                {
                    "bus_type": bus_type,
                    "component": ref,
                    "net_count": len(nets),
                    "description": bus_info.get("description", bus_type),
                }
            )

            for net_p, net_n in _find_diff_pairs(nets):
                diff_pairs.append({"bus_type": bus_type, "net_p": net_p, "net_n": net_n, "source_ref": ref})

            if bus_info.get("z_diff"):
                diff_desc = (
                    f"{bus_info['description']}: {bus_info['z_diff']}\u03a9 "
                    f"\u00b1{bus_info['tolerance_pct']}% differential"
                )
                impedance_constraints.append(
                    {
                        "bus_type": bus_type,
                        "type": "differential",
                        "target_ohms": bus_info["z_diff"],
                        "tolerance_pct": bus_info["tolerance_pct"],
                        "nets": nets,
                        "source_ref": ref,
                        "description": diff_desc,
                    }
                )
            elif bus_info.get("z_single"):
                single_desc = (
                    f"{bus_info['description']}: {bus_info['z_single']}\u03a9 "
                    f"\u00b1{bus_info['tolerance_pct']}% single-ended"
                )
                impedance_constraints.append(
                    {
                        "bus_type": bus_type,
                        "type": "single-ended",
                        "target_ohms": bus_info["z_single"],
                        "tolerance_pct": bus_info["tolerance_pct"],
                        "nets": nets,
                        "source_ref": ref,
                        "description": single_desc,
                    }
                )

            if bus_info.get("length_match_mm") and len(nets) >= 2:
                length_groups.append(
                    {
                        "bus_type": bus_type,
                        "nets": nets,
                        "tolerance_mm": bus_info["length_match_mm"],
                        "source_ref": ref,
                        "description": f"{bus_info['description']}: \u00b1{bus_info['length_match_mm']}mm length match",
                    }
                )

            if bus_type in ("usb2", "usb3"):
                usb_desc = f"Route {bus_info['description']} diff pairs with 4x trace-width spacing from other signals"
                routing_rules.append(
                    {
                        "bus_type": bus_type,
                        "nets": nets,
                        "source_ref": ref,
                        "description": usb_desc,
                    }
                )
            if bus_type.startswith("ddr"):
                ddr_desc = (
                    f"Route {bus_info['description']} with matched delays; "
                    f"place termination resistors within 10mm of memory IC"
                )
                routing_rules.append(
                    {
                        "bus_type": bus_type,
                        "nets": nets,
                        "source_ref": ref,
                        "description": ddr_desc,
                    }
                )

    # Deduplicate
    seen_buses: set[tuple] = set()
    unique_buses = []
    for b in buses_detected:
        key = (b["bus_type"], b["component"])
        if key not in seen_buses:
            seen_buses.add(key)
            unique_buses.append(b)
    buses_detected = unique_buses

    parts = []
    if buses_detected:
        bus_types = ", ".join(sorted(set(b["bus_type"] for b in buses_detected)))
        parts.append(f"Detected {len(buses_detected)} high-speed buses: {bus_types}")
    if diff_pairs:
        parts.append(f"{len(diff_pairs)} differential pairs")
    if impedance_constraints:
        parts.append(f"{len(impedance_constraints)} impedance constraints")
    if length_groups:
        parts.append(f"{len(length_groups)} length-matching groups")
    if not parts:
        parts.append("No high-speed buses detected")

    return {
        "status": "ok",
        "buses_detected": buses_detected,
        "diff_pairs": diff_pairs,
        "impedance_constraints": impedance_constraints,
        "length_groups": length_groups,
        "routing_rules": routing_rules,
        "warnings": [],
        "summary": ". ".join(parts) + ".",
    }
