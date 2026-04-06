# Circuit Design Wizard — User Workflow Guide

This guide walks you through what to expect when using the Circuit Weaver
design wizard. The wizard is an interactive, conversational workflow that
takes you from "I have an idea for a circuit" to a quote-ready KiCad project
with BOM, schematics, and PCB layout guidance.

---

## How It Works

The wizard is a console-level Q&A session. You talk to the AI agent, it asks
targeted questions, presents recommendations, and builds your design
incrementally. At every step, it summarizes what it understood and asks you
to confirm before moving on.

**Start the wizard** by saying any of:
- "I want to design a new board"
- "Start a new project"
- "/design_wizard"
- "Help me design a circuit"
- "Walk me through a new design"

You can **pause, go back, or skip** any step. If your session ends, the wizard
can pick up where you left off from your saved YAML spec.

---

## What You'll Need

Before starting, it helps (but isn't required) to have thought about:

- **What the board does** — even a rough description like "reads temperature
  and sends it over WiFi" is enough
- **How it's powered** — USB, battery, wall adapter
- **Your experience level** — the wizard adjusts its depth based on whether
  you're a beginner or a seasoned EE

Everything else can be figured out during the conversation.

---

## The Six Steps

### Step 1 — Requirements & Goals

**What happens:** The wizard asks you about your circuit in manageable chunks —
not a 20-question form. It covers:

| Topic | Example questions |
|---|---|
| Purpose | "What does this board need to do?" |
| Environment | "Consumer, industrial, automotive, or hobby?" |
| Mechanical | "Is there an enclosure? Connector positions? Height limits?" |
| Interfaces | "USB? WiFi? I2C sensors? Motors?" |
| Power | "USB 5V? Battery? What voltage rails?" |
| Goals | "How many boards? Target cost? Timeline?" |
| Comparables | "Anything similar you've seen? Dev boards? Reference designs?" |

**What you get at the end:**

A structured requirements summary that looks like this:

```
=== Requirements Summary ===

Project:       smart_greenhouse
Application:   Solar-powered environmental monitor with WiFi
Environment:   Outdoor / hobby
Form factor:   80x50mm, IP65 enclosure

Interfaces:    WiFi, I2C, UART, USB-C (programming only)
Sensors:       BME280 (temp/humidity/pressure), soil moisture (analog)
Actuators:     Relay for water valve

Power source:  6V solar panel + 3.7V LiPo battery
Voltage rails: 3.3V (200mA), 5V (100mA relay)
Battery:       LiPo charging from solar, TP4056 or similar

Volume:        5 prototypes
Budget:        ~$15/board
Certifications: None (hobby)
```

**Automatic checks at this point:**

- **Power budget validation** — the wizard does the math to confirm your power
  source can actually deliver what your circuit needs. If it doesn't add up,
  you'll know before choosing any ICs.

- **Complexity flags** — if your requirements include high-speed signals (USB 3,
  Ethernet), RF (WiFi antenna), mixed analog/digital, high current, or battery
  charging, the wizard flags these and explains what extra work they'll require.

- **Test & debug strategy** — the wizard recommends debug headers (SWD, UART),
  power LEDs, test points, and spare GPIO. These cost almost nothing but save
  enormous time when the board arrives.

---

### Step 2 — IC Selection & Research

**What happens:** Based on your requirements, the wizard proposes specific ICs
for each functional block and explains *why* each was chosen.

```
MCU: ESP32-S3-WROOM-1 (N16R8)
  Why: WiFi + BLE built-in, sufficient GPIO, Arduino/ESP-IDF support,
       JLCPCB basic part, $2.85 @ LCSC

Power: TP4056 (LiPo charger) + AP2112K-3.3 (LDO)
  Why: Simple, proven combo for solar + battery designs

Sensor: BME280
  Why: Temp + humidity + pressure in one I2C package
```

**For MCUs**, it also considers your firmware preferences — Arduino vs ESP-IDF
vs PlatformIO vs vendor SDK — because a great chip with a bad toolchain is
worse than a modest chip with great tooling.

**After you confirm the selections**, the wizard researches each IC:

- **Distributor availability** — checks LCSC and suggests DigiKey/Mouser alternatives
- **Datasheet highlights** — recommended application circuit, key specs,
  decoupling requirements
- **Alternative parts** — at least one backup for each IC
- **Known gotchas** — errata, strapping pins, common mistakes
- **Thermal analysis** — for power ICs, it calculates junction temperature
  and flags if copper pours or heatsinks are mandatory
- **Lead time check** — flags any part that's out of stock, low stock, or has
  16+ week lead times

```
=== Supply Chain Summary ===

Part                    DigiKey    Mouser     LCSC       Lead Time
--------------------------------------------------------------------
ESP32-S3-WROOM-1        2,400+     800+      In stock    Immediate
AP2112K-3.3             5,200+     3,100+    In stock    Immediate
BME280                  150        0          In stock    ⚠ Low stock
```

You can swap any IC, request deeper research, or ask for more alternatives
at any point.

---

### Step 3 — BOM Assembly & Sourcing

**What happens:** The wizard asks about your manufacturing and purchasing
preferences:

- **Where will you manufacture?** Hand-solder at home, JLCPCB, PCBWay, local
  fab, etc.
- **Assembly level?** Bare PCB, partial assembly, or full turnkey
- **PCB specs?** Layer count, surface finish, controlled impedance needs
- **Preferred distributors?** DigiKey, Mouser, LCSC, or mix-and-match
- **Budget?** Target BOM cost, max spend for this run, board quantity
- **Part preferences?** Passive sizes (0402/0603/0805), JLCPCB basic parts
  preferred, automotive grade, etc.

**What you get:**

A YAML design spec saved to your project directory, plus a BOM summary:

```
=== Draft BOM Summary ===

Active components:     8 unique / 8 total
Passive components:    ~24 (auto-generated decoupling, pull-ups, etc.)
Connectors:            3

All parts in stock:    Yes
```

You can then run `cost-bom` to estimate pricing at multiple quantity breaks, or drill into the full part list with MPNs, unit costs, and distributor details.

---

### Step 4 — Schematic Generation

**What happens:** The wizard generates your KiCad schematic from the YAML spec
using the Circuit Weaver engine.

**Before generating**, it confirms what's about to be built:

```
Project:    smart_greenhouse
Sheets:     3 (top-level + power + digital)
Components: 8 active + 24 passive
Power tree: Solar → TP4056 → LiPo → AP2112K → 3.3V
Buses:      I2C (BME280), UART (debug), SPI (none)
```

**After generating**, it runs four validation checks:

| Check | What it verifies |
|---|---|
| Structural | Topology, connections, hierarchy |
| Electrical | Power, ground, net integrity |
| Implementation | Part bindings, footprint assignments |
| Presentation | Labels, pin numbers, readability |

**What you get:**

- `.kicad_sch` schematic files (top-level + sub-sheets)
- A design report (markdown)
- Placer hints for PCB layout (JSON)

### What's automated vs. what you finish

This is important to understand:

| Done automatically (~80-90%) | You finish in KiCad (~10-20%) |
|---|---|
| All symbol placements with correct pin mappings | Review net label names for clarity |
| Power connections and decoupling capacitors | Adjust component positions for readability |
| Net labels for all buses | Add project-specific notes |
| Hierarchical sheet structure | Verify pin assignments match layout intent |
| Support passives (pull-ups, bypass caps, etc.) | Run ERC and resolve remaining warnings |
| | Fine-tune sheet aesthetics |

---

### Step 5 — Design Review Checkpoint

**What happens:** Before you invest time in PCB layout, the wizard runs an
automated design review and guides you through a manual check.

**Automated review** covers:

- Power tree completeness (all rails sourced, decoupling present, enables connected)
- Connectivity (bus pull-ups, CS lines, TX/RX crossovers)
- Protection (ESD, overcurrent, reverse polarity)
- Debug & test features (SWD, UART, power LEDs)

**Manual review checklist** — the wizard tells you exactly what to open in
KiCad and verify:

- Pin assignments match your physical layout intent
- Net names are meaningful
- No unintended connections in dense areas
- Footprint assignments are correct (SOT-23-3 vs SOT-23-5 is a classic mistake)
- Power flags on all power nets

**Why this matters:** A schematic fix takes minutes. A PCB respin after
fabrication takes weeks and costs real money. This checkpoint is where you
catch the expensive mistakes.

---

### Step 6 — PCB Layout Guidance & Next Steps

**What happens:** The wizard transitions you from schematic to PCB with clear
expectations about what can be automated and what requires manual work.

#### What we can script for you

The wizard can generate Python scripts that automate:

- Board outline / edge cuts (from your mechanical constraints)
- Initial component placement by functional group
- Mounting hole positions
- Design rule constraints (trace widths, clearances, via sizes)
- Zone fills for ground/power planes
- Fiducial markers for assembly

If you specified an enclosure in Step 1, the board outline, mounting holes,
and connector positions are already defined.

#### What requires manual KiCad work

- Critical trace routing (power buses, USB differential pairs, high-speed signals)
- Component fine-tuning for thermal management and signal integrity
- Silkscreen labels and polarity markers
- Final DFM verification

The wizard identifies which nets need manual attention and suggests trace widths
for power vs. signal nets.

**Optional: Freerouting autorouting** — If you have Freerouting installed
(separate download from https://github.com/mirage335/freerouting/releases),
the wizard can autoroute non-critical signal nets. Otherwise, manual routing
in KiCad is your best option.

#### Manufacturing checklist

Before ordering, the wizard presents a pre-flight checklist tailored to your
chosen manufacturer:

```
=== Pre-Order Checklist ===

  [ ] ERC clean in KiCad
  [ ] DRC clean in KiCad
  [ ] BOM exported
  [ ] Gerbers exported and visually inspected
  [ ] CPL (component placement list) generated
  [ ] Design rules match manufacturer minimums
  [ ] Silkscreen readable, polarity marked
  [ ] Test points accessible
  [ ] Board dimensions verified against enclosure
```

#### Revision planning

The wizard helps you prepare for the next revision:

- Add "Rev 1.0" and date to the silkscreen
- Tag the design in git
- Keep the YAML spec, generated files, and BOM committed
- Plan for rev2 (component swaps, layout tweaks, cost optimization)

---

## Experience Levels

The wizard adapts its behavior based on your self-reported experience:

| Level | What changes |
|---|---|
| **Beginner** | Every concept explained briefly as it comes up. Safe defaults suggested aggressively. Anything requiring manual EE judgment is flagged clearly. Links to reference material provided. |
| **Intermediate** | Non-obvious trade-offs explained. Defaults suggested but easy to override. Basic definitions skipped. |
| **Advanced** | Options presented first, explanations on request. Compact summaries. Obvious defaults skipped. |
| **Professional EE** | Minimal chatter. Choices presented as tables. Batch answers accepted. Option to jump straight to YAML spec editing. |

You choose your level at the start and the wizard remembers it throughout.

---

## Resuming a Session

If your session ends, you don't lose progress. Come back and say:

- "Continue my design"
- "Where were we?"
- "Resume the wizard"

The wizard finds your saved YAML spec and figures out which step you were on:

| Spec state | Resumes at |
|---|---|
| Has requirements, no ICs | Step 2 — IC Selection |
| Has ICs, no sourcing data | Step 3 — BOM Assembly |
| Has full spec, no generated files | Step 4 — Schematic Generation |
| Has schematics, no review | Step 5 — Design Review |
| Has reviewed schematics | Step 6 — PCB Layout |

---

## What the Wizard Does NOT Do

Being clear about boundaries prevents frustration:

- **It does not replace an EE for safety-critical designs.** If you're building
  something for medical, automotive, or aerospace use, the wizard will help with
  structure but you need a qualified engineer to review.

- **It does not route your PCB.** It generates placement scripts and identifies
  critical nets, but trace routing is still a manual (or Freerouting-assisted)
  step in KiCad.

- **It does not guarantee manufacturability.** It flags common DFM issues and
  checks against manufacturer minimums, but final responsibility for Gerber
  review is yours.

- **It does not order parts or boards for you.** It generates order files and
  BOMs in the right format, but clicking "submit" on DigiKey or JLCPCB is
  your call.

- **It cannot handle every topology.** Unusual circuits (RF power amplifiers,
  multi-phase switching, custom ASIC integration) may exceed what the engine
  can generate. The wizard will tell you when you've hit this boundary and
  suggest the manual path.

---

## Files Created During the Wizard

| File | Created at | Purpose | Keep in git? |
|---|---|---|---|
| `design_spec.yaml` | Step 3 | Canonical design specification | Yes |
| `*.kicad_sch` | Step 4 | Generated schematic files | Yes |
| `*_report.md` | Step 4 | Design report | Yes |
| `placer_hints.json` | Step 4 | PCB placement guidance | Yes |
| `jlcpcb/bom_jlcpcb.csv` | Step 6 | BOM for JLCPCB assembly | Yes |
| `jlcpcb/cpl_jlcpcb.csv` | Step 6 | Component placement for JLCPCB | Yes |
| `datasheets/` | Step 2 | Downloaded IC datasheets | No (large, re-downloadable) |

---

## Related Skills

The wizard coordinates with other Circuit Weaver skills automatically. You
don't need to invoke them separately, but you can if you want to go deeper
on any topic.

| Skill | What it does | When it's used |
|---|---|---|
| `ee` | Electrical engineering calculations | Power budget, thermal checks, trace widths |
| `digikey` | DigiKey part search and datasheets | IC research, stock checks |
| `mouser` | Mouser part search | Alternative sourcing |
| `lcsc` | LCSC/JLCPCB part search | Production sourcing |
| `bom` | BOM export and order files | BOM construction, order prep |
| `kicad` | Schematic and PCB analysis | Validation, design review |
| `jlcpcb` | JLCPCB DFM rules | Manufacturing prep |
| `pcbway` | PCBWay DFM rules | Manufacturing prep |

---

## Tips for a Smooth Experience

1. **Don't overthink Step 1.** Rough estimates are fine — "about 200mA" is
   better than spending an hour calculating exact current draw. The wizard
   will flag if something is obviously wrong.

2. **Trust the defaults.** For prototypes especially, the wizard's suggestions
   (0603 passives, HASL finish, 2-layer board) are battle-tested starting
   points. Override them when you have a reason to.

3. **Say "I don't know."** The wizard can suggest reasonable answers for most
   questions. Saying "not sure, what do you recommend?" is always valid.

4. **Save early, save often.** After Steps 1 and 2, accept the offer to save
   a draft YAML spec. Sessions can end unexpectedly.

5. **Review the schematic in KiCad.** Step 5 exists for a reason. Even a quick
   5-minute visual scan catches things automated checks miss.

6. **Plan for rev2.** Your first board almost never works perfectly. The spare
   GPIO, debug headers, and test points the wizard recommends will pay for
   themselves on the first debug session.
