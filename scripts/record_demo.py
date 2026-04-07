"""Generate an asciinema .cast file by running demo commands and capturing output.

Works on Windows (no pty/fcntl required). Produces a standard v2 .cast file
that can be played with `asciinema play` or embedded on asciinema.org.

Usage:
    py scripts/record_demo.py -o demo_humidistat.cast
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

SPEC = "samples/zigbee_humidistat/zigbee_humidistat.yaml"

# Commands to record — (label, command_args, timeout)
DEMO_STEPS: list[tuple[str, list[str], int]] = [
    (
        "# Step 1: List available templates",
        ["list-templates"],
        15,
    ),
    (
        "# Step 2: Validate the design spec",
        ["validate", SPEC],
        60,
    ),
    (
        "# Step 3: Generate KiCad schematic + PCB",
        ["generate", SPEC, "--output", "samples/zigbee_humidistat/output", "--no-svg", "--no-require-valid"],
        120,
    ),
    (
        "# Step 4: Estimate component costs",
        ["cost-bom", SPEC, "--qty", "1,10,100"],
        120,
    ),
    (
        "# Step 5: Check signal integrity constraints",
        ["si-constraints", SPEC],
        60,
    ),
    (
        "# Step 6: Thermal analysis",
        ["thermal-analysis", SPEC],
        60,
    ),
    (
        "# Step 7: Optimize component placement",
        ["optimize-placement", SPEC, "--iterations", "1000", "--seed", "42"],
        60,
    ),
    (
        "# Step 8: Generate interactive placement viewer",
        ["placement-viewer", SPEC, "--output", "samples/zigbee_humidistat/output/viewer.html"],
        60,
    ),
    (
        "# Step 9: Suggest panel layout (50x40mm board, 100 qty)",
        ["panelize", "--board-width", "50", "--board-height", "40", "--qty", "100"],
        15,
    ),
    (
        "# Step 10: Generate 3D-printable enclosure",
        [
            "design-enclosure",
            "--board-width",
            "50",
            "--board-height",
            "40",
            "--component-height",
            "10",
            "--output",
            "samples/zigbee_humidistat/output/enclosure.scad",
        ],
        15,
    ),
    (
        "# Step 11: Export for JLCPCB assembly",
        ["export-jlcpcb", SPEC, "--output", "samples/zigbee_humidistat/output/jlcpcb"],
        60,
    ),
]

TYPING_SPEED = 0.03  # seconds per character
PAUSE_AFTER_COMMENT = 0.8
PAUSE_AFTER_OUTPUT = 1.5
PROMPT = "$ "


def _type_text(events: list, t: float, text: str, speed: float = TYPING_SPEED) -> float:
    """Simulate typing text character by character."""
    for ch in text:
        events.append([round(t, 4), "o", ch])
        t += speed
    return t


def _emit_output(events: list, t: float, text: str) -> float:
    """Emit output text (instant, line by line for readability)."""
    for line in text.split("\n"):
        events.append([round(t, 4), "o", line + "\r\n"])
        t += 0.02  # Small delay between lines for readability
    return t


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Record Circuit Weaver demo as .cast file")
    parser.add_argument("-o", "--output", default="demo_humidistat.cast", help="Output .cast file")
    args = parser.parse_args()

    events: list = []
    t = 0.0

    # Header comment
    t = _type_text(events, t, "", speed=0)
    events.append([round(t, 4), "o", "\r\n"])
    t += 0.3
    t = _type_text(events, t, "# Circuit Weaver Demo: Zigbee/BT Humidistat")
    events.append([round(t, 4), "o", "\r\n"])
    t += 0.5
    t = _type_text(events, t, "# Full pipeline: YAML spec -> fab-ready outputs + enclosure")
    events.append([round(t, 4), "o", "\r\n"])
    t += PAUSE_AFTER_COMMENT

    for label, cmd_args, timeout in DEMO_STEPS:
        # Show comment
        events.append([round(t, 4), "o", "\r\n"])
        t += 0.2
        t = _type_text(events, t, f"\033[1;36m{label}\033[0m")
        events.append([round(t, 4), "o", "\r\n"])
        t += PAUSE_AFTER_COMMENT

        # Show prompt and type command
        full_cmd = f"circuit-weaver {' '.join(cmd_args)}"
        events.append([round(t, 4), "o", f"\033[1;32m{PROMPT}\033[0m"])
        t += 0.1
        t = _type_text(events, t, full_cmd)
        events.append([round(t, 4), "o", "\r\n"])
        t += 0.3

        # Run the actual command and capture output
        print(f"Running: circuit-weaver {' '.join(cmd_args[:2])}...", file=sys.stderr)
        start = time.time()
        try:
            result = subprocess.run(
                [sys.executable, "-m", "circuit_weaver.mvp"] + cmd_args,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output = result.stdout or ""
            stderr = result.stderr or ""
            # Filter out noisy KiCad library detection lines
            output_lines = [
                line
                for line in (output + stderr).split("\n")
                if line.strip() and "Found local KiCad" not in line and "WARNING: Unknown component" not in line
            ]
            # Limit output to 30 lines for readability
            if len(output_lines) > 30:
                output_lines = output_lines[:28] + [f"  ... ({len(output_lines) - 28} more lines)"]
            filtered = "\n".join(output_lines)
        except subprocess.TimeoutExpired:
            filtered = "(timed out)"
        except Exception as e:
            filtered = f"(error: {e})"

        elapsed = time.time() - start
        t = _emit_output(events, t, filtered)
        t += PAUSE_AFTER_OUTPUT

    # Final message
    events.append([round(t, 4), "o", "\r\n"])
    t += 0.3
    t = _type_text(events, t, "\033[1;33m# Done! All outputs in samples/zigbee_humidistat/output/\033[0m")
    events.append([round(t, 4), "o", "\r\n"])
    t += 1.0

    # Write .cast file (asciicast v2 format)
    header = {
        "version": 2,
        "width": 120,
        "height": 35,
        "timestamp": int(time.time()),
        "title": "Circuit Weaver Demo: Zigbee/BT Humidistat",
        "env": {"SHELL": "/bin/bash", "TERM": "xterm-256color"},
    }

    output_path = Path(args.output)
    with output_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(header, ensure_ascii=False) + "\n")
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    print(f"Recorded {len(events)} events, {t:.1f}s duration -> {output_path}", file=sys.stderr)
    print(f"Play with: asciinema play {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
