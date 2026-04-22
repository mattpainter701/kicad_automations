"""Design workflow logging for circuit-weaver projects.

Tracks all tool calls, validations, generations, and errors during design wizard execution.
Enables proactive troubleshooting and resumption of incomplete designs.

Log format: JSON Lines (one JSON object per line, easy to parse and stream).
Log location: <project_root>/design.log
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DesignLogger:
    """Log circuit design workflow operations."""

    def __init__(self, project_dir: str | Path):
        """Initialize logger for a project directory.

        Args:
            project_dir: Root directory of the circuit design project.
        """
        self.project_dir = Path(project_dir)
        self.log_path = self.project_dir / "design.log"
        self.entries = []

        # Load existing log if present
        if self.log_path.exists():
            self._load_existing_log()

    def _load_existing_log(self) -> None:
        """Load existing design log entries.

        Per-line parsing so one malformed entry (e.g. a partial line from a
        prior crash) doesn't drop every subsequent entry from memory.
        """
        try:
            fh = open(self.log_path, "r", encoding="utf-8")
        except OSError as e:
            print(f"Warning: Could not open existing log: {e}", file=sys.stderr)
            return
        with fh as f:
            for lineno, raw in enumerate(f, start=1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    self.entries.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(
                        f"Warning: skipping malformed design.log line {lineno}: {e}",
                        file=sys.stderr,
                    )

    def _append_entry(self, entry: dict[str, Any]) -> None:
        """Append a single entry to the log file."""
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                json.dump(entry, f, ensure_ascii=False)
                f.write("\n")
            self.entries.append(entry)
        except Exception as e:
            print(f"Error writing to design log: {e}", file=sys.stderr)

    def log_step(self, step: int, description: str, user_input: dict[str, str] | None = None) -> None:
        """Log a wizard step completion.

        Args:
            step: Step number (1, 2, 3, etc.)
            description: Human-readable description of the step
            user_input: Dict of user responses captured in this step
        """
        entry = {
            "timestamp": _now_iso(),
            "type": "wizard_step",
            "step": step,
            "description": description,
            "user_input": user_input or {},
        }
        self._append_entry(entry)

    def log_cli_call(
        self,
        command: str,
        args: list[str],
        return_code: int,
        stdout: str = "",
        stderr: str = "",
        duration_sec: float = 0.0,
        generated_files: list[str] | None = None,
    ) -> None:
        """Log a CLI subcommand execution.

        Args:
            command: CLI command name (scaffold, validate, generate, etc.)
            args: Command arguments
            return_code: Process return code (0 = success)
            stdout: Standard output
            stderr: Standard error output
            duration_sec: Execution time in seconds
            generated_files: List of files created/modified
        """
        entry = {
            "timestamp": _now_iso(),
            "type": "cli_call",
            "command": command,
            "args": args,
            "return_code": return_code,
            "duration_sec": round(duration_sec, 2),
            "generated_files": generated_files or [],
            "success": return_code == 0,
        }

        # Include error output if present
        if stderr:
            entry["stderr"] = stderr[:500]  # Truncate to 500 chars
        if stdout and return_code != 0:
            entry["stdout_error"] = stdout[:500]  # Include output for debugging failures

        self._append_entry(entry)

    def log_validation(
        self,
        spec_file: str,
        passed: bool,
        errors: list[str] | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        """Log a validation check result.

        Args:
            spec_file: Path to the spec file validated
            passed: Whether validation passed
            errors: List of error messages
            warnings: List of warning messages
        """
        entry = {
            "timestamp": _now_iso(),
            "type": "validation",
            "spec_file": spec_file,
            "passed": passed,
            "error_count": len(errors or []),
            "warning_count": len(warnings or []),
            "errors": (errors or [])[:5],  # Include first 5 errors
            "warnings": (warnings or [])[:5],  # Include first 5 warnings
        }
        self._append_entry(entry)

    def log_research(
        self,
        query_phase: str,
        query: str,
        status: str,
        result_count: int = 0,
        backend: str = "",
        artifact_path: str = "",
    ) -> None:
        """Log a research-analyst query.

        Args:
            query_phase: Phase name (project_context, boost_converter, mcu, etc.)
            query: The query sent to Perplexity
            status: ok, timeout, error, no_api_key
            result_count: Number of results returned
            backend: Backend used for the research run (sonar-pro, standard)
            artifact_path: Path to the canonical saved research JSON file
        """
        entry = {
            "timestamp": _now_iso(),
            "type": "research",
            "phase": query_phase,
            "status": status,
            "result_count": result_count,
            "query_length": len(query),
        }
        if backend:
            entry["backend"] = backend
        if artifact_path:
            entry["artifact_path"] = artifact_path
        self._append_entry(entry)

    def log_part_lookup(
        self,
        mpn: str,
        source: str,
        status: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Log a part/model lookup attempt.

        Args:
            mpn: Manufacturer part number being looked up
            source: Lookup source (digikey, mouser, lcsc, spice_model, etc.)
            status: ok, not_found, timeout, error
            details: Additional info (price, stock, model_path, etc.)
        """
        entry = {
            "timestamp": _now_iso(),
            "type": "part_lookup",
            "mpn": mpn,
            "source": source,
            "status": status,
            "details": details or {},
        }
        self._append_entry(entry)

    def log_symbol_resolution(
        self,
        ref: str,
        mpn: str,
        status: str,
        pinout_source: str = "",
    ) -> None:
        """Log a symbol/pinout resolution attempt.

        Args:
            ref: Component reference designator (U1, R3, etc.)
            mpn: Manufacturer part number
            status: ok, stub, not_found, error
            pinout_source: How pinout was resolved (datasheet, library, stub, etc.)
        """
        entry = {
            "timestamp": _now_iso(),
            "type": "symbol_resolution",
            "ref": ref,
            "mpn": mpn,
            "status": status,
            "pinout_source": pinout_source,
        }
        self._append_entry(entry)

    def log_simulation(
        self,
        sim_type: str,
        target: str,
        status: str,
        metrics: dict[str, Any] | None = None,
        duration_sec: float = 0.0,
    ) -> None:
        """Log a circuit simulation result.

        Args:
            sim_type: Simulation type (tran, ac, dc, op)
            target: What was simulated (buck_U1, filter_C3_R5, etc.)
            status: ok, failed, skipped, timeout
            metrics: Extracted metrics (ripple_mv, phase_margin_deg, etc.)
            duration_sec: Simulation wall-clock time
        """
        entry = {
            "timestamp": _now_iso(),
            "type": "simulation",
            "sim_type": sim_type,
            "target": target,
            "status": status,
            "metrics": metrics or {},
            "duration_sec": round(duration_sec, 2),
        }
        self._append_entry(entry)

    def log_thermal(
        self,
        ref: str,
        tj_calc: float,
        tj_max: float,
        status: str,
    ) -> None:
        """Log a thermal analysis result for a component.

        Args:
            ref: Component reference designator
            tj_calc: Calculated junction temperature (degrees C)
            tj_max: Maximum junction temperature rating (degrees C)
            status: ok, warning, critical
        """
        entry = {
            "timestamp": _now_iso(),
            "type": "thermal",
            "ref": ref,
            "tj_calc": round(tj_calc, 1),
            "tj_max": round(tj_max, 1),
            "margin_deg": round(tj_max - tj_calc, 1),
            "status": status,
        }
        self._append_entry(entry)

    def log_erc_drc(
        self,
        check_type: str,
        file: str,
        errors: int,
        warnings: int,
        details: list[str] | None = None,
    ) -> None:
        """Log an ERC or DRC check result.

        Args:
            check_type: Check type (erc, drc, dfm)
            file: File that was checked
            errors: Number of errors found
            warnings: Number of warnings found
            details: First few violation descriptions
        """
        entry = {
            "timestamp": _now_iso(),
            "type": "erc_drc",
            "check_type": check_type,
            "file": file,
            "errors": errors,
            "warnings": warnings,
            "passed": errors == 0,
            "details": (details or [])[:5],
        }
        self._append_entry(entry)

    def log_scoring(
        self,
        dimension: str,
        score: float,
        grade: str,
        gaps: list[str] | None = None,
    ) -> None:
        """Log a design scoring result.

        Args:
            dimension: Scoring dimension (power, signal, thermal, overall, etc.)
            score: Numeric score (0-100)
            grade: Letter grade (A-F)
            gaps: List of gaps or improvement areas
        """
        entry = {
            "timestamp": _now_iso(),
            "type": "scoring",
            "dimension": dimension,
            "score": round(score, 1),
            "grade": grade,
            "gaps": (gaps or [])[:5],
        }
        self._append_entry(entry)

    def log_sourcing(
        self,
        mpn: str,
        supplier: str,
        status: str,
        price: float | None = None,
        stock: int | None = None,
    ) -> None:
        """Log a sourcing/availability check.

        Args:
            mpn: Manufacturer part number
            supplier: Supplier name (digikey, mouser, lcsc, etc.)
            status: ok, out_of_stock, not_found, error
            price: Unit price if available
            stock: Stock quantity if available
        """
        entry: dict[str, Any] = {
            "timestamp": _now_iso(),
            "type": "sourcing",
            "mpn": mpn,
            "supplier": supplier,
            "status": status,
        }
        if price is not None:
            entry["price"] = round(price, 4)
        if stock is not None:
            entry["stock"] = stock
        self._append_entry(entry)

    def log_generation(
        self,
        artifact_type: str,
        path: str,
        status: str,
        duration_sec: float = 0.0,
    ) -> None:
        """Log an artifact generation event.

        Args:
            artifact_type: Type of artifact (schematic, pcb, bom, report, netlist, etc.)
            path: Output file path
            status: ok, failed, skipped
            duration_sec: Generation time
        """
        entry = {
            "timestamp": _now_iso(),
            "type": "generation",
            "artifact_type": artifact_type,
            "path": path,
            "status": status,
            "duration_sec": round(duration_sec, 2),
        }
        self._append_entry(entry)

    def log_error(
        self,
        operation: str,
        error: str,
        traceback: str = "",
    ) -> None:
        """Log a structured error.

        Args:
            operation: Operation that failed (validate, generate, simulate, etc.)
            error: Error message
            traceback: Optional traceback string
        """
        entry: dict[str, Any] = {
            "timestamp": _now_iso(),
            "type": "error",
            "operation": operation,
            "error": error[:500],
        }
        if traceback:
            entry["traceback"] = traceback[:1000]
        self._append_entry(entry)

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of the design workflow so far.

        Returns:
            Dict with workflow state, files, validation, simulation, thermal,
            scoring, ERC/DRC, errors, and warnings aggregated from all event types.
        """
        if not self.entries:
            return {"status": "empty", "entries": 0}

        last_step = 0
        files = set()
        validation_passed = None
        errors: list[str] = []
        warnings: list[str] = []
        sim_count = 0
        sim_passed = 0
        sim_skipped = 0
        thermal_warnings = 0
        thermal_critical = 0
        erc_errors = 0
        erc_warnings = 0
        scoring: dict[str, Any] = {}
        part_lookups = 0
        part_failures = 0

        for entry in self.entries:
            etype = entry.get("type")

            if etype == "wizard_step":
                last_step = max(last_step, entry.get("step", 0))

            elif etype == "cli_call":
                files.update(entry.get("generated_files", []))
                if not entry.get("success"):
                    errors.append(f"{entry.get('command')}: {entry.get('stderr', 'unknown error')}")

            elif etype == "validation":
                validation_passed = entry.get("passed")
                errors.extend(entry.get("errors", []))
                warnings.extend(entry.get("warnings", []))

            elif etype == "research":
                if entry.get("status") != "ok":
                    warnings.append(f"Research phase '{entry.get('phase')}': {entry.get('status')}")

            elif etype == "simulation":
                sim_count += 1
                if entry.get("status") == "ok":
                    sim_passed += 1
                elif entry.get("status") == "skipped":
                    sim_skipped += 1

            elif etype == "thermal":
                if entry.get("status") == "warning":
                    thermal_warnings += 1
                elif entry.get("status") == "critical":
                    thermal_critical += 1

            elif etype == "erc_drc":
                erc_errors += entry.get("errors", 0)
                erc_warnings += entry.get("warnings", 0)

            elif etype == "scoring":
                scoring[entry.get("dimension", "unknown")] = {
                    "score": entry.get("score"),
                    "grade": entry.get("grade"),
                }

            elif etype == "part_lookup":
                part_lookups += 1
                if entry.get("status") not in ("ok",):
                    part_failures += 1

            elif etype == "generation":
                if entry.get("status") == "ok":
                    files.add(entry.get("path", ""))

            elif etype == "error":
                errors.append(f"{entry.get('operation')}: {entry.get('error', 'unknown')}")

        return {
            "status": "in_progress" if last_step > 0 else "empty",
            "last_step": last_step,
            "entries": len(self.entries),
            "files_generated": sorted(f for f in files if f),
            "validation_passed": validation_passed,
            "simulation": {"total": sim_count, "passed": sim_passed, "skipped": sim_skipped} if sim_count else None,
            "thermal": {"warnings": thermal_warnings, "critical": thermal_critical}
            if (thermal_warnings or thermal_critical)
            else None,
            "erc_drc": {"errors": erc_errors, "warnings": erc_warnings} if (erc_errors or erc_warnings) else None,
            "scoring": scoring or None,
            "part_lookups": {"total": part_lookups, "failures": part_failures} if part_lookups else None,
            "errors": errors[:10],
            "warnings": warnings[:10],
            "log_path": str(self.log_path),
        }

    def print_summary(self) -> None:
        """Print a human-readable summary of the design workflow."""
        summary = self.get_summary()

        if summary["status"] == "empty":
            print("No design workflow recorded yet.")
            return

        print("\n" + "=" * 72)
        print("Design Workflow Summary")
        print("=" * 72)
        print(f"Status:      {summary['status'].upper()}")
        print(f"Last step:   {summary['last_step']}")
        print(f"Log entries: {summary['entries']}")
        print(f"Files:       {len(summary['files_generated'])} generated")

        if summary["validation_passed"] is not None:
            status = "PASSED" if summary["validation_passed"] else "FAILED"
            print(f"Validation:  {status}")

        sim = summary.get("simulation")
        if sim:
            print(
                f"Simulation:  {sim['passed']}/{sim['total']} passed"
                + (f", {sim['skipped']} skipped" if sim["skipped"] else "")
            )

        thermal = summary.get("thermal")
        if thermal:
            parts = []
            if thermal["warnings"]:
                parts.append(f"{thermal['warnings']} warnings")
            if thermal["critical"]:
                parts.append(f"{thermal['critical']} critical")
            print(f"Thermal:     {', '.join(parts)}")

        erc = summary.get("erc_drc")
        if erc:
            print(f"ERC/DRC:     {erc['errors']} errors, {erc['warnings']} warnings")

        scoring = summary.get("scoring")
        if scoring:
            overall = scoring.get("overall")
            if overall:
                print(f"Score:       {overall['score']}/100 ({overall['grade']})")

        parts = summary.get("part_lookups")
        if parts:
            print(f"Parts:       {parts['total']} lookups, {parts['failures']} failures")

        if summary["errors"]:
            print(f"\nErrors ({len(summary['errors'])} total):")
            for err in summary["errors"]:
                print(f"  - {err[:70]}")

        if summary["warnings"]:
            print(f"\nWarnings ({len(summary['warnings'])} total):")
            for warn in summary["warnings"]:
                print(f"  - {warn[:70]}")

        print(f"\nLog: {summary['log_path']}")
        print("=" * 72 + "\n")
