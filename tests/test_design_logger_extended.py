"""Tests for extended DesignLogger event types and logging bridge."""

import json
import logging
import os
import tempfile
from pathlib import Path

import pytest

from circuit_weaver.design_logger import DesignLogger
from circuit_weaver.logging_bridge import (
    DesignLogHandler,
    cleanup_logging,
    get_design_logger,
    init_logging,
    set_design_logger,
)


@pytest.fixture
def tmp_project(tmp_path):
    """Create a temporary project directory."""
    project = tmp_path / "test_project"
    project.mkdir()
    return project


@pytest.fixture
def logger(tmp_project):
    """Create a DesignLogger for a temp project."""
    return DesignLogger(tmp_project)


def _read_log_entries(log_path: Path) -> list[dict]:
    """Read all JSON Lines entries from a design.log."""
    entries = []
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").strip().splitlines():
            if line.strip():
                entries.append(json.loads(line))
    return entries


# ---- Test new DesignLogger event types ----

class TestPartLookup:
    def test_log_part_lookup_ok(self, logger, tmp_project):
        logger.log_part_lookup(mpn="TPS62300", source="digikey", status="ok", details={"price": 1.20})
        entries = _read_log_entries(tmp_project / "design.log")
        assert len(entries) == 1
        assert entries[0]["type"] == "part_lookup"
        assert entries[0]["mpn"] == "TPS62300"
        assert entries[0]["source"] == "digikey"
        assert entries[0]["status"] == "ok"
        assert entries[0]["details"]["price"] == 1.20

    def test_log_part_lookup_not_found(self, logger, tmp_project):
        logger.log_part_lookup(mpn="UNKNOWN123", source="lcsc", status="not_found")
        entries = _read_log_entries(tmp_project / "design.log")
        assert entries[0]["status"] == "not_found"
        assert entries[0]["details"] == {}


class TestSymbolResolution:
    def test_log_symbol_resolution(self, logger, tmp_project):
        logger.log_symbol_resolution(ref="U1", mpn="ESP32-S3", status="ok", pinout_source="datasheet")
        entries = _read_log_entries(tmp_project / "design.log")
        assert entries[0]["type"] == "symbol_resolution"
        assert entries[0]["ref"] == "U1"
        assert entries[0]["pinout_source"] == "datasheet"


class TestSimulation:
    def test_log_simulation(self, logger, tmp_project):
        logger.log_simulation(
            sim_type="tran", target="buck_U1", status="ok",
            metrics={"ripple_mv": 12.3, "phase_margin_deg": 52.0},
            duration_sec=3.45,
        )
        entries = _read_log_entries(tmp_project / "design.log")
        assert entries[0]["type"] == "simulation"
        assert entries[0]["sim_type"] == "tran"
        assert entries[0]["target"] == "buck_U1"
        assert entries[0]["metrics"]["ripple_mv"] == 12.3
        assert entries[0]["duration_sec"] == 3.45


class TestThermal:
    def test_log_thermal(self, logger, tmp_project):
        logger.log_thermal(ref="U1", tj_calc=85.3, tj_max=125.0, status="ok")
        entries = _read_log_entries(tmp_project / "design.log")
        assert entries[0]["type"] == "thermal"
        assert entries[0]["tj_calc"] == 85.3
        assert entries[0]["tj_max"] == 125.0
        assert entries[0]["margin_deg"] == 39.7
        assert entries[0]["status"] == "ok"

    def test_log_thermal_critical(self, logger, tmp_project):
        logger.log_thermal(ref="U2", tj_calc=130.0, tj_max=125.0, status="critical")
        entries = _read_log_entries(tmp_project / "design.log")
        assert entries[0]["margin_deg"] == -5.0
        assert entries[0]["status"] == "critical"


class TestErcDrc:
    def test_log_erc_drc(self, logger, tmp_project):
        logger.log_erc_drc(
            check_type="erc", file="main.kicad_sch", errors=2, warnings=1,
            details=["pin not connected", "wire not connected"],
        )
        entries = _read_log_entries(tmp_project / "design.log")
        assert entries[0]["type"] == "erc_drc"
        assert entries[0]["check_type"] == "erc"
        assert entries[0]["errors"] == 2
        assert entries[0]["passed"] is False

    def test_log_erc_drc_passing(self, logger, tmp_project):
        logger.log_erc_drc(check_type="drc", file="main.kicad_pcb", errors=0, warnings=0)
        entries = _read_log_entries(tmp_project / "design.log")
        assert entries[0]["passed"] is True


class TestScoring:
    def test_log_scoring(self, logger, tmp_project):
        logger.log_scoring(dimension="power", score=85.0, grade="B", gaps=["missing bulk cap"])
        entries = _read_log_entries(tmp_project / "design.log")
        assert entries[0]["type"] == "scoring"
        assert entries[0]["score"] == 85.0
        assert entries[0]["grade"] == "B"
        assert entries[0]["gaps"] == ["missing bulk cap"]


class TestSourcing:
    def test_log_sourcing(self, logger, tmp_project):
        logger.log_sourcing(mpn="ESP32-S3", supplier="lcsc", status="ok", price=2.85, stock=5000)
        entries = _read_log_entries(tmp_project / "design.log")
        assert entries[0]["type"] == "sourcing"
        assert entries[0]["price"] == 2.85
        assert entries[0]["stock"] == 5000

    def test_log_sourcing_no_price(self, logger, tmp_project):
        logger.log_sourcing(mpn="RARE123", supplier="mouser", status="not_found")
        entries = _read_log_entries(tmp_project / "design.log")
        assert "price" not in entries[0]
        assert "stock" not in entries[0]


class TestGeneration:
    def test_log_generation(self, logger, tmp_project):
        logger.log_generation(
            artifact_type="schematic", path="output/main.kicad_sch", status="ok", duration_sec=1.23,
        )
        entries = _read_log_entries(tmp_project / "design.log")
        assert entries[0]["type"] == "generation"
        assert entries[0]["artifact_type"] == "schematic"
        assert entries[0]["duration_sec"] == 1.23


class TestError:
    def test_log_error(self, logger, tmp_project):
        logger.log_error(operation="generate", error="Failed to resolve symbol", traceback="Traceback...")
        entries = _read_log_entries(tmp_project / "design.log")
        assert entries[0]["type"] == "error"
        assert entries[0]["operation"] == "generate"
        assert "traceback" in entries[0]

    def test_log_error_truncates(self, logger, tmp_project):
        logger.log_error(operation="x", error="E" * 1000)
        entries = _read_log_entries(tmp_project / "design.log")
        assert len(entries[0]["error"]) == 500


# ---- Test get_summary with new event types ----

class TestExtendedSummary:
    def test_summary_includes_simulation(self, logger, tmp_project):
        logger.log_simulation(sim_type="tran", target="buck", status="ok")
        logger.log_simulation(sim_type="ac", target="filter", status="skipped")
        summary = logger.get_summary()
        assert summary["simulation"]["total"] == 2
        assert summary["simulation"]["passed"] == 1
        assert summary["simulation"]["skipped"] == 1

    def test_summary_includes_thermal(self, logger, tmp_project):
        logger.log_thermal(ref="U1", tj_calc=130, tj_max=125, status="critical")
        logger.log_thermal(ref="U2", tj_calc=100, tj_max=125, status="warning")
        summary = logger.get_summary()
        assert summary["thermal"]["critical"] == 1
        assert summary["thermal"]["warnings"] == 1

    def test_summary_includes_erc_drc(self, logger, tmp_project):
        logger.log_erc_drc(check_type="erc", file="x", errors=3, warnings=2)
        summary = logger.get_summary()
        assert summary["erc_drc"]["errors"] == 3

    def test_summary_includes_scoring(self, logger, tmp_project):
        logger.log_scoring(dimension="overall", score=78.0, grade="C")
        summary = logger.get_summary()
        assert summary["scoring"]["overall"]["score"] == 78.0

    def test_summary_includes_part_lookups(self, logger, tmp_project):
        logger.log_part_lookup(mpn="A", source="x", status="ok")
        logger.log_part_lookup(mpn="B", source="x", status="not_found")
        summary = logger.get_summary()
        assert summary["part_lookups"]["total"] == 2
        assert summary["part_lookups"]["failures"] == 1

    def test_summary_includes_generation_files(self, logger, tmp_project):
        logger.log_generation(artifact_type="schematic", path="out/main.kicad_sch", status="ok")
        summary = logger.get_summary()
        assert "out/main.kicad_sch" in summary["files_generated"]

    def test_summary_includes_errors(self, logger, tmp_project):
        logger.log_error(operation="validate", error="Something broke")
        summary = logger.get_summary()
        assert any("Something broke" in e for e in summary["errors"])

    def test_summary_none_sections_when_empty(self, logger, tmp_project):
        logger.log_step(1, "First step")
        summary = logger.get_summary()
        assert summary["simulation"] is None
        assert summary["thermal"] is None
        assert summary["erc_drc"] is None
        assert summary["scoring"] is None
        assert summary["part_lookups"] is None


# ---- Test DesignLogHandler (bridge) ----

class TestDesignLogHandler:
    def test_handler_routes_erc_drc(self, logger, tmp_project):
        handler = DesignLogHandler(logger)
        record = logging.LogRecord(
            name="circuit_weaver.erc_runner", level=logging.INFO,
            pathname="", lineno=0, msg="ERC done", args=(), exc_info=None,
        )
        record.dl_type = "erc_drc"  # type: ignore[attr-defined]
        record.dl_data = {"check_type": "erc", "file": "test.sch", "errors": 1, "warnings": 0}  # type: ignore[attr-defined]
        handler.emit(record)

        entries = _read_log_entries(tmp_project / "design.log")
        assert len(entries) == 1
        assert entries[0]["type"] == "erc_drc"
        assert entries[0]["errors"] == 1

    def test_handler_captures_warnings_as_errors(self, logger, tmp_project):
        handler = DesignLogHandler(logger)
        handler.setFormatter(logging.Formatter("%(message)s"))
        record = logging.LogRecord(
            name="circuit_weaver.generator", level=logging.WARNING,
            pathname="", lineno=0, msg="Missing footprint for C5", args=(), exc_info=None,
        )
        handler.emit(record)

        entries = _read_log_entries(tmp_project / "design.log")
        assert len(entries) == 1
        assert entries[0]["type"] == "error"
        assert "Missing footprint" in entries[0]["error"]

    def test_handler_ignores_info_without_dl_type(self, logger, tmp_project):
        handler = DesignLogHandler(logger)
        record = logging.LogRecord(
            name="circuit_weaver.x", level=logging.INFO,
            pathname="", lineno=0, msg="Just info", args=(), exc_info=None,
        )
        handler.emit(record)
        entries = _read_log_entries(tmp_project / "design.log")
        assert len(entries) == 0  # INFO without dl_type is ignored


# ---- Test singleton accessors ----

class TestSingleton:
    def test_get_set_design_logger(self, logger):
        assert get_design_logger() is None or True  # may be set from prior test
        set_design_logger(logger)
        assert get_design_logger() is logger
        set_design_logger(None)
        assert get_design_logger() is None

    def test_init_logging_creates_files(self, tmp_project):
        dl, handler = init_logging(tmp_project)
        try:
            # design.log is created on first write; circuit-weaver.log is created by FileHandler
            assert get_design_logger() is dl
            assert isinstance(handler, DesignLogHandler)
            # Write an entry to create design.log
            dl.log_step(0, "init test")
            assert (tmp_project / "design.log").exists()
            assert (tmp_project / "circuit-weaver.log").exists()
        finally:
            cleanup_logging()

    def test_init_logging_enables_python_logging(self, tmp_project):
        dl, handler = init_logging(tmp_project)
        try:
            test_logger = logging.getLogger("circuit_weaver.test_module")
            test_logger.warning("test warning from bridge")
            # Should be captured as an error entry in design.log
            entries = _read_log_entries(tmp_project / "design.log")
            assert any(e["type"] == "error" for e in entries)
        finally:
            cleanup_logging()

    def test_cleanup_removes_handlers(self, tmp_project):
        init_logging(tmp_project)
        cw_logger = logging.getLogger("circuit_weaver")
        bridge_count_before = sum(1 for h in cw_logger.handlers if isinstance(h, DesignLogHandler))
        assert bridge_count_before >= 1
        cleanup_logging()
        bridge_count_after = sum(1 for h in cw_logger.handlers if isinstance(h, DesignLogHandler))
        assert bridge_count_after == 0
        assert get_design_logger() is None


# ---- Test log-event CLI subcommand ----

class TestLogEventCLI:
    def test_log_event_wizard_step(self, tmp_project):
        import subprocess
        result = subprocess.run(
            [
                "python", "-m", "circuit_weaver", "log-event", str(tmp_project),
                "--type", "wizard_step",
                "--message", "Step 1: Project setup",
                "--data", '{"step": 1, "user_input": {"name": "TestProj"}}',
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        entries = _read_log_entries(tmp_project / "design.log")
        assert any(e["type"] == "wizard_step" and e["step"] == 1 for e in entries)

    def test_log_event_error_type(self, tmp_project):
        import subprocess
        result = subprocess.run(
            [
                "python", "-m", "circuit_weaver", "log-event", str(tmp_project),
                "--type", "error",
                "--message", "Something went wrong",
                "--data", '{"operation": "generate"}',
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        entries = _read_log_entries(tmp_project / "design.log")
        assert any(e["type"] == "error" and "wrong" in e["error"] for e in entries)

    def test_log_event_invalid_json(self, tmp_project):
        import subprocess
        result = subprocess.run(
            [
                "python", "-m", "circuit_weaver", "log-event", str(tmp_project),
                "--type", "scoring",
                "--message", "test",
                "--data", "not-json",
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 1


# ---- Test print_summary with new sections ----

class TestPrintSummary:
    def test_print_summary_with_all_sections(self, logger, capsys):
        logger.log_step(1, "Setup")
        logger.log_simulation(sim_type="tran", target="buck", status="ok")
        logger.log_simulation(sim_type="ac", target="filter", status="skipped")
        logger.log_thermal(ref="U1", tj_calc=130, tj_max=125, status="critical")
        logger.log_erc_drc(check_type="erc", file="x", errors=1, warnings=2)
        logger.log_scoring(dimension="overall", score=72.0, grade="C")
        logger.log_part_lookup(mpn="A", source="x", status="ok")
        logger.log_part_lookup(mpn="B", source="x", status="not_found")

        logger.print_summary()
        output = capsys.readouterr().out
        assert "Simulation:" in output
        assert "1/2 passed" in output
        assert "1 skipped" in output
        assert "Thermal:" in output
        assert "1 critical" in output
        assert "ERC/DRC:" in output
        assert "Score:" in output
        assert "72.0/100" in output
        assert "Parts:" in output
