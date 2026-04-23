# Battery_IoT_Sensor — Design Report

**Company:** Demo Corp  
**Date:** 2026-04-23  
**Components:** 5  

## Power Tree

```
  external -> [CELL_U2] -> U2:CCELL
  U1 -> [VBAT] -> U2, U3, U1:CBAT, U2:CVDD, U3:CIN
  J1 -> [VBUS_5V] -> J1, J1:auto
  U3 -> [VDD_3P3] -> U4, U3:COUT, U4:2, U4:2
  external -> [VUSB_5V] -> U1, U1:CIN
```

## BOM Summary

- **Total ICs:** 5
- **Total passive instances:** 16
- **Total pins:** 63

| Category | Count |
|-|-|
| connector | 1 |
| mcu | 1 |
| power | 3 |

### Component List

| Ref | MPN | Value | Category | Pins | Bypass | Straps |
|-|-|-|-|-|-|-|
| U1 | MCP73831T-2ACI/OT | MCP73831T-2ACI/OT | power | 5 | 2 | 1 |
| U2 | MAX17048G+T | MAX17048G+T | power | 8 | 2 | 2 |
| U3 | TLV75518 | TLV75518 | power | 5 | 2 | 0 |
| U4 | ESP32-WROOM-32E | ESP32-WROOM-32E | mcu | 39 | 2 | 2 |
| J1 | USB-C-PWR | USB-C | connector | 6 | 1 | 2 |

## Design Rationale

### U1 — MCP73831T-2ACI/OT

- Charge VBAT: 0.5A into 4.2V cell from VUSB_5V
- Rprog = 1000 / 0.5A = 2k (actual 0.500A)
- Cin=4.7uF, Cbat=4.7uF
- Thermal: Pdiss = (Vin - Vbat) * Ichg = (5.0V - 4.2V) * 0.5A = 0.40W

### U2 — MAX17048G+T

- Fuel gauge MAX17048G+T: ModelGauge (voltage-based)
- Cell capacity: 2000mAh, I2C addr: 0x36
- CELL filter: 100R + 1uF
- QSTRT pulled low (quick start disabled)

### U3 — TLV75518

- VDD_3P3: 3.3V from VBAT at 0.5A (TLV75518)
- Dropout: 0.180V, Pdiss: 0.20W, Iq: 35uA

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
  - [WARNING] U1 MCP73831T-2ACI/OT: Net 'STAT_U1' has only one connection (pin 1 on U1) — likely dangling
  - [WARNING] U2 MAX17048G+T: Net 'I2C_SDA' has only one connection (pin 7 on U2) — likely dangling
  - [WARNING] U2 MAX17048G+T: Net 'I2C_SCL' has only one connection (pin 8 on U2) — likely dangling
  - [WARNING] U4 ESP32-WROOM-32E: Net 'UART0_RX' has only one connection (pin 34 on U4) — likely dangling
  - [WARNING] U4 ESP32-WROOM-32E: Net 'UART0_TX' has only one connection (pin 35 on U4) — likely dangling
- PASS: Enable/shutdown pins
- **WARN**: Bus completeness
  - [WARNING] U2 MAX17048G+T: I2C signal 'I2C_SCL' has no pull-up resistor
  - [WARNING] U2 MAX17048G+T: I2C signal 'I2C_SDA' has no pull-up resistor
- PASS: Pin type conflicts (ERC)
- PASS: Power budget
- PASS: Thermal limits
- PASS: Signal integrity
