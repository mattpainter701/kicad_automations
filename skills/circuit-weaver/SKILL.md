---
name: circuit-weaver
description: >
  Circuit Weaver main entry point. Routes to new design (wizard + research-driven IC selection + 
  passive generation + schematic generation) or opens existing design for review/modification.
  Trigger on: "design a circuit", "new design", "design wizard", "circuit-weaver", or 
  when user provides a design directory path.
---

# Circuit Weaver — Main Entry Skill

The master entry point for circuit design workflows. This skill orchestrates:
1. New design creation (wizard + requirements + research + IC selection + BOM + passive generation + schematic)
2. Existing design loading and review

## Quick Start

**For a new design:**
```
/circuit-weaver
→ [asks new/existing]
→ [collects requirements via design_wizard]
→ [spawns research agent to find ICs]
→ [generates passives, validates, creates schematic]
```

**For an existing design:**
```
/circuit-weaver
→ [asks for design directory path]
→ [loads design.yaml and reports current state]
→ [offers options: validate, regenerate, modify, review]
```

---

## Workflow: New Design

### Step 0 — Welcome & Route

Display:
```
Welcome to Circuit Weaver

What would you like to do?
  [1] Design a new circuit (I'll guide you through the full workflow)
  [2] Open an existing design (I'll load your project)
```

Ask user to choose. If [1], proceed to Step 1. If [2], jump to "Existing Design" section below.

### Step 1 — Requirements Capture

Use the existing `design_wizard` skill logic (Steps 0-1a from `skills/design_wizard/SKILL.md`):

1. **Experience Level** — Ask beginner/intermediate/advanced/professional
   - Calibrate explanation depth throughout
2. **Purpose & Application** — What does this board do?
   - Example: "WiFi environmental sensor, battery-powered, 50x30mm enclosure"
3. **Features & Interfaces** — What external connections/sensors?
   - Example: "USB for charging, I2C for sensor, WiFi via ESP32"
4. **Power & Electrical** — Power source and rail requirements
   - Example: "3.7V LiPo, needs 5V and 3.3V rails, ~500mA total"

**Sanity check:** Run a power budget estimate inline using the `ee` skill formulas. If the math doesn't work (e.g., demanding 5A from a USB 2.0 port), flag it and ask the user to revise.

**Summarize before proceeding:**
```
=== Requirements Summary ===

Device:        WiFi Environmental Sensor (battery-powered)
Enclosure:     50x30mm (SMD components only, <10mm height)
Power source:  3.7V LiPo (500mAh nominal)
Output rails:  5V @ 1A, 3.3V @ 0.5A
Interfaces:    USB (charging), I2C (sensor)
Sensors:       Temperature + humidity + pressure
MCU:           WiFi capable (e.g., ESP32)

Power budget:  1.5A avg draw @ 3.7V → needs efficient boost + buck
Estimated BOM: 4-5 ICs (boost, buck, MCU, sensor, maybe charger)
```

Ask: **"Does this look right? Any changes?"**

### Step 2 — IC Research & Selection (Hybrid Query Strategy)

**Phase 2a — Project Context** (one broad query)

Run the research-analyst agent with a single project-level query to understand design context:

```bash
/research "Design a [user's application description with form factor, power constraints, interfaces].
  Find similar existing products, reference designs, and IC families commonly used in [application category].
  Return: 1-2 comparable designs, key IC families, typical topologies, power budgets."
```

This grounds subsequent searches in project reality.

**Phase 2b — Targeted Function Queries** (parallel sub-queries)

Once you understand the design space, run **3-4 parallel targeted queries** for each functional block:

```bash
# These run in parallel:
/research "Boost converter: [user's input voltage] to [output voltage] @ [current].
  Find common ICs used in [application]. Return: 3 options with MPN, LCSC cost, typical application circuit."

/research "MCU for [specific features: WiFi, BLE, audio processing, etc.]. 
  Find suitable processors with [required interfaces]. Return: 3 options with MPN, LCSC cost, peripheral support."

/research "Audio codec and speaker driver for battery-powered [application].
  Find low-power solutions. Return: 3 options with MPN, LCSC cost, power consumption."

/research "Sensor/interface: [specific sensor type or interface bus].
  Find components suitable for [application]. Return: 3 options with MPN, LCSC cost, pins/packages."
```

Each narrow query (5-10 sec) is faster than one mega-query (15-60 sec).

**Phase 2c — Merge & Present**

Consolidate findings from all queries:
- Project context from 2a guides IC selection
- Specific recommendations from 2b (no duplication)
- Display as unified table with cross-references to project context

**User confirmation:**

Display research findings:
```
=== IC Research Results ===

Boost Converter (3.7V → 5V @ 1A):
  [1] TPS61230A (most common, $2.50)
  [2] MT3608   (budget option, $1.00)
  [3] LTC3105  (low-dropout, $4.20)

Buck Converter (5V → 3.3V @ 0.5A):
  [1] AP62300  (recommended, $1.20)
  [2] LM3671   (lower noise, $2.80)

MCU (WiFi, 4MB flash):
  [1] ESP32-WROOM-32E (widely used, $5.80)
  [2] ESP32-S3        (newer, better performance, $6.50)

Sensor (I2C, temp/humidity/pressure):
  [1] BME280 (very common, $2.15)
  [2] BME680 (gas sensor too, $3.50)

Charger (LiPo, optional):
  [1] TP5000 (simple, $1.80)
  [2] BQ24075 (more features, $3.50)
```

Ask: **"Do these IC choices look good? Any you'd like to swap?"**

If user wants to change any, re-run research for that block and re-confirm.

### Step 3 — Passive Generation & BOM Assembly

Once ICs are locked:

1. **Collect IC datasheets** — Extract from research findings
2. **Generate passives** — For each IC, calculate:
   - Input/output bulk caps (aluminum or ceramic, voltage rating, ESR)
   - Decoupling caps (100nF per VCC pin + 10µF mid-range)
   - Feedback divider resistors (voltage dividers for buck/boost feedback)
   - RC/LC filters (input/output EMI filters, crystal load caps)
   - Current-sense resistors (if any)
3. **Build initial BOM** — Combine ICs + passives
4. **Search LCSC for all parts** — Get live pricing and stock

Display:
```
=== Generated BOM ===

Reference | MPN              | Value         | Package  | LCSC       | Cost
----------|------------------|---------------|----------|------------|--------
U1        | TPS61230A        | Boost Conv.   | SOT-23-6 | C406093    | $2.50
U2        | AP62300          | Buck Conv.    | SOT-23-6 | C460320    | $1.20
U3        | ESP32-WROOM-32E  | WiFi MCU      | SMD-30   | C529676    | $5.80
U4        | BME280           | Sensor        | LGA-8    | C91305     | $2.15
C1-C8     | Passives (caps)  | Various       | 0402-1206| Various    | $0.60
R1-R8     | Passives (R)     | Various       | 0402     | Various    | $0.15
          |                  |               |          | TOTAL:     | $12.40
```

Ask: **"BOM looks good? Want to add/remove anything before we generate the schematic?"**

### Step 4 — Schematic Generation & Validation

Run the circuit-weaver CLI subcommands:

```bash
# Validate the design spec
circuit-weaver validate design.yaml

# Generate schematic, BOM, placement files, and design report
circuit-weaver generate design.yaml --output ./output
```

Display results from validation:
```
=== Validation Report ===

Structural checks:      PASS
Electrical checks:      PASS
  [✓] Power domain consistency (3 domains: VBAT, VBUS_5V, VDD_3P3)
  [✓] Decoupling coverage (all ICs have 100nF + bulk caps)
  [✓] Net connectivity (16 nets, no floating pins)
  [✓] Component ratings (voltage/current within safe limits)
  [✓] Feedback dividers (buck/boost feedback verified)
  [✓] Filter cutoff frequencies (input/output EMI filters OK)
  [✓] Crystal load caps (if applicable)
  [✓] Inductor selection (saturation current sufficient)

Implementation checks:   PASS
Presentation checks:    PASS

Overall: PASS (ready for schematic generation)
```

Display generated files:
```
=== Generated Artifacts ===

Schematic:
  ✓ output/main.kicad_sch (73 KB, 4 ICs + 16 passives, 16 nets)
  ✓ KiCad-native format, ready to open in KiCad GUI

PCB Placement:
  ✓ output/WiFi_Sensor_v1_placement.kicad_pcb (footprints with hints)

Design Documentation:
  ✓ output/WiFi_Sensor_v1_report.md (design analysis, power budget, DFM notes)
  ✓ output/design_ir.json (internal representation)
  ✓ output/canonical_spec.yaml (final design definition)
```

### Step 5 — Design Review Checkpoint

Parse the generated design report and present:
```
=== Design Review Checkpoint ===

Schematic generated: 4 ICs + 16 passive components
Nets: 16 unique signal/power networks
Power budget: 1.5A @ 3.7V → 3.9W average load

Warnings to review:
  [!] UART0_RX/TX on ESP32 are unconnected (OK for WiFi-only, but flag for user review)
  [!] I2C pull-ups on BME280 should be on parent board if shared bus

Next steps:
  1. Open output/main.kicad_sch in KiCad to review layout
  2. Add connectors, test points, mechanical holes
  3. Run KiCad DRC/ERC
  4. Generate gerbers and send to JLCPCB
```

Ask: **"Does the design look correct? Any changes needed?"**

If yes: ask what to change, loop back to Step 3.
If no: proceed to Step 6.

### Step 6 — PCB Layout Guidance & Export

Display:
```
=== PCB Layout Guidance ===

Board size: Recommend 60x40mm (fits your 50x30mm enclosure with margin)
Layers: 2-layer sufficient (single-sided with via stitching)
Component placement hints:
  - Boost converter (U1) near input (LiPo connector)
  - Buck converter (U2) near boost output
  - MCU (U3) center with decoupling caps nearby
  - Sensor (U4) on opposite edge (for airflow)
  - Power planes recommended (5V and 3.3V)

Manufacturing:
  - SMD assembly ready (all 0402-1206 passives, no fine-pitch BGA)
  - No thermal vias required for your power levels
  - JLCPCB-compatible (basic parts only)

Files ready to order:
  ✓ Design spec: design.yaml
  ✓ Schematic: output/main.kicad_sch
  ✓ Placement hints: output/WiFi_Sensor_v1_placement.kicad_pcb
  ✓ Design report: output/WiFi_Sensor_v1_report.md
```

Ask: **"Want to export manufacturing files (BOM + CPL for JLCPCB)?"**

If yes, run:
```bash
circuit-weaver export-jlcpcb design.yaml --output ./jlcpcb_export
```

This generates:
- `jlcpcb_export/bom_jlcpcb.csv` — LCSC part numbers for ordering
- `jlcpcb_export/cpl_jlcpcb.csv` — Placement file for pick-and-place
- `jlcpcb_export/README.txt` — Upload instructions for JLCPCB

---

## Workflow: Existing Design

### Load & Route

Ask: **"Path to your design directory?"**

User provides path (e.g., `./my_wifi_sensor` or `~/projects/sensor_board/design`).

Validate it contains `design.yaml`. Load it.

Display:
```
=== Loaded Design ===

Project:  WiFi_Sensor_v1
Modified: 2026-04-05
ICs:      4 (TPS61230A, AP62300, ESP32-WROOM-32E, BME280)
Status:   Schematic generated, ready for PCB layout

What would you like to do?
  [1] Validate design (check electrical rules)
  [2] Regenerate schematic (after making edits to design.yaml)
  [3] Review design report
  [4] Export manufacturing files (BOM + CPL)
  [5] Make design changes (IC swap, add/remove component, etc.)
  [6] Export gerbers (requires PCB file)
```

Route based on user's choice.

---

## Architecture: Skill vs CLI

This design separates two paths:

### `/circuit-weaver` Skill (Claude Code, Codex, OpenCode users)
- **Triggers when:** user says "design a circuit", `/circuit-weaver`, etc.
- **What it does:**
  1. Routes new vs existing design
  2. Runs interactive Q&A (steps 0-1)
  3. Spawns research-analyst agent (uses Perplexity Sonar API)
  4. Calls CLI subcommands: `circuit-weaver validate`, `circuit-weaver generate`, etc.
  5. Displays results + next steps
- **User experience:** Guided, mostly automatic, agent-driven IC research

### `circuit-weaver` CLI Wizard (Python CLI, standalone users)
When user runs:
```bash
circuit-weaver design-wizard
```

The Python CLI should:
1. Launch interactive wizard (same steps as skill)
2. Handle all Q&A locally (no agent calls)
3. Call internal functions from `mvp.py` (not subcommands)
4. Generate outputs without spawning external agents
5. Allow offline use (for environments without Perplexity API)

**Key difference:** Skill is agent-rich (research-driven), CLI is self-contained (no external APIs).

The **design_wizard** skill remains a fallback for manual step-by-step guidance if the user wants more control or offline operation.

---

## Files Generated

All files go in `./output/` and `./jlcpcb_export/`:

| File | Purpose |
|------|---------|
| `design.yaml` | Canonical circuit spec (YAML) |
| `design_ir.json` | Internal design representation (JSON) |
| `main.kicad_sch` | KiCad schematic (ready to open in KiCad GUI) |
| `main_report.md` | Design analysis report (features, power budget, DFM notes) |
| `main_placement.kicad_pcb` | PCB template with placement hints |
| `jlcpcb_export/bom_jlcpcb.csv` | BOM for JLCPCB (LCSC part numbers) |
| `jlcpcb_export/cpl_jlcpcb.csv` | Placement file for pick-and-place |

---

## Implementation Status

| Component | Status | Notes |
|-----------|--------|-------|
| CLI subcommands | ✅ Done | `validate`, `generate`, `export-jlcpcb`, etc. in `mvp.py` |
| Passive generation | ✅ Done | Implemented in subcircuits (boost, buck, etc.) |
| Research-analyst agent | ✅ Done | Uses Perplexity Sonar API via `PERPLEXITY_API_KEY` env var |
| `/circuit-weaver` skill | 🔨 TODO | Routes new/existing, orchestrates CLI calls |
| CLI wizard mode | 🔨 TODO | `circuit-weaver design-wizard` interactive workflow |
| Research integration | 🔨 TODO | Skill spawns research agent after Step 1 |

---

## Related Skills

- **design_wizard** — Detailed step-by-step guidance (manual control)
- **research-analyst** — EE research agent (IC selection, reference designs)
  - Uses Perplexity Sonar API (env var: `PERPLEXITY_API_KEY`)
  - Access: `~/.claude/agents/research-analyst.md`
- **ee** — Electrical engineering formulas (power budget, filter design)
- **bom** — BOM management and sourcing
- **jlcpcb** — Manufacturing file export and quoting
- **kicad** — Schematic and PCB analysis

