# Tasks

> Work only on what's listed here. Check boxes as completed, update CHANGELOG.md alongside.

## Sprint 1 — Robust KiCad Import Pipeline (v0.2.0)

**Goal:** Make every KiCad-library-imported component generate a usable, non-broken schematic — no silent drops, no net collisions, no bare ICs missing decoupling.

### 1. Stop silently dropping components (P0, LARGE) — DONE

- [x] Create a stub `ComponentDef` with `category="unknown"` instead of returning `[]` — `_make_stub_component()` in `project_spec.py`
- [x] Add a warning annotation on the stub symbol ("UNRESOLVED — verify manually")
- [x] Stub created for: unknown template, template validation error, no type/ic, unknown IC
- [x] Validation detects stubs via "UNRESOLVED" annotation in `mvp.py:_validate_component_resolution()`

### 2. Auto-generate bypass caps for KiCad-imported ICs (P0, MEDIUM) — DONE

- [x] Verified `auto_generate_bypass_caps()` fires for KiCad imports (power_pins set, bypass_caps empty)
- [x] Fixed: power ICs (category=power, ref_prefix=U) bypass the 6-pin minimum threshold
- [x] Test: LM7805 (3 pins, power category) now gets decoupling caps
- [x] Test: built-in ICs with explicit caps are NOT double-capped
- [x] Test: connectors with power pins do NOT get auto-decoupling

### 3. Fix net name collisions on KiCad-imported signal pins (P0, LARGE) — DONE

- [x] `_apply_net_prefix()` in `project_spec.py`: prefixes generic pin names with ref designator
- [x] Generic set: G, S, D, IN, OUT, A, B, C, E, IN+, IN-, OUT+, OUT-, FB, EN, SW, BST, PG, SS, COMP, RT, SYNC, NC, ~
- [x] Global bus names preserved: SDA, SCL, MOSI, MISO, TX, RX, D+, D-, CAN_H/L, SWDIO, SWCLK, etc.
- [x] Short names (<=3 chars) also prefixed as safety net
- [x] Test: two BSS138s get separate gate nets (Q1_G, Q2_G)

### 4. Map KiCad power pin names to project rail names (P1, MEDIUM) — DONE

- [x] `_apply_power_map()` in `project_spec.py`: remaps raw KiCad power pin names
- [x] Optional `power_map` dict in YAML: `power_map: {V+: VDD_5V, V-: GND}`
- [x] Default mapping: VCC/VDD→VDD_3P3, VBUS→VBUS_5V, GND/VSS/AGND/DGND→GND, VIN→VIN
- [x] Unknown power names preserved as-is
- [x] Test: explicit map overrides, default map applies, unknown names pass through

### 5. Add "Miscellaneous" sheet for unclassified components (P1, SMALL) — DONE

- [x] Added `misc` sheet category in `allocator.py` with title "Miscellaneous / Discrete"
- [x] Routes: unknown, protection, discrete, analog, misc categories → misc sheet
- [x] Default fallback changed from "mcu" to "misc" in `classify_component()`
- [x] Expanded `_SECTION_CATEGORY_MAP`: analog, discrete, motor, protection, audio, display, misc
- [x] Test: unknown/protection/discrete → misc, mcu → mcu, unrecognized → misc

### 6. Wire passive inference into resolver (P1, MEDIUM) — DONE

- [x] `_resolve_component()` now tries `infer_passive_component(ref, value)` before creating stub
- [x] Supports: `{value: "10k", ref: "R1"}` and `{value: "100nF", ref: "C1"}` in any YAML section
- [x] Footprint auto-inferred: R/C→0402, L→0805
- [x] Test: bare resistor and capacitor resolve to valid ComponentDefs
- [x] Test: missing ref still creates stub (can't infer passive type without ref prefix)

### 7. Add spec-vs-output reconciliation validation (P0, MEDIUM) — DONE

- [x] `_validate_component_resolution()` in `mvp.py` detects stub components via "UNRESOLVED" annotation
- [x] Emits `unresolved-component` structural error with the stub's reason message
- [x] Test: unresolved component produces stub with UNRESOLVED annotation
- [x] Test: valid spec passes validation cleanly

Files: `mvp.py`, `validator.py`

---

## Sprint 2 — Template Expansion & DFM Quality (v0.3.0)

**Goal:** Expand template coverage for common circuit patterns, improve category classification, and make generated schematics closer to hand-drawn quality.

### 8. Add op-amp subcircuit template (P1, LARGE)

Op-amps are one of the most common analog building blocks and have no template. Users must specify them as bare `ic:` entries with no auto-generated feedback network, bias resistors, or decoupling.

- [ ] Create `subcircuits/opamp.py` with `OpAmpTemplate`
- [ ] Support configurations: inverting, non-inverting, voltage follower, differential
- [ ] Auto-generate feedback resistors from gain parameter
- [ ] Auto-generate input bias resistors where needed
- [ ] Auto-generate decoupling caps on supply pins
- [ ] Add to template registry in `subcircuits/base.py`
- [ ] Add tests for each configuration

Files: `subcircuits/opamp.py`, `subcircuits/base.py`

### 9. Add protection/ESD subcircuit template (P1, MEDIUM)

TVS diodes, ESD protection arrays, and reverse-polarity circuits are common and repetitive. No template exists.

- [ ] Create `subcircuits/protection.py` with `ProtectionTemplate`
- [ ] Support types: TVS (uni/bidirectional), ESD array, reverse polarity (P-FET, Schottky)
- [ ] Auto-generate per connector/interface usage
- [ ] Add to template registry
- [ ] Add tests

Files: `subcircuits/protection.py`, `subcircuits/base.py`

### 10. Add gate driver / level shifter template (P2, MEDIUM)

Common in motor control, LED driving, and mixed-voltage designs. Currently requires manual `ic:` entries.

- [ ] Create `subcircuits/driver.py` with `GateDriverTemplate` and `LevelShifterTemplate`
- [ ] Support: half-bridge, full-bridge, bidirectional level shifter
- [ ] Auto-generate bootstrap caps, gate resistors, deadtime components
- [ ] Add to template registry
- [ ] Add tests

Files: `subcircuits/driver.py`, `subcircuits/base.py`

### 11. Improve KiCad import category classification (P1, MEDIUM)

`kicad_lib.symbol_to_component_def()` infers category from description keywords and ref prefix. It misses many cases — an RF amplifier gets classified as "digital", a power MOSFET as "discrete" with no subcategory.

- [ ] Expand the keyword→category mapping in `kicad_lib.py:251-263`
- [ ] Add library-name-based classification: `Regulator_*→power`, `Sensor_*→sensor`, `Amplifier_*→analog`, `Transistor_*→discrete`, `Diode_*→discrete`, `Driver_*→power`
- [ ] Pass the source library name through from `get_symbol_data()` to `symbol_to_component_def()`
- [ ] Add test: parts from known library categories get correct classification

Files: `kicad_lib.py`

### 12. Add external component database support (P2, LARGE)

The 22-part built-in registry is too small. Users need to be able to define their own component libraries with full bypass cap, strap, and power pin metadata — without editing Python source.

- [ ] Define a JSON schema for component definitions (matching ComponentDef fields)
- [ ] Add `ComponentRegistry.load_json(path)` method
- [ ] Support a `components.json` or `components/` directory in the project root
- [ ] Auto-load project-local component databases before falling back to KiCad library
- [ ] Add test: JSON-defined component resolves with full metadata

Files: `component_db.py`, `project_spec.py`

### 13. Improve motif renderer coverage (P2, MEDIUM)

The decoupling bank and strap ladder renderers from the presentation parity work only trigger for groups of 2+ passives sharing a rail. Single-passive topology-local items still use the generic sidecar placement, which can produce awkward positioning for LDO support clusters.

- [ ] Add compact LDO support cluster renderer: input cap, output cap, enable strap as a unit
- [ ] Add USB-C CC network block renderer: connector + 2 CC resistors as a visual group
- [ ] Improve sidecar fallback: when only 1 passive per pin, place it inline (horizontal) rather than offset
- [ ] Add visual regression tests comparing placed coordinates against expected ranges

Files: `placer.py`

### 14. Add footprint fallback heuristics for KiCad imports (P1, SMALL)

Some KiCad symbols have empty `Footprint` properties. The schematic generates but with missing footprints, breaking PCB transfer.

- [ ] In `kicad_lib.symbol_to_component_def()`: if footprint is empty, infer from pin count and package hints in the symbol name
- [ ] Common heuristics: 3-pin + "SOT" in name → SOT-23, 8-pin + "SOP/SOIC" → SOIC-8, 2-pin + ref=R/C/L → 0402
- [ ] Add a validation warning (not error) when footprint was inferred rather than specified
- [ ] Add test: symbol with no footprint gets a reasonable inference

Files: `kicad_lib.py`, `validator.py`

### 15. Add section-category extensibility (P2, SMALL)

Custom YAML sections like `analog:`, `motor_control:`, or `rf_frontend:` fall through to using the section name as the category, which the allocator doesn't recognize.

- [ ] Expand `_SECTION_CATEGORY_MAP` in `project_spec.py` with common additional sections
- [ ] Add: `analog→analog`, `discrete→discrete`, `motor→power`, `protection→protection`, `audio→analog`, `rf_frontend→rf`, `display→digital`, `power_distribution→power`, `misc→misc`
- [ ] Add test: custom section names map to correct sheet categories

Files: `project_spec.py`
