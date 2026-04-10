---
name: circuit-weaver
description: Master entry point for Circuit Weaver workflows. Routes to new design (wizard + research-driven IC selection + passive generation + schematic generation) or opens existing design for review/modification. Load the canonical Circuit Weaver skill from `skills/circuit-weaver/SKILL.md`.
---

This is a repository-local compatibility entrypoint for the canonical Circuit Weaver master orchestrator skill.

Immediately read and follow `skills/circuit-weaver/SKILL.md` relative to the repo root.
Treat that file as the source of truth for workflow steps, agents, CLI subcommands, and design generation logic.

Key CLI commands available:
- `circuit-weaver discover` — Auto-detect projects in current directory
- `circuit-weaver validate design.yaml --enhanced` — Run full validation with cross-reference audit
- `circuit-weaver simulate design.yaml -o ./sims` — Run SPICE simulations
- `circuit-weaver confidence design.yaml --run-sims` — Full design readiness score (0-100)
- `circuit-weaver generate design.yaml -o ./output` — Generate schematic artifacts
- `circuit-weaver log-event <dir> --type <type> --message <msg>` — Log structured events
