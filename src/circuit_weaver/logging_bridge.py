"""Bridge between Python's logging module and DesignLogger.

Provides a unified logging interface so that:
1. Python module-level loggers (logging.getLogger(__name__)) automatically
   feed into the project's design.log via DesignLogHandler.
2. A singleton accessor (get_design_logger / set_design_logger) lets any
   module log structured events without passing a logger instance around.
3. init_logging() sets up both design.log (JSON Lines) and circuit-weaver.log
   (text) from the start of any operation, not just during generate_artifacts().
4. init_logging_for_cli(args) picks the right log directory based on the
   argparse Namespace — a file-path --output writes to the file's parent
   dir, a directory --output writes to the dir itself, and commands with
   no --output fall back to the YAML spec's parent or CWD.

The root logger level is controlled by ``CIRCUIT_WEAVER_LOG_LEVEL``
(default ``INFO``). Setting ``DEBUG`` surfaces byte-level trace — useful
when reproducing resolver/subprocess issues.
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import argparse

    from .design_logger import DesignLogger

_lock = threading.Lock()
_current_logger: DesignLogger | None = None
_file_handler: logging.FileHandler | None = None

# Filename extensions that indicate args.output is a single artifact file
# rather than an output directory. When we detect one of these we log to
# the parent directory instead of trying to create args.output/ as a dir.
_FILE_OUTPUT_SUFFIXES = {
    ".html",
    ".htm",
    ".yaml",
    ".yml",
    ".json",
    ".csv",
    ".md",
    ".svg",
    ".txt",
    ".pdf",
    ".zip",
    ".stl",
    ".scad",
    ".kicad_sch",
    ".kicad_pcb",
    ".gbr",
    ".drl",
}

# Commands that intentionally don't touch a project directory — skip file
# logging entirely for these so we don't litter CWD with empty log files.
_NO_LOG_COMMANDS = {
    "doctor",
    "discover",
    "list-templates",
    "schema",
    "cache",
    "log-view",
    "log-status",
    "install-skills",
    "log-event",
    "status",
    "resume",
    "import-design",
}


def _log_dir_candidates(preferred: Path) -> list[Path]:
    """Return best-effort fallback locations for CLI log files."""
    candidates = [preferred]
    temp_logs = Path(tempfile.gettempdir()) / "circuit-weaver-logs"
    for candidate in (temp_logs, Path.cwd()):
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def get_design_logger() -> DesignLogger | None:
    """Get the active DesignLogger for the current project context.

    Returns None if no logger has been set (e.g. running outside a project).
    Callers should guard: ``dl = get_design_logger(); if dl: dl.log_...()``.
    """
    with _lock:
        return _current_logger


def set_design_logger(logger: DesignLogger | None) -> None:
    """Set the active DesignLogger (called at workflow start)."""
    global _current_logger
    with _lock:
        _current_logger = logger


class DesignLogHandler(logging.Handler):
    """Python logging handler that routes records to DesignLogger.

    Records with extra attributes (e.g. ``logger.info("...", extra={"dl_type": "erc_drc"})``)
    are routed to the corresponding DesignLogger method. Plain records are
    captured as generic log entries if they are WARNING or above.
    """

    def __init__(self, design_logger: DesignLogger):
        super().__init__()
        self._dl = design_logger

    def emit(self, record: logging.LogRecord) -> None:
        try:
            dl_type = getattr(record, "dl_type", None)
            dl_data = getattr(record, "dl_data", {})

            if dl_type == "part_lookup":
                self._dl.log_part_lookup(
                    mpn=dl_data.get("mpn", ""),
                    source=dl_data.get("source", ""),
                    status=dl_data.get("status", ""),
                    details=dl_data.get("details"),
                )
            elif dl_type == "simulation":
                self._dl.log_simulation(
                    sim_type=dl_data.get("sim_type", ""),
                    target=dl_data.get("target", ""),
                    status=dl_data.get("status", ""),
                    metrics=dl_data.get("metrics"),
                    duration_sec=dl_data.get("duration_sec", 0.0),
                )
            elif dl_type == "erc_drc":
                self._dl.log_erc_drc(
                    check_type=dl_data.get("check_type", ""),
                    file=dl_data.get("file", ""),
                    errors=dl_data.get("errors", 0),
                    warnings=dl_data.get("warnings", 0),
                    details=dl_data.get("details"),
                )
            elif dl_type == "thermal":
                self._dl.log_thermal(
                    ref=dl_data.get("ref", ""),
                    tj_calc=dl_data.get("tj_calc", 0.0),
                    tj_max=dl_data.get("tj_max", 0.0),
                    status=dl_data.get("status", ""),
                )
            elif dl_type == "scoring":
                self._dl.log_scoring(
                    dimension=dl_data.get("dimension", ""),
                    score=dl_data.get("score", 0.0),
                    grade=dl_data.get("grade", ""),
                    gaps=dl_data.get("gaps"),
                )
            elif dl_type == "generation":
                self._dl.log_generation(
                    artifact_type=dl_data.get("artifact_type", ""),
                    path=dl_data.get("path", ""),
                    status=dl_data.get("status", ""),
                    duration_sec=dl_data.get("duration_sec", 0.0),
                )
            elif record.levelno >= logging.ERROR:
                # ERROR and CRITICAL → structured error entry
                self._dl.log_error(
                    operation=record.name,
                    error=self.format(record),
                )
            elif record.levelno >= logging.WARNING:
                # WARNING → structured warning entry (Sprint 45 Bug 2:
                # previously WARNINGs were logged as type:error, conflating
                # severities and creating false ERROR noise in design.log).
                self._dl.log_warning(
                    operation=record.name,
                    message=self.format(record),
                )
        except Exception:
            self.handleError(record)


def init_logging(
    project_dir: str | Path,
) -> tuple[DesignLogger, DesignLogHandler]:
    """Initialize unified logging for a project.

    Creates both:
    - design.log (JSON Lines via DesignLogger)
    - circuit-weaver.log (text via Python logging FileHandler)

    Sets the module-level singleton so get_design_logger() works everywhere.

    Args:
        project_dir: Project root directory.

    Returns:
        Tuple of (DesignLogger instance, DesignLogHandler instance).
    """
    from .design_logger import DesignLogger

    global _file_handler

    project_path = Path(project_dir)
    project_path.mkdir(parents=True, exist_ok=True)

    # Create DesignLogger (handles design.log)
    dl = DesignLogger(project_path)
    set_design_logger(dl)

    cw_logger = logging.getLogger("circuit_weaver")

    # Remove any prior handlers we attached before re-attaching. Calling
    # init_logging twice in one process (e.g. two wizard invocations) used
    # to stack handlers and double-log every record.
    for existing in list(cw_logger.handlers):
        if isinstance(existing, DesignLogHandler):
            cw_logger.removeHandler(existing)
    if _file_handler is not None:
        cw_logger.removeHandler(_file_handler)
        try:
            _file_handler.close()
        except Exception:
            pass
        _file_handler = None

    # Create bridge handler
    bridge = DesignLogHandler(dl)
    bridge.setLevel(logging.DEBUG)
    cw_logger.addHandler(bridge)

    # Also set up circuit-weaver.log text file. The file handler always
    # captures DEBUG so reruns can inspect everything; the root logger
    # level is driven by CIRCUIT_WEAVER_LOG_LEVEL (default INFO) which
    # controls what propagates to stderr.
    log_path = project_path / "circuit-weaver.log"
    try:
        with _lock:
            _file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
            _file_handler.setLevel(logging.DEBUG)
            _file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        cw_logger.addHandler(_file_handler)
    except OSError:
        cleanup_logging()
        raise

    env_level = os.environ.get("CIRCUIT_WEAVER_LOG_LEVEL", "INFO").upper()
    try:
        level = getattr(logging, env_level)
    except AttributeError:
        level = logging.INFO
    if cw_logger.level == logging.NOTSET or cw_logger.level > level:
        cw_logger.setLevel(level)

    return dl, bridge


def _resolve_log_dir(command: str, args: argparse.Namespace | None) -> Path | None:
    """Pick one project-root log directory from the CLI arguments.

    Input paths are authoritative because output directories commonly live
    below the project root. This prevents generation and routing from creating
    a second, disconnected ``design.log`` under ``output/``.
    """
    if not command or command in _NO_LOG_COMMANDS:
        return None

    from .project_state import project_state_path, resolve_project_root

    if command == "generate" and args is not None:
        spec_value = getattr(args, "spec", None)
        output_value = getattr(args, "output", None)
        if spec_value:
            spec_root = resolve_project_root(Path(spec_value))
            has_project_marker = (
                project_state_path(spec_root).is_file()
                or (spec_root / "design.yaml").is_file()
                or any(spec_root.glob("*.kicad_pro"))
            )
            if has_project_marker:
                return spec_root
        if output_value:
            return resolve_project_root(Path(output_value))

    for attr in ("project_dir", "project", "spec", "design", "schematic", "kicad_pcb", "resume"):
        val = getattr(args, attr, None) if args is not None else None
        if val:
            return resolve_project_root(Path(val))

    out = getattr(args, "output", None) if args is not None else None
    if out:
        output_path = Path(out)
        candidate = output_path.parent if output_path.suffix.lower() in _FILE_OUTPUT_SUFFIXES else output_path
        return resolve_project_root(candidate)

    return resolve_project_root(Path.cwd())


def init_logging_for_cli(
    command: str,
    args: argparse.Namespace | None = None,
) -> Path | None:
    """Initialise logging for a CLI subcommand.

    Figures out where ``circuit-weaver.log`` should live based on ``args``
    and calls :func:`init_logging`. Idempotent — if a DesignLogger is
    already bound for a different directory (e.g. from an in-process
    caller like ``generate_artifacts``) we leave it alone.

    Returns the resolved log directory, or ``None`` if logging was skipped.
    """
    if get_design_logger() is not None:
        # Already initialised by an outer caller.
        return None

    log_dir = _resolve_log_dir(command, args)
    if log_dir is None:
        return None

    last_error: OSError | None = None
    for candidate in _log_dir_candidates(log_dir):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            init_logging(candidate)
            if candidate != log_dir:
                print(
                    f"Warning: log directory '{log_dir}' is not writable; using '{candidate}' instead.",
                    file=sys.stderr,
                )
            return candidate
        except OSError as exc:
            last_error = exc
            cleanup_logging()

    if last_error is not None:
        print(
            f"Warning: unable to initialize file logging for '{log_dir}': {last_error}",
            file=sys.stderr,
        )
    return None


def log_workflow_step(
    command: str,
    step: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Emit a visible workflow marker to both design.log and circuit-weaver.log.

    Use at the top of each CLI handler and at major transitions inside
    long-running workflows (validate → generate → confidence, etc.) so
    users can trace what the tool was doing just by reading the log.

    Args:
        command: CLI subcommand name (e.g. ``"generate"``).
        step: Short step label (e.g. ``"start"``, ``"validate"``, ``"emit-artifacts"``).
        message: Human-readable description.
        details: Optional structured fields for the design.log JSON entry.
    """
    cw_logger = logging.getLogger("circuit_weaver")
    prefix = f"[{command}:{step}]"
    cw_logger.info("%s %s", prefix, message)

    dl = get_design_logger()
    if dl is not None:
        try:
            dl.log_step(0, f"{prefix} {message}", user_input=details)
        except Exception:  # pragma: no cover — logger must never raise
            pass


def cleanup_logging() -> None:
    """Remove handlers added by init_logging(). Call at end of workflow."""
    global _file_handler

    try:
        cw_logger = logging.getLogger("circuit_weaver")

        # Remove DesignLogHandler instances
        for handler in cw_logger.handlers[:]:
            if isinstance(handler, DesignLogHandler):
                cw_logger.removeHandler(handler)

        # Remove file handler
        with _lock:
            if _file_handler is not None:
                cw_logger.removeHandler(_file_handler)
                try:
                    _file_handler.close()
                except Exception:
                    pass
                _file_handler = None
    finally:
        set_design_logger(None)
