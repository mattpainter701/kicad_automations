"""OLED/LCD display driver subcircuit template.

Generates a complete display driver subcircuit from design parameters:
interface mode (I2C/SPI), VDD net, resolution, backlight configuration.

Supports SSD1306 (default, 128x64 OLED with charge pump) and ST7789V
(240x320 SPI TFT LCD with optional backlight).
"""

from __future__ import annotations

from typing import Any

from ..component_db import BypassCap, ComponentDef, StrapConfig
from .base import (
    FP_0402R,
    BoundaryPort,
    LegacyDBProxy,
    SubcircuitResult,
    SubcircuitTemplate,
    cap_footprint,
    format_capacitance,
    format_resistance,
    snap_cap,
    snap_to_e24,
    snap_to_e96,
)

# Known display driver ICs and their parameters
DISPLAY_DRIVER_IC_DATABASE = LegacyDBProxy("display_driver")  # backed by ic_data/*.json (Task 178)


class DisplayDriverTemplate(SubcircuitTemplate):
    """OLED/LCD display driver with I2C or SPI interface."""

    template_type = "display_driver"
    description = "OLED/LCD display driver with reset circuit and interface config"
    param_schema = [
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "SSD1306",
            "description": "Display driver IC MPN",
        },
        {
            "name": "ref",
            "type": "string",
            "required": False,
            "default": "U",
            "description": "Reference designator for the IC",
        },
        {
            "name": "interface",
            "type": "string",
            "required": False,
            "default": "i2c",
            "description": "Interface mode: 'i2c' or 'spi'",
        },
        {
            "name": "vdd_net",
            "type": "string",
            "required": False,
            "default": "VDD_3P3",
            "description": "Logic supply net name",
        },
        {
            "name": "resolution",
            "type": "string",
            "required": False,
            "default": "128x64",
            "description": "Display resolution (informational)",
        },
        {
            "name": "backlight",
            "type": "boolean",
            "required": False,
            "default": False,
            "description": "Enable backlight resistor (LCD only)",
        },
        {
            "name": "bl_current",
            "type": "number",
            "required": False,
            "default": 0.020,
            "description": "Backlight LED current in amps",
        },
        {
            "name": "bl_vf",
            "type": "number",
            "required": False,
            "default": 3.0,
            "description": "Backlight LED forward voltage in volts",
        },
    ]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        ic_name = params.get("ic", "SSD1306")
        if ic_name not in DISPLAY_DRIVER_IC_DATABASE:
            errors.append(
                f"Unknown display driver IC '{ic_name}'. Supported: {', '.join(DISPLAY_DRIVER_IC_DATABASE.keys())}"
            )
        interface = params.get("interface", "i2c").lower()
        if interface not in ("i2c", "spi"):
            errors.append(f"interface must be 'i2c' or 'spi', got '{interface}'")
        bl_current = params.get("bl_current", 0.020)
        if bl_current is not None and bl_current <= 0:
            errors.append(f"bl_current ({bl_current}A) must be positive")
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        """Generate a display driver subcircuit.

        Optional params:
            ic: str — IC MPN (default: "SSD1306")
            ref: str — reference designator for IC (default: "U")
            interface: str — 'i2c' or 'spi' (default: "i2c")
            vdd_net: str — logic supply net (default: "VDD_3P3")
            resolution: str — display resolution (default: "128x64")
            backlight: bool — enable backlight resistor (default: False)
            bl_current: float — backlight LED current (A, default: 0.020)
            bl_vf: float — backlight LED forward voltage (V, default: 3.0)
        """
        ic_name = params.get("ic", "SSD1306")
        ref = params.get("ref", "U")
        interface = params.get("interface", "i2c").lower()
        vdd_net = params.get("vdd_net", "VDD_3P3")
        resolution = params.get("resolution", "128x64")
        backlight = params.get("backlight", False)
        bl_current = params.get("bl_current", 0.020)
        bl_vf = params.get("bl_vf", 3.0)

        # Look up IC parameters
        ic_db = DISPLAY_DRIVER_IC_DATABASE.get(ic_name, DISPLAY_DRIVER_IC_DATABASE["SSD1306"])
        display_type = ic_db["display_type"]

        # ---- Net names (unique per instance) ----
        res_n_net = f"RES_N_{ref}"
        dc_net = f"DC_{ref}"
        cs_n_net = f"CS_N_{ref}"
        iref_net = f"IREF_{ref}"
        bl_net = f"BL_{ref}"

        # ---- Build IC component ----
        power_pins: dict[str, str] = {
            ic_db["pin_vdd"]: vdd_net,
            ic_db["pin_gnd"]: "GND",
        }

        # SSD1306 VCC pin: internal charge pump output, tie to VDD
        if ic_db.get("pin_vcc"):
            power_pins[ic_db["pin_vcc"]] = vdd_net

        pin_nets: dict[str, str] = {
            ic_db["pin_res_n"]: res_n_net,
        }

        bypass_caps: list[BypassCap] = []
        straps: list[StrapConfig] = []
        annotations: list[str] = []

        # VDD decoupling: 100nF + 10uF
        cdec_val = snap_cap(100e-9)
        cbulk_val = snap_cap(10e-6)
        bypass_caps.append(
            BypassCap(
                "CVDD",
                vdd_net,
                "GND",
                format_capacitance(cdec_val),
                cap_footprint(cdec_val),
                role="decoupling",
                presentation="topology_local",
            ),
        )
        bypass_caps.append(
            BypassCap(
                "CVDD_BULK",
                vdd_net,
                "GND",
                format_capacitance(cbulk_val),
                cap_footprint(cbulk_val),
                role="bulk_cap",
                presentation="topology_local",
            ),
        )

        # Reset RC circuit: 10k pull-up + 100nF cap -> ~1ms RC delay
        rres_val = snap_to_e96(10e3)
        cres_val = snap_cap(100e-9)
        straps.append(
            StrapConfig(
                "RRES",
                vdd_net,
                res_n_net,
                format_resistance(rres_val),
                FP_0402R,
                role="reset_pullup",
                presentation="topology_local",
            ),
        )
        bypass_caps.append(
            BypassCap(
                "CRES",
                res_n_net,
                "GND",
                format_capacitance(cres_val),
                cap_footprint(cres_val),
                role="reset_delay",
                presentation="topology_local",
            ),
        )
        rc_delay_ms = rres_val * cres_val * 1e3
        annotations.append(
            f"Reset RC delay: {format_resistance(rres_val)} * {format_capacitance(cres_val)} = {rc_delay_ms:.1f}ms"
        )

        # ---- Interface mode wiring ----
        # T228 — honor caller-supplied shared bus net names so designs that
        # name their I2C/SPI buses (e.g. OLED_SDA / OLED_SCL) keep that name
        # all the way through the schematic.
        if interface == "i2c":
            sda_net = params.get("sda_net", "I2C_SDA")
            scl_net = params.get("scl_net", "I2C_SCL")
            pin_nets[ic_db["pin_sda"]] = sda_net
            pin_nets[ic_db["pin_scl"]] = scl_net

            # DC pin: tie to GND for I2C address 0x3C (or VDD for 0x3D)
            pin_nets[ic_db["pin_dc"]] = "GND"

            # CS_N: tie to GND (always selected in I2C mode)
            if ic_db.get("pin_cs_n"):
                pin_nets[ic_db["pin_cs_n"]] = "GND"

            annotations.append("Interface: I2C (DC=GND -> addr 0x3C)")
        else:
            # SPI mode
            mosi_net = params.get("mosi_net", "SPI_MOSI")
            sclk_net = params.get("sclk_net", params.get("sck_net", "SPI_SCLK"))
            pin_nets[ic_db["pin_sda"]] = mosi_net  # SDA doubles as MOSI in SPI
            pin_nets[ic_db["pin_scl"]] = sclk_net  # SCL doubles as SCLK in SPI
            pin_nets[ic_db["pin_dc"]] = dc_net
            if ic_db.get("pin_cs_n"):
                pin_nets[ic_db["pin_cs_n"]] = params.get("cs_net", cs_n_net)

            annotations.append("Interface: SPI (4-wire)")

        # ---- IC-specific passives ----

        if ic_db.get("has_charge_pump"):
            # SSD1306: IREF resistor sets segment current
            riref_val = snap_to_e96(ic_db.get("riref_default", 910e3))
            pin_nets[ic_db["pin_iref"]] = iref_net
            straps.append(
                StrapConfig(
                    "RIREF",
                    iref_net,
                    "GND",
                    format_resistance(riref_val),
                    FP_0402R,
                    role="iref_set",
                    presentation="topology_local",
                ),
            )
            annotations.append(f"IREF: {format_resistance(riref_val)} (segment current set)")

            # Charge pump caps: 2x 2.2uF
            cpump_val = snap_cap(2.2e-6)
            if ic_db.get("pin_c1p"):
                bypass_caps.append(
                    BypassCap(
                        "C1P",
                        ic_db["pin_c1p"],
                        "GND",
                        format_capacitance(cpump_val),
                        cap_footprint(cpump_val),
                        role="charge_pump_cap",
                        presentation="topology_local",
                    ),
                )
                # Wire the C1P pin to its local net for the cap
                c1p_net = f"C1P_{ref}"
                pin_nets[ic_db["pin_c1p"]] = c1p_net
                # Update the cap to use the local net
                bypass_caps[-1] = BypassCap(
                    "C1P",
                    c1p_net,
                    "GND",
                    format_capacitance(cpump_val),
                    cap_footprint(cpump_val),
                    role="charge_pump_cap",
                    presentation="topology_local",
                )

            if ic_db.get("pin_c2p"):
                c2p_net = f"C2P_{ref}"
                pin_nets[ic_db["pin_c2p"]] = c2p_net
                bypass_caps.append(
                    BypassCap(
                        "C2P",
                        c2p_net,
                        "GND",
                        format_capacitance(cpump_val),
                        cap_footprint(cpump_val),
                        role="charge_pump_cap",
                        presentation="topology_local",
                    ),
                )

            annotations.append(f"Charge pump caps: 2x {format_capacitance(cpump_val)}")

            # VCOMH: leave floating (internal connection)
            if ic_db.get("pin_vcomh"):
                vcomh_net = f"VCOMH_{ref}"
                pin_nets[ic_db["pin_vcomh"]] = vcomh_net

        if ic_db.get("has_backlight") and backlight:
            # Backlight resistor: Rbl = (Vdd - Vf) / Ibl
            # Assume VDD is 3.3V for calculation
            vdd_assumed = 3.3
            rbl_raw = (vdd_assumed - bl_vf) / bl_current if bl_current > 0 else 100.0
            rbl_val = snap_to_e24(max(1.0, rbl_raw))

            if ic_db.get("pin_bl"):
                pin_nets[ic_db["pin_bl"]] = bl_net
                straps.append(
                    StrapConfig(
                        "RBL",
                        vdd_net,
                        bl_net,
                        format_resistance(rbl_val),
                        FP_0402R,
                        role="backlight_resistor",
                        presentation="topology_local",
                    ),
                )
                actual_current = (vdd_assumed - bl_vf) / rbl_val if rbl_val > 0 else 0
                annotations.append(
                    f"Backlight: {format_resistance(rbl_val)} "
                    f"(Ibl = ({vdd_assumed}V - {bl_vf}V) / {format_resistance(rbl_val)} "
                    f"= {actual_current * 1e3:.1f}mA)"
                )
        elif ic_db.get("pin_bl") and not backlight:
            # BL pin exists but backlight disabled — leave unconnected or note it
            bl_nc_net = f"BL_NC_{ref}"
            pin_nets[ic_db["pin_bl"]] = bl_nc_net
            annotations.append("Backlight: disabled (BL pin unconnected)")

        # Top-level annotation
        annotations.insert(
            0,
            f"Display {ic_name}: {resolution} {display_type.upper()}, {interface.upper()}",
        )

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

        # ---- Boundary ports ----
        ports = [
            BoundaryPort(vdd_net, "input"),
            BoundaryPort("GND", "passive"),
            BoundaryPort(res_n_net, "input"),
        ]

        if interface == "i2c":
            ports.append(BoundaryPort(params.get("sda_net", "I2C_SDA"), "bidirectional"))
            ports.append(BoundaryPort(params.get("scl_net", "I2C_SCL"), "input"))
        else:
            ports.append(BoundaryPort(params.get("mosi_net", "SPI_MOSI"), "input"))
            ports.append(BoundaryPort(params.get("sclk_net", params.get("sck_net", "SPI_SCLK")), "input"))
            ports.append(BoundaryPort(dc_net, "input"))
            ports.append(BoundaryPort(params.get("cs_net", cs_n_net), "input"))

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[
                f"Display {ic_name}: {resolution} {display_type.upper()}, {interface.upper()} interface",
            ],
            primary_category="digital",
        )
