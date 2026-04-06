#!/usr/bin/env python3
"""Create demo.mp4 from demo.cast using imageio."""

import json
import sys
from pathlib import Path

try:
    import imageio
    from PIL import Image, ImageDraw, ImageFont
except ImportError as e:
    print(f"Error: {e}")
    print("Install: pip install pillow imageio imageio-ffmpeg")
    sys.exit(1)


def create_video(cast_file="demo.cast", output="demo.mp4"):
    """Create MP4 video from .cast file."""

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

    width = header.get("width", 100)
    height = header.get("height", 30)

    print(f"Creating video: {output}")
    print(f"  Terminal: {width}x{height}")
    print(f"  Events: {len(events)}")

    # Create frames
    frames = []
    fps = 10
    frame_interval = 1.0 / fps  # Time between frames

    # Replay terminal
    text = ""
    last_frame_time = -1

    print("  Rendering frames...")
    frame_count = 0

    for time, event_type, data in events:
        if event_type == "o":
            text += data

        # Create frame every ~100ms
        if time - last_frame_time >= frame_interval or frame_count == 0:
            # Create image
            img = Image.new("RGB", (1280, 720), color=(0, 0, 0))
            draw = ImageDraw.Draw(img)

            try:
                font = ImageFont.truetype("C:\\Windows\\Fonts\\consola.ttf", 10)
            except:
                try:
                    font = ImageFont.truetype("C:\\Windows\\Fonts\\cour.ttf", 10)
                except:
                    font = ImageFont.load_default()

            # Draw text (green terminal style)
            lines = text.split("\n")[-25:]  # Last 25 lines
            y = 10
            for line in lines:
                draw.text((10, y), line, fill=(0, 200, 0), font=font)
                y += 24

            frames.append(img)
            frame_count += 1
            last_frame_time = time

    if not frames:
        print("No frames generated!")
        return False

    print(f"  Total frames: {len(frames)}")
    print(f"  Encoding to MP4 ({fps} fps)...")

    try:
        imageio.mimwrite(output, frames, fps=fps, codec="libx264")
        size_mb = Path(output).stat().st_size / 1024 / 1024
        print(f"\nSuccess! Created {output} ({size_mb:.1f} MB)")
        return True
    except Exception as e:
        print(f"Error encoding: {e}")
        return False


if __name__ == "__main__":
    cast = sys.argv[1] if len(sys.argv) > 1 else "demo.cast"
    output = sys.argv[2] if len(sys.argv) > 2 else "demo.mp4"

    success = create_video(cast, output)
    sys.exit(0 if success else 1)
