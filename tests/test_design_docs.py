"""Tests for design documentation generator."""

import csv
from dataclasses import dataclass

import pytest

from circuit_weaver.component_db import ComponentDef
from circuit_weaver.design_docs import (
    _generate_bom_table,
    _generate_power_budget,
    generate_all_docs,
    generate_assembly_guide_csv,
    generate_datasheet_index,
    generate_ordering_checklist,
    generate_power_budget_csv,
)
from circuit_weaver.design_ir import DesignIR, PowerDomain


@dataclass
class MockDesignIR:
    """Mock DesignIR for testing."""

    components: dict


@pytest.fixture
def sample_design_ir():
    """Create a minimal design IR for testing."""
    ir = MockDesignIR(
        components={
            "U1": ComponentDef(
                mpn="STM32H743VIT6",
                ref_prefix="U",
                value="STM32H743",
                category="mcu",
                footprint="BGA-176",
                source_mpn="STM32H743VIT6",
                source_manufacturer="STMicroelectronics",
            ),
            "R1": ComponentDef(
                mpn="RC0805FR-0710KL",
                ref_prefix="R",
                value="10k",
                category="passive",
                footprint="0805",
                source_mpn="RC0805FR-0710KL",
                source_manufacturer="Yageo",
            ),
            "C1": ComponentDef(
                mpn="GRM155R71C104KA88D",
                ref_prefix="C",
                value="100nF",
                category="passive",
                footprint="0402",
                source_mpn="GRM155R71C104KA88D",
                source_manufacturer="Murata",
            ),
        },
    )
    return ir


class TestGenerateBOMTable:
    """Test BOM extraction."""

    def test_generate_bom_table(self, sample_design_ir):
        """Extract BOM from design IR."""
        bom = _generate_bom_table(sample_design_ir)
        assert len(bom) == 3
        assert bom[0]["reference"] in ("C1", "R1", "U1")  # May be sorted

    def test_bom_table_fields(self, sample_design_ir):
        """BOM table should have required fields."""
        bom = _generate_bom_table(sample_design_ir)
        required_fields = {
            "reference",
            "value",
            "footprint",
            "mpn",
            "manufacturer",
            "category",
        }
        assert required_fields.issubset(bom[0].keys())

    def test_bom_sorted_by_category(self, sample_design_ir):
        """BOM should be sorted by category then reference."""
        bom = _generate_bom_table(sample_design_ir)
        # All passives should come after MCU (alphabetically)
        categories = [item["category"] for item in bom]
        assert categories.index("mcu") < categories.index("passive")


class TestGeneratePowerBudget:
    """Test power budget generation."""

    def test_generate_power_budget(self, sample_design_ir):
        """Extract power budget from design IR."""
        budget = _generate_power_budget(sample_design_ir)
        assert isinstance(budget, list)
        if budget:
            assert "rail" in budget[0]
            assert "voltage" in budget[0]

    def test_typed_power_domains_preserve_unknowns_and_declared_provenance(self):
        design = DesignIR(
            power_domains=[
                PowerDomain(
                    net="VBAT", v_min=3.0, v_nominal=3.7, v_max=4.2,
                    direction="source", i_peak_ma=800, evidence_id="EV-DATASHEET-123456789abc",
                )
            ]
        )

        budget = _generate_power_budget(design)

        assert budget == [
            {
                "rail": "VBAT", "voltage": 3.7, "current_ma": None, "power_w": None,
                "v_min": 3.0, "v_nominal": 3.7, "v_max": 4.2, "direction": "source",
                "i_steady_ma": None, "i_peak_ma": 800, "sequence_order": None,
                "sequence_dependency": None, "tolerance": None, "evidence_id": "EV-DATASHEET-123456789abc",
            }
        ]


class TestAssemblyGuideCSV:
    """Test assembly guide CSV generation."""

    def test_generate_assembly_guide_csv(self, sample_design_ir, tmp_path):
        """Generate assembly guide CSV."""
        output = tmp_path / "assembly_guide.csv"
        result = generate_assembly_guide_csv(sample_design_ir, output)
        assert result.exists()
        assert result.suffix == ".csv"

    def test_assembly_guide_csv_content(self, sample_design_ir, tmp_path):
        """CSV should have valid headers and data."""
        output = tmp_path / "assembly_guide.csv"
        generate_assembly_guide_csv(sample_design_ir, output)

        with open(output, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 3
        assert "Reference" in rows[0]
        assert "MPN" in rows[0]

    def test_assembly_guide_creates_parent_dir(self, sample_design_ir, tmp_path):
        """Should create parent directories if they don't exist."""
        output = tmp_path / "subdir" / "assembly_guide.csv"
        result = generate_assembly_guide_csv(sample_design_ir, output)
        assert result.parent.exists()


class TestPowerBudgetCSV:
    """Test power budget CSV generation."""

    def test_generate_power_budget_csv(self, sample_design_ir, tmp_path):
        """Generate power budget CSV."""
        output = tmp_path / "power_budget.csv"
        result = generate_power_budget_csv(sample_design_ir, output)
        assert result.exists()
        assert result.suffix == ".csv"

    def test_power_budget_csv_content(self, sample_design_ir, tmp_path):
        """CSV should have valid structure."""
        output = tmp_path / "power_budget.csv"
        generate_power_budget_csv(sample_design_ir, output)

        with open(output, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if rows:
            assert "Rail" in rows[0]
            assert "Voltage" in rows[0]


class TestOrderingChecklist:
    """Test ordering checklist generation."""

    def test_generate_ordering_checklist(self, sample_design_ir, tmp_path):
        """Generate ordering checklist."""
        output = tmp_path / "ordering_checklist.md"
        result = generate_ordering_checklist(sample_design_ir, output)
        assert result.exists()
        assert result.suffix == ".md"

    def test_ordering_checklist_content(self, sample_design_ir, tmp_path):
        """Checklist should contain distributors and component status."""
        output = tmp_path / "ordering_checklist.md"
        generate_ordering_checklist(sample_design_ir, output)

        content = output.read_text()
        assert "DigiKey" in content
        assert "Mouser" in content
        assert "LCSC" in content
        assert "U1" in content  # Component reference should be present


class TestDatasheetIndex:
    """Test datasheet index generation."""

    def test_generate_datasheet_index_empty(self, tmp_path):
        """Generate index for empty datasheet directory."""
        datasheets_dir = tmp_path / "datasheets"
        datasheets_dir.mkdir()
        output = tmp_path / "datasheet_index.md"

        result = generate_datasheet_index(datasheets_dir, output)
        assert result.exists()

    def test_datasheet_index_content(self, tmp_path):
        """Index should list all PDF files."""
        datasheets_dir = tmp_path / "datasheets"
        datasheets_dir.mkdir()

        # Create dummy PDF files
        (datasheets_dir / "STM32H743VIT6.pdf").write_text("dummy")
        (datasheets_dir / "RC0805FR-0710KL.pdf").write_text("dummy")

        output = tmp_path / "datasheet_index.md"
        generate_datasheet_index(datasheets_dir, output)

        content = output.read_text()
        assert "STM32H743VIT6" in content
        assert "RC0805FR-0710KL" in content
        assert ".pdf" in content

    def test_datasheet_index_missing_dir(self, tmp_path):
        """Should handle missing datasheet directory gracefully."""
        datasheets_dir = tmp_path / "missing"
        output = tmp_path / "datasheet_index.md"

        # Should return empty index or note missing dir
        generate_datasheet_index(datasheets_dir, output)
        # May or may not succeed depending on implementation


class TestGenerateAllDocs:
    """Test all-in-one documentation generation."""

    def test_generate_all_docs(self, sample_design_ir, tmp_path):
        """Generate all documentation files."""
        output_dir = tmp_path / "docs"
        results = generate_all_docs(sample_design_ir, output_dir)

        assert "assembly_guide" in results
        assert "power_budget" in results
        assert "ordering_checklist" in results

    def test_generate_all_docs_with_datasheets(self, sample_design_ir, tmp_path):
        """Generate all docs including datasheet index."""
        datasheets_dir = tmp_path / "datasheets"
        datasheets_dir.mkdir()
        (datasheets_dir / "STM32H743VIT6.pdf").write_text("dummy")

        output_dir = tmp_path / "docs"
        results = generate_all_docs(
            sample_design_ir,
            output_dir,
            datasheets_dir=datasheets_dir,
        )

        assert "datasheet_index" in results

    def test_all_generated_files_exist(self, sample_design_ir, tmp_path):
        """All generated files should exist and be readable."""
        output_dir = tmp_path / "docs"
        results = generate_all_docs(sample_design_ir, output_dir)

        for file_type, path in results.items():
            assert path.exists(), f"{file_type} file does not exist: {path}"
            assert path.stat().st_size > 0, f"{file_type} file is empty: {path}"
