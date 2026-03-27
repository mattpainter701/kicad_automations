---
name: jlcpcb
description: JLCPCB PCB fabrication and assembly — BOM/CPL generation, basic vs extended parts, assembly constraints, design rules, ordering workflow. Use with KiCad for JLCPCB manufacturing. Use this skill when the user mentions JLCPCB, wants to order PCBs or assembled boards, needs prototype bare PCBs and stencils, wants to know JLCPCB design rules and capabilities, or is asking about PCB manufacturing costs or turnaround times. For gerber/CPL export, stencil ordering, and BOM management, see the `bom` skill.
---

# JLCPCB — PCB Fabrication & Assembly

JLCPCB is a PCB fabrication and assembly service based in Shenzhen, China. It is a sister company to LCSC Electronics (common ownership) — they share the same parts library.

**Typical usage**: Order bare prototype PCBs + framed stencil from JLCPCB during prototyping (parts sourced separately from DigiKey/Mouser, hand-assembled in lab). For production runs (100s qty), order fully assembled boards from JLCPCB using LCSC parts. PCBWay is an alternative assembler. For component searching, see the `lcsc` skill. For BOM management, gerber/CPL export, and stencil ordering, see the `bom` skill.

## Related Skills

| Skill | Purpose |
|-------|---------|
| `kicad` | Read/analyze KiCad project files, DFM scoring against JLCPCB capabilities |
| `bom` | BOM management, gerber/CPL export, stencil ordering |
| `digikey` | Search DigiKey (prototype sourcing, primary — also preferred for datasheet downloads via API) |
| `mouser` | Search Mouser (prototype sourcing, secondary) |
| `lcsc` | Search LCSC (production sourcing — JLCPCB uses LCSC parts library) |
| `pcbway` | Alternative PCB fabrication & assembly |

## Assembly Parts Library

### Part Categories

| Category | Description | Assembly Fee |
|----------|-------------|--------------|
| **Basic** | ~698 common parts (resistors, caps, diodes, etc.) pre-loaded on pick-and-place machines | No extra fee |
| **Preferred Extended** | Frequently used extended parts | No feeder loading fee (Economic assembly) |
| **Extended** | 300k+ less common parts loaded on demand | $3 per unique extended part |

### LCSC Part Numbers

Every assembly component is identified by an **LCSC Part Number** (`Cxxxxx`, e.g., `C14663`). This is the definitive identifier for BOM matching. See the `lcsc` skill for searching parts.

### Parts Search (JLCPCB-Specific)

- Parts library: `https://jlcpcb.com/parts/componentSearch?searchTxt=<query>`
- Basic parts only: `https://jlcpcb.com/parts/basic_parts`

## BOM Format for Assembly

JLCPCB accepts CSV, XLS, or XLSX BOMs with these columns:

| Column | Required | Description |
|--------|----------|-------------|
| `Comment` / `Value` | Yes | Component value (e.g., 100nF, 10k) |
| `Designator` | Yes | Reference designators, comma-separated (e.g., C1,C2,C5) |
| `Footprint` | Yes | Package/footprint name |
| `LCSC Part #` | Recommended | LCSC part number (Cxxxxx) — guarantees exact match |

The column header for LCSC numbers must be exactly **"LCSC Part #"** or **"LCSC Part Number"** — typos cause upload failures.

### KiCad BOM Export for JLCPCB

1. In KiCad schematic editor, add an `LCSC` field to each symbol with the LCSC part number
2. Export BOM as CSV with columns: Reference, Value, Footprint, LCSC
3. Rename columns to match JLCPCB's expected format:
   - `Reference` -> `Designator`
   - `Value` -> `Comment`
   - `Footprint` -> `Footprint`
   - `LCSC` -> `LCSC Part #`

For gerber export settings, CPL format, and stencil ordering, see the `bom` skill.

## JLCPCB Partner API

Apply at `https://api.jlcpcb.com`. Access is gated — requires review based on order history and business profile. Two tiers: **Pricing** (quote only) and **Ordering** (full lifecycle, requires monthly volume).

### API Credential Setup

After approval, JLCPCB provides credentials via the developer portal at `api.jlcpcb.com`:

```bash
# Add to ~/.config/secrets.env
JLCPCB_Accesskey=your_access_key_here
JLCPCB_SecretKey=your_secret_key_here
# JLCPCB_AppID=optional_if_different_from_accesskey
```

### Authentication: JOP-HMAC-SHA256

Every request is signed with HMAC-SHA256. The signing format:

```
String-to-sign: METHOD\nURI\nTIMESTAMP\nNONCE\nBODY\n
Signature: HMAC-SHA256(SecretKey, string_to_sign).hexdigest()

Authorization: JOP-HMAC-SHA256 appid="...",accesskey="...",timestamp="...",nonce="...",signature="..."
```

- `METHOD` — uppercase HTTP method (GET, POST)
- `URI` — path portion only (e.g., `/pcb/calculate`)
- `TIMESTAMP` — Unix epoch in seconds (not milliseconds)
- `NONCE` — 32-char hex random string
- `BODY` — compact JSON body string (no spaces), empty string for GET/multipart

### Base URL

```
https://jlcpcb.com/api/overseas/openapi
```

Note: `prod-api.jlcpcb.com` is not reachable from US networks. Use the main `jlcpcb.com` domain.

### Scripts

```bash
# API client library (importable)
python3 <skill-path>/scripts/jlcpcb_api.py --probe    # Test connectivity
python3 <skill-path>/scripts/jlcpcb_api.py --quote    # Quick PCB price quote
```

The `JLCPCBClient` class can be imported:
```python
from jlcpcb_api import JLCPCBClient
client = JLCPCBClient()
result, status = client.pcb_quote(layers=2, width=100, height=80, qty=5)
```

### Endpoints

| Method | Path | Purpose | Tier |
|-|-|-|-|
| POST | `/pcb/calculate` | PCB price quote (no gerber needed) | Pricing |
| POST | `/pcb/uploadGerber` | Upload gerber ZIP (returns fileKey) | Ordering |
| POST | `/pcb/create` | Create/place PCB order | Ordering |
| POST | `/pcb/wip/get` | Query order production status | Ordering |

**Component search** uses the free `jlcsearch.tscircuit.com` API (no key needed) via the `lcsc` skill — separate from the Partner API.

### PCB Quote Parameters

```json
{
  "orderType": 1,
  "pcbParam": {
    "layer": 2,
    "width": 100.0,
    "length": 80.0,
    "qty": 5,
    "thickness": 1.6,
    "pcbColor": 1,
    "surfaceFinish": 1,
    "copperWeight": 1.0,
    "goldFinger": 0,
    "materialDetails": "<see note>",
    "panelFlag": 0,
    "differentDesign": 1
  },
  "country": "US",
  "postCode": "94102",
  "city": "San Francisco"
}
```

**Known field values:**
- `pcbColor`: 1=Green, 2=Red, 3=Yellow, 4=Blue, 5=White, 6=Black (unconfirmed)
- `surfaceFinish`: 1=HASL, 2=LeadFreeHASL, 3=ENIG (unconfirmed)
- `materialDetails`: **Not publicly documented** — requires partner docs. Values 0-14 all return `pcb_material_details_error`. Check `api.jlcpcb.com/docs/start` (behind login) for valid codes.

### Gerber Upload Flow

For the Ordering tier:
1. `POST /pcb/uploadGerber` — multipart form upload, sign with empty body
2. Response returns `fileKey` and `batchNum`
3. `POST /pcb/create` — pass `fileKey`, `batchNum`, and PCB params
4. `POST /pcb/wip/get` — poll with `orderNumber` for status

## PCB Design Rules (JLCPCB Capabilities)

### Standard PCB (1-2 layers)

| Parameter | Minimum |
|-----------|---------|
| Trace width | 0.127mm (5mil) |
| Trace spacing | 0.127mm (5mil) |
| Via diameter | 0.45mm |
| Via drill | 0.2mm |
| Annular ring | 0.125mm |
| Min hole size | 0.2mm |
| Board thickness | 0.4-2.4mm (default 1.6mm) |
| Min board size | 6x6mm |
| Max board size | 500x400mm (2-layer) |

### Multi-layer (4+ layers)

| Parameter | Minimum |
|-----------|---------|
| Trace width | 0.09mm (3.5mil) |
| Trace spacing | 0.09mm (3.5mil) |
| Via diameter | 0.25mm |
| Via drill | 0.15mm |
| Board thickness | 0.6-2.4mm |

### Importing DRU into KiCad

If you have a JLCPCB `.kicad_dru` design rules file, import it in KiCad Board Editor > Board Setup > Design Rules > Import Settings.

## Assembly Constraints

### Economic vs Standard Assembly

| Feature | Economic | Standard |
|---------|----------|----------|
| Sides | Top only | Top + Bottom |
| Component types | SMD only | SMD + through-hole |
| Min component size | 0201 | 01005 |
| Fine-pitch BGA/QFP | Down to 0.5mm pitch | Down to 0.4mm pitch |
| Turnaround | ~3-5 days | ~3-5 days |
| Extended part fee | $3 per unique part | $3 per unique part |

### General Constraints

- **Minimum order**: 5 PCBs for assembly
- **Unique parts limit**: No hard limit, but each extended part adds $3
- **Basic parts**: No extra fee, pre-loaded on machines

## Rotation Offsets

JLCPCB's pick-and-place uses different rotation conventions than KiCad for some footprints. Common offsets:

| Footprint Family | Typical Offset |
|-----------------|----------------|
| SOT-23, SOT-23-5, SOT-23-6 | +180° |
| SOT-223 | +180° |
| SOIC-8, SOIC-16 | +90° or +270° |
| QFN (all sizes) | +90° |
| SMA/SMB/SMC diodes | +180° |
| USB-C connectors | Varies — check datasheet |

To fix rotation issues:
1. Add rotation corrections directly in the CPL file before uploading (adjust the Rotation column)
2. For custom footprints, verify pin 1 orientation matches JLCPCB expectations
3. JLCPCB's review step catches major errors, but subtle 180° rotations on symmetric parts (caps, resistors) may slip through
4. After first assembly order, note any rotation corrections needed and apply them to future CPL exports

## Ordering Workflow

### Prototype Order (Bare PCB + Stencil)

1. **Export gerbers** from KiCad (see `bom` skill for export settings)
2. Upload gerbers to `https://cart.jlcpcb.com/quote` — configure layers, thickness, color, qty
3. Add a **framed stencil** to the cart (uses paste layers from your gerbers)
4. Order — PCBs and stencil typically arrive in ~1 week

### Production Order (Assembled Boards)

1. **Export gerbers** from KiCad (see `bom` skill for export settings)
2. **Export BOM** as CSV with LCSC part numbers (format above)
3. **Export CPL** (placement file) as CSV (see `bom` skill for format)
4. Upload gerbers to `https://cart.jlcpcb.com/quote` — configure layers, thickness, color, qty
5. Enable "PCB Assembly", select Economic or Standard
6. Upload BOM and CPL files
7. Review part matching — fix any unmatched parts by searching LCSC numbers
8. Confirm and order

## Tips

- **Prefer Basic parts** — no extra fee, always in stock, faster assembly
- **Check stock before ordering** — extended parts can go out of stock; use the `lcsc` skill to search
- **Panel by JLCPCB** — for small boards, let JLCPCB panelize (cheaper) vs custom panels
- **Lead-free solder** — default is leaded (HASL); select lead-free HASL or ENIG if needed
- **Impedance control** — available for multi-layer boards, specify stackup in order notes
- **Castellated holes** — supported, enable in order options
- **V-cuts and mouse bites** — supported for panel separation
- **Silkscreen minimum** — 0.8mm height, 0.15mm line width for readable text
- **Edge clearance** — keep copper >=0.3mm from board edge (0.5mm recommended)
