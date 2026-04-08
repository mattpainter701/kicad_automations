"""Firmware co-design export — Tasks 120, 121, 122.

Emits hardware/firmware contract files alongside schematics:
- ``{project}_pinout.csv``      — universal pinout table (all MCUs)
- ``{project}.ioc``             — STM32CubeMX skeleton (STM32* MPNs)
- ``sdkconfig.defaults``        — ESP-IDF fragment (ESP32* MPNs)
"""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

# MPN prefixes that identify MCU-type components
_MCU_PREFIXES = (
    "STM32",
    "ESP32",
    "ESP8266",
    "RP2040",
    "ATMEGA",
    "ATTINY",
    "PIC",
    "NRF5",
    "EFR32",
    "LPC",
    "SAMD",
    "SAML",
    "SAMC",
    "XMC",
    "MSP430",
)

# Net-name → peripheral inference rules (checked in order, first match wins)
_PERIPHERAL_RULES: list[tuple[list[str], str]] = [
    (["SDA", "I2C_DATA", "I2C_SDA"], "I2C"),
    (["SCL", "I2C_CLK", "I2C_SCL"], "I2C"),
    (["MOSI", "COPI", "SDO"], "SPI"),
    (["MISO", "CIPO", "SDI"], "SPI"),
    (["SCK", "SCLK", "SPI_CLK"], "SPI"),
    (["SPI_CS", "NSS", "SS_N", "CS_N", "SSEL"], "SPI"),
    (["UART", "USART", "RXD", "TXD", "RX0", "TX0", "RX1", "TX1"], "UART"),
    (["CAN_TX", "CAN_RX", "CANRX", "CANTX"], "CAN"),
    (["USB_D", "USB_DP", "USB_DM", "USBP", "USBM"], "USB"),
    (["ADC", "AIN", "VREF_ADC"], "ADC"),
    (["DAC", "VOUT_DAC"], "DAC"),
    (["PWM", "TIM", "CCR"], "TIM"),
    (["SWDIO", "SWDCLK", "JTAG", "TCK", "TMS", "TDI", "TDO"], "DEBUG"),
    (["IRQ", "INT", "_INT", "ALERT", "EXTI"], "GPIO_INT"),
    (["RESET", "NRST", "RST_N", "RESET_N"], "RESET"),
    (["BOOT", "BOOT0", "BOOT1"], "BOOT"),
    (["EN", "ENABLE", "_EN", "SHDN"], "GPIO"),
    (["LED"], "GPIO"),
    (["GND", "AGND", "DGND", "PGND", "VDD", "VCC", "VBUS", "VIN", "VDDA"], "PWR"),
]

# PinDef electrical type → Direction column
_DIRECTION_MAP: dict[str, str] = {
    "input": "IN",
    "output": "OUT",
    "bidirectional": "IO",
    "power_in": "PWR",
    "power_out": "PWR",
    "passive": "IO",
    "open_collector": "OUT_OC",
    "open_emitter": "OUT_OE",
    "3state": "OUT_3ST",
    "no_connect": "NC",
}

# ESP32 sdkconfig: net-name fragment → CONFIG key prefix
_ESP32_CONFIG_RULES: list[tuple[list[str], str]] = [
    (["I2C_SDA", "SDA"], "I2C_SDA"),
    (["I2C_SCL", "SCL"], "I2C_SCL"),
    (["SPI_MOSI", "MOSI", "COPI"], "SPI_MOSI"),
    (["SPI_MISO", "MISO", "CIPO"], "SPI_MISO"),
    (["SPI_CLK", "SCK", "SCLK"], "SPI_CLK"),
    (["SPI_CS", "NSS", "CS"], "SPI_CS"),
    (["UART_TX", "TXD", "TX"], "UART_TX"),
    (["UART_RX", "RXD", "RX"], "UART_RX"),
    (["ADC"], "ADC"),
    (["CAN_TX", "CANTX"], "TWAI_TX"),
    (["CAN_RX", "CANRX"], "TWAI_RX"),
]


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def is_mcu(comp: Any) -> bool:
    """Return True if *comp* looks like an MCU based on its MPN prefix."""
    mpn = (comp.mpn or "").upper()
    return any(mpn.startswith(p) for p in _MCU_PREFIXES)


def infer_peripheral(net: str) -> str:
    """Infer peripheral type from a net name string."""
    net_up = net.upper()
    for keywords, peripheral in _PERIPHERAL_RULES:
        if any(k in net_up for k in keywords):
            return peripheral
    return "GPIO"


def infer_direction(pin_type: str) -> str:
    """Map a PinDef electrical type string to a Direction column value."""
    return _DIRECTION_MAP.get(pin_type.lower(), "IO")


# ---------------------------------------------------------------------------
# Task 120 — Pinout CSV
# ---------------------------------------------------------------------------


def export_pinout_csv(
    components: list[Any],
    output_path: str | Path,
    *,
    mcu_only: bool = True,
) -> Path | None:
    """Write ``{project}_pinout.csv`` for MCU-type components.

    Returns the output path on success, or None if no qualifying components
    were found and *mcu_only* is True.
    """
    output_path = Path(output_path)
    pin_map: dict[str, tuple[str, str]] = {}  # pin_num → (name, elec_type)

    qualifying = [c for c in components if (not mcu_only or is_mcu(c))]
    if not qualifying:
        _logger.debug("No MCU components found — pinout CSV not written")
        return None

    rows: list[dict[str, str]] = []

    for comp in qualifying:
        ref = comp.source_ref or comp.ref_prefix

        # Build pin_num → (pin_name, elec_type) lookup from PinDef list
        pin_map = {p.number: (p.name, p.electrical_type) for p in (comp.pins or [])}

        # Signal pins from pin_nets
        for pin_num, net in sorted((comp.pin_nets or {}).items(), key=lambda x: _sort_key(x[0])):
            pin_name, elec_type = pin_map.get(pin_num, ("", "bidirectional"))
            rows.append(
                {
                    "Ref": ref,
                    "Pin": pin_num,
                    "PinName": pin_name,
                    "Net": net,
                    "Peripheral": infer_peripheral(net),
                    "Direction": infer_direction(elec_type),
                }
            )

        # Power pins
        for pin_num, net in sorted((comp.power_pins or {}).items(), key=lambda x: _sort_key(x[0])):
            pin_name, elec_type = pin_map.get(pin_num, ("", "power_in"))
            rows.append(
                {
                    "Ref": ref,
                    "Pin": pin_num,
                    "PinName": pin_name,
                    "Net": net,
                    "Peripheral": "PWR",
                    "Direction": infer_direction(elec_type),
                }
            )

    if not rows:
        _logger.debug("MCU components present but no pin_nets/power_pins — pinout CSV not written")
        return None

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["Ref", "Pin", "PinName", "Net", "Peripheral", "Direction"]
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    _logger.info("Pinout CSV written: %s (%d rows)", output_path, len(rows))
    return output_path


def _sort_key(pin_num: str) -> tuple[int, str]:
    """Sort pin numbers numerically when possible, lexicographically otherwise."""
    try:
        return (int(pin_num), "")
    except ValueError:
        return (9999, pin_num)


# ---------------------------------------------------------------------------
# Task 121 — STM32 .ioc skeleton
# ---------------------------------------------------------------------------


def export_stm32_ioc(
    comp: Any,
    project_name: str,
    output_path: str | Path,
) -> Path | None:
    """Emit a STM32CubeMX .ioc skeleton for *comp* if it is a STM32 MCU.

    Populates ``[PinoutTool.PinMappings]`` from the component's ``pin_nets``.
    Pin labels are taken from the ``PinDef.name`` field (e.g., ``PA13/SWDIO``
    → ``PA13``).  Returns None if the component is not an STM32 part.
    """
    if not comp.mpn.upper().startswith("STM32"):
        return None

    output_path = Path(output_path)
    pin_map = {p.number: p.name for p in (comp.pins or [])}

    mappings: list[str] = []
    for pin_num, net in sorted((comp.pin_nets or {}).items(), key=lambda x: _sort_key(x[0])):
        label = _stm32_port_label(pin_map.get(pin_num, ""))
        if not label:
            continue
        signal = _stm32_signal_from_net(net, label)
        mappings.append(f"{label}={signal}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# STM32CubeMX .ioc skeleton — auto-generated by circuit-weaver",
        f"# Project: {project_name}  Component: {comp.source_ref or comp.mpn}",
        "",
        "[PinoutTool.PinMappings]",
        *mappings,
        "",
        "[Mcu]",
        f"Name={comp.mpn}",
        "",
    ]
    output_path.write_text("\n".join(lines), encoding="utf-8")
    _logger.info("STM32 .ioc written: %s", output_path)
    return output_path


def _stm32_port_label(pin_name: str) -> str:
    """Extract port label (e.g., 'PA13') from a pin name like 'PA13/SWDIO'."""
    if not pin_name:
        return ""
    label = pin_name.split("/")[0].strip()
    # Must match P<letter><digits> pattern (PA0, PB12, PC6, …)
    if re.match(r"^P[A-Z]\d{1,2}$", label):
        return label
    return ""


def _stm32_signal_from_net(net: str, port_label: str) -> str:
    """Map a net name to a STM32CubeMX peripheral signal string."""
    net_up = net.upper()
    mappings = [
        (["SWDIO", "SWDCLK", "JTAG"], lambda: f"SYS_{net_up}"),
        (["RESET", "NRST"], lambda: "SYS_RESET"),
        (["UART1_TX", "USART1_TX"], lambda: "USART1_TX"),
        (["UART1_RX", "USART1_RX"], lambda: "USART1_RX"),
        (["UART2_TX", "USART2_TX"], lambda: "USART2_TX"),
        (["UART2_RX", "USART2_RX"], lambda: "USART2_RX"),
        (["I2C1_SDA", "I2C_SDA", "SDA"], lambda: "I2C1_SDA"),
        (["I2C1_SCL", "I2C_SCL", "SCL"], lambda: "I2C1_SCL"),
        (["SPI1_MOSI", "MOSI", "COPI"], lambda: "SPI1_MOSI"),
        (["SPI1_MISO", "MISO", "CIPO"], lambda: "SPI1_MISO"),
        (["SPI1_SCK", "SCK", "SCLK"], lambda: "SPI1_SCK"),
        (["ADC"], lambda: f"ADC1_IN{_extract_number(net)}"),
        (["TIM", "PWM"], lambda: f"TIM1_CH{_extract_number(net) or '1'}"),
    ]
    for keywords, signal_fn in mappings:
        if any(k in net_up for k in keywords):
            return signal_fn()
    # Default: generic GPIO output
    return "GPIO_Output"


def _extract_number(s: str) -> str:
    m = re.search(r"\d+", s)
    return m.group() if m else ""


# ---------------------------------------------------------------------------
# Task 122 — ESP32 sdkconfig.defaults fragment
# ---------------------------------------------------------------------------


def export_esp32_sdkconfig(
    comp: Any,
    project_name: str,
    output_path: str | Path,
) -> Path | None:
    """Emit an ESP-IDF ``sdkconfig.defaults`` fragment for *comp*.

    GPIO numbers are extracted from ESP32 pin names (``IO21`` → GPIO 21).
    Returns None if the component is not an ESP32 part.
    """
    if not comp.mpn.upper().startswith("ESP32"):
        return None

    output_path = Path(output_path)
    pin_map = {p.number: p.name for p in (comp.pins or [])}

    config_lines: list[str] = []
    for pin_num, net in sorted((comp.pin_nets or {}).items(), key=lambda x: _sort_key(x[0])):
        pin_name = pin_map.get(pin_num, "")
        gpio_num = _esp32_gpio_number(pin_name)
        if gpio_num is None:
            continue
        config_key = _esp32_config_key(net)
        if config_key:
            config_lines.append(f"CONFIG_{config_key}_GPIO_NUM={gpio_num}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "# sdkconfig.defaults — auto-generated by circuit-weaver",
        f"# Project: {project_name}  Component: {comp.source_ref or comp.mpn}",
        "# Review and adjust before use.",
        "",
    ]
    output_path.write_text("\n".join(header + sorted(set(config_lines)) + [""]), encoding="utf-8")
    _logger.info("ESP32 sdkconfig.defaults written: %s", output_path)
    return output_path


def _esp32_gpio_number(pin_name: str) -> int | None:
    """Extract GPIO number from ESP32 pin name (IO21 → 21, RXD0 → None)."""
    m = re.match(r"^IO(\d+)$", pin_name.upper())
    return int(m.group(1)) if m else None


def _esp32_config_key(net: str) -> str | None:
    """Map a net name to an ESP-IDF CONFIG key fragment."""
    net_up = net.upper()
    for keywords, key in _ESP32_CONFIG_RULES:
        if any(k in net_up for k in keywords):
            return key
    return None
