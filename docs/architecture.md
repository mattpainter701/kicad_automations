# Circuit Weaver Architecture

This document describes the internal design, data flow, and key architectural decisions in Circuit Weaver.

## High-Level Overview

Circuit Weaver is a transactional circuit design engine that transforms YAML specifications into validated KiCad artifacts (schematics, PCB placement hints, BOMs). The architecture emphasizes **immutability**, **determinism**, and **composable transformations**.

```
┌─────────────────────────────────────────────────────────────────┐
│ USER INTERFACE LAYER                                           │
│ ├─ CLI Commands (dispatcher.py: validate, generate, scaffold, etc.)   │
│ ├─ Interactive Wizard (design-wizard skill)                    │
│ └─ Skills (bom, digikey, lcsc, jlcpcb, kicad, etc.)            │
└──────────────────────┬──────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────────┐
│ SPECIFICATION LAYER                                            │
│ ├─ YAML/JSON Input (user-provided design.yaml)                │
│ ├─ Project Spec Parser (project_spec.py)                      │
│ └─ Design Normalization (normalize_design_spec)               │
└──────────────────────┬──────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────────┐
│ DESIGN INTERMEDIATE REPRESENTATION (IR) LAYER                  │
│ ├─ DesignIR (top-level object)                               │
│ ├─ DesignBlock (circuit block: IC + support passives)        │
│ ├─ DesignInterface (power/signal connections)                │
│ └─ design_ir.py (IR transformations: normalize, diff, export) │
└──────────────────────┬──────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────────┐
│ VALIDATION LAYER                                               │
│ ├─ validator.py (validation rules: electrical, structural)   │
│ ├─ Grouped checks (5 categories, ~10 sub-checks each)        │
│ ├─ ValidationMessage (error codes + suggestions)              │
│ └─ ValidationReport (categorized results + metadata)          │
└──────────────────────┬──────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────────┐
│ GENERATION LAYER                                               │
│ ├─ generator.py (converts IR → KiCad artifacts)              │
│ ├─ KiCad Symbol Placement (allocator.py: hierarchical layout) │
│ ├─ SVG Placement Export (svg_placement.py)                   │
│ ├─ Schematic Generation (.kicad_sch files)                  │
│ ├─ PCB Hint Generation (.kicad_pcb + placement coords)      │
│ └─ Design Report (Markdown analysis)                         │
└──────────────────────┬──────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────────┐
│ ARTIFACT OUTPUT LAYER                                          │
│ ├─ KiCad schematic (.kicad_sch)                              │
│ ├─ KiCad PCB template (.kicad_pcb)                           │
│ ├─ SVG placement export (design_placement.svg)               │
│ ├─ BOM (CSV for JLCPCB, Mouser, DigiKey)                    │
│ ├─ CPL (component placement list)                           │
│ └─ Design Report (Markdown)                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Core Concepts

### Design IR (Intermediate Representation)

The IR is the **canonical representation** of a design. Everything flows through it:

```python
DesignIR (top-level):
├─ metadata: {project, version, presentation_profile, ...}
├─ blocks: [DesignBlock, DesignBlock, ...]  # Circuit blocks
└─ interfaces: [DesignInterface, ...]       # Power/signal nets

DesignBlock (e.g., LDO regulator):
├─ id: "U2_ldo"
├─ section: "power"
├─ kind: "template"  # or "raw_component"
├─ template_type: "ldo"
├─ ref: "U2"
├─ params: {vin: 5.0, vout: 3.3, vin_net: "VDD_5V", ...}
├─ components: [ComponentDef, ...]  # Generated IC + passives
└─ interfaces: [DesignInterface, ...]

ComponentDef (final mapped component):
├─ ref_prefix: "U", value: "AP2112K", footprint: "SOT-23-5"
├─ mpn: "AP2112K-3.3TR2G", datasheet_url: "..."
├─ power_reqs: [{net: "VDD_5V", voltage: 5.0}, ...]
├─ bypass_caps: [...]  # Support passives
└─ presentation: "inherit"  # Rendering profile
```

### Transactional Specs

Designs are modified via transactional **patches** that are applied atomically:

```python
# patch_ldo.json
{
  "upsert_blocks": [
    {
      "id": "U2_ldo",
      "section": "power",
      "kind": "template",
      "template_type": "ldo",
      "template_params": {"vin": 5.0, "vout": 3.3}
    }
  ]
}

# Apply with atomicity guarantee
result = apply_design_patch(spec, patch)  # All or nothing
```

### Subcircuit Templates

Templates are reusable, parameterized circuit blocks:

```python
class LDOTemplate(SubcircuitTemplate):
    def generate(self, params) -> TemplateResult:
        # Return (IC + passives) based on params
        # Params drive component selection, values, connections
```

Available templates: `ldo`, `buck`, `boost`, `audio_amplifier`, `usb_controller`, etc.

## Data Flow: From YAML to KiCad

### Step 1: Specification Parsing

```
design.yaml (YAML input)
    ↓
_simple_yaml_parse()  # YAML → dict
    ↓
normalize_design_spec()  # dict → DesignIR
    ↓
DesignIR (immutable)
```

### Step 2: Template Expansion

```
DesignIR (blocks: [template instances])
    ↓
_instantiate_templates()
  - For each block, call Template.generate(params)
  - Collect IC + support passives
    ↓
IR with resolved components
```

### Step 3: Validation

```
DesignIR (with components)
    ↓
validate_design()
  - 5 validation categories
  - Each check emits ValidationMessage
  - Grouped into ValidationReport
    ↓
ValidationReport (errors + suggestions)
```

### Step 4: Generation

```
Validated DesignIR
    ↓
generate_artifacts()
  - Allocate components to sheets (hierarchical layout)
  - Create KiCad schematic (.kicad_sch)
  - Generate PCB placement (.kicad_pcb)
  - Export SVG placement
  - Write design report
    ↓
Generated files (output/)
```

## Key Modules

### `dispatcher.py` — Core Workflow

Main CLI dispatcher and validation pipeline orchestrator.

**Exports:**
- `validate_design()` — Run validation rules
- `generate_artifacts()` — Generate KiCad outputs
- `apply_design_patch()` — Transactional spec updates
- `compile_design_ir()` — Full IR compilation pipeline

**Key Functions:**
- `_print_validation_report()` — Human-readable validation output
- `_color_support()` — ANSI color detection (Windows WT_SESSION)
- `_wizard_input()` — Input with dry-run support

### `design_ir.py` — IR Dataclasses & Transformations

**Classes:**
- `DesignIR` — Top-level design container
- `DesignBlock` — Circuit block (IC + passives)
- `DesignInterface` — Power/signal net definition
- `ComponentDef` — Mapped component with all properties

**Functions:**
- `normalize_design_spec()` — YAML → DesignIR
- `design_ir_to_spec()` — DesignIR → YAML (round-trip)
- `semantic_diff()` — Compare two designs structurally

### `validator.py` — Validation Rules

**Exports:**
- `validate_design()` — Run all checks, return ValidationReport

**Validation Categories:**
1. **Structural** — Topology, hierarchy, completeness
2. **Electrical** — Power domains, decoupling, connectivity
3. **Implementation** — Symbol bindings, footprints, MPN consistency
4. **Presentation** — Component rendering, label visibility
5. **ERC** — KiCad electrical rule checks (ERC warnings)

**Error Codes:**
- `power-domain-voltage-conflict` — Same net, different voltages
- `missing-bypass-cap-for-rail` — Undecked IC power pin
- `footprint-package-mismatch` — Symbol ↔ footprint inconsistency
- etc. (10 categories × ~10 sub-checks)

### `generator.py` — KiCad Artifact Generation

**Exports:**
- `generate_from_components()` — IR → KiCad schematic structure
- `generate_pcb_placement()` — Placement coordinates + CPL

**Submodules:**
- `allocator.py` — Hierarchical sheet allocation (grouping components)
- `svg_placement.py` — SVG export/import for placement editing
- `jlcpcb_export.py` — BOM + CPL CSV for JLCPCB

### `subcircuits/` — Template Library

**Base Class:**
- `SubcircuitTemplate` — Abstract template with `generate(params) → TemplateResult`

**Concrete Templates:**
- `ldo.py` — Linear voltage regulator
- `buck.py` — Step-down switching converter
- `boost.py` — Step-up switching converter
- `audio_amplifier.py` — Audio output stage
- `usb_controller.py` — USB device controller
- etc.

### `component_db.py` — Component Metadata

**Exports:**
- `ComponentDef` — Component with all properties (MPN, footprint, datasheet, etc.)
- `PresentationWiringPolicy` — Support passive rendering hints
- `BUILTIN_REGISTRY` — Built-in components (connectors, common parts)

### `skill_installer.py` — Skill Distribution (Task 77)

**Exports:**
- `detect_platforms()` → list of detected AI platforms
- `install_skills(platforms, skills)` → installation result

**Platforms:**
- Claude Code (`~/.claude/skills/`)
- Codex (`~/.agents/skills/`)
- OpenCode (`$OPENCODE_CONFIG_DIR/skills/` or `~/.agents/skills/`)
- Kilo (`~/.kilo/skills/`)

### `schema.py` — JSON Schema Generation (Task 79)

**Exports:**
- `get_design_ir_schema()` → JSON Schema for DesignIR

Used for IDE autocomplete (VS Code, PyCharm) and API documentation.

### `logging_bridge.py` — Unified Logging (Sprint 26)

**Exports:**
- `DesignLogHandler` — Python `logging.Handler` that routes records to `DesignLogger`
- `get_design_logger()` / `set_design_logger()` — Context-based singleton accessor
- `init_logging(project_dir)` — Creates both `design.log` (JSON Lines) and `circuit-weaver.log` (text)

### `project_discovery.py` — Project Auto-Detection (Sprint 27)

**Exports:**
- `DiscoveredProject` — Dataclass with project metadata (type, status, files)
- `discover_projects(root_dir, max_depth)` — Scan directories for circuit projects
- `detect_project_type(dir)` — Classify as `circuit_weaver`, `kicad_native`, or `mixed`

### `simulation.py` — Simulation Orchestrator (Sprint 28)

**Exports:**
- `plan_simulations(components)` — Auto-detect which simulations are needed
- `run_design_simulations(components, plan)` — Execute all planned simulations
- `score_simulation_confidence(results)` — Score 0-100 from simulation outcomes

**Dependencies:** `spice_netlist.py` (netlist generation), `spice_runner.py` (ngspice execution)

### `cross_reference_validator.py` — Design Audit (Sprint 29)

**Exports:**
- `run_cross_reference_audit(components, spec)` — 3-pass audit (spec vs schematic, BOM, consistency)
- `CrossReferenceResult` — Per-pass result with issues and checked item count

### `confidence_dashboard.py` — Design Readiness (Sprint 30)

**Exports:**
- `generate_confidence_report(...)` — Aggregate 7 data sources into weighted 0-100 score
- `DesignConfidenceReport` — Report with sections, blockers, action items, HTML/terminal output

## Design Patterns

### Immutability

- Specs and IRs are treated as immutable (dataclasses with `frozen=True`)
- Changes are made via transactional patches
- Enables safe composition and undo/redo

### Determinism

- Same input → same output (no random choices)
- Enables reproducible builds, version control-friendly diffs
- Validation errors are stable (no flaky tests)

### Composition

- Templates compose with each other (e.g., buck + LDO in series)
- Validation rules are composable (run checks in any order)
- Transformations chain: parse → validate → generate

### Fallback Chains

- Symbol resolution: custom → KiCad library → DigiKey → EasyEDA
- Datasheet download: DigiKey API → LCSC CDN → Mouser → manual
- No single point of failure

## Version & Compatibility

| Version | Feature | Status |
|-|-|-|
| 0.8.0 | Core IR + templates | Stable |
| 0.9.0 | Visual diff (SVG) | Stable |
| 0.10.x | Team adoption + CI | Stable |
| 0.11.0 | PyPI distribution + UX | Stable (Sprint 13) |
| 0.12.0 | Auto-discovery + SVG placement | Stable (Sprint 14) |
| 0.13.0 | Spec harvesting (datasheets, S-params, SPICE) | Stable (Sprint 15) |
| 0.14.0 | Placement optimizer, SI constraints, thermal analysis, dual-sided CPL, panelization | Stable (Sprint 16) |

## Future Roadmap

- **Test coverage hardening** (Sprint 17) — CLI end-to-end tests for all subcommands
- **PCB routing integration** — Freerouting + KiCad via-stitching automation
- **Multi-language support** (Future) — French, German, Mandarin, Japanese

---

For implementation details, see the relevant module docstrings and comments in the code.
