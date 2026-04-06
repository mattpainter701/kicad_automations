#!/usr/bin/env python3
"""Create realistic advertisement demo: user types commands, sees actual outputs."""

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
        if line.startswith("$"):
            # Command in bright green
            draw.text((20, y), line, fill=(0, 255, 0), font=term_font)
        elif line.startswith(">"):
            # Cursor (typing indicator)
            draw.text((20, y), line, fill=(255, 255, 0), font=term_font)
        else:
            # Output in white
            draw.text((20, y), line, fill=(200, 200, 200), font=term_font)
        y += 25


def draw_schematic_block_diagram(draw, width, height):
    """Draw a visual block diagram of the power chain."""
    # Title
    try:
        title_font = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 16)
        label_font = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 11)
    except:
        title_font = label_font = ImageFont.load_default()

    draw.text((20, 20), "WiFi Environmental Sensor — Power Chain", fill=(0, 255, 0), font=title_font)

    # Draw the power chain blocks
    blocks = [
        {"label": "3.7V\nLiPo", "x": 40, "color": (100, 100, 100), "specs": ""},
        {
            "label": "TPS61230A\nBoost\n→ 5V @ 1A",
            "x": 170,
            "color": (100, 150, 200),
            "specs": "L=1µH\nfSW=2.5MHz",
        },
        {
            "label": "AP62300\nBuck\n→ 3.3V @ 0.8A",
            "x": 340,
            "color": (100, 150, 200),
            "specs": "L=8.2µH\nfSW=600kHz",
        },
        {
            "label": "ESP32-WROOM\nWiFi MCU",
            "x": 540,
            "color": (150, 100, 200),
            "specs": "39 pins\n4 MB flash",
        },
        {
            "label": "BME280\nSensor\nI2C",
            "x": 740,
            "color": (100, 200, 100),
            "specs": "Temp/Humid\nPress",
        },
    ]

    box_w, box_h = 110, 100
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

        # Main label
        lines = block["label"].split("\n")
        text_y = y_top + 8
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=label_font)
            text_w = bbox[2] - bbox[0]
            text_x = x + (box_w - text_w) // 2
            draw.text((text_x, text_y), line, fill=(255, 255, 255), font=label_font)
            text_y += 18

        # Specs below
        spec_y = y_top + 70
        if block["specs"]:
            for spec_line in block["specs"].split("\n"):
                bbox = draw.textbbox((0, 0), spec_line, font=label_font)
                text_w = bbox[2] - bbox[0]
                text_x = x + (box_w - text_w) // 2
                draw.text((text_x, spec_y), spec_line, fill=(150, 200, 150), font=label_font)
                spec_y += 12

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

    # Legend at bottom
    y_legend = y_top + box_h + 40
    draw.text((40, y_legend), "Input Power", fill=(150, 150, 150), font=label_font)
    draw.text((170, y_legend), "Power Conversion", fill=(150, 150, 150), font=label_font)
    draw.text((540, y_legend), "Logic & Communications", fill=(150, 150, 150), font=label_font)


def draw_bom_table(draw, width, height):
    """Draw the BOM as a formatted table."""
    # Title
    try:
        title_font = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 16)
        table_font = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 12)
    except:
        title_font = table_font = ImageFont.load_default()

    draw.text((20, 30), "Bill of Materials (LCSC)", fill=(0, 255, 0), font=title_font)

    # Table header
    bom_data = [
        ("Ref", "MPN", "Package", "LCSC", "Cost (1x)"),
        ("U1", "TPS61230A", "SOT-23-6", "C406093", "$2.50"),
        ("U2", "AP62300", "SOT-23-6", "C460320", "$1.20"),
        ("U3", "ESP32-WROOM-32E", "SMD-30", "C529676", "$5.80"),
        ("U4", "BME280", "LGA-8", "C91305", "$2.15"),
        ("C1-C16", "Passives (caps/resistors)", "0402-1206", "Various", "$0.60"),
        ("", "", "", "TOTAL:", "$12.25"),
    ]

    y = 80
    col_x = [20, 100, 220, 340, 480]
    row_h = 28

    # Draw header row
    for i, (col_text, col_x_pos) in enumerate(zip(bom_data[0], col_x)):
        draw.text((col_x_pos, y), col_text, fill=(0, 255, 0), font=table_font)

    # Draw separator
    y += row_h - 5
    draw.line([(20, y), (width - 20, y)], fill=(100, 100, 100), width=1)

    # Draw data rows
    y += 10
    for row in bom_data[1:]:
        for col_text, col_x_pos in zip(row, col_x):
            color = (255, 255, 100) if col_text == "$12.25" else (200, 200, 200)
            draw.text((col_x_pos, y), col_text, fill=color, font=table_font)
        y += row_h


def draw_placement_data(draw, width, height):
    """Draw PCB placement coordinates."""
    try:
        title_font = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 16)
        content_font = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 13)
    except:
        title_font = content_font = ImageFont.load_default()

    draw.text((20, 30), "PCB Placement (Pick & Place)", fill=(0, 255, 0), font=title_font)

    placement = [
        "Reference  | X (mm)  | Y (mm)  | Rotation | Layer",
        "-----------|---------|---------|----------|------",
        "U1         |  10.00  |  10.00  |    0°    | Top",
        "U2         |  18.00  |  10.00  |    0°    | Top",
        "U3         |  50.00  |  30.00  |    0°    | Top",
        "U4         |  90.00  |  60.00  |    0°    | Top",
        "C1-C16     | Various | Various | 0°/180°  | Top",
        "",
        "Status: READY FOR ASSEMBLY",
    ]

    y = 90
    for line in placement:
        if "READY" in line:
            draw.text((20, y), line, fill=(0, 255, 0), font=content_font)
        elif "---" in line:
            draw.line([(20, y + 8), (600, y + 8)], fill=(100, 100, 100), width=1)
        elif line.startswith("Reference"):
            draw.text((20, y), line, fill=(0, 255, 0), font=content_font)
        else:
            draw.text((20, y), line, fill=(200, 200, 200), font=content_font)
        y += 28


# Define the demo sequence
demo_frames = [
    {
        "type": "terminal",
        "title": "$ circuit-weaver design-wizard",
        "duration": 6,
        "content": [
            "$ circuit-weaver design-wizard",
            "",
            "Welcome to Circuit Weaver Design Wizard",
            "=====================================",
            "",
            "Step 1: What are you designing?",
            "  [1] WiFi/BLE device",
            "  [2] Wired sensor",
            "  [3] Battery-powered IoT",
            "",
            "> Design Type: [1] WiFi/BLE device",
        ],
    },
    {
        "type": "terminal",
        "title": "$ circuit-weaver design-wizard (continued)",
        "duration": 5,
        "content": [
            "Step 2: Select your power source",
            "  [1] USB-C (5V input)",
            "  [2] LiPo battery (3.7V)",
            "  [3] Wall adapter (12V)",
            "",
            "> Power Source: [2] LiPo battery (3.7V)",
            "",
            "Step 3: Main microcontroller?",
            "  [1] ESP32-S3 (WiFi + BLE, 4MB)",
            "  [2] nRF52840 (BLE only)",
            "",
            "> MCU: [1] ESP32-S3 (WiFi + BLE, 4MB)",
        ],
    },
    {
        "type": "terminal",
        "title": "$ circuit-weaver design-wizard (sensors & validation)",
        "duration": 5,
        "content": [
            "Step 4: Sensors?",
            "  [1] BME280 (Temp/Humidity/Pressure)",
            "  [2] MPU6050 (Accelerometer + Gyro)",
            "  [3] None (skip)",
            "",
            "> Sensor: [1] BME280 (Temp/Humidity/Pressure)",
            "",
            "[✓] Analyzing design requirements...",
            "[✓] Selecting components from LCSC...",
            "[✓] Calculating feedback networks...",
            "[✓] Verifying power budget...",
            "[✓] Running electrical validation...",
            "",
            "VALIDATION: PASS (all checks)",
        ],
    },
    {
        "type": "diagram",
        "title": "Generated Schematic",
        "duration": 5,
    },
    {
        "type": "bom",
        "title": "Bill of Materials - Ready to Order",
        "duration": 4,
    },
    {
        "type": "placement",
        "title": "PCB Placement Coordinates",
        "duration": 4,
    },
    {
        "type": "terminal",
        "title": "Export Complete",
        "duration": 5,
        "content": [
            "[✓] Generated: output/main.kicad_sch (73 KB)",
            "[✓] Generated: output/WiFi_Sensor_v1_placement.kicad_pcb",
            "[✓] Generated: jlcpcb_export/bom_jlcpcb.csv",
            "[✓] Generated: jlcpcb_export/cpl_jlcpcb.csv",
            "",
            "Design Time: 3 minutes 45 seconds",
            "Normally this takes: 1-2 weeks",
            "",
            "READY TO ORDER FROM JLCPCB",
            "",
            "Next step: Review in KiCad and submit to manufacturing!",
        ],
    },
]

# Create frames
print("Creating realistic advertisement demo...")
frames = []

for scene_idx, scene in enumerate(demo_frames):
    scene_type = scene["type"]
    duration = scene["duration"]

    # Create frames for this scene
    for frame_num in range(duration):
        img = Image.new("RGB", (1280, 720), color=(10, 10, 10))
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
            draw_terminal_frame(draw, 1280, 680, scene["content"])
        elif scene_type == "diagram":
            draw_schematic_block_diagram(draw, 1280, 680)
        elif scene_type == "bom":
            draw_bom_table(draw, 1280, 680)
        elif scene_type == "placement":
            draw_placement_data(draw, 1280, 680)

        # Progress bar
        progress = (scene_idx + frame_num / duration) / len(demo_frames)
        bar_width = int(1280 * progress)
        draw.rectangle([(0, 700), (bar_width, 720)], fill=(0, 200, 100))
        draw.rectangle([(bar_width, 700), (1280, 720)], fill=(40, 40, 40))

        frames.append(img)

# Save as GIF
print(f"Saving {len(frames)} frames...")
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
print(f"Created demo_realistic.gif ({size_mb:.1f} MB, {playback_sec}s playback)")
