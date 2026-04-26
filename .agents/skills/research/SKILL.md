---
name: research
description: >
  Deep research on any topic. Parallel Perplexity web search (sonar-pro) + codebase analysis.
  Returns a structured report with cited sources and actionable recommendations.
---

This is a repository-local compatibility entrypoint for the global Research skill.

Immediately read and follow `~/.claude/skills/research/SKILL.md`.
Treat that file as the source of truth for workflow steps, scripts, credentials, and models.

The script `~/.claude/scripts/perplexity_search.py` is the backend. It loads `PERPLEXITY_API_KEY` from `~/.config/secrets.env` automatically.

### Default model: `sonar-pro`
| Variant | Trigger | Model |
|-|-|-|
| Standard | default | sonar-pro |
| Deep dive | "deep dive" / "thorough" prefix | sonar-deep-research |
