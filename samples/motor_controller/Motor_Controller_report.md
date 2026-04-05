# Motor_Controller — Design Report

**Company:** Demo Corp  
**Date:** 2026-04-05  
**Components:** 2  

## Power Tree

```
  external -> [BST_U1] -> U1:CBST
  external -> [SW_U1] -> U1:L
  external -> [VDD_3P3] -> U2, U1:COUT, U2:36
  external -> [VIN_12V] -> U1, U1:CIN
```

## BOM Summary

- **Total ICs:** 2
- **Total passive instances:** 7
- **Total pins:** 14

| Category | Count |
|-|-|
| mcu | 1 |
| power | 1 |

### Component List

| Ref | MPN | Value | Category | Pins | Bypass | Straps |
|-|-|-|-|-|-|-|
| U1 | AP62300 | AP62300 | power | 6 | 4 | 2 |
| U2 | STM32F103C8T6 | STM32F103C8T6 | mcu | 8 | 1 | 0 |

## Design Rationale

### U1 — AP62300

- VDD_3P3: 3.3V from VIN_12V at 1A
- Vout = 0.8V * (1 + 316k/100k) = 3.328V
- L=12uH, Cin=10uF, Cout=3.3uF
- fsw=600kHz, ripple=0.33A (33%)

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
  - [WARNING] U2 STM32F103C8T6: Net 'BOOT0' has only one connection (pin 7 on U2) — likely dangling
  - [WARNING] U2 STM32F103C8T6: Net 'RESET_N' has only one connection (pin 44 on U2) — likely dangling
  - [WARNING] U2 STM32F103C8T6: Net 'SWDIO' has only one connection (pin 37 on U2) — likely dangling
  - [WARNING] U2 STM32F103C8T6: Net 'SWCLK' has only one connection (pin 34 on U2) — likely dangling
- PASS: Enable/shutdown pins
- PASS: Bus completeness
- PASS: Pin type conflicts (ERC)
