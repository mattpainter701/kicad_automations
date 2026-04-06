# WiFi_Sensor_v1 — Design Report

**Date:** 2026-04-05  
**Components:** 4  

## Power Tree

```
  external -> [BST_U2] -> U2:CBST
  external -> [SW_U2] -> U2:L
  U1 -> [VBAT] -> U1:CIN, U1:L
  U1 -> [VBUS_5V] -> U2, U1:COUT, U2:CIN
  external -> [VDD_3P3] -> U3, U4, U2:COUT, U3:2, U3:2 +1
```

## BOM Summary

- **Total ICs:** 4
- **Total passive instances:** 16
- **Total pins:** 59

| Category | Count |
|-|-|
| mcu | 1 |
| power | 2 |
| sensor | 1 |

### Component List

| Ref | MPN | Value | Category | Pins | Bypass | Straps |
|-|-|-|-|-|-|-|
| U1 | TPS61230A | TPS61230A | power | 6 | 3 | 2 |
| U2 | AP62300 | AP62300 | power | 6 | 4 | 2 |
| U3 | ESP32-WROOM-32E | ESP32-WROOM-32E | mcu | 39 | 2 | 2 |
| U4 | BME280 | BME280 | sensor | 8 | 1 | 0 |

## Design Rationale

### U1 — TPS61230A

- VBUS_5V: 5.0V from VBAT at 1.0A
- Vout = 0.5V * (1 + 9.09M/1M) = 5.045V
- L=1uH, Cin=10uF, Cout=22uF
- fsw=2500kHz, D=0.26, Iin_avg=1.35A

### U2 — AP62300

- VDD_3P3: 3.3V from VBUS_5V at 0.8A
- Vout = 0.8V * (1 + 316k/100k) = 3.328V
- L=8.2uH, Cin=10uF, Cout=2.2uF
- fsw=600kHz, ripple=0.23A (29%)

## Fabrication Notes

**PCB Specification:**
- Layer count: 2-layer sufficient
- Surface finish: ENIG or HASL lead-free (ENIG preferred for reliability)
- Solder type: Lead-free (RoHS)

**Assembly Notes:**
- **Fine-Pitch Components** — Paste stencil required; thermal pad via array recommended
- **SMT Assembly** — Stencil, pick-and-place, and reflow furnace required

**Design Checklist:**
- [ ] Gerbers exported and verified with Gerber viewer
- [ ] Component footprints match datasheets (especially fine-pitch packages)
- [ ] Thermal vias present under power dissipation components
- [ ] Solder mask clearance verified (0.1mm min from pad)
- [ ] Silkscreen text readable (>0.8mm height, >0.15mm width)

## Circuit Validation

- PASS: Feedback dividers
- PASS: RC/LC filters
- PASS: Crystal load caps
- PASS: Decoupling coverage
- PASS: Inductor selection
- PASS: Capacitor voltage ratings
- **WARN**: Net connectivity
  - [WARNING] U3 ESP32-WROOM-32E: Net 'UART0_RX' has only one connection (pin 34 on U3) — likely dangling
  - [WARNING] U3 ESP32-WROOM-32E: Net 'UART0_TX' has only one connection (pin 35 on U3) — likely dangling
  - [WARNING] U4 BME280: Net 'I2C_SDA' has only one connection (pin 3 on U4) — likely dangling
  - [WARNING] U4 BME280: Net 'I2C_SCL' has only one connection (pin 4 on U4) — likely dangling
  - [WARNING] U4 BME280: Net 'BME_SDO' has only one connection (pin 5 on U4) — likely dangling
- PASS: Enable/shutdown pins
- **WARN**: Bus completeness
  - [WARNING] U4 BME280: I2C signal 'I2C_SCL' has no pull-up resistor
  - [WARNING] U4 BME280: I2C signal 'I2C_SDA' has no pull-up resistor
- PASS: Pin type conflicts (ERC)
