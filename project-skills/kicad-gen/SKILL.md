---
name: kicad-gen
description: >
  Generate KiCad schematics from a Circuit Weaver design.yaml or a project's own
  checked-in generator. Use for large, repetitive, or machine-synchronized designs.
  Prefer the Circuit Weaver CLI unless the project actually contains and documents
  its own generation scripts.
---

## When to Use

- BGA/QFN devices with 100+ pins -- manual placement is error-prone
- Multi-sheet designs where repetitive structure can be scripted
- Pin maps derived from datasheet tables or CSV (auto-assign ball-to-net)
- Schematic must stay synchronized with a separate spec or pin database

## Workflow

```
1. Define components and pin maps in design.yaml
2. Generate sheets   -> circuit-weaver generate
3. Require real ERC  -> circuit-weaver generate --require-kicad
4. Review in KiCad   -> open .kicad_sch files, run Update PCB from Schematic
```

Give each block a stable unique `id` and functional `section`. Circuit Weaver
preserves explicit sections as separate sheets, keeps generated support parts
with their owning block, and disambiguates sanitized sheet filenames. Read the
root and child paths from `artifact_manifest.json`; never guess `main.kicad_sch`.

## Project-Specific Setup

**Spec:** `${SPEC_PATH}`
**Output directory:** `${OUTPUT_DIR}`

If a project supplies custom scripts, record their checked-in paths here. Do not
invoke `scripts/generate_schematics.py` or `scripts/pin_maps.py` unless those
files exist in the current project.

Edit this file to record:
- Which ICs are generated vs hand-drawn
- Pin coverage per IC (total pins, mapped pins, no-connect pins)
- How to re-run generation after spec changes

## KiCad Format Rules (Critical)

- `_0_1`/`_1_1` sub-units REQUIRED -- SnapEDA flat format fails silently without them
- `lib_id` in schematic instances: bare names (no `library:` prefix)
- Power symbols: bare `lib_id` (e.g. `"VCC"` not `"power:VCC"`), `(power)` flag required
- 1.27mm grid: all pin endpoints, labels, wires must snap to `round(val / 1.27) * 1.27`
- Wire stubs REQUIRED between pins and labels -- labels at pin endpoints without wires do not reliably connect
- Version `20231120` (KiCad 8+) for per-symbol `instances` blocks

## Regeneration Protocol

```bash
# Transactionally regenerate and require the exact final hierarchy to pass a
# real installed kicad-cli ERC run.
circuit-weaver generate "${SPEC_PATH}" --output "${OUTPUT_DIR}" --require-kicad

# Then in KiCad GUI: Tools -> Update PCB from Schematic
```

Read `valid`, `kicad_verified`, `verification_status`, and `erc` from
`artifact_manifest.json`. Internal validation alone is not real KiCad
verification. If `--require-kicad` cannot run or ERC fails, generation fails;
do not claim release-quality artifacts.

Never hand-edit generated `.kicad_sch` files -- changes will be overwritten on next generation.

## Pin Coverage Tracking

| IC | Total pins | Mapped | No-connect | Coverage |
|-|-|-|-|-|
| (fill in) | | | | |

## Common Issues

**Silent connection failure:** Labels placed directly on pin endpoints without a wire stub.
Fix: generate wire + label pairs, not label-only.

**PCB import failure:** Version mismatch -- KiCad 7 expects root-level `symbol_instances`;
KiCad 8+ uses per-symbol `instances` blocks. Use `version 20231120` for KiCad 8+ compatibility.

**Symbol not recognized:** SnapEDA flat format lacks `_0_1`/`_1_1` sub-unit notation.
Rebuild the symbol from scratch using the KiCad S-expression format.
