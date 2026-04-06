# Circuit Weaver CLI Demo

This file contains the command sequence for recording a live CLI demo using asciinema.

## Prerequisites

Install asciinema (not included in Circuit Weaver dependencies):

```bash
# macOS (Homebrew)
brew install asciinema

# Linux (apt, yum, or pacman)
sudo apt install asciinema

# Windows (Chocolatey or manual download)
choco install asciinema
# or https://asciinema.org/
```

Install circuit-weaver in development mode:
```bash
cd circuit_weaver
pip install -e .
```

## Recording the Demo

Create a demo directory:
```bash
mkdir -p demo/{output,jlcpcb}
```

Record the demo:
```bash
asciinema rec demo.cast
```

Then run each command below in order:

---

## Command Sequence

### Step 1: List available templates
```bash
circuit-weaver list-templates | head -15
```

Output shows 30+ templates for power, analog, digital, communication circuits.

---

### Step 2: Scaffold the first block (battery charger buck converter)
```bash
circuit-weaver scaffold --template buck --ref U1 --output demo/design.yaml
cat demo/design.yaml
```

Output: YAML spec with U1 buck converter, scaffolded with defaults.

---

### Step 3: Add an LDO via apply-patch
Create a patch file first:
```bash
cat > demo/patch_ldo.json << 'EOF'
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
        "vin_net": "VBUS_5V",
        "rail_name": "VDD_3P3"
      }
    }
  ]
}
EOF
```

Apply the patch:
```bash
circuit-weaver apply-patch demo/design.yaml demo/patch_ldo.json --output demo/design.yaml
```

Output: "Added U2 (ldo) to design.yaml."

---

### Step 4: Validate the design
```bash
circuit-weaver validate demo/design.yaml
```

Output: Validation passed, 0 errors, N warnings (decoupling cap recommendations, etc.)

---

### Step 5: Generate KiCad schematic
```bash
circuit-weaver generate demo/design.yaml --output demo/output --no-svg
ls -la demo/output/
```

Output: Generated KiCad files (.kicad_sch sheets), design report, placer hints.

---

### Step 6: Estimate BOM cost at multiple quantities
```bash
circuit-weaver cost-bom demo/design.yaml --qty 1,10,100
```

Output: Formatted BOM table with LCSC pricing at qty breaks.

---

### Step 7: Export JLCPCB assembly files
```bash
circuit-weaver export-jlcpcb demo/design.yaml -o demo/jlcpcb
ls -la demo/jlcpcb/
```

Output: BOM and CPL CSV files ready for JLCPCB assembly ordering.

---

## Stopping the Recording

Press `Ctrl+D` or type `exit` to stop recording.

asciinema will prompt for optional metadata (title, author, description).

Example:
```
Title: Circuit Weaver CLI Demo
Author: Demo User
Description: End-to-end workflow: scaffold → patch → validate → generate → cost → export
```

## Playing Back the Recording

```bash
asciinema play demo.cast
```

Or view it in your browser:
```bash
asciinema upload demo.cast
```

This will give you a shareable URL.

## Tips for Good Recordings

1. **Font size**: Use a large terminal font (18+ pt) for readability
2. **Speed**: asciinema plays at recorded speed — most commands run fast
3. **Pauses**: Use `sleep 1-2` between sections if you want time to read output
4. **Annotations**: Add comments (start with `#`) to explain each step
5. **Demo data**: Use sample designs (e.g., `samples/iot_sensor_node/`) instead of creating from scratch

## Alternative: Static Markdown Script

If you prefer a static markdown file (no playback), keep this file as-is — it documents the complete workflow.
