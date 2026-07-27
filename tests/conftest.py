from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Iterator
from importlib import import_module
from pathlib import Path
from uuid import uuid4

import pytest

# ``python -m pytest`` puts the repository root on sys.path, but this is a
# src-layout project.  Without this insertion a globally installed
# circuit_weaver wins the import and tests silently exercise the wrong code.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SOURCE_ROOT = _REPO_ROOT / "src"
_PACKAGE_ROOT = _SOURCE_ROOT / "circuit_weaver"
_TEST_PACKAGE_MODE = os.environ.get("CIRCUIT_WEAVER_TEST_PACKAGE", "source")
os.environ.setdefault("CIRCUIT_WEAVER_TEST_PACKAGE", _TEST_PACKAGE_MODE)


def _prepend_pythonpath(path: Path) -> None:
    existing = os.environ.get("PYTHONPATH")
    parts = [str(path)]
    if existing:
        parts.append(existing)
    os.environ["PYTHONPATH"] = os.pathsep.join(parts)


if _TEST_PACKAGE_MODE == "source":
    sys.path.insert(0, str(_SOURCE_ROOT))
    _prepend_pythonpath(_SOURCE_ROOT)
elif _TEST_PACKAGE_MODE != "wheel":
    raise pytest.UsageError(
        "CIRCUIT_WEAVER_TEST_PACKAGE must be 'source' or 'wheel', "
        f"not {_TEST_PACKAGE_MODE!r}"
    )

# Tests that spawn Python must use this exact interpreter; PYTHONPATH above
# makes a bare ``python -m circuit_weaver`` inherit the source target too.
os.environ["CIRCUIT_WEAVER_TEST_PYTHON"] = sys.executable

cleanup_logging = import_module("circuit_weaver.logging_bridge").cleanup_logging

_TMP_ROOT = _REPO_ROOT / ".test-tmp" / "fixture-tmp"
_TMP_ROOT.mkdir(parents=True, exist_ok=True)

_SKIP_CATEGORIES = frozenset({"platform", "optional-tool", "network", "defect"})


def _package_file() -> Path:
    import circuit_weaver

    package_file = getattr(circuit_weaver, "__file__", None)
    if package_file is None:
        raise pytest.UsageError("circuit_weaver has no __file__; cannot verify test target")
    return Path(package_file).resolve()


def pytest_sessionstart(session: pytest.Session) -> None:
    """Fail before tests run if imports do not match the requested target."""
    import circuit_weaver

    package_file = _package_file()
    in_source_checkout = package_file.is_relative_to(_PACKAGE_ROOT)
    if _TEST_PACKAGE_MODE == "source" and not in_source_checkout:
        raise pytest.UsageError(
            "source tests imported circuit_weaver outside this checkout: "
            f"{package_file} (expected beneath {_PACKAGE_ROOT})"
        )
    if _TEST_PACKAGE_MODE == "wheel" and in_source_checkout:
        raise pytest.UsageError(
            "wheel tests imported the checkout source instead of the installed wheel: "
            f"{package_file}"
        )
    if _TEST_PACKAGE_MODE == "wheel":
        # Make bare-Python subprocesses choose this installed wheel, even when
        # their working directory changes during an integration test.
        _prepend_pythonpath(package_file.parent.parent)
    session.config._circuit_weaver_test_target = {
        "mode": _TEST_PACKAGE_MODE,
        "file": str(package_file),
        "version": circuit_weaver.__version__,
        "python": sys.executable,
    }


def pytest_report_header(config: pytest.Config) -> list[str]:
    target = getattr(config, "_circuit_weaver_test_target", None)
    if not target:
        return []
    return [
        "circuit-weaver test target: "
        f"{target['mode']} v{target['version']} at {target['file']} via {target['python']}"
    ]


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "skip_category(category): classify a skip as platform, optional-tool, network, or defect",
    )
    config._unclassified_skips = set()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        categories = [mark.args[0] for mark in item.iter_markers(name="skip_category")]
        invalid = [category for category in categories if category not in _SKIP_CATEGORIES]
        if invalid:
            raise pytest.UsageError(f"{item.nodeid} has invalid skip category: {invalid!r}")
        if len(set(categories)) > 1:
            raise pytest.UsageError(f"{item.nodeid} has conflicting skip categories: {categories!r}")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[object]) -> Iterator[None]:
    outcome = yield
    report = outcome.get_result()
    if not report.skipped:
        return
    categories = [mark.args[0] for mark in item.iter_markers(name="skip_category")]
    if len(categories) != 1 or categories[0] not in _SKIP_CATEGORIES:
        item.config._unclassified_skips.add(report.nodeid)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    unclassified = session.config._unclassified_skips
    if unclassified:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
        terminal = session.config.pluginmanager.get_plugin("terminalreporter")
        if terminal:
            terminal.write_line(
                "ERROR: unclassified pytest skips (add @pytest.mark.skip_category): "
                + ", ".join(sorted(unclassified)),
                red=True,
            )


@pytest.fixture
def tmp_path() -> Iterator[Path]:
    """Repo-local tmp_path override for Windows hosts with broken basetemp ACLs."""
    path = _TMP_ROOT / f"cw-{uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        try:
            cleanup_logging()
        except Exception:
            pass
        shutil.rmtree(path, ignore_errors=True)
