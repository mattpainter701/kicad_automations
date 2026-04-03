# USB_Regulated_Supply — Design Report

**Company:** Demo Corp  
**Date:** 2026-04-02  
**Components:** 3  

## Power Tree

```
  external -> [BST_U1] -> U1:CBST
  external -> [SW_U1] -> U1:L
  J1 -> [VBUS_5V] -> J1, U1, J1:auto, U1:CIN
  U2 -> [VDD_1P8] -> U2:COUT
  external -> [VDD_3P3] -> U2, U1:COUT, U2:CIN
```

## BOM Summary

- **Total ICs:** 3
- **Total passive instances:** 11
- **Total pins:** 17

| Category | Count |
|-|-|
| connector | 1 |
| power | 2 |

### Component List

| Ref | MPN | Value | Category | Pins | Bypass | Straps |
|-|-|-|-|-|-|-|
| U1 | AP62300 | AP62300 | power | 6 | 4 | 2 |
| U2 | TLV75518 | TLV75518 | power | 5 | 2 | 0 |
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

## Circuit Validation

All checks passed — no algebraic circuit issues detected.

- PASS: Feedback dividers
- PASS: RC/LC filters
- PASS: Crystal load caps
- PASS: Decoupling coverage
