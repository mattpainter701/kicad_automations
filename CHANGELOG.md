# Changelog

## [0.9.0] - 2026-04-05

### Sprint 11 — Visual Design Diff (partial)

### Added
- `diff` CLI subcommand enhanced with `--svg` and `--output` flags for visual HTML diff reports
- `diff_renderer.py` module: structural block diff (added/removed/changed), metadata comparison, SVG side-by-side via KiCad CLI
- HTML report with summary cards, color-coded block table, inline SVG panels
- 5 diff tests covering add/remove/change/metadata/HTML output

### Sprint 10 — Close the Fab Gap

### Added
- `export-jlcpcb` CLI subcommand — exports BOM and CPL CSV files for JLCPCB assembly ordering
- `export-gerbers` CLI subcommand — wraps KiCad CLI to export Gerber and drill files with ZIP output
- Fabrication notes section in design reports (`_fab_notes_section()`) — auto-detects package types and recommends PCB specs (layer count, surface finish, assembly requirements)
- 5 new realistic sample designs: battery-powered IoT sensor, motor controller, OLED display module, USB-UART bridge, FPGA power carrier
- CPL placement data extraction from `generate_pcb_placement()` — returns both PCB file path and placement coordinates dict
- `jlcpcb_export.py` module with BOM grouping by (value, footprint, lcsc_pn) and CSV export
- BOM and CPL tests in `test_bootstrap.py`

### Changed
- `generate_pcb_placement()` signature: now returns `tuple[str, dict[str, tuple[float, float, float, str]]]` instead of just `str`
- Sample validation expanded: 8 total samples (3 original + 5 new), 159 tests passing (was 133)

### Fixed
- Circular import in `jlcpcb_export.py` resolved by deferring `compile_design_ir` import inside function

### Tests
- 159 total tests passing (8 samples × 4 validation tests each + other test suites)
- All 5 new samples pass validation with expected warnings (missing LCSC codes, floating pins on MCU)
- Version bump: 0.8.0 → 0.9.0

## [0.8.0] - 2026-04-05

### Sprint 9 — Unblock Day-1 Onboarding

### Added
- `list-templates` CLI subcommand with `--json` and `--verbose` flags
- `scaffold` CLI subcommand — emits valid YAML spec stubs from param_schema
- Auto-generated `docs/templates.md` reference (30 templates) via `scripts/gen_template_docs.py`
- `python-multipart` dependency for API extras
- Design wizard skill (`skills/design_wizard/SKILL.md`) — interactive 6-step circuit design workflow
- User workflow guide (`docs/user_workflow.md`)

### Changed
- Example `iot_sensor.yaml` cleaned up to pass validation
- Net connectivity check counts bypass_caps and straps as connections (FB/BST nets no longer flagged)
- MCU floating GPIO warnings summarized (28 warnings → 1 summary)
- Bootstrap tests tolerate KiCad CLI unavailability

### Fixed
- Net connectivity validator treated passive components (feedback dividers, pull-ups, bootstrap caps) as undriven — now recognizes passive pin type as valid driver
- 4 test_presentation.py failures caused by false-positive undriven-net warnings on internal subcircuit nets

### Tests
- 133 total tests passing (was 113 + 4 failures)
- Version bump: 0.7.0 → 0.8.0

## [0.7.0] - 2026-04-05

### Sprint 6–8 — Circuit Quality Overhaul

Comprehensive rework of circuit generation quality. The engine now catches floating pins,
validates power domains, checks bus completeness, and scores electrical quality — reducing
the ~50% error rate in generated circuits to near zero for template-based designs.

### Added
- **Pin-type-aware no-connect classification** (`generator.py`): replaces blanket NC with per-pin-type logic — errors on floating power_in, warns on floating inputs, silently NC's outputs and NC-named pins
- **`explicit_no_connects` field** on `ComponentDef`: templates declare intentionally unconnected pins (7 templates migrated: USB, clock, ethernet, opamp, relay_driver, sensor_frontend, charge_pump)
- **`_validate_pin_coverage()`** gate in MVP pipeline: catches floating pins at design-validation time
- **Power domain cross-check** (`_validate_power_domain_consistency`): conflicting voltage requirements, rail name vs voltage mismatch, missing bypass cap declarations
- **PWR_FLAG auto-generation**: one `PWR_FLAG` per unique power net per sheet for KiCad ERC compliance (`sexpr_pwr_flag_lib_entry`, `sexpr_pwr_flag_instance`)
- **Net connectivity graph**: single-pin-net (dangling) and undriven-net (input-only, no driver) detection
- **Enable pin validation**: detects floating EN/SHDN/CE pins on regulators that would prevent startup
- **Bus completeness checks**: I2C missing pull-ups, SPI floating CS, UART unpaired TX/RX
- **Intent annotations**: generator annotates schematics with "Unused: PIN(num): NC" summaries
- **Auto schema-driven `validate_params()`** on `SubcircuitTemplate` base class: type checking, required params, options validation, range bounds
- **Component contract validation** (`SubcircuitResult.validate_contract()`): components present, ICs have power pins, boundary ports declared
- **Inductor selection validator**: flags inductors < 0.1µH or > 100µH on switching converters
- **Capacitor voltage rating validator**: warns when rail voltage exceeds 80% of cap rating
- **In-process ERC** (`_validate_pin_type_conflicts`): output-to-output on same net = bus contention
- **Electrical quality scorer** (`score_electrical_quality`): weighted composite of pin coverage, decoupling, power pin coverage, validation pass rate — 0–100 score with A–F grade
- **`--strict` mode**: `validate_design(strict=True)` treats warnings as errors; CLI flag on validate subcommand
- **Design checklist generator** (`generate_design_checklist`): Markdown with checkbox items for pre-fab review
- **Fix suggestions** on `ValidationIssue`: `suggestion` field with actionable remediation text
- **EasyEDA pin type enrichment**: infers input/output/bidirectional from name patterns when EasyEDA type is "unspecified"
- **Pin count sanity check**: ICs with < 3 pins flagged as likely incomplete symbol
- **Footprint-to-pin consistency**: extracts pad count from footprint name (QFN-48, SOIC-8, BGA-121) and compares to symbol pin count

### Changed
- **Validation now has 10 checks** (was 4): feedback-divider, rc-lc-filter, crystal-load, decoupling, inductor-selection, cap-voltage, net-connectivity, enable-pins, bus-completeness, pin-type-conflicts
- **`_FEEDBACK_VREF`** expanded from 1 IC (AP62300TWU) to 7 (+ TPS62088, TPS61230A, MT3608, TPS63020, TPS63000)
- **`valid` computation** in `validate_design`: only errors cause failure (warnings are informational unless `--strict`)
- Power pin inference in `kicad_lib.py` expanded from 8 name patterns to 20+ (AVDD, DVDD, EPAD, EP, VBAT, VSYS, etc.)
- Power pin inference in `easyeda_parser.py` expanded with VDDCORE, VDD_*, VCC_*, 1P2, 2P5 variants

### Fixed
- **opamp.py**: replaced hardcoded pin numbers ("1","2","3") with database lookups (`pin_out_a`, `pin_inm_a`, `pin_inp_a`)
- **power_mux.py**: replaced hardcoded LTC4357 VIN pins 6/7/8 with `pin_vin_extra` database field
- **can_transceiver.py**: RS pin moved from `power_pins` to `pin_nets` (input type, not power); fixed ordering bug
- **usb.py**: CYUSB3014 wires all data bus pins (SSRX, GPIF, SPI, RESET, XTALIN); USB2514B unused pins → explicit NC
- **ethernet.py**: KSZ9031 RGMII data bus + PHY pair pins wired to named nets
- **clock.py**: AD9528 unused optional inputs → explicit_no_connects
- **relay_driver.py**: ULN2003A unused channel inputs → explicit_no_connects
- **sensor_frontend.py**: INA128PA RG gain pins at unity → explicit_no_connects

### Tests
- 123 total tests passing (was 106), 26 in test_template_structure.py
- 0 regressions across all 4 commits
- Version bump: 0.6.0 → 0.7.0

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
