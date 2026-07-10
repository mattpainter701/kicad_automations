"""Safety boundaries for the review-only PCB placement preview."""

from __future__ import annotations

from pathlib import Path

from circuit_weaver.component_db import ComponentDef
from circuit_weaver.pcb_export import _safe_project_filename, generate_pcb_placement


def _assert_balanced_sexpr(text: str) -> None:
    depth = 0
    quoted = False
    escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            assert depth >= 0
    assert not quoted
    assert depth == 0


def test_project_name_cannot_escape_output_directory(tmp_path: Path) -> None:
    output = tmp_path / "preview"

    pcb_file, _ = generate_pcb_placement([], output, project_name="../../outside")

    path = Path(pcb_file)
    assert path.resolve().parent == output.resolve()
    assert path.name == ".._.._outside_placement_preview.kicad_pcb"
    assert not (tmp_path / "outside_placement_preview.kicad_pcb").exists()


def test_project_filename_is_portable_for_empty_and_windows_device_names() -> None:
    assert _safe_project_filename("..") == "project"
    assert _safe_project_filename("CON") == "_CON"
    assert _safe_project_filename("lpt9.txt") == "_lpt9.txt"
    assert _safe_project_filename(' board:*?<>. ') == "board_____"


def test_user_controlled_fields_cannot_inject_kicad_sexpressions(tmp_path: Path) -> None:
    malicious_ref = 'U1") (gr_text "INJECTED_REF" (at 0 0)) ('
    malicious_value = 'line1\nline2 \\ value ") (segment (start 0 0) (end 1 1)) ('
    malicious_footprint = 'Package:Thing") (zone (net 0) (layer "F.Cu")) ('
    malicious_net = 'SIGNAL") (segment (start 0 0) (end 2 2)) ('
    component = ComponentDef(
        mpn="unsafe",
        source_ref=malicious_ref,
        value=malicious_value,
        footprint=malicious_footprint,
        pin_nets={"1": malicious_net},
    )

    pcb_file, _ = generate_pcb_placement([component], tmp_path, project_name="safe")
    content = Path(pcb_file).read_text(encoding="utf-8")

    assert malicious_ref not in content
    assert malicious_value not in content
    assert malicious_footprint not in content
    assert malicious_net not in content
    assert "line1 line2" in content
    assert "\\\\ value" in content
    assert '\\"INJECTED_REF\\"' in content
    _assert_balanced_sexpr(content)
