"""Design workflow logging for circuit-weaver projects.

Tracks all tool calls, validations, generations, and errors during design wizard execution.
Enables proactive troubleshooting and resumption of incomplete designs.

Log format: JSON Lines (one JSON object per line, easy to parse and stream).
Log location: <project_root>/design.log
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


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
        """Load existing design log entries."""
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        self.entries.append(json.loads(line))
        except Exception as e:
            print(f"Warning: Could not load existing log: {e}", file=sys.stderr)

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
            "timestamp": datetime.utcnow().isoformat(),
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
            "timestamp": datetime.utcnow().isoformat(),
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
            "timestamp": datetime.utcnow().isoformat(),
            "type": "validation",
            "spec_file": spec_file,
            "passed": passed,
            "error_count": len(errors or []),
            "warning_count": len(warnings or []),
            "errors": (errors or [])[:5],  # Include first 5 errors
            "warnings": (warnings or [])[:5],  # Include first 5 warnings
        }
        self._append_entry(entry)

    def log_research(self, query_phase: str, query: str, status: str, result_count: int = 0) -> None:
        """Log a research-analyst query.

        Args:
            query_phase: Phase name (project_context, boost_converter, mcu, etc.)
            query: The query sent to Perplexity
            status: ok, timeout, error, no_api_key
            result_count: Number of results returned
        """
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "type": "research",
            "phase": query_phase,
            "status": status,
            "result_count": result_count,
            "query_length": len(query),
        }
        self._append_entry(entry)

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of the design workflow so far.

        Returns:
            Dict with: current_step, files_generated, validation_status, errors, warnings, timeline
        """
        if not self.entries:
            return {"status": "empty", "entries": 0}

        last_step = 0
        files = set()
        validation_passed = None
        errors = []
        warnings = []

        for entry in self.entries:
            if entry.get("type") == "wizard_step":
                last_step = max(last_step, entry.get("step", 0))

            if entry.get("type") == "cli_call":
                files.update(entry.get("generated_files", []))
                if not entry.get("success"):
                    errors.append(f"{entry.get('command')}: {entry.get('stderr', 'unknown error')}")

            if entry.get("type") == "validation":
                validation_passed = entry.get("passed")
                errors.extend(entry.get("errors", []))
                warnings.extend(entry.get("warnings", []))

            if entry.get("type") == "research":
                if entry.get("status") != "ok":
                    warnings.append(f"Research phase '{entry.get('phase')}': {entry.get('status')}")

        return {
            "status": "in_progress" if last_step > 0 else "empty",
            "last_step": last_step,
            "entries": len(self.entries),
            "files_generated": sorted(list(files)),
            "validation_passed": validation_passed,
            "errors": errors[:5],  # Last 5 errors
            "warnings": warnings[:5],  # Last 5 warnings
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
            status = "✓ PASSED" if summary["validation_passed"] else "✗ FAILED"
            print(f"Validation:  {status}")

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
