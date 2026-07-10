# Circuit Design Wizard — User Workflow Guide

This guide walks you through what to expect when using the Circuit Weaver
design wizard. The wizard is an interactive, conversational workflow that
takes you from "I have an idea for a circuit" to a quote-ready KiCad project
with BOM, schematics, and PCB layout guidance.

---

## Getting Started — Which Path?

Circuit Weaver offers **three ways** to design a circuit:

| Path | Command/Trigger | Best For | Speed | Requirements |
|------|-----------------|----------|-------|--------------|
| **`/circuit-weaver` skill** | Say "design a circuit" in Claude Code (registered globally) | Automatic, same-agent IC research (`sonar-pro` or native web) | 5–10 min | `pip install circuit-weaver` + LLM access |
| **`design-wizard` skill** | Invoke `/design-wizard` in Claude Code | Manual step-by-step control with AI guidance | 10–20 min | `pip install circuit-weaver` + LLM access |
| **`circuit-weaver design-wizard` CLI** | Run `circuit-weaver design-wizard` in terminal | Offline, standalone, good for learning | 5–10 min | `pip install circuit-weaver` (no APIs, no agents) |

**Getting Started:**

1. Install circuit-weaver: `pip install circuit-weaver`
2. Register skills: `circuit-weaver install-skills`
3. Choose your path (see table above)

**Recommendation:** Start with `/circuit-weaver` (fastest) if you want automatic same-agent orchestration. If `PERPLEXITY_API_KEY` is configured it can use `sonar-pro`; otherwise it will use native web tooling. Use the CLI wizard if you want a fully offline flow.

---

## How It Works

The wizard is a console-level Q&A session. You talk to the AI agent (or answer interactive prompts for CLI), it asks
targeted questions, presents recommendations, and builds your design
incrementally. At every step, it summarizes what it understood and asks you
to confirm before moving on.

**Start the wizard** by saying any of:
- "I want to design a new board"
- "Start a new project"
- "/circuit-weaver" (fastest, agent-driven)
- "/design-wizard" (manual step-by-step)
- "Help me design a circuit"
- "Walk me through a new design"

**Or from the terminal:**
```bash
circuit-weaver design-wizard
```

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

## The Eight Steps

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

**After you confirm the selections**, the wizard researches each IC. The
effective backend is controlled by `metadata.research_backend` in the scaffolded
spec or by `CIRCUIT_WEAVER_RESEARCH_BACKEND={auto,sonar-pro,standard}`. The
research depth is controlled by `metadata.research_depth` or
`CIRCUIT_WEAVER_RESEARCH_DEPTH={fast,normal}`.

Keep this research in the current agent session. If a premium-research command
would delegate to a subagent or hits a model/tool conflict, fall back to the
platform's native web tools and persist the backend that actually ran.

- **`fast` research depth** — one broad context query plus at most two targeted
  block queries; optimized for latency, minimal alternates/costing
- **`normal` research depth** — one broad context query plus the fuller 3-5
  targeted block queries with alternates and rough pricing context

- **Datasheet highlights** — recommended application circuit, key specs,
  decoupling requirements
- **Alternative parts** — at least one backup for each IC
- **Known gotchas** — errata, strapping pins, common mistakes
- **Thermal analysis** — for power ICs, it calculates junction temperature
  and flags if copper pours or heatsinks are mandatory
- **Traceable artifacts** — each completed query should be persisted to
  `output/research/{topic}.json` via `circuit-weaver save-research`, with
  `summary.md` as the rolling project index

You can swap any IC, request deeper research, or ask for more alternatives
at any point.

---

### Step 3 — Spec Assembly & Costing

**What happens:** You build your design specification incrementally using the
CLI commands. The wizard helps you structure each block and validates the result.

**Compatibility note:** The current CLI still uses legacy names like
`--template`, `kind: "template"`, and `template_type` in a few commands and
patch examples. Treat those as compatibility syntax for selecting a generated
block topology, not as the conceptual workflow model.

**Scaffold a starter block:**
```bash
circuit-weaver scaffold --template buck --ref U1 --output design.yaml
```

This creates a base design with one generated power block (buck converter, LDO, etc.).
You can inspect and edit `design.yaml` at any time.

**Add additional blocks via `apply-patch`:**

For each additional component block (another regulator, sensor, driver, etc.),
create a patch JSON file and apply it:

```bash
# patch_ldo.json
{
  "upsert_blocks": [
    {
      "id": "U2_ldo",
      "section": "power",
      "kind": "template",
      "template_type": "ldo",
      "ref": "U2",
      "params": {
        "vin": 3.3,
        "vout": 1.8,
        "vin_net": "VDD_3P3",
        "rail_name": "VDD_1P8"
      }
    }
  ]
}

# Apply the patch
circuit-weaver apply-patch design.yaml patch_ldo.json --output design.yaml
```

Repeat for each block until your design is complete.

**Estimate component costs:**

Once your spec is complete, run the cost analyzer to see pricing at multiple
quantity breaks:

```bash
circuit-weaver cost-bom design.yaml --qty 1,10,100,1000
```

This queries LCSC pricing tiers for all components and shows you unit and
extended costs per quantity level. Helps you identify price breakpoints and
decide your optimal production volume.

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

> **Enforcement (v0.27.0+):** Structural and implementation errors always
> block artifact emission, regardless of the `--no-require-valid` flag.
> `--no-require-valid` only relaxes soft electrical warnings (dangling dev
> signals, crystal load-cap tolerance, etc.); the bypass is logged so it's
> visible in `circuit-weaver.log`.

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

### Step 6 — Confidence & Simulation Check

**What happens:** The wizard automatically runs a comprehensive design readiness
check. This aggregates all available data — validation results, circuit
simulations, thermal analysis, cross-reference audit, and ERC — into a single
0-100 confidence score.

```bash
circuit-weaver confidence design.yaml --run-sims -o output/confidence_report.html
```

**What you get:**
- A confidence score (0-100) with letter grade (A-F)
- Readiness classification: `ready_for_fab`, `needs_review`, or `not_ready`
- Per-section breakdown (electrical, simulation, thermal, DFM, etc.)
- Prioritized action items if issues are found
- HTML dashboard for detailed review in a browser

**Why this matters:** This step catches problems that individual checks might
miss. A schematic can pass electrical validation but fail simulation (regulator
unstable), or pass simulation but have thermal issues (junction temp too high).
The confidence score gives you a single number to decide: should I proceed to
PCB layout or fix things first?

If the score is below 80, the wizard offers to loop back to fix action items.

---

### Step 7 — PCB Layout Preparation

**What happens:** The wizard prepares your PCB for routing with automated tools:

```bash
# Optimize component placement (simulated annealing)
circuit-weaver optimize-placement design.yaml -o output/placement.json

# Generate interactive HTML placement viewer
circuit-weaver placement-viewer design.yaml -o output/placement.html

# Optional: export editable SVG for visual placement in Inkscape
circuit-weaver generate design.yaml -o output/ --svg-placement

# Optional: autoroute non-critical nets (requires Freerouting).
# Note: run this on the real forward-annotated PCB, not the
# *_placement.kicad_pcb preview — the preview has no pads and the
# autoroute preflight rejects it.
circuit-weaver autoroute output/MyBoard.kicad_pcb -o output/MyBoard.ses

# DFM check against manufacturer rules
circuit-weaver check-dfm output/MyBoard.kicad_pcb
```

> **Note on `{project}_placement.kicad_pcb`:** as of v0.27.0 this file is a
> placement *preview* (its `(generator ...)` field reads
> `schematic_engine placement_preview`). It carries reference locations and
> board outline for layout review, but **real footprint pads come from KiCad's
> schematic → PCB forward annotation**, not from this file. If a component's
> footprint binding was missing at generation time the preview shows a
> `Placement_Preview:Missing_<ref>` placeholder — resolve those in the source
> YAML before fab.

**What you get:**
- Optimized component positions (thermal spacing, SI, DFM)
- Interactive HTML viewer with thermal heatmap and net highlighting
- Optional: SVG file editable in Inkscape, importable back to KiCad
- Optional: autorouted PCB (best for non-critical signal nets)
- DFM violation report against JLCPCB/PCBWay rules

---

### Step 8 — Final Review & Next Steps

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
(separate download from https://github.com/mirage335/freerouting/releases or
`brew install freerouting`), you can autoroute signal nets:

```bash
circuit-weaver autoroute output/MyBoard.kicad_pcb --effort high
```

The board must be a real forward-annotated PCB (Tools → Update PCB from
Schematic in KiCad) — the generated `*_placement.kicad_pcb` preview has no
pads and fails the routing preflight with a pointer to this step. With
`kicad-cli` installed the router uses the supported Specctra pipeline and
writes a `.ses` session you import via *File → Import → Specctra Session*.

Freerouting routes simple circuits 100% automatically and complex circuits
~90%. If you don't have Freerouting or prefer manual control, use KiCad's
interactive routing or the placer hints for guidance.

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

#### Prototype Enclosure Design

After you have a finalized PCB layout, you can generate a parametric OpenSCAD enclosure:

```bash
circuit-weaver design-enclosure \
  --board-width 100 \
  --board-height 80 \
  --component-height 15 \
  --wall-thickness 2.5 \
  --clearance 2 \
  -o enclosure.scad
```

The generator creates:
- **Parametric OpenSCAD code** — adjust dimensions by editing the top of the file, re-render instantly
- **Main body & lid** — snap-fit or screw-down assembly (customize in OpenSCAD)
- **Port cutouts** — USB, barrel jack, circular, or rectangular ports (add manually in OpenSCAD)
- **Mounting holes** — M3 screw bosses for PCB standoffs (configure as needed)
- **Optional vents** — for thermal management in enclosures with power dissipation

To render to STL for 3D printing:

```bash
circuit-weaver design-enclosure \
  --board-width 100 --board-height 80 \
  --render-stl --stl-output enclosure.stl
```

The OpenSCAD code is **fully parametric** — all dimensions are variables at the top of the file. Change `wall = 2.5` to `wall = 4.0`, re-render, and test fit in your slicer. See the [OpenSCAD skill](../skills/openscad/SKILL.md) for advanced customization (BOSL2 library, MOLLE mounting, heat-set inserts, etc.).

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
| Has reviewed schematics, no confidence score | Step 6 — Confidence & Simulation Check |
| Has confidence score, no PCB layout | Step 7 — PCB Layout Preparation |
| Has PCB layout, no manufacturing files | Step 8 — Final Review & Next Steps |

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
| `research/*.json` | Step 2 | Canonical saved research runs and citations | Yes |
| `research/summary.md` | Step 2 | Rolling index of all saved research runs | Yes |
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
| `openscad` | Parametric 3D modeling | Enclosure design, mechanical parts, mounts |
| `autoroute` | Freerouting PCB router | Automatic signal routing (optional; user installs JAR separately) |

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

---

## Advanced Workflows — Auto-Sourcing & Placement Editing

Once you have a working schematic, Circuit Weaver offers two powerful shortcuts:

### Auto-Source Components (Task 86)

Instead of hand-specifying part numbers for every component, Circuit Weaver can auto-discover
them from component values/footprints via DigiKey and Mouser APIs:

```bash
# Auto-discover and cache part numbers (30-day TTL)
circuit-weaver generate design.yaml -o /tmp/out --auto-source

# Also write discovered parts back to your YAML spec
circuit-weaver generate design.yaml -o /tmp/out --auto-source --update-spec
```

**What happens:**
1. For each component with a blank MPN, Circuit Weaver queries DigiKey, Mouser, and LCSC APIs
2. Results are cached locally for 30 days (no redundant API calls)
3. A summary is printed: "Auto-sourced 42/45 parts (DigiKey: 25, Mouser: 12, LCSC: 5)"
4. If `--update-spec` is set, discovered part numbers are written back to your YAML file

**When to use:** After your schematic is finalized and you're ready for a costed BOM.

### Edit Placement Visually (Task 93)

Instead of hand-moving every component in KiCad, export an SVG diagram that you can edit
in Inkscape or any vector tool, then import the edits back:

```bash
# Export placement diagram
circuit-weaver generate design.yaml -o /tmp/out --svg-placement
# → Creates /tmp/out/placement.svg

# User opens placement.svg in Inkscape and moves components around...

# Import edits back into KiCad
circuit-weaver import-placement /tmp/out/placement.svg /tmp/out/design.kicad_pcb
# → Updates design.kicad_pcb and *_cpl.csv automatically
```

**What you can do in the SVG:**
- Move components (drag rectangles)
- Rotate components (rotate rectangles)
- Change layer (front/back) — edit the `data-layer` attribute
- Use Inkscape's snap-to-grid for precision
- Version control the SVG (it's plain XML) for design review

**Component colors by category:**
- Red: power rails, regulators
- Blue: digital ICs
- Green: connectors
- Yellow: passives (resistors, capacitors)

**⚠️ SVG editing constraints for GIMP/Inkscape:**

The SVG round-trip (export → edit → import) is most reliable when using **standard SVG transforms**:
- **translate(x, y)** — move a component
- **rotate(angle)** — rotate a component  

Avoid:
- Matrix transforms like `matrix(a b c d e f)` — the importer may misinterpret rotation
- Complex shape edits (don't reshape the component rectangles)
- 3-argument rotate like `rotate(angle cx cy)` — we extract the angle only (center point ignored)

**In GIMP:** Use Move/Rotate tools (they output standard transforms). Avoid Effects → Distorts.

**In Inkscape:** Use Transform → Position/Size for moving and rotating. Be careful with Bézier edits—if you reshape component geometry, the importer may not recognize it.

**When to use:** After schematic generation, before sending to fab. Fast for adjusting
component spacing, swapping placement between board sides, or sharing layout feedback.

---

## FAQ — Auto-Source & Placement

**Q: Do I need API keys for auto-sourcing?**
A: No. If DigiKey/Mouser credentials are missing, the tool silently falls back to your local
LCSC database or leaves components unresolved. No errors.

**Q: How fresh are the cached parts?**
A: 30 days. After that, Circuit Weaver re-queries the APIs. You can clear the cache
manually with `circuit-weaver cache clear`.

**Q: Can I edit placement without exiting KiCad?**
A: Yes. Export SVG *before* opening the .kicad_pcb in KiCad, edit, import back, then
open in KiCad. This avoids conflicts with KiCad's in-memory copy.

**Q: What if I move a component off the board in the SVG?**
A: The coordinates are preserved as-is. Just don't go too negative or the component
will be off-canvas. Inkscape's bounds guides help prevent this.
