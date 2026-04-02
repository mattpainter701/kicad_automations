"""Pre-built component library — common MCUs, regulators, sensors, connectors.

Downloads pin definitions from KiCad's official symbol library (GitLab),
then adds datasheet-derived bypass caps, strap resistors, and power requirements
that can't be inferred from pin definitions alone.

Usage:
    from schematic_engine.library import build_standard_library
    registry = build_standard_library()
    comp = registry.get("ESP32-WROOM-32E")
"""

from .component_db import (
    BUILTIN_REGISTRY,
    BypassCap,
    ComponentRegistry,
    PowerReq,
    StrapConfig,
)
from .kicad_lib import KiCadLibrary

# Components to download from KiCad's official library.
# Format: (kicad_lib_name, symbol_name, category, overrides_dict)
# overrides_dict can set bypass_caps, straps, power_reqs, description, etc.
STANDARD_COMPONENTS = [
    # ---- MCUs ----
    # Note: ESP32-WROOM-32E is in RF_Module, not MCU_Espressif
    ("MCU_Microchip_ATmega", "ATmega328P-AU", "digital", {
        "description": "8-bit AVR MCU 32KB Flash (Arduino Uno)",
        "power_reqs": [PowerReq("VCC", 5.0, 200)],
        "bypass_caps": [
            BypassCap("7", "VCC", "GND", "100nF", "Capacitor_SMD:C_0402_1005Metric"),
            BypassCap("20", "AVCC", "GND", "100nF", "Capacitor_SMD:C_0402_1005Metric"),
        ],
    }),
    ("MCU_ST_STM32F1", "STM32F103C8Tx", "digital", {
        "description": "ARM Cortex-M3 MCU 64KB Flash (Blue Pill)",
        "power_reqs": [PowerReq("VDD", 3.3, 150)],
        "bypass_caps": [
            BypassCap("24", "VDD", "GND", "100nF", "Capacitor_SMD:C_0402_1005Metric"),
            BypassCap("48", "VDD", "GND", "100nF", "Capacitor_SMD:C_0402_1005Metric"),
            BypassCap("23", "VDDA", "GND", "1uF", "Capacitor_SMD:C_0402_1005Metric"),
        ],
    }),
    ("MCU_RaspberryPi", "RP2040", "digital", {
        "description": "Dual ARM Cortex-M0+ MCU 264KB SRAM",
        "power_reqs": [
            PowerReq("IOVDD", 3.3, 100),
            PowerReq("DVDD", 1.1, 200),
        ],
        "bypass_caps": [
            BypassCap("1", "IOVDD", "GND", "100nF", "Capacitor_SMD:C_0402_1005Metric"),
            BypassCap("22", "DVDD", "GND", "100nF", "Capacitor_SMD:C_0402_1005Metric"),
            BypassCap("44", "USB_VDD", "GND", "100nF", "Capacitor_SMD:C_0402_1005Metric"),
        ],
    }),
    ("MCU_Nordic", "nRF52840", "digital", {
        "description": "BLE 5.0 + 802.15.4 SoC, 1MB Flash, 256KB SRAM",
        "power_reqs": [PowerReq("VDD", 3.3, 50)],
        "bypass_caps": [
            BypassCap("13", "VDD", "GND", "100nF", "Capacitor_SMD:C_0402_1005Metric"),
            BypassCap("36", "VDD", "GND", "100nF", "Capacitor_SMD:C_0402_1005Metric"),
            BypassCap("48", "VDDH", "GND", "1uF", "Capacitor_SMD:C_0402_1005Metric"),
        ],
    }),

    # ---- Regulators ----
    ("Regulator_Linear", "AP1117-15", "power", {
        "description": "1A LDO Regulator (base for AMS1117 family)",
        "power_reqs": [PowerReq("VIN", 5.0, 1000)],
        "bypass_caps": [
            BypassCap("3", "VIN", "GND", "10uF", "Capacitor_SMD:C_0805_2012Metric"),
            BypassCap("2", "VOUT", "GND", "10uF", "Capacitor_SMD:C_0805_2012Metric"),
        ],
    }),
    ("Regulator_Linear", "AMS1117-3.3", "power", {
        "description": "3.3V 1A LDO Regulator SOT-223",
        "power_reqs": [PowerReq("VIN", 5.0, 1000)],
        "bypass_caps": [
            BypassCap("3", "VIN", "GND", "10uF", "Capacitor_SMD:C_0805_2012Metric"),
            BypassCap("2", "VDD_3P3", "GND", "10uF", "Capacitor_SMD:C_0805_2012Metric"),
        ],
    }),
    ("Regulator_Linear", "AP2112K-3.3", "power", {
        "description": "600mA LDO 3.3V Low-Noise SOT-23-5",
        "power_reqs": [PowerReq("VIN", 5.0, 600)],
        "bypass_caps": [
            BypassCap("1", "VIN", "GND", "1uF", "Capacitor_SMD:C_0402_1005Metric"),
            BypassCap("5", "VDD_3P3", "GND", "1uF", "Capacitor_SMD:C_0402_1005Metric"),
        ],
    }),
    ("Regulator_Linear", "MCP1700-3302E_TO", "power", {
        "description": "250mA LDO 3.3V Low-Quiescent SOT-23",
        "power_reqs": [PowerReq("VIN", 5.0, 250)],
        "bypass_caps": [
            BypassCap("1", "VIN", "GND", "1uF", "Capacitor_SMD:C_0402_1005Metric"),
            BypassCap("3", "VOUT", "GND", "1uF", "Capacitor_SMD:C_0402_1005Metric"),
        ],
    }),

    # ---- Sensors ----
    ("Sensor_Pressure", "BMP280", "sensor", {
        "description": "Barometric Pressure + Temperature Sensor I2C/SPI",
        "power_reqs": [PowerReq("VDD", 3.3, 1)],
        "bypass_caps": [
            BypassCap("8", "VDD", "GND", "100nF", "Capacitor_SMD:C_0402_1005Metric"),
        ],
    }),
    ("Sensor_Motion", "MPU-6050", "sensor", {
        "description": "6-axis IMU (3-axis Gyro + 3-axis Accel) I2C",
        "power_reqs": [PowerReq("VDD", 3.3, 10)],
        "bypass_caps": [
            BypassCap("13", "VDD", "GND", "100nF", "Capacitor_SMD:C_0402_1005Metric"),
            BypassCap("10", "REGOUT", "GND", "100nF", "Capacitor_SMD:C_0402_1005Metric"),
        ],
    }),
    ("Sensor_Motion", "BMI160", "sensor", {
        "description": "6-axis IMU (3-axis Gyro + 3-axis Accel) I2C/SPI",
        "power_reqs": [PowerReq("VDD", 3.3, 5)],
        "bypass_caps": [
            BypassCap("12", "VDD", "GND", "100nF", "Capacitor_SMD:C_0402_1005Metric"),
        ],
    }),

    # ---- Ethernet ----
    ("Interface_Ethernet", "DP83848C", "communication", {
        "description": "10/100 Ethernet PHY RMII",
        "power_reqs": [PowerReq("VDD_3P3", 3.3, 270)],
        "bypass_caps": [
            BypassCap("16", "VDD_3P3", "GND", "100nF", "Capacitor_SMD:C_0402_1005Metric"),
            BypassCap("16", "VDD_3P3", "GND", "10uF", "Capacitor_SMD:C_0805_2012Metric"),
        ],
    }),

    # ---- RF Modules ----
    ("RF_Module", "ESP32-WROOM-32E", "digital", {
        "description": "WiFi+BT Module (ESP32, 4MB Flash) — RF_Module variant",
        "power_reqs": [PowerReq("VDD_3P3", 3.3, 500)],
        "bypass_caps": [
            BypassCap("2", "VDD_3P3", "GND", "10uF", "Capacitor_SMD:C_0805_2012Metric"),
            BypassCap("2", "VDD_3P3", "GND", "100nF", "Capacitor_SMD:C_0402_1005Metric"),
        ],
        "straps": [
            StrapConfig("3", "ESP_EN", "VDD_3P3", "10k", "Resistor_SMD:R_0402_1005Metric"),
        ],
    }),
    ("RF_Module", "RFM95W-868S2", "rf", {
        "description": "LoRa Transceiver Module 868MHz SPI",
        "power_reqs": [PowerReq("VCC", 3.3, 120)],
        "bypass_caps": [
            BypassCap("13", "VCC", "GND", "100nF", "Capacitor_SMD:C_0402_1005Metric"),
            BypassCap("13", "VCC", "GND", "10uF", "Capacitor_SMD:C_0805_2012Metric"),
        ],
    }),
]


def build_standard_library(verbose: bool = True) -> ComponentRegistry:
    """Download and register standard components from KiCad's official library.

    Returns a ComponentRegistry populated with common MCUs, regulators,
    sensors, and connectors — each with datasheet-derived bypass caps and
    strap resistors.

    Falls back gracefully if network is unavailable (uses cached downloads
    or built-in definitions).
    """
    # Start with built-in components (always available, no network needed)
    registry = ComponentRegistry()
    for mpn in BUILTIN_REGISTRY.all_mpns():
        comp = BUILTIN_REGISTRY.get(mpn)
        if comp:
            registry.register(comp)

    lib = KiCadLibrary()

    # Group downloads by library to batch requests
    by_lib = {}
    for kicad_lib, sym_name, category, overrides in STANDARD_COMPONENTS:
        if kicad_lib not in by_lib:
            by_lib[kicad_lib] = []
        by_lib[kicad_lib].append((sym_name, category, overrides))

    downloaded = 0
    for kicad_lib, entries in by_lib.items():
        symbols = [e[0] for e in entries]
        if verbose:
            print(f"Downloading {kicad_lib}: {len(symbols)} symbols...")
        success = lib.download_kicad_lib(kicad_lib, symbols=symbols)

        if success:
            for sym_name, category, overrides in entries:
                comp = lib.get_component(sym_name, kicad_lib, category=category)
                if comp:
                    # Apply datasheet-derived overrides
                    if "description" in overrides:
                        comp.description = overrides["description"]
                    if "power_reqs" in overrides:
                        comp.power_reqs = overrides["power_reqs"]
                    if "bypass_caps" in overrides:
                        comp.bypass_caps = overrides["bypass_caps"]
                    if "straps" in overrides:
                        comp.straps = overrides["straps"]
                    registry.register(comp)
                    downloaded += 1

    if verbose:
        total = len(registry)
        print(f"\nStandard library: {total} components ({downloaded} from KiCad, "
              f"{total - downloaded} built-in)")
        cats = {}
        for mpn in registry.all_mpns():
            c = registry.get(mpn)
            cats[c.category] = cats.get(c.category, 0) + 1
        for cat, count in sorted(cats.items()):
            print(f"  {cat}: {count}")

    return registry
