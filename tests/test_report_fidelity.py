"""Sprint 40 Task 172 — report must describe only what's in the design.

The IoT AQ Sensor audit shipped a report that claimed "BME688 I2C + pull-ups"
and "LED + current-limit R4 = 330Ω" when the emitted schematic contained
zero wires for any of those components. The report was pulling annotations
from template boilerplate rather than what the placer actually emitted.

``verify_report_fidelity`` is a diagnostic the test suite and generation
pipeline can run against any report text to catch references to
components or nets that don't exist in the resolved design.
"""

from __future__ import annotations

from circuit_weaver.component_db import ComponentDef, PinDef
from circuit_weaver.report import verify_report_fidelity


def _mcu(ref: str = "U1") -> ComponentDef:
    return ComponentDef(
        mpn="GENERIC-MCU-32",
        ref_prefix="U",
        value="GENERIC-MCU-32",
        footprint="Package_QFP:LQFP-32",
        category="digital",
        source_ref=ref,
        pins=[PinDef(str(i), f"P{i}", "bidirectional", "L" if i % 2 else "R") for i in range(1, 33)],
        power_pins={"1": "VDD_3P3", "32": "GND"},
        pin_nets={"5": "SDA", "6": "SCL"},
    )


def test_fidelity_passes_for_report_that_only_names_real_refs_and_nets():
    comps = [_mcu("U1")]
    report_text = (
        "## Power Tree\n"
        "external -> [VDD_3P3] -> U1\n"
        "## Design Rationale\n"
        "### U1 — GENERIC-MCU-32\n"
        "- Uses SDA and SCL for I2C\n"
    )
    result = verify_report_fidelity(report_text, comps)
    assert result["ghost_refs"] == [], result
    assert result["ghost_nets"] == [], result
    assert result["stub_annotations"] == []


def test_fidelity_flags_ghost_component_references():
    """Report names U2, R4, LED1 — none of which exist in the design."""
    comps = [_mcu("U1")]
    report_text = "### U2 — BME688\n- I2C connection via R4 pull-up\n### LED1 — status indicator\n"
    result = verify_report_fidelity(report_text, comps)
    assert "U2" in result["ghost_refs"]
    assert "R4" in result["ghost_refs"]
    assert "LED1" in result["ghost_refs"]


def test_fidelity_flags_ghost_nets():
    """Report names SDA/SCL/SWDIO/SWO — only SDA and SCL are on real pins."""
    comps = [_mcu("U1")]
    report_text = (
        "### U1 — MCU\n"
        "- Debug: SWDIO and SWO exposed on pins 36/37\n"
        "- Sensor bus: SDA/SCL routed to external connector\n"
    )
    result = verify_report_fidelity(report_text, comps)
    assert "SWDIO" in result["ghost_nets"]
    assert "SWO" in result["ghost_nets"]
    # SDA and SCL are real pin_nets and must NOT be flagged
    assert "SDA" not in result["ghost_nets"]
    assert "SCL" not in result["ghost_nets"]


def test_fidelity_flags_ghost_annotations_inside_components():
    """An annotation attached to U1 that references R99 (nonexistent) is
    a ghost-feature claim even if the report text itself never mentions R99
    directly. The IoT AQ regression was exactly this pattern — U1's
    annotation claimed "EN=10k pull-up (R5) + IO0=10k pull-up (R6)" when
    R6 didn't exist.
    """
    comp = _mcu("U1")
    comp.annotations = [
        "EN=10k pull-up via R99 + 1uF cap",
        "Designed for I2C bus",
    ]
    result = verify_report_fidelity(report_text="", components=[comp])
    ghost_refs = [s["ghost_ref"] for s in result["stub_annotations"]]
    assert "R99" in ghost_refs, result


def test_user_reported_iot_audit_would_be_caught():
    """Reconstruct the IoT AQ audit scenario and prove the fidelity check
    catches it. The audit report called out BME688 I2C + pull-ups and
    LED current-limit chain, none of which existed in the schematic.
    """
    u1 = _mcu("U1")
    # Simulate the audited output: U1 is present, but BME688 / LED1 / R4 /
    # SW1 are not wired — they'd fail to appear in the resolved components
    # list because the generator stubbed them out.
    comps = [u1]
    report_text = (
        "### U2 — BME688\n"
        "- CACHED: from digikey via symbol cache\n"
        "- I2C bus: SDA + SCL + 10k pull-ups\n"
        "### LED1 — status\n"
        "- Current-limited by R4 (330Ω) from VBAT\n"
        "### SW1 — tactile reset\n"
    )
    result = verify_report_fidelity(report_text, comps)
    assert {"U2", "LED1", "R4", "SW1"}.issubset(set(result["ghost_refs"]))
    assert "VBAT" in result["ghost_nets"]


# ---------------------------------------------------------------------------
# Power tree section — release-prep regressions
# ---------------------------------------------------------------------------

from circuit_weaver.component_db import BypassCap, PowerReq, StrapConfig  # noqa: E402
from circuit_weaver.report import _power_tree_section  # noqa: E402


def _buck(ref: str = "U1") -> ComponentDef:
    """A buck regulator whose output rail is only reachable through the
    external inductor — no power pin carries the rail net directly."""
    return ComponentDef(
        mpn="GENERIC-BUCK",
        ref_prefix="U",
        value="GENERIC-BUCK",
        footprint="Package_TO_SOT_SMD:SOT-23-6",
        category="power",
        source_ref=ref,
        pins=[
            PinDef("1", "VIN", "power_in", "L"),
            PinDef("2", "GND", "power_in", "L"),
            PinDef("3", "SW", "output", "R"),
            PinDef("4", "FB", "input", "R"),
        ],
        power_pins={"1": "VBUS_5V", "2": "GND"},
        pin_nets={"3": f"SW_{ref}", "4": f"FB_{ref}"},
        bypass_caps=[
            BypassCap("CIN", "VBUS_5V", "GND", "10uF", "C_0805", role="input_cap"),
            BypassCap("COUT", "VDD_3P3", "GND", "22uF", "C_0805", role="output_cap"),
            BypassCap("L", f"SW_{ref}", "VDD_3P3", "3.3uH", "L_0806", role="inductor"),
            BypassCap("CBST", f"BST_{ref}", f"SW_{ref}", "100nF", "C_0402", role="bootstrap_cap"),
        ],
        straps=[
            StrapConfig("4", f"FB_{ref}", "VDD_3P3", "100k", "R_0402", role="feedback_top"),
        ],
    )


def test_power_tree_credits_regulator_output_rail_to_the_regulator():
    """A buck whose rail is reached through the inductor must still show as
    the rail's source, not 'external'."""
    tree = _power_tree_section([_buck("U1"), _mcu("U2")])
    assert "U1 -> [VDD_3P3]" in tree, tree
    assert "external -> [VDD_3P3]" not in tree, tree
    assert "U2" in tree.split("[VDD_3P3]")[1].splitlines()[0], tree


def test_power_tree_excludes_internal_switching_nodes():
    """SW_x / BST_x per-instance nets are regulator plumbing, not rails."""
    tree = _power_tree_section([_buck("U1"), _mcu("U2")])
    assert "SW_U1" not in tree, tree
    assert "BST_U1" not in tree, tree


def test_power_tree_does_not_repeat_source_as_consumer():
    """The rail's source must not also be listed among its consumers, and
    support-passive suffixes like 'U1:CBST' must not appear."""
    tree = _power_tree_section([_buck("U1"), _mcu("U2")])
    rail_line = next(line for line in tree.splitlines() if "[VDD_3P3]" in line)
    consumers = rail_line.split("->")[-1]
    assert "U1" not in consumers, tree
    assert ":" not in consumers, tree


def test_power_tree_marks_unconsumed_rails():
    tree = _power_tree_section([_buck("U1")])
    rail_line = next(line for line in tree.splitlines() if "[VDD_3P3]" in line)
    assert "(no consumers)" in rail_line, tree


def test_power_tree_serializes_declared_envelopes_without_turning_unknowns_into_zeroes():
    consumer = _mcu("U2")
    consumer.power_reqs = [
        PowerReq(
            "VDD_3P3", v_min=3.0, v_nominal=3.3, v_max=3.6, direction="load",
            i_steady_ma=80, i_peak_ma=140, sequence_order=2,
            sequence_dependency="VDD_1V8", tolerance=0.1, evidence_id="EV-DATASHEET-123456789abc",
        )
    ]
    tree = _power_tree_section([_buck("U1"), consumer])
    assert "### Operating Envelopes" in tree
    assert "3.6" in tree and "140" in tree
    assert "EV-DATASHEET-123456789abc" in tree


def test_power_tree_does_not_relabel_legacy_peak_current_as_steady_current():
    consumer = _mcu("U2")
    consumer.power_reqs = [PowerReq("VDD_3P3", 3.3, 140)]

    tree = _power_tree_section([consumer])
    envelope_row = next(line for line in tree.splitlines() if line.startswith("| VDD_3P3 |"))

    assert "| — | 140 |" in envelope_row
