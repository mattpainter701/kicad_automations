# Epics — Planner Layer (v0.32 → v0.37)

> **Roles.** This file is the **planner** layer. Codex is the **worker**. `TASKS.md`
> holds the executable task list (T241–T264, four tasks per sprint). This file sits
> above it: it groups the six planned sprints into six outcome epics, fixes the
> dependency order between them, and expands each into a work-breakdown a worker can
> pick up without re-deriving architecture. Every epic cross-references its sprint and
> tasks in `TASKS.md`; where this file adds sub-tasks beyond the four headline tasks,
> they are numbered `T24x.n` so they thread back cleanly.
>
> **Authority.** `CLAUDE.md` architectural constraints (part-neutral, vendor-agnostic,
> data/spec-driven, fail-closed) and the `TASKS.md` "Roadmap Principles" (truth before
> convenience, evidence before confidence, fail closed at irreversible boundaries, one
> behavior across surfaces, benchmarks over anecdotes) are binding on every epic below
> and are not restated per-epic.

---

## Epic map & dependency order

| Epic | Theme | Sprint | Tasks | Release | Depends on |
|---|---|---|---|---|---|
| **A** | Measurable Truth Substrate | 55 | T241–T244 | v0.32.1 | — (foundation) |
| **B** | Evidence-Backed Electrical Accuracy | 56 | T245–T248 | v0.33.0 | A |
| **C** | Authoritative PCB Handoff & DRC Closure | 57 | T249–T252 | v0.34.0 | A, B |
| **D** | Import Review & Safe Repair Loop | 58 | T253–T256 | v0.35.0 | A (B, C reused) |
| **E** | Sourcing Intelligence & BOM Resilience | 59 | T257–T260 | v0.36.0 | A |
| **F** | Simulation Evidence & Calibrated Confidence | 60 | T261–T264 | v0.37.0 | A, B |
| **G** | Symbol Coverage & Provenance | 61 | T265–T268 | v0.38.0 | A, B |

```
        ┌─────────────────────────── A (substrate) ───────────────────────────┐
        │  benchmark corpus · evidence manifest · maturity registry · gates    │
        └───┬───────────────┬───────────────┬───────────────┬─────────────────┘
            │               │               │               │
            ▼               ▼               ▼               ▼
            B ───────────▶  C               E               (all consume evidence+benchmark)
        (electrical)   (PCB handoff)    (sourcing)
            │               │
            └──────┬────────┘
                   ▼
                   D (import review & repair — reuses B validators + C DRC)
                   ▲
                   │
                   F (simulation & confidence — oracle from B, calibrated on A benchmark)
```

**Critical path:** A → B → C. D, E, F can proceed in parallel once A lands, but each
of them is release-gated on A's evidence + benchmark schemas being frozen. **A must
complete first** — every other epic writes into schemas A owns (evidence IDs,
finding model, benchmark baseline). Freezing those schemas late forces rework
everywhere downstream.

**Absorbed legacy audit findings.** The 2026-05-04 pipeline audit's still-open
findings are folded into these epics rather than tracked separately:
- **F11** (power-pin substring match, `topology_builders.py:1589`) → **Epic B / T245.4**
- **F17** (footprint-size heuristic, `pcb_export.py:171-199`) → **Epic C / T249.2**
- **F18** (percentage zone map + missing categories, `placement_optimizer.py:60`, `pcb_export.py:136`) → **Epic C / T249.3**
- **F19** (pad-less export by design, `pcb_export.py:260-277`) → **Epic C / T249.1** (this is the epic's core)

---

## Epic A — Measurable Truth Substrate (Sprint 55, T241–T244)

**Outcome.** Before adding capability, make the product's existing claims *measurable
and green*. Three durable schemas are born here and every later epic consumes them:
the **benchmark corpus** (precision/recall over a labelled fixture set), the
**evidence manifest** (traceable provenance for every asserted fact), and the
**capability/maturity registry** (one state vocabulary across all surfaces). Nothing
downstream is trustworthy until this substrate exists.

**Why first.** B calibrates validator severity against the benchmark. C gates handoff
on evidence completeness. D unifies findings against the same finding model. F
calibrates confidence against the benchmark and forbids credit without evidence.
If these schemas are invented ad hoc inside each later epic they will diverge —
exactly the drift `TASKS.md` principle "one behavior across surfaces" forbids.

### Current state (grounded)
- Test baseline is red: `1431 passed, 16 skipped, 7 failed, 6 errors` (Win/Py3.13).
  User-reported clusters: three `svg-left-overflow` sample regressions + their
  layout-quality fixture errors, and a generation-call determinism assertion.
- A plain `python -m pytest` can import an already-installed `circuit_weaver` instead
  of the checkout — origin/version of the package under test is unproven.
- `doctor.py` (`run_doctor`, `CheckResult`/`DoctorReport`) checks tools/creds but
  exposes **no capability→maturity map**; README claims are hand-maintained.
- No `evidence_manifest.json`; provenance is scattered across `design_logger`,
  `sourcing_auditor`, and ad-hoc report fields with no stable IDs.
- Confidence/scoring (`confidence_dashboard.py`, `design_scorer.py`) already emit
  section breakdowns — a natural first consumer of evidence IDs.

### Work breakdown

**T241 — Restore green source + wheel gates (P0, HIGH).** *Blocking; do first.*
- **T241.1** Reproduce and bisect the 7 failures / 6 errors. Planner hypotheses to
  confirm, not assume: (a) the `svg-left-overflow` trio and their layout-quality
  fixture errors share one boundary/transform root cause (a sample crossing the left
  sheet margin after a Sprint 53/54 detour change) — fix once, expect the fixture
  errors to clear with it; (b) the determinism assertion is unstable dict/set
  ordering or a timestamp in a generation call — pin ordering or freeze the clock in
  the fixture. Do **not** relax the assertion to make it pass.
- **T241.2** Guarantee test-target identity: add a `conftest` guard (or documented
  `-p no:cacheprovider` + editable-install runner) that asserts
  `circuit_weaver.__file__` resolves inside the checkout and records
  `__version__`; fail collection otherwise. Subprocess tests must inherit the same
  interpreter/package (`sys.executable`, `PYTHONPATH`), never the ambient install.
- **T241.3** Run the identical required gate against **both** the source tree and the
  exact built wheel, on Linux and Windows.
- **T241.4** Classify every skip → `{platform, optional-tool, network, defect}`; CI
  fails on any unclassified skip. Encode classification as a marker/registry, not a
  comment.
- **T241.5** Record final counts + exact commands in `CHANGELOG.md` and the release
  workflow.
- **Exit:** required source + wheel suites 100% green on Linux+Windows; zero
  unexplained skips; documented, origin-verified runner.

**T242 — Capability & maturity registry (P1, MEDIUM).**
- **T242.1** Single source of truth: a checked-in registry (e.g.
  `src/circuit_weaver/capabilities.py` / `capabilities.json`) mapping every CLI
  command ↔ Python/HTTP/MCP/skill entrypoint to one state:
  `supported | beta | experimental | review_only | deprecated`.
- **T242.2** Each design capability declares its **verification prerequisite** and
  **output guarantee** on a fixed ladder: `static-parse < kicad-load < erc < drc <
  fabrication-ready`. Non-design operational capabilities use the paired,
  non-ordered state `not_applicable`; it cannot be mixed with a ladder value. A
  capability may never advertise a guarantee above what its code path actually
  verifies.
- **T242.3** Generate the README capability table *from* the registry; surface the
  same registry via `doctor --json` and a public API. Docs cannot drift because they
  are generated.
- **T242.4** Contract tests: reject (a) any CLI subcommand absent from the registry,
  (b) invalid maturity transitions, (c) any surface returning a stronger claim than
  its registry guarantee.
- **Registry record shape (freeze):**
  `{ id, surfaces:{cli,python,http,mcp,skill}, maturity, verification_prereq,
  output_guarantee, evidence_kinds:[...], since_version }`.

**T243 — Versioned electrical-accuracy benchmark corpus (P1, HIGH).**
- **T243.1** Directory `benchmarks/electrical/{positive,negative}/<domain>/` for
  domains: power, clock, usb, i2c, spi, uart, analog, protection, manufacturing.
  Each fixture is a minimal reviewable design + an expected-findings file; every
  expected finding carries a **stable rule ID** and rationale.
- **T243.2** Firewall: keep **generator-authored** fixtures separate from
  **independently-authored reference** fixtures so the engine is not only grading its
  own output. Mark provenance per fixture.
- **T243.3** Runner (`benchmarks/run.py` + `tests/test_benchmark_corpus.py`) reports
  per-rule and per-domain: precision, recall, FP, FN, unsupported, runtime.
- **T243.4** Checked-in **baseline artifact** (`benchmarks/baseline.json`); the gate
  is a regression in precision/recall, not aggregate pass count. Regression budget
  lives here and is consumed by T264.
- **Rule-ID scheme (freeze):** `CW-<DOMAIN>-<NNN>` (e.g. `CW-USB-014`). This ID is
  the join key across benchmark, validator findings, evidence manifest, and the
  Epic D finding model. **Assign the namespace now; every later epic reuses it.**

**T244 — Evidence manifest (P1, HIGH).** *Deep spec — Codex picks this up next.*

This is the second frozen substrate schema (the `CW-*` rule-ID namespace is the first).
Every later epic attaches provenance to its assertions through this ledger, so the
record shape, ID scheme, and fail-closed contract must be right before B/C/D/E/F build
on them. Design goal: **an asserted fact you can trace to its source, reproducibly.**

*Design invariants (bind the whole task):*
- **Deterministic IDs.** Re-running generation on the same inputs yields the same
  manifest IDs. Wall-clock (`retrieved_at`) and freshness are stored but **never** in
  the ID hash — otherwise diffs (E/T260) and dedup (D/T253) break.
- **Additive, never silent.** An absent source lowers confidence; it never fabricates
  a record or awards credit (mirrors F/T263 monotonicity).
- **Redacted by construction.** No credentials, no machine-local absolute paths ever
  enter a record — enforced at write, not by reviewer discipline.

- **T244.1 — Schema + collector module.** New `src/circuit_weaver/evidence.py`:
  - `EvidenceRecord` dataclass (freeze this shape):
    `{ id, subject_ref, claim, kind, confidence, source:{uri, doc_id, content_hash,
    retrieved_at, extraction_method}, freshness, conflicts:[evidence_id...],
    supersedes:evidence_id|null }`.
  - `EvidenceLedger` collector: `record(...) -> evidence_id` (idempotent — same inputs
    return the existing ID), `get(id)`, `for_subject(ref)`, `to_manifest()`,
    `write(output_dir)` → `evidence_manifest.json` (deterministically sorted).
  - **ID scheme (freeze):** `EV-<KIND>-<12-hex>` where the 12-hex is
    `sha256(subject_ref | claim | source.doc_id-or-uri | extraction_method)`
    truncated. Inputs only — no timestamps.
  - **`subject_ref` grammar (freeze):** `comp:<REF>`, `pin:<REF>.<num>`,
    `net:<NAME>`, `param:<REF>.<domain>.<field>`, `footprint:<name>`,
    `calc:<rule_id>@<REF>`, `tool:<name>`. This is the join key into validation and
    the finding model.
  - **`kind` taxonomy (freeze):** `datasheet | distributor | symbol_lib |
    footprint_lib | catalog | calculation | tool_result | user | heuristic | stub`.
    The last two are the fail-closed triggers.
  - **`confidence` ladder (freeze):** `verified | corroborated | single_source |
    heuristic | stub | conflicting`. `corroborated` requires ≥2 agreeing records for
    the same `subject_ref`+`claim` (the T247 two-source rule feeds this).

- **T244.2 — Populate at the real sources (grounded touchpoints).** Each producer
  calls `ledger.record(...)`; nothing invents provenance it doesn't have:
  - Component identity → `component_db.ComponentDef` fields (`mpn`, `lcsc_pn`,
    `digikey_pn`, `source_*`) → `kind=catalog|distributor|user`.
  - Pinout → `kicad_lib.symbol_to_component_def`, `symbol_resolver`,
    `easyeda_parser`, `datasheet_parser` → `kind=symbol_lib|datasheet`.
  - Footprint → `footprint_lib` (and the C/T249.2 `.kicad_mod` bbox read) →
    `kind=footprint_lib`; the regex fallback records `kind=heuristic`.
  - Electrical params/calculations → B/T245–T246 calc records → `kind=calculation`
    (carries the equation/rule version).
  - Validator findings → `validator.ValidationIssue` gains an `evidence_ids` field.
  - Tool versions + results → `doctor.CheckResult` (kicad-cli/ngspice/freerouting
    versions) and `erc_runner.ErcResult` / future DRC → `kind=tool_result`.

- **T244.3 — Carry IDs across every surface (one ID space).** Validation JSON, design
  report (`report.py`/`review_report.py`), confidence report
  (`confidence_dashboard.py`), artifact/delivery manifests
  (`assembly_manifest.py`/`delivery_manifest.py`), HTTP (`api.py`), MCP
  (`mcp_server.py`) all reference `evidence_id`s — none embeds a second, divergent
  provenance blob. `retrieved_at`/`content_hash` recorded when available; **redaction
  enforced in `EvidenceLedger.record`** (reuse the path-safety pattern from
  `design_import._safe_member_path` / `pcb_export._kicad_string`): reject/strip
  absolute paths and known credential env-var shapes before a record is stored.

- **T244.4 — Fail-closed contract.** Define `FABRICATION_CRITICAL` subject classes
  (component identity, pin→pad mapping, footprint, power-rail limits, routing/DRC
  result). A `require_backing(subject_ref, min_confidence)` gate refuses to mark any
  output order-ready when the backing evidence is only `kind∈{stub,heuristic}` (with
  the heuristic not explicitly user-acknowledged) or has unresolved `conflicts`.
  This gate is the single chokepoint the C/T252 readiness state machine calls — do
  not scatter the policy.

- **T244.5 — Determinism, idempotency & versioning.** `evidence_manifest.json` carries
  a `schema_version`; identical inputs produce byte-identical manifests (sorted keys,
  IDs excluded from wall-clock). Add a golden-manifest regression that fails on any
  unintended shape drift.

- **T244.6 — Test matrix.** (a) record/roundtrip + schema-version; (b) ID determinism
  across two runs and stability under reordering of producers; (c) redaction: a
  planted credential + absolute path never survive into the manifest (containment
  test); (d) fail-closed truth table across `kind`×`confidence`×`conflicts` for a
  fabrication-critical subject; (e) cross-surface parity: the *same* evidence ID
  appears in validation JSON, report, confidence, manifest, HTTP, and MCP for one
  planted assertion; (f) conflict path: two disagreeing sources for one
  subject+claim yield `confidence=conflicting` and block order-ready.

- **Sequencing note for Codex:** land T244.1 (module + frozen schema) and T244.4
  (fail-closed gate) *before* wide T244.2 population — the schema freeze is the part
  every later epic depends on; the producer wiring can then fan out incrementally
  without reopening the contract.

**Epic A exit gate.** All mandatory source/wheel gates green; every public workflow
carries a maturity state enforced by contract test; benchmark + evidence schemas are
versioned and already consumed by at least validation and reporting. **The rule-ID
namespace, evidence-record shape, and maturity vocabulary are frozen and published —
downstream epics may extend but not fork them.**

---

## Epic B — Evidence-Backed Electrical Accuracy (Sprint 56, T245–T248)

**Outcome.** Move from "structurally valid / passes ERC" to "traceable to component
limits, equations, and cross-checked identity." Every recommendation and synthesized
support network cites the rule/equation/source that produced it (Epic A evidence
IDs). This epic also owns the **typed power-domain model** that Epic C compiles into
PCB constraints — so its schema must land before C.

### Current state (grounded)
- Power rails are thin: `PowerPin{net, voltage, max_current_ma}` (`component_db.py`)
  — no min/max/tolerance, no direction, no sequencing, no provenance.
- `validator.py` (1075 lines) has real electrical checks already
  (`_validate_feedback_dividers`, `_validate_filter_cutoffs`,
  `_validate_crystal_caps`, `_validate_decoupling`, `_validate_enable_pins`, …) but
  severity is hand-set and unproven against any corpus.
- **F11 lives here:** `topology_builders.py:1589` still binds power via substring
  `p in name_upper`, so `MAINSVIN_SENSE` → a VIN rail.
- Support-passive synthesis (`component_db.auto_generate_bypass_caps`, T230/T234) is
  partly datasheet-driven but still falls back to universal 100nF/10µF defaults.

### Work breakdown

**T245 — Typed power domains & operating envelopes end-to-end (P1, HIGH).**
- **T245.1** Extend normalized schema: rail `v_min/v_nominal/v_max`,
  `direction (source|load|bidirectional)`, `i_peak_ma/i_steady_ma`,
  `sequencing (order, dependency)`, `tolerance`, `provenance (evidence_id)`. Extend
  `PowerPin` (and add `PowerDomain` to `design_ir.py`).
- **T245.2** Propagate through ingest → templates → `DesignIR` → validator →
  power-tree report → PCB constraint context (Epic C input). Absent fields stay
  absent — **never infer false precision**; a missing max-current is "unknown," not 0.
- **T245.3** New checks with evidence-linked calculations: over/under-voltage,
  reverse-flow, source contention, regulator dropout/headroom, current-budget,
  sequencing violation. Each emits a `CW-PWR-*` finding with observed vs expected.
- **T245.4** *(absorbs F11)* Replace substring power matching with prefix-exact +
  curated equivalence allowlist; `MAINSVIN_SENSE`-class names must not bind to a
  power rail. Regression fixture in the benchmark negative set.
- **T245.5** Benchmark cases: valid margins + near-boundary failures, multi-rail and
  battery designs (add to `benchmarks/electrical/power/`).

**T246 — Equation/datasheet-driven support-passive synthesis (P1, HIGH).**

*Framing.* The equations already exist — but only on the **checking** side, inside
`validator.py` (`_validate_feedback_dividers` line 182: `Vout=Vref·(1+Rtop/Rbottom)`;
`_validate_filter_cutoffs` line 222: RC `fc=1/(2πRC)`, LC `fc=1/(2π√LC)`;
`_validate_crystal_caps` line 297: `C_ext=2·(CL−Cstray)`). Synthesis
(`component_db.auto_generate_bypass_caps` line 1185) still hands back universal
`100nF`/`10µF` string literals with no math behind them. T246 builds the **synthesis
half** and forces both halves to share **one** equation implementation, so the T243
benchmark oracle, the generator, and the validator can never drift apart.

- **T246.1 — Single equation module (do this first).** New `src/circuit_weaver/calc.py`
  holding each passive-synthesis family as a pure function `(inputs) → CalculationRecord`
  (below). Refactor the three validators above to *consume* `calc.py` instead of
  re-deriving the formula inline. Acceptance: deleting a formula from `calc.py` breaks
  both synth and validate — proving there is exactly one source of equation truth. No
  new behavior lands until this is the shared substrate.
- **T246.2 — Frozen `CalculationRecord` contract.** Every synthesized value emits one
  (schema in the frozen-contracts box below). It is an **evidence producer**: it writes
  an `EvidenceRecord{kind=calculation}` into the T244 ledger, with `subject_ref =
  param:<REF>.<domain>.<field>` (reusing the frozen grammar), so a synthesized cap is
  traceable end-to-end exactly like a `CW-PWR-*` finding's inputs.
- **T246.3 — Replace universal defaults with recommendation records + bounded
  fallback.** Regulator I/O caps, crystal load caps, reset/enable RC straps, interface
  termination (USB/CAN/RS-485), protection nets. Order of precedence, fail-closed:
  `datasheet-recommended (component metadata) → equation-derived (calc.py) →
  bounded fallback`. Fallback is **never silent**: it emits `confidence=heuristic`
  evidence and is bounded by a declared range; a value with *no* datasheet, *no*
  equation, and *no* in-range fallback is **not emitted** (T246.5), never a bare
  `100nF`. This retires the per-MPN `_FEEDBACK_VREF` table (validator.py) in favor of a
  normalized `ComponentDef` vref field with provenance — see cleanup note.
- **T246.4 — E-series snapping is a declared policy, not a guess.** Each family declares
  `{series: E6|E12|E24|E96, direction: nearest|up|down|ratio_preserving}` and the chosen
  standard value + realized tolerance + resulting margin go in the record. **Divider
  resistor pairs snap as a pair to minimize output-voltage error — never each leg
  independently** (independent rounding corrupts the ratio). Bulk/limit caps round in the
  safe direction (up for hold-up, up for current limit headroom). The raw computed value
  and the snapped value are both retained.
- **T246.5 — Reject out-of-range *before* emission (fail closed).** An incompatible or
  out-of-bounds synthesized network raises a `CW-PSV-*` finding and the value is withheld
  from the netlist — not appended-then-warned. (New rule-ID sub-namespace `CW-PSV-001…`
  for passive-synthesis violations, under the frozen `CW-<DOMAIN>-<NNN>` scheme.)
- **T246.6 — Verification against independent oracle.** Buck/boost/LDO, crystal, USB,
  CAN/RS-485, analog-front-end designs checked against independently reviewed expected
  values (reference fixtures from T243.2). The synth output feeds the *same* validator
  that T245 proved at 1.0 — so a correctly synthesized part must produce **zero**
  `CW-PSV`/`CW-PWR` findings on itself (self-consistency gate). Add these to
  `benchmarks/electrical/passives/`.

**Cleanup folded in:** `_FEEDBACK_VREF.get(comp.mpn)` (validator.py:185) is an
unprovenanced per-MPN lookup — the exact anti-pattern CLAUDE.md warns against. T246.3
moves `vref` onto normalized component metadata with a `kind=datasheet` evidence source;
the MPN dict becomes a deprecated compatibility shim, deleted once fixtures carry the
normalized field.

> **Frozen contract — `CalculationRecord` (T246.1/.2, extends the T244 evidence
> schema; freeze before T246.3 producer wiring).**
> ```
> CalculationRecord {
>   id:              "CALC-<FAMILY>-<12-hex>"   # sha256(target | equation_id |
>                                               #   sorted(input name:value:unit) |
>                                               #   equation_version) — inputs only, no
>                                               #   timestamps (deterministic, like EV-*)
>   equation_id:     "feedback_divider" | "rc_cutoff" | "lc_cutoff" |
>                    "crystal_load_cap" | "ldo_io_cap" | "term_resistor" | ...
>   equation_version:"v1"                       # bump on any formula change
>   target:          subject_ref                # "param:<REF>.<domain>.<field>" (frozen grammar)
>   inputs:          [ { name, value, unit, evidence_id } ]  # each input cites its provenance
>   equation_str:    "Vout = Vref*(1 + Rtop/Rbottom)"        # human-readable form
>   raw_result:      { value, unit }            # before E-series snapping
>   chosen_value:    { value, unit, e_series, tolerance }    # snapped standard value
>   snap_policy:     { series: "E6|E12|E24|E96", direction: "nearest|up|down|ratio_preserving" }
>   margin:          { kind, value, unit, ok: bool }         # headroom vs the checked bound
>   policy:          "datasheet" | "equation" | "bounded_fallback"
>   confidence:      <evidence confidence ladder>            # bounded_fallback ⇒ heuristic
>   emits_evidence:  evidence_id                # the kind=calculation record it writes
> }
> ```
> - Determinism: same inputs → same `id` (idempotent in the ledger, mirrors `EV-*`).
> - `calc:<equation_id>@<REF>` is the already-frozen `subject_ref` form for the calc
>   *act*; `param:<REF>.…` is the *value* it produces. Both resolve in the ledger.
> - A withheld value (T246.5) still emits its record with `chosen_value=null` +
>   `policy` + the `CW-PSV-*` finding id, so "why is this cap missing" is answerable.

**T247 — Cross-check identity/pinout/symbol/footprint before routing (P0, HIGH).**
> ⚠️ **P0 — can't ship late.** T247 is the only P0 in Sprint 56 and is the guard Epic
> C's PCB handoff (T249/T251) *calls* before it will emit pads. If T247 slips, Epic C is
> blocked and any board produced in the interim has unverified pin→pad identity — the
> exact class of defect F17/F18/F19 are about. Sequence T247 so it lands **within** this
> sprint even if T246/T248 compress; do not let it roll into Sprint 57.

- **T247.1** Shared **identity record** joining manufacturer, exact MPN + package
  suffix, symbol pins, footprint pad numbers, distributor aliases.
- **T247.2** Compare ≥2 independent sources when available; represent
  `agree | conflict | missing | human-approved` as distinct states (not a boolean).
- **T247.3** **Block routing/manufacturing** when exact package can't be proven
  compatible with the selected footprint, or symbol-pin→pad mapping is ambiguous.
  (This is the guard Epic C's handoff calls.)
- **T247.4** Adversarial fixtures: look-alike MPNs, package-suffix changes, exposed
  pads, duplicated pin names, swapped differential pairs, distributor stubs.

**T248 — Calibrate validator severity & remediation (P1, MEDIUM).**

*Framing.* This is the task that turns "the validators exist" into "the validators are
*trustworthy* and the exit-gate numbers are *published*." It closes the Epic B gate. The
central defect it fixes: `ValidationIssue` (validator.py:39) carries a **single `level`
field** that conflates two orthogonal axes — *how sure are we this is real* vs *how bad
is it if real*. Today a weakly-evidenced guess and a proven violation can both render as
`level="error"`. T248 separates them and makes every finding self-describing and
benchmark-scored.

- **T248.1 — Full-coverage benchmark run + published scorecard.** The harness already
  computes correct per-rule precision/recall with proper `unsupported` and
  undefined-denominator handling (`benchmark_runner.py`) — but `baseline.json` only
  scores `CW-PWR-*`; the other eight domains sit in `unsupported_scope`.
  T248.1 extends fixtures + baseline so **every** registered rule (`_VALIDATORS` table,
  validator.py:1014) has either a real precision/recall pair or an explicit
  `unsupported` declaration — no rule may be silently unscored. Publish the scorecard as
  a committed artifact (`benchmarks/scorecard.json` + a human-readable summary) and wire
  `run.py --check-baseline` into the T241 release gate so a regression fails CI.
- **T248.2 — Split detection-confidence from severity (schema change).** `ValidationIssue`
  gains two fields replacing the overloaded `level`:
  - `detection_confidence`: reuse the **frozen evidence ladder**
    (`verified | corroborated | single_source | heuristic | stub | conflicting`) — how
    well-evidenced the *detection* is.
  - `severity`: `blocker | major | minor | info` — impact **if** real.
  Rendering rule (freeze): a finding may present as a hard **blocker** only when
  `severity=blocker` **and** `detection_confidence ∈ {verified, corroborated}`. A
  `severity=blocker` + `detection_confidence=heuristic` finding renders as a *review
  item*, never a confirmed defect. Keep `level` as a derived, read-only compatibility
  property (a pure function of the two new fields) so existing consumers don't break —
  deprecate, don't hard-cut.
- **T248.3 — Every actionable finding is self-describing.** Required fields on any
  finding with `severity ≥ minor`: violated `rule_id` (`CW-<DOMAIN>-<NNN>`), observed
  value (unit-labelled), expected range, `evidence_ids` (the T244/T246 IDs that back
  it — this is where the `ValidationIssue.evidence_ids` field from T244.2 lands), and a
  **safest next action** (the remediation, phrased as the least-destructive fix). A
  finding that cannot name its evidence is itself a `conflicting`/`stub` case and must
  be marked as such, not published as confirmed.
- **T248.4 — Explicit, expiring suppressions.** A suppression/override record:
  `{ rule_id, scope (comp/net/design glob), owner, reason, created_at, expires_at,
  approved_by }`. Enforcement is fail-closed at the release gate: an **expired**
  suppression, a suppression with **no expiry**, or one whose `scope` is broader than a
  single justified target (e.g. wildcards all refs) **fails the T241 gate**. Suppressions
  are evidence too — a suppressed finding still appears in the scorecard denominators so
  precision/recall isn't gamed by hiding failures. Store in a versioned
  `suppressions.yaml` (or json) alongside the benchmark, never inline per-run flags.

**Sequencing.** T248.2 (the `ValidationIssue` split) is a schema change every other
finding-producer touches — land it **before** T248.3/.4 wiring, same discipline as
"schema before producers" in T244/T246. T248.1's scorecard can proceed in parallel since
it reads outputs, not the schema. Note the dependency the *other* way: T248.1's ≥95%/≥90%
targets for the passive domains only become real once T246's synthesis lands, and the
identity rules only once T247 lands — so T248 finalizes **after** T246/T247, and is the
correct last task in the sprint (it certifies the whole epic).

**Epic B exit gate.** Critical generated circuits carry traceable operating
envelopes, calculated support values, and verified pin→pad identity. Benchmark
targets: **≥95% precision, ≥90% recall** for supported rules. Power-domain schema is
frozen (Epic C consumes it).

---

## Epic C — Authoritative PCB Handoff & Constraint Closure (Sprint 57, T249–T252)

**Outcome.** Turn an approved placement review into a **real, pad-bearing** KiCad PCB
with authoritative connectivity, compiled electrical constraints, and a transactional
DRC gate — while the existing pad-less *placement preview* contract stays intact and
clearly separate. This is the single largest functionality jump on the roadmap and
directly closes legacy audit findings **F17, F18, F19** (and consumes F11's fix from
Epic B).

### Current state (grounded)
- **F19:** `pcb_export._footprint_sexpr` deliberately emits **zero pads**
  (`pcb_export.py:251`, docstring lines 265-272); the artifact is a preview hint,
  forward-annotation is authoritative. Gap-close = a *separate, opt-in, real-pad* path —
  never relabel the preview.
- **F17:** `_footprint_size_mm` (`pcb_export.py:171-199`) is regex + hardcoded
  fallbacks (BGA→25×25, small IC→5×5). No real `.kicad_mod` bbox read.
  `footprint_lib.KiCadFootprintLibrary` exists but only resolves URLs/alternatives.
- **F18:** `placement_optimizer._ZONE_CENTERS` (`placement_optimizer.py:60`) is
  board-percentage → aspect-blind; `pcb_export._ZONE_MAP` (`pcb_export.py:136`)
  misses `motor`, `audio`, `power_management` (silently → `digital`).
- Autorouter (`autoroute.py`, Sprint 54/T240) is Specctra-only, preflight fail-closed,
  DSN pipeline present — ready to consume a real pad-bearing board.
- `placement_pipeline.py` already does staged/transactional writes with an output
  lock and last-known-good preservation — reuse this pattern for the real board.
- `erc_runner.py` parses ERC JSON into a typed result — mirror it for DRC (no DRC
  runner exists yet; T251.1 is net-new).
- **T252 target grounding:** `confidence_dashboard.py:47` already carries an informal
  `readiness` string (`ready_for_fab | needs_review | not_ready`, hardcoded to
  `ready_for_fab` at line 423). That is one of the scattered readiness booleans T252's
  single state machine subsumes — it must read the state machine, not set its own.

### Work breakdown

**T249 — Authoritative schematic→PCB handoff (P0, HIGH).**
- **T249.1** *(closes F19)* New path emitting a **real** `.kicad_pcb`: resolved
  library footprints **with pads/pad-numbers**, net assignments, board outline,
  stack-up, and the approved placement state. Distinct artifact + code path from the
  preview; the preview keeps its zero-pad banner. Refuse to relabel the preview.
- **T249.2** *(closes F17)* Read real footprint bbox/courtyard from `.kicad_mod` via
  the fp-lib table (extend `footprint_lib`); **cache per footprint name**; fall back
  to the regex heuristic *only* when the file isn't found, and mark the fallback as
  low-confidence evidence.
- **T249.3** *(closes F18)* Zones in **absolute mm relative to board edges**,
  aspect-aware (replace `_ZONE_CENTERS` percentages); align `_ZONE_MAP` with the full
  `component_db` category set (add `motor`, `audio`, `power_management`, …). No
  category silently collapses to `digital`.
- **T249.4** Preserve stable references + UUID identity across regenerate/apply;
  produce a **semantic change manifest** (added/removed/moved/remapped).
- **T249.5** Refuse handoff for placeholder geometry, unresolved footprints, pin/pad
  mismatch (Epic B/T247 guard), stale placement approval, or missing board
  constraints — fail closed.
- **T249.6** Round-trip loadability proven in KiCad 8/9/10 gates with golden 2-layer
  and 4-layer designs.

**T250 — Compile electrical intent into enforceable PCB constraints (P1, HIGH).**
- **T250.1** Translate normalized interfaces + power domains (Epic B) into net
  classes, differential pairs, width/clearance/via rules, impedance targets, length
  constraints, keepouts, placement constraints.
- **T250.2** Record each constraint's origin: `calculated | user | manufacturer |
  fab-profile`; flag conflicts **before** board mutation.
- **T250.3** Benchmark coverage: USB 2.0, crystal loop, switch-mode power loop, I2C,
  CAN/RS-485, analog sense, high-current rails.
- **T250.4** Verify emitted KiCad project/board rules match the evidence manifest and
  survive reopen/export.

**T251 — Transactional DRC & connectivity closure (P0, HIGH).**
- **T251.1** Run KiCad connectivity + DRC on the **exact staged board bytes**
  (`kicad-cli pcb drc`); parse violations into the Epic D shared findings schema with
  stable rule IDs + object refs (mirror `erc_runner._parse_erc_json`).
- **T251.2** Require zero unapproved connectivity errors + zero fab-profile blockers
  before publishing an authoritative board.
- **T251.3** Preserve last-known-good board + reports when apply/save/reload/DRC/
  manifest reconciliation fails (reuse `placement_pipeline` staging + lock).
- **T251.4** Deterministic rerun + failure-injection tests: interrupted writes, stale
  board state, KiCad absent, version differences, DRC parser drift.

**T252 — Single manufacturing-readiness contract (P1, MEDIUM).**
- **T252.1** Replace scattered readiness booleans with **one state machine** over
  identity, placement, routing, ERC, DRC, BOM/CPL reconciliation, Gerber/drill
  validation, approved overrides.
- **T252.2** CLI, API, MCP, HTML, manifests return the **same** state, blockers,
  evidence IDs, next safe actions.
- **T252.3** `manufacturing-readiness --json` command; export/publish paths cannot
  bypass its blockers.
- **T252.4** Gate two golden designs end to end: generate → reviewed placement → real
  PCB → DRC → verified BOM/CPL/Gerbers.

> **Frozen contract 1 — Authoritative-board vs preview separation (T249.1, closes
> F19; freeze before any pad-emitting code).** The one rule that prevents re-opening
> F19: the two artifacts must be **impossible to confuse**, structurally not by label.
> - Distinct filenames: preview stays `*.pcb_preview.kicad_pcb` (or current name) with
>   its zero-pad banner; the authoritative board is `*.kicad_pcb` produced **only** by
>   the new path. A file may carry pads **or** the preview banner, never both — a
>   contract test asserts the preview path emits zero `(pad …)` s-exprs and the
>   authoritative path emits ≥1 per placed component with a real footprint.
> - Every authoritative board records `board_provenance` evidence
>   (`subject_ref=tool:pcb_handoff`, `kind=tool_result`) naming the source placement
>   approval id, fp-lib snapshot, and the T247 identity-guard result it passed.
> - No code path may *upgrade* a preview file in place to authoritative — it is always a
>   fresh emit from resolved footprints. Relabeling is a fail-closed error.
>
> **Frozen contract 2 — `PcbConstraint` record (T250; extends the evidence schema, same
> shape discipline as `CalculationRecord`).**
> ```
> PcbConstraint {
>   id:          "PCBC-<CLASS>-<12-hex>"   # sha256(target | class | normalized-params) — deterministic
>   klass:       "net_class" | "diff_pair" | "width" | "clearance" | "via" |
>                "impedance" | "length" | "keepout" | "placement"
>   target:      subject_ref               # net:<NAME> | comp:<REF> | net_class:<NAME> (frozen grammar)
>   params:      { … class-specific, unit-labelled … }
>   origin:      "calculated" | "user" | "manufacturer" | "fab_profile"   # T250.2
>   evidence_ids:[ … ]                     # what proves it (power domain, calc record, fab profile)
>   conflicts:   [ constraint_id … ]       # flagged BEFORE board mutation (T250.2), not after
> }
> ```
> Constraints compile from Epic B's frozen power-domain + interface schema; a constraint
> with `origin=calculated` must cite the `CalculationRecord`/power evidence it derives
> from. Conflicts fail closed before the board is touched.
>
> **Frozen contract 3 — DRC findings reuse the T248 finding model (T251.1; do NOT fork).**
> DRC violations parse into the **same** `ValidationIssue` schema T248 froze —
> `severity` + `detection_confidence` + `rule_id` (`CW-DRC-<NNN>`) + `evidence_ids` +
> object refs — not a parallel DRC-only struct. `kicad-cli pcb drc` output is a
> `kind=tool_result` evidence source; a DRC error is `detection_confidence=verified`
> (the tool observed it). This is the shared finding model Epic D also consumes — freeze
> it here so D doesn't inherit a second shape.
>
> **Frozen contract 4 — `ManufacturingReadiness` state machine (T252; one vocabulary,
> all surfaces).** One ordered state enum, single source of truth, subsumes
> `confidence_dashboard.readiness` and every scattered boolean:
> `not_ready → needs_review → drc_pending → drc_clean → fabrication_ready`, plus a
> terminal `blocked{reason}`. Transitions are gated by evidence (e.g. `drc_clean`
> requires a passing `CW-DRC` run's tool_result evidence; `fabrication_ready` requires
> the T244.4 `require_fabrication_evidence` gate to pass over identity/pads/DRC). CLI,
> API, MCP, HTML, and manifests all **read** this one state — none computes its own.
> Export/publish paths query it and refuse on any state below `fabrication_ready` (or an
> explicit, expiring T248.4 override).

**Sequencing.** Freeze contracts 1–4 first (they are what D and the export surfaces
join on). Then: **T249 before T250 before T251** (can't constrain or DRC a board that
doesn't exist yet); T252's state machine can be scaffolded in parallel but only reaches
`drc_clean`/`fabrication_ready` once T251 lands. T249.5 reuses the **T247 identity guard
verbatim** — it must not re-implement the check. The pad-less preview path is touched
**only** to keep it separate, never to extend it.

**Epic C exit gate.** ≥2 representative designs complete a transactional,
evidence-linked KiCad PCB handoff and pass the configured KiCad DRC /
manufacturing-readiness gate. F17/F18/F19 closed; the pad-less preview contract is
still explicit and separate. The four contracts above are frozen (Epic D consumes the
finding model + readiness state).

---

## Epic D — Import Review & Safe Repair Loop (Sprint 58, T253–T256)

**Outcome.** Promote import analysis from report-only to a **human-reviewable,
transactional remediation** workflow that never makes uncontrolled edits to a
customer's design. Reuses Epic B's validators and Epic C's DRC as verification steps;
owns the **unified finding model** that Epics A/B/C findings normalize into.

### Current state (grounded)
- `design_import.py` (938 lines) already does safe extraction (`safe_extract_zip`,
  `_safe_member_path`), inventory, content-identity caching, staged install with
  rollback/quarantine — a strong transactional base to build repair on.
- `generational_repair.py` (Sprints 51/53/T233) does I2C/SPI/UART/crystal repair on
  *generated* designs — repair primitives exist but aren't wired to imported KiCad
  files or to a plan/approve/apply/verify lifecycle.
- `diff_renderer.py` (`compute_diff`, `_generate_svg`, `render_html`) diffs design
  specs and renders before/after SVG — reusable for repair review.
- `review_report.py` renders ERC/DFM/BOM/scoring HTML — the native report to extend.

### Work breakdown

**T253 — Unify findings across generated + imported artifacts (P1, MEDIUM).**
- **T253.1** One versioned **finding model** normalizing schematic/PCB/Gerber/ERC/
  DRC/DFM/sourcing/evidence-conflict findings. **Reuses Epic A's `CW-*` rule IDs.**
- **T253.2** Fields: stable rule/finding ID, severity, detection confidence, exact
  object/location, evidence ID, remediation options, verification status.
- **T253.3** Deduplicate one root cause across analyzers while keeping every
  supporting observation.
- **T253.4** SARIF + JSON export for CI/code-review, without weakening the HTML
  report.

**T254 — Bounded, transactional repair plans (P0, HIGH).**
- **T254.1** Convert supported findings into explicit operations: prerequisites,
  affected objects/nets, expected postconditions, risk, rollback data.
- **T254.2** Separate `suggest | preview | apply | verify`; require an **approved plan
  hash** before mutating imported KiCad files (extend `design_import` staging).
- **T254.3** Start with deterministic low-risk repairs only: metadata/property
  normalization, library-table fixes, explicit no-connects, net-class assignment,
  missing test-point labels, evidence-backed support passives.
- **T254.4** **Reject** ambiguous topology, part replacement, pin remap, geometry
  edits unless a dedicated repair implementation proves the required invariants.

**T255 — Semantic + visual before/after review (P1, HIGH).**
- **T255.1** Render affected sheets/PCB regions before+after (reuse `diff_renderer`),
  paired with a semantic net/component/constraint diff.
- **T255.2** Verify unchanged regions stay byte- or semantically-stable per the
  operation contract.
- **T255.3** Append-only repair log: reviewer decision, plan hash, timestamps,
  evidence IDs, tool versions, verification results.
- **T255.4** Idempotency, rollback, stale-plan, concurrent-edit, partial-failure
  tests.

**T256 — Expose review/repair lifecycle across surfaces (P1, MEDIUM).**
- **T256.1** Shared service functions: import, analyze, findings, repair
  preview/apply/verify, status/resume.
- **T256.2** CLI/HTTP/MCP/skills route through those functions with schema parity +
  structured errors.
- **T256.3** End-to-end contract tests: same project state, findings, plan hash,
  blockers on every surface.
- **T256.4** Document human-approval boundaries; agents must report unsupported
  repairs, never improvise file edits.

**Epic D exit gate.** A supported imported defect can be found → previewed →
explicitly approved → applied transactionally → visually reviewed → re-verified, with
a complete audit trail, on CLI and MCP/API.

---

## Epic E — Sourcing Intelligence & BOM Resilience (Sprint 59, T257–T260)

**Outcome.** Make BOM decisions genuinely useful for prototype→production planning:
provenance-backed lifecycle/availability, compatibility-checked alternates,
quantity/risk-aware scenarios, and sourcing freshness wired into readiness. Largely
independent of B/C; release-gated on Epic A's evidence/provenance schema.

### Current state (grounded)
- `sourcing_auditor.py`: `_query_digikey_lifecycle` returns an **`Unknown`
  placeholder**; `_suggest_alternates` is **description-keyword** based
  (`_suggest_alternates(mpn, max_results)`) — exactly the weak paths to replace.
- Loaders exist: `digikey_loader.py`, `mouser_loader.py`, `parts_lookup.py`,
  `cost_bom.py` — normalize their outputs into one snapshot schema.
- `ComponentDef` already carries `lcsc_pn`, `digikey_pn`, `source_*` alias fields —
  the identity anchor for reconciliation.

### Work breakdown

**T257 — Sourced lifecycle/availability snapshots (P0, HIGH).**
- **T257.1** Remove the DigiKey `Unknown` placeholder; use supported distributor/mfr
  integrations with explicit `unavailable | offline` states.
- **T257.2** Normalized snapshot schema: stock, price breaks, MOQ, packaging, factory
  lead time, lifecycle, timestamp, currency, region, source.
- **T257.3** Distinguish **zero stock** from lookup-failure / missing-credentials /
  stale-cache / not-carried-by-distributor.
- **T257.4** Deterministic **recorded-response** tests; live-network tests separately
  marked and non-authoritative (ties to Epic A skip classification).

**T258 — Compatibility evidence for alternates (P0, HIGH).**
- **T258.1** Replace keyword alternates with a **constraint comparison**: function,
  electrical limits, exact package/footprint, pinout, temp grade, qualification,
  critical parameters.
- **T258.2** Classify: `drop_in | schematic_change | pcb_change | unverified`. Never
  call a candidate pin-compatible without a verified pin/pad map (reuse Epic B/T247
  identity record).
- **T258.3** Explain every passed/failed/missing/waived constraint with evidence IDs.
- **T258.4** Adversarial fixtures: similar descriptions hiding incompatible pinouts /
  voltage grades / packages.

**T259 — Quantity- & risk-aware BOM scenarios (P1, MEDIUM).**
- **T259.1** Compare prototype/pilot/production quantities across distributors:
  price breaks, MOQ, cut-tape/reel, configurable buffer/scrap.
- **T259.2** Optimize for landed cost / supplier count / stock coverage / lifecycle
  risk / user-weighted policy — **without hiding tradeoffs**.
- **T259.3** Persist exact chosen snapshot + policy in a reproducible **order-plan
  artifact**.
- **T259.4** Emit order-ready lists only when identity + distributor PNs reconcile
  exactly with the manufacturing BOM.

**T260 — Sourcing freshness in readiness & change review (P1, MEDIUM).**
- **T260.1** Configurable freshness thresholds; expired/partial snapshots become
  readiness blockers or explicit waivers (feed Epic C/T252 state machine).
- **T260.2** Diff BOM revisions for cost/availability/lifecycle/identity/alternate
  status.
- **T260.3** Carry sourcing blockers + evidence into the unified report, manifest,
  API/MCP, resume plan.
- **T260.4** Benchmark a JLCPCB-focused prototype scenario + a mixed-distributor
  production scenario end to end.

**Epic E exit gate.** Every BOM risk statement + alternate recommendation is
timestamped, sourced, reproducible, and compatibility-classified; no lookup failure
is ever reported as zero stock.

---

## Epic F — Simulation Evidence & Calibrated Confidence (Sprint 60, T261–T264)

**Outcome.** Make simulation and confidence outputs **decision-grade** for supported
circuit classes and **explicitly inconclusive** everywhere else. Closes the roadmap
with outcome-level release gates. Depends on A (benchmark + confidence calibration)
and B (electrical envelopes as numeric oracle).

### Current state (grounded)
- `simulation.py` (`plan_simulations`, `score_simulation_confidence`,
  `run_design_simulations`) + `spice_netlist.py` (`export_spice_netlist`,
  `_ic_to_spice_subckt`, `_generate_analysis_cards`) exist; AC metric behavior is
  placeholder and model binding is MPN-derived (guessed).
- `confidence_dashboard.generate_confidence_report` + `design_scorer`
  (`_score_power_integrity`, `_score_signal_integrity`, `_score_thermal`,
  `_score_manufacturing`) already decompose scores — but can award credit from
  counts/names/unverified heuristics.

### Work breakdown

**T261 — Validate SPICE model acquisition & binding (P1, HIGH).**
- **T261.1** Replace guessed model URLs + MPN-derived subckt names with a **model
  manifest**: license, source, checksum, model kind, declared subcircuit, pin order,
  temp/range limits, validation state.
- **T261.2** Safely unpack/inspect archives; block path traversal, binary surprises,
  ambiguous subcircuits, unverified pin-order bindings (reuse `design_import`
  extraction safety).
- **T261.3** Map symbol pins → model nodes explicitly; fail closed on missing/
  duplicate/ambiguous mappings.
- **T261.4** Offline fixture models for regulator, op-amp, filter, MOSFET, protection.

**T262 — Trustworthy simulations for bounded topology classes (P1, HIGH).**
- **T262.1** Build complete testbenches (sources, loads, startup, tolerances,
  analysis directives) from normalized design intent — no disconnected partial
  netlists.
- **T262.2** Implement transient/OP/AC metrics with units + pass/fail limits; remove
  placeholder AC behavior.
- **T262.3** Convergence failure / skipped-unmodeled device / invalid measurement /
  insufficient duration → **inconclusive, not passing**.
- **T262.4** Compare simulated metrics to hand-calculated/golden expectations with
  numeric tolerances in CI (oracle from Epic B envelopes).

**T263 — Rebuild confidence around evidence coverage & calibration (P0, HIGH).**
- **T263.1** Inventory every confidence contribution; remove credit from mere
  counts/names/unverified heuristics/skipped tools.
- **T263.2** Report separate dimensions: evidence coverage, rule results, external-
  tool verification, unresolved risk — not one opaque grade.
- **T263.3** Calibrate thresholds against the benchmark; publish confusion matrices /
  reliability curves for any pass/fail recommendation.
- **T263.4** **Monotonicity invariant:** adding an unknown/skipped/stale/conflicting
  input can only **hold or reduce** confidence unless new verified evidence resolves
  it. (Property test.)

**T264 — Outcome-level release gates (P1, MEDIUM).**
- **T264.1** Run generation, import/repair, PCB handoff, manufacturing, sourcing,
  supported-simulation **golden journeys from the exact built wheel**.
- **T264.2** Publish machine-readable metrics as release artifacts: latency,
  precision/recall, evidence coverage, KiCad verification, repair success/rollback,
  sourcing freshness.
- **T264.3** Regression budgets + explicit reviewed waiver for any release below them
  (consumes Epic A/T243.4 baseline).
- **T264.4** Reconcile README claims, capability maturity, sample outputs, agent
  skills, changelog against measured release artifacts.

**Epic F exit gate.** Supported simulations have verified models/testbenches + numeric
oracle tests; confidence never rewards missing evidence (monotonicity property holds);
every major product journey has an outcome-level release gate.

---

## Epic G — Symbol Coverage & Provenance (Sprint 61, T265–T268)

**Release v0.38.0. Depends on A (evidence substrate, confidence ladder, `CW-*` namespace) and
B (T247 identity cross-check). Independent of C/D/E/F — can run in parallel after B ships.**

**Why this epic exists.** "Symbols with no source/library" was one of the product's biggest
pains. The *safety* half is already closed: `symbol_resolver.py`'s 7-tier chain fails closed to
an explicit `unresolved`/`stub`, and `validator.py:973` `_validate_pinout_sources` blocks
generation on any `pinout_source=="stub"` until the user supplies a `pin_map` or sets
`pinout_verified`. What is **not** solved is the *coverage* half, and research surfaced three
concrete, load-bearing gaps:

1. **Coverage is unmeasured.** The only thing the codebase calls "coverage" is *validation-rule*
   coverage (`benchmark_baseline.py:23`). There is **no metric for symbol-resolution coverage** —
   we cannot say what fraction of representative parts resolve to a trusted symbol, per tier or
   per category. You cannot grow what you do not measure; this is the same gap the electrical
   scorecard closed for Epic B, applied to symbols.
2. **The catalog is un-provenanced.** The curated `ic_data` store is ~100 entries across 12
   category files; **every entry has `pins` but ZERO carry a provenance/evidence field** (verified:
   `with_provenance_field=0`). A symbol resolved from the catalog therefore asserts a pinout with
   no `kind=symbol_lib` evidence tying it to a datasheet/library and no confidence rating —
   invisible to the Epic A substrate that every other fact now flows through.
3. **Ingestion is non-deterministic and evidence-blind.** `datasheet_parser.py` *can* extract pin
   tables (`_parse_pin_table_text`, `_normalize_pin_schema`) but stamps a wall-clock
   `extracted_timestamp` (`:297`) — which would break the no-timestamp determinism contract the
   moment it feeds an ID — scores no extraction confidence, and emits no `EvidenceRecord`.
4. **Coverage is hostage to a local KiCad install.** The KiCad-symbol tier (`kicad_lib.py:395-463`,
   `_find_local_kicad`) discovers symbols only from a locally-installed KiCad (hardcoded
   `C:/Program Files/KiCad/…`, `/usr/share/kicad/symbols`, `KICAD_SYMBOL_DIR`). Tier 3 is therefore
   **empty in headless/CI and minimal on a fresh install** — the largest ready pool of open symbols
   is left on the floor unless the operator happens to have a full KiCad install. The original
   "discover the local install" design was never broadened to *pull* the libraries themselves.

**Thesis:** make coverage a *measured, provenanced, deterministically-grown* property — mirroring
how Epic B made electrical accuracy measured — without weakening the fail-closed posture already
in place. New rule domain **`CW-SYM-*`** (free; existing domains are ANALOG/CLK/DRC/ERC/POWER/
PWR/PSV/SPI/UART/USB/ID).

> **Frozen contract 1 — Symbol-coverage scorecard (deterministic, committed, regression-gated).**
> Mirror `benchmarks/electrical/` structure under `benchmarks/coverage/`: a versioned corpus of
> representative MPNs (per category), scored by `resolution_tier` (registry|ic_data|kicad|cache|
> easyeda|digikey|mouser|unresolved) and `resolution_quality` (see contract 3). Emits a committed
> scorecard JSON + a baseline gate (`--check-baseline` style) that fails closed on coverage
> regression. Offline-deterministic: remote tiers (easyeda/digikey/mouser) are replayed from
> recorded fixtures, never live, so the score is reproducible in CI. **No wall-clock in any scored
> field or ID.**

> **Frozen contract 2 — Every catalog pinout carries provenance evidence (fail-closed at ingestion).**
> Each `ic_data` entry MUST carry a `kind=symbol_lib` (or `kind=datasheet`) `EvidenceRecord` per
> Epic A's frozen shape, with `subject_ref="pin:<MPN>.<num>"` scope and a `source` identifying the
> library/datasheet. `register_ic` REJECTS an entry whose pinout lacks provenance (mirrors T246's
> "feedback_vref requires `_provenance`" rule — CLAUDE.md fail-closed). Reuses Epic A's evidence
> `kind` taxonomy (`symbol_lib` is already in the frozen list — **extend, do not fork**).

> **Frozen contract 3 — Resolution-quality ladder = Epic A confidence ladder, applied to symbols.**
> A resolved symbol's trust is one of `verified|corroborated|single_source|heuristic|stub`
> (Epic A's frozen ladder — no new vocabulary). `verified` requires the T247 identity cross-check
> (symbol pins ↔ footprint pads) to pass; a datasheet-only or single-library pinout is at most
> `single_source`; a distributor stub with no pin topology is `stub`. **A pinout is never silently
> promoted to `verified` without the T247 join.** This is the field the scorecard (contract 1) and
> readiness (T268) both read.

**T265 — Symbol-coverage scorecard & baseline (P0, HIGH). Measurement first.**
- **T265.1** Build `benchmarks/coverage/` corpus (per-category MPN sets seeded from the existing
  12 `ic_data` categories + a deliberately-unresolvable negative set), and a `coverage_runner`
  that scores `resolution_tier` × `resolution_quality` deterministically (remote tiers replayed
  from recorded fixtures). Freeze contract 1.
- **T265.2** Emit a committed scorecard JSON + human summary; add a `--check-baseline` regression
  gate that fails closed on coverage or quality regression (reuse `benchmark_baseline.py` shape).
- **T265.3** Establish the honest v0.38 baseline — publish the current resolution rate and the
  `stub`/`unresolved` counts as the declared starting point (no inflation), exactly as the
  electrical scorecard declared 14 scored / 19 unsupported.

**T266 — Provenance-backed catalog (P0, HIGH).**
- **T266.1** Extend the `ic_data` entry schema with a required provenance block; make `register_ic`
  (`ic_data/__init__.py:215`) reject a pinout with no `kind=symbol_lib`/`kind=datasheet` evidence.
  Freeze contract 2.
- **T266.2** Retrofit the ~100 existing entries with provenance evidence (from their existing
  `datasheet_url` where present; mark `single_source` where only one library backs the pinout;
  mark `verified` only where the T247 join passes). No entry silently `verified`.
- **T266.3** Thread `symbol_lib` evidence IDs through the resolver return path so a resolved
  `ComponentDef` carries its provenance into the evidence manifest (like B's power/calc evidence).

**T267 — Deterministic, evidence-emitting ingestion pipeline (P1, HIGH).**
- **T267.1** Remove the wall-clock `extracted_timestamp` (`datasheet_parser.py:297`) from any field
  that feeds an ID or scored output; make datasheet extraction reproducible (same PDF bytes → same
  `EV-<KIND>-<12hex>` id, per Epic A's determinism rule).
- **T267.2** Score extraction confidence (pin-table completeness, name/number consistency) and emit
  each extracted pinout as a `kind=datasheet` `EvidenceRecord`; cross-check against the T247
  identity join before admitting to the catalog — an extracted pinout that fails pin↔pad coverage
  is `review_only`, never auto-promoted.
- **T267.3** Same deterministic + evidence-emitting treatment for the KiCad-library
  (`kicad_lib.py`) and EasyEDA/LCSC (`easyeda_parser.py`) tiers, so every non-stub resolution can
  state its source and confidence.
- **T267.4** **Decouple the KiCad-symbol tier from the local install (gap 4).** Vendor the official
  open KiCad symbol libraries as a deterministic, versioned, bundled source (pinned to a commit,
  hash-verified) so headless/CI runs get identical coverage to a full desktop install; the local
  install (`_find_local_kicad`) becomes an *additive override*, not the only source. Evaluate
  additional pullable symbol sources under **explicit license + provenance discipline** — the
  official KiCad libraries are permissively licensed and are the clear first pull; catalog any
  third-party source (SnapEDA, Ultra Librarian, Component Search Engine, vendor EDA exports) with
  its license posture before ingesting, and never bundle a source whose terms forbid
  redistribution. Every symbol pulled this way still flows through contract 2 (provenance) and
  contract 3 (quality ladder) — a bundled library symbol is `single_source` until the T247 join
  corroborates it.

**T268 — Coverage in readiness + the frequency-weighted growth loop (P1, MEDIUM).**
- **T268.1** Add symbol-coverage as a first-class dimension in `confidence_dashboard.py` (which has
  none today) and in the unified report/manifest — separate from evidence coverage, per F/T263's
  "report separate dimensions" discipline. Never reward missing symbols (monotonicity).
- **T268.2** A design's `unresolved`/`stub` parts become explicit `CW-SYM-*` readiness blockers
  with concrete remediation ("supply pin_map / add provenanced catalog entry"), consumed by the
  C/T252 `ManufacturingReadiness` state machine.
- **T268.3** Close the loop: emit a **coverage-gap report** that ranks the highest-impact missing
  parts by frequency across the corpus/real designs, so catalog growth (`TASKS.md:534`'s lever) is
  prioritized by real demand instead of ad-hoc.

**Sequencing.** Freeze the three contracts first. **T265 → (T266 ‖ T267) → T268.** Measurement
(T265) must land first so T266/T267 improvements are provable against a baseline; T266 and T267
both feed the catalog and can run in parallel; T268 consumes all three. T266.2's retrofit and
T267.2's admission both depend on B/T247 — do not promote any pinout to `verified` before the
identity join is wired.

**Epic G exit gate.** Symbol-resolution coverage is measured by a committed, regression-gated
scorecard; every catalog pinout carries `kind=symbol_lib`/`datasheet` provenance and a
confidence-ladder rating; datasheet/library ingestion is deterministic and evidence-emitting; the
KiCad-symbol tier no longer depends on a local install (official libraries bundled, hash-verified,
CI-reproducible); `unresolved`/`stub` parts are explicit readiness blockers; and a
frequency-weighted coverage-gap report exists to steer catalog growth. Fail-closed posture is
preserved throughout — nothing here lets an unsourced or unverified symbol reach generation
unblocked.

**Open planner question (G).** Which additional symbol sources beyond the official KiCad libraries
do we accept into the bundle, and under what license bar? Official KiCad libs are the clear first
pull (permissive, redistributable). SnapEDA / Ultra Librarian / Component Search Engine have
broader coverage but restrictive redistribution terms — likely *fetch-on-demand with attribution*
rather than *bundled*. Needs the maintainer's license-risk call before T267.4 ingests any
third-party source. (Related to A/T243.2's externally-sourced-fixture licensing question.)

---

## Frozen-schema checklist (owned by Epic A, extended by later epics)

These are the contracts that cause the most rework if they drift. Freeze in Sprint 55;
later epics **extend, never fork**:

1. **Rule-ID namespace** `CW-<DOMAIN>-<NNN>` — benchmark ↔ validator ↔ evidence ↔
   findings (A/T243, B/T248, D/T253).
2. **Evidence record shape** — provenance for every asserted fact (A/T244, all epics).
3. **Finding model** — one normalized shape for every analyzer (A seeds, D/T253 owns).
4. **Maturity vocabulary** `supported|beta|experimental|review_only|deprecated`
   (A/T242, surfaced everywhere).
5. **Verification contract:** ordered design ladder `static-parse < kicad-load < erc
   < drc < fabrication-ready`, plus paired non-design state `not_applicable` (A/T242,
   C/T251-T252 enforce).
6. **Power-domain schema** (B/T245, consumed by C/T250).
7. **Manufacturing-readiness state machine** (C/T252, consumed by E/T260).
8. **Symbol-coverage scorecard** — deterministic, committed, regression-gated corpus scored by
   resolution tier × quality (G/T265). Offline-replayed remote tiers; no wall-clock.
9. **Symbol provenance + resolution-quality** — every catalog pinout carries `kind=symbol_lib`/
   `datasheet` evidence; trust uses Epic A's confidence ladder, `verified` gated on the B/T247
   identity join (G/T266). Reuses A's evidence taxonomy — **extends, never forks**.

## Open planner questions (for the maintainer)

- **Epic sequencing vs. parallelism:** D/E/F are drawn parallel-after-A. Is there a
  worker-bandwidth reason to serialize them, or should Codex pick up E (sourcing,
  most independent) in parallel with the B→C critical path?
- **F19 default:** should the real pad-bearing board ever become the *default*
  `pcb-export` output once DRC-gated, or stay strictly opt-in behind an explicit flag
  with the preview as default? (Affects the C/T249 CLI contract.)
- **Benchmark authorship:** T243.2 wants independently-authored reference fixtures.
  Who authors them, and do we accept a small set of externally-sourced golden designs
  as fixtures under license?
