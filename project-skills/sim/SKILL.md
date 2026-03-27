---
name: sim
description: >
  Pre-fabrication simulation -- three-layer simulation stack for RF-capable PCBs:
  RF chain (scikit-rf), power/clock (LTspice/PyLTSpice), PCB EM (openEMS FDTD).
  Run before ordering to validate performance before spending on prototypes.
---

## Three-Layer Stack

### Layer 1 -- RF Chain (scikit-rf)

Cascades S2P files (filters, LNAs, mixers, PCB traces) to compute end-to-end
insertion loss, return loss, and noise figure across the signal chain.

```python
import skrf as rf

bpf   = rf.Network("sims/rf/filters/bpf_2450.s2p")
lna   = rf.Network("sims/rf/lna/lna.s2p")
trace = rf.Network("sims/rf/traces/microstrip_50ohm_5mm.s2p")

chain = bpf ** lna ** trace
print(f"IL @ 2.45 GHz: {-chain.s21.db[freq_idx]:.1f} dB")
print(f"NF: {chain.nf(T=290)[freq_idx]:.2f} dB")
```

**S2P sources (priority order):**
1. Vendor-measured data (request from manufacturer -- best)
2. Datasheet typical curves extracted with WebPlotDigitizer
3. Synthetic models (document clearly -- mark as unvalidated)

**Simulation targets (fill in per project):**

| Signal path | Target | Result |
|-|-|-|
| RX insertion loss | < X dB | TBD |
| TX insertion loss | < Y dB | TBD |
| Noise figure | < Z dB | TBD |

### Layer 2 -- Power / Clock (LTspice / PyLTSpice)

Transient and AC analysis of power supply circuits and clock distribution.
Validates regulator stability, output ripple, PDN impedance, and load response.

```python
from PyLTSpice import LTspice

lt = LTspice("sims/power/buck_3v3.asc")
lt.run()
vout = lt.get_trace("V(vout)")
ripple_mv = (vout.max() - vout.min()) * 1000
print(f"Output ripple: {ripple_mv:.1f} mV")
```

**Subcircuits to simulate (fill in per project):**

| Subcircuit | Analysis type | Key metric |
|-|-|-|
| Buck converter | Transient + AC | Ripple < X mV, phase margin > 45 deg |
| LDO | Transient | Dropout headroom, PSRR |
| Crystal oscillator | Transient | Startup time, frequency accuracy |
| PDN impedance | AC | Z < X mohm at operating frequency |

**SPICE model sources:**
- Manufacturer SPICE models (from product page -- preferred)
- IBIS models for digital ICs (use ibis2spice if needed)
- LTspice built-in library for generic models

### Layer 3 -- PCB EM (openEMS FDTD)

Full-wave electromagnetic simulation for antenna performance, via transitions,
edge coupling, and shielding effectiveness. Most expensive -- run selectively.

**Run Layer 3 for:**
- On-board antennas (patch, meandered monopole, chip antenna matching)
- Via transitions on high-speed interfaces (> 5 Gbps)
- Near-field coupling characterization between modules
- Shielding can effectiveness

**Skip Layer 3 for:**
- Standard passive components
- Well-characterized reference designs validated by manufacturer

```bash
# openEMS requires platform binary + Python bindings
# See: https://openems.de/start/
python3 sims/em/antenna/run_sim.py
```

## Directory Structure

```
sims/
  rf/         -- scikit-rf scripts + S2P files
  power/      -- LTspice .asc schematics + PyLTSpice runner scripts
  em/         -- openEMS geometry definitions + run scripts
  results/    -- output plots and summary JSONs (add to .gitignore if large)
```

## Pre-Fab Simulation Checklist

- [ ] Layer 1: All RF paths passing insertion loss targets
- [ ] Layer 1: Noise figure budget within sensitivity requirement
- [ ] Layer 2: All regulators stable (phase margin > 45 deg)
- [ ] Layer 2: Output ripple < specification on all rails
- [ ] Layer 2: PDN impedance < target at operating frequency
- [ ] Layer 3: Antenna efficiency > target (if on-board antenna)
- [ ] Layer 3: Via transitions characterized for high-speed interfaces

## Requirements

```bash
pip install scikit-rf PyLTSpice
# openEMS: see https://openems.de/start/ for platform-specific install
```
