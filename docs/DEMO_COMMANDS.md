# Circuit Weaver CLI Demo — Command Sequence

This document shows the CLI workflow from initial design to production-ready output.
All commands are executable and demonstrate the full design pipeline.

## Quick Start

```bash
# Install Circuit Weaver
pip install -e .

# Run through the demo sequence (see below)
cd demo/  # or create a fresh directory
```

## Demo Sequence

### 1. List Available Templates

```bash
circuit-weaver list-templates
```

Shows all 30 built-in circuit templates with descriptions and key parameters.

### 2. Scaffold a Battery Charger Design

Create a starter project with a buck converter template:

```bash
mkdir -p demo && cd demo
circuit-weaver scaffold --template battery_charger --ref U1 --output design.yaml
```

This generates `design.yaml` with a base buck converter (TP4056 charger circuit).

### 3. Add a Linear Regulator Block (Optional)

Create a patch to add a 3.3V LDO:

```bash
cat > patch_ldo.json <<'PATCH'
{
  "upsert_blocks": [
    {
      "id": "U2_ldo",
      "section": "power",
      "kind": "template",
      "template_type": "ldo",
      "ref": "U2",
      "params": {
        "vin": 5.0,
        "vout": 3.3,
        "vin_net": "VBUS",
        "rail_name": "VDD_3P3"
      }
    }
  ]
}
PATCH

circuit-weaver apply-patch design.yaml patch_ldo.json --output design.yaml
```

Inspect the updated `design.yaml` to see the new LDO block added alongside the buck converter.

### 4. Validate the Specification

```bash
circuit-weaver validate design.yaml
```

Runs structural, electrical, and implementation checks. Reports any issues:
- Floating pins
- Power domain conflicts
- Bus completeness (I2C pull-ups, SPI CS lines)
- Decoupling requirements

### 5. Generate Schematic & PCB Layout Files

```bash
circuit-weaver generate design.yaml --output ./output --no-svg
```

Creates:
- `.kicad_sch` schematic files (top-level + functional sheets)
- `.kicad_pcb` PCB with initial placement
- `placer_hints.json` for layout guidance
- `design_report.md` with validation summary

### 6. Estimate Component Costs

```bash
circuit-weaver cost-bom design.yaml --qty 1,10,100,1000
```

Queries LCSC pricing for all components and shows:
- Unit cost at each quantity tier
- Extended cost (unit × qty × board qty)
- Total project cost across qty breaks

Use this to identify optimal production volume and price breakpoints.

### 7. Export for JLCPCB Assembly (Optional)

If you want to order the board from JLCPCB:

```bash
circuit-weaver export-jlcpcb design.yaml -o ./jlcpcb
```

Generates:
- `jlcpcb/bom_jlcpcb.csv` — BOM with LCSC part numbers
- `jlcpcb/cpl_jlcpcb.csv` — Component placement file
- Ready to upload to JLCPCB's assembly service

### 8. Export Gerbers for Bare PCB (Optional)

```bash
circuit-weaver export-gerbers output/YourBoard.kicad_pcb -o ./gerbers
```

Creates manufacturing-ready Gerber files for custom fab shops or local fabrication.

### 9. Optional: Autoroute with Freerouting

If you have Freerouting installed:

```bash
# Install Freerouting (macOS)
brew install freerouting

# Or download from: https://github.com/mirage335/freerouting/releases
```

Then autoroute the PCB:

```bash
circuit-weaver autoroute output/YourBoard.kicad_pcb -o routed.kicad_pcb
```

Routes signal nets automatically. Simple circuits route 100%; complex circuits ~90%.

## Recording the Demo with Asciinema (Optional)

To record this workflow as a terminal recording:

```bash
# Install asciinema (not a Circuit Weaver dependency)
pip install asciinema

# Record a session
asciinema rec demo.cast

# Paste the commands from the demo sequence above
# Press Ctrl+D to finish recording

# Play back the recording
asciinema play demo.cast

# Share the recording (text file, ~1-2 KB)
# Can be viewed at: https://asciinema.org/
cat demo.cast | wc -c
```

Asciinema records terminal sessions as plain-text `.cast` files — no video encoding, no large MP4 files, just text and timing data.

## Output Files

After running the full sequence, your demo directory looks like:

```
demo/
├── design.yaml                    # Specification (YAML)
├── patch_ldo.json                 # Optional patch to add LDO
├── output/
│   ├── BatteryCharger.kicad_sch   # Schematic files
│   ├── BatteryCharger.kicad_pcb   # PCB layout
│   └── placer_hints.json          # Placement guidance
├── jlcpcb/
│   ├── bom_jlcpcb.csv             # JLCPCB assembly BOM
│   └── cpl_jlcpcb.csv             # JLCPCB placement file
├── gerbers/                       # Gerber files (if exported)
├── routed.kicad_pcb               # Autorouted PCB (if Freerouting available)
└── demo.cast                      # Terminal recording (if asciinema used)
```

## What This Demonstrates

1. **Scaffolding** — start with a template, don't write YAML from scratch
2. **Incremental design** — add blocks with `apply-patch`, see changes accumulate
3. **Validation** — automated checks before layout (catch mistakes early)
4. **Generation** — from YAML spec → KiCad files in one command
5. **Costing** — see price breakpoints across quantity tiers
6. **Manufacturing** — export in correct formats for JLCPCB or custom fabs
7. **Automation** — Freerouting routes the PCB with one command
8. **Documentation** — all files are git-trackable (YAML, CSV, KiCad formats)

## Next Steps

After the demo:

1. **Review the schematic in KiCad** — open `.kicad_sch`, verify nets and components
2. **Adjust PCB placement** — use `placer_hints.json` as guidance, route manually in KiCad
3. **DFM check** — use `circuit-weaver kicad-drc output/*.kicad_pcb` for design rule violations
4. **Order PCBs** — upload Gerbers to your fab (JLCPCB, PCBWay, local fab)
5. **Order assembly** — upload BOM + CPL to JLCPCB if using their assembly service
6. **Iterate** — save your design YAML, update for rev2, re-run pipeline

## Tips

- **Commit your design.yaml to git** — it's your source of truth
- **Use `--json` flags for machine parsing** — scripts can consume JSON output
- **Save YAML specs across revisions** — branch for rev2 experiments
- **Validate early, validate often** — catch issues before PCB layout
- **Read the placer hints** — they guide manual routing decisions

For full documentation, see `docs/user_workflow.md`.
