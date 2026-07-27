"""T246.1: validator calculations delegate to the shared calc module."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from circuit_weaver import calc, validator
from circuit_weaver.component_db import BypassCap, ComponentDef, StrapConfig


def _record(value: float):
    return SimpleNamespace(raw_result=SimpleNamespace(value=value))


def test_calculation_target_normalizes_ref_to_frozen_param_grammar():
    component = ComponentDef(mpn="TEST", ref_prefix="U", source_ref="1 bad-ref")

    assert validator._calculation_target(component, "feedback", "vout_FB") == "param:X_1_bad_ref.feedback.vout_FB"


def test_feedback_divider_validator_uses_shared_calculation(monkeypatch):
    calls = []

    def fake_feedback(**kwargs):
        calls.append(kwargs)
        return _record(3.3)

    monkeypatch.setattr(calc, "feedback_divider_vout", fake_feedback)
    component = ComponentDef(
        mpn="AP62300",
        ref_prefix="U",
        source_ref="U1",
        feedback_vref_voltage=0.8,
        feedback_vref_provenance="https://www.diodes.com/assets/Datasheets/AP62300.pdf",
        straps=[
            StrapConfig("1", "FB", "GND", "10k", "R_0402"),
            StrapConfig("1", "FB", "VDD_3P3", "31.6k", "R_0402"),
        ],
    )

    assert validator._validate_feedback_dividers([component]) == []
    assert calls == [
        {
            "target": "param:U1.feedback.vout_FB",
            "r_top_ohm": 31_600.0,
            "r_bottom_ohm": 10_000.0,
            "vref_v": 0.8,
        }
    ]


def test_filter_validators_use_shared_calculations(monkeypatch):
    rc_calls = []
    lc_calls = []

    def fake_rc(**kwargs):
        rc_calls.append(kwargs)
        return _record(50_000.0)

    def fake_lc(**kwargs):
        lc_calls.append(kwargs)
        return _record(50_000.0)

    monkeypatch.setattr(calc, "rc_cutoff", fake_rc)
    monkeypatch.setattr(calc, "lc_cutoff", fake_lc)
    component = ComponentDef(
        mpn="FILTER_TEST",
        ref_prefix="U",
        source_ref="U-1",
        category="power",
        straps=[StrapConfig("1", "FILTER", "GND", "1k", "R_0402")],
        bypass_caps=[
            BypassCap("1", "FILTER", "GND", "1nF", "C_0402"),
            BypassCap("2", "FILTER", "GND", "10uH", "L_0603"),
        ],
    )

    assert validator._validate_filter_cutoffs([component]) == []
    assert rc_calls == [
        {
            "target": "param:U_1.filter.rc_cutoff_FILTER",
            "resistance_ohm": 1_000.0,
            "capacitance_f": 1e-9,
        }
    ]
    assert len(lc_calls) == 1
    assert lc_calls[0]["target"] == "param:U_1.filter.lc_cutoff_FILTER"
    assert lc_calls[0]["inductance_h"] == pytest.approx(10e-6)
    assert lc_calls[0]["capacitance_f"] == pytest.approx(1e-9)


def test_crystal_validator_uses_shared_calculation(monkeypatch):
    calls = []

    def fake_crystal(**kwargs):
        calls.append(kwargs)
        return _record(10e-12)

    monkeypatch.setattr(calc, "crystal_effective_load", fake_crystal)
    crystal = ComponentDef(
        mpn="CRYSTAL_TEST",
        ref_prefix="Y",
        source_ref="Y1",
        description="12MHz crystal, CL = 10pF",
        pin_nets={"1": "XI", "2": "XO"},
    )
    capacitors = ComponentDef(
        mpn="CAPS",
        ref_prefix="U",
        bypass_caps=[
            BypassCap("1", "XI", "GND", "10pF", "C_0402"),
            BypassCap("2", "XO", "GND", "10pF", "C_0402"),
        ],
    )

    assert validator._validate_crystal_caps([crystal, capacitors]) == []
    assert calls == [
        {
            "target": "param:Y1.crystal.effective_load",
            "capacitance_1_f": 10e-12,
            "capacitance_2_f": 10e-12,
            "stray_capacitance_f": 2e-12,
        }
    ]
