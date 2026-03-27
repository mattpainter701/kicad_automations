---
name: kicad_validate
description: >
  Cross-reference design audit -- validates consistency across spec, schematics,
  BOM, pin maps, and PCB layout. Catches disagreements before fabrication.
  Run after any significant design change.
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
python3 skills/kicad/scripts/analyze_schematic.py design.kicad_sch > analysis.json
python3 scripts/validate_pinmaps.py analysis.json scripts/pin_maps.py
```

Critical checks:
- Power pins (VDD, GND, VDDIO) connected to correct rails
- Reset/enable pins asserted correctly
- Clock inputs connected to clock sources

### Pass 3: Schematic vs BOM

```bash
python3 skills/bom/scripts/bom_manager.py analyze design.kicad_sch --json
```

Every component must have: MPN specified, footprint matching the MPN package,
DNP components flagged consistently.

### Pass 4: Schematic vs PCB Layout

```bash
python3 skills/kicad/scripts/analyze_pcb.py design.kicad_pcb > pcb.json
```

- Component count: schematic total minus DNP = PCB footprint count
- All schematic nets appear in PCB net list
- No unrouted nets

### Pass 5: Datasheet vs Symbol

For each IC with an MPN:
1. Download datasheet (digikey skill)
2. Verify pin numbers/names match KiCad symbol
3. Verify footprint pad numbering matches package pinout

## Running Validation

```bash
python3 scripts/validate_design.py \
  hardware/<project>/kicad/<project>.kicad_sch \
  hardware/<project>/kicad/<project>.kicad_pcb \
  --pin-maps scripts/pin_maps.py \
  --spec docs/SPEC.md
```

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
