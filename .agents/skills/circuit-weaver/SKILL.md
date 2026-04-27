---
name: circuit-weaver
description: Master entry point for Circuit Weaver workflows. Routes to new design (wizard + research-driven IC selection + passive generation + schematic generation) or opens existing design for review/modification. Load the canonical Circuit Weaver skill from `skills/circuit-weaver/SKILL.md`.
---

This is a repository-local compatibility entrypoint for the canonical Circuit Weaver master orchestrator skill.

Immediately read and follow `skills/circuit-weaver/SKILL.md` relative to the repo root.
Treat that file as the source of truth for workflow steps, agents, CLI subcommands, and design generation logic.

Do NOT run all CLI commands at once. The canonical skill places each command at a specific workflow step — follow the step-by-step instructions, not a flat list.
