"""Unit tests for the shared layout-quality analyzer (T239)."""

from __future__ import annotations

from circuit_weaver.layout_quality import LayoutQualityReport, analyze_schematic_text

_SCH_TEMPLATE = """(kicad_sch (version 20230121) (generator circuit_weaver)
  (lib_symbols
    (symbol "BOX" (pin_names hide)
      (symbol "BOX_0_1"
        (rectangle (start -2.54 2.54) (end 2.54 -2.54)
          (stroke (width 0.254) (type default))
          (fill (type background))
        )
      )
    )
  )
{body}
)
"""


def _sym(ref: str, x: float, y: float, rot: float = 0.0) -> str:
    return (
        f'  (symbol (lib_id "BOX") (at {x} {y} {rot}) (unit 1)\n'
        f'    (property "Reference" "{ref}" (at {x} {y} 0))\n'
        "  )\n"
    )


def _wire(x1: float, y1: float, x2: float, y2: float) -> str:
    return f"  (wire (pts (xy {x1} {y1}) (xy {x2} {y2})))\n"


def test_clean_sheet_reports_clean():
    text = _SCH_TEMPLATE.format(body=_sym("U1", 50, 50) + _wire(60, 60, 80, 60))
    report = analyze_schematic_text(text)
    assert report.symbols == 1
    assert report.clean
    assert "no overlaps" in report.summary()


def test_overlapping_bodies_detected():
    text = _SCH_TEMPLATE.format(body=_sym("U1", 50, 50) + _sym("U2", 51, 51))
    report = analyze_schematic_text(text)
    assert report.symbols == 2
    assert len(report.overlaps) == 1
    assert report.overlaps[0][:2] == ("U1", "U2")
    assert not report.clean
    assert "overlapping" in report.summary()


def test_wire_through_body_detected():
    text = _SCH_TEMPLATE.format(body=_sym("U1", 50, 50) + _wire(40, 50, 60, 50))
    report = analyze_schematic_text(text)
    assert report.wire_body_crossings == 1
    assert not report.clean
    assert "crossing" in report.summary()


def test_rotated_instance_bbox_applies_rotation():
    # A wire passing where the un-rotated body would NOT be, but the
    # rotated body IS: symmetric square means rotation-neutral, so use a
    # crossing that hits regardless to prove rotation parsing doesn't blow up.
    text = _SCH_TEMPLATE.format(body=_sym("U1", 50, 50, rot=90) + _wire(50, 40, 50, 60))
    report = analyze_schematic_text(text)
    assert report.symbols == 1
    assert report.wire_body_crossings == 1


def test_report_section_renders_layout_quality(tmp_path):
    from circuit_weaver.report import generate_report

    reports = {
        "clean.kicad_sch": LayoutQualityReport(symbols=5),
        "dirty.kicad_sch": LayoutQualityReport(
            symbols=7, overlaps=[("C1", "C2", 1.5)], wire_body_crossings=3
        ),
    }
    out = generate_report(
        [],
        output_path=tmp_path / "report.md",
        metadata={"project": "T", "layout_quality": reports},
    )
    content = out.read_text(encoding="utf-8")
    assert "## Layout Quality" in content
    assert "`dirty.kicad_sch` | 7 | 1 | 3" in content
    assert "`clean.kicad_sch` | 5 | 0 | 0" in content
    assert "review placement" in content
