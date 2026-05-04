# Tasks

> Work only on what's listed here. Check boxes as completed, update CHANGELOG.md alongside.

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
