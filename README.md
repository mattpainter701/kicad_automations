<p align="center">
  <img src="assets/circuit-weaver-banner.svg" alt="Circuit Weaver" width="100%">
</p>

<p align="center">
  <a href="https://github.com/mattpainter701/kicad_automations/actions/workflows/ci.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/mattpainter701/kicad_automations/ci.yml?branch=main&label=CI&style=flat-square" alt="CI">
  </a>
  <a href="https://pypi.org/project/circuit-weaver/">
    <img src="https://img.shields.io/pypi/v/circuit-weaver?style=flat-square&label=PyPI&color=0ea5e9" alt="PyPI">
  </a>
  <img src="https://img.shields.io/badge/python-3.10%2B-0b1320?logo=python&logoColor=ffd43b&style=flat-square" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/KiCad-8%2B-0ea5e9?style=flat-square" alt="KiCad 8+">
  <img src="https://img.shields.io/badge/license-MIT-1f2937?style=flat-square" alt="MIT">
</p>

<p align="center">
  <strong>Programmatic KiCad schematic generation, strict validation, and manufacturing export<br>
  designed for AI-assisted hardware workflows — Claude Code, Codex, and offline CLI.</strong>
</p>

---

## How It Works

<p align="center">
  <img src="assets/workflow.svg" alt="Circuit Weaver full pipeline — from install to KiCad export" width="100%">
</p>

Every path through Circuit Weaver follows the same contract: **describe the design → validate → generate KiCad artifacts**. The diagram above shows what each module does and which function it calls. Pick your entry point (Claude Code skill, Codex agent, or CLI wizard) and the rest is automatic.

---

## Quick Start

**Step 1 — Install**

```bash
pip install circuit-weaver
```

**Step 2 — Register the skill** *(one-time, for Claude Code / Codex / OpenCode)*

```bash
circuit-weaver install-skills            # safe: skips existing skills, reports what would overwrite
circuit-weaver install-skills --dry-run  # preview without touching disk
circuit-weaver install-skills --force --backup   # overwrite existing skills, keep timestamped .bak files
```

> **Note:** `install-skills` will **not** overwrite an existing `SKILL.md` that differs from the
> bundled version — it prints a warning and leaves your customizations intact. Pass `--force` (and
> optionally `--backup`) only after reviewing the reported collisions.

**Step 3 — Launch**

```bash
# In Claude Code or Codex — type the skill name:
/circuit-weaver

# Or run offline without any agent:
circuit-weaver design-wizard
```

That's it. The skill walks you through IC selection, passive generation, and manufacturing export. No YAML hand-editing required.

---

## Research Traceability

Agentic research runs are expected to persist their output into `output/research/`.
That directory is the source of truth for why an IC was chosen, which citations
backed it, and which backend produced the result.

For Codex / Claude / OpenCode workflows, Step 2 IC research should stay in the
current agent session. If a premium-research command would delegate to a
subagent or fails with a model/tool conflict, use the platform's native web
tools instead and persist the backend that actually ran.

```bash
# Check which backend and depth are active before research starts
circuit-weaver doctor

# Optional: force backend/depth selection for agent workflows
export CIRCUIT_WEAVER_RESEARCH_BACKEND=standard   # or sonar-pro / auto
export CIRCUIT_WEAVER_RESEARCH_DEPTH=fast         # or normal
# PowerShell: $env:CIRCUIT_WEAVER_RESEARCH_BACKEND="standard"
# PowerShell: $env:CIRCUIT_WEAVER_RESEARCH_DEPTH="fast"

# Persist a completed research result
circuit-weaver save-research --project-dir ./output --file research.json
```

Each saved run produces `{slug}.json`, `{slug}.md`, and `summary.md`, and the
matching `design.log` entry records the canonical JSON path for later audit.

---

## What You Get

Every `generate` run produces a complete artifact bundle:

| Artifact | File | Description |
|-|-|-|
| KiCad schematic | `{project}.kicad_sch` | Real, loadable `.kicad_sch` — not a placeholder |
| HTML review report | `{project}_review.html` | Validation results, component rationale, DFM score, BOM |
| Test point map | `{project}_test_points.csv` | Auto-detected power, clock, bus, and differential-pair nets |
| JLCPCB BOM + CPL | `bom.csv`, `cpl.csv` | Upload-ready assembly files |
| Firmware stubs | `{project}_pinout.csv`, `.ioc`, `sdkconfig` | MCU pin map + STM32/ESP32 co-design files |
| Enclosure model | `enclosure.scad` | Parametric OpenSCAD model sized to the PCB |
| Placement SVG | `placement.svg` | Editable SVG of component placements — import back after editing in Inkscape |
| PCB file | `design.kicad_pcb` | Initial PCB with zone-based component placement |

---

## PCB Placement Workflow

Circuit Weaver has a complete placement pipeline — from automatic initial placement through optimization, interactive review, and write-back to KiCad.

### 1 — Generate initial placement

`generate` produces an initial `.kicad_pcb` with topology-aware placement (power zone, digital zone, RF zone, connector zone, passive banks) and exports a `placement.svg` for editing:

```bash
circuit-weaver generate design.yaml -o ./output
# → output/design.kicad_pcb   (zone-based initial placement)
# → output/placement.svg       (editable placement diagram)
```

### 2 — Optimize with simulated annealing

```bash
# Basic optimization (5 000 iterations, reproducible with seed)
circuit-weaver optimize-placement design.yaml --iterations 5000 --seed 42

# Thermal-aware strategy (minimizes hotspot proximity)
circuit-weaver optimize-placement design.yaml --strategy thermal --iterations 10000

# Read component thermal/SI specs from YAML files
circuit-weaver optimize-placement design.yaml --specs-dir ./specs/
```

The optimizer minimizes: overlap, boundary violations, thermal clustering, and DFM zone penalties via simulated annealing. Returns a placement JSON with x/y/rotation/layer per component.

### 3 — Review in the interactive viewer

```bash
circuit-weaver placement-viewer design.yaml -o output/viewer.html
```

Opens a self-contained HTML file with:
- Click-to-highlight nets
- Component hover tooltips (value, footprint, MPN)
- Thermal heatmap overlay (blue → red gradient by power dissipation)
- CSV export button for placement data

### 4 — Edit in Inkscape → import back

```bash
# Export editable SVG
circuit-weaver generate design.yaml --svg-placement -o ./output
# → output/placement.svg

# Edit in Inkscape (drag components, adjust positions)…

# Import edits back to .kicad_pcb and CPL
circuit-weaver import-placement output/placement.svg \
    output/design.kicad_pcb \
    output/design_updated.kicad_pcb \
    --output-cpl output/cpl_updated.csv
```

### 5 — Write directly via KiCad API

If KiCad 6+ is installed, write placements directly without SVG round-trip:

```python
from circuit_weaver import check_kicad_available, update_board_placements

if check_kicad_available():
    update_board_placements("design.kicad_pcb", placements)
```

### 6 — DFM check and panelization

```bash
# Check clearances, pad sizes, and DFM rules
circuit-weaver check-dfm design.yaml

# Get panel layout suggestions for small boards
circuit-weaver panelize design.yaml

# Export dual-sided CPL (top + bottom)
circuit-weaver export-dual-cpl design.yaml -o ./jlcpcb
```

---

## CLI Reference

```bash
# ── Design lifecycle ──────────────────────────────────────────────────────────
circuit-weaver validate design.yaml               # Validate spec (no files written)
circuit-weaver generate design.yaml -o ./output  # Full artifact bundle
circuit-weaver erc output/design.kicad_sch        # KiCad built-in ERC
circuit-weaver diff old.yaml new.yaml             # Semantic diff + optional SVG

# ── Placement ─────────────────────────────────────────────────────────────────
circuit-weaver optimize-placement design.yaml --iterations 5000 --seed 42
circuit-weaver placement-viewer design.yaml -o output/viewer.html
circuit-weaver import-placement placement.svg board.kicad_pcb out.kicad_pcb
circuit-weaver check-dfm design.yaml
circuit-weaver panelize design.yaml
circuit-weaver export-dual-cpl design.yaml -o ./jlcpcb

# ── Simulation & confidence ──────────────────────────────────────────────────
circuit-weaver simulate design.yaml -o ./sims      # Run SPICE simulations (ngspice)
circuit-weaver confidence design.yaml --run-sims   # Full design readiness score (0-100)
circuit-weaver confidence design.yaml -o report.html --pcb board.kicad_pcb

# ── BOM and manufacturing ─────────────────────────────────────────────────────
circuit-weaver cost-bom design.yaml --qty 1,10,100
circuit-weaver export-jlcpcb design.yaml -o ./jlcpcb
circuit-weaver export-gerbers design.yaml -o ./gerbers

# ── Project management ───────────────────────────────────────────────────────
circuit-weaver discover                             # Auto-detect projects in CWD
circuit-weaver discover --json --depth 2            # JSON output, search 2 levels deep
circuit-weaver save-research --project-dir ./output --file research.json
circuit-weaver log-event ./project --type scoring --message "Review done"
circuit-weaver doctor                               # Check credentials, backends, and tool availability

# ── Design tools ──────────────────────────────────────────────────────────────
circuit-weaver scaffold --template buck --ref U1   # New spec from template
circuit-weaver list-templates --verbose             # Browse 37 subcircuit templates
circuit-weaver design-enclosure --board-width 50 --board-height 40 -o enclosure.scad
circuit-weaver harvest-specs design.yaml           # Download datasheets + extract specs
circuit-weaver fetch-spice design.yaml             # Fetch SPICE models (TI, ADI, Microchip…)
```

Run `circuit-weaver --help` or `circuit-weaver <subcommand> --help` for full flag reference.

---

## Python API

```python
from circuit_weaver.dispatcher import (
    validate_design,
    apply_design_patch,
    generate_artifacts,
    diff_designs,
    ingest_pcb_feedback,
)

# Validate a canonical design spec
report = validate_design(spec)

# Apply a transactional patch and re-validate
result = apply_design_patch(spec, patch)

# Generate the full KiCad artifact bundle
bundle = generate_artifacts(spec, output_dir="out/design")

# Semantic diff between two specs
changes = diff_designs(old_spec, new_spec)

# Feed PCB layout feedback back into the design spec
updated = ingest_pcb_feedback(spec, pcb_feedback)
```

### Validation groups

`validate_design` runs five grouped checks and returns a structured `ValidationReport`:

| Group | What it checks |
|-|-|
| `structural` | Topology, block connections, hierarchy integrity |
| `electrical` | Power rails, ground nets, net continuity |
| `implementation` | Part bindings, footprint assignments, pinout verification |
| `placement_readiness` | **Hard-gated** — dangling buses, missing I2C pull-ups, orphan interfaces, floating enables; never bypassable by `--no-require-valid` |
| `presentation` | Labels, pin numbers, sheet readability |

### HTTP API

```bash
uvicorn circuit_weaver.api:app --host 0.0.0.0 --port 5000
```

| Endpoint | Method | Description |
|-|-|-|
| `/health` | GET | Service health |
| `/templates` | GET | Available subcircuit templates |
| `/generate` | POST | YAML spec → ZIP of `.kicad_sch` + report |
| `/validate` | POST | YAML spec → validation JSON |
| `/mvp/apply-patch` | POST | Transactional patch + re-validation |
| `/mvp/diff` | POST | Semantic diff between two specs |
| `/mvp/pcb-feedback` | POST | Merge PCB layout feedback into spec |

---

## What's New in v0.31.0

Circuit Weaver `v0.31.0` collects the Sprint 53-54 schematic layout quality work and graduates the prior `0.30.x` sprint-release series into a minor release.

| Sprint | Feature |
|-|-|
| 54 | **Layout quality zero-crossing gate** — all quality-gated sample schematics now target zero wire-through-body crossings, with body-aware stubs, tapped-rail splitting, unrounded keep-outs, and generator-visible layout-quality warnings/reports. |
| 54 | **Density, sheet splitting, and autorouter hardening** — connector-heavy layouts now use a continuous density score, oversized sheets split instead of cramming onto A0, and Freerouting preflight/effort/timeout handling fail closed with clearer remediation. |
| 53 | **Schematic readability and passive placement** — sidecar passives, passive motifs, and local wiring now use occupancy-aware placement and body-aware routing to remove symbol overlaps and sharply reduce wire-body crossings. |
| 52 | **Part-neutral repair and schema plumbing** — normalized `pin_roles` now flow through `ComponentDef`, `ic_data`, EasyEDA imports, generic-builder outputs, and cache round-trips, so SPI/UART repair can operate from shared capabilities instead of exact MPN branches. |
| 52 | **Generation and placement hardening** — readiness gating now lives in `generate_from_components`, generic bypass policy is centralized, orphan non-power nets are hard-gated in placement-readiness, and PCB placement preview now penalizes long connected pairs instead of staying purely zone-based. |
| 51 | **Restart and validation flows are more truthful** — `log-status` works for validate-only sessions, persisted validation summaries now reflect the final verdict, Windows text-mode validation falls back to ASCII, and bad data-driven `ic` resolution now fails closed instead of silently substituting another part. |
| 51 | **Workflow skills are less brittle under long-running sessions** — `/circuit-weaver` now reports the installed CLI version first, long steps require timeout follow-up checks, and the validate-output recipe now preserves JSON on stdout instead of mixing it with stderr. |
| 50 | **Generic builder parity gate is closed** — the data-driven path now covers the remaining sensor-front-end, shared-bus, battery, display, and passive-diode contracts that were blocking the sample/corpus release gate; the full suite passes `1009 passed, 1 skipped`. |
| 50 | **CLI/package workflows are hardened for PyPI use** — read-only spec directories no longer crash file logging, unreadable `~/.config/secrets.env` no longer breaks `doctor` or unknown-part fallback, and the bundled skill payload is resynced byte-identical with `skills/`. |
| 49 | **Wizard intake now tiers by experience level** — the offline `design-wizard` asks for experience before requirements, uses compact design-brief intake for advanced/professional users, and no longer forces the same opening question flow on every user. |
| 49 | **Specialized RF workflows are now framed correctly** — Circuit Weaver skills now route radar / RF / microwave requests into a research-first custom engineering flow instead of treating the lack of turnkey coverage as an out-of-scope rejection. |
| 45-47 | **Schematic paper over-promotion fix** — `layout_sheet()` now starts from the allocator-selected paper size and only promotes if it doesn't fit. Small IoT-sensor-class designs no longer cascade to A2. Tighter title-block clearance keeps content on A3. |
| 45-47 | **Design log severity mapping** — `DesignLogHandler` maps Python `WARNING` records to `"warning"` type instead of `"error"` in `design.log`. |
| 45-47 | **BME688 bundled IC data** — sensor pin/footprint metadata shipped in `ic_data/misc.json`. `IoT_AQ_Sensor_v2` resolves without local `custom.json`. |
| 45-47 | **JLCPCB assembly variants** — `generate_assembly_variants()` supports `include_refs`, `exclude_refs`, `dnp_refs` subsets; per-variant BOM/CPL output. |
| 45-47 | **Allocator + placement-readiness tests** — 52 new dedicated tests closing Sprint 42 coverage gaps. |
| 44 | **Label collision avoidance** — overlapping labels on dense sheets are detected and shifted along wire-stub direction. Same-name labels skipped. |
| 44 | **Validate-all regression gate** — 14+1 sample YAMLs now validate clean; CI gate enforces zero hard errors. |
| 44 | **Sourcing auditor alternates** — queries LCSC/DigiKey for functionally similar parts when a component has CRITICAL/WARNING risk. |
| 44 | **MCP server** — `circuit-weaver-mcp` entry point for AI agent tool access via FastMCP. |
| 44 | **Wire-crossing minimization** — placer penalizes crossing-dense placements; bus signal groups detected for future parallel routing. |
| 43 | **Density-scaled grid spacing** — inter-component gaps scale to spread content across available page area, preventing corner-clustering on large sheets. |
| 43 | **Annotation overlap prevention** — per-IC annotations shift down when they would collide, with overflow line drops. |
| 43 | **Lane routing counter recycling** — capped at 6 with modulo wrap, preventing lanes from drifting 194mm from the IC. |

<details><summary>v0.27.0</summary>

| Sprint | Feature |
|-|-|
| 40 | **Cache-rebuilt components no longer ship as silent 2-pin stubs** — `SymbolResolver._rebuild_from_cache` now marks cache hits without real pin topology as `pinout_source="stub"`, so the existing `pinout-source` validator gate catches any multi-pin IC (sensor, MCU, H-bridge, gate driver, regulator) that would otherwise emit as a passive. The EasyEDA tier now persists full pin + power + bypass / strap topology via `symbol_cache.component_def_to_cache_payload()` so round-tripping a part through the cache preserves everything |
| 40 | **Schematic emission invariant** — `primitives.assemble_sheet` now dedupes structural duplicates before writing (symbol instances, wires, global / hierarchical labels, no-connects, junctions, UUIDs). Catches the placer / topology-dispatcher double-emission class of bug that was causing stacked passives, duplicate wires, and shared-UUID power symbols |
| 40 | **Placement PCB preview never fabricates footprints or synthetic pads** — the generator field now reads `placement_preview` so reviewers can tell the file apart from fab-ready output; missing footprint bindings emit `Placement_Preview:Missing_<ref>` placeholders instead of the old SOIC-8 fallback; and no synthetic pads are emitted for any component. KiCad's schematic → PCB forward annotation is the authoritative source of pads |
| 40 | **`generate` enforcement is now deterministic across runs** — structural + implementation category errors always raise, regardless of `require_valid`. `--no-require-valid` now only bypasses soft electrical warnings (dangling dev signals, crystal load-cap tolerance) and the bypass is logged at WARNING level. Two runs on the same spec + cache state always reach the same verdict |
| 40 | **Report-fidelity diagnostic** — `report.verify_report_fidelity(report_text, components)` flags references to component refs, net names, or annotations that don't exist in the resolved design. Catches the ghost-feature pattern where a report claimed "BME688 I2C + pull-ups" or "LED + current-limit R4" without any backing wires |
| 40 | **Five-archetype generation regression corpus** — `tests/test_generation_corpus.py` runs `generate_artifacts` end-to-end on LED driver, IoT sensor, motor controller, USB bridge, and FPGA power carrier samples, enforcing all three Sprint 40 invariants. Breadth-guard test keeps the corpus at ≥ 5 archetypes |
| 39 | **Step 2 IC research stays in the current agent session** across Codex / Claude / OpenCode instead of delegating to a spawned `/research` / `research-analyst` path that could trigger model conflicts; workflow docs and skill prompts now describe the real behavior |
| 39 | **Research-depth latency selector** — `design-wizard --research-depth {fast,normal}` persists into spec metadata; `doctor` reports the effective depth; Circuit Weaver skill uses a smaller query budget in `fast` mode |

</details>

<details><summary>v0.26.1</summary>

| Sprint | Feature |
|-|-|
| 38 | **Research workflow is now reproducible end-to-end** — `design-wizard --research-backend` persists the effective backend into spec metadata, `save-research` records the canonical JSON artifact path in `design.log`, and the workflow docs now tell agents to treat `output/research/` as the source of truth |
| 38 | **Resolver credential diagnostics now match real runtime behavior** — DigiKey checks both `DIGIKEY_CLIENT_ID` and `DIGIKEY_CLIENT_SECRET`, Mouser honors `MOUSER_SEARCH_API_KEY` through the shared credential loader, and `circuit-weaver doctor` now reports both credential states directly |
| 37 | **Research persistence + backend selection shipped in the CLI** — `circuit-weaver save-research`, `CIRCUIT_WEAVER_RESEARCH_BACKEND`, and `circuit-weaver doctor` backend reporting are now available in the published package |

</details>

<details><summary>v0.25.0</summary>

| Sprint | Feature |
|-|-|
| 35 | **`install-skills` collision protection** — will no longer silently overwrite a curated `SKILL.md` whose content differs from the bundled source. New `--force`, `--backup`, `--dry-run` flags; skipped entries are reported via `skills_skipped` so you can review before acting |
| 35 | **All 11 skills now bundled in the wheel** — previously only a stale `circuit-weaver/SKILL.md` (410 of 651 lines) shipped to PyPI; `install-skills` from a fresh `pip install` was missing `bom`, `kicad`, `digikey`, `lcsc`, `mouser`, `jlcpcb`, `pcbway`, `ee`, `design_wizard`, `vivado`. Kept in sync by `scripts/sync_bundled_skills.py` with CI + pre-commit drift guards |
| 35 | **Windows CI leg** — `windows-latest` / Python 3.12 smoke run (non-blocking first sprint) covering CLI commands, doctor, skill installer, and `python -m circuit_weaver --version` |

</details>

<details><summary>v0.24.0</summary>

| Sprint | Feature |
|-|-|
| 34 | **Data-Driven Template Engine** — IC data now lives in JSON files under `src/circuit_weaver/ic_data/` (11 categories). New `topology_builders.py` produces schematic fragments dynamically, replacing hardcoded template classes |
| 34 | **7 New Subcircuit Templates** — RTC (DS3231, PCF8563), EEPROM (24LCxx, 25LCxx), wireless modules (nRF52, ESP32, LoRa), USB-C connectors, SPI bus conditioning, voltage references (REF5025, LM4040), generic connectors — total template count now 37 |
| 34 | **IC Registration CLI** — `scripts/extract_ic_data.py` harvests IC entries from datasheet research; `register_ic()` API persists to `custom.json` |
| 33 | **Platform Compatibility** — full Claude Code / Codex / OpenCode support across all skills, updated shim files, skill trigger disambiguation |
| 32 | **CLI Integration Tests** — 24 end-to-end CLI tests; informational output moved to stderr |
| 31 | **Bug Fixes & Hardening** — thread-safe logging bridge, correct zero-check scoring, connector MPN validation, SPICE value parser edge cases |

</details>

<details><summary>v0.22.0</summary>

| Sprint | Feature |
|-|-|
| 30 | **Confidence Dashboard** — `circuit-weaver confidence` aggregates 7 data sources into a 0-100 readiness score with HTML report; now a mandatory step in the wizard flow |
| 30 | **Workflow Overhaul** — wizard now 9 steps: added auto-detection, confidence check, and PCB layout preparation (placement optimizer, SVG editor, autoroute, DFM check) |
| 29 | **Enhanced Validations** — 3 new checks (power budget, thermal limits, signal integrity); cross-reference auditor validates spec-vs-schematic-vs-BOM consistency |
| 28 | **Circuit Simulation Engine** — SPICE netlist generation, ngspice runner with graceful degradation, simulation orchestrator with auto-planning and confidence scoring |
| 27 | **Project Discovery** — `circuit-weaver discover` auto-detects projects in CWD; all skills now pre-check before asking for paths |
| 26 | **Logging Overhaul** — 13 structured event types in `design.log`, Python logging bridge, `log-event` CLI for skill-callable logging, 7 modules instrumented |

</details>

<details><summary>v0.21.0</summary>

| Sprint | Feature |
|-|-|
| 25 | **Component Selection Rationale** — HTML review report now includes a per-IC table showing why each part was chosen, key electrical specs, and any reference design cited |
| 25 | **Auto Test Point Generation** — `generate_artifacts()` emits `{project}_test_points.csv` and annotates the schematic with TP labels; detects power, ground, clock, bus, and differential-pair nets |
| 24 | **Firmware Co-Design Export** — Auto-generates `{project}_pinout.csv`, STM32 `.ioc` skeleton, and ESP32 `sdkconfig.defaults` when MCU blocks are present |
| 23 | **KiCad CLI ERC Integration** — `circuit-weaver erc` runs KiCad's built-in ERC and surfaces results in the HTML report with a pass/fail badge |
| 22 | **Pinout Verification Gate** — ICs using unverified stub pinouts now fail validation before any schematic is emitted |

</details>

---

## Repo Layout

```
kicad_automations/
├── src/circuit_weaver/      # Core engine
│   ├── dispatcher.py           # Public API: validate, patch, generate, diff, pcb-feedback
│   ├── design_ir.py            # Canonical design intermediate representation (DesignIR)
│   ├── generator.py            # .kicad_sch file emitter
│   ├── validator.py            # 14-check validation pipeline (electrical + thermal + SI)
│   ├── cross_reference_validator.py  # Spec vs schematic vs BOM audit
│   ├── confidence_dashboard.py # Design readiness scoring (0–100) + HTML dashboard
│   ├── simulation.py           # Simulation orchestrator (plan → run → score)
│   ├── spice_netlist.py        # SPICE .cir netlist generator
│   ├── spice_runner.py         # ngspice subprocess runner with graceful degradation
│   ├── symbol_resolver.py      # IC symbol resolution chain (EasyEDA → cache → stub)
│   ├── symbol_cache.py         # Persistent symbol cache with full pin/power map schema
│   ├── research.py             # Research query orchestration (Perplexity / native web)
│   ├── research_store.py       # Research artifact persistence (JSON + summary.md)
│   ├── doctor.py               # Credential + backend diagnostics (circuit-weaver doctor)
│   ├── logging_bridge.py       # Unified logging: Python logging ↔ DesignLogger bridge
│   ├── design_logger.py        # Structured JSON Lines workflow logging (13 event types)
│   ├── project_discovery.py    # Auto-detect circuit projects in directories
│   ├── review_report.py        # HTML review report generator
│   ├── test_point_gen.py       # Auto test-point classification and CSV export
│   ├── firmware_export.py      # MCU co-design stubs (pinout CSV, .ioc, sdkconfig)
│   ├── placer.py               # Topology-aware schematic placement engine
│   ├── placement_optimizer.py  # Simulated annealing PCB placement optimizer
│   ├── placement_viewer.py     # Interactive HTML viewer (net highlight, thermal heatmap)
│   ├── svg_placement.py        # Bidirectional SVG placement editor (export + import)
│   ├── pcb_export.py           # Initial .kicad_pcb generation with zone-based layout
│   ├── design_scorer.py        # Electrical quality score (0–100, A–F)
│   ├── dfm_checker.py          # DFM rule checks
│   ├── thermal_analysis.py     # Thermal modeling and junction temp analysis
│   ├── si_constraints.py       # Signal integrity constraint solver
│   ├── api.py                  # FastAPI HTTP server
│   ├── helpers/placement.py    # KiCad API abstraction, footprint matching utilities
│   └── subcircuits/            # Reusable circuit template library (37 templates)
├── tests/                   # Regression test suite (998 tests)
├── skills/                  # Global workflow skills: kicad, bom, digikey, lcsc, ee…
├── project-skills/          # Per-project templates: kicad_gen, autoroute, sim…
├── agents/                  # Hardware reviewer AI agent definitions
├── rules/                   # KiCad workflow policy files
├── samples/                 # Sample designs (iot_sensor_node, zigbee_humidistat…)
└── assets/                  # README visuals: banner, workflow diagram
```

---

## Agent Platform Support

| Platform | What's included |
|-|-|
| **Claude Code** | `/circuit-weaver` global skill via `install-skills` |
| **Codex** | `AGENTS.md` guidance + global `~/.codex/skills` install |
| **OpenCode / Kilo** | `opencode.json`, `.opencode/agents/`, `.agents/skills/` shims |

Install for all platforms at once:

```bash
# Bash (Mac/Linux/WSL)
./install.sh --platform all

# PowerShell (Windows)
./install.ps1 -Platform all
```

---

## Sample Design

Try the full workflow on a built-in sample:

```bash
# Validate
circuit-weaver validate samples/iot_sensor_node/iot_sensor_node.yaml

# Generate schematic + report + test points + firmware stubs
circuit-weaver generate samples/iot_sensor_node/iot_sensor_node.yaml -o ./output

# Export JLCPCB BOM + CPL
circuit-weaver export-jlcpcb samples/iot_sensor_node/iot_sensor_node.yaml -o ./output/jlcpcb
```

---

## Contributing

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install

# Lint
python -m ruff check src tests

# Test
python -m pytest tests -q
```

Pre-commit hooks run ruff, YAML validation, and `circuit-weaver validate --strict` on changed design specs automatically.

---

## License

MIT. See [LICENSE](LICENSE).
