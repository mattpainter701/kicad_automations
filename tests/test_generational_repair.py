"""Tests for generational_repair.py — auto-repair pipeline.

Sprint 44 T191 — dedicated unit tests for the auto-repair pass that
synthesizes missing conditioning blocks (I2C pull-ups, etc.).
"""

from __future__ import annotations

import pytest

from circuit_weaver.design_ir import DesignBlock, DesignIR
from circuit_weaver.component_db import ComponentDef, PinDef
from circuit_weaver.generational_repair import (
    RepairAction,
    auto_repair_design,
    _is_ground,
)


class TestIsGround:
    """_is_ground() helper — net name convention matching."""

    def test_ground_nets_match(self):
        assert _is_ground("GND") is True
        assert _is_ground("AGND") is True
        assert _is_ground("DGND") is True
        assert _is_ground("PGND") is True
        assert _is_ground("VSS") is True
        assert _is_ground("GNDA") is True
        assert _is_ground("GNDD") is True

    def test_ground_prefixes_match(self):
        assert _is_ground("GND_MAIN") is True
        assert _is_ground("AGND_POWER") is True
        assert _is_ground("PGND_P1") is True

    def test_non_ground_does_not_match(self):
        assert _is_ground("") is False
        assert _is_ground("VDD") is False
        assert _is_ground("SIGNAL") is False
        assert _is_ground("3.3V") is False
        assert _is_ground(None) is False

    def test_case_insensitive(self):
        assert _is_ground("gnd") is True
        assert _is_ground("agnd") is True
        assert _is_ground("Vss") is True


class TestRepairActionDataclass:
    """RepairAction dataclass — construction, to_dict, repr."""

    def test_construction(self):
        action = RepairAction(kind="i2c_pullups", rationale="Added RP1")
        assert action.kind == "i2c_pullups"
        assert action.rationale == "Added RP1"

    def test_to_dict(self):
        action = RepairAction(
            kind="i2c_pullups",
            rationale="Added RP1 on I2C_SDA/I2C_SCL",
            synthetic_block_id="digital:RP1:abc123",
            nets=["I2C_SDA", "I2C_SCL", "VDD"],
        )
        d = action.to_dict()
        assert d["kind"] == "i2c_pullups"
        assert d["synthetic_block_id"] == "digital:RP1:abc123"
        assert "I2C_SDA" in d["nets"]

    def test_default_fields(self):
        action = RepairAction(kind="test", rationale="")
        d = action.to_dict()
        assert d["rationale"] == ""
        assert d["synthetic_block_id"] == ""
        assert d["nets"] == []


class TestAutoRepairDesign:
    """auto_repair_design() — the main entry point."""

    def _make_ir(self, blocks: list[dict]) -> DesignIR:
        """Helper: build a DesignIR from block dicts."""
        return DesignIR(
            metadata={"project": "test"},
            blocks=[DesignBlock(
                id=b.get("id", ""),
                section=b.get("section", "digital"),
                kind=b.get("kind", "digital"),
                ref=b.get("ref", ""),
                template_type=b.get("template_type", ""),
                ic=b.get("ic", ""),
                params=b.get("params", {}),
            ) for b in blocks],
            interfaces=[],
        )

    def _make_component(self, ref: str, pin_nets: dict[str, str],
                        power_pins: dict[str, str] | None = None) -> ComponentDef:
        """Helper: build a minimal ComponentDef with pin nets."""
        pins = []
        for num in pin_nets:
            pins.append(PinDef(
                number=num, name=f"pin{num}",
                electrical_type="bidirectional", side="L",
            ))
        return ComponentDef(
            mpn=f"IC_{ref}",
            source_ref=ref,
            pins=pins,
            pin_nets=dict(pin_nets),
            power_pins=dict(power_pins or {}),
        )

    def test_enabled_by_default(self):
        """auto_repair runs and produces repair actions when enabled."""
        ir = self._make_ir([
            {"ref": "U1", "kind": "digital", "template_type": "mcu",
             "params": {"vdd_net": "VDD", "sda_net": "I2C_SDA", "scl_net": "I2C_SCL"}},
        ])
        components = [self._make_component("U1", {"1": "VDD", "2": "I2C_SDA", "3": "I2C_SCL"},
                                            power_pins={"4": "VDD"})]

        repaired, actions = auto_repair_design(ir, components, enabled=True)

        assert len(actions) > 0, "Expected at least one repair action for I2C design"
        assert any(a.kind == "i2c_pullups" for a in actions)

    def test_disabled_via_flag(self):
        """auto_repair does nothing when disabled."""
        ir = self._make_ir([
            {"ref": "U1", "kind": "digital", "template_type": "mcu",
             "params": {"vdd_net": "VDD", "sda_net": "I2C_SDA", "scl_net": "I2C_SCL"}},
        ])
        components = [self._make_component("U1", {"1": "VDD", "2": "I2C_SDA", "3": "I2C_SCL"},
                                            power_pins={"4": "VDD"})]

        repaired, actions = auto_repair_design(ir, components, enabled=False)

        assert len(actions) == 0, "No repair actions expected when disabled"

    def test_skips_when_i2c_block_already_present(self):
        """Auto-repair suppresses I2C pull-up synthesis when an i2c_bus block
        already exists in the design."""
        ir = self._make_ir([
            {"ref": "U1", "kind": "digital", "template_type": "mcu",
             "params": {"vdd_net": "VDD", "sda_net": "I2C_SDA", "scl_net": "I2C_SCL"}},
            {"ref": "RP1", "kind": "digital", "template_type": "i2c_bus",
             "params": {"vdd": 3.3, "sda_net": "I2C_SDA", "scl_net": "I2C_SCL"}},
        ])
        components = [
            self._make_component("U1", {"1": "VDD", "2": "I2C_SDA", "3": "I2C_SCL"},
                                 power_pins={"4": "VDD"}),
            self._make_component("RP1", {"1": "VDD", "2": "GND", "3": "I2C_SDA", "4": "I2C_SCL"}),
        ]

        repaired, actions = auto_repair_design(ir, components, enabled=True)

        i2c_actions = [a for a in actions if a.kind == "i2c_pullups"]
        assert len(i2c_actions) == 0, (
            f"Should not synthesize pull-ups when i2c_bus block exists, got {i2c_actions}"
        )

    def test_no_i2c_nets_does_nothing(self):
        """Design without I2C nets produces no repair actions."""
        ir = self._make_ir([
            {"ref": "U1", "kind": "power", "template_type": "ldo",
             "params": {"vin_net": "VIN", "vout_net": "VDD"}},
        ])
        components = [self._make_component("U1", {"1": "VIN", "2": "GND", "3": "VDD"})]

        repaired, actions = auto_repair_design(ir, components, enabled=True)

        assert len(actions) == 0, "No repair expected for non-I2C design"

    def test_repair_adds_synthetic_block(self):
        """The repair pass should add a synthetic block to the IR."""
        ir = self._make_ir([
            {"ref": "U1", "kind": "digital", "template_type": "mcu",
             "params": {"vdd_net": "VDD", "sda_net": "I2C_SDA", "scl_net": "I2C_SCL"}},
        ])
        components = [self._make_component("U1", {"1": "VDD", "2": "I2C_SDA", "3": "I2C_SCL"},
                                            power_pins={"4": "VDD"})]

        repaired, actions = auto_repair_design(ir, components, enabled=True)

        # The repaired IR should have a synthetic i2c_bus block
        i2c_blocks = [b for b in repaired.blocks if b.template_type == "i2c_bus"]
        assert len(i2c_blocks) > 0, "Expected synthetic i2c_bus block in repaired IR"
        # Verify it has the right net params
        synth = i2c_blocks[0]
        assert synth.params.get("sda_net") == "I2C_SDA"
        assert synth.params.get("scl_net") == "I2C_SCL"
