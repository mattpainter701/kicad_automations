---
name: EDA Model Provider APIs
description: Programmatic access to KiCad symbols/footprints from DigiKey, SnapEDA, Ultra Librarian, Samacsys, EasyEDA/LCSC — API endpoints, auth, formats
type: reference
---

## DigiKey EDA Models
- DigiKey offers 15 free EDA/CAD model downloads/month via **Ultra Librarian** and **SnapEDA**
- No direct DigiKey API for EDA models; models come from UL or SnapEDA partners
- Formats: KiCad, Altium, Eagle, OrCAD, PADS, plus 3D STEP

## SnapEDA / SnapMagic Search
- API page: https://www.snapeda.com/get-api/
- Enterprise API (not free): contact sales@snapeda.com or 1-844-625-8890
- OpenAPI/Swagger docs available behind account; no public endpoint documentation
- KiCad plugin available via Plugin Manager
- Perplexity returned plausible endpoint structure but **zero citations** — treat as unverified

## Ultra Librarian
- Site: https://www.ultralibrarian.com/cad-vendors/kicad/
- Downloads KiCad-format ZIP files (symbols, footprints, 3D STEP)
- No public API; web download + Import-LIB-KiCad-Plugin CLI for automation
- Free Reader tool converts .BXL files to KiCad
- Plugin: https://github.com/Steffen-W/Import-LIB-KiCad-Plugin

## Samacsys / Component Search Engine
- Site: https://componentsearchengine.com
- Library Loader: system-tray app, watches downloads, imports into KiCad
- Backend API endpoint: `https://componentsearchengine.com/ga/model.php?partID={id}`
- Auth: HTTP Basic (credentials from componentsearchengine.com account)
- Response: ZIP file (application/x-zip) containing .kicad_sym, .pretty/, 3D models
- EPW trigger file: text format with MPN, manufacturer, source, checksum
- Unofficial cross-platform Rust implementation: https://github.com/olback/library-loader

## EasyEDA / LCSC (Best Programmatic Access)
- **Component API**: `https://easyeda.com/api/products/{lcsc_id}/components?version=6.4.19.5`
  - No auth required
  - Returns JSON with symbol, footprint, and 3D model UUIDs
- **3D Model (OBJ)**: `https://modules.easyeda.com/3dmodel/{uuid}`
- **3D Model (STEP)**: `https://modules.easyeda.com/qAxj6KHrDKw4blvCG8QJPs7Y/{uuid}`
- Headers: Accept-Encoding gzip, Accept application/json, User-Agent custom
- **easyeda2kicad** tool: `pip install easyeda2kicad` (v0.8.0)
  - Converts LCSC components to KiCad v5/v6 symbols, footprints, 3D models
  - CLI: `easyeda2kicad --full --lcsc_id=C2040`
  - GitHub: https://github.com/uPesy/easyeda2kicad.py
  - KiCad plugin variant: https://github.com/rasmushauschild/easyeda2kicad_plugin
- Caveat: Generated symbols need manual verification for accuracy

## KiCad Official Libraries
- GitLab: https://gitlab.com/kicad/libraries/kicad-symbols
- Download: clone via git or ZIP archive
- No REST API for individual symbol lookup
- Already used by circuit_weaver's `kicad_lib.py` via GitHub download + local install paths
