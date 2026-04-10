"""ngspice simulation runner for circuit-weaver.

Runs ngspice on generated .cir netlists, parses results, and extracts
domain-specific metrics. Follows the erc_runner.py pattern for graceful
degradation when ngspice is not installed.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SimulationResult:
    """Structured result from a SPICE simulation."""

    status: str  # "ok", "failed", "skipped", "timeout"
    sim_type: str = ""  # "tran", "ac", "dc", "op"
    raw_file: str | None = None
    traces: dict[str, list[float]] = field(default_factory=dict)
    time_axis: list[float] | None = None
    freq_axis: list[float] | None = None
    metrics: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    duration_sec: float = 0.0
    skip_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "sim_type": self.sim_type,
            "raw_file": self.raw_file,
            "trace_names": list(self.traces.keys()),
            "trace_count": len(self.traces),
            "metrics": self.metrics,
            "warnings": self.warnings,
            "duration_sec": round(self.duration_sec, 2),
            "skip_reason": self.skip_reason,
        }


def _find_ngspice() -> str | None:
    """Locate ngspice binary on PATH.

    Returns the path string if found, None otherwise.
    """
    path = shutil.which("ngspice")
    return path


def _parse_raw_ascii(raw_path: Path) -> tuple[dict[str, list[float]], list[str]]:
    """Parse ngspice ASCII .raw output file into traces.

    Returns:
        (traces dict, variable names list)
    """
    content = raw_path.read_text(encoding="utf-8", errors="replace")
    traces: dict[str, list[float]] = {}
    var_names: list[str] = []
    in_values = False

    for line in content.splitlines():
        line = line.strip()

        if line.startswith("No. Variables:"):
            pass  # n_vars parsed but not needed for trace extraction
        elif line.startswith("No. Points:"):
            pass  # n_points parsed but not needed for trace extraction
        elif line.startswith("Variables:"):
            continue
        elif re.match(r"^\d+\t", line) and not in_values:
            # Variable definition line: "0\ttime\ttime"
            parts = line.split("\t")
            if len(parts) >= 2:
                name = parts[1].strip()
                var_names.append(name)
                traces[name] = []
        elif line == "Values:":
            in_values = True
        elif in_values and line:
            # Data values
            parts = line.split()
            for i, val_str in enumerate(parts):
                try:
                    val = float(val_str.replace(",", ""))
                    if i < len(var_names):
                        traces[var_names[i]].append(val)
                except (ValueError, IndexError):
                    pass

    return traces, var_names


def _extract_metrics(
    traces: dict[str, list[float]],
    sim_type: str,
    params: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Extract domain-specific metrics from simulation traces.

    For transient: ripple_mv, settling_time_us, overshoot_pct, avg_voltage
    For AC: bandwidth_hz (placeholder)
    For DC: output voltage at operating point
    """
    metrics: dict[str, float] = {}
    params = params or {}

    if sim_type == "tran":
        # Look for output voltage traces (V(vout), V(out), V(3v3), etc.)
        for name, values in traces.items():
            name_lower = name.lower()
            if not values:
                continue

            if any(kw in name_lower for kw in ("vout", "v_out", "3v3", "3p3", "1v8", "5v")):
                # Compute ripple: skip first 20% (startup transient)
                start_idx = max(1, len(values) // 5)
                steady = values[start_idx:]
                if steady:
                    vmin = min(steady)
                    vmax = max(steady)
                    ripple_mv = (vmax - vmin) * 1000
                    avg = sum(steady) / len(steady)
                    metrics[f"{name}_ripple_mv"] = round(ripple_mv, 2)
                    metrics[f"{name}_avg_v"] = round(avg, 4)
                break

        # Time axis info
        time_trace = traces.get("time", [])
        if time_trace:
            metrics["sim_duration_s"] = round(time_trace[-1] - time_trace[0], 6) if len(time_trace) > 1 else 0.0

    elif sim_type == "ac":
        # Placeholder for AC metrics
        for name, values in traces.items():
            if values:
                metrics[f"{name}_points"] = len(values)

    elif sim_type == "op" or sim_type == "dc":
        # Report all node voltages/currents
        for name, values in traces.items():
            if values:
                metrics[name] = round(values[-1], 6)

    return metrics


def run_simulation(
    netlist: str | Path,
    *,
    sim_type: str = "tran",
    timeout: int = 120,
    working_dir: str | Path | None = None,
) -> SimulationResult:
    """Run ngspice on a netlist and parse results.

    Degrades gracefully:
    - Returns status="skipped" if ngspice not installed
    - Returns status="failed" on timeout or parse error
    - Returns status="ok" with parsed traces on success

    Args:
        netlist: Path to .cir netlist file.
        sim_type: Simulation type hint for metric extraction.
        timeout: Maximum seconds to wait for ngspice.
        working_dir: Working directory for ngspice (default: netlist parent).

    Returns:
        SimulationResult with parsed traces and metrics.
    """
    netlist = Path(netlist)
    t0 = time.time()

    ngspice = _find_ngspice()
    if ngspice is None:
        return SimulationResult(
            status="skipped",
            sim_type=sim_type,
            skip_reason="ngspice not installed. Install ngspice to enable circuit simulation.",
        )

    if not netlist.exists():
        return SimulationResult(
            status="failed",
            sim_type=sim_type,
            skip_reason=f"Netlist not found: {netlist}",
        )

    wdir = Path(working_dir) if working_dir else netlist.parent

    try:
        # Run ngspice in batch mode
        proc = subprocess.run(
            [ngspice, "-b", str(netlist)],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(wdir),
        )

        duration = time.time() - t0

        # Check for raw file output
        raw_file = wdir / "results.raw"
        if not raw_file.exists():
            # Try default output name
            raw_file = netlist.with_suffix(".raw")

        warnings = []
        if proc.stderr:
            for line in proc.stderr.splitlines():
                if "warning" in line.lower() or "error" in line.lower():
                    warnings.append(line.strip())

        if raw_file.exists() and raw_file.stat().st_size > 0:
            try:
                traces, var_names = _parse_raw_ascii(raw_file)
                metrics = _extract_metrics(traces, sim_type)

                result = SimulationResult(
                    status="ok",
                    sim_type=sim_type,
                    raw_file=str(raw_file),
                    traces=traces,
                    time_axis=traces.get("time"),
                    freq_axis=traces.get("frequency"),
                    metrics=metrics,
                    warnings=warnings[:10],
                    duration_sec=duration,
                )
            except Exception as exc:
                result = SimulationResult(
                    status="failed",
                    sim_type=sim_type,
                    skip_reason=f"Failed to parse simulation output: {exc}",
                    warnings=warnings[:10],
                    duration_sec=duration,
                )
        else:
            result = SimulationResult(
                status="failed",
                sim_type=sim_type,
                skip_reason="ngspice produced no output file",
                warnings=warnings[:10],
                duration_sec=duration,
            )

    except subprocess.TimeoutExpired:
        result = SimulationResult(
            status="timeout",
            sim_type=sim_type,
            skip_reason=f"ngspice timed out after {timeout}s",
            duration_sec=time.time() - t0,
        )
    except OSError as exc:
        result = SimulationResult(
            status="failed",
            sim_type=sim_type,
            skip_reason=f"Failed to run ngspice: {exc}",
            duration_sec=time.time() - t0,
        )

    # Log to design.log
    from .logging_bridge import get_design_logger

    dl = get_design_logger()
    if dl:
        dl.log_simulation(
            sim_type=sim_type,
            target=str(netlist.stem),
            status=result.status,
            metrics=result.metrics,
            duration_sec=result.duration_sec,
        )

    return result
