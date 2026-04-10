"""Tests for SPICE simulation runner."""

from pathlib import Path
from unittest.mock import patch

import pytest

from circuit_weaver.spice_runner import (
    SimulationResult,
    _extract_metrics,
    _find_ngspice,
    _parse_raw_ascii,
    run_simulation,
)


class TestFindNgspice:
    def test_returns_none_when_not_installed(self):
        with patch("shutil.which", return_value=None):
            assert _find_ngspice() is None

    def test_returns_path_when_installed(self):
        with patch("shutil.which", return_value="/usr/bin/ngspice"):
            assert _find_ngspice() == "/usr/bin/ngspice"


class TestRunSimulation:
    def test_skipped_when_ngspice_missing(self, tmp_path):
        netlist = tmp_path / "test.cir"
        netlist.write_text(".end")
        with patch("circuit_weaver.spice_runner._find_ngspice", return_value=None):
            result = run_simulation(netlist)
        assert result.status == "skipped"
        assert "ngspice not installed" in result.skip_reason

    def test_failed_when_netlist_missing(self, tmp_path):
        with patch("circuit_weaver.spice_runner._find_ngspice", return_value="/usr/bin/ngspice"):
            result = run_simulation(tmp_path / "nonexistent.cir")
        assert result.status == "failed"
        assert "not found" in result.skip_reason

    def test_to_dict(self):
        result = SimulationResult(
            status="ok", sim_type="tran",
            traces={"time": [0, 1], "V(vout)": [3.3, 3.3]},
            metrics={"ripple_mv": 5.0},
            duration_sec=1.23,
        )
        d = result.to_dict()
        assert d["status"] == "ok"
        assert d["sim_type"] == "tran"
        assert d["trace_count"] == 2
        assert d["metrics"]["ripple_mv"] == 5.0
        assert d["duration_sec"] == 1.23


class TestParseRawAscii:
    def test_parse_simple_raw(self, tmp_path):
        raw_content = """Title: Test
Plotname: Transient Analysis
Flags: real
No. Variables: 2
No. Points: 3
Variables:
0\ttime\ttime
1\tv(out)\tvoltage
Values:
0.0 3.3
1e-6 3.31
2e-6 3.29
"""
        raw_file = tmp_path / "test.raw"
        raw_file.write_text(raw_content)
        traces, var_names = _parse_raw_ascii(raw_file)
        assert "time" in var_names
        assert "v(out)" in var_names

    def test_empty_raw_file(self, tmp_path):
        raw_file = tmp_path / "empty.raw"
        raw_file.write_text("")
        traces, var_names = _parse_raw_ascii(raw_file)
        assert traces == {}
        assert var_names == []


class TestExtractMetrics:
    def test_tran_ripple_extraction(self):
        traces = {
            "time": [0, 1e-6, 2e-6, 3e-6, 4e-6, 5e-6, 6e-6, 7e-6, 8e-6, 9e-6],
            "V(vout)": [0, 0, 3.28, 3.30, 3.32, 3.29, 3.31, 3.30, 3.28, 3.32],
        }
        metrics = _extract_metrics(traces, "tran")
        assert "V(vout)_ripple_mv" in metrics
        assert "V(vout)_avg_v" in metrics
        # Ripple should be (3.32 - 3.28) * 1000 = 40 mV (from steady state)
        assert metrics["V(vout)_ripple_mv"] > 0

    def test_tran_time_duration(self):
        traces = {"time": [0, 1e-6, 2e-6]}
        metrics = _extract_metrics(traces, "tran")
        assert "sim_duration_s" in metrics

    def test_op_metrics(self):
        traces = {"V(vdd)": [3.3], "I(r1)": [0.001]}
        metrics = _extract_metrics(traces, "op")
        assert metrics["V(vdd)"] == 3.3
        assert metrics["I(r1)"] == 0.001

    def test_empty_traces(self):
        metrics = _extract_metrics({}, "tran")
        assert metrics == {}
