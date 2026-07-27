"""T246 producer traces for representative crystal and analog RC templates."""

from circuit_weaver.evidence import EvidenceLedger, collect_component_evidence
from circuit_weaver.subcircuits.adc import ADCTemplate
from circuit_weaver.subcircuits.crystal_oscillator import CrystalOscillatorTemplate
from circuit_weaver.validator import _validate_crystal_caps, _validate_filter_cutoffs


def test_crystal_load_caps_retain_shared_calculation_and_pass_validator() -> None:
    component = CrystalOscillatorTemplate().generate({"freq": 12e6, "cl_spec": 12, "ref": "Y1"}).components[0]

    calculation = next(
        record for record in component.passive_synthesis_calculations if record.equation_id == "crystal_load_cap"
    )
    assert calculation.equation_id == "crystal_load_cap"
    assert calculation.emits_evidence
    assert all(cap.calculation_id == calculation.id for cap in component.bypass_caps if cap.role == "load_cap")
    assert all(item.calculation_id and item.evidence_ids for item in [*component.bypass_caps, *component.straps])
    assert _validate_crystal_caps([component]) == []

    ledger = EvidenceLedger()
    collect_component_evidence(ledger, [component])
    assert ledger.get(calculation.emits_evidence) is not None


def test_adc_input_filter_retain_shared_calculation_and_pass_validator() -> None:
    component = ADCTemplate().generate({"ref": "U1", "input_filter_bw": 1_000}).components[0]

    calculation = next(
        record for record in component.passive_synthesis_calculations if record.equation_id == "rc_cutoff"
    )
    filters = [cap for cap in component.bypass_caps if cap.role == "input_filter"]
    assert calculation.equation_id == "rc_cutoff"
    assert calculation.emits_evidence
    assert filters and all(cap.calculation_id == calculation.id for cap in filters)
    generated_support = [
        *component.bypass_caps,
        *(strap for strap in component.straps if strap.role != "address_select"),
    ]
    assert all(item.calculation_id and item.evidence_ids for item in generated_support)
    assert _validate_filter_cutoffs([component]) == []

    ledger = EvidenceLedger()
    collect_component_evidence(ledger, [component])
    assert ledger.get(calculation.emits_evidence) is not None
