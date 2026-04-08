"""Tests for ERC section in review_report.py — Task 119."""

from __future__ import annotations

from circuit_weaver.erc_runner import ErcResult, ErcViolation
from circuit_weaver.review_report import _generate_erc_section


def test_erc_section_none_shows_not_run():
    html = _generate_erc_section(None)
    assert "not run" in html
    assert "ERC" in html


def test_erc_section_skipped():
    result = ErcResult(status="skipped", skip_reason="KiCad CLI not available")
    html = _generate_erc_section(result)
    assert "not run" in html
    assert "KiCad CLI not available" in html


def test_erc_section_clean_shows_green_badge():
    result = ErcResult(status="ok", errors=0, warnings=0)
    html = _generate_erc_section(result)
    assert "0 errors" in html
    assert "0 warnings" in html
    assert "green" in html
    assert "✓" in html


def test_erc_section_errors_shows_red_badge_and_list():
    result = ErcResult(
        status="ok",
        errors=1,
        warnings=1,
        violations=[
            ErcViolation(type="pin_not_connected", description="Pin unconnected", severity="error"),
            ErcViolation(type="label_dangling", description="Dangling label", severity="warning"),
        ],
    )
    html = _generate_erc_section(result)
    assert "red" in html
    assert "1 error" in html
    assert "pin_not_connected" in html
    assert "label_dangling" in html
    assert "✗" in html


def test_erc_section_accepts_dict_from_generate_artifacts():
    """_generate_erc_section must accept a plain dict (as returned by generate_artifacts)."""
    d = {
        "status": "ok",
        "errors": 0,
        "warnings": 0,
        "skip_reason": "",
        "violations": [],
        "schematic": "board.kicad_sch",
    }
    html = _generate_erc_section(d)
    assert "0 errors" in html
    assert "green" in html


def test_erc_section_failed_shows_warning():
    result = ErcResult(status="failed", skip_reason="parse error: unexpected token")
    html = _generate_erc_section(result)
    assert "failed" in html.lower() or "⚠" in html
    assert "parse error" in html
