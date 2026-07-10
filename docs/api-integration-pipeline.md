# API Integration Pipeline — Leveraging Distributors & Symbol Sources

This document describes how Circuit Weaver will coordinate datasheet, symbol, and spec fetching across multiple APIs to build a unified component knowledge base.

## Data Flow Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ USER WORKFLOW: Schematic → BOM → Specs → Placement → Routing → Export      │
└──────────────────────────────────────────────────────────────────────────────┘

  Step 1: Schematic Generation + BOM Population
  ┌────────────────────────────────────────────┐
  │ generate_artifacts(spec) + auto_source=true │
  │ Populates missing MPNs via Sprint 14        │
  └───────┬────────────────────────────────────┘
          │ Output: {ref: MPN, value, footprint, ...}
          ↓
  
  Step 2: Datasheet & Spec Harvesting (Task 94–96)
  ┌────────────────────────────────────────────────────────┐
  │ Parallel Fetchers:                                      │
  │   DigiKey API ────→ DatasheetUrl + Parameters          │
  │   LCSC jlcsearch ──→ PDF direct link (wmsc.lcsc.com)   │
  │   EasyEDA API ─────→ Symbol metadata + thermal hints   │
  │   Manufacturer ────→ SPICE models, S-parameters        │
  └───────┬────────────────────────────────────────────────┘
          │ Output: project/{datasheets,specs,spice_models,s_params}/
          │         index.json + metadata.json
          ↓
  
  Step 3: SVG Placement Export (Task 93)
  ┌────────────────────────────────────────────┐
  │ placement dict → SVG                        │
  │ User edits in Inkscape/CorelDRAW           │
  │ SVG → placement dict (parse & import)      │
  └───────┬────────────────────────────────────┘
          │ Output: design_placement.svg, updated .kicad_pcb
          ↓
  
  Step 4: Placement Optimization (Sprint 15, Task 87–89)
  ┌────────────────────────────────────────────┐
  │ Reads: specs/metadata.json (thermal data)  │
  │ Reads: specs/si_params.json (SI constraints)
  │ Multi-objective optimizer:                  │
  │   - Thermal: group hot components          │
  │   - SI: length-match DDR/USB               │
  │   - DFM: respect clearance rules           │
  │   - Cost: minimize vias/layers             │
  └───────┬────────────────────────────────────┘
          │ Output: optimized placement + constraints
          ↓
  
  Step 5: PCB Routing (Task 88 + Freerouting)
  ┌────────────────────────────────────────────┐
  │ Input: placement + SI constraints           │
  │ Freerouting or manual KiCad routing        │
  └───────┬────────────────────────────────────┘
          │ Output: routed .kicad_pcb
          ↓
  
  Step 6: Manufacturing Export
  ┌────────────────────────────────────────────┐
  │ BOM + CPL (both sides if dual-sided)       │
  │ Gerbers + Drill files                       │
  │ Panelization hints (Task 92)               │
  └────────────────────────────────────────────┘
```

## API Services & Data Provided

| API | Source | Type | Auth | Cache | Data Provided |
|-|-|-|-|-|-|
| **DigiKey** | Product Info v4 | REST | OAuth2 | 10-min token | DatasheetUrl, params, stock, pricing |
| **LCSC jlcsearch** | LCSC/JLCPCB | REST | None | User-managed | PDF link (CDN), specs, stock, pricing |
| **EasyEDA** | EasyEDA public | REST | None | 7-day disk | Symbol shapes, footprint data, metadata |
| **Mouser** | Mouser Search | REST | API key | N/A | DatasheetUrl, params, stock, pricing |
| **Manufacturer** (TI, ADI, Microchip) | Individual sites | HTML/PDF | None | User-managed | Datasheets, SPICE, S-params, app circuits |

## Implementation Order (Sprints 14–15)

### Sprint 14: Symbol/MPN Auto-Discovery (Tasks 83–86)
- **Task 83:** DigiKey API client + symbol fallback chain
- **Task 84:** Mouser API client
- **Task 85:** Symbol cache layer (persistent `~/.cache/circuit-weaver/symbols/`)
- **Task 86:** Auto-populate BOM during generation

**Output:** User runs `generate --auto-source` → all MPNs discovered automatically

### Sprint 15a: Spec Harvesting & SVG Placement (Tasks 93–96)
- **Task 93:** SVG placement bidirectional converter
- **Task 94:** Unified datasheet harvester (leverage existing APIs)
- **Task 95:** SPICE + S-parameter fetcher
- **Task 96:** Datasheet metadata parser (JSON extraction)

**Output:**
```
project/
├─ design.yaml
├─ datasheets/
│  ├─ TPS61023DRLR.pdf
│  ├─ GRM155R71C104KA88D.pdf
│  └─ index.json
├─ specs/
│  ├─ ic_thermal.json {MPN → {theta_ja, pdiss_max, tmax}}
│  ├─ passives.json {value+fp → {v_rating, tolerance, temp_coeff}}
│  ├─ si_params.json {MPN → {impedance_target, match_tol}}
│  └─ metadata.json {MPN → {pinout, status, vendor}}
├─ spice_models/
│  ├─ TPS61023DRLR.subckt
│  └─ ...
├─ s_params/
│  ├─ USB3.S4P
│  └─ ...
└─ design_placement.svg (user-editable)
```

### Sprint 15b: Placement Optimization (Tasks 87–92)
- Reads specs/ directory
- Thermal placement optimizer (uses `specs/ic_thermal.json`)
- SI constraint solver (uses `specs/si_params.json`)
- Interactive viewer or SVG refinement

**Output:** Final placement coordinates, CPL, dual-sided assembly support

## Cascading Fallbacks (No Single Point of Failure)

For datasheet download, fallback order:

```python
def get_datasheet(mpn, lcsc_pn):
    """Fetch datasheet with multiple fallback sources."""
    
    # Try 1: DigiKey API (fastest, direct PDF URLs)
    url = digikey_api.search(mpn)["DatasheetUrl"]
    if url and is_valid_pdf(fetch(url)):
        return url, "digikey"
    
    # Try 2: LCSC jlcsearch (if LCSC PN available)
    if lcsc_pn:
        url = lcsc_search(lcsc_pn)["datasheet"]["pdf"]
        if url and is_valid_pdf(fetch(url)):
            return url, "lcsc"
    
    # Try 3: EasyEDA (if LCSC part)
    if lcsc_pn:
        meta = easyeda_api.fetch(lcsc_pn)
        if meta.get("datasheet_url"):
            return meta["datasheet_url"], "easyeda"
    
    # Try 4: Mouser (fallback)
    if mouser_key:
        url = mouser_api.search(mpn)["DatasheetUrl"]
        if url and is_valid_pdf(fetch(url)):
            return url, "mouser"
    
    # Fallback: Manufacturer site (not automated, user provides)
    return None, "manual"
```

This ensures:
- **DigiKey API issue?** Falls back to LCSC (300K+ parts) → EasyEDA → Mouser
- **LCSC CDN down?** Falls back to DigiKey → Mouser → manufacturer
- **All APIs fail?** CLI tells user which parts are missing, provides mfr datasheets links

## Cache Strategy

### Symbol Cache (`~/.cache/circuit-weaver/symbols/`)
```
symbols/
├─ digikey/
│  ├─ TPS61023DRLR.json {symbol shapes, footprint name}
│  └─ ...
├─ easyeda/
│  ├─ C14663.json {symbol, footprint, metadata}
│  └─ ...
└─ index.json {MPN → (file, source, timestamp)}
```
- **TTL:** 30 days (symbols rarely change)
- **Hit rate:** 80%+ for common parts (reuse across projects)

### Datasheet Cache (`project/datasheets/`)
```
datasheets/
├─ TPS61023DRLR.pdf (from DigiKey)
├─ GRM155R71C104KA88D.pdf (from LCSC CDN)
├─ index.json {MPN → (file, source, download_timestamp, ttl_seconds)}
└─ ...
```
- **TTL:** 7 days (check for updated versions)
- **Re-sync:** `circuit-weaver spec-harvest --force` to refresh

### Metadata Cache (`project/specs/`)
```
specs/
├─ metadata.json {MPN → {extracted_timestamp, theta_ja, status, ...}}
├─ ic_thermal.json {MPN → {theta_ja_c, pdiss_max_w, tmax_c}}
├─ passives.json {value+footprint → {v_rating, tolerance, tc_ppm}}
└─ si_params.json {MPN → {impedance_target_ohm, length_match_tol_mil}}
```
- **TTL:** None (metadata is static, extracted once)
- **Regenerate:** Only if PDF updated or user requests `--extract-specs --force`

## CLI Usage Examples

### Example 1: Full Auto-Discovery → Specs → Placement

```bash
# Step 1: Scaffold design (user provides template + ref)
circuit-weaver scaffold --template buck --ref U1 --output design.yaml

# Step 2: Build BOM via patches (manual or agent-assisted)
circuit-weaver apply-patch design.yaml patch_ldo.json --output design.yaml --enrich-parts
# Discovers: LDO IC + bypass cap

# Step 3: Generate schematic, then harvest optional engineering data
circuit-weaver generate design.yaml --output out/ --auto-source --update-spec --svg-placement
circuit-weaver harvest-specs design.yaml --output out/
circuit-weaver fetch-spice design.yaml --output out/

# Step 4: Edit the generated placement SVG
# User edits out/placement.svg in Inkscape

# Step 5: Import placement into a real forward-annotated PCB
circuit-weaver import-placement out/placement.svg out/MyBoard.kicad_pcb \
  --output-pcb out/MyBoard.kicad_pcb

# Step 6: Run placement optimizer (reads specs/)
circuit-weaver optimize-placement design.yaml --strategy thermal \
  --specs-dir out/specs/ --output out/placement.json
# Reads: specs/ic_thermal.json
# Output: optimized coordinates
```

### Example 2: Specs-Only (No Placement Yet)

```bash
# Generate schematic, then download datasheets and extract specs
circuit-weaver generate design.yaml --output out/
circuit-weaver harvest-specs design.yaml --output out/

# Review what was extracted
cat out/specs/metadata.json | jq '.[] | {mpn: .id, theta_ja, status}'

# Regenerate specs if PDFs updated
circuit-weaver extract-specs out/datasheets/ --output out/specs/
```

### Example 3: Manual Placement with Constraints

```bash
# Export placement hints (current heuristic layout)
circuit-weaver generate design.yaml --output out/ --svg-placement

# Edit in Inkscape, save as design_placement_custom.svg

# Import and lock placement on the real forward-annotated PCB
circuit-weaver import-placement design_placement_custom.svg out/MyBoard.kicad_pcb \
  --output-pcb out/placement_locked.kicad_pcb

# Now optimize routing (placement is fixed)
circuit-weaver autoroute out/placement_locked.kicad_pcb \
  --output out/routed.ses
```

## Benefits of This Approach

| Benefit | How Achieved |
|-|-|
| **No manual MPN entry** | Sprint 14 auto-discovery via DigiKey/LCSC |
| **Thermal-aware placement** | Specs harvester extracts θJA → optimizer uses it |
| **SI constraints included** | Specs harvester extracts impedance targets → routing respects them |
| **Dual-sided support** | Placement + CPL generation for both sides (Task 91) |
| **Offline-capable** | Cache datasheets locally, git-track specs/ |
| **Version control friendly** | SVG + JSON are text; diffs are meaningful |
| **No proprietary tools** | Inkscape (free) for placement editing, SVG standard |
| **Reproducible** | Specs are deterministic; same BOM → same placement |
| **Extensible** | New API integrations (Digi-Key 3D models, TI reference designs, etc.) added easily |

## Known Limitations & Future Work

- **OCR for datasheet metadata:** PDF text extraction works for 80% of datasheets; some manufacturers use scanned images (require OCR + training)
- **S-parameters:** Not always available online; fallback to manual datasheet search for RF parts
- **SPICE model licensing:** Some SPICE models restrict redistribution; cache locally, don't commit to public repos
- **Interactive viewer:** SVG editing is powerful but not real-time WYSIWYG; Sprint 15 Task 90 adds live viewer if needed
- **Panelization:** Currently generates hints; actual panelization still requires KiCad manual work or external tools (Altium)

## References

- DigiKey Product Information v4: https://developer.digikey.com/documentation/51ec8ee9-4f63-45ab-8254-c6be6f94b833
- LCSC jlcsearch: https://github.com/tscircuit/tscircuit/tree/main/packages/jlcsearch
- EasyEDA API: https://easyeda.com/api/
- KiCad PCB format: https://dev-docs.kicad.org/en/file_formats/index.html
- Freerouting: https://github.com/mirage335/freerouting
