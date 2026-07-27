"""Sprint 41 Task 178 — every-template smoke test.

After draining every hardcoded ``*_IC_DATABASE`` dict into
``ic_data/*.json``, the only way a template's generate() path can fail
is if the JSON entries are missing a field the template reads. The
existing 9-archetype corpus (``tests/test_generation_corpus.py``) only
covers a handful of template types — `adc`, `rtc`, `rs485_transceiver`,
`can_transceiver`, `level_shifter`, `charge_pump`, `dac`, etc. have no
coverage there.

This smoke test iterates every template type in the registry and calls
``generate()`` on each one's default IC (pulled live from
``ic_data/*.json`` via the template's ``LegacyDBProxy``). It asserts:

1. Every template's merged IC database is non-empty. Empty means the
   JSON migration dropped entries under the wrong topology, or the
   template's ``template_type`` doesn't match the JSON topology name.
2. ``generate()`` returns a ``SubcircuitResult`` with at least one
   ComponentDef. Missing-key errors, KeyErrors, or silent empty
   results signal a schema drift between the template and the JSON.

The test uses minimal params — the same a user would get from a
bare-bones YAML spec. Templates that require specific extra fields
(e.g., crystal frequency) supply them via ``_MIN_PARAMS``.
"""

from __future__ import annotations

import pytest

from circuit_weaver.ic_data import merge_into_legacy_db
from circuit_weaver.subcircuits.base import get_default_registry

pytestmark = pytest.mark.skip_category("defect")

# Extra params some templates need to generate (beyond just `ic` +
# defaults from param_schema). Keep minimal — anything that isn't here
# falls back to the schema's defaults.
_MIN_PARAMS: dict[str, dict[str, object]] = {
    "crystal_oscillator": {"freq": 12_000_000.0, "cl_spec": 10e-12},
    "clock_synth": {"freq_out": 100e6},
    "current_sense": {"imax": 1.0},
    "mosfet_switch": {"iload": 0.1},
    "voltage_reference": {"vin": 5.0, "iload": 0.001},
    "led_driver": {"led_count": 4, "led_if": 0.02, "led_vf": 2.1, "iled": 0.02},
    "battery_charger": {"ichg": 0.5},
    "audio_amplifier": {"speaker_impedance": 8},
    "opamp": {"gain": 10},
    "buck": {"vin": 12.0, "vout": 5.0, "iout": 1.0},
    "boost": {"vin": 3.3, "vout": 12.0, "iout": 0.5},
    "buck_boost": {"vin": 3.3, "vout": 5.0, "iout": 1.0},
    "charge_pump": {"vin": 3.3, "vout": -3.3},
    "ldo": {"vin": 5.0, "vout": 3.3, "iout": 0.2},
    "protection": {"protect_net": "VBUS"},
    "sensor_frontend": {"gain": 10},
    "adc": {"channels": 2, "cutoff_hz": 1000},
    "dac": {},
    "gate_driver": {"vgs": 12},
    "relay_driver": {"vcoil": 12.0, "icoil": 0.07},
    "i2c_bus": {"vdd_voltage": 3.3},
    "spi_bus": {},
    "usb_controller": {},
    "usb_hub": {},
    "usb_c_connector": {"role": "device"},
    "motor_driver": {"vmotor": 5.0, "imotor": 1.0, "vm": 5.0},
    "battery_monitor": {},
    "display_driver": {},
    "ethernet_phy": {},
    "power_mux": {},
    "rs485_transceiver": {},
    "can_transceiver": {},
    "level_shifter": {},
    "rtc": {},
    "wireless_module": {},
    "connector": {},
}


def _all_template_types() -> list[str]:
    """Every template currently in the default registry, not counting
    subcircuit aliases that have no distinct template."""
    reg = get_default_registry()
    return [t.template_type for t in reg._templates.values() if t.template_type]


@pytest.mark.parametrize("template_type", sorted(set(_all_template_types())))
def test_template_ic_db_is_populated(template_type):
    """Every template's merged IC database must be non-empty. An empty
    database means the JSON migration dropped entries or the template's
    ``template_type`` drifted from the JSON topology key."""
    reg = get_default_registry()
    template = reg.get(template_type)
    assert template is not None, f"{template_type} missing from default registry"
    # Ask the template first (for templates that have an _ic_db()
    # classmethod), fall back to merging ic_data by topology name.
    if hasattr(template, "_ic_db"):
        ic_db = template._ic_db()
    else:
        ic_db = merge_into_legacy_db({}, template_type)
    assert len(ic_db) > 0, (
        f"{template_type}'s merged IC database is empty — JSON entries for this topology are missing "
        f"or the template's template_type='{template_type}' doesn't match any ic_data topology key"
    )


@pytest.mark.parametrize("template_type", sorted(set(_all_template_types())))
def test_template_generates_default_ic(template_type):
    """Every template must generate at least one ComponentDef using any
    IC from its merged database. Minimal params + IC MPN are supplied.
    KeyError / missing-field / empty-result failures here mean a JSON
    entry is missing something the template's generate() path reads.
    """
    reg = get_default_registry()
    template = reg.get(template_type)
    assert template is not None

    if hasattr(template, "_ic_db"):
        ic_db = template._ic_db()
    else:
        ic_db = merge_into_legacy_db({}, template_type)
    if not ic_db:
        pytest.skip(f"{template_type}: no ICs in merged database")
    ic_name = next(iter(ic_db))

    params: dict[str, object] = {"ic": ic_name, "ref": "U1"}
    params.update(_MIN_PARAMS.get(template_type, {}))

    errors = template.validate_params(params)
    assert errors == [], f"{template_type} ({ic_name}): validate_params rejected default params: {errors}"

    result = template.generate(params)
    assert result is not None, f"{template_type}: generate returned None"
    assert len(result.components) >= 1, (
        f"{template_type} ({ic_name}): generate returned no ComponentDefs — "
        f"JSON entry likely missing a field the template reads"
    )
    primary = result.components[0]
    assert primary.mpn == ic_name, f"{template_type}: primary component MPN {primary.mpn} != requested {ic_name}"
    assert len(primary.pins) > 0, f"{template_type} ({ic_name}): primary component has no pins"
