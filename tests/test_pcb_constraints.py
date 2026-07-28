"""T250 constraint compilation and pre-mutation conflict gates."""

from __future__ import annotations

from pathlib import Path

import pytest

import circuit_weaver.pcb_handoff as pcb_handoff
from circuit_weaver.component_db import ComponentDef, PinDef
from circuit_weaver.design_ir import DesignIR, PowerDomain
from circuit_weaver.pcb_constraints import (
    PcbConstraintConflictError,
    compile_pcb_constraints,
    render_kicad_dru,
)

EVIDENCE = "EV-CALCULATION-0123456789ab"
FAB_EVIDENCE = "EV-DATASHEET-abcdef012345"


def _component() -> ComponentDef:
    nets = {
        "1": "USB_DP",
        "2": "USB_DM",
        "3": "I2C_SDA",
        "4": "I2C_SCL",
        "5": "XTAL_IN",
        "6": "SW",
        "7": "ANALOG_SENSE",
        "8": "CANH",
        "9": "CANL",
    }
    return ComponentDef(
        mpn="MIXED-SIGNAL",
        source_ref="U1",
        description="USB 2.0 and CAN controller",
        pins=[PinDef(number, net, "bidirectional", "L") for number, net in nets.items()],
        pin_nets=nets,
    )


def _evidence() -> dict[str, tuple[str, ...]]:
    return {
        f"net:{net}": (EVIDENCE,)
        for net in _component().pin_nets.values()
    }


def test_compile_covers_interface_power_and_fab_profile_origins() -> None:
    design = DesignIR(
        power_domains=[PowerDomain(net="VBUS", i_peak_ma=2500, evidence_id=EVIDENCE)],
    )
    compilation = compile_pcb_constraints(
        design,
        components=[_component()],
        fab_profile="jlcpcb",
        fab_profile_evidence_id=FAB_EVIDENCE,
        evidence_by_subject=_evidence(),
    )

    assert compilation.ready
    constraints = compilation.constraints
    assert {item.origin for item in constraints} == {"calculated", "fab_profile"}
    assert any(item.klass == "diff_pair" and item.target == "net:USB_DP" for item in constraints)
    assert any(item.klass == "impedance" and item.params["target"]["value"] == 90 for item in constraints)
    assert any(item.klass == "net_class" and item.params["name"] == "I2C" for item in constraints)
    assert any(item.klass == "length" and item.target == "net:XTAL_IN" for item in constraints)
    assert any(item.klass == "keepout" and item.target == "net:SW" for item in constraints)
    assert any(item.klass == "net_class" and item.params["name"] == "ANALOG_SENSE" for item in constraints)
    vbus = next(item for item in constraints if item.klass == "width" and item.target == "net:VBUS")
    assert vbus.params["minimum"] == {"unit": "mm", "value": 1.0}


def test_all_four_origins_and_deterministic_kicad_rules() -> None:
    design = DesignIR(
        pcb_constraints=[
            {
                "klass": "placement",
                "target": "comp:U1",
                "params": {"edge": "left", "distance": {"value": 5, "unit": "mm"}},
                "evidence_ids": [EVIDENCE],
            }
        ]
    )
    compilation = compile_pcb_constraints(
        design,
        fab_profile="pcbway",
        fab_profile_evidence_id=FAB_EVIDENCE,
        manufacturer_constraints=[
            {
                "klass": "length",
                "target": "net:RESET",
                "params": {"maximum": {"value": 20, "unit": "mm"}},
                "evidence_ids": [EVIDENCE],
            }
        ],
        user_constraints=[
            {
                "klass": "clearance",
                "target": "net:HV",
                "params": {"minimum": {"value": 1, "unit": "mm"}},
                "evidence_ids": [EVIDENCE],
            }
        ],
    )

    assert {item.origin for item in compilation.constraints} == {"fab_profile", "manufacturer", "user"}
    first = render_kicad_dru(compilation)
    assert first == render_kicad_dru(compilation)
    assert "PCBC-CLEARANCE-" in first and "constraint clearance" in first
    assert "PCBC-LENGTH-" in first and "constraint length" in first


def test_conflicts_are_symmetric_and_fail_before_board_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compilation = compile_pcb_constraints(
        DesignIR(),
        fab_profile="jlcpcb",
        fab_profile_evidence_id=FAB_EVIDENCE,
        user_constraints=[
            {
                "klass": "clearance",
                "target": "net_class:Default",
                "params": {"minimum": {"value": 0.05, "unit": "mm"}},
                "evidence_ids": [EVIDENCE],
            }
        ],
    )
    conflicts = [item for item in compilation.constraints if item.conflicts]
    assert len(conflicts) == 2
    assert conflicts[0].id in conflicts[1].conflicts and conflicts[1].id in conflicts[0].conflicts
    with pytest.raises(PcbConstraintConflictError):
        compilation.require_ready()

    board = tmp_path / "out" / "Conflict.kicad_pcb"
    board.parent.mkdir()
    board.write_text("last-known-good", encoding="utf-8")
    monkeypatch.setattr(
        pcb_handoff,
        "_render_authoritative_footprint",
        lambda *_args, **_kwargs: pytest.fail("render must not run with constraint conflicts"),
    )
    with pytest.raises(PcbConstraintConflictError):
        pcb_handoff._require_compiled_constraints(compilation)
    assert board.read_text(encoding="utf-8") == "last-known-good"
