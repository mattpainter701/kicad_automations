---
name: autoroute
description: >
  PCB auto-routing workflow -- Freerouting (open-source) integration with KiCad,
  interactive router tips, design rule prep, and post-route cleanup checklist.
  Use after component placement to route a board automatically or semi-automatically.
---

# PCB Auto-Routing Skill

## When to Use Autorouting

### Freerouting vs KiCad Interactive Router vs Manual

| Method | Best for | Avoid when |
|-|-|-|
| Freerouting (autorouter) | General digital I/O, non-critical signal nets, high net count boards | Any impedance-controlled or differential signal |
| KiCad interactive router | Guided routing with DRC enforcement, semi-manual cleanup | Hundreds of nets (too slow) |
| Manual routing | All critical signals — see table below | Bulk single-ended digital nets |

**Decision rule:** Route critical signals manually first, then hand the remaining nets to Freerouting. A board where 20% of nets are critical and 80% are general digital can use Freerouting productively for the 80%.

### Signals That Should NEVER Be Autorouted

| Signal type | Reason | Correct method |
|-|-|-|
| Differential pairs (USB, LVDS, Ethernet, HDMI, PCIe) | Requires precise length matching and controlled impedance; autorouter cannot guarantee pair skew within spec | KiCad differential pair router with interactive length tuning |
| Crystal oscillator traces | Must be short, have minimal parasitic capacitance, and often need a guard ring; length and topology matter | Manual — route crystal as close to IC as possible, keep symmetric |
| RF traces (antenna feed, LNA input/output, matching networks) | Controlled impedance (typically 50 Ω); trace width calculated from stackup; any detour changes characteristic impedance | Manual — calculate width from stackup, route directly |
| Power rails and planes | Current capacity determines trace width (IPC-2221); wide traces or filled zones needed | Manual or copper pour — set by IPC-2221 current tables |
| High-current switching node (buck/boost) | Minimizing loop area is critical for EMC; autorouter maximizes completion, not loop area | Manual — identify the critical switching loop and route it first |
| Decoupling capacitor bypass paths | Must be the shortest physical path between IC power pin and decoupling cap | Manual — place cap before routing, connect before autorouting runs |
| DDR/LPDDR address and data buses | Fly-by topology, length matching within byte lanes, Vref routing | Manual with KiCad length tuning |
| Clock distribution networks | Star topology or matched-length tree; autorouter uses shortest path, not matched path | Manual with KiCad length tuning |

### When Autorouting Is Appropriate

- General-purpose digital I/O lines (GPIO, SPI, I2C on a microcontroller header)
- LED drive lines and indicator signals
- UART, I2C, SPI at low frequencies where trace length is not critical
- Non-matched address lines on parallel buses where the MCU has sufficient setup/hold margin
- Passive component interconnects (resistor networks, filter arrays)
- Test point connections
- Boards under 4 layers where you want a routing draft to identify congestion before routing manually

---

## Pre-Route Checklist

Work through every item before starting the router. Skipping steps causes incomplete routes or DRC violations that are expensive to fix after routing.

**Net class assignment:**
- Every net must belong to a named net class with correct trace width and clearance.
- Default net class catches unassigned nets — verify its width is acceptable for your fab tier.
- Power nets must be in a net class with widths sized by IPC-2221 for worst-case current.
- Differential pairs should be in a net class matching their impedance target width.
- Net classes set in KiCad: PCB Editor → Board Setup → Design Rules → Net Classes.

**Design rule import:**
- Import the fab's `.kicad_dru` constraint file before routing.
- JLCPCB standard: min trace 0.127mm, min clearance 0.127mm, min via drill 0.2mm, min via pad 0.45mm.
- JLCPCB advanced: min trace 0.09mm, min clearance 0.09mm, min via drill 0.15mm.
- PCBWay standard: min trace 0.1mm, min clearance 0.1mm, min via drill 0.15mm.
- Import: PCB Editor → Board Setup → Design Rules → Import Settings → select `.kicad_dru`.

**Component placement:**
- All components placed and locked (`E` on component → Lock).
- Locked footprints cannot be moved by the router's fanout pass.
- Confirm courtyard overlaps = 0 before routing (DRC → Courtyard).

**Board outline:**
- Edge.Cuts layer must form a single closed polygon.
- Gaps in the board outline prevent DSN export from Freerouting.
- Verify: PCB Editor → Inspect → Board Statistics confirms a valid outline.

**Copper pours disabled:**
- Unfilled zones do not participate in routing but slow down DRC.
- Remove all zone fills before starting: Edit → Unfill All Zones (shortcut `B` fills, unfill is under Edit menu or use `Ctrl+B`).
- Re-enable and refill after routing is complete.

**Ratsnest verification:**
- The ratsnest (airwires) shows all unconnected net endpoints.
- Before routing, the airwire count should match the number of logical connections minus any deliberate no-connects.
- Zero DRC "unconnected items" errors after a fresh netlist push confirms the netlist is clean.
- Push netlist from schematic: PCB Editor → Tools → Update PCB from Schematic.

**Teardrops:**
- Remove any existing teardrops before routing (they interfere with the autorouter).
- Re-add after routing: Edit → Add Teardrops.

---

## Freerouting — Setup

**Download:**
```
https://github.com/freerouting/freerouting/releases
```
Download `freerouting-X.Y.Z-executable.jar`. No installer needed.

**Java requirement:**
- Requires Java 11 or later.
- Verify: `java -version`
- Install OpenJDK 17 (LTS) if not present: `winget install Microsoft.OpenJDK.17` (Windows) or `sudo apt install openjdk-17-jre` (Linux/WSL).

**Two modes:**

| Mode | Use when |
|-|-|
| GUI | Interactive exploration, watching routing in progress, manual intervention between passes |
| CLI | Scripted pipelines, batch routing, headless environments, CI integration |

**GUI launch:**
```bash
java -jar freerouting.jar
```
Open DSN file from within the GUI, start autorouter from the menu.

---

## Freerouting — DSN Export from KiCad

```
KiCad PCB Editor → File → Export → Specctra DSN (.dsn)
Save as: design.dsn (same directory as .kicad_pcb recommended)
```

**What exports correctly:**
- All net assignments and ratsnest connections
- Net class trace widths and clearances
- Via rules (drill size, pad size) from Board Setup
- Layer stack with copper layer names
- Board outline from Edge.Cuts

**What does NOT export:**
- Teardrops (add after import)
- Zone fills (Freerouting treats zones as obstacles)
- Differential pair constraints — pairs route as independent nets in Freerouting
- Length tuning constraints

**Common export failures:**

| Symptom | Cause | Fix |
|-|-|-|
| DSN export fails or produces empty outline | Edge.Cuts is not a closed polygon | Close the polygon — use PCB Editor → Edit → Close Polygon if available, or trace the gap visually |
| Freerouting reports "no design rules" | Net class widths not set | Set width/clearance in Board Setup → Net Classes before export |
| Some nets missing from DSN | Components not associated with netlist | Re-run Update PCB from Schematic |

---

## Freerouting — CLI Routing

```bash
# Minimal autoroute
java -jar freerouting.jar -de design.dsn -do design.ses -mp 100

# Fanout pass first (recommended for BGA and QFN escape routing)
java -jar freerouting.jar -de design.dsn -do design.ses -mp 100 -fo

# More passes for dense boards
java -jar freerouting.jar -de design.dsn -do design.ses -mp 200 -mt 4

# Save intermediate result every 10 passes (safe for long runs)
java -jar freerouting.jar -de design.dsn -do design.ses -mp 100 -is 10

# Import external design rules file
java -jar freerouting.jar -de design.dsn -do design.ses -mp 100 -dr design.rules

# Quick test pass (verify DSN is valid before long run)
java -jar freerouting.jar -de design.dsn -do design.ses -mp 10
```

**Key flags reference:**

| Flag | Argument | Description |
|-|-|-|
| `-de` | path | Input DSN file |
| `-do` | path | Output SES file (Specctra Session) |
| `-mp` | integer | Maximum routing passes. Start with 50 for a test, 100-200 for production |
| `-fo` | — | Fanout pass: escapes BGA/QFN pads to vias before main routing. Always use for fine-pitch ICs |
| `-mt` | integer | Multi-threaded routing passes. Set to CPU core count for speed |
| `-is` | integer | Save intermediate SES every N passes. Useful if routing a large board overnight |
| `-dr` | path | External design rules file |
| `-da` | — | Disable auto-routing (use with GUI to only show ratsnest) |

**Pass count guidance:**

| Board complexity | Recommended passes |
|-|-|
| Simple (< 50 nets, 2 layers) | 50 |
| Medium (50-200 nets, 2-4 layers) | 100 |
| Complex (200+ nets, 4+ layers) | 200+ |
| Dense BGA/high layer count | 500+ or until completion plateaus |

Routing completion typically plateaus — if pass 150 and pass 200 show the same unrouted count, more passes will not help. Resolve DRC violations manually and re-run.

---

## Freerouting — SES Import Back to KiCad

```
KiCad PCB Editor → File → Import → Specctra Session (.ses)
Select: design.ses
```

After import:
1. KiCad immediately re-runs DRC — review all violations before proceeding.
2. Via sizes in the SES are applied — verify they match your fab's minimum annular ring requirements.
3. All track segments from the autorouter are on signal layers as specified in the DSN.
4. Teardrops are not generated by Freerouting — add manually (see Post-Route Cleanup).
5. Copper pours are still unfilled — refill after DRC is clean.

**If SES import fails:**
- Verify the SES file is not empty (Freerouting crashed mid-run).
- Check that the DSN was exported from the same board revision currently open.
- Re-export DSN and re-run if the board was modified after DSN export.

---

## KiCad Interactive Router Tips

The KiCad interactive router is the right tool for routing critical signals manually or cleaning up after Freerouting.

**Essential keyboard shortcuts:**

| Key | Action |
|-|-|
| `X` | Start routing a trace from a pad or track end |
| `Escape` | Abandon current trace (nothing is placed) |
| `V` | Place a via and continue routing on the other layer |
| `W` | Cycle trace width (through your net class widths) |
| `/` | Toggle between 45° and 90° corner mode (prefer 45° for signal integrity) |
| `U` | Expand selection along a connected track |
| `` ` `` (backtick) | Highlight a net — shows ratsnest for that net only |
| `I` | Inspect the properties of the selected item |
| `E` | Edit the properties of the selected item |
| `D` | Interactive drag — moves a segment while maintaining connections |
| `G` | Interactive grab — adjust a segment without breaking connections |

**Router mode selection:**
- PCB Editor → Interactive Router Settings (right-click or Route menu)
- **Walk Around:** Avoids obstacles without moving them. Safest, preserves existing routing.
- **Shove:** Moves existing tracks to make room. Aggressive — use carefully.
- **Free Angle (45°):** Standard for most routing. Keeps traces on 45°/90° angles.

**Differential pair routing:**
- Route → Route Differential Pair
- Select one net of the pair — KiCad auto-pairs by suffix convention (net `CLK_P` / `CLK_N`, `USB_DP` / `USB_DM`)
- Set gap from the net class differential pair gap setting
- Use Route → Interactive Router Settings → Differential Pairs for gap/width

**Length tuning:**
- Route → Tune Trace Length (single-ended) or Tune Differential Pair Length
- Set target length from timing constraints
- KiCad adds meanders to match length

---

## Net Class Setup

Net classes must be configured before exporting DSN. The autorouter uses them directly. Set in PCB Editor → Board Setup → Design Rules → Net Classes.

**Example net class table — adapt to your fab tier and design:**

| Net class | Width | Clearance | Via drill | Via pad | Nets |
|-|-|-|-|-|-|
| Default | 0.2mm | 0.2mm | 0.3mm | 0.6mm | General signal nets |
| Power_1A | 0.5mm | 0.3mm | 0.4mm | 0.8mm | VCC_3V3, VCC_1V8, GND |
| Power_3A | 1.5mm | 0.5mm | 0.6mm | 1.0mm | VIN, VBUS, main power input |
| USB | 0.2mm | 0.2mm | 0.3mm | 0.6mm | USB_DP, USB_DM |
| Clock | 0.15mm | 0.3mm | 0.3mm | 0.6mm | MCLK, SCLK, REFCLK |
| HighSpeed | 0.2mm | 0.25mm | 0.3mm | 0.6mm | DDR data, LVDS pairs |

**Via sizing rule of thumb for JLCPCB:**
- Standard tier: drill 0.3mm minimum, pad 0.6mm minimum (0.15mm annular ring)
- Advanced tier: drill 0.2mm minimum, pad 0.45mm minimum

**Width calculation for power traces (IPC-2221A):**
```
External layer (1 oz copper):
  Width (mm) = (I / (0.048 × ΔT^0.44))^(1/0.725) / 25.4 × (1/oz_factor)
  oz_factor: 1 oz = 1.0, 2 oz = 0.5

Quick reference (1 oz, 10°C rise, external):
  0.5mm → ~1.0A
  1.0mm → ~2.5A
  1.5mm → ~4.0A
  2.0mm → ~5.5A
  3.0mm → ~8.5A
```

---

## Signals to Route Manually (Never Autoroute)

Route these before running Freerouting. The order matters — manually route, lock the traces, then run the autorouter on remaining nets.

| Signal type | Why manual | Routing guidance |
|-|-|-|
| Differential pairs (USB 2.0 DP/DM) | 90 Ω differential impedance; pair skew < 100 ps (USB 2.0 HS spec) | Use KiCad diff pair router; keep gap constant; match lengths to within 0.1mm |
| Differential pairs (LVDS, Ethernet 100BaseTX) | 100 Ω differential impedance; crosstalk isolation from adjacent signals | Surround with ground guard traces; 3W spacing rule to other signals |
| Crystal oscillator (XO/TCXO) | Trace capacitance adds to load capacitance; affects oscillation frequency | Shortest possible traces; no vias; copper pour keepout under traces; guard ring to ground |
| RF antenna feed line | 50 Ω characteristic impedance; any length change affects matching network | Calculate width from stackup (microstrip formula); route directly; minimize bends |
| High-current power (> 1A continuous) | Trace width from IPC-2221; wide traces needed for thermal headroom | Set trace width in net class; route manually to ensure minimum via count; consider copper pour instead |
| Buck/boost switching node (LX/SW) | Switching loop area is the primary EMC radiator; minimize loop area | Identify the critical loop (switch FET → inductor → output cap → return); route it as a tight polygon |
| DDR data bus (DQ, DQS, CLK) | Byte lane length matching within 25 ps; fly-by topology required | Route as a group with KiCad length tuning; match within byte lanes first, then across lanes |
| Decoupling bypass path | Must be the lowest inductance path from IC VCC pin to cap pad | Place cap first (must be closest component to power pin), then manually connect; this is typically a 1-2mm trace |
| Impedance-controlled single-ended | Any trace where source termination, stub length, or propagation delay is constrained | Calculate width from stackup, route manually, use length tuning if needed |

**Workflow for mixed manual/autorouted designs:**
1. Route all manually-required signals.
2. Lock those traces: select all → Right-click → Lock.
3. Export DSN — locked traces export as fixed routes, Freerouting will not touch them.
4. Run Freerouting on remaining nets.
5. Import SES, verify locked traces are intact.

---

## Post-Route Cleanup

After SES import, work through this checklist before considering routing complete.

**1. DRC — resolve all violations**
- PCB Editor → Inspect → Design Rules Checker → Run DRC
- Zero violations required before proceeding.
- Common post-import violations: clearance violations on tight sections where Freerouting placed a via too close to a pad; via-in-pad on SMD footprints.

**2. Teardrops**
- KiCad 7+: Edit → Add Teardrops
- Add to all vias and all SMD pads.
- Teardrops reduce mechanical stress at pad-to-trace transitions and improve etching reliability.

**3. Via optimization**
- Inspect routing for unnecessary layer changes (a trace that goes F.Cu → B.Cu → F.Cu with no reason).
- Delete redundant via pairs and reroute the segment to stay on one layer.
- Use `U` to select connected segments and evaluate the full routing path.

**4. Copper pours — refill all zones**
- PCB Editor → Edit → Fill All Zones (shortcut `B`)
- Ground pour fills first, then power pours.
- After fill, run DRC again — copper pours can create new clearance violations.
- Verify no "isolated copper area" DRC warnings on GND pour (these are slivers with no connection to the main pour).

**5. Silkscreen review**
- After routing, copper fills change the available clearance.
- PCB Editor → Inspect → Design Rules Checker → enable "Silkscreen" checks.
- Move any silkscreen text that overlaps copper, pads, or vias.

**6. Courtyard check**
- DRC → Courtyard → 0 violations required.
- If routing added vias that intrude into a courtyard, move the via or adjust the courtyard.

**7. Trace stubs**
- The autorouter occasionally leaves very short stub traces (< 0.5mm) from aborted routing attempts.
- Select → Inspect → Net Inspector → filter for zero-length or very short segments.
- Delete stubs: right-click segment → Select → Select Connected Tracks → Delete if appropriate.

**8. Differential pair length matching**
- Inspect → Net Inspector — search for diff pair nets.
- Check reported lengths. Skew target: USB 2.0 HS < 100 ps (≈ 14mm in FR4); Ethernet 100BaseTX < 250 ps (≈ 35mm).
- If skew exceeds target, use Route → Tune Differential Pair Length to add meanders.

**9. High-speed return paths**
- Visually inspect all clock, USB, DDR, and RF signal traces.
- Confirm the trace does not cross a slot, split plane, or pour boundary on the reference plane layer directly beneath it.
- Splits in the ground plane directly under a high-speed trace force return current around the gap, creating a large loop antenna.
- Fix: add stitching vias to bridge across splits near the trace; avoid routing over splits.

**10. Ground stitching vias**
- Add stitching vias around the board perimeter and between copper pour islands.
- Rule of thumb: stitch every λ/20 at the highest signal frequency. At 100 MHz this is 150mm; at 1 GHz this is 15mm.
- Place stitching vias at corners, near connectors, and near any slot or cutout.

---

## Routing Quality Metrics

| Metric | Target | How to check |
|-|-|-|
| Routing completion | 100% | Inspect → Board Statistics → Unrouted count = 0 |
| DRC violations | 0 | Run DRC → no errors |
| Via count | Minimize (quality indicator) | Inspect → Board Statistics |
| Longest unmatched differential pair | < 0.1mm (within spec for pair) | Inspect → Net Inspector → compare paired net lengths |
| Ground plane coverage (inner) | > 70% of board area | Visual + copper pour fill ratio |
| Decoupling cap distance to IC power pin | < 2mm (ideally < 1mm) | Visual inspection |
| Trace stubs | 0 | DRC + visual |

---

## Common Freerouting Issues

**Board outline not closed:**
DSN export succeeds but Freerouting reports no board boundary or routes outside the board. Fix: select all segments on Edge.Cuts layer, use PCB Editor → Edit → Close Polygon, or manually find and connect the gap.

**Routing completion plateaus before 100%:**
More passes will not help once the pass-over-pass improvement drops to zero. The remaining unrouted nets are blocked by geometry or design rule constraints. Options: (1) resolve DRC violations from partial routing, then re-export and re-run; (2) manually route the remaining nets; (3) increase layer count or reduce component density.

**Vias too small after SES import:**
Freerouting created vias smaller than the fab minimum. Cause: net class via sizes not exported correctly. Fix: verify Board Setup → Net Classes → Via Diameter and Via Drill are set (not left as "from design rules"), re-export DSN, re-run.

**SES import creates wrong layer assignments:**
A trace intended for F.Cu appears on B.Cu. Cause: layer name mismatch between KiCad and Freerouting DSN. Fix: check the DSN file layer names match KiCad's layer names exactly (KiCad uses `F.Cu`, `B.Cu`, `In1.Cu`, etc.).

**Slow routing on Windows:**
Java garbage collection pauses. Set JVM heap: `java -Xmx2g -jar freerouting.jar ...`. Also ensure `-mt` matches your CPU thread count.

**Fanout pass places vias in pads (via-in-pad):**
Some fab tiers do not allow via-in-pad (JLCPCB requires copper tenting for via-in-pad at standard tier). If the fanout pass places vias directly on SMD pads, disable `-fo` and place escape vias manually before running the main routing pass.

**Net class violations in SES:**
Freerouting does not always respect net class clearance rules for all net combinations. After import, run DRC with "Clearance" and "Short circuit" checks enabled. Manually fix any clearance violations.

---

## Integration with KiCad Skills

| Workflow step | Skill |
|-|-|
| Assign MPNs to components before placement | `bom` |
| Verify net class assignments match design intent | `kicad_validate` |
| Run DRC after SES import | `kicad` (analyze_pcb.py) |
| Calculate trace widths for power nets | `ee` (IPC-2221 current capacity tables) |
| Verify controlled impedance trace width from stackup | `ee` (microstrip formula) |
| Check via current capacity | `ee` (via current capacity guidelines) |
| Export BOM and CPL after routing is complete | `bom` |
| Prepare gerbers for JLCPCB | `jlcpcb` |
| Prepare gerbers for PCBWay | `pcbway` |

## Changelog
- 2026-03-27: Created skill — Freerouting CLI/GUI, DSN export/SES import, interactive router tips, net class setup, manual routing signal table, post-route cleanup checklist, common issues
