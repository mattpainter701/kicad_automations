"""Regression tests for register-ic input handling."""

from __future__ import annotations

import argparse
import json

import pytest

from circuit_weaver import dispatcher, ic_data


def _args(path, mpn: str | None = None):
    return argparse.Namespace(command="register-ic", file=str(path), mpn=mpn)


def _generate_args(path, output):
    return argparse.Namespace(
        command="generate",
        spec=str(path),
        output=str(output),
        presentation_profile=None,
        auto_source=False,
        update_spec=False,
        svg_placement=False,
        require_valid=True,
        enrich_parts=False,
        export_svg=False,
        score=False,
        export_pinout=False,
    )


def test_register_ic_accepts_single_object_with_mpn_and_template_type(tmp_path, monkeypatch):
    payload = {
        "mpn": "TLV3691IDPFR",
        "template_type": "opamp",
        "manufacturer": "Texas Instruments",
        "footprint": "Package_SO:TSSOP-8_3x3mm_P0.65mm",
        "pins": [],
    }
    path = tmp_path / "tlv3691.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    calls = []

    monkeypatch.setattr(ic_data, "register_ic", lambda mpn, data, persist=True: calls.append((mpn, data, persist)))

    with pytest.raises(SystemExit) as exc:
        dispatcher._main_dispatch(_args(path), lambda *_args, **_kwargs: None)

    assert exc.value.code == 0
    assert calls == [("TLV3691IDPFR", {**payload, "topology": "opamp"}, True)]


def test_register_ic_rejects_mapping_with_scalar_entries(tmp_path, monkeypatch):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"mpn": "TLV3691", "manufacturer": "TI"}), encoding="utf-8")
    calls = []
    monkeypatch.setattr(ic_data, "register_ic", lambda mpn, data, persist=True: calls.append((mpn, data, persist)))

    with pytest.raises(SystemExit) as exc:
        dispatcher._main_dispatch(_args(path), lambda *_args, **_kwargs: None)

    assert exc.value.code == 1
    assert calls == []


def test_ic_data_accessors_ignore_malformed_custom_entries():
    original = ic_data._ic_database
    ic_data._ic_database = {
        "mpn": "TLV3691IDPFR",
        "GOOD_CONN": {"topology": "connector", "pins": []},
    }
    try:
        assert ic_data.get_all_ics("connector") == {"GOOD_CONN": {"topology": "connector", "pins": []}}
        assert ic_data.list_topologies() == ["connector"]
    finally:
        ic_data._ic_database = original


def test_register_ic_replaces_existing_malformed_entry(monkeypatch):
    original = ic_data._ic_database
    ic_data._ic_database = {"BAD": "not an ic"}
    monkeypatch.setattr(ic_data, "_write_custom", lambda mpn, data: None)
    try:
        ic_data.register_ic("BAD", {"topology": "connector", "pins": []})
        assert ic_data.get_ic_data("BAD") == {"topology": "connector", "pins": []}
    finally:
        ic_data._ic_database = original


def test_generate_invalid_design_returns_clean_cli_error(tmp_path, monkeypatch, capsys):
    spec_path = tmp_path / "design.yaml"
    spec_path.write_text("project: bad\n", encoding="utf-8")

    def fail_validation(*_args, **_kwargs):
        raise ValueError("Design has 1 structural/implementation/placement_readiness error(s) - fix these")

    monkeypatch.setattr(dispatcher, "generate_artifacts", fail_validation)

    with pytest.raises(SystemExit) as exc:
        dispatcher._main_dispatch(_generate_args(spec_path, tmp_path / "out"), lambda *_args, **_kwargs: None)

    out = capsys.readouterr().out
    assert exc.value.code == 2
    assert '"status": "error"' in out
    assert "Traceback" not in out
