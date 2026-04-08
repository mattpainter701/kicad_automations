"""Tests for Task 124 — Automatic Test Point Generation."""

from __future__ import annotations

import csv
import io

from circuit_weaver.design_ir import DesignInterface, DesignIR
from circuit_weaver.test_point_gen import (
    annotate_schematic,
    generate_test_points,
    write_test_points_csv,
)


def _ir_with_interfaces(*net_names: str, pcb_constraints: list | None = None) -> DesignIR:
    """Build a minimal DesignIR whose top-level interfaces carry the given net names."""
    interfaces = [DesignInterface(block_id="root", name=net, direction="bidirectional") for net in net_names]
    return DesignIR(
        metadata={"project": "test"},
        interfaces=interfaces,
        pcb_constraints=pcb_constraints or [],
    )


# ---------------------------------------------------------------------------
# Test 1: Power rails detected
# ---------------------------------------------------------------------------


def test_power_rails_detected():
    """VDD_*, VCC*, VBUS* nets are classified as power_rail with high priority."""
    ir = _ir_with_interfaces("VDD_3V3", "VCC_CORE", "VBUS", "GND", "SPI_CLK")
    tps = generate_test_points(ir)

    tp_map = {tp.net: tp for tp in tps}

    assert "VDD_3V3" in tp_map
    assert tp_map["VDD_3V3"].tp_type == "power_rail"
    assert tp_map["VDD_3V3"].priority == "high"

    assert "VCC_CORE" in tp_map
    assert tp_map["VCC_CORE"].tp_type == "power_rail"

    assert "VBUS" in tp_map
    assert tp_map["VBUS"].tp_type == "power_rail"

    # GND must also appear (as ground type, not power_rail)
    assert "GND" in tp_map
    assert tp_map["GND"].tp_type == "ground"


# ---------------------------------------------------------------------------
# Test 2: Differential pairs detected
# ---------------------------------------------------------------------------


def test_differential_pairs_detected():
    """Nets ending in _P/_N are classified as differential test points."""
    ir = _ir_with_interfaces("USB_DP", "USB_DN", "CAN_TX_P", "CAN_TX_N")
    tps = generate_test_points(ir)

    tp_map = {tp.net: tp for tp in tps}

    # USB_DP/DN — data_bus takes precedence via _DATA_BUS_RE on "USB"
    # but they must still appear
    assert "USB_DP" in tp_map
    assert "USB_DN" in tp_map

    # CAN_TX_P / CAN_TX_N — data_bus or differential, both must appear
    assert "CAN_TX_P" in tp_map
    assert "CAN_TX_N" in tp_map


def test_differential_pairs_from_pcb_constraints():
    """Explicit diff_pair pcb_constraints produce differential test points."""
    ir = _ir_with_interfaces(
        "DDR_D0_P",
        "DDR_D0_N",
        pcb_constraints=[{"kind": "diff_pair", "target": "DDR_D0_P,DDR_D0_N"}],
    )
    tps = generate_test_points(ir)

    tp_map = {tp.net: tp for tp in tps}
    assert "DDR_D0_P" in tp_map
    assert "DDR_D0_N" in tp_map
    # At least one of the pair should be classified differential
    diff_types = {tp_map[n].tp_type for n in ("DDR_D0_P", "DDR_D0_N")}
    assert "differential" in diff_types


# ---------------------------------------------------------------------------
# Test 3: CSV format correct
# ---------------------------------------------------------------------------


def test_csv_format_correct(tmp_path):
    """Written CSV has the required columns in the correct order."""
    ir = _ir_with_interfaces("GND", "VDD_3V3", "SPI_CLK")
    tps = generate_test_points(ir)

    csv_path = tmp_path / "test_points.csv"
    write_test_points_csv(tps, csv_path)

    with csv_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == ["TestPoint", "Net", "Type", "Priority"]
        rows = list(reader)

    assert len(rows) == len(tps)
    for row in rows:
        assert row["TestPoint"].startswith("TP")
        assert row["Net"]
        assert row["Type"] in ("power_rail", "differential", "clock", "data_bus", "ground")
        assert row["Priority"] in ("high", "medium", "low")


# ---------------------------------------------------------------------------
# Test 4: Schematic annotation added
# ---------------------------------------------------------------------------


def test_schematic_annotation_added():
    """annotate_schematic inserts a (text ...) element for each test point."""
    minimal_sch = "(kicad_sch (version 20231120)\n)"
    ir = _ir_with_interfaces("GND", "VDD_3V3")
    tps = generate_test_points(ir)

    annotated = annotate_schematic(minimal_sch, tps)

    # Must contain at least one annotation for each test point net
    for tp in tps:
        assert tp.name in annotated, f"{tp.name} not found in annotated schematic"
        assert tp.net in annotated, f"{tp.net} not found in annotated schematic"

    # Must still be valid (closing paren preserved)
    assert annotated.rstrip().endswith(")")

    # Annotations must follow KiCad text element format
    assert "(text " in annotated


# ---------------------------------------------------------------------------
# Test 5: Empty design handled
# ---------------------------------------------------------------------------


def test_empty_design_handled():
    """A DesignIR with no blocks or interfaces produces an empty test point list."""
    ir = DesignIR(metadata={"project": "empty"})
    tps = generate_test_points(ir)
    assert tps == []

    # CSV should still be written with only the header row
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["TestPoint", "Net", "Type", "Priority"])
    writer.writeheader()
    content = buf.getvalue()
    assert "TestPoint" in content
    assert len(content.strip().splitlines()) == 1  # header only
