# Design Review Report Generation

Guide for producing comprehensive design review reports from analyzer output + raw file cross-referencing. These reports help EE designers validate their designs before committing to fabrication.

## Contents

| Section | Line | Purpose |
|---------|------|---------|
| Report Structure | ~18 | Full report template (copy and fill in) |
| Analyzer Output Field Reference | ~248 | Maps every JSON output field to its report section — use as checklist |
| Severity Definitions | ~350 | CRITICAL / WARNING / SUGGESTION criteria |
| Writing Principles | ~358 | How to write actionable findings |
| Handling Different Design Domains | ~391 | Domain-specific focus areas (IoT, motor, RF, analog, industrial) |
| Cross-Referencing with Raw Schematic | ~408 | Mandatory verification steps |
| Known Analyzer Limitations | ~418 | What the tool can and can't catch |
| Report Length Guidelines | ~445 | Target report sizes by complexity |

## Report Structure

Use this template. Include sections that are relevant to the design — skip sections that genuinely don't apply (a battery-powered sensor board doesn't need an isolation barrier section). For sections where the analyzer returned empty data, briefly assess whether that's expected ("no mains input, creepage N/A") or a gap worth noting ("no ESD protection detected on external USB connector").

```markdown
# [Project Name] Design Review

**Project:** [name] ([KiCad version], [single sheet | N hierarchical sheets], [N-layer PCB | no PCB])
**Date:** [analysis date]
**Analyzers:** [list scripts run: analyze_schematic.py, analyze_pcb.py, analyze_gerbers.py] ([modern/legacy format], [full signal analysis | legacy mode])

## Overview
[2-4 sentence description of the board: MCU, power architecture, key peripherals, domain (IoT/motor control/RF/instrumentation/etc.), form factor context]

## Critical Findings
[**This section comes first** so the designer sees the most important issues immediately. Move here after completing the full analysis.]

| Severity | Issue | Section |
|----------|-------|---------|
| CRITICAL | [Board won't function, safety hazard, or fabrication failure] | [link to section with details] |
| WARNING  | [Suboptimal but board may work, potential reliability issue] | [link to section with details] |

[Only CRITICAL and WARNING items here. SUGGESTION-level items go in the Issues Found section later. If no CRITICAL or WARNING issues: "No critical or warning-level issues found." — this itself is a valuable finding.]

## Component Summary
[Table: Type | Count, broken down by resistors, capacitors, ICs, connectors, etc.]
[One-line stats: Nets, Wires, No-connects, Power rails, Sheets]
[Sourcing audit: MPN coverage %, missing distributor part numbers — do not recommend any specific distributor by name]

## Power Tree
[ASCII art showing the power distribution hierarchy]
[Include: input source, each regulator with type (LDO/buck/boost/inverting), input->output voltages, enable conditions, key caps with values, feedback divider calculations]
[Note vref_source for each regulator: "lookup" (datasheet-verified) or "heuristic" (needs manual verification)]

## Analyzer Verification
[Spot-checks proving the analyzer data is trustworthy]
### Component Count — [N/N match status]
### Component Pinout Verification — [Table: ALL components verified against raw schematic + datasheets: Ref | Value | lib_id | Footprint | Pin Count | All Pins Verified | Datasheet Cross-checked | Match. Every component must be checked — not just ICs. Include connectors, transistors, diodes, and critical passives.]
### Pinout Ambiguity & Plausibility — [Components where the symbol's pin assignment depends on the specific MPN. Table: Ref | lib_id | Footprint | MPN | Assumed Pinout | Datasheet Pinout | Plausibility | Status. When verification is possible (MPN + datasheet), verify directly. When it isn't, assess plausibility: does the assumed pinout match the dominant convention for this device type and package? Report confidence: "matches most common convention," "plausible but multiple variants exist," or "unusual — most parts in this category use a different pinout." Flag CRITICAL when no MPN is specified AND the assumed pinout is uncommon or genuinely ambiguous.]
### Net Tracing — [All power rails + critical signal nets traced end-to-end: list all pins, verify connectivity, confirm correctness]
### PCB Verification — [If PCB analyzed: footprint count match, pad-net spot-check, board dimensions confirmed]
### Gerber Verification — [If gerbers analyzed: layer completeness, drill count, alignment check]

## Signal Analysis Review
[Walk through each detected subcircuit category, validate calculations, note any false positives]

### Power Regulators
[Each regulator: topology (LDO/buck/boost/inverting), input/output rails, Vout estimate, vref_source (lookup vs heuristic), vout_net_mismatch flag. Verify heuristic Vref values against datasheets.]

### Voltage Dividers & Feedback Networks
[Table: R_top | R_bottom | Ratio | Output voltage | Purpose | Verified status. For feedback dividers: Vref verification against datasheet lookup table. Flag any vout_net_mismatch where estimated Vout differs >15% from the output rail name voltage.]

### RC/LC Filters
[Cutoff frequencies, filter type (low-pass/high-pass), component values, purpose, verified status]

### Op-Amp Circuits
[Configuration (inverting/non-inverting/buffer/differential), gain from Rf/Ri, topology identification accuracy]

### Protection Devices
[ESD, TVS, varistors — placement coverage on external connectors, voltage ratings vs rail voltages]

### LED Circuits
[For each LED: verify current limiting resistor value provides correct forward current. Calculate: I_LED = (V_supply - V_f) / R_limit. Check against LED datasheet for typical V_f, V_f tolerance range, and maximum current rating. Flag cases where current margin is tight (operating near max or where V_f variation could push current out of spec). Consider supply voltage tolerance as well.]

### Transistor Circuits
[Type (N-ch/P-ch MOSFET, NPN/PNP BJT), load type classification (inductive/led/resistive/motor/heater/fan/solenoid/connector), gate/base drive analysis, protection (flyback diode, snubber)]

### Bridge Circuits
[Topology (half_bridge/h_bridge/three_phase), FET references, output nets, gate driver ICs. Note: cross-sheet bridge detection works through unified hierarchical nets.]

### Crystal Circuits
[Load cap analysis, frequency, Cload vs recommended values]

### Current Sense
[Shunt values, sense amplifier, measurement range]

### Decoupling Analysis
[Table: Rail | Cap Count | Total uF | Bulk | Bypass — one row per rail. Flag rails with inadequate decoupling.]

### Buzzer/Speaker Circuits
[Driver topology, frequency if applicable]

### Domain-Specific Detections
[Include subsections only when detected:]
- **RF Chains** — component chain, frequency bands, switch matrix
- **BMS Systems** — cell count, balance topology, protection
- **Ethernet Interfaces** — magnetics, PHY, termination
- **Memory Interfaces** — type, data bus width, address lines
- **Key Matrices** — row/column count, diode matrix
- **Isolation Barriers** — isolation voltage, optocoupler/digital isolator

### Design Observations
[Automated observations from the analyzer: decoupling coverage, I2C pull-ups, crystal load caps, regulator details, etc. Validate each against the raw schematic.]

## Power Analysis

### PDN Impedance
[Per-rail impedance profile (1kHz–1GHz), key impedance points, anti-resonances, SRF gaps, MLCC parasitic modeling]

### Power Budget
[Per-rail load estimates vs regulator capacity, flag any overloaded rails, regulator headroom]

### Power Sequencing
[Enable chains (EN/PG dependencies), startup order, missing PG feedback]

### Sleep Current Audit
[Per-rail estimated sleep current, dominant leakage paths (pull-up/pull-down resistors), regulator Iq estimates with EN pin detection. Note: worst-case model — real sleep current typically 5-20x lower.]

### Inrush Analysis
[Power-on current analysis — not limited to regulators. Consider ALL current paths at power-on:]
- Per-regulator inrush (input capacitance, soft-start adequacy)
- IC supply pin absolute maximum ratings vs capacitor charging current (e.g., 74HC-series ±50mA VCC/GND limit, small MCUs with low abs max supply current)
- Bulk/decoupling capacitor charging through connectors (hot-plug scenarios produce fast voltage steps → high dI/dt)
- Source impedance: connector resistance, wire gauge, trace resistance — these limit peak inrush naturally
- Series resistance or soft-start mechanisms (or lack thereof)
- Multiple rails energizing simultaneously (total system inrush vs supply capability)
[Even designs with no regulators need this section — external supply rails still charge decoupling caps through IC supply pins at power-on. Check each IC's datasheet for absolute maximum continuous current through VCC/GND pins.]

### Voltage Derating
[Component voltage ratings vs applied voltages, capacitor derating at operating voltage]

## Standards Compliance
[Include when applicable — see `references/standards-compliance.md` for auto-trigger conditions and tables. Consider for all boards: even low-voltage designs benefit from a brief conductor spacing and current capacity check. For mains-connected or safety-isolated designs, this section is mandatory.]

### Product Classification
[Class 1/2/3 determination with rationale from BOM indicators]

### Conductor Spacing (IPC-2221A Table 6-1)
[High-voltage net pairs with required vs actual spacing. Skip for designs where all nets are ≤15V and traces meet minimums.]

### Current Capacity (IPC-2221A / IPC-2152)
[Power traces: expected current, trace width, copper weight, calculated capacity, margin. Flag <50% margin as WARNING, <20% as CRITICAL.]

### Creepage/Clearance (ECMA-287 / IEC 60664-1)
[Only for mains-connected or safety-isolated designs. Working voltage, OVC, pollution degree, material group, required vs actual distances.]

### Annular Ring (IPC-2221A Table 9-2)
[Via annular ring analysis, fab capability vs IPC minimums]

### Via Protection (IPC-4761)
[Only for via-in-pad designs: protection type, BGA/QFN thermal pad vias]

## Design Analysis

### Net Classification
[Power/ground/high_speed/data/analog/control/chip_select/interrupt/output_drive/debug/config/signal categorization. Verify output_drive nets (motor, heater, fan, solenoid, relay, lamp, LED, PWM, buzzer).]

### Cross-Domain Signals
[Signals crossing voltage domains, level shifter assessment. Uses voltage equivalence from rail name parsing to reduce false positives. Rails without parseable voltages may trigger false warnings.]

### ERC Warnings
[Total count, categorize: genuine issues vs benign/false positives. Covers: multi-driver nets, unconnected power pins, pin type conflicts.]

### Bus Topology
[I2C detection (SDA/SCL + pull-ups), SPI (SCK/MOSI/MISO/COPI/CIPO/SDI/SDO/CS), UART (TX/RX), CAN bus grouping accuracy]

### Differential Pairs
[Suffix-pair detection for USB (D+/D-), LVDS, Ethernet (TX+/TX-), HDMI, MIPI, PCIe, SATA, CAN, RS-485. Protocol guessing from net name keywords.]

### Connectivity Issues
[Unconnected pins, single-pin nets, multi-driver conflicts, power net summary]

### Label/Annotation Warnings
[Label shape warnings (input/output direction), PWR_FLAG coverage, annotation gaps, hierarchical label validation]

### Passive Warnings
[Unusual passive values, tolerance concerns]

### Footprint Filter Warnings
[Custom library vs standard filter mismatches]

## PCB Layout Analysis
[Include when a .kicad_pcb file was analyzed — skip for schematic-only reviews]

### Board Overview
[Dimensions, layer count (from tracks + vias + zones), copper layer names, stackup summary from .kicad_pro, board thickness]

### Footprint Placement
[Front/back side counts, SMD/THT ratio, placement density, courtyard overlaps, edge clearance warnings]

### Via Analysis
[Type breakdown (through/blind/micro), size distribution, annular ring checks, via-in-pad detection, BGA/QFN fanout patterns, current capacity, stitching via identification, tenting assessment]

### Trace Routing
[Per-net trace lengths, width distribution, layer distribution, power trace widths vs current requirements (IPC-2221)]

### Signal Integrity
[Layer transitions per net, ground return path assessment, trace proximity/crosstalk (with --proximity flag)]

### Power & Ground
[Power net routing summary (width, length, current capacity), ground domain identification (AGND/DGND/PGND), zone stitching via density]

### Thermal Analysis
[Thermal pad detection, via counting and adequacy for QFN/DFN packages, zone stitching density, thermal relief settings, tombstoning risk assessment (0201/0402 thermal asymmetry)]

### Copper Presence
[Zone copper at component pad locations — from `copper_presence` section. Focus on `no_opposite_layer_copper` list: which components lack zone copper on the opposite layer? Verify this is intentional for capacitive touch pads and antennas (need isolation) vs unexpected for other components (might indicate a zone gap). Also note `same_layer_foreign_zones` — pads sitting on zones they're not connected to, which is normal for tightly-packed power island zones but worth flagging if unexpected.]

### Decoupling Placement
[Cap-to-IC distances for critical components, flag caps too far from IC power pins]

### Current Capacity
[Per-net trace/via current capacity vs estimated load, narrow signal net warnings]

### DFM Assessment
[JLCPCB standard/advanced tier determination, DFM metrics (min trace width, min clearance, min drill, min annular ring), violation list]

### Silkscreen
[Board text count, reference designator visibility, documentation warnings, values on silk]

### Connectivity
[Routing completeness, unrouted net count and list]

## Schematic ↔ PCB Cross-Reference
[Include when both schematic and PCB were analyzed — this catches the most dangerous bugs]
### Component Count Match — [Schematic (excl. power symbols) vs PCB footprint count]
### Pin-Net Verification — [ALL components: schematic pin mapping vs PCB pad mapping. Table: Ref | Pins | All Match | Mismatches. Do not sample — verify every component including connectors, transistors, diodes.]
### Footprint Match — [Schematic Footprint property vs actual PCB footprint]
### Value/MPN Consistency — [Spot-check values and MPNs between schematic and PCB]
### DNP Consistency — [Components marked DNP in schematic should not have routing on PCB]

## Gerber Analysis
[Include when gerber directory was analyzed]
### Layer Completeness — [Found vs missing required/recommended layers, source identification]
### Drill Classification — [Via count, component holes, mounting holes, classification method]
### Alignment Verification — [Layer alignment check, extent comparison]
### Pad Summary — [SMD vs THT aperture counts, via apertures, heatsink apertures]
### Board Dimensions — [From gerber extents, compare against PCB if both analyzed]

## Interface Summary
[One-line summary of each external interface: connector type, protection, protocol, pin mapping]
[Examples: USB-C (ESD: yes, CC: 5.1kΩ), SWD (J1, no ESD), CAN (120Ω term, PESD2CAN)]

## Quality & Manufacturing

### Assembly Complexity
[Score, SMD/THT ratio, difficulty breakdown (fine-pitch, BGA, QFN), dominant package, unique footprint count]

### Sourcing Audit
[MPN coverage %, missing MPNs list, missing distributor part numbers. Do not recommend or prefer any specific distributor by name — keep sourcing observations neutral.]

### BOM Optimization
[Unique passive value counts per type, total unique footprints, single-use passive values, consolidation opportunities]

### Test Coverage
[Test points found and nets covered, debug connectors, uncovered critical nets]

### USB Compliance
[If applicable: connector type, ESD protection, CC resistors, VBUS protection, D+/D- impedance]

### Simulation Readiness
[Components likely simulatable vs needing SPICE models, coverage percentage]

## All Issues & Suggestions
[Complete list of all findings. CRITICAL and WARNING items were already shown in the Critical Findings section at the top — repeat them here with full detail and context. SUGGESTION items appear here only.]

| Severity | Issue | Detail |
|----------|-------|--------|
| CRITICAL | [Board won't function, safety hazard, or fabrication failure] | [Full explanation, datasheet citation, affected components] |
| WARNING  | [Suboptimal but board may work, potential reliability issue] | [Full explanation, recommendation] |
| SUGGESTION | [Improvements, best practices, documentation gaps] | [Rationale, optional fix] |

## Positive Findings
[Numbered list of things the design does well — builds designer confidence and validates good practices]

## Analyzer Gaps
[Numbered list of things the analyzer missed, got wrong, or couldn't detect — transparency about tool limitations]
```

## Analyzer Output Field Reference

Quick reference for what each analyzer produces, to ensure no analysis dimension is missed in the report.

### Schematic Analyzer (`analyze_schematic.py`)

| Output Section | Report Section | Key Fields |
|---|---|---|
| `statistics` | Component Summary | component_types, power_rails, missing_mpn |
| `bom` | Component Summary, BOM Optimization | deduplicated parts with quantities |
| `components` | IC Spot-Check, throughout | full component details with pin_uuids, parsed_value |
| `nets` | Net Tracing, throughout | per-net pin lists with pin_type |
| `subcircuits` | Power Tree | auto-detected power/signal subcircuits |
| `ic_pin_analysis` | MCU pin audit | per-IC pin utilization summary |
| `signal_analysis.power_regulators` | Power Regulators | topology, vref_source, vout_estimate, vout_net_mismatch, inverting |
| `signal_analysis.feedback_networks` | Feedback Networks | R_top, R_bottom, vref, vout, vref_source |
| `signal_analysis.voltage_dividers` | Voltage Dividers | ratio, output_voltage |
| `signal_analysis.rc_filters` | RC/LC Filters | cutoff_hz, filter_type |
| `signal_analysis.lc_filters` | RC/LC Filters | resonant_freq_hz |
| `signal_analysis.opamp_circuits` | Op-Amp Circuits | configuration, gain |
| `signal_analysis.protection_devices` | Protection Devices | type, placement |
| `signal_analysis.transistor_circuits` | Transistor Circuits | load_type (motor/heater/fan/solenoid/etc.), is_pchannel, gate_drive |
| `signal_analysis.bridge_circuits` | Bridge Circuits | topology, half_bridges, driver_ics |
| `signal_analysis.crystal_circuits` | Crystal Circuits | cload, frequency |
| `signal_analysis.current_sense` | Current Sense | shunt_value, gain |
| `signal_analysis.decoupling_analysis` | Decoupling Analysis | per-rail cap inventory |
| `signal_analysis.buzzer_speaker_circuits` | Buzzer/Speaker | driver topology |
| `signal_analysis.rf_chains` | RF Chains | component chain |
| `signal_analysis.bms_systems` | BMS Systems | cell monitoring |
| `signal_analysis.ethernet_interfaces` | Ethernet | magnetics, PHY |
| `signal_analysis.memory_interfaces` | Memory | bus width |
| `signal_analysis.key_matrices` | Key Matrices | row/col count |
| `signal_analysis.isolation_barriers` | Isolation | isolation type |
| `signal_analysis.design_observations` | Design Observations | automated findings |
| `design_analysis.net_classification` | Net Classification | per-net class (power/data/analog/output_drive/etc.) |
| `design_analysis.power_domains` | Power Domains | per-IC rail mapping with IO rails |
| `design_analysis.cross_domain_signals` | Cross-Domain Signals | voltage equivalence filtering |
| `design_analysis.bus_analysis` | Bus Topology | I2C/SPI/UART/CAN with COPI/CIPO support |
| `design_analysis.differential_pairs` | Differential Pairs | suffix-pair matching, protocol guessing |
| `design_analysis.erc_warnings` | ERC Warnings | type, severity |
| `design_analysis.passive_warnings` | Passive Warnings | unusual values |
| `connectivity_issues` | Connectivity Issues | unconnected, single-pin, multi-driver |
| `pdn_impedance` | PDN Impedance | per-rail impedance with MLCC parasitics |
| `power_budget` | Power Budget | load vs capacity |
| `power_sequencing` | Power Sequencing | EN/PG chains |
| `sleep_current_audit` | Sleep Current | per-rail with regulator Iq, EN detection |
| `inrush_analysis` | Inrush Analysis | per-regulator inrush (automated); also manually consider IC supply pin abs max ratings and capacitor charging through connectors |
| `ground_domains` | Power & Ground | AGND/DGND/PGND separation |
| `sourcing_audit` | Sourcing Audit | MPN and distributor PN coverage (report neutrally, no distributor preference) |
| `bom_optimization` | BOM Optimization | value consolidation |
| `test_coverage` | Test Coverage | test points, debug connectors |
| `assembly_complexity` | Assembly Complexity | score, difficulty breakdown |
| `usb_compliance` | USB Compliance | connector, ESD, CC |
| `simulation_readiness` | Simulation Readiness | SPICE model coverage |
| `label_shape_warnings` | Label Warnings | direction mismatches |
| `pwr_flag_warnings` | PWR_FLAG | missing flags |
| `footprint_filter_warnings` | Footprint Filters | library mismatches |
| `annotation_issues` | Label Warnings | duplicate/missing refs |
| `property_issues` | Quality | property pattern issues |
| `placement_analysis` | (spatial context) | component clusters, grid |
| `alternate_pin_summary` | MCU pin audit | alt function usage |

### PCB Analyzer (`analyze_pcb.py`)

| Output Section | Report Section | Key Fields |
|---|---|---|
| `statistics` | Board Overview | copper_layers_used (tracks+vias+zones), layer names, SMD/THT counts |
| `layers` | Board Overview | full layer stack |
| `setup` | Board Overview | thickness, mask clearance |
| `board_outline` | Board Overview | bounding box, edge geometry |
| `board_metadata` | Board Overview | title block, paper |
| `footprints` | Footprint Placement | per-footprint pads, nets, schematic cross-ref (sch_path, sch_sheetname) |
| `component_groups` | Footprint Placement | grouped by reference prefix |
| `tracks` | Trace Routing | width/layer distribution |
| `vias` | Via Analysis | size distribution, via_analysis (types, annular ring, via-in-pad, tenting) |
| `zones` | Power & Ground | per-zone net, layers, outline/filled bbox, fill area, fill_ratio, thermal settings |
| `connectivity` | Connectivity | routing completeness, unrouted list |
| `net_lengths` | Signal Integrity | per-net trace length and layer transitions |
| `power_net_routing` | Power & Ground | power net width/length/current capacity |
| `ground_domains` | Power & Ground | AGND/DGND domains, multi-domain components |
| `current_capacity` | Current Capacity | per-net capacity vs load |
| `thermal_analysis` | Thermal Analysis | zone stitching density |
| `thermal_pad_vias` | Thermal Analysis | per-footprint thermal pad via count and adequacy |
| `decoupling_placement` | Decoupling Placement | cap-to-IC distances |
| `placement_analysis` | Footprint Placement | density, courtyard overlaps, edge clearance |
| `layer_transitions` | Signal Integrity | per-net layer change tracking |
| `silkscreen` | Silkscreen | ref visibility, documentation warnings |
| `dfm` | DFM Assessment | tier, metrics, violations |
| `tombstoning_risk` | Manufacturing | at-risk 0201/0402 components, thermal asymmetry reasons |
| `copper_presence` | Copper Presence | opposite_layer_summary, no_opposite_layer_copper (components WITHOUT zone copper on opposite layer — check capacitive touch pads, antennas), same_layer_foreign_zones |

### Gerber Analyzer (`analyze_gerbers.py`)

| Output Section | Report Section | Key Fields |
|---|---|---|
| `statistics` | Gerber Analysis | file counts, total holes/flashes/draws |
| `completeness` | Layer Completeness | found/missing layers, source |
| `alignment` | Alignment Verification | aligned status, layer extents |
| `drill_classification` | Drill Classification | vias, component holes, mounting holes |
| `pad_summary` | Pad Summary | SMD/THT/via/heatsink apertures |
| `board_dimensions` | Board Dimensions | from gerber extents |
| `gerbers` | (per-layer detail) | aperture functions, trace widths, X2 attributes |
| `drills` | (per-file detail) | tool list, hole counts |

## Severity Definitions

Use these consistently across all reports:

- **CRITICAL**: The board will not function as designed, or there is a safety/damage risk. Examples: swapped pins in symbol library, output contention from shorted op-amp outputs, regulator can't start, missing power path, thermal pad without ground vias on QFN.
- **WARNING**: The board may work but has a reliability, performance, or compliance concern. Examples: floating digital inputs, missing flyback diode on inductive load, cross-domain signal without level shifter, inadequate decoupling, regulator thermal margin tight.
- **SUGGESTION**: Best-practice improvement or documentation gap that doesn't affect functionality. Examples: missing MPNs, no test points on power rails, DNP components not marked, footprint filter mismatch with custom library.

## Writing Principles

### Be specific and actionable
Bad: "Power supply may have issues"
Good: "LMR51450 (U7) feedback divider R12/R13 gives Vout = 0.6*(1+100k/47k) = 1.88V, but target rail is 3.3V. Vref for LMR51450 is 1.0V (not 0.6V assumed by analyzer), giving actual Vout = 1.0*(1+100k/47k) = 3.13V — still 5% below target."

### Show your work
Include the calculation, the datasheet reference, and the conclusion. EE designers want to verify your reasoning, not just trust a pass/fail label.

### Distinguish analyzer findings from manual findings
Make it clear what came from the analyzer JSON vs what you found by reading the raw schematic. This helps designers understand the tool's coverage.

### Call out false positives explicitly
When the analyzer flags something that isn't actually a problem, explain why it's a false positive. This prevents designers from wasting time investigating non-issues and helps calibrate trust in the analyzer.

### Validate calculations, don't just echo them
When the analyzer reports a voltage divider ratio or filter cutoff, verify the calculation: check the formula, confirm the component values against the schematic, and validate the result against the datasheet's expected values (Vref, recommended output voltage, etc.).

### Cross-check against datasheets
The highest-value findings come from verifying component connections and values against datasheets. Check IC pin assignments against the datasheet pinout, feedback divider values against regulator recommendations, capacitor selections against min/max requirements, and pull-up/pull-down values against acceptable ranges. These checks catch the bugs that internal consistency checks miss.

### Assess plausibility when verification isn't possible
When a component can't be fully verified (missing MPN, missing datasheet), don't just report "unverified" and move on — assess how likely the design choice is to be correct. Use domain knowledge: typical pinouts for that device/package combination, standard passive values for the application, common circuit topologies. Report the assessment alongside the ambiguity. "Q1 uses Q_NPN_BEC (SOT-23) with no MPN — BCE is the most common SOT-23 NPN pinout, so this is likely correct but should be confirmed" is far more useful than "Q1 pinout is unverified." The principle: ambiguity is not uniform risk. Some unverified choices align with strong conventions and are low risk; others are genuinely ambiguous or go against convention and deserve higher suspicion.

### Verify battery and power source configurations
Don't assume a battery holder is a single cell. Check the footprint, part number, and trace connectivity to determine the actual battery configuration (series vs parallel, cell count). A 2×AA holder provides ~3V nominal, not 1.5V — getting this wrong invalidates the entire power tree analysis.

### Check thermal vias in footprints
Thermal vias for QFN/BGA/module packages may be embedded in the footprint definition as thru_hole pads (sharing the thermal pad's net and number) rather than standalone vias. The PCB analyzer counts both types. When reviewing thermal via adequacy, confirm you're counting footprint-embedded via pads in addition to standalone vias.

### Distributor neutrality
Never recommend or prefer any specific component distributor (DigiKey, LCSC, Mouser, etc.) by name in the report. Keep sourcing observations neutral — report MPN coverage and missing part numbers without directing the user toward a particular source.

### Power tree is king
For almost every board, the power tree section is the most valuable. Draw the complete hierarchy from input to every rail, including regulator types, enable conditions, and output capacitance. This single diagram often reveals the most critical issues (missing paths, wrong sequencing, inadequate capacitance).

## Handling Different Design Domains

### IoT / Battery-Powered
Focus on: sleep current budget (validate against analyzer's worst-case estimates), startup voltage thresholds, power path (USB vs battery), regulator quiescent current (check Iq estimates), deep sleep GPIO configuration.

### Motor Control
Focus on: H-bridge/3-phase topology detection, gate driver bootstrap, current sense chain, MOSFET load classification (motor/heater/fan/solenoid), ground domain separation (analog/power), bulk capacitance adequacy, reverse polarity protection, thermal considerations.

### RF / SDR
Focus on: RF chain path tracing through switches, LNA/mixer/filter identification, frequency planning, decoupling tier analysis (bulk + bypass + HF), reference clock distribution, ground plane continuity.

### Precision Analog / Instrumentation
Focus on: op-amp configurations and gain accuracy, reference voltage chain, input protection on measurement channels, ADC/DAC interface verification, PGA detection, bipolar supply generation, guard traces.

### Industrial / Multi-rail
Focus on: power sequencing (EN/PG chains from analyzer), input protection (TVS, MOV, fuses), communication buses (CAN, RS485, Ethernet — check bus analysis), isolation barriers, creepage/clearance for high voltage. The Standards Compliance section in the report template is especially important here — fill in all subsections including creepage/clearance.

## Cross-Referencing with Raw Schematic

The analyzer can silently produce plausible but incorrect results. Cross-reference against the raw `.kicad_sch` to catch these. The full verification procedure is in SKILL.md — the key checks are:

1. **Component count**: Analyzer total vs `grep -c '(lib_id' file.kicad_sch` (subtract power symbols)
2. **Pin-to-net mapping**: Verify against raw schematic for each component. Cross-reference IC pin assignments against datasheets.
3. **Physical correctness**: For components with package-dependent pinouts (transistors in SOT-23 etc.), verify symbol assumptions against the MPN's datasheet — consistency checks alone don't catch wrong pinout assumptions.
4. **Net connectivity**: Trace power rails and critical signal nets end-to-end.
5. **Signal analysis**: Confirm detected subcircuit topologies against the raw schematic.
6. **Hierarchical sheets**: Verify all sub-sheets were parsed (`grep -c '(sheet ' file.kicad_sch`).

## Known Analyzer Limitations

Document these when they affect the report — it helps the designer understand what the tool can and can't catch:

- **Vref coverage**: Feedback divider Vout calculations use a lookup table (~60 regulator families) with heuristic fallback. When `vref_source` is `"heuristic"`, the assumed Vref may be wrong — always verify against the datasheet. The `vout_net_mismatch` field flags cases where estimated Vout differs >15% from the output rail name voltage.
- **Legacy format**: KiCad 5 `.sch` files get component + net extraction only — no pin-to-net mapping, no signal analysis, no subcircuit detection.
- **Sleep current model**: Uses worst-case assumption (all pull-ups driven low simultaneously) plus family-level regulator Iq estimates with EN pin detection. Real sleep current is typically 5-20x lower than reported.
- **Cross-domain analysis**: Uses voltage equivalence (parsing voltage from rail names) to reduce false positives, but rails without parseable voltages in their names may still trigger false cross-domain warnings.
- **MOSFET load classification**: Net name keyword detection covers common patterns (motor, heater, fan, solenoid, valve, pump, relay, speaker, buzzer, lamp) but may miss unusual naming conventions.
- **Bridge circuits**: Cross-sheet detection works through unified hierarchical nets. Topology classification is based on half-bridge count (1=half, 2=H-bridge, 3+=3-phase) which may misclassify independent half-bridges as an H-bridge.

## Report Length Guidelines

Typical report lengths by design complexity:

| Design | Components | Typical Report |
|--------|-----------|---------------|
| Simple (IoT, single sheet) | 30-100 | 150-250 lines |
| Medium (motor control, few sheets) | 100-300 | 200-350 lines |
| Complex (DAQ, RF, many sheets) | 300-700 | 300-450 lines |

Keep it thorough but avoid padding. Every line should provide information the designer can act on or use to build confidence in the design.
