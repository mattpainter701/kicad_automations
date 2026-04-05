"""Presentation parity regression tests.

Validates that sample specs generate components with correct presentation
metadata, and that the review profile activates topology-local rendering.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from circuit_weaver.component_db import BUILTIN_REGISTRY
from circuit_weaver.design_ir import normalize_design_spec
from circuit_weaver.mvp import compile_design_ir, validate_design
from circuit_weaver.subcircuits.ldo import LDOTemplate
from circuit_weaver.subcircuits.usb import USBControllerTemplate, USBHubTemplate

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"


# ================================================================
# Milestone 1: Template parity — support passives opt into topology_local
# ================================================================


class TestLDOPresentation:
    def test_ldo_bypass_caps_use_topology_local(self):
        t = LDOTemplate()
        r = t.generate({"vin": 5.0, "vout": 3.3, "ic": "TLV75518"})
        caps = r.components[0].bypass_caps
        assert len(caps) == 2
        for cap in caps:
            assert cap.presentation == "topology_local", f"{cap.pin} should be topology_local"
            assert cap.role == "decoupling"

    def test_all_ldo_ics_produce_topology_local_caps(self):
        from circuit_weaver.subcircuits.ldo import LDO_IC_DATABASE

        t = LDOTemplate()
        for ic_name, ic_db in LDO_IC_DATABASE.items():
            vout = ic_db.get("vout_fixed", 3.3)
            r = t.generate({"vin": vout + 2.0, "ic": ic_name})
            for cap in r.components[0].bypass_caps:
                assert cap.presentation == "topology_local", f"{ic_name} cap {cap.pin} should be topology_local"


class TestUSBPresentation:
    def test_usb_controller_decoupling_uses_topology_local(self):
        t = USBControllerTemplate()
        r = t.generate({"ic": "CH340G"})
        caps = r.components[0].bypass_caps
        assert len(caps) > 0
        for cap in caps:
            assert cap.presentation == "topology_local", f"{cap.pin} should be topology_local"

    def test_usb_controller_boot_straps_use_topology_local(self):
        t = USBControllerTemplate()
        r = t.generate({"ic": "CYUSB3014"})
        straps = r.components[0].straps
        for strap in straps:
            assert strap.presentation == "topology_local", f"Boot strap pin {strap.pin} should be topology_local"
            assert strap.role == "bootstrap_strap"

    def test_usb_hub_decoupling_uses_topology_local(self):
        t = USBHubTemplate()
        r = t.generate({})
        caps = r.components[0].bypass_caps
        assert len(caps) > 0
        for cap in caps:
            assert cap.presentation == "topology_local", f"{cap.pin} should be topology_local"

    def test_usb_hub_rbias_and_reset_use_topology_local(self):
        t = USBHubTemplate()
        r = t.generate({})
        straps = r.components[0].straps
        roles = {s.role for s in straps}
        assert "bias" in roles
        assert "pull_up" in roles
        for strap in straps:
            assert strap.presentation == "topology_local", (
                f"Strap {strap.role} pin {strap.pin} should be topology_local"
            )


class TestUSBCPWRPresentation:
    def test_cc_pulldowns_use_topology_local(self):
        usbc = BUILTIN_REGISTRY.get("USB-C-PWR")
        assert usbc is not None, "USB-C-PWR must be in builtin registry"
        assert len(usbc.straps) == 2
        for strap in usbc.straps:
            assert strap.presentation == "topology_local"
            assert strap.role == "termination"


# ================================================================
# Milestone 2: Review profile — activates topology_local globally
# ================================================================


class TestReviewProfile:
    def test_review_profile_accepted_in_metadata(self):
        spec = {"project": "test", "presentation_profile": "review", "blocks": []}
        ir = normalize_design_spec(spec)
        assert ir.metadata["presentation_profile"] == "review"

    def test_default_profile_omits_key(self):
        spec = {"project": "test", "blocks": []}
        ir = normalize_design_spec(spec)
        assert "presentation_profile" not in ir.metadata

    def test_invalid_profile_raises(self):
        spec = {"project": "test", "presentation_profile": "fancy", "blocks": []}
        with pytest.raises(ValueError, match="Unknown presentation_profile"):
            normalize_design_spec(spec)


# ================================================================
# Milestone 4: Sample regression — samples validate cleanly
# ================================================================


def _load_sample_spec(name: str) -> dict:
    """Load a sample YAML spec by directory name."""
    from circuit_weaver.mvp import _simple_yaml_parse

    yaml_path = SAMPLES_DIR / name / f"{name}.yaml"
    if not yaml_path.exists():
        pytest.skip(f"Sample {name} not found at {yaml_path}")
    return _simple_yaml_parse(yaml_path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "sample_name",
    ["usb_regulated_supply", "led_power_indicator", "iot_sensor_node"],
)
class TestSampleValidation:
    def test_sample_validates_cleanly(self, sample_name):
        spec = _load_sample_spec(sample_name)
        report = validate_design(spec)
        assert report.valid, f"Sample {sample_name} failed validation: " + json.dumps(report.to_dict(), indent=2)[:500]

    def test_sample_compiles_without_error(self, sample_name):
        spec = _load_sample_spec(sample_name)
        compiled = compile_design_ir(spec)
        assert len(compiled.components) > 0, f"{sample_name} should produce components"

    def test_sample_support_passives_have_presentation(self, sample_name):
        spec = _load_sample_spec(sample_name)
        compiled = compile_design_ir(spec)
        for comp in compiled.components:
            for cap in comp.bypass_caps:
                assert cap.presentation != "inherit", (
                    f"{sample_name}: {comp.mpn} cap {cap.pin} still uses 'inherit' "
                    f"— should declare explicit presentation"
                )

    def test_sample_no_diagonal_clutter_metric(self, sample_name):
        """Check that no single IC has more than 8 unresolved 'inherit' passives.

        This is a proxy metric for 'clutter' — a high count of passives
        with no presentation policy means the placer will scatter them
        with generic point-to-point wiring.
        """
        spec = _load_sample_spec(sample_name)
        compiled = compile_design_ir(spec)
        for comp in compiled.components:
            inherit_count = sum(1 for cap in comp.bypass_caps if cap.presentation == "inherit") + sum(
                1 for strap in comp.straps if strap.presentation == "inherit"
            )
            assert inherit_count <= 8, (
                f"{sample_name}: {comp.mpn} has {inherit_count} passives with "
                f"'inherit' presentation — too many for clean rendering"
            )


@pytest.mark.parametrize(
    "sample_name",
    ["usb_regulated_supply", "led_power_indicator", "iot_sensor_node"],
)
def test_sample_generates_artifacts(sample_name, tmp_path):
    """End-to-end: sample spec generates KiCad schematics without errors."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "circuit_weaver",
            "generate",
            str(SAMPLES_DIR / sample_name / f"{sample_name}.yaml"),
            "--output",
            str(tmp_path / sample_name),
            "--no-svg",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Generate failed for {sample_name}:\nstdout: {result.stdout[:500]}\nstderr: {result.stderr[:500]}"
    )
    payload = json.loads(result.stdout)
    assert payload["valid"] is True
