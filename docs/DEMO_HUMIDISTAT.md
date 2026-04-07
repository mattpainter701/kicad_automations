# Demo: Zigbee/BT Humidistat -- Full Pipeline

Build a compact IoT humidity sensor end-to-end.

## Commands

```bash
circuit-weaver generate zigbee_humidistat.yaml --output ./output --no-svg --no-require-valid
circuit-weaver cost-bom zigbee_humidistat.yaml --qty 1,10,100
circuit-weaver si-constraints zigbee_humidistat.yaml
circuit-weaver thermal-analysis zigbee_humidistat.yaml
circuit-weaver optimize-placement zigbee_humidistat.yaml --iterations 1000 --seed 42
circuit-weaver placement-viewer zigbee_humidistat.yaml --output output/viewer.html
circuit-weaver panelize --board-width 50 --board-height 40 --qty 100
circuit-weaver design-enclosure --board-width 50 --board-height 40 --component-height 10 --output output/enclosure.scad
circuit-weaver export-jlcpcb zigbee_humidistat.yaml --output output/jlcpcb
```

9 pipeline stages: generate, cost, SI, thermal, placement, viewer, panelize, enclosure, fab export.

See `samples/zigbee_humidistat/README.md` for the full design description.
