# Tasks

> Work only on what's listed here. Check boxes as completed, update CHANGELOG.md alongside.

## Sprint 50 — Generic Builder Parity Cleanup (v0.30.5)

**Goal:** Close the remaining Sprint 49 data-driven generic-builder failures so the sample/corpus release gate can return to zero known hard failures.

### T215. Port sensor_frontend dual-rail power handling (P1, MEDIUM)

- [ ] Reproduce the INA128PA `sensor_frontend` failures from the current full-suite catalog.
- [ ] Add regression coverage for dual-rail instrumentation amplifier power pins (`V_POS`, `V_NEG`) with no floating power pins.
- [ ] Update the data-driven path with the smallest correct builder/generic mapping fix.
- [ ] Run focused tests and update the failure catalog.

Files: `src/circuit_weaver/subcircuits/topology_builders.py`, `tests/test_template_structure.py`, sample/corpus tests

### T216. Port shared I2C/SPI boundary nets for generic sensors (P1, MEDIUM)

- [ ] Reproduce the `iot_sensor_node`, `oled_display_module`, and bootstrap example boundary-port mismatches.
- [ ] Add regressions for shared SDA/SCL/SPI nets and pull-up boundary naming.
- [ ] Preserve custom net names rather than defaulting to `{PIN}_{REF}` for shared bus pins.
- [ ] Run focused sample/presentation tests and update the failure catalog.

Files: `src/circuit_weaver/subcircuits/topology_builders.py`, `tests/test_presentation.py`, corpus tests

### T217. Port battery charger and fuel-gauge signal net contracts (P1, MEDIUM)

- [ ] Reproduce the `wearable_bms` and `battery_iot_sensor` failures.
- [ ] Add regressions for PROG/CTG/CELL/SDA/SCL signal naming and required boundary ports.
- [ ] Update data-driven builders/generic mappings without reintroducing legacy template classes.
- [ ] Run focused corpus and presentation checks.

Files: `src/circuit_weaver/subcircuits/topology_builders.py`, `tests/test_generation_corpus.py`, `tests/test_presentation.py`

### T218. Close sample/corpus release gate (P1, MEDIUM)

- [ ] Run the full suite and 9-archetype corpus after T215–T217.
- [ ] Drive remaining pre-existing T180 failures to zero, or catalog any deliberately deferred failures with root cause and next task.
- [ ] Run the `I:/my_circuit` validate/generate probe.
- [ ] Update `TASKS.md` and `CHANGELOG.md` with final Sprint 50 results.

Files: `tests/`, `samples/`, `TASKS.md`, `CHANGELOG.md`

---
