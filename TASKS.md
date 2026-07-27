# Tasks

> Work only on what's listed here. Check boxes as completed, update CHANGELOG.md alongside.

## Roadmap Principles (2026-07-25)

The v0.32 release substantially improved artifact integrity, resumability, import analysis, placement review, and manufacturing-delivery safety. The next roadmap is deliberately narrower than the current command surface: first make every product claim measurable, then deepen electrical accuracy, then close the loop from schematic to a real PCB and from imported findings to safe repairs.

> **Planner layer:** Sprints 55–60 below are grouped into six outcome epics (A–F) with dependency ordering, frozen cross-epic schemas, sub-task breakdowns, and exit gates in [`EPICS.md`](./EPICS.md). Read that first for the *why/what-order*; this file is the executable task list. Legacy audit findings F11/F17/F18/F19 are absorbed into Epics B (T245.4) and C (T249.1–.3).

Every sprint below must preserve these cross-cutting rules:

- **Truth before convenience:** unverified, estimated, heuristic, review-only, and fabrication-ready states remain distinct in CLI, API, MCP, reports, and manifests.
- **Evidence before confidence:** a score or recommendation must link to the rule, calculation, source, or tool result that produced it. Missing evidence reduces confidence; it never silently receives credit.
- **Fail closed at irreversible boundaries:** unresolved pinouts, ambiguous footprints, failed ERC/DRC, stale prices, and incomplete routing cannot become order-ready outputs.
- **One behavior across surfaces:** CLI, Python, HTTP, MCP, and agent skills consume the same service-layer contracts and return the same status vocabulary.
- **Benchmarks over anecdotes:** each accuracy feature lands with a positive/negative corpus, measured false-positive and false-negative behavior, and a checked-in regression fixture.

### Roadmap success measures

| Pillar | Measure | Target by Sprint 60 |
|---|---|---|
| Product truth | Advertised workflows with an explicit maturity/verification state | 100% |
| Regression health | Required source and built-wheel suites | 100% green; no unexplained skips |
| Electrical accuracy | Curated benchmark findings with traceable evidence | >=95% precision and >=90% recall |
| Component trust | Routed critical parts with verified pinout + footprint evidence | 100% |
| PCB handoff | Golden designs producing a pad-bearing board that loads and passes configured KiCad DRC | 100% |
| Repair safety | Applied repairs that are transactional, idempotent, and auditable | 100% |
| Confidence honesty | Score contribution backed by completed evidence | 100% |

---

## Sprint 55 — Release Truth, Regression Recovery, and Product Benchmarks (v0.32.1) — ✅ DONE

**Goal:** Restore a trustworthy green baseline and make product maturity measurable before adding more surface area. This is the immediate sprint.

### T241. Restore the source-tree and installed-wheel release gates (P0, HIGH) ✅ DONE

- [x] Fix the current source-selected baseline (`1431 passed, 16 skipped, 7 failed, 6 errors` on Windows/Python 3.13): the three sample `svg-left-overflow` regressions, their layout-quality fixture errors, and the generation-call determinism regression. Long centered root-sheet titles now reserve their estimated left half-width; the determinism test is isolated from presentation validation without weakening production gates.
- [x] Make a plain developer `python -m pytest` test the checkout instead of accidentally collecting/importing an already-installed `circuit_weaver`; add a regression or documented runner that proves import origin and version. Source and wheel modes now verify the resolved package path/version and propagate the selected interpreter/package to subprocesses.
- [x] Run the same required gates against the source tree and the exact built wheel on Linux and Windows, with subprocess tests inheriting the intended package under test. Local Windows/Python 3.13 is green for both (`1766 passed, 16 classified skips` each against the `0.33.0` candidate); hosted PR CI run `30286803276` passed all 19 jobs, including the source and exact-wheel matrices on Linux/Python 3.10–3.14 and Windows/Python 3.12/3.13 plus real KiCad 8/9/10 final-artifact validation.
- [x] Classify every skip as platform-required, optional-tool-required, network, or defect; fail CI on unknown/unclassified skips. Missing checked-in fixtures now fail instead of skipping, and runtime as well as collection/setup skips are enforced.
- [x] Record the local source/wheel counts and exact commands in `CHANGELOG.md`; update CI/release workflows to select source or exact-wheel mode explicitly. Hosted matrix counts remain part of the preceding exit item.

### T242. Publish a machine-readable capability and maturity registry (P1, MEDIUM) ✅ DONE

- [x] Inventory every CLI command and corresponding Python/HTTP/MCP/skill path; assign one state: `supported`, `beta`, `experimental`, `review_only`, or `deprecated`. The registry covers all 44 top-level commands plus both `cache` child operations and advertises Python surfaces only when a real public function exists.
- [x] Define verification prerequisites and output guarantees on the ordered design ladder, with a paired non-ordered `not_applicable` state for operational commands that make no design claim. Variable/tool-dependent commands publish conservative default guarantees and may claim more only with matching returned evidence.
- [x] Generate the README capability table from the registry and surface the same copy-safe JSON through `doctor --json`, terminal doctor summaries, the public Python accessor, and HTTP `GET /capabilities`; CI rejects generated-doc drift.
- [x] Add contract tests that reject missing CLI registrations, malformed schemas/vocabularies, mixed `not_applicable` states, and runtime claims stronger than their returned evidence supports.

### T243. Establish a versioned electrical-accuracy benchmark corpus (P1, HIGH) ✅ DONE

- [x] Add small, reviewable positive and negative fixtures for power, clocks, USB, I2C/SPI/UART, analog, protection, and manufacturing checks; every oracle uses the frozen `CW-<DOMAIN>-<NNN>` namespace and includes a rationale.
- [x] Separate generator-owned positive fixtures from independently-authored negative reference fixtures with explicit source type, reference, and license provenance.
- [x] Add a real-validation benchmark runner that reports precision, recall, false positives, false negatives, unsupported cases, and runtime by rule/domain without turning unsupported scope into false negatives.
- [x] Store a versioned baseline artifact and gate per-rule/per-domain precision and recall rather than aggregate pass counts. The first supported rule now uses the canonical `CW-PWR-*` namespace and is gated at 1.0 precision/recall; the remaining eight domain cases stay explicitly unsupported until their normalized validators land.

### T244. Emit an evidence manifest for generated and analyzed designs (P1, HIGH) ✅ DONE

- [x] Add versioned `evidence_manifest.json` with timestamp-independent stable IDs and frozen subjects for component identity, pinout, footprint, power parameters, calculations, validator findings, tool versions, and verification results. Producers record only evidence they actually possess.
- [x] Carry evidence IDs through validation JSON, generated design and review reports, confidence reports, assembly/delivery manifests, legacy and MVP HTTP validation, generated HTTP archives, and MCP validation/generation responses.
- [x] Preserve source URI/document identity, retrieval time, content hash when available, extraction method, confidence, freshness, and conflicts while rejecting credentials, machine-local absolute paths, unsafe manifest references, and unresolved links.
- [x] Fail closed on fabrication-ready delivery claims backed only by missing, stub, unacknowledged heuristic, insufficient-confidence, or conflicting evidence. Existing JLC export remains explicitly non-fabrication-ready unless a future board-verification path supplies trusted critical evidence.

**Sprint exit:** all mandatory source/wheel gates are green; every public workflow has a maturity state; the benchmark and evidence schemas are versioned and consumed by at least validation and reporting.

> **T244 REMEDIATION (reopened — planner code-review, 2026-07-27).** Suite is green and the ID scheme / fail-closed gate / manifest determinism verified correct, but three defects must close before T244 is truly done:
> - [x] **T244.R1 (HIGH — data leak).** Redaction is now recursive and unanchored for embedded Windows drive, UNC, POSIX/home, and `file://` paths; direct record validation and ledger admission share one detector. The real `collect_component_evidence` absolute-`.kicad_mod` path is rejected before manifest emission. HTTP(S) userinfo and local paths hidden in URL queries are rejected without blocking ordinary remote URLs or slash notation.
> - [x] **T244.R2 (MEDIUM — frozen-contract fork).** `EvidenceRecord.supersedes` now flows through builder, copy, manifest, and legacy-compatible rehydration; IDs remain independent of supersession metadata. Programmatic links must already resolve, forward manifest links load deterministically, cycles/unresolved links fail, corroborated records round-trip regardless of ID sort order, and superseded records cannot remain fabrication-authoritative.
> - [x] **T244.R3 (cleanup).** Consolidated emitted rule IDs on `CW-PWR-*`; legacy `CW-POWER-*` values are accepted only at the benchmark input boundary and canonicalized before scoring or result emission. A repository contract test prevents the old namespace from returning outside that explicit alias map.
>
> **Remediation verification:** R1/R2 source suite `1601 passed, 16 classified skips`; focused exact-wheel evidence safety/schema suite `60 passed`. R3 focused namespace/benchmark suite `48 passed`, Ruff clean, and the benchmark baseline gate remains green at 1.0 precision/recall for supported power rules.

---

## Sprint 56 — Evidence-Backed Electrical Accuracy (v0.33.0) — ✅ DONE

**Goal:** Move from structurally valid circuits to recommendations and generated support networks that are traceable to component limits, equations, and cross-checked identity data.

### T245. Model typed power domains and operating envelopes end to end (P1, HIGH) ✅ DONE

- [x] Extend the normalized schema with optional rail min/nominal/max voltage, source/load/bidirectional direction, peak and steady current, sequencing constraints, tolerance, and provenance. `PowerDomain`, `PowerReq`, and `PowerPin` reject invalid ranges/directions while retaining positional compatibility for legacy nominal-voltage and peak-current declarations.
- [x] Propagate those fields through canonical/legacy ingest, component registries and resolver caches, templates, `DesignIR`, generational repair, validation, power-tree/design-document reporting, HTML review, and `placement_review_context.json`. Omission-preserving serialization keeps unknown values absent rather than converting them to zero or inferred limits.
- [x] Detect over-voltage, under-voltage, reverse-flow, source contention, regulator dropout/headroom, steady/peak current-budget, and sequencing violations as `CW-PWR-001` through `CW-PWR-007`. Findings carry sparse unit-labelled inputs, observed/expected values, margins, remediations, and resolvable calculation/parameter/rail evidence; unresolved provenance tokens are removed rather than published as dangling evidence IDs.
- [x] Expand the electrical corpus from 18 to 27 fixtures with valid multi-rail and battery margins plus a detected adverse case for every `CW-PWR-*` rule. All seven rules baseline at 1.0 precision/recall with zero false positives/negatives; source suite is `1551 passed, 16 classified skips`, and the focused exact-wheel T245/evidence/report suite is `72 passed`.

### T246. Make support-passive synthesis equation- and datasheet-driven (P1, HIGH) ✅ DONE

> **Planner spec:** see `EPICS.md` T246.1–.6 + the frozen **`CalculationRecord`** contract box. Land the shared `src/circuit_weaver/calc.py` equation module **first** (T246.1) — validators refactor to consume it so synth/validate/benchmark share one formula. Precedence is fail-closed `datasheet → equation → bounded fallback`; a value with none of those is **withheld** (`CW-PSV-*`), never a bare `100nF`. Retires the per-MPN `_FEEDBACK_VREF` table.

> **Execution status (2026-07-27): T246.1 ✅ DONE.** Added the immutable, unit-explicit `CalculationRecord` substrate and deterministic `CALC-*` IDs in `calc.py`; feedback-divider, RC/LC-cutoff, inverse RC sizing, and crystal-load synthesis/validation now delegate to that module. The crystal equation drift was corrected to `Cext = 2*(CL - Cstray)`, and both legacy `calc:CW-*` acts and `calc:<equation_id>@<REF>` acts resolve through the evidence grammar. Source suite: `1574 passed, 16 classified skips`; focused exact-wheel contract/delegation suite: `36 passed`.

> **Execution status (2026-07-27): T246.2 ✅ DONE.** A separate deterministic adapter now emits each `CalculationRecord` as idempotent `kind=calculation` evidence against its frozen `param:<REF>.<domain>.<field>` target, requires all cited input evidence to resolve, and returns a new record with `emits_evidence` populated without mutating the pure equation result. Integrated focused schema/calculation suite: `51 passed` across T246/T247/R3 contracts.

> **Execution status (2026-07-27): T246.3–.6 ✅ DONE.** Normalized recommendations enforce datasheet → equation → bounded-fallback precedence and provenance; feedback Vref moved off the MPN table; E6/E12/E24/E96 selection, ratio-preserving divider-pair snapping, safe-up capacitor selection, and deterministic `CW-PSV-001…003` withholding are implemented. Auto-bypass plus switching/LDO, crystal, USB-C, CAN/RS-485, reset/display, and analog-filter producers retain calculation evidence and reject invalid selections before emission. The 10-case independent passive oracle is producer-verified, all three `CW-PSV-*` rules score 1.0 precision/recall, and representative synthesized designs self-validate. Full source suite: `1766 passed, 16 classified skips`.

- [x] Replace remaining universal defaults for regulators, crystals, reset/enable straps, interface termination, and protection networks with normalized recommendation records plus bounded fallback policies.
- [x] Emit a calculation record for every synthesized value: inputs, units, equation/rule version, chosen standard value, tolerance, margin, and source evidence.
- [x] Reject incompatible or out-of-range synthesized networks instead of warning after emission.
- [x] Verify representative buck/boost/LDO, crystal, USB, CAN/RS-485, and analog front-end designs against independently reviewed expected values.

### T247. Cross-check part identity, pinout, symbol, and footprint before routing (P0, HIGH) ✅ DONE

> ⚠️ **P0 — can't ship late.** Only P0 in Sprint 56; it's the identity guard Epic C's PCB handoff (T249/T251) calls before emitting pads, and it closes legacy F17/F18/F19's failure class. Must land **within** this sprint even if T246/T248 compress — do not let it roll into Sprint 57.

> **Execution status (2026-07-27): T247.1 ✅ DONE.** Added an immutable, deterministic identity record for exact manufacturer/MPN/package, symbol pins, footprint pads, one-to-one pin→pad joins, distributor aliases, and evidence IDs. Unknown identity remains explicitly unresolved, ambiguous mappings fail closed, and real-world manufacturer/package/distributor text is preserved exactly. Focused identity suite: `9 passed`.

> **Execution status (2026-07-27): T247.2–.4 ✅ DONE.** Exact independent-source reconciliation now preserves `agree|conflict|missing|human-approved`; approvals target a specific identity. The physical JLC CPL boundary calls the fail-closed handoff guard and requires complete pin→pad coverage plus exact footprint identity for every primary component. Nine adversarial/control fixtures execute the native guard; `CW-ID-001…004` each score 1.0 precision/recall with zero unsupported cases. Focused identity/JLC suite: `49 passed`; benchmark/baseline contracts: `42 passed`.

- [x] Build a shared identity record joining manufacturer, exact MPN/package suffix, symbol pins, footprint pad numbers, and distributor aliases.
- [x] Compare at least two independent sources when available; represent agreement, conflict, missing coverage, and explicit human approval as distinct states.
- [x] Block routing/manufacturing when an exact package cannot be proven compatible with the selected footprint or when symbol-pin-to-pad mapping is ambiguous.
- [x] Add adversarial fixtures for look-alike MPNs, package suffix changes, exposed pads, duplicated pin names, swapped differential pairs, and distributor stubs.

### T248. Calibrate validator severity and remediation quality (P1, MEDIUM) ✅ DONE

> **Planner spec:** see `EPICS.md` T248.1–.4. Core fix: `ValidationIssue.level` (validator.py:39) conflates *confidence* and *severity* — split into `detection_confidence` (frozen evidence ladder) + `severity` (`blocker|major|minor|info`), keep `level` as a derived compat property. Land that schema split **first**. A `blocker` may render as a hard defect only if `detection_confidence ∈ {verified, corroborated}`. Suppressions expire and stay in the scorecard denominators. This is the **last task in the sprint** — it certifies the Epic B ≥95%/≥90% gate, so it finalizes *after* T246/T247.

> **Execution status (2026-07-27): T248.1–.4 ✅ DONE.** `ValidationIssue` now separates severity from detection confidence while retaining derived `level`; every validator finding carries a canonical rule ID, unit-labelled observation, expected constraint, resolvable evidence, and safest action. Versioned narrow/expiring suppressions are validated and mark rather than remove findings. The published 40-fixture scorecard inventories exactly 33 emitted/contract rule IDs: 14 scored and 19 explicitly unsupported; supported aggregate precision and recall are both `1.000`, above the `0.95/0.90` gate. The release workflow runs the benchmark baseline. Full source and exact installed-wheel suites: `1766 passed, 16 classified skips` each; the `0.33.0` distributions pass `twine check`, and Ruff, benchmark baseline, and diff checks pass.

- [x] Run every validation rule through the Sprint 55 benchmark and publish per-rule precision/recall plus unsupported scope.
- [x] Split detection confidence from issue severity; a severe but weakly evidenced suspicion must not masquerade as a confirmed defect.
- [x] Require each actionable finding to name the violated constraint, observed value, expected range, evidence, and safest next action.
- [x] Add explicit suppressions/approved overrides with owner, reason, scope, and expiry; stale or overly broad suppressions fail the release gate.

**Sprint exit:** critical generated circuits have traceable operating envelopes, calculated support values, and verified pin-to-pad identity; benchmark targets reach >=95% precision and >=90% recall for supported rules.

---

## Sprint 57 — Real PCB Handoff and Constraint Closure (v0.34.0) — PLANNED

**Goal:** Convert an approved placement review into a real, pad-bearing KiCad PCB with authoritative connectivity and verification, while preserving the review-only placement-preview contract.

### T249. Create an authoritative schematic-to-PCB handoff (P0, HIGH)

- [ ] Generate or update a real `.kicad_pcb` using resolved library footprints, pad numbers, net assignments, board outline, stack-up, and the approved placement state; never relabel the existing preview as authoritative.
- [ ] Preserve stable references and UUID identity across regenerate/apply cycles, and produce a semantic change manifest for added, removed, moved, or remapped items.
- [ ] Refuse handoff for placeholder geometry, unresolved footprints, pin/pad mismatches, stale placement approval, or missing board constraints.
- [ ] Prove round-trip loadability in supported KiCad 8/9/10 gates with golden two-layer and four-layer designs.

### T250. Compile electrical intent into enforceable PCB constraints (P1, HIGH)

- [ ] Translate normalized interfaces and power domains into net classes, differential pairs, width/clearance/via rules, impedance targets, length constraints, keepouts, and placement constraints.
- [ ] Record which constraints are calculated, user-specified, manufacturer-specified, or fabrication-profile-derived and flag conflicts before board mutation.
- [ ] Cover USB 2.0, crystal loops, switch-mode power loops, I2C, CAN/RS-485, analog sense, and high-current rails in the benchmark corpus.
- [ ] Verify that emitted KiCad project/board rules match the evidence manifest and survive reopen/export.

### T251. Add transactional DRC and connectivity closure (P0, HIGH)

- [ ] Run KiCad connectivity checks and DRC on the exact staged board bytes; parse violations into the shared findings schema with stable rule IDs and object references.
- [ ] Require zero unapproved connectivity errors and zero fabrication-profile blockers before publishing an authoritative board.
- [ ] Preserve the last known-good board and reports when apply, save, reload, DRC, or manifest reconciliation fails.
- [ ] Add deterministic rerun and failure-injection tests for interrupted writes, stale board state, KiCad absence, version differences, and DRC parser drift.

### T252. Define a single manufacturing-readiness contract (P1, MEDIUM)

- [ ] Replace scattered readiness booleans with one state machine spanning identity, placement, routing, ERC, DRC, BOM/CPL reconciliation, Gerber/drill validation, and approved overrides.
- [ ] Make CLI, API, MCP, HTML reports, and artifact manifests return the same state, blockers, evidence IDs, and next safe actions.
- [ ] Add a `manufacturing-readiness --json` command and prevent export/publish paths from bypassing its blockers.
- [ ] Gate two golden designs through schematic generation -> reviewed placement -> real PCB -> DRC -> verified BOM/CPL/Gerbers.

**Sprint exit:** at least two representative designs complete a transactional, evidence-linked KiCad PCB handoff and pass the configured KiCad DRC/manufacturing-readiness gate.

---

## Sprint 58 — Imported-Design Review and Safe Repair Loop (v0.35.0) — PLANNED

**Goal:** Turn import analysis from a report-only feature into a high-value, human-reviewable remediation workflow without making uncontrolled edits to customer designs.

### T253. Unify findings across generated and imported artifacts (P1, MEDIUM)

- [ ] Normalize schematic, PCB, Gerber, ERC, DRC, DFM, sourcing, and evidence conflicts into one versioned finding model.
- [ ] Include stable rule/finding IDs, severity, detection confidence, exact object/location, evidence, remediation options, and verification status.
- [ ] Deduplicate the same root cause across analyzers while retaining every supporting observation.
- [ ] Add SARIF and JSON export for CI/code-review integration without weakening the native HTML report.

### T254. Generate bounded, transactional repair plans (P0, HIGH)

- [ ] Convert supported findings into explicit operations with prerequisites, affected objects/nets, expected postconditions, risk, and rollback data.
- [ ] Separate `suggest`, `preview`, `apply`, and `verify`; require an explicit approved plan hash before mutating imported KiCad files.
- [ ] Start with deterministic low-risk repairs: metadata/property normalization, library-table fixes, explicit no-connects, net-class assignment, missing test-point labels, and evidence-backed support passives.
- [ ] Reject ambiguous topology, part replacement, pin remapping, or geometry edits unless a dedicated repair implementation proves the required invariants.

### T255. Add semantic and visual before/after review (P1, HIGH)

- [ ] Render affected schematic sheets/PCB regions before and after a proposed repair and pair them with a semantic net/component/constraint diff.
- [ ] Verify unchanged regions remain byte- or semantically stable according to the operation contract.
- [ ] Persist reviewer decision, plan hash, timestamps, evidence IDs, tool versions, and verification results in an append-only repair log.
- [ ] Add idempotency, rollback, stale-plan, concurrent-edit, and partial-failure tests.

### T256. Expose the complete review/repair lifecycle across product surfaces (P1, MEDIUM)

- [ ] Implement shared service functions for import, analyze, findings, repair preview/apply/verify, and status/resume.
- [ ] Route CLI, HTTP, MCP, and agent skills through those functions with schema parity and structured errors.
- [ ] Add end-to-end contract tests proving the same project state, findings, plan hash, and blockers on every surface.
- [ ] Document human approval boundaries and require agents to report unsupported repairs instead of improvising file edits.

**Sprint exit:** a supported imported-design defect can be found, previewed, explicitly approved, applied transactionally, visually reviewed, and re-verified with a complete audit trail on CLI and MCP/API surfaces.

---

## Sprint 59 — Sourcing Intelligence and BOM Resilience (v0.36.0) — PLANNED

**Goal:** Make BOM decisions genuinely useful for prototype and production planning by replacing placeholder lifecycle logic and weak keyword alternates with provenance-backed, compatibility-checked data.

### T257. Replace placeholder lifecycle/availability results with sourced snapshots (P0, HIGH)

- [ ] Remove the DigiKey lifecycle `Unknown` placeholder path from `sourcing_auditor.py`; use supported distributor/manufacturer integrations with explicit unavailable/offline states.
- [ ] Normalize stock, price breaks, MOQ, packaging, factory lead time, lifecycle, timestamp, currency, region, and source into a cached snapshot schema.
- [ ] Distinguish zero stock from lookup failure, missing credentials, stale cache, and a part not carried by that distributor.
- [ ] Add deterministic recorded-response tests and keep live-network tests separately marked and non-authoritative.

### T258. Require compatibility evidence for suggested alternates (P0, HIGH)

- [ ] Replace description-keyword alternates with a constraint comparison over function, electrical limits, exact package/footprint, pinout, temperature grade, qualification, and critical parameters.
- [ ] Classify candidates as `drop_in`, `schematic_change`, `pcb_change`, or `unverified`; never call a candidate pin-compatible without a verified pin/pad map.
- [ ] Explain every passed, failed, missing, and waived constraint and link it to evidence.
- [ ] Add adversarial alternate fixtures where similar descriptions hide incompatible pinouts, voltage grades, or packages.

### T259. Add quantity- and risk-aware BOM scenarios (P1, MEDIUM)

- [ ] Compare prototype, pilot, and production quantities across supported distributors, including price breaks, MOQ, cut-tape/reel effects, and configurable buffer/scrap.
- [ ] Optimize for landed component cost, supplier count, stock coverage, lifecycle risk, or a user-defined weighted policy without hiding tradeoffs.
- [ ] Preserve the exact chosen snapshot and policy in an order-plan artifact so results remain reproducible after market data changes.
- [ ] Export order-ready lists only when identity and distributor part numbers reconcile exactly with the manufacturing BOM.

### T260. Integrate sourcing freshness into readiness and change review (P1, MEDIUM)

- [ ] Add configurable freshness thresholds and surface expired/partial snapshots as readiness blockers or explicit waivers.
- [ ] Diff BOM revisions for cost, availability, lifecycle, identity, and alternate-status changes.
- [ ] Carry sourcing blockers and evidence into the unified report, manifest, API/MCP responses, and project resume plan.
- [ ] Benchmark a JLCPCB-focused prototype scenario and a mixed-distributor production scenario end to end.

**Sprint exit:** every BOM risk statement and alternate recommendation is timestamped, sourced, reproducible, and compatibility-classified; no lookup failure is reported as zero stock.

---

## Sprint 60 — Simulation Evidence and Calibrated Confidence (v0.37.0) — PLANNED

**Goal:** Make simulation and confidence outputs decision-grade for supported circuit classes and explicitly inconclusive everywhere else.

### T261. Validate SPICE model acquisition and binding (P1, HIGH)

- [ ] Replace guessed model URLs and MPN-derived subcircuit names with a manifest that records license, source, checksum, model kind, declared subcircuit, pin order, temperature/range limits, and validation state.
- [ ] Safely unpack and inspect model archives; block path traversal, binary surprises, ambiguous subcircuits, and unverified pin-order bindings.
- [ ] Map symbol pins to model nodes explicitly and fail closed on missing/duplicate/ambiguous mappings.
- [ ] Add offline fixture models for supported regulator, op-amp, filter, MOSFET, and protection cases.

### T262. Deliver trustworthy simulations for bounded topology classes (P1, HIGH)

- [ ] Build complete testbenches with sources, loads, startup conditions, tolerances, and analysis directives from normalized design intent rather than emitting disconnected partial netlists.
- [ ] Implement transient, operating-point, and AC metrics with units and pass/fail limits; remove the current placeholder AC metric behavior.
- [ ] Detect convergence failures, skipped/unmodeled devices, invalid measurements, and insufficient simulation duration as inconclusive—not passing.
- [ ] Compare simulated metrics to hand-calculated/golden expectations with numeric tolerances in CI.

### T263. Rebuild confidence scoring around evidence coverage and calibration (P0, HIGH)

- [ ] Inventory every confidence-score contribution and remove credit derived solely from component counts, names, unverified heuristics, or skipped tools.
- [ ] Report separate dimensions for evidence coverage, rule results, external-tool verification, and unresolved risk instead of compressing uncertainty into one opaque grade.
- [ ] Calibrate thresholds against the benchmark corpus and publish confusion matrices/reliability curves for any pass/fail recommendation derived from the score.
- [ ] Ensure adding an unknown, skipped, stale, or conflicting input can only hold or reduce confidence unless new verified evidence resolves it.

### T264. Close the roadmap with outcome-level release gates (P1, MEDIUM)

- [ ] Run generation, import/repair, PCB handoff, manufacturing, sourcing, and supported simulation golden journeys from the exact built wheel.
- [ ] Publish machine-readable latency, precision/recall, evidence coverage, KiCad verification, repair success/rollback, and sourcing freshness metrics as release artifacts.
- [ ] Define regression budgets and require an explicit reviewed waiver for any release that falls below them.
- [ ] Reconcile README claims, capability maturity, sample outputs, agent skills, and changelog against the measured release artifacts.

**Sprint exit:** supported simulations have verified models/testbenches and numeric oracle tests; confidence outputs never reward missing evidence; every major product journey has an outcome-level release gate.

## Sprint 54 — Layout Quality Zero Gate, Density Strategy, Sheet Splitting, Autorouter Hardening (v0.31.0)

**Goal:** Close the remaining Sprint 53 layout follow-ups (ENDPOINT-INSIDE crossings, F13, F15), give real designs the same geometric scrutiny as the test corpus, and turn the Freerouting wrapper from a placeholder into a fail-closed, pipeline-correct integration.

### T236. Drive remaining wire-body crossings to zero (P1, HIGH) ✅ DONE

- [x] Make net-marker stub emission body-aware: `_clear_stub_length` picks a stub length whose endpoint and marker glyph clear every neighboring symbol body (candidates deviate in 1.27mm steps, non-crossing candidates preferred, fall back to the requested length). Applied to IC signal-pin labels, IC power-pin stubs, passive endpoints, and topology anchors. This closed the dominant ENDPOINT-INSIDE class — power symbols/labels parked inside adjacent cap bodies.
- [x] Split T-joint-carrying segments at their tap points in `_detour_wires_around_bodies` so tapped rails can be detoured per piece with every junction preserved as a piece endpoint (the previous pass skipped them wholesale).
- [x] Stop grid-snapping collision keep-out boxes (`component_body_bounds`, sheet-wide body-box set): rounding corners to the 1.27mm wire grid could shrink a box past a wire running just inside its true edge, hiding the collision from every detour pass.
- [x] Lower `tests/test_layout_quality.py` ceilings to zero for all three gated samples and add unit regressions for tap-splitting, junction preservation, and stub clearance.

Measured across the quality-gated samples: wire-body crossings 13 → 0 (motor_controller 2→0, oled_display_module 8→0, usb_regulated_supply 3→0).

### T237. Continuous connector-density layout strategy (P2, MEDIUM) ✅ DONE — closes F13

- [x] Replace the boolean `connector_heavy` cliff (`>= 8 connectors and no regulators and few ICs`) with `_connector_dominance`: the fraction of estimated occupied block area contributed by connectors, gated on a minimum of 4 connectors and a 0.7 dominance threshold.
- [x] Verify the audit's cliff cases: a 7-connector board and an 8-connector board with one small regulator now pack width-first; a few headers around one large MCU keep the normal layout.
- [x] Add unit regressions covering both sides of the threshold and score monotonicity in IC area.

### T238. Split A0-overflowing sheets or fail clearly (P2, MEDIUM) ✅ DONE — closes F15

- [x] Mark layouts that overflow every paper size up to A0 (`SheetLayout.overflow`) instead of only printing warnings.
- [x] Add `split_sheet_allocation`: area-balanced two-way split of an overflowing sheet's components (allocation order preserved; per-half support-passive lists recomputed).
- [x] In `generate_from_components`, re-layout split halves (bounded rounds, ref-state restored between attempts) and raise a clear `Design too large` error when a single-component sheet still overflows.
- [x] Add regressions for the balanced split, the unsplittable case, the split-then-render path, and the hard-failure path.

### T239. Layout-quality validation for real designs (P2, MEDIUM) ✅ DONE

- [x] Promote the geometric `.kicad_sch` analysis (symbol-body overlaps, wire-body crossings) from `tests/test_layout_quality.py` into `circuit_weaver.layout_quality` with a stable `analyze_schematic_file` / `analyze_schematic_text` API.
- [x] Analyze every emitted sheet in `generate_from_components` and log a warning with the per-sheet summary when a sheet is not geometrically clean.
- [x] Add a per-sheet "Layout Quality" section to the generated design report.
- [x] Point the test suite at the shared module and add unit coverage for the analyzer and the report section.

### T240. Autorouter preflight + Specctra pipeline (P2, MEDIUM) ✅ DONE

- [x] Add `preflight_pcb`: fail closed before invoking Freerouting on the engine's own placement-preview boards (zero pads by design), pad-less boards, and boards without named nets — each with a remediation message pointing at KiCad forward-annotation.
- [x] Use the supported Specctra pipeline when `kicad-cli` is available: `kicad-cli pcb export specctra` → Freerouting `-de board.dsn -do board.ses` → import hint for *File → Import → Specctra Session*. Keep the direct `.kicad_pcb` invocation as the fallback.
- [x] Add `--effort fast|medium|high` (Freerouting `-mp` pass budget) and `--timeout` to the CLI; surface incomplete-route counts in the result stats and message.
- [x] Rework `tests/test_autoroute.py` around routable fixture boards; add preflight, DSN-pipeline, effort-budget, and end-to-end placement-preview-rejection coverage. Update `docs/cli-reference.md` / `docs/user_workflow.md`, which previously told users to autoroute the pad-less placement preview.

---

## Sprint 53 — Schematic Layout Quality (congestion / overlaps / readability)

**Goal:** Make generated schematics read as professional: no stacked symbols, no wires slicing through symbol bodies, no cross-sheet "local" wires. Closes audit findings F6 and F14; F13/F15 remain open below.

### T235. Eliminate support-passive stacking and route-through-body wiring (P1, HIGH) ✅ DONE

- [x] Fix `_apply_topology_sidecar_cluster` to group passives by *resolved* parent-pin location and walk collision-free candidate slots against a sheet-wide occupancy list (previously, distinct owner labels resolving to one pin stacked C/R bodies at identical coordinates — 7 overlapping pairs on `oled_display_module` alone).
- [x] Seed the occupancy list with every cluster-motif pose and every junction anchor so sidecars never park on a wiring target.
- [x] Fix `_passive_pin_side` to treat the pin angle as authoritative (distance-based inference misclassified top-face pins near a body corner as "left", parking buck-cluster passives on the wrong face).
- [x] Make `_apply_topology_buck_cluster` face-aware: CIN/SW-anchor/FB-anchor/COUT/divider columns grow away from the pin's actual face instead of assuming side-face pins and hanging everything below the IC.
- [x] Route buck-cluster local wires around the IC body (`_wire_points_around`) instead of drawing pin-to-anchor straight lines through it.
- [x] Extend `_route_local_connection` to take multiple keep-out boxes (sibling passives, own body, neighbor ICs), generate detour candidates around every blocker, relax progressively with a logged warning instead of silently falling back to a direct line (closes F6).
- [x] Cap "local" wiring distance (`_LOCAL_WIRE_MAX_RUN` = 50.8mm): anchors/owner pins beyond the budget fall back to net labels, killing 60–130mm cross-sheet wire runs.
- [x] Add a final wire-hygiene pass (`_detour_wires_around_bodies`) that rewrites any remaining emitted segment crossing a symbol body as an endpoint-preserving detour, skipping segments carrying T-joints.
- [x] Add `tests/test_layout_quality.py`: geometric S-expression analysis of generated samples asserting zero symbol-body overlaps and per-sample wire-crossing ceilings, plus unit regressions for each fix.

Measured across the nine-sample corpus: symbol-body overlaps 11 → 0; wire-through-body segments 147 → 36.

### Layout follow-ups

- [x] Make `_apply_topology_decoupling_bank` / `_apply_topology_strap_ladder` / `_apply_topology_ldo_cluster` occupancy-aware so cluster bodies and their local anchors reserve sheet-wide slots before later motifs are placed; deduplicate shared reservations and add unit regressions for bank, LDO, and occupancy reservation behavior.
- [x] Reduce the remaining ENDPOINT-INSIDE wire-body crossings after the bank/ladder/LDO occupancy pass, including the tapped rails that still run through IC bodies on multi-tap nets. → Closed by T236 (Sprint 54): body-aware stub lengths + tap-splitting detours + un-snapped keep-out boxes drove the gated samples to zero crossings.
- [x] F13 — replace the connector-heavy boolean threshold in `placer.py` with a continuous density score. → Closed by T237 (Sprint 54).
- [x] F15 — when A0 still overflows, split the largest sheet and re-allocate (or fail with a clear "design too large" error) instead of emitting a crammed page. → Closed by T238 (Sprint 54).

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
