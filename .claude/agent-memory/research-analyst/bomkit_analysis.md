---
name: bomkit repo analysis
description: lamb356/bomkit — KiCad BOM/CPL export plugin targeting JLCPCB, architecture and overlap with circuit_weaver
type: reference
---

## bomkit (github.com/lamb356/bomkit)

**Created:** 2026-04-03. MIT license. Python-only. KiCad 9/10 compatible.
**Status:** v0.1.0, 15 commits, single-day build. Only bomkit-fab is implemented; dashboard and parts-server are empty `.gitkeep` stubs.

### What it does
- KiCad pcbnew ActionPlugin: reads loaded PCB, resolves LCSC PNs from field aliases, applies JLCPCB rotation offsets, exports BOM + CPL CSVs.
- JLCPCB part classifier (basic/preferred-extended/extended) from a CSV parts DB.
- Cost estimator: counts extended loading fees ($3/unique extended part).
- wxPython dialog: sortable/filterable parts table, LCSC link on double-click.

### Architecture (bomkit-fab/)
- `sexp_parser.py` — standalone S-expr tokenizer+parser for `.kicad_pcb` files
- `board_adapter.py` — `ComponentData` dataclass, dual loader: pcbnew API or file parse
- `field_resolver.py` — alias normalization for LCSC (8 aliases), MPN (13), manufacturer (9)
- `bom_exporter.py` — groups by value/footprint/LCSC, chunks designators at 200, CSV output
- `cpl_exporter.py` — placement CSV with rotation correction and bottom-layer mirroring
- `rotations.py` — regex-based rotation offset DB with project-level overrides
- `cost_estimator.py` — JLCPCB loading fee calculation from classifier output
- `jlcpcb_classifier.py` — loads JLCPCB parts CSV, classifies by LCSC PN
- `plugin.py` — pcbnew.ActionPlugin registration
- `ui/` — wxPython dialog + parts table (mock fallback when wx unavailable)

### What it does NOT do
- No distributor API search (DigiKey, Mouser, LCSC) — purely offline field resolution
- No datasheet fetching
- No schematic analysis (PCB-only)
- No BOM diffing, stock checking, or cost optimization beyond loading fees
- No part substitution or lifecycle checking
- bomkit-dashboard and bomkit-parts are vaporware (empty dirs)

### Overlap with circuit_weaver
- Field aliasing pattern overlaps with circuit_weaver's `ComponentDef` fields (`lcsc_pn`, `digikey_pn`)
- S-expr parser is a simpler version of what the kicad skill's `analyze_pcb.py` does
- Rotation offset DB is useful reference data; circuit_weaver doesn't have this yet
- JLCPCB classifier logic could inform circuit_weaver's future assembly cost estimation

### Key technical details
- No external dependencies beyond stdlib + wxPython (for UI only)
- pytest test suite: 8 test files, integration tests with fixture `.kicad_pcb`
- ComponentData: reference, value, footprint, pos_x/y_mm, rotation_deg, layer, fields dict, is_dnp, exclude_from_bom, exclude_from_board
