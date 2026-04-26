# Tasks

> Work only on what's listed here. Check boxes as completed, update CHANGELOG.md alongside.

## Sprint 41 — Resolver + Template UX Follow-ups (Released in v0.28.0) ✅ DONE

**Goal:** Kill two related failure modes surfaced by a user running the
design wizard on a novel IC (RP2040-based toy phone): (a) the symbol
resolver re-hitting remote APIs once per instance for the same
unresolvable MPN, and (b) `circuit-weaver register-ic` writing a pin map
that legacy topology templates silently ignore because they only consult
their hardcoded `*_IC_DATABASE` dict.

### 175. Cache negative resolver results within a process (P1, SMALL) ✅ DONE

A design with 12 identical buttons whose MPN isn't in any tier used to
hit the DigiKey / Mouser / EasyEDA / cache chain 12 separate times per
validate, adding ~12 seconds and 12 API quota hits. Once the first
lookup fails through all tiers, the answer is deterministic for the
rest of the process — there's no need to re-ask.

- [x] `SymbolResolver` adds a class-level `_unresolved_cache: set[str]`
  (matching the existing `_cred_warned` pattern). `resolve()` checks
  it at entry and returns `(None, "unresolved")` without touching
  tiers.
- [x] Class method `clear_unresolved_cache()` exposed for tests /
  long-running processes that want to retry after a transient flap.
- [x] Regression tests in `test_resolver_chain.py`:
  `test_unresolved_mpn_is_cached_within_process` (patches DigiKey
  loader with a call counter, asserts 1 call across 3 repeated
  lookups, plus clear-and-retry round-trip) and
  `test_unresolved_cache_does_not_shadow_successful_resolutions` so
  the cache never masks a hit on the same MPN.

Files: `src/circuit_weaver/symbol_resolver.py`,
`tests/test_resolver_chain.py`

### 176. Legacy topology templates honor `register-ic` pin maps (P0, MEDIUM) ✅ DONE

`circuit-weaver register-ic` writes to `ic_data/custom.json`, but four
legacy templates (`usb_controller`, `connector`, `usb_c_connector`,
`eeprom`) only consulted their own hardcoded `*_IC_DATABASE`. Users
who registered a new MPN got a misleading "Unknown …" error + silent
fallback to the template's default IC, so downstream net connectivity
flagged USB_DP dangling even though the registered IC had pin 43 →
USB_DP. Fixed by:

- [x] Each of the four templates now has a `_ic_db()` classmethod that
  returns `merge_into_legacy_db(LEGACY_DB, topology)` — same pattern
  `audio_amplifier`, `motor_driver`, `protection` already use.
  `validate_params` and `generate` switched to the merged DB.
- [x] `USBControllerTemplate.generate()` prefers `pin_usb_dp` /
  `pin_usb_dm` number fields from ic_data, falling back to the
  existing `pin.name == "D_P" / "D_N"` match AND adding `USB_DP` /
  `USB_DM` as accepted pin names (matches the naming used by
  `register-ic` JSON output and bundled misc.json entries).
- [x] Regression tests in `test_legacy_template_hotload.py`:
  `test_usb_controller_hotload_via_register_ic`,
  `test_usb_controller_generate_wires_registered_ic_usb_pins`
  (end-to-end: registered MCU's pin 43 → USB_DP net),
  `test_connector_hotload_via_register_ic`,
  `test_usb_c_connector_hotload_via_register_ic`,
  `test_eeprom_hotload_via_register_ic`.
- [x] Follow-up (Sprint 42): the remaining ~25 legacy templates with
  hardcoded DBs (buck, boost, ldo, can_transceiver, etc.) have the
  same structural bug. Migrating all of them is a bigger cleanup;
  this sprint scopes to the four that the user's toy-phone run
  actually hit.

Files: `src/circuit_weaver/subcircuits/usb.py`,
`src/circuit_weaver/subcircuits/connector.py`,
`src/circuit_weaver/subcircuits/usb_c_connector.py`,
`src/circuit_weaver/subcircuits/eeprom.py`,
`tests/test_legacy_template_hotload.py`

### 178. Drain every hardcoded `*_IC_DATABASE` dict into ic_data JSON (P1, LARGE) ✅ DONE

Completes the migration Task 176 started. Every IC pin map,
footprint, power rail table, and application field belongs in
`ic_data/*.json` — not in Python dicts baked into subcircuit
template modules. Eliminates the "user runs `register-ic`, template
silently ignores it" failure mode generally, not just for the four
templates Task 176 scoped to.

**Audit results** (84 ICs across 37 `*_IC_DATABASE` dicts in
`subcircuits/*.py`, bucketed against the current `ic_data/*.json`
view each template's `merge_into_legacy_db({}, topology)` returns):

- **Bucket A (55 ICs):** JSON matches hardcoded. Safe to drop
  from Python after migrating the template to the `_ic_db()`
  pattern.
- **Bucket B (19 ICs):** JSON diverges on template-specific scalar
  fields (`vdd_range`, `vin_range`, `supply_range`, `boot_straps`).
  Hardcoded is the source of truth — overwrite JSON.
- **Bucket C (10 ICs):** JSON entry has wrong topology
  (`AT25SF128A` → `component`, `BSS138` → `low_side`, `REF3030`
  → `series`, etc.), so the template's topology-filtered merge
  never sees them. Fix: change `topology` to the template's
  `template_type`, preserve the old value as `topology_subtype`.
- **Bucket D (0 ICs):** nothing net-new to add to JSON.

Work items:

- [x] Reconciled Bucket B + Bucket C values in `ic_data/*.json` via
  `scripts/migrate_hardcoded_ics_to_json.py` (one-shot; idempotent
  if re-run). Bucket C's old subtype (`low_side`, `high_side`,
  `series`, `shunt`, `buck`, `linear_sink`, `component`) is
  preserved as `topology_subtype`; templates that used to dispatch
  on `ic_db["topology"]` now read `ic_db["topology_subtype"]`
  (`mosfet_switch`, `voltage_reference`, `led_driver`).
- [x] Deduped 8 MPNs that lived in two JSON files — kept the
  version with the specific topology (`eeprom`, `connector`,
  `logic`, `led`, `diode`), removed the generic `component`
  duplicate so the topology-filtered merge resolves cleanly.
- [x] Added `LegacyDBProxy` in `subcircuits/base.py`: dict-like
  view backed by a live `merge_into_legacy_db({}, topology)` call.
  Templates' module-level `XYZ_IC_DATABASE` variables now bind to a
  proxy — method bodies that read `db[key]`, `db.get(key)`,
  `key in db`, or `db.keys()` continue to work without edits.
  `register_ic()` calls are visible on the next read without an
  `importlib.reload`.
- [x] Converted all 38 hardcoded `*_IC_DATABASE` dicts across 35
  template files: 8 templates that already had `_ic_db()` classmethods
  (`audio_amplifier`, `connector`, `eeprom`, `motor_driver`,
  `protection`, `usb` x2, `usb_c_connector`) now start from an
  empty dict; the remaining 30 bind their module-level name to a
  `LegacyDBProxy`.
- [x] `tests/test_template_smoke.py`: 74 tests iterating every
  template in the default registry, asserting (a) merged IC
  database is non-empty, (b) `generate()` returns at least one
  ComponentDef with pins. Covers the 28+ templates the 9-archetype
  corpus doesn't exercise.
- [x] Full suite: **825 passed, 1 skipped, 0 failed** (baseline
  751; +74 smoke tests).

Files: `src/circuit_weaver/subcircuits/base.py`,
every `src/circuit_weaver/subcircuits/*.py` that carried a
`*_IC_DATABASE` dict, `src/circuit_weaver/ic_data/*.json`,
`tests/test_template_smoke.py` (new),
`scripts/migrate_hardcoded_ics_to_json.py` (new, one-shot).

---

### 177. Placement preview PCB uses KiCad's fixed layer hash (P1, SMALL) ✅ DONE

The layout-hint board `${project}/output/*_placement.kicad_pcb` opened
in KiCad 10 with:

`error loading pcb: Layer ECO1.User at line 16 is not fixed layer hash`

Root cause: `pcb_export.py` was still emitting a KiCad-5-era hardcoded
layer table (`B.Cu=31`, `ECO1.User`, `ECO2.User`, no `User.1-User.4`),
but KiCad 10 validates the fixed-layer hash against its canonical
2-layer map and rejects the file before loading footprints.

- [x] `pcb_export._LAYERS` updated to KiCad's current fixed 2-layer
  ids/names (`B.Cu=2`, `Eco1.User`, `Eco2.User`, `User.1-User.4`,
  etc.), matching a board written by KiCad 10.
- [x] Regression test in `test_pcb_preview_invariants.py` asserts the
  preview board contains the KiCad fixed-layer markers and explicitly
  rejects the legacy `B.Cu=31` / `ECO1.User` spellings that caused the
  loader failure.
- [x] Manual verification: the generated preview board now round-trips
  through KiCad 10 CLI export instead of failing with `Failed to load board`.

Files: `src/circuit_weaver/pcb_export.py`,
`tests/test_pcb_preview_invariants.py`

---

## Legacy Template Migration Backlog (Tasks 179–185)

**Goal:** Replace the 35 legacy Python `*Template` classes in
`subcircuits/` with the data-driven path (`DataDrivenTemplate` +
`topology_builders.py` + `ic_data/*.json`). The IC dictionaries were
drained to JSON in Sprint 41 (Task 178); the generation code path has
not been changed yet — the registry still resolves legacy-first, so
`DataDrivenTemplate` never fires for any registered topology.

**Completion state of each phase is gated on the previous phase.**
Do not skip the audit (179) or the priority flip (180) — downstream
deletion tasks assume both are done.

---

### 179. Audit: per-template verdict table (P1, MEDIUM)

Research task. No code changes. Produces the decision table that
gates tasks 181–184.

For each of the 35 legacy templates:
1. Instantiate the legacy template and call `generate()` on a real IC
   from its merged `_ic_db()`. Record: component count, component
   types, passive values, net assignments.
2. Instantiate `DataDrivenTemplate(template_type=topo)` backed by the
   same IC and call `generate()` via `topology_builders.get_builder()`.
   Record the same fields.
3. Classify:
   - **A — Delete safe:** outputs are equivalent within 5% on passive
     values; no topology-specific passive calculation in legacy
     `generate()` that `build_generic` doesn't replicate.
   - **B — Port first:** legacy `generate()` has custom pin-wiring or
     passive calculation not present in any builder; must add a
     topology-specific builder function before deleting.
   - **C — Complex:** 400+ line template with multiple IC sub-modes
     (e.g. `usb.py` handles both `usb_controller` and `usb_hub`); plan
     as a dedicated task per topology.

- [ ] Run audit across all 35 templates; write verdict table to
  `docs/legacy_template_audit.md` with columns: template file,
  topology, line count, verdict (A/B/C), notes on custom logic to port.
- [ ] Flag any template whose `generate()` references fields not yet
  present in the IC data JSON (would cause silent regression if
  deleted before the JSON is updated).

Files: `docs/legacy_template_audit.md` (new, research output only)

---

### 180. Flip registry resolution order (P1, SMALL)

Depends on: 179 (audit complete — no surprises before flipping).

The current `SubcircuitRegistry.get()` checks legacy `_templates` dict
first; `DataDrivenTemplate` only fires for topologies with no legacy
class registered. Flip the order: data-driven first, legacy as
fallback. This is the minimal change that activates the new path
without deleting anything.

- [ ] In `SubcircuitRegistry.get()`: call `_get_data_driven()` first;
  if it returns a template, use it. Fall through to `_templates` only
  if ic_data returns nothing for that topology.
- [ ] Add test asserting a topology that has ic_data JSON entries uses
  `DataDrivenTemplate`, not the legacy class, after the flip.
- [ ] Confirm full test suite passes with no changes to legacy
  templates (legacy path now only fires when ic_data has no entries,
  which should not happen for any topology after Task 178).

Files: `src/circuit_weaver/subcircuits/base.py`,
`tests/test_template_structure.py`

---

### 181. Delete specialized topology legacy classes (P1, MEDIUM)

Depends on: 179, 180.

The four topologies with dedicated builders in `topology_builders.py`
(`buck` → `build_switching_regulator`, `boost` →
`build_switching_regulator`, `buck_boost` →
`build_switching_regulator`, `ldo` → `build_linear_regulator`) are the
lowest-risk deletions. The builder logic already exists; this task
verifies parity then removes the dead files.

- [ ] Write output-parity tests for each topology: call
  `DataDrivenTemplate.generate()` and legacy `XTemplate.generate()`
  on the same IC+params; assert component count matches, passive
  values agree within 5%, and all net assignments are identical.
- [ ] Fix any gaps in `topology_builders.py` uncovered by the parity
  tests (e.g. a passive net or boundary port the legacy class emits
  that `build_switching_regulator` doesn't).
- [ ] Remove `buck.py`, `boost.py`, `buck_boost.py`, `ldo.py` from
  `subcircuits/`. Remove their imports and `reg.register()` calls from
  `_build_default_registry()`.
- [ ] Remove the four classes from the existing legacy smoke tests;
  confirm smoke suite still passes.

Files: `subcircuits/buck.py`, `subcircuits/boost.py`,
`subcircuits/buck_boost.py`, `subcircuits/ldo.py` (deleted),
`subcircuits/base.py`, `subcircuits/topology_builders.py`,
`tests/test_template_parity_switching.py` (new),
`tests/test_template_parity_linear.py` (new)

---

### 182. Port and delete thin generic templates (P2, MEDIUM)

Depends on: 179, 180. Can run after 181 in parallel.

Audit verdict-A templates — those where `build_generic` already
produces equivalent output and the legacy `generate()` has no custom
passive calculation. Expected members (confirm against audit):
`protection.py`, `connector.py`, `mosfet_switch.py`,
`wireless_module.py`, `rtc.py`, `battery_charger.py`,
`battery_monitor.py`, `charge_pump.py`, `voltage_reference.py`,
`can_transceiver.py`, `rs485_transceiver.py`, `crystal_oscillator.py`,
`driver.py` (gate_driver + level_shifter).

For each:
- [ ] Write a parity test (same pattern as 181).
- [ ] If any verdict-A template turns out to have non-trivial logic
  (audit miss), move it to task 183 rather than forcing it here.
- [ ] Delete the template file; remove from `_build_default_registry()`.

Files: ~13 template files (deleted), `subcircuits/base.py`,
`tests/test_template_parity_generic_thin.py` (new)

---

### 183. Port and delete medium generic templates (P2, LARGE)

Depends on: 179, 180, 182.

Audit verdict-B templates where custom wiring logic must be ported to
`topology_builders.py` before deletion. Expected members (confirm
against audit): `opamp.py`, `spi_bus.py`, `sensor_frontend.py`,
`power_mux.py`, `ethernet.py`, `clock.py`, `eeprom.py`,
`audio_amplifier.py`, `display_driver.py`, `usb_c_connector.py`.

For each:
- [ ] Extract the topology-specific logic from `generate()` into a new
  builder function `build_<topology>()` in `topology_builders.py`; add
  it to `TOPOLOGY_BUILDERS`.
- [ ] Write parity test.
- [ ] Delete legacy file; remove from `_build_default_registry()`.

Files: ~10 template files (deleted), `subcircuits/topology_builders.py`,
`subcircuits/base.py`, `tests/test_template_parity_generic_medium.py` (new)

---

### 184. Port and delete complex generic templates (P2, LARGE)

Depends on: 179, 180, 183.

Audit verdict-C templates — the large, multi-mode files. Work each as
a sub-item:

- [ ] `usb.py` (536 L, two topologies: `usb_controller` + `usb_hub`):
  port both modes to `topology_builders.py`; preserve the
  `pin_usb_dp`/`pin_usb_dm` wiring logic that Sprint 41 fixed.
- [ ] `adc.py` (523 L): port; verify differential-input and SAR/sigma-
  delta mode variants produce correct pin wiring.
- [ ] `motor_driver.py` (477 L): port; H-bridge vs single-half-bridge
  variants; verify direction/enable/PWM net assignments.
- [ ] `dac.py` (467 L): port; verify reference/output net wiring.
- [ ] `current_sense.py` (467 L): port; verify sense resistor value
  calculation and Rsense net assignments.
- [ ] `led_driver.py` (405 L): port; verify `topology_subtype`
  dispatch (Task 178 introduced this field; builder must read it).
- [ ] `relay_driver.py` (399 L): port; coil/flyback/contact net wiring.
- [ ] `i2c_bus.py` (394 L): port; pull-up network and bus topology.

For each sub-item: parity test → port → delete → remove from registry.

Files: 8 template files (deleted), `subcircuits/topology_builders.py`,
`subcircuits/base.py`, `tests/test_template_parity_generic_complex.py` (new)

---

### 185. Final cleanup (P1, SMALL)

Depends on: 181, 182, 183, 184 (all legacy templates deleted).

- [ ] Remove `_build_default_registry()` from `base.py`. Remove the
  `DEFAULT_REGISTRY` global and `get_default_registry()` lazy-loader;
  callers receive a plain `SubcircuitRegistry` seeded only by
  `DataDrivenTemplate` on first lookup.
- [ ] Update the 3 import sites that currently pull from the legacy
  registry: `dispatcher.py`, `api.py`, `project_spec.py`. Remove
  `BoundaryPort` imports if they're no longer needed; keep
  `SubcircuitRegistry` and `SubcircuitResult` (still used).
- [ ] Rewrite `tests/test_legacy_template_hotload.py` →
  `tests/test_data_driven_hotload.py`. The invariant being tested
  (`register_ic()` makes a new IC visible to generation) must be
  preserved; the test now calls `DataDrivenTemplate.generate()`
  instead of the legacy class's `generate()`. Delete the legacy file.
- [ ] Delete `subcircuits/topology_builders.py` is NOT part of this
  task — it becomes the primary generation code path and stays.
- [ ] `subcircuits/__init__.py`: remove re-exports of now-deleted
  symbols; keep `SubcircuitRegistry`, `SubcircuitResult`,
  `SubcircuitTemplate` (base class still needed for
  `DataDrivenTemplate`).
- [ ] Confirm: `py -m pytest --tb=short -q` passes with no legacy-
  path test failures.

Files: `subcircuits/base.py`, `subcircuits/__init__.py`,
`src/circuit_weaver/dispatcher.py`, `src/circuit_weaver/api.py`,
`src/circuit_weaver/project_spec.py`,
`tests/test_legacy_template_hotload.py` (deleted),
`tests/test_data_driven_hotload.py` (new)

---

## Sprint 40 — Generation Quality Regression Repair (v0.27.0)

**Goal:** Repair regressions introduced while building out the dynamic IC
designer, placement pipeline, and schematic density work. A user-shared
generation output (IoT air-quality sensor) surfaced failure modes that are
not design-specific — cache-stub poisoning, strap double-emission, fabricated
PCB footprints, and reports claiming features the schematic doesn't contain —
so every fix must generalize across circuit archetypes (IoT, motor/toy, SBC,
inverter, wearable) and land behind regression coverage that prevents the next
wave of generator improvements from silently breaking these subsystems again.

---

### 169. Cache rebuild must produce real symbols, not 2-pin stubs (P0, MEDIUM) ✅ DONE

`SymbolResolver._rebuild_from_cache` previously emitted every cached MPN as
a 2-pin passive stub with `pinout_source="explicit"`, bypassing the
validator's existing `pinout-source` gate. Fixed by (a) marking cache
rebuilds without pin data as `pinout_source="stub"` so the validator fails
closed, and (b) extending `SymbolCache.put()` + adding
`component_def_to_cache_payload()` so loaders with real pin topology
(EasyEDA) persist full data and rebuild as trusted on the next session.

- [x] `symbol_resolver.py` no longer silently emits routed 2-pin passives
  for multi-pin cached parts — stubs are flagged with
  `pinout_source="stub"` so the existing `pinout-source` validator rejects
  them.
- [x] `symbol_cache` entries now carry pins, pin_nets, power_pins,
  power_reqs, bypass_caps, straps, and explicit_no_connects when the caller
  supplies them (versioned as `_schema_version: 2`). Legacy entries still
  parse cleanly as stubs.
- [x] EasyEDA resolver tier caches via `component_def_to_cache_payload()`
  so full pin topology round-trips across sessions.
- [x] Tests: cache-without-pins marks component stub, cache-with-full-pins
  is trusted with round-tripped power_pins, stub rebuild triggers the
  `unverified-pinout` validator error.

Files: `src/circuit_weaver/symbol_resolver.py`,
`src/circuit_weaver/symbol_cache.py`, `tests/test_resolver_chain.py`

Files: `src/circuit_weaver/symbol_resolver.py`,
`src/circuit_weaver/symbol_cache.py`, `src/circuit_weaver/validator.py`,
`tests/test_resolver_chain.py`, `tests/test_symbol_cache.py`

---

### 170. Eliminate double-emission in strap/support placer (P0, MEDIUM) ✅ DONE

Fixed by instituting a hard invariant in `primitives.assemble_sheet` —
structural duplicates are deduped before emission, and a test module
`test_schematic_invariants` runs the same invariants from outside so any
future placer/topology-dispatcher regression shows up as a test failure.
Root-cause search in the 1522-line placer deferred to follow-up work;
current fix guarantees the on-disk schematic is always internally
consistent regardless of where upstream duplication was introduced.

- [x] `primitives._dedupe_sheet_elements` now dedupes instances by
  `(lib_id, ref, at)` + UUID, wires by sorted endpoints, labels by
  `(kind, text, at)`, no-connects + junctions by `(at)`.
- [x] Two distinct refs at the same coordinate are preserved — that's an
  overlap bug for the placer to flag, not a reason to silently drop a
  component.
- [x] `tests/test_schematic_invariants.py` exposes
  `assert_schematic_invariants(sch_text)` for reuse by the Sprint 40
  corpus runner (Task 174).
- [x] Reproducer built from the user-reported IoT AQ sensor symptom is
  detected by the invariant runner — test fails loudly if the invariant
  ever stops catching it.

Follow-up (deferred): root-cause the doubled emission in `placer.py` /
`_apply_topology_*` so duplicates don't need to be cleaned up at assembly
time. Tracked as a backlog item; current dedup is the shipping safety net.

Files: `src/circuit_weaver/primitives.py`,
`tests/test_schematic_invariants.py`

Files: `src/circuit_weaver/placer.py`, `src/circuit_weaver/generator.py`,
`tests/test_placer.py`, `tests/test_schematic_invariants.py` (new)

---

### 171. Placement PCB emits real footprints or no pads — never fabricated ones (P0, MEDIUM) ✅ DONE

Root cause: `pcb_export._footprint_sexpr` fell back to
`Package_SO:SOIC-8_3.9x4.9mm_P1.27mm` whenever a component had no
`footprint` binding AND synthesized two 1.27-pitch SMD pads for every
footprint regardless of the part's real pad count. This produced
physically-misleading geometry — ESP32-S3-WROOM-1 modules with 2 pads,
LEDs / switches / sensors silently wearing SOIC-8 outlines.

The placement `.kicad_pcb` is a layout *preview*, not a fabrication
artifact. Real pads come from KiCad's forward-annotation pass after the
user opens the generated schematic. Fixed by:

- [x] Never fabricate a SOIC-8 fallback. Missing footprint bindings emit
  `Placement_Preview:Missing_<ref>` placeholders so reviewers can't
  mistake them for a real part.
- [x] Never emit synthetic pads. Whichever footprint lands in the file,
  zero pads are synthesized — KiCad's forward-annotation is authoritative.
- [x] The `(generator ...)` field now reads
  `"schematic_engine placement_preview"` so downstream tooling can
  distinguish preview PCBs from fab-ready ones.
- [x] `tests/test_pcb_preview_invariants.py` — three tests: no SOIC-8
  fallback, no synthetic pads on any footprint, generator field
  self-identifies.

Files: `src/circuit_weaver/pcb_export.py`,
`tests/test_pcb_preview_invariants.py`

Files: `src/circuit_weaver/kicad_placement_api.py`,
`src/circuit_weaver/generator.py`, `src/circuit_weaver/pcb_export.py`,
`tests/test_kicad_placement_api.py`, `tests/test_pcb_invariants.py` (new)

---

### 172. Report and downstream artifacts describe only what was emitted (P0, SMALL) ✅ DONE

Added `report.verify_report_fidelity(report_text, components)` — a
diagnostic that scans any report text for references to component refs,
net names, and component-embedded annotations that don't exist in the
resolved design. Catches the IoT AQ audit pattern where the report
claimed "BME688 I2C + pull-ups" and "LED + current-limit R4" without
any backing wires.

- [x] Regex-based scanner detects ghost refs (`U2`, `R4`, `LED1`), ghost
  nets (`VBAT`, `SWDIO`, `SDA`, `SWCLK`, etc.), and ghost annotations
  (claims naming a ref that isn't on any component in the design).
- [x] Five tests cover: clean report passes, ghost refs caught, ghost
  nets caught, annotation-level ghost claims caught, and the
  reconstructed IoT AQ audit scenario.
- [x] Diagnostic today; adopting as a generate-time gate is a follow-up
  once the Sprint 40 corpus confirms no template currently trips it.

Files: `src/circuit_weaver/report.py`, `tests/test_report_fidelity.py`

Files: `src/circuit_weaver/report.py`, `src/circuit_weaver/design_ir.py`,
`src/circuit_weaver/generator.py`, `tests/test_report_fidelity.py` (new)

---

### 173. `generate` honors every validator category consistently across runs (P1, SMALL) ✅ DONE

Root cause: `dispatcher.generate_artifacts` had a single `require_valid`
gate that bypassed ALL validation categories at once. `--no-require-valid`
(intended to let users skip soft electrical warnings while iterating)
silently let hard structural + implementation errors through too — which
is how the IoT AQ audit ended up with 4 `missing-footprint` errors in
`validation_report.json` but still writing artifacts to disk.

Split the gate into two tiers:

- [x] `structural` + `implementation` category errors ALWAYS raise,
  regardless of `require_valid`. The error message explicitly tells the
  user these are not bypassable.
- [x] `--no-require-valid` now only bypasses soft electrical warnings, and
  the bypass is logged at WARNING level so the user sees what was
  ignored.
- [x] Deterministic-verdict test: two runs on the same fake validator
  state hit the same outcome.
- [x] Four tests covering both bypass paths and default behavior.

Files: `src/circuit_weaver/dispatcher.py`,
`tests/test_generate_enforcement.py`

Files: `src/circuit_weaver/dispatcher.py`,
`src/circuit_weaver/validator.py`, `tests/test_generate_enforcement.py` (new)

---

### 174. Diverse-circuit regression corpus + generation invariants (P1, LARGE) ✅ DONE

Leveraged the existing `samples/` directory (9 committed sample projects)
as the corpus source instead of inventing new fixtures. Five archetypes
cover the breadth goal:

- [x] **LED power indicator** — discrete LED + current-limit + divider
- [x] **IoT sensor node** — I2C + MCU + sensor bus
- [x] **Motor controller** — H-bridge + motor driver
- [x] **USB UART bridge** — USB + regulator + bridge IC
- [x] **FPGA power carrier** — multi-rail power tree + FPGA
- [x] Each runs `generate_artifacts` end-to-end and asserts the three
  generation invariants: no schematic structural duplicates (Task 170),
  no ghost IC refs in the report (Task 172), no cache-stub regressions
  (Task 169 via the `pinout-source` validator).
- [x] Test module `tests/test_generation_corpus.py` uses pytest
  parametrize so new archetypes drop in with one-line additions. A
  separate guard test asserts the corpus never drops below 5.
- [x] Full suite: **737 passed, 1 skipped, 0 failed** in 100s,
  including all six corpus cases (16s of it).

Follow-up archetypes to add as user reports surface: inverter (gate
driver + high-side + isolation), wearable (coin cell + BMS + E-ink),
RF chain (LNA + mixer + IF), high-voltage (mains + safety isolation).

Files: `tests/test_generation_corpus.py`

Files: `tests/fixtures/sprint40_corpus/` (new),
`tests/test_generation_corpus.py` (new), `pyproject.toml` (CI wiring)

---

## Sprint 39 — Research Workflow Compatibility (Unreleased) ✅ DONE

**Goal:** Keep Step 2 IC research reliable across Codex / Claude / OpenCode by
avoiding delegated research-agent paths that can fail with model conflicts.

### 167. Keep IC research in the current agent session (P1, SMALL) ✅ DONE

- [x] `skills/circuit-weaver/SKILL.md` now tells agents to keep Step 2 research
  in the current session, avoid spawning a dedicated research worker, and fall
  back to native web tooling when a premium path delegates or conflicts.
- [x] `skills/design_wizard/SKILL.md`, `README.md`, and `docs/user_workflow.md`
  now describe `/circuit-weaver` as same-agent orchestration with backend
  fallback behavior instead of a spawned research-agent workflow.
- [x] User-facing CLI/help strings no longer refer to `/research` calls or a
  `research-analyst` implementation, and regression tests guard the updated
  prompt language.

Files: `skills/circuit-weaver/SKILL.md`, `skills/design_wizard/SKILL.md`, `README.md`, `docs/user_workflow.md`, `src/circuit_weaver/dispatcher.py`, `src/circuit_weaver/design_logger.py`, `src/circuit_weaver/research.py`, `src/circuit_weaver/research_store.py`, `tests/test_research_backend.py`

### 168. Add fast vs normal research depth selector (P1, SMALL) ✅ DONE

- [x] `design-wizard` now accepts `--research-depth {fast,normal}` and persists
  the effective depth into `metadata.research_depth` plus the initial
  `design.log` entry.
- [x] `CIRCUIT_WEAVER_RESEARCH_DEPTH` and `circuit-weaver doctor` now expose the
  active depth setting alongside the backend.
- [x] The Circuit Weaver workflow docs now treat `fast` as a reduced-query
  latency profile and `normal` as the existing fuller research pass.

Files: `src/circuit_weaver/research.py`, `src/circuit_weaver/dispatcher.py`, `src/circuit_weaver/doctor.py`, `skills/circuit-weaver/SKILL.md`, `skills/design_wizard/SKILL.md`, `README.md`, `docs/user_workflow.md`, `tests/test_research_backend.py`

## Sprint 37 — Observability, Research Pipeline & Resolver Polish (v0.26.0) ✅ DONE

**Goal:** Turn the v0.25.0 resolver into something users can trust end-to-end — visible credentials diagnostics, persistent research output, hermetic regression coverage of the full chain, and a finished data-driven template migration.

Three categories bundled into one minor-version release:
- **Observability** (Tasks 156, 159) — users can see what the engine is doing, which tiers fired, and why some skipped.
- **Research pipeline** (Tasks 160, 161) — structured, persisted research output with a backend selector (sonar-pro vs. standard WebSearch).
- **Resolver polish** (Tasks 157, 158) — end-to-end integration coverage + complete the Sprint 34 data-driven migration.

---

### 156. Resolver credential visibility (P1, SMALL) ✅ DONE

When a SymbolResolver tier skips because its env vars aren't set, log one clear INFO line instead of silently falling through.

- [ ] `_resolve_digikey` / `_resolve_mouser` / `_resolve_easyeda` emit a single `logging.info` line the first time they're skipped per session: `"DigiKey tier skipped: DIGIKEY_CLIENT_ID not set. Run 'circuit-weaver doctor' to configure."`
- [ ] De-dupe so multi-component runs don't spam the same message N times (module-level flag or `functools.lru_cache`).
- [ ] `doctor` already surfaces credential status — cross-link in the skip message.

Files: `src/circuit_weaver/symbol_resolver.py`, `src/circuit_weaver/doctor.py`, `tests/test_resolver_chain.py`

---

### 157. Resolver end-to-end integration test (P1, MEDIUM) ✅ DONE

Lock in the user-reported Zigbee sensor flow as a hermetic test so v0.24.x-style resolver regressions never ship again.

- [ ] Write `tests/test_resolver_e2e.py` with a minimal YAML containing `SHT41-AD1B-R2`, `SGP40-D-R4`, `nRF52840` (mix of MPNs that should resolve via ic_data, DigiKey, and stub-with-reason).
- [ ] Mock the DigiKey HTTP layer (use `responses` or `httpx-mock`; prefer `responses` since the DigiKey loader uses `requests`).
- [ ] Assert: (a) no component falls back to a generic stub when a tier should have caught it, (b) diagnostic log mentions which tier resolved each MPN, (c) when all tiers fail, the stub reason enumerates all 7 tiers.
- [ ] Test runs under ~1 second with no network.

Files: `tests/test_resolver_e2e.py` (new), possibly `pyproject.toml` (add `responses` to dev deps if needed)

---

### 158. Migrate legacy templates to data-driven path (P2, MEDIUM) ✅ DONE

Close the Sprint 34 footnote: `audio_amplifier.py`, `motor_driver.py`, `protection.py` still have hardcoded Python dicts even though their ICs are now in `ic_data/`. Migrate + dedupe.

- [ ] Add parity tests comparing legacy class output to the data-driven builder output for each representative IC (PAM8302A, DRV8833, SMBJ5.0A).
- [ ] Delete hardcoded `*_IC_DATABASE` dicts once parity is verified.
- [ ] Register legacy class names as aliases so existing YAML `type: audio_amplifier` continues to work via `DataDrivenTemplate`.
- [ ] Update CHANGELOG "Follow-up" item from v0.24.0 → mark resolved.

Files: `src/circuit_weaver/subcircuits/audio_amplifier.py`, `motor_driver.py`, `protection.py`, `base.py`, `tests/test_template_structure.py`

---

### 159. Workflow-level logging hardening (P0, MEDIUM) — user-reported ✅ DONE

**User report:** `i:\my_circuit\zigbee_air_sensor\output\circuit-weaver.log` is weak — no workflow step markers, no visible log-level messages, barely populated.

Root causes identified:
- `init_logging()` only called from `generate_artifacts()` — `validate`, `confidence`, `simulate`, `erc`, `cost-bom` don't create a log.
- Many key modules use `_logger.debug()` for events that should be `info()`.
- No explicit "Workflow Step N: …" markers in the log.

- [ ] Move `init_logging()` invocation up to the CLI dispatcher so every subcommand that operates on an output dir gets a log.
- [ ] Add a `log_workflow_step(step, message)` helper to `design_logger.py` + Python-side INFO log; instrument the top of each major CLI handler (validate, generate, confidence, simulate, erc, cost-bom, export-*).
- [ ] Audit `_logger.debug(...)` calls in resolver, validator, generator, spice_runner, erc_runner — promote user-visible events to `info`; keep byte-level trace at debug.
- [ ] Ensure the `circuit-weaver` root logger is at `INFO` by default (debug via `CIRCUIT_WEAVER_LOG_LEVEL=DEBUG` env var).
- [ ] Document the log locations in README + `docs/user_workflow.md`.
- [ ] Regression test: run `circuit-weaver validate <yaml> -o <dir>` and assert `<dir>/circuit-weaver.log` exists, mentions "Workflow Step", has at least one INFO-level entry per major module.

Files: `src/circuit_weaver/dispatcher.py`, `src/circuit_weaver/logging_bridge.py`, `src/circuit_weaver/design_logger.py`, `src/circuit_weaver/validator.py`, `src/circuit_weaver/generator.py`, `src/circuit_weaver/spice_runner.py`, `src/circuit_weaver/erc_runner.py`, `README.md`, `docs/user_workflow.md`, `tests/test_logging_workflow.py` (new)

---

### 160. Persist research output to project directory (P0, MEDIUM) — user-reported ✅ DONE

**User report:** `research-analyst` runs but produces no artifacts in the project dir — users can't see what was researched, what citations were consulted, or reproduce the findings.

- [ ] Every research call (via the `/research` skill or `research-analyst` agent) writes to `{output_dir}/research/`:
  - `{topic-slug}.json` — structured result: query, backend used, citations, summary, timestamp
  - `{topic-slug}.md` — human-readable rendering
  - `summary.md` — rolling index of all research runs for this project
- [ ] `design.log` entry references the `{topic-slug}.json` file path so the full chain is reproducible.
- [ ] Update `skills/circuit-weaver/SKILL.md` Step 2 to instruct the agent to dump research output via `circuit-weaver log-event --type research --file <path.json>` (or a new `save-research` subcommand).
- [ ] Document in README that `output/research/` is the single source of truth for how ICs were chosen.

Files: `src/circuit_weaver/dispatcher.py` (new `save-research` or extend `log-event`), `src/circuit_weaver/design_logger.py`, `skills/circuit-weaver/SKILL.md`, `agents/research-analyst.md`, `README.md`

---

### 161. Research backend selector (sonar-pro vs standard) (P1, SMALL) — user-reported ✅ DONE

**User report:** user wants to choose between Perplexity sonar-pro (paid, high-quality) and standard Claude WebSearch/WebFetch (free) for research runs.

- [ ] Add `--research-backend {sonar-pro,standard,auto}` to any CLI command that spawns research, plus env var `CIRCUIT_WEAVER_RESEARCH_BACKEND`.
- [ ] `auto` (default) uses sonar-pro if `PERPLEXITY_API_KEY` is set, otherwise standard.
- [ ] `skills/circuit-weaver/SKILL.md` Step 2 reads the backend and invokes either `/research` (sonar-pro path) or Claude's native WebSearch tool.
- [ ] `research-analyst` agent prompt updated to respect the backend choice.
- [ ] `doctor` reports the selected backend + whether Perplexity creds are configured.

Files: `src/circuit_weaver/dispatcher.py`, `src/circuit_weaver/doctor.py`, `skills/circuit-weaver/SKILL.md`, `agents/research-analyst.md`

---

### 162. CHANGELOG + version bump for v0.26.0 (P1, XS) ✅ DONE

- [ ] Add `## [0.26.0] - YYYY-MM-DD` entry summarising Sprints 37.
- [ ] Bump `__version__` to 0.26.0 in `pyproject.toml`, `__init__.py`, `tests/test_bootstrap.py`.
- [ ] Tag + push to trigger PyPI release.

Files: `CHANGELOG.md`, `pyproject.toml`, `src/circuit_weaver/__init__.py`, `tests/test_bootstrap.py`

---

## Sprint 38 — Review Follow-up Hardening (v0.26.1) ✅ DONE

**Goal:** Close the medium/high gaps found while reviewing Sprint 36-37 before the next release cut.

### 163. Resolver credential checks honor shared loader state (P1, SMALL) ✅ DONE

- [x] `SymbolResolver` now checks credentials through the shared `_get_credential()` path instead of raw env vars.
- [x] DigiKey requires both `DIGIKEY_CLIENT_ID` and `DIGIKEY_CLIENT_SECRET` before the tier runs.
- [x] Mouser skip detection now honors `MOUSER_SEARCH_API_KEY` from `secrets.env` as well as env vars.

Files: `src/circuit_weaver/symbol_resolver.py`, `tests/test_resolver_chain.py`

### 164. Doctor surfaces actionable resolver credential status (P1, SMALL) ✅ DONE

- [x] `circuit-weaver doctor` now reports DigiKey and Mouser credential configuration as optional checks.
- [x] Task 156 skip messages now point to a diagnostic command that actually shows the missing credentials.

Files: `src/circuit_weaver/doctor.py`, `tests/test_doctor.py`

### 165. Research artifacts are traceable from design.log (P1, SMALL) ✅ DONE

- [x] `DesignLogger.log_research()` records backend + canonical artifact path when available.
- [x] `save-research` writes those fields into the matching `design.log` entry for reproducibility.

Files: `src/circuit_weaver/design_logger.py`, `src/circuit_weaver/research_store.py`, `src/circuit_weaver/dispatcher.py`, `tests/test_research_store.py`

### 166. Backend selector wired into the agent workflow docs (P1, SMALL) ✅ DONE

- [x] `design-wizard --research-backend` now persists the effective backend into scaffold metadata and the first design-log step.
- [x] `skills/circuit-weaver/SKILL.md` now tells Codex / Claude / OpenCode how to honor `sonar-pro` vs `standard`.
- [x] `README.md` now documents `output/research/` as the source of truth and shows `save-research`.

Files: `src/circuit_weaver/dispatcher.py`, `skills/circuit-weaver/SKILL.md`, `README.md`, `tests/test_research_backend.py`

---

## Sprint 35 — Install-UX Hardening & Platform Parity (v0.25.0) ✅ DONE

**Goal:** Close the three P0 footguns identified in the v0.24.x review — silent overwrite of curated user skills, bundled-skill drift vs repo, and zero Windows CI coverage. Keeps `pip install circuit-weaver && circuit-weaver install-skills` safe to recommend.

### 147. install-skills collision protection (P0, MEDIUM) ✅ DONE

- [x] `_copy_skill()` hashes existing destination `SKILL.md` and skips mismatches by default
- [x] `install_skills()` gained `force`, `backup`, `dry_run` params; result dict exposes `skills_skipped` / `skills_unchanged`
- [x] `install-skills` CLI parser adds `--force`, `--backup`, `--dry-run`; handler prints skipped entries to stderr
- [x] README quick-start + `docs/agent-platforms.md` document the collision matrix and flags
- [x] 11 regression tests in `tests/test_skill_installer.py`

Files: `src/circuit_weaver/skill_installer.py`, `src/circuit_weaver/dispatcher.py`, `tests/test_skill_installer.py`, `README.md`, `docs/agent-platforms.md`

### 148. Bundle all skills + CI drift guard (P0, MEDIUM) ✅ DONE

- [x] `scripts/sync_bundled_skills.py` mirrors `skills/` → `_bundled_skills/` with a `--check` mode
- [x] Bundled tree seeded with all 11 workflow skills, byte-identical to source
- [x] `bundled-skills` CI job runs `--check` on every push
- [x] `.pre-commit-config.yaml` adds `sync-bundled-skills` hook
- [x] `test_bundled_skills_parity_with_repo_skills` covers the invariant at pytest time

Files: `scripts/sync_bundled_skills.py`, `src/circuit_weaver/_bundled_skills/**`, `.github/workflows/ci.yml`, `.pre-commit-config.yaml`, `tests/test_skill_installer.py`

### 149. Windows CI leg (P0, SMALL) ✅ DONE

- [x] `ci.yml` matrix now includes `windows-latest` / Python 3.12
- [x] Non-blocking smoke subset runs `test_cli_commands`, `test_cli_new_commands`, `test_doctor`, `test_skill_installer` + `python -m circuit_weaver --version`
- [x] Existing Linux Python 3.10–3.13 legs remain blocking

Files: `.github/workflows/ci.yml`

### 150. CHANGELOG + release notes for v0.25.0 (P1, XS) ✅ DONE

- [x] `## [0.25.0] - 2026-04-22` entry added summarising tasks 147-149
- [x] `__version__` bumped to 0.25.0 in `src/circuit_weaver/__init__.py` and `pyproject.toml`

Files: `CHANGELOG.md`, `pyproject.toml`, `src/circuit_weaver/__init__.py`

## Sprint 36 — Resolver Chain Fix (v0.25.0) ✅ DONE

**Goal:** Fix the v0.24.x regression where common MPNs (SHT41-AD1B-R2, SGP40-D-R4, nRF52840) produced stubs despite being available on DigiKey/Mouser and in the bundled `ic_data` JSON store. Root cause: `project_spec._resolve_component` used an ad-hoc 3-tier inline resolver that never called `SymbolResolver`'s full chain.

### 151. Wire ic_data into SymbolResolver as Tier 2 (P0, SMALL) ✅ DONE

- [x] Add `_resolve_ic_data(mpn)` method in `SymbolResolver`
- [x] Insert between ComponentRegistry and KiCad library tiers
- [x] Add `use_ic_data` flag so tests can disable the tier
- [x] Update class docstrings to reflect 7-tier chain (registry → ic_data → kicad → cache → easyeda → digikey → mouser)

Files: `src/circuit_weaver/symbol_resolver.py`

### 152. ic_data_to_component_def() converter (P0, MEDIUM) ✅ DONE

- [x] New `ic_data_to_component_def(mpn, data)` helper in `ic_data/__init__.py`
- [x] Converts JSON entry → `ComponentDef` with pins, footprint, power_pins auto-derived from `power_in` pin types
- [x] Topology → category mapping (`_TOPOLOGY_CATEGORY`), topology → ref_prefix (connector=J, protection=D, crystal=Y)
- [x] Returns None (rather than a broken ComponentDef) when `pins` list is missing/invalid

Files: `src/circuit_weaver/ic_data/__init__.py`

### 153. Replace project_spec.py inline resolver with SymbolResolver (P0, MEDIUM) ✅ DONE

- [x] Delete the ad-hoc 3-tier chain (registry → kicad_lib → EasyEDA) in `_resolve_component`
- [x] Delegate to `SymbolResolver.resolve()` — gets cache + DigiKey + Mouser fallback for free
- [x] Keep `_try_easyeda_resolve` complementary path for YAMLs using explicit `lcsc:` keys
- [x] Update stub warning to enumerate all 7 tiers so operators see what was tried

Files: `src/circuit_weaver/project_spec.py`

### 154. Fix register_ic() deadlock (P0, SMALL) ✅ DONE

- [x] `register_ic()` used to hold `_db_lock` then call `_get_db()` which re-acquires it — deadlocked first call after `reload()`
- [x] Resolve the db reference before entering the mutation lock block

Files: `src/circuit_weaver/ic_data/__init__.py`

### 155. Regression tests — resolver chain (P0, SMALL) ✅ DONE

- [x] `tests/test_resolver_chain.py` — 6 tests covering the full chain
- [x] Mocked DigiKey test for SHT41-AD1B-R2 (the user-reported failure case)
- [x] `register_ic()` hot-load visibility test

Files: `tests/test_resolver_chain.py`

## Sprint 31 — Bug Fixes & Error Handling (v0.23.0) ✅ DONE

**Goal:** Fix confirmed bugs from code review, add error handling to all new CLI handlers.

### 131. Fix _score_from_issues() (P0, SMALL) ✅ DONE
- [x] Fix zero-checks-with-errors returning 100; add tests
Files: `src/circuit_weaver/confidence_dashboard.py`, `tests/test_confidence_dashboard.py`

### 132. Logging bridge thread safety (P0, MEDIUM) ✅ DONE
- [x] Add threading.Lock, try/finally cleanup
Files: `src/circuit_weaver/logging_bridge.py`

### 133. Connector MPN validation (P1, SMALL) ✅ DONE
- [x] Remove "J" from passive prefixes; add test
Files: `src/circuit_weaver/cross_reference_validator.py`, `tests/test_enhanced_validation.py`

### 134. CLI error handling (P0, LARGE) ✅ DONE
- [x] Wrap confidence, simulate, discover, log-event in try/except with user-friendly messages
Files: `src/circuit_weaver/dispatcher.py`

### 135. SPICE value parser edge cases (P2, SMALL) ✅ DONE
- [x] Handle picohenry, spaces, standalone F/H; add tests
Files: `src/circuit_weaver/spice_netlist.py`, `tests/test_spice_netlist.py`

## Sprint 32 — CLI Integration Tests (v0.23.0) ✅ DONE

**Goal:** Add integration tests for all untested CLI commands. Standardize output.

### 136. CLI integration tests (P0, LARGE) ✅ DONE
- [x] 24 tests: discover, simulate, confidence, log-event, log-status, log-view
Files: `tests/test_cli_new_commands.py`

### 137. Output standardization (P1, MEDIUM) ✅ DONE
- [x] Move informational messages to stderr
Files: `src/circuit_weaver/dispatcher.py`

## Sprint 33 — Platform Compatibility & Skill UX (v0.23.0) ✅ DONE

**Goal:** Ensure all features work on Claude Code, Codex, and OpenCode.

### 139. OpenCode/Kilo shims (P0, MEDIUM) ✅ DONE
- [x] Create sim shim, update circuit-weaver shim with full CLI list
Files: `.agents/skills/sim/SKILL.md`, `.agents/skills/circuit-weaver/SKILL.md`

### 140. Platform guidance for all skills (P1, MEDIUM) ✅ DONE
- [x] Add Platform Guidance section to 9 skills
Files: `skills/{bom,digikey,mouser,lcsc,jlcpcb,pcbway,ee,vivado,kicad}/SKILL.md`

### 141. Skill trigger disambiguation (P1, MEDIUM) ✅ DONE
- [x] Add disambiguation notes to bom, design_wizard, kicad, sim skills
Files: `skills/bom/SKILL.md`, `skills/kicad/SKILL.md`, `skills/design_wizard/SKILL.md`, `project-skills/sim/SKILL.md`

## Sprint 34 — Data-Driven Template Engine (v0.24.0 / v0.24.1) ✅ DONE

**Goal:** Replace hardcoded subcircuit template classes with a JSON-driven IC data system + dynamic topology builders. Expand the template library to 37 entries covering RTC, EEPROM, wireless, USB-C, SPI bus, voltage reference, and connectors.

### 146. Sprint 34 Follow-up Hardening (P1, SMALL) ✅ DONE — v0.24.1

Post-release review cleanup — documentation accuracy + `register_ic()` portability.

- [x] Atomic write (tmp-file rename) for `custom.json` to prevent corruption on interrupt
- [x] Fallback to user data dir (`$XDG_DATA_HOME` / `%APPDATA%`) when package dir is read-only; load merges overlays from both
- [x] Thread-safe `_get_db()` lazy init via `threading.Lock` (double-checked locking)
- [x] USB-C `source_current` param: Rp selection per USB-C Rev 2.1 — `default`/`1.5A`/`3A` → 56k/22k/10k
- [x] CHANGELOG v0.24.0 correction: remove false claim about legacy module migration (audio_amplifier/motor_driver/protection remain hardcoded; data-driven fallback exists but none are migrated yet)

Files: `src/circuit_weaver/ic_data/__init__.py`, `src/circuit_weaver/subcircuits/usb_c_connector.py`, `CHANGELOG.md`, `docs/ic-data-system.md`

### 142. IC Data System (P0, LARGE) ✅ DONE

- [x] New `ic_data/` directory: 11 JSON files (amplifier, bus_interface, connector, converter, linear_regulator, memory, misc, oscillator, protection, switching_regulator, custom) holding IC specs, pinmaps, and topology classifiers
- [x] New `ic_data/__init__.py` module with `load_ic_data()`, `register_ic()`, and data lookup helpers
- [x] New `scripts/extract_ic_data.py` CLI for harvesting IC data from datasheet research output
- [x] New `docs/ic-data-system.md` reference documentation

Files: `src/circuit_weaver/ic_data/*.json`, `src/circuit_weaver/ic_data/__init__.py`, `scripts/extract_ic_data.py`, `docs/ic-data-system.md`

### 143. Dynamic Topology Builders (P0, LARGE) ✅ DONE

- [x] New `subcircuits/topology_builders.py`: `build_switching_regulator()`, `build_linear_regulator()`, `build_generic()` — reads IC data JSON and produces schematic fragments dynamically, replacing hardcoded template classes
- [x] Refactored `subcircuits/base.py` (+90 lines) to support data-driven dispatch
- [x] Updated legacy templates (`audio_amplifier.py`, `motor_driver.py`, `protection.py`) to delegate to the new builder path

Files: `src/circuit_weaver/subcircuits/topology_builders.py`, `src/circuit_weaver/subcircuits/base.py`, `src/circuit_weaver/subcircuits/audio_amplifier.py`, `src/circuit_weaver/subcircuits/motor_driver.py`, `src/circuit_weaver/subcircuits/protection.py`

### 144. Expanded Template Library (P1, LARGE) ✅ DONE

Added 7 new subcircuit templates (brings total to 37):
- [x] `rtc.py` — real-time clocks (DS3231, PCF8563, MCP79410)
- [x] `eeprom.py` — I2C/SPI EEPROMs (24LCxx, 25LCxx, M95xxx families)
- [x] `wireless_module.py` — BLE/WiFi/LoRa modules (nRF52-DK, ESP32, RYLR896)
- [x] `usb_c_connector.py` — USB-C receptacles with CC/SBU routing
- [x] `spi_bus.py` — SPI bus conditioning (pull-ups, chip-select matrix)
- [x] `voltage_reference.py` — precision voltage references (REF5025, LM4040, ADR4540)
- [x] `connector.py` — generic pin-header/through-hole connectors

Files: `src/circuit_weaver/subcircuits/rtc.py`, `src/circuit_weaver/subcircuits/eeprom.py`, `src/circuit_weaver/subcircuits/wireless_module.py`, `src/circuit_weaver/subcircuits/usb_c_connector.py`, `src/circuit_weaver/subcircuits/spi_bus.py`, `src/circuit_weaver/subcircuits/voltage_reference.py`, `src/circuit_weaver/subcircuits/connector.py`

### 145. CLI + Tests (P1, MEDIUM) ✅ DONE

- [x] `list-templates` extended to show data-driven entries alongside legacy templates
- [x] `scaffold` supports data-driven template params
- [x] `.pre-commit-config.yaml` and `tests/test_cli_commands.py` updated for `circuit_weaver` package rename (post-dispatcher refactor)
- [x] 380 new lines in `tests/test_template_structure.py`: parity tests comparing data-driven output to legacy templates, new-template structural tests

Files: `src/circuit_weaver/dispatcher.py`, `src/circuit_weaver/api.py`, `.pre-commit-config.yaml`, `tests/test_template_structure.py`, `tests/test_cli_commands.py`, `scripts/gen_template_docs.py`, `docs/templates.md`, `docs/cli-reference.md`

## Sprint 26 — Logging Overhaul (v0.22.0) ✅ DONE

**Goal:** Make DesignLogger the single authoritative logging system. Instrument all major operations. Give skills a callable logging interface.

### 125. Expand DesignLogger Event Types (P0, MEDIUM) ✅ DONE

- [x] Add 9 new log methods: part_lookup, symbol_resolution, simulation, thermal, erc_drc, scoring, sourcing, generation, error
- [x] Update get_summary() and print_summary() to aggregate new event types
- [x] 33 tests in tests/test_design_logger_extended.py

Files: `src/circuit_weaver/design_logger.py`, `tests/test_design_logger_extended.py`

### 126. Create Logging Bridge (P0, MEDIUM) ✅ DONE

- [x] Create `logging_bridge.py` with DesignLogHandler, get/set_design_logger, init_logging
- [x] Integrate into dispatcher.py (generate_artifacts, validate_design, design_workflow)
- [x] Add `log-event` CLI subcommand for skill-callable structured logging
- [x] Instrument 7 modules: erc_runner, dfm_checker, validator, design_scorer, thermal_analysis, exporters, spice_fetcher

Files: `src/circuit_weaver/logging_bridge.py`, `src/circuit_weaver/dispatcher.py`

## Sprint 27 — Project Discovery (v0.22.0) ✅ DONE

**Goal:** Skills auto-detect existing circuits in CWD before asking for paths.

### 127. Project Discovery Module (P1, MEDIUM) ✅ DONE

- [x] Create `project_discovery.py` with DiscoveredProject, discover_projects(), detect_project_type()
- [x] Add `discover` CLI subcommand with JSON and table output
- [x] Refactor _find_existing_circuits() to use discovery module
- [x] Update 4 skills with auto-detection (circuit-weaver, design_wizard, kicad_validate, sim)
- [x] 20 tests in tests/test_project_discovery.py

Files: `src/circuit_weaver/project_discovery.py`, `src/circuit_weaver/dispatcher.py`, `tests/test_project_discovery.py`

## Sprint 28 — Circuit Simulation Engine (v0.22.0) ✅ DONE

**Goal:** Build SPICE netlist generation, ngspice execution, result parsing, and simulation confidence scoring.

### 128. SPICE Netlist & Runner (P0, LARGE) ✅ DONE

- [x] Create `spice_netlist.py`: SPICE .cir generation from ComponentDef lists
- [x] Create `spice_runner.py`: ngspice subprocess runner with graceful degradation
- [x] Create `simulation.py`: orchestrator with plan_simulations(), run_design_simulations(), score_simulation_confidence()
- [x] Add resolve_spice_models() to spice_fetcher.py
- [x] Add `simulate` CLI subcommand
- [x] Update sim skill with automated quick-start
- [x] 36 tests across test_spice_netlist.py, test_spice_runner.py, test_simulation.py

Files: `src/circuit_weaver/spice_netlist.py`, `src/circuit_weaver/spice_runner.py`, `src/circuit_weaver/simulation.py`, `src/circuit_weaver/spice_fetcher.py`

## Sprint 29 — Enhanced Validations (v0.22.0) ✅ DONE

**Goal:** Add simulation-backed checks, thermal validation, SI checks, and cross-reference audit.

### 129. Enhanced Validation Checks (P0, MEDIUM) ✅ DONE

- [x] Add 3 new validation checks: power_budget, thermal_limits, signal_integrity (14 total)
- [x] Create `cross_reference_validator.py` with 3 audit passes
- [x] Add --enhanced flag to validate CLI
- [x] Update kicad_validate skill
- [x] 16 tests in tests/test_enhanced_validation.py

Files: `src/circuit_weaver/validator.py`, `src/circuit_weaver/cross_reference_validator.py`, `src/circuit_weaver/dispatcher.py`

## Sprint 30 — Confidence Dashboard & Workflow (v0.22.0) ✅ DONE

**Goal:** Aggregate all checks into a unified confidence report. Wire placement/routing/SVG into the wizard flow.

### 130. Confidence Dashboard (P0, LARGE) ✅ DONE

- [x] Create `confidence_dashboard.py`: 7-source weighted scoring, HTML/terminal/JSON output
- [x] Add `confidence` CLI subcommand with --run-sims and --pcb options
- [x] Add Step 6 (Confidence) to both wizard flows as automatic step
- [x] Add Step 7 (PCB Layout Preparation) with placement optimizer, viewer, SVG, autoroute, DFM
- [x] Expand Existing Design menu to 13 categorized options
- [x] Cross-reference all project-skills from main skills
- [x] 23 tests in tests/test_confidence_dashboard.py

Files: `src/circuit_weaver/confidence_dashboard.py`, `src/circuit_weaver/dispatcher.py`, `skills/circuit-weaver/SKILL.md`, `skills/design_wizard/SKILL.md`

## Sprint 31 — Sprints 26-30 Review Follow-ups (backlog)

**Context:** Items deferred from the pre-merge code review of PR #2 (Sprints 26-30) and a CI workflow regression discovered during that review. Non-blocking for PR #2 merge; queued for the next sprint.

### 130. Fix legacy validation errors in `samples/*` and re-enable validate gate (P1, MEDIUM)

The `Validate Designs` workflow was silently broken since Sprint 20 (renamed `mvp` → `dispatcher` without updating the workflow YAML). After fixing the invocation in PR #2, ~30 pre-existing validation errors surfaced across 11 sample YAMLs (unconnected pins, dangling nets, missing I2C pull-ups, missing artifact-export tooling). The job is set `continue-on-error: true` so it does not block merges; this task fixes the underlying samples and removes the flag.

- [ ] Triage the validate-workflow output for each sample and decide per-sample: fix the YAML, add `explicit_no_connects` entries, or remove the sample
- [ ] Document any required external dependencies (e.g., `kicad-cli` for artifact export) in the workflow setup or skip them on CI
- [ ] Remove `continue-on-error: true` from `.github/workflows/validate-design.yml` once samples are clean

Files: `.github/workflows/validate-design.yml`, `samples/**/*.yaml`

### 131. Code-review SUGGESTIONs from PR #2 (P2, SMALL)

Polish items from the pre-merge review. None block correctness; bundle into a single sweep.

- [ ] `cross_reference_validator.py`: add `"warn"` to the `CrossReferenceResult.status` enum docstring (or normalise to `pass`/`fail`/`skipped`)
- [ ] `cross_reference_validator.py`: tighten `_passive_prefixes` — diodes (`D`) and connectors (`J`) usually need MPNs for production sourcing; consider dropping them from the skip set
- [ ] `confidence_dashboard.py`: `_score_from_issues(total_checks, ...)` ignores `total_checks` for scoring; either normalise the penalty by it or drop the parameter
- [ ] `spice_runner.py`: `wdir / "results.raw"` is a fixed filename; safe today (sequential loop) but races if simulations are ever parallelised — derive output name from the netlist stem instead

Files: `src/circuit_weaver/cross_reference_validator.py`, `src/circuit_weaver/confidence_dashboard.py`, `src/circuit_weaver/spice_runner.py`

## Sprint 22 — Pinout Verification Gate (v0.18.0)

**Goal:** Before emitting any schematic, verify every IC pinout has a confirmed source. Replace silent STUB annotations with hard validation failures. This is the #1 community trust blocker — a swapped pin is invisible to DRC/ERC and kills the board.

### 116. Pinout Source Validation (P0, MEDIUM) ✅ DONE

Add a `validate_pinout_sources()` check to `validator.py` that fails validation for any IC whose pin map is derived from a STUB (unverified) source. Users must supply an explicit `pin_map` in their YAML spec, or confirm pins via `pinout_verified: true`, or use a component with a KiCad-library-backed pinout.

- [x] Add `_validate_pinout_sources()` to `validator.py` — scans components for `pinout_source == "stub"`
- [x] Emit `ValidationIssue(level="error", code="unverified-pinout", ref=..., message=...)` for each STUB IC
- [x] Surfaces in `validate` CLI output: "U1 (BGB707): pinout not verified — add explicit pin_map or set pinout_verified: true"
- [x] Add `pinout_verified: bool = False` flag to `ComponentDef` (opt-in override for user-confirmed parts)
- [x] Wire `pinout_verified: true` through standalone YAML/project-spec resolution
- [x] Support explicit YAML `pin_map` overrides for standalone components, promoting distributor stubs to explicit pinout provenance
- [x] Narrow pass-through exemptions to true pinout-irrelevant passives only; diode/crystal/oscillator-style stubs still fail validation
- [x] 10 unit tests in `tests/test_validator.py`: STUB IC fails, explicit passes, spec-level `pinout_verified` and `pin_map` overrides work, passive skipped, diode stub fails, mixed design, multiple stubs, check registration

Files: `src/circuit_weaver/validator.py`, `src/circuit_weaver/component_db.py`, `tests/test_validator.py`

### 117. Remove STUB Annotations from DigiKey/Mouser Loaders (P0, SMALL) ✅ DONE

Replace the silent "STUB: verify pinmap" annotations in `digikey_loader.py` and `mouser_loader.py` with a structured `pinout_source` field. When source is `"stub"`, Task 116's validator catches it and fails cleanly.

- [x] Add `pinout_source: str = "explicit"` and `pinout_verified: bool = False` fields to `ComponentDef`
- [x] Set `pinout_source = "stub"` in `digikey_loader.py` (both stub paths) instead of STUB annotation
- [x] Set `pinout_source = "stub"` in `mouser_loader.py` (both stub paths) instead of STUB annotation
- [x] Default `pinout_source = "explicit"` for all registry/library-backed components

Files: `src/circuit_weaver/component_db.py`, `src/circuit_weaver/digikey_loader.py`, `src/circuit_weaver/mouser_loader.py`

---

## Sprint 23 — Post-Generation ERC (v0.19.0)

**Goal:** Invoke KiCad CLI ERC after generation and surface results in the HTML review report. A clean "ERC: 0 errors" badge becomes a shareable trust signal for community posts.

### 118. KiCad CLI ERC Integration (P0, MEDIUM) ✅ DONE

- [x] Added `erc` subcommand: `circuit-weaver erc <schematic.kicad_sch> [--json]`
- [x] `src/circuit_weaver/erc_runner.py` — invokes `kicad-cli sch erc --format json`, parses violation array
- [x] `_classify_severity()` — promotes 13 known error types regardless of raw kicad-cli severity field
- [x] Degrades gracefully: `{"status": "skipped"}` when KiCad CLI absent, `{"status": "failed"}` on timeout/parse error
- [x] `generate_artifacts()` auto-runs ERC when root schematic present; adds `"erc"` key to result dict
- [x] 12 unit tests: mock success, timeout, absent CLI, JSON parsing, severity classification, to_dict roundtrip

Files: `src/circuit_weaver/erc_runner.py` (new), `src/circuit_weaver/dispatcher.py`, `tests/test_erc_runner.py` (new)

### 119. ERC Results in HTML Review Report (P1, SMALL) ✅ DONE

- [x] `_generate_erc_section()` added to `review_report.py`
- [x] Green badge "✓ ERC: 0 errors, 0 warnings" when clean
- [x] Red badge "✗ ERC: N errors" with violation table (type, description, severity) when errors present
- [x] "ERC: not run (…)" for skipped/None; "⚠ ERC failed: …" for failed status
- [x] Accepts both `ErcResult` objects and plain dicts (from `generate_artifacts` JSON output)
- [x] 6 unit tests in `tests/test_review_report_erc.py`

Files: `src/circuit_weaver/review_report.py`, `tests/test_review_report_erc.py` (new)

---

## Sprint 24 — Firmware Co-Design Export (v0.20.0)

**Goal:** For MCU-based designs, emit a `pinout.csv` alongside the schematic. For STM32 and ESP32 targets, also emit target-specific config stubs. Closes the hardware/firmware contract gap.

### 120. Pinout CSV Export (P0, SMALL) ✅ DONE

- [x] `export_pinout_csv()` in `firmware_export.py` — writes `{project}_pinout.csv` with columns Ref, Pin, PinName, Net, Peripheral, Direction
- [x] Inferred from `pin_nets` + `power_pins` for all MCU-type components (detected by MPN prefix)
- [x] `generate_artifacts()` auto-runs for designs with MCUs; adds `"pinout_csv"` key to result dict
- [x] `--pinout` flag on `generate` subcommand forces emission for all components
- [x] 5 unit tests: MCU emits csv, correct columns, signal rows present, power pins included, non-MCU skipped

Files: `src/circuit_weaver/firmware_export.py` (new), `src/circuit_weaver/dispatcher.py`, `tests/test_firmware_export.py` (new)

### 121. STM32 .ioc Skeleton Export (P1, SMALL) ✅ DONE

- [x] `export_stm32_ioc()` detects STM32 by MPN prefix, returns None for non-STM32
- [x] Emits `{project}.ioc` with `[PinoutTool.PinMappings]` populated from `pin_nets`
- [x] `_stm32_port_label()` extracts PA13 from "PA13/SWDIO"; `_stm32_signal_from_net()` maps nets to CubeMX signal names
- [x] `generate_artifacts()` auto-emits `.ioc` for any STM32 component; adds `"stm32_ioc"` key
- [x] 3 unit tests: creates file, contains pin mappings, skips non-STM32

Files: `src/circuit_weaver/firmware_export.py`, `tests/test_firmware_export.py`

### 122. ESP32 sdkconfig Fragment Export (P2, SMALL) ✅ DONE

- [x] `export_esp32_sdkconfig()` detects ESP32 by MPN prefix, returns None for non-ESP32
- [x] Emits `sdkconfig.defaults` with `CONFIG_*_GPIO_NUM=<N>` from IO<N> pin names + net-based key mapping
- [x] `_esp32_gpio_number()` extracts GPIO from "IO21" → 21; `_esp32_config_key()` maps net→CONFIG prefix
- [x] `generate_artifacts()` auto-emits for any ESP32 component; adds `"esp32_sdkconfig"` key
- [x] 3 unit tests: creates file, correct GPIO mapping (IO21→I2C_SDA=21), skips non-ESP32

Files: `src/circuit_weaver/firmware_export.py`, `tests/test_firmware_export.py`

---

## Sprint 25 — Explainability & Test Points (v0.21.0)

**Goal:** Surface design rationale in the review report so community reviewers can audit component selection. Auto-generate test points for power rails and critical signals.

### 123. Design Rationale in HTML Review Report (P0, MEDIUM) ✅ DONE

- [x] Add "Component Selection Rationale" section to `review_report.py` per IC
- [x] Source: wizard choices from `design.log`, research queries, template selection reason
- [x] For each IC show: why selected (voltage/current match), reference design cited (if any), key specs used
- [x] If no rationale available, show: "Selected via component registry — verify against datasheet"
- [x] 4 unit tests: rationale renders per IC, missing rationale shows fallback, HTML escaping correct, key specs from params appear

Files: `src/circuit_weaver/review_report.py`, `src/circuit_weaver/design_logger.py`, `tests/test_review_report.py`

### 124. Automatic Test Point Generation (P1, MEDIUM) ✅ DONE

- [x] Identify key nets: all power rails (`VDD_*`, `VCC*`, `VBUS*`, `GND`), differential pairs, high-speed signals
- [x] Emit `{project_name}_test_points.csv` with columns: `TestPoint, Net, Type, Priority`
- [x] Types: `power_rail`, `differential`, `clock`, `data_bus`, `ground`
- [x] Add test point annotation labels to generated schematic at rail connection sites
- [x] 6 unit tests: power rails detected, differential pairs detected (from names + pcb_constraints), CSV format correct, schematic annotation added, empty design handled

Files: `src/circuit_weaver/test_point_gen.py` (new), `src/circuit_weaver/generator.py`, `tests/test_test_point_gen.py` (new)

---

## Sprint 20 — Design Review Completion & Production Assembly (v0.17.0)

**Goal:** Complete Sprint 19 backlog (dispatcher refactor, sourcing audit), then enable production assembly workflows. Users can now design → validate → review → estimate costs → order assembled boards from JLCPCB.

### 109. Rename mvp.py to dispatcher.py (P1, SMALL) — DONE ✅

- [x] Rename `src/circuit_weaver/mvp.py` → `src/circuit_weaver/dispatcher.py`
- [x] Update all imports across codebase (cli.py, __init__.py, tests/)
- [x] Update docstrings and comments
- [x] Update CLI help text and error messages if needed
- [x] Update test references and CI/CD configs
- [x] Verify all tests still pass after rename
- [x] Update CONTRIBUTING.md and architecture docs

**Rationale**: "mvp" is outdated naming (no longer a minimum viable product, it's the full CLI dispatcher). "dispatcher.py" accurately reflects its role: routing subcommands to handlers.

Files: `src/circuit_weaver/mvp.py` → `src/circuit_weaver/dispatcher.py` (rename), all imports, docs

### 107. Component Sourcing Risk Audit (P2, SMALL) — DONE ✅

- [x] Create `sourcing_auditor.py` — queries distributor APIs for component health
- [x] For each BOM component:
  - [x] Query DigiKey (via existing `_search_digikey()`) for lifecycle status: Active / NRND / Obsolete / EOL
  - [x] Query LCSC (via existing jlcsearch) for stock levels + lead time
  - [x] Detect: out-of-stock, <100 units in stock, >12 week lead time
  - [x] Flag: parts with no distributor PN (unpriced)
- [x] Output: audit report with risk levels
  - [x] **CRITICAL:** obsolete parts, zero stock, >16 week lead time
  - [x] **WARNING:** low stock (<100), long lead (>8 weeks), single-source only
  - [x] Suggest alternates (pin-compatible parts) from LCSC for at-risk parts
- [x] CLI: `circuit-weaver audit-bom <design.yaml> [--lcsc-only]`
- [x] Integrate into review workflow: call after `cost-bom`
- [x] 20 unit tests in `test_sourcing_auditor.py`

Files: `src/circuit_weaver/sourcing_auditor.py` (new, 250 LOC), `src/circuit_weaver/__init__.py`, `tests/test_sourcing_auditor.py` (new, 180 tests)

### 110. JLCPCB Assembly Integration (P1, MEDIUM) — DEFERRED

**Deferred to Sprint 21+** — Product validation not yet at manufacturing stage.

- [ ] Auto-generate **CPL (component placement list)** + **BOM CSV** in JLCPCB format
- [ ] Map components to LCSC part numbers (fallback to MPN if LCSC missing)
- [ ] Flag extended parts (cost warning: $3 each setup fee)
- [ ] Detect PCB assembly constraints: top/bottom/both sides, SMD/THT/mixed
- [ ] Output format validation against JLCPCB upload spec (column headers, encoding, etc.)
- [ ] CLI: `circuit-weaver export-jlcpcb-assembly <design.yaml> [--output asm/]`
- [ ] Output: `asm/bom.csv`, `asm/placement.csv` ready to upload to JLCPCB cart
- [ ] Integration: call after `cost-bom`, report extended parts count + setup cost
- [ ] 12 unit tests in `test_jlcpcb_assembly.py` covering BOM format, CPL generation, extended parts flagging

Files: `src/circuit_weaver/jlcpcb_assembly.py` (new), `src/circuit_weaver/dispatcher.py`, `tests/test_jlcpcb_assembly.py` (new)

### 111. BOM Cost Estimation & Price Breaks (P2, SMALL) — DEFERRED

**Deferred to Sprint 21+** — Dependent on Task 110; revisit when approaching production.

- [ ] Query DigiKey + Mouser pricing at multiple quantities (1, 5, 10, 25, 50, 100)
- [ ] Detect price breaks and alert: "Resistor R5: $0.01 @ 1, $0.005 @ 100 (50% savings for qty 100+)"
- [ ] Aggregate: total BOM cost at 1 qty vs 5 qty vs 10 qty
- [ ] Output: cost summary table + recommended order quantity
- [ ] CLI: `circuit-weaver cost-bom <design.yaml> --quantities 1,5,10,50,100`
- [ ] Integration: show cost vs price break breakeven point for bulk orders
- [ ] 8 unit tests in `test_cost_estimation.py` covering price break detection, quantity optimization

Files: `src/circuit_weaver/cost_estimation.py` (new), `src/circuit_weaver/dispatcher.py`, `tests/test_cost_estimation.py` (new)

---

## Sprint 21 — v0.17.0 Bug Fixes & Generator Hardening

**Goal:** Fix production bugs found in v0.17.0 release testing, stabilize schematic generation, clean up intermediate artifacts.

### 112. Fix Schematic Naming (P0, SMALL) — DONE ✅

**RESOLUTION NOTES:**
- Multi-sheet root schematics were already named correctly as `{project_name}.kicad_sch`
- Single-sheet generation still wrote `{sheet_alloc.name}.kicad_sch`, which defaulted to `main.kicad_sch`
- Reproduced with `src/circuit_weaver/examples/iot_sensor.yaml` (`project: IoT_Sensor`)
- Fixed single-sheet output naming to use `project_name` instead of generic sheet names

- [x] Reproduce the bug on a single-sheet design (`IoT_Sensor` generated `main.kicad_sch`)
- [x] Update single-sheet file writes to use `project_name`
- [x] Add regression coverage in bootstrap and CLI generate tests

Files: `src/circuit_weaver/dispatcher.py`, `src/circuit_weaver/generator.py`, `tests/test_bootstrap.py`

### 113. Remove generate_schematic.py from Output (P0, SMALL) — DONE ✅

**RESOLUTION NOTES:**
- Exhaustive search of dispatcher.py + generator.py found no code path that writes `.py` files to output
- `--output` is required in the generate CLI; all file writes target `output_path` only
- `generate_schematic.py` at user's project root was a pre-existing artifact from an older code version (prior to `--output` being required)
- Current code correctly outputs only `.kicad_sch`, `.kicad_pcb`, `.json`, `.yaml`, `.md` files

- [x] Find where `.py` extension is hardcoded in file writes — not present in current code
- [x] Verify output/ contains ONLY expected file types
- [x] Test: `test_generate_no_py_artifacts` asserts no `.py` files in output directory

Files: `tests/test_cli_commands.py`

### 114. Add Logging to Output Directory (P0, SMALL) — DONE ✅

**RESOLUTION NOTES:**
- Added `logging.FileHandler` in `generate_artifacts()` targeting `output/circuit-weaver.log`
- Temporarily sets `circuit_weaver` logger level to DEBUG during generation; restores it in a finally block
- Converted key `print()` calls in `generator.py` to `_logger.info()`: component count, sheet allocation, file paths written, design report path
- Log captures: validation warnings, component allocation, sheet ICs/passives/paper, file writes
- Added `import logging` to `dispatcher.py`

- [x] Add `FileHandler` in `generate_artifacts()` → `output/circuit-weaver.log`
- [x] Convert key `print()` to `_logger.info()` in generator.py
- [x] Log: component count, sheet allocations, file paths written
- [x] Test: `test_generate_log_file` asserts log exists with allocation + file path entries

Files: `src/circuit_weaver/dispatcher.py`, `src/circuit_weaver/generator.py`, `tests/test_cli_commands.py`

### 115. Fix S-Expression Syntax Error (P0, SMALL) — DONE ✅

**RESOLUTION NOTES:**
- Cannot reproduce the specific stray `)` with current code on IoT sensor example — paren balance is correct
- Root cause of user's SDR LNA issue is not detectable without that design; may have been a transient artifact from the pre-fix `main.kicad_sch` naming (Task 112)
- **Hardened the generator** to catch future paren imbalances early: `_validate_sexpr_balance()` checks open/close paren counts (ignoring string literals) before writing each `.kicad_sch` file, emitting `_logger.warning()` if depth ≠ 0
- The warning lands in `circuit-weaver.log` (Task 114) so users can see it without crashing generation

- [x] Identify which S-expression function adds extra `)` — not reproducible with current code
- [x] Add paren-balance validator called before each sheet file write
- [x] Test: `test_generate_schematic_paren_balance` checks depth == 0 on all generated `.kicad_sch` files

Files: `src/circuit_weaver/generator.py`, `tests/test_cli_commands.py`

---

## Sprint 19 — Design Review & Quality Assurance (v0.16.0)

**Goal:** Improve design review workflows, add design-time quality checks, and expand documentation for users starting their first designs. Focus on DFM validation, design scoring, and design documentation generation.

### 104. Design DFM Checker (P0, MEDIUM) — DONE

- [x] Create `dfm_checker.py` — validates PCB design against fab capabilities
- [x] Check categories:
  - [x] Trace width minimum (0.127mm for JLCPCB 2-layer, 0.09mm for 4-layer)
  - [x] Trace-to-trace spacing (same minimums)
  - [x] Via diameter and drill size (0.45mm / 0.2mm for 2-layer)
  - [x] Annular ring on vias (≥0.125mm)
  - [x] Solder mask clearance (0.1mm typical)
  - [x] Board edge clearance for traces (0.3mm minimum)
  - [x] Pad-to-pad spacing (accounts for solder paste bridge risk)
- [x] Support multiple fab profiles: JLCPCB, PCBWay, custom `.dru` rules from KiCad
- [x] Output: list of violations with: location (net/component), violation type, actual/minimum values, fix suggestion
- [x] CLI command: `circuit-weaver check-dfm <design.kicad_pcb> [--profile jlcpcb|pcbway]`
- [x] Integration: can be called standalone or as pre-flight check in `export-gerbers`
- [x] Generate violation summary: X critical, Y warnings
- [x] 14 unit tests in `test_dfm_checker.py` covering profiles, parsing, violations, reports

Files: `src/circuit_weaver/dfm_checker.py` (new), `src/circuit_weaver/mvp.py`, `tests/test_dfm_checker.py` (new)

### 105. Enhanced Design Scoring (P1, MEDIUM) — DONE

- [x] Extend current `score_electrical_quality()` with per-section metrics
- [x] New score categories:
  - [x] **Power Integrity:** decoupling adequacy, bulk cap presence, regulator headroom, rail noise risk (weighted)
  - [x] **Signal Integrity:** termination on high-speed nets, differential pair tuning, layer stack compliance
  - [x] **Placement Quality:** thermal clustering, decap proximity to power pins, connector-to-component distances
  - [x] **Thermal:** estimated junction temps vs max ratings, thermal via coverage on power devices
  - [x] **Manufacturing:** DFM violations (from Task 104), component availability, assembly complexity
- [x] Composite score: weighted average of 5 sections (each 0-100)
- [x] Return detailed report: {power: 85, signal: 92, placement: 78, thermal: 90, mfg: 88, overall: 86, grade: "B+"}
- [x] Add `--detailed-score` flag to `validate` command
- [x] Produce text summary with "gaps" flagged (any section < 75 triggers recommendation)

Files: `src/circuit_weaver/design_scorer.py` (new), `src/circuit_weaver/mvp.py`, `tests/test_design_scorer.py` (new, 19 tests)

### 106. Interactive Design Review Report (P1, MEDIUM) — DONE

- [x] Generate HTML report with all design analysis in one shareable file
- [x] Report sections:
  - [x] **Summary card:** project name, version, overall score, grade, creation date
  - [x] **Design checklist:** pre-fab review items (DFM, sourcing, thermal, SI, placement)
  - [x] **DFM violations table:** violations from Task 104, sorted by severity
  - [x] **Component BOM table:** reference, value, footprint, MPN, distributor, cost, qty
  - [x] **Scoring breakdown:** bar charts of 5 quality metrics
  - [x] **Power tree:** hierarchical view of regulators → rails → loads
  - [x] **Next steps:** actionable recommendations based on violations + scores
- [x] Export command: `circuit-weaver review-report <design.yaml> [--kicad-pcb board.kicad_pcb] --output report.html`
- [x] Styling: professional, printable, responsive design
- [x] Data embedding: all data embedded in HTML (no external dependencies)

Files: `src/circuit_weaver/review_report.py` (new, 650 LOC), `src/circuit_weaver/mvp.py`

### 108. Design Documentation Generator (P2, MEDIUM) — DONE

- [x] Create `design_docs.py` — auto-generate assembly and ordering documents
- [x] Outputs:
  - [x] **Assembly guide CSV:** BOM table with reference, value, footprint, MPN, manufacturer
  - [x] **Ordering checklist:** markdown with per-distributor checkboxes and component status
  - [x] **Component datasheet index:** markdown links to downloaded PDFs
  - [x] **Power budget CSV:** rail voltage, estimated current, power per supply rail
- [x] Assembly guide functions:
  - [x] `_generate_bom_table()` — extract from design IR
  - [x] `_generate_power_budget()` — estimate power per rail from component categories
  - [x] `generate_assembly_guide_csv()` — CSV export
  - [x] `generate_ordering_checklist()` — markdown checklist with distributor status
  - [x] `generate_datasheet_index()` — index all PDFs in a directory
  - [x] `generate_all_docs()` — orchestrator for all doc types
- [x] CLI: `circuit-weaver generate-docs <design.yaml> --output docs/ [--datasheets-dir X]`
- [x] 17 unit tests in `test_design_docs.py` covering BOM, power budget, CSV/markdown exports

Files: `src/circuit_weaver/design_docs.py` (new), `src/circuit_weaver/mvp.py`, `tests/test_design_docs.py` (new)

---

## Sprint 18 — Mechanical & API Enhancements (v0.14.1)

**Goal:** Add parametric 3D-printable enclosure generation via OpenSCAD and robust KiCad placement updates via official Python API with automatic fallback.

### 102. OpenSCAD Enclosure Designer (P1, MEDIUM) — DONE

- [x] Create `enclosure_designer.py` — parametric OpenSCAD code generator
- [x] `generate_enclosure_scad()` with customizable wall thickness, clearance, component height
- [x] Port cutout support: USB-C, Micro-USB, barrel jack, round, rectangular
- [x] M3 mounting hole generation with countersink
- [x] Optional vent hole pattern in lid
- [x] `render_enclosure_stl()` calls OpenSCAD CLI to generate STL
- [x] `design-enclosure` CLI subcommand with full parameter support
- [x] Export functions in `__init__.py` public API
- [x] Documentation: added enclosure design workflow to `user_workflow.md`

Files: `src/circuit_weaver/enclosure_designer.py` (new), `src/circuit_weaver/mvp.py`, `src/circuit_weaver/__init__.py`, `docs/user_workflow.md`

### 103. KiCad Python API Integration (P1, MEDIUM) — DONE

- [x] Create `kicad_placement_api.py` — KiCad 6+ pcbnew API wrapper
- [x] `detect_kicad_version()` — CLI-based detection + pcbnew module import
- [x] `check_kicad_available(min_version=6)` — validates KiCad with platform-specific guidance
  - [x] macOS: `brew install kicad`
  - [x] Windows: direct kicad.org download link
  - [x] Linux: package manager guidance
- [x] `update_board_placements()` — uses official pcbnew API for placement updates
  - [x] Converts mm to KiCad internal units (nm)
  - [x] Handles layer flipping for bottom-side components
  - [x] Full validation and error reporting
- [x] Automatic fallback to regex-based updates when API unavailable (offline, legacy KiCad)
- [x] Consistent result structure: {success, updated, not_found, errors, message}
- [x] `import-placement` command now checks KiCad availability and reports API status
- [x] Export API functions in `__init__.py` public API

Files: `src/circuit_weaver/kicad_placement_api.py` (new), `src/circuit_weaver/svg_placement.py`, `src/circuit_weaver/mvp.py`, `src/circuit_weaver/__init__.py`

---

## Sprint 17 — Housekeeping & Test Coverage (v0.14.0) — DONE

**Goal:** Fix version mismatches, add .gitignore for generated files, comprehensive CLI end-to-end tests, enclosure designer test coverage, and update stale documentation.

### 97. Fix version mismatch (P0, XS) — DONE

- [x] Sync pyproject.toml to 0.14.0
- [x] Sync __init__.py to 0.14.0
- [x] Sync test_bootstrap.py version assertions to 0.14.0

Files: `pyproject.toml`, `src/circuit_weaver/__init__.py`, `tests/test_bootstrap.py`

### 98. .gitignore for generated files (P0, XS) — DONE

- [x] Add datasheets/, specs/, spice_models/, bom/orders/, *.bak

Files: `.gitignore`

### 99. CLI end-to-end test suite (P1, MEDIUM) — DONE

- [x] Parameterized --help test for all 20 subcommands
- [x] End-to-end tests: validate, validate --strict, list-templates, scaffold, schema, generate, cost-bom, export-jlcpcb, si-constraints, thermal-analysis, optimize-placement, panelize, export-dual-cpl, placement-viewer, diff
- [x] JSON extraction helper for commands with prefix output lines
- [x] 37 tests total in test_cli_commands.py

Files: `tests/test_cli_commands.py` (new)

### 100. Enclosure designer test coverage (P1, SMALL) — DONE

- [x] Test basic enclosure generation, ports, mounting holes, custom dimensions
- [x] Test render_enclosure_stl graceful fallback when OpenSCAD not installed
- [x] Test package-level exports (generate_enclosure_scad, render_enclosure_stl)
- [x] 7 tests in test_enclosure_designer.py

Files: `tests/test_enclosure_designer.py` (new)

### 101. Update stale docs (P1, SMALL) — DONE

- [x] CONTRIBUTING.md: update release example from v0.11.0 to v0.14.0
- [x] architecture.md: update version roadmap table (all sprints through 16 marked stable)
- [x] architecture.md: update future roadmap to reflect actual next steps
- [x] mvp.py: replace TODO placeholder with actual placement optimizer call in SVG export

Files: `CONTRIBUTING.md`, `docs/architecture.md`, `src/circuit_weaver/mvp.py`

---

## Sprint 13 — Community Ready: PyPI Distribution & Developer UX (v0.11.0)

**Goal:** Circuit Weaver is on PyPI with clear, automated installation. New users get helpful error messages, better debugging, and a path to contribution. Reduce barriers to adoption and enable self-serve problem solving.

**Priority Order:** Start with Task 77 (P0 blocker). Tasks 78–80 unlock user workflows. Tasks 81–82 can ship in patch release.

### 77. Implement `install-skills` command (P0, MEDIUM) — UNBLOCKS ALL WORKFLOWS ✓

- [x] Add `install-skills` CLI subcommand — detects Claude Code / Codex / OpenCode / Kilo and registers global skills
- [x] Detects platform by checking `~/.claude/`, `~/.codex/`, `~/.opencode/`, `~/.kilo/` directories
- [x] Copies skill YAML files to correct platform directories (`global/skills/`, `~/.codex/skills/`, etc.)
- [x] Validates installation by checking file presence and reporting success
- [x] `--platform` flag to force specific platform (useful for CI/CD)
- [x] Graceful error if no platform detected: "No AI platform found. Supported: Claude Code, Codex, OpenCode, Kilo"

Files: `mvp.py`, `skill_installer.py` (new), `_bundled_skills/circuit-weaver/SKILL.md` (new), `pyproject.toml`

### 78. Enhanced error messages for common failures (P1, MEDIUM) ✓

- [x] Categorize validation errors: "Structural", "Electrical", "Implementation", "Presentation"
- [x] Add "How to fix" section to each error category (e.g., "Floating pin detected on U1 pin 3 (VCC). Add capacitor or check if pin should be no-connect.")
- [-] Detect common patterns: "Did you mean to use `ldo` template instead of `buck`?" when power output is too low
- [x] Surface the `suggestion` field from ValidationIssue prominently in CLI output
- [x] Color-code errors (red), warnings (yellow), suggestions (blue) in terminal output when `--color` flag used (default: auto-detect)
- [x] Add `--verbose` flag to validator: includes full datasheet-cited reasoning and alternative solutions

Files: `mvp.py` (added --color, --verbose, _ANSI, _color_support, _print_validation_report)

### 79. Developer debugging: YAML schema inspector (P1, SMALL) ✓

- [x] `circuit-weaver schema` command — outputs JSON schema for design IR
- [x] `--format` flag: `json`, `yaml`, `markdown` (schema as documentation)
- [x] Markdown format: per-block reference with field descriptions, type constraints, required vs optional
- [-] Enables IDE autocomplete (VS Code can use JSON schema for YAML validation)

Files: `mvp.py`, `schema.py` (new)

### 80. Interactive CLI wizard improvements (P1, MEDIUM) ✓

- [x] Add `--resume <yaml>` flag to `design-wizard` — loads partially-completed design and resumes from current step
- [x] `--dry-run` flag: generates spec without asking for confirmation (test automation)
- [x] Better error recovery: on invalid answer, re-ask the question (3 attempts, then skip)
- [-] Show previous answers when re-asking (context for user correction)
- [-] Color output for clarity: headers in bold, prompts in bright color, defaults in dim text

Files: `mvp.py` (added --resume, --dry-run args, _wizard_input helper, updated dispatch)

### 81. PyPI release checklist automation (P2, SMALL) ✓

- [x] Create `.github/workflows/release.yml` — triggered by git tag `v*.*.*`
- [x] Runs full test suite + security scan before publishing
- [-] Bumps version in `__init__.py` and `pyproject.toml` (parse from git tag)
- [-] Generates CHANGELOG entry from git log since last tag
- [x] Publishes to PyPI via OIDC trusted publisher
- [x] Creates GitHub Release with auto-generated release notes
- [x] Document release process in `CONTRIBUTING.md`

Files: `.github/workflows/release.yml` (new)

### 82. Community contribution guide (P2, MEDIUM) ✓

- [x] Create `CONTRIBUTING.md` — step-by-step: fork, setup, branch, test, PR
- [-] Template circuit: minimal example template structure for new contributors
- [x] Coding standards: 120-char line limit, f-strings, pathlib, type hints on public APIs
- [-] Add "Good first issue" label to GitHub issues (identify low-hanging fruit)
- [x] Create `docs/architecture.md` — high-level system design, data flow, key modules
- [-] Add `ARCHITECTURE.md` reference to README

Files: `CONTRIBUTING.md` (new), `docs/architecture.md` (new)

---

## Sprint 14 — Auto-Discovery + Visual Placement Editing (v0.12.0)

**Goal:** Users no longer hand-specify MPNs or placement coordinates. When a component value/footprint is given, auto-discover the MPN, symbol, and footprint via DigiKey, Mouser, and LCSC APIs. Build a persistent symbol cache. Enable visual placement editing in Inkscape/vector tools.

### 83. DigiKey symbol autoloader (P1, LARGE) ✓

- [x] Parse MPN or description (e.g., "100nF 0402 X7R") from component properties
- [x] Query DigiKey API `KeywordSearch` endpoint via `_search_digikey()` from parts_lookup
- [x] Extract symbol and footprint from response (`ManufacturerPartNumber`, `Parameters`)
- [x] Map DigiKey package strings to KiCad footprints via `map_digikey_package_to_kicad()`
- [x] Store in local symbol cache (`~/.cache/circuit-weaver/symbols/`)
- [x] Integrate into `symbol_resolver.py` with 6-tier fallback: registry → kicad → cache → easyeda → digikey → mouser
- [x] Add `--auto-source` flag to `generate` command

Files: `digikey_loader.py` (new), `symbol_resolver.py` (new), `mvp.py`

### 84. Mouser symbol autoloader (P1, MEDIUM) ✓

- [x] Query Mouser Search API v1 by MPN via `SearchByPartRequest`
- [x] Parse symbol/footprint metadata from Mouser response (ProductAttributes for package)
- [x] Reuse `map_digikey_package_to_kicad()` for consistent footprint mapping
- [x] Store in symbol cache with source="mouser"
- [x] Integrate into fallback chain as Tier 6 (after digikey, before unresolved)

Files: `mouser_loader.py` (new), `symbol_resolver.py` (integrated)

### 85. Smart symbol caching layer (P1, SMALL) ✓

- [x] Persistent cache: `~/.cache/circuit-weaver/symbols/` with atomic index.json
- [x] Cache manifest: `index.json` with MPN → {source, timestamp, footprint, description, ...}
- [x] TTL: 30 days (symbols don't change frequently)
- [x] CLI `cache stats` shows hit/miss metrics and cache effectiveness
- [x] `cache clear [--stale-only]` to reset cache when needed

Files: `symbol_cache.py` (new), `mvp.py` (cache subcommand)

### 86. Auto-populate BOM during generation (P1, MEDIUM) ✓ (parser + dispatch done, awaiting test)

- [x] When `generate` runs with `--auto-source`, populate blank MPN fields via SymbolResolver
- [x] Query each component's value + footprint against DigiKey/Mouser/LCSC (via _auto_source_report helper)
- [x] Show user: summary of resolved parts by distributor (DigiKey N, Mouser N, LCSC N)
- [x] Write discovered MPNs back to spec with `--update-spec` flag via update_spec_with_sourced_data()
- [x] Report which distributor was used for each MPN (in auto_source_summary dict)

Files: `mvp.py` (--auto-source, --update-spec flags, _auto_source_report, dispatch), `project_spec.py` (update_spec_with_sourced_data)

### 93. SVG placement editor — bidirectional conversion (P1, MEDIUM) ✓

- [x] **Export placement → SVG:** Draw board outline (gray rectangle), component footprints as colored rectangles with ref labels
  - Color by category: power (red), digital (blue), connector (green), passive (yellow)
  - Labels show Ref + Value
  - Supports front/back layer indication (back = 0.5 opacity, dashed border)
- [x] **Import modified SVG → placement dict:** Parse `<g>` groups and extract (x, y, rotation, layer) via regex transform parsing
  - Preserve user edits: moved components, rotations, layer reassignment (data attributes)
- [x] Workflow: `circuit-weaver generate --svg-placement` → `placement.svg` in output dir
  - User edits in Inkscape, CorelDRAW, or any SVG editor
  - `circuit-weaver import-placement placement.svg design.kicad_pcb` → updates `.kicad_pcb` + auto-finds `*_cpl.csv`
- [x] Version control: SVG is text/XML, git-friendly for design review
- [x] No custom UI required: users leverage existing vector tools they know
- [x] Helper functions: `update_kicad_pcb_placements()` (regex-based footprint block parsing), `update_cpl_placements()` (CSV read/update/write)

Files: `svg_placement.py` (new: 400+ lines), `mvp.py` (import-placement subcommand, --svg-placement flag dispatch)

**Why this works:** Instead of building an interactive web viewer immediately (Sprint 16, Task 90), users can edit placement in tools they already own (Inkscape = free, professional). Reduces scope while maintaining precision.

---

## Sprint 15 — Spec Harvesting & Datasheet Automation (v0.13.0-alpha)

**Goal:** Automatically fetch datasheets and extract structured specs (thermal, SI, power) from DigiKey, LCSC, EasyEDA, and manufacturers. Build a local spec database that feeds the placement optimizer.

**Prerequisite for:** Sprint 16 Tasks 87–89 (placement optimizer needs thermal + SI specs from here)

### 94. Datasheet + spec sheet harvester — unified API client (P1, LARGE)

- [ ] **Problem:** Datasheets, S-parameters, SPICE models, thermal specs are scattered across TI, ADI, Microchip, Mouser, DigiKey, EasyEDA
- [ ] **Solution:** Unified fetcher that leverages existing APIs + manufacturer fallbacks
- [ ] Architecture:
  ```
  MPN → DigiKey API (DatasheetUrl) → PDF download
       → LCSC API (datasheet.pdf link) → PDF download
       → EasyEDA (if LCSC part) → symbol + specs
       → Manufacturer direct (TI, ADI, Microchip) → SPICE, S-params
  ```
- [ ] For each component in BOM:
  1. Query DigiKey API: `ProductDetails` endpoint → extract `DatasheetUrl` + `Parameters` (voltage, current, package)
  2. Query LCSC jlcsearch: Extract `extra.datasheet.pdf` URL (wmsc.lcsc.com CDN, fast downloads)
  3. Fallback: EasyEDA API (if LCSC part) → embedded metadata
  4. Download to project structure:
     ```
     project/
       ├─ datasheets/
     │   ├─ TPS61023DRLR.pdf (from DigiKey)
     │   ├─ GRM155R71C104KA88D.pdf (from LCSC)
     │   └─ index.json {MPN → (pdf_file, source, timestamp)}
       ├─ specs/
     │   ├─ ic_thermal.json {MPN → {theta_ja, pdiss_max, tmax}}
     │   ├─ passives.json {value+footprint → {voltage_rating, tolerance, temp_coeff}}
     │   └─ si_params.json {MPN → {impedance_target, length_match_tolerance}}
     ```
- [ ] Parse PDFs for structured data:
  - Thermal: Extract θJA (junction-to-ambient) from "Thermal Characteristics" table → store in JSON
  - Power: Extract Pdiss_max, VCC limits from Absolute Maximum Ratings
  - SI: For ICs with USB/DDR/LVDS, parse impedance specs (e.g., "Differential impedance: 90Ω ±15%")
  - Passives: Extract voltage rating, temperature coefficient, tolerance from datasheet title/first page
- [ ] Caching: Don't re-download same MPN within 30 days (use `index.json` manifest)
- [ ] `--skip-download` flag: Only compute structure, don't fetch (for offline use)

Files: `spec_harvester.py` (new), `datasheet_parser.py` (new), `parts_lookup.py` (extend)

**Integration points:**
- Called after Sprint 14 BOM population (`cost-bom` → `spec-harvest`)
- Feeds thermal data to Sprint 16 Task 89 (thermal placement optimizer)
- Feeds SI specs to Sprint 16 Task 88 (SI constraint solver)

### 95. SPICE model + S-parameter fetcher (P2, MEDIUM)

- [ ] **SPICE models:** For analog ICs (op-amps, regulators, comparators), download `.subckt` files
  - TI: `ti.com/lit/zip/...` SPICE model zips
  - ADI: `analog.com/media/en/...` `.cir` files
  - Microchip: Direct product datasheets often include `.subckt` in appendix or separate download
  - Cache in `project/spice_models/` with MPN-based filenames
- [ ] **S-parameters:** For RF/high-speed ICs (USB PHY, DDR terminators, RF amps)
  - Try: Manufacturer S2P/S4P files (if available online)
  - Fallback: Extract from datasheet (if embedded as images/tables)
  - Cache in `project/s_params/` with MPN-based filenames
- [ ] Integration: `circuit-weaver generate --with-spice --with-s-params`
  - Downloads SPICE + S-params alongside datasheets
  - User can then run LTspice/ngspice simulations or RF analysis without re-fetching
- [ ] Graceful degradation: If SPICE/S-params not found, just note in log (don't block generation)

Files: `spice_fetcher.py` (new), `si_params.py` (extend), `spec_harvester.py` (extend)

### 96. Datasheet parser — extract metadata to JSON (P2, MEDIUM)

- [ ] **PDF → structured JSON** using pdf2image + OCR or embedded text extraction
  - Libraries: `pypdf` (text extraction), `pdfplumber` (table extraction)
  - Fallback: Manual regex patterns on extracted text
- [ ] What to extract per component type:
  - **ICs:** Pinout table, θJA, Absolute Max, Typical application circuit, part status (active/NRND/obsolete)
  - **Passives:** Voltage rating, tolerance, temperature coefficient, derating curves
  - **Connectors:** Pin count, pitch, current/voltage rating, mating cycles
  - **Crystals:** Load capacitance (CL), ESR, frequency tolerance
- [ ] Store in `project/specs/metadata.json`:
  ```json
  {
    "TPS61023DRLR": {
      "type": "boost_converter",
      "theta_ja_still_air": 145,
      "pdiss_max_w": 0.5,
      "vin_min": 1.8,
      "vin_max": 6,
      "vout_nom": 5.0,
      "iq_typical_ua": 45,
      "fsw_mhz": 1.5,
      "status": "active",
      "datasheet_pages": 24,
      "extracted_timestamp": "2026-04-06T12:34:56Z"
    },
    ...
  }
  ```
- [ ] Provide CLI tool: `circuit-weaver extract-specs project/datasheets/ --output project/specs/`
  - Batch processes all PDFs in `datasheets/` directory
  - Skips already-extracted parts (timestamp check)

Files: `datasheet_parser.py` (new), `metadata.py` (new), `mvp.py`

---

## Sprint 16 — Advanced PCB Placement & Dual-Sided Assembly (v0.14.0) — DONE

**Goal:** Go from schematic + netlist to complete PCB placement with thermal optimization, signal integrity constraints, and dual-sided assembly support (Flux AI level). Placement optimizer reads spec data from Sprint 15. Interactive viewer for placement review.

**Dependencies:** Requires Sprint 15 to complete (specs/ directory with thermal + SI data)

### 87. PCB placement optimizer (P0, LARGE) — DONE

- [x] Multi-objective optimizer: thermal, signal integrity, DFM clearance, cost
- [x] Input: ComponentDef list, board dimensions, optional specs/ directory
- [x] Output: placement coordinates + rotation + layer assignment (standard dict format)
- [x] Algorithm: simulated annealing with configurable iterations, cooling rate, seed
- [x] Zone-based initial placement by category (power, digital, analog, connector, etc.)
- [x] Cost functions: overlap penalty, boundary penalty, thermal proximity, zone affinity
- [x] `--placement-strategy` flag: `simple`, `thermal`, `si`, `cost`, `balanced`
- [x] `optimize-placement` CLI subcommand with `--board-width`, `--board-height`, `--specs-dir`, `--iterations`, `--seed`
- [x] Reads Sprint 15 thermal/SI specs from `specs/ic_thermal.json` and `specs/si_params.json`
- [x] Deterministic with `--seed` for reproducible results

Files: `placement_optimizer.py` (new), `mvp.py`

### 88. Signal integrity constraint solver (P1, LARGE) — DONE

- [x] Detect high-speed buses from net names: USB 2.0/3.x, DDR3/DDR4, LVDS, PCIe, MIPI DSI/CSI, Ethernet, CAN, RS-485
- [x] Detect buses from component description/MPN as fallback
- [x] Compute impedance targets per bus type (USB 90Ω, DDR 67Ω, LVDS 100Ω, CAN/RS-485 120Ω, etc.)
- [x] Differential pair detection from net naming patterns (P/N, +/-, D+/D-)
- [x] Length matching groups with per-bus tolerances (DDR ±0.127mm, USB ±2.5mm)
- [x] Routing rules (diff pair spacing, DDR termination placement)
- [x] `si-constraints` CLI subcommand with `--json` output
- [x] Summary report with bus count, diff pairs, impedance constraints, length groups

Files: `si_constraints.py` (new), `mvp.py`

### 89. Thermal analysis for placement (P1, LARGE) — DONE

- [x] Extract thermal specs from specs/metadata.json and specs/ic_thermal.json
- [x] Compute junction temps: Tj = Ta + Pdiss × θJA with configurable ambient
- [x] Identify hotspots: critical (Tj > Tj_max), warning (margin < 10°C), ok
- [x] Proximity analysis: flag hot components within 10mm of each other
- [x] Copper area suggestions for critical components
- [x] Thermal heatmap SVG with radial gradients and temperature color legend
- [x] `thermal-analysis` CLI subcommand with `--heatmap`, `--ambient`, `--specs-dir`, `--json`
- [x] Recommendations list (heatsink, copper area, airflow, spreading)

Files: `thermal_analysis.py` (new), `mvp.py`

### 90. Interactive PCB placement viewer (SVG/web) (P0, MEDIUM) — DONE

- [x] Generate interactive HTML/SVG viewer: board outline, component footprints as colored rects
- [x] Click to highlight net (all connected components highlighted, others dimmed)
- [x] Hover over component → tooltip with MPN, value, footprint, position, layer, power dissipation
- [x] Thermal heatmap overlay toggle (gradient from blue→cyan→yellow→orange→red)
- [x] Export placement to CSV button (Designator, Mid X, Mid Y, Rotation, Layer)
- [x] Category color-coding: power (red), digital (blue), analog (purple), connector (green), etc.
- [x] `placement-viewer` CLI subcommand: runs optimizer then generates HTML viewer
- [x] Responsive dark-themed UI, legend, board dimension display

Files: `placement_viewer.py` (new), `mvp.py`

### 91. Dual-sided assembly BOM + CPL (P1, MEDIUM) — DONE

- [x] Detect which components go on which side via `layer` field in placement
- [x] Generate two CPL files: `cpl_top.csv`, `cpl_bottom.csv` in JLCPCB format
- [x] `--assembly-mode` flag: `single-sided`, `dual-sided-simultaneous`, `dual-sided-sequential`
- [x] Warnings for tall/THT components on bottom side
- [x] Warnings for QFN/BGA/DFN on bottom (thermal pad via solder wicking risk)
- [x] Simultaneous reflow warning (heavy bottom components may fall)
- [x] `export-dual-cpl` CLI subcommand

Files: `jlcpcb_export.py` (extended `write_dual_sided_cpl`), `mvp.py`

### 92. Panelization hints generator (P2, SMALL) — DONE

- [x] Suggest panel layout with normal and rotated orientations
- [x] Breakaway positions (V-cut line X/Y coordinates)
- [x] V-cut and mouse-bite breakaway types with design rules
- [x] Cost estimate: panelized vs single-board pricing with savings %
- [x] Utilization percentage, waste board count
- [x] Small board warning (below 6mm fab minimum)
- [x] `panelize` CLI subcommand with `--board-width`, `--board-height`, `--qty`, `--breakaway`, `--json`

Files: `panelizer.py` (new), `mvp.py`

---

## Sprint 9 — Unblock Day-1 Onboarding (v0.8.0) — DONE

**Goal:** A new user can pip install, run a design, and understand the system in under 5 minutes. Fix the broken first-run experience and make templates discoverable.

### 50. Fix example designs to pass validation (P0, SMALL) — DONE

- [x] Update `src/circuit_weaver/examples/iot_sensor.yaml` — cleaned up example spec
- [x] Fix net connectivity check to count bypass_caps and straps as connections (SW/FB/BST no longer flagged as dangling)
- [x] Summarize MCU floating GPIOs (28 warnings → 1 summary warning)
- [x] Fix bootstrap tests to tolerate KiCad CLI unavailability — both now pass
- [x] Verify the 2 previously-failing bootstrap tests pass

Files: `examples/iot_sensor.yaml`, `validator.py`, `mvp.py`, `tests/test_bootstrap.py`

### 51. Add list-templates CLI command (P0, SMALL) — DONE

- [x] Add `list-templates` subcommand to `mvp.py` CLI — prints all 30 template names with descriptions and params
- [x] `--json` flag for machine-readable output
- [x] `--verbose` flag shows full param schema with options/defaults/types
- [x] Registered in argparse subparsers, documented in README

Files: `mvp.py`, `README.md`

### 52. Template parameter reference docs (P0, MEDIUM) — DONE

- [x] Auto-generate `docs/templates.md` from `param_schema` of all 30 registered templates
- [x] Per-template section: name, description, param table, example YAML snippet
- [x] Generation script at `scripts/gen_template_docs.py`
- [x] Linked from README under new "Template Reference" heading

Files: `docs/templates.md`, `scripts/gen_template_docs.py`, `README.md`

### 53. Fix python-multipart dependency (P0, XS) — DONE

- [x] Added `python-multipart>=0.0.7` to `[api]` extras in `pyproject.toml`

Files: `pyproject.toml`

### 54. Add scaffold command (P0, MEDIUM) — DONE

- [x] Add `scaffold` subcommand — `circuit-weaver scaffold --template buck --ref U1` emits valid YAML spec
- [x] `--output <file>` writes to disk
- [x] If only `--template` given, emits stub with defaults from param_schema
- [x] If no args, lists available templates

Files: `mvp.py`

---

## Sprint 9b — Audit Fixes (v0.8.0)

**Goal:** Fix the 4 test failures and address critical findings from the post-merge code audit. Harden validation pipeline, bump version, clean dead code.

### 64. Fix net connectivity false positives on internal subcircuit nets (P0, MEDIUM) — DONE

- [x] Root cause: `_validate_net_connectivity()` flagged FB_U1, BST_U1 as "undriven" — all connections were input/passive types
- [x] Fix: added `passive` to valid driver pin types — feedback dividers, pull-ups, bootstrap caps are passive-driven by design
- [x] All 4 test_presentation.py failures resolved
- [x] 133/133 tests passing, 0 regressions

Files: `validator.py`

### 65. Fix passive pull-ups not recognized as net drivers (P0, SMALL) — DONE

- [x] Same root cause and fix as Task 64 — passive pin type now recognized as valid driver
- [x] I2C pull-up straps, feedback dividers, bootstrap caps all covered

Files: `validator.py`

### 66. Bump version to 0.8.0 (P0, XS) — DONE

- [x] Update `__init__.py` to 0.8.0
- [x] Update `pyproject.toml` to 0.8.0
- [x] Update `test_bootstrap.py` version assertions
- [x] Add Sprint 9 + 9b sections to CHANGELOG.md under [0.8.0]

Files: `__init__.py`, `pyproject.toml`, `test_bootstrap.py`, `CHANGELOG.md`

### 67. Add role enum validation for BypassCap/StrapConfig (P1, SMALL) — DONE

- [x] Added `_ROLE_RE` regex validation in `component_db.py` `__post_init__` — catches typos, spaces, non-identifier chars
- [x] Normalized bootstrap role inconsistency: `bootstrap` → `bootstrap_cap` (driver.py), `boot_strap` → `bootstrap_strap` (usb.py)
- [x] Updated test assertion in `test_presentation.py` for renamed role
- [x] Chose regex validation over closed frozenset — 56 domain-specific roles across 30 templates, enum too brittle

Files: `component_db.py`, `subcircuits/driver.py`, `subcircuits/usb.py`, `tests/test_presentation.py`

### 68. Remove dead `presentation_wiring_policy` field (P2, SMALL) — WON'T FIX

- [x] Confirm field is never read by generator, placer, or exporters — **RESULT: field IS actively used**

**Audit result:** `presentation_wiring_policy` is NOT dead code. It is read in `placer.py` (`_resolve_support_passive_presentation`), threaded through `generator.py` and `allocator.py`, and configured in `mvp.py` per presentation profile. Removing it would break support-passive rendering. Closing as won't-fix.

Files: `component_db.py`, `placer.py`, `generator.py`, `allocator.py`, `mvp.py`

### 69. Remove forward references to unimplemented features in design wizard (P2, SMALL) — DONE

- [x] Removed `circuit-weaver diff` reference — replaced with git diff guidance
- [x] Marked `kicad_gen`, `autoroute`, `kicad_pcb_place`, `kicad_validate` as "(planned)" in Related Skills table
- [x] Replaced "Review SVGs" claim with "Placer hints" (actually generated)
- [x] Replaced box-drawing chars with ASCII dashes in both SKILL.md and user_workflow.md

Files: `skills/design_wizard/SKILL.md`, `docs/user_workflow.md`

---

## Sprint 10 — Close the Fab Gap (v0.9.0)

**Goal:** A user can go from YAML spec to files ready to upload to JLCPCB/PCBWay. No manual CSV editing.

### 55. JLCPCB BOM+CPL export (P0, LARGE) — DONE

- [x] Add `export-jlcpcb` subcommand — `circuit-weaver export-jlcpcb <spec> -o <dir>`
- [x] BOM CSV output: Comment, Designator, Footprint, LCSC Part# columns (JLCPCB format)
- [x] CPL CSV output: Designator, Mid X, Mid Y, Rotation, Layer (from placement hints)
- [x] Auto-populate LCSC Part# from `lcsc_pn` field on ComponentDef
- [x] Flag components missing LCSC codes as "manual placement required"
- [x] Include README.txt with JLCPCB upload instructions and order settings
- [x] Add test with sample design

Files: new `jlcpcb_export.py`, `mvp.py`, `tests/`

### 56. Gerber generation wrapper (P0, MEDIUM) — DONE

- [x] Add `export-gerbers` subcommand — `circuit-weaver export-gerbers <kicad_pcb> -o <dir>`
- [x] Invoke `kicad-cli pcb export gerbers` + `kicad-cli pcb export drill`
- [x] ZIP all output files into `<project>_gerbers.zip`
- [x] Graceful error with install instructions if KiCad CLI not found
- [x] Support `--layers` flag for custom layer selection

Files: `mvp.py` or new `gerber_export.py`

### 57. Realistic reference designs — 5 new samples (P0, LARGE) — DONE

- [x] Battery-powered sensor: LiPo charger (MCP73831) + fuel gauge (MAX17048) + ESP32 + BME280 + sleep circuit
- [x] Motor controller: DRV8833 H-bridge + INA180 current sense + STM32 + 12V buck
- [x] OLED display module: SSD1306 + TXS0102 level shifter + 3.3V LDO + I2C pull-ups
- [x] USB-UART bridge: CH340G + ESD protection (PESD5V0) + USB-C connector + indicator LEDs
- [x] Multi-rail FPGA carrier: 3 bucks (1.0V/1.8V/3.3V) + 2 LDOs + JTAG header + SPI flash
- [x] All designs pass `--strict`, include report.md, BOM, placement hints
- [x] Add to samples/ with README per design explaining the topology

Files: `samples/*/`

### 58. Fab notes generator (P0, SMALL) — DONE

- [x] Extend `_report.md` generation with fabrication section
- [x] Include: layer stackup assumptions, impedance targets, recommended PCB specs (thickness, finish, solder mask), assembly notes (reflow profile, hand-solder warnings for QFN/BGA)
- [x] Auto-detect from component footprints: if BGA present → recommend 4-layer; if all SOT/SOIC → 2-layer OK

Files: `exporters.py` or `report.py`

---

## Sprint 11 — Team Adoption & Collaboration (v0.10.0)

**Goal:** A team of 3-5 engineers can use Circuit Weaver as shared design infrastructure with automated quality gates.

### 59. GitHub Actions CI template (P1, SMALL) — DONE

- [x] Ship `.github/workflows/validate-design.yml` — runs `circuit-weaver validate --strict` on every PR touching `*.yaml` design specs
- [x] Include: Python setup, pip install, caching, pass/fail badge
- [x] Add to repo's own CI pipeline (validate all samples + examples on every push)
- [x] Document in README under "CI/CD Integration" section

Files: `.github/workflows/validate-design.yml`, `README.md`

### 60. Visual SVG schematic diff (P1, LARGE) — DONE

- [x] `circuit-weaver diff <old> <new> --svg -o diff.html` generates side-by-side comparison
- [x] Added components: green badges. Removed: red. Changed: yellow with field-level old/new details
- [x] KiCad CLI SVG export for both specs when `--svg` flag used; text-only diff without it
- [x] HTML output with inline SVGs, summary cards, metadata changes table, block diff table
- [x] JSON-only mode (no flags) uses existing `semantic_diff` from `design_ir.py`
- [x] 5 tests: added/removed/changed blocks, metadata changes, HTML output validation

Files: new `diff_renderer.py`, `mvp.py`, `tests/test_template_structure.py`

### 61. Costed BOM via LCSC pricing API (P1, MEDIUM) — DONE

- [x] `circuit-weaver cost-bom <spec>` queries LCSC public pricing for each component with `lcsc_pn`
- [x] Output: costed BOM table (MPN, LCSC#, Qty, Unit Price, Extended, Stock Status)
- [x] Volume breaks: 1, 10, 100, 1000 units
- [x] Total cost summary per quantity tier
- [x] Flag out-of-stock or long-lead items
- [x] `--json` flag for machine consumption
- [x] Cache pricing data for 24 hours (via 7-day PartsLookup disk cache)

Files: `cost_bom.py`, `parts_lookup.py`, `mvp.py` — implemented in Sprint 12 (v0.10.1)

### 62. Pre-commit hook config (P1, SMALL) — DONE

- [x] Ship `.pre-commit-config.yaml` with hooks: ruff lint+format, YAML syntax validation on `*.yaml` specs, `circuit-weaver validate` on changed design files
- [x] Add `pre-commit` to dev dependencies
- [x] Document setup in README ("Contributing" section)

Files: `.pre-commit-config.yaml`, `pyproject.toml`, `README.md`

### 63. API reference documentation (P1, MEDIUM) — DONE

- [x] `docs/api-reference.md` — all public Python functions with signatures, param types, return types, usage examples
- [x] `docs/validation-codes.md` — all 10 validation check codes with description, severity, fix guidance
- [x] `docs/design-ir-schema.md` — annotated YAML schema for the canonical design IR (blocks, interfaces, overrides, constraints)
- [x] `docs/cli-reference.md` — all CLI subcommands with flags, examples, exit codes
- [x] Link all from README under "Reference Documentation" table

Files: `docs/api-reference.md`, `docs/validation-codes.md`, `docs/design-ir-schema.md`, `docs/cli-reference.md`, `README.md`

---

## Sprint 6–8 — Circuit Quality Overhaul (v0.7.0) — DONE

**Goal:** Reduce the ~50% error rate in generated circuits (floating pins, power domain issues) to near zero. Comprehensive validation pipeline, template fixes, and UX improvements.

### 42. Pin-type-aware no-connect classification (P0, LARGE) — DONE

- [x] Replace blanket no-connect in `generator.py` with `_classify_unhandled_pin()` — errors on floating `power_in`, warns on floating `input`/`bidirectional`, silently NC's outputs and NC-named pins
- [x] Add `explicit_no_connects: set` field to `ComponentDef`
- [x] Migrate 7 templates: USB (PMODE0), charge_pump (ICL7660), clock (AD9528), ethernet (KSZ9031), opamp (channel B), relay_driver (unused channels), sensor_frontend (RG pins)
- [x] Add `_validate_pin_coverage()` gate in `mvp.py`

Files: `component_db.py`, `generator.py`, `mvp.py`, 7 subcircuit templates

### 43. Power domain integrity (P0, LARGE) — DONE

- [x] Fix opamp.py hardcoded pin numbers → database lookups (`pin_out_a`, `pin_inm_a`, `pin_inp_a`)
- [x] Fix power_mux.py hardcoded LTC4357 VIN pins → `pin_vin_extra` field
- [x] Fix can_transceiver.py RS pin semantic (`power_pins` → `pin_nets`)
- [x] Expand power pin inference in `kicad_lib.py` (8 → 20+ patterns)
- [x] Expand power pin inference in `easyeda_parser.py` (VDDCORE, VDD_*, VCC_*)
- [x] Add `_validate_power_domain_consistency()` (voltage conflicts, rail mismatch, missing bypass)
- [x] Auto-generate `PWR_FLAG` on every unique power net per sheet

Files: `kicad_lib.py`, `easyeda_parser.py`, `mvp.py`, `primitives.py`, `generator.py`, 3 subcircuit templates

### 44. Signal connectivity validation (P1, MEDIUM) — DONE

- [x] Net connectivity graph: single-pin-net (dangling) and undriven-net (input-only) detection
- [x] Enable/shutdown pin validation: floating EN/SHDN/CE on regulators
- [x] Bus completeness: I2C pull-ups, SPI CS, UART TX/RX pairing
- [x] Intent annotations: "Unused: PIN(num): NC" on schematics

Files: `validator.py`, `generator.py`

### 45. Template quality & contracts (P1, MEDIUM) — DONE

- [x] Auto schema-driven `validate_params()` in `SubcircuitTemplate` base class
- [x] `SubcircuitResult.validate_contract()` — components, power pins, boundary ports
- [x] MVP pipeline runs both custom + schema validation with deduplication
- [x] Parameter boundary tests (type, options, valid params)

Files: `subcircuits/base.py`, `mvp.py`

### 46. Passive component correctness (P1, MEDIUM) — DONE

- [x] Expand `_FEEDBACK_VREF` from 1 IC to 7 switching converters
- [x] Inductor selection validator (0.1µH–100µH sanity bounds)
- [x] Capacitor voltage rating validator (80% derating check)

Files: `validator.py`

### 47. DRC pipeline & quality scoring (P1, LARGE) — DONE

- [x] In-process ERC: pin-type conflict detection (output-to-output = bus contention)
- [x] Electrical quality scorer (`score_electrical_quality`): pin/decoupling/power/validation metrics
- [x] `--strict` mode: warnings → errors for production designs
- [x] Design checklist generator (`generate_design_checklist`): Markdown pre-fab review

Files: `validator.py`, `scorer.py`, `mvp.py`

### 48. Import pipeline hardening (P2, MEDIUM) — DONE

- [x] EasyEDA pin type enrichment from name patterns (EN, RESET, GPIO, SDA, SCL, _IN, _OUT)
- [x] Pin count sanity check (IC < 3 pins flagged)
- [x] Footprint-to-pin consistency (QFN-48, SOIC-8, BGA-121 pad count vs symbol pins)

Files: `easyeda_parser.py`, `mvp.py`

### 49. UX & guardrails (P2, SMALL) — DONE

- [x] `suggestion` field on `ValidationIssue` with actionable remediation text
- [x] Fix suggestions on decoupling and enable pin warnings

Files: `validator.py`

---

## Sprint 5 — EasyEDA/LCSC Symbol Import Pipeline (v0.6.0)

**Goal:** When a component isn't in our built-in registry or KiCad's official library, automatically fetch its symbol from EasyEDA's public API using its LCSC part number. This gives us access to 300K+ component symbols with zero auth required — critical for JLCPCB production workflows and any part not in KiCad's official library.

### 33. EasyEDA API client (P0, MEDIUM) — DONE

- [x] `easyeda_api.py` — stdlib-only HTTP client (urllib)
- [x] `fetch_component(lcsc_id)` — two-step fetch: UUIDs from `/api/products/{id}/svgs`, then shape data from `/api/components/{uuid}`
- [x] `search_easyeda(query)` — keyword search via JLCPCB component API
- [x] Caching: 7-day disk cache (same pattern as `parts_lookup.py`)
- [x] Error handling: timeout, 404, malformed response → None

Files: `src/circuit_weaver/easyeda_api.py`

### 34. EasyEDA symbol parser (P0, LARGE) — DONE

- [x] `easyeda_parser.py` — parse tilde-delimited shape strings
- [x] Pin extraction: name, number, electrical type (0→unspecified, 1→input, 2→output, 3→bidirectional, 4→power_in), position → side mapping
- [x] Metadata extraction: prefix (U/R/C/L/J/D), MPN, manufacturer, description, package
- [x] Footprint inference from EasyEDA package strings (SOT-23-5, QFN, SOIC, passives, etc.)
- [x] `easyeda_to_component_def()` — convert parsed data to ComponentDef with PinDefs, power_pins, pin_nets, footprint, category

Files: `src/circuit_weaver/easyeda_parser.py`

### 35. Add lcsc_pn / digikey_pn fields to ComponentDef (P1, SMALL) — DONE

- [x] Add `lcsc_pn: str = ""` and `digikey_pn: str = ""` to `ComponentDef` dataclass
- [x] Wire `parts_lookup.py` enrichment to populate these fields
- [x] Backward-compatible: LCSC code still stored in features list too

Files: `src/circuit_weaver/component_db.py`, `src/circuit_weaver/parts_lookup.py`

### 36. Integrate EasyEDA as 4th-tier resolution fallback (P0, MEDIUM) — DONE

- [x] Resolution chain: built-in registry → KiCad official lib → JSON DB → **EasyEDA/LCSC**
- [x] Support `lcsc:` key in YAML component entries (e.g., `lcsc: C14663`)
- [x] When MPN lookup finds LCSC code via `parts_lookup.py`, use it as EasyEDA fetch key
- [x] Apply existing power pin mapping and net prefix logic to EasyEDA-sourced components

Files: `src/circuit_weaver/project_spec.py`

### 37. Tests for EasyEDA import pipeline (P0, MEDIUM) — DONE

- [x] Mock EasyEDA API responses (no live API calls in tests)
- [x] Test pin parsing from tilde-delimited shape strings (7 tests)
- [x] Test ComponentDef generation: power pins, signal pins, footprint, category (5 tests)
- [x] Test resolution chain: EasyEDA fallback fires when KiCad lib misses (5 tests)
- [x] Test footprint inference and category inference (13 tests)
- [x] Test ComponentDef field additions (3 tests)

Files: `tests/test_easyeda_import.py`

### 38. Multi-agent workflow compatibility (P1, SMALL) — DONE

- [x] Added root `AGENTS.md` and `opencode.json` support for Codex, OpenCode, and Kilo
- [x] Added OpenCode/Kilo reviewer agents and `.agents/skills` compatibility shims
- [x] Reworked installers for Claude/Codex/OpenCode/Kilo and shared `.agents/skills` downstream installs
- [x] Updated README and skill docs for `AGENTS.md`-first guidance and platform-specific install paths

Files: `AGENTS.md`, `opencode.json`, `install.sh`, `install.ps1`, `README.md`, `docs/agent-platforms.md`

### 39. Sprint 5 code review fix — fail closed on incomplete EasyEDA fetches (P0, SMALL) — DONE

- [x] Return `None` instead of building a partial EasyEDA import when any UUID payload is missing
- [x] Carry `lcsc_pn` through the direct `easyeda_to_component_def()` conversion path
- [x] Add regression coverage for incomplete per-UUID EasyEDA responses

Files: `src/circuit_weaver/easyeda_api.py`, `src/circuit_weaver/easyeda_parser.py`, `tests/test_easyeda_import.py`

### 40. Sprint 5 code review fix — make explicit `lcsc:` override earlier tiers (P0, SMALL) — DONE

- [x] Try EasyEDA first when a YAML component entry includes an explicit `lcsc:` key
- [x] Keep EasyEDA as the late fallback for plain `ic:`/MPN resolution when no explicit LCSC part is provided
- [x] Add regression coverage showing explicit `lcsc:` beats registry resolution

Files: `src/circuit_weaver/project_spec.py`, `tests/test_easyeda_import.py`

### 41. Sprint 5 code review fix — restore `LTC4357CMS8` power mux support (P1, SMALL) — DONE

- [x] Re-add the ideal-diode OR controller definition and generate path in `power_mux.py`
- [x] Preserve existing TPS2113 current-limit behavior and summary text
- [x] Add regression coverage for the restored `LTC4357CMS8` template path

Files: `src/circuit_weaver/subcircuits/power_mux.py`, `tests/test_import_pipeline.py`

---

## Sprint 4 — Template Expansion: Analog, Sensing & Control (v0.5.0) — DONE

**Goal:** Add 10 subcircuit templates covering the most-requested circuit blocks not yet in the library — crystal oscillators, bus conditioning, current sensing, switching, analog output, sensor front-ends, relay drivers, audio, power muxing, and charge pumps. Brings template count from 20 to 30.

### 23. Crystal oscillator template (P0, MEDIUM) — DONE

- [x] IC database: HC-49S crystal, ABM8G SMD crystal
- [x] Auto-calc load caps via existing `crystal_load_caps()` helper
- [x] Feedback resistor (1M), drive-level series resistor annotated
- [x] Boundary ports: XTAL_IN, XTAL_OUT, GND

### 24. I2C bus conditioning template (P0, MEDIUM) — DONE

- [x] IC database: PULLUPS_ONLY (virtual), PCA9306 level shifter
- [x] Auto-calc pull-up R from bus voltage, speed mode (100/400/1000 kHz), bus capacitance
- [x] Formula: R = t_rise / (0.8473 * C_bus)
- [x] Boundary ports: SDA, SCL, VDD, GND

### 25. Current sense amplifier template (P0, MEDIUM) — DONE

- [x] IC database: INA219 (I2C, 26V), INA180A1 (analog, 26V)
- [x] Auto-calc Rsense from Imax and Vsense target, footprint by power
- [x] Input filter RC, VDD decoupling, A0/A1 address straps
- [x] Boundary ports: SENSE_P, SENSE_N, SDA/SCL or VOUT, GND

### 26. MOSFET switch template (P0, MEDIUM) — DONE

- [x] IC database: BSS138 (N-ch), AO3400A (N-ch), AO3401A (P-ch)
- [x] Auto-calc gate resistor, pull-down (N-ch) / pull-up (P-ch) for default-off
- [x] Optional snubber RC for inductive loads
- [x] Boundary ports: GATE, LOAD, GND, VDD (P-ch)

### 27. DAC output template (P1, MEDIUM) — DONE

- [x] IC database: MCP4725 (I2C, 12-bit), DAC8552 (SPI, 16-bit dual)
- [x] Auto-calc output RC filter from DAC update rate (fc = rate/10)
- [x] VREF decoupling for external-ref ICs
- [x] Boundary ports: VOUT, SDA/SCL or SPI, VDD, GND

### 28. Sensor front-end template (P1, LARGE) — DONE

- [x] IC database: INA128PA (instrumentation amp), AD8421BRZ
- [x] Auto-calc INA gain R: G = 1 + 50k/Rg (INA128) or G = 1 + 9.9k/Rg (AD8421)
- [x] Optional anti-alias output filter
- [x] Boundary ports: SENSOR_P, SENSOR_N, VOUT, VDD, GND

### 29. Relay/solenoid driver template (P1, SMALL) — DONE

- [x] IC database: ULN2003A (7-ch Darlington), DISCRETE_NPN (standalone BJT)
- [x] Auto-calc base resistor for discrete: R = (Vdrive - Vbe) / (Icoil / beta * overdrive)
- [x] ULN2003 has internal base R + flyback diodes
- [x] Boundary ports: VCOIL, DRIVE, LOAD, GND

### 30. Audio amplifier template (P1, MEDIUM) — DONE

- [x] IC database: PAM8302A (analog Class-D), MAX98357A (I2S Class-D)
- [x] Auto-calc input coupling cap: C = 1/(2*pi*f_low*R_in)
- [x] VDD bulk decoupling, shutdown pull-up
- [x] Boundary ports: AUDIO_IN/I2S, SPEAKER_P, SPEAKER_N, VDD, GND

### 31. Power mux / ideal diode template (P1, MEDIUM) — DONE

- [x] IC database: TPS2113 (auto-switching mux), LTC4357 (ideal diode OR)
- [x] Auto-calc ILIM resistors: R = 375k / Ilim
- [x] Input/output decoupling, D1/D2 dead-battery disconnect
- [x] Boundary ports: VIN1, VIN2, VOUT, GND

### 32. Charge pump template (P2, SMALL) — DONE

- [x] IC database: LM2776 (SOT-23-5, 1MHz), ICL7660 (SOIC-8, 10kHz)
- [x] Auto-calc flying cap and output cap: C = Iout / (fsw * V_ripple)
- [x] Input decoupling
- [x] Boundary ports: VIN, VOUT_NEG, GND

## Sprint 1 — Robust KiCad Import Pipeline (v0.2.0)

**Goal:** Make every KiCad-library-imported component generate a usable, non-broken schematic — no silent drops, no net collisions, no bare ICs missing decoupling.

### 1. Stop silently dropping components (P0, LARGE) — DONE

- [x] Create a stub `ComponentDef` with `category="unknown"` instead of returning `[]` — `_make_stub_component()` in `project_spec.py`
- [x] Add a warning annotation on the stub symbol ("UNRESOLVED — verify manually")
- [x] Stub created for: unknown template, template validation error, no type/ic, unknown IC
- [x] Validation detects stubs via "UNRESOLVED" annotation in `mvp.py:_validate_component_resolution()`

### 2. Auto-generate bypass caps for KiCad-imported ICs (P0, MEDIUM) — DONE

- [x] Verified `auto_generate_bypass_caps()` fires for KiCad imports (power_pins set, bypass_caps empty)
- [x] Fixed: power ICs (category=power, ref_prefix=U) bypass the 6-pin minimum threshold
- [x] Test: LM7805 (3 pins, power category) now gets decoupling caps
- [x] Test: built-in ICs with explicit caps are NOT double-capped
- [x] Test: connectors with power pins do NOT get auto-decoupling

### 3. Fix net name collisions on KiCad-imported signal pins (P0, LARGE) — DONE

- [x] `_apply_net_prefix()` in `project_spec.py`: prefixes generic pin names with ref designator
- [x] Generic set: G, S, D, IN, OUT, A, B, C, E, IN+, IN-, OUT+, OUT-, FB, EN, SW, BST, PG, SS, COMP, RT, SYNC, NC, ~
- [x] Global bus names preserved: SDA, SCL, MOSI, MISO, TX, RX, D+, D-, CAN_H/L, SWDIO, SWCLK, etc.
- [x] Short names (<=3 chars) also prefixed as safety net
- [x] Test: two BSS138s get separate gate nets (Q1_G, Q2_G)

### 4. Map KiCad power pin names to project rail names (P1, MEDIUM) — DONE

- [x] `_apply_power_map()` in `project_spec.py`: remaps raw KiCad power pin names
- [x] Optional `power_map` dict in YAML: `power_map: {V+: VDD_5V, V-: GND}`
- [x] Default mapping: VCC/VDD→VDD_3P3, VBUS→VBUS_5V, GND/VSS/AGND/DGND→GND, VIN→VIN
- [x] Unknown power names preserved as-is
- [x] Test: explicit map overrides, default map applies, unknown names pass through

### 5. Add "Miscellaneous" sheet for unclassified components (P1, SMALL) — DONE

- [x] Added `misc` sheet category in `allocator.py` with title "Miscellaneous / Discrete"
- [x] Routes: unknown, protection, discrete, analog, misc categories → misc sheet
- [x] Default fallback changed from "mcu" to "misc" in `classify_component()`
- [x] Expanded `_SECTION_CATEGORY_MAP`: analog, discrete, motor, protection, audio, display, misc
- [x] Test: unknown/protection/discrete → misc, mcu → mcu, unrecognized → misc

### 6. Wire passive inference into resolver (P1, MEDIUM) — DONE

- [x] `_resolve_component()` now tries `infer_passive_component(ref, value)` before creating stub
- [x] Supports: `{value: "10k", ref: "R1"}` and `{value: "100nF", ref: "C1"}` in any YAML section
- [x] Footprint auto-inferred: R/C→0402, L→0805
- [x] Test: bare resistor and capacitor resolve to valid ComponentDefs
- [x] Test: missing ref still creates stub (can't infer passive type without ref prefix)

### 7. Add spec-vs-output reconciliation validation (P0, MEDIUM) — DONE

- [x] `_validate_component_resolution()` in `mvp.py` detects stub components via "UNRESOLVED" annotation
- [x] Emits `unresolved-component` structural error with the stub's reason message
- [x] Test: unresolved component produces stub with UNRESOLVED annotation
- [x] Test: valid spec passes validation cleanly

Files: `mvp.py`, `validator.py`

---

## Sprint 2 — Template Expansion & DFM Quality (v0.3.0)

**Goal:** Expand template coverage for common circuit patterns, improve category classification, and make generated schematics closer to hand-drawn quality.

### 8. Add op-amp subcircuit template (P1, LARGE) — DONE

Op-amps are one of the most common analog building blocks and have no template. Users must specify them as bare `ic:` entries with no auto-generated feedback network, bias resistors, or decoupling.

- [ ] Create `subcircuits/opamp.py` with `OpAmpTemplate`
- [ ] Support configurations: inverting, non-inverting, voltage follower, differential
- [ ] Auto-generate feedback resistors from gain parameter
- [ ] Auto-generate input bias resistors where needed
- [ ] Auto-generate decoupling caps on supply pins
- [ ] Add to template registry in `subcircuits/base.py`
- [ ] Add tests for each configuration

Files: `subcircuits/opamp.py`, `subcircuits/base.py`

### 9. Add protection/ESD subcircuit template (P1, MEDIUM) — DONE

- [x] Created `subcircuits/protection.py` with `ProtectionTemplate`
- [x] TVS database: SMBJ5.0A, SMBJ12A (unidirectional), SMBJ5.0CA, PESD5V0S1BA (bidirectional)
- [x] Registered in default registry

### 10. Add gate driver / level shifter template (P2, MEDIUM) — DONE

- [x] Created `subcircuits/driver.py` with `GateDriverTemplate` and `LevelShifterTemplate`
- [x] Gate drivers: IR2110 (half-bridge with bootstrap), UCC27524 (dual low-side)
- [x] Level shifters: TXB0108 (8ch), TXS0102 (2ch) with OE pull-up
- [x] Bootstrap cap auto-generated for high-side drivers
- [x] Registered in default registry

### 11. Improve KiCad import category classification (P1, MEDIUM) — DONE

- [x] Added `_LIB_CATEGORY_MAP`: 30+ library prefix → category mappings
- [x] `_infer_category_from_lib()` uses library name as highest-priority classifier
- [x] `get_component()` passes resolved library name through to `symbol_to_component_def()`
- [x] Expanded description keyword matching: op-amp, MOSFET, TVS, driver, sensor, etc.
- [x] Uses `Description` property (not just Datasheet URL) for keyword matching

### 12. Add external component database support (P2, LARGE) — DONE

- [x] `ComponentRegistry.load_json(path)` loads components from JSON file
- [x] `ComponentRegistry.load_json_dir(directory)` loads all *.json files from a directory
- [x] Full schema support: pins, pin_nets, power_pins, bypass_caps, straps
- [x] YAML spec `components_db` key auto-loads project-local JSON database
- [x] Verified: JSON-defined components resolve with full metadata

### 13. Improve motif renderer coverage (P2, MEDIUM) — DEFERRED

Deferred to Sprint 3. Existing sidecar/bank/ladder renderers handle most cases adequately after Sprint 1 defaults change.

### 14. Add footprint fallback heuristics for KiCad imports (P1, SMALL) — DONE

- [x] `_infer_footprint()` in `kicad_lib.py`: infers from pin count + name hints
- [x] Heuristics: 3-pin+SOT/Q→SOT-23, 5-pin+SOT-23→SOT-23-5, 8-pin+SOIC→SOIC-8, 2-pin+D→SOD-123, R/C/L→0402
- [x] Falls back to empty string for truly unknown packages
- [x] Uses KiCad `Description` property for better context

### 15. Add section-category extensibility (P2, SMALL) — DONE (Sprint 1)

Completed during Sprint 1 Task 5. `_SECTION_CATEGORY_MAP` expanded with analog, discrete, motor, protection, audio, display, misc, rf_frontend, power_distribution.

---

## Sprint 3 — Placement, Routing & Presentation Readiness (v0.4.0)

**Goal:** Close the gap between auto-generated and hand-drawn quality with aesthetics scoring, motif refinement, and routing improvements.

### 16. Schematic aesthetics scorer (P0, LARGE) — DONE

- [x] `scorer.py` module with `score_layout()` and `score_project()`
- [x] 6 metrics: spacing uniformity (CV), whitespace ratio, label overlap potential, wire crossing estimate, aspect ratio, component density
- [x] Weighted aggregate score 0-100 with A-F grade
- [x] Wired into `generate_from_components()` via `score=True` parameter
- [x] CLI flag: `--score` on the `generate` subcommand
- [x] Piped through `generate_artifacts()` and `_generate_compiled_artifacts()`

### 17. Compact LDO cluster motif (P1, MEDIUM) — DONE

- [x] `_apply_topology_ldo_cluster()` in `placer.py`
- [x] Detects power-category IC with exactly 2 decoupling caps (CIN + COUT)
- [x] Places CIN left-of-center, COUT right-of-center in a row below IC
- [x] Shared rail labels and ground anchor
- [x] Optional enable strap placed inline

### 18. USB-C CC network block (P1, SMALL) — DONE

- [x] `_apply_topology_cc_network()` in `placer.py`
- [x] Detects connector with 2 termination straps pulling to same GND with same value
- [x] Places both resistors vertically beside connector with shared GND label
- [x] Dispatch chain updated: buck -> LDO cluster -> CC network -> bank -> ladder -> sidecar

### 19. Single-passive inline placement (P1, SMALL) — DONE

- [x] Sidecar cluster now handles single-passive pin groups with inline placement (8.89mm offset)
- [x] Multi-passive groups (2+) still use the full grid layout (12.70mm offset)
- [x] Tighter inline placement reduces visual noise for solo bypass caps

### 20. Wire crossing minimization (P2, MEDIUM) — DEFERRED

Deferred to Sprint 4. Current crossing count is low with topology-local rendering.

### 21. Bus routing for parallel signals (P2, MEDIUM) — DEFERRED

Deferred to Sprint 4. Current label-based bus connections work adequately.

### 22. Sample gallery refresh (P1, SMALL) — DEFERRED

Deferred until KiCad CLI SVG export is integrated into CI.

---

## Sprint 12 — Platform Integrity: Guided CLI Workflow (v0.10.1)

**Goal:** Circuit Weaver is an LLM-first tool — Claude Code, Codex, and OpenCode ARE the interface. The Python engine is the backend. Graduate from manually-triggered skills to a seamless guided workflow with reliable orchestration and comprehensive logging.

### 74. Clean up demo artifacts (P0, XS) — DONE

- [x] Remove demo_live/ directory (35 files: HTML, GIFs, demo scripts) via git rm
- [x] Remove demo_realistic.gif via git rm
- [x] Update .gitignore: added *.gif (*.mp4 already present)
- [x] Update README.md: replaced GIF demo section with CLI demo commands
- [x] Verify no remaining git-tracked demo files (only DEMO_COMMANDS.md remains as reference)

Files: `.gitignore`, `git rm`

### 72. cost-bom CLI subcommand (P1, MEDIUM) — DONE

- [x] Extend parts_lookup.py: parse extra.prices array into price_tiers (already done)
- [x] Add get_unit_price(price_tiers, qty) helper (already done)
- [x] Add lookup_by_lcsc(lcsc_pn) to PartsLookup
- [x] Create cost_bom.py: cost_bom(spec, qty_breaks) → structured costed BOM (already done)
- [x] Add cost-bom subcommand to mvp.py with --qty flag (already done)
- [x] _print_cost_bom_table() for formatted output (already done)
- [x] Tests: price tier selection, math validation, network test on iot_sensor_node sample

Files: `parts_lookup.py`, `cost_bom.py`, `mvp.py`, `tests/test_cost_bom.py`

### 70. Rewrite design_wizard/SKILL.md (P0, MEDIUM) — DONE

- [x] Fix upsert vs upsert_blocks patch key names (verified correct)
- [x] Remove analyze_schematic.py references (none found)
- [x] Replace Freerouting mention with manual KiCad routing guidance (positioned as optional)
- [x] Update Step 3 with real scaffold + apply-patch commands (already correct)
- [x] Add "Output Formatting Rules" section at top
- [x] Update command syntax table with exact CLI invocations (added output formatting rules)
- [x] Remove references to unimplemented skills (updated PCB workflow section)

Files: `skills/design_wizard/SKILL.md`

### 76. Freerouting PCB autorouting integration (P1, MEDIUM) — DONE

- [x] Create autoroute.py: autoroute_pcb(pcb_path, output_path) (already exists)
- [x] Check for Freerouting JAR installation, graceful failure with instructions
- [x] Add autoroute subcommand to mvp.py (already exists)
- [x] Tests: mock Freerouting subprocess, graceful failure when missing, trace/via extraction (created with 13 test cases covering all scenarios)

Files: `autoroute.py`, `mvp.py`, `tests/test_autoroute.py`

### 73. Fix docs/user_workflow.md (P1, SMALL) — DONE

- [x] Remove false promises: DigiKey/Mouser/LCSC stock checks, estimated costs
- [x] Add scaffold + apply-patch workflow
- [x] Add cost-bom command
- [x] Add autoroute command (with note: optional, user installs JAR)
- [x] Remove unimplemented related skills rows (none were present)
- [x] Update files table: add jlcpcb CSV files, remove non-existent files (already correct)

Files: `docs/user_workflow.md`

### 75. CLI demo capture (P2, SMALL) — DONE

- [x] Create docs/DEMO_COMMANDS.md: git-tracked script with command sequence (9 command groups)
- [x] Commands: list-templates, scaffold, apply-patch, validate, generate, cost-bom, export-jlcpcb, autoroute
- [x] Document asciinema recording (optional tool, not a dependency)
- [x] Update README: README already pointed to DEMO_COMMANDS.md
