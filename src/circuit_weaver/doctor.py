"""Environment health check for circuit-weaver.

The `doctor` command audits the system for required and optional dependencies,
reports what's installed vs missing, and provides install instructions for each
platform (Linux, macOS, Windows).

Modeled after `flutter doctor`, `brew doctor`, `rustup check`.
"""

from __future__ import annotations

import importlib
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .parts_lookup import _get_credential


@dataclass
class CheckResult:
    """Result of a single dependency check."""

    name: str
    status: str  # "ok", "missing", "outdated", "warning"
    version: str = ""
    message: str = ""
    install_hint: str = ""
    required: bool = True  # False for optional deps

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "version": self.version,
            "message": self.message,
            "install_hint": self.install_hint,
            "required": self.required,
        }


@dataclass
class DoctorReport:
    """Full environment health report."""

    checks: list[CheckResult] = field(default_factory=list)
    python_version: str = ""
    platform: str = ""
    circuit_weaver_version: str = ""
    research_backend: dict[str, Any] = field(default_factory=dict)

    @property
    def ok_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "ok")

    @property
    def missing_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "missing")

    @property
    def warning_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "warning")

    @property
    def all_ok(self) -> bool:
        return all(c.status == "ok" for c in self.checks if c.required)

    def to_dict(self) -> dict[str, Any]:
        return {
            "python_version": self.python_version,
            "platform": self.platform,
            "circuit_weaver_version": self.circuit_weaver_version,
            "research_backend": self.research_backend,
            "checks": [c.to_dict() for c in self.checks],
            "ok_count": self.ok_count,
            "missing_count": self.missing_count,
            "warning_count": self.warning_count,
            "all_required_ok": self.all_ok,
        }

    def to_terminal(self) -> str:
        lines = []
        lines.append("")
        lines.append("=" * 60)
        lines.append("Circuit Weaver Doctor")
        lines.append("=" * 60)
        lines.append(f"Python:          {self.python_version}")
        lines.append(f"Platform:        {self.platform}")
        lines.append(f"Circuit Weaver:  {self.circuit_weaver_version}")
        lines.append("")

        for check in self.checks:
            if check.status == "ok":
                icon = "[OK]"
            elif check.status == "missing":
                icon = "[!!]" if check.required else "[--]"
            elif check.status == "warning":
                icon = "[??]"
            else:
                icon = "[??]"

            version_str = f" ({check.version})" if check.version else ""
            req_str = "" if check.required else " (optional)"
            lines.append(f"  {icon} {check.name}{version_str}{req_str}")

            if check.status != "ok" and check.message:
                lines.append(f"      {check.message}")
            if check.status != "ok" and check.install_hint:
                lines.append(f"      Install: {check.install_hint}")

        lines.append("")

        if self.all_ok:
            lines.append("All required dependencies are installed.")
        else:
            missing_required = [c for c in self.checks if c.status == "missing" and c.required]
            if missing_required:
                lines.append(f"{len(missing_required)} required dependency(ies) missing.")
                lines.append("Install them to unlock full functionality.")
        missing_optional = [c for c in self.checks if c.status == "missing" and not c.required]
        if missing_optional:
            lines.append(f"{len(missing_optional)} optional dependency(ies) not installed.")

        if self.research_backend and "error" not in self.research_backend:
            lines.append("")
            lines.append("Research backend:")
            effective = self.research_backend.get("effective_backend", "?")
            depth = self.research_backend.get("effective_depth", "normal")
            env_val = self.research_backend.get("env_value")
            depth_env_val = self.research_backend.get("depth_env_value")
            has_key = self.research_backend.get("perplexity_key_set")
            lines.append(f"  Selected:           {effective}")
            lines.append(f"  Research depth:     {depth}")
            lines.append(f"  PERPLEXITY_API_KEY: {'set' if has_key else 'not set'}")
            if env_val:
                lines.append(f"  CIRCUIT_WEAVER_RESEARCH_BACKEND: {env_val}")
            if depth_env_val:
                lines.append(f"  CIRCUIT_WEAVER_RESEARCH_DEPTH:   {depth_env_val}")
            if effective == "standard" and not has_key:
                lines.append("  (set PERPLEXITY_API_KEY to enable sonar-pro)")

        lines.append("=" * 60)
        return "\n".join(lines)


def _get_os_hint() -> str:
    """Detect OS for install hints."""
    system = platform.system().lower()
    if system == "linux":
        return "linux"
    elif system == "darwin":
        return "macos"
    elif system == "windows":
        return "windows"
    return "unknown"


def _check_python() -> CheckResult:
    ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 10):
        return CheckResult(name="Python", status="ok", version=ver)
    return CheckResult(
        name="Python",
        status="warning",
        version=ver,
        message=f"Python 3.10+ recommended, found {ver}",
        install_hint="https://www.python.org/downloads/",
    )


def _check_circuit_weaver() -> CheckResult:
    try:
        import circuit_weaver

        ver = getattr(circuit_weaver, "__version__", "unknown")
        return CheckResult(name="circuit-weaver", status="ok", version=ver)
    except ImportError:
        return CheckResult(
            name="circuit-weaver",
            status="missing",
            message="circuit-weaver package not installed",
            install_hint="pip install circuit-weaver",
        )


def _check_kicad_cli() -> CheckResult:
    os_hint = _get_os_hint()
    hints = {
        "linux": "sudo apt install kicad  (or download from https://www.kicad.org/download/)",
        "macos": "brew install kicad  (or download from https://www.kicad.org/download/)",
        "windows": "Download from https://www.kicad.org/download/windows/",
    }

    path = shutil.which("kicad-cli")
    if path:
        # Try to get version
        try:
            result = subprocess.run(
                [path, "version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            ver = result.stdout.strip().split("\n")[0] if result.returncode == 0 else ""
        except Exception:
            ver = ""
        return CheckResult(name="KiCad CLI", status="ok", version=ver)

    # Check Windows default paths
    for ver in ("10.0", "9.0", "8.0"):
        candidate = Path(f"C:/Program Files/KiCad/{ver}/bin/kicad-cli.exe")
        if candidate.exists():
            return CheckResult(name="KiCad CLI", status="ok", version=ver)

    return CheckResult(
        name="KiCad CLI",
        status="missing",
        message="Required for ERC, Gerber export, and DFM checks",
        install_hint=hints.get(os_hint, hints["linux"]),
    )


def _check_ngspice() -> CheckResult:
    os_hint = _get_os_hint()
    hints = {
        "linux": "sudo apt install ngspice",
        "macos": "brew install ngspice",
        "windows": "Download from https://ngspice.sourceforge.io/download.html",
    }

    path = shutil.which("ngspice")
    if path:
        try:
            result = subprocess.run(
                [path, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            ver = result.stdout.strip().split("\n")[0] if result.returncode == 0 else ""
        except Exception:
            ver = ""
        return CheckResult(name="ngspice", status="ok", version=ver, required=False)

    return CheckResult(
        name="ngspice",
        status="missing",
        required=False,
        message="Required for circuit simulation (SPICE analysis)",
        install_hint=hints.get(os_hint, hints["linux"]),
    )


def _check_freerouting() -> CheckResult:
    # Check PATH
    path = shutil.which("freerouting")
    if path:
        return CheckResult(name="Freerouting", status="ok", required=False)

    # Check default install location
    home_jar = Path.home() / ".freerouting" / "freerouting.jar"
    if home_jar.exists():
        return CheckResult(name="Freerouting", status="ok", version="JAR", required=False)

    return CheckResult(
        name="Freerouting",
        status="missing",
        required=False,
        message="Required for PCB autorouting",
        install_hint="Download from https://github.com/freerouting/freerouting/releases",
    )


def _check_python_package(name: str, pip_name: str, purpose: str, required: bool = False) -> CheckResult:
    try:
        mod = importlib.import_module(name)
        ver = getattr(mod, "__version__", getattr(mod, "VERSION", ""))
        return CheckResult(name=pip_name, status="ok", version=str(ver), required=required)
    except ImportError:
        return CheckResult(
            name=pip_name,
            status="missing",
            required=required,
            message=purpose,
            install_hint=f"pip install {pip_name}",
        )


def _check_api_credentials(name: str, env_vars: list[str], purpose: str) -> CheckResult:
    """Report whether optional API credentials are configured via env or secrets.env."""
    missing = [env_var for env_var in env_vars if not _get_credential(env_var)]
    if not missing:
        return CheckResult(
            name=name,
            status="ok",
            version="configured",
            required=False,
        )

    install_bits = " and ".join(env_vars)
    return CheckResult(
        name=name,
        status="missing",
        required=False,
        message=f"{purpose}. Missing: {', '.join(missing)}",
        install_hint=f"Set {install_bits} in the environment or secrets.env",
    )


def run_doctor() -> DoctorReport:
    """Run all environment checks and return a structured report."""
    report = DoctorReport(
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        platform=f"{platform.system()} {platform.release()} ({platform.machine()})",
    )

    # Get circuit-weaver version
    try:
        import circuit_weaver

        report.circuit_weaver_version = getattr(circuit_weaver, "__version__", "unknown")
    except ImportError:
        report.circuit_weaver_version = "not installed"

    # Core checks
    report.checks.append(_check_python())
    report.checks.append(_check_circuit_weaver())

    # External tools
    report.checks.append(_check_kicad_cli())
    report.checks.append(_check_ngspice())
    report.checks.append(_check_freerouting())

    # Python optional dependencies
    report.checks.append(
        _check_python_package(
            "yaml",
            "PyYAML",
            "Required for YAML spec parsing",
            required=True,
        )
    )
    report.checks.append(
        _check_python_package(
            "requests",
            "requests",
            "Required for online part lookups (DigiKey, Mouser, LCSC)",
        )
    )
    report.checks.append(
        _check_api_credentials(
            "DigiKey API credentials",
            ["DIGIKEY_CLIENT_ID", "DIGIKEY_CLIENT_SECRET"],
            "Enables DigiKey resolver fallback and part lookup",
        )
    )
    report.checks.append(
        _check_api_credentials(
            "Mouser API key",
            ["MOUSER_SEARCH_API_KEY"],
            "Enables Mouser resolver fallback and part lookup",
        )
    )
    report.checks.append(
        _check_python_package(
            "fastapi",
            "fastapi",
            "Required for HTTP API server",
            required=False,
        )
    )
    report.checks.append(
        _check_python_package(
            "skrf",
            "scikit-rf",
            "Required for RF chain simulation (S-parameter analysis)",
            required=False,
        )
    )

    # Research workflow selection (backend + depth)
    try:
        from .research import backend_info

        report.research_backend = backend_info()
    except Exception as exc:  # pragma: no cover — diagnostic path
        report.research_backend = {"error": str(exc)}

    return report
