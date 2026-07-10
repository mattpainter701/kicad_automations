---
name: kicad-pcb-place
description: >
  Generate and review a constraint-driven placement plan, then apply it to an
  electrically annotated KiCad PCB. Use after Circuit Weaver generation when the
  user wants placement optimization or KiCad placement guidance. Never route the
  generated placement-preview PCB.
---

## Two-Stage Workflow

### Stage 1: Generate Placement Plan

```bash
circuit-weaver optimize-placement "${SPEC_PATH}" \
  --output "${OUTPUT_DIR}/placement.json"
circuit-weaver placement-viewer "${SPEC_PATH}" \
  --output "${OUTPUT_DIR}/placement.html"
```

Outputs a reference JSON: `{reference: {x_mm, y_mm, rotation_deg, layer}}`.
Validates all constraints before writing (edge clearance, group proximity, etc.).

### Stage 2: Apply Placement to an Electrical PCB

First open the generated root schematic in KiCad, assign footprints, and run
**Update PCB from Schematic**. Do not use the generated
`*_placement.kicad_pcb` preview here; it has no electrical pads or nets.

**Option A -- pcbnew scripting console (standalone):**
```python
# In KiCad Scripting Console (PCB Editor -> Scripting Console).
# Apply the reviewed coordinates from placement.json using the KiCad version's
# supported pcbnew API, then save to a new board and run DRC.
```

**Option B -- KiCad IPC API (live session via kipy):**
```python
from kipy import KiCad
kicad = KiCad()
board = kicad.get_board()
# Move footprints via board.update_items()
```

## Placement Constraints

Document project-specific constraints here:

| Constraint | Value | Rationale |
|-|-|-|
| Board edge clearance | 3mm min | Assembly requirement |
| BGA-to-BGA spacing | 20mm min | Thermal + rework access |
| Decoupling cap to IC | < 2mm | PDN impedance |
| Crystal isolation | 5mm from switchers | EMI |
| Connector alignment | edge-flush | Mechanical fit |

## pcbnew API Notes

```python
import pcbnew
from pathlib import Path

board_path = Path("design.kicad_pcb").resolve()
board = pcbnew.LoadBoard(str(board_path))

fp = board.FindFootprintByReference("U1")
fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(50), pcbnew.FromMM(40)))
fp.SetOrientationDegrees(0)

board.Save(r"design.kicad_pcb")
pcbnew.Refresh()
```

KiCad's Python API changes between major versions. Use the Python environment
bundled with the installed KiCad version and verify the board reloads before
replacing the original. Do not hardcode a KiCad 10 installation path.

## Freerouting Integration

```bash
# 1. Export DSN: KiCad File -> Export -> Specctra DSN
java -jar freerouting.jar -de design.dsn -do design.ses -mp 100
# 2. Import SES: KiCad File -> Import -> Specctra Session
```

Best results after: components placed with correct orientation, net classes assigned,
DRU design rules imported from fab (JLCPCB or PCBWay).

Run Freerouting only on the electrical PCB created from the schematic, never on
`*_placement.kicad_pcb`.

## Post-Placement Checklist

- [ ] All components placed (0 unplaced in status bar)
- [ ] Edge clearance rule passes (DRC)
- [ ] Courtyard overlaps = 0 (DRC)
- [ ] Decoupling caps adjacent to IC power pins
- [ ] High-speed pairs routed first (USB, DDR, high-speed clocks)
- [ ] Power traces widened per IPC-2221 current capacity
- [ ] Thermal vias under QFN/BGA exposed pads
