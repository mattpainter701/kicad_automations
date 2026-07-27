"""Evidence traceability rendering for primary report generators."""

from __future__ import annotations

from pathlib import Path

import pytest

from circuit_weaver.design_ir import DesignIR
from circuit_weaver.report import generate_report
from circuit_weaver.review_report import generate_review_report_html


def test_markdown_report_renders_sorted_portable_evidence_references(tmp_path: Path) -> None:
    output = tmp_path / "design_report.md"

    generate_report(
        [],
        output_path=output,
        evidence_manifest="evidence_manifest.json",
        evidence_ids=["EV-USER-2", "EV-CALC-1", "EV-USER-2"],
    )

    content = output.read_text(encoding="utf-8")
    assert "## Evidence Traceability" in content
    assert "[`evidence_manifest.json`](evidence_manifest.json)" in content
    assert content.index("EV-CALC-1") < content.index("EV-USER-2")


def test_review_report_renders_portable_evidence_link_and_escapes_ids(tmp_path: Path) -> None:
    output = tmp_path / "review.html"

    generate_review_report_html(
        DesignIR(metadata={"project": "Evidence"}),
        output,
        evidence_manifest="evidence_manifest.json",
        evidence_ids=["EV-USER-1", "EV-<unsafe>"],
    )

    content = output.read_text(encoding="utf-8")
    assert "Evidence Traceability" in content
    assert 'href="evidence_manifest.json"' in content
    assert "EV-&lt;unsafe&gt;" in content


@pytest.mark.parametrize("generator", [generate_report, generate_review_report_html])
def test_report_generators_reject_nonportable_evidence_paths(tmp_path: Path, generator) -> None:
    output = tmp_path / "report.out"

    with pytest.raises(ValueError, match="output-relative"):
        if generator is generate_report:
            generator([], output_path=output, evidence_manifest=tmp_path / "evidence_manifest.json")
        else:
            generator(DesignIR(metadata={}), output, evidence_manifest=tmp_path / "evidence_manifest.json")
