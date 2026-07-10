"""Compatibility module for the former :mod:`circuit_weaver.mvp` API."""

from __future__ import annotations

import warnings
from typing import Any

from . import dispatcher as _dispatcher

warnings.warn(
    "circuit_weaver.mvp is deprecated; import public workflow functions from circuit_weaver.dispatcher",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [name for name in dir(_dispatcher) if not name.startswith("_")]


def __getattr__(name: str) -> Any:
    return getattr(_dispatcher, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
