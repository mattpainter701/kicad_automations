# KiCad Workflow Rules

These rules are the generic baseline for downstream KiCad projects using `kicad_automations` and `circuit_weaver`.

## Source of truth

- Treat YAML/Design IR as canonical when using `circuit_weaver`
- Treat generated KiCad files as derived artifacts unless the project explicitly documents manual-authoring mode
- Do not mix manual KiCad edits and generator changes without an override/merge path

## Validation

- Run structural, electrical, implementation, and presentation checks together before accepting generated output
- KiCad load/export smoke is part of the validity gate, not a cosmetic afterthought
- Do not accept unresolved symbols, footprints, or interfaces

## Review

- Findings must distinguish source defects from stale-artifact defects
- Prefer false positives over false negatives on board-killing issues
- Dense review sheets must be judged for readability, not only ERC cleanliness

## Downstream boundary

- Keep project-specific wrappers, BOMs, pin maps, symbols, footprints, and generated artifacts in the downstream project
- Keep generic skills, helpers, agents, and package code upstream in `kicad_automations`
