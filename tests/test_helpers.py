from __future__ import annotations

from pathlib import Path

from circuit_weaver.helpers import (
    find_width_for_z0,
    get_state_path,
    microstrip_z0,
    values_match,
)


def test_values_match_normalizes_passive_spellings():
    assert values_match("4u7", "4.7uF")
    assert values_match("100nF", "0.1uF")
    assert not values_match("10uF", "1uF")


def test_get_state_path_places_silkscreen_sidecar_next_to_board():
    state = get_state_path(r"C:\proj\board.kicad_pcb")
    assert state == Path(r"C:\proj\board.silkscreen_state.json")


def test_microstrip_helpers_find_near_50_ohm_width():
    width = find_width_for_z0(50.0, h_mm=0.10, er=4.1, t_mm=0.035)
    z0, _ = microstrip_z0(width, h_mm=0.10, er=4.1, t_mm=0.035)
    assert 45.0 <= z0 <= 55.0
