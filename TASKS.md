# Tasks

> Work only on what's listed here. Check boxes as completed, update CHANGELOG.md alongside.

## Sprint 5 — EasyEDA/LCSC Symbol Import Pipeline (v0.6.0)

**Goal:** When a component isn't in our built-in registry or KiCad's official library, automatically fetch its symbol from EasyEDA's public API using its LCSC part number. This gives us access to 300K+ component symbols with zero auth required — critical for JLCPCB production workflows and any part not in KiCad's official library.

### 33. EasyEDA API client (P0, MEDIUM) — DONE

- [x] `easyeda_api.py` — stdlib-only HTTP client (urllib)
- [x] `fetch_component(lcsc_id)` — two-step fetch: UUIDs from `/api/products/{id}/svgs`, then shape data from `/api/components/{uuid}`
- [x] `search_easyeda(query)` — keyword search via JLCPCB component API
- [x] Caching: 7-day disk cache (same pattern as `parts_lookup.py`)
- [x] Error handling: timeout, 404, malformed response → None

Files: `src/circuit_weaver/easyeda_api.py`

### 34. EasyEDA symbol parser (P0, LARGE) — DONE

- [x] `easyeda_parser.py` — parse tilde-delimited shape strings
- [x] Pin extraction: name, number, electrical type (0→unspecified, 1→input, 2→output, 3→bidirectional, 4→power_in), position → side mapping
- [x] Metadata extraction: prefix (U/R/C/L/J/D), MPN, manufacturer, description, package
- [x] Footprint inference from EasyEDA package strings (SOT-23-5, QFN, SOIC, passives, etc.)
- [x] `easyeda_to_component_def()` — convert parsed data to ComponentDef with PinDefs, power_pins, pin_nets, footprint, category

Files: `src/circuit_weaver/easyeda_parser.py`

### 35. Add lcsc_pn / digikey_pn fields to ComponentDef (P1, SMALL) — DONE

- [x] Add `lcsc_pn: str = ""` and `digikey_pn: str = ""` to `ComponentDef` dataclass
- [x] Wire `parts_lookup.py` enrichment to populate these fields
- [x] Backward-compatible: LCSC code still stored in features list too

Files: `src/circuit_weaver/component_db.py`, `src/circuit_weaver/parts_lookup.py`

### 36. Integrate EasyEDA as 4th-tier resolution fallback (P0, MEDIUM) — DONE

- [x] Resolution chain: built-in registry → KiCad official lib → JSON DB → **EasyEDA/LCSC**
- [x] Support `lcsc:` key in YAML component entries (e.g., `lcsc: C14663`)
- [x] When MPN lookup finds LCSC code via `parts_lookup.py`, use it as EasyEDA fetch key
- [x] Apply existing power pin mapping and net prefix logic to EasyEDA-sourced components

Files: `src/circuit_weaver/project_spec.py`

### 37. Tests for EasyEDA import pipeline (P0, MEDIUM) — DONE

- [x] Mock EasyEDA API responses (no live API calls in tests)
- [x] Test pin parsing from tilde-delimited shape strings (7 tests)
- [x] Test ComponentDef generation: power pins, signal pins, footprint, category (5 tests)
- [x] Test resolution chain: EasyEDA fallback fires when KiCad lib misses (5 tests)
- [x] Test footprint inference and category inference (13 tests)
- [x] Test ComponentDef field additions (3 tests)

Files: `tests/test_easyeda_import.py`

### 38. Multi-agent workflow compatibility (P1, SMALL) — DONE

- [x] Added root `AGENTS.md` and `opencode.json` support for Codex, OpenCode, and Kilo
- [x] Added OpenCode/Kilo reviewer agents and `.agents/skills` compatibility shims
- [x] Reworked installers for Claude/Codex/OpenCode/Kilo and shared `.agents/skills` downstream installs
- [x] Updated README and skill docs for `AGENTS.md`-first guidance and platform-specific install paths

Files: `AGENTS.md`, `opencode.json`, `install.sh`, `install.ps1`, `README.md`, `docs/agent-platforms.md`

### 39. Sprint 5 code review fix — fail closed on incomplete EasyEDA fetches (P0, SMALL) — DONE

- [x] Return `None` instead of building a partial EasyEDA import when any UUID payload is missing
- [x] Carry `lcsc_pn` through the direct `easyeda_to_component_def()` conversion path
- [x] Add regression coverage for incomplete per-UUID EasyEDA responses

Files: `src/circuit_weaver/easyeda_api.py`, `src/circuit_weaver/easyeda_parser.py`, `tests/test_easyeda_import.py`

### 40. Sprint 5 code review fix — make explicit `lcsc:` override earlier tiers (P0, SMALL) — DONE

- [x] Try EasyEDA first when a YAML component entry includes an explicit `lcsc:` key
- [x] Keep EasyEDA as the late fallback for plain `ic:`/MPN resolution when no explicit LCSC part is provided
- [x] Add regression coverage showing explicit `lcsc:` beats registry resolution

Files: `src/circuit_weaver/project_spec.py`, `tests/test_easyeda_import.py`

### 41. Sprint 5 code review fix — restore `LTC4357CMS8` power mux support (P1, SMALL) — DONE

- [x] Re-add the ideal-diode OR controller definition and generate path in `power_mux.py`
- [x] Preserve existing TPS2113 current-limit behavior and summary text
- [x] Add regression coverage for the restored `LTC4357CMS8` template path

Files: `src/circuit_weaver/subcircuits/power_mux.py`, `tests/test_import_pipeline.py`

---

## Sprint 4 — Template Expansion: Analog, Sensing & Control (v0.5.0) — DONE

**Goal:** Add 10 subcircuit templates covering the most-requested circuit blocks not yet in the library — crystal oscillators, bus conditioning, current sensing, switching, analog output, sensor front-ends, relay drivers, audio, power muxing, and charge pumps. Brings template count from 20 to 30.

### 23. Crystal oscillator template (P0, MEDIUM) — DONE

- [x] IC database: HC-49S crystal, ABM8G SMD crystal
- [x] Auto-calc load caps via existing `crystal_load_caps()` helper
- [x] Feedback resistor (1M), drive-level series resistor annotated
- [x] Boundary ports: XTAL_IN, XTAL_OUT, GND

### 24. I2C bus conditioning template (P0, MEDIUM) — DONE

- [x] IC database: PULLUPS_ONLY (virtual), PCA9306 level shifter
- [x] Auto-calc pull-up R from bus voltage, speed mode (100/400/1000 kHz), bus capacitance
- [x] Formula: R = t_rise / (0.8473 * C_bus)
- [x] Boundary ports: SDA, SCL, VDD, GND

### 25. Current sense amplifier template (P0, MEDIUM) — DONE

- [x] IC database: INA219 (I2C, 26V), INA180A1 (analog, 26V)
- [x] Auto-calc Rsense from Imax and Vsense target, footprint by power
- [x] Input filter RC, VDD decoupling, A0/A1 address straps
- [x] Boundary ports: SENSE_P, SENSE_N, SDA/SCL or VOUT, GND

### 26. MOSFET switch template (P0, MEDIUM) — DONE

- [x] IC database: BSS138 (N-ch), AO3400A (N-ch), AO3401A (P-ch)
- [x] Auto-calc gate resistor, pull-down (N-ch) / pull-up (P-ch) for default-off
- [x] Optional snubber RC for inductive loads
- [x] Boundary ports: GATE, LOAD, GND, VDD (P-ch)

### 27. DAC output template (P1, MEDIUM) — DONE

- [x] IC database: MCP4725 (I2C, 12-bit), DAC8552 (SPI, 16-bit dual)
- [x] Auto-calc output RC filter from DAC update rate (fc = rate/10)
- [x] VREF decoupling for external-ref ICs
- [x] Boundary ports: VOUT, SDA/SCL or SPI, VDD, GND

### 28. Sensor front-end template (P1, LARGE) — DONE

- [x] IC database: INA128PA (instrumentation amp), AD8421BRZ
- [x] Auto-calc INA gain R: G = 1 + 50k/Rg (INA128) or G = 1 + 9.9k/Rg (AD8421)
- [x] Optional anti-alias output filter
- [x] Boundary ports: SENSOR_P, SENSOR_N, VOUT, VDD, GND

### 29. Relay/solenoid driver template (P1, SMALL) — DONE

- [x] IC database: ULN2003A (7-ch Darlington), DISCRETE_NPN (standalone BJT)
- [x] Auto-calc base resistor for discrete: R = (Vdrive - Vbe) / (Icoil / beta * overdrive)
- [x] ULN2003 has internal base R + flyback diodes
- [x] Boundary ports: VCOIL, DRIVE, LOAD, GND

### 30. Audio amplifier template (P1, MEDIUM) — DONE

- [x] IC database: PAM8302A (analog Class-D), MAX98357A (I2S Class-D)
- [x] Auto-calc input coupling cap: C = 1/(2*pi*f_low*R_in)
- [x] VDD bulk decoupling, shutdown pull-up
- [x] Boundary ports: AUDIO_IN/I2S, SPEAKER_P, SPEAKER_N, VDD, GND

### 31. Power mux / ideal diode template (P1, MEDIUM) — DONE

- [x] IC database: TPS2113 (auto-switching mux), LTC4357 (ideal diode OR)
- [x] Auto-calc ILIM resistors: R = 375k / Ilim
- [x] Input/output decoupling, D1/D2 dead-battery disconnect
- [x] Boundary ports: VIN1, VIN2, VOUT, GND

### 32. Charge pump template (P2, SMALL) — DONE

- [x] IC database: LM2776 (SOT-23-5, 1MHz), ICL7660 (SOIC-8, 10kHz)
- [x] Auto-calc flying cap and output cap: C = Iout / (fsw * V_ripple)
- [x] Input decoupling
- [x] Boundary ports: VIN, VOUT_NEG, GND

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
