"""Smoke tests for thermal analysis module."""

import json
import tempfile
from pathlib import Path

import yaml

from circuit_weaver.component_db import ComponentDef
from circuit_weaver.design_loader import compile_design_ir
from circuit_weaver.thermal_analysis import analyze_thermal, generate_heatmap_svg

SAMPLE_SPEC = Path(__file__).resolve().parent.parent / "samples" / "iot_sensor_node" / "iot_sensor_node.yaml"


def _spec_components():
    """Load and compile the sample spec to get ComponentDef list."""
    spec = yaml.safe_load(SAMPLE_SPEC.read_text(encoding="utf-8"))
    compiled = compile_design_ir(spec)
    return compiled.components


def _hot_components():
    """Return two ComponentDefs with MPNs used in metadata specs."""
    return [
        ComponentDef(mpn="CHIP_HOT", source_ref="U1", footprint="QFN-32", ref_prefix="U"),
        ComponentDef(mpn="CHIP_WARM", source_ref="U2", footprint="QFN-32", ref_prefix="U"),
    ]


def _write_thermal_specs(tmp_dir: str) -> None:
    """Write metadata.json with thermal specs into tmp_dir."""
    meta = {
        "CHIP_HOT": {"pdiss_max_w": 2.0, "theta_ja": 50, "tj_max": 125},
        "CHIP_WARM": {"pdiss_max_w": 0.6, "theta_ja": 45, "tj_max": 125},
    }
    (Path(tmp_dir) / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")


class TestAnalyzeThermal:
    """Tests for analyze_thermal()."""

    def test_returns_expected_keys(self):
        """Compiled spec components return a dict with expected keys."""
        components = _spec_components()
        result = analyze_thermal(components)
        assert isinstance(result, dict)
        assert result["status"] == "ok"
        assert "ambient_temp_c" in result
        assert "total_power_w" in result
        assert "components" in result
        assert "hotspots" in result
        assert "proximity_warnings" in result
        assert "summary" in result
        assert "recommendations" in result

    def test_with_placements(self):
        """Placements dict produces proximity_warnings when hot components are close."""
        comps = _hot_components()
        with tempfile.TemporaryDirectory() as tmp:
            _write_thermal_specs(tmp)
            placements = {
                "U1": {"x": 10, "y": 10},
                "U2": {"x": 12, "y": 12},
            }
            result = analyze_thermal(comps, placements=placements, specs_dir=tmp)
        assert len(result["proximity_warnings"]) > 0
        pw = result["proximity_warnings"][0]
        assert pw["ref_a"] == "U1"
        assert pw["ref_b"] == "U2"
        assert pw["distance_mm"] <= 3.0  # ~2.8mm euclidean
        assert pw["combined_heat_w"] > 0.5

    def test_custom_ambient_temp(self):
        """Higher ambient temp produces more critical/warning results."""
        comps = _hot_components()
        with tempfile.TemporaryDirectory() as tmp:
            _write_thermal_specs(tmp)
            cool = analyze_thermal(comps, ambient_temp_c=25.0, specs_dir=tmp)
            hot_env = analyze_thermal(comps, ambient_temp_c=85.0, specs_dir=tmp)
        cool_warn = sum(1 for c in cool["components"] if c["status"] != "ok")
        hot_warn = sum(1 for c in hot_env["components"] if c["status"] != "ok")
        # Higher ambient must be at least as severe
        assert hot_warn >= cool_warn
        # At 85C ambient: U1 tj=85+100=185 > 125 → critical, U2 tj=85+27=112 < 125 → ok
        assert hot_env["components"][0]["status"] == "critical"
        assert hot_env["ambient_temp_c"] == 85.0

    def test_empty_components(self):
        """Empty component list returns valid but empty result."""
        result = analyze_thermal([])
        assert isinstance(result, dict)
        assert result["status"] == "ok"
        assert result["components"] == []
        assert result["hotspots"] == []
        assert result["total_power_w"] == 0
        assert "summary" in result


class TestGenerateHeatmapSvg:
    """Tests for generate_heatmap_svg()."""

    def test_returns_svg_string(self):
        """Heatmap returns a non-empty SVG string."""
        comps = _hot_components()
        placements = {"U1": {"x": 20, "y": 30}, "U2": {"x": 60, "y": 50}}
        with tempfile.TemporaryDirectory() as tmp:
            _write_thermal_specs(tmp)
            svg = generate_heatmap_svg(comps, placements, specs_dir=tmp)
        assert isinstance(svg, str)
        assert svg.startswith("<svg") or "<svg" in svg
        assert "</svg>" in svg
        assert "U1" in svg
        assert "U2" in svg

    def test_with_output_path(self):
        """Output path causes heatmap SVG to be written to disk."""
        comps = _hot_components()
        placements = {"U1": {"x": 20, "y": 30}, "U2": {"x": 60, "y": 50}}
        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
            out_path = f.name
        try:
            with tempfile.TemporaryDirectory() as tmp:
                _write_thermal_specs(tmp)
                svg = generate_heatmap_svg(comps, placements, specs_dir=tmp, output_path=out_path)
            written = Path(out_path).read_text(encoding="utf-8")
            assert written == svg
            assert "<svg" in written
        finally:
            Path(out_path).unlink(missing_ok=True)
