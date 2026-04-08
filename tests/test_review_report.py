"""Tests for Task 123 — Design Rationale in HTML Review Report."""

from __future__ import annotations

from circuit_weaver.design_ir import DesignBlock, DesignIR
from circuit_weaver.review_report import _generate_rationale_section


def _ic_block(ref: str, ic: str = "", description: str = "", params: dict | None = None) -> DesignBlock:
    return DesignBlock(
        id=f"power:{ref}:aabbccdd",
        section="power",
        kind="component",
        ref=ref,
        ic=ic,
        description=description,
        params=params or {},
    )


def test_rationale_renders_per_ic():
    """Each IC block appears as a row in the rationale section."""
    ir = DesignIR(
        metadata={"project": "test"},
        blocks=[
            _ic_block("U1", ic="TPS62082", description="3.3V buck for MCU rail"),
            _ic_block("U2", ic="ESP32-S3", description="Main application MCU"),
        ],
    )
    html = _generate_rationale_section(ir)
    assert "U1" in html
    assert "TPS62082" in html
    assert "3.3V buck for MCU rail" in html
    assert "U2" in html
    assert "ESP32-S3" in html
    assert "Main application MCU" in html
    assert "<table" in html


def test_missing_rationale_shows_fallback():
    """Blocks with no description or specs get the fallback notice."""
    ir = DesignIR(
        metadata={"project": "test"},
        blocks=[_ic_block("U3", ic="LM1117")],  # no description, no params
    )
    html = _generate_rationale_section(ir)
    assert "U3" in html
    assert "verify against datasheet" in html
    # Should NOT show an empty why-selected cell without the fallback text
    assert "Selected via component registry" in html


def test_html_escaping_correct():
    """HTML special characters in IC names and descriptions are escaped."""
    ir = DesignIR(
        metadata={"project": "test"},
        blocks=[
            _ic_block(
                "U4",
                ic='<script>alert("xss")</script>',
                description="5V rail: Vin > 4.5V & Vout < 5.5V",
            )
        ],
    )
    html = _generate_rationale_section(ir)
    # Raw special chars must not appear unescaped
    assert "<script>" not in html
    assert 'alert("xss")' not in html
    assert "&lt;script&gt;" in html
    # Description escaping
    assert "&amp;" in html
    assert "&gt;" in html or "&lt;" in html


def test_key_specs_from_params_appear():
    """Electrical specs from block.params are listed in the Key Specs column."""
    ir = DesignIR(
        metadata={"project": "test"},
        blocks=[
            _ic_block(
                "U5",
                ic="TPS61230",
                description="Boost converter",
                params={"vin": "3.3V", "vout": "5V", "iout": "500mA"},
            )
        ],
    )
    html = _generate_rationale_section(ir)
    assert "vin: 3.3V" in html
    assert "vout: 5V" in html
    assert "iout: 500mA" in html
    # Description is present as why-selected, not fallback
    assert "Boost converter" in html
    assert "verify against datasheet" not in html
