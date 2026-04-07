"""KiCad Python API integration for placement updates.

Uses the official pcbnew module to read/write PCB placements with full validation.
Supports KiCad 6+ with version detection and compatibility checks.
"""

from __future__ import annotations

import logging
import platform
import subprocess
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def detect_kicad_version() -> tuple[int, bool] | None:
    """Detect installed KiCad version via CLI.

    Returns:
        (major_version, available) tuple, e.g., (8, True) or (6, True)
        None if KiCad is not installed or version cannot be determined
    """
    try:
        # Try kicad --version
        result = subprocess.run(
            ["kicad", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            # Parse output like "KiCad 8.0.0"
            version_str = result.stdout.strip()
            if "KiCad" in version_str or "kicad" in version_str:
                parts = version_str.split()
                for part in parts:
                    try:
                        major = int(part.split(".")[0])
                        if major >= 6:
                            log.info(f"KiCad {major} detected via CLI")
                            return (major, True)
                    except (ValueError, IndexError):
                        pass
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Try pcbnew module directly
    try:
        import pcbnew

        # pcbnew doesn't expose version cleanly, but presence indicates KiCad 6+
        log.info("KiCad pcbnew module available (6+)")
        return (6, True)
    except ImportError:
        pass

    return None


def check_kicad_available(min_version: int = 6) -> tuple[bool, str]:
    """Check if KiCad is installed and meets minimum version.

    Args:
        min_version: Minimum required KiCad major version (default 6)

    Returns:
        (available, message) tuple
    """
    os_name = platform.system()

    # Try to import pcbnew
    try:
        import pcbnew  # noqa: F401

        log.info(f"KiCad Python API available on {os_name}")
        return (True, "KiCad 6+ detected (pcbnew module available)")
    except ImportError:
        pass

    # Try CLI detection
    version_info = detect_kicad_version()
    if version_info:
        major, available = version_info
        if available and major >= min_version:
            return (True, f"KiCad {major} installed")
        else:
            return (False, f"KiCad {major} detected but version {min_version}+ required")

    # Not found
    if os_name == "Darwin":
        msg = (
            "KiCad not found. On macOS, install via:\n"
            "  brew install kicad\n"
            "Or download from https://kicad.org/download/macos/"
        )
    elif os_name == "Windows":
        msg = "KiCad not found. On Windows, download from:\n  https://kicad.org/download/windows/"
    else:
        msg = "KiCad not found. Install from:\n  https://kicad.org/download/"

    return (False, msg)


def update_board_placements(
    kicad_pcb_path: Path,
    placements: dict[str, dict[str, Any]],
    output_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Update PCB placements using KiCad pcbnew API.

    Args:
        kicad_pcb_path: Path to .kicad_pcb file
        placements: Dict mapping ref to {x, y, rotation, layer}
                   x/y in mm, rotation in degrees, layer in "front"/"back"
        output_path: Save to different file (default: overwrite original)
        dry_run: If True, don't write to disk, just report changes

    Returns:
        {
            "success": bool,
            "updated": [list of refs updated],
            "not_found": [list of refs not on board],
            "errors": [list of error messages],
            "message": summary string
        }
    """
    available, msg = check_kicad_available()
    if not available:
        return {
            "success": False,
            "updated": [],
            "not_found": [],
            "errors": [msg],
            "message": "KiCad API unavailable, cannot update placements",
        }

    try:
        import pcbnew
    except ImportError:
        return {
            "success": False,
            "updated": [],
            "not_found": [],
            "errors": ["pcbnew module not importable"],
            "message": "KiCad Python API not accessible",
        }

    try:
        # Load the board
        board = pcbnew.LoadBoard(str(kicad_pcb_path))
        if not board:
            return {
                "success": False,
                "updated": [],
                "not_found": [],
                "errors": [f"Failed to load {kicad_pcb_path}"],
                "message": "Could not open KiCad PCB file",
            }

        updated = []
        not_found = []
        errors = []

        # Update each placement
        for ref, placement_data in placements.items():
            footprint = board.FindFootprintByReference(ref)
            if not footprint:
                not_found.append(ref)
                continue

            try:
                x_mm = float(placement_data.get("x", 0))
                y_mm = float(placement_data.get("y", 0))
                rotation_deg = float(placement_data.get("rotation", 0))
                layer = placement_data.get("layer", "front").lower()

                # Convert mm to KiCad internal units (nm)
                x_nm = int(x_mm * 1_000_000)
                y_nm = int(y_mm * 1_000_000)

                # Set position
                footprint.SetPosition(pcbnew.VECTOR2I(x_nm, y_nm))

                # Set rotation (in tenths of degrees in KiCad)
                rotation_tenths = int(rotation_deg * 10)
                footprint.SetOrientation(pcbnew.EDA_ANGLE(rotation_tenths, pcbnew.TENTHS_OF_A_DEGREE))

                # Set layer
                if layer == "back" or layer == "bottom":
                    footprint.Flip(pcbnew.VECTOR2I(x_nm, y_nm), False)
                elif layer != "front" and layer != "top":
                    errors.append(f"{ref}: invalid layer '{layer}', keeping current")

                updated.append(ref)
                log.info(f"Updated {ref}: ({x_mm}, {y_mm}) mm, {rotation_deg}°, {layer}")

            except (ValueError, TypeError) as e:
                errors.append(f"{ref}: invalid placement data — {e}")
                not_found.append(ref)

        # Save if not dry-run
        if updated and not dry_run:
            output_file = output_path or kicad_pcb_path
            board.Save(str(output_file))
            log.info(f"Saved updated PCB to {output_file}")

        summary = f"Updated {len(updated)}/{len(placements)} placements"
        if not_found:
            summary += f", {len(not_found)} not found"
        if errors:
            summary += f", {len(errors)} errors"

        return {
            "success": len(errors) == 0 and len(updated) > 0,
            "updated": updated,
            "not_found": not_found,
            "errors": errors,
            "message": summary,
        }

    except Exception as e:
        log.exception(f"Error updating placements via pcbnew: {e}")
        return {
            "success": False,
            "updated": [],
            "not_found": [],
            "errors": [f"Exception during placement update: {str(e)}"],
            "message": f"Failed to update placements: {e}",
        }
