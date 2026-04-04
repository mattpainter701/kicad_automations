"""Tests for EasyEDA/LCSC symbol import pipeline.

Uses mock data — no live API calls. Tests cover:
- Pin parsing from tilde-delimited shape strings
- ComponentDef generation (power pins, signal pins, footprint, category)
- Resolution chain fallback (EasyEDA fires when KiCad lib misses)
- YAML ``lcsc:`` key triggers EasyEDA fetch
"""

from __future__ import annotations

import copy
from unittest.mock import patch

from circuit_weaver.component_db import ComponentDef, ComponentRegistry, PinDef
from circuit_weaver.easyeda_api import fetch_easyeda_component
from circuit_weaver.easyeda_parser import (
    _infer_category,
    _infer_footprint_from_package,
    _parse_pin,
    _rotation_to_side,
    easyeda_to_component_def,
    parse_symbol_shapes,
)

# ---------------------------------------------------------------------------
# Mock EasyEDA API response data
# ---------------------------------------------------------------------------

# ME6217C33M5G LDO in SOT-23-5 (5 pins)
MOCK_LDO_SHAPES = [
    "R~370~280~2~2~60~40~#880000~1~0~none~gge1~0~",
    "E~375~285~1.5~1.5~#880000~1~0~#880000~gge2~0",
    (
        "P~show~0~1~360~290~180~gge5~0^^360~290^^M360,290h10~#880000^^"
        "1~373.7~294~0~VIN~start~~~#0000FF^^1~369.5~289~0~1~end~~~#0000FF^^"
        "0~367~290^^0~M 370 293 L 373 290 L 370 287"
    ),
    (
        "P~show~0~2~360~300~180~gge6~0^^360~300^^M360,300h10~#000000^^"
        "1~373.7~304~0~VSS~start~~~#000000^^1~369.5~299~0~2~end~~~#000000^^"
        "0~367~300^^0~M 370 303 L 373 300 L 370 297"
    ),
    (
        "P~show~0~3~360~310~180~gge7~0^^360~310^^M360,310h10~#880000^^"
        "1~373.7~314~0~CE~start~~~#0000FF^^1~369.5~309~0~3~end~~~#0000FF^^"
        "0~367~310^^0~M 370 313 L 373 310 L 370 307"
    ),
    (
        "P~show~0~4~440~310~0~gge8~0^^440~310^^M 440 310 h -10~#880000^^"
        "1~426.3~314~0~NC~end~~~#0000FF^^1~430.5~309~0~4~start~~~#0000FF^^"
        "0~433~310^^0~M 430 307 L 427 310 L 430 313"
    ),
    (
        "P~show~0~5~440~290~0~gge9~0^^440~290^^M 440 290 h -10~#880000^^"
        "1~426.3~294~0~VOUT~end~~~#0000FF^^1~430.5~289~0~5~start~~~#0000FF^^"
        "0~433~290^^0~M 430 287 L 427 290 L 430 293"
    ),
]

MOCK_LDO_API_DATA = {
    "title": "ME6217C33M5G",
    "prefix": "U",
    "description": "300mA LDO 3.3V SOT-23-5",
    "lcsc_id": "C427602",
    "mpn": "ME6217C33M5G",
    "manufacturer": "MICRONE",
    "package": "SOT-23-5_L3.0-W1.7-P0.95-LS2.8-BR",
    "datasheet_url": "https://example.com/datasheet.pdf",
    "symbol_shapes": [MOCK_LDO_SHAPES],
    "footprint_shapes": [],
}

# Simple 2-pin capacitor
MOCK_CAP_SHAPES = [
    "PL~-2 8 -2 -8~#A00000~1~0~none~gge9~0",
    (
        "P~show~0~1~-20~0~180~gge10~0^^-20~0^^M -10 0 h -10~#800^^"
        "0~-6~0~0~1~start~~~#800^^0~-14~-4~0~1~end~~~#800^^"
        "0~-33~0^^0~M -30 3 L -27 0 L -30 -3"
    ),
    "PL~10 0 2 0~#A00000~1~0~none~gge19~0",
    "PL~2 -8 2 8~#A00000~1~0~none~gge20~0",
    (
        "P~show~0~2~20~0~0~gge21~0^^20~0^^M 10 0 h 10~#800^^"
        "0~6~0~0~2~end~~~#800^^0~14~-4~0~2~start~~~#800^^"
        "0~33~0^^0~M 30 -3 L 27 0 L 30 3"
    ),
    "PL~-2 0 -10 0~#A00000~1~0~none~gge28~0",
]

MOCK_CAP_API_DATA = {
    "title": "CC0603KRX7R9BB104",
    "prefix": "C",
    "description": "100nF 50V X7R 0603",
    "lcsc_id": "C14663",
    "mpn": "CC0603KRX7R9BB104",
    "manufacturer": "YAGEO",
    "package": "C0603",
    "datasheet_url": "",
    "symbol_shapes": [MOCK_CAP_SHAPES],
    "footprint_shapes": [],
}

# ESP32-WROVER module (39 pins, for testing large component)
MOCK_ESP32_SHAPES = [
    "R~300~180~2~2~100~130~#880000~1~0~none~gge1~0~",
    # GND pins
    (
        "P~show~0~39~390~190~0~gge2~0^^390~190^^M 390 190 h -10~#000000^^"
        "0~380~194~0~GND~end~~~#000000^^0~384~189~0~39~start~~~#000000^^"
        "0~387~190^^0~M 384 187 L 381 190 L 384 193"
    ),
    (
        "P~show~0~38~390~200~0~gge3~0^^390~200^^M 390 200 h -10~#000000^^"
        "0~380~204~0~GND~end~~~#000000^^0~384~199~0~38~start~~~#000000^^"
        "0~387~200^^0~M 384 197 L 381 200 L 384 203"
    ),
    # VDD pin
    (
        "P~show~4~2~310~180~270~gge4~0^^310~180^^M 310 180 v 10~#880000^^"
        "1~314~168~0~VDD~start~~~#0000FF^^1~309~172~0~2~end~~~#0000FF^^"
        "0~310~177^^0~M 307 174 L 310 171 L 313 174"
    ),
    # IO pins
    (
        "P~show~0~37~390~210~0~gge5~0^^390~210^^M 390 210 h -10~#880000^^"
        "0~380~214~0~IO23~end~~~#0000FF^^0~384~209~0~37~start~~~#0000FF^^"
        "0~387~210^^0~M 384 207 L 381 210 L 384 213"
    ),
    (
        "P~show~0~36~390~220~0~gge6~0^^390~220^^M 390 220 h -10~#880000^^"
        "0~380~224~0~IO22~end~~~#0000FF^^0~384~219~0~36~start~~~#0000FF^^"
        "0~387~220^^0~M 384 217 L 381 220 L 384 223"
    ),
    (
        "P~show~0~35~390~230~0~gge7~0^^390~230^^M 390 230 h -10~#880000^^"
        "0~380~234~0~TXD0~end~~~#0000FF^^0~384~229~0~35~start~~~#0000FF^^"
        "0~387~230^^0~M 384 227 L 381 230 L 384 233"
    ),
    (
        "P~show~0~34~390~240~0~gge8~0^^390~240^^M 390 240 h -10~#880000^^"
        "0~380~244~0~RXD0~end~~~#0000FF^^0~384~239~0~34~start~~~#0000FF^^"
        "0~387~240^^0~M 384 237 L 381 240 L 384 243"
    ),
    # EN pin (left side)
    (
        "P~show~0~3~310~310~90~gge9~0^^310~310^^M 310 310 v -10~#880000^^"
        "1~314~318~0~EN~end~~~#0000FF^^1~309~322~0~3~start~~~#0000FF^^"
        "0~310~313^^0~M 307 316 L 310 319 L 313 316"
    ),
]

MOCK_ESP32_API_DATA = {
    "title": "ESP32-WROVER-E(4MB)",
    "prefix": "U",
    "description": "WiFi+BT module ESP32-WROVER",
    "lcsc_id": "C529587",
    "mpn": "ESP32-WROVER-E-N4R8",
    "manufacturer": "Espressif",
    "package": "",
    "datasheet_url": "",
    "symbol_shapes": [MOCK_ESP32_SHAPES],
    "footprint_shapes": [],
}


# ================================================================
# Pin parsing tests
# ================================================================


class TestPinParsing:
    def test_parse_left_side_pin(self):
        shape = MOCK_LDO_SHAPES[2]  # VIN pin, rotation=180 (left side)
        pin = _parse_pin(shape)
        assert pin is not None
        assert pin.number == "1"
        assert pin.name == "VIN"
        assert pin.rotation == 180

    def test_parse_right_side_pin(self):
        shape = MOCK_LDO_SHAPES[6]  # VOUT pin, rotation=0 (right side)
        pin = _parse_pin(shape)
        assert pin is not None
        assert pin.number == "5"
        assert pin.name == "VOUT"
        assert pin.rotation == 0

    def test_parse_gnd_pin(self):
        shape = MOCK_LDO_SHAPES[3]  # VSS pin
        pin = _parse_pin(shape)
        assert pin is not None
        assert pin.number == "2"
        assert pin.name == "VSS"

    def test_parse_capacitor_pin(self):
        shape = MOCK_CAP_SHAPES[1]  # Pin 1
        pin = _parse_pin(shape)
        assert pin is not None
        assert pin.number == "1"
        assert pin.rotation == 180

    def test_non_pin_shape_returns_none(self):
        shape = "R~370~280~2~2~60~40~#880000~1~0~none~gge1~0~"
        pin = _parse_pin(shape)
        assert pin is None

    def test_rotation_to_side(self):
        assert _rotation_to_side(0) == "R"
        assert _rotation_to_side(180) == "L"
        assert _rotation_to_side(90) == "B"
        assert _rotation_to_side(270) == "T"
        assert _rotation_to_side(360) == "R"  # wraps

    def test_parse_power_typed_pin(self):
        """Pin with electrical_type=4 (power_in) should be classified correctly."""
        shape = MOCK_ESP32_SHAPES[3]  # VDD pin, elec=4
        pin = _parse_pin(shape)
        assert pin is not None
        assert pin.number == "2"
        assert pin.name == "VDD"
        assert pin.electrical_type == 4


# ================================================================
# Symbol assembly tests
# ================================================================


class TestSymbolAssembly:
    def test_parse_ldo_symbol(self):
        meta = {"pre": "U?", "name": "ME6217C33M5G", "Manufacturer Part": "ME6217C33M5G"}
        symbol = parse_symbol_shapes([MOCK_LDO_SHAPES], meta)
        assert len(symbol.pins) == 5
        assert symbol.prefix == "U"
        assert symbol.mpn == "ME6217C33M5G"
        pin_names = {p.name for p in symbol.pins}
        assert "VIN" in pin_names
        assert "VSS" in pin_names
        assert "VOUT" in pin_names

    def test_parse_capacitor_symbol(self):
        meta = {"pre": "C?", "name": "CC0603KRX7R9BB104"}
        symbol = parse_symbol_shapes([MOCK_CAP_SHAPES], meta)
        assert len(symbol.pins) == 2
        assert symbol.prefix == "C"

    def test_deduplicates_pins(self):
        """Same shapes passed twice as two units should not duplicate pins."""
        meta = {"pre": "U?"}
        symbol = parse_symbol_shapes([MOCK_LDO_SHAPES, MOCK_LDO_SHAPES], meta)
        assert len(symbol.pins) == 5  # Not 10


# ================================================================
# ComponentDef conversion tests
# ================================================================


class TestComponentDefConversion:
    def test_ldo_conversion(self):
        comp = easyeda_to_component_def(MOCK_LDO_API_DATA)
        assert comp is not None
        assert comp.mpn == "ME6217C33M5G"
        assert comp.ref_prefix == "U"
        assert comp.lcsc_pn == "C427602"
        assert "SOT-23-5" in comp.footprint
        assert len(comp.pins) == 5
        # VIN and VSS should be power pins
        assert "1" in comp.power_pins  # VIN
        assert "2" in comp.power_pins  # VSS/GND
        assert comp.power_pins["2"] == "GND"
        # CE and VOUT should be signal pins
        assert "3" in comp.pin_nets  # CE
        assert "5" in comp.pin_nets  # VOUT
        # LCSC tag
        assert "LCSC:C427602" in comp.features

    def test_capacitor_conversion(self):
        comp = easyeda_to_component_def(MOCK_CAP_API_DATA)
        assert comp is not None
        assert comp.ref_prefix == "C"
        assert comp.category == "passive"
        assert "0603" in comp.footprint
        assert len(comp.pins) == 2

    def test_esp32_power_classification(self):
        comp = easyeda_to_component_def(MOCK_ESP32_API_DATA)
        assert comp is not None
        assert comp.category == "mcu"  # "wifi" or "esp32" in description
        # VDD pin should be power
        assert "2" in comp.power_pins
        # GND pins should be power
        assert "39" in comp.power_pins
        assert "38" in comp.power_pins
        assert comp.power_pins["39"] == "GND"
        # IO pins should be signal
        assert "37" in comp.pin_nets
        assert comp.pin_nets["37"] == "IO23"

    def test_empty_data_returns_none(self):
        assert easyeda_to_component_def({}) is None
        assert easyeda_to_component_def({"symbol_shapes": []}) is None

    def test_no_pins_returns_none(self):
        data = copy.deepcopy(MOCK_LDO_API_DATA)
        data["symbol_shapes"] = [["R~1~2~3~4~5~6~#000~1~0~none~id~0"]]
        assert easyeda_to_component_def(data) is None


# ================================================================
# Footprint inference tests
# ================================================================


class TestFootprintInference:
    def test_sot23_5_before_sot23(self):
        fp = _infer_footprint_from_package("SOT-23-5_L3.0-W1.7-P0.95-LS2.8-BR", "U", 5)
        assert "SOT-23-5" in fp

    def test_sot23_3_pin(self):
        fp = _infer_footprint_from_package("SOT-23", "Q", 3)
        assert "SOT-23" in fp
        assert "SOT-23-5" not in fp

    def test_soic8(self):
        fp = _infer_footprint_from_package("SOIC-8_EP_3.9x4.9mm", "U", 8)
        assert "SOIC-8" in fp

    def test_passive_0402(self):
        fp = _infer_footprint_from_package("R0402", "R", 2)
        assert "0402" in fp
        assert "Resistor_SMD" in fp

    def test_cap_0603(self):
        fp = _infer_footprint_from_package("C0603", "C", 2)
        assert "0603" in fp
        assert "Capacitor_SMD" in fp

    def test_unknown_package(self):
        fp = _infer_footprint_from_package("CUSTOM_PKG", "U", 16)
        assert fp == ""

    def test_empty_package(self):
        fp = _infer_footprint_from_package("", "U", 8)
        assert fp == ""

    def test_qfn_32(self):
        fp = _infer_footprint_from_package("QFN-32(5x5)", "U", 32)
        assert "QFN-32" in fp


# ================================================================
# Category inference tests
# ================================================================


class TestCategoryInference:
    def test_passive_prefix(self):
        assert _infer_category("R", "RC0402", "", "") == "passive"
        assert _infer_category("C", "GRM155", "", "") == "passive"
        assert _infer_category("L", "LQH32", "", "") == "passive"

    def test_connector_prefix(self):
        assert _infer_category("J", "USB-C", "", "") == "connector"

    def test_mcu_from_description(self):
        assert _infer_category("U", "STM32F103", "STM32 microcontroller", "") == "mcu"

    def test_power_from_description(self):
        assert _infer_category("U", "TPS62160", "3.3V buck converter", "") == "power"

    def test_default_digital(self):
        assert _infer_category("U", "CUSTOM_IC", "custom part", "") == "digital"


# ================================================================
# Resolution chain integration tests
# ================================================================


class TestResolutionChain:
    def test_easyeda_fallback_with_lcsc_key(self):
        """YAML item with lcsc: key resolves via EasyEDA when other tiers miss."""
        from circuit_weaver.project_spec import _try_easyeda_resolve

        item = {"ic": "ME6217C33M5G", "ref": "U5", "lcsc": "C427602"}

        # Mock the EasyEDA API call
        with patch("circuit_weaver.easyeda_api.fetch_easyeda_component") as mock_fetch:
            mock_fetch.return_value = MOCK_LDO_API_DATA
            comp = _try_easyeda_resolve(item, "ME6217C33M5G")

        assert comp is not None
        assert comp.mpn == "ME6217C33M5G"
        assert comp.lcsc_pn == "C427602"
        assert len(comp.pins) == 5
        mock_fetch.assert_called_once_with("C427602")

    def test_easyeda_fallback_via_mpn_lookup(self):
        """When no lcsc: key, uses parts_lookup to find LCSC code, then fetches."""
        from circuit_weaver.project_spec import _try_easyeda_resolve

        item = {"ic": "ME6217C33M5G", "ref": "U5"}

        class MockPartsLookup:
            def lookup(self, mpn):
                if mpn == "ME6217C33M5G":
                    return {"lcsc": "C427602", "mpn": "ME6217C33M5G"}
                return None

        with patch("circuit_weaver.easyeda_api.fetch_easyeda_component") as mock_fetch:
            mock_fetch.return_value = MOCK_LDO_API_DATA
            comp = _try_easyeda_resolve(item, "ME6217C33M5G", parts_lookup=MockPartsLookup())

        assert comp is not None
        assert comp.lcsc_pn == "C427602"
        mock_fetch.assert_called_once_with("C427602")

    def test_explicit_lcsc_overrides_registry_resolution(self):
        """An explicit lcsc: key should prefer EasyEDA even if the registry hits."""
        from circuit_weaver.project_spec import _resolve_component
        from circuit_weaver.subcircuits.base import get_default_registry

        registry = ComponentRegistry()
        registry.register(
            ComponentDef(
                mpn="REG_PART",
                ref_prefix="U",
                value="REG_PART",
                description="Registry component",
                pins=[PinDef("1", "IN", "input", "L")],
                pin_nets={"1": "IN"},
            )
        )

        item = {"ic": "REG_PART", "ref": "U5", "lcsc": "C427602"}
        with patch("circuit_weaver.easyeda_api.fetch_easyeda_component") as mock_fetch:
            mock_fetch.return_value = MOCK_LDO_API_DATA
            result = _resolve_component(item, "power", get_default_registry(), registry, None)

        assert len(result) == 1
        assert result[0].mpn == "ME6217C33M5G"
        assert result[0].lcsc_pn == "C427602"
        mock_fetch.assert_called_once_with("C427602")

    def test_easyeda_fallback_no_lcsc_returns_none(self):
        """When no LCSC code is available, returns None gracefully."""
        from circuit_weaver.project_spec import _try_easyeda_resolve

        item = {"ic": "MYSTERY_IC", "ref": "U9"}
        comp = _try_easyeda_resolve(item, "MYSTERY_IC")
        assert comp is None

    def test_easyeda_fetch_failure_returns_none(self):
        """API failure returns None (doesn't crash)."""
        from circuit_weaver.project_spec import _try_easyeda_resolve

        item = {"ic": "BAD_PART", "ref": "U9", "lcsc": "C999999"}

        with patch("circuit_weaver.easyeda_api.fetch_easyeda_component") as mock_fetch:
            mock_fetch.return_value = None
            comp = _try_easyeda_resolve(item, "BAD_PART")

        assert comp is None

    def test_easyeda_fetch_exception_returns_none(self):
        """API exception is caught and returns None."""
        from circuit_weaver.project_spec import _try_easyeda_resolve

        item = {"ic": "BAD_PART", "ref": "U9", "lcsc": "C999999"}

        with patch("circuit_weaver.easyeda_api.fetch_easyeda_component") as mock_fetch:
            mock_fetch.side_effect = ConnectionError("timeout")
            comp = _try_easyeda_resolve(item, "BAD_PART")

        assert comp is None


# ================================================================
# ComponentDef field tests
# ================================================================


class TestComponentDefFields:
    def test_lcsc_pn_field_exists(self):
        comp = ComponentDef(mpn="TEST")
        assert comp.lcsc_pn == ""
        comp.lcsc_pn = "C14663"
        assert comp.lcsc_pn == "C14663"

    def test_digikey_pn_field_exists(self):
        comp = ComponentDef(mpn="TEST")
        assert comp.digikey_pn == ""
        comp.digikey_pn = "490-10698-1-ND"
        assert comp.digikey_pn == "490-10698-1-ND"

    def test_easyeda_conversion_sets_lcsc_feature(self):
        comp = easyeda_to_component_def(MOCK_LDO_API_DATA)
        assert any("LCSC:" in f for f in comp.features)
        assert comp.lcsc_pn == "C427602"


class TestEasyEDAApiClient:
    def test_partial_uuid_fetch_returns_none(self):
        """Missing any UUID payload should fail closed instead of returning a partial symbol."""
        symbol_payload = {
            "title": "ME6217C33M5G",
            "dataStr": '{"head": {"c_para": {"pre": "U?", "Manufacturer Part": "ME6217C33M5G"}}}',
        }

        with patch("circuit_weaver.easyeda_api._fetch_component_uuids", return_value=["sym-1", "fp-1"]):
            with patch(
                "circuit_weaver.easyeda_api._fetch_component_data",
                side_effect=[symbol_payload, None],
            ):
                assert fetch_easyeda_component("C427602", use_cache=False) is None
