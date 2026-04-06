# Circuit Weaver Live Demo

**WiFi Environmental Sensor — Complete Design Workflow**

This directory contains a complete end-to-end demonstration of Circuit Weaver, from YAML design spec to JLCPCB-ready manufacturing files.

---

## 🎬 Watch the Demo

### Option 1: Interactive Web Player (Recommended)
Open `index.html` in your browser to see an interactive terminal recording with play/pause controls.

```bash
# Open in browser
start index.html
```

Features:
- ▶️ Play/pause/seek through the recording
- 🎨 Clean dark theme
- 📊 Summary stats and workflow diagram
- 📱 Responsive on desktop and mobile

### Option 2: asciinema Player
The `demo.cast` file is a standard asciinema recording format. Play it directly:

```bash
# Play with asciinema (install: pip install asciinema)
asciinema play demo.cast

# Or view online at: https://asciinema.org/a/YOUR_ID
asciinema upload demo.cast
```

### Option 3: Convert to Video/GIF
Several tools can convert the `.cast` file to video or GIF:

**Using asciinema-to-gif:**
```bash
npm install -g asciinema-to-gif
asciinema-to-gif demo.cast demo.gif
```

**Using svg-term:**
```bash
npm install -g svg-term-cli
svg-term --cast demo.cast --output demo.svg
```

**Using terminalizer:**
```bash
npm install -g terminalizer
terminalizer render demo.cast -o demo.gif
```

---

## 📋 What's Demonstrated

The demo walks through 6 steps to design a complete WiFi-enabled environmental sensor:

| Step | Command | Output |
|-|-|-|
| 1 | `list-templates` | Explore 30+ subcircuit templates (boost, buck, ADC, etc.) |
| 2 | Create `design.yaml` | 24-line YAML specification for the sensor circuit |
| 3 | `validate design.yaml` | Verify electrical rules, decoupling, component ratings |
| 4 | `generate design.yaml --output ./output` | Generate KiCad schematic (73 KB, 4 ICs + 16 passives) |
| 5 | `cost-bom design.yaml --qty 1,10,100` | Estimate pricing at quantity breaks |
| 6 | `export-jlcpcb design.yaml -o jlcpcb_export` | Generate BOM + CPL for assembly |

**Total time: ~30 seconds**

---

## 🗂️ Files in This Directory

```
demo_live/
├── index.html                    ⭐ START HERE — interactive web player
├── demo.cast                     asciinema recording (JSON format)
├── DEMO_WALKTHROUGH.md           Detailed markdown walkthrough
├── design.yaml                   24-line design specification
├── render_cast_to_mp4.py         Python script to convert .cast to video
│
├── output/                       Generated schematic artifacts
│   ├── main.kicad_sch           KiCad schematic (73 KB)
│   ├── WiFi_Sensor_v1_report.md Design analysis report
│   ├── WiFi_Sensor_v1_placement.kicad_pcb  PCB placement hints
│   ├── design_ir.json           Design IR
│   └── canonical_spec.yaml      Normalized spec with calculated values
│
└── jlcpcb_export/               Manufacturing files (ready to order)
    ├── bom_jlcpcb.csv           BOM in JLCPCB format
    ├── cpl_jlcpcb.csv           Centroid/placement file
    └── README.txt               Upload instructions
```

---

## 🔌 Circuit Architecture

**WiFi Environmental Sensor**

```
┌─────────────┐
│ 3.7V Battery│
└──────┬──────┘
       │
   ┌───▼──────────────┐
   │  MT3608 Boost    │  3.7V → 5V, 1A
   │  (U1)            │
   └───┬──────────────┘
       │ VBUS_5V
       │
   ┌───▼──────────────┐
   │  AP62300 Buck    │  5V → 3.3V, 800mA
   │  (U2)            │
   └───┬──────────────┘
       │ VDD_3P3
       │
   ┌───┼──────────┬──────────┐
   │   │          │          │
┌──▼───▼──┐   ┌──▼───┐   ┌──▼──────┐
│ ESP32    │   │ BME280   │ (Power  │
│ WROOM-32E│   │ Sensor   │  Bypass)│
│ (U3)     │   │ (U4)     │         │
│ WiFi     │   │ I2C      │ (Caps)  │
│ BLE      │   │ Temp/    │         │
│          │   │ Humid    │         │
└──────────┘   │ Press    │         │
               └──────────┘         │
               
Generated: 4 ICs + 16 passive components
Board: 102 × 69 mm, 2-layer, A2 size
```

---

## 🚀 Next Steps

### To Use This Design

1. **Review the schematic** — Open `output/main.kicad_sch` in KiCad
2. **Layout the PCB** — KiCad → PCB Editor
3. **Add connectors** — USB, UART, antenna connectors (not in auto-generated spec)
4. **Verify design** — Run KiCad DRC/ERC
5. **Export gerbers** — KiCad → Export → Gerbers
6. **Order from JLCPCB** — Use files in `jlcpcb_export/` + gerbers

### To Customize

Edit `design.yaml` to change:
- Input voltage (e.g., 5V input instead of 3.7V battery)
- Output voltages (add more rails, change rail voltages)
- Components (substitute different ICs)
- Board size (change `board_width` / `board_height`)

Re-run validation and generation — all dependent components auto-update.

---

## 📊 Design Statistics

| Metric | Value |
|-|-|
| Design spec | 24 lines YAML |
| Design time | ~2 minutes (human) + 30 seconds (Circuit Weaver) |
| Schematic | 73 KB |
| Components | 4 ICs + 16 passives |
| Board size | 102 × 69 mm (A2 area) |
| Nets | 16 (VCC, GND, control, data) |
| Decoupling caps | Auto-placed |
| Feedback networks | Auto-calculated |
| Time to JLCPCB-ready files | 30 seconds |

---

## 🎯 Key Features Shown

✅ **Zero manual calculations** — Resistor/capacitor values computed from IC datasheets  
✅ **Auto-decoupling** — Proper bypass capacitors placed on every IC VCC/GND pair  
✅ **Electrical validation** — Feedback dividers, filter cutoffs, voltage ratings verified  
✅ **Real-time pricing** — LCSC price tiers at qty 1, 10, 100, 1000  
✅ **LLM-native** — Every step uses real CLI commands (Codex, OpenCode, Claude can run them)  
✅ **Production-ready** — JLCPCB BOM + CPL generated immediately  

---

## 📚 Documentation

- **`DEMO_WALKTHROUGH.md`** — Complete step-by-step guide with all outputs
- **`design.yaml`** — The design specification used in the demo
- **`index.html`** — Interactive web player (best for sharing)
- **`render_cast_to_mp4.py`** — Convert `.cast` to video/GIF (requires external tools)

---

## 💡 Why This Demo Matters

This demo shows that Circuit Weaver can:

1. **Capture requirements in plain English** — `WiFi_Sensor_v1` with power chain, MCU, sensor
2. **Generate production schematics** — Auto-routed, properly decoupled, validated
3. **Work with LLMs** — Claude, Codex, OpenCode can execute every CLI command
4. **Integrate with manufacturing** — JLCPCB/PCBWay files ready to order

**Result:** Hardware designers can work at the system level (topology, component selection, constraints) while the platform handles the low-level details (passives, decoupling, layout).

---

## 🔗 Related Files

- **Parent project:** `../` (Circuit Weaver source)
- **Full documentation:** `../docs/user_workflow.md`
- **CLI guide:** `../docs/DEMO_COMMANDS.md`
- **Skill reference:** `../skills/design_wizard/SKILL.md`

---

Created: 2026-04-05  
Circuit Weaver v0.10.1
