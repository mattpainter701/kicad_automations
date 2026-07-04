"""Freerouting PCB autorouting integration.

Optional best-effort wrapper around Freerouting for automated PCB routing.
Simple circuits route 100% automatically; complex circuits ~90%.

The wrapper fails closed on boards that cannot be routed: the engine's own
``*_placement.kicad_pcb`` export is a placement *preview* with zero pads
(KiCad forward-annotation is the authoritative source of pads), so routing
it would silently produce garbage. ``preflight_pcb`` detects that case and
any other pad-less/net-less board before Freerouting is ever invoked.

Routing pipeline (T240):

1. Preflight the board (pads, nets, placement-preview marker).
2. When ``kicad-cli`` is available, export a Specctra DSN
   (``kicad-cli pcb export specctra``) and run Freerouting on it
   (``-de board.dsn -do board.ses``). The resulting ``.ses`` session file
   is imported in KiCad via *File → Import → Specctra Session*.
3. Without ``kicad-cli``, fall back to invoking Freerouting directly on
   the ``.kicad_pcb`` (some builds accept it).

Freerouting installation:
  Homebrew: brew install freerouting
  Manual: Download from https://github.com/freerouting/freerouting/releases

Usage:
    from circuit_weaver.autoroute import autoroute_pcb
    result = autoroute_pcb("board.kicad_pcb", effort="medium")
    print(result["status"])  # "ok" or "error"
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Freerouting "-mp" max-passes budget per effort level.
_EFFORT_PASSES = {
    "fast": 10,
    "medium": 25,
    "high": 99,
}

_PREVIEW_GENERATOR_RE = re.compile(r'\(generator\s+"[^"]*placement_preview[^"]*"\)')
_PAD_RE = re.compile(r"\(pad\s")
_FOOTPRINT_RE = re.compile(r"\(footprint\s")
# Board-level net declarations: (net 1 "GND") — net 0 is the unnamed net.
_NET_DECL_RE = re.compile(r'\(net\s+(\d+)\s+"([^"]*)"\)')


def preflight_pcb(pcb_path: str | Path) -> dict[str, Any]:
    """Check that a .kicad_pcb is actually routable before autorouting.

    Returns ``{"routable": bool, "reason": str, "stats": {...}}``. A board
    is routable when it has at least one footprint pad and at least one
    named net. The engine's own placement-preview export (zero pads by
    design) is called out with a specific remediation message.
    """
    path = Path(pcb_path)
    text = path.read_text(encoding="utf-8", errors="replace")

    footprints = len(_FOOTPRINT_RE.findall(text))
    pads = len(_PAD_RE.findall(text))
    named_nets = {name for num, name in _NET_DECL_RE.findall(text) if name and num != "0"}
    is_preview = bool(_PREVIEW_GENERATOR_RE.search(text))

    stats = {
        "footprints": footprints,
        "pads": pads,
        "nets": len(named_nets),
        "placement_preview": is_preview,
    }

    if is_preview:
        return {
            "routable": False,
            "reason": (
                "This file is a Circuit Weaver placement preview — it has no pads "
                "by design and cannot be routed. Open the generated schematic in "
                "KiCad, forward-annotate to a real PCB (Tools → Update PCB from "
                "Schematic), then autoroute that board."
            ),
            "stats": stats,
        }
    if footprints == 0:
        return {
            "routable": False,
            "reason": "Board has no footprints — nothing to route.",
            "stats": stats,
        }
    if pads == 0:
        return {
            "routable": False,
            "reason": (
                "Board footprints have no pads — routing would produce nothing. "
                "Forward-annotate from the schematic in KiCad to populate real pads."
            ),
            "stats": stats,
        }
    if not named_nets:
        return {
            "routable": False,
            "reason": (
                "Board declares no named nets — there is no connectivity to route. "
                "Forward-annotate from the schematic in KiCad first."
            ),
            "stats": stats,
        }
    return {"routable": True, "reason": "", "stats": stats}


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


def _find_kicad_cli() -> str | None:
    """Locate the kicad-cli executable for Specctra DSN export."""
    return shutil.which("kicad-cli")


def _parse_routing_stats(output_text: str) -> dict[str, int]:
    """Best-effort extraction of trace/via/incomplete counts from Freerouting output."""
    stats = {"traces": 0, "vias": 0, "incomplete": 0}
    trace_match = re.search(r"(\d+)\s+traces?", output_text, re.IGNORECASE)
    via_match = re.search(r"(\d+)\s+vias?", output_text, re.IGNORECASE)
    incomplete_match = re.search(r"(\d+)\s+(?:incompletes?|unrouted)", output_text, re.IGNORECASE)
    if trace_match:
        stats["traces"] = int(trace_match.group(1))
    if via_match:
        stats["vias"] = int(via_match.group(1))
    if incomplete_match:
        stats["incomplete"] = int(incomplete_match.group(1))
    return stats


def export_dsn(pcb_path: str | Path, dsn_path: str | Path, timeout_seconds: float = 120) -> dict[str, Any]:
    """Export a Specctra DSN from a .kicad_pcb via kicad-cli.

    Returns {"status": "ok"|"error", "dsn_path": str, "message": str}.
    """
    kicad_cli = _find_kicad_cli()
    if kicad_cli is None:
        return {
            "status": "error",
            "message": "kicad-cli not found — install KiCad 7+ or route the .kicad_pcb directly.",
        }
    try:
        result = subprocess.run(
            [kicad_cli, "pcb", "export", "specctra", "-o", str(dsn_path), str(pcb_path)],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "kicad-cli specctra export timed out"}
    if result.returncode != 0 or not Path(dsn_path).exists():
        return {
            "status": "error",
            "message": f"kicad-cli specctra export failed:\n{result.stderr.strip()}",
        }
    return {"status": "ok", "dsn_path": str(dsn_path), "message": "DSN exported"}


def autoroute_pcb(
    pcb_path: str,
    output_path: str | None = None,
    effort: str = "medium",
    timeout_seconds: float = 300,
) -> dict[str, Any]:
    """Route a KiCad PCB using Freerouting.

    Args:
        pcb_path: Path to .kicad_pcb file (must be a real board with pads
            and nets — placement previews fail the preflight check)
        output_path: Where to write the routed output. With the DSN/SES
            pipeline this is the ``.ses`` session file (import in KiCad via
            File → Import → Specctra Session); with the legacy direct
            invocation it is a routed ``.kicad_pcb``.
        effort: "fast" | "medium" | "high" — Freerouting optimization-pass
            budget.
        timeout_seconds: routing timeout.

    Returns:
        {
            "status": "ok" | "error",
            "pcb_path": str (output path if success),
            "message": str,
            "preflight": {...},
            "stats": {
                "traces": int,
                "vias": int,
                "incomplete": int,
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

    if effort not in _EFFORT_PASSES:
        return {
            "status": "error",
            "message": f"Unknown effort '{effort}' — pick one of {sorted(_EFFORT_PASSES)}",
        }

    preflight = preflight_pcb(pcb)
    if not preflight["routable"]:
        return {
            "status": "error",
            "message": f"Board failed routing preflight: {preflight['reason']}",
            "preflight": preflight,
        }

    # Check if Freerouting is installed
    jar = _find_freerouting_jar()
    if jar is None:
        return {
            "status": "error",
            "message": (
                "Freerouting not found. Install with:\n"
                "  Homebrew: brew install freerouting\n"
                "  Manual: https://github.com/freerouting/freerouting/releases\n"
                "\nAlternatively, route manually in KiCad using placer_hints.json for guidance."
            ),
            "preflight": preflight,
        }

    log.info("Routing %s with Freerouting (effort=%s)...", pcb.name, effort)
    start_time = time.perf_counter()
    passes = _EFFORT_PASSES[effort]

    kicad_cli = _find_kicad_cli()
    try:
        if kicad_cli:
            # DSN/SES pipeline: the only officially supported Freerouting flow.
            dsn_path = pcb.parent / f"{pcb.stem}.dsn"
            ses_path = Path(output_path) if output_path else pcb.parent / f"{pcb.stem}.ses"
            exported = export_dsn(pcb, dsn_path, timeout_seconds=min(timeout_seconds, 120))
            if exported["status"] != "ok":
                return {**exported, "preflight": preflight}
            cmd = [
                "java",
                "-jar",
                str(jar),
                "-de",
                str(dsn_path),
                "-do",
                str(ses_path),
                "-mp",
                str(passes),
            ]
            output_file = ses_path
            import_hint = (
                f"Import the session in KiCad: File → Import → Specctra Session → {ses_path.name}"
            )
        else:
            # Legacy fallback — some Freerouting builds accept .kicad_pcb directly.
            if output_path is None:
                output_path = str(pcb.parent / f"{pcb.stem}_routed.kicad_pcb")
            cmd = [
                "java",
                "-jar",
                str(jar),
                "-dr",
                str(pcb),
                "-out",
                str(output_path),
                "-mp",
                str(passes),
            ]
            output_file = Path(output_path)
            import_hint = ""

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )

        elapsed = time.perf_counter() - start_time

        if result.returncode != 0:
            log.warning("Freerouting failed: %s", result.stderr)
            return {
                "status": "error",
                "message": f"Freerouting routing failed:\n{result.stderr}",
                "preflight": preflight,
            }

        output_text = result.stdout + result.stderr
        stats = _parse_routing_stats(output_text) if "routed" in output_text.lower() else {
            "traces": 0,
            "vias": 0,
            "incomplete": 0,
        }
        stats["routing_time_seconds"] = elapsed

        log.info(
            "Routing complete in %.1fs: %d traces, %d vias, %d incomplete",
            elapsed,
            stats["traces"],
            stats["vias"],
            stats["incomplete"],
        )

        message = (
            f"Routed successfully in {elapsed:.1f}s: "
            f"{stats['traces']} traces, {stats['vias']} vias"
        )
        if stats["incomplete"]:
            message += f", {stats['incomplete']} incomplete (re-run with --effort high)"
        if import_hint:
            message += f"\n{import_hint}"

        return {
            "status": "ok",
            "pcb_path": str(output_file),
            "message": message,
            "preflight": preflight,
            "stats": stats,
        }

    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "message": f"Freerouting routing timed out after {timeout_seconds:.0f} seconds",
            "preflight": preflight,
        }
    except Exception as e:
        log.exception("Freerouting integration error")
        return {
            "status": "error",
            "message": f"Freerouting error: {e}",
            "preflight": preflight,
        }
