from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest

from circuit_weaver.logging_bridge import cleanup_logging

_TMP_ROOT = Path(__file__).resolve().parent.parent / ".test-tmp" / "fixture-tmp"
_TMP_ROOT.mkdir(parents=True, exist_ok=True)


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
