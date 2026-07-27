"""T246 producer traces for USB-C and wireless reset/boot support networks."""

from circuit_weaver import calc
from circuit_weaver.subcircuits.usb_c_connector import USBCConnectorTemplate
from circuit_weaver.subcircuits.wireless_module import WirelessModuleTemplate


def _assert_traced(comp) -> None:
    physical = [*comp.bypass_caps, *comp.straps]
    assert physical
    assert all(item.selection_policy == "bounded_fallback" for item in physical)
    assert all(item.confidence == "heuristic" for item in physical)
    assert all(item.calculation_id and item.evidence_ids for item in physical)
    assert {item.calculation_id for item in physical} == {record.id for record in comp.passive_synthesis_calculations}


def test_usb_c_support_values_retain_traceable_bounded_fallbacks():
    comp = USBCConnectorTemplate().generate({"ref": "J4", "role": "source", "source_current": "3A"}).components[0]

    _assert_traced(comp)
    assert {strap.value for strap in comp.straps} == {"10k"}
    assert {cap.value for cap in comp.bypass_caps} == {"10uF", "100nF"}


def test_wireless_enable_boot_and_reset_support_values_retain_traces():
    esp = WirelessModuleTemplate().generate({"ref": "U7", "ic": "ESP32-S3-WROOM-1"}).components[0]
    nrf = WirelessModuleTemplate().generate({"ref": "U8", "ic": "nRF52840-MODULE"}).components[0]

    _assert_traced(esp)
    _assert_traced(nrf)
    assert {strap.role for strap in esp.straps} == {"enable_pullup", "boot_pullup"}
    assert {strap.role for strap in nrf.straps} == {"reset_pullup"}


def test_out_of_range_bounded_support_value_is_withheld_before_selection():
    decision = calc.bounded_fallback_scalar(
        target="param:J4.usb_c_vbus_bulk.c_vbus",
        value=100e-6,
        minimum=1e-6,
        maximum=47e-6,
        unit="F",
        series="E24",
        direction="up",
    )

    assert decision.finding is not None
    assert not calc.is_selection_eligible(decision.calculation)
