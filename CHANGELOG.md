# Changelog

## [0.6.0] - 2026-04-03

### Sprint 5 — EasyEDA/LCSC Symbol Import Pipeline

### Added
- EasyEDA API client (`easyeda_api.py`): fetch symbol/footprint data from JLCPCB/LCSC by LCSC part number — zero auth, 300K+ parts, 7-day disk cache
- EasyEDA symbol parser (`easyeda_parser.py`): parse tilde-delimited shapes into PinDefs with power/signal classification, footprint inference from 25+ package patterns, category inference from description keywords
- 4th-tier component resolution fallback: built-in → KiCad official lib → JSON DB → **EasyEDA/LCSC**
- YAML `lcsc:` key support — specify `lcsc: C14663` on any component to fetch from EasyEDA
- MPN-to-LCSC auto-discovery: when `parts_lookup.py` finds an LCSC code for an MPN, the EasyEDA tier fires automatically
- `lcsc_pn` and `digikey_pn` first-class fields on `ComponentDef` (replaces features-list workaround)
- `search_easyeda()` function for keyword search across JLCPCB component library
- EasyEDA regression coverage in `test_easyeda_import.py` for pin parsing, symbol assembly, ComponentDef conversion, footprint/category inference, and mocked resolution paths

### Changed
- `enrich_component()` now populates `lcsc_pn` and `digikey_pn` fields directly (backward-compatible: still writes features list too)
- Resolution chain stub message updated to mention EasyEDA as a checked source
- Version bump: 0.5.0 → 0.6.0

### Fixed
- EasyEDA imports now fail closed when any UUID payload is missing, instead of silently returning a truncated symbol
- Explicit YAML `lcsc:` keys now prefer EasyEDA import even when earlier registry/KiCad tiers would otherwise resolve the part by name
- `easyeda_to_component_def()` now carries `lcsc_pn` directly from EasyEDA metadata
- Restored `LTC4357CMS8` support in the `power_mux` template after the sprint 5 regression review

### Tests
- Added regression coverage for incomplete EasyEDA UUID fetches, explicit `lcsc:` override precedence, and restored `LTC4357CMS8` generation

## [0.5.0] - 2026-04-03

### Sprint 4 — Template Expansion: Analog, Sensing & Control

### Added
- Crystal oscillator template (`crystal_oscillator`): HC-49S, ABM8G — auto-calc load caps, feedback R
- I2C bus conditioning template (`i2c_bus`): pull-ups or PCA9306 — auto-calc pull-up R from speed/capacitance
- Current sense amplifier template (`current_sense`): INA219, INA180A1 — Rsense from Imax, footprint by power
- MOSFET switch template (`mosfet_switch`): BSS138, AO3400A, AO3401A — gate R, default-off pull, snubber RC
- DAC output template (`dac`): MCP4725, DAC8552 — output RC filter from update rate
- Sensor front-end template (`sensor_frontend`): INA128, AD8421 — gain R (G=1+50k/Rg)
- Relay driver template (`relay_driver`): ULN2003A, discrete NPN — base R with overdrive
- Audio amplifier template (`audio_amplifier`): PAM8302A, MAX98357A — input coupling cap
- Power mux template (`power_mux`): TPS2113, LTC4357 — ILIM resistor auto-calc
- Charge pump template (`charge_pump`): LM2776, ICL7660 — flying/output cap from Iout/fsw/ripple
- `boost_inductor()` and `buck_boost_inductor()` helpers in base.py
- `qualify_footprint()` auto-resolves bare footprint names to Library:Name
- Template count: 20 → 30

### Tests
- 68 tests passing

## [0.4.0] - 2026-04-03

### Sprint 3 — Placement, Routing & Presentation Readiness

### Added
- Schematic aesthetics scorer (`scorer.py`): 6-metric rule-based quality gate (spacing uniformity, whitespace ratio, label overlap, wire crossings, aspect ratio, density)
- `score_layout()` returns 0-100 score with A-F grade; `score_project()` aggregates across sheets
- `--score` CLI flag on `generate` subcommand; piped through `generate_artifacts()` API
- LDO cluster motif renderer (`_apply_topology_ldo_cluster`): CIN + COUT as compact unit below IC
- USB-C CC network motif renderer (`_apply_topology_cc_network`): CC1/CC2 pull-downs as tight pair beside connector
- Single-passive inline placement in sidecar cluster: 8.89mm offset for solo passives (vs 12.70mm grid)
- Dispatch chain: buck -> LDO cluster -> CC network -> decoupling bank -> strap ladder -> sidecar
- 10 new tests in `test_sprint3.py`

### Changed
- Sidecar cluster distinguishes single-passive (inline) from multi-passive (grid) placement

### Tests
- 68 total tests passing

## [0.3.0] - 2026-04-02

### Sprint 2 — Template Expansion & DFM Quality

### Added
- Op-amp template (`opamp`): non-inverting, inverting, follower, differential configs with auto-computed E24 feedback network
- Protection template (`protection`): TVS diodes (SMBJ5.0A/12A, SMBJ5.0CA, PESD5V0S1BA) for power/signal lines
- Gate driver template (`gate_driver`): IR2110 (half-bridge with bootstrap cap), UCC27524 (dual low-side)
- Level shifter template (`level_shifter`): TXB0108 (8ch), TXS0102 (2ch) with OE pull-up and dual-rail decoupling
- Template count: 6 → 10
- Library-name-based category classification (`_LIB_CATEGORY_MAP`): 30+ KiCad library prefixes mapped to categories
- Footprint heuristic inference (`_infer_footprint`): SOT-23, SOIC-8, SOD-123, 0402 from pin count + name
- External component database: `ComponentRegistry.load_json()` and `.load_json_dir()` for project-local JSON parts
- YAML `components_db` key for auto-loading project-local component databases
- KiCad `Description` property used for better category/description inference

### Changed
- `symbol_to_component_def()` now accepts `lib_name` parameter for library-aware classification
- `get_component()` passes resolved library name through search cache
- Category inference priority: library name > ref prefix > description keywords
- `project_spec.py` skips metadata keys (`spec_version`, `presentation_profile`, `components_db`) in section loop

### Tests
- 58 total tests passing (no regressions)

## [0.2.0] - 2026-04-02

### Sprint 1 — Robust KiCad Import Pipeline

### Added
- Stub ComponentDefs for unresolved components — never silently drop parts
- `_make_stub_component()` creates visible "UNRESOLVED" placeholders in schematics
- `_apply_power_map()` remaps KiCad power pin names to project rail names (VCC→VDD_3P3, etc.)
- `_apply_net_prefix()` prevents net collisions by prefixing generic signal names with ref (Q1_G, Q1_S)
- Optional `power_map` dict in YAML spec for explicit power pin remapping
- "Miscellaneous / Discrete" sheet category for unknown/protection/discrete/analog components
- Passive inference from bare YAML entries: `{value: "10k", ref: "R1"}` resolves without `ic:` field
- Expanded section category map: analog, discrete, motor, protection, audio, display, misc
- 26 new tests in `test_import_pipeline.py`

### Changed
- `auto_generate_bypass_caps()` now bypasses 6-pin minimum for power ICs and U-prefixed parts
- Default allocator fallback changed from "mcu" to "misc" — unclassified parts get their own sheet
- `_validate_component_resolution()` detects stub components and emits structural errors
- `_SECTION_CATEGORY_MAP` expanded with common analog/discrete/motor/protection sections

### Fixed
- Voltage regulators (3 pins) now get auto-decoupling caps (was blocked by pin count threshold)
- Two BSS138 FETs in the same design no longer short their gates via shared "G" net
- Components not in registry or KiCad library now produce visible stubs instead of vanishing

### Tests
- 58 total tests (32 presentation + 26 import pipeline), all passing

## [0.1.0] - 2026-04-02

### Initial Release

### Added
- Circuit Weaver schematic generation engine
- 6 subcircuit templates: buck, ldo, clock, ethernet, usb_controller, usb_hub
- 22-component built-in registry with full pin/bypass/strap metadata
- KiCad 8/9/10 symbol library import (10,000+ parts via local install or GitLab)
- Multi-sheet hierarchical schematic generation with boundary net promotion
- Auto-placement engine with topology-aware motif renderers
- Transactional MVP workflow: validate, generate, apply-patch, diff, ingest-pcb-feedback
- PCB placement export and constraint feedback loop
- 3 sample circuits: usb_regulated_supply, led_power_indicator, iot_sensor_node
- Presentation parity: topology-local rendering for all support passives
- Review presentation profile (--presentation-profile review)
- Decoupling bank and strap ladder motif renderers
- 32 tests (bootstrap, helpers, presentation regression)
