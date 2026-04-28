"""Smoke tests for circuit_weaver.si_constraints.

Tests the analyze_si_constraints() function with compiled designs and
manually constructed ComponentDef objects to verify:
- Return value structure
- Empty/edge-case handling
- Bus detection from pin nets and descriptions
- Component filtering (source_ref required)
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from circuit_weaver.component_db import ComponentDef
from circuit_weaver.design_loader import compile_design_ir
from circuit_weaver.si_constraints import analyze_si_constraints

_SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"
_IOT_SENSOR_YAML = _SAMPLES_DIR / "iot_sensor_node" / "iot_sensor_node.yaml"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def iot_sensor_components():
    """Compile the IoT sensor spec and return its ComponentDef list."""
    with open(_IOT_SENSOR_YAML) as f:
        spec = yaml.safe_load(f)
    compiled = compile_design_ir(spec)
    return compiled.components


# ---------------------------------------------------------------------------
# Structural and edge-case tests
# ---------------------------------------------------------------------------


def test_analyze_si_constraints_returns_dict(iot_sensor_components):
    """Smoke: passing compiled IoT sensor components returns a dict."""
    result = analyze_si_constraints(iot_sensor_components)
    assert isinstance(result, dict)


def test_result_has_expected_structure(iot_sensor_components):
    """Result dict contains all documented top-level keys."""
    result = analyze_si_constraints(iot_sensor_components)
    expected_keys = {
        "status",
        "buses_detected",
        "diff_pairs",
        "impedance_constraints",
        "length_groups",
        "routing_rules",
        "warnings",
        "summary",
    }
    assert expected_keys.issubset(result.keys()), (
        f"Missing keys: {expected_keys - set(result)}"
    )
    assert result["status"] == "ok"


def test_empty_components_returns_safe_dict():
    """Empty component list does not crash and returns a valid dict."""
    result = analyze_si_constraints([])
    assert isinstance(result, dict)
    assert result["status"] == "ok"
    assert result["buses_detected"] == []
    assert result["diff_pairs"] == []
    assert result["impedance_constraints"] == []
    assert result["length_groups"] == []
    assert result["routing_rules"] == []
    assert result["warnings"] == []
    assert "No high-speed buses detected" in result["summary"]


def test_iot_sensor_no_si_buses_graceful(iot_sensor_components):
    """IoT sensor has no SI-sensitive pins; verifies graceful empty output."""
    result = analyze_si_constraints(iot_sensor_components)
    assert result["status"] == "ok"
    assert result["buses_detected"] == []
    assert result["diff_pairs"] == []
    assert result["impedance_constraints"] == []
    assert result["length_groups"] == []
    assert result["routing_rules"] == []
    assert "No high-speed buses detected" in result["summary"]


def test_components_without_source_ref_skipped():
    """Components with empty source_ref are silently skipped."""
    comp = ComponentDef(
        mpn="SOME_IC",
        source_ref="",
        description="USB 2.0 Controller",
        pin_nets={"1": "DP", "2": "DM"},
    )
    result = analyze_si_constraints([comp])
    # source_ref is empty → component is skipped → no buses detected
    assert result["buses_detected"] == []
    assert "No high-speed buses detected" in result["summary"]


# ---------------------------------------------------------------------------
# Bus detection tests (construct ComponentDef manually)
# ---------------------------------------------------------------------------


def test_usb_bus_detected_from_nets():
    """Component with USB DP/DM net names triggers USB2 SI detection."""
    comp = ComponentDef(
        mpn="USB_CONN",
        source_ref="J1",
        description="USB Connector",
        pin_nets={"1": "VBUS", "2": "DP", "3": "DM", "4": "GND"},
    )
    result = analyze_si_constraints([comp])

    assert len(result["buses_detected"]) == 1
    bus = result["buses_detected"][0]
    assert bus["bus_type"] == "usb2"
    assert bus["component"] == "J1"
    assert bus["net_count"] >= 2

    # Should detect at least one differential pair
    assert len(result["diff_pairs"]) >= 1

    # Should have impedance constraint for USB2 (z_diff: 90)
    assert len(result["impedance_constraints"]) >= 1
    ic = result["impedance_constraints"][0]
    assert ic["bus_type"] == "usb2"
    assert ic["type"] == "differential"
    assert ic["target_ohms"] == 90

    # USB should also generate routing rules
    assert len(result["routing_rules"]) >= 1
    assert result["routing_rules"][0]["bus_type"] == "usb2"

    # Length matching for USB2 (≥ 2 nets → length group)
    assert any(g["bus_type"] == "usb2" for g in result["length_groups"])

    assert "usb2" in result["summary"].lower()


def test_bus_detected_from_description():
    """Component whose description mentions USB is detected if pin nets
    don't match directly."""
    comp = ComponentDef(
        mpn="MY_USB_IC",
        source_ref="U1",
        description="USB 2.0 PHY Controller IC",
        pin_nets={"1": "VDD", "2": "GND", "3": "CLK"},
    )
    result = analyze_si_constraints([comp])

    # Description pattern matches usb2
    assert len(result["buses_detected"]) == 1
    assert result["buses_detected"][0]["bus_type"] == "usb2"


def test_no_si_sensitive_pins():
    """Component with only power/generic pins yields no SI constraints."""
    comp = ComponentDef(
        mpn="GPIO_EXPANDER",
        source_ref="U5",
        description="General purpose I/O expander",
        pin_nets={"1": "VDD", "2": "GND", "3": "GPIO1", "4": "GPIO2"},
    )
    result = analyze_si_constraints([comp])
    assert result["buses_detected"] == []
    assert "No high-speed buses detected" in result["summary"]
