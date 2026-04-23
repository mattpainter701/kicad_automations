# IoT_Sensor_Node — Design Report

**Company:** Demo Corp  
**Date:** 2026-04-22  
**Components:** 5  

## Power Tree

```
  external -> [BST_U1] -> U1:CBST
  external -> [SW_U1] -> U1:L
  J1 -> [VBUS_5V] -> J1, U1, J1:auto, U1:CIN
  U2 -> [VDD_1P8] -> U2:COUT
  external -> [VDD_3P3] -> U2, U3, U4, U1:COUT, U2:CIN +3
```

## BOM Summary

- **Total ICs:** 5
- **Total passive instances:** 16
- **Total pins:** 64

| Category | Count |
|-|-|
| connector | 1 |
| mcu | 1 |
| power | 2 |
| sensor | 1 |

### Component List

| Ref | MPN | Value | Category | Pins | Bypass | Straps |
|-|-|-|-|-|-|-|
| U1 | AP62300 | AP62300 | power | 6 | 4 | 2 |
| U2 | TLV75518 | TLV75518 | power | 5 | 2 | 0 |
| U3 | ESP32-WROOM-32E | ESP32-WROOM-32E | mcu | 39 | 2 | 2 |
| U4 | BME280 | BME280 | sensor | 8 | 1 | 0 |
| J1 | USB-C-PWR | USB-C | connector | 6 | 1 | 2 |

## Design Rationale

### U1 — AP62300

- VDD_3P3: 3.3V from VBUS_5V at 2A
- Vout = 0.8V * (1 + 316k/100k) = 3.328V
- L=3.3uH, Cin=10uF, Cout=6.8uF
- fsw=600kHz, ripple=0.57A (28%)

### U2 — TLV75518

- VDD_1P8: 1.8V from VDD_3P3 at 0.5A (TLV75518)
- Dropout: 0.180V, Pdiss: 0.75W, Iq: 35uA
- WARNING: Pdiss=0.75W > 500mW — needs heatsink or copper pour

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

- PASS: Pinout verification
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
- PASS: Power budget
- PASS: Thermal limits
- PASS: Signal integrity
