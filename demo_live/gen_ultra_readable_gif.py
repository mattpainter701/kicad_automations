#!/usr/bin/env python3
"""Create ultra-readable demo GIF: huge fonts, slow pacing, visible CLI commands."""

import json
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as e:
    print(f"Error: {e}")
    print("Install: pip install pillow")
    exit(1)

# Phase specifications
phases = [
    {
        "name": "START",
        "start": 0,
        "duration": 6,
        "color": (50, 50, 50),
        "title": "CIRCUIT WEAVER DEMO",
        "subtitle": "Design a WiFi Environmental Sensor",
        "cmd": "",
        "desc": [
            "Watch how we go from requirements",
            "to manufacturing-ready files",
            "",
            "in just 60 seconds of engineering.",
        ],
    },
    {
        "name": "EXPLORE",
        "start": 0,
        "duration": 5,
        "color": (100, 200, 255),
        "title": "Step 1: Explore Available Subcircuits",
        "subtitle": "",
        "cmd": "$ circuit-weaver list-templates",
        "desc": [
            "See all 30+ available templates:",
            "Power (buck, boost, LDO)",
            "Communications (USB, I2C, SPI)",
            "Sensors (ADC, comparators)",
            "Support circuits (filters, oscillators)",
        ],
    },
    {
        "name": "SCAFFOLD",
        "start": 5,
        "duration": 6,
        "color": (100, 255, 150),
        "title": "Step 2: Create Design Specification",
        "subtitle": "Build the circuit from templates",
        "cmd": "$ circuit-weaver scaffold --template boost --ref U1",
        "desc": [
            "Define circuit in YAML:",
            "",
            "- MT3608 boost: 3.7V -> 5V",
            "- AP62300 buck: 5V -> 3.3V",
            "- ESP32 MCU with WiFi",
            "- BME280 I2C sensor",
        ],
    },
    {
        "name": "VALIDATE",
        "start": 11,
        "duration": 6,
        "color": (255, 200, 100),
        "title": "Step 3: Validate Electrical Design",
        "subtitle": "Automated safety checks",
        "cmd": "$ circuit-weaver validate design.yaml",
        "desc": [
            "Checks that pass:",
            "",
            "[OK] Power domain consistency",
            "[OK] Decoupling coverage (all ICs bypassed)",
            "[OK] Net connectivity (no floating pins)",
            "[OK] Component ratings safe",
        ],
    },
    {
        "name": "GENERATE",
        "start": 17,
        "duration": 6,
        "color": (255, 150, 150),
        "title": "Step 4: Generate KiCad Schematic",
        "subtitle": "Create production schematic",
        "cmd": "$ circuit-weaver generate design.yaml --output ./output",
        "desc": [
            "Output: main.kicad_sch (73 KB)",
            "",
            "Includes:",
            "- 4 ICs placed and connected",
            "- 16 passive components auto-calculated",
            "- Proper power distribution",
        ],
    },
    {
        "name": "COST",
        "start": 23,
        "duration": 6,
        "color": (200, 150, 255),
        "title": "Step 5: Cost Analysis at Volume",
        "subtitle": "Real pricing from LCSC",
        "cmd": "$ circuit-weaver cost-bom design.yaml --qty 1,10,100,1000",
        "desc": ["Unit pricing:", "", "1x:    $12.45", "10x:   $8.90 each", "100x:  $6.20 each", "1000x: $4.15 each"],
    },
    {
        "name": "EXPORT",
        "start": 29,
        "duration": 6,
        "color": (255, 200, 200),
        "title": "Step 6: Export for Assembly",
        "subtitle": "Ready for JLCPCB upload",
        "cmd": "$ circuit-weaver export-jlcpcb design.yaml -o jlcpcb/",
        "desc": [
            "Generated manufacturing files:",
            "",
            "- bom.csv (part numbers + quantities)",
            "- cpl.csv (placement + rotation)",
            "- README (upload instructions)",
            "",
        ],
    },
    {
        "name": "DONE",
        "start": 35,
        "duration": 8,
        "color": (100, 255, 100),
        "title": "COMPLETE: 60 Seconds of Engineering",
        "subtitle": "From requirements to quote-ready",
        "cmd": "",
        "desc": [
            "What normally takes 2 weeks:",
            "",
            "Requirements -> Component selection ->",
            "Schematic design -> Validation ->",
            "Cost analysis -> Manufacturing export",
            "",
            "All in one minute with Circuit Weaver",
        ],
    },
]

# Read cast file
with open("demo.cast") as f:
    header = json.loads(f.readline())
    events = []
    for line in f:
        if line.strip():
            try:
                events.append(json.loads(line))
            except:
                pass

print("Creating ultra-readable demo (1400ms/frame, HUGE fonts, visible commands)...")

frames = []
text = ""
last_frame_time = -1
frame_interval = 1.4  # 1400ms per frame
current_phase = None

for time, event_type, data in events:
    if event_type == "o":
        text += data

    # Find current phase
    current_phase = None
    for phase in phases:
        if time >= phase["start"] and time < phase["start"] + phase["duration"]:
            current_phase = phase
            break

    if time - last_frame_time >= frame_interval or len(frames) == 0:
        img = Image.new("RGB", (1280, 720), color=(20, 20, 20))
        draw = ImageDraw.Draw(img)

        try:
            # MUCH larger fonts
            title_font = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 32)
            subtitle_font = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 20)
            desc_font = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 18)
            cmd_font = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 16)
            terminal_font = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 14)
        except:
            title_font = subtitle_font = desc_font = cmd_font = terminal_font = ImageFont.load_default()

        if current_phase:
            # Large title bar
            draw.rectangle([(0, 0), (1280, 90)], fill=current_phase["color"])
            draw.text((30, 15), current_phase["title"], fill=(0, 0, 0), font=title_font)
            if current_phase["subtitle"]:
                draw.text(
                    (30, 55),
                    current_phase["subtitle"],
                    fill=(50, 50, 50),
                    font=subtitle_font,
                )

            # Command line in yellow box
            if current_phase["cmd"]:
                draw.rectangle([(0, 100), (1280, 140)], fill=(255, 220, 0))
                draw.text((30, 105), current_phase["cmd"], fill=(0, 0, 0), font=cmd_font)
                desc_start_y = 160
            else:
                desc_start_y = 110

            # Large description text
            y = desc_start_y
            for line in current_phase["desc"]:
                if line:
                    draw.text((40, y), line, fill=(220, 220, 220), font=desc_font)
                y += 40

            # Terminal output at bottom (larger)
            term_y = 480
            lines = text.split("\n")[-6:]
            for line in lines:
                draw.text((40, term_y), line[:80], fill=(0, 255, 0), font=terminal_font)
                term_y += 28
        else:
            # Just large terminal before phases
            lines = text.split("\n")[-15:]
            y = 30
            for line in lines:
                draw.text((30, y), line, fill=(0, 255, 0), font=desc_font)
                y += 36

        # Large progress bar
        total_time = 43
        progress = min(time / total_time, 1.0)
        bar_width = int(1280 * progress)
        draw.rectangle([(0, 700), (bar_width, 720)], fill=(0, 255, 0))
        draw.rectangle([(bar_width, 700), (1280, 720)], fill=(40, 40, 40))

        # Time counter
        draw.text((1150, 705), f"{time:.0f}s", fill=(255, 255, 255), font=subtitle_font)

        frames.append(img)
        last_frame_time = time

print(f"Saving {len(frames)} frames (1400ms/frame)...")
frames[0].save(
    "demo_ultra_readable.gif",
    save_all=True,
    append_images=frames[1:],
    duration=1400,
    loop=0,
    optimize=False,
)

size_mb = Path("demo_ultra_readable.gif").stat().st_size / 1024 / 1024
playback_sec = int(len(frames) * 1.4)
print(f"Created demo_ultra_readable.gif ({size_mb:.1f} MB)")
print(f"Frames: {len(frames)}, Playback: ~{playback_sec}s")
