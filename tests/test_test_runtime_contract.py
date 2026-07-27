from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import circuit_weaver


def test_suite_targets_its_declared_package_and_exports_subprocess_contract() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    source_package = repo_root / "src" / "circuit_weaver"
    source_target = Path(circuit_weaver.__file__).resolve().is_relative_to(source_package)
    mode = os.environ["CIRCUIT_WEAVER_TEST_PACKAGE"]
    assert source_target is (mode == "source")
    assert os.environ["CIRCUIT_WEAVER_TEST_PYTHON"] == sys.executable
    if mode == "source":
        assert os.environ["PYTHONPATH"].split(os.pathsep)[0] == str(repo_root / "src")


def test_python_subprocess_imports_the_same_circuit_weaver_target() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", "import circuit_weaver; print(circuit_weaver.__file__)"],
        capture_output=True,
        check=True,
        text=True,
    )
    assert Path(completed.stdout.strip()).resolve() == Path(circuit_weaver.__file__).resolve()


def test_unclassified_call_phase_skip_fails_the_test_run() -> None:
    test_dir = Path(__file__).parent / f".skip-contract-{uuid4().hex}"
    test_dir.mkdir()
    test_file = test_dir / "test_unclassified_skip.py"
    test_file.write_text(
        "import pytest\n\ndef test_runtime_skip():\n    pytest.skip('unclassified contract fixture')\n",
        encoding="utf-8",
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_file), "-q"],
            capture_output=True,
            check=False,
            text=True,
        )
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)
    assert completed.returncode != 0
    assert "unclassified pytest skips" in completed.stdout
