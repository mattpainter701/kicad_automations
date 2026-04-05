---
name: kicad_jlcimport architecture
description: Full architecture of jvanderberg/kicad_jlcimport — EasyEDA to KiCad conversion pipeline, API endpoints, module structure, data flow, limitations
type: reference
---

## Overview
KiCad plugin (v1.6.0, MIT) importing symbols, footprints, and 3D models from JLCPCB/LCSC/EasyEDA into KiCad 8/9/10 libraries. Python 3.8+, zero external deps for the plugin (wxPython for GUI, textual for TUI are optional).

## Repository
- GitHub: https://github.com/jvanderberg/kicad_jlcimport
- 204 commits, 36 releases, 51 stars, 99.5% Python
- Author: jvanderberg

## API Endpoints (no auth required)
- Component UUIDs: `https://easyeda.com/api/products/{lcsc_id}/svgs`
- Component data: `https://easyeda.com/api/components/{uuid}`
- 3D model STEP: `https://modules.easyeda.com/qAxj6KHrDKw4blvCG8QJPs7Y/{uuid}`
- 3D model OBJ/WRL: `https://easyeda.com/analyzer/api/3dmodel/{uuid}`
- JLCPCB search: `https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList`
- Chinese search: `https://so.szlcsc.com/query/product`

## Conversion Pipeline
1. `fetch_full_component(lcsc_id)` -> fetches UUIDs, then symbol + footprint data from EasyEDA API
2. `parse_footprint_shapes(shapes, ox, oy)` -> EasyEDA tilde-delimited strings to EEFootprint dataclass
3. `parse_symbol_shapes(shapes, ox, oy)` -> EasyEDA strings to EESymbol dataclass
4. `write_footprint(footprint, name, ...)` -> EEFootprint to .kicad_mod S-expression string
5. `write_symbol(symbol, name, ...)` -> EESymbol to .kicad_sym S-expression string
6. `download_step(uuid)` + `download_wrl_source(uuid)` -> 3D model files
7. `convert_to_vrml(obj_source)` -> EasyEDA OBJ format to VRML 2.0
8. `save_models()` -> writes .step and .wrl files

## Key Data Structures (ee_types.py)
- EEPad: shape, position, dimensions, layer, drill, rotation, polygon_points
- EETrack: width, layer, points list
- EEArc: start/end, radii, SVG arc flags
- EEPin: electrical type, name, number, position, rotation, length, visibility
- EESymbol: rectangles, circles, pins, polylines, arcs, texts
- EEFootprint: pads, tracks, circles, arcs, regions, holes, model

## EasyEDA Shape Format
- Tilde-delimited strings (e.g., "PAD~...~...~...")
- First field = shape type (PAD, TRACK, ARC, CIRCLE, HOLE, SOLIDREGION, RECT, SVGNODE, etc.)
- Coordinates in 10-mil units, converted via factor 3.937 to mm
- Layer mapping: EasyEDA layer numbers to KiCad layer names (1->F.Cu, 2->B.Cu, 3->F.SilkS, etc.)
- SVG path syntax for arcs and polygons

## Module Structure
```
src/kicad_jlcimport/
  __init__.py          - Plugin registration
  plugin.py            - KiCad pcbnew plugin interface
  importer.py          - Core import_component() orchestrator
  cli.py               - CLI (search + import commands)
  dialog.py            - wxPython metadata editing dialog
  categories.py        - JLCPCB part category definitions
  gui_entry.py         - Standalone GUI entry
  tui_entry.py         - TUI entry (textual library)
  easyeda/
    api.py             - HTTP client, EasyEDA/JLCPCB/SZLCSC APIs, DNS caching, SSL handling
    parser.py          - Shape string parser (tilde-delimited to dataclasses)
    ee_types.py        - 11 dataclasses for intermediate representation
    cacerts.pem        - Bundled CA certificates
    fetch_cacerts.py   - CA cert updater
  kicad/
    symbol_writer.py   - EESymbol to .kicad_sym S-expression
    footprint_writer.py - EEFootprint to .kicad_mod S-expression
    library.py         - Lib structure, lib-table management, footprint matching
    model3d.py         - OBJ to VRML conversion, offset/rotation computation
    version.py         - KiCad 8/9/10 version constants and format stamps
    _format.py         - S-expression escaping, float formatting, UUID generation
```

## Limitations & Known Issues
- Open issue #83: imported footprints don't snap to grid
- Closed #81: redundant pins in symbols
- Closed #71: only parts of symbols imported (multi-unit handling)
- Closed #84: search results include parts without EasyEDA data
- 3D model offset calculation uses heuristic spurious-offset detection (can misalign)
- Generated symbols need manual verification (pin types, accuracy)
- Multi-unit symbols: entry 0 is package overview (skipped), real units start at index 1
- No support for KiCad 7 or earlier
- Footprint matching uses scoring algorithm (family, pin count, dims, pitch) with tolerance
