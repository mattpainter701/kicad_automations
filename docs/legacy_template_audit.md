# Legacy Template Audit

Generated: 2026-04-28T13:59:04.086780

Audit of all 37 legacy templates comparing `generate()` output against `DataDrivenTemplate`.


## Verdict Legend

- **A — Delete safe:** outputs are equivalent within tolerance; no topology-specific passive

  calculation in legacy `generate()` that `build_generic` doesn't replicate.

- **B — Port first:** legacy `generate()` has custom pin-wiring or passive calculation

  not present in any builder; must add a topology-specific builder function before deleting.

- **C — Complex:** 400+ line template with multiple IC sub-modes; plan as a dedicated task per topology.


## Verdict Table

| # | File | Topology | Lines | Verdict | IC Tested | Notes |
|---|------|----------|-------|---------|-----------|-------|
| 1 | `adc.py` | `adc` | 523 | **C** | ADS1115IDGSR | bypass caps only in legacy: [('bulk_cap', '10uF'), ('input_filter', '150nF')]; straps only in legacy: [('address_sele... |
| 2 | `audio_amplifier.py` | `audio_amplifier` | 301 | **B** | PAM8302AASCR | bypass caps only in legacy: [('decoupling', '10uF'), ('input_coupling', '68nF')]; straps only in legacy: [('shutdown_... |
| 3 | `battery_charger.py` | `battery_charger` | 251 | **B** | MCP73831T-2ACI/OT | bypass caps only in legacy: [('input_cap', '4.7uF'), ('output_cap', '4.7uF')]; bypass caps only in data-driven: [('de... |
| 4 | `battery_monitor.py` | `battery_monitor` | 300 | **B** | MAX17048G+T | bypass caps only in legacy: [('cell_filter_cap', '1uF'), ('decoupling', '1uF')]; bypass caps only in data-driven: [('... |
| 5 | `boost.py` | `boost` | 291 | **A** | TPS61230A | bypass caps only in legacy: [('output_cap', '22uF')]; bypass caps only in data-driven: [('output_cap', '470nF')] |
| 6 | `buck.py` | `buck` | 325 | **A** | AP62300 | — |
| 7 | `buck_boost.py` | `buck_boost` | 380 | **A** | TPS63020 | bypass caps only in legacy: [('decoupling', '10uF'), ('input_cap', '100nF'), ('output_cap', '100nF'), ('output_cap', ... |
| 8 | `can_transceiver.py` | `can_transceiver` | 277 | **A** | SN65HVD230 | boundary ports only in legacy: ['CAN_H_U', 'CAN_L_U', 'CAN_RXD_U', 'CAN_TXD_U']; boundary ports only in data-driven: ... |
| 9 | `charge_pump.py` | `charge_pump` | 226 | **B** | LM2776 | bypass caps only in legacy: [('decoupling', '1uF'), ('flying_cap', '1uF'), ('output_cap', '1uF')]; bypass caps only i... |
| 10 | `clock.py` | `clock_synth` | 356 | **B** | AD9528 | bypass caps only in legacy: [('decoupling', '10uF'), ('loop_filter', '100nF'), ('loop_filter', '10nF')]; straps only ... |
| 11 | `connector.py` | `connector` | 181 | **B** | BARREL_JACK_2.1MM | bypass caps only in legacy: [('input_bulk', '10uF')]; bypass caps only in data-driven: [('decoupling', '100nF')]; bou... |
| 12 | `crystal_oscillator.py` | `crystal_oscillator` | 236 | **B** | HC-49S | bypass caps only in legacy: [('load_cap', '1pF')]; bypass caps only in data-driven: [('decoupling', '100nF')]; straps... |
| 13 | `current_sense.py` | `current_sense` | 467 | **C** | INA219 | bypass caps only in legacy: [('input_filter', '100nF')]; straps only in legacy: [('address_select', '0R'), ('input_fi... |
| 14 | `dac.py` | `dac` | 467 | **C** | MCP4725A0T | bypass caps only in legacy: [('bulk_cap', '10uF'), ('output_filter', '1.5uF')]; straps only in legacy: [('output_filt... |
| 15 | `display_driver.py` | `display_driver` | 392 | **B** | SSD1306 | bypass caps only in legacy: [('bulk_cap', '10uF'), ('charge_pump_cap', '2.2uF'), ('reset_delay', '100nF')]; straps on... |
| 16 | `eeprom.py` | `eeprom` | 303 | **A** | 24LC256 | pin nets only in data-driven: ['1', '2', '3', '7']; boundary ports only in legacy: ['I2C_SCL', 'I2C_SDA']; boundary p... |
| 17 | `ethernet.py` | `ethernet_phy` | 352 | **B** | KSZ9031 | bypass caps only in legacy: [('crystal_load', '15pF'), ('decoupling', '10uF'), ('decoupling', '1uF')]; straps only in... |
| 18 | `driver.py` | `gate_driver` | 221 | **B** | IR2110 | bypass caps only in legacy: [('bootstrap_cap', '100nF'), ('decoupling', '10uF')]; boundary ports only in data-driven:... |
| 19 | `i2c_bus.py` | `i2c_bus` | 394 | **C** | PULLUPS_ONLY | bypass caps only in data-driven: [('decoupling', '100nF')]; straps only in legacy: [('i2c_pullup', '3.6k')]; boundary... |
| 20 | `ldo.py` | `ldo` | 202 | **A** | TLV75518 | — |
| 21 | `led_driver.py` | `led_driver` | 405 | **C** | AL8861Y-13 | bypass caps only in legacy: [('inductor', '47uH'), ('input_cap', '10uF')]; bypass caps only in data-driven: [('decoup... |
| 22 | `driver.py` | `level_shifter` | 221 | **B** | IR2110 | straps only in legacy: [('pull_up', '10k')]; pin nets only in legacy: ['1']; pin nets only in data-driven: ['11', '12... |
| 23 | `mosfet_switch.py` | `mosfet_switch` | 311 | **B** | BSS138 | bypass caps only in data-driven: [('decoupling', '100nF')]; straps only in legacy: [('gate_pulldown', '100k'), ('gate... |
| 24 | `motor_driver.py` | `motor_driver` | 477 | **C** | DRV8833 | bypass caps only in legacy: [('input_bulk', '100uF'), ('input_cap', '100nF')]; bypass caps only in data-driven: [('de... |
| 25 | `opamp.py` | `opamp` | 279 | **B** | LM358 | straps only in legacy: [('feedback', '10k'), ('feedback', '39k')]; pin nets only in data-driven: ['5', '6', '7']; bou... |
| 26 | `power_mux.py` | `power_mux` | 327 | **B** | TPS2113ADRBR | bypass caps only in legacy: [('decoupling', '10uF')]; straps only in legacy: [('current_limit', '374k')]; pin nets on... |
| 27 | `protection.py` | `protection` | 123 | **A** | SMBJ5.0A | bypass caps only in data-driven: [('decoupling', '100nF')]; boundary ports only in legacy: ['VIN']; boundary ports on... |
| 28 | `relay_driver.py` | `relay_driver` | 399 | **C** | ULN2003A | pin nets only in data-driven: ['10', '11', '12', '13', '14', '15', '2', '3', '4', '5', '6', '7']; boundary ports only... |
| 29 | `rs485_transceiver.py` | `rs485_transceiver` | 255 | **B** | SP3485EN-L/TR | straps only in legacy: [('bias', '390R')]; boundary ports only in legacy: ['RS485_A_U', 'RS485_B_U', 'RS485_DE_U', 'R... |
| 30 | `rtc.py` | `rtc` | 232 | **B** | DS3231 | straps only in legacy: [('reset_pullup', '10k')]; boundary ports only in legacy: ['I2C_SCL', 'I2C_SDA', 'RTC_32K_U', ... |
| 31 | `sensor_frontend.py` | `sensor_frontend` | 340 | **B** | INA128PA | bypass caps only in legacy: [('bulk_decoupling', '10uF'), ('ref_bypass', '100nF')]; straps only in legacy: [('gain_re... |
| 32 | `spi_bus.py` | `spi_bus` | 366 | **B** | RESISTORS_ONLY | bypass caps only in data-driven: [('decoupling', '100nF')]; straps only in legacy: [('spi_termination', '33R')]; boun... |
| 33 | `usb_c_connector.py` | `usb_c_connector` | 315 | **B** | USB4125-GF-A | bypass caps only in legacy: [('vbus_bulk', '10uF'), ('vbus_decoupling', '100nF')]; bypass caps only in data-driven: [... |
| 34 | `usb.py` | `usb_controller` | 536 | **C** | CYUSB3014 | bypass caps only in legacy: [('decoupling', '10uF')]; straps only in legacy: [('bootstrap_strap', '10k')]; pin nets o... |
| 35 | `usb.py` | `usb_hub` | 536 | **C** | USB2514B | bypass caps only in legacy: [('decoupling', '10uF'), ('pll_filter', '1uF')]; straps only in legacy: [('bias', '12k'),... |
| 36 | `voltage_reference.py` | `voltage_reference` | 293 | **B** | REF3030 | bypass caps only in legacy: [('output_filter', '100nF')]; boundary ports only in legacy: ['VDD_3P3', 'VREF_3P0V']; bo... |
| 37 | `wireless_module.py` | `wireless_module` | 263 | **B** | ESP32-S3-WROOM-1 | bypass caps only in legacy: [('bulk_decoupling', '22uF'), ('reset_delay', '1uF')]; straps only in legacy: [('boot_pul... |

## Summary

- **A (Delete safe):** 7
- **B (Port first):** 21
- **C (Complex):** 9
- **Total:** 37


## Verdict-A Templates (Delete Safe)

- `boost` (boost.py, 291 L) — IC: TPS61230A
- `buck` (buck.py, 325 L) — IC: AP62300
- `buck_boost` (buck_boost.py, 380 L) — IC: TPS63020
- `can_transceiver` (can_transceiver.py, 277 L) — IC: SN65HVD230
- `eeprom` (eeprom.py, 303 L) — IC: 24LC256
- `ldo` (ldo.py, 202 L) — IC: TLV75518
- `protection` (protection.py, 123 L) — IC: SMBJ5.0A

These can be deleted after Task 180 (registry flip) + parity tests (Task 181/182).


## Verdict-B Templates (Port First)

- `audio_amplifier` (audio_amplifier.py, 301 L) — IC: PAM8302AASCR
  - bypass caps only in legacy: [('decoupling', '10uF'), ('input_coupling', '68nF')]; straps only in legacy: [('shutdown_pullup', '100k')]; pin nets only in data-driven: ['6']; boundary ports only in legacy: ['AUDIO_IN', 'SPKR_N_U', 'SPKR_P_U']; boundary ports only in data-driven: ['IN_N_U', 'IN_P_U', 'SD_N_U', 'VO_N_U', 'VO_P_U']
- `battery_charger` (battery_charger.py, 251 L) — IC: MCP73831T-2ACI/OT
  - bypass caps only in legacy: [('input_cap', '4.7uF'), ('output_cap', '4.7uF')]; bypass caps only in data-driven: [('decoupling', '100nF')]; straps only in legacy: [('current_program', '1k')]; boundary ports only in legacy: ['VBAT', 'VIN']; boundary ports only in data-driven: ['PROG_U', 'VDD_3P3']
- `battery_monitor` (battery_monitor.py, 300 L) — IC: MAX17048G+T
  - bypass caps only in legacy: [('cell_filter_cap', '1uF'), ('decoupling', '1uF')]; bypass caps only in data-driven: [('decoupling', '100nF')]; straps only in legacy: [('cell_filter_series', '100R'), ('qstrt_pulldown', '10k')]; pin nets only in data-driven: ['1']; boundary ports only in legacy: ['I2C_SCL', 'I2C_SDA', 'VBAT']; boundary ports only in data-driven: ['CELL_U', 'CTG_U', 'QSTRT_U', 'SCL_U', 'SDA_U', 'VDD_3P3']
- `charge_pump` (charge_pump.py, 226 L) — IC: LM2776
  - bypass caps only in legacy: [('decoupling', '1uF'), ('flying_cap', '1uF'), ('output_cap', '1uF')]; bypass caps only in data-driven: [('decoupling', '100nF')]; pin nets only in legacy: ['3']; boundary ports only in legacy: ['VNEG']; boundary ports only in data-driven: ['C_FLY_N_U', 'C_FLY_P_U']
- `clock_synth` (clock.py, 356 L) — IC: AD9528
  - bypass caps only in legacy: [('decoupling', '10uF'), ('loop_filter', '100nF'), ('loop_filter', '10nF')]; straps only in legacy: [('loop_filter', '78.7R')]; pin nets only in data-driven: ['19', '20', '22', '23', '25', '26', '28', '29', '31', '32', '34', '35', '37', '38', '4', '40', '41', '43', '44', '46', '47', '49', '5', '50', '52', '53', '55', '56', '58', '59', '61', '62', '65', '67', '69', '7', '71', '72']; boundary ports only in legacy: ['REF_CLK_N', 'REF_CLK_P']; boundary ports only in data-driven: ['CSB_U', 'IP_PLL2_U', 'LF1_U', 'LF2_U', 'LF3_U', 'OUT0+_U', 'OUT0-_U', 'OUT1+_U', 'OUT1-_U', 'OUT10+_U', 'OUT10-_U', 'OUT11+_U', 'OUT11-_U', 'OUT12+_U', 'OUT12-_U', 'OUT13+_U', 'OUT13-_U', 'OUT2+_U', 'OUT2-_U', 'OUT3+_U', 'OUT3-_U', 'OUT4+_U', 'OUT4-_U', 'OUT5+_U', 'OUT5-_U', 'OUT6+_U', 'OUT6-_U', 'OUT7+_U', 'OUT7-_U', 'OUT8+_U', 'OUT8-_U', 'OUT9+_U', 'OUT9-_U', 'PD_U', 'REFA+_U', 'REFA-_U', 'REFB+_U', 'REFB-_U', 'RESETB_U', 'SCLK_U', 'SDIO_U', 'SDO_U', 'STATUS0_U', 'STATUS1_U', 'SYSREF_REQ_U', 'VCXO_OUT_U', 'XO+_U', 'XO-_U']
- `connector` (connector.py, 181 L) — IC: BARREL_JACK_2.1MM
  - bypass caps only in legacy: [('input_bulk', '10uF')]; bypass caps only in data-driven: [('decoupling', '100nF')]; boundary ports only in legacy: ['VIN']; boundary ports only in data-driven: ['RING_U', 'SWITCH_U', 'TIP_U', 'VDD_3P3']
- `crystal_oscillator` (crystal_oscillator.py, 236 L) — IC: HC-49S
  - bypass caps only in legacy: [('load_cap', '1pF')]; bypass caps only in data-driven: [('decoupling', '100nF')]; straps only in legacy: [('feedback', '1M')]; boundary ports only in legacy: ['XTAL_IN', 'XTAL_OUT']; boundary ports only in data-driven: ['VDD_3P3', 'XTAL1_U', 'XTAL2_U']
- `display_driver` (display_driver.py, 392 L) — IC: SSD1306
  - bypass caps only in legacy: [('bulk_cap', '10uF'), ('charge_pump_cap', '2.2uF'), ('reset_delay', '100nF')]; straps only in legacy: [('iref_set', '909k'), ('reset_pullup', '10k')]; pin nets only in legacy: ['9']; boundary ports only in legacy: ['I2C_SCL', 'I2C_SDA']; boundary ports only in data-driven: ['C1P_U', 'C2P_U', 'CS_N_U', 'DC_U', 'IREF_U', 'SCL_U', 'SDA_U']
- `ethernet_phy` (ethernet.py, 352 L) — IC: KSZ9031
  - bypass caps only in legacy: [('crystal_load', '15pF'), ('decoupling', '10uF'), ('decoupling', '1uF')]; straps only in legacy: [('bias', '12.1k'), ('strap', '10k')]; boundary ports only in legacy: ['ETH_INT_N_U', 'ETH_RESET_N', 'MDC', 'MDIO']; boundary ports only in data-driven: ['INT_N_U', 'ISET_U', 'LED0_U', 'LED1_U', 'LED2_U', 'MDC_U', 'MDIO_U', 'RESET_N_U', 'RXCTL_CLK_U', 'RXCTL_U', 'RXC_U', 'RXD0_MODE0_U', 'RXD0_U', 'RXD1_MODE1_U', 'RXD1_U', 'RXD2_MODE2_U', 'RXD2_U', 'RXD3_MODE3_U', 'RXD3_U', 'RXN_B_U', 'RXN_D_U', 'RXP_B_U', 'RXP_D_U', 'TXCTL_U', 'TXC_U', 'TXD0_U', 'TXD1_U', 'TXD2_U', 'TXD3_U', 'TXN_A_U', 'TXN_C_U', 'TXP_A_U', 'TXP_C_U', 'XI_U', 'XO_U']
- `gate_driver` (driver.py, 221 L) — IC: IR2110
  - bypass caps only in legacy: [('bootstrap_cap', '100nF'), ('decoupling', '10uF')]; boundary ports only in data-driven: ['SD_U']
- `level_shifter` (driver.py, 221 L) — IC: IR2110
  - straps only in legacy: [('pull_up', '10k')]; pin nets only in legacy: ['1']; pin nets only in data-driven: ['11', '12', '13', '14', '15', '16', '17', '18', '19', '2', '3', '6', '9']; boundary ports only in legacy: ['LS_A1_U', 'LS_A2_U', 'LS_B1_U', 'LS_B2_U', 'VDD_1P8']; boundary ports only in data-driven: ['A1_U', 'A2_U', 'A3_U', 'A4_U', 'A5_U', 'A6_U', 'A7_U', 'A8_U', 'B1_U', 'B2_U', 'B3_U', 'B4_U', 'B5_U', 'B6_U', 'B7_U', 'B8_U', 'OE_U']
- `mosfet_switch` (mosfet_switch.py, 311 L) — IC: BSS138
  - bypass caps only in data-driven: [('decoupling', '100nF')]; straps only in legacy: [('gate_pulldown', '100k'), ('gate_resistor', '100R')]; pin nets only in data-driven: ['2']; boundary ports only in legacy: ['GATE_Q', 'LOAD_Q']; boundary ports only in data-driven: ['D_U', 'G_U', 'S_U', 'VDD_3P3']
- `opamp` (opamp.py, 279 L) — IC: LM358
  - straps only in legacy: [('feedback', '10k'), ('feedback', '39k')]; pin nets only in data-driven: ['5', '6', '7']; boundary ports only in legacy: ['OPAMP_IN_U', 'OPAMP_OUT_U']; boundary ports only in data-driven: ['IN+_A_U', 'IN+_B_U', 'IN-_A_U', 'IN-_B_U', 'OUT_A_U', 'OUT_B_U']
- `power_mux` (power_mux.py, 327 L) — IC: TPS2113ADRBR
  - bypass caps only in legacy: [('decoupling', '10uF')]; straps only in legacy: [('current_limit', '374k')]; pin nets only in legacy: ['7']; pin nets only in data-driven: ['2', '3']; boundary ports only in legacy: ['VBAT', 'VSYS', 'VUSB']; boundary ports only in data-driven: ['D1_U', 'D2_U', 'ILIM1_U', 'ILIM2_U', 'VDD_3P3']
- `rs485_transceiver` (rs485_transceiver.py, 255 L) — IC: SP3485EN-L/TR
  - straps only in legacy: [('bias', '390R')]; boundary ports only in legacy: ['RS485_A_U', 'RS485_B_U', 'RS485_DE_U', 'RS485_RXD_U', 'RS485_TXD_U']; boundary ports only in data-driven: ['A_U', 'B_U', 'DE_U', 'DI_U', 'RE_N_U', 'RO_U']
- `rtc` (rtc.py, 232 L) — IC: DS3231
  - straps only in legacy: [('reset_pullup', '10k')]; boundary ports only in legacy: ['I2C_SCL', 'I2C_SDA', 'RTC_32K_U', 'RTC_INT_U', 'VBAT_RTC']; boundary ports only in data-driven: ['32KHZ_U', 'INT_N/SQW_U', 'RST_N_U', 'SCL_U', 'SDA_U']
- `sensor_frontend` (sensor_frontend.py, 340 L) — IC: INA128PA
  - bypass caps only in legacy: [('bulk_decoupling', '10uF'), ('ref_bypass', '100nF')]; straps only in legacy: [('gain_resistor', '5.62k')]; boundary ports only in legacy: ['INA_OUT_U', 'SENSOR_N', 'SENSOR_P']; boundary ports only in data-driven: ['IN_N_U', 'IN_P_U', 'REF_U', 'RG_N_U', 'RG_P_U', 'VOUT_U']
- `spi_bus` (spi_bus.py, 366 L) — IC: RESISTORS_ONLY
  - bypass caps only in data-driven: [('decoupling', '100nF')]; straps only in legacy: [('spi_termination', '33R')]; boundary ports only in legacy: ['MOSI_T_RP', 'SCLK_T_RP', 'SPI_CS_N', 'SPI_MISO', 'SPI_MOSI', 'SPI_SCLK']; boundary ports only in data-driven: ['CS_N_U', 'MISO_U', 'MOSI_U', 'SCLK_U']
- `usb_c_connector` (usb_c_connector.py, 315 L) — IC: USB4125-GF-A
  - bypass caps only in legacy: [('vbus_bulk', '10uF'), ('vbus_decoupling', '100nF')]; bypass caps only in data-driven: [('decoupling', '100nF')]; straps only in legacy: [('cc_pulldown', '5.1k')]; pin nets only in data-driven: ['A8', 'B8']; boundary ports only in legacy: ['CC1_J', 'CC2_J', 'USB_DN', 'USB_DP', 'VBUS']; boundary ports only in data-driven: ['CC1_U', 'CC2_U', 'DN1_U', 'DN2_U', 'DP1_U', 'DP2_U', 'SBU1_U', 'SBU2_U', 'VDD_5V']
- `voltage_reference` (voltage_reference.py, 293 L) — IC: REF3030
  - bypass caps only in legacy: [('output_filter', '100nF')]; boundary ports only in legacy: ['VDD_3P3', 'VREF_3P0V']; boundary ports only in data-driven: ['VDD_5V']
- `wireless_module` (wireless_module.py, 263 L) — IC: ESP32-S3-WROOM-1
  - bypass caps only in legacy: [('bulk_decoupling', '22uF'), ('reset_delay', '1uF')]; straps only in legacy: [('boot_pullup', '10k'), ('enable_pullup', '10k')]; pin nets only in data-driven: ['10', '11', '12', '13', '14', '15', '16', '17', '18', '19', '20', '21', '22', '23', '24', '25', '26', '28', '29', '30', '31', '32', '33', '34', '35', '38', '39', '4', '5', '6', '7', '8', '9']; boundary ports only in legacy: ['BOOT_U', 'UART_RXD', 'UART_TXD']; boundary ports only in data-driven: ['IO0_U', 'IO10_U', 'IO11_U', 'IO12_U', 'IO13_U', 'IO14_U', 'IO15_U', 'IO16_U', 'IO17_U', 'IO18_U', 'IO19_U', 'IO1_U', 'IO20_U', 'IO21_U', 'IO2_U', 'IO35_U', 'IO36_U', 'IO37_U', 'IO38_U', 'IO39_U', 'IO3_U', 'IO40_U', 'IO41_U', 'IO42_U', 'IO45_U', 'IO46_U', 'IO47_U', 'IO48_U', 'IO4_U', 'IO5_U', 'IO6_U', 'IO7_U', 'IO8_U', 'IO9_U', 'RXD0_U', 'TXD0_U']

Need topology-specific builder functions in `topology_builders.py` before deletion.


## Verdict-C Templates (Complex)

- `adc` (adc.py, 523 L) — IC: ADS1115IDGSR
- `current_sense` (current_sense.py, 467 L) — IC: INA219
- `dac` (dac.py, 467 L) — IC: MCP4725A0T
- `i2c_bus` (i2c_bus.py, 394 L) — IC: PULLUPS_ONLY
- `led_driver` (led_driver.py, 405 L) — IC: AL8861Y-13
- `motor_driver` (motor_driver.py, 477 L) — IC: DRV8833
- `relay_driver` (relay_driver.py, 399 L) — IC: ULN2003A
- `usb_controller` (usb.py, 536 L) — IC: CYUSB3014
- `usb_hub` (usb.py, 536 L) — IC: USB2514B

Multi-mode templates with 400+ lines. Each needs a dedicated porting sub-task in Task 184.


## IC Data JSON Field Coverage

Templates whose `generate()` references fields NOT in the IC data JSON would cause silent regression if deleted before JSON is updated.

> **Note:** Field coverage is verified at generation time — if a template reads a field that doesn't exist in ic_data, `generate()` will raise `KeyError`. The audit above catches those cases as `Legacy template failed`.
