"""Tests for firmware_export.py — Tasks 120, 121, 122."""

from __future__ import annotations

import csv

from circuit_weaver.component_db import ComponentDef, PinDef
from circuit_weaver.firmware_export import (
    _esp32_gpio_number,
    _stm32_port_label,
    export_esp32_sdkconfig,
    export_pinout_csv,
    export_stm32_ioc,
    infer_direction,
    infer_peripheral,
    is_mcu,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _esp32_comp(ref: str = "U1") -> ComponentDef:
    return ComponentDef(
        mpn="ESP32-WROOM-32E",
        ref_prefix="U",
        source_ref=ref,
        value="ESP32-WROOM-32E",
        category="digital",
        pins=[
            PinDef("1", "GND", "power_in", "B"),
            PinDef("2", "3V3", "power_in", "T"),
            PinDef("33", "IO21", "bidirectional", "R"),
            PinDef("36", "IO22", "bidirectional", "R"),
            PinDef("34", "RXD0", "input", "L"),
            PinDef("35", "TXD0", "output", "L"),
        ],
        pin_nets={"33": "I2C_SDA", "36": "I2C_SCL", "34": "UART_RX", "35": "UART_TX"},
        power_pins={"1": "GND", "2": "VDD_3P3"},
    )


def _stm32_comp(ref: str = "U2") -> ComponentDef:
    return ComponentDef(
        mpn="STM32F103C8T6",
        ref_prefix="U",
        source_ref=ref,
        value="STM32F103C8T6",
        category="digital",
        pins=[
            PinDef("24", "VSSA", "power_in", "B"),
            PinDef("23", "VDDA", "power_in", "T"),
            PinDef("37", "PA13/SWDIO", "bidirectional", "R"),
            PinDef("34", "PA14/SWCLK", "input", "R"),
            PinDef("42", "PB6/I2C1_SCL", "bidirectional", "R"),
            PinDef("43", "PB7/I2C1_SDA", "bidirectional", "R"),
        ],
        pin_nets={"37": "SWDIO", "34": "SWCLK", "42": "SCL", "43": "SDA"},
        power_pins={"23": "VDD_3P3", "24": "GND"},
    )


def _passive_comp(ref: str = "R1") -> ComponentDef:
    return ComponentDef(
        mpn="RC0402FR-0710KL",
        ref_prefix="R",
        source_ref=ref,
        value="10k",
        pins=[PinDef("1", "~", "passive", "L"), PinDef("2", "~", "passive", "R")],
        pin_nets={"1": "I2C_SDA", "2": "VDD_3P3"},
    )


# ---------------------------------------------------------------------------
# is_mcu
# ---------------------------------------------------------------------------


def test_is_mcu_esp32():
    assert is_mcu(_esp32_comp()) is True


def test_is_mcu_stm32():
    assert is_mcu(_stm32_comp()) is True


def test_is_mcu_passive():
    assert is_mcu(_passive_comp()) is False


def test_is_mcu_rp2040():
    comp = ComponentDef(mpn="RP2040", ref_prefix="U", source_ref="U3")
    assert is_mcu(comp) is True


# ---------------------------------------------------------------------------
# infer_peripheral + infer_direction
# ---------------------------------------------------------------------------


def test_infer_peripheral_i2c():
    assert infer_peripheral("I2C_SDA") == "I2C"
    assert infer_peripheral("SCL") == "I2C"


def test_infer_peripheral_spi():
    assert infer_peripheral("SPI_MOSI") == "SPI"
    assert infer_peripheral("MISO") == "SPI"


def test_infer_peripheral_uart():
    assert infer_peripheral("UART_TX") == "UART"
    assert infer_peripheral("RXD0") == "UART"


def test_infer_peripheral_gpio_fallback():
    assert infer_peripheral("SOME_RANDOM_NET") == "GPIO"


def test_infer_direction_input():
    assert infer_direction("input") == "IN"


def test_infer_direction_power():
    assert infer_direction("power_in") == "PWR"
    assert infer_direction("power_out") == "PWR"


# ---------------------------------------------------------------------------
# Task 120 — Pinout CSV
# ---------------------------------------------------------------------------


def test_export_pinout_csv_mcu_design(tmp_path):
    out = tmp_path / "design_pinout.csv"
    result = export_pinout_csv([_esp32_comp()], out)
    assert result is not None
    assert out.exists()

    with out.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Must have the required columns
    assert "Ref" in rows[0]
    assert "Pin" in rows[0]
    assert "Net" in rows[0]
    assert "Peripheral" in rows[0]
    assert "Direction" in rows[0]


def test_export_pinout_csv_contains_signal_rows(tmp_path):
    out = tmp_path / "design_pinout.csv"
    export_pinout_csv([_esp32_comp()], out)

    with out.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        nets = {r["Net"] for r in reader}

    assert "I2C_SDA" in nets
    assert "I2C_SCL" in nets
    assert "UART_TX" in nets


def test_export_pinout_csv_includes_power_pins(tmp_path):
    out = tmp_path / "design_pinout.csv"
    export_pinout_csv([_esp32_comp()], out)

    with out.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    peripherals = {r["Peripheral"] for r in rows}
    assert "PWR" in peripherals


def test_export_pinout_csv_non_mcu_skipped_by_default(tmp_path):
    out = tmp_path / "design_pinout.csv"
    result = export_pinout_csv([_passive_comp()], out, mcu_only=True)
    assert result is None
    assert not out.exists()


def test_export_pinout_csv_non_mcu_included_when_mcu_only_false(tmp_path):
    out = tmp_path / "design_pinout.csv"
    result = export_pinout_csv([_passive_comp()], out, mcu_only=False)
    assert result is not None


# ---------------------------------------------------------------------------
# Task 121 — STM32 .ioc
# ---------------------------------------------------------------------------


def test_export_stm32_ioc_creates_file(tmp_path):
    out = tmp_path / "project.ioc"
    result = export_stm32_ioc(_stm32_comp(), "MyProject", out)
    assert result is not None
    assert out.exists()


def test_export_stm32_ioc_contains_pin_mappings(tmp_path):
    out = tmp_path / "project.ioc"
    export_stm32_ioc(_stm32_comp(), "MyProject", out)
    content = out.read_text(encoding="utf-8")
    assert "[PinoutTool.PinMappings]" in content
    # PA13 and PA14 should appear (from SWDIO/SWCLK pins)
    assert "PA13=" in content
    assert "PA14=" in content


def test_export_stm32_ioc_skips_non_stm32(tmp_path):
    out = tmp_path / "project.ioc"
    result = export_stm32_ioc(_esp32_comp(), "MyProject", out)
    assert result is None
    assert not out.exists()


# ---------------------------------------------------------------------------
# Task 122 — ESP32 sdkconfig
# ---------------------------------------------------------------------------


def test_export_esp32_sdkconfig_creates_file(tmp_path):
    out = tmp_path / "sdkconfig.defaults"
    result = export_esp32_sdkconfig(_esp32_comp(), "MyProject", out)
    assert result is not None
    assert out.exists()


def test_export_esp32_sdkconfig_correct_gpio_mapping(tmp_path):
    out = tmp_path / "sdkconfig.defaults"
    export_esp32_sdkconfig(_esp32_comp(), "MyProject", out)
    content = out.read_text(encoding="utf-8")
    # IO21 on I2C_SDA net → CONFIG_I2C_SDA_GPIO_NUM=21
    assert "CONFIG_I2C_SDA_GPIO_NUM=21" in content
    # IO22 on I2C_SCL net → CONFIG_I2C_SCL_GPIO_NUM=22
    assert "CONFIG_I2C_SCL_GPIO_NUM=22" in content


def test_export_esp32_sdkconfig_skips_non_esp32(tmp_path):
    out = tmp_path / "sdkconfig.defaults"
    result = export_esp32_sdkconfig(_stm32_comp(), "MyProject", out)
    assert result is None
    assert not out.exists()


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


def test_esp32_gpio_number():
    assert _esp32_gpio_number("IO21") == 21
    assert _esp32_gpio_number("IO0") == 0
    assert _esp32_gpio_number("RXD0") is None
    assert _esp32_gpio_number("GND") is None


def test_stm32_port_label():
    assert _stm32_port_label("PA13/SWDIO") == "PA13"
    assert _stm32_port_label("PB6/I2C1_SCL") == "PB6"
    assert _stm32_port_label("BOOT0") == ""
    assert _stm32_port_label("") == ""
