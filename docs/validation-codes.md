# Validation Codes

Circuit Weaver's validation pipeline runs a set of check categories. Each produces a `ValidationCheckResult` with status `PASS`, `WARN`, or `FAIL` and zero or more `ValidationIssue` items.

In `--strict` mode, warnings are promoted to errors.

## Hard-Gated Categories

Three validation categories are **hard-gated** at generation time — `generate_artifacts` always blocks on errors in any of them, regardless of `--no-require-valid`:

| Category | Purpose |
|-|-|
| `structural` | IR integrity: every block has a ref, every interface has a target. |
| `implementation` | Resolution results: footprints bound, symbols complete, pins consistent. |
| `placement_readiness` | **Sprint 41** — schematic is physically wired enough to forward-annotate to a PCB. |

`placement_readiness` promotes the following previously-soft codes:

- `single-pin-net` — a non-power signal net terminates at a single pin.
- `undriven-net` — a net has only input-side contributors and no driver.
- `i2c-missing-pullup` — an I2C_SDA / I2C_SCL net has no pull-up strap.
- `spi-floating-cs` — a chip-select pin is unhandled.
- `uart-unpaired` — a TX net has no matching RX (or vice versa).
- `floating-enable` — a regulator enable is unconnected (the part won't start).
- `floating-power-pin` — an IC power pin has no rail assignment.
- `unverified-pinout` — a stub-pinout IC lacks an explicit pin_map / `pinout_verified: true`.
- `orphan-interface` — **new Sprint 41** — a block declared an interface whose net no other block consumes.

`--no-require-valid` still bypasses **soft** electrical warnings: crystal-load tolerance, rc/lc-filter cutoff hints, cap-voltage derating hints, power-budget definition gaps, thermal margin warnings, signal-integrity termination hints.

## Check Categories

### feedback-divider

**What it checks:** Voltage divider ratios on regulator feedback (VREF) pins.

**Severity:** Error if divider ratio produces Vout outside ±10% of target.

**Fix:** Adjust R_top or R_bottom to match the regulator's datasheet formula: `Vout = Vref × (1 + R1/R2)`.

---

### rc-lc-filter

**What it checks:** RC and LC filter cutoff frequencies against expected ranges.

**Severity:** Warning if cutoff is far from typical application values.

**Fix:** Recalculate component values using `fc = 1 / (2π × R × C)` or `fc = 1 / (2π × √(L × C))`.

---

### crystal-load

**What it checks:** Crystal oscillator load capacitor coverage — whether the correct CL value is present.

**Severity:** Warning if load caps are missing or values don't match the crystal's specified CL.

**Fix:** Calculate: `CL_ext = 2 × CL_spec − Cstray` (Cstray ≈ 3–5 pF). Typical: 12 pF spec → 18–22 pF external caps.

---

### decoupling

**What it checks:** Bypass capacitor presence on every IC power pin.

**Severity:** Warning per uncovered power pin.

**Fix:** Add a 100 nF ceramic capacitor (C0G or X7R) close to each VCC/GND pair. Bulk caps (10–100 µF) for regulators.

---

### inductor-selection

**What it checks:** Switching converter inductor values are within plausible range (0.1 µH – 100 µH).

**Severity:** Warning if outside range.

**Fix:** Recalculate using the converter datasheet's inductor selection formula. Verify Isat > Ipeak × 1.3.

---

### cap-voltage

**What it checks:** Capacitor voltage derating — whether the rated voltage is at least 1.25× the rail voltage (80% derating rule).

**Severity:** Warning if rated voltage is too close to operating voltage.

**Fix:** Select a capacitor with voltage rating ≥ 2× nominal rail voltage (especially for X7R MLCCs, which lose capacitance under DC bias).

---

### net-connectivity

**What it checks:** Net integrity — single-pin nets (dangling wires) and undriven nets (no output or passive driver).

**Sub-codes:**
- `single-pin-net` — Net with only one connection (likely a dangling wire or missing connection).
- `undriven-net` — Net has inputs but no output or passive driver.

**Severity:** Error for single-pin nets, warning for undriven nets.

**Fix:** Connect the dangling wire to its intended destination, or add a no-connect flag if intentional.

---

### enable-pins

**What it checks:** Enable/shutdown pin connectivity on voltage regulators (EN, SHDN, CE pins).

**Sub-codes:**
- `floating-enable` — Enable pin left floating on a regulator.

**Severity:** Warning. A floating enable pin may cause the regulator to not start or oscillate.

**Fix:** Tie EN high through a resistor divider (for delayed startup) or directly to VIN. Tie SHDN high or connect to a control signal.

---

### bus-completeness

**What it checks:** Communication bus integrity — I2C pull-ups, SPI chip select, UART TX/RX pairing.

**Sub-codes:**
- `i2c-missing-pullup` — I2C SDA or SCL line without a pull-up resistor.
- `spi-floating-cs` — SPI chip select pin left floating.
- `uart-unpaired` — UART TX without matching RX (or vice versa).

**Severity:** Warning.

**Fix:** Add 4.7 kΩ pull-ups for I2C at 3.3V/100 kHz (2.2 kΩ for 400 kHz). Connect SPI CS to a GPIO or tie high/low. Ensure UART TX connects to the peer's RX.

---

### pin-type-conflicts

**What it checks:** Electrical rule check (ERC) for output-to-output driver conflicts on the same net.

**Sub-codes:**
- `output-conflict` — Multiple output drivers on the same net (bus contention).

**Severity:** Error.

**Fix:** Only one output driver per net. Use tri-state buffers or mux if multiple sources need to share a net.

---

## ValidationIssue Fields

Each issue contains:

| Field | Type | Description |
|-|-|-|
| `code` | string | Check code or sub-code (e.g., `single-pin-net`) |
| `level` | string | `error` or `warning` |
| `ref` | string | Component reference designator (e.g., `U1`) |
| `mpn` | string | Manufacturer part number |
| `message` | string | Human-readable description |
| `suggestion` | string | Actionable fix guidance (may be empty) |
