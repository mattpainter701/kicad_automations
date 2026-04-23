# OLED_Display_Module — Design Report

**Company:** Demo Corp  
**Date:** 2026-04-23  
**Components:** 4  

## Power Tree

```
  external -> [C1P_U2] -> U2:C1P
  external -> [C2P_U2] -> U2:C2P
  external -> [RES_N_U2] -> U2:CRES
  J1 -> [VBUS_5V] -> J1, U1, J1:auto, U1:CIN
  external -> [VDD_1P8] -> U3, U3:C_VCCA
  U1 -> [VDD_3P3] -> U2, U3, U1:COUT, U2:CVDD, U2:CVDD_BULK +1
```

## BOM Summary

- **Total ICs:** 4
- **Total passive instances:** 15
- **Total pins:** 31

| Category | Count |
|-|-|
| connector | 1 |
| mcu | 2 |
| power | 1 |

### Component List

| Ref | MPN | Value | Category | Pins | Bypass | Straps |
|-|-|-|-|-|-|-|
| U1 | TLV75518 | TLV75518 | power | 5 | 2 | 0 |
| U2 | SSD1306 | SSD1306 | mcu | 12 | 5 | 2 |
| U3 | TXS0102 | TXS0102 | mcu | 8 | 2 | 1 |
| J1 | USB-C-PWR | USB-C | connector | 6 | 1 | 2 |

## Design Rationale

### U1 — TLV75518

- VDD_3P3: 3.3V from VBUS_5V at 0.5A (TLV75518)
- Dropout: 0.180V, Pdiss: 0.85W, Iq: 35uA
- WARNING: Pdiss=0.85W > 500mW — needs heatsink or copper pour

### U2 — SSD1306

- Display SSD1306: 128x64 OLED, I2C
- Reset RC delay: 10k * 100nF = 1.0ms
- Interface: I2C (DC=GND -> addr 0x3C)
- IREF: 909k (segment current set)
- Charge pump caps: 2x 2.2uF

### U3 — TXS0102

- Level shifter: TXS0102 (2ch)
- VCCA=VDD_1P8, VCCB=VDD_3P3

## Fabrication Notes

**PCB Specification:**
- Layer count: 2-layer sufficient
- Surface finish: ENIG or HASL lead-free (ENIG preferred for reliability)
- Solder type: Lead-free (RoHS)

**Assembly Notes:**
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
  - [WARNING] U2 SSD1306: Net 'I2C_SDA' has only one connection (pin 4 on U2) — likely dangling
  - [WARNING] U2 SSD1306: Net 'I2C_SCL' has only one connection (pin 3 on U2) — likely dangling
  - [WARNING] U2 SSD1306: Net 'VCOMH_U2' has only one connection (pin 9 on U2) — likely dangling
  - [WARNING] U3 TXS0102: Net 'LS_B1_U3' has only one connection (pin 1 on U3) — likely dangling
  - [WARNING] U3 TXS0102: Net 'LS_A1_U3' has only one connection (pin 4 on U3) — likely dangling
  - [WARNING] U3 TXS0102: Net 'LS_A2_U3' has only one connection (pin 5 on U3) — likely dangling
  - [WARNING] U3 TXS0102: Net 'LS_B2_U3' has only one connection (pin 8 on U3) — likely dangling
- PASS: Enable/shutdown pins
- **WARN**: Bus completeness
  - [WARNING] U2 SSD1306: I2C signal 'I2C_SCL' has no pull-up resistor
  - [WARNING] U2 SSD1306: I2C signal 'I2C_SDA' has no pull-up resistor
- PASS: Pin type conflicts (ERC)
- PASS: Power budget
- PASS: Thermal limits
- PASS: Signal integrity
