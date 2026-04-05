# USB_UART_Bridge — Design Report

**Company:** Demo Corp  
**Date:** 2026-04-05  
**Components:** 5  

## Power Tree

```
  external -> [AVDD] -> U2, U2:C_BULK_AVDD, U2:C_HF_AVDD
  external -> [DVDDIO] -> U2, U2:C_BULK_DVDDIO, U2:C_HF_DVDDIO
  external -> [VBUS] -> U2, U2:C_BULK_VBUS, U2:C_HF_VBUS
  J1 -> [VBUS_5V] -> J1, U1, J1:auto, U1:CIN
  external -> [VDD] -> U2, U2:C_BULK_VDD, U2:C_HF_VDD
  U1 -> [VDD_3P3] -> U1:COUT
```

## BOM Summary

- **Total ICs:** 5
- **Total passive instances:** 15
- **Total pins:** 40

| Category | Count |
|-|-|
| connector | 1 |
| misc | 2 |
| power | 1 |
| usb | 1 |

### Component List

| Ref | MPN | Value | Category | Pins | Bypass | Straps |
|-|-|-|-|-|-|-|
| U1 | TLV75518 | TLV75518 | power | 5 | 2 | 0 |
| U2 | CYUSB3014 | CYUSB3014 | usb | 25 | 8 | 2 |
| D1 | SMBJ5.0A | SMBJ5.0A | misc | 2 | 0 | 0 |
| D2 | SMBJ5.0A | SMBJ5.0A | misc | 2 | 0 | 0 |
| J1 | USB-C-PWR | USB-C | connector | 6 | 1 | 2 |

## Design Rationale

### U1 — TLV75518

- VDD_3P3: 3.3V from VBUS_5V at 0.5A (TLV75518)
- Dropout: 0.180V, Pdiss: 0.85W, Iq: 35uA
- WARNING: Pdiss=0.85W > 500mW — needs heatsink or copper pour

### U2 — CYUSB3014

- USB device controller: CYUSB3014
- Bus: UART, Boot: SPI slave boot (PMODE[2:0]=1,0,Z)
- Decoupling VDD: 100nF + 10uF (1.2V)
- Decoupling VBUS: 100nF + 10uF (5.0V)
- Decoupling DVDDIO: 100nF + 10uF (1.8V)
- Decoupling AVDD: 100nF + 10uF (1.2V)
- Unused: PMODE2(H3): NC, PMODE1(H2): NC

### D1 — SMBJ5.0A

- Protection: SMBJ5.0A (unidirectional) on VBUS_5V
- Vrwm=5.0V, Vbr=6.4V, Vc=9.2V

### D2 — SMBJ5.0A

- Protection: SMBJ5.0A (unidirectional) on USB_DP
- Vrwm=5.0V, Vbr=6.4V, Vc=9.2V

## Fabrication Notes

**PCB Specification:**
- Layer count: 4-layer minimum (recommended 6-layer for thermal)
- Surface finish: ENIG (mandatory for BGA)
- Solder type: Lead-free (RoHS)

**Assembly Notes:**
- **BGA Assembly** — Requires X-ray inspection and controlled reflow profile
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
  - [WARNING] U2 CYUSB3014: Net 'USB_DP_U2' has only one connection (pin J1 on U2) — likely dangling
  - [WARNING] U2 CYUSB3014: Net 'USB_DM_U2' has only one connection (pin J2 on U2) — likely dangling
  - [WARNING] U2 CYUSB3014: Net 'SSRX_P_U2' has only one connection (pin K1 on U2) — likely dangling
  - [WARNING] U2 CYUSB3014: Net 'SSRX_N_U2' has only one connection (pin K2 on U2) — likely dangling
  - [WARNING] U2 CYUSB3014: Net 'SSTX_P_U2' has only one connection (pin K3 on U2) — likely dangling
  - [WARNING] U2 CYUSB3014: Net 'SSTX_N_U2' has only one connection (pin K4 on U2) — likely dangling
  - [WARNING] U2 CYUSB3014: Net 'GPIF_D0_U2' has only one connection (pin C1 on U2) — likely dangling
  - [WARNING] U2 CYUSB3014: Net 'GPIF_D1_U2' has only one connection (pin C2 on U2) — likely dangling
  - [WARNING] U2 CYUSB3014: Net 'GPIF_CLK_U2' has only one connection (pin C3 on U2) — likely dangling
  - [WARNING] U2 CYUSB3014: Net 'GPIF_CTL0_U2' has only one connection (pin C4 on U2) — likely dangling
  - [WARNING] U2 CYUSB3014: Net 'SPI_CLK_U2' has only one connection (pin G1 on U2) — likely dangling
  - [WARNING] U2 CYUSB3014: Net 'SPI_SSN_U2' has only one connection (pin G2 on U2) — likely dangling
  - [WARNING] U2 CYUSB3014: Net 'SPI_MISO_U2' has only one connection (pin G3 on U2) — likely dangling
  - [WARNING] U2 CYUSB3014: Net 'SPI_MOSI_U2' has only one connection (pin G4 on U2) — likely dangling
  - [WARNING] U2 CYUSB3014: Net 'RESET_N_U2' has only one connection (pin F1 on U2) — likely dangling
  - [WARNING] U2 CYUSB3014: Net 'XTALIN_U2' has only one connection (pin E1 on U2) — likely dangling
  - [WARNING] U2 CYUSB3014: Net 'XTALOUT_U2' has only one connection (pin E2 on U2) — likely dangling
  - [WARNING] U2 CYUSB3014: Net 'PMODE2_U2' has only one connection (pin H3 on U2) — likely dangling
  - [WARNING] U2 CYUSB3014: Net 'PMODE1_U2' has only one connection (pin H2 on U2) — likely dangling
  - [WARNING] D2 SMBJ5.0A: Net 'USB_DP' has only one connection (pin 1 on D2) — likely dangling
- PASS: Enable/shutdown pins
- PASS: Bus completeness
- PASS: Pin type conflicts (ERC)
