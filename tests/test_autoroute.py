"""Tests for Freerouting PCB autorouting integration."""

import subprocess
from unittest import mock

from circuit_weaver.autoroute import (
    _find_freerouting_jar,
    _parse_routing_stats,
    autoroute_pcb,
    export_dsn,
    preflight_pcb,
)

ROUTABLE_PCB = """(kicad_pcb (version 20240108) (generator "pcbnew")
  (net 0 "")
  (net 1 "GND")
  (net 2 "VDD_3P3")
  (footprint "Resistor_SMD:R_0402_1005Metric" (layer "F.Cu") (at 10 10)
    (pad "1" smd rect (at -0.5 0) (size 0.5 0.5) (layers "F.Cu") (net 1 "GND"))
    (pad "2" smd rect (at 0.5 0) (size 0.5 0.5) (layers "F.Cu") (net 2 "VDD_3P3"))
  )
)
"""

PREVIEW_PCB = """(kicad_pcb (version 20240108) (generator "schematic_engine placement_preview")
  (net 0 "")
  (net 1 "GND")
  (footprint "Resistor_SMD:R_0402_1005Metric" (layer "F.Cu") (at 10 10))
)
"""


def _routable_board(tmp_path, name="test.kicad_pcb"):
    pcb_file = tmp_path / name
    pcb_file.write_text(ROUTABLE_PCB, encoding="utf-8")
    return pcb_file


class TestPreflight:
    """preflight_pcb fails closed on boards Freerouting cannot route."""

    def test_routable_board_passes(self, tmp_path):
        result = preflight_pcb(_routable_board(tmp_path))
        assert result["routable"] is True
        assert result["stats"]["pads"] == 2
        assert result["stats"]["nets"] == 2

    def test_placement_preview_fails_with_remediation(self, tmp_path):
        pcb_file = tmp_path / "preview.kicad_pcb"
        pcb_file.write_text(PREVIEW_PCB, encoding="utf-8")
        result = preflight_pcb(pcb_file)
        assert result["routable"] is False
        assert "placement preview" in result["reason"]
        assert "forward-annotate" in result["reason"].lower()
        assert result["stats"]["placement_preview"] is True

    def test_padless_board_fails(self, tmp_path):
        pcb_file = tmp_path / "padless.kicad_pcb"
        pcb_file.write_text(
            '(kicad_pcb (version 20240108) (generator "pcbnew")\n'
            '  (net 0 "")\n  (net 1 "GND")\n'
            '  (footprint "X" (layer "F.Cu") (at 10 10))\n)\n',
            encoding="utf-8",
        )
        result = preflight_pcb(pcb_file)
        assert result["routable"] is False
        assert "no pads" in result["reason"]

    def test_netless_board_fails(self, tmp_path):
        pcb_file = tmp_path / "netless.kicad_pcb"
        pcb_file.write_text(
            '(kicad_pcb (version 20240108) (generator "pcbnew")\n'
            '  (net 0 "")\n'
            '  (footprint "X" (layer "F.Cu") (at 10 10)\n'
            '    (pad "1" smd rect (at 0 0) (size 0.5 0.5) (layers "F.Cu"))\n'
            "  )\n)\n",
            encoding="utf-8",
        )
        result = preflight_pcb(pcb_file)
        assert result["routable"] is False
        assert "no named nets" in result["reason"]

    def test_empty_board_fails(self, tmp_path):
        pcb_file = tmp_path / "empty.kicad_pcb"
        pcb_file.write_text("(kicad_pcb)\n", encoding="utf-8")
        result = preflight_pcb(pcb_file)
        assert result["routable"] is False
        assert "no footprints" in result["reason"]


class TestFindFreeroutingJar:
    """Test Freerouting JAR discovery."""

    def test_find_jar_in_home_directory(self, tmp_path):
        """Test finding JAR in ~/.freerouting/ directory."""
        home = tmp_path
        jar_dir = home / ".freerouting"
        jar_dir.mkdir()
        jar_file = jar_dir / "freerouting.jar"
        jar_file.touch()

        with mock.patch("pathlib.Path.home", return_value=home):
            result = _find_freerouting_jar()

        assert result == jar_file

    def test_find_jar_in_path(self, tmp_path):
        """Test finding JAR in PATH via 'which'."""
        jar_path = str(tmp_path / "freerouting")

        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout=f"{jar_path}\n")
            result = _find_freerouting_jar()

        assert str(result) == jar_path
        mock_run.assert_called_once()

    def test_jar_not_found(self, tmp_path):
        """Test when Freerouting is not found."""
        home = tmp_path

        with mock.patch("pathlib.Path.home", return_value=home):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(returncode=1, stdout="")
                result = _find_freerouting_jar()

        assert result is None

    def test_jar_path_home_takes_precedence(self, tmp_path):
        """Test that home directory JAR takes precedence over PATH."""
        home = tmp_path
        jar_dir = home / ".freerouting"
        jar_dir.mkdir()
        home_jar = jar_dir / "freerouting.jar"
        home_jar.touch()

        path_jar = str(tmp_path / "alt_freerouting")

        with mock.patch("pathlib.Path.home", return_value=home):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(returncode=0, stdout=f"{path_jar}\n")
                result = _find_freerouting_jar()

        # Home directory should be checked first and found
        assert result == home_jar
        mock_run.assert_not_called()  # Shouldn't even check PATH


class TestParseRoutingStats:
    def test_stat_extraction_variants(self):
        cases = [
            ("Routed: 123 traces, 45 vias", 123, 45, 0),
            ("123 trace segments and 45 vias routed, 3 incomplete", 123, 45, 3),
            ("routed with 200 TRACES and 30 VIAS completed", 200, 30, 0),
            ("No match in output", 0, 0, 0),
        ]
        for text, traces, vias, incomplete in cases:
            stats = _parse_routing_stats(text)
            assert stats["traces"] == traces
            assert stats["vias"] == vias
            assert stats["incomplete"] == incomplete


class TestExportDsn:
    def test_missing_kicad_cli_reports_error(self, tmp_path):
        with mock.patch("circuit_weaver.autoroute._find_kicad_cli", return_value=None):
            result = export_dsn(tmp_path / "b.kicad_pcb", tmp_path / "b.dsn")
        assert result["status"] == "error"
        assert "kicad-cli not found" in result["message"]

    def test_successful_export(self, tmp_path):
        dsn = tmp_path / "b.dsn"

        def fake_run(cmd, **kwargs):
            dsn.write_text("(pcb)")
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch("circuit_weaver.autoroute._find_kicad_cli", return_value="kicad-cli"):
            with mock.patch("subprocess.run", side_effect=fake_run):
                result = export_dsn(tmp_path / "b.kicad_pcb", dsn)
        assert result["status"] == "ok"
        assert result["dsn_path"] == str(dsn)

    def test_failed_export(self, tmp_path):
        with mock.patch("circuit_weaver.autoroute._find_kicad_cli", return_value="kicad-cli"):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(returncode=1, stdout="", stderr="boom")
                result = export_dsn(tmp_path / "b.kicad_pcb", tmp_path / "b.dsn")
        assert result["status"] == "error"
        assert "boom" in result["message"]


class TestAutoroutePcb:
    """Test PCB autorouting."""

    def test_pcb_file_not_found(self):
        """Test error when PCB file doesn't exist."""
        result = autoroute_pcb("/nonexistent/board.kicad_pcb")

        assert result["status"] == "error"
        assert "not found" in result["message"].lower()

    def test_placement_preview_fails_closed(self, tmp_path):
        """A placement-preview PCB must fail before Freerouting is invoked."""
        pcb_file = tmp_path / "preview.kicad_pcb"
        pcb_file.write_text(PREVIEW_PCB, encoding="utf-8")

        with mock.patch("circuit_weaver.autoroute._find_freerouting_jar") as mock_jar:
            result = autoroute_pcb(str(pcb_file))

        assert result["status"] == "error"
        assert "preflight" in result["message"].lower() or "preview" in result["message"].lower()
        mock_jar.assert_not_called()

    def test_unknown_effort_rejected(self, tmp_path):
        result = autoroute_pcb(str(_routable_board(tmp_path)), effort="ludicrous")
        assert result["status"] == "error"
        assert "effort" in result["message"]

    def test_freerouting_not_installed(self, tmp_path):
        """Test graceful failure when Freerouting is not installed."""
        pcb_file = _routable_board(tmp_path)

        with mock.patch("circuit_weaver.autoroute._find_freerouting_jar", return_value=None):
            result = autoroute_pcb(str(pcb_file))

        assert result["status"] == "error"
        assert "freerouting not found" in result["message"].lower()
        assert "brew install freerouting" in result["message"]

    def test_successful_routing_legacy_path(self, tmp_path):
        """Direct .kicad_pcb routing when kicad-cli is unavailable."""
        pcb_file = _routable_board(tmp_path)
        jar_file = tmp_path / "freerouting.jar"
        jar_file.touch()

        mock_output = "Routed: 347 traces, 89 vias"

        with mock.patch("circuit_weaver.autoroute._find_freerouting_jar", return_value=jar_file):
            with mock.patch("circuit_weaver.autoroute._find_kicad_cli", return_value=None):
                with mock.patch("subprocess.run") as mock_run:
                    mock_run.return_value = mock.Mock(returncode=0, stdout=mock_output, stderr="")
                    result = autoroute_pcb(str(pcb_file))

        assert result["status"] == "ok"
        assert "routed" in result["message"].lower()
        assert result["stats"]["traces"] == 347
        assert result["stats"]["vias"] == 89
        assert result["stats"]["routing_time_seconds"] > 0
        # Legacy invocation routes the .kicad_pcb directly
        cmd = mock_run.call_args[0][0]
        assert "-dr" in cmd
        assert "-mp" in cmd

    def test_successful_routing_dsn_pipeline(self, tmp_path):
        """kicad-cli present: DSN export + Freerouting SES output."""
        pcb_file = _routable_board(tmp_path)
        jar_file = tmp_path / "freerouting.jar"
        jar_file.touch()

        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[0] == "kicad-cli":
                (tmp_path / "test.dsn").write_text("(pcb)")
                return mock.Mock(returncode=0, stdout="", stderr="")
            return mock.Mock(returncode=0, stdout="Routed: 12 traces, 3 vias", stderr="")

        with mock.patch("circuit_weaver.autoroute._find_freerouting_jar", return_value=jar_file):
            with mock.patch("circuit_weaver.autoroute._find_kicad_cli", return_value="kicad-cli"):
                with mock.patch("subprocess.run", side_effect=fake_run):
                    result = autoroute_pcb(str(pcb_file), effort="high")

        assert result["status"] == "ok"
        assert result["pcb_path"].endswith(".ses")
        assert "Specctra Session" in result["message"]
        # Freerouting invoked with DSN input, SES output, and the high-effort pass budget
        fr_cmd = calls[-1]
        assert "-de" in fr_cmd and "-do" in fr_cmd
        assert fr_cmd[fr_cmd.index("-mp") + 1] == "99"

    def test_routing_failure(self, tmp_path):
        """Test handling of Freerouting failure."""
        pcb_file = _routable_board(tmp_path)
        jar_file = tmp_path / "freerouting.jar"
        jar_file.touch()

        with mock.patch("circuit_weaver.autoroute._find_freerouting_jar", return_value=jar_file):
            with mock.patch("circuit_weaver.autoroute._find_kicad_cli", return_value=None):
                with mock.patch("subprocess.run") as mock_run:
                    mock_run.return_value = mock.Mock(
                        returncode=1, stdout="", stderr="Routing failed: netlist error"
                    )
                    result = autoroute_pcb(str(pcb_file))

        assert result["status"] == "error"
        assert "routing failed" in result["message"].lower()

    def test_routing_timeout(self, tmp_path):
        """Test timeout handling."""
        pcb_file = _routable_board(tmp_path)
        jar_file = tmp_path / "freerouting.jar"
        jar_file.touch()

        with mock.patch("circuit_weaver.autoroute._find_freerouting_jar", return_value=jar_file):
            with mock.patch("circuit_weaver.autoroute._find_kicad_cli", return_value=None):
                with mock.patch("subprocess.run") as mock_run:
                    mock_run.side_effect = subprocess.TimeoutExpired("java", 300)
                    result = autoroute_pcb(str(pcb_file))

        assert result["status"] == "error"
        assert "timed out" in result["message"].lower()

    def test_output_path_default(self, tmp_path):
        """Test default output path generation (legacy path)."""
        pcb_file = _routable_board(tmp_path)
        jar_file = tmp_path / "freerouting.jar"
        jar_file.touch()

        with mock.patch("circuit_weaver.autoroute._find_freerouting_jar", return_value=jar_file):
            with mock.patch("circuit_weaver.autoroute._find_kicad_cli", return_value=None):
                with mock.patch("subprocess.run") as mock_run:
                    mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
                    result = autoroute_pcb(str(pcb_file))

        assert result["status"] == "ok"
        assert "routed" in result["pcb_path"]

    def test_output_path_custom(self, tmp_path):
        """Test custom output path (legacy path)."""
        pcb_file = _routable_board(tmp_path)
        output_file = tmp_path / "custom_routed.kicad_pcb"
        jar_file = tmp_path / "freerouting.jar"
        jar_file.touch()

        with mock.patch("circuit_weaver.autoroute._find_freerouting_jar", return_value=jar_file):
            with mock.patch("circuit_weaver.autoroute._find_kicad_cli", return_value=None):
                with mock.patch("subprocess.run") as mock_run:
                    mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
                    result = autoroute_pcb(str(pcb_file), output_path=str(output_file))

        assert result["status"] == "ok"
        assert result["pcb_path"] == str(output_file)

    def test_incomplete_routes_surface_in_message(self, tmp_path):
        pcb_file = _routable_board(tmp_path)
        jar_file = tmp_path / "freerouting.jar"
        jar_file.touch()

        mock_output = "Routed: 40 traces, 8 vias, 2 incomplete"
        with mock.patch("circuit_weaver.autoroute._find_freerouting_jar", return_value=jar_file):
            with mock.patch("circuit_weaver.autoroute._find_kicad_cli", return_value=None):
                with mock.patch("subprocess.run") as mock_run:
                    mock_run.return_value = mock.Mock(returncode=0, stdout=mock_output, stderr="")
                    result = autoroute_pcb(str(pcb_file))

        assert result["status"] == "ok"
        assert result["stats"]["incomplete"] == 2
        assert "incomplete" in result["message"]


def test_generated_placement_preview_fails_autoroute_preflight(tmp_path):
    """End-to-end: the engine's own placement preview is rejected by preflight."""
    from circuit_weaver.component_db import ComponentDef, PinDef
    from circuit_weaver.pcb_export import generate_pcb_placement

    comp = ComponentDef(
        mpn="TEST_U1",
        ref_prefix="U",
        source_ref="U1",
        value="TEST",
        footprint="Package_DFN_QFN:QFN-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm",
        category="digital",
        pins=[
            PinDef("1", "SIG", "bidirectional", "L"),
            PinDef("2", "VDD", "power_in", "T"),
            PinDef("3", "GND", "power_in", "B"),
        ],
        power_pins={"2": "VDD_3P3", "3": "GND"},
    )
    pcb_file, _ = generate_pcb_placement([comp], tmp_path, "Preview")
    result = preflight_pcb(pcb_file)
    assert result["routable"] is False
    assert result["stats"]["placement_preview"] is True
