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

### Step -1 — Auto-Detection (ALWAYS RUN FIRST)

Before presenting any choices, **automatically scan the current directory for existing projects**:

```bash
python -m circuit_weaver discover --json
```

If projects are found, present them to the user:

```
Found 2 existing circuit project(s):

  #  Project                  Type            Status       Files
  -  -------                  ----            ------       -----
  1  WiFi_Sensor_v1           circuit_weaver  validated    yaml, sch, pcb, log
  2  Motor_Controller         kicad_native    generated    sch, pcb, pro

What would you like to do?
  [1] Open an existing project (select from above)
  [2] Design a new circuit
```

If no projects are found, skip directly to Step 0 with only the "Design a new circuit" option.

**Log:** `python -m circuit_weaver log-event <project_dir> --type wizard_step --message "Auto-detection: N projects found"`

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

### Step 1 — Project Setup & Folder Creation

**This step must happen FIRST, before any other questions.**

#### 1a. Project Name (REQUIRED FIRST)

Question: "What's the name of your project?"

Examples:
- "WiFi_Sensor_v1"
- "Motor_Controller_2024"
- "USB_Audio_Interface"

**All platforms:** Ask as open text input.

**Action:** 
1. Take the project name
2. Create folder: `${PROJECT_NAME}/`
3. Create logfile: `${PROJECT_NAME}/design.log`
4. Log: `[Step 1] Project created: {project_name}`
5. Print to user: `✓ Project folder and logfile created`

Continue immediately to Step 1b once folder + log are created.

#### 1b. Experience Level

Question: "What's your EE experience level?"

**Claude Code:** Use AskUserQuestion with options:
- Beginner (I'm new to circuit design)
- Intermediate (I've designed 1-2 circuits)
- Advanced (I've designed 5+ circuits)
- Professional (I design circuits for a living)

**Codex/OpenCode:** Present as numbered list, ask user to select [1-4]

**Reasoning:** Calibrate explanation depth and component complexity throughout the wizard.

**Log:** `[Step 1b] Experience level: {selected_level}`

#### 1c. Purpose & Application

Question: "What does this circuit do? (describe the end application)"

Examples:
- "WiFi environmental sensor, battery-powered, 50x30mm enclosure"
- "Motor controller for robot arm, wall-powered"
- "USB audio interface, desktop device"

**All platforms:** Ask as open text input.

**Log:** `[Step 1c] Purpose: {user_input}`

#### 1d. Form Factor & Mechanical

Question: "What are the size and component height constraints?"

Examples:
- "50×30mm enclosure, max component height 12mm"
- "Credit-card sized (85×54mm), compact"
- "No size constraint, but want to fit in existing housing"

**All platforms:** Ask as open text input.

**Log:** `[Step 1d] Form factor: {user_input}`

#### 1e. Power Source & Rails

Question: "What power source will you use, and what voltage rails do you need?"

Examples:
- "3.7V LiPo battery, needs 3.3V@500mA for MCU and 5V@100mA for USB"
- "5V USB, only needs 3.3V rail"
- "12V wall supply, needs 5V and 3.3V"

**All platforms:** Ask as open text input.

**Log:** `[Step 1e] Power rails: {user_input}`

#### 1f. Interfaces & Sensors

Question: "What interfaces and sensors does your circuit need?"

Examples:
- "USB charging, I2C for BME280 sensor, WiFi via ESP32"
- "SPI for SD card, UART for debug, GPIO for button/LED"
- "CAN bus, no sensors"

**All platforms:** Ask as open text input.

**Log:** `[Step 1f] Interfaces: {user_input}`

#### 1g. Confirm & Summarize

Compile the answers and present a summary:

```
=== Requirements Summary ===

Project:        {project_name}
Application:    WiFi Environmental Sensor
Experience:     Intermediate
Form Factor:    50×30mm enclosure, SMD only, <12mm component height
Power Source:   3.7V LiPo battery (500mAh nominal)
Output Rails:   3.3V @ 500mA (MCU), 5V @ 100mA (USB charging circuit)
Interfaces:     USB for charging, I2C for sensor (BME280)
```

Question: "Does this look right? Any changes?"

**Claude Code / Codex / OpenCode:** Use yes/no question
**All platforms:** Accept "yes", "no", or redirection to specific field

If user wants to change something, loop back to the relevant question.

**Log:** `[Step 1g] Requirements confirmed. Ready for IC research.`

### Step 2 — IC Research & Selection

Run `/research` agent with structured queries. **Log all research queries and results to design.log.**

#### Phase 2a — Project Context

Single broad query to understand the design space:

```
/research "Design a [application description]. 
  Constraints: [form factor], [power source], [interfaces].
  Find 1-2 existing reference designs, key IC families (MCU, power conversion, sensors), 
  typical topologies, and estimated BOM size."
```

This grounds subsequent searches in reality.

**Log:** `[Step 2a] Started IC research for {application} | Query logged`

#### Phase 2b — Targeted Function Queries

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

**Log:** `[Step 2b] Targeted research queries:` [list each query]

#### Phase 2c — Present & Confirm

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

**Log:** `[Step 2c] IC selections confirmed: {selected_ics_list}`

### Step 3 — Generate Design Spec

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

**Log:** `[Step 3] Design spec generated: design.yaml`

### Step 4 — Validate Design

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

**Log:** `[Step 4] Validation: {PASS|FAIL}. Errors: {error_list if any}`

### Step 5 — Generate Artifacts

Generate the schematic and placement files:

```bash
python -m circuit_weaver generate "${PROJECT_NAME}/design.yaml" \
  --output "${PROJECT_NAME}/output"
```

**Output files:**
- `${PROJECT_NAME}/output/main.kicad_sch` — Schematic, ready to open in KiCad
- `${PROJECT_NAME}/output/main_placement.kicad_pcb` — PCB placement hints
- `${PROJECT_NAME}/output/main_report.md` — Design analysis and power budget

**Log:** `[Step 5] Artifacts generated in output/`

### Step 6 — Design Review & Next Steps

Display:

```
=== Design Complete ===

Project:      ${PROJECT_NAME}
Logfile:      ${PROJECT_NAME}/design.log
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
- Run confidence report (design readiness check)
- Make changes to the design (return to Step 2)
- Done (exit)

If user selects **confidence report**, run:

```bash
python -m circuit_weaver confidence "${PROJECT_NAME}/design.yaml" --run-sims -o "${PROJECT_NAME}/output/confidence_report.html"
```

This aggregates validation, simulation, thermal, DFM, ERC, and cross-reference
checks into a single 0-100 confidence score with readiness classification
(ready_for_fab / needs_review / not_ready). Present the terminal output to the
user and mention the HTML report for detailed review.

**Log:** `[Step 6] Design review complete. User choice: {export|confidence|edit|done}`

---

## Workflow: Existing Design

### Route to Existing Design

If Step -1 already discovered projects, use the user's selection from there.

Otherwise, run auto-detection first:

```bash
python -m circuit_weaver discover --json
```

If projects are found, present the list and let the user select one by number.
If no projects are found, ask: "Path to your design directory?"

**Claude Code / Codex / OpenCode:** Ask for text input only as fallback (path to folder with `design.yaml`)

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
  [4] Run confidence report (design readiness check)
  [5] Run simulations
  [6] Export BOM & CPL for ordering
  [7] Make changes to the design
  [8] Exit
```

Route based on selection:
- **[1] Validate** → `python -m circuit_weaver validate ${DESIGN_PATH}/design.yaml --enhanced --verbose`
- **[2] Regenerate** → `python -m circuit_weaver generate ${DESIGN_PATH}/design.yaml -o ${DESIGN_PATH}/output`
- **[3] Report** → Show `main_report.md`
- **[4] Confidence** → `python -m circuit_weaver confidence ${DESIGN_PATH}/design.yaml --run-sims -o ${DESIGN_PATH}/output/confidence_report.html`
- **[5] Simulate** → `python -m circuit_weaver simulate ${DESIGN_PATH}/design.yaml -o ${DESIGN_PATH}/sims`
- **[6] Export** → Run `export-jlcpcb` command
- **[7] Changes** → Return to Step 1 (requirements capture for edits)
- **[8] Exit** → End the skill

---

## Implementation Notes

### Project Logging (ALL PLATFORMS)

**Critical:** Project folder + design.log must be created **immediately** after user enters project name (Step 1a), BEFORE any other questions.

```bash
# Step 1a action:
mkdir -p "${PROJECT_NAME}"
touch "${PROJECT_NAME}/design.log"
# Log: [Step 1a] Project created: ${PROJECT_NAME}
```

Subsequent steps must write logs like:
```
[Step 1b] Experience level: Intermediate
[Step 1c] Purpose: WiFi environmental sensor
[Step 2a] Started IC research for WiFi environmental sensor
[Step 2c] IC selections confirmed: [ESP32-S3, TPS62300, BME280]
[Step 3] Design spec generated: design.yaml
[Step 4] Validation: PASS
[Step 5] Artifacts generated in output/
[Step 6] Design review complete. User choice: export
```

### For Claude Code

The skill emits AskUserQuestion tool calls. Claude Code's TUI renders buttons/checkboxes, responses come back as tool results. **Claude orchestrates project folder creation via instructions in Step 1a**, but the actual folder/log creation happens in Python (mvp.py `_run_design_wizard()` or skill must tell user to run the CLI to create it).

### For Codex/OpenCode

Use conversational prompting with numbered options. The AI model handles the input, user types their selection. Same logging behavior as Claude Code.

### For CLI Users

They run:
```bash
python -m circuit_weaver design-wizard
```

This directly invokes `_run_design_wizard()` in Python with `input()` prompts. **The Python function handles folder + log creation immediately after getting project name.**

### Python Subcommands

All Python operations accept **command-line arguments only**, no interactive prompts:
- `scaffold --name X --mcu Y --power-converter Z --output design.yaml`
- `validate design.yaml [--enhanced] [--verbose] [--detailed-score]`
- `generate design.yaml --output ./out`
- `export-jlcpcb design.yaml --output ./export`
- `confidence design.yaml [--run-sims] [--pcb file.kicad_pcb] [-o report.html] [--json]`
- `simulate design.yaml [-o ./sims] [--type power|signal|thermal|all] [--json]`
- `discover [--root .] [--depth 2] [--json]`
- `log-event project_dir --type <type> --message <msg> [--data <json>]`
- `log-status project_dir`
- `log-view project_dir` (show recent log entries)

This ensures the skill can call them without dealing with subprocess stdin/stdout complexity.

---

## Related Skills

- **design_wizard** — Offline wizard variant (no research, no IC selection)
- **research-analyst** — IC and design research agent
- **ee** — Electrical engineering formulas and analysis
- **bom** — BOM management and sourcing
- **kicad** — Schematic and PCB analysis
- **jlcpcb** — Manufacturing and ordering
