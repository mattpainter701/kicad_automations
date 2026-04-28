"""Tests for datasheet_parser.py — PDF spec extraction.

Sprint 44 T190 — regression tests for the regex-based datasheet
text extraction pipeline.
"""

from __future__ import annotations

from pathlib import Path

from circuit_weaver.datasheet_parser import (
    _PASSIVE_PATTERNS,
    _PATTERNS,
    _apply_patterns,
    extract_specs,
    parse_datasheet,
)


class TestApplyPatterns:
    """_apply_patterns — regex-based spec extraction from text."""

    def test_theta_ja_extraction(self):
        text = "θJA = 45.2 °C/W"
        result = _apply_patterns(text, _PATTERNS)
        assert abs(result.get("theta_ja", 0) - 45.2) < 0.01

    def test_theta_ja_alternate_format(self):
        text = "RθJA= 32.5"
        result = _apply_patterns(text, _PATTERNS)
        assert abs(result.get("theta_ja", 0) - 32.5) < 0.01

    def test_theta_jc_extraction(self):
        text = "θJC = 8.0 °C/W"
        result = _apply_patterns(text, _PATTERNS)
        assert abs(result.get("theta_jc", 0) - 8.0) < 0.01

    def test_power_dissipation(self):
        text = "Maximum Power Dissipation = 2.5 W"
        result = _apply_patterns(text, _PATTERNS)
        assert abs(result.get("pdiss_max_w", 0) - 2.5) < 0.01

    def test_junction_temperature(self):
        text = "Maximum Junction Temperature = 150 °C"
        result = _apply_patterns(text, _PATTERNS)
        assert abs(result.get("tj_max", 0) - 150.0) < 0.01

    def test_input_voltage_range(self):
        text = "Input Voltage = 2.5 to 5.5 V"
        result = _apply_patterns(text, _PATTERNS)
        assert abs(result.get("vin_max", 0) - 5.5) < 0.01

    def test_output_voltage(self):
        text = "Output Voltage = 3.3 V"
        result = _apply_patterns(text, _PATTERNS)
        assert abs(result.get("vout_nom", 0) - 3.3) < 0.01

    def test_quiescent_current(self):
        text = "Quiescent Current = 45 µA"
        result = _apply_patterns(text, _PATTERNS)
        assert abs(result.get("iq_ua", 0) - 45.0) < 0.01

    def test_switching_frequency_mhz(self):
        text = "Switching Frequency = 2.2 MHz"
        result = _apply_patterns(text, _PATTERNS)
        assert abs(result.get("fsw_mhz", 0) - 2.2) < 0.01

    def test_passive_voltage_rating(self):
        text = "Rated Voltage = 25 V"
        result = _apply_patterns(text, _PASSIVE_PATTERNS)
        assert abs(result.get("voltage_rating", 0) - 25.0) < 0.01

    def test_passive_tolerance(self):
        text = "Tolerance = ±5%"
        result = _apply_patterns(text, _PASSIVE_PATTERNS)
        assert abs(result.get("tolerance_pct", 0) - 5.0) < 0.01

    def test_no_match_returns_empty(self):
        text = "This is just a description with no specs."
        result = _apply_patterns(text, _PATTERNS)
        assert result == {}

    def test_multiple_matches_first_wins(self):
        text = "θJA = 32.0 °C/W\nθJA = 45.0 °C/W"
        result = _apply_patterns(text, _PATTERNS)
        assert abs(result.get("theta_ja", 0) - 32.0) < 0.01


class TestParseDatasheet:
    """parse_datasheet — PDF file parsing."""

    def test_missing_file_returns_empty(self):
        result = parse_datasheet("/nonexistent/path.pdf")
        assert result == {}

    def test_no_pypdf_graceful_fallback(self, monkeypatch):
        monkeypatch.setattr("circuit_weaver.datasheet_parser._try_import_pypdf", lambda: None)
        result = parse_datasheet(Path(__file__))
        assert result.get("status") == "no_pypdf"

    def test_power_dissipation_unit_conversion(self):
        text = "Power Dissipation = 500 mW"
        result = _apply_patterns(text, _PATTERNS)
        assert "pdiss_max_mw" in result


class TestExtractSpecs:
    """extract_specs — batch extraction from directory."""

    def test_missing_directory(self, tmp_path):
        result = extract_specs(tmp_path / "nonexistent", tmp_path / "out")
        assert result.get("status") == "error"

    def test_no_pypdf_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setattr("circuit_weaver.datasheet_parser._try_import_pypdf", lambda: None)
        datasheets_dir = tmp_path / "datasheets"
        datasheets_dir.mkdir()
        (datasheets_dir / "dummy.pdf").write_text("not a pdf")
        result = extract_specs(datasheets_dir, tmp_path / "out")
        assert result.get("status") == "error"
        assert "pypdf" in result.get("message", "")
