# Template Reference

Auto-generated from `param_schema` of all registered subcircuit templates.

**30 templates available.**

---

## `adc`

Precision ADC with anti-alias RC input filters

### Parameters

| Name | Type | Required | Default | Options |
|------|------|----------|---------|---------|
| `ic` | string |  | ADS1115IDGSR |  |
| `ref` | string |  | U |  |
| `vdd_net` | string |  | VDD_3P3 |  |
| `input_filter_bw` | number |  | 1000 |  |
| `channels` | number |  | 4 |  |
| `i2c_addr` | string |  | GND |  |
| `sda_net` | string |  | SDA |  |
| `scl_net` | string |  | SCL |  |
| `cs_net` | string |  |  |  |
| `spi_mosi_net` | string |  | MOSI |  |
| `spi_miso_net` | string |  | MISO |  |
| `spi_sck_net` | string |  | SCK |  |
| `vref_net` | string |  |  |  |

### Example

```yaml
power:
  - type: adc
    ref: U1
```

---

## `audio_amplifier`

Class-D audio amplifier with input coupling and decoupling

### Parameters

| Name | Type | Required | Default | Options |
|------|------|----------|---------|---------|
| `ic` | string |  | PAM8302AASCR |  |
| `ref` | string |  | U |  |
| `vdd_net` | string |  | VDD_3P3 |  |
| `audio_in_net` | string |  | AUDIO_IN |  |
| `f_low` | number |  | 100 |  |
| `speaker_impedance` | number |  | 8 |  |

### Example

```yaml
power:
  - type: audio_amplifier
    ref: U1
```

---

## `battery_charger`

Li-Ion/LiPo battery charger with programmable charge current

### Parameters

| Name | Type | Required | Default | Options |
|------|------|----------|---------|---------|
| `ichg` | number | Yes |  |  |
| `vcell` | number |  | 4.2 |  |
| `ic` | string |  | MCP73831T-2ACI/OT |  |
| `ref` | string |  | U |  |
| `vin_net` | string |  | VUSB |  |
| `bat_net` | string |  | VBAT |  |
| `stat_net` | string |  |  |  |

### Example

```yaml
power:
  - type: battery_charger
    ref: U1
    ichg: 3.3
```

---

## `battery_monitor`

Battery fuel gauge / state-of-charge monitor with I2C

### Parameters

| Name | Type | Required | Default | Options |
|------|------|----------|---------|---------|
| `ic` | string |  | MAX17048G+T |  |
| `ref` | string |  | U |  |
| `bat_net` | string |  | VBAT |  |
| `cell_capacity_mah` | number |  | 2000 |  |
| `rsense` | number |  |  |  |
| `i2c_bus` | string |  | I2C |  |

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

| Name | Type | Required | Default | Options |
|------|------|----------|---------|---------|
| `vin` | number | Yes |  |  |
| `vout` | number | Yes |  |  |
| `iout` | number | Yes |  |  |
| `ic` | string |  | TPS61230A |  |
| `ref` | string |  | U |  |
| `rail_name` | string |  |  |  |
| `vin_net` | string |  | VIN |  |
| `en_net` | string |  |  |  |
| `fsw` | number |  |  |  |
| `r_fbb` | number |  |  |  |

### Example

```yaml
power:
  - type: boost
    ref: U1
    vin: 3.3
    vout: 3.3
    iout: 3.3
```

---

## `buck`

Synchronous buck DC-DC converter with feedback divider

### Parameters

| Name | Type | Required | Default | Options |
|------|------|----------|---------|---------|
| `vin` | number | Yes |  |  |
| `vout` | number | Yes |  |  |
| `iout` | number | Yes |  |  |
| `ic` | string |  | AP62300 |  |
| `ref` | string |  | U |  |
| `rail_name` | string |  |  |  |
| `vin_net` | string |  | VIN |  |
| `en_net` | string |  |  |  |
| `fsw` | number |  |  |  |
| `r_fbb` | number |  |  |  |
| `ripple_ratio` | number |  | 0.3 |  |
| `vout_ripple` | number |  | 0.02 |  |

### Example

```yaml
power:
  - type: buck
    ref: U1
    vin: 3.3
    vout: 3.3
    iout: 3.3
```

---

## `buck_boost`

Buck-Boost DC-DC converter with feedback divider

### Parameters

| Name | Type | Required | Default | Options |
|------|------|----------|---------|---------|
| `vin` | number | Yes |  |  |
| `vout` | number | Yes |  |  |
| `iout` | number | Yes |  |  |
| `vin_min` | number |  |  |  |
| `vin_max` | number |  |  |  |
| `ic` | string |  | TPS63020 |  |
| `ref` | string |  | U |  |
| `rail_name` | string |  |  |  |
| `vin_net` | string |  | VBAT |  |
| `en_net` | string |  |  |  |
| `r_fbb` | number |  |  |  |

### Example

```yaml
power:
  - type: buck_boost
    ref: U1
    vin: 3.3
    vout: 3.3
    iout: 3.3
```

---

## `can_transceiver`

CAN bus transceiver with decoupling and optional split termination

### Parameters

| Name | Type | Required | Default | Options |
|------|------|----------|---------|---------|
| `ic` | string |  | SN65HVD230 |  |
| `ref` | string |  | U |  |
| `vdd_net` | string |  | VDD_3P3 |  |
| `txd_net` | string |  |  |  |
| `rxd_net` | string |  |  |  |
| `bus_net_prefix` | string |  | CAN |  |
| `termination` | boolean |  | False |  |
| `slope_control` | boolean |  | False |  |

### Example

```yaml
power:
  - type: can_transceiver
    ref: U1
```

---

## `charge_pump`

Inverting charge pump with flying cap and output cap

### Parameters

| Name | Type | Required | Default | Options |
|------|------|----------|---------|---------|
| `ic` | string |  | LM2776 |  |
| `ref` | string |  | U |  |
| `vin_net` | string |  | VDD_3P3 |  |
| `rail_name` | string |  | VNEG |  |
| `iout` | number |  | 0.05 |  |

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

| Name | Type | Required | Default | Options |
|------|------|----------|---------|---------|
| `ic` | string |  | AD9528 |  |
| `ref` | string |  | U |  |
| `ref_freq` | number |  | 30720000.0 |  |
| `pll_bw` | number |  | 20000.0 |  |
| `vdd_net` | string |  | VDD_1P8 |  |
| `vddo_net` | string |  |  |  |
| `ref_net` | string |  | REF_CLK |  |

### Example

```yaml
power:
  - type: clock_synth
    ref: U1
```

---

## `crystal_oscillator`

Crystal oscillator with load capacitors and feedback resistor

### Parameters

| Name | Type | Required | Default | Options |
|------|------|----------|---------|---------|
| `freq` | number | Yes |  |  |
| `cl_spec` | number | Yes |  |  |
| `c_stray` | number |  | 3e-12 |  |
| `ic` | string |  | ABM8G |  |
| `ref` | string |  | Y |  |
| `xtal_in_net` | string |  | XTAL_IN |  |
| `xtal_out_net` | string |  | XTAL_OUT |  |

### Example

```yaml
power:
  - type: crystal_oscillator
    ref: U1
    freq: 3.3
    cl_spec: 3.3
```

---

## `current_sense`

High-side current sense amplifier with auto-calculated Rsense

### Parameters

| Name | Type | Required | Default | Options |
|------|------|----------|---------|---------|
| `imax` | number | Yes |  |  |
| `vsense_target` | number |  | 0.05 |  |
| `ic` | string |  | INA219 |  |
| `ref` | string |  | U |  |
| `vdd_net` | string |  | VDD_3P3 |  |
| `sense_p_net` | string |  | SENSE_P |  |
| `sense_n_net` | string |  | SENSE_N |  |
| `sda_net` | string |  | I2C_SDA |  |
| `scl_net` | string |  | I2C_SCL |  |
| `out_net` | string |  |  |  |

### Example

```yaml
power:
  - type: current_sense
    ref: U1
    imax: 3.3
```

---

## `dac`

Digital-to-analog converter with output RC filter

### Parameters

| Name | Type | Required | Default | Options |
|------|------|----------|---------|---------|
| `ic` | string |  | MCP4725A0T |  |
| `ref` | string |  | U |  |
| `vdd_net` | string |  | VDD_3P3 |  |
| `update_rate` | number |  | 1000 |  |
| `vref` | string |  |  |  |
| `output_net` | string |  |  |  |
| `sda_net` | string |  | SDA |  |
| `scl_net` | string |  | SCL |  |
| `din_net` | string |  | MOSI |  |
| `sclk_net` | string |  | SCK |  |
| `sync_net` | string |  |  |  |
| `output_b_net` | string |  |  |  |

### Example

```yaml
power:
  - type: dac
    ref: U1
```

---

## `display_driver`

OLED/LCD display driver with reset circuit and interface config

### Parameters

| Name | Type | Required | Default | Options |
|------|------|----------|---------|---------|
| `ic` | string |  | SSD1306 |  |
| `ref` | string |  | U |  |
| `interface` | string |  | i2c |  |
| `vdd_net` | string |  | VDD_3P3 |  |
| `resolution` | string |  | 128x64 |  |
| `backlight` | boolean |  | False |  |
| `bl_current` | number |  | 0.02 |  |
| `bl_vf` | number |  | 3.0 |  |

### Example

```yaml
power:
  - type: display_driver
    ref: U1
```

---

## `ethernet_phy`

Gigabit Ethernet PHY with RGMII/RMII/MII interface

### Parameters

| Name | Type | Required | Default | Options |
|------|------|----------|---------|---------|
| `ic` | string |  | KSZ9031 |  |
| `ref` | string |  | U |  |
| `mode` | string |  | rgmii | rgmii, rmii, mii |
| `crystal_cl` | number |  | 9e-12 |  |
| `vdd_net` | string |  | VDD_3P3 |  |
| `gnd_net` | string |  | GND |  |
| `reset_net` | string |  | ETH_RESET_N |  |
| `mdio_net` | string |  | MDIO |  |
| `mdc_net` | string |  | MDC |  |

### Example

```yaml
power:
  - type: ethernet_phy
    ref: U1
```

---

## `gate_driver`

Gate driver IC with bootstrap and decoupling

### Parameters

| Name | Type | Required | Default | Options |
|------|------|----------|---------|---------|
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

| Name | Type | Required | Default | Options |
|------|------|----------|---------|---------|
| `vdd` | number |  | 3.3 |  |
| `speed` | number |  | 400000 |  |
| `c_bus` | number |  | 1e-10 |  |
| `ic` | string |  | PULLUPS_ONLY |  |
| `ref` | string |  | RP |  |
| `vdd_net` | string |  | VDD_3P3 |  |
| `sda_net` | string |  | I2C_SDA |  |
| `scl_net` | string |  | I2C_SCL |  |
| `vdd_low_net` | string |  |  |  |
| `vdd_high_net` | string |  |  |  |
| `sda_low_net` | string |  |  |  |
| `scl_low_net` | string |  |  |  |
| `sda_high_net` | string |  |  |  |
| `scl_high_net` | string |  |  |  |

### Example

```yaml
power:
  - type: i2c_bus
    ref: U1
```

---

## `ldo`

LDO linear regulator with decoupling

### Parameters

| Name | Type | Required | Default | Options |
|------|------|----------|---------|---------|
| `vin` | number | Yes |  |  |
| `vout` | number |  |  |  |
| `iout` | number |  |  |  |
| `ic` | string |  | TLV75518 |  |
| `ref` | string |  | U |  |
| `rail_name` | string |  |  |  |
| `vin_net` | string |  | VIN |  |
| `en_net` | string |  |  |  |

### Example

```yaml
power:
  - type: ldo
    ref: U1
    vin: 3.3
```

---

## `led_driver`

Constant-current LED driver (buck or linear sink)

### Parameters

| Name | Type | Required | Default | Options |
|------|------|----------|---------|---------|
| `iled` | number | Yes |  |  |
| `vled` | number |  | 3.0 |  |
| `num_leds` | number |  | 1 |  |
| `vin` | number |  | 12 |  |
| `ic` | string |  | AL8861Y-13 |  |
| `ref` | string |  | U |  |
| `vin_net` | string |  | VIN |  |

### Example

```yaml
power:
  - type: led_driver
    ref: U1
    iled: 3.3
```

---

## `level_shifter`

Bidirectional voltage level shifter

### Parameters

| Name | Type | Required | Default | Options |
|------|------|----------|---------|---------|
| `ic` | string |  | TXS0102 |  |
| `ref` | string |  | U |  |
| `vcca_net` | string |  | VDD_1P8 |  |
| `vccb_net` | string |  | VDD_3P3 |  |
| `gnd_net` | string |  | GND |  |

### Example

```yaml
power:
  - type: level_shifter
    ref: U1
```

---

## `mosfet_switch`

Low-side or high-side MOSFET switch with gate protection

### Parameters

| Name | Type | Required | Default | Options |
|------|------|----------|---------|---------|
| `iload` | number | Yes |  |  |
| `vdrive` | number |  | 3.3 |  |
| `ic` | string |  | BSS138 |  |
| `ref` | string |  | Q |  |
| `vdd_net` | string |  | VDD_3P3 |  |
| `load_net` | string |  |  |  |
| `gate_net` | string |  |  |  |
| `inductive` | boolean |  | False |  |

### Example

```yaml
power:
  - type: mosfet_switch
    ref: U1
    iload: 3.3
```

---

## `motor_driver`

Dual H-bridge motor driver with optional current limiting

### Parameters

| Name | Type | Required | Default | Options |
|------|------|----------|---------|---------|
| `vm` | number | Yes |  |  |
| `imotor` | number | Yes |  |  |
| `ic` | string |  | DRV8833 |  |
| `ref` | string |  | U |  |
| `vm_net` | string |  | VMOT |  |
| `vdd_net` | string |  | VDD_3P3 |  |
| `motor_type` | string |  | dc |  |

### Example

```yaml
power:
  - type: motor_driver
    ref: U1
    vm: 3.3
    imotor: 3.3
```

---

## `opamp`

Op-amp with configurable gain and feedback

### Parameters

| Name | Type | Required | Default | Options |
|------|------|----------|---------|---------|
| `ic` | string |  | LM358 |  |
| `ref` | string |  | U |  |
| `config` | string |  | non_inverting | non_inverting, inverting, follower, differential |
| `gain` | number |  | 1.0 |  |
| `rf` | number |  |  |  |
| `rin` | number |  |  |  |
| `vdd_net` | string |  | VDD_3P3 |  |
| `gnd_net` | string |  | GND |  |
| `in_net` | string |  |  |  |
| `out_net` | string |  |  |  |

### Example

```yaml
power:
  - type: opamp
    ref: U1
```

---

## `power_mux`

Auto-switching power mux or ideal diode OR controller

### Parameters

| Name | Type | Required | Default | Options |
|------|------|----------|---------|---------|
| `ic` | string |  | TPS2113ADRBR |  |
| `ref` | string |  | U |  |
| `ilim` | number |  | 1.0 |  |
| `vin1_net` | string |  | VUSB |  |
| `vin2_net` | string |  | VBAT |  |
| `vout_net` | string |  | VSYS |  |

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

| Name | Type | Required | Default | Options |
|------|------|----------|---------|---------|
| `ic` | string |  | SMBJ5.0A |  |
| `ref` | string |  | D |  |
| `protect_net` | string | Yes |  |  |
| `gnd_net` | string |  | GND |  |
| `protection_type` | string |  | tvs | tvs, esd |

### Example

```yaml
power:
  - type: protection
    ref: U1
    protect_net: <value>
```

---

## `relay_driver`

Relay coil driver with Darlington array or discrete NPN

### Parameters

| Name | Type | Required | Default | Options |
|------|------|----------|---------|---------|
| `vcoil` | number | Yes |  |  |
| `icoil` | number | Yes |  |  |
| `ic` | string |  | ULN2003A |  |
| `ref` | string |  | U |  |
| `vcoil_net` | string |  | VCOIL |  |
| `drive_net` | string |  | RELAY_DRV |  |
| `channels_used` | number |  | 1 |  |
| `vdrive` | number |  | 3.3 |  |

### Example

```yaml
power:
  - type: relay_driver
    ref: U1
    vcoil: 3.3
    icoil: 3.3
```

---

## `rs485_transceiver`

RS-485 half-duplex transceiver with failsafe bias and optional termination

### Parameters

| Name | Type | Required | Default | Options |
|------|------|----------|---------|---------|
| `ic` | string |  | SP3485EN-L/TR |  |
| `ref` | string |  | U |  |
| `vdd_net` | string |  | VDD_3P3 |  |
| `txd_net` | string |  |  |  |
| `rxd_net` | string |  |  |  |
| `de_net` | string |  |  |  |
| `bus_net_prefix` | string |  | RS485 |  |
| `termination` | boolean |  | False |  |
| `failsafe_bias` | boolean |  | True |  |

### Example

```yaml
power:
  - type: rs485_transceiver
    ref: U1
```

---

## `sensor_frontend`

Instrumentation amplifier front-end with gain resistor and filtering

### Parameters

| Name | Type | Required | Default | Options |
|------|------|----------|---------|---------|
| `gain` | number | Yes |  |  |
| `ic` | string |  | INA128PA |  |
| `ref` | string |  | U |  |
| `vdd_net` | string |  | VDD_3P3 |  |
| `gnd_net` | string |  | GND |  |
| `sensor_p_net` | string |  | SENSOR_P |  |
| `sensor_n_net` | string |  | SENSOR_N |  |
| `output_net` | string |  |  |  |
| `filter_bw` | number |  |  |  |

### Example

```yaml
power:
  - type: sensor_frontend
    ref: U1
    gain: 3.3
```

---

## `usb_controller`

USB controller with decoupling, boot straps, and data bus

### Parameters

| Name | Type | Required | Default | Options |
|------|------|----------|---------|---------|
| `ic` | string |  | CYUSB3014 |  |
| `ref` | string |  | U |  |
| `mode` | string |  | device | device, host |
| `data_bus` | string |  |  |  |
| `vdd_net` | string |  |  |  |
| `usb_dp_net` | string |  |  |  |
| `usb_dm_net` | string |  |  |  |

### Example

```yaml
power:
  - type: usb_controller
    ref: U1
```

---

## `usb_hub`

USB hub with bias resistor, PLL filter, and port configuration

### Parameters

| Name | Type | Required | Default | Options |
|------|------|----------|---------|---------|
| `ic` | string |  | USB2514B |  |
| `ref` | string |  | U |  |
| `ports` | integer |  | 4 |  |
| `vdd_net` | string |  |  |  |

### Example

```yaml
power:
  - type: usb_hub
    ref: U1
```

---
