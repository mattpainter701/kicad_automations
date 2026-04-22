"""Sprint 37 Task 158 — legacy template hot-load regression test.

The three pre-Sprint-34 template modules still carry their own hardcoded
``*_IC_DATABASE`` dicts. In v0.26.0 we added a lightweight bridge so
entries registered at runtime via :func:`register_ic` also reach the
legacy template's own IC database. This test locks that invariant in.
"""

from __future__ import annotations

import pytest

from circuit_weaver.ic_data import register_ic
from circuit_weaver.ic_data import reload as reload_ic_data


@pytest.fixture(autouse=True)
def _clean_ic_data():
    reload_ic_data()
    yield
    reload_ic_data()


def test_audio_amplifier_hotload_via_register_ic():
    """A user register_ic() call on an 'audio_amplifier' topology must
    be picked up by AudioAmplifierTemplate._ic_db() without reimport."""
    from circuit_weaver.subcircuits.audio_amplifier import (
        AUDIO_AMP_IC_DATABASE,
        AudioAmplifierTemplate,
    )

    original_keys = set(AUDIO_AMP_IC_DATABASE)
    # Make sure the hot-loaded MPN isn't already there.
    hot_mpn = "TEST-HOT-AMP-99"
    assert hot_mpn not in original_keys

    register_ic(
        hot_mpn,
        {
            "topology": "audio_amplifier",
            "description": "Test hot-loaded amp",
            "footprint": "SOIC-8",
            "vdd_min": 2.5,
            "vdd_max": 5.5,
            "output_power_w": 1.0,
            "speaker_impedance": 8,
            "gain_db": 18,
            "filterless": False,
            "interface": "analog",
            "r_in": 10000,
            "pins": [
                {"number": "1", "name": "VDD", "type": "power_in", "side": "T"},
                {"number": "2", "name": "GND", "type": "power_in", "side": "B"},
                {"number": "3", "name": "INP", "type": "input", "side": "L"},
            ],
            "pin_vdd": "1",
            "pin_gnd": "2",
            "pin_sd": "3",
            "pin_inp": "3",
            "pin_inn": "3",
            "pin_vop": "3",
            "pin_von": "3",
        },
        persist=False,
    )

    merged = AudioAmplifierTemplate._ic_db()
    assert hot_mpn in merged, "register_ic() entry must appear in merged DB"
    # Legacy entries remain.
    for k in original_keys:
        assert k in merged, f"legacy IC {k} must survive the merge"


def test_motor_driver_hotload_via_register_ic():
    from circuit_weaver.subcircuits.motor_driver import (
        MOTOR_DRIVER_IC_DATABASE,
        MotorDriverTemplate,
    )

    register_ic(
        "TEST-HOT-MOTOR-99",
        {
            "topology": "motor_driver",
            "description": "Test hot-loaded motor driver",
            "vin_range": [4.5, 18],
            "ipeak": 2.0,
            "pins": [
                {"number": "1", "name": "VM", "type": "power_in", "side": "T"},
                {"number": "2", "name": "GND", "type": "power_in", "side": "B"},
            ],
        },
        persist=False,
    )
    merged = MotorDriverTemplate._ic_db()
    assert "TEST-HOT-MOTOR-99" in merged
    assert set(MOTOR_DRIVER_IC_DATABASE).issubset(merged)


def test_protection_hotload_via_register_ic():
    from circuit_weaver.subcircuits.protection import TVS_DATABASE, ProtectionTemplate

    register_ic(
        "TEST-HOT-TVS-99",
        {
            "topology": "protection",
            "description": "Test hot-loaded TVS",
            "vrwm": 5.0,
            "vbr_min": 6.4,
            "vc_max": 9.2,
            "bidirectional": False,
            "pins": [
                {"number": "1", "name": "A", "type": "passive", "side": "L"},
                {"number": "2", "name": "K", "type": "passive", "side": "R"},
            ],
        },
        persist=False,
    )
    merged = ProtectionTemplate._ic_db()
    assert "TEST-HOT-TVS-99" in merged
    assert set(TVS_DATABASE).issubset(merged)


def test_generate_uses_hotloaded_ic():
    """End-to-end: after registering a new protection IC, the legacy
    ProtectionTemplate.generate() path should accept it in params."""
    from circuit_weaver.subcircuits.protection import ProtectionTemplate

    register_ic(
        "TEST-GEN-TVS",
        {
            "topology": "protection",
            "description": "Test generated TVS",
            "footprint": "Diode_SMD:D_SMB",
            "vrwm": 5.0,
            "vbr_min": 6.4,
            "vc_max": 9.2,
            "bidirectional": True,
            "pins": [
                {"number": "1", "name": "A", "type": "passive", "side": "L"},
                {"number": "2", "name": "K", "type": "passive", "side": "R"},
            ],
        },
        persist=False,
    )

    tpl = ProtectionTemplate()
    errors = tpl.validate_params({"ic": "TEST-GEN-TVS", "protect_net": "VBUS"})
    assert errors == [], f"validate_params should pass, got: {errors}"
    result = tpl.generate({"ic": "TEST-GEN-TVS", "protect_net": "VBUS"})
    assert len(result.components) >= 1
    assert result.components[0].mpn == "TEST-GEN-TVS"
