# Circuit Weaver Presentation Parity Plan

## Goal

Bring the generic `circuit_weaver` generator up to the readability and review quality we reached in the Varta downstream flow, without baking Varta-specific assumptions into the engine.

The target is:

- generic samples should render cleanly out of the box
- support passives should use deliberate motifs instead of noisy point-to-point wiring
- dense review sheets should default to readable spacing
- generated review schematics should be about 90% presentation-complete before any manual KiCad polish

## Current State

The extracted engine already contains most of the generic rendering machinery:

- review passive symbols: `R_Review`, `C_Review`, `L_Review`
- denser sheet spacing and larger multi-column symbol gutters
- topology-aware local routing (`topology_local`)
- explicit interface handling
- review audits and SVG export smoke
- richer root-sheet previews and explanation blocks

The remaining gap is mostly **adoption**, not missing primitives.

## What Is Still Missing

### 1. Template coverage gap

Some generic templates still emit plain passives instead of opting into the cleaner presentation modes.

Concrete examples:

- `src/circuit_weaver/subcircuits/ldo.py`
  - input/output caps are still plain `BypassCap(...)`
- `src/circuit_weaver/subcircuits/usb.py`
  - many HF/bulk decoupling caps are still plain `BypassCap(...)`
  - only special cases like `RBIAS` / `PLLFILT` are already `presentation="topology_local"`
- `src/circuit_weaver/component_db.py`
  - built-in `USB-C-PWR` CC pull-down resistors still use generic strap rendering

### 2. Generic sample path does not force a review preset

The MVP/CLI path generates from templates with default rendering behavior, but does not currently apply a stronger review-oriented presentation preset for sample/demo output.

This means:

- samples only look as good as the template metadata they explicitly declare
- Varta-grade finishing behavior is not guaranteed in fresh standalone demos

### 3. Motif-level renderers are incomplete

We still need first-class renderers for recurring patterns:

- decoupling banks
- pull-up / pull-down ladder banks
- compact LDO support clusters
- USB connector + CC network blocks
- small regulator sidecars and bias networks

### 4. QA coverage is not sample-first enough

We already have engine-level presentation checks, but sample/demo generation should also fail when:

- support clusters are too tight
- repeated labels make local motifs unreadable
- review samples regress to messy diagonal wiring

## Design Principles

1. Keep the engine generic.
   - No Varta-specific names, sheet assumptions, or per-project hacks.

2. Preserve valid circuits first.
   - Presentation cleanup must never remove required electrical intent.

3. Encode readability as policy and metadata.
   - Avoid one-off post-processing.

4. Prefer motif renderers over increasingly clever generic routing.
   - `decoupling cap != generic 2-pin passive`
   - `strap ladder != repeated loose resistor`

5. Sample output is a product surface.
   - The sample gallery must show off the generator, not expose unfinished defaults.

## Milestones

### Milestone 1: Template Parity

Bring built-in templates onto the generic presentation system already available in the engine.

Scope:

- `src/circuit_weaver/subcircuits/ldo.py`
  - opt input/output caps into decoupling-aware presentation
- `src/circuit_weaver/subcircuits/usb.py`
  - upgrade generic HF/bulk decoupling to review-aware / topology-aware modes
  - upgrade USB power and bias motifs
- `src/circuit_weaver/component_db.py`
  - upgrade `USB-C-PWR` CC pull-downs from generic straps to a dedicated presentation path

Acceptance:

- `usb_regulated_supply` and `led_power_indicator` no longer show diagonal loose-passive clutter around USB-C and LDO support parts
- repeated support caps render as deliberate clusters, not scattered generic passives

### Milestone 2: Review Preset for Standalone Use

Add a generic presentation preset for sample/demo and human review output.

Scope:

- add a review-oriented presentation preset surfaced through the CLI/MVP layer
- allow project-level opt-in from canonical specs
- make sample generation use this preset by default

Candidate interface:

- `presentation_profile: default | review`
- or an explicit `presentation_wiring_policy` expansion at project level

Files:

- `src/circuit_weaver/mvp.py`
- `src/circuit_weaver/generator.py`
- sample generation scripts/docs

Acceptance:

- fresh sample generation uses the cleaner review posture without requiring custom per-sample hacks

### Milestone 3: Motif Renderers

Add proper renderers for the most common noisy support patterns.

Scope:

- decoupling bank renderer
  - vertical caps
  - shared rail spine
  - shared ground spine / symbol row
  - deduplicated labels inside the cluster
- strap ladder renderer
  - aligned resistor column
  - common breakout points
  - cleaner label lanes
- compact LDO / small-power support block renderer
  - input cap, output cap, enable net, rail label spacing handled as a unit

Files:

- `src/circuit_weaver/generator.py`
- `src/circuit_weaver/placer.py`
- `src/circuit_weaver/primitives.py`

Acceptance:

- sample support clusters read like schematic motifs, not auto-routed passives

### Milestone 4: Sample and QA Parity

Make the sample suite act as a presentation regression corpus.

Scope:

- add sample-specific presentation tests
- add clutter metrics for support clusters and repeated labels
- add SVG/image smoke checks for sample outputs
- add assertions against the exact problem samples now show

Files:

- `tests/`
- sample generation harness

Acceptance:

- `usb_regulated_supply`
- `led_power_indicator`
- `iot_sensor_node`

all pass presentation QA without manual fixes

### Milestone 5: Product Polish

Reflect the parity work in docs and examples.

Scope:

- refresh sample screenshots
- update README workflow/examples to show cleaner outputs
- explain review vs manufacturing handoff expectations

Acceptance:

- GitHub landing page and sample outputs agree on actual product quality

## Recommended Execution Order

1. Milestone 1: template parity
2. Milestone 2: review preset
3. Milestone 3: motif renderers
4. Milestone 4: sample QA parity
5. Milestone 5: docs/screenshots refresh

That order gives the biggest visible improvement quickly while keeping the engine generic.

## Completion Status

All five milestones implemented. 32 tests passing.

### Work Item A: LDO cleanup -- DONE

- LDO input/output bypass caps now emit `presentation=”topology_local”` (`subcircuits/ldo.py`)
- Default `BypassCap.presentation` changed from `”inherit”` to `”topology_local”` so all built-in ICs benefit automatically

### Work Item B: USB connector cleanup -- DONE

- `USB-C-PWR` CC pull-down straps now use `role=”termination”, presentation=”topology_local”` (`component_db.py`)
- Default `StrapConfig.presentation` changed from `”inherit”` to `”topology_local”`

### Work Item C: USB template cleanup -- DONE

- USB controller HF/bulk decoupling caps: `presentation=”topology_local”` (`subcircuits/usb.py`)
- USB controller boot straps: `role=”boot_strap”, presentation=”topology_local”`
- USB hub HF/bulk caps: `presentation=”topology_local”`
- USB hub reset pull-up: `role=”pull_up”, presentation=”topology_local”`
- RBIAS and PLLFILT were already `topology_local` (unchanged)

### Work Item D: Review profile -- DONE

- Added `presentation_profile` metadata key to `DesignIR` (`design_ir.py`): `default | review`
- `review` profile activates `PresentationWiringPolicy(support_passives=”topology_local”)` at generation time (`mvp.py`)
- CLI flag: `--presentation-profile review` on the `generate` subcommand
- YAML spec key: `presentation_profile: review`

### Work Item E: Sample regression suite -- DONE

- 25 new tests in `tests/test_presentation.py` covering:
  - LDO template caps use `topology_local` (all IC variants)
  - USB controller/hub caps and straps use `topology_local`
  - USB-C-PWR CC pull-downs use `topology_local`
  - Review profile metadata round-trips correctly, invalid profiles rejected
  - All three samples (`usb_regulated_supply`, `led_power_indicator`, `iot_sensor_node`) validate cleanly
  - All three samples compile with no `inherit` bypass caps
  - Clutter metric: no IC has >8 unresolved-presentation passives
  - End-to-end artifact generation for all three samples

### Additional: Motif renderers -- DONE

- `_apply_topology_decoupling_bank()`: stacks 2+ decoupling caps sharing a rail into a vertical bank with shared rail/ground labels (`placer.py`)
- `_apply_topology_strap_ladder()`: aligns 2+ straps sharing a rail into a vertical column with shared rail anchor (`placer.py`)
- Dispatch chain: buck cluster -> decoupling bank -> strap ladder -> sidecar (fallback)

## Definition of Done

The generic engine is considered “on par” when:

- [x] sample schematics no longer show obvious messy support-passive wiring
- [x] sample SVGs look close to the current Varta review quality for comparable motifs
- [x] the same parity is achieved through generic template metadata and policies, not project hacks
- [x] sample generation remains deterministic and validation-clean
- [ ] docs/screenshots reflect the improved output (requires regenerating sample PNGs)
