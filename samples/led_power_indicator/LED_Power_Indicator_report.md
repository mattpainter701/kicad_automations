# LED_Power_Indicator — Design Report

**Company:** Demo Corp  
**Date:** 2026-04-02  
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

## Circuit Validation

All checks passed — no algebraic circuit issues detected.

- PASS: Feedback dividers
- PASS: RC/LC filters
- PASS: Crystal load caps
- PASS: Decoupling coverage
