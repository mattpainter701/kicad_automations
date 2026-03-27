---
name: kicad_pcb_place
description: >
  PCB component placement -- generate and apply a constraint-driven placement
  plan for KiCad PCB layouts. Covers placement strategy, pcbnew API usage,
  and Freerouting autorouter integration.
---

## Two-Stage Workflow

### Stage 1: Generate Placement Plan

```bash
python3 scripts/generate_placement.py \
  hardware/<project>/kicad/<project>.kicad_pcb \
  --output hardware/<project>/kicad/placement.json
```

Outputs a reference JSON: `{reference: {x_mm, y_mm, rotation_deg, layer}}`.
Validates all constraints before writing (edge clearance, group proximity, etc.).

### Stage 2: Apply Placement

**Option A -- pcbnew scripting console (standalone):**
```python
# In KiCad Scripting Console (PCB Editor -> Scripting Console)
import importlib, sys
sys.path.insert(0, r'path/to/project/scripts')
import apply_placement; importlib.reload(apply_placement)
apply_placement.run()
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

## pcbnew API Notes (KiCad 10)

```python
import pcbnew
board = pcbnew.LoadBoard(r"design.kicad_pcb")  # Windows: backslash required

fp = board.FindFootprintByReference("U1")
fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(50), pcbnew.FromMM(40)))
fp.SetOrientationDegrees(0)

board.Save(r"design.kicad_pcb")
pcbnew.Refresh()
```

**Windows gotcha:** `LoadBoard()` requires native backslash paths. Forward slashes return None silently.
**KiCad 10:** `IO_MGR` is removed -- use `LoadBoard(path)` directly, no plugin argument.
**KiCad 10 Python:** `C:/Program Files/KiCad/10.0/bin/pythonw.exe` -- use for pcbnew API scripts.

## Freerouting Integration

```bash
# 1. Export DSN: KiCad File -> Export -> Specctra DSN
java -jar freerouting.jar -de design.dsn -do design.ses -mp 100
# 2. Import SES: KiCad File -> Import -> Specctra Session
```

Best results after: components placed with correct orientation, net classes assigned,
DRU design rules imported from fab (JLCPCB or PCBWay).

## Post-Placement Checklist

- [ ] All components placed (0 unplaced in status bar)
- [ ] Edge clearance rule passes (DRC)
- [ ] Courtyard overlaps = 0 (DRC)
- [ ] Decoupling caps adjacent to IC power pins
- [ ] High-speed pairs routed first (USB, DDR, high-speed clocks)
- [ ] Power traces widened per IPC-2221 current capacity
- [ ] Thermal vias under QFN/BGA exposed pads
