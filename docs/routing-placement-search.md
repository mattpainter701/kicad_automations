# PCB placement and routing search

The upgrade addresses two search limits: a single placement trajectory selected
before overlap repair, and a single routing attempt with no comparison against
alternatives. Implementation follows three stages: generate bounded candidates,
validate their physical constraints, then publish the best measured result.

## Placement

`PlacementConfig` adds `restarts=3` and `refinement_passes=2`. All restarts share
the existing `iterations` budget. Each restart has its own seed, cooling schedule,
and progressively smaller local moves. Final refinement tries small translations,
rotations, whole-block moves, and attractions toward electrically connected blocks.
Every accepted refinement improves the lexicographic pair `(hard defects, cost)`.
Candidate selection uses the same pair after legalization. A legalized initial
layout remains available even when every annealed candidate is worse.

Fixed components reserve space first, including fixed support parts. Movable
support parts follow owners displaced during legalization. The edge-to-edge gap
is split between courtyard envelopes, and non-orthogonal rotations use a
conservative enclosing rectangle. Fixed coordinates retain their supplied
precision; movable coordinates are evaluated at their published precision.
Unresolved or impossible constraints remain visible as review blockers.

The existing objective still balances thermal separation, connectivity, parent
affinity, edge access, compactness, and zoning. Shared-net attractions are divided
by fanout minus one to prevent a large bus overwhelming point-to-point nets.
This is heuristic placement with estimated geometry, not pad-aware PCB routing.

```sh
circuit-weaver optimize-placement design.yaml --iterations 6000 --restarts 4 --seed 7 --json
circuit-weaver placement-viewer design.yaml -o placement.html --restarts 4 --seed 7
python benchmarks/placement_search.py --output .test-tmp/placement-search.json
```

## Measured comparison

The local comparison uses full generated physical assembly inventories from
three checked-in examples, seed 7, 3,000 total annealing iterations, and the same
declared constraints. The baseline is commit `2d036c3`. HPWL is the sum of
component-center net bounding-box width plus height, excluding ground nets.

| Example | Parts | Original HPWL (mm) | Upgraded HPWL (mm) | Reduction |
|---|---:|---:|---:|---:|
| USB regulated supply | 17 | 99.11 | 92.77 | 6.4% |
| IoT sensor node | 27 | 239.24 | 228.17 | 4.6% |
| Motor controller | 10 | 55.03 | 50.25 | 8.7% |

Both versions have zero overlaps and zero declared-constraint violations in
these runs. This small corpus demonstrates these particular seeded outcomes;
it does not establish improvements for every board or predict routed length.
Refinement performs additional evaluations beyond the annealing budget and
increases runtime. Use fewer restarts/refinement passes when latency matters.

## Routing

```sh
circuit-weaver autoroute board.dsn --attempts 4 --seed 42 --timeout 600 -o selected.ses
```

The default remains one attempt. Multiple attempts require a Freerouting build
whose help advertises `-random_seed`. They use consecutive seeds (zero-based if
unspecified) and default to one optimization thread. The timeout is a shared
budget for routing attempts; capability probes and optional DSN export have
their existing separate limits. Each attempt receives the remaining time divided
by the remaining attempts, so time saved by early completion can be reused.

Each candidate must pass existing SES syntax, semantic, source correlation,
connection-statistics, and reported-clearance checks. Candidates with clearance
violations or unknown completeness are rejected. Remaining candidates are ranked
by incomplete connections, whether clearance was reported clear, via count, and
trace segment count. Unknown metrics rank after known metrics. Ties retain the
earlier candidate. A session with unreported clearance still requires review;
partial results retain their partial status.

Candidates stay in an isolated temporary directory until selection. The winner
is published atomically, losing sessions are removed, and all-attempt failure
preserves any existing output. A changing source DSN aborts publication. The
returned `search` object explains the selection and failed attempts. The final
artifact is a Specctra session that must be imported into KiCad and checked with
DRC. No fabrication readiness or controlled-impedance guarantee is inferred.

Local routing validation uses controlled router-process fixtures for selection,
timeout, cleanup, and failure behavior; real Freerouting quality improvement
requires a compatible installed router and representative real boards.
