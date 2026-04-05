---
name: design_wizard
description: >
  Interactive circuit design wizard — a guided, step-by-step console workflow
  that takes users from a blank slate to a quote-ready KiCad project. Covers
  requirements capture, AI-driven IC selection, research-backed BOM assembly,
  manufacturing preferences, schematic generation, and PCB layout guidance.
  Trigger on phrases like "new design", "start a project", "design wizard",
  "circuit wizard", "help me design", "I want to build", "new board",
  "new circuit", or "walk me through".
---

# Circuit Design Wizard

An interactive, console-level question-and-answer workflow that hand-holds
users through the full Circuit Weaver pipeline — from vague idea to
quote-ready KiCad outputs.

**How this skill works:** You (the AI agent) drive a multi-step conversation.
At each step you ask the user targeted questions, summarize what you learned,
and then proceed. Never skip a step without telling the user why. Use the
`AskUserQuestion`-style conversational pattern throughout — present numbered
options, suggest defaults, and let the user confirm or override.

---

## Step 0 — Welcome & Orientation

Greet the user and explain what the wizard will cover:

```
Welcome to the Circuit Weaver Design Wizard.

I'll walk you through building a new circuit design from scratch:

  Step 1  Requirements & goals
  Step 2  IC selection & research
  Step 3  BOM assembly & sourcing preferences
  Step 4  Schematic generation
  Step 5  PCB layout guidance & next steps

You can pause, go back, or skip any step. Let's start.
```

Ask: **Do you have an existing YAML spec or are we starting fresh?**

- If they have a spec, load it and skip to the step that makes sense.
- If starting fresh, proceed to Step 1.

---

## Step 1 — Requirements Definition

**Goal:** Capture enough context to make informed IC and topology decisions.

Ask these questions **one group at a time** — don't dump them all at once.
After each answer, acknowledge and summarize before moving on.

### 1a. Purpose & Application

Ask:
- What does this circuit/board need to do? (e.g., "battery-powered IoT sensor",
  "USB-powered motor controller", "audio amplifier with Bluetooth")
- What is the end-use environment? (consumer, industrial, automotive, hobby)
- Any size or form-factor constraints? (e.g., "fits in a 50x30mm enclosure")

### 1b. Features & Interfaces

Ask:
- What external interfaces are needed? (USB, SPI, I2C, UART, Ethernet, WiFi,
  BLE, CAN, analog I/O, GPIO, display, buttons, LEDs, etc.)
- What sensors or actuators? (temperature, pressure, IMU, motor, relay, etc.)
- How many of each? Any specific models or preferences?

### 1c. Power & Electrical Requirements

Ask:
- What is the primary power source? (USB 5V, battery type/voltage, wall adapter,
  PoE, solar, etc.)
- What voltage rails do you need? (3.3V, 1.8V, 5V, 12V, etc.)
- Estimated current budget per rail? (rough is fine — "under 500mA" works)
- Any battery charging requirements?

### 1d. Goals & Constraints

Ask:
- Target unit cost at volume? (or "doesn't matter, it's a prototype")
- Target production volume? (1-off prototype, 10 units, 1000+, etc.)
- Timeline or deadline?
- Regulatory or certification needs? (FCC, CE, UL, automotive, medical, etc.)
- Any must-use or must-avoid components/vendors?

### 1e. Comparable Products or Reference Designs

Ask:
- Are there existing products, dev boards, or reference designs that do
  something similar? (e.g., "like an Adafruit Feather but with CAN bus")
- Any open-source hardware projects to draw from?
- Datasheets or app notes you've already found?

### Summary Gate

After collecting all answers, present a structured **Requirements Summary**:

```
=== Requirements Summary ===

Project:       [name]
Application:   [description]
Environment:   [consumer/industrial/etc.]
Form factor:   [constraints]

Interfaces:    [list]
Sensors:       [list]
Actuators:     [list]

Power source:  [description]
Voltage rails: [list with estimated currents]
Battery:       [charging? type?]

Volume:        [quantity]
Budget:        [target cost or "prototype"]
Certifications: [list or "none"]

Comparables:   [list]
```

Ask: **Does this look right? Anything to add or change?**

Iterate until the user confirms.

---

## Step 2 — IC Selection & Research

**Goal:** Use AI reasoning to identify the primary ICs, then kick off
research to validate and enrich selections before BOM construction.

### 2a. AI-Driven IC Reasoning

Based on the requirements summary, reason through the design and propose
primary ICs for each functional block:

- **MCU / processor** — Match peripherals, memory, package, ecosystem
- **Power management** — Buck, boost, LDO, charger ICs based on rails and source
- **Communication ICs** — WiFi/BLE modules, Ethernet PHY, CAN transceivers, etc.
- **Sensor ICs** — Match specifications to requirements
- **Driver ICs** — Motor drivers, LED drivers, display drivers
- **Protection** — ESD, overcurrent, reverse polarity

For each proposed IC, explain **why** it was chosen:

```
=== Proposed IC Selection ===

MCU: ESP32-S3-WROOM-1 (N16R8)
  Why: WiFi + BLE built-in, sufficient GPIO for your sensor array,
       large community, good availability, JLCPCB basic part

Power: TPS563200 (5V→3.3V buck, 3A)
  Why: Wide input range covers USB 5V with margin, high efficiency
       at your current draw, SOT-23-6 keeps it small

Sensor: BME280
  Why: Temp + humidity + pressure in one package, I2C, matches your
       environmental monitoring requirement

[... etc for each block ...]
```

Ask: **Do these selections look reasonable? Want me to research alternatives
for any of them?**

### 2b. Parallel Research Jobs

For each confirmed IC, kick off research to gather:

1. **Datasheet review** — Verify pinout, electrical specs, recommended circuit
2. **Application circuit** — Extract reference design from datasheet
3. **Availability check** — Stock at DigiKey, Mouser, LCSC (use distributor skills)
4. **Alternative parts** — At least one pin-compatible or functional alternative
5. **Known issues** — Errata, common design pitfalls, community reports

Use the `digikey`, `mouser`, and `lcsc` skills to search for parts and check
stock. Use the `ee` skill for any calculations (power budgets, filter values,
thermal checks).

Present research results per IC:

```
=== Research: ESP32-S3-WROOM-1 ===

DigiKey:  In stock (2,400+ units), $3.15 @ qty 1
Mouser:   In stock (800+ units), $3.22 @ qty 1
LCSC:     In stock (JLCPCB basic), $2.85 @ qty 1

Reference circuit: See datasheet Section 4.2
  - Requires 3.3V rail, 500mA peak during TX
  - 10uF + 100nF decoupling on VDD
  - EN pin needs RC delay (10k + 1uF)
  - USB D+/D- need 22R series resistors

Alternatives:
  - ESP32-C3-MINI-1: Cheaper, single-core, fewer GPIO (if you can trim pins)
  - STM32WB55: ST ecosystem, better low-power, no WiFi (BLE only)

Known issues:
  - GPIO 12 must be LOW at boot (strapping pin)
  - ADC2 unavailable when WiFi active
```

Ask after presenting all research: **Any ICs you want to swap or dig deeper on?**

### 2c. Subcircuit Template Matching

Check which of the confirmed blocks map to existing `circuit_weaver` subcircuit
templates (there are 30+ in `src/circuit_weaver/subcircuits/`):

- buck, boost, buck_boost, ldo, charge_pump, power_mux
- usb, ethernet, can_transceiver, rs485_transceiver
- motor_driver, relay_driver, led_driver, display_driver
- crystal_oscillator, clock, i2c_bus, opamp, audio_amplifier
- sensor_frontend, current_sense, battery_monitor, battery_charger
- mosfet_switch, driver, protection, adc, dac

Report which blocks have templates and which will need custom definition:

```
Template matches:
  [x] Power: buck (TPS563200)         -> subcircuits/buck.py
  [x] Power: ldo (TLV75533)           -> subcircuits/ldo.py
  [x] Sensor: sensor_frontend (BME280) -> subcircuits/sensor_frontend.py
  [x] Comms: usb (USB-C)              -> subcircuits/usb.py

Custom blocks needed:
  [ ] MCU: ESP32-S3 — will use component_db + manual pin mapping
  [ ] Custom analog frontend — no matching template
```

---

## Step 3 — BOM Assembly & Sourcing Preferences

**Goal:** Build the BOM with user input on manufacturing, vendors, and budget.

### 3a. Manufacturing Intent

Ask:
- **Where do you plan to manufacture?**
  - Hand-solder prototype at home
  - JLCPCB (economic or standard assembly)
  - PCBWay
  - Local PCB house (specify)
  - Other (specify)

- **Assembly level?**
  - Bare PCB only (you solder everything)
  - Partial assembly (fab places SMD, you do through-hole)
  - Full turnkey assembly

- **PCB specs?**
  - Layer count preference? (2-layer is cheapest, 4-layer for complex designs)
  - Any controlled impedance needs? (USB, Ethernet, RF)
  - Board thickness? (standard 1.6mm unless specified)
  - Surface finish? (HASL is cheapest, ENIG for fine-pitch)

### 3b. Vendor & Sourcing Preferences

Ask:
- **Preferred distributors?** (or "whatever is cheapest")
  - DigiKey (fast US shipping, best for prototypes)
  - Mouser (similar to DigiKey, good international)
  - LCSC (cheapest, best for JLCPCB assembly)
  - No preference / mix-and-match

- **Budget constraints?**
  - Target BOM cost per board?
  - Maximum spend for this prototype run?
  - Number of boards for first run?

- **Part preferences?**
  - Prefer JLCPCB basic parts where possible? (cheaper assembly fee)
  - Prefer automotive-grade parts?
  - Any approved vendor list (AVL) to follow?
  - Preferred passive sizes? (0402 for density, 0603 for hand-solder, 0805 for easy rework)

### 3c. BOM Construction

Using the confirmed ICs and user preferences, build the initial YAML spec:

1. Map each IC to its block definition (power, digital, sensors, connectors)
2. Add support passives (decoupling caps, pull-ups, etc.) — the engine handles
   most of these automatically
3. Set distributor preference flags
4. Generate the initial spec file

Present the draft BOM summary:

```
=== Draft BOM Summary ===

Active components:     8 unique / 8 total
Passive components:    ~24 (auto-generated decoupling, pull-ups, etc.)
Connectors:            3

Estimated BOM cost:    ~$12.50/board @ qty 5 (DigiKey prototype pricing)
JLCPCB assembly cost:  ~$4.20/board (6 basic + 2 extended parts)

All parts in stock:    Yes (checked DigiKey + LCSC)
```

Ask: **Want to review the full part list, or does this summary look good
to proceed?**

If they want the full list, present it in a table with MPN, description,
quantity, unit cost, and distributor.

---

## Step 4 — Schematic Generation

**Goal:** Generate the KiCad schematic and set expectations for what comes out.

### 4a. Pre-Generation Review

Before generating, confirm the YAML spec with the user:

```
I'm about to generate the KiCad schematic from this spec:

  Project:    [name]
  Sheets:     [estimated count] (1 top-level + N sub-sheets)
  Components: [count] active + [count] passive
  Power tree: [description]
  Buses:      [I2C, SPI, UART, etc.]

Output directory: [path]
```

Ask: **Ready to generate? Any last changes?**

### 4b. Generate & Validate

Run the generation pipeline:

```bash
# Generate artifacts
circuit-weaver generate [spec.yaml] --output [output_dir]

# Validate the generated output
circuit-weaver validate [spec.yaml]
```

Report results:

```
=== Generation Results ===

Files created:
  [x] project.kicad_sch          (top-level schematic)
  [x] power.kicad_sch            (power sheet)
  [x] digital.kicad_sch          (MCU + peripherals)
  [x] project_report.md          (design report)
  [x] placer_hints.json          (PCB placement guide)

Validation:
  Structural:      PASS (12/12 checks)
  Electrical:      PASS (8/8 checks)
  Implementation:  PASS (6/6 checks) [or WARN with details]
  Presentation:    PASS (4/4 checks)
```

### 4c. What's Automated vs. Manual

**Be explicit about what the user still needs to do.** This is critical for
setting expectations:

```
=== What's Done vs. What You'll Finish ===

DONE (generated automatically):
  - All symbol placements with correct pin mappings
  - Power connections and decoupling capacitors
  - Net labels for all buses (I2C, SPI, UART, etc.)
  - Hierarchical sheet structure
  - Support passives (pull-ups, bypass caps, RC filters)

YOU'LL FINISH IN KICAD (~10-20% of the schematic work):
  - Review net label names for clarity
  - Adjust component positions for readability
  - Add any project-specific notes or annotations
  - Verify pin assignments match your physical layout intent
  - Run ERC and resolve any remaining warnings
  - Fine-tune sheet aesthetics (alignment, spacing)

Open the schematic:
  kicad [output_dir]/[project].kicad_sch
```

---

## Step 5 — PCB Layout Guidance & Next Steps

**Goal:** Guide the user into the PCB phase with clear expectations about
what can be scripted vs. what requires manual KiCad work.

### 5a. PCB Kickoff

Explain the PCB workflow:

```
=== PCB Layout — What Comes Next ===

The generated schematic includes placer hints (placer_hints.json) that
suggest component grouping and rough placement zones.

WHAT WE CAN SCRIPT FOR YOU:
  - Board outline / edge cuts (Python script generation)
  - Initial component placement from placer hints
  - Mounting hole positions
  - Design rule constraints (trace widths, clearances, via sizes)
  - Zone fills for ground/power planes
  - Fiducial markers for assembly

WHAT REQUIRES MANUAL KICAD WORK:
  - Critical trace routing (power, high-speed signals)
  - Component fine-tuning for thermal and signal integrity
  - Silkscreen labels and polarity markers
  - Design review and DFM verification

I can generate Python placement scripts that automate the tedious
parts. Want me to create those?
```

### 5b. Placement Script Generation

If the user wants placement scripts, generate them using the `kicad_pcb_place`
project skill patterns:

- Board outline definition (coordinates, corner radii)
- Component placement by functional group
- Design rule settings (per the manufacturer's capabilities)
- Zone definitions for power/ground pours

### 5c. Routing Guidance

Based on the design:

- Identify critical nets that need manual routing (power, USB, high-speed)
- Suggest trace widths for power vs signal nets (use `ee` skill calculations)
- Recommend layer stackup if 4-layer
- Identify candidates for autorouting (non-critical signal nets)

Reference the `autoroute` project skill for Freerouting integration.

### 5d. Manufacturing Checklist

Based on Step 3 manufacturer choice, present the final checklist:

```
=== Pre-Order Checklist ===

  [ ] ERC clean in KiCad
  [ ] DRC clean in KiCad
  [ ] BOM exported (use /bom skill)
  [ ] Gerbers exported and visually inspected
  [ ] CPL (component placement list) generated for assembly
  [ ] Design rules match manufacturer minimums
  [ ] Silkscreen readable, polarity marked
  [ ] Test points accessible
  [ ] Board dimensions verified against enclosure
```

Reference the `jlcpcb` or `pcbway` skill for manufacturer-specific DFM rules.

---

## Conversation Style Guide

Throughout the wizard, follow these principles:

1. **One topic at a time.** Don't ask 10 questions in one message. Group 2-3
   related questions, wait for answers, acknowledge, then move on.

2. **Suggest sensible defaults.** "For a prototype, I'd suggest 0603 passives
   and HASL finish — does that work?" is better than "what passive size and
   surface finish do you want?"

3. **Show your reasoning.** When recommending an IC or topology, briefly
   explain why. Users learn from this and catch bad assumptions early.

4. **Summarize before proceeding.** At each step boundary, show what you
   captured and ask for confirmation before moving to the next step.

5. **Save progress.** After Steps 1 and 2, offer to save a draft YAML spec
   so the user doesn't lose work if the session ends. After Step 3, the
   spec should be saved to disk.

6. **Be honest about limitations.** If the engine can't handle something
   (e.g., a very unusual topology), say so and suggest the manual path.

---

## Related Skills

| Skill | Used in step | Purpose |
|-------|-------------|---------|
| `ee` | 1, 2 | Calculations: power budget, filter values, thermal |
| `digikey` | 2, 3 | Part search, stock check, datasheets |
| `mouser` | 2, 3 | Alternative sourcing |
| `lcsc` | 2, 3 | Production sourcing, JLCPCB parts |
| `bom` | 3 | BOM export and order file generation |
| `kicad` | 4 | Schematic analysis and validation |
| `jlcpcb` | 3, 5 | DFM rules, assembly ordering |
| `pcbway` | 3, 5 | Alternative fab DFM rules |
| `kicad_gen` | 4 | Programmatic schematic generation |
| `kicad_pcb_place` | 5 | Placement scripting |
| `kicad_validate` | 4 | Validation runner |
| `autoroute` | 5 | Freerouting integration |

---

## Resuming a Wizard Session

If the user returns and says "continue my design" or "where were we":

1. Look for a saved YAML spec in the project directory
2. Determine which step was last completed based on spec completeness:
   - Has requirements but no ICs → resume at Step 2
   - Has ICs but no sourcing data → resume at Step 3
   - Has full spec but no generated files → resume at Step 4
   - Has generated schematics → resume at Step 5
3. Summarize the current state and confirm with the user before proceeding
