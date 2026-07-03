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


class TestNormalizedPinSchema:
    """Sprint 52 / T234 — datasheet ingest emits the shared normalized schema."""

    PIN_TABLE_TEXT = """
Pin Functions
1 VDD P Supply voltage
2 GND G Ground
3 USB_DP I/O USB D+ differential pair
4 USB_DM I/O USB D- differential pair
5 XTAL1 I Crystal input
6 XTAL2 O Crystal output
7 SWDIO I/O Serial wire debug data
8 NC NC No internal connection
9 EN I Enable input

Bypass the VDD pin with a 0.1 µF ceramic capacitor placed close to the pin.
"""

    def test_pin_table_rows_are_extracted(self):
        from circuit_weaver.datasheet_parser import _parse_pin_table_text

        pins = _parse_pin_table_text(self.PIN_TABLE_TEXT)
        assert [p["number"] for p in pins] == [str(n) for n in range(1, 10)]
        by_num = {p["number"]: p for p in pins}
        assert by_num["1"]["type"] == "power_in"
        assert by_num["3"]["type"] == "bidirectional"
        assert by_num["5"]["type"] == "input"
        assert by_num["6"]["type"] == "output"
        assert by_num["8"]["type"] == "no_connect"

    def test_normalized_fields_match_easyeda_contract(self):
        from circuit_weaver.datasheet_parser import parse_datasheet_text

        result = parse_datasheet_text(self.PIN_TABLE_TEXT)
        assert result["pin_vdd"] == ["1"]
        assert result["pin_gnd"] == ["2"]
        assert result["power_domains"] == ["VDD"]
        assert result["explicit_no_connects"] == ["8"]
        assert result["debug_pins"] == ["7"]
        # Canonical interface roles inferred from pin names.
        assert result["pin_roles"]["dp"] == "3"
        assert result["pin_roles"]["dm"] == "4"
        assert result["pin_roles"]["xtal_in"] == "5"
        assert result["pin_roles"]["xtal_out"] == "6"

    def test_recommended_bypass_extracted_and_normalized(self):
        from circuit_weaver.datasheet_parser import parse_datasheet_text

        result = parse_datasheet_text(self.PIN_TABLE_TEXT)
        assert result["recommended_bypass"] == [{"net": "VDD", "value": "100nF", "count": 1}]

    def test_text_without_pin_table_emits_no_schema_fields(self):
        from circuit_weaver.datasheet_parser import parse_datasheet_text

        result = parse_datasheet_text("Output Voltage: 3.3 V, nothing else here")
        assert "pins" not in result
        assert "pin_roles" not in result
        assert "recommended_bypass" not in result

    def test_datasheet_entry_flows_through_build_generic_without_artifacts(self):
        """Corpus regression: a datasheet-derived part must route USB and
        crystal pins onto shared buses and NC pins into explicit no-connects
        with no synthetic {PIN}_{REF} nets or phantom boundary ports."""
        from circuit_weaver.datasheet_parser import parse_datasheet_text
        from circuit_weaver.subcircuits.topology_builders import build_generic

        ic_data = parse_datasheet_text(self.PIN_TABLE_TEXT)
        ic_data["_mpn"] = "DS_IMPORTED_MCU"
        ic_data["topology"] = "component"

        result = build_generic(ic_data, {"ic": "DS_IMPORTED_MCU", "ref": "U9"})
        comp = result.components[0]
        assert comp.power_pins["1"].startswith("VDD")
        assert comp.power_pins["2"] == "GND"
        assert comp.pin_nets["3"] == "USB_DP"
        assert comp.pin_nets["4"] == "USB_DM"
        assert comp.pin_nets["5"] == "XTAL_IN"
        assert comp.pin_nets["6"] == "XTAL_OUT"
        assert "8" in comp.explicit_no_connects
        assert comp.recommended_bypass == [{"net": "VDD", "value": "100nF", "count": 1}]
        # The EN pin has no declared interface — fail closed, not FOO_U9.
        assert comp.unmapped_required_pins.get("9") == "EN"
        # Declared debug pins are optional: unrouted SWDIO must not hard-fail.
        assert "7" not in comp.unmapped_required_pins
        for net in list(comp.pin_nets.values()) + [p.name for p in result.boundary_ports]:
            assert not net.endswith("_U9"), f"synthetic per-instance net leaked: {net}"
