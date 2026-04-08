---
name: SDR 4-Channel LNA test project
description: User test project for circuit-weaver v0.17.0 validation
type: reference
---

**Location:** `I:\my_circuit\sdr_lna_4ch`

**Files:**
- `design.yaml` — project spec (4-channel LNA, BGB707 + BGS12P2L6, ADP7118 regulators)
- `bom_jlcpcb.csv` — generated BOM
- `output/` — schematic output directory

**Issues found in v0.17.0:**
1. Generated schematic named `untitled.kicad_sch` instead of `sdr_lna_4ch.kicad_sch`
2. `generate_schematic.py` written to project root (should not be in user directory)
3. No log file created in output directory
4. Stray `)` syntax error on line 273 of schematic (S-expression)

**Confirmed working:**
- BOM export to JLCPCB format
- Component lookup and risk auditing
- Schematic generation (output exists, but with naming/logging issues)
