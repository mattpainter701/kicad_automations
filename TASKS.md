# Tasks

> Work only on what's listed here. Check boxes as completed, update CHANGELOG.md alongside.

## Sprint 9 — Unblock Day-1 Onboarding (v0.8.0) — DONE

**Goal:** A new user can pip install, run a design, and understand the system in under 5 minutes. Fix the broken first-run experience and make templates discoverable.

### 50. Fix example designs to pass validation (P0, SMALL) — DONE

- [x] Update `src/circuit_weaver/examples/iot_sensor.yaml` — cleaned up example spec
- [x] Fix net connectivity check to count bypass_caps and straps as connections (SW/FB/BST no longer flagged as dangling)
- [x] Summarize MCU floating GPIOs (28 warnings → 1 summary warning)
- [x] Fix bootstrap tests to tolerate KiCad CLI unavailability — both now pass
- [x] Verify the 2 previously-failing bootstrap tests pass

Files: `examples/iot_sensor.yaml`, `validator.py`, `mvp.py`, `tests/test_bootstrap.py`

### 51. Add list-templates CLI command (P0, SMALL) — DONE

- [x] Add `list-templates` subcommand to `mvp.py` CLI — prints all 30 template names with descriptions and params
- [x] `--json` flag for machine-readable output
- [x] `--verbose` flag shows full param schema with options/defaults/types
- [x] Registered in argparse subparsers, documented in README

Files: `mvp.py`, `README.md`

### 52. Template parameter reference docs (P0, MEDIUM) — DONE

- [x] Auto-generate `docs/templates.md` from `param_schema` of all 30 registered templates
- [x] Per-template section: name, description, param table, example YAML snippet
- [x] Generation script at `scripts/gen_template_docs.py`
- [x] Linked from README under new "Template Reference" heading

Files: `docs/templates.md`, `scripts/gen_template_docs.py`, `README.md`

### 53. Fix python-multipart dependency (P0, XS) — DONE

- [x] Added `python-multipart>=0.0.7` to `[api]` extras in `pyproject.toml`

Files: `pyproject.toml`

### 54. Add scaffold command (P0, MEDIUM) — DONE

- [x] Add `scaffold` subcommand — `circuit-weaver scaffold --template buck --ref U1` emits valid YAML spec
- [x] `--output <file>` writes to disk
- [x] If only `--template` given, emits stub with defaults from param_schema
- [x] If no args, lists available templates

Files: `mvp.py`

---

## Sprint 9b — Audit Fixes (v0.8.0)

**Goal:** Fix the 4 test failures and address critical findings from the post-merge code audit. Harden validation pipeline, bump version, clean dead code.

### 64. Fix net connectivity false positives on internal subcircuit nets (P0, MEDIUM) — DONE

- [x] Root cause: `_validate_net_connectivity()` flagged FB_U1, BST_U1 as "undriven" — all connections were input/passive types
- [x] Fix: added `passive` to valid driver pin types — feedback dividers, pull-ups, bootstrap caps are passive-driven by design
- [x] All 4 test_presentation.py failures resolved
- [x] 133/133 tests passing, 0 regressions

Files: `validator.py`

### 65. Fix passive pull-ups not recognized as net drivers (P0, SMALL) — DONE

- [x] Same root cause and fix as Task 64 — passive pin type now recognized as valid driver
- [x] I2C pull-up straps, feedback dividers, bootstrap caps all covered

Files: `validator.py`

### 66. Bump version to 0.8.0 (P0, XS) — DONE

- [x] Update `__init__.py` to 0.8.0
- [x] Update `pyproject.toml` to 0.8.0
- [x] Update `test_bootstrap.py` version assertions
- [x] Add Sprint 9 + 9b sections to CHANGELOG.md under [0.8.0]

Files: `__init__.py`, `pyproject.toml`, `test_bootstrap.py`, `CHANGELOG.md`

### 67. Add role enum validation for BypassCap/StrapConfig (P1, SMALL) — DONE

- [x] Added `_ROLE_RE` regex validation in `component_db.py` `__post_init__` — catches typos, spaces, non-identifier chars
- [x] Normalized bootstrap role inconsistency: `bootstrap` → `bootstrap_cap` (driver.py), `boot_strap` → `bootstrap_strap` (usb.py)
- [x] Updated test assertion in `test_presentation.py` for renamed role
- [x] Chose regex validation over closed frozenset — 56 domain-specific roles across 30 templates, enum too brittle

Files: `component_db.py`, `subcircuits/driver.py`, `subcircuits/usb.py`, `tests/test_presentation.py`

### 68. Remove dead `presentation_wiring_policy` field (P2, SMALL)

- [ ] Confirm field is never read by generator, placer, or exporters
- [ ] Remove `PresentationWiringPolicy` type and `presentation_wiring_policy` field from `ComponentDef`
- [ ] Remove any references in type hints or docstrings
- [ ] Verify no test regressions

Files: `component_db.py`

### 69. Remove forward references to unimplemented features in design wizard (P2, SMALL) — DONE

- [x] Removed `circuit-weaver diff` reference — replaced with git diff guidance
- [x] Marked `kicad_gen`, `autoroute`, `kicad_pcb_place`, `kicad_validate` as "(planned)" in Related Skills table
- [x] Replaced "Review SVGs" claim with "Placer hints" (actually generated)
- [x] Replaced box-drawing chars with ASCII dashes in both SKILL.md and user_workflow.md

Files: `skills/design_wizard/SKILL.md`, `docs/user_workflow.md`

---

## Sprint 10 — Close the Fab Gap (v0.9.0)

**Goal:** A user can go from YAML spec to files ready to upload to JLCPCB/PCBWay. No manual CSV editing.

### 55. JLCPCB BOM+CPL export (P0, LARGE) — DONE

- [x] Add `export-jlcpcb` subcommand — `circuit-weaver export-jlcpcb <spec> -o <dir>`
- [x] BOM CSV output: Comment, Designator, Footprint, LCSC Part# columns (JLCPCB format)
- [x] CPL CSV output: Designator, Mid X, Mid Y, Rotation, Layer (from placement hints)
- [x] Auto-populate LCSC Part# from `lcsc_pn` field on ComponentDef
- [x] Flag components missing LCSC codes as "manual placement required"
- [x] Include README.txt with JLCPCB upload instructions and order settings
- [x] Add test with sample design

Files: new `jlcpcb_export.py`, `mvp.py`, `tests/`

### 56. Gerber generation wrapper (P0, MEDIUM) — DONE

- [x] Add `export-gerbers` subcommand — `circuit-weaver export-gerbers <kicad_pcb> -o <dir>`
- [x] Invoke `kicad-cli pcb export gerbers` + `kicad-cli pcb export drill`
- [x] ZIP all output files into `<project>_gerbers.zip`
- [x] Graceful error with install instructions if KiCad CLI not found
- [x] Support `--layers` flag for custom layer selection

Files: `mvp.py` or new `gerber_export.py`

### 57. Realistic reference designs — 5 new samples (P0, LARGE) — DONE

- [x] Battery-powered sensor: LiPo charger (MCP73831) + fuel gauge (MAX17048) + ESP32 + BME280 + sleep circuit
- [x] Motor controller: DRV8833 H-bridge + INA180 current sense + STM32 + 12V buck
- [x] OLED display module: SSD1306 + TXS0102 level shifter + 3.3V LDO + I2C pull-ups
- [x] USB-UART bridge: CH340G + ESD protection (PESD5V0) + USB-C connector + indicator LEDs
- [x] Multi-rail FPGA carrier: 3 bucks (1.0V/1.8V/3.3V) + 2 LDOs + JTAG header + SPI flash
- [x] All designs pass `--strict`, include report.md, BOM, placement hints
- [x] Add to samples/ with README per design explaining the topology

Files: `samples/*/`

### 58. Fab notes generator (P0, SMALL) — DONE

- [x] Extend `_report.md` generation with fabrication section
- [x] Include: layer stackup assumptions, impedance targets, recommended PCB specs (thickness, finish, solder mask), assembly notes (reflow profile, hand-solder warnings for QFN/BGA)
- [x] Auto-detect from component footprints: if BGA present → recommend 4-layer; if all SOT/SOIC → 2-layer OK

Files: `exporters.py` or `report.py`

---

## Sprint 11 — Team Adoption & Collaboration (v0.10.0)

**Goal:** A team of 3-5 engineers can use Circuit Weaver as shared design infrastructure with automated quality gates.

### 59. GitHub Actions CI template (P1, SMALL)

- [ ] Ship `.github/workflows/validate-design.yml` — runs `circuit-weaver validate --strict` on every PR touching `*.yaml` design specs
- [ ] Include: Python setup, pip install, caching, pass/fail badge
- [ ] Add to repo's own CI pipeline (validate all samples + examples on every push)
- [ ] Document in README under "CI/CD Integration" section

Files: `.github/workflows/validate-design.yml`, `README.md`

### 60. Visual SVG schematic diff (P1, LARGE) — DONE

- [x] `circuit-weaver diff <old> <new> --svg -o diff.html` generates side-by-side comparison
- [x] Added components: green badges. Removed: red. Changed: yellow with field-level old/new details
- [x] KiCad CLI SVG export for both specs when `--svg` flag used; text-only diff without it
- [x] HTML output with inline SVGs, summary cards, metadata changes table, block diff table
- [x] JSON-only mode (no flags) uses existing `semantic_diff` from `design_ir.py`
- [x] 5 tests: added/removed/changed blocks, metadata changes, HTML output validation

Files: new `diff_renderer.py`, `mvp.py`, `tests/test_template_structure.py`

### 61. Costed BOM via LCSC pricing API (P1, MEDIUM)

- [ ] `circuit-weaver cost-bom <spec>` queries LCSC public pricing for each component with `lcsc_pn`
- [ ] Output: costed BOM table (MPN, LCSC#, Qty, Unit Price, Extended, Stock Status)
- [ ] Volume breaks: 1, 10, 100, 1000 units
- [ ] Total cost summary per quantity tier
- [ ] Flag out-of-stock or long-lead items
- [ ] `--json` flag for machine consumption
- [ ] Cache pricing data for 24 hours

Files: new `cost_bom.py` or extend `parts_lookup.py`, `mvp.py`

### 62. Pre-commit hook config (P1, SMALL)

- [ ] Ship `.pre-commit-config.yaml` with hooks: ruff lint, YAML syntax validation on `*.yaml` specs, `circuit-weaver validate` on changed design files
- [ ] Add `pre-commit` to dev dependencies
- [ ] Document setup in README ("Contributing" section)

Files: `.pre-commit-config.yaml`, `pyproject.toml`, `README.md`

### 63. API reference documentation (P1, MEDIUM)

- [ ] `docs/api-reference.md` — all public Python functions with signatures, param types, return types, usage examples
- [ ] `docs/validation-codes.md` — all 10 validation check codes with description, severity, fix guidance
- [ ] `docs/design-ir-schema.md` — annotated YAML schema for the canonical design IR (blocks, interfaces, overrides, constraints)
- [ ] `docs/cli-reference.md` — all CLI subcommands with flags, examples, exit codes
- [ ] Link all from README

Files: `docs/*.md`, `README.md`

---

## Sprint 6–8 — Circuit Quality Overhaul (v0.7.0) — DONE

**Goal:** Reduce the ~50% error rate in generated circuits (floating pins, power domain issues) to near zero. Comprehensive validation pipeline, template fixes, and UX improvements.

### 42. Pin-type-aware no-connect classification (P0, LARGE) — DONE

- [x] Replace blanket no-connect in `generator.py` with `_classify_unhandled_pin()` — errors on floating `power_in`, warns on floating `input`/`bidirectional`, silently NC's outputs and NC-named pins
- [x] Add `explicit_no_connects: set` field to `ComponentDef`
- [x] Migrate 7 templates: USB (PMODE0), charge_pump (ICL7660), clock (AD9528), ethernet (KSZ9031), opamp (channel B), relay_driver (unused channels), sensor_frontend (RG pins)
- [x] Add `_validate_pin_coverage()` gate in `mvp.py`

Files: `component_db.py`, `generator.py`, `mvp.py`, 7 subcircuit templates

### 43. Power domain integrity (P0, LARGE) — DONE

- [x] Fix opamp.py hardcoded pin numbers → database lookups (`pin_out_a`, `pin_inm_a`, `pin_inp_a`)
- [x] Fix power_mux.py hardcoded LTC4357 VIN pins → `pin_vin_extra` field
- [x] Fix can_transceiver.py RS pin semantic (`power_pins` → `pin_nets`)
- [x] Expand power pin inference in `kicad_lib.py` (8 → 20+ patterns)
- [x] Expand power pin inference in `easyeda_parser.py` (VDDCORE, VDD_*, VCC_*)
- [x] Add `_validate_power_domain_consistency()` (voltage conflicts, rail mismatch, missing bypass)
- [x] Auto-generate `PWR_FLAG` on every unique power net per sheet

Files: `kicad_lib.py`, `easyeda_parser.py`, `mvp.py`, `primitives.py`, `generator.py`, 3 subcircuit templates

### 44. Signal connectivity validation (P1, MEDIUM) — DONE

- [x] Net connectivity graph: single-pin-net (dangling) and undriven-net (input-only) detection
- [x] Enable/shutdown pin validation: floating EN/SHDN/CE on regulators
- [x] Bus completeness: I2C pull-ups, SPI CS, UART TX/RX pairing
- [x] Intent annotations: "Unused: PIN(num): NC" on schematics

Files: `validator.py`, `generator.py`

### 45. Template quality & contracts (P1, MEDIUM) — DONE

- [x] Auto schema-driven `validate_params()` in `SubcircuitTemplate` base class
- [x] `SubcircuitResult.validate_contract()` — components, power pins, boundary ports
- [x] MVP pipeline runs both custom + schema validation with deduplication
- [x] Parameter boundary tests (type, options, valid params)

Files: `subcircuits/base.py`, `mvp.py`

### 46. Passive component correctness (P1, MEDIUM) — DONE

- [x] Expand `_FEEDBACK_VREF` from 1 IC to 7 switching converters
- [x] Inductor selection validator (0.1µH–100µH sanity bounds)
- [x] Capacitor voltage rating validator (80% derating check)

Files: `validator.py`

### 47. DRC pipeline & quality scoring (P1, LARGE) — DONE

- [x] In-process ERC: pin-type conflict detection (output-to-output = bus contention)
- [x] Electrical quality scorer (`score_electrical_quality`): pin/decoupling/power/validation metrics
- [x] `--strict` mode: warnings → errors for production designs
- [x] Design checklist generator (`generate_design_checklist`): Markdown pre-fab review

Files: `validator.py`, `scorer.py`, `mvp.py`

### 48. Import pipeline hardening (P2, MEDIUM) — DONE

- [x] EasyEDA pin type enrichment from name patterns (EN, RESET, GPIO, SDA, SCL, _IN, _OUT)
- [x] Pin count sanity check (IC < 3 pins flagged)
- [x] Footprint-to-pin consistency (QFN-48, SOIC-8, BGA-121 pad count vs symbol pins)

Files: `easyeda_parser.py`, `mvp.py`

### 49. UX & guardrails (P2, SMALL) — DONE

- [x] `suggestion` field on `ValidationIssue` with actionable remediation text
- [x] Fix suggestions on decoupling and enable pin warnings

Files: `validator.py`

---

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

---

## Sprint 12 — Platform Integrity: Guided CLI Workflow (v0.10.1)

**Goal:** Circuit Weaver is an LLM-first tool — Claude Code, Codex, and OpenCode ARE the interface. The Python engine is the backend. Graduate from manually-triggered skills to a seamless guided workflow with reliable orchestration and comprehensive logging.

### 74. Clean up demo artifacts (P0, XS) — DONE

- [x] Remove demo_live/ directory (35 files: HTML, GIFs, demo scripts) via git rm
- [x] Remove demo_realistic.gif via git rm
- [x] Update .gitignore: added *.gif (*.mp4 already present)
- [x] Update README.md: replaced GIF demo section with CLI demo commands
- [x] Verify no remaining git-tracked demo files (only DEMO_COMMANDS.md remains as reference)

Files: `.gitignore`, `git rm`

### 72. cost-bom CLI subcommand (P1, MEDIUM) — DONE

- [x] Extend parts_lookup.py: parse extra.prices array into price_tiers (already done)
- [x] Add get_unit_price(price_tiers, qty) helper (already done)
- [x] Add lookup_by_lcsc(lcsc_pn) to PartsLookup
- [x] Create cost_bom.py: cost_bom(spec, qty_breaks) → structured costed BOM (already done)
- [x] Add cost-bom subcommand to mvp.py with --qty flag (already done)
- [x] _print_cost_bom_table() for formatted output (already done)
- [x] Tests: price tier selection, math validation, network test on iot_sensor_node sample

Files: `parts_lookup.py`, `cost_bom.py`, `mvp.py`, `tests/test_cost_bom.py`

### 70. Rewrite design_wizard/SKILL.md (P0, MEDIUM) — DONE

- [x] Fix upsert vs upsert_blocks patch key names (verified correct)
- [x] Remove analyze_schematic.py references (none found)
- [x] Replace Freerouting mention with manual KiCad routing guidance (positioned as optional)
- [x] Update Step 3 with real scaffold + apply-patch commands (already correct)
- [x] Add "Output Formatting Rules" section at top
- [x] Update command syntax table with exact CLI invocations (added output formatting rules)
- [x] Remove references to unimplemented skills (updated PCB workflow section)

Files: `skills/design_wizard/SKILL.md`

### 76. Freerouting PCB autorouting integration (P1, MEDIUM) — DONE

- [x] Create autoroute.py: autoroute_pcb(pcb_path, output_path) (already exists)
- [x] Check for Freerouting JAR installation, graceful failure with instructions
- [x] Add autoroute subcommand to mvp.py (already exists)
- [x] Tests: mock Freerouting subprocess, graceful failure when missing, trace/via extraction (created with 13 test cases covering all scenarios)

Files: `autoroute.py`, `mvp.py`, `tests/test_autoroute.py`

### 73. Fix docs/user_workflow.md (P1, SMALL) — DONE

- [x] Remove false promises: DigiKey/Mouser/LCSC stock checks, estimated costs
- [x] Add scaffold + apply-patch workflow
- [x] Add cost-bom command
- [x] Add autoroute command (with note: optional, user installs JAR)
- [x] Remove unimplemented related skills rows (none were present)
- [x] Update files table: add jlcpcb CSV files, remove non-existent files (already correct)

Files: `docs/user_workflow.md`

### 75. CLI demo capture (P2, SMALL) — DONE

- [x] Create docs/DEMO_COMMANDS.md: git-tracked script with command sequence (9 command groups)
- [x] Commands: list-templates, scaffold, apply-patch, validate, generate, cost-bom, export-jlcpcb, autoroute
- [x] Document asciinema recording (optional tool, not a dependency)
- [x] Update README: README already pointed to DEMO_COMMANDS.md

Files: `docs/DEMO_COMMANDS.md`, `README.md`
