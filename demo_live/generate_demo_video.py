#!/usr/bin/env python3
"""Generate demo.mp4 from demo.cast using ffmpeg."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def create_mp4_from_cast(cast_file: str, output_mp4: str = "demo.mp4", fps: int = 30) -> bool:
    """
    Convert .cast to MP4 by:
    1. Parsing the cast file
    2. Creating text frames showing terminal output
    3. Using ffmpeg to encode as MP4
    """

    cast_path = Path(cast_file)
    if not cast_path.exists():
        print(f"❌ Cast file not found: {cast_file}")
        return False

    print("📹 Generating video from terminal recording...")
    print()

    # Parse cast file
    with open(cast_path) as f:
        header = json.loads(f.readline())
        events = []
        for line in f:
            if line.strip():
                try:
                    parts = json.loads(line)
                    if len(parts) >= 3:
                        events.append(parts)
                except:
                    pass

    width = header.get("width", 120)
    height = header.get("height", 30)
    total_time = events[-1][0] if events else 10

    print(f"  Terminal: {width}×{height}")
    print(f"  Duration: {total_time:.1f}s")
    print(f"  Events: {len(events)}")
    print()

    # Reconstruct terminal state at each frame
    char_width = 8
    char_height = 16
    video_width = width * char_width
    video_height = height * char_height

    print(f"  Video: {video_width}×{video_height}px")
    print()

    # Create temporary directory for frames
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Replay cast to get terminal state over time
        terminal_state = [""] * height
        cursor_y = 0
        cursor_x = 0

        frame_times = []
        frame_files = []
        frame_num = 0

        print("🎨 Creating frames...")

        for time, event_type, data in events:
            if event_type == "o":  # Output
                # Process escape sequences (simplified - just output text)
                for char in data:
                    if char == "\n":
                        cursor_y += 1
                        cursor_x = 0
                        if cursor_y >= height:
                            terminal_state.pop(0)
                            terminal_state.append("")
                            cursor_y = height - 1
                    elif char == "\r":
                        cursor_x = 0
                    else:
                        if cursor_y >= len(terminal_state):
                            terminal_state.append("")
                        line = terminal_state[cursor_y]
                        if cursor_x >= len(line):
                            line = line + " " * (cursor_x - len(line)) + char
                        else:
                            line = line[:cursor_x] + char + line[cursor_x + 1 :]
                        terminal_state[cursor_y] = line
                        cursor_x += 1

        # Create simple test frames as PNG images
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            print("❌ Pillow not installed. Installing...")
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pillow"], check=True)
            from PIL import Image, ImageDraw, ImageFont

        print("   Creating image frames...")

        # Use a monospace font if available, otherwise use default
        try:
            font = ImageFont.truetype("C:\\Windows\\Fonts\\consola.ttf", 12)
        except:
            try:
                font = ImageFont.load_default()
            except:
                font = None

        # Create first frame
        img = Image.new("RGB", (video_width, video_height), color=(0, 0, 0))
        draw = ImageDraw.Draw(img)

        frame_path = tmpdir / "frame_0000.png"
        img.save(frame_path)
        frame_files.append(frame_path)
        frame_times.append(0.0)
        frame_num = 1

        # Create frames for each event
        current_text = ""
        for time, event_type, data in events:
            if event_type == "o":
                current_text += data

            # Create frame every 100ms
            if frame_num % 3 == 0 or time >= total_time:
                img = Image.new("RGB", (video_width, video_height), color=(0, 0, 0))
                draw = ImageDraw.Draw(img)

                # Draw text
                y = 5
                for line in current_text.split("\n")[-height:]:
                    draw.text((5, y), line[:width], fill=(0, 200, 0), font=font)
                    y += char_height

                frame_path = tmpdir / f"frame_{frame_num:04d}.png"
                img.save(frame_path)
                frame_files.append(frame_path)
                frame_times.append(time)

            frame_num += 1

        print(f"   ✓ Created {len(frame_files)} frames")
        print()

        # Use ffmpeg to create video from image sequence
        print("🎬 Encoding video with ffmpeg...")

        # Create a concat demuxer file
        concat_file = tmpdir / "concat.txt"
        with open(concat_file, "w") as f:
            duration_per_frame = total_time / len(frame_files)
            for frame_file in frame_files:
                f.write(f"file '{frame_file}'\n")
                f.write(f"duration {duration_per_frame}\n")

        try:
            # Use image2pipe for more control
            cmd = [
                "ffmpeg",
                "-r",
                str(fps),
                "-i",
                str(tmpdir / "frame_%04d.png"),
                "-pix_fmt",
                "yuv420p",
                "-y",
                output_mp4,
            ]

            print(f"   Command: ffmpeg -r {fps} -i frame_%04d.png -pix_fmt yuv420p -y {output_mp4}")
            print()

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            if result.returncode != 0:
                print("❌ ffmpeg error:")
                print(result.stderr[:500])
                return False

            output_path = Path(output_mp4)
            if output_path.exists():
                size_mb = output_path.stat().st_size / 1024 / 1024
                print(f"✅ Video created: {output_mp4} ({size_mb:.1f} MB)")
                return True
            else:
                print("❌ ffmpeg did not create output file")
                return False

        except FileNotFoundError:
            print("❌ ffmpeg not found. Install with: choco install ffmpeg")
            return False
        except subprocess.TimeoutExpired:
            print("❌ ffmpeg timeout (took >2 minutes)")
            return False
        except Exception as e:
            print(f"❌ Error: {e}")
            return False


if __name__ == "__main__":
    cast_file = sys.argv[1] if len(sys.argv) > 1 else "demo.cast"
    output_file = "demo.mp4"

    if len(sys.argv) > 2 and sys.argv[1] == "-o":
        output_file = sys.argv[2]
        cast_file = sys.argv[3] if len(sys.argv) > 3 else "demo.cast"

    success = create_mp4_from_cast(cast_file, output_file)
    sys.exit(0 if success else 1)
