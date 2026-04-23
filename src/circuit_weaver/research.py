"""Research workflow selection — backend plus depth profile.

Sprint 37 Task 161: users can pick between Perplexity sonar-pro (paid,
high-quality citations) and native web search/web fetch (free, broader
but noisier) when the Circuit Weaver IC research workflow runs.

Sprint 39 follow-up: users can also choose a research depth profile so
agent workflows can trade completeness for latency. ``fast`` keeps the
query budget intentionally small; ``normal`` preserves the fuller pass.

Selection order, highest priority first:

1. Explicit ``--research-backend`` CLI flag (``sonar-pro`` | ``standard`` | ``auto``).
2. ``CIRCUIT_WEAVER_RESEARCH_BACKEND`` env var (same values).
3. ``auto`` (the default) → ``sonar-pro`` when ``PERPLEXITY_API_KEY`` is
   set in the environment, otherwise ``standard``.

Research depth selection order:

1. Explicit ``--research-depth`` CLI flag (``fast`` | ``normal``).
2. ``CIRCUIT_WEAVER_RESEARCH_DEPTH`` env var (same values).
3. Default to ``normal``.

Agents should call :func:`resolve_backend` and :func:`resolve_depth` at
the start of a research step and honor the returned values. The CLI
surfaces the selections via ``circuit-weaver doctor`` so users can
verify their configuration.
"""

from __future__ import annotations

import logging
import os
from typing import Literal

_logger = logging.getLogger(__name__)

Backend = Literal["sonar-pro", "standard"]
Depth = Literal["fast", "normal"]

_VALID_CHOICES: tuple[str, ...] = ("sonar-pro", "standard", "auto")
_ENV_VAR = "CIRCUIT_WEAVER_RESEARCH_BACKEND"
_PERPLEXITY_KEY_VAR = "PERPLEXITY_API_KEY"
_DEPTH_CHOICES: tuple[str, ...] = ("fast", "normal")
_DEPTH_ENV_VAR = "CIRCUIT_WEAVER_RESEARCH_DEPTH"


def _has_perplexity_creds() -> bool:
    key = os.environ.get(_PERPLEXITY_KEY_VAR, "").strip()
    return bool(key)


def resolve_backend(cli_choice: str | None = None) -> Backend:
    """Return the effective research backend.

    Args:
        cli_choice: Value passed via ``--research-backend`` (if any).
            One of ``"sonar-pro"``, ``"standard"``, ``"auto"``, or None.

    Returns:
        ``"sonar-pro"`` or ``"standard"``.
    """
    candidate: str | None = (cli_choice or "").lower() or None
    if candidate not in (None, "", *_VALID_CHOICES):
        _logger.warning(
            "Invalid --research-backend value %r; expected one of %s. Falling back to auto.",
            cli_choice,
            ", ".join(_VALID_CHOICES),
        )
        candidate = "auto"

    if not candidate or candidate == "auto":
        env_val = os.environ.get(_ENV_VAR, "").strip().lower()
        if env_val in _VALID_CHOICES and env_val != "auto":
            candidate = env_val
        else:
            candidate = "sonar-pro" if _has_perplexity_creds() else "standard"

    if candidate == "sonar-pro" and not _has_perplexity_creds():
        _logger.info(
            "Research backend requested sonar-pro but PERPLEXITY_API_KEY is not set — "
            "falling back to 'standard'. Run 'circuit-weaver doctor' to configure."
        )
        candidate = "standard"

    return "sonar-pro" if candidate == "sonar-pro" else "standard"


def resolve_depth(cli_choice: str | None = None) -> Depth:
    """Return the effective research depth profile."""

    candidate: str | None = (cli_choice or "").lower() or None
    if candidate not in (None, "", *_DEPTH_CHOICES):
        _logger.warning(
            "Invalid --research-depth value %r; expected one of %s. Falling back to env/default.",
            cli_choice,
            ", ".join(_DEPTH_CHOICES),
        )
        candidate = None

    if not candidate:
        env_val = os.environ.get(_DEPTH_ENV_VAR, "").strip().lower()
        candidate = env_val if env_val in _DEPTH_CHOICES else "normal"

    return "fast" if candidate == "fast" else "normal"


def backend_info() -> dict[str, object]:
    """Diagnostic snapshot of research workflow configuration."""
    explicit = os.environ.get(_ENV_VAR, "").strip().lower() or None
    depth_explicit = os.environ.get(_DEPTH_ENV_VAR, "").strip().lower() or None
    has_key = _has_perplexity_creds()
    selected = resolve_backend(explicit)
    depth = resolve_depth(depth_explicit)
    return {
        "env_var": _ENV_VAR,
        "env_value": explicit,
        "perplexity_key_set": has_key,
        "effective_backend": selected,
        "valid_choices": list(_VALID_CHOICES),
        "depth_env_var": _DEPTH_ENV_VAR,
        "depth_env_value": depth_explicit,
        "effective_depth": depth,
        "depth_valid_choices": list(_DEPTH_CHOICES),
    }
