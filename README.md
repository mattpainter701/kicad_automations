# KiCad Automations — Claude Code Skills for EDA

A production-grade suite of Claude Code skills and Python scripts for KiCad schematic/PCB design, BOM management, component sourcing, fabrication, and electrical engineering analysis.

Battle-tested on complex multi-layer RF PCBs: 50+ component 6-layer designs with BGAs, multi-distributor BOM pipelines, and full pre-fab simulation chains.

---

## What's in This Repo

```
skills/
  kicad/          — Schematic, PCB, and Gerber analysis (the core analyzers)
  bom/            — BOM lifecycle: analyze, enrich, export, order
  digikey/        — DigiKey API: part search + datasheet downloads
  lcsc/           — LCSC/jlcsearch: production sourcing + JLCPCB parts
  mouser/         — Mouser API: secondary prototype sourcing
  jlcpcb/         — JLCPCB Partner API: PCB quoting + assembly ordering
  pcbway/         — PCBWay: alternative fab + assembly ordering
  ee/             — Electrical engineering reference skill

project-skills/   — Project-specific skill templates (customize per design)
  kicad_gen/      — Programmatic schematic generation
  kicad_hierarchy/ — Root schematic management
  kicad_validate/ — Cross-reference design audit
  kicad_pinmap/   — Pin-to-net mapping auditor
  kicad_pcb_place/ — PCB component placement
  sim/            — RF chain + power + PCB EM simulation
```

---

## Quick Install

```bash
# Clone
git clone https://github.com/mattpainter701/kicad_automations.git
cd kicad_automations

# Install global skills to ~/.claude/skills/
./install.sh

# Or install specific skills only
./install.sh kicad bom digikey lcsc
```

The install script copies each skill directory to `~/.claude/skills/`, where Claude Code picks them up automatically.

---

## Core Skills

### `kicad` — Schematic, PCB & Gerber Analysis

The heart of the suite. Three Python scripts that extract comprehensive structured JSON from KiCad files in a single pass.

```bash
# Full schematic analysis (BOM, nets, pin connectivity, subcircuits, ERC)
python3 skills/kicad/scripts/analyze_schematic.py design.kicad_sch

# PCB layout analysis (routing, vias, zones, DFM, thermal, crosstalk)
python3 skills/kicad/scripts/analyze_pcb.py design.kicad_pcb --proximity

# Gerber/Excellon analysis (layer ID, completeness, drill classification)
python3 skills/kicad/scripts/analyze_gerbers.py gerbers/
```

**What `analyze_schematic.py` detects:**
- Power regulators (LDO/buck/boost, Vout estimation via ~60-family lookup table)
- RC/LC filters (cutoff frequency), feedback networks, crystal circuits
- Op-amp configurations (gain), transistor circuits (load classification)
- H-bridge and 3-phase bridge circuits, ESD/TVS protection, current sense
- USB, I2C, SPI, UART, CAN bus detection
- Differential pairs (USB/LVDS/Ethernet/HDMI/PCIe/SATA/CAN/RS-485)
- PDN impedance (1 kHz–1 GHz), power budget, sequencing, sleep current

Supports KiCad 6/7/8/9/10 (`.kicad_sch`) and legacy KiCad 5 (`.sch`). Hierarchical designs parsed recursively.

### `bom` — BOM Lifecycle

```bash
# Analyze and find gaps
python3 skills/bom/scripts/bom_manager.py analyze design.kicad_sch --json

# Export tracking CSV (merge with existing, preserve user columns)
python3 skills/bom/scripts/bom_manager.py export design.kicad_sch -o bom/bom.csv

# Generate per-distributor order files (5 boards + 2 spares)
python3 skills/bom/scripts/bom_manager.py order bom/bom.csv --boards 5 --spares 2

# Write distributor PNs back to schematic symbols
echo '{"U1": {"MPN": "TPS62130ARGTR", "DigiKey": "296-TPS62130ARGTR-ND"}}' \
  | python3 skills/bom/scripts/edit_properties.py design.kicad_sch
```

### `digikey` — DigiKey Integration

Requires `DIGIKEY_CLIENT_ID` and `DIGIKEY_CLIENT_SECRET` (OAuth2 client credentials from [developer.digikey.com](https://developer.digikey.com)).

```bash
# Sync all datasheets for a KiCad project
python3 skills/digikey/scripts/sync_datasheets_digikey.py design.kicad_sch

# Download a single datasheet by MPN
python3 skills/digikey/scripts/fetch_datasheet_digikey.py --search "TPS62130" -o tps62130.pdf
```

### `lcsc` — LCSC / JLCPCB Parts

No API key required — uses the free [jlcsearch](https://jlcsearch.tscircuit.com) community API.

```bash
python3 skills/lcsc/scripts/sync_datasheets_lcsc.py design.kicad_sch
python3 skills/lcsc/scripts/fetch_datasheet_lcsc.py --search "C14663" -o datasheet.pdf
```

### `mouser` — Mouser Integration

Requires `MOUSER_SEARCH_API_KEY` from [mouser.com](https://www.mouser.com) developer portal.

```bash
python3 skills/mouser/scripts/sync_datasheets_mouser.py design.kicad_sch
```

### `jlcpcb` — JLCPCB API

Requires `JLCPCB_Accesskey` + `JLCPCB_SecretKey` (apply at [api.jlcpcb.com](https://api.jlcpcb.com)).

```bash
# PCB price quote (no gerber needed)
python3 skills/jlcpcb/scripts/jlcpcb_api.py --quote
```

### `ee` — Electrical Engineering Reference

Passive and active component calculations, power supply design, signal integrity, RF, thermal, EMC, and test & measurement — all in one reference skill. See [`skills/ee/SKILL.md`](skills/ee/SKILL.md).

---

## Project Skills (Templates)

The `project-skills/` directory contains SKILL.md templates for project-specific workflows. Copy them into your project's `.claude/skills/` and customize:

| Skill | Purpose |
|-|-|
| `kicad_gen` | Programmatic schematic generation from Python |
| `kicad_hierarchy` | Root schematic management across sub-sheets |
| `kicad_validate` | Cross-reference audit: spec vs schematic vs BOM vs layout |
| `kicad_pinmap` | IC pin-to-net mapping auditor and gap filler |
| `kicad_pcb_place` | Constraint-driven placement + Freerouting integration |
| `sim` | RF chain (scikit-rf), power (LTspice/PyLTSpice), PCB EM (openEMS) |

```bash
# Install a project skill into your project
cp -r project-skills/kicad_validate .claude/skills/
# Then edit .claude/skills/kicad_validate/SKILL.md for your project
```

---

## Credential Setup

Store API keys in `~/.config/secrets.env` (outside all git repos):

```bash
DIGIKEY_CLIENT_ID=your_client_id
DIGIKEY_CLIENT_SECRET=your_client_secret
MOUSER_SEARCH_API_KEY=your_mouser_key
JLCPCB_Accesskey=your_jlcpcb_key
JLCPCB_SecretKey=your_jlcpcb_secret
PERPLEXITY_API_KEY=pplx-xxxx   # optional, for /research skill
```

Load before running scripts:
```bash
export $(grep -v '^#' ~/.config/secrets.env | grep -v '^$' | xargs)
```

---

## Typical Workflow

```
1. Design schematic in KiCad
2. analyze_schematic.py  → structural + signal analysis JSON
3. bom_manager.py analyze → find missing MPNs, distributor PNs
4. sync_datasheets_digikey.py → download all datasheets
5. bom_manager.py export → BOM tracking CSV
6. edit_properties.py → write PNs back to schematic symbols
7. analyze_pcb.py → routing, DFM, thermal review
8. bom_manager.py order → per-distributor order CSVs
9. jlcpcb_api.py --quote → PCB price confirmation
```

---

## References

Each skill ships with detailed reference documentation:

| Reference | What It Covers |
|-|-|
| `kicad/references/schematic-analysis.md` | Deep schematic review methodology, error taxonomy |
| `kicad/references/pcb-layout-analysis.md` | Impedance, return paths, copper balance, DFM |
| `kicad/references/standards-compliance.md` | IPC-2221A, IPC-2152, IEC 60664-1 tables |
| `kicad/references/report-generation.md` | Review report template, severity definitions |
| `kicad/references/file-formats.md` | KiCad S-expression format field-by-field |
| `bom/references/ordering-and-fabrication.md` | Gerber export, CPL format, fab cost templates |
| `bom/references/part-number-conventions.md` | MPN patterns across 56+ real KiCad projects |

---

## Requirements

```
python >= 3.10
requests          # HTTP (most scripts)
playwright        # optional — headless browser fallback for protected datasheets
```

```bash
pip install requests
pip install playwright && playwright install chromium  # optional
```

---

## Related Projects

- [kicad-happy](https://github.com/aklofas/kicad-happy) — upstream of the analyzer scripts; sync for improvements
- [KiBot](https://pypi.org/project/kibot/) — CI/CD output automation (gerbers, BOM, DRC reports)
- [kicad-python (kipy)](https://github.com/atait/kicad-python) — IPC API for live KiCad session control
- [Circuit-Synth](https://github.com/circuit-synth/circuit-synth) — Python-defined circuits + AI

---

## License

MIT
