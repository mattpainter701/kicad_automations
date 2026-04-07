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

This skill is **platform-aware**:
- **Claude Code**: Uses native interactive buttons (AskUserQuestion tool) for all choices
- **Codex/OpenCode**: Uses conversational prompting with numbered options
- **CLI**: Uses `py -m circuit_weaver design-wizard` with `input()` for terminal mode

All platforms follow the same design flow — just different UI for user input.

---

## Workflow: New Design

### Step 0 — Welcome & Route

Present a choice (platform-adapted):

**Claude Code / Codex / OpenCode:**
```
Welcome to Circuit Weaver

What would you like to do?
  [1] Design a new circuit
  [2] Open an existing design
```

For Claude Code: Use AskUserQuestion with options `["Design a new circuit", "Open an existing design"]`
For Codex/OpenCode: Present as numbered list, ask user to type [1] or [2]
For CLI: User already running `design-wizard`, skip this step

Based on choice:
- **[1] New design** → Proceed to Step 1
- **[2] Existing design** → Jump to "Workflow: Existing Design" section

### Step 1 — Requirements Capture

Collect requirements through a structured conversation. Ask these questions in order:

#### 1a. Experience Level
Question: "What's your EE experience level?"

**Claude Code:** Use AskUserQuestion with options:
- Beginner (I'm new to circuit design)
- Intermediate (I've designed 1-2 circuits)
- Advanced (I've designed 5+ circuits)
- Professional (I design circuits for a living)

**Codex/OpenCode:** Present as numbered list, ask user to select [1-4]

**Reasoning:** Calibrate explanation depth and component complexity throughout the wizard.

#### 1b. Purpose & Application
Question: "What does this circuit do? (describe the end application)"

Examples:
- "WiFi environmental sensor, battery-powered, 50x30mm enclosure"
- "Motor controller for robot arm, wall-powered"
- "USB audio interface, desktop device"

**All platforms:** Ask as open text input.

#### 1c. Form Factor & Mechanical
Question: "What are the size and component height constraints?"

Examples:
- "50×30mm enclosure, max component height 12mm"
- "Credit-card sized (85×54mm), compact"
- "No size constraint, but want to fit in existing housing"

**All platforms:** Ask as open text input.

#### 1d. Power Source & Rails
Question: "What power source will you use, and what voltage rails do you need?"

Examples:
- "3.7V LiPo battery, needs 3.3V@500mA for MCU and 5V@100mA for USB"
- "5V USB, only needs 3.3V rail"
- "12V wall supply, needs 5V and 3.3V"

**All platforms:** Ask as open text input.

#### 1e. Interfaces & Sensors
Question: "What interfaces and sensors does your circuit need?"

Examples:
- "USB charging, I2C for BME280 sensor, WiFi via ESP32"
- "SPI for SD card, UART for debug, GPIO for button/LED"
- "CAN bus, no sensors"

**All platforms:** Ask as open text input.

#### 1f. Confirm & Summarize
Compile the answers and present a summary:

```
=== Requirements Summary ===

Application:    WiFi Environmental Sensor
Form Factor:    50×30mm enclosure, SMD only, <12mm component height
Power Source:   3.7V LiPo battery (500mAh nominal)
Output Rails:   3.3V @ 500mA (MCU), 5V @ 100mA (USB charging circuit)
Interfaces:     USB for charging, I2C for sensor (BME280)
Experience:     Intermediate
```

Question: "Does this look right? Any changes?"

**Claude Code / Codex / OpenCode:** Use yes/no question
**All platforms:** Accept "yes", "no", or redirection to specific field

If user wants to change something, loop back to the relevant question.

### Step 2 — Project Folder Setup

Create a folder structure and initialize the design:

```bash
mkdir -p "${PROJECT_NAME}"
cd "${PROJECT_NAME}"
```

Store the requirements temporarily (you'll pass them to Step 3).

### Step 3 — IC Research & Selection

Run `/research` agent with structured queries.

#### Phase 3a — Project Context
Single broad query to understand the design space:

```
/research "Design a [application description]. 
  Constraints: [form factor], [power source], [interfaces].
  Find 1-2 existing reference designs, key IC families (MCU, power conversion, sensors), 
  typical topologies, and estimated BOM size."
```

This grounds subsequent searches in reality.

#### Phase 3b — Targeted Function Queries
For each major functional block, run targeted research in parallel:

Based on application type, run 3-5 of these (adapt to your design):

```
/research "MCU for [interfaces: WiFi, BLE, Ethernet, etc.], 
  [power constraint: battery, low-power, high-performance].
  Return: Top 3 options with MPN, LCSC cost, key specs (flash, RAM, peripherals)."

/research "Power conversion: [input voltage] to [output voltage, current].
  Application: [battery/USB/wall-powered, form factor constraints].
  Return: Top 3 IC options (topology, MPN, LCSC cost, efficiency), required passives."

/research "[Sensor type: environmental, motion, audio, etc.] for [application].
  Interface: [I2C/SPI/analog], power constraint: [mA budget].
  Return: Top 3 sensors with MPN, LCSC cost, typical application circuit."

/research "Connector/interface: [USB/Barrel Jack/JST-PH/etc.] for [application].
  Return: Recommended part with MPN, LCSC cost, pin assignment, typical footprint."
```

Run these in parallel (spawn multiple `/research` calls).

#### Phase 3c — Present & Confirm
Consolidate findings into a table:

```
=== IC Selection Results ===

MCU (WiFi, 4MB flash, 500mA):
  [1] ESP32-S3-WROOM-1 (most common, $5.80)
  [2] ESP32-C3 (smaller, $3.50)

Power Conversion (3.7V → 3.3V @ 500mA):
  [1] TPS62300 (buck, 95% eff, $1.20)
  [2] LDO (simpler, lower noise, $0.50)

Sensor (I2C, temp+humidity+pressure):
  [1] BME280 (standard, $2.15)
  [2] BME680 (with gas, $3.50)

Charging Circuit (LiPo, USB 5V input):
  [1] TP5000 (simple, $1.80)
  [2] BQ24075 (feature-rich, $3.50)
```

**Claude Code / Codex / OpenCode:**
"Do these IC selections look good? Want to swap any?"

### Step 4 — Generate Design Spec

Call Python to scaffold the design YAML with the selected ICs:

```bash
python -m circuit_weaver scaffold \
  --name "${PROJECT_NAME}" \
  --mcu "${SELECTED_MCU_MPN}" \
  --power-converter "${SELECTED_POWER_TOPOLOGY}" \
  --output "${PROJECT_NAME}/design.yaml"
```

Example:
```bash
python -m circuit_weaver scaffold \
  --name "WiFi_Sensor_v1" \
  --mcu "ESP32-S3-WROOM-1-N16R8" \
  --power-converter "buck:TPS62300" \
  --output "WiFi_Sensor_v1/design.yaml"
```

**Output:** `design.yaml` with ICs, passives, and block structure.

### Step 5 — Validate Design

Run validation to catch errors before generation:

```bash
python -m circuit_weaver validate "${PROJECT_NAME}/design.yaml"
```

If validation passes:
```
[PASS] Design validated successfully.
  - Electrical checks: OK
  - Power domain consistency: OK
  - Decoupling coverage: OK
```

If validation fails, display errors and ask user to refine the spec.

### Step 6 — Generate Artifacts

Generate the schematic and placement files:

```bash
python -m circuit_weaver generate "${PROJECT_NAME}/design.yaml" \
  --output "${PROJECT_NAME}/output"
```

**Output files:**
- `${PROJECT_NAME}/output/main.kicad_sch` — Schematic, ready to open in KiCad
- `${PROJECT_NAME}/output/main_placement.kicad_pcb` — PCB placement hints
- `${PROJECT_NAME}/output/main_report.md` — Design analysis and power budget

### Step 7 — Design Review & Next Steps

Display:

```
=== Design Complete ===

Schematic:    ${PROJECT_NAME}/output/main.kicad_sch
Placement:    ${PROJECT_NAME}/output/main_placement.kicad_pcb
Report:       ${PROJECT_NAME}/output/main_report.md

Next steps:
  1. Open main.kicad_sch in KiCad to review the layout
  2. Add connectors, test points, and mechanical holes
  3. Run KiCad DRC/ERC checks
  4. Design the PCB layout
  5. Export gerbers and order from JLCPCB or similar
```

Question: "Want to export a BOM for ordering, or make any changes?"

**Claude Code / Codex / OpenCode:** Present choices:
- Export BOM & CPL for assembly
- Make changes to the design (return to Step 3)
- Done (exit)

---

## Workflow: Existing Design

### Route to Existing Design

Question: "Path to your design directory?"

**Claude Code / Codex / OpenCode:** Ask for text input (path to folder with `design.yaml`)

Validate the path and load `design.yaml`.

### Display Current State

```bash
python -m circuit_weaver log-status "${DESIGN_PATH}"
```

Shows:
```
=== Design Status ===

Project:      WiFi_Sensor_v1
ICs:          4 (ESP32-S3, TPS62300, BME280, TP5000)
Status:       Schematic generated, ready for PCB layout

Last operation:   Generate artifacts (2026-04-07, 18:30)
Next action:      Design PCB layout in KiCad
```

### Offer Actions

**Claude Code / Codex / OpenCode:** Use AskUserQuestion / numbered options:

```
What would you like to do?
  [1] Validate design (check electrical rules)
  [2] Regenerate schematic (after making edits)
  [3] View design report
  [4] Export BOM & CPL for ordering
  [5] Make changes to the design
  [6] Exit
```

Route based on selection:
- **[1] Validate** → Run `validate` command
- **[2] Regenerate** → Run `generate` command
- **[3] Report** → Show `main_report.md`
- **[4] Export** → Run `export-jlcpcb` command
- **[5] Changes** → Return to Step 1 (requirements capture for edits)
- **[6] Exit** → End the skill

---

## Implementation Notes

### For Claude Code
The skill should emit AskUserQuestion tool calls during its response. Claude Code's TUI will render buttons/checkboxes, and the response comes back as the tool result.

### For Codex/OpenCode
Use conversational prompting with numbered options. The AI language model handles the input, and the user types their selection naturally.

### For CLI Users
They run:
```bash
python -m circuit_weaver design-wizard
```
This directly invokes the interactive wizard with `input()` prompts. No skill involved.

### Python Subcommands
All Python operations accept **command-line arguments only**, no interactive prompts:
- `scaffold --name X --mcu Y --power-converter Z --output design.yaml`
- `validate design.yaml`
- `generate design.yaml --output ./out`
- `export-jlcpcb design.yaml --output ./export`
- `log-status project_dir`

This ensures the skill can call them without dealing with subprocess stdin/stdout complexity.

---

## Related Skills

- **design_wizard** — Offline wizard variant (no research, no IC selection)
- **research-analyst** — IC and design research agent
- **ee** — Electrical engineering formulas and analysis
- **bom** — BOM management and sourcing
- **kicad** — Schematic and PCB analysis
- **jlcpcb** — Manufacturing and ordering
