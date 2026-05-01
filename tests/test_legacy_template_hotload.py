"""Sprint 37 Task 158 — legacy template hot-load regression test.

The three pre-Sprint-34 template modules still carry their own hardcoded
``*_IC_DATABASE`` dicts. In v0.26.0 we added a lightweight bridge so
entries registered at runtime via :func:`register_ic` also reach the
legacy template's own IC database. This test locks that invariant in.
"""

from __future__ import annotations

import pytest

from circuit_weaver.ic_data import register_ic
from circuit_weaver.ic_data import reload as reload_ic_data


@pytest.fixture(autouse=True)
def _clean_ic_data():
    reload_ic_data()
    yield
    reload_ic_data()


def test_audio_amplifier_hotload_via_register_ic():
    """A user register_ic() call on an 'audio_amplifier' topology must
    be picked up by AudioAmplifierTemplate._ic_db() without reimport."""
    from circuit_weaver.subcircuits.audio_amplifier import (
        AUDIO_AMP_IC_DATABASE,
        AudioAmplifierTemplate,
    )

    original_keys = set(AUDIO_AMP_IC_DATABASE)
    # Make sure the hot-loaded MPN isn't already there.
    hot_mpn = "TEST-HOT-AMP-99"
    assert hot_mpn not in original_keys

    register_ic(
        hot_mpn,
        {
            "topology": "audio_amplifier",
            "description": "Test hot-loaded amp",
            "footprint": "SOIC-8",
            "vdd_min": 2.5,
            "vdd_max": 5.5,
            "output_power_w": 1.0,
            "speaker_impedance": 8,
            "gain_db": 18,
            "filterless": False,
            "interface": "analog",
            "r_in": 10000,
            "pins": [
                {"number": "1", "name": "VDD", "type": "power_in", "side": "T"},
                {"number": "2", "name": "GND", "type": "power_in", "side": "B"},
                {"number": "3", "name": "INP", "type": "input", "side": "L"},
            ],
            "pin_vdd": "1",
            "pin_gnd": "2",
            "pin_sd": "3",
            "pin_inp": "3",
            "pin_inn": "3",
            "pin_vop": "3",
            "pin_von": "3",
        },
        persist=False,
    )

    merged = AudioAmplifierTemplate._ic_db()
    assert hot_mpn in merged, "register_ic() entry must appear in merged DB"
    # Legacy entries remain.
    for k in original_keys:
        assert k in merged, f"legacy IC {k} must survive the merge"


def test_motor_driver_hotload_via_register_ic():
    from circuit_weaver.subcircuits.motor_driver import (
        MOTOR_DRIVER_IC_DATABASE,
        MotorDriverTemplate,
    )

    register_ic(
        "TEST-HOT-MOTOR-99",
        {
            "topology": "motor_driver",
            "description": "Test hot-loaded motor driver",
            "vin_range": [4.5, 18],
            "ipeak": 2.0,
            "pins": [
                {"number": "1", "name": "VM", "type": "power_in", "side": "T"},
                {"number": "2", "name": "GND", "type": "power_in", "side": "B"},
            ],
        },
        persist=False,
    )
    merged = MotorDriverTemplate._ic_db()
    assert "TEST-HOT-MOTOR-99" in merged
    assert set(MOTOR_DRIVER_IC_DATABASE).issubset(merged)


def test_protection_hotload_via_register_ic():
    from circuit_weaver.ic_data import get_all_ics

    register_ic(
        "TEST-HOT-TVS-99",
        {
            "topology": "protection",
            "description": "Test hot-loaded TVS",
            "vrwm": 5.0,
            "vbr_min": 6.4,
            "vc_max": 9.2,
            "bidirectional": False,
            "pins": [
                {"number": "1", "name": "A", "type": "passive", "side": "L"},
                {"number": "2", "name": "K", "type": "passive", "side": "R"},
            ],
        },
        persist=False,
    )
    merged = get_all_ics("protection")
    assert "TEST-HOT-TVS-99" in merged
    assert "SMBJ5.0A" in merged


def test_usb_controller_hotload_via_register_ic():
    """Sprint 41 Task 176: a user register_ic() call on a
    'usb_controller' topology must be visible to
    USBControllerTemplate._ic_db() — otherwise the user's pin map is
    silently ignored and the resulting net-connectivity check flags
    USB_DP as dangling (toy_phone RP2040 regression)."""
    from circuit_weaver.subcircuits.usb import (
        USB_CONTROLLER_IC_DATABASE,
        USBControllerTemplate,
    )

    hot_mpn = "TEST-USB-MCU-99"
    assert hot_mpn not in USB_CONTROLLER_IC_DATABASE

    register_ic(
        hot_mpn,
        {
            "topology": "usb_controller",
            "description": "Test hot-loaded USB-capable MCU",
            "footprint": "Package_DFN_QFN:QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm",
            "power_rails": {"IOVDD": 3.3, "USB_VDD": 3.3},
            "pins": [
                {"number": "1", "name": "IOVDD", "type": "power_in", "side": "T"},
                {"number": "43", "name": "USB_DP", "type": "bidirectional", "side": "L"},
                {"number": "44", "name": "USB_DM", "type": "bidirectional", "side": "L"},
                {"number": "45", "name": "GND", "type": "power_in", "side": "B"},
            ],
            "pin_vdd": ["1"],
            "pin_gnd": ["45"],
            "pin_usb_dp": "43",
            "pin_usb_dm": "44",
            "data_buses": ["USB"],
        },
        persist=False,
    )

    merged = USBControllerTemplate._ic_db()
    assert hot_mpn in merged, "register_ic() entry must appear in merged USB controller DB"
    for k in USB_CONTROLLER_IC_DATABASE:
        assert k in merged, f"legacy IC {k} must survive the merge"


def test_usb_controller_generate_wires_registered_ic_usb_pins():
    """End-to-end: after registering a new usb_controller IC with
    ``pin_usb_dp: "43"`` / ``pin_usb_dm: "44"``, the template's
    generate() must produce a ComponentDef where pin 43 maps to the
    requested USB_DP net (not ``USB_DP_<ref>`` or silently missing).

    Without this, the net-connectivity validator sees USB_DP as
    single-pin because the USB-C receptacle's DP pin is the only
    endpoint on the net. That's the user-facing "USB_DP dangling"
    warning the toy_phone RP2040 flow tripped.
    """
    from circuit_weaver.subcircuits.usb import USBControllerTemplate

    register_ic(
        "TEST-USB-MCU-GEN",
        {
            "topology": "usb_controller",
            "description": "Test hot-loaded MCU with USB",
            "footprint": "Package_DFN_QFN:QFN-56",
            "power_rails": {"IOVDD": 3.3},
            "pins": [
                {"number": "1", "name": "IOVDD", "type": "power_in", "side": "T"},
                {"number": "43", "name": "USB_DP", "type": "bidirectional", "side": "L"},
                {"number": "44", "name": "USB_DM", "type": "bidirectional", "side": "L"},
                {"number": "45", "name": "GND", "type": "power_in", "side": "B"},
            ],
            "pin_vdd": ["1"],
            "pin_gnd": ["45"],
            "pin_usb_dp": "43",
            "pin_usb_dm": "44",
            "data_buses": ["USB"],
        },
        persist=False,
    )

    tpl = USBControllerTemplate()
    errors = tpl.validate_params(
        {
            "ic": "TEST-USB-MCU-GEN",
            "ref": "U1",
            "usb_dp_net": "USB_DP",
            "usb_dm_net": "USB_DM",
        }
    )
    assert errors == [], f"validate_params should accept a registered IC, got: {errors}"

    result = tpl.generate(
        {
            "ic": "TEST-USB-MCU-GEN",
            "ref": "U1",
            "usb_dp_net": "USB_DP",
            "usb_dm_net": "USB_DM",
            "vdd_net": "VCC3V3",
        }
    )
    assert len(result.components) >= 1
    ic_comp = result.components[0]
    assert ic_comp.mpn == "TEST-USB-MCU-GEN"
    assert ic_comp.pin_nets.get("43") == "USB_DP", (
        f"pin 43 must be wired to USB_DP (pin_usb_dp field from registration), got {ic_comp.pin_nets!r}"
    )
    assert ic_comp.pin_nets.get("44") == "USB_DM", (
        f"pin 44 must be wired to USB_DM (pin_usb_dm field from registration), got {ic_comp.pin_nets!r}"
    )


def test_connector_hotload_via_register_ic():
    """Sprint 41 Task 176: connector template accepts ic_data hot-loads."""
    from circuit_weaver.subcircuits.connector import CONNECTOR_DATABASE, ConnectorTemplate

    register_ic(
        "TEST-CONN-99",
        {
            "topology": "connector",
            "description": "Test hot-loaded connector",
            "footprint": "Connector_Test:Fake",
            "connector_type": "generic",
            "pins": [
                {"number": "1", "name": "P1", "type": "passive", "side": "R"},
                {"number": "2", "name": "P2", "type": "passive", "side": "R"},
            ],
        },
        persist=False,
    )
    merged = ConnectorTemplate._ic_db()
    assert "TEST-CONN-99" in merged
    assert set(CONNECTOR_DATABASE).issubset(merged)


def test_usb_c_connector_hotload_via_register_ic():
    """Sprint 41 Task 176: usb_c_connector template accepts ic_data hot-loads."""
    from circuit_weaver.subcircuits.usb_c_connector import (
        USB_C_CONNECTOR_DATABASE,
        USBCConnectorTemplate,
    )

    register_ic(
        "TEST-USBC-99",
        {
            "topology": "usb_c_connector",
            "description": "Test hot-loaded USB-C connector",
            "footprint": "USB_C_Test:Fake",
            "pins": [
                {"number": "A1", "name": "GND", "type": "power_in", "side": "B"},
                {"number": "A4", "name": "VBUS", "type": "power_in", "side": "T"},
                {"number": "A5", "name": "CC1", "type": "bidirectional", "side": "L"},
                {"number": "A6", "name": "DP1", "type": "bidirectional", "side": "R"},
                {"number": "A7", "name": "DN1", "type": "bidirectional", "side": "R"},
            ],
        },
        persist=False,
    )
    merged = USBCConnectorTemplate._ic_db()
    assert "TEST-USBC-99" in merged
    assert set(USB_C_CONNECTOR_DATABASE).issubset(merged)


def test_eeprom_hotload_via_register_ic():
    """Sprint 41 Task 176: eeprom template accepts ic_data hot-loads."""
    from circuit_weaver.ic_data import get_all_ics

    register_ic(
        "TEST-EEPROM-99",
        {
            "topology": "eeprom",
            "description": "Test hot-loaded EEPROM",
            "footprint": "Package_SO:SOIC-8",
            "interface": "i2c",
            "capacity_kbit": 128,
            "i2c_base_addr": 0x50,
            "vdd_range": (2.5, 5.5),
            "pins": [
                {"number": "1", "name": "A0", "type": "input", "side": "L"},
                {"number": "2", "name": "A1", "type": "input", "side": "L"},
                {"number": "3", "name": "A2", "type": "input", "side": "L"},
                {"number": "4", "name": "VSS", "type": "power_in", "side": "B"},
                {"number": "5", "name": "SDA", "type": "bidirectional", "side": "R"},
                {"number": "6", "name": "SCL", "type": "input", "side": "R"},
                {"number": "7", "name": "WP", "type": "input", "side": "L"},
                {"number": "8", "name": "VCC", "type": "power_in", "side": "T"},
            ],
            "pin_vcc": "8",
            "pin_gnd": "4",
            "pin_sda": "5",
            "pin_scl": "6",
            "pin_wp": "7",
            "pin_addr": ["1", "2", "3"],
        },
        persist=False,
    )
    merged = get_all_ics("eeprom")
    assert "TEST-EEPROM-99" in merged
    assert "24LC256" in merged


def test_generate_uses_hotloaded_ic():
    """End-to-end: data-driven protection generation accepts registered ICs."""
    from circuit_weaver.subcircuits.base import get_default_registry

    register_ic(
        "TEST-GEN-TVS",
        {
            "topology": "protection",
            "description": "Test generated TVS",
            "footprint": "Diode_SMD:D_SMB",
            "vrwm": 5.0,
            "vbr_min": 6.4,
            "vc_max": 9.2,
            "bidirectional": True,
            "pins": [
                {"number": "1", "name": "A", "type": "passive", "side": "L"},
                {"number": "2", "name": "K", "type": "passive", "side": "R"},
            ],
        },
        persist=False,
    )

    tpl = get_default_registry().get("protection")
    result = tpl.generate({"ic": "TEST-GEN-TVS", "protect_net": "VBUS"})
    assert len(result.components) >= 1
    assert result.components[0].mpn == "TEST-GEN-TVS"
