"""Tests for erc_runner.py — Task 118."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from circuit_weaver.erc_runner import (
    ErcResult,
    ErcViolation,
    _classify_severity,
    _parse_erc_json,
    run_erc,
)

# ---------------------------------------------------------------------------
# _classify_severity
# ---------------------------------------------------------------------------


def test_classify_severity_error_string():
    assert _classify_severity("unknown_type", "error") == "error"


def test_classify_severity_warning_string():
    assert _classify_severity("unknown_type", "warning") == "warning"


def test_classify_severity_known_error_type_overrides_warning():
    """Known error types should be promoted to 'error' even if kicad-cli says 'warning'."""
    assert _classify_severity("pin_not_connected", "warning") == "error"
    assert _classify_severity("missing_power_flag", "warning") == "error"


def test_classify_severity_unknown_type_stays_warning():
    assert _classify_severity("some_informational_note", "warning") == "warning"


# ---------------------------------------------------------------------------
# _parse_erc_json
# ---------------------------------------------------------------------------


def test_parse_erc_json_clean():
    raw = {"violations": [], "coordinator": {"errors": 0, "warnings": 0}}
    result = _parse_erc_json(raw, "test.kicad_sch")
    assert result.status == "ok"
    assert result.errors == 0
    assert result.warnings == 0
    assert result.violations == []


def test_parse_erc_json_with_violations():
    raw = {
        "violations": [
            {
                "type": "pin_not_connected",
                "description": "Pin unconnected",
                "severity": "error",
                "items": [{"description": "U1 pin 3"}],
            },
            {
                "type": "simulation_hint",
                "description": "Informational note",
                "severity": "warning",
                "items": [],
            },
        ]
    }
    result = _parse_erc_json(raw, "board.kicad_sch")
    assert result.status == "ok"
    assert result.errors == 1
    assert result.warnings == 1
    assert len(result.violations) == 2
    assert result.violations[0].type == "pin_not_connected"
    assert result.violations[0].severity == "error"


def test_parse_erc_json_empty_violations_key():
    raw = {}  # missing 'violations' key entirely
    result = _parse_erc_json(raw, "sch.kicad_sch")
    assert result.status == "ok"
    assert result.errors == 0


# ---------------------------------------------------------------------------
# run_erc — no KiCad CLI
# ---------------------------------------------------------------------------


def test_run_erc_missing_schematic(tmp_path):
    result = run_erc(tmp_path / "nonexistent.kicad_sch")
    assert result.status == "failed"
    assert "not found" in result.skip_reason.lower()


def test_run_erc_no_kicad_cli(tmp_path):
    sch = tmp_path / "test.kicad_sch"
    sch.write_text("(kicad_sch)")
    with patch("circuit_weaver.erc_runner._kicad_cli_path", return_value=None):
        result = run_erc(sch)
    assert result.status == "skipped"
    assert "KiCad CLI" in result.skip_reason or "not available" in result.skip_reason


# ---------------------------------------------------------------------------
# run_erc — mocked kicad-cli success
# ---------------------------------------------------------------------------


def test_run_erc_success(tmp_path):
    sch = tmp_path / "design.kicad_sch"
    sch.write_text("(kicad_sch)")

    erc_json = json.dumps(
        {
            "violations": [
                {
                    "type": "pin_not_connected",
                    "description": "Pin unconnected",
                    "severity": "error",
                    "items": [],
                }
            ]
        }
    )

    def fake_run(cmd, **kwargs):
        # Write ERC JSON to the --output path from the command
        out_idx = cmd.index("--output") + 1
        Path(cmd[out_idx]).write_text(erc_json, encoding="utf-8")
        return MagicMock(returncode=0, stdout="", stderr="")

    fake_cli = tmp_path / "kicad-cli"
    with patch("circuit_weaver.erc_runner._kicad_cli_path", return_value=fake_cli):
        with patch("circuit_weaver.erc_runner.subprocess.run", side_effect=fake_run):
            result = run_erc(sch)

    assert result.status == "ok"
    assert result.errors == 1
    assert result.warnings == 0


# ---------------------------------------------------------------------------
# run_erc — mocked kicad-cli timeout
# ---------------------------------------------------------------------------


def test_run_erc_timeout(tmp_path):
    sch = tmp_path / "design.kicad_sch"
    sch.write_text("(kicad_sch)")
    fake_cli = tmp_path / "kicad-cli"

    with patch("circuit_weaver.erc_runner._kicad_cli_path", return_value=fake_cli):
        with patch(
            "circuit_weaver.erc_runner.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="kicad-cli", timeout=60),
        ):
            result = run_erc(sch)

    assert result.status == "failed"
    assert "timed out" in result.skip_reason.lower()


# ---------------------------------------------------------------------------
# ErcResult.to_dict
# ---------------------------------------------------------------------------


def test_erc_result_to_dict_roundtrip():
    result = ErcResult(
        status="ok",
        schematic="board.kicad_sch",
        errors=1,
        warnings=2,
        violations=[ErcViolation(type="pin_not_connected", description="desc", severity="error")],
    )
    d = result.to_dict()
    assert d["status"] == "ok"
    assert d["errors"] == 1
    assert d["warnings"] == 2
    assert len(d["violations"]) == 1
    assert d["violations"][0]["type"] == "pin_not_connected"
