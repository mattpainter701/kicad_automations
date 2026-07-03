# Tasks

> Work only on what's listed here. Check boxes as completed, update CHANGELOG.md alongside.

## Generation Pipeline Audit (2026-05-04)

> Scoping document for Sprint 52+. Reviews the schematic, passive-synthesis,
> and PCB-placement code paths against four recurring real-world symptoms.
> Each finding cites primary evidence and proposes a gap-closing option.
> Not committed work — this is the input to sprint planning.

### Scope Reviewed

- `generator.py` (2476 lines) — top-level schematic emitter, pin/wire/label routing
- `subcircuits/topology_builders.py` (1621 lines) — `build_generic` + 13 specialized builders dispatched via `TOPOLOGY_BUILDERS`
- `subcircuits/base.py` (887 lines) — `DataDrivenTemplate`, `BoundaryPort`, value calculators
- `component_db.py` — `auto_generate_bypass_caps`, `infer_passive_component`, BOM ingestion
- `generational_repair.py` (365 lines) — I2C pull-up auto-repair pass
- `validator.py` (939 lines) + `placement_readiness.py` (207 lines) — validation gates
- `placer.py` (1635 lines) — schematic sheet layout + paper sizing + density heuristics
- `placement_optimizer.py` (416 lines) + `pcb_export.py` — PCB placement preview generation
- `ic_data/*.json` — 99 IC entries total across 11 categories (full catalog)
- `I:/my_circuit/val_output.txt` — live failing-validation evidence

### Symptom Legend

The user reported four observed failure classes. Findings below tag which they produce:

- **[OP]** Orphaned pin — pin wired to a net no other component touches
- **[HP]** Hanging pin — pin emitted as no-connect or left dangling without intent
- **[CD]** Crazy density — schematic sheet or PCB region unreadable / over-packed
- **[NR]** Logically valid but Not Real — passes validator/ERC but won't function (wrong topology, wrong support parts, wrong pinout for that part)

---

### Findings — Schematic Emission

**F1. `build_generic` synthesizes per-instance net names for every unmapped signal pin** [OP, NR]

`subcircuits/topology_builders.py:1507` — every signal pin not pre-mapped to a shared bus gets the net name `f"{pin.name}_{ref}"`. This is then exported as a `BoundaryPort` (line 1553-1554). 23 topologies fall through to this builder (`_GENERIC_TOPOLOGIES`, lines 1586-1613) — including `usb_controller`, `usb_hub`, `ethernet_phy`, `motor_driver`, `audio_amplifier`, `adc`, `dac`, `current_sense`, `opamp`, `sensor_frontend`, `crystal_oscillator`, `clock_synth`. Live evidence in `I:/my_circuit/val_output.txt`: `USB_DP_U1`, `USB_DM_U1`, `USB_DP_U4`, `USB_DM_U4`, `XTAL2_FE`, `XTAL1_FE` all flagged as single-pin nets — these are the USB and crystal pins of an MCU getting per-instance suffixes that the USB-C connector and crystal subcircuit never see.

*Gap-closing option:* For each topology in `_GENERIC_TOPOLOGIES`, declare its real signal interfaces in `ic_data/*.json` (e.g. `pin_usb_dp`, `pin_usb_dm`, `pin_xtal_in`, `pin_xtal_out`) and route them through the shared-bus mechanism that already exists for SDA/SCL/SPI (lines 1478-1494). Hard-fail when an unmapped non-power signal pin remains — the present synthesized-net path is the bug surface, not a feature.

**F2. Pin name `~` (no-name pin) emitted as literal net `~_{REF}`** [OP, HP]

Same line 1507. KiCad symbols for many MCUs use `~` for un-named pins (RESET#, generic GPIO). Evidence: `Net '~_U1' has no output driver — only inputs: U1:46, U1:47, U1:49` and `~_U4` in val_output.txt. The classifier at `generator.py:108` (`_NC_PIN_NAME_PATTERNS`) already knows `~` means no-connect, but `build_generic` runs first and gives it a synthesized net name before the classifier ever sees it.

*Gap-closing option:* Filter pin names against `_NC_PIN_NAME_PATTERNS` inside `build_generic` before synthesizing net names; route those pins to `explicit_no_connects` instead.

**F3. Single 100nF on VDD only for all `build_generic` ICs — silently bypasses the smarter per-rail policy** [NR]

`topology_builders.py:1510-1520` unconditionally adds one `BypassCap` on `vdd_net` regardless of how many power pins or rails the IC has. Then at `generator.py:1094`, `auto_generate_bypass_caps` runs — but `component_db.py:904` skips any component whose `bypass_caps` list is non-empty. So the smarter policy (one 100nF per power net, +10µF bulk if ≥3 rails) at `component_db.py:891-953` is silently disabled for exactly the 23 generic-built topologies that need it most (multi-rail ADCs, mixed-signal opamps, ethernet PHYs with separate AVDD/DVDD).

*Gap-closing option:* Make `build_generic` enumerate `power_pins` and emit one HF cap per non-ground rail, OR make `auto_generate_bypass_caps` augment rather than skip when existing caps don't cover every rail.

**F4. Pin classification fallback always emits no-connect with only a warning** [HP]

`generator.py:126-184` `_classify_unhandled_pin` returns `"no_connect"` for every level (silent/warning/error). Even when the level is `"error"` (`FLOATING power_in pin`), the schematic still gets emitted with the NC marker. Validation runs at line 1101, before sheet rendering at line 1108, but the emit decision was made by the classifier itself. The validator can flag it but cannot prevent it.

*Gap-closing option:* Promote `level=="error"` from `_classify_unhandled_pin` to a hard generation failure (raise to caller) instead of emitting a `(no_connect)` and a log line.

**F5. Validator runs before schematic emit but emit proceeds regardless of severity** [OP, HP]

`generator.py:1100-1108` — `run_validation_checks` called, then `_report_validation_results` prints, then sheet allocation continues unconditionally. The hard gate is at `dispatcher.generate_artifacts` (which treats `placement_readiness` errors as non-bypassable per `placement_readiness.py:1-9`), but `generate_from_components` itself has no early return. Direct callers of the generator (tests, scripts, `--no-readiness-gate`) still produce `.kicad_sch` files containing dangling nets.

*Gap-closing option:* Move the placement-readiness gate up into `generate_from_components` so any caller path inherits the same guarantee, with a single named override flag if a debug emit is genuinely needed.

**F6. Local route picker silently falls back to a direct line through obstacles** [CD]

`generator.py:714-768` `_route_local_connection` tries lane routes, then six L/U-shaped detour candidates, picks the shortest clear one — and at line 767 falls back to `connect_points` (a direct line) if every candidate intersected an obstacle. There is no warning emitted and no escalation. Result: passive support wires can cross IC bodies, producing visually unreadable schematics that still pass ERC.

*Gap-closing option:* Log the fallback (or escalate to a "wire could not be routed cleanly" warning), and bias the layout pass to leave more lane space when a fallback fires.

**F7. Boundary-net set is polluted by synthesized per-instance nets, promoting them to hierarchical sheet pins** [NR, OP]

`generator.py:1772-1776` `_label_fn` correctly decides per-net based on `boundary_nets` membership. The bug is upstream: `_compute_boundary_nets` (`generator.py:984-988`) unions `explicit_boundary_ports` with cross-sheet-appearing nets. Every `BoundaryPort` declared by `build_generic` (one per signal pin per F1, line 1553-1554) ends up in `explicit_boundary_ports`. So a synthesized name like `USB_DP_U1` becomes a hierarchical sheet pin on the parent sheet — a phantom interface that looks legitimate but connects nothing.

*Gap-closing option:* Filter `explicit_boundary_ports` against actual cross-component reachability before promoting; or fix at the source (F1) so synthesized per-instance nets are never declared as `BoundaryPort` in the first place.

---

### Findings — Passive Generation & Repair

**F8. Bypass cap policy ignores datasheet-recommended values** [NR]

`component_db.py:881-882` hard-codes `_AUTO_BYPASS_FP_HF = "0402"` and `_AUTO_BYPASS_FP_BULK = "0805"` and `100nF` / `10uF` values. There is no lookup against the IC's datasheet-specified input/output capacitance, which for switching regulators (TPS62088 etc.) and high-current loads (motor drivers) is the difference between stable operation and instability. The same 100nF goes on a 50mA RTC and a 3A buck.

*Gap-closing option:* Extend `ic_data/*.json` with `recommended_bypass: [{net, value, count}]` blocks and prefer those when present. Fall back to the heuristic only for parts without datasheet data.

**F9. Auto-repair only covers I2C pull-ups; SPI CS / UART pairing detected but not synthesized** [HP, NR]

`generational_repair.py` only emits `i2c_pullups` repairs. Validator codes `spi-floating-cs` and `uart-unpaired` exist (`placement_readiness.py:43-44`) but no repair pass produces the corresponding straps or sister-net declarations. User must manually fix every flagged case.

*Gap-closing option:* Extend `generational_repair.py` with passes for SPI CS pull-up synthesis and UART pair-completion (or explicit-NC declaration on the unused side).

**F10. I2C repair fires on lone-sensor designs, creating phantom buses** [NR]

`generational_repair.py:65-125` `_bus_pairs` triggers as soon as one SDA-named net and one SCL-named net both exist anywhere in the design. A single I2C sensor with no MCU yet still gets pull-ups synthesized to a guessed VDD rail (`_pick_vdd_rail`, lines 164-186) — which becomes the wrong rail when the MCU is added later on a different VDD.

*Gap-closing option:* Require ≥2 distinct components on each of SDA/SCL before synthesizing pull-ups; emit a placement-readiness warning rather than auto-repair when only one is present.

**F11. Power-pin auto-detection uses substring match, risking false positives** [NR]

`topology_builders.py:1450-1476` walks pin names and matches `p in name_upper` for any prefix in `POWER_NET_PREFIXES` (which includes generic prefixes like `VDD`, `VCC`, `VIN`). A pin literally named `MAINSVIN_SENSE` becomes a power-input bound to `VDD_3P3`. This sets up nets that the rest of the design doesn't know about.

*Gap-closing option:* Restrict to prefix-exact matching plus a curated allowlist of equivalences; never use substring containment for net assignment.

**F12. Crystal load capacitor coverage detected but never auto-repaired** [HP, NR]

Live evidence in val_output.txt lines 9-22: `crystal-load` warnings on X1 and X2. Validator detects the missing load caps; no repair pass synthesizes them. The crystal_oscillator topology dispatches to `build_generic` (per F1) which doesn't know what a crystal needs.

*Gap-closing option:* Promote `crystal_oscillator` out of `_GENERIC_TOPOLOGIES` into a dedicated builder that emits the load-cap network sized from the crystal datasheet's `CL` value.

---

### Findings — Sheet Layout & Density

**F13. Connector-heavy heuristic only triggers above a fixed threshold** [CD]

`placer.py:1318` — `connector_heavy = len(connectors) >= 8 and not regulators and len(other_ics) <= max(6, len(connectors)//3)`. A 7-connector board, or one with 8 connectors plus a single regulator, falls to the default layout that doesn't pack connectors into columns and produces sparse-looking sheets. Conversely a 12-connector board with one MCU still triggers the dense connector grid even when a normal layout would fit.

*Gap-closing option:* Replace the boolean threshold with a continuous density score (connectors-per-page, IC-per-page) and pick layout strategy from the score.

**F14. Bypass cap clusters can overflow into adjacent IC zones** [CD]

`placer.py:1466-1510` lays bypass caps in a tight row below the parent IC with `_support_cluster_cols` columns. There is no lookahead check that the row fits within the IC's allocated horizontal slot, so a wide cluster (≥6 caps on a multi-rail chip) can overlap the next IC's footprint zone. The router then either crosses the neighbor (F6) or pushes wires through obstacles.

*Gap-closing option:* Compute cluster width before sheet layout and reserve the column space; if the cluster exceeds slot width, wrap into multiple rows or move some caps to a dedicated power-tree sheet.

**F15. Paper size promotion proceeds even when A0 doesn't fit** [CD]

`generator.py:1163-1189` (paper-fit loop) tries A4→A3→A2→A1→A0 in order. If A0 still overflows, a warning is logged but the schematic emits at A0 with components crammed. The user sees an unreadable A0 page rather than a hard failure.

*Gap-closing option:* When A0 cannot fit the content, split the largest sheet into two and re-allocate, OR fail generation with a clear "design too large for single sheet" error.

---

### Findings — PCB Placement

**F16. Placement optimizer has no connectivity-driven cost** [NR]

`placement_optimizer.py:262-275` `_total_cost` sums overlap + boundary + thermal + zone costs. The signal-integrity branch at line 270-271 is `pass  # Placeholder — needs net connectivity data`. Simulated annealing therefore runs with no awareness of which components share nets, so the placement preview is purely zone-based and provides no useful signal-routing hint.

*Gap-closing option:* Add a wire-length cost term using `pin_nets` + `power_pins` net-to-component map (data already collected in `pcb_export._build_net_list`); even a crude squared-distance sum across shared-net component pairs would change behavior.

**F17. Footprint size estimation regex misses non-metric and custom footprints** [CD]

`pcb_export.py:140-168` uses regex on the footprint string. Metric-coded passives (`0402metric`) work; QFP/QFN with `WxH` in the name work; everything else falls through to a pin-count heuristic where BGA defaults to 25×25mm and small ICs to 5×5mm. Custom footprints (`Connector_Custom:My_Special_Header`) get the 5×5mm default, producing wildly wrong placement spacing in either direction.

*Gap-closing option:* Read the actual footprint from KiCad's library files when available; cache the resulting bbox per footprint name. Fall back to the regex heuristic only when the file isn't found.

**F18. PCB zone map hardcoded to fractions of board, ignores aspect ratio** [CD]

`placement_optimizer.py:50-58` `_ZONE_CENTERS` is `(x_pct, y_pct)` of board. Same percentages applied to a 20×20mm board and a 200×100mm board — on a square board the connector zone at `(0.5, 0.95)` is fine; on a long thin board it crowds against one edge. Plus `pcb_export._ZONE_MAP` (lines 105-124) misses categories the rest of the system uses (e.g. no `motor`, no `audio`, no `power_management` — those silently fall to `digital`).

*Gap-closing option:* Define zones in absolute mm relative to board edges (not percentages), and align `_ZONE_MAP` with the full category set used by `component_db`.

**F19. PCB export emits zero pads — placement is preview-only** [NR]

`pcb_export.py:202-240` `_footprint_sexpr` deliberately emits no pads (Sprint 40 design choice, line 217-220). The user's `.kicad_pcb` file is a hint, not a routable artifact; KiCad's forward-annotation from the schematic is the authoritative source. This is documented behavior but easy to misread — users have repeatedly assumed the PCB is functional and tried to fab it.

*Gap-closing option:* Either rename the output to `*.placement_preview.kicad_pcb` and add a banner comment refusing to emit unless explicitly requested, or close the gap by reading footprint pad data from `.kicad_mod` files in the system library and emitting real pads.

---

### Findings — Cross-Cutting

**F20. IC catalog is sparse — 99 entries across 11 categories** [NR, OP]

`ic_data/*.json` total: 8 amplifiers, 10 bus interfaces, 11 connectors, 6 converters, 7 customs, 12 LDOs, 2 memories, 29 misc, 4 oscillators, 4 protection, 6 switching regulators. Nothing in this set covers the live design `I:/my_circuit/design.yaml` (which references USB controllers, ethernet PHYs, sensor frontends, etc.). Designs route through `build_generic` not because they want generic behavior but because the catalog has no real entry for the part — and `build_generic` cannot infer signal contracts from a name alone.

*Gap-closing option:* Treat catalog growth as the primary lever for reducing F1/F2/F3/F12-class issues. Each new entry deletes synthesized-net failures for every design that uses that part. Source from datasheet ingestion (`datasheet_parser.py` already exists) and from EasyEDA/KiCad symbol libraries (`easyeda_parser.py`, `symbol_resolver.py` already exist).

**F21. Pin electrical type defaults to `passive` in catalog JSON** [HP, NR]

Confirmed via `ic_data/connector.json` lines 7-25 — every pin has `"type": "passive"`. The pin classifier at `generator.py:163-177` then can't distinguish a real power pin from an unused GPIO and falls into the generic warning bucket. F4's no-connect-on-warning fallback fires routinely as a result.

*Gap-closing option:* Bulk-update the catalog with real electrical types (`power_in`, `power_out`, `input`, `output`, `bidirectional`, `tri_state`) — derivable from datasheet pin-function tables.

**F22. Two parallel bypass-cap synthesis paths can drift** [NR]

`build_generic` (topology_builders.py:1510) and `auto_generate_bypass_caps` (component_db.py:891) both emit `BypassCap` objects with overlapping intent but different policies. The interlock at `component_db.py:904` (skip-if-non-empty) is the only thing preventing duplication, and it exists implicitly rather than by contract. Future edits to either path can silently break it.

*Gap-closing option:* Single owner — pick `auto_generate_bypass_caps` as authoritative, remove the bypass cap emit from `build_generic`, and let the central pass handle every IC uniformly.

**F23. Orphan-interface detection only fires on declared block interfaces** [OP]

`placement_readiness.py:79-128` `_orphan_interface_issues` only walks `compiled_ir.blocks[].interfaces`. A net that appears in `pin_nets` but isn't declared as a block interface is treated as internal — even if no other component touches it. The synthesized per-instance nets from F1 (`USB_DP_U1`) are exactly this case and never surface as orphans; they only show up via the structural `single-pin-net` check, which is a `warning`, not a hard error.

*Gap-closing option:* Extend orphan detection to include any non-power net with `len(consumers) <= 1` — promote those to placement-readiness errors so the gate at dispatcher catches them before emit.

---

### Symptom-to-Finding Cross-Reference

| Symptom | Findings |
|-|-|
| Orphaned pin (OP) | F1, F2, F5, F7, F20, F23 |
| Hanging pin (HP) | F2, F4, F5, F9, F12, F21 |
| Crazy density (CD) | F6, F13, F14, F15, F17, F18 |
| Logically valid but Not Real (NR) | F1, F3, F7, F8, F9, F10, F11, F12, F16, F19, F20, F21, F22 |

### Highest-Leverage Gap-Closing Options (Ranked)

1. **F1 + F23** — Kill `build_generic`'s synthesized-net behavior + extend orphan detection to all non-power single-consumer nets. Single largest source of OP/NR issues; one architectural change closes the most failure modes.
2. **F20** — Catalog growth pipeline (datasheet → `ic_data/*.json` ingestion). Reduces every downstream failure proportional to coverage.
3. **F22 + F8** — Consolidate bypass-cap synthesis into one datasheet-aware owner. Removes silent interaction bug + improves real-circuit correctness.
4. **F16** — Add connectivity cost to PCB optimizer. Smallest code change with biggest visible PCB-quality jump.
5. **F4 + F5** — Make floating-power-pin a hard generation failure, lift readiness gate into `generate_from_components`. Stops bad schematics from being written at all.
6. **F12** — Promote `crystal_oscillator` (and other passive-heavy topologies) out of `_GENERIC_TOPOLOGIES` into dedicated builders.
7. **F9 + F10** — Extend `generational_repair.py` to cover SPI CS / UART pairing; tighten I2C trigger to ≥2 participants.
8. **F14 + F15** — Density / paper-fit improvements. Lower priority than correctness fixes but high user-visible impact.

### Proposed Sprint 52 Task Slate (Draft)

If the user/maintainer accepts this audit, candidate tasks (T228+) for the next sprint open:

- **T228** — Replace `build_generic` fallback signal-net synthesis with normalized interface / pin-role routing; hard-fail on unresolved required signal pins (closes F1, F2, partially F23).
- **T229** — Promote single-consumer non-power nets to `placement_readiness` errors (closes F23, hardens F1's blast radius).
- **T230** — Consolidate bypass-cap synthesis into `auto_generate_bypass_caps`; remove duplicate path from `build_generic`; add per-rail HF + bulk-cap policy driven by `ic_data` recommended values when present (closes F3, F22, partially F8).
- **T231** — Add connectivity-driven wire-length cost to `placement_optimizer._total_cost` using existing net maps (closes F16).
- **T232** — Lift placement-readiness gate from `dispatcher.generate_artifacts` into `generate_from_components`; promote `_classify_unhandled_pin` errors to hard failures (closes F4, F5).
- **T233** — Extend repair from named-bus heuristics to normalized interface roles; keep crystal handling on a dedicated builder and finish SPI / UART completion from shared metadata (closes F9, F12).
- **T234** — Turn catalog growth into a normalized ingest pipeline: expand schema + importers so missing parts enter as vendor-agnostic capabilities instead of per-part engine behavior (closes parts of F20, F21).

Files most likely impacted: `subcircuits/topology_builders.py`, `subcircuits/base.py`, `component_db.py`, `generator.py`, `placement_readiness.py`, `placement_optimizer.py`, `generational_repair.py`, `easyeda_parser.py`, `datasheet_parser.py`, `ic_data/*.json`.

---

## Sprint 52 — Generation Pipeline Hardening (v0.30.52)

**Goal:** Close the highest-leverage findings from the 2026-05-04 generation pipeline audit while keeping the engine part-neutral. Eliminate synthesized-net orphans, consolidate bypass-cap synthesis behind one datasheet-aware owner, tighten the placement-readiness gate across schematic and PCB paths, and convert catalog work into normalized, vendor-agnostic schema + ingest improvements rather than a per-part template backlog.

### T228. Replace fallback signal-net synthesis with normalized interface routing (P1, HIGH) ✅ DONE

- [x] Reproduce the live `USB_DP_U1`, `USB_DM_U1`, `XTAL2_FE`, `~_U1` synthesized-net failures from `I:/my_circuit/val_output.txt` against the current build as normalized routing/schema failures, not as part-specific exceptions: the new T228 regressions in `tests/test_template_structure.py` reproduce each class (USB pin-name routing, crystal role routing, `~`/`RESERVED` NC filtering) against synthetic parts.
- [x] In `subcircuits/topology_builders.py:build_generic`, remove `f"{pin.name}_{ref}"` fallback synthesis for unresolved non-power signal pins; route only through normalized declared interfaces, pin electrical types, optional-pin annotations, and shared-bus metadata from `ic_data` / imported part data. Pin-name role inference (`infer_pin_roles_from_pins`) fills undeclared roles so imported parts land on shared buses; everything else stays unmapped and fails closed.
- [x] Filter pin names against `_NC_PIN_NAME_PATTERNS` (e.g. `~`) before any net synthesis so they route to `explicit_no_connects` instead of becoming `~_{REF}` nets.
- [x] Hard-fail generation when an unmapped non-power signal pin remains after declared-interface routing; surface the failure with pin name and component reference.
- [x] Add regression coverage proving imported USB, crystal, and ethernet-family parts no longer emit per-instance signal nets or synthesized `BoundaryPort` declarations when normalized metadata is sufficient, and fail closed when it is not.

Follow-on hardening landed with this task: the T229 `orphan-net` gate now recognizes support-passive endpoints (straps, bypass/bootstrap caps, inductors, feedback dividers) as real second consumers, fixing false-positive errors on every regulator SW/FB/BST node and strap net that had turned the sample/corpus release gates red; `build_generic` no longer defaults chip-select to a per-instance `CS_{REF}` net (the mapped default blocked the SPI repair pass); and `MCP1700-1802E` joins `linear_regulator.json` so `oled_display_module` resolves without silent substitution.

Closes audit findings F1, F2, partially F23.

Files: `src/circuit_weaver/subcircuits/topology_builders.py`, `src/circuit_weaver/generator.py`, `tests/`

### T229. Promote single-consumer non-power nets to placement-readiness errors (P1, MEDIUM)

- [x] Extend `_orphan_interface_issues` (or a sibling check) in `placement_readiness.py` to flag any non-power net with `len(consumers) <= 1` as an error, not just declared block interfaces.
- [x] Add a curated allowlist for legitimate single-pin nets (test points, debug headers, explicit no-connects) so the new gate does not fire on intentional cases.
- [x] Re-run validation on `I:/my_circuit/design.yaml` and confirm the new gate catches what F1 leaves behind without producing false positives on real designs.
- [x] Add regression coverage for both the failure path and the allowlisted exemption path.

Closes audit finding F23, hardens F1's blast radius.

Files: `src/circuit_weaver/placement_readiness.py`, `tests/test_placement_readiness.py`

### T230. Consolidate bypass-cap synthesis under `auto_generate_bypass_caps` (P1, MEDIUM)

- [x] Remove the in-builder bypass-cap emission from `subcircuits/topology_builders.py:build_generic` (and any other builder that duplicates the policy).
- [x] Make `auto_generate_bypass_caps` enumerate `power_pins` and emit one HF cap per non-ground rail plus a bulk cap when the IC has ≥3 rails, regardless of whether the builder already declared any caps.
- [x] Honor `recommended_bypass: [{net, value, count}]` from `ic_data/*.json` when present; fall back to the heuristic only for parts without datasheet-driven values.
- [x] Add regression coverage for multi-rail ICs (ADC, ethernet PHY, mixed-signal opamp) proving every power rail gets a cap and the catalog-driven path overrides the heuristic.

Closes audit findings F3, F22, partially F8.

Files: `src/circuit_weaver/component_db.py`, `src/circuit_weaver/subcircuits/topology_builders.py`, `src/circuit_weaver/ic_data/*.json`, `tests/`

### T231. Add connectivity-driven wire-length cost to PCB placement optimizer (P2, MEDIUM)

- [x] Replace the `pass  # Placeholder` branch in `placement_optimizer._total_cost` with a wire-length cost term that uses the `pin_nets` + `power_pins` net-to-component map already collected by `pcb_export._build_net_list`.
- [x] Compute a squared-distance sum across shared-net component pairs and weight it relative to the existing overlap/boundary/thermal/zone costs.
- [x] Add a regression proving SA placement of a connected pair settles closer than placement of two unconnected components on the same board.
- [x] Re-run a representative archetype from the corpus and confirm the placement preview becomes signal-aware rather than purely zone-based.

Closes audit finding F16.

Files: `src/circuit_weaver/placement_optimizer.py`, `src/circuit_weaver/pcb_export.py`, `tests/`

### T232. Lift placement-readiness gate into `generate_from_components` (P2, MEDIUM)

- [x] Move the placement-readiness gate from `dispatcher.generate_artifacts` up into `generator.generate_from_components` so direct callers (tests, scripts, `--no-readiness-gate`) inherit the same guarantee.
- [x] Keep a single named override flag for legitimate debug emits; do not regress the existing `--no-readiness-gate` workflow without an explicit test.
- [x] Promote `_classify_unhandled_pin` `level == "error"` results from a logged no-connect to a hard generation failure that surfaces the offending pin and component.
- [x] Add regression coverage for the lifted gate, the override flag, and the floating-power-pin hard-fail path.

Closes audit findings F4, F5.

Files: `src/circuit_weaver/generator.py`, `src/circuit_weaver/dispatcher.py`, `src/circuit_weaver/placement_readiness.py`, `tests/`

### T233. Extend repair using normalized interface roles (P2, MEDIUM) ✅ DONE

- [x] Add a dedicated `crystal_oscillator` builder that emits the load-cap network sized from the crystal datasheet's `CL` value, replacing the current `_GENERIC_TOPOLOGIES` fall-through with topology-level behavior.
- [x] Extend `generational_repair.py` with SPI repair keyed to normalized controller/peripheral interface roles so floating chip-select pins complete onto an existing unique CS net shared by the same SPI bus, not via part-name allowlists.
- [x] Extend `generational_repair.py` with UART repair keyed to normalized TX/RX roles so incomplete UART participants can complete onto an existing peer-direction net instead of relying on per-device rules.
- [x] Add optional flow-control / explicit-NC behavior for metadata-declared but intentionally unused UART handshake pins: `_repair_uart_flow_control` completes an unmapped RTS/CTS pin onto the existing sibling flow-control net when derivable, and otherwise declares it an explicit no-connect (clearing the T228 fail-closed marker) whenever the component's TX/RX pair is actively wired.
- [x] Add regression coverage proving the crystal, SPI, and UART repair paths work for both imported and curated parts from shared interface metadata alone: new tests cover pin-name-inference-only SPI/UART repair, curated `pin_roles` flow-control completion and NC fallback, and imported-`pin_roles` crystal building plus its fail-closed path.

Closes audit findings F9, F12.

Files: `src/circuit_weaver/subcircuits/topology_builders.py`, `src/circuit_weaver/generational_repair.py`, `src/circuit_weaver/ic_data/*.json`, `tests/`

### T234. Turn catalog growth into a normalized ingest pipeline (P3, MEDIUM) — MOSTLY DONE

- [x] Bulk-update `ic_data/connector.json` to replace the universal `"type": "passive"` with real normalized pin types so `_classify_unhandled_pin` no longer falls into the generic warning bucket.
- [x] Add normalized `pin_roles` as a shared interface-role contract on `ComponentDef`, cache payloads, generic-builder outputs, and `ic_data` conversion so repairs/builders can consume capabilities instead of exact MPNs.
- [x] Upgrade the EasyEDA ingest path to populate that schema from imported pin names, so imported parts expose vendor-agnostic interface roles without new Python templates.
- [x] Extend the same normalized schema propagation to datasheet-derived ingest and broader fields (optional/debug pins, power domains, recommended support passives, vendor aliases): `datasheet_parser.parse_datasheet_text` now extracts pin-function tables into normalized `pins` / `pin_roles` / `pin_vdd` / `pin_gnd` / `power_domains` / `explicit_no_connects` / `debug_pins`, recognizes datasheet-recommended bypass values into `recommended_bypass`, and `extract_specs` propagates index-declared `vendor_aliases` as sourcing metadata. `build_generic` honors declared `debug_pins` / `optional_pins` as safely-unrouted instead of hard-failing.
- [x] Use `samples/` as an acceptance corpus for missing-part coverage, treating named MPNs only as fixtures (sample validate/generate gates plus a catalog-wide sweep asserting every generic-dispatched entry emits no synthetic nets). Re-checking `I:/my_circuit/design.yaml` remains for the maintainer's machine — the path is not available in this environment.
- [x] Add regression coverage showing representative buck, USB, memory, and audio/imported parts flow through normalized schema + generic/topology builders without synthetic-net or pin-type artifacts: `test_t234_catalog_generic_entries_emit_no_synthetic_nets` sweeps every catalog entry that dispatches to `build_generic`, and the datasheet-ingest tests prove an imported pin table flows through `build_generic` end-to-end.

Closes audit findings F20, F21.

Files: `src/circuit_weaver/ic_data/*.json`, `src/circuit_weaver/datasheet_parser.py`, `src/circuit_weaver/easyeda_parser.py`, `tests/`

---

## Sprint 51 — Restart & Validation Hardening (v0.30.6)

**Goal:** Make `/circuit-weaver` restarts truthful and robust on Windows, fail closed on invalid component/template resolution, and harden the validation/auto-repair path exposed by `I:/my_circuit/design.yaml`.

### T219. Surface installed CLI version at `/circuit-weaver` startup (P1, LOW)

- [x] Require the `/circuit-weaver` skill to print the installed `circuit-weaver --version` result before presenting route choices.
- [x] Keep the repo-local canonical skill and bundled shipped skill byte-identical after the change.
- [x] Verify the startup banner wording against the installed CLI in this environment.

Files: `skills/circuit-weaver/SKILL.md`, `src/circuit_weaver/_bundled_skills/circuit-weaver/SKILL.md`

### T220. Restore truthful restart/log-status visibility (P1, HIGH)

- [x] Reproduce the `I:/my_circuit` restart issue where `design.log` exists but `circuit-weaver log-status` reports `No design workflow recorded yet.`
- [x] Make `log-status` treat validate-only / CLI-only sessions as real workflow progress instead of requiring wizard steps with `step > 0`.
- [x] Make persisted validation summaries reflect the real post-placement-readiness validity, not just the early raw validator pass.
- [x] Add regression coverage for validate-only projects and failed validation sessions.

Files: `src/circuit_weaver/design_logger.py`, `src/circuit_weaver/dispatcher.py`, `src/circuit_weaver/validator.py`, tests

### T221. Make validation output Windows-console safe (P1, MEDIUM)

- [x] Reproduce the cp1252 `UnicodeEncodeError` from `validate` on Windows consoles.
- [x] Replace unsafe glyph-only status output with an encoding-safe fallback while preserving readable colored output where supported.
- [x] Add regression coverage for non-UTF-8 stdout encodings.

Files: `src/circuit_weaver/dispatcher.py`, tests

### T222. Fail closed on invalid data-driven component and connector resolution (P1, HIGH)

- [x] Remove the data-driven template fallback that silently substitutes the first registered IC when the requested `ic` is missing.
- [x] Make connector intent explicit: support the `usb-a` connector path used by `I:/my_circuit/design.yaml`, or emit a clear validation/generation failure instead of falling back to a barrel jack model.
- [x] Add regression coverage proving unknown `type: component` ICs and unsupported connector variants fail closed.
- [x] Re-run validation on `I:/my_circuit/design.yaml` and confirm the old bogus `TIP_J2` / `RING_J2` / repeated `USB_DP_*` artifacts are gone.

Files: `src/circuit_weaver/subcircuits/base.py`, `src/circuit_weaver/subcircuits/connector.py`, `src/circuit_weaver/ic_data/connector.json`, `src/circuit_weaver/project_spec.py`, tests

### T223. Harden auto-repair bus pairing and suppression scope (P2, MEDIUM)

- [x] Require meaningful SDA/SCL participant overlap before synthesizing I2C pull-up repairs.
- [x] Scope `i2c_bus` suppression to the matching bus instead of disabling repair globally for every I2C bus in a design.
- [x] Add negative tests for unrelated SDA/SCL nets and mixed manual/auto bus designs.

Files: `src/circuit_weaver/generational_repair.py`, `tests/test_generational_repair.py`

### T224. Tighten placement-readiness interface semantics (P2, MEDIUM)

- [x] Revisit orphan-interface detection so passive support parts do not satisfy “another block consumes this signal” for real interfaces.
- [x] Add targeted tests covering straps/bypass parts versus true inter-block consumers.
- [x] Re-check `I:/my_circuit/design.yaml` after the semantics change to separate real design blockers from modeling noise.

Files: `src/circuit_weaver/placement_readiness.py`, `tests/test_placement_readiness.py`

### T225. Consolidate compile-path duplication and warning debt (P3, MEDIUM)

- [x] Remove the dead duplicate `_synthesize_shared_net_interfaces()` implementation from `dispatcher.py` so `design_loader.py` remains the single owner.
- [x] Replace remaining `datetime.utcnow()` usage with timezone-aware UTC timestamps.
- [x] Register the `network` pytest marker to eliminate the current warning.

Files: `src/circuit_weaver/design_loader.py`, `src/circuit_weaver/dispatcher.py`, `src/circuit_weaver/confidence_dashboard.py`, `pyproject.toml`, tests

### T226. Add timeout-aware skill follow-ups for long-running workflows (P2, LOW)

- [x] Define explicit follow-up thresholds for long-running Circuit Weaver operations instead of allowing silent 30-minute waits.
- [x] Require the workflow skills to check status/logs/issues during long runs before assuming the wait is normal.
- [x] Keep the repo-local canonical skills and bundled shipped skills in sync for the timeout/follow-up guidance.

Files: `skills/circuit-weaver/SKILL.md`, `skills/design_wizard/SKILL.md`, bundled skill copies

### T227. Add canonical validate-output parsing guidance to workflow skills (P2, LOW)

- [x] Document that `validate` emits JSON to stdout by default in the current CLI.
- [x] Document that stderr must stay separate from stdout when parsing `validate` output.
- [x] Add a safe capture/parsing recipe so the agent does not invent broken `2>&1 | json.load(...)` wrappers.

Files: `skills/circuit-weaver/SKILL.md`, `skills/design_wizard/SKILL.md`, bundled skill copies

### Validation Follow-On Notes

- `I:/my_circuit/design.yaml` now re-validates without the old bogus `TIP_J2` / `RING_J2` connector artifacts or repeated `USB_DP_*` substitution noise.
- The current remaining summary is `1 structural`, `59 electrical`, `9 implementation`, and `59 placement_readiness`.
- The next product-side follow-on candidate is the `QSPI_SCLK` false-positive I2C pull-up classification exposed by that re-check; the remaining unresolved part/footprint issues are design-modeling gaps, not Sprint 51 regressions.

### Next Sprint Follow-Up

- Revisit agent compatibility for Codex, Claude, OpenCode, and Kilo after the next sprint.
- Recover any config fragments that were gitignored only as a temporary unblocker, and move product-critical compatibility defaults back under source control.
- Treat those configs as interface contracts, not user-local cache.

---

## Sprint 50 — Generic Builder Parity Cleanup (v0.30.5)

**Goal:** Close the remaining Sprint 49 data-driven generic-builder failures so the sample/corpus release gate can return to zero known hard failures.

### T215. Port sensor_frontend dual-rail power handling (P1, MEDIUM) ✅ DONE

- [x] Reproduce the INA128PA `sensor_frontend` failures from the current full-suite catalog.
- [x] Add regression coverage for dual-rail instrumentation amplifier power pins (`V_POS`, `V_NEG`) with no floating power pins.
- [x] Update the data-driven path with the smallest correct builder/generic mapping fix: `build_generic()` now honors explicit `pin_vpos`/`pin_vneg` metadata and `gnd_net`.
- [x] Run focused tests and update the failure catalog: focused T215 tests pass; full suite is now `983 passed, 18 failed, 1 skipped`.

Files: `src/circuit_weaver/subcircuits/topology_builders.py`, `tests/test_template_structure.py`, sample/corpus tests

### T216. Port shared I2C/SPI boundary nets for generic sensors (P1, MEDIUM) ✅ DONE

- [x] Reproduce the `iot_sensor_node`, `oled_display_module`, and bootstrap example boundary-port mismatches.
- [x] Add regressions for shared SDA/SCL/SPI nets and pull-up boundary naming.
- [x] Preserve custom net names rather than defaulting to `{PIN}_{REF}` for shared bus pins: `i2c_bus` now has a dedicated data-driven builder, and generic explicit SDA/SCL/SPI metadata maps to shared bus nets.
- [x] Run focused sample/presentation tests and update the failure catalog: T216-focused paths passed, with remaining corpus failure isolated to T217 battery support passives.

Files: `src/circuit_weaver/subcircuits/topology_builders.py`, `tests/test_presentation.py`, corpus tests

### T217. Port battery charger and fuel-gauge signal net contracts (P1, MEDIUM) ✅ DONE

- [x] Reproduce the `wearable_bms` and `battery_iot_sensor` failures.
- [x] Add regressions for PROG/CTG/CELL/SDA/SCL signal naming and required boundary ports.
- [x] Update data-driven builders/generic mappings without reintroducing legacy template classes: `battery_charger` and `battery_monitor` now generate the required programming, cell-sense, QSTRT, I2C, and support passive networks.
- [x] Run focused corpus and presentation checks: corpus hard-error gate now passes `9 passed`; T216/T217 regression set passes `13 passed`.

Files: `src/circuit_weaver/subcircuits/topology_builders.py`, `tests/test_generation_corpus.py`, `tests/test_presentation.py`

### T218. Close sample/corpus release gate (P1, MEDIUM) ✅ DONE

- [x] Run the full suite and 9-archetype corpus after T215–T217: full suite passes `1009 passed, 1 skipped, 6 warnings`; corpus hard-error gate passes `9 passed`.
- [x] Drive remaining pre-existing T180 failures to zero, or catalog any deliberately deferred failures with root cause and next task: no repo sample/corpus hard failures remain; focused sample/presentation/generation gate passes `38 passed`.
- [x] Run the `I:/my_circuit` validate/generate probe: validate still reports the external design's pre-existing 44 placement-readiness errors; generate is blocked by those same design connectivity issues before artifact emission.
- [x] Update `TASKS.md` and `CHANGELOG.md` with final Sprint 50 results.

Files: `tests/`, `samples/`, `TASKS.md`, `CHANGELOG.md`

---
