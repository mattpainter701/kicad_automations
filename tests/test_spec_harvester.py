"""Tests for spec_harvester, datasheet_parser, and spice_fetcher modules."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

# ---------- spec_harvester tests ----------


def test_harvest_specs_compiles_design(tmp_path):
    from circuit_weaver.spec_harvester import harvest_specs

    with patch("circuit_weaver.spec_harvester.PartsLookup") as MockLookup:
        instance = MockLookup.return_value
        instance.lookup.return_value = {
            "mpn": "AP62300",
            "manufacturer": "Diodes Inc",
            "description": "Buck converter",
            "datasheet_url": "",
            "attributes": {"Voltage - Supply": "3.8V to 32V"},
            "stock": 5000,
            "lcsc": "C460320",
        }
        result = harvest_specs(_minimal_spec(), output_dir=str(tmp_path), skip_download=True)

    assert result["status"] == "ok"
    assert result["components_processed"] >= 1
    assert (tmp_path / "datasheets" / "index.json").exists()


def test_harvest_specs_writes_index_json(tmp_path):
    from circuit_weaver.spec_harvester import harvest_specs

    with patch("circuit_weaver.spec_harvester.PartsLookup") as MockLookup:
        instance = MockLookup.return_value
        instance.lookup.return_value = {
            "mpn": "AP62300",
            "manufacturer": "Diodes Inc",
            "description": "3.8V-32V Buck",
            "datasheet_url": "https://example.com/ap62300.pdf",
            "attributes": {},
            "stock": 100,
        }
        harvest_specs(_minimal_spec(), output_dir=str(tmp_path), skip_download=True, delay=0)

    index = json.loads((tmp_path / "datasheets" / "index.json").read_text(encoding="utf-8"))
    assert "parts" in index
    assert "AP62300" in index["parts"]
    assert index["parts"]["AP62300"]["datasheet_url"] == "https://example.com/ap62300.pdf"


def test_harvest_specs_extracts_ic_thermal(tmp_path):
    from circuit_weaver.spec_harvester import harvest_specs

    with patch("circuit_weaver.spec_harvester.PartsLookup") as MockLookup:
        instance = MockLookup.return_value
        instance.lookup.return_value = {
            "mpn": "AP62300",
            "manufacturer": "Diodes Inc",
            "description": "Buck converter 3.8-32V",
            "datasheet_url": "",
            "attributes": {"Voltage - Supply": "3.8V to 32V", "Current - Output": "2A"},
            "stock": 100,
        }
        harvest_specs(_minimal_spec(), output_dir=str(tmp_path), skip_download=True, delay=0)

    thermal_path = tmp_path / "specs" / "ic_thermal.json"
    assert thermal_path.exists()
    data = json.loads(thermal_path.read_text(encoding="utf-8"))
    assert "AP62300" in data
    assert data["AP62300"]["type"] in ("buck_converter", "ic")


def test_harvest_specs_error_on_bad_spec(tmp_path):
    from circuit_weaver.spec_harvester import harvest_specs

    result = harvest_specs({"not": "a valid spec"}, output_dir=str(tmp_path))
    assert result["status"] == "error"


def test_harvest_specs_skip_download_flag(tmp_path):
    from circuit_weaver.spec_harvester import harvest_specs

    with (
        patch("circuit_weaver.spec_harvester.PartsLookup") as MockLookup,
        patch("circuit_weaver.spec_harvester._download_datasheet") as mock_dl,
    ):
        instance = MockLookup.return_value
        instance.lookup.return_value = {
            "mpn": "AP62300",
            "manufacturer": "Diodes Inc",
            "description": "Buck",
            "datasheet_url": "https://example.com/ds.pdf",
            "attributes": {},
            "stock": 100,
        }
        harvest_specs(_minimal_spec(), output_dir=str(tmp_path), skip_download=True, delay=0)

    mock_dl.assert_not_called()


# ---------- datasheet_parser tests ----------


def test_parse_datasheet_missing_file():
    from circuit_weaver.datasheet_parser import parse_datasheet

    assert parse_datasheet("/nonexistent/path.pdf") == {}


def test_apply_patterns_extracts_theta_ja():
    from circuit_weaver.datasheet_parser import _PATTERNS, _apply_patterns

    text = "Thermal Characteristics\nθJA = 45.2 °C/W for SOIC-8 package"
    result = _apply_patterns(text, _PATTERNS)
    assert "theta_ja" in result
    assert result["theta_ja"] == pytest.approx(45.2)


def test_apply_patterns_extracts_tj_max():
    from circuit_weaver.datasheet_parser import _PATTERNS, _apply_patterns

    result = _apply_patterns("Maximum Junction Temperature: 150°C", _PATTERNS)
    assert result["tj_max"] == pytest.approx(150.0)


def test_apply_patterns_extracts_pdiss_mw():
    from circuit_weaver.datasheet_parser import _PATTERNS, _apply_patterns

    result = _apply_patterns("Maximum Power Dissipation = 500 mW at 25°C", _PATTERNS)
    assert result["pdiss_max_mw"] == pytest.approx(500.0)


def test_apply_patterns_extracts_fsw():
    from circuit_weaver.datasheet_parser import _PATTERNS, _apply_patterns

    result = _apply_patterns("Switching Frequency: 1.5 MHz typical", _PATTERNS)
    assert result["fsw_mhz"] == pytest.approx(1.5)


def test_extract_specs_no_directory(tmp_path):
    from circuit_weaver.datasheet_parser import extract_specs

    result = extract_specs(tmp_path / "nonexistent", tmp_path / "out")
    assert result["status"] == "error"


def test_extract_specs_empty_directory(tmp_path):
    from circuit_weaver.datasheet_parser import extract_specs

    ds_dir = tmp_path / "datasheets"
    ds_dir.mkdir()
    result = extract_specs(str(ds_dir), str(tmp_path / "out"))
    assert result["status"] in ("ok", "error")


# ---------- spice_fetcher tests ----------


def test_fetch_spice_models_compiles_design(tmp_path):
    from circuit_weaver.spice_fetcher import fetch_spice_models

    with patch("circuit_weaver.spice_fetcher._try_spice_urls", return_value=None):
        result = fetch_spice_models(_minimal_spec(), output_dir=str(tmp_path), delay=0)

    assert result["status"] == "ok"
    assert result["components_checked"] >= 0


def test_fetch_spice_error_on_bad_spec(tmp_path):
    from circuit_weaver.spice_fetcher import fetch_spice_models

    result = fetch_spice_models({"bad": "spec"}, output_dir=str(tmp_path))
    assert result["status"] == "error"


def test_guess_manufacturer_ti():
    from circuit_weaver.component_db import ComponentDef, PinDef
    from circuit_weaver.spice_fetcher import _guess_manufacturer

    comp = ComponentDef(
        mpn="TPS61023DRLR",
        description="Boost converter",
        pins=[PinDef(number="1", name="VIN", electrical_type="power_in", side="L")],
    )
    assert "texas instruments" in _guess_manufacturer(comp)


def test_guess_manufacturer_adi():
    from circuit_weaver.component_db import ComponentDef, PinDef
    from circuit_weaver.spice_fetcher import _guess_manufacturer

    comp = ComponentDef(
        mpn="ADP1706",
        description="LDO regulator",
        pins=[PinDef(number="1", name="VIN", electrical_type="power_in", side="L")],
    )
    assert "analog devices" in _guess_manufacturer(comp)


def test_is_analog_component():
    from circuit_weaver.component_db import ComponentDef, PinDef
    from circuit_weaver.spice_fetcher import _is_analog_component

    comp = ComponentDef(
        mpn="OPA2340",
        description="Dual op amp",
        pins=[PinDef(number="1", name="OUT", electrical_type="output", side="R")],
    )
    assert _is_analog_component(comp)


def test_is_high_speed_component():
    from circuit_weaver.component_db import ComponentDef, PinDef
    from circuit_weaver.spice_fetcher import _is_high_speed_component

    comp = ComponentDef(
        mpn="USB3300",
        description="USB 2.0 ULPI PHY",
        pins=[PinDef(number="1", name="DP", electrical_type="bidirectional", side="R")],
    )
    assert _is_high_speed_component(comp)


# ---------- CLI integration tests ----------


def test_cli_harvest_specs_help():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "circuit_weaver.dispatcher", "harvest-specs", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "harvest-specs" in result.stdout or "Download datasheets" in result.stdout


def test_cli_extract_specs_help():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "circuit_weaver.dispatcher", "extract-specs", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


def test_cli_fetch_spice_help():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "circuit_weaver.dispatcher", "fetch-spice", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "SPICE" in result.stdout or "fetch-spice" in result.stdout


# ---------- helpers ----------


def _minimal_spec() -> dict:
    return {
        "project": "TestProject",
        "power": [
            {
                "section": "power",
                "template": "buck",
                "ref": "U1",
                "ic": "AP62300",
                "params": {"vout": 3.3, "iout_max": 2.0},
            },
        ],
    }
