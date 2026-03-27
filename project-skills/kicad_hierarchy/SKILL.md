---
name: kicad_hierarchy
description: >
  Hierarchical root schematic management -- maintains the top-level .kicad_sch
  that references all sub-sheets. Use to add/remove sheets, validate hierarchy
  structure, and regenerate the root after programmatic sheet generation.
---

## Overview

KiCad hierarchical designs use a root sheet containing only sheet references
(no symbols). Each sub-sheet is a separate `.kicad_sch` file.

## Workflow

```
1. Generate sub-sheets        -> kicad_gen skill
2. Update root sheet          -> scripts/build_root_schematic.py
3. Validate sheet filenames   -> all referenced paths must exist on disk
4. Open in KiCad              -> verify hierarchy navigator shows all sheets
5. Run ERC on hierarchy       -> kicad-cli sch erc <root>.kicad_sch
```

## Example Root Structure

```
root.kicad_sch
  power.kicad_sch
  mcu.kicad_sch
  rf_frontend.kicad_sch
  io_connectors.kicad_sch
  clocking.kicad_sch
```

## Sheet Entry Format

```lisp
(sheet (at X Y) (size W H)
  (uuid "...")
  (property "Sheetname" "Power" ...)
  (property "Sheetfile" "power.kicad_sch" ...)
  (hierarchical_label "NET_NAME" (shape input) ...)
)
```

## Validation Checklist

- [ ] All referenced `.kicad_sch` files exist on disk
- [ ] No duplicate sheet names
- [ ] Hierarchical labels match between root reference and sub-sheet definition
- [ ] Page numbers sequential
- [ ] ERC passes with 0 errors across all sheets

## Adding a New Sheet

1. Generate the new `.kicad_sch` file (via kicad_gen or manually)
2. Run `build_root_schematic.py` (or manually add the sheet entry to root)
3. Verify with ERC
4. Run "Update PCB from Schematic" in KiCad GUI to sync new nets
