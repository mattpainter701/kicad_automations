"""Data-driven topology builders.

Each builder takes IC data (from JSON) and design parameters, then produces
a SubcircuitResult — the same output as legacy template classes, but without
any hardcoded IC knowledge. New ICs are added by writing JSON, not Python.

Builder functions are keyed by topology name in TOPOLOGY_BUILDERS dict.
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
    buck_inductor,
    buck_output_cap,
    boost_inductor,
    buck_boost_inductor,
    crystal_load_caps,
    cap_footprint,
    feedback_divider_top,
    feedback_divider_vout,
    format_capacitance,
    format_inductance,
    format_resistance,
    ind_footprint,
    res_footprint,
    snap_cap,
    snap_ind,
    snap_to_e24,
    snap_to_e96,
)


def _pins_from_data(ic_data: dict) -> list[PinDef]:
    """Convert JSON pin list to PinDef objects."""
    return [
        PinDef(p["number"], p["name"], p["type"], p["side"])
        for p in ic_data.get("pins", [])
    ]


def _pin_role(ic_data: dict, role: str) -> str | None:
    """Look up a pin number by role name from pin_roles or pin_<role> keys."""
    roles = ic_data.get("pin_roles", {})
    if role in roles:
        return str(roles[role])
    key = f"pin_{role}"
    val = ic_data.get(key)
    return str(val) if val is not None else None


# ================================================================
# Switching regulator builder (buck, boost, buck_boost)
# ================================================================


def build_switching_regulator(ic_data: dict, params: dict[str, Any]) -> SubcircuitResult:
    """Build a switching regulator subcircuit from IC data + design params."""
    topology = ic_data.get("topology", "buck")
    vin = params["vin"]
    vout = params["vout"]
    iout = params["iout"]
    ic_name = params.get("ic", ic_data.get("_mpn", "UNKNOWN"))
    ref = params.get("ref", "U")
    rail_name = params.get("rail_name") or f"VDD_{vout:.1f}V".replace(".", "P")
    vin_net = params.get("vin_net", "VIN")
    en_net = params.get("en_net", vin_net)
    ripple_ratio = params.get("ripple_ratio", 0.3)
    vout_ripple = params.get("vout_ripple", 0.020)

    vref = ic_data.get("vref", 0.8)
    fsw = params.get("fsw", ic_data.get("fsw", 600e3))
    r_fbb = params.get("r_fbb", ic_data.get("r_fbb_default", 100e3))

    # Calculate feedback divider
    r_fbt_raw = feedback_divider_top(vout, vref, r_fbb)
    r_fbt = snap_to_e96(r_fbt_raw)
    r_fbb_snapped = snap_to_e96(r_fbb)
    actual_vout = feedback_divider_vout(r_fbt, r_fbb_snapped, vref)

    # Calculate inductor
    if topology == "boost":
        l_raw = boost_inductor(vin, vout, fsw, iout, ripple_ratio)
    elif topology == "buck_boost":
        vin_min = params.get("vin_min", vin * 0.8)
        l_raw = buck_boost_inductor(vin_min, vout, fsw, iout, ripple_ratio)
    else:
        l_raw = buck_inductor(vin, vout, fsw, iout, ripple_ratio)
    l_val = snap_ind(l_raw)

    # Ripple current with actual inductor value
    if fsw > 0 and l_val > 0:
        if topology == "buck":
            d = vout / vin
            delta_il = (vin - vout) * d / (fsw * l_val)
        elif topology == "boost":
            d = 1.0 - vin / vout if vout > vin else 0.5
            delta_il = vin * d / (fsw * l_val)
        else:  # buck_boost
            vin_min = params.get("vin_min", vin * 0.8)
            d = 1.0 - vin_min / vout if vout > vin_min else 0.5
            delta_il = vin_min * d / (fsw * l_val)
    else:
        delta_il = iout * 0.3
    cout_raw = buck_output_cap(abs(delta_il), fsw, vout_ripple)
    cout_val = snap_cap(cout_raw)
    cin_val = 22e-6 if iout > 2.0 else 10e-6
    cbst_val = 100e-9

    # Net names
    sw_net = f"SW_{ref}"
    bst_net = f"BST_{ref}"
    fb_net = f"FB_{ref}"

    # Power pins
    pin_vin = _pin_role(ic_data, "vin")
    pin_gnd = _pin_role(ic_data, "gnd")
    pin_sw = _pin_role(ic_data, "sw")
    pin_fb = _pin_role(ic_data, "fb")
    pin_en = _pin_role(ic_data, "en")
    pin_bst = _pin_role(ic_data, "bst")

    power_pins: dict[str, str] = {}
    if pin_vin:
        power_pins[pin_vin] = vin_net
    if pin_gnd:
        power_pins[pin_gnd] = "GND"
    for extra in ic_data.get("pin_gnd_extra", []):
        power_pins[str(extra)] = "GND"

    pin_nets: dict[str, str] = {}
    if pin_sw:
        pin_nets[pin_sw] = sw_net
    if pin_fb:
        pin_nets[pin_fb] = fb_net
    if pin_en:
        pin_nets[pin_en] = en_net
    if pin_bst:
        pin_nets[pin_bst] = bst_net

    bypass_caps = [
        BypassCap("CIN", vin_net, "GND", format_capacitance(cin_val),
                  cap_footprint(cin_val), role="input_cap", presentation="topology_local"),
        BypassCap("COUT", rail_name, "GND", format_capacitance(cout_val),
                  cap_footprint(cout_val), role="output_cap", presentation="topology_local"),
        BypassCap("L", sw_net, rail_name, format_inductance(l_val),
                  ind_footprint(l_val, iout), role="inductor", presentation="topology_local"),
    ]
    if pin_bst:
        bypass_caps.append(
            BypassCap("CBST", bst_net, sw_net, format_capacitance(cbst_val),
                      FP_0402C, role="bootstrap_cap", presentation="topology_local"),
        )

    straps = [
        StrapConfig("FBT", fb_net, rail_name, format_resistance(r_fbt),
                    FP_0402R, role="feedback_top", presentation="topology_local"),
        StrapConfig("FBB", fb_net, "GND", format_resistance(r_fbb_snapped),
                    FP_0402R, role="feedback_bottom", presentation="topology_local"),
    ]

    annotations = [
        f"{rail_name}: {vout}V from {vin_net} at {iout}A",
        f"Vout = {vref}V * (1 + {format_resistance(r_fbt)}/{format_resistance(r_fbb_snapped)}) = {actual_vout:.3f}V",
        f"L={format_inductance(l_val)}, Cin={format_capacitance(cin_val)}, Cout={format_capacitance(cout_val)}",
        f"fsw={fsw / 1e3:.0f}kHz, ripple={delta_il:.2f}A ({abs(delta_il / iout * 100):.0f}%)",
    ]

    ic_comp = ComponentDef(
        mpn=ic_name, ref_prefix="U", value=ic_name,
        footprint=ic_data.get("footprint", ""),
        description=ic_data.get("description", ""),
        category="power", pins=_pins_from_data(ic_data),
        power_pins=power_pins, pin_nets=pin_nets,
        bypass_caps=bypass_caps, straps=straps, annotations=annotations,
    )

    ports = [
        BoundaryPort(vin_net, "input"),
        BoundaryPort(rail_name, "output"),
        BoundaryPort("GND", "passive"),
        BoundaryPort(en_net, "input"),
    ]

    topo_label = {"buck": "Buck", "boost": "Boost", "buck_boost": "Buck-Boost"}[topology]
    return SubcircuitResult(
        components=[ic_comp], boundary_ports=ports,
        annotations=[f"{topo_label} {ic_name}: {vin_net} ({vin}V) -> {rail_name} ({actual_vout:.2f}V) at {iout}A"],
        primary_category="power",
    )


# ================================================================
# Linear regulator builder (ldo)
# ================================================================


def build_linear_regulator(ic_data: dict, params: dict[str, Any]) -> SubcircuitResult:
    """Build an LDO regulator subcircuit."""
    ic_name = params.get("ic", ic_data.get("_mpn", "UNKNOWN"))
    ref = params.get("ref", "U")
    vin = params["vin"]
    vout = params.get("vout", ic_data.get("vout_fixed", 3.3))
    iout = params.get("iout", ic_data.get("iout_max", 0.5))
    rail_name = params.get("rail_name") or f"VDD_{vout:.1f}V".replace(".", "P")
    vin_net = params.get("vin_net", "VIN")
    en_net = params.get("en_net", vin_net)

    vdropout = ic_data.get("vdropout", 0.2)
    warnings = []
    if vin - vout < vdropout:
        warnings.append(f"WARNING: Vin-Vout={vin - vout:.2f}V < Vdropout={vdropout:.3f}V")
    pdiss = (vin - vout) * iout
    if pdiss > 0.5:
        warnings.append(f"WARNING: Pdiss={pdiss:.2f}W > 500mW — needs heatsink")

    cin_val = ic_data.get("cin", 1e-6)
    cout_val = ic_data.get("cout", 1e-6)

    pin_vin = _pin_role(ic_data, "vin")
    pin_gnd = _pin_role(ic_data, "gnd")
    pin_out = _pin_role(ic_data, "out")
    pin_en = _pin_role(ic_data, "en")

    power_pins: dict[str, str] = {}
    if pin_vin:
        power_pins[pin_vin] = vin_net
    if pin_gnd:
        power_pins[pin_gnd] = "GND"
    if pin_out:
        power_pins[pin_out] = rail_name

    pin_nets: dict[str, str] = {}
    if pin_en:
        pin_nets[pin_en] = en_net

    bypass_caps = [
        BypassCap("CIN", vin_net, "GND", format_capacitance(cin_val),
                  cap_footprint(cin_val), role="decoupling", presentation="topology_local"),
        BypassCap("COUT", rail_name, "GND", format_capacitance(cout_val),
                  cap_footprint(cout_val), role="decoupling", presentation="topology_local"),
    ]

    iq_ua = ic_data.get("iq_ua", 0)
    annotations = [
        f"{rail_name}: {vout}V from {vin_net} at {iout}A ({ic_name})",
        f"Dropout: {vdropout:.3f}V, Pdiss: {pdiss:.2f}W, Iq: {iq_ua}uA",
    ] + warnings

    ic_comp = ComponentDef(
        mpn=ic_name, ref_prefix="U", value=ic_name,
        footprint=ic_data.get("footprint", ""),
        description=ic_data.get("description", ""),
        category="power", pins=_pins_from_data(ic_data),
        power_pins=power_pins, pin_nets=pin_nets,
        bypass_caps=bypass_caps, annotations=annotations,
    )

    ports = [
        BoundaryPort(vin_net, "input"),
        BoundaryPort(rail_name, "output"),
        BoundaryPort("GND", "passive"),
    ]
    if pin_en:
        ports.append(BoundaryPort(en_net, "input"))

    return SubcircuitResult(
        components=[ic_comp], boundary_ports=ports,
        annotations=[f"LDO {ic_name}: {vin_net} ({vin}V) -> {rail_name} ({vout}V) at {iout}A"] + warnings,
        primary_category="power",
    )


# ================================================================
# Generic wiring builder (pin map + decoupling)
# ================================================================


def build_generic(ic_data: dict, params: dict[str, Any]) -> SubcircuitResult:
    """Fallback builder for ICs without specialized topology logic.

    Assigns power pins, adds standard decoupling, and exports boundary ports.
    Works for: protection, connectors, EEPROM, RTC, display, wireless, etc.
    """
    ic_name = params.get("ic", ic_data.get("_mpn", "UNKNOWN"))
    ref = params.get("ref", "U")
    vdd_net = params.get("vdd_net", "VDD_3P3")

    pin_gnd = _pin_role(ic_data, "gnd")
    pin_vdd = _pin_role(ic_data, "vdd") or _pin_role(ic_data, "vcc") or _pin_role(ic_data, "vin")

    power_pins: dict[str, str] = {}
    if pin_vdd:
        power_pins[pin_vdd] = vdd_net
    if pin_gnd:
        power_pins[pin_gnd] = "GND"

    # Handle multiple GND pins
    for key in ic_data:
        if key.startswith("pin_gnd") and key != "pin_gnd":
            extras = ic_data[key]
            if isinstance(extras, list):
                for p in extras:
                    power_pins[str(p)] = "GND"

    bypass_caps = [
        BypassCap("C_VDD", vdd_net, "GND", "100nF", FP_0402C,
                  role="decoupling", presentation="topology_local"),
    ]

    ref_prefix = ic_data.get("ref_prefix", "U")
    ic_comp = ComponentDef(
        mpn=ic_name, ref_prefix=ref_prefix, value=ic_name,
        footprint=ic_data.get("footprint", ""),
        description=ic_data.get("description", ""),
        category=ic_data.get("category", "digital"),
        pins=_pins_from_data(ic_data),
        power_pins=power_pins, pin_nets={},
        bypass_caps=bypass_caps,
        annotations=[f"{ic_data.get('description', ic_name)}"],
    )
    ic_comp.source_ref = ref

    ports = [
        BoundaryPort(vdd_net, "input"),
        BoundaryPort("GND", "passive"),
    ]

    return SubcircuitResult(
        components=[ic_comp], boundary_ports=ports,
        annotations=[f"{ic_name}: {vdd_net}"],
        primary_category=ic_data.get("primary_category", "digital"),
    )


# ================================================================
# Topology builder registry
# ================================================================


TOPOLOGY_BUILDERS: dict[str, Any] = {
    "buck": build_switching_regulator,
    "boost": build_switching_regulator,
    "buck_boost": build_switching_regulator,
    "ldo": build_linear_regulator,
}

# All other topologies fall through to build_generic
_GENERIC_TOPOLOGIES = {
    "protection", "connector", "usb_c_connector", "eeprom", "rtc",
    "display_driver", "wireless_module", "mosfet_switch", "relay_driver",
    "gate_driver", "led_driver", "power_mux", "battery_monitor",
    "ethernet_phy", "usb_controller", "usb_hub", "battery_charger",
    "charge_pump", "voltage_reference", "motor_driver",
    "can_transceiver", "rs485_transceiver", "level_shifter",
    "i2c_bus", "spi_bus", "adc", "dac", "current_sense",
    "opamp", "sensor_frontend", "audio_amplifier",
    "crystal_oscillator", "clock_synth",
}

for _topo in _GENERIC_TOPOLOGIES:
    TOPOLOGY_BUILDERS.setdefault(_topo, build_generic)


def get_builder(topology: str):
    """Look up the builder function for a topology."""
    return TOPOLOGY_BUILDERS.get(topology, build_generic)
