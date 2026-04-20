"""Bridge between Python's logging module and DesignLogger.

Provides a unified logging interface so that:
1. Python module-level loggers (logging.getLogger(__name__)) automatically
   feed into the project's design.log via DesignLogHandler.
2. A singleton accessor (get_design_logger / set_design_logger) lets any
   module log structured events without passing a logger instance around.
3. init_logging() sets up both design.log (JSON Lines) and circuit-weaver.log
   (text) from the start of any operation, not just during generate_artifacts().
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .design_logger import DesignLogger

_current_logger: DesignLogger | None = None


def get_design_logger() -> DesignLogger | None:
    """Get the active DesignLogger for the current project context.

    Returns None if no logger has been set (e.g. running outside a project).
    Callers should guard: ``dl = get_design_logger(); if dl: dl.log_...()``.
    """
    return _current_logger


def set_design_logger(logger: DesignLogger | None) -> None:
    """Set the active DesignLogger (called at workflow start)."""
    global _current_logger
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
            elif record.levelno >= logging.WARNING:
                # Capture untyped warnings/errors as error log entries
                self._dl.log_error(
                    operation=record.name,
                    error=self.format(record),
                )
        except Exception:
            self.handleError(record)


_file_handler: logging.FileHandler | None = None


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

    # Also set up circuit-weaver.log text file
    log_path = project_path / "circuit-weaver.log"
    _file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    _file_handler.setLevel(logging.DEBUG)
    _file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    cw_logger.addHandler(_file_handler)
    if cw_logger.level == logging.NOTSET or cw_logger.level > logging.DEBUG:
        cw_logger.setLevel(logging.DEBUG)

    return dl, bridge


def cleanup_logging() -> None:
    """Remove handlers added by init_logging(). Call at end of workflow."""
    global _file_handler

    cw_logger = logging.getLogger("circuit_weaver")

    # Remove DesignLogHandler instances
    for handler in cw_logger.handlers[:]:
        if isinstance(handler, DesignLogHandler):
            cw_logger.removeHandler(handler)

    # Remove file handler
    if _file_handler is not None:
        cw_logger.removeHandler(_file_handler)
        _file_handler.close()
        _file_handler = None

    set_design_logger(None)
