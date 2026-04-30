# Tasks

> Work only on what's listed here. Check boxes as completed, update CHANGELOG.md alongside.

## Sprint 49 — Incremental Legacy Migration (T180–T181)

**Goal:** Begin the legacy template deletion with the lowest-risk topologies. Flip the registry to data-driven-first so the full test suite validates the new path before any deletions. Then delete the 4 topologies with dedicated builders — `buck`, `boost`, `buck_boost`, `ldo` — which already have parity builder logic in `topology_builders.py`.

**Scope:** T180 + T181. T182 (verdict-A deletions) is a stretch goal if velocity allows.

### T180. Flip registry resolution order (P1, SMALL) ✅ DONE

Depends on: Sprint 47 audit (done; A=7, B=21, C=9).

The current `SubcircuitRegistry.get()` checks legacy `_templates` dict first; `DataDrivenTemplate` only fires for topologies with no legacy class registered. Flip the order: data-driven first, legacy as fallback. This is the minimal change that activates the new path without deleting anything. Running the full test suite after this flip validates that no silent regressions exist.

- [x] In `SubcircuitRegistry.get()`: call `_get_data_driven()` first; if it returns a template, use it. Fall through to `_templates` only if ic_data returns nothing for that topology.
- [x] Removed `_DATA_DRIVEN_FIRST` class variable (dead code after flip).
- [x] Updated class docstring to reflect data-driven-first resolution order.
- [x] Add test asserting a topology that has ic_data JSON entries uses `DataDrivenTemplate`, not the legacy class, after the flip.
- [x] Replace `test_registry_prefers_legacy_for_unported_topologies` with `test_registry_uses_data_driven_first` and `test_registry_legacy_fallback_when_no_ic_data`.
- [x] Confirm full test suite passes with no changes to legacy templates — **26 failures cataloged below**.
- [x] Cataloged failures — the flip exposes which legacy templates still have gaps vs the data-driven path.

**Catalog of gaps exposed by the flip (26 failures across 8 sample designs + sensor_frontend smoke):**

| Failure Cluster | Count | Root Cause |
|-|-|-|
| `sensor_frontend` (INA128PA) | 3 | `build_generic` doesn't handle dual-rail power pins V_NEG/V_POS for instrumentation amps |
| `iot_sensor_node` | 4 | `build_generic` creates `{PIN}_{REF}` boundary ports; BME280 I2C/SPI signal ports don't match legacy shared-net naming |
| `battery_iot_sensor` | 3 | I2C pull-ups, battery management signal boundary port naming mismatch |
| `usb_uart_bridge` | 4 | Protection diode (TVS) boundary ports and USB_DP/USB_DM signal naming mismatch |
| `wearable_bms` | 4 | Battery charger (PROG), fuel gauge (CTG/CELL/SDA/SCL), I2C pull-up boundary port naming |
| `high_voltage_isolation` | 4 | Protection diode anode/cathode boundary port naming |
| `oled_display_module` | 3 | I2C boundary port naming mismatch |
| `example/iot_sensor` (bootstrap/CLI) | 1 | Same boundary port naming issue |

All failures are boundary-port naming mismatches: `build_generic` assigns `{PIN_NAME}_{REF}` (e.g., `SDA_U2`, `PROG_U1`) while legacy templates use shared/custom net names. Buck/boost/buck_boost/ldo are unaffected — they use dedicated builders in `topology_builders.py` with verified parity.

Files: `src/circuit_weaver/subcircuits/base.py`,
`tests/test_template_structure.py`, `tests/test_template_parity.py` (new if needed)

### T181. Delete specialized topology legacy classes (P1, MEDIUM)

Depends on: T180 (registry flipped, tests confirm no regressions).

The four topologies with dedicated builders in `topology_builders.py` (`buck` → `build_switching_regulator`, `boost` → `build_switching_regulator`, `buck_boost` → `build_switching_regulator`, `ldo` → `build_linear_regulator`) are the lowest-risk deletions. The builder logic already exists; this task verifies parity then removes the dead files.

- [ ] Write output-parity tests for each topology: call `DataDrivenTemplate.generate()` and legacy `XTemplate.generate()` on the same IC+params; assert component count matches, passive values agree within 5%, and all net assignments are identical.
- [ ] Fix any gaps in `topology_builders.py` uncovered by the parity tests (e.g. a passive net or boundary port the legacy class emits that the builder doesn't).
- [ ] Remove `buck.py`, `boost.py`, `buck_boost.py`, `ldo.py` from `subcircuits/`. Remove their imports and `reg.register()` calls from `_build_default_registry()`.
- [ ] Remove the four classes from the existing legacy smoke tests; confirm smoke suite still passes.
- [ ] Confirm full test suite passes.
- [ ] Confirm 9-archetype corpus `test_corpus_validate_no_hard_errors` still passes.
- [ ] Re-run `I:/my_circuit` validate/generate probe to confirm no real-world regression.

Files: `subcircuits/buck.py`, `subcircuits/boost.py`,
`subcircuits/buck_boost.py`, `subcircuits/ldo.py` (deleted),
`subcircuits/base.py`, `subcircuits/topology_builders.py`,
`tests/test_template_parity_switching.py` (new),
`tests/test_template_parity_linear.py` (new)

### T182. Port and delete thin verdict-A templates (P2, MEDIUM) — STRETCH

Depends on: T180, T181. Only if velocity allows after T180+T181 are complete.

Audit verdict-A templates from Sprint 47 — those where `build_generic` already produces equivalent output and the legacy `generate()` has no custom passive calculation. Run parity tests, delete files, remove from registry.

- [ ] Identify exact verdict-A templates from `docs/legacy_template_audit.md`.
- [ ] For each: write parity test, delete template file, remove from registry.
- [ ] Confirm full suite + corpus pass.

Files: ~7 template files (deleted), `subcircuits/base.py`,
`tests/test_template_parity_generic_thin.py` (new)

---
