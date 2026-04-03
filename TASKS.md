# Tasks

> Work only on what's listed here. Check boxes as completed, update CHANGELOG.md alongside.

## Sprint 1 — Robust KiCad Import Pipeline (v0.2.0)

**Goal:** Make every KiCad-library-imported component generate a usable, non-broken schematic — no silent drops, no net collisions, no bare ICs missing decoupling.

### 1. Stop silently dropping components (P0, LARGE)

When a component can't be resolved from the built-in registry OR KiCad library, the engine currently prints a WARNING and returns `[]` — the part vanishes from the design with no error code.

- [ ] Create a stub `ComponentDef` with `category="unknown"` instead of returning `[]` in `project_spec.py:191,198,219,226`
- [ ] Add a yellow warning annotation on the stub symbol ("UNRESOLVED — verify manually")
- [ ] Add an "Unknown" sheet category in `allocator.py` so stubs don't land on the MCU sheet
- [ ] Add validation check: count spec blocks vs output components, fail if mismatch

Files: `project_spec.py`, `allocator.py`, `validator.py`

### 2. Auto-generate bypass caps for KiCad-imported ICs (P0, MEDIUM)

KiCad library symbols have power pin information but no bypass cap metadata. An LM7805 imports with 0 decoupling caps. The engine already has `auto_generate_bypass_caps()` in `component_db.py` but it only fires for components that have power pins AND zero bypass caps defined.

- [ ] Verify `auto_generate_bypass_caps()` fires for KiCad-imported components (it should — they have `power_pins` but no `bypass_caps`)
- [ ] If it doesn't fire, wire it into `kicad_lib.symbol_to_component_def()` or the post-resolution step
- [ ] Add test: KiCad-imported IC with power pins gets at least one 100nF cap per supply pin
- [ ] Add test: built-in registry ICs with explicit caps are NOT double-capped

Files: `component_db.py`, `kicad_lib.py`, `generator.py:1257`

### 3. Fix net name collisions on KiCad-imported signal pins (P0, LARGE)

KiCad symbols use generic pin names like `G`, `S`, `D` (MOSFET) or `IN+`, `IN-` (op-amp). These become global net names, so two BSS138 FETs would both connect to a global "G" net — shorting their gates together.

- [ ] In `kicad_lib.symbol_to_component_def()`: prefix signal pin_nets with `{ref}_` when the pin name is short/generic (< 4 chars or matches a known-generic set)
- [ ] Build a generic-name set: `G, S, D, IN, OUT, A, B, C, E, IN+, IN-, OUT+, OUT-, FB, EN, SW, BST, PG, SS, COMP, RT, SYNC`
- [ ] Preserve actual bus names (SDA, SCL, MOSI, MISO, TX, RX, D+, D-) as global nets — these SHOULD be shared
- [ ] In `project_spec.py:229-240`: apply ref prefix to KiCad-imported pin_nets when `source_ref` is set
- [ ] Add test: two BSS138s in same design get separate gate nets

Files: `kicad_lib.py`, `project_spec.py`

### 4. Map KiCad power pin names to project rail names (P1, MEDIUM)

KiCad symbols use raw pin names for power: `V+`, `VI`, `VO`, `VCC`, `AVDD`. These don't match the project's rail names (`VDD_3P3`, `VBUS_5V`). Currently, an LM358's `V+` pin creates a net called "V+" instead of connecting to the project's actual positive rail.

- [ ] Add optional `power_map` dict to YAML spec items: `power_map: {V+: VDD_3P3, V-: GND}`
- [ ] In `project_spec.py:229-240`: apply power_map to `power_pins` dict after KiCad import
- [ ] Default mapping for common names: `VCC→VDD_3P3, VDD→VDD_3P3, VIN→VIN, VBUS→VBUS_5V, GND/VSS/AGND/DGND→GND`
- [ ] Add test: power_map overrides raw KiCad pin names

Files: `project_spec.py`, `kicad_lib.py`

### 5. Add "Miscellaneous" sheet for unclassified components (P1, SMALL)

The allocator defaults unknown categories to `"mcu"`. Discrete transistors, protection ICs, and anything without a matching category description silently lands on the MCU sheet.

- [ ] Add `"misc"` sheet category in `allocator.py` for components that don't match any known category
- [ ] Route `category="unknown"`, `category="protection"`, `category="discrete"`, and any unrecognized category to the misc sheet
- [ ] Give the misc sheet a descriptive title ("Miscellaneous / Discrete")
- [ ] Add test: a component with `category="unknown"` lands on misc sheet, not MCU

Files: `allocator.py`

### 6. Wire passive inference into resolver (P1, MEDIUM)

`infer_passive_component()` exists in `component_db.py` but is never called from `project_spec.py`. A YAML entry like `{value: 10k, ref: R1, footprint: 0402}` in a `misc:` section gets silently dropped because it has no `ic:` field.

- [ ] In `project_spec.py:216-220`: before skipping, try `infer_passive_component(item)` as fallback
- [ ] Support YAML entries: `{value: "10k", ref: "R1"}` and `{value: "100nF", ref: "C1"}`
- [ ] Infer footprint from value if not specified (R→0402, C<1uF→0402, C>=1uF→0805)
- [ ] Apply `section_category` and `source_ref` to the inferred passive
- [ ] Add test: bare passive in YAML resolves to valid ComponentDef

Files: `project_spec.py`, `component_db.py`

### 7. Add spec-vs-output reconciliation validation (P0, MEDIUM)

No check exists to verify the output matches the input. A design with 15 blocks might generate 12 components with no error.

- [ ] In `mvp.py` after `compile_design_ir()`: count IR blocks vs resolved components
- [ ] Emit a validation error (not just warning) when components are missing
- [ ] Include the list of missing block IDs/refs in the error message
- [ ] Add test: spec with an invalid IC produces a validation error, not silent success

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
