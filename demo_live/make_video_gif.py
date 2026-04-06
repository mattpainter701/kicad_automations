#!/usr/bin/env python3
"""Create demo.gif from demo.cast using PIL."""

import json
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as e:
    print(f"Error: {e}")
    print("Install: pip install pillow")
    exit(1)


def create_gif(cast_file="demo.cast", output="demo.gif"):
    """Create animated GIF from .cast file."""

    # Parse cast
    with open(cast_file) as f:
        header = json.loads(f.readline())
        events = []
        for line in f:
            if line.strip():
                try:
                    events.append(json.loads(line))
                except:
                    pass

    width = header.get("width", 120)
    height = header.get("height", 30)

    print(f"Creating GIF: {output}")
    print(f"  Terminal: {width}x{height}")
    print(f"  Events: {len(events)}")

    # Create frames every 200ms (slower for better GIF compression)
    frames = []
    text = ""
    last_frame_time = -1
    frame_interval = 0.2  # 200ms per frame

    print("  Rendering frames...")

    for time, event_type, data in events:
        if event_type == "o":
            text += data

        if time - last_frame_time >= frame_interval or len(frames) == 0:
            img = Image.new("RGB", (1280, 720), color=(0, 0, 0))
            draw = ImageDraw.Draw(img)

            try:
                font = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 10)
            except:
                try:
                    font = ImageFont.truetype(r"C:\Windows\Fonts\cour.ttf", 10)
                except:
                    font = ImageFont.load_default()

            # Draw text (green terminal style)
            lines = text.split("\n")[-25:]  # Last 25 lines
            y = 10
            for line in lines:
                draw.text((10, y), line, fill=(0, 200, 0), font=font)
                y += 24

            frames.append(img)
            last_frame_time = time

    if not frames:
        print("No frames generated!")
        return False

    print(f"  Total frames: {len(frames)}")
    print("  Saving to GIF (200ms per frame)...")

    try:
        frames[0].save(
            output,
            save_all=True,
            append_images=frames[1:],
            duration=200,  # 200ms per frame
            loop=0,
            optimize=False,
        )
        size_mb = Path(output).stat().st_size / 1024 / 1024
        print(f"\nSuccess! Created {output} ({size_mb:.1f} MB)")
        return True
    except Exception as e:
        print(f"Error creating GIF: {e}")
        return False


if __name__ == "__main__":
    import sys

    cast = sys.argv[1] if len(sys.argv) > 1 else "demo.cast"
    output = sys.argv[2] if len(sys.argv) > 2 else "demo.gif"

    success = create_gif(cast, output)
    exit(0 if success else 1)
