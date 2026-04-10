---
name: sim
description: >
  Circuit simulation workflows — SPICE simulation via ngspice, confidence scoring,
  RF chain analysis (scikit-rf), power/clock transient and AC analysis.
  Trigger on: "simulate", "run simulation", "spice", "check stability", "ripple analysis".
  Load the canonical sim skill from `project-skills/sim/SKILL.md`.
---

This is a repository-local compatibility entrypoint for the canonical simulation skill.

Immediately read and follow `project-skills/sim/SKILL.md` relative to the repo root.
Treat that file as the source of truth for simulation workflows, CLI commands, and setup.

Key CLI commands available:
- `circuit-weaver simulate design.yaml -o ./sims` — Run SPICE simulations
- `circuit-weaver confidence design.yaml --run-sims` — Full design readiness check
- `circuit-weaver fetch-spice design.yaml` — Download SPICE models from manufacturers
