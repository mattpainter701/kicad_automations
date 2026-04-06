"""Tests for Freerouting PCB autorouting integration."""

import subprocess
from unittest import mock

from circuit_weaver.autoroute import _find_freerouting_jar, autoroute_pcb


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


class TestAutoroutePcb:
    """Test PCB autorouting."""

    def test_pcb_file_not_found(self):
        """Test error when PCB file doesn't exist."""
        result = autoroute_pcb("/nonexistent/board.kicad_pcb")

        assert result["status"] == "error"
        assert "not found" in result["message"].lower()

    def test_freerouting_not_installed(self, tmp_path):
        """Test graceful failure when Freerouting is not installed."""
        pcb_file = tmp_path / "test.kicad_pcb"
        pcb_file.touch()

        with mock.patch("circuit_weaver.autoroute._find_freerouting_jar", return_value=None):
            result = autoroute_pcb(str(pcb_file))

        assert result["status"] == "error"
        assert "freerouting not found" in result["message"].lower()
        assert "brew install freerouting" in result["message"]

    def test_successful_routing(self, tmp_path):
        """Test successful PCB routing with mocked Freerouting."""
        pcb_file = tmp_path / "test.kicad_pcb"
        pcb_file.touch()
        jar_file = tmp_path / "freerouting.jar"
        jar_file.touch()

        mock_output = "Routed: 347 traces, 89 vias"

        with mock.patch("circuit_weaver.autoroute._find_freerouting_jar", return_value=jar_file):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(returncode=0, stdout=mock_output, stderr="")
                result = autoroute_pcb(str(pcb_file))

        assert result["status"] == "ok"
        assert "routed" in result["message"].lower()
        assert result["stats"]["traces"] == 347
        assert result["stats"]["vias"] == 89
        assert result["stats"]["routing_time_seconds"] > 0

    def test_routing_failure(self, tmp_path):
        """Test handling of Freerouting failure."""
        pcb_file = tmp_path / "test.kicad_pcb"
        pcb_file.touch()
        jar_file = tmp_path / "freerouting.jar"
        jar_file.touch()

        with mock.patch("circuit_weaver.autoroute._find_freerouting_jar", return_value=jar_file):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(returncode=1, stdout="", stderr="Routing failed: netlist error")
                result = autoroute_pcb(str(pcb_file))

        assert result["status"] == "error"
        assert "routing failed" in result["message"].lower()

    def test_routing_timeout(self, tmp_path):
        """Test timeout handling."""
        pcb_file = tmp_path / "test.kicad_pcb"
        pcb_file.touch()
        jar_file = tmp_path / "freerouting.jar"
        jar_file.touch()

        with mock.patch("circuit_weaver.autoroute._find_freerouting_jar", return_value=jar_file):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.side_effect = subprocess.TimeoutExpired("java", 300)
                result = autoroute_pcb(str(pcb_file))

        assert result["status"] == "error"
        assert "timed out" in result["message"].lower()

    def test_output_path_default(self, tmp_path):
        """Test default output path generation."""
        pcb_file = tmp_path / "test.kicad_pcb"
        pcb_file.touch()
        jar_file = tmp_path / "freerouting.jar"
        jar_file.touch()

        with mock.patch("circuit_weaver.autoroute._find_freerouting_jar", return_value=jar_file):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
                result = autoroute_pcb(str(pcb_file))

        assert result["status"] == "ok"
        assert "routed" in result["pcb_path"]

    def test_output_path_custom(self, tmp_path):
        """Test custom output path."""
        pcb_file = tmp_path / "test.kicad_pcb"
        pcb_file.touch()
        output_file = tmp_path / "custom_routed.kicad_pcb"
        jar_file = tmp_path / "freerouting.jar"
        jar_file.touch()

        with mock.patch("circuit_weaver.autoroute._find_freerouting_jar", return_value=jar_file):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
                result = autoroute_pcb(str(pcb_file), output_path=str(output_file))

        assert result["status"] == "ok"
        assert result["pcb_path"] == str(output_file)

    def test_trace_via_extraction(self, tmp_path):
        """Test parsing of trace and via counts from Freerouting output."""
        pcb_file = tmp_path / "test.kicad_pcb"
        pcb_file.touch()
        jar_file = tmp_path / "freerouting.jar"
        jar_file.touch()

        # Test various output formats
        test_cases = [
            ("Routed: 123 traces, 45 vias", 123, 45),
            ("123 trace segments and 45 vias routed", 123, 45),
            ("routed with 200 TRACES and 30 VIAS completed", 200, 30),
            ("No match in output", 0, 0),  # Fallback to 0 if no match
        ]

        for output_text, expected_traces, expected_vias in test_cases:
            with mock.patch("circuit_weaver.autoroute._find_freerouting_jar", return_value=jar_file):
                with mock.patch("subprocess.run") as mock_run:
                    mock_run.return_value = mock.Mock(returncode=0, stdout=output_text, stderr="")
                    result = autoroute_pcb(str(pcb_file))

            assert result["stats"]["traces"] == expected_traces
            assert result["stats"]["vias"] == expected_vias
