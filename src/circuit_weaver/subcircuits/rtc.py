"""Real-time clock (RTC) subcircuit template.

Generates a complete RTC subcircuit with backup battery input, crystal,
load capacitors, and I2C pull-up/decoupling.

Supports DS3231 (integrated TCXO, default) and PCF8523 (external crystal).
Auto-calculates crystal load caps for PCF8523.
"""

from __future__ import annotations

from typing import Any

from ..component_db import BypassCap, ComponentDef, PinDef, StrapConfig
from .base import (
    BoundaryPort,
    FP_0402C,
    FP_0402R,
    LegacyDBProxy,
    SubcircuitResult,
    SubcircuitTemplate,
    crystal_load_caps,
    format_capacitance,
    format_resistance,
    snap_cap,
    snap_to_e24,
)

RTC_IC_DATABASE = LegacyDBProxy("rtc")  # backed by ic_data/*.json (Task 178)


class RTCTemplate(SubcircuitTemplate):
    """Real-time clock with backup battery, optional crystal, and I2C."""

    template_type = "rtc"
    description = "Real-time clock with backup battery and I2C interface"
    param_schema = [
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "DS3231",
            "description": "RTC IC MPN",
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
            "description": "Main supply net name",
        },
        {
            "name": "vbat_net",
            "type": "string",
            "required": False,
            "default": "VBAT_RTC",
            "description": "Backup battery net name",
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
            "name": "int_net",
            "type": "string",
            "required": False,
            "description": "Interrupt/alarm output net name",
        },
    ]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        ic_name = params.get("ic", "DS3231")
        if ic_name not in RTC_IC_DATABASE:
            errors.append(
                f"Unknown RTC IC '{ic_name}'. "
                f"Available: {', '.join(RTC_IC_DATABASE)}"
            )
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        ic_name = params.get("ic", "DS3231")
        ic_db = RTC_IC_DATABASE.get(ic_name, RTC_IC_DATABASE["DS3231"])
        ref = params.get("ref", "U")
        vdd_net = params.get("vdd_net", "VDD_3P3")
        vbat_net = params.get("vbat_net", "VBAT_RTC")
        sda_net = params.get("sda_net", "I2C_SDA")
        scl_net = params.get("scl_net", "I2C_SCL")
        int_net = params.get("int_net", f"RTC_INT_{ref}")

        power_pins: dict[str, str] = {
            ic_db["pin_vcc"]: vdd_net,
            ic_db["pin_gnd"]: "GND",
            ic_db["pin_vbat"]: vbat_net,
        }

        pin_nets: dict[str, str] = {
            ic_db["pin_sda"]: sda_net,
            ic_db["pin_scl"]: scl_net,
            ic_db["pin_int"]: int_net,
        }

        bypass_caps: list[BypassCap] = [
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

        straps: list[StrapConfig] = []
        annotations: list[str] = [
            f"RTC {ic_name}: I2C addr 0x{ic_db['i2c_addr']:02X}",
        ]
        explicit_nc: set[str] = set()

        if ic_name == "DS3231":
            # DS3231 has integrated TCXO — no external crystal needed.
            # RST_N: pull up to VCC
            rst_net = f"RTC_RST_{ref}"
            pin_nets[ic_db["pin_rst"]] = rst_net
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
            # 32KHZ output — export as boundary port
            pin_nets[ic_db["pin_32k"]] = f"RTC_32K_{ref}"
            # Mark NC pins
            for pin in ic_db["pins"]:
                if pin.name == "NC":
                    explicit_nc.add(pin.number)
            annotations.append("Integrated TCXO — no external crystal needed")
            annotations.append(f"VBAT={vbat_net} for backup (CR2032 coin cell)")

        elif ic_name == "PCF8523":
            # PCF8523 needs external 32.768 kHz crystal + load caps
            xtal_cl = ic_db["xtal_cl"]
            cl_ext = crystal_load_caps(xtal_cl, 3e-12)
            cl_ext_snapped = snap_cap(cl_ext)

            osci_net = f"OSCI_{ref}"
            osco_net = f"OSCO_{ref}"
            pin_nets[ic_db["pin_osci"]] = osci_net
            pin_nets[ic_db["pin_osco"]] = osco_net

            bypass_caps.extend([
                BypassCap(
                    "CL1",
                    osci_net,
                    "GND",
                    format_capacitance(cl_ext_snapped),
                    FP_0402C,
                    role="crystal_load",
                    presentation="topology_local",
                ),
                BypassCap(
                    "CL2",
                    osco_net,
                    "GND",
                    format_capacitance(cl_ext_snapped),
                    FP_0402C,
                    role="crystal_load",
                    presentation="topology_local",
                ),
            ])
            annotations.append(
                f"External 32.768kHz crystal, CL={format_capacitance(cl_ext_snapped)}"
            )
            annotations.append(f"VBAT={vbat_net} for backup")

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

        ports = [
            BoundaryPort(vdd_net, "input"),
            BoundaryPort(vbat_net, "input"),
            BoundaryPort("GND", "passive"),
            BoundaryPort(sda_net, "bidirectional"),
            BoundaryPort(scl_net, "input"),
            BoundaryPort(int_net, "output"),
        ]
        if ic_name == "DS3231":
            ports.append(BoundaryPort(f"RTC_32K_{ref}", "output"))

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[f"RTC {ic_name}: I2C, VBAT={vbat_net}"],
            primary_category="digital",
        )
