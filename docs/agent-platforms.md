# Agent Platform Support

Circuit Weaver supports four agent surfaces directly from this repo: Claude Code, Codex, OpenCode, and Kilo.

## Support Matrix

| Platform | Rules / instructions | Global skill directory | Repo-local assets |
|---|---|---|---|
| Claude Code | `CLAUDE.md` or explicit skill references | `~/.claude/skills` | Existing `.claude` compatibility path |
| Codex | `AGENTS.md` | `~/.codex/skills` | Root `AGENTS.md` plus canonical `skills/` and `project-skills/` sources |
| OpenCode | `AGENTS.md` + `opencode.json` | `~/.config/opencode/skills` | `.opencode/agents` and `.agents/skills` |
| Kilo | `AGENTS.md` + `opencode.json` | `~/.kilo/skills` | Same `.opencode/agents` and `.agents/skills` assets as OpenCode |

## Repo Files That Matter

- `AGENTS.md` is the shared repo-level instruction file for Codex, OpenCode, and Kilo.
- `opencode.json` adds shared OpenCode/Kilo instructions and keeps `rules/kicad.md` in scope.
- `.opencode/agents/` contains OpenCode/Kilo subagent definitions derived from the reviewer prompts in `agents/`.
- `.agents/skills/` contains repo-local compatibility entrypoints for the canonical global skills under `skills/`.
- `skills/` remains the source of truth for global workflow skills.
- `project-skills/` remains the source of truth for downstream project templates.

## Installer Commands

Installers require an explicit platform or explicit destination path. They do not assume a default platform.

### Install global skills everywhere

```bash
./install.sh --platform all
./install.ps1 -Platform all
```

### Install only Codex, OpenCode, and Kilo globals

```bash
./install.sh --platform codex,opencode,kilo
./install.ps1 -Platform codex,opencode,kilo
```

### Install downstream project templates into one shared open-agent directory

```bash
./install.sh --project-platform agents
./install.ps1 -ProjectPlatform agents
```

### Install downstream project templates into native Claude/OpenCode/Kilo directories

```bash
./install.sh --project-platform claude,opencode,kilo
./install.ps1 -ProjectPlatform claude,opencode,kilo
```

## Naming Rule for Project Templates

The source project templates use underscore directory names such as `kicad_gen` and `kicad_pcb_place`.

OpenCode, Kilo, and the shared `.agents/skills` convention expect kebab-case skill IDs. The installers handle this automatically:

- `kicad_gen` -> `kicad-gen`
- `kicad_hierarchy` -> `kicad-hierarchy`
- `kicad_validate` -> `kicad-validate`
- `kicad_pinmap` -> `kicad-pinmap`
- `kicad_pcb_place` -> `kicad-pcb-place`

The copied `SKILL.md` frontmatter is rewritten to match the installed kebab-case ID so these platforms can load the templates cleanly.

## Downstream Guidance

- Keep this repo upstream and generic.
- Install `project-skills/` into downstream hardware repos instead of editing the upstream templates in place.
- Keep project-specific symbol libraries, footprint libraries, BOMs, pin maps, generated KiCad artifacts, and local wrappers in the downstream repo.
