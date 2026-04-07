# Changelog

## [0.17.0] - (In Progress)

### Sprint 20 — Design Review Completion & Production Assembly

### Changed (Task 109 — Dispatcher Refactor)
- **Renamed core module** `mvp.py` → `dispatcher.py`:
  - Reflects actual role: CLI subcommand dispatcher, not MVP
  - Updated all imports in source code (7 modules), tests (6 test suites), and documentation
  - Updated module docstring to clarify dispatcher + workflow engine role
  - Updated CONTRIBUTING.md, api-reference.md, architecture.md, cli-reference.md
  - All tests pass with new module name

### Added
- (to be filled during sprint)

### Fixed
- (to be filled during sprint)

### Tests
- All 60+ existing tests pass with dispatcher.py module name

---

## [0.16.0] - (In Progress)

### Sprint 19 — Design Review & Quality Assurance

### Added (Task 104 — Design DFM Checker)
- **DFM (Design for Manufacture) checker** (`dfm_checker.py`):
  - Validates PCB design against fab capabilities: trace width, spacing, via size, annular ring, edge clearance
  - Supports JLCPCB (2/4-layer) and PCBWay profiles with customizable DFM rules
  - Parses `.kicad_pcb` S-expression format to extract traces, vias, board dimensions
  - Returns structured `DFMViolation` objects with severity (critical/warning), actual vs minimum values, fix suggestions
  - `check_dfm()` function and `dfm_report()` for human-readable output
  - CLI command: `circuit-weaver check-dfm <design.kicad_pcb> [--profile jlcpcb|pcbway]`

### Added (Task 108 — Design Documentation Generator)
- **Design documentation generator** (`design_docs.py`):
  - `generate_assembly_guide_csv()` — exports BOM table: reference, value, footprint, MPN, manufacturer
  - `generate_power_budget_csv()` — estimates power per supply rail based on component categories
  - `generate_ordering_checklist()` — markdown checklist with per-distributor status
  - `generate_datasheet_index()` — markdown index of all downloaded datasheets
  - `generate_all_docs()` — orchestrator to generate all documentation types at once
  - CLI command: `circuit-weaver generate-docs <design.yaml> --output docs/ [--datasheets-dir X]`
  - Supports integration with BOM workflow: `cost-bom → generate-docs`

### Added (Task 106 — Interactive Design Review Report)
- **HTML design review report generator** (`review_report.py`):
  - `generate_review_report_html()` — generates comprehensive, self-contained HTML reports
  - **Report sections**:
    - Design summary card with project name, version, overall score/grade, creation timestamp
    - Pre-fabrication checklist (8 standard review items, user-checkable)
    - Detailed scoring breakdown with visual bar charts for all 5 quality dimensions
    - DFM violations table (from Task 104) with severity, location, actual/minimum values, suggestions
    - Component BOM table (reference, value, footprint, MPN, manufacturer, category, qty)
    - Power distribution tree (rails, voltages, current, power budget)
    - Actionable recommendations based on gap analysis (sections < 75 score)
  - **HTML features**:
    - Embedded CSS with responsive grid layout (no external dependencies)
    - Professional styling with color-coded score badges
    - Print-optimized layout with proper page breaks
    - Fully self-contained (all data + styles in single HTML file)
  - CLI command: `circuit-weaver review-report <design.yaml> [--kicad-pcb board.kicad_pcb] --output report.html`
  - Optional DFM integration: analyzes violations from .kicad_pcb file if provided

### Added (Task 105 — Enhanced Design Scoring)
- **Comprehensive design quality scoring** (`design_scorer.py`):
  - `DetailedElectricalQualityScore` dataclass with per-section breakdown
  - **5 quality dimensions** (each scored 0-100, A-F grading):
    - **Power Integrity:** bulk capacitor presence, decoupling coverage, voltage regulator identification
    - **Signal Integrity:** pull-up/pull-down resistor detection, differential pair indicators
    - **Placement Quality:** component reference designation coverage, thermal constraints
    - **Thermal:** power component identification, operating temperature range specification
    - **Manufacturing:** MPN coverage, part sourcing bindings, assembly complexity (package variety)
  - Weighted composite score (20% each dimension) with letter grades A-F
  - `score_design_comprehensive()` analyzes `DesignIR` and returns detailed breakdown
  - `summary_with_gaps()` method flags sections < 75 score with actionable recommendations
  - CLI integration: `circuit-weaver validate --detailed-score` adds scoring to validation output
  - Fully autonomous scoring without PCB data (works on schematic/DesignIR only)

### Tests
- 50 new tests total:
  - 14 DFM checker tests: profiles, PCB parsing, violation detection, report generation
  - 17 design documentation tests: BOM table extraction, power budget calculation, CSV/markdown exports
  - 19 design scoring tests: score creation, all 5 dimensions, weighted composites, gap detection, grade mapping
  - All tests passing in ~0.25s total

### Changed
- `mvp.py`: Added three new CLI subcommands: `check-dfm`, `generate-docs`, `review-report` with full argument parsing
- `__init__.py`: Exported scoring, design_docs, DFM, and review_report functions in public API
- `validate` command: Added `--detailed-score` flag to include 5-dimension quality analysis

---

---

## [0.15.2] - 2026-04-07 (Hotfix)

### Fixed
- **Design wizard architecture**: Restructured to use SKILL.md instructions instead of broken Python-level platform detection
  - Python code cannot invoke Claude Code tools (AskUserQuestion) — only Claude instructions can
  - Removed non-functional `interactive_prompts.py` module (dead code)
  - Refactored `_run_design_wizard()` to use plain `input()` for CLI compatibility
  - Restored cross-platform support: Claude Code (buttons), Codex/OpenCode (conversational), CLI (terminal input)
- **Dependencies**: Removed unused `questionary` from optional dependencies

### Architecture
- Interactive prompts now handled by SKILL.md instructions (Claude invokes AskUserQuestion)
- Python `mvp.py` contains only CLI implementation (non-interactive input())
- CLI mode: `python -m circuit_weaver design-wizard` with plain input() prompts
- Skill mode: Invoked via `/circuit-weaver` in Claude Code for native interactive UI

---

## [0.15.1] - 2026-04-07

### Fixed
- Add missing import for interactive prompts module in mvp.py

---

## [0.15.0] - 2026-04-07

### Platform-Aware Interactive Prompts

### Added
- **Interactive prompts system** (`interactive_prompts.py`):
  - Auto-detects execution platform (Claude Code, Codex, OpenCode, CLI)
  - Uses native UI for each platform:
    - **Claude Code**: AskUserQuestion tool (interactive buttons/checkboxes, scrollable)
    - **Codex/OpenCode**: Conversational prompting (natural text responses)
    - **CLI**: Terminal UI with questionary (arrow keys, spacebar, Enter)
  - Graceful fallback across platforms

- **Refactored design-wizard**:
  - Uses `ask_form_section()` for grouped form sections
  - Uses `ask_multiple_choice()` for option selection
  - Uses `ask_text()` for free-form input
  - Better UX with section grouping (BASIC INFO, POWER SUPPLY, COMPONENTS & INTERFACES)

### Dependencies
- Added `questionary>=1.10.0` to optional `[ui]` dependencies

### Documentation
- Updated `/circuit-weaver` skill docs with platform support notes
- Documented fallback behavior and feature parity across platforms

### Tests
- All 42 CLI tests passing
- Full test suite: 299+ tests passing

---

## [0.14.2] - 2026-04-07 (Hotfix)

### Design Wizard & Logging Enhancements

### Added
- **Design Wizard UX Redesign**:
  - Form-like interface with grouped sections (Basic Info, Power Supply, Components & Interfaces)
  - Section headers and clear visual hierarchy
  - Indented input prompts for better readability
  - Structured summary display with labels
  - Improved next-steps guidance

- **Design Log Viewer** (`log-view` command):
  - New `circuit-weaver log-view <project_dir>` command for viewing recent log entries
  - Filter by entry type: `wizard_step`, `cli_call`, `validation`, `research`
  - `--lines N` flag to show last N entries (default: 10)
  - Human-readable timestamp and entry type formatting
  - Helps troubleshoot issues and understand project history

### Improved
- **Logging Visibility**:
  - Wizard now prominently displays log file location after project creation
  - Added `log-view` and `log-status` commands to next-steps output
  - Better integration between wizard and logging workflow

### Fixed
- Removed emoji characters for Windows terminal compatibility (cp1252 encoding)
- All terminal output now uses ASCII-safe characters

### Documentation
- Updated `docs/DESIGN_LOGGING.md` with `log-view` command documentation
- Updated `docs/cli-reference.md` with improved design-wizard and logging command details

### Tests
- All 37 CLI tests passing
- Full test suite: 299 passed, 1 skipped

---

## [0.14.1] - 2026-04-07

### Sprint 17 — Housekeeping & Test Coverage + Mechanical & API Enhancements

### Fixed
- Version mismatch: synced pyproject.toml, __init__.py, and test assertions to 0.14.0 (Task 97)
- .gitignore: added datasheets/, specs/, spice_models/, bom/orders/, *.bak (Task 98)
- CONTRIBUTING.md: updated release example from v0.11.0 to v0.14.0 (Task 101)
- architecture.md: updated roadmap — all sprints through 16 marked stable (Task 101)
- mvp.py: replaced SVG placement TODO with actual placement optimizer call (Task 101)

### Added (Sprint 17 — Housekeeping)
- `test_cli_commands.py` — 37 end-to-end CLI tests covering all 20 subcommands (Task 99)
- `test_enclosure_designer.py` — 7 tests for enclosure generation and package exports (Task 100)
- Parameterized --help test validates every subcommand accepts help flag
- JSON extraction helper for CLI output with prefix lines

### Added (Mechanical & API Enhancements — Post-Sprint)
- **OpenSCAD Enclosure Designer** (`enclosure_designer.py`):
  - `design-enclosure` CLI subcommand for parametric 3D-printable enclosure generation
  - `generate_enclosure_scad()` supports customizable wall thickness, clearance, component height, ports, mounting holes, and vents
  - Port types: USB-C, Micro-USB, barrel jack, round, rectangular
  - M3 mounting holes with countersink for PCB standoffs
  - `render_enclosure_stl()` calls OpenSCAD CLI to generate STL files (optional)
  - Full parametric OpenSCAD code generation — users can tweak dimensions and re-render in seconds

- **KiCad Python API Integration** (`kicad_placement_api.py`):
  - `check_kicad_available(min_version=6)` validates KiCad 6+ installed with platform-specific guidance
  - `detect_kicad_version()` CLI-based detection via `kicad --version` + pcbnew module import
  - `update_board_placements()` uses official KiCad pcbnew API for placement updates (robust, future-proof)
  - Automatic fallback to regex-based updates when API unavailable (offline, legacy versions)
  - Consistent result structure across both API and fallback paths
  - `import-placement` command now reports KiCad API status and uses official API when available

### Tests
- 44 new tests (37 CLI + 7 enclosure), all passing in 12.6s
- 255 total tests pass (full suite: 11:25 runtime)

### Documentation
- `docs/user_workflow.md` — Added 'Prototype Enclosure Design' section with examples
- Added openscad skill to Related Skills table
- `svg_placement.py` — Updated docstring with KiCad API integration notes

## [0.14.0] - 2026-04-07

### Sprint 16 — Advanced PCB Placement & Dual-Sided Assembly (complete)

### Added
- `placement_optimizer.py` — simulated annealing PCB placement optimizer with multi-objective cost functions (overlap, boundary, thermal proximity, zone affinity) (Task 87)
- `optimize-placement` CLI subcommand — `circuit-weaver optimize-placement <spec> --strategy balanced --board-width 100 --board-height 80`
- 5 placement strategies: `simple` (zone heuristic), `thermal`, `si`, `cost`, `balanced` (all combined)
- Reads Sprint 15 `specs/ic_thermal.json` and `specs/si_params.json` for thermal/SI-aware placement
- Deterministic placement with `--seed` flag for reproducible results
- `placement_viewer.py` — interactive HTML/SVG PCB placement viewer with dark theme (Task 90)
- `placement-viewer` CLI subcommand — runs optimizer then generates interactive HTML
- Viewer features: click-to-highlight nets, hover tooltips (MPN, value, position, power), thermal heatmap overlay toggle, CSV export button, category color-coding
- 16 tests covering optimizer (empty, single, multi-component, strategies, thermal warnings, determinism, specs loading) and viewer (HTML generation, file output, thermal overlay, CSV export, empty input)

### Added (P1/P2 completion)
- `si_constraints.py` — signal integrity constraint solver detecting USB/DDR/LVDS/PCIe/MIPI/Ethernet/CAN/RS-485 buses from net names and descriptions (Task 88)
- `si-constraints` CLI subcommand — impedance targets, differential pair detection, length-matching groups, routing rules
- `thermal_analysis.py` — junction temperature calculator with hotspot detection, proximity analysis, and thermal heatmap SVG generation (Task 89)
- `thermal-analysis` CLI subcommand with `--heatmap`, `--ambient`, `--specs-dir`
- `write_dual_sided_cpl()` in jlcpcb_export.py — splits placements into top/bottom CPL files with assembly mode warnings (Task 91)
- `export-dual-cpl` CLI subcommand with `--assembly-mode` flag
- `panelizer.py` — panel layout optimizer with breakaway positions, cost estimates, design rules for V-cut and mouse-bite (Task 92)
- `panelize` CLI subcommand with `--board-width`, `--board-height`, `--qty`, `--breakaway`

### Tests
- 16 tests in `test_placement_optimizer.py` (P0 tasks)
- 30 tests in `test_sprint16_remaining.py` (P1/P2 tasks) — all passing

## [0.12.0] - 2026-04-06

### Sprint 14 — Auto-Discovery + Visual Placement Editing

### Added
- **Task 85:** `symbol_cache.py` — 30-day TTL persistent cache for symbol resolution at `~/.cache/circuit-weaver/symbols/`
  - `SymbolCache.get()` / `.put()` / `.stats()` / `.clear()` interface with atomic index.json manifest
  - `cache stats` subcommand shows cache hit rate and size
  - `cache clear [--stale-only]` removes old/unused entries
- **Task 83:** `digikey_loader.py` — DigiKey API symbol autoloader with package-to-footprint mapping
  - `load_from_digikey(mpn)` queries DigiKey API, extracts package metadata, maps to KiCad footprints
  - Reuses `_search_digikey()` and `_get_credential()` from `parts_lookup.py` (no code duplication)
  - Creates minimal ComponentDef stubs when full symbol data unavailable
  - Graceful fallback when DIGIKEY_CLIENT_ID/SECRET missing
- **Task 84:** `mouser_loader.py` — Mouser Search API v1 symbol autoloader
  - `load_from_mouser(mpn)` queries Mouser, extracts package attributes, maps to KiCad footprints
  - Reuses `map_digikey_package_to_kicad()` for consistent package mapping across both APIs
  - Integrated as Tier 6 in symbol resolution chain (fallback after DigiKey)
  - MOUSER_SEARCH_API_KEY credential support
- **Task 83/84:** `symbol_resolver.py` — 6-tier unified symbol resolution chain
  - Tiers: registry → kicad_lib → cache → easyeda → digikey → mouser → unresolved
  - Lazy imports for DigiKey/Mouser loaders prevent startup failures when credentials absent
  - `resolve(mpn)` returns `(ComponentDef | None, source_str)` indicating which tier succeeded
  - `resolve_batch(items)` for bulk component resolution
- **Task 86:** Auto-MPN discovery during `generate` command
  - `--auto-source` flag: auto-discover and cache MPNs for unresolved components
  - `--update-spec` flag: write discovered MPNs/LCSC back to original YAML spec file
  - `_auto_source_report()` helper queries PartsLookup, DigiKey, and Mouser; returns summary stats
  - `update_spec_with_sourced_data()` in `project_spec.py` safely updates YAML specs (only fills blank fields)
  - Stderr output shows resolved component counts by distributor (DigiKey: N, Mouser: N, LCSC: N)
  - Enrich-parts mode enabled automatically when `--auto-source` is set
- **Task 93:** `svg_placement.py` — SVG-based bidirectional placement editor
  - `export_placement_svg(components, placements, board_w, board_h)` generates editable SVG with colored component rectangles
  - `import_placement_from_svg(svg_path)` parses user-edited SVG back to placement dict via regex transform parsing
  - `update_kicad_pcb_placements(kicad_pcb, placements)` updates .kicad_pcb footprint `(at ...)` clauses via regex
  - `update_cpl_placements(cpl_path, placements)` updates CPL CSV with new X/Y/Rotation values
  - `import-placement` subcommand: `circuit-weaver import-placement placement.svg design.kicad_pcb [--output-pcb FILE] [--dry-run]`
  - Auto-detects and updates `*_cpl.csv` siblings in same directory
  - Color-coded by component category (power=red, digital=blue, connector=green, passive=yellow)
  - Back-layer components drawn with 0.5 opacity and dashed borders
  - Component size heuristics for 20+ common packages (0402, SOT-23, SOIC-8, QFN, BGA, etc.)
  - `--svg-placement` flag in `generate` command exports placement.svg to output directory
  - SVG is text/XML and git-friendly for design review

### Changed
- `generate_artifacts()` signature: added `auto_source`, `update_spec`, `spec_path`, `svg_placement` parameters
- `generate` dispatch: passes auto-source flags from CLI to `generate_artifacts()`

### Tests
- All new modules compile and import successfully
- Symbol resolver 6-tier fallback chain verified
- (Full test suite: running)

## [0.10.2] - 2026-04-06

### Sprint 11 — Team Adoption & Collaboration (completion)

### Added
- `.github/workflows/validate-design.yml` — CI workflow that runs `circuit-weaver validate --strict` on all sample and example specs when design files change (Task 59)
- `.pre-commit-config.yaml` — ruff lint+format, YAML syntax validation, and design validation hooks (Task 62)
- `pre-commit>=3.7` added to `[dev]` optional dependencies
- `docs/api-reference.md` — public Python API with signatures, parameters, return types, and usage examples (Task 63)
- `docs/cli-reference.md` — all 13 CLI subcommands with flags, examples, and exit codes (Task 63)
- `docs/validation-codes.md` — all 10 validation check categories with severity, sub-codes, and fix guidance (Task 63)
- `docs/design-ir-schema.md` — annotated YAML schema for the canonical design IR (Task 63)
- "Reference Documentation" table in README linking all 5 reference docs
- "CI/CD Integration" section in README documenting both CI workflows
- "Contributing" section in README with pre-commit setup instructions
- Design validation CI badge in README header

### Changed
- Task 68 (`presentation_wiring_policy` removal) closed as won't-fix — field is actively used in placer.py, generator.py, allocator.py, and mvp.py for support-passive rendering
- Task 61 (costed BOM) confirmed already complete from Sprint 12 — checkboxes updated

### Tests
- Design validation CI validates all `samples/` and `examples/` specs on every push

## [0.10.1] - 2026-04-05

### Sprint 12 — Platform Integrity: Guided CLI Workflow

### Added
- `/circuit-weaver` master orchestrator skill — LLM-first skill that routes new vs existing designs, orchestrates research-analyst agent (Perplexity IC research), CLI subcommands, and generates quote-ready outputs
- Skill implementation: `skills/circuit-weaver/SKILL.md` with Steps 0-7 (new design: welcome → requirements → research → BOM → schematic → review → export; existing design: load → validate/regenerate/export/modify)
- `.agents/skills/circuit-weaver/SKILL.md` compatibility stub for Claude Code discovery
- `cost-bom` CLI subcommand — generates costed BOM with LCSC pricing at multiple volume breaks (1, 10, 100, 1000 qty)
- `cost_bom.py` module: queries LCSC, extracts price tiers, calculates per-board and total costs
- Extended `parts_lookup.py` with `get_unit_price()` helper to select correct price tier for given quantity
- Price tier parsing in `_search_lcsc()` — converts API `extra.prices` array to `[{min_qty, max_qty, unit_price}]` dicts
- Rewrote `design_wizard/SKILL.md` Step 3c to reflect real CLI workflow: `scaffold` → `apply-patch` → `cost-bom`
- All wizard steps now reference working CLI commands (removed non-existent analyze_schematic.py, kicad_gen, kicad_pcb_place, kicad_validate)
- Automated installation scripts: `install.ps1` (Windows) and `install.sh` (Mac/Linux) — handles Python package setup, PATH configuration, and Claude Code skill registration in one command

### Changed
- Design wizard Step 3c: shifted from abstract BOM description to concrete `scaffold`+`apply-patch`+`cost-bom` commands
- Design wizard Step 5a: replaced non-existent script call with `circuit-weaver validate` direct call
- Design wizard Step 6c: Freerouting made optional (separate installation required, graceful fallback)
- Installation process: automated via `install.ps1` (Windows) and `install.sh` (Mac/Linux) — one-command setup eliminates manual pip/PATH/skill registration steps

### Fixed
- Removed non-existent `comp.dnp` attribute check in `cost_bom.py` (ComponentDef has no DNP field)

### Tests
- `cost-bom samples/iot_sensor_node/iot_sensor_node.yaml --qty 1,10` verified working
- All wizard steps now use real, tested CLI commands
- Version bump: 0.9.0 → 0.10.1

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
