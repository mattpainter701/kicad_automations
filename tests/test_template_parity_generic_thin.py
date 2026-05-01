"""Regression coverage for deleted verdict-A legacy templates."""

from __future__ import annotations

from circuit_weaver.subcircuits.base import DataDrivenTemplate, get_default_registry


def _template(topology: str) -> DataDrivenTemplate:
    template = get_default_registry().get(topology)
    assert isinstance(template, DataDrivenTemplate)
    return template


def test_can_transceiver_builder_preserves_legacy_nets_and_options():
    result = _template("can_transceiver").generate(
        {
            "ic": "SN65HVD230",
            "ref": "U7",
            "txd_net": "MCU_CAN_TX",
            "rxd_net": "MCU_CAN_RX",
            "bus_net_prefix": "FIELD_CAN",
            "termination": True,
            "slope_control": True,
        }
    )

    comp = result.components[0]
    assert comp.power_pins == {"3": "VDD_3P3", "2": "GND"}
    assert comp.pin_nets["1"] == "MCU_CAN_TX"
    assert comp.pin_nets["4"] == "MCU_CAN_RX"
    assert comp.pin_nets["7"] == "FIELD_CAN_H_U7"
    assert comp.pin_nets["6"] == "FIELD_CAN_L_U7"
    assert comp.pin_nets["8"] == "CAN_RS_U7"
    assert {s.role for s in comp.straps} == {"slope_control", "termination"}
    assert any(c.role == "termination" for c in comp.bypass_caps)
    assert {p.name for p in result.boundary_ports} >= {"FIELD_CAN_H_U7", "FIELD_CAN_L_U7"}


def test_eeprom_i2c_builder_preserves_address_and_wp_strapping():
    result = _template("eeprom").generate(
        {"ic": "24LC256", "i2c_addr_offset": 5, "write_protect": True, "sda_net": "SDA0", "scl_net": "SCL0"}
    )

    comp = result.components[0]
    assert comp.power_pins["1"] == "VDD_3P3"
    assert comp.power_pins["2"] == "GND"
    assert comp.power_pins["3"] == "VDD_3P3"
    assert comp.power_pins["7"] == "VDD_3P3"
    assert comp.pin_nets == {"5": "SDA0", "6": "SCL0"}


def test_eeprom_spi_builder_preserves_wp_hold_and_bus_nets():
    result = _template("eeprom").generate(
        {"ic": "AT25SF128A", "ref": "U9", "cs_net": "FLASH0_CS", "write_protect": False}
    )

    comp = result.components[0]
    assert comp.power_pins["3"] == "VDD_3P3"
    assert comp.power_pins["7"] == "VDD_3P3"
    assert comp.pin_nets["1"] == "FLASH0_CS"
    assert comp.pin_nets["5"] == "SPI_MOSI"
    assert comp.pin_nets["2"] == "SPI_MISO"
    assert comp.pin_nets["6"] == "SPI_SCLK"


def test_protection_builder_preserves_passive_device_contract():
    result = _template("protection").generate({"ic": "SMBJ5.0A", "ref": "D5", "protect_net": "VBUS"})

    comp = result.components[0]
    assert comp.ref_prefix == "D"
    assert comp.power_pins == {}
    assert comp.pin_nets == {"1": "VBUS", "2": "GND"}
    assert comp.bypass_caps == []
    assert result.validate_contract() == []
