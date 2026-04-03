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

### 8. Add op-amp subcircuit template (P1, LARGE) — DONE

Op-amps are one of the most common analog building blocks and have no template. Users must specify them as bare `ic:` entries with no auto-generated feedback network, bias resistors, or decoupling.

- [ ] Create `subcircuits/opamp.py` with `OpAmpTemplate`
- [ ] Support configurations: inverting, non-inverting, voltage follower, differential
- [ ] Auto-generate feedback resistors from gain parameter
- [ ] Auto-generate input bias resistors where needed
- [ ] Auto-generate decoupling caps on supply pins
- [ ] Add to template registry in `subcircuits/base.py`
- [ ] Add tests for each configuration

Files: `subcircuits/opamp.py`, `subcircuits/base.py`

### 9. Add protection/ESD subcircuit template (P1, MEDIUM) — DONE

- [x] Created `subcircuits/protection.py` with `ProtectionTemplate`
- [x] TVS database: SMBJ5.0A, SMBJ12A (unidirectional), SMBJ5.0CA, PESD5V0S1BA (bidirectional)
- [x] Registered in default registry

### 10. Add gate driver / level shifter template (P2, MEDIUM) — DONE

- [x] Created `subcircuits/driver.py` with `GateDriverTemplate` and `LevelShifterTemplate`
- [x] Gate drivers: IR2110 (half-bridge with bootstrap), UCC27524 (dual low-side)
- [x] Level shifters: TXB0108 (8ch), TXS0102 (2ch) with OE pull-up
- [x] Bootstrap cap auto-generated for high-side drivers
- [x] Registered in default registry

### 11. Improve KiCad import category classification (P1, MEDIUM) — DONE

- [x] Added `_LIB_CATEGORY_MAP`: 30+ library prefix → category mappings
- [x] `_infer_category_from_lib()` uses library name as highest-priority classifier
- [x] `get_component()` passes resolved library name through to `symbol_to_component_def()`
- [x] Expanded description keyword matching: op-amp, MOSFET, TVS, driver, sensor, etc.
- [x] Uses `Description` property (not just Datasheet URL) for keyword matching

### 12. Add external component database support (P2, LARGE) — DONE

- [x] `ComponentRegistry.load_json(path)` loads components from JSON file
- [x] `ComponentRegistry.load_json_dir(directory)` loads all *.json files from a directory
- [x] Full schema support: pins, pin_nets, power_pins, bypass_caps, straps
- [x] YAML spec `components_db` key auto-loads project-local JSON database
- [x] Verified: JSON-defined components resolve with full metadata

### 13. Improve motif renderer coverage (P2, MEDIUM) — DEFERRED

Deferred to Sprint 3. Existing sidecar/bank/ladder renderers handle most cases adequately after Sprint 1 defaults change.

### 14. Add footprint fallback heuristics for KiCad imports (P1, SMALL) — DONE

- [x] `_infer_footprint()` in `kicad_lib.py`: infers from pin count + name hints
- [x] Heuristics: 3-pin+SOT/Q→SOT-23, 5-pin+SOT-23→SOT-23-5, 8-pin+SOIC→SOIC-8, 2-pin+D→SOD-123, R/C/L→0402
- [x] Falls back to empty string for truly unknown packages
- [x] Uses KiCad `Description` property for better context

### 15. Add section-category extensibility (P2, SMALL) — DONE (Sprint 1)

Completed during Sprint 1 Task 5. `_SECTION_CATEGORY_MAP` expanded with analog, discrete, motor, protection, audio, display, misc, rf_frontend, power_distribution.

---

## Sprint 3 — Placement, Routing & Presentation Readiness (v0.4.0)

**Goal:** Close the gap between auto-generated and hand-drawn quality with aesthetics scoring, motif refinement, and routing improvements.

### 16. Schematic aesthetics scorer (P0, LARGE) — DONE

- [x] `scorer.py` module with `score_layout()` and `score_project()`
- [x] 6 metrics: spacing uniformity (CV), whitespace ratio, label overlap potential, wire crossing estimate, aspect ratio, component density
- [x] Weighted aggregate score 0-100 with A-F grade
- [x] Wired into `generate_from_components()` via `score=True` parameter
- [x] CLI flag: `--score` on the `generate` subcommand
- [x] Piped through `generate_artifacts()` and `_generate_compiled_artifacts()`

### 17. Compact LDO cluster motif (P1, MEDIUM) — DONE

- [x] `_apply_topology_ldo_cluster()` in `placer.py`
- [x] Detects power-category IC with exactly 2 decoupling caps (CIN + COUT)
- [x] Places CIN left-of-center, COUT right-of-center in a row below IC
- [x] Shared rail labels and ground anchor
- [x] Optional enable strap placed inline

### 18. USB-C CC network block (P1, SMALL) — DONE

- [x] `_apply_topology_cc_network()` in `placer.py`
- [x] Detects connector with 2 termination straps pulling to same GND with same value
- [x] Places both resistors vertically beside connector with shared GND label
- [x] Dispatch chain updated: buck -> LDO cluster -> CC network -> bank -> ladder -> sidecar

### 19. Single-passive inline placement (P1, SMALL) — DONE

- [x] Sidecar cluster now handles single-passive pin groups with inline placement (8.89mm offset)
- [x] Multi-passive groups (2+) still use the full grid layout (12.70mm offset)
- [x] Tighter inline placement reduces visual noise for solo bypass caps

### 20. Wire crossing minimization (P2, MEDIUM) — DEFERRED

Deferred to Sprint 4. Current crossing count is low with topology-local rendering.

### 21. Bus routing for parallel signals (P2, MEDIUM) — DEFERRED

Deferred to Sprint 4. Current label-based bus connections work adequately.

### 22. Sample gallery refresh (P1, SMALL) — DEFERRED

Deferred until KiCad CLI SVG export is integrated into CI.
