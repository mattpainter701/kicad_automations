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

## Domain Routing

Do **not** treat the absence of built-in topology coverage as evidence that a design
domain is unsupported.

Use these routing rules:

- **Standard covered designs**: follow the normal wizard flow.
- **Specialized domains** such as RF/microwave, phased arrays, Ku-band radar,
  mmWave, precision analog instrumentation, unusual isolation, or mixed-signal
  boards with custom front ends: still proceed with Circuit Weaver, but switch
  to a **research-first custom architecture path**.

In the research-first custom architecture path:

- Use `ee` for first-principles analysis and domain-specific calculations.
- Use `sim` for RF chain / S-parameter / power / stability analysis where applicable.
- Use `kicad` for review and downstream schematic/PCB analysis.
- Capture the system as **custom blocks + interfaces + explicit constraints**
  even when no turnkey builder/topology coverage exists.
- Be precise about what is automated versus what remains manual
  (for example: transmission-line synthesis, antenna tuning, EM/cavity effects,
  array calibration, and final RF layout closure).

Do **not** respond with blanket language like "Circuit Weaver is only for
standard embedded electronics" when the real limitation is narrower: some
domains have less automation and require more manual engineering review.

---

## Long-Running Operations & Timeout Awareness

Do not let Circuit Weaver work run silently for long periods.

When a step is expected to take noticeable time — for example `confidence --run-sims`,
`simulate`, `generate` on a large design, `optimize-placement`, `autoroute`, large
research passes, or repeated validation/generation retries — follow these rules:

1. **Before starting any command likely to exceed ~2 minutes**, tell the user:
   - what command or phase is starting,
   - why it may take a while,
   - what success artifact or status you expect.
2. **At ~2 minutes without completion**, send a follow-up and check progress using the
   best available source:
   - `python -m circuit_weaver log-status <project_dir>`
   - `python -m circuit_weaver log-view <project_dir>`
   - recent entries in `design.log`
   - recent entries in `circuit-weaver.log`
   - output/artifact timestamps or files created so far
3. **At ~5 minutes**, do not just keep waiting. Inspect for actionable issues:
   - unresolved validation blockers,
   - missing dependencies/tools,
   - stalled artifact generation,
   - repeated warnings/errors in logs,
   - no file or status movement since the last check.
   Then tell the user whether the work is actively progressing, blocked, or likely stuck.
4. **At ~15 minutes**, either:
   - explain concretely why the wait is still expected and what milestone remains, or
   - stop/pivot to a smaller bounded step and surface the blocker.
5. **Never allow a run to sit silent for ~30 minutes.** Long-running work must include
   periodic follow-up plus an explicit progress/issue check.

When reopening an interrupted or stale project, check status/logs before re-running
expensive commands. Minimum restart triage:

```bash
python -m circuit_weaver log-status <project_dir>
python -m circuit_weaver log-view <project_dir>
```

If those suggest a prior failure or stalled run, inspect `design.log` and
`circuit-weaver.log` before deciding whether to retry, validate, or edit the spec.

---

## Workflow: New Design

### Step -2 — Installed Version Banner (ALWAYS RUN FIRST)

Before presenting any choices, detect the **installed Circuit Weaver CLI version**
from the command on `PATH` and paste it back to the user.

Preferred command:

```bash
circuit-weaver --version
```

Fallback if the `circuit-weaver` entrypoint is missing:

```bash
python -m circuit_weaver --version
```

Rules:

- Prefer the `circuit-weaver` command on `PATH` when available. That is the installed CLI.
- Do **not** infer the version by reading `src/circuit_weaver/__init__.py` or other repo files.
- If forced to use `python -m circuit_weaver --version` from a checkout, clearly label it as
  the local/imported version rather than the installed CLI version.

Paste back a short banner before the menu, for example:

```text
Circuit Weaver installed: v0.30.52
```

If only the fallback worked:

```text
Circuit Weaver local/imported version: v0.30.52
```

### Step -1 — Auto-Detection

Before presenting any choices, **automatically scan for existing projects and available samples**:

```bash
python -m circuit_weaver discover --json
```

Then manually scan the `samples/` directory (relative to the repo root) for available sample designs:

```bash
ls -d samples/*/  # POSIX
# or
dir /b /ad samples\  # Windows
```

**Separate user projects from bundled samples:**

- **User projects**: from the `discover --json` output, **exclude** any project whose path contains `/samples/` or `\samples\`. These are your actual user projects. Only show these in the "Open existing" option.
- **Sample designs**: the subdirectories of `samples/` are bundled reference designs (e.g. `iot_sensor_node`, `motor_controller`, `usb_uart_bridge`, `led_power_indicator`, `fpga_power_carrier`, etc.). These are NOT user projects — they are starting-point reference designs. Show these only under option [3].

If user projects are found, present them:

```
Found 2 existing circuit project(s):

  #  Project                  Type            Status       Files
  -  -------                  ----            ------       -----
  1  WiFi_Sensor_v1           circuit_weaver  validated    yaml, sch, pcb, log
  2  Motor_Controller         kicad_native    generated    sch, pcb, pro
```

If no user projects are found (only samples or nothing), skip the project list.

**Log:** `python -m circuit_weaver log-event <project_dir> --type wizard_step --message "Auto-detection: N projects found, M samples available"`

### Step 0 — Welcome & Route

Present a choice (platform-adapted):

**Claude Code / Codex / OpenCode:**
```
Welcome to Circuit Weaver

What would you like to do?
  [1] Design a new circuit
  [2] Open an existing design
  [3] Start from a sample design
```

For Claude Code: Use AskUserQuestion with options `["Design a new circuit", "Open an existing design", "Start from a sample design"]`
For Codex/OpenCode: Present as numbered list, ask user to type [1], [2], or [3]
For CLI: User already running `design-wizard`, skip this step

Based on choice:
- **[1] New design** → Proceed to Step 1
- **[2] Existing design** → Jump to "Workflow: Existing Design" section
- **[3] Sample design** → Proceed to Step 0.3 (below)

### Step 0.3 — Start from a Sample Design

List the available sample designs from the `samples/` directory:

```
Available sample designs:

  #  Sample                   Description
  -  ------                   -----------
  1  iot_sensor_node          ESP32-based IoT environmental sensor
  2  motor_controller         H-bridge motor driver with DRV8833
  3  usb_uart_bridge          USB-to-UART bridge with CH340G + ESD
  4  led_power_indicator      Discrete LED + current-limit resistor
  5  fpga_power_carrier       Multi-rail FPGA power tree
  6  battery_iot_sensor       Battery-powered BLE sensor
  7  oled_display_module      I2C OLED display
  8  wearable_bms             Coin-cell BMS + E-ink
  9  rf_frontend              LNA + mixer RF chain
  10 inverter_gate_driver     Gate driver + isolation
  11 high_voltage_isolation   Mains + safety isolation
  12 usb_regulated_supply     USB 5V regulated supply
  13 zigbee_humidistat        Zigbee humidistat

  [0] Back to main menu
```

Ask: "Which sample would you like to start from? [1-13]"

On selection:
1. Copy the sample directory to a new working project directory: `cp -r samples/<sample>/ ~/<user-chosen-name>/`
2. Ask the user for a project name (default: same as sample)
3. Rename the YAML + set project name in the spec
4. Print: `✓ Sample copied to <project_name>/`
5. Log: `[Step 0.3] Started from sample: <sample_name>`
6. Jump to "Workflow: Existing Design" section (treat the copied sample as an existing design to review/modify)

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

Immediately branch the intake style by level. Do **not** use the same first
requirements question for every tier:

- **Beginner**: Start with a plain-language application question, then ask form factor, power, and interfaces separately.
- **Intermediate**: Keep guided prompts with examples and defaults.
- **Advanced**: Start with one compact design brief covering purpose, power, interfaces, and constraints, then ask only the missing fields.
- **Professional**: Do **not** immediately ask "What does this circuit do?" as a standalone question. Ask for a compact design brief or spec fragment instead.

Useful professional format:
`purpose; input power; rails/current; interfaces; mechanical constraints; preferred ICs`

#### 1c. Requirements Intake

For **Beginner / Intermediate**, ask:

Question: "What does this circuit do? (describe the end application)"

Examples:
- "WiFi environmental sensor, battery-powered, 50x30mm enclosure"
- "Motor controller for robot arm, wall-powered"
- "USB audio interface, desktop device"

For **Advanced**, ask:

Question: "Give me a compact design brief covering purpose, power, interfaces, and constraints."

For **Professional**, ask:

Question: "Paste a compact design brief or spec fragment. Useful format: purpose; input power; rails/current; interfaces; constraints."

**Log:** `[Step 1c] Purpose: {user_input}`

If the brief indicates specialized RF/microwave work (radar, phased array,
Ku-band, mmWave, custom RF front-end), immediately switch from generic
embedded intake to a specialized architecture intake. Ask for:

- frequency band and bandwidth
- system architecture (FMCW, direct conversion, superhet, IF chain, etc.)
- channel/array count
- LO/reference clock plan
- gain / NF / power / dynamic-range targets
- controlled-impedance and shielding constraints

Do **not** refuse the design space. Frame it as:
"supported through a custom engineering workflow with manual RF closure."

#### 1d. Form Factor & Mechanical

Only ask this as a separate follow-up if it was not already captured clearly in Step 1c.

Question: "What are the size and component height constraints?"

Examples:
- "50×30mm enclosure, max component height 12mm"
- "Credit-card sized (85×54mm), compact"
- "No size constraint, but want to fit in existing housing"

**All platforms:** Ask as open text input.

**Log:** `[Step 1d] Form factor: {user_input}`

#### 1e. Power Source & Rails

Only ask this as a separate follow-up if Step 1c did not already capture input power and rail/current needs.

Question: "What power source will you use, and what voltage rails do you need?"

Examples:
- "3.7V LiPo battery, needs 3.3V@500mA for MCU and 5V@100mA for USB"
- "5V USB, only needs 3.3V rail"
- "12V wall supply, needs 5V and 3.3V"

**All platforms:** Ask as open text input.

**Log:** `[Step 1e] Power rails: {user_input}`

#### 1f. Interfaces & Sensors

Only ask this as a separate follow-up if Step 1c did not already capture the key interfaces, buses, or sensors.

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

Before the first query, resolve the effective research settings:

Backend:

- Respect `metadata.research_backend` from a scaffolded spec when present.
- Otherwise respect `CIRCUIT_WEAVER_RESEARCH_BACKEND={auto,sonar-pro,standard}`.
- `auto` means: use `sonar-pro` when `PERPLEXITY_API_KEY` is configured, otherwise `standard`.

Depth:

- Respect `metadata.research_depth` from a scaffolded spec when present.
- Otherwise respect `CIRCUIT_WEAVER_RESEARCH_DEPTH={fast,normal}`.
- `fast` means: latency-first pass. Run one project-context query plus at most 2 targeted
  block queries. Skip deep alternates, detailed pricing, and connector research unless the
  user explicitly asks or the block is critical.
- `normal` means: fuller pass. Run one project-context query plus the standard 3-5 targeted
  block queries, including alternatives and rough pricing context where useful.
- `circuit-weaver doctor` is the source of truth for the effective backend, depth, and
  credential status.

Use the backend consistently for the whole session:

- Keep IC research in the current agent/session. Do **not** spawn a separate
  research subagent or worker for Step 2.
- `sonar-pro` → prefer the platform's high-quality research mode **only if it
  runs in-thread in the current agent**.
- `standard` → use the platform's native web search / web fetch tools in the
  current agent.
- If the premium path would delegate to a subagent, or if it throws a model /
  tool conflict, skip it and continue with native web tooling in the current
  agent. Persist the backend that actually ran.

Persist every completed research run with `circuit-weaver save-research`. The saved
`{project_dir}/research/*.json` files are the source of truth; `design.log` should
point back to those JSON artifacts for reproducibility.

#### Phase 2a — Project Context

Single broad query to understand the design space in the current agent session:

```
Design a [application description].
  Constraints: [form factor], [power source], [interfaces].
  Find 1-2 existing reference designs, key IC families (MCU, power conversion, sensors),
  typical topologies, and estimated BOM size."
```

If `sonar-pro` is available without delegation, use that path for the query.
Otherwise, run the same query with the platform's built-in web tools and record
`standard` as the backend you actually used.

After the result is consolidated, persist it:

```bash
circuit-weaver save-research --project-dir ./output --backend <sonar-pro|standard> --topic "project-context" --file research.json
```

This grounds subsequent searches in reality.

**Log:** `[Step 2a] Started IC research for {application} | Query logged`

#### Phase 2b — Targeted Function Queries

For each major functional block, run targeted research in parallel:

If research depth is `fast`, run at most 2 of these and prioritize the highest-risk
blocks first:

- MCU / main SoC
- Primary power conversion path
- Primary sensor or interface only if it is novel, safety-critical, or likely to drive the package choice

In `fast` mode, return 1-2 options per block and skip deep alternates, detailed cost tables,
and non-critical connector lookups unless the user explicitly asks.

If research depth is `normal`, run 3-5 of these (adapt to your design):

```
MCU for [interfaces: WiFi, BLE, Ethernet, etc.],
  [power constraint: battery, low-power, high-performance].
  Return: Top 3 options with MPN, LCSC cost, key specs (flash, RAM, peripherals).

Power conversion: [input voltage] to [output voltage, current].
  Application: [battery/USB/wall-powered, form factor constraints].
  Return: Top 3 IC options (topology, MPN, LCSC cost, efficiency), required passives.

[Sensor type: environmental, motion, audio, etc.] for [application].
  Interface: [I2C/SPI/analog], power constraint: [mA budget].
  Return: Top 3 sensors with MPN, LCSC cost, typical application circuit.

Connector/interface: [USB/Barrel Jack/JST-PH/etc.] for [application].
  Return: Recommended part with MPN, LCSC cost, pin assignment, typical footprint.
```

Run these in parallel where the platform supports it, but keep them in the
current agent/session. Do not offload Step 2 to a research subagent. Use the
selected backend's same-agent tooling when available; otherwise use native web
tooling. Persist the backend and depth that actually ran with
`circuit-weaver save-research --project-dir ./output ...`.

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

### Step 6 — Confidence & Simulation Check

**This step runs automatically after artifact generation. Do not skip it.**

Run the confidence dashboard to get a unified design readiness score:

```bash
python -m circuit_weaver confidence "${PROJECT_NAME}/design.yaml" \
  --run-sims \
  -o "${PROJECT_NAME}/output/confidence_report.html"
```

This runs **all available checks** in one pass:
- Electrical validation (14 checks: decoupling, enable pins, power budget, thermal, SI, etc.)
- Circuit simulation via ngspice (power supply transient/AC, filter response)
- Thermal analysis (junction temperature vs Tj_max)
- Cross-reference audit (spec vs schematic, BOM completeness, duplicate refs)
- ERC (if KiCad CLI available)

Present the result to the user:

```
=== Design Confidence Report ===

Score:      82/100 (B)
Readiness:  NEEDS REVIEW

Sections:
  [OK] Electrical Validation     90/100 (A)
  [OK] Simulation                75/100 (C)
  [OK] Thermal Analysis         100/100 (A)
  [--] Signal Integrity            N/A (skipped)
  [--] Manufacturing (DFM)         N/A (skipped)
  [OK] Cross-Reference Audit     85/100 (B)
  [--] ERC/DRC                     N/A (skipped)

Action Items (2):
  - [high] U1: Ripple 62 mV exceeds target 50 mV
  - [medium] Install ngspice to enable full simulation

HTML report: output/confidence_report.html
```

**Interpretation guidance for user:**
- **ready_for_fab** (80+, no blockers): Design is ready to order
- **needs_review** (60-80): Design works but has issues worth addressing
- **not_ready** (<60 or has blockers): Must fix blockers before ordering

If score is below 80, ask the user if they want to address the action items
before proceeding. Offer to loop back to the relevant step.

**Log:** `[Step 6] Confidence: {score}/100 ({grade}), readiness: {readiness}`

### Step 7 — PCB Layout Preparation

**Goal:** Prepare the PCB for routing. This step optimizes component placement,
generates visual layout guides, and optionally auto-routes non-critical nets.

#### 7a. Placement Optimization

Run the simulated annealing placement optimizer on the generated PCB:

```bash
python -m circuit_weaver optimize-placement "${PROJECT_NAME}/design.yaml" \
  -o "${PROJECT_NAME}/output" --json
```

This optimizes component positions for:
- Thermal spacing (power ICs separated, copper pour areas)
- Signal integrity (high-speed pairs close, short traces)
- Manufacturing (courtyard clearances, assembly accessibility)

#### 7b. Interactive Placement Viewer

Generate an interactive HTML placement diagram:

```bash
python -m circuit_weaver placement-viewer "${PROJECT_NAME}/design.yaml" \
  -o "${PROJECT_NAME}/output/placement.html"
```

Present to user: "Open `placement.html` in a browser to see component positions,
net connections, and thermal heatmap. You can review before committing to routing."

#### 7c. SVG Placement Export (Optional)

For users who want to fine-tune placement visually in an editor:

```bash
python -m circuit_weaver generate "${PROJECT_NAME}/design.yaml" \
  -o "${PROJECT_NAME}/output" --svg-placement
```

This exports an editable SVG that can be modified in Inkscape/CorelDRAW and
imported back:

```bash
python -m circuit_weaver import-placement "${PROJECT_NAME}/output/main_placement.kicad_pcb" \
  --svg "${PROJECT_NAME}/output/placement.svg"
```

#### 7d. Autorouting (Optional)

If the user has Freerouting installed, offer to auto-route the PCB:

```bash
python -m circuit_weaver autoroute "${PROJECT_NAME}/output/main_placement.kicad_pcb" \
  -o "${PROJECT_NAME}/output/main_routed.kicad_pcb"
```

**Note:** Freerouting must be installed separately. If not available, the user
routes manually in KiCad. Autorouting works best for non-critical signal nets;
power and high-speed traces should be routed manually.

**Claude Code / Codex / OpenCode:** Present choices:
- **[1] Optimize placement** (recommended)
- **[2] View placement** (generate interactive HTML)
- **[3] Export SVG for manual editing**
- **[4] Autoroute** (requires Freerouting)
- **[5] Skip to review** (route manually in KiCad)

Run whichever the user selects. After each action, offer to run another or proceed.

**Log:** `[Step 7] PCB layout: {actions_taken}`

#### Related Project-Skills

For advanced PCB workflows, these project-skills provide deeper functionality:
- `/kicad_pcb_place` — constraint-based placement with pcbnew API
- `/autoroute` — detailed Freerouting workflow with DSN/SES conversion
- `/kicad_pinmap` — pin-to-net audit and verification
- `/kicad_hierarchy` — hierarchical schematic sheet management
- `/kicad_gen` — programmatic schematic generation for large ICs (BGAs)

### Step 8 — Design Review & Next Steps

Display:

```
=== Design Complete ===

Project:      ${PROJECT_NAME}
Logfile:      ${PROJECT_NAME}/design.log
Schematic:    ${PROJECT_NAME}/output/main.kicad_sch
Placement:    ${PROJECT_NAME}/output/main_placement.kicad_pcb
Placement:    ${PROJECT_NAME}/output/placement.html (interactive)
Report:       ${PROJECT_NAME}/output/main_report.md
Confidence:   ${PROJECT_NAME}/output/confidence_report.html

Next steps:
  1. Open main.kicad_sch in KiCad to review the schematic
  2. Open main_placement.kicad_pcb in KiCad for PCB layout
  3. Route remaining traces (power first, then signals)
  4. Run KiCad DRC/ERC checks
  5. Export gerbers and order from JLCPCB or similar
```

Question: "What would you like to do next?"

**Claude Code / Codex / OpenCode:** Present choices:
- Export BOM & CPL for assembly
- Re-run confidence report (after making changes)
- Re-optimize placement
- Run DFM check on PCB (`python -m circuit_weaver check-dfm <pcb>`)
- Make changes to the design (return to Step 2)
- Done (exit)

**Log:** `[Step 8] Design review complete. User choice: {export|confidence|placement|dfm|edit|done}`

---

## Workflow: Existing Design

### Route to Existing Design

If Step -1 already discovered user projects (excluding samples), present the list with numbered choices and let the user select one. Also offer a "Browse for path" option.

If no user projects were found, or the user chooses to browse:
- Ask: "Path to your design directory?" (text input)
- Expected: a directory containing a `design.yaml` or `*.kicad_pro` file

**Claude Code / Codex / OpenCode:** Ask for text input as fallback (path to folder with `design.yaml`)

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

  --- Verify ---
  [1] Validate design (electrical rules + cross-reference audit)
  [2] Run confidence report (full design readiness check)
  [3] Run simulations (SPICE power/signal analysis)

  --- Generate & Layout ---
  [4] Regenerate schematic (after making edits)
  [5] Optimize PCB placement (simulated annealing)
  [6] View interactive placement (HTML thermal/net viewer)
  [7] Autoroute PCB (requires Freerouting)

  --- Export ---
  [8] Export BOM & CPL for ordering
  [9] Export Gerbers for fabrication
  [10] Run DFM check on PCB

  --- Other ---
  [11] View design report
  [12] Make changes to the design
  [13] Exit
```

Route based on selection:
- **[1] Validate** → `python -m circuit_weaver validate ${DESIGN_PATH}/design.yaml --enhanced --verbose`
- **[2] Confidence** → `python -m circuit_weaver confidence ${DESIGN_PATH}/design.yaml --run-sims -o ${DESIGN_PATH}/output/confidence_report.html`
- **[3] Simulate** → `python -m circuit_weaver simulate ${DESIGN_PATH}/design.yaml -o ${DESIGN_PATH}/sims`
- **[4] Regenerate** → `python -m circuit_weaver generate ${DESIGN_PATH}/design.yaml -o ${DESIGN_PATH}/output`
- **[5] Optimize placement** → `python -m circuit_weaver optimize-placement ${DESIGN_PATH}/design.yaml -o ${DESIGN_PATH}/output`
- **[6] Placement viewer** → `python -m circuit_weaver placement-viewer ${DESIGN_PATH}/design.yaml -o ${DESIGN_PATH}/output/placement.html`
- **[7] Autoroute** → `python -m circuit_weaver autoroute ${DESIGN_PATH}/output/main_placement.kicad_pcb -o ${DESIGN_PATH}/output/main_routed.kicad_pcb`
- **[8] Export BOM** → `python -m circuit_weaver export-jlcpcb ${DESIGN_PATH}/design.yaml -o ${DESIGN_PATH}/export`
- **[9] Export Gerbers** → `python -m circuit_weaver export-gerbers ${DESIGN_PATH}/output/main_placement.kicad_pcb -o ${DESIGN_PATH}/gerbers`
- **[10] DFM check** → `python -m circuit_weaver check-dfm ${DESIGN_PATH}/output/main_placement.kicad_pcb`
- **[11] Report** → Show `main_report.md`
- **[12] Changes** → Return to Step 1 (requirements capture for edits)
- **[13] Exit** → End the skill

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
[Step 6] Confidence: 82/100 (B), readiness: needs_review
[Step 7] PCB layout: optimize-placement, placement-viewer
[Step 8] Design review complete. User choice: export
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

### Validation Output Handling

Treat `validate` output carefully.

- In the current Circuit Weaver CLI, `validate` already emits JSON to **stdout** by default.
- Human diagnostics and environment warnings may still appear on **stderr**.
- Do **not** add `--json` to `validate` unless the CLI explicitly grows that flag in a later version.
- Do **not** merge stderr into stdout with `2>&1` before parsing JSON.
- A non-zero exit code from `validate` usually means the design is invalid, not that the command wrapper failed.

Expected top-level JSON keys:

```text
valid
summary
categories
metadata
```

Do **not** assume top-level `error_count`, `warning_count`, or `errors` fields.
Use `summary` and `categories`.

Safe pattern:

```bash
circuit-weaver validate design.yaml > val.json 2> val.err
python - <<'PY'
import json
data = json.load(open('val.json', encoding='utf-8'))
print('Valid:', data['valid'])
print('Summary:', data['summary'])
PY
```

If you need to summarize failures, read from `categories` rather than inventing a
wrapper that reparses mixed stdout/stderr streams.

---

## Related Skills

- **design_wizard** — Offline wizard variant (no research, no IC selection)
- **ee** — Electrical engineering formulas and analysis
- **bom** — BOM management and sourcing
- **kicad** — Schematic and PCB analysis
- **jlcpcb** — Manufacturing and ordering
