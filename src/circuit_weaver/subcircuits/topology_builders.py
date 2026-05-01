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
    GROUND_NET_PREFIXES,
    POWER_NET_PREFIXES,
    BoundaryPort,
    SubcircuitResult,
    boost_inductor,
    buck_boost_inductor,
    buck_inductor,
    buck_output_cap,
    cap_footprint,
    feedback_divider_top,
    feedback_divider_vout,
    format_capacitance,
    format_inductance,
    format_resistance,
    ind_footprint,
    snap_cap,
    snap_ind,
    snap_to_e24,
    snap_to_e96,
)


def _pins_from_data(ic_data: dict) -> list[PinDef]:
    """Convert JSON pin list to PinDef objects."""
    return [PinDef(p["number"], p["name"], p["type"], p["side"]) for p in ic_data.get("pins", [])]


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
    """Build a switching regulator subcircuit, dispatching by topology."""
    topology = ic_data.get("topology", "buck")
    if topology == "boost":
        return _build_boost(ic_data, params)
    elif topology == "buck_boost":
        return _build_buck_boost(ic_data, params)
    return _build_buck(ic_data, params)


def _build_buck(ic_data: dict, params: dict[str, Any]) -> SubcircuitResult:
    """Build a buck (step-down) regulator."""
    vin = params["vin"]
    vout = params["vout"]
    iout = params["iout"]
    fsw = params.get("fsw", ic_data.get("fsw", 600e3))
    ripple_ratio = params.get("ripple_ratio", 0.3)
    l_raw = buck_inductor(vin, vout, fsw, iout, ripple_ratio)
    l_val = snap_ind(l_raw)
    if fsw > 0 and l_val > 0:
        d = vout / vin
        delta_il = (vin - vout) * d / (fsw * l_val)
    else:
        delta_il = iout * 0.3
    return _build_switching_core(ic_data, params, "buck", l_val, delta_il)


def _build_boost(ic_data: dict, params: dict[str, Any]) -> SubcircuitResult:
    """Build a boost (step-up) regulator."""
    vin = params["vin"]
    vout = params["vout"]
    iout = params["iout"]
    fsw = params.get("fsw", ic_data.get("fsw", 600e3))
    ripple_ratio = params.get("ripple_ratio", 0.3)
    l_raw = boost_inductor(vin, vout, fsw, iout, ripple_ratio)
    l_val = snap_ind(l_raw)
    if fsw > 0 and l_val > 0:
        d = 1.0 - vin / vout if vout > vin else 0.5
        delta_il = vin * d / (fsw * l_val)
    else:
        delta_il = iout * 0.3
    return _build_switching_core(ic_data, params, "boost", l_val, delta_il)


def _build_buck_boost(ic_data: dict, params: dict[str, Any]) -> SubcircuitResult:
    """Build a buck-boost (inverting/step-up-down) regulator."""
    vin = params["vin"]
    vout = params["vout"]
    iout = params["iout"]
    fsw = params.get("fsw", ic_data.get("fsw", 600e3))
    ripple_ratio = params.get("ripple_ratio", 0.3)
    vin_min = params.get("vin_min", vin * 0.8)
    l_raw = buck_boost_inductor(vin_min, vout, fsw, iout, ripple_ratio)
    l_val = snap_ind(l_raw)
    if fsw > 0 and l_val > 0:
        d = 1.0 - vin_min / vout if vout > vin_min else 0.5
        delta_il = vin_min * d / (fsw * l_val)
    else:
        delta_il = iout * 0.3
    return _build_switching_core(ic_data, params, "buck_boost", l_val, delta_il)


def _build_switching_core(
    ic_data: dict,
    params: dict[str, Any],
    topology: str,
    l_val: float,
    delta_il: float,
) -> SubcircuitResult:
    """Shared core: feedback, caps, pins, and component assembly for switching regulators."""
    vin = params["vin"]
    vout = params["vout"]
    iout = params["iout"]
    ic_name = params.get("ic", ic_data.get("_mpn", "UNKNOWN"))
    ref = params.get("ref", "U")
    rail_name = params.get("rail_name") or f"VDD_{vout:.1f}V".replace(".", "P")
    vin_net = params.get("vin_net", "VIN")
    en_net = params.get("en_net", vin_net)
    vout_ripple = params.get("vout_ripple", 0.020)
    fsw = params.get("fsw", ic_data.get("fsw", 600e3))

    vref = ic_data.get("vref", 0.8)
    r_fbb = params.get("r_fbb", ic_data.get("r_fbb_default", 100e3))

    # Feedback divider
    r_fbt_raw = feedback_divider_top(vout, vref, r_fbb)
    r_fbt = snap_to_e96(r_fbt_raw)
    r_fbb_snapped = snap_to_e96(r_fbb)
    actual_vout = feedback_divider_vout(r_fbt, r_fbb_snapped, vref)

    # Output capacitor
    cout_raw = buck_output_cap(abs(delta_il), fsw, vout_ripple)
    cout_val = snap_cap(cout_raw)
    cin_val = 22e-6 if iout > 2.0 else 10e-6
    cbst_val = 100e-9

    # Net names
    sw_net = f"SW_{ref}"
    bst_net = f"BST_{ref}"
    fb_net = f"FB_{ref}"
    l1_net = f"L1_{ref}"
    l2_net = f"L2_{ref}"
    pg_net = f"PG_{ref}"
    vaux_net = f"VAUX_{ref}"

    # Power pins
    pin_vin = _pin_role(ic_data, "vin")
    pin_gnd = _pin_role(ic_data, "gnd")
    pin_sw = _pin_role(ic_data, "sw")
    pin_fb = _pin_role(ic_data, "fb")
    pin_en = _pin_role(ic_data, "en")
    pin_bst = _pin_role(ic_data, "bst")
    pin_l1 = _pin_role(ic_data, "l1")
    pin_l2 = _pin_role(ic_data, "l2")
    pin_pg = _pin_role(ic_data, "pg")
    pin_vaux = _pin_role(ic_data, "vaux")
    pin_ps_sync = _pin_role(ic_data, "ps_sync")

    power_pins: dict[str, str] = {}
    if pin_vin:
        power_pins[pin_vin] = vin_net
    if pin_gnd:
        power_pins[pin_gnd] = "GND"
    for extra in ic_data.get("pin_gnd_extra", []):
        power_pins[str(extra)] = "GND"

    # Auto-detect additional power pins from pin list (VIN2, VOUT2, EPAD, etc.)
    pins = _pins_from_data(ic_data)
    for pin in pins:
        if pin.number in power_pins:
            continue
        name_upper = pin.name.upper()
        if pin.electrical_type == "power_in":
            if name_upper in ("GND", "VSS", "VEE", "PGND", "SGND", "EPAD"):
                power_pins[pin.number] = "GND"
            elif name_upper in ("VIN", "VINA", "VINB", "VBAT"):
                power_pins[pin.number] = vin_net
            elif name_upper in ("VOUT", "VOUTA", "VOUTB"):
                power_pins[pin.number] = rail_name
        elif pin.electrical_type == "power_out":
            if name_upper in ("VOUT", "VOUTA", "VOUTB", "VAUX"):
                power_pins[pin.number] = rail_name

    pin_nets: dict[str, str] = {}
    if topology == "buck_boost":
        if pin_l1:
            pin_nets[pin_l1] = l1_net
        if pin_l2:
            pin_nets[pin_l2] = l2_net
        if pin_pg:
            pin_nets[pin_pg] = pg_net
        if pin_vaux:
            pin_nets[pin_vaux] = vaux_net
        if pin_ps_sync:
            pin_nets[pin_ps_sync] = "GND"
    else:
        if pin_sw:
            pin_nets[pin_sw] = sw_net
    if pin_fb:
        pin_nets[pin_fb] = fb_net
    if pin_en:
        pin_nets[pin_en] = en_net
    if pin_bst and topology != "buck_boost":
        pin_nets[pin_bst] = bst_net

    # Mark any unused input/bidirectional pins as explicit no-connect
    explicit_no_connects: set[str] = set()
    for pin in pins:
        if pin.number in power_pins or pin.number in pin_nets:
            continue
        if pin.electrical_type in ("input", "bidirectional"):
            explicit_no_connects.add(pin.number)

    bypass_caps: list[BypassCap] = []
    if topology == "buck_boost":
        cin_bulk_val = 10e-6
        cin_hf_val = 100e-9
        cout_bulk_val = 22e-6
        cout_hf_val = 100e-9
        c_vaux_val = 10e-6
        bypass_caps = [
            BypassCap(
                "CIN_BULK",
                vin_net,
                "GND",
                format_capacitance(cin_bulk_val),
                cap_footprint(cin_bulk_val),
                role="input_cap",
                presentation="topology_local",
            ),
            BypassCap(
                "CIN_HF",
                vin_net,
                "GND",
                format_capacitance(cin_hf_val),
                cap_footprint(cin_hf_val),
                role="input_cap",
                presentation="topology_local",
            ),
            BypassCap(
                "COUT_BULK",
                rail_name,
                "GND",
                format_capacitance(cout_bulk_val),
                cap_footprint(cout_bulk_val),
                role="output_cap",
                presentation="topology_local",
            ),
            BypassCap(
                "COUT_HF",
                rail_name,
                "GND",
                format_capacitance(cout_hf_val),
                cap_footprint(cout_hf_val),
                role="output_cap",
                presentation="topology_local",
            ),
            BypassCap(
                "L",
                l1_net,
                l2_net,
                format_inductance(l_val),
                ind_footprint(l_val, iout),
                role="inductor",
                presentation="topology_local",
            ),
        ]
        if pin_vaux and ic_data.get("has_vaux"):
            bypass_caps.append(
                BypassCap(
                    "CVAUX",
                    vaux_net,
                    "GND",
                    format_capacitance(c_vaux_val),
                    cap_footprint(c_vaux_val),
                    role="decoupling",
                    presentation="topology_local",
                ),
            )
    else:
        bypass_caps = [
            BypassCap(
                "CIN",
                vin_net,
                "GND",
                format_capacitance(cin_val),
                cap_footprint(cin_val),
                role="input_cap",
                presentation="topology_local",
            ),
            BypassCap(
                "COUT",
                rail_name,
                "GND",
                format_capacitance(cout_val),
                cap_footprint(cout_val),
                role="output_cap",
                presentation="topology_local",
            ),
            BypassCap(
                "L",
                vin_net if topology == "boost" else sw_net,
                sw_net if topology == "boost" else rail_name,
                format_inductance(l_val),
                ind_footprint(l_val, iout),
                role="inductor",
                presentation="topology_local",
            ),
        ]
        if pin_bst:
            bypass_caps.append(
                BypassCap(
                    "CBST",
                    bst_net,
                    sw_net,
                    format_capacitance(cbst_val),
                    FP_0402C,
                    role="bootstrap_cap",
                    presentation="topology_local",
                ),
            )

    straps = [
        StrapConfig(
            "FBT",
            fb_net,
            rail_name,
            format_resistance(r_fbt),
            FP_0402R,
            role="feedback_top",
            presentation="topology_local",
        ),
        StrapConfig(
            "FBB",
            fb_net,
            "GND",
            format_resistance(r_fbb_snapped),
            FP_0402R,
            role="feedback_bottom",
            presentation="topology_local",
        ),
    ]

    annotations = [
        f"{rail_name}: {vout}V from {vin_net} at {iout}A",
        f"Vout = {vref}V * (1 + {format_resistance(r_fbt)}/{format_resistance(r_fbb_snapped)}) = {actual_vout:.3f}V",
    ]
    if topology == "buck_boost":
        cin_bulk_val = 10e-6
        cin_hf_val = 100e-9
        cout_bulk_val = 22e-6
        cout_hf_val = 100e-9
        annotations += [
            f"L={format_inductance(l_val)} (sized for Vin_min={params.get('vin_min', vin * 0.8)}V)",
            f"Cin={format_capacitance(cin_bulk_val)}+{format_capacitance(cin_hf_val)}, "
            f"Cout={format_capacitance(cout_bulk_val)}+{format_capacitance(cout_hf_val)}",
            f"fsw={fsw / 1e6:.1f}MHz",
        ]
    else:
        annotations += [
            f"L={format_inductance(l_val)}, Cin={format_capacitance(cin_val)}, Cout={format_capacitance(cout_val)}",
            f"fsw={fsw / 1e3:.0f}kHz, ripple={delta_il:.2f}A ({abs(delta_il / iout * 100):.0f}%)",
        ]

    ic_comp = ComponentDef(
        mpn=ic_name,
        ref_prefix="U",
        value=ic_name,
        footprint=ic_data.get("footprint", ""),
        description=ic_data.get("description", ""),
        category="power",
        pins=_pins_from_data(ic_data),
        power_pins=power_pins,
        pin_nets=pin_nets,
        bypass_caps=bypass_caps,
        straps=straps,
        annotations=annotations,
        explicit_no_connects=explicit_no_connects,
    )

    ports = [
        BoundaryPort(vin_net, "input"),
        BoundaryPort(rail_name, "output"),
        BoundaryPort("GND", "passive"),
    ]
    if pin_en:
        ports.append(BoundaryPort(en_net, "input"))
    if topology == "buck_boost" and pin_pg:
        ports.append(BoundaryPort(pg_net, "output"))

    topo_label = {"buck": "Buck", "boost": "Boost", "buck_boost": "Buck-Boost"}[topology]
    return SubcircuitResult(
        components=[ic_comp],
        boundary_ports=ports,
        annotations=[f"{topo_label} {ic_name}: {vin_net} ({vin}V) -> {rail_name} ({actual_vout:.2f}V) at {iout}A"],
        primary_category="power",
    )


# ================================================================
# Linear regulator builder (ldo)
# ================================================================


def build_linear_regulator(ic_data: dict, params: dict[str, Any]) -> SubcircuitResult:
    """Build an LDO regulator subcircuit."""
    ic_name = params.get("ic", ic_data.get("_mpn", "UNKNOWN"))
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
        BypassCap(
            "CIN",
            vin_net,
            "GND",
            format_capacitance(cin_val),
            cap_footprint(cin_val),
            role="decoupling",
            presentation="topology_local",
        ),
        BypassCap(
            "COUT",
            rail_name,
            "GND",
            format_capacitance(cout_val),
            cap_footprint(cout_val),
            role="decoupling",
            presentation="topology_local",
        ),
    ]

    iq_ua = ic_data.get("iq_ua", 0)
    annotations = [
        f"{rail_name}: {vout}V from {vin_net} at {iout}A ({ic_name})",
        f"Dropout: {vdropout:.3f}V, Pdiss: {pdiss:.2f}W, Iq: {iq_ua}uA",
    ] + warnings

    ic_comp = ComponentDef(
        mpn=ic_name,
        ref_prefix="U",
        value=ic_name,
        footprint=ic_data.get("footprint", ""),
        description=ic_data.get("description", ""),
        category="power",
        pins=_pins_from_data(ic_data),
        power_pins=power_pins,
        pin_nets=pin_nets,
        bypass_caps=bypass_caps,
        annotations=annotations,
    )

    ports = [
        BoundaryPort(vin_net, "input"),
        BoundaryPort(rail_name, "output"),
        BoundaryPort("GND", "passive"),
    ]
    if pin_en:
        ports.append(BoundaryPort(en_net, "input"))

    return SubcircuitResult(
        components=[ic_comp],
        boundary_ports=ports,
        annotations=[f"LDO {ic_name}: {vin_net} ({vin}V) -> {rail_name} ({vout}V) at {iout}A"] + warnings,
        primary_category="power",
    )


# ================================================================
# Thin verdict-A builders
# ================================================================


def build_can_transceiver(ic_data: dict, params: dict[str, Any]) -> SubcircuitResult:
    """Build a CAN transceiver with legacy-compatible CAN net options."""
    ic_name = params.get("ic", ic_data.get("_mpn", "SN65HVD230"))
    ref = params.get("ref", "U")
    vdd_net = params.get("vdd_net", "VDD_3P3")
    txd_net = params.get("txd_net", f"CAN_TXD_{ref}")
    rxd_net = params.get("rxd_net", f"CAN_RXD_{ref}")
    bus_prefix = params.get("bus_net_prefix", "CAN")
    termination = params.get("termination", False)
    slope_control = params.get("slope_control", False)

    pins = _pins_from_data(ic_data)
    canh_net = f"{bus_prefix}_H_{ref}"
    canl_net = f"{bus_prefix}_L_{ref}"
    vref_net = f"CAN_VREF_{ref}"

    pin_vcc = _pin_role(ic_data, "vcc")
    pin_gnd = _pin_role(ic_data, "gnd")
    pin_txd = _pin_role(ic_data, "txd")
    pin_rxd = _pin_role(ic_data, "rxd")
    pin_canh = _pin_role(ic_data, "canh")
    pin_canl = _pin_role(ic_data, "canl")
    pin_vref = _pin_role(ic_data, "vref")
    pin_rs = _pin_role(ic_data, "rs")

    power_pins = {pin_vcc: vdd_net, pin_gnd: "GND"}
    pin_nets = {
        pin_txd: txd_net,
        pin_rxd: rxd_net,
        pin_canh: canh_net,
        pin_canl: canl_net,
        pin_vref: vref_net,
    }

    if slope_control:
        rs_net = f"CAN_RS_{ref}"
        pin_nets[pin_rs] = rs_net
    elif ic_data.get("rs_highspeed_to_gnd", False):
        pin_nets[pin_rs] = "GND"

    bypass_caps = [
        BypassCap("C_VCC", vdd_net, "GND", "100nF", FP_0402C, role="decoupling", presentation="topology_local"),
        BypassCap("C_VREF", vref_net, "GND", "100nF", FP_0402C, role="decoupling", presentation="topology_local"),
    ]
    straps = []
    if slope_control:
        straps.append(
            StrapConfig(
                "RS",
                rs_net,
                "GND",
                format_resistance(snap_to_e24(10e3)),
                FP_0402R,
                role="slope_control",
                presentation="topology_local",
            )
        )
    if termination:
        term_mid_net = f"CAN_TERM_MID_{ref}"
        straps.extend(
            [
                StrapConfig(
                    "RT1",
                    canh_net,
                    term_mid_net,
                    format_resistance(snap_to_e96(60)),
                    FP_0402R,
                    role="termination",
                    presentation="topology_local",
                ),
                StrapConfig(
                    "RT2",
                    term_mid_net,
                    canl_net,
                    format_resistance(snap_to_e96(60)),
                    FP_0402R,
                    role="termination",
                    presentation="topology_local",
                ),
            ]
        )
        bypass_caps.append(
            BypassCap(
                "CT",
                term_mid_net,
                "GND",
                format_capacitance(snap_cap(4.7e-9)),
                cap_footprint(4.7e-9),
                role="termination",
                presentation="topology_local",
            )
        )

    comp = ComponentDef(
        mpn=ic_name,
        ref_prefix="U",
        value=ic_name,
        footprint=ic_data.get("footprint", ""),
        description=ic_data.get("description", ""),
        category="digital",
        pins=pins,
        power_pins={k: v for k, v in power_pins.items() if k},
        pin_nets={k: v for k, v in pin_nets.items() if k},
        bypass_caps=bypass_caps,
        straps=straps,
        annotations=[
            f"CAN transceiver {ic_name}: {ic_data.get('vdd')}V, {ic_data.get('speed_mbps')}Mbps",
            f"Termination: {'split 2x60R + 4.7nF' if termination else 'none'}",
        ],
    )
    comp.source_ref = ref

    return SubcircuitResult(
        components=[comp],
        boundary_ports=[
            BoundaryPort(vdd_net, "input"),
            BoundaryPort("GND", "passive"),
            BoundaryPort(txd_net, "input"),
            BoundaryPort(rxd_net, "output"),
            BoundaryPort(canh_net, "bidirectional"),
            BoundaryPort(canl_net, "bidirectional"),
        ],
        annotations=[
            f"CAN transceiver {ic_name}: {vdd_net} ({ic_data.get('vdd')}V), "
            f"{'terminated' if termination else 'unterminated'}"
        ],
        primary_category="digital",
    )


def build_eeprom(ic_data: dict, params: dict[str, Any]) -> SubcircuitResult:
    """Build I2C EEPROM or SPI flash with legacy-compatible strapping."""
    if ic_data.get("interface") == "spi":
        return _build_spi_eeprom(ic_data, params)
    return _build_i2c_eeprom(ic_data, params)


def _build_i2c_eeprom(ic_data: dict, params: dict[str, Any]) -> SubcircuitResult:
    ic_name = params.get("ic", ic_data.get("_mpn", "24LC256"))
    ref = params.get("ref", "U")
    vdd_net = params.get("vdd_net", "VDD_3P3")
    sda_net = params.get("sda_net", "I2C_SDA")
    scl_net = params.get("scl_net", "I2C_SCL")
    addr_offset = params.get("i2c_addr_offset", 0)
    write_protect = params.get("write_protect", False)

    power_pins = {
        _pin_role(ic_data, "vcc"): vdd_net,
        _pin_role(ic_data, "gnd"): "GND",
    }
    pin_nets = {
        _pin_role(ic_data, "sda"): sda_net,
        _pin_role(ic_data, "scl"): scl_net,
    }
    for i, pin_num in enumerate(ic_data.get("pin_addr", [])):
        power_pins[str(pin_num)] = vdd_net if addr_offset & (1 << i) else "GND"
    pin_wp = _pin_role(ic_data, "wp")
    if pin_wp:
        power_pins[pin_wp] = vdd_net if write_protect else "GND"

    actual_addr = ic_data.get("i2c_base_addr", 0x50) + addr_offset
    comp = ComponentDef(
        mpn=ic_name,
        ref_prefix="U",
        value=ic_name,
        footprint=ic_data.get("footprint", ""),
        description=ic_data.get("description", ""),
        category="digital",
        pins=_pins_from_data(ic_data),
        power_pins={k: v for k, v in power_pins.items() if k},
        pin_nets={k: v for k, v in pin_nets.items() if k},
        bypass_caps=[
            BypassCap("C_VDD", vdd_net, "GND", "100nF", FP_0402C, role="decoupling", presentation="topology_local")
        ],
        annotations=[
            f"EEPROM {ic_name}: {ic_data.get('capacity_kbit')}Kbit I2C",
            f"Address: 0x{actual_addr:02X} (offset={addr_offset})",
        ],
    )
    comp.source_ref = ref
    return SubcircuitResult(
        components=[comp],
        boundary_ports=[
            BoundaryPort(vdd_net, "input"),
            BoundaryPort("GND", "passive"),
            BoundaryPort(sda_net, "bidirectional"),
            BoundaryPort(scl_net, "input"),
        ],
        annotations=[f"EEPROM {ic_name}: {ic_data.get('capacity_kbit')}Kbit, I2C 0x{actual_addr:02X}"],
        primary_category="digital",
    )


def _build_spi_eeprom(ic_data: dict, params: dict[str, Any]) -> SubcircuitResult:
    ic_name = params.get("ic", ic_data.get("_mpn", "AT25SF128A"))
    ref = params.get("ref", "U")
    vdd_net = params.get("vdd_net", "VDD_3P3")
    cs_net = params.get("cs_net", f"FLASH_CS_{ref}")
    mosi_net = params.get("mosi_net", "SPI_MOSI")
    miso_net = params.get("miso_net", "SPI_MISO")
    sclk_net = params.get("sclk_net", "SPI_SCLK")
    write_protect = params.get("write_protect", False)

    power_pins = {
        _pin_role(ic_data, "vcc"): vdd_net,
        _pin_role(ic_data, "gnd"): "GND",
        _pin_role(ic_data, "wp"): "GND" if write_protect else vdd_net,
        _pin_role(ic_data, "hold"): vdd_net,
    }
    pin_nets = {
        _pin_role(ic_data, "cs"): cs_net,
        _pin_role(ic_data, "si"): mosi_net,
        _pin_role(ic_data, "so"): miso_net,
        _pin_role(ic_data, "sck"): sclk_net,
    }
    cap_mbit = ic_data.get("capacity_kbit", 0) // 1024
    comp = ComponentDef(
        mpn=ic_name,
        ref_prefix="U",
        value=ic_name,
        footprint=ic_data.get("footprint", ""),
        description=ic_data.get("description", ""),
        category="digital",
        pins=_pins_from_data(ic_data),
        power_pins={k: v for k, v in power_pins.items() if k},
        pin_nets={k: v for k, v in pin_nets.items() if k},
        bypass_caps=[
            BypassCap("C_VDD", vdd_net, "GND", "100nF", FP_0402C, role="decoupling", presentation="topology_local")
        ],
        annotations=[f"Flash {ic_name}: {cap_mbit}Mbit SPI NOR"],
    )
    comp.source_ref = ref
    return SubcircuitResult(
        components=[comp],
        boundary_ports=[
            BoundaryPort(vdd_net, "input"),
            BoundaryPort("GND", "passive"),
            BoundaryPort(cs_net, "input"),
            BoundaryPort(mosi_net, "input"),
            BoundaryPort(miso_net, "output"),
            BoundaryPort(sclk_net, "input"),
        ],
        annotations=[f"Flash {ic_name}: {cap_mbit}Mbit SPI NOR, CS={cs_net}"],
        primary_category="digital",
    )


def build_protection(ic_data: dict, params: dict[str, Any]) -> SubcircuitResult:
    """Build a passive TVS/ESD protection device without IC decoupling."""
    ic_name = params.get("ic", ic_data.get("_mpn", "SMBJ5.0A"))
    ref = params.get("ref", "D")
    protect_net = params.get("protect_net", "PROTECTED_NET")
    gnd_net = params.get("gnd_net", "GND")
    direction = "bidirectional" if ic_data.get("bidirectional") else "unidirectional"
    comp = ComponentDef(
        mpn=ic_name,
        ref_prefix="D",
        value=ic_name,
        footprint=ic_data.get("footprint", ""),
        description=ic_data.get("description", ""),
        category="protection",
        pins=_pins_from_data(ic_data),
        pin_nets={"1": protect_net, "2": gnd_net},
        annotations=[
            f"Protection: {ic_name} ({direction}) on {protect_net}",
            f"Vrwm={ic_data.get('vrwm')}V, Vbr={ic_data.get('vbr_min')}V, Vc={ic_data.get('vc_max')}V",
        ],
    )
    comp.source_ref = ref
    return SubcircuitResult(
        components=[comp],
        boundary_ports=[BoundaryPort(protect_net, "bidirectional"), BoundaryPort(gnd_net, "passive")],
        annotations=[f"TVS {ic_name} on {protect_net}"],
        primary_category="protection",
    )


# ================================================================
# Generic wiring builder (pin map + decoupling)
# ================================================================


def build_generic(ic_data: dict, params: dict[str, Any]) -> SubcircuitResult:
    """Fallback builder for ICs without specialized topology logic.

    Assigns power pins, wires all non-power signal pins to boundary ports,
    adds standard decoupling, and exports boundary ports.
    Works for: protection, connectors, EEPROM, RTC, display, wireless, etc.
    """
    ic_name = params.get("ic", ic_data.get("_mpn", "UNKNOWN"))
    ref = params.get("ref", "U")
    vdd_net = params.get("vdd_net", "VDD_3P3")

    pins = _pins_from_data(ic_data)

    # Read raw pin_vdd / pin_gnd from ic_data (may be list or scalar)
    raw_vdd = ic_data.get("pin_vdd") or ic_data.get("pin_vcc") or ic_data.get("pin_vin")
    raw_gnd = ic_data.get("pin_gnd")

    power_pins: dict[str, str] = {}

    # Handle pin_vdd as list or scalar
    if raw_vdd:
        if isinstance(raw_vdd, list):
            for p in raw_vdd:
                power_pins[str(p)] = vdd_net
        else:
            power_pins[str(raw_vdd)] = vdd_net

    # Handle pin_gnd as list or scalar
    if raw_gnd:
        if isinstance(raw_gnd, list):
            for p in raw_gnd:
                power_pins[str(p)] = "GND"
        else:
            power_pins[str(raw_gnd)] = "GND"

    # Handle multiple GND pins (pin_gnd_extra as list or scalar)
    for key in ic_data:
        if key.startswith("pin_gnd") and key != "pin_gnd":
            extras = ic_data[key]
            if isinstance(extras, list):
                for p in extras:
                    power_pins[str(p)] = "GND"
            else:
                power_pins[str(extras)] = "GND"

    # Auto-detect additional power pins by name from the pin list
    for pin in pins:
        if pin.number in power_pins:
            continue
        name_upper = pin.name.upper()
        if pin.electrical_type == "power_in":
            if any(
                name_upper == p or name_upper.startswith(f"{p}_") or name_upper == p for p in GROUND_NET_PREFIXES
            ) or name_upper in ("VEE", "SGND", "COM", "V-", "EPAD"):
                power_pins[pin.number] = "GND"
            elif any(
                name_upper == p or name_upper.startswith(f"{p}_") or p in name_upper for p in POWER_NET_PREFIXES
            ) or name_upper in (
                "IN1",
                "IN2",
                "VPLUS",
                "VPOS",
                "V+",
                "AVDDH",
                "AVDDL",
                "DVDDH",
                "DVDDL",
                "DVDDIO",
                "VDDL",
                "VDDA",
            ):
                power_pins[pin.number] = vdd_net

    # Wire all non-power signal pins to per-instance boundary ports
    pin_nets: dict[str, str] = {}
    power_types = {"power_in", "power_out"}
    for pin in pins:
        if pin.number in power_pins:
            continue
        if pin.electrical_type in power_types:
            continue
        # Skip NC / reserved pins
        if pin.name.upper().startswith("NC") or pin.name.upper().startswith("RESERVED"):
            continue
        net_name = f"{pin.name}_{ref}"
        pin_nets[pin.number] = net_name

    bypass_caps = [
        BypassCap(
            str(raw_vdd) if raw_vdd else "VDD",
            vdd_net,
            "GND",
            "100nF",
            FP_0402C,
            role="decoupling",
            presentation="topology_local",
        ),
    ]

    # Detect ref_prefix based on topology / component type
    detected_ref_prefix = "U"
    topo = ic_data.get("topology", "")
    if ic_data.get("connector_type"):
        detected_ref_prefix = "J"
    elif topo == "crystal_oscillator" or "crystal" in ic_data.get("description", "").lower():
        detected_ref_prefix = "Y"
    elif topo == "protection":
        detected_ref_prefix = "D"
    elif topo in ("mosfet_switch",):
        detected_ref_prefix = "Q"
    ref_prefix = ic_data.get("ref_prefix", detected_ref_prefix)
    ic_comp = ComponentDef(
        mpn=ic_name,
        ref_prefix=ref_prefix,
        value=ic_name,
        footprint=ic_data.get("footprint", ""),
        description=ic_data.get("description", ""),
        category=ic_data.get("category", "digital"),
        pins=pins,
        power_pins=power_pins,
        pin_nets=pin_nets,
        bypass_caps=bypass_caps,
        annotations=[f"{ic_data.get('description', ic_name)}"],
    )
    ic_comp.source_ref = ref

    ports = [
        BoundaryPort(vdd_net, "input"),
        BoundaryPort("GND", "passive"),
    ]
    for pin_num, net_name in pin_nets.items():
        ports.append(BoundaryPort(net_name, "bidirectional"))

    return SubcircuitResult(
        components=[ic_comp],
        boundary_ports=ports,
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
    "can_transceiver": build_can_transceiver,
    "eeprom": build_eeprom,
    "protection": build_protection,
}

# All other topologies fall through to build_generic
_GENERIC_TOPOLOGIES = {
    "connector",
    "usb_c_connector",
    "rtc",
    "display_driver",
    "wireless_module",
    "mosfet_switch",
    "relay_driver",
    "gate_driver",
    "led_driver",
    "power_mux",
    "battery_monitor",
    "ethernet_phy",
    "usb_controller",
    "usb_hub",
    "battery_charger",
    "charge_pump",
    "voltage_reference",
    "motor_driver",
    "rs485_transceiver",
    "level_shifter",
    "i2c_bus",
    "spi_bus",
    "adc",
    "dac",
    "current_sense",
    "opamp",
    "sensor_frontend",
    "audio_amplifier",
    "crystal_oscillator",
    "clock_synth",
}

for _topo in _GENERIC_TOPOLOGIES:
    TOPOLOGY_BUILDERS.setdefault(_topo, build_generic)


def get_builder(topology: str):
    """Look up the builder function for a topology."""
    return TOPOLOGY_BUILDERS.get(topology, build_generic)
