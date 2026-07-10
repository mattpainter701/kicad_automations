"""Keep the public imports shipped by 0.30.x alive for one deprecation cycle."""

from __future__ import annotations

import importlib
import sys

import pytest


@pytest.mark.parametrize(
    ("module_name", "class_name", "template_type", "database_name"),
    [
        ("buck", "BuckConverterTemplate", "buck", "BUCK_IC_DATABASE"),
        ("boost", "BoostConverterTemplate", "boost", "BOOST_IC_DATABASE"),
        ("buck_boost", "BuckBoostConverterTemplate", "buck_boost", "BUCK_BOOST_IC_DATABASE"),
        ("ldo", "LDOTemplate", "ldo", "LDO_IC_DATABASE"),
        ("can_transceiver", "CANTransceiverTemplate", "can_transceiver", "CAN_TRANSCEIVER_IC_DATABASE"),
        ("eeprom", "EEPROMTemplate", "eeprom", "EEPROM_IC_DATABASE"),
        ("protection", "ProtectionTemplate", "protection", "TVS_DATABASE"),
    ],
)
def test_removed_template_imports_delegate_to_current_registry(
    module_name: str,
    class_name: str,
    template_type: str,
    database_name: str,
) -> None:
    module = importlib.import_module(f"circuit_weaver.subcircuits.{module_name}")
    template_class = getattr(module, class_name)

    with pytest.warns(DeprecationWarning, match=class_name):
        template = template_class()

    assert template.template_type == template_type
    assert template.get_param_schema()
    assert len(getattr(module, database_name)) > 0


def test_mvp_module_reexports_dispatcher_api() -> None:
    sys.modules.pop("circuit_weaver.mvp", None)
    with pytest.warns(DeprecationWarning, match="dispatcher"):
        legacy = importlib.import_module("circuit_weaver.mvp")

    from circuit_weaver import dispatcher

    assert legacy.generate_artifacts is dispatcher.generate_artifacts
    assert legacy.validate_design is dispatcher.validate_design
