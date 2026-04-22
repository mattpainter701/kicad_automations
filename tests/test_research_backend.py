"""Regression tests for Sprint 37 Task 161 — research backend selector.

User request: let callers pick between sonar-pro (Perplexity, paid) and
standard (Claude WebSearch, free) research backends via either
``--research-backend`` CLI flag or ``CIRCUIT_WEAVER_RESEARCH_BACKEND``
env var, with sensible auto-detection fallback.
"""

from __future__ import annotations

import pytest

from circuit_weaver.research import backend_info, resolve_backend


@pytest.fixture
def clean_env(monkeypatch):
    """Strip both research-related env vars so tests are hermetic."""
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    monkeypatch.delenv("CIRCUIT_WEAVER_RESEARCH_BACKEND", raising=False)
    yield monkeypatch


class TestResolveBackend:
    def test_auto_without_key_picks_standard(self, clean_env):
        assert resolve_backend("auto") == "standard"
        assert resolve_backend(None) == "standard"
        assert resolve_backend("") == "standard"

    def test_auto_with_key_picks_sonar_pro(self, clean_env):
        clean_env.setenv("PERPLEXITY_API_KEY", "pplx-test-key")
        assert resolve_backend("auto") == "sonar-pro"
        assert resolve_backend(None) == "sonar-pro"

    def test_explicit_standard_always_wins(self, clean_env):
        clean_env.setenv("PERPLEXITY_API_KEY", "pplx-test-key")
        assert resolve_backend("standard") == "standard"

    def test_explicit_sonar_pro_without_key_falls_back(self, clean_env):
        # User asked for sonar-pro but has no Perplexity key — fall back
        # to standard rather than making API calls that will fail.
        assert resolve_backend("sonar-pro") == "standard"

    def test_explicit_sonar_pro_with_key_honored(self, clean_env):
        clean_env.setenv("PERPLEXITY_API_KEY", "pplx-test-key")
        assert resolve_backend("sonar-pro") == "sonar-pro"

    def test_env_var_fallback(self, clean_env):
        clean_env.setenv("CIRCUIT_WEAVER_RESEARCH_BACKEND", "standard")
        clean_env.setenv("PERPLEXITY_API_KEY", "pplx-test-key")
        # Env var "standard" overrides auto-detect.
        assert resolve_backend(None) == "standard"
        assert resolve_backend("auto") == "standard"

    def test_env_var_sonar_pro_requires_key(self, clean_env):
        clean_env.setenv("CIRCUIT_WEAVER_RESEARCH_BACKEND", "sonar-pro")
        # No API key → fallback wins even over env-var request.
        assert resolve_backend(None) == "standard"

    def test_explicit_cli_beats_env_var(self, clean_env):
        clean_env.setenv("CIRCUIT_WEAVER_RESEARCH_BACKEND", "standard")
        clean_env.setenv("PERPLEXITY_API_KEY", "pplx-test-key")
        assert resolve_backend("sonar-pro") == "sonar-pro"

    def test_case_insensitive(self, clean_env):
        clean_env.setenv("PERPLEXITY_API_KEY", "pplx-test-key")
        assert resolve_backend("SONAR-PRO") == "sonar-pro"
        assert resolve_backend("Standard") == "standard"

    def test_invalid_value_falls_back_to_auto(self, clean_env):
        # Typo → warn + auto-detect; no crash.
        assert resolve_backend("sonarpro") == "standard"

    def test_blank_api_key_treated_as_missing(self, clean_env):
        clean_env.setenv("PERPLEXITY_API_KEY", "   ")
        assert resolve_backend("auto") == "standard"


class TestBackendInfo:
    def test_returns_diagnostic_snapshot(self, clean_env):
        info = backend_info()
        assert info["env_var"] == "CIRCUIT_WEAVER_RESEARCH_BACKEND"
        assert info["effective_backend"] in ("sonar-pro", "standard")
        assert info["perplexity_key_set"] is False
        assert "valid_choices" in info

    def test_reflects_env_config(self, clean_env):
        clean_env.setenv("PERPLEXITY_API_KEY", "pplx-xxxx")
        clean_env.setenv("CIRCUIT_WEAVER_RESEARCH_BACKEND", "sonar-pro")
        info = backend_info()
        assert info["perplexity_key_set"] is True
        assert info["env_value"] == "sonar-pro"
        assert info["effective_backend"] == "sonar-pro"


class TestDoctorIncludesBackendInfo:
    def test_doctor_reports_backend(self, clean_env):
        from circuit_weaver.doctor import run_doctor

        report = run_doctor()
        assert report.research_backend, "doctor must populate research_backend"
        assert "effective_backend" in report.research_backend

    def test_doctor_terminal_mentions_backend(self, clean_env):
        from circuit_weaver.doctor import run_doctor

        text = run_doctor().to_terminal()
        assert "Research backend" in text
