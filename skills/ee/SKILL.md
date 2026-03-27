---
name: ee
description: >
  Electrical and electronic engineering reference — circuit analysis, component
  selection, power supply design, signal integrity, RF, thermal, EMC, and test
  & measurement. Use for design questions, calculations, component vetting, and
  first-principles analysis.
---

## Core Circuit Laws

### DC Analysis
```
V = IR                           Ohm's Law
P = VI = I²R = V²/R             Power
KVL: ΣV around loop = 0         Kirchhoff's Voltage Law
KCL: ΣI into node = 0           Kirchhoff's Current Law
```

### Voltage Divider
```
Vout = Vin × R2 / (R1 + R2)
Rload effect: Vout_actual = Vin × (R2||Rload) / (R1 + R2||Rload)
For < 1% load error: Rload > 100 × R2
```

### Thevenin / Norton
```
Vth = open-circuit voltage at terminals
Rth = resistance seen from terminals with all sources zeroed (V→short, I→open)
In  = Vth / Rth
```

### Superposition
For linear circuits: activate one source at a time, zero others, sum results.

---

## Passive Components

### Resistors

| Parameter | Calculation | Notes |
|-|-|-|
| Power derate | P_rated × 0.5 at 70°C | Derate linearly to 0 at T_max |
| Noise (Johnson) | Vn = √(4kTRB) | k=1.38e-23, B=bandwidth |
| Tolerance effect | ΔVout/Vout = √(ΔR1²+ΔR2²) / (R1+R2) | Worst-case RSS |

**Standard E-series values:** E12 (10% tol), E24 (5%), E48 (2%), E96 (1%), E192 (0.5%)
**SMD sizes:** 0201, 0402 (¼W), 0603 (⅒W), 0805 (⅛W), 1206 (¼W), 2512 (1W)

### Capacitors

| Type | Voltage coeff | Temp coeff | Use case |
|-|-|-|-|
| C0G/NP0 | None | ±30 ppm/°C | Timing, RF, precision |
| X7R | Moderate (−80% at rated V) | ±15% (-55→125°C) | Decoupling |
| X5R | Higher | ±15% (-55→85°C) | Bulk, lower-cost decoupling |
| Y5V | Severe (−82% at rated V) | +22/−82% | Avoid for power |
| Electrolytic | Low | Varies | Bulk, low-freq only |
| Tantalum | Low | Stable | Bulk; high inrush risk |

**Derating rule:** Use caps at ≤ 50% rated voltage for X7R (capacitance drops ~20% at 50%). Check datasheet derating curves.

**Self-resonant frequency (SRF):** Above SRF, cap is inductive. Rule of thumb: 0402 MLCC SRF ≈ 200–600 MHz, 0201 ≈ 1–3 GHz.

**Decoupling placement:** Place closest cap to IC power pin first. Cascade: bulk (10–100 µF) + mid (1–10 µF) + HF (100 nF) + ultra-HF (10 nF). Minimize loop area.

### Inductors

```
V = L × dI/dt
Isat: current at which inductance drops 20–30%
Irms: continuous current at rated temperature rise
Q = ωL / R_dc                   Quality factor
SRF: above this, acts capacitive
```

**DCR power loss:** P = I² × DCR. Key spec for power inductors.
**Saturation:** Never exceed Isat. Size to Ipeak × 1.3 minimum margin.

---

## RC / LC Circuits

### RC Low-Pass Filter
```
fc = 1 / (2π × R × C)           Cutoff frequency (-3 dB)
Attenuation at f: A = 1 / √(1 + (f/fc)²)
Phase shift:      φ = -arctan(f/fc)
```

### RC High-Pass Filter
```
fc = 1 / (2π × R × C)
A = (f/fc) / √(1 + (f/fc)²)
```

### LC Resonant Circuit
```
f0 = 1 / (2π × √(L × C))        Resonant frequency
Q  = (1/R) × √(L/C)             Series resonance
BW = f0 / Q                     Bandwidth at -3 dB
Z  = √(L/C)                     Characteristic impedance
```

### π / T filter (EMC)
π: cap–inductor–cap (low impedance source/load)
T: inductor–cap–inductor (high impedance source/load)

---

## Op-Amps

### Ideal Op-Amp Rules
1. V+ = V− (virtual short)
2. Input current = 0

### Common Configurations

| Config | Gain | Formula |
|-|-|-|
| Inverting | −Rf/Rin | Vout = -(Rf/Rin) × Vin |
| Non-inverting | 1 + Rf/Rin | Vout = (1 + Rf/Rin) × Vin |
| Voltage follower | 1 | Vout = Vin |
| Differential | Rf/Rin | Vout = (Rf/Rin)(V+ − V−) |
| Integrator | −1/(RC×s) | Vout = −(1/RC)∫Vin dt |
| Differentiator | −RC×s | Vout = −RC × dVin/dt |

### Key Specs
- **GBW (gain-bandwidth product):** Gain × BW = constant. Av=10 → BW = GBW/10.
- **Slew rate:** Maximum dVout/dt. Limits large-signal bandwidth: fmax = SR / (2π × Vpeak).
- **Input offset voltage (Vos):** DC error. Total output offset = Vos × (1 + Rf/Rin).
- **CMRR:** Common-mode rejection. Target > 80 dB for precision.
- **PSRR:** Power supply rejection. Decouple op-amp supplies with 100 nF close.

---

## Power Supply Design

### LDO Linear Regulator

```
Vout = Vref × (1 + R1/R2)       Adjustable output
Pdiss = (Vin - Vout) × Iout     Power dissipation (heat!)
η = Vout / Vin                  Efficiency (poor for large dropout)
```

**When to use LDO:** Low noise, small dropout (< 0.5V), < 500 mA, noise-sensitive analog/RF.
**Min dropout voltage:** Vin ≥ Vout + Vdropout (typically 100–300 mV for modern LDOs).
**Thermal check:** θJA × Pdiss < Tj_max − Tambient. Use exposed pad or heatsink if > 1W.

### Buck Converter (Step-Down)

```
D = Vout / Vin                  Duty cycle (ideal, continuous mode)
ΔIL = (Vin - Vout) × D / (L × fsw)    Inductor ripple current
ΔVout = ΔIL / (8 × C × fsw)    Output voltage ripple
Lmin = (Vin - Vout) × D / (2 × Iout × fsw)   Min L for CCM
```

**Component selection:**
- L: Isat > Iout + ΔIL/2. L value for 20–40% ripple ratio.
- Cin: rated for Vin, low ESR. Irms_cin = Iout × √(D(1-D)).
- Cout: C > ΔIL / (8 × fsw × ΔVout_spec). ESR < ΔVout / ΔIL.

**Layout rules:** Short, fat traces on switching node. Input cap right at Vin pin. GND plane under switcher. Keep Lx node away from feedback resistors.

### Boost Converter (Step-Up)

```
D = 1 - Vin/Vout               Duty cycle
ΔIL = Vin × D / (L × fsw)      Inductor ripple
Isat_req = Iout/(1-D) + ΔIL/2  Peak inductor current
```

### Power Budget Template

| Rail | Voltage | Current | Power |
|-|-|-|-|
| +3.3V_IO | 3.3V | xxx mA | xxx mW |
| +1.8V_DDR | 1.8V | xxx mA | xxx mW |
| +1.0V_CORE | 1.0V | xxx mA | xxx mW |
| **Total** | | | **xxx mW** |

Add 20% margin for thermal and headroom.

---

## Transistors

### BJT

```
IC = β × IB                    Collector current
VCE_sat ≈ 0.2V (ON), VBE ≈ 0.7V
IB_req = IC / (β × 0.1)       Force saturation: overdrive 10×
Pdiss = VCE × IC (linear) or VCEsat × IC (switch)
```

**Check:** IC < IC_max, VCE < VCEO, Pdiss < Pd_max.

### MOSFET

```
ID = (k/2)(VGS - Vth)²         Saturation
VGS > Vth + safety margin       Fully enhanced
Rds(on) varies with VGS and Tj: derate 2× from datasheet at 125°C vs 25°C
Pdiss (switch) ≈ ID² × Rds(on) + Qg × VGS × fsw
```

**Gate drive:** Sufficient VGS for low Rds(on). Drive impedance limits switching speed → EMI trade-off.
**Body diode:** Always present; check reverse recovery for high-side switches.

---

## Signal Integrity

### Transmission Lines

```
Z0 = √(L/C)                    Characteristic impedance
v  = 1/√(LC) = c/√(εr_eff)     Propagation velocity
λ  = v/f                       Wavelength
```

**Rule of thumb:** Treat trace as transmission line when length > λ/10 at the signal's knee frequency (≈ 0.35/tr for digital).

**Microstrip (PCB, trace over ground plane):**
```
Z0 ≈ (87/√(εr+1.41)) × ln(5.98H / (0.8W + T))
εr_eff ≈ (εr+1)/2 + (εr-1)/2 × (1+12H/W)^(-0.5)
```
- H = height to ground plane, W = trace width, T = trace thickness
- FR4: εr ≈ 4.0–4.5 (use 4.2 at 1 GHz), εr_eff ≈ 3.0

**Stripline (buried trace between planes):** Fully enclosed, εr_eff = εr, no dispersion. Use for tight impedance control.

**Termination:**
- Series: R = Z0, at source. Eliminates reflections at load (point-to-point).
- Parallel: R = Z0 to GND, at load. Eliminates reflections at source (multi-drop).
- AC: cap in series with R. DC-blocking parallel termination.

### Return Paths

Signal current returns via lowest impedance path — not the shortest ground path. At high frequency, this is directly beneath the signal trace (the image current in the reference plane).

**Rules:**
- Never split ground plane under a high-speed signal. Splits force current around the gap → loop antenna.
- Cross splits only through bypass caps bridging the split.
- Via stitching closes return path at layer transitions.

### Crosstalk

```
NEXT (near-end) ≈ (Cm/C0 + Lm/L0) / 4
FEXT (far-end)  ≈ (Cm/C0 - Lm/L0) / 4 × TD
```

**Reduce crosstalk:** Increase trace spacing (3W rule: spacing ≥ 3× trace width), reduce parallel run length, use ground guard traces, use differential pairs.

---

## RF Design

### dB Reference Table

| Power ratio | dB |
|-|-|
| 2× | +3 dB |
| 10× | +10 dB |
| 0.5× | −3 dB |
| 0.1× | −10 dB |

**dBm:** Power relative to 1 mW. 0 dBm = 1 mW, +30 dBm = 1 W.
**dBW:** Relative to 1 W. 0 dBW = +30 dBm.

### RF Chain Budget

```
Pout = Pin + Gain − Losses
NF_total = NF1 + (NF2-1)/G1 + (NF3-1)/(G1×G2) + ...   (Friis formula)
IP3_total: 1/IP3_in = 1/IP3_1 + G1/IP3_2 + G1G2/IP3_3 ...
```

**Sensitivity:** Sens = kTB + NF + SNRmin = −174 + 10log(BW) + NF + SNRmin [dBm]

### S-Parameters

| Parameter | Meaning |
|-|-|
| S11 | Input reflection (return loss). Good: < −10 dB |
| S21 | Forward gain (or insertion loss if passive) |
| S22 | Output reflection |
| S12 | Reverse isolation |

**Return loss:** RL = −20 log|Γ|. VSWR = (1+|Γ|)/(1−|Γ|).
**Insertion loss:** IL = −20 log|S21| for a 2-port.

### Impedance Matching (L-network)

Given Rsource → Rload (both real, Rsource > Rload):
```
Q = √(Rsource/Rload - 1)
Xs (series element) = Q × Rload
Xp (shunt element) = Rsource / Q
```

BW ≈ f0/Q. Use π or T networks for narrower BW.

---

## Thermal Design

### Heat Flow

```
Tj = Ta + Pdiss × (θJC + θCS + θSA)
θJA = θJC + θCS + θSA          Junction-to-ambient total
```

- θJC: Junction-to-case (datasheet)
- θCS: Case-to-sink (thermal interface material — TIM)
- θSA: Sink-to-ambient (heatsink spec, depends on airflow)
- Ta: Ambient temperature

**Copper area as heatsink:** 1 in² of 1 oz copper ≈ 50–70°C/W (still air). Doubles with 2 oz copper.

**Thermal via:** Each via ≈ 3–10°C/W. Use arrays under exposed pads (QFN, BGA). Guideline: 1 via per 100 mW for QFN.

**Derate components:** At T > 25°C, many parameters degrade. Check derating curves: Rds(on) of MOSFETs typically doubles 25→125°C.

### Junction Temp Check

```
Tj_max (datasheet) — Tj_operating ≥ 10°C margin
Tj = Ta + Pdiss × θJA
```

If Tj > limit: reduce Pdiss, increase copper area, add heatsink, improve airflow, choose lower Rds(on) part.

---

## EMC

### Emission Reduction

**Common-mode filter:** Series CM choke + shunt caps (π filter) on cable exits.
**Differential-mode filter:** LC filter on power lines.
**Shielding:** Enclosure or shielded connector. Ground the shield at one point (low-freq) or both (high-freq > 1 MHz).

### Layout Rules for EMC

1. **Minimize loop areas** — current loops are antennas. Keep signal and return traces close.
2. **Solid ground plane** — no splits under switching circuits or clock lines.
3. **Separate grounds** — AGND and DGND joined at single star point (or solid plane with careful routing).
4. **Decoupling every IC** — 100 nF + bulk cap, right at VCC pins, shortest possible trace.
5. **Clock/oscillator** — keep under metal (internal layer or add copper pour), surround with GND vias.
6. **High-current loops first** — SMPS switching loop, gate drive loop. Minimize physically.

### Common Failure Modes

| Symptom | Likely cause |
|-|-|
| Oscillation in amplifier | Parasitic feedback, missing decoupling |
| SMPS noise on analog rail | Insufficient filtering, layout ground loop |
| Erratic digital behavior | Ground bounce, inadequate bulk caps |
| ESD latchup | Missing ESD diodes on I/O, wrong ground return |
| EMC emission at clock frequency | Clock harmonics, inadequate shielding |

---

## Protection Circuits

### ESD Protection

- **TVS diode:** Clamp voltage, bidirectional or unidirectional. Select Vclamp < IC's abs max.
- **Rail-to-rail TVS:** One device per supply rail.
- **Line protection:** Series R (33–100 Ω) + TVS to GND. Limits ESD current into IC.

### Overcurrent Protection

```
Ifuse = Imax_load × 1.5        Fuse rating (with 50% margin)
Rsense = Vsense / Ilimit       Current sense resistor (Vsense typically 50–100 mV)
```

**Polyfuse (PPTC):** Self-resetting. Trips when Joule heating exceeds threshold. Slow — not for fast faults.
**Ideal diode / load switch:** MOSFET-based, fast, no voltage drop.

### Reverse Polarity

- Series diode (Schottky): Simple, 0.3–0.5V drop.
- P-channel MOSFET: Near-zero drop, controlled by gate. Source to input+, drain to load+, gate through R to GND, TVS gate-source.

### Overvoltage

- Clamp: TVS or Zener in parallel with load.
- Crowbar (SCR): Fires on OV event, blows fuse. Latching — requires power cycle.
- Ideal OVP: Comparator + MOSFET series switch. Non-latching.

---

## Test & Measurement

### Oscilloscope Setup

| Setting | Rule of Thumb |
|-|-|
| Bandwidth | ≥ 5× signal bandwidth (≥ 3.5× for digital: 0.35/tr) |
| Sample rate | ≥ 5× signal bandwidth |
| Probe compensation | Square-wave comp at 1 kHz before measuring |
| Ground clip | Shortest possible — loop is antenna |
| Probe loading | 10 MΩ ‖ 10 pF at 1× → use 10× probe (10 MΩ ‖ 1 pF) for fast signals |

**Measure power supply noise:** AC-couple, 20 MHz BW limit, 100 mV/div. Short probe ground.

### DMM Tips

- Resistance: Power off, discharge caps, avoid measuring in-circuit (parallel paths).
- Diode test: 0.3–0.5V = Schottky/Ge, 0.6–0.7V = Si, OL = open, ~0 = short/zener-in-circuit.
- Continuity: Not reliable for detecting shared return paths (other paths sink current).

### Spectrum Analyzer / Tinker SA

- Resolution bandwidth (RBW): narrower → slower sweep, better sensitivity.
- Reference level: Set 10 dB above expected signal.
- Span: Start wide, then zoom in.
- Input protection: Know your max input power. +10 dBm (10 mW) is common; check before connecting.

### Calibration / Null Measurements

- Use 4-wire (Kelvin) sensing for resistance < 10 Ω to eliminate lead resistance.
- Thermal EMF (Seebeck effect) corrupts µV-level DC measurements. Use DC reversal method.
- Lock-in amplifier: Detect signals buried in noise; phase-lock to known reference.

---

## Component Selection Checklist

For every component in a new design:

- [ ] **MPN specified** (no generic "10k 0402")
- [ ] **Package confirmed** against footprint (SOT-23-3 vs SOT-23-5 etc.)
- [ ] **Voltage rated** at ≥ 2× nominal (caps), or Vds/Vce > max circuit voltage
- [ ] **Current rated** at ≥ 1.5× max operating current
- [ ] **Temperature range** covers operating range (-40→+85°C industrial, -40→+125°C automotive)
- [ ] **Lifecycle** — not obsolete/NRND; check DigiKey/Mouser lifecycle status
- [ ] **Lead time** and stock verified at target quantity
- [ ] **Datasheet read** — verify application circuit, decoupling, Abs Max ratings
- [ ] **Datasheet pinout** confirmed against KiCad symbol (especially SOT-23 BJTs/MOSFETs)

---

## Quick Reference — Standard Values

### Resistor Values (E24 common subset)
1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0, 3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1 (× 10^n)

### Capacitor Common Values
1, 1.5, 2.2, 3.3, 4.7, 10, 22, 47, 100 nF; 1, 2.2, 4.7, 10, 22, 47, 100 µF

### Typical I²C Pull-Up Values
- 3.3V, 400 kHz (fast-mode): 2.2 kΩ – 4.7 kΩ
- 3.3V, 100 kHz (standard): 4.7 kΩ – 10 kΩ
- 1.8V, 400 kHz: 1 kΩ – 2.2 kΩ

### Crystal Load Capacitors
```
CL_ext = 2 × CL_spec − Cstray     (Cstray ≈ 3–5 pF)
Typical: 12 pF spec → 18–22 pF external caps
```

### USB Signal Integrity
- USB 2.0 FS/HS differential impedance: 90 Ω ± 15%
- USB 3.x differential impedance: 85 Ω ± 15%
- USB 3.x max length: 1m (channel loss < 8 dB at Nyquist)

---

## Integration with KiCad Skills

This skill feeds the rest of the EDA workflow:

| Calculation | → Use in |
|-|-|
| Voltage divider for VREF | `kicad_validate`: verify feedback resistors |
| LDO dropout check | `kicad_validate`: verify rail headroom |
| Inductor current ripple | `bom`: confirm Isat rating from DigiKey |
| Crystal load caps | `kicad_validate`: verify Cload in schematic |
| I²C pull-up values | `analyze_schematic.py` bus detection output |
| Signal trace impedance | `analyze_pcb.py` trace width + stackup |
| Thermal check | `kicad_validate`: flag missing thermal vias |
| EMC filter values | `sim/SKILL.md` Layer 1 RF chain |
