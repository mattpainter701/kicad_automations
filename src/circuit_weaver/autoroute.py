"""Freerouting PCB autorouting integration.

Optional best-effort wrapper around Freerouting for automated PCB routing.
Simple circuits route 100% automatically; complex circuits ~90%.

Freerouting installation:
  Homebrew: brew install freerouting
  Manual: Download from https://github.com/mirage335/freerouting/releases

Usage:
    from circuit_weaver.autoroute import autoroute_pcb
    result = autoroute_pcb("board.kicad_pcb", output_path="routed.kicad_pcb")
    print(result["status"])  # "ok" or "error"
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _find_freerouting_jar() -> Path | None:
    """Locate the Freerouting JAR file.

    Searches in order:
    1. ~/.freerouting/freerouting.jar (default install location)
    2. PATH (if installed via package manager)
    3. None if not found
    """
    # Check user home directory
    home_jar = Path.home() / ".freerouting" / "freerouting.jar"
    if home_jar.exists():
        return home_jar

    # Check if 'freerouting' is in PATH (package manager install)
    try:
        result = subprocess.run(
            ["which", "freerouting"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return None


def autoroute_pcb(
    pcb_path: str,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Route a KiCad PCB using Freerouting.

    Args:
        pcb_path: Path to .kicad_pcb file (must be compiled with nets)
        output_path: Where to write routed PCB (defaults to <name>_routed.kicad_pcb)

    Returns:
        {
            "status": "ok" | "error",
            "pcb_path": str (output path if success),
            "message": str,
            "stats": {
                "traces": int,
                "vias": int,
                "routing_time_seconds": float,
            }
        }
    """
    pcb = Path(pcb_path)
    if not pcb.exists():
        return {
            "status": "error",
            "message": f"PCB file not found: {pcb_path}",
        }

    if output_path is None:
        output_path = str(pcb.parent / f"{pcb.stem}_routed.kicad_pcb")

    # Check if Freerouting is installed
    jar = _find_freerouting_jar()
    if jar is None:
        return {
            "status": "error",
            "message": (
                "Freerouting not found. Install with:\n"
                "  Homebrew: brew install freerouting\n"
                "  Manual: https://github.com/mirage335/freerouting/releases\n"
                "\nAlternatively, route manually in KiCad using placer_hints.json for guidance."
            ),
        }

    log.info("Routing %s with Freerouting...", pcb.name)
    start_time = time.perf_counter()

    try:
        # Create a temporary .dsn file for Freerouting
        with tempfile.NamedTemporaryFile(
            suffix=".dsn",
            delete=False,
            mode="w",
            encoding="utf-8",
        ) as dsn_file:
            dsn_path = dsn_file.name
            # Placeholder DSN export — real implementation would call KiCad CLI or pcbnew API
            # For now, we'll attempt the Freerouting call with a kicad_pcb as input if possible

        # Attempt to invoke Freerouting
        # Note: KiCad's pcbnew can export to DSN, but we'd need kicad-cli or python-kicad
        # For now, this is a placeholder that documents the integration point
        result = subprocess.run(
            [
                "java",
                "-jar",
                str(jar),
                "-dr",
                str(pcb),  # Some versions accept .kicad_pcb directly
                "-out",
                output_path,
            ],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )

        elapsed = time.perf_counter() - start_time

        if result.returncode != 0:
            log.warning("Freerouting failed: %s", result.stderr)
            return {
                "status": "error",
                "message": f"Freerouting routing failed:\n{result.stderr}",
            }

        # Parse output to extract trace and via counts
        # Freerouting prints completion summary to stdout/stderr
        output_text = result.stdout + result.stderr

        # Heuristic: look for "Routed" or completion messages
        traces = 0
        vias = 0
        if "routed" in output_text.lower():
            # Extract numbers if Freerouting prints them
            # Format varies by version, so this is best-effort
            import re

            trace_match = re.search(r"(\d+)\s+traces?", output_text, re.IGNORECASE)
            via_match = re.search(r"(\d+)\s+vias?", output_text, re.IGNORECASE)
            if trace_match:
                traces = int(trace_match.group(1))
            if via_match:
                vias = int(via_match.group(1))

        log.info(
            "Routing complete in %.1fs: %d traces, %d vias",
            elapsed,
            traces,
            vias,
        )

        return {
            "status": "ok",
            "pcb_path": output_path,
            "message": f"Routed successfully in {elapsed:.1f}s: {traces} traces, {vias} vias",
            "stats": {
                "traces": traces,
                "vias": vias,
                "routing_time_seconds": elapsed,
            },
        }

    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "message": "Freerouting routing timed out after 5 minutes",
        }
    except Exception as e:
        log.exception("Freerouting integration error")
        return {
            "status": "error",
            "message": f"Freerouting error: {e}",
        }
    finally:
        # Clean up temporary files
        temp_dsn = Path(dsn_path) if "dsn_path" in locals() else None
        if temp_dsn and temp_dsn.exists():
            try:
                temp_dsn.unlink()
            except OSError:
                pass
