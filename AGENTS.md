# Circuit Weaver Agent Guide

Circuit Weaver has two layers:

- `src/circuit_weaver/` is the Python engine for canonical design IR, validation, patching, and KiCad artifact generation.
- `skills/`, `project-skills/`, `agents/`, and `rules/` are the workflow layer used by agentic coding tools.

## Platform Map

| Platform | Primary repo entrypoints |
|---|---|
| Claude Code | `.claude/skills` compatibility path plus installer targets |
| Codex | `AGENTS.md` plus global installs to `~/.codex/skills` |
| OpenCode | `AGENTS.md`, `opencode.json`, `.opencode/agents`, and `.agents/skills` |
| Kilo | Same repo entrypoints as OpenCode |

Installers do not assume a default platform. Always pass an explicit platform flag or explicit destination path.

## Core Commands

- Lint: `python -m ruff check src tests`
- Test: `python -m pytest tests -q`
- Validate example design: `circuit-weaver validate src/circuit_weaver/examples/iot_sensor.yaml`
- Enhanced validation: `circuit-weaver validate design.yaml --enhanced --verbose`
- Generate example artifacts: `circuit-weaver generate src/circuit_weaver/examples/iot_sensor.yaml --output out/iot_sensor`
- Confidence report: `circuit-weaver confidence design.yaml --run-sims -o report.html`
- Simulate: `circuit-weaver simulate design.yaml -o ./sims`
- Discover projects: `circuit-weaver discover --json`
- Log event: `circuit-weaver log-event ./project --type scoring --message "Review done"`

## Workflow Assets

- Canonical global skills live in `skills/<name>/SKILL.md`.
- Canonical project-skill templates live in `project-skills/<name>/SKILL.md`. These are copied into downstream repos by `install.sh` or `install.ps1`.
- OpenCode/Kilo compatibility shims live in `.agents/skills/<name>/SKILL.md`. When one of these shims is selected, immediately read the canonical file it points to and treat that file as the source of truth.
- OpenCode/Kilo subagent definitions live in `.opencode/agents/`. The repo also keeps human-readable prompt copies in `agents/`.

## Rules

- When editing workflow assets, installers, or cross-agent documentation, load `rules/kicad.md`.
- Keep upstream generic. Project-specific wrappers, BOMs, pin maps, symbol libraries, footprint libraries, generated KiCad artifacts, and local integration tests belong downstream.
- Keep README/install docs synchronized with the actual installer target lists and supported skill directories.

## Documentation Sync

- If you add or rename a skill, update `install.sh`, `install.ps1`, `README.md`, and `docs/agent-platforms.md` together.
- OpenCode/Kilo project skill directories require kebab-case skill IDs. Source templates under `project-skills/` keep underscore directory names; installer targets for `.opencode/skills`, `.kilo/skills`, and `.agents/skills` convert those names on copy.
