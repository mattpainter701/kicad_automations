# Zigbee_Humidistat — Design Report

**Company:** Demo  
**Date:** 2026-04-23  
**Components:** 3  

## Power Tree

```
  U1 -> [VDD_3P3] -> U2, U3, U1:5, U2:auto, U3:auto
  external -> [VIN] -> U1
```

## BOM Summary

- **Total ICs:** 3
- **Total passive instances:** 3
- **Total pins:** 24

| Category | Count |
|-|-|
| mcu | 2 |
| power | 1 |

### Component List

| Ref | MPN | Value | Category | Pins | Bypass | Straps |
|-|-|-|-|-|-|-|
| U1 | AP2112K-3.3TRG1 | AP2112K-3.3 | power | 4 | 1 | 0 |
| U2 | CH340G | CH340G | mcu | 16 | 1 | 0 |
| U3 | PULLUPS_ONLY | PULLUPS_ONLY | mcu | 4 | 1 | 0 |

## Design Rationale

### U3 — PULLUPS_ONLY

- Unused: SDA(3): NC, SCL(4): NC

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
- **WARN**: Decoupling coverage
  - [WARNING] U1 AP2112K-3.3TRG1: VIN has no matching bypass cap
- PASS: Inductor selection
- PASS: Capacitor voltage ratings
- **WARN**: Net connectivity
  - [WARNING] U1 AP2112K-3.3TRG1: Net 'REG_EN' has only one connection (pin 3 on U1) — likely dangling
- PASS: Enable/shutdown pins
- PASS: Bus completeness
- PASS: Pin type conflicts (ERC)
- PASS: Power budget
- PASS: Thermal limits
- PASS: Signal integrity
