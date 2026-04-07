# Zigbee/BT Humidistat — Demo Design

A compact IoT humidity sensor with USB-C charging, 3.3V LDO, USB-UART bridge, and I2C sensor bus. Demonstrates the full Circuit Weaver pipeline from YAML spec to manufacturing-ready outputs.

## Design Blocks

| Ref | Template | IC | Purpose |
|-|-|-|-|
| U1 | ldo | AP2112K-3.3TRG1 | 5V USB -> 3.3V regulated supply |
| U2 | usb_controller | CH340G | USB-UART bridge for programming |
| U3 | i2c_bus | PULLUPS_ONLY | I2C pull-ups for SHT40 sensor |

## Run the Demo

```bash
# 1. Generate KiCad schematic + PCB placement
circuit-weaver generate zigbee_humidistat.yaml --output ./output --no-svg --no-require-valid

# 2. Estimate component costs at volume
circuit-weaver cost-bom zigbee_humidistat.yaml --qty 1,10,100

# 3. Check signal integrity constraints
circuit-weaver si-constraints zigbee_humidistat.yaml

# 4. Thermal analysis
circuit-weaver thermal-analysis zigbee_humidistat.yaml

# 5. Optimize component placement
circuit-weaver optimize-placement zigbee_humidistat.yaml --iterations 1000 --seed 42

# 6. Interactive placement viewer
circuit-weaver placement-viewer zigbee_humidistat.yaml --output output/viewer.html

# 7. Panelization hints (50x40mm board, 100 qty)
circuit-weaver panelize --board-width 50 --board-height 40 --qty 100

# 8. Generate 3D-printable enclosure
circuit-weaver design-enclosure --board-width 50 --board-height 40 --component-height 10 --output output/enclosure.scad

# 9. Export for JLCPCB assembly
circuit-weaver export-jlcpcb zigbee_humidistat.yaml --output output/jlcpcb
```

## Output Files

```
output/
  main.kicad_sch                  # KiCad schematic
  Zigbee_Humidistat_placement.kicad_pcb  # PCB with initial placement
  Zigbee_Humidistat_report.md     # Design report
  canonical_spec.yaml             # Normalized spec
  design_ir.json                  # Design intermediate representation
  viewer.html                     # Interactive placement viewer
  enclosure.scad                  # OpenSCAD enclosure (3D printable)
  jlcpcb/
    bom_jlcpcb.csv               # JLCPCB assembly BOM
    cpl_jlcpcb.csv               # Component placement file
    README.txt                    # Upload instructions
```
