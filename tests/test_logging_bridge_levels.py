"""Sprint 45 Bug 2 — DesignLogHandler must map Python log levels to
the correct DesignLogger event type.

Regression: prior to Sprint 45, both WARNING and ERROR records emitted via
the standard ``logging`` API ended up as ``{"type": "error"}`` entries in
design.log. The IoT_AQ_Sensor run (April 28) showed the BME688 SDO
floating-pin warning logged as type:error in design.log even though it
was correctly emitted at WARNING level by generator.py:1903 and rendered
as WARNING in circuit-weaver.log.

This test pins the level→type mapping:
- DEBUG / INFO       → info       (or routed via dl_type)
- WARNING            → warning
- ERROR / CRITICAL   → error
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from circuit_weaver.design_logger import DesignLogger
from circuit_weaver.logging_bridge import DesignLogHandler


def _make_logger_and_handler(tmp_path: Path) -> tuple[logging.Logger, DesignLogger, str]:
    """Build an isolated logger + DesignLogger for testing."""
    dl = DesignLogger(tmp_path)
    handler = DesignLogHandler(dl)
    handler.setLevel(logging.DEBUG)

    name = f"test_logger_{id(tmp_path)}"
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return logger, dl, name


def _read_log_entries(log_path: Path) -> list[dict]:
    if not log_path.exists():
        return []
    out = []
    for raw in log_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


def test_warning_record_emits_warning_type(tmp_path):
    """logger.warning() should produce {type: 'warning'}, not 'error'."""
    logger, dl, name = _make_logger_and_handler(tmp_path)

    logger.warning("U2 (BME688): unconnected bidirectional pin SDO")

    entries = _read_log_entries(dl.log_path)
    warning_entries = [e for e in entries if e.get("type") == "warning"]
    error_entries = [e for e in entries if e.get("type") == "error"]

    assert len(warning_entries) == 1, (
        f"Expected exactly 1 warning entry, got {len(warning_entries)}. "
        f"All entries: {entries}"
    )
    assert len(error_entries) == 0, (
        f"WARNING records must NOT emit type:error entries. "
        f"Got {len(error_entries)} false errors: {error_entries}"
    )
    assert "BME688" in warning_entries[0]["message"]


def test_error_record_emits_error_type(tmp_path):
    """logger.error() must still produce {type: 'error'}."""
    logger, dl, name = _make_logger_and_handler(tmp_path)

    logger.error("Generation failed: missing root schematic")

    entries = _read_log_entries(dl.log_path)
    error_entries = [e for e in entries if e.get("type") == "error"]
    warning_entries = [e for e in entries if e.get("type") == "warning"]

    assert len(error_entries) == 1, (
        f"Expected exactly 1 error entry, got {len(error_entries)}"
    )
    assert len(warning_entries) == 0


def test_critical_record_emits_error_type(tmp_path):
    """logger.critical() should also map to 'error' (most-severe bucket)."""
    logger, dl, _ = _make_logger_and_handler(tmp_path)

    logger.critical("KiCad subprocess crashed")

    entries = _read_log_entries(dl.log_path)
    error_entries = [e for e in entries if e.get("type") == "error"]
    assert len(error_entries) == 1


def test_info_record_with_no_dl_type_does_not_log_to_design_log(tmp_path):
    """INFO records without a dl_type extra are NOT written to design.log
    (they go to circuit-weaver.log only). The bridge intentionally skips
    untyped INFO/DEBUG to avoid swamping design.log with mundane chatter."""
    logger, dl, _ = _make_logger_and_handler(tmp_path)

    logger.info("Allocated 5 components to 1 sheet(s)")
    logger.debug("Extra debugging detail")

    entries = _read_log_entries(dl.log_path)
    # Bridge requires dl_type extra to write INFO/DEBUG records;
    # bare INFO/DEBUG produce no design.log entry at all.
    assert len(entries) == 0, (
        f"INFO/DEBUG without dl_type should not write design.log entries; "
        f"got {entries}"
    )


def test_typed_record_routes_to_typed_method(tmp_path):
    """An INFO record with dl_type='erc_drc' should use log_erc_drc()
    even though the level is INFO, not WARNING."""
    logger, dl, _ = _make_logger_and_handler(tmp_path)

    logger.info(
        "ERC results",
        extra={
            "dl_type": "erc_drc",
            "dl_data": {
                "check_type": "erc",
                "file": "test.kicad_sch",
                "errors": 0,
                "warnings": 0,
            },
        },
    )

    entries = _read_log_entries(dl.log_path)
    erc_entries = [e for e in entries if e.get("type") == "erc_drc"]
    assert len(erc_entries) == 1
    assert erc_entries[0]["check_type"] == "erc"


def test_warning_with_dl_type_uses_dl_type_routing(tmp_path):
    """A WARNING record with a recognised dl_type should follow that route,
    not the generic warning route."""
    logger, dl, _ = _make_logger_and_handler(tmp_path)

    logger.warning(
        "Thermal hotspot",
        extra={
            "dl_type": "thermal",
            "dl_data": {
                "ref": "U1",
                "tj_calc": 105.0,
                "tj_max": 125.0,
                "status": "warning",
            },
        },
    )

    entries = _read_log_entries(dl.log_path)
    thermal_entries = [e for e in entries if e.get("type") == "thermal"]
    warning_entries = [e for e in entries if e.get("type") == "warning"]

    assert len(thermal_entries) == 1, (
        f"dl_type=thermal record should route to log_thermal; got {entries}"
    )
    assert len(warning_entries) == 0
