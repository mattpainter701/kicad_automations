# LED_Power_Indicator — Design Report

**Company:** Demo Corp  
**Date:** 2026-04-22  
**Components:** 2  

## Power Tree

```
  J1 -> [VBUS_5V] -> J1, U1, J1:auto, U1:CIN
  U1 -> [VDD_3P3] -> U1:COUT
```

## BOM Summary

- **Total ICs:** 2
- **Total passive instances:** 5
- **Total pins:** 11

| Category | Count |
|-|-|
| connector | 1 |
| power | 1 |

### Component List

| Ref | MPN | Value | Category | Pins | Bypass | Straps |
|-|-|-|-|-|-|-|
| U1 | TLV75518 | TLV75518 | power | 5 | 2 | 0 |
| J1 | USB-C-PWR | USB-C | connector | 6 | 1 | 2 |

## Design Rationale

### U1 — TLV75518

- VDD_3P3: 3.3V from VBUS_5V at 0.5A (TLV75518)
- Dropout: 0.180V, Pdiss: 0.85W, Iq: 35uA
- WARNING: Pdiss=0.85W > 500mW — needs heatsink or copper pour

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

All checks passed — no algebraic circuit issues detected.

- PASS: Pinout verification
- PASS: Feedback dividers
- PASS: RC/LC filters
- PASS: Crystal load caps
- PASS: Decoupling coverage
- PASS: Inductor selection
- PASS: Capacitor voltage ratings
- PASS: Net connectivity
- PASS: Enable/shutdown pins
- PASS: Bus completeness
- PASS: Pin type conflicts (ERC)
- PASS: Power budget
- PASS: Thermal limits
- PASS: Signal integrity
