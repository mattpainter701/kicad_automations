"""Legacy synthesis helpers must route scalar math through ``calc`` records."""

from types import SimpleNamespace

from circuit_weaver.subcircuits import base


def _record(value: float) -> SimpleNamespace:
    return SimpleNamespace(raw_result=SimpleNamespace(value=value))


def test_feedback_divider_wrappers_delegate_with_stable_targets(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def top(**kwargs):
        calls.append(("top", kwargs))
        return _record(12_300.0)

    def vout(**kwargs):
        calls.append(("vout", kwargs))
        return _record(3.3)

    monkeypatch.setattr(base.calc, "feedback_divider_top", top)
    monkeypatch.setattr(base.calc, "feedback_divider_vout", vout)

    assert base.feedback_divider_top(3.3, 0.6, 2_700.0) == 12_300.0
    assert base.feedback_divider_vout(12_300.0, 2_700.0, 0.6) == 3.3
    assert calls == [
        ("top", {"target": "param:CALC.feedback.r_top", "vout_v": 3.3, "vref_v": 0.6, "r_bottom_ohm": 2_700.0}),
        ("vout", {"target": "param:CALC.feedback.vout", "r_top_ohm": 12_300.0, "r_bottom_ohm": 2_700.0, "vref_v": 0.6}),
    ]


def test_rc_cutoff_wrapper_delegates(monkeypatch) -> None:
    received: dict = {}

    def cutoff(**kwargs):
        received.update(kwargs)
        return _record(1_592.0)

    monkeypatch.setattr(base.calc, "rc_cutoff", cutoff)
    assert base.rc_filter_cutoff(1_000.0, 100e-9) == 1_592.0
    assert received == {
        "target": "param:CALC.filter.cutoff",
        "resistance_ohm": 1_000.0,
        "capacitance_f": 100e-9,
    }


def test_rc_cutoff_preserves_legacy_zero_after_core_rejects_input(monkeypatch) -> None:
    calls = 0

    def cutoff(**_kwargs):
        nonlocal calls
        calls += 1
        raise ValueError("invalid RC values")

    monkeypatch.setattr(base.calc, "rc_cutoff", cutoff)
    assert base.rc_filter_cutoff(0.0, 100e-9) == 0.0
    assert calls == 1


def test_inverse_rc_wrappers_delegate_with_stable_targets(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def capacitance(**kwargs):
        calls.append(("capacitance", kwargs))
        return _record(100e-9)

    def resistance(**kwargs):
        calls.append(("resistance", kwargs))
        return _record(1_000.0)

    monkeypatch.setattr(base.calc, "rc_capacitance_for_cutoff", capacitance)
    monkeypatch.setattr(base.calc, "rc_resistance_for_cutoff", resistance)
    assert base.rc_capacitance_for_cutoff(1_000.0, 1_592.0) == 100e-9
    assert base.rc_resistance_for_cutoff(100e-9, 1_592.0) == 1_000.0
    assert calls == [
        ("capacitance", {
            "target": "param:CALC.filter.capacitance", "resistance_ohm": 1_000.0, "cutoff_hz": 1_592.0,
        }),
        ("resistance", {
            "target": "param:CALC.filter.resistance", "capacitance_f": 100e-9, "cutoff_hz": 1_592.0,
        }),
    ]


def test_crystal_wrapper_delegates_and_retains_legacy_floor(monkeypatch) -> None:
    received: dict = {}

    def external_cap(**kwargs):
        received.update(kwargs)
        return _record(-2e-12)

    monkeypatch.setattr(base.calc, "crystal_external_load_cap", external_cap)
    assert base.crystal_load_caps(6e-12, 8e-12) == 1e-12
    assert received == {
        "target": "param:CALC.crystal.load_cap",
        "load_capacitance_f": 6e-12,
        "stray_capacitance_f": 8e-12,
    }


def test_crystal_wrapper_preserves_floor_after_core_rejects_input(monkeypatch) -> None:
    def external_cap(**_kwargs):
        raise ValueError("load capacitance must exceed stray capacitance")

    monkeypatch.setattr(base.calc, "crystal_external_load_cap", external_cap)
    assert base.crystal_load_caps(2e-12, 4e-12) == 1e-12
