"""Research backend selection — sonar-pro vs standard.

Sprint 37 Task 161: users can pick between Perplexity sonar-pro (paid,
high-quality citations) and Claude's native WebSearch/WebFetch (free,
broader but noisier) when the ``/research`` skill or research-analyst
agent is invoked.

Selection order, highest priority first:

1. Explicit ``--research-backend`` CLI flag (``sonar-pro`` | ``standard`` | ``auto``).
2. ``CIRCUIT_WEAVER_RESEARCH_BACKEND`` env var (same values).
3. ``auto`` (the default) → ``sonar-pro`` when ``PERPLEXITY_API_KEY`` is
   set in the environment, otherwise ``standard``.

Agents should call :func:`resolve_backend` at the start of a research
step and honor the returned value. The CLI surfaces the selection via
``circuit-weaver doctor`` so users can verify their configuration.
"""

from __future__ import annotations

import logging
import os
from typing import Literal

_logger = logging.getLogger(__name__)

Backend = Literal["sonar-pro", "standard"]

_VALID_CHOICES: tuple[str, ...] = ("sonar-pro", "standard", "auto")
_ENV_VAR = "CIRCUIT_WEAVER_RESEARCH_BACKEND"
_PERPLEXITY_KEY_VAR = "PERPLEXITY_API_KEY"


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


def backend_info() -> dict[str, object]:
    """Diagnostic snapshot of backend configuration — used by ``doctor``."""
    explicit = os.environ.get(_ENV_VAR, "").strip().lower() or None
    has_key = _has_perplexity_creds()
    selected = resolve_backend(explicit)
    return {
        "env_var": _ENV_VAR,
        "env_value": explicit,
        "perplexity_key_set": has_key,
        "effective_backend": selected,
        "valid_choices": list(_VALID_CHOICES),
    }
