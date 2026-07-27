"""Shared switching-regulator equation and compatibility-wrapper contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from circuit_weaver.calc import (
    apply_e_series_selection,
    boost_inductor,
    buck_boost_inductor,
    buck_inductor,
    buck_output_cap,
)
from circuit_weaver.subcircuits import base

TARGET = "param:U1.switching.value"


def test_switching_equations_match_fixed_independent_numeric_values_and_units():
    buck = buck_inductor(
        target=TARGET,
        vin_v=12.0,
        vout_v=5.0,
        switching_frequency_hz=500_000,
        output_current_a=2.0,
        ripple_ratio=0.3,
    )
    cap = buck_output_cap(
        target=TARGET,
        ripple_current_a=0.6,
        switching_frequency_hz=500_000,
        output_ripple_v=0.020,
    )
    boost = boost_inductor(
        target=TARGET,
        vin_v=5.0,
        vout_v=12.0,
        switching_frequency_hz=500_000,
        output_current_a=1.0,
        ripple_ratio=0.3,
    )
    buck_boost = buck_boost_inductor(
        target=TARGET,
        vin_min_v=5.0,
        vout_v=12.0,
        switching_frequency_hz=500_000,
        output_current_a=1.0,
        ripple_ratio=0.3,
    )

    assert buck.raw_result.value == pytest.approx(9.722222222222223e-6)
    assert buck.raw_result.unit == "H"
    assert cap.raw_result.value == pytest.approx(7.5e-6)
    assert cap.raw_result.unit == "F"
    assert boost.raw_result.value == pytest.approx(8.101851851851853e-6)
    assert buck_boost.raw_result.value == pytest.approx(8.101851851851853e-6)
    assert "ideal CCM" in buck.equation_str
    assert "ESR excluded" in cap.equation_str
    assert (
        buck.id
        == buck_inductor(
            target=TARGET,
            vin_v=12.0,
            vout_v=5.0,
            switching_frequency_hz=500_000,
            output_current_a=2.0,
            ripple_ratio=0.3,
        ).id
    )


def test_switching_raw_results_use_declared_e_series_only_when_explicitly_applied():
    raw = buck_inductor(
        target=TARGET,
        vin_v=12.0,
        vout_v=5.0,
        switching_frequency_hz=500_000,
        output_current_a=2.0,
    )
    selected = apply_e_series_selection(raw, series="E24", direction="nearest")

    assert raw.chosen_value is None
    assert selected.chosen_value is not None
    assert selected.chosen_value.value == pytest.approx(10e-6)


@pytest.mark.parametrize(
    "call",
    [
        lambda: buck_inductor(
            target=TARGET,
            vin_v=5,
            vout_v=5,
            switching_frequency_hz=500_000,
            output_current_a=1,
        ),
        lambda: buck_inductor(
            target=TARGET,
            vin_v=12,
            vout_v=5,
            switching_frequency_hz=0,
            output_current_a=1,
        ),
        lambda: buck_output_cap(
            target=TARGET,
            ripple_current_a=0.3,
            switching_frequency_hz=500_000,
            output_ripple_v=0,
        ),
        lambda: boost_inductor(
            target=TARGET,
            vin_v=12,
            vout_v=5,
            switching_frequency_hz=500_000,
            output_current_a=1,
        ),
        lambda: buck_boost_inductor(
            target=TARGET,
            vin_min_v=float("nan"),
            vout_v=12,
            switching_frequency_hz=500_000,
            output_current_a=1,
        ),
    ],
)
def test_switching_equations_fail_closed_on_invalid_domains(call):
    with pytest.raises(ValueError):
        call()


@pytest.mark.parametrize(
    ("wrapper", "calc_name", "args", "expected_kwargs"),
    [
        (
            base.buck_inductor,
            "buck_inductor",
            (12.0, 5.0, 500_000, 2.0, 0.3),
            {"vin_v": 12.0, "vout_v": 5.0, "switching_frequency_hz": 500_000, "output_current_a": 2.0},
        ),
        (
            base.buck_output_cap,
            "buck_output_cap",
            (0.6, 500_000, 0.020),
            {"ripple_current_a": 0.6, "switching_frequency_hz": 500_000, "output_ripple_v": 0.020},
        ),
        (
            base.boost_inductor,
            "boost_inductor",
            (5.0, 12.0, 500_000, 1.0, 0.3),
            {"vin_v": 5.0, "vout_v": 12.0, "switching_frequency_hz": 500_000, "output_current_a": 1.0},
        ),
        (
            base.buck_boost_inductor,
            "buck_boost_inductor",
            (5.0, 12.0, 500_000, 1.0, 0.3),
            {"vin_min_v": 5.0, "vout_v": 12.0, "switching_frequency_hz": 500_000, "output_current_a": 1.0},
        ),
    ],
)
def test_legacy_switching_wrappers_delegate_to_shared_calc(monkeypatch, wrapper, calc_name, args, expected_kwargs):
    seen = {}

    def fake(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(raw_result=SimpleNamespace(value=4.7e-6))

    monkeypatch.setattr(base.calc, calc_name, fake)

    assert wrapper(*args) == 4.7e-6
    for key, value in expected_kwargs.items():
        assert seen[key] == value
    assert seen["target"].startswith("param:CALC.switching.")


def test_legacy_switching_wrappers_no_longer_return_magic_fallbacks():
    with pytest.raises(ValueError):
        base.buck_inductor(12, 5, 0, 2)
    with pytest.raises(ValueError):
        base.buck_output_cap(0.6, 0)
    with pytest.raises(ValueError):
        base.boost_inductor(5, 12, 0, 1)
