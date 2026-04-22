"""Tests for the doctor (environment health check) command."""

import json
import subprocess
import sys

from circuit_weaver.doctor import (
    CheckResult,
    DoctorReport,
    _check_circuit_weaver,
    _check_python,
    run_doctor,
)


class TestCheckResult:
    def test_to_dict(self):
        r = CheckResult(name="test", status="ok", version="1.0")
        d = r.to_dict()
        assert d["name"] == "test"
        assert d["status"] == "ok"
        assert d["version"] == "1.0"


class TestDoctorReport:
    def test_counts(self):
        report = DoctorReport(checks=[
            CheckResult(name="a", status="ok"),
            CheckResult(name="b", status="missing"),
            CheckResult(name="c", status="ok", required=False),
        ])
        assert report.ok_count == 2
        assert report.missing_count == 1
        assert report.all_ok is False  # 'b' is required and missing

    def test_all_ok_when_optional_missing(self):
        report = DoctorReport(checks=[
            CheckResult(name="a", status="ok"),
            CheckResult(name="b", status="missing", required=False),
        ])
        assert report.all_ok is True  # only optional is missing

    def test_to_dict(self):
        report = DoctorReport(
            python_version="3.11.0",
            platform="Linux",
            circuit_weaver_version="0.23.0",
            checks=[CheckResult(name="test", status="ok")],
        )
        d = report.to_dict()
        assert d["python_version"] == "3.11.0"
        assert d["all_required_ok"] is True
        assert len(d["checks"]) == 1

    def test_to_terminal(self):
        report = DoctorReport(
            python_version="3.11.0",
            platform="Linux",
            circuit_weaver_version="0.23.0",
            checks=[
                CheckResult(name="Python", status="ok", version="3.11.0"),
                CheckResult(name="ngspice", status="missing", required=False,
                           message="Required for simulation",
                           install_hint="sudo apt install ngspice"),
            ],
        )
        text = report.to_terminal()
        assert "Circuit Weaver Doctor" in text
        assert "[OK]" in text
        assert "ngspice" in text
        assert "sudo apt install" in text


class TestRunDoctor:
    def test_returns_report(self):
        report = run_doctor()
        assert isinstance(report, DoctorReport)
        assert len(report.checks) >= 5  # python, cw, kicad, ngspice, freerouting + packages
        assert report.python_version != ""
        assert report.platform != ""

    def test_python_check_ok(self):
        result = _check_python()
        assert result.status == "ok"
        assert result.name == "Python"

    def test_circuit_weaver_check_ok(self):
        result = _check_circuit_weaver()
        assert result.status == "ok"


class TestDoctorCLI:
    def test_doctor_text_output(self):
        result = subprocess.run(
            [sys.executable, "-m", "circuit_weaver", "doctor"],
            capture_output=True, text=True,
        )
        # Exit code depends on what's installed, but it shouldn't crash
        assert result.returncode in (0, 1)
        assert "Circuit Weaver Doctor" in result.stdout
        assert "Python" in result.stdout

    def test_doctor_json_output(self):
        result = subprocess.run(
            [sys.executable, "-m", "circuit_weaver", "doctor", "--json"],
            capture_output=True, text=True,
        )
        assert result.returncode in (0, 1)
        data = json.loads(result.stdout)
        assert "python_version" in data
        assert "checks" in data
        assert isinstance(data["checks"], list)
        assert data["ok_count"] >= 1  # at least Python should be OK
