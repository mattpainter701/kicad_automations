#!/usr/bin/env python3
"""Create realistic demo GIF showing /circuit-weaver skill workflow."""

from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Error: Install pillow with: pip install pillow")
    exit(1)


def draw_terminal_frame(draw, width, height, terminal_content, title=""):
    """Draw a terminal-style frame with content."""
    # Terminal background
    draw.rectangle([(0, 0), (width, height)], fill=(20, 20, 20))

    # Title bar if provided
    if title:
        draw.rectangle([(0, 0), (width, 40)], fill=(50, 50, 50))
        try:
            title_font = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 14)
        except:
            title_font = ImageFont.load_default()
        draw.text((15, 10), title, fill=(0, 255, 0), font=title_font)
        content_y = 50
    else:
        content_y = 10

    # Terminal content
    try:
        term_font = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 13)
    except:
        term_font = ImageFont.load_default()

    y = content_y
    for line in terminal_content:
        if line.startswith("$") or line.startswith(">"):
            color = (0, 255, 0) if line.startswith("$") else (255, 255, 0)
            draw.text((20, y), line, fill=color, font=term_font)
        elif line.startswith("["):
            draw.text((20, y), line, fill=(0, 200, 255), font=term_font)
        else:
            draw.text((20, y), line, fill=(200, 200, 200), font=term_font)
        y += 25


def draw_power_chain(draw, width, height):
    """Draw power supply chain visualization."""
    try:
        title_font = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 16)
        label_font = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 11)
    except:
        title_font = label_font = ImageFont.load_default()

    draw.text((20, 20), "Generated Schematic - Power Chain", fill=(0, 255, 0), font=title_font)

    # Draw the power chain
    blocks = [
        {"label": "3.7V\nLiPo", "x": 50, "color": (100, 100, 100), "specs": "Battery"},
        {
            "label": "TPS61230A\nBoost\n→ 5V @ 1A",
            "x": 180,
            "color": (100, 150, 200),
            "specs": "fSW=2.5MHz",
        },
        {
            "label": "AP62300\nBuck\n→ 3.3V @ 0.8A",
            "x": 330,
            "color": (100, 150, 200),
            "specs": "fSW=600kHz",
        },
        {
            "label": "ESP32-WROOM\nWiFi MCU",
            "x": 500,
            "color": (150, 100, 200),
            "specs": "39 pins",
        },
        {
            "label": "BME280\nSensor\nI2C",
            "x": 670,
            "color": (100, 200, 100),
            "specs": "Temp/Humid",
        },
    ]

    box_w, box_h = 100, 90
    y_top = 100

    # Draw boxes
    for i, block in enumerate(blocks):
        x = block["x"]

        # Box
        draw.rectangle(
            [(x, y_top), (x + box_w, y_top + box_h)],
            fill=block["color"],
            outline=(200, 200, 200),
            width=2,
        )

        # Label
        lines = block["label"].split("\n")
        text_y = y_top + 8
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=label_font)
            text_w = bbox[2] - bbox[0]
            text_x = x + (box_w - text_w) // 2
            draw.text((text_x, text_y), line, fill=(255, 255, 255), font=label_font)
            text_y += 16

        # Specs
        if block["specs"]:
            bbox = draw.textbbox((0, 0), block["specs"], font=label_font)
            text_w = bbox[2] - bbox[0]
            text_x = x + (box_w - text_w) // 2
            draw.text((text_x, y_top + 68), block["specs"], fill=(150, 200, 150), font=label_font)

        # Arrow to next block
        if i < len(blocks) - 1:
            next_x = blocks[i + 1]["x"]
            arrow_y = y_top + box_h // 2
            draw.line(
                [(x + box_w, arrow_y), (next_x - 5, arrow_y)],
                fill=(150, 200, 150),
                width=2,
            )
            # Arrowhead
            draw.polygon(
                [(next_x - 5, arrow_y), (next_x - 12, arrow_y - 4), (next_x - 12, arrow_y + 4)],
                fill=(150, 200, 150),
            )

    # Bill of Materials table
    y_bom = y_top + box_h + 50
    draw.text((20, y_bom), "Bill of Materials (LCSC pricing)", fill=(0, 255, 0), font=title_font)

    y_bom += 35
    col_x = [20, 100, 200, 320, 450]
    bom_rows = [
        ("Ref", "MPN", "Package", "LCSC", "Cost (1x)"),
        ("U1", "TPS61230A", "SOT-23-6", "C406093", "$2.50"),
        ("U2", "AP62300", "SOT-23-6", "C460320", "$1.20"),
        ("U3", "ESP32-WROOM-32E", "SMD-30", "C529676", "$5.80"),
        ("U4", "BME280", "LGA-8", "C91305", "$2.15"),
    ]

    try:
        table_font = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 11)
    except:
        table_font = label_font

    for i, row in enumerate(bom_rows):
        for j, text in enumerate(row):
            color = (0, 255, 0) if i == 0 else (255, 255, 100) if j == 4 else (200, 200, 200)
            draw.text((col_x[j], y_bom), text, fill=color, font=table_font)
        y_bom += 20

    draw.text((20, y_bom + 5), "TOTAL: $12.25", fill=(255, 255, 100), font=table_font)


def draw_export_screen(draw, width, height):
    """Draw the export/manufacturing files screen."""
    try:
        title_font = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 16)
        content_font = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 12)
    except:
        title_font = content_font = ImageFont.load_default()

    draw.text((20, 20), "Export Complete - Ready for JLCPCB", fill=(0, 255, 0), font=title_font)

    y = 80
    exports = [
        "[✓] output/main.kicad_sch (73 KB, 4 ICs + 16 passives)",
        "[✓] output/WiFi_Sensor_v1_placement.kicad_pcb (footprints + placement hints)",
        "[✓] output/WiFi_Sensor_v1_report.md (design analysis, power budget, DFM notes)",
        "[✓] jlcpcb_export/bom_jlcpcb.csv (LCSC part numbers for ordering)",
        "[✓] jlcpcb_export/cpl_jlcpcb.csv (placement file for pick-and-place)",
        "[✓] jlcpcb_export/README.txt (upload instructions for JLCPCB)",
        "",
        "Design Time: 3 minutes",
        "Normally this takes: 1-2 weeks",
        "",
        "READY TO ORDER FROM JLCPCB",
        "",
        "Next: Review in KiCad and submit to manufacturing!",
    ]

    for line in exports:
        if line.startswith("[✓]"):
            draw.text((20, y), line, fill=(0, 255, 0), font=content_font)
        elif "READY" in line or "JLCPCB" in line:
            draw.text((20, y), line, fill=(0, 255, 0), font=content_font)
        elif "Normally" in line or "weeks" in line:
            draw.text((20, y), line, fill=(255, 200, 0), font=content_font)
        else:
            draw.text((20, y), line, fill=(200, 200, 200), font=content_font)
        y += 28


# Define the demo sequence
demo_frames = [
    {
        "type": "terminal",
        "title": "Claude Code: /circuit-weaver",
        "duration": 6,
        "content": [
            "user> /circuit-weaver",
            "",
            "Welcome to Circuit Weaver",
            "========================",
            "",
            "What would you like to do?",
            "  [1] Design a new circuit (guided workflow)",
            "  [2] Open an existing design (load & review)",
            "",
            "> Choice: [1] Design a new circuit",
        ],
    },
    {
        "type": "terminal",
        "title": "Step 1: Experience Level",
        "duration": 4,
        "content": [
            "How would you describe your electronics experience?",
            "  [1] Beginner",
            "  [2] Intermediate",
            "  [3] Advanced",
            "  [4] Professional EE",
            "",
            "> Choice: [2] Intermediate",
        ],
    },
    {
        "type": "terminal",
        "title": "Step 2: Requirements Capture",
        "duration": 5,
        "content": [
            "[?] What does this board do?",
            "> WiFi environmental sensor, battery-powered, 50x30mm enclosure",
            "",
            "[?] Interfaces (USB, I2C, WiFi)?",
            "> USB for charging, I2C for sensor, WiFi via ESP32",
            "",
            "[?] Power source?",
            "> 3.7V LiPo, needs 5V and 3.3V rails, ~500mA total",
            "",
            "[✓] Power budget validated: 1.5A @ 3.7V = 5.5W",
        ],
    },
    {
        "type": "terminal",
        "title": "Step 3: IC Research (Agent)",
        "duration": 6,
        "content": [
            "[*] Spawning research-analyst agent...",
            "[*] Searching for reference designs via Perplexity Sonar API",
            "",
            "=== IC Research Results ===",
            "",
            "Boost Converter (3.7V -> 5V @ 1A):",
            "  [1] TPS61230A (most common, $2.50) <- SELECTED",
            "",
            "Buck Converter (5V -> 3.3V @ 0.8A):",
            "  [1] AP62300 (recommended, $1.20) <- SELECTED",
            "",
            "[*] Fetching datasheets from DigiKey...",
        ],
    },
    {
        "type": "terminal",
        "title": "Step 4: BOM & Passive Generation",
        "duration": 5,
        "content": [
            "[*] Calculating feedback dividers and decoupling caps",
            "[*] Querying LCSC for pricing and availability",
            "",
            "=== Generated BOM ===",
            "",
            "Reference | MPN              | LCSC       | Cost",
            "-----------|------------------+------------|--------",
            "U1        | TPS61230A        | C406093    | $2.50",
            "U2        | AP62300          | C460320    | $1.20",
            "U3        | ESP32-WROOM-32E  | C529676    | $5.80",
            "U4        | BME280           | C91305     | $2.15",
            "C1-C16    | Passives         | Various    | $0.60",
            "          |                  | TOTAL:     | $12.25",
        ],
    },
    {
        "type": "diagram",
        "title": "Step 5: Schematic Generation",
        "duration": 6,
    },
    {
        "type": "terminal",
        "title": "Validation Report",
        "duration": 4,
        "content": [
            "[*] circuit-weaver validate design.yaml",
            "",
            "=== Validation Report ===",
            "",
            "Structural checks:      PASS",
            "Electrical checks:      PASS",
            "  [✓] Power domains (3 domains: VBAT, VBUS_5V, VDD_3P3)",
            "  [✓] Decoupling coverage (all ICs have bypass + bulk caps)",
            "  [✓] Net connectivity (16 nets, no floating pins)",
            "  [✓] Component ratings (voltage/current safe)",
            "",
            "Overall: PASS (ready for manufacturing)",
        ],
    },
    {
        "type": "export",
        "title": "Step 6: Export to JLCPCB",
        "duration": 6,
    },
    {
        "type": "terminal",
        "title": "Next Steps",
        "duration": 5,
        "content": [
            "=== Design Complete ===",
            "",
            "[✓] Design spec: design.yaml",
            "[✓] Schematic: output/main.kicad_sch",
            "[✓] Placement: output/WiFi_Sensor_v1_placement.kicad_pcb",
            "[✓] JLCPCB files: jlcpcb_export/bom.csv + cpl.csv",
            "",
            "Next steps:",
            "  1. Review in KiCad (kicad output/main.kicad_sch)",
            "  2. Upload to JLCPCB: https://cart.jlcpcb.com/quote",
            "  3. Enable PCB Assembly + upload jlcpcb_export/",
            "",
            "Questions? Use /research or /kicad to dive deeper.",
        ],
    },
]

# Create frames
print("Creating /circuit-weaver skill demo GIF...")
frames = []

for scene_idx, scene in enumerate(demo_frames):
    scene_type = scene["type"]
    duration = scene["duration"]

    # Create frames for this scene
    for frame_num in range(duration):
        img = Image.new("RGB", (1280, 800), color=(10, 10, 10))
        draw = ImageDraw.Draw(img)

        # Title bar
        try:
            title_font = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 14)
        except:
            title_font = ImageFont.load_default()

        if "title" in scene:
            draw.rectangle([(0, 0), (1280, 40)], fill=(50, 50, 80))
            draw.text((15, 10), scene["title"], fill=(0, 200, 255), font=title_font)

        # Content based on scene type
        if scene_type == "terminal":
            draw_terminal_frame(draw, 1280, 760, scene["content"])
        elif scene_type == "diagram":
            draw_power_chain(draw, 1280, 760)
        elif scene_type == "export":
            draw_export_screen(draw, 1280, 760)

        # Progress bar
        progress = (scene_idx + frame_num / duration) / len(demo_frames)
        bar_width = int(1280 * progress)
        draw.rectangle([(0, 780), (bar_width, 800)], fill=(0, 200, 100))
        draw.rectangle([(bar_width, 780), (1280, 800)], fill=(40, 40, 40))

        frames.append(img)

# Save as GIF
print(f"Saving {len(frames)} frames to demo_realistic.gif...")
frames[0].save(
    "demo_realistic.gif",
    save_all=True,
    append_images=frames[1:],
    duration=1000,
    loop=0,
    optimize=False,
)

size_mb = Path("demo_realistic.gif").stat().st_size / 1024 / 1024
playback_sec = len(frames)
print(f"[+] Created demo_realistic.gif ({size_mb:.1f} MB, {playback_sec}s playback)")
print("\nDemo shows:")
print("  1. User triggers /circuit-weaver skill")
print("  2. Experience level & requirements capture")
print("  3. Research-analyst agent finding ICs (Perplexity)")
print("  4. Passive generation & BOM assembly (LCSC pricing)")
print("  5. Schematic validation & generation")
print("  6. Export to JLCPCB (BOM + CPL files)")
print("\nNext: Review in KiCad and order from JLCPCB!")
