---
name: kicad-validate
description: >
  Cross-reference design audit -- validates consistency across spec, schematics,
  BOM, pin maps, and PCB layout. Catches disagreements before fabrication.
  Run after any significant design change.
---

## Auto-Detection

Before running validation, discover existing projects in the current directory:

```bash
python -m circuit_weaver discover --json
```

If projects are found, use the detected paths for schematic and PCB files
instead of asking the user for paths. Select the most recently modified project
by default, or ask the user to choose if multiple projects exist.

For an unmanaged KiCad project, PCB, Gerber/drill directory, or ZIP, establish
durable non-destructive state and run every applicable bundled analyzer:

```bash
circuit-weaver import-design "${SOURCE_PATH}" --analyze
circuit-weaver status "${PROJECT_ROOT}"
```

Review `.circuit-weaver/analysis/index.json`. Reuse valid cached evidence; run
`analyze-design "${PROJECT_ROOT}" --force` only for an intentional rerun.

---

## Audit Passes

Run all passes after any significant design change.

### Pass 1: Spec vs Schematic

Verify every requirement in the design spec has a corresponding net or component.

- Power rails: all specified voltages present as named nets
- Required interfaces: USB, Ethernet, JTAG -- verify connector and IC present
- IO counts: verify pin counts match spec

### Pass 2: Pin Map vs Schematic

For each programmatically mapped IC, verify the schematic matches the pin map.

```bash
circuit-weaver validate "${SPEC_PATH}" --enhanced --verbose
```

If the project has a separate pin-map source of truth, compare it with the
schematic analysis explicitly. Do not invoke `scripts/validate_pinmaps.py`
unless that project-specific script actually exists.

Critical checks:
- Power pins (VDD, GND, VDDIO) connected to correct rails
- Reset/enable pins asserted correctly
- Clock inputs connected to clock sources

### Pass 3: Schematic vs BOM

Use the schematic analysis result registered in
`.circuit-weaver/analysis/index.json`, then reconcile its references and
footprints with `assembly_manifest.json` when the latter exists.

Every component must have: MPN specified, footprint matching the MPN package,
DNP components flagged consistently.

### Pass 4: Schematic vs PCB Layout

Use the registered PCB analysis result from
`.circuit-weaver/analysis/index.json`. The static analyzer does not replace a
real KiCad DRC run.

- Component count: schematic total minus DNP = PCB footprint count
- All schematic nets appear in PCB net list
- No unrouted nets

### Pass 5: Datasheet vs Symbol

For each IC with an MPN:
1. Download datasheet (digikey skill)
2. Verify pin numbers/names match KiCad symbol
3. Verify footprint pad numbering matches package pinout

## Running Validation

### Quick (standard validation only)
```bash
python -m circuit_weaver validate design.yaml
```

### Enhanced (with cross-reference audit, thermal, SI, power budget)
```bash
python -m circuit_weaver validate design.yaml --enhanced --verbose
```

### Full audit with scoring
```bash
python -m circuit_weaver validate design.yaml --enhanced --detailed-score --verbose
```

### Release-quality final schematic gate

```bash
circuit-weaver generate design.yaml --output output --require-kicad
```

Internal validation is not real KiCad verification. For a final generated
design, require `artifact_manifest.json` to report `kicad_verified: true` and
`verification_status: verified`. For imported native boards, run KiCad ERC/DRC
on the actual project in addition to the bundled static analysis.

## Reporting

Document findings in `hardware/<project>/review/validate_<date>.md`:

```markdown
## Validation -- YYYY-MM-DD

### Pass 1: PASS / FAIL (N issues)
### Pass 2: PASS / FAIL (N issues)
### Pass 3: PASS / FAIL (N issues)
### Pass 4: PASS / FAIL (N issues)
### Pass 5: PASS / FAIL (N issues)

### Issues Found
- [CRITICAL] description
- [WARNING] description
```
