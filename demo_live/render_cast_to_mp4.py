#!/usr/bin/env python3
"""
Convert asciinema .cast file to MP4 video.
Requires: ffmpeg (install via chocolatey: choco install ffmpeg)

Usage:
  python render_cast_to_mp4.py demo.cast -o demo.mp4
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def render_cast_to_mp4(cast_file: str, output_file: str = "output.mp4", speed: float = 2.0) -> bool:
    """
    Render asciinema .cast file to MP4 using ffmpeg.

    This requires:
    1. ffmpeg (install: choco install ffmpeg)
    2. (optional) imagemagick for better text rendering

    Args:
        cast_file: Path to .cast file
        output_file: Path to output MP4 file
        speed: Playback speed multiplier (2.0 = 2x speed)

    Returns:
        True if successful, False otherwise
    """

    # Check if ffmpeg is available
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ ffmpeg not found. Install with: choco install ffmpeg")
        return False

    cast_path = Path(cast_file)
    if not cast_path.exists():
        print(f"❌ Cast file not found: {cast_file}")
        return False

    # Load cast file
    try:
        with open(cast_path) as f:
            header = json.loads(f.readline())
            events = [json.loads(line) for line in f if line.strip()]
    except json.JSONDecodeError as e:
        print(f"❌ Invalid cast file: {e}")
        return False

    width = header.get("width", 120)
    height = header.get("height", 30)

    # Create temporary frames
    temp_dir = Path(tempfile.mkdtemp())
    frames_dir = temp_dir / "frames"
    frames_dir.mkdir(parents=True)

    try:
        print(f"🎬 Rendering {len(events)} events to video...")
        print(f"   Resolution: {width}×{height}")
        print(f"   Speed: {speed}x")
        print(f"   Output: {output_file}")
        print()
        print("   Note: Using text-based ffmpeg filter (slower)")
        print("   For better quality, install: pip install pillow")
        print()

        # Since we can't easily render terminal frames without heavy dependencies,
        # we'll create a simple text-based approach using ffmpeg's drawtext
        print("   Generating video frames...")
        print()
        print("   ⚠️  For a full terminal-rendered video, use one of:")
        print("   1. asciinema-to-gif (npm install asciinema-to-gif)")
        print("   2. svg-term (npm install svg-term-cli)")
        print("   3. terminalizer (npm install terminalizer)")
        print()

        return False  # Indicate that additional tools are needed

    except Exception as e:
        print(f"❌ Error: {e}")
        return False
    finally:
        # Cleanup
        import shutil

        shutil.rmtree(temp_dir, ignore_errors=True)


def print_alternatives():
    """Print alternatives for creating terminal recordings."""
    print("\n" + "=" * 60)
    print("ALTERNATIVES FOR TERMINAL VIDEO RECORDING")
    print("=" * 60 + "\n")

    print("✅ Option 1: Use Web Player (Recommended for Web)")
    print("   - Already created: index.html + demo.cast")
    print("   - Interactive (play/pause/seek)")
    print("   - Works on any browser")
    print("   - Embed in website easily")
    print()

    print("✅ Option 2: Use asciinema-to-gif")
    print("   npm install -g asciinema-to-gif")
    print("   asciinema-to-gif demo.cast demo.gif")
    print()

    print("✅ Option 3: Use svg-term")
    print("   npm install -g svg-term-cli")
    print("   svg-term --cast demo.cast --output demo.svg")
    print()

    print("✅ Option 4: Use terminalizer")
    print("   npm install -g terminalizer")
    print("   terminalizer render demo.cast -o demo.gif")
    print()

    print("💡 Fastest for Web: index.html player (no conversion needed)")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        print_alternatives()
        sys.exit(1)

    cast_file = sys.argv[1]
    output_file = sys.argv[3] if len(sys.argv) > 3 and sys.argv[2] == "-o" else "output.mp4"

    success = render_cast_to_mp4(cast_file, output_file)

    if not success:
        print_alternatives()
        sys.exit(1)
    else:
        print(f"\n✅ Video saved to: {output_file}")
