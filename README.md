<p align="center">
  <img src="assets/circuit-weaver-banner.svg" alt="Circuit Weaver — KiCad automation engine and workflow toolkit" width="100%">
</p>

<p align="center">
  <a href="https://github.com/mattpainter701/kicad_automations/actions/workflows/ci.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/mattpainter701/kicad_automations/ci.yml?branch=main&label=CI" alt="CI status">
  </a>
  <img src="https://img.shields.io/badge/python-3.11%2B-0b1320?logo=python&logoColor=ffd43b" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/package-circuit__weaver-0f766e" alt="Package circuit_weaver">
  <img src="https://img.shields.io/badge/target-KiCad%2010-0ea5e9" alt="Target KiCad 10">
  <img src="https://img.shields.io/badge/license-MIT-1f2937" alt="MIT License">
</p>

<p align="center">
  <strong>KiCad automation for people building real hardware.</strong><br>
  Programmatic schematic generation, transactional design validation, BOM + sourcing workflows, PCB review helpers, and agent-friendly hardware automation.
</p>

---

## What This Is

`kicad_automations` has two product layers:

| Layer | What it is | Use it for |
|---|---|---|
| `circuit_weaver` | Python package | Canonical design IR, transactional patching, strict validation, KiCad artifact generation |
| `skills/`, `project-skills/`, `agents/`, `rules/` | Workflow layer | Review, BOM, sourcing, KiCad analysis, placement, manufacturing, AI/operator playbooks |

This repo is designed for:

- engineers who want KiCad-native automation without giving up real schematic outputs
- AI/agent workflows that need a strict, machine-readable contract instead of ad hoc script chains
- downstream hardware projects that want to consume a reusable engine instead of maintaining a custom generator forever

---

## Why Circuit Weaver

Most hardware automation stops at one of two bad extremes:

- a pile of one-off scripts that only the original author can operate
- a flashy design layer that is disconnected from the actual KiCad deliverables

`circuit_weaver` sits in the useful middle:

- **canonical spec first**: YAML/Design IR is the source of truth
- **KiCad-native outputs**: generate real `.kicad_sch` artifacts, reports, and review SVGs
- **strict validity gates**: no accepted design state should be structurally, electrically, or implementation-invalid
- **agent-compatible**: patch, validate, diff, generate, and feed PCB constraints back in predictable machine-readable flows
- **downstream-friendly**: VartaSDR is one consumer, not the identity of the engine

---

## What You Can Do

### `circuit_weaver` package

- validate a canonical design with `mvp_strict`
- apply transactional patches to a design spec
- generate KiCad schematics, reports, placement hints, and review artifacts
- diff two canonical designs semantically
- ingest PCB feedback as constraints instead of silently mutating topology

### workflow layer

- analyze KiCad schematics, PCBs, and Gerbers
- audit BOMs and sync part metadata
- source alternates from DigiKey, Mouser, LCSC, JLCPCB, or PCBWay workflows
- run project-specific generation/validation/placement playbooks
- attach repo-native agents/rules to hardware review pipelines

---

## Quick Start

### Install

```bash
pip install -e ".[dev]"
circuit-weaver --version
```

### Validate a design

```bash
circuit-weaver validate src/circuit_weaver/examples/iot_sensor.yaml
```

### Generate KiCad artifacts

```bash
circuit-weaver generate src/circuit_weaver/examples/iot_sensor.yaml --output out/iot_sensor
```

### Use the Python API

```python
from circuit_weaver.mvp import (
    apply_design_patch,
    diff_designs,
    generate_artifacts,
    ingest_pcb_feedback,
    validate_design,
)

report = validate_design(spec)
result = apply_design_patch(spec, patch)
bundle = generate_artifacts(spec, output_dir="out/design")
```

---

## Product Surface

### Core transaction flow

```text
spec -> normalize -> validate -> patch -> revalidate -> generate KiCad artifacts
```

### Public workflows

| Workflow | Purpose |
|---|---|
| `validate_design()` | strict grouped validation |
| `apply_design_patch()` | transactional in-memory mutation with reject-on-failure |
| `generate_artifacts()` | derived KiCad bundle generation |
| `diff_designs()` | semantic design change reporting |
| `ingest_pcb_feedback()` | constraint/override feedback loop from layout back to design spec |

### Validation model

`mvp_strict` groups failures into:

- `structural`
- `electrical`
- `implementation`
- `presentation`

That means “the schematic generated” is not enough. The output also needs to be loadable, internally coherent, and reviewable.

---

## Repo Layout

```text
kicad_automations/
├─ src/circuit_weaver/        # package: engine, IR, MVP, validators, exporters, helpers
├─ tests/                     # package-level regression coverage
├─ skills/                    # reusable KiCad/BOM/sourcing skills
├─ project-skills/            # project workflow templates
├─ agents/                    # hardware reviewer personas
├─ rules/                     # repo-native KiCad workflow policy
└─ assets/                    # README visuals and branding
```

### Helper modules

The extracted helper layer lives under `src/circuit_weaver/helpers/`:

- `placement.py` — footprint matching and passive-placement helpers
- `silkscreen.py` — managed silkscreen ownership and collision-aware label updates
- `impedance.py` — reusable controlled-impedance math helpers

---

## Skills and Project Skills

### Global skills

- `kicad`
- `bom`
- `digikey`
- `mouser`
- `lcsc`
- `jlcpcb`
- `pcbway`
- `ee`
- `vivado`

### Project skill templates

- `kicad_gen`
- `kicad_hierarchy`
- `kicad_validate`
- `kicad_pinmap`
- `kicad_pcb_place`
- `autoroute`
- `sim`

Install global skills:

```bash
./install.sh
```

Install project-skill templates into a downstream repo:

```bash
./install.sh --project-skills-dir .claude/skills
```

---

## Downstream Boundary

Keep these **upstream** in `kicad_automations`:

- `circuit_weaver` package code
- generic helpers
- generic skills and project-skill templates
- repo-native agents and rules

Keep these **downstream** in each hardware project:

- project wrappers such as `generate_via_engine.py`
- project BOMs and pin maps
- project-local symbol and footprint libraries
- generated KiCad artifacts
- project-specific integration tests

That boundary is intentional. It keeps the engine generic while still letting each hardware program own its actual design assets.

---

## Example Output Story

<details>
<summary><strong>Worked example: buck converter flow</strong></summary>

### 1. Analyze the schematic

```bash
python3 skills/kicad/scripts/analyze_schematic.py buck.kicad_sch --output buck_analysis.json
```

### 2. Find missing sourcing data

```bash
python3 skills/bom/scripts/bom_manager.py analyze buck.kicad_sch --json
```

### 3. Pull datasheets and vendor metadata

```bash
python3 skills/digikey/scripts/sync_datasheets_digikey.py buck.kicad_sch
```

### 4. Export manufacturing BOMs

```bash
python3 skills/bom/scripts/bom_manager.py export buck.kicad_sch -o bom/bom.csv
python3 skills/bom/scripts/bom_manager.py order bom/bom.csv --boards 3 --spares 2
```

### 5. Review PCB quality

```bash
python3 skills/kicad/scripts/analyze_pcb.py buck.kicad_pcb
```

</details>

---

## Status

### Working now

- standalone `circuit_weaver` package scaffold
- extracted engine + MVP surface
- package-level tests and CI
- helper extraction
- downstream cutover path for Varta-style projects

### Active next steps

- continue polishing downstream package consumption
- deepen workflow asset extraction and cleanup
- expand acceptance fixtures beyond the current example designs

---

## Development

Run checks locally:

```bash
python -m ruff check src tests
python -m pytest tests -q
```

If you are consuming this from another repo in editable mode:

```bash
pip install -e /path/to/kicad_automations
```

---

## License

MIT. See [LICENSE](LICENSE).
