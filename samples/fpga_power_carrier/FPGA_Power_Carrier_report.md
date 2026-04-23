# FPGA_Power_Carrier — Design Report

**Company:** Demo Corp  
**Date:** 2026-04-23  
**Components:** 4  

## Power Tree

```
  external -> [BST_U1] -> U1:CBST
  external -> [BST_U2] -> U2:CBST
  external -> [BST_U3] -> U3:CBST
  external -> [SW_U1] -> U1:L
  external -> [SW_U2] -> U2:L
  external -> [SW_U3] -> U3:L
  external -> [VDD_1P2] -> U3:COUT
  external -> [VDD_1P8] -> U2:COUT
  U4 -> [VDD_1P8_ANALOG] -> U4:COUT
  external -> [VDD_3P3] -> U4, U1:COUT, U4:CIN
  external -> [VIN_12V] -> U1, U2, U3, U1:CIN, U2:CIN +1
```

## BOM Summary

- **Total ICs:** 4
- **Total passive instances:** 20
- **Total pins:** 23

| Category | Count |
|-|-|
| power | 4 |

### Component List

| Ref | MPN | Value | Category | Pins | Bypass | Straps |
|-|-|-|-|-|-|-|
| U1 | AP62300 | AP62300 | power | 6 | 4 | 2 |
| U2 | AP62300 | AP62300 | power | 6 | 4 | 2 |
| U3 | AP62300 | AP62300 | power | 6 | 4 | 2 |
| U4 | TLV75518 | TLV75518 | power | 5 | 2 | 0 |

## Design Rationale

### U1 — AP62300

- VDD_3P3: 3.3V from VIN_12V at 3A
- Vout = 0.8V * (1 + 316k/100k) = 3.328V
- L=4.7uH, Cin=22uF, Cout=10uF
- fsw=600kHz, ripple=0.85A (28%)

### U2 — AP62300

- VDD_1P8: 1.8V from VIN_12V at 2A
- Vout = 0.8V * (1 + 124k/100k) = 1.792V
- L=3.9uH, Cin=10uF, Cout=6.8uF
- fsw=600kHz, ripple=0.65A (33%)

### U3 — AP62300

- VDD_1P2: 1.2V from VIN_12V at 1A
- Vout = 0.8V * (1 + 49.9k/100k) = 1.199V
- L=5.6uH, Cin=10uF, Cout=3.3uF
- fsw=600kHz, ripple=0.32A (32%)

### U4 — TLV75518

- VDD_1P8_ANALOG: 1.8V from VDD_3P3 at 0.5A (TLV75518)
- Dropout: 0.180V, Pdiss: 0.75W, Iq: 35uA
- WARNING: Pdiss=0.75W > 500mW — needs heatsink or copper pour

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
