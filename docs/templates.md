# Template Reference

Auto-generated from `param_schema` of all registered subcircuit templates.

**37 templates available.**

---

## `adc`

Precision ADC with anti-alias RC input filters

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `ic` | string |  | ADS1115IDGSR | ADC IC MPN |
| `ref` | string |  | U | Reference designator for the IC |
| `vdd_net` | string |  | VDD_3P3 | Power supply net name |
| `input_filter_bw` | number |  | 1000 | Anti-alias filter bandwidth in Hz |
| `channels` | number |  | 4 | Number of active input channels |
| `i2c_addr` | string |  | GND | I2C address select (GND/VDD/SDA/SCL) for ADS1115 |
| `sda_net` | string |  | SDA | I2C SDA bus net name |
| `scl_net` | string |  | SCL | I2C SCL bus net name |
| `cs_net` | string |  |  | SPI chip select net name (MCP3208) |
| `spi_mosi_net` | string |  | MOSI | SPI MOSI bus net name |
| `spi_miso_net` | string |  | MISO | SPI MISO bus net name |
| `spi_sck_net` | string |  | SCK | SPI clock bus net name |
| `vref_net` | string |  |  | External VREF net (MCP3208); defaults to vdd_net |

### Example

```yaml
analog:
  - type: adc
    ref: U1
```

---

## `audio_amplifier`

Class-D audio amplifier with input coupling and decoupling

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `ic` | string |  | PAM8302AASCR | Audio amplifier IC MPN |
| `ref` | string |  | U | Reference designator for the IC |
| `vdd_net` | string |  | VDD_3P3 | Supply rail net name |
| `audio_in_net` | string |  | AUDIO_IN | Audio input net name (analog ICs only) |
| `f_low` | number |  | 100 | Low-frequency cutoff in Hz for input coupling cap |
| `speaker_impedance` | number |  | 8 | Speaker impedance in ohms |

### Example

```yaml
analog:
  - type: audio_amplifier
    ref: U1
```

---

## `battery_charger`

Li-Ion/LiPo battery charger with programmable charge current

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `ichg` | number | Yes |  | Charge current in amps |
| `vcell` | number |  | 4.2 | Cell termination voltage in volts |
| `ic` | string |  | MCP73831T-2ACI/OT | Charger IC MPN |
| `ref` | string |  | U | Reference designator for the IC |
| `vin_net` | string |  | VUSB | Input power net name |
| `bat_net` | string |  | VBAT | Battery output net name |
| `stat_net` | string |  |  | Charge status output net name |

### Example

```yaml
power:
  - type: battery_charger
    ref: U1
    ichg: 0.5
```

---

## `battery_monitor`

Battery fuel gauge / state-of-charge monitor with I2C

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `ic` | string |  | MAX17048G+T | Fuel gauge IC MPN |
| `ref` | string |  | U | Reference designator for the IC |
| `bat_net` | string |  | VBAT | Battery positive net name |
| `cell_capacity_mah` | number |  | 2000 | Cell capacity in milliamp-hours |
| `rsense` | number |  |  | Sense resistor value in ohms (BQ27441 only) |
| `i2c_bus` | string |  | I2C | I2C bus name prefix for SDA/SCL nets |

### Example

```yaml
power:
  - type: battery_monitor
    ref: U1
```

---

## `boost`

Boost DC-DC step-up converter with feedback divider

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `vin` | number | Yes |  | Input voltage in volts |
| `vout` | number | Yes |  | Output voltage in volts |
| `iout` | number | Yes |  | Maximum output current in amps |
| `ic` | string |  | TPS61230A | Boost regulator IC MPN |
| `ref` | string |  | U | Reference designator for the IC |
| `rail_name` | string |  |  | Output rail net name |
| `vin_net` | string |  | VIN | Input rail net name |
| `en_net` | string |  |  | Enable net name; defaults to vin_net |
| `fsw` | number |  |  | Switching frequency override in hertz |
| `r_fbb` | number |  |  | Bottom feedback resistor override in ohms |

### Example

```yaml
power:
  - type: boost
    ref: U1
    vin: 12
    vout: 3.3
    iout: 1
```

---

## `buck`

Synchronous buck DC-DC converter with feedback divider

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `vin` | number | Yes |  | Input voltage in volts |
| `vout` | number | Yes |  | Output voltage in volts |
| `iout` | number | Yes |  | Maximum output current in amps |
| `ic` | string |  | AP62300 | Buck regulator IC MPN |
| `ref` | string |  | U | Reference designator for the IC |
| `rail_name` | string |  |  | Output rail net name |
| `vin_net` | string |  | VIN | Input rail net name |
| `en_net` | string |  |  | Enable net name; defaults to vin_net |
| `fsw` | number |  |  | Switching frequency override in hertz |
| `r_fbb` | number |  |  | Bottom feedback resistor override in ohms |
| `ripple_ratio` | number |  | 0.3 | Target inductor ripple ratio |
| `vout_ripple` | number |  | 0.02 | Target output ripple in volts |

### Example

```yaml
power:
  - type: buck
    ref: U1
    vin: 12
    vout: 3.3
    iout: 1
```

---

## `buck_boost`

Buck-Boost DC-DC converter with feedback divider

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `vin` | number | Yes |  | Nominal input voltage in volts |
| `vout` | number | Yes |  | Output voltage in volts |
| `iout` | number | Yes |  | Maximum output current in amps |
| `vin_min` | number |  |  | Minimum input voltage (for inductor sizing); defaults to vin |
| `vin_max` | number |  |  | Maximum input voltage |
| `ic` | string |  | TPS63020 | Buck-boost regulator IC MPN |
| `ref` | string |  | U | Reference designator for the IC |
| `rail_name` | string |  |  | Output rail net name |
| `vin_net` | string |  | VBAT | Input rail net name |
| `en_net` | string |  |  | Enable net name; defaults to vin_net |
| `r_fbb` | number |  |  | Bottom feedback resistor override in ohms |

### Example

```yaml
power:
  - type: buck_boost
    ref: U1
    vin: 12
    vout: 3.3
    iout: 1
```

---

## `can_transceiver`

CAN bus transceiver with decoupling and optional split termination

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `ic` | string |  | SN65HVD230 | CAN transceiver IC MPN |
| `ref` | string |  | U | Reference designator for the transceiver |
| `vdd_net` | string |  | VDD_3P3 | Supply rail net name |
| `txd_net` | string |  |  | TXD signal net from MCU |
| `rxd_net` | string |  |  | RXD signal net to MCU |
| `bus_net_prefix` | string |  | CAN | Prefix for CANH/CANL bus nets |
| `termination` | boolean |  | False | Enable split termination (2x60R + 4.7nF) |
| `slope_control` | boolean |  | False | Enable slope control via 10k on RS pin (otherwise RS to GND) |

### Example

```yaml
interfaces:
  - type: can_transceiver
    ref: U1
```

---

## `charge_pump`

Inverting charge pump with flying cap and output cap

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `ic` | string |  | LM2776 | Charge pump IC MPN |
| `ref` | string |  | U | Reference designator for the IC |
| `vin_net` | string |  | VDD_3P3 | Input rail net name |
| `rail_name` | string |  | VNEG | Output rail net name (negative rail) |
| `iout` | number |  | 0.05 | Output current in amps (default 50mA) |

### Example

```yaml
power:
  - type: charge_pump
    ref: U1
```

---

## `clock_synth`

Clock synthesizer IC with decoupling and PLL loop filter

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `ic` | string |  | AD9528 | Clock synthesizer IC MPN |
| `ref` | string |  | U | Reference designator for the IC |
| `ref_freq` | number |  | 30720000.0 | Reference input frequency in hertz |
| `pll_bw` | number |  | 20000.0 | PLL loop bandwidth in hertz |
| `vdd_net` | string |  | VDD_1P8 | Core supply net name |
| `vddo_net` | string |  |  | Output driver supply net name; defaults to vdd_net |
| `ref_net` | string |  | REF_CLK | Reference clock input net name |

### Example

```yaml
clocking:
  - type: clock_synth
    ref: U1
```

---

## `connector`

Barrel jack, pin header, or JST connector with optional decoupling

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `ic` | string |  | BARREL_JACK_2.1MM | Connector MPN/type |
| `ref` | string |  | J | Reference designator for the connector |
| `positive_net` | string |  | VIN | Positive/power net name (power connectors) |
| `negative_net` | string |  | GND | Negative/ground net name (power connectors) |
| `signal_nets` | string |  |  | Comma-separated net names for signal pins (generic connectors) |
| `decoupling` | boolean |  | True | Add input decoupling capacitor (power connectors) |

### Example

```yaml
connectors:
  - type: connector
    ref: U1
```

---

## `crystal_oscillator`

Crystal oscillator with load capacitors and feedback resistor

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `freq` | number | Yes |  | Crystal frequency in Hz (e.g. 8e6 for 8 MHz) |
| `cl_spec` | number | Yes |  | Crystal load capacitance spec in pF (e.g. 12 or 20) |
| `c_stray` | number |  | 3e-12 | Board stray capacitance in farads (default 3pF) |
| `ic` | string |  | ABM8G | Crystal package MPN |
| `ref` | string |  | Y | Reference designator for the crystal |
| `xtal_in_net` | string |  | XTAL_IN | Crystal input net name (from MCU OSC_IN) |
| `xtal_out_net` | string |  | XTAL_OUT | Crystal output net name (to MCU OSC_OUT) |

### Example

```yaml
clocking:
  - type: crystal_oscillator
    ref: U1
    freq: 8000000
    cl_spec: 9e-12
```

---

## `current_sense`

High-side current sense amplifier with auto-calculated Rsense

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `imax` | number | Yes |  | Maximum current to measure in amps |
| `vsense_target` | number |  | 0.05 | Target sense voltage at Imax in volts (default 50mV) |
| `ic` | string |  | INA219 | Current sense amplifier IC MPN |
| `ref` | string |  | U | Reference designator for the IC |
| `vdd_net` | string |  | VDD_3P3 | Power supply net name |
| `sense_p_net` | string |  | SENSE_P | High-side sense point net (upstream of Rsense) |
| `sense_n_net` | string |  | SENSE_N | Low-side sense point net (downstream of Rsense) |
| `sda_net` | string |  | I2C_SDA | I2C SDA net (INA219 only) |
| `scl_net` | string |  | I2C_SCL | I2C SCL net (INA219 only) |
| `out_net` | string |  |  | Analog output net (INA180A1 only) |

### Example

```yaml
analog:
  - type: current_sense
    ref: U1
    imax: 5
```

---

## `dac`

Digital-to-analog converter with output RC filter

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `ic` | string |  | MCP4725A0T | DAC IC MPN |
| `ref` | string |  | U | Reference designator for the IC |
| `vdd_net` | string |  | VDD_3P3 | Power supply net name |
| `update_rate` | number |  | 1000 | DAC update rate in Hz (filter cutoff = rate / 10) |
| `vref` | string |  |  | External VREF net name (DAC8552); defaults to vdd_net |
| `output_net` | string |  |  | Output net name; defaults to DAC_OUT_{ref} |
| `sda_net` | string |  | SDA | I2C SDA bus net name (MCP4725) |
| `scl_net` | string |  | SCL | I2C SCL bus net name (MCP4725) |
| `din_net` | string |  | MOSI | SPI DIN net name (DAC8552) |
| `sclk_net` | string |  | SCK | SPI SCLK net name (DAC8552) |
| `sync_net` | string |  |  | SPI SYNC_N net name (DAC8552); defaults to SYNC_DAC_{ref} |
| `output_b_net` | string |  |  | Second output net for dual DAC (DAC8552); defaults to DAC_OUTB_{ref} |

### Example

```yaml
analog:
  - type: dac
    ref: U1
```

---

## `display_driver`

OLED/LCD display driver with reset circuit and interface config

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `ic` | string |  | SSD1306 | Display driver IC MPN |
| `ref` | string |  | U | Reference designator for the IC |
| `interface` | string |  | i2c | Interface mode: 'i2c' or 'spi' |
| `vdd_net` | string |  | VDD_3P3 | Logic supply net name |
| `resolution` | string |  | 128x64 | Display resolution (informational) |
| `backlight` | boolean |  | False | Enable backlight resistor (LCD only) |
| `bl_current` | number |  | 0.02 | Backlight LED current in amps |
| `bl_vf` | number |  | 3.0 | Backlight LED forward voltage in volts |

### Example

```yaml
interfaces:
  - type: display_driver
    ref: U1
```

---

## `eeprom`

I2C EEPROM or SPI flash with address config and write protect

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `ic` | string |  | 24LC256 | EEPROM/flash IC MPN |
| `ref` | string |  | U | Reference designator for the IC |
| `vdd_net` | string |  | VDD_3P3 | Supply rail net name |
| `i2c_addr_offset` | integer |  | 0 | I2C address offset (0-7) set by A0/A1/A2 pins |
| `sda_net` | string |  | I2C_SDA | I2C SDA net name |
| `scl_net` | string |  | I2C_SCL | I2C SCL net name |
| `cs_net` | string |  |  | SPI chip select net name (SPI flash only) |
| `mosi_net` | string |  | SPI_MOSI | SPI MOSI net name (SPI flash only) |
| `miso_net` | string |  | SPI_MISO | SPI MISO net name (SPI flash only) |
| `sclk_net` | string |  | SPI_SCLK | SPI SCLK net name (SPI flash only) |
| `write_protect` | boolean |  | False | Enable hardware write protection (WP tied high) |

### Example

```yaml
digital:
  - type: eeprom
    ref: U1
```

---

## `ethernet_phy`

Gigabit Ethernet PHY with RGMII/RMII/MII interface

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `ic` | string |  | KSZ9031 | Ethernet PHY IC MPN |
| `ref` | string |  | U | Reference designator for the PHY |
| `mode` | string |  | rgmii | MAC interface mode (rgmii, rmii, mii) |
| `crystal_cl` | number |  | 9e-12 | Crystal load capacitance in farads |
| `vdd_net` | string |  | VDD_3P3 | Digital supply net |
| `gnd_net` | string |  | GND | Ground net |
| `reset_net` | string |  | ETH_RESET_N | Reset net name |
| `mdio_net` | string |  | MDIO | MDIO management bus net |
| `mdc_net` | string |  | MDC | MDC management clock net |

### Example

```yaml
interfaces:
  - type: ethernet_phy
    ref: U1
```

---

## `gate_driver`

Gate driver IC with bootstrap and decoupling

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `ic` | string |  | UCC27524 |  |
| `ref` | string |  | U |  |
| `vdd_net` | string |  | VDD_12V |  |
| `gnd_net` | string |  | GND |  |
| `hin_net` | string |  |  |  |
| `lin_net` | string |  |  |  |

### Example

```yaml
power:
  - type: gate_driver
    ref: U1
```

---

## `i2c_bus`

I2C bus pull-ups or level shifter with auto-calculated resistance

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `vdd` | number |  | 3.3 | I2C bus supply voltage in volts |
| `speed` | number |  | 400000 | I2C bus speed in Hz (100000, 400000, or 1000000) |
| `c_bus` | number |  | 1e-10 | Total I2C bus capacitance in farads (default 100pF) |
| `ic` | string |  | PULLUPS_ONLY | I2C bus IC MPN (PULLUPS_ONLY or PCA9306) |
| `ref` | string |  | RP | Reference designator |
| `vdd_net` | string |  | VDD_3P3 | Power supply net name for pull-ups |
| `sda_net` | string |  | I2C_SDA | I2C SDA bus net name |
| `scl_net` | string |  | I2C_SCL | I2C SCL bus net name |
| `vdd_low_net` | string |  |  | Low-side supply net for PCA9306 (VREF1) |
| `vdd_high_net` | string |  |  | High-side supply net for PCA9306 (VREF2) |
| `sda_low_net` | string |  |  | Low-side SDA net for PCA9306 |
| `scl_low_net` | string |  |  | Low-side SCL net for PCA9306 |
| `sda_high_net` | string |  |  | High-side SDA net for PCA9306 |
| `scl_high_net` | string |  |  | High-side SCL net for PCA9306 |

### Example

```yaml
interfaces:
  - type: i2c_bus
    ref: U1
```

---

## `ldo`

LDO linear regulator with decoupling

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `vin` | number | Yes |  | Input voltage in volts |
| `vout` | number |  |  | Output voltage in volts; inferred from fixed-output ICs when omitted |
| `iout` | number |  |  | Maximum output current in amps |
| `ic` | string |  | TLV75518 | LDO IC MPN; fixed-output parts can imply vout |
| `ref` | string |  | U | Reference designator for the IC |
| `rail_name` | string |  |  | Output rail net name |
| `vin_net` | string |  | VIN | Input rail net name |
| `en_net` | string |  |  | Enable net name; defaults to vin_net |

### Example

```yaml
power:
  - type: ldo
    ref: U1
    vin: 12
```

---

## `led_driver`

Constant-current LED driver (buck or linear sink)

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `iled` | number | Yes |  | LED current in amps |
| `vled` | number |  | 3.0 | Forward voltage per LED in volts |
| `num_leds` | number |  | 1 | Number of LEDs in series |
| `vin` | number |  | 12 | Input voltage in volts |
| `ic` | string |  | AL8861Y-13 | LED driver IC MPN |
| `ref` | string |  | U | Reference designator for the IC |
| `vin_net` | string |  | VIN | Input rail net name |

### Example

```yaml
power:
  - type: led_driver
    ref: U1
    iled: 0.02
```

---

## `level_shifter`

Bidirectional voltage level shifter

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `ic` | string |  | TXS0102 |  |
| `ref` | string |  | U |  |
| `vcca_net` | string |  | VDD_1P8 |  |
| `vccb_net` | string |  | VDD_3P3 |  |
| `gnd_net` | string |  | GND |  |

### Example

```yaml
interfaces:
  - type: level_shifter
    ref: U1
```

---

## `mosfet_switch`

Low-side or high-side MOSFET switch with gate protection

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `iload` | number | Yes |  | Load current in amps |
| `vdrive` | number |  | 3.3 | GPIO drive voltage in volts |
| `ic` | string |  | BSS138 | MOSFET MPN |
| `ref` | string |  | Q | Reference designator for the MOSFET |
| `vdd_net` | string |  | VDD_3P3 | Supply rail net name (used for P-ch pull-up) |
| `load_net` | string |  |  | Load connection net name; defaults to LOAD_{ref} |
| `gate_net` | string |  |  | Gate drive net name; defaults to GATE_{ref} |
| `inductive` | boolean |  | False | True for inductive loads (relay, solenoid, motor) — adds snubber RC |

### Example

```yaml
power:
  - type: mosfet_switch
    ref: U1
    iload: 0.5
```

---

## `motor_driver`

Dual H-bridge motor driver with optional current limiting

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `vm` | number | Yes |  | Motor supply voltage in volts |
| `imotor` | number | Yes |  | Motor current per channel in amps |
| `ic` | string |  | DRV8833 | Motor driver IC MPN |
| `ref` | string |  | U | Reference designator for the IC |
| `vm_net` | string |  | VMOT | Motor supply net name |
| `vdd_net` | string |  | VDD_3P3 | Logic supply net name (TB6612 VCC) |
| `motor_type` | string |  | dc | Motor type: 'dc' or 'stepper' |

### Example

```yaml
motor:
  - type: motor_driver
    ref: U1
    vm: 7.4
    imotor: 1
```

---

## `opamp`

Op-amp with configurable gain and feedback

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `ic` | string |  | LM358 |  |
| `ref` | string |  | U |  |
| `config` | string |  | non_inverting | Options: non_inverting, inverting, follower, differential |
| `gain` | number |  | 1.0 | Voltage gain (absolute value) |
| `rf` | number |  |  | Feedback resistor in ohms (overrides gain calculation) |
| `rin` | number |  |  | Input resistor in ohms (overrides gain calculation) |
| `vdd_net` | string |  | VDD_3P3 |  |
| `gnd_net` | string |  | GND |  |
| `in_net` | string |  |  |  |
| `out_net` | string |  |  |  |

### Example

```yaml
analog:
  - type: opamp
    ref: U1
```

---

## `power_mux`

Auto-switching power mux or ideal diode OR controller

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `ic` | string |  | TPS2113ADRBR | Power mux IC MPN |
| `ref` | string |  | U | Reference designator for the IC |
| `ilim` | number |  | 1.0 | Current limit in amps (TPS2113 only) |
| `vin1_net` | string |  | VUSB | Primary input rail net name |
| `vin2_net` | string |  | VBAT | Secondary input rail net name |
| `vout_net` | string |  | VSYS | Output rail net name |

### Example

```yaml
power:
  - type: power_mux
    ref: U1
```

---

## `protection`

Protection circuit (TVS, ESD, reverse polarity)

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `ic` | string |  | SMBJ5.0A | Protection device MPN |
| `ref` | string |  | D | Reference designator for the protection device |
| `protect_net` | string | Yes |  | Net to protect (e.g., VBUS_5V, USB_DP) |
| `gnd_net` | string |  | GND | Ground reference net name |
| `protection_type` | string |  | tvs | Protection type: TVS for power lines, ESD for signal lines (tvs, esd) |

### Example

```yaml
protection:
  - type: protection
    ref: U1
    protect_net: VBUS_5V
```

---

## `relay_driver`

Relay coil driver with Darlington array or discrete NPN

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `vcoil` | number | Yes |  | Relay coil voltage in volts |
| `icoil` | number | Yes |  | Relay coil current in amps |
| `ic` | string |  | ULN2003A | Driver IC MPN |
| `ref` | string |  | U | Reference designator for the IC |
| `vcoil_net` | string |  | VCOIL | Relay coil supply rail net name |
| `drive_net` | string |  | RELAY_DRV | MCU drive signal net name (or base name for multi-channel) |
| `channels_used` | number |  | 1 | Number of relay channels to wire up |
| `vdrive` | number |  | 3.3 | MCU GPIO drive voltage in volts |

### Example

```yaml
power:
  - type: relay_driver
    ref: U1
    vcoil: 12
    icoil: 0.05
```

---

## `rs485_transceiver`

RS-485 half-duplex transceiver with failsafe bias and optional termination

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `ic` | string |  | SP3485EN-L/TR | RS-485 transceiver IC MPN |
| `ref` | string |  | U | Reference designator for the transceiver |
| `vdd_net` | string |  | VDD_3P3 | Supply rail net name |
| `txd_net` | string |  |  | TXD signal net from MCU (connects to DI) |
| `rxd_net` | string |  |  | RXD signal net to MCU (connects to RO) |
| `de_net` | string |  |  | Driver enable net (active high, shared with RE_N for half-duplex) |
| `bus_net_prefix` | string |  | RS485 | Prefix for A/B bus nets |
| `termination` | boolean |  | False | Enable 120R termination between A and B |
| `failsafe_bias` | boolean |  | True | Enable failsafe bias resistors (A pull-up, B pull-down) |

### Example

```yaml
interfaces:
  - type: rs485_transceiver
    ref: U1
```

---

## `rtc`

Real-time clock with backup battery and I2C interface

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `ic` | string |  | DS3231 | RTC IC MPN |
| `ref` | string |  | U | Reference designator for the IC |
| `vdd_net` | string |  | VDD_3P3 | Main supply net name |
| `vbat_net` | string |  | VBAT_RTC | Backup battery net name |
| `sda_net` | string |  | I2C_SDA | I2C SDA net name |
| `scl_net` | string |  | I2C_SCL | I2C SCL net name |
| `int_net` | string |  |  | Interrupt/alarm output net name |

### Example

```yaml
digital:
  - type: rtc
    ref: U1
```

---

## `sensor_frontend`

Instrumentation amplifier front-end with gain resistor and filtering

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `gain` | number | Yes |  | Desired voltage gain (>=1) |
| `ic` | string |  | INA128PA | Instrumentation amplifier IC MPN |
| `ref` | string |  | U | Reference designator for the IC |
| `vdd_net` | string |  | VDD_3P3 | Positive supply rail net name |
| `gnd_net` | string |  | GND | Ground net name |
| `sensor_p_net` | string |  | SENSOR_P | Positive sensor input net name |
| `sensor_n_net` | string |  | SENSOR_N | Negative sensor input net name |
| `output_net` | string |  |  | Amplifier output net name; defaults to INA_OUT_{ref} |
| `filter_bw` | number |  |  | Anti-alias filter cutoff frequency in Hz (optional) |

### Example

```yaml
analog:
  - type: sensor_frontend
    ref: U1
    gain: 10
```

---

## `spi_bus`

SPI bus series termination or level shifter

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `ic` | string |  | RESISTORS_ONLY | SPI bus topology (RESISTORS_ONLY or SN74LVC1T45) |
| `ref` | string |  | RP | Reference designator |
| `speed_mhz` | number |  | 10 | SPI clock speed in MHz |
| `z_trace` | number |  | 50 | PCB trace impedance in ohms (for series termination) |
| `vdd_net` | string |  | VDD_3P3 | SPI bus supply net name |
| `mosi_net` | string |  | SPI_MOSI | MOSI signal net name |
| `miso_net` | string |  | SPI_MISO | MISO signal net name |
| `sclk_net` | string |  | SPI_SCLK | SCLK signal net name |
| `cs_net` | string |  | SPI_CS_N | Chip select net name (directly passed through) |
| `vcca_net` | string |  |  | Low-side voltage for level shifter (A side) |
| `vccb_net` | string |  |  | High-side voltage for level shifter (B side) |

### Example

```yaml
interfaces:
  - type: spi_bus
    ref: U1
```

---

## `usb_c_connector`

USB Type-C receptacle with CC resistors and VBUS decoupling

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `ic` | string |  | USB4125-GF-A | USB-C connector MPN |
| `ref` | string |  | J | Reference designator for the connector |
| `role` | string |  | device | USB role: device (5.1k pull-down) or source (Rp to VBUS) (device, source) |
| `vbus_net` | string |  | VBUS | VBUS power net name |
| `dp_net` | string |  | USB_DP | USB D+ signal net name |
| `dn_net` | string |  | USB_DN | USB D- signal net name |
| `esd` | boolean |  | True | Add ESD protection on data lines |
| `usb3` | boolean |  | False | Expose USB 3.x SuperSpeed pairs (full pinout connectors only) |

### Example

```yaml
interfaces:
  - type: usb_c_connector
    ref: U1
```

---

## `usb_controller`

USB controller with decoupling, boot straps, and data bus

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `ic` | string |  | CYUSB3014 | USB controller IC MPN |
| `ref` | string |  | U | Reference designator for the controller |
| `mode` | string |  | device | USB operating mode (device, host) |
| `data_bus` | string |  |  | Data bus type such as GPIF or UART |
| `vdd_net` | string |  |  | Primary controller supply net name |
| `usb_dp_net` | string |  |  | USB D+ net name |
| `usb_dm_net` | string |  |  | USB D- net name |

### Example

```yaml
interfaces:
  - type: usb_controller
    ref: U1
```

---

## `usb_hub`

USB hub with bias resistor, PLL filter, and port configuration

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `ic` | string |  | USB2514B | USB hub IC MPN |
| `ref` | string |  | U | Reference designator for the hub |
| `ports` | integer |  | 4 | Number of downstream ports |
| `vdd_net` | string |  |  | Primary hub supply net name |

### Example

```yaml
interfaces:
  - type: usb_hub
    ref: U1
```

---

## `voltage_reference`

Precision voltage reference (series or shunt topology)

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `ic` | string |  | REF3030 | Voltage reference IC MPN |
| `ref` | string |  | U | Reference designator for the IC |
| `vin_net` | string |  | VDD_3P3 | Input supply net name |
| `vref_net` | string |  |  | Output reference net name; defaults to VREF_{vout}V |
| `iload` | number |  | 0.001 | Expected load current in amps (used for shunt resistor sizing) |
| `vin` | number |  |  | Input voltage in volts (used for shunt resistor calculation) |

### Example

```yaml
power:
  - type: voltage_reference
    ref: U1
```

---

## `wireless_module`

WiFi/BLE wireless module with decoupling and boot config

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `ic` | string |  | ESP32-S3-WROOM-1 | Wireless module MPN |
| `ref` | string |  | U | Reference designator for the module |
| `vdd_net` | string |  | VDD_3P3 | Supply rail net name |
| `txd_net` | string |  | UART_TXD | UART TXD net name (ESP32 only) |
| `rxd_net` | string |  | UART_RXD | UART RXD net name (ESP32 only) |

### Example

```yaml
digital:
  - type: wireless_module
    ref: U1
```

---
