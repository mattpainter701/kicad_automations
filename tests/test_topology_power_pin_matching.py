from circuit_weaver.subcircuits.topology_builders import _is_power_input_pin_name, build_generic


def test_power_input_name_requires_prefix_exact_or_curated_equivalence():
    assert _is_power_input_pin_name("VIN")
    assert _is_power_input_pin_name("VIN_SENSE")
    assert _is_power_input_pin_name("PVIN")
    assert not _is_power_input_pin_name("MAINSVIN_SENSE")


def test_mainsvin_sense_does_not_bind_to_synthesized_vin():
    result = build_generic(
        {
            "mpn": "TEST",
            "pins": [
                {"number": "1", "name": "MAINSVIN_SENSE", "type": "power_in", "side": "L"},
                {"number": "2", "name": "GND", "type": "power_in", "side": "L"},
            ],
        },
        {},
    )
    component = result.components[0]
    assert "1" not in component.power_pins
    assert component.power_pins["2"] == "GND"
