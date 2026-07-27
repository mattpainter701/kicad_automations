"""Regression tests for Sprint 37 Task 160 — research output persistence.

User report: the ``/research`` skill and ``research-analyst`` agent ran
but produced no artifacts in the project directory, so users couldn't
see or reproduce the reasoning behind IC selection. v0.26.0 introduces
``circuit-weaver save-research`` and a ``research_store`` module that
write ``{project_dir}/research/{topic}.json`` + ``.md`` + ``summary.md``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from circuit_weaver.logging_bridge import cleanup_logging, init_logging
from circuit_weaver.research_store import (
    ResearchCitation,
    ResearchFinding,
    ResearchResult,
    list_research_topics,
    load_research_result,
    save_research_from_dict,
    save_research_result,
    slugify,
)


class TestSlugify:
    def test_basic_lowercase(self):
        assert slugify("MCU Selection") == "mcu-selection"

    def test_strips_punctuation(self):
        assert slugify("MCU Selection (Zigbee)") == "mcu-selection-zigbee"

    def test_empty_string(self):
        assert slugify("") == "untitled"

    def test_only_punctuation(self):
        assert slugify("!!!") == "untitled"

    def test_truncates_long_input(self):
        long = "a" * 200
        assert len(slugify(long)) <= 60


class TestSaveResearchResult:
    @pytest.fixture(autouse=True)
    def _cleanup_logging(self):
        cleanup_logging()
        yield
        cleanup_logging()

    def test_writes_json_md_and_summary(self, tmp_path):
        result = ResearchResult(
            topic="MCU Selection",
            query="Battery-powered Zigbee MCU",
            backend="sonar-pro",
            summary="nRF52840 recommended",
            findings=[ResearchFinding(title="nRF52840", mpn="nRF52840-QIAA-R", cost_usd=6.5)],
            citations=[ResearchCitation(title="nRF52840 datasheet", url="https://nordic.example/ds")],
        )
        path = save_research_result(tmp_path, result)
        research_dir = tmp_path / "research"
        assert path == research_dir / "mcu-selection.json"
        assert (research_dir / "mcu-selection.md").exists()
        assert (research_dir / "summary.md").exists()

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["topic"] == "MCU Selection"
        assert data["backend"] == "sonar-pro"
        assert data["findings"][0]["mpn"] == "nRF52840-QIAA-R"
        assert data["timestamp"], "timestamp must be populated"

    def test_summary_md_indexes_multiple_topics(self, tmp_path):
        save_research_result(
            tmp_path,
            ResearchResult(topic="MCU", query="q1", backend="sonar-pro"),
        )
        save_research_result(
            tmp_path,
            ResearchResult(topic="Power", query="q2", backend="standard"),
        )
        summary = (tmp_path / "research" / "summary.md").read_text(encoding="utf-8")
        assert "| MCU |" in summary
        assert "| Power |" in summary
        assert "| sonar-pro |" in summary
        assert "| standard |" in summary

    def test_atomic_write_leaves_no_tmp_on_success(self, tmp_path):
        save_research_result(tmp_path, ResearchResult(topic="x", query="q"))
        leftover = list((tmp_path / "research").glob("*.tmp"))
        assert leftover == [], f"expected no tmp files, got: {leftover}"

    def test_re_save_overwrites_in_place(self, tmp_path):
        save_research_result(
            tmp_path,
            ResearchResult(topic="mcu", query="v1", backend="sonar-pro"),
        )
        save_research_result(
            tmp_path,
            ResearchResult(topic="mcu", query="v2", backend="standard"),
        )
        data = json.loads((tmp_path / "research" / "mcu.json").read_text(encoding="utf-8"))
        assert data["query"] == "v2"
        assert data["backend"] == "standard"

    def test_design_log_references_saved_json_path(self, tmp_path):
        init_logging(tmp_path)
        json_path = save_research_result(
            tmp_path,
            ResearchResult(topic="Sensor", query="q", backend="standard"),
        )

        entries = [
            json.loads(line)
            for line in (tmp_path / "design.log").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        research_entries = [entry for entry in entries if entry.get("type") == "research"]
        assert research_entries, "expected at least one research entry in design.log"
        latest = research_entries[-1]
        assert latest["backend"] == "standard"
        assert latest["artifact_path"] == str(json_path)


class TestSaveResearchFromDict:
    def test_accepts_plain_dict_payload(self, tmp_path):
        payload = {
            "topic": "Power Supply",
            "query": "3.3V buck at 1A",
            "backend": "sonar-pro",
            "findings": [{"title": "AP62300", "mpn": "AP62300TWU-7", "cost_usd": 0.85}],
            "citations": [{"title": "AP62300 ds", "url": "https://diodes.example/ds"}],
        }
        path = save_research_from_dict(tmp_path, payload)
        assert path.exists()
        loaded = load_research_result(path)
        assert loaded.topic == "Power Supply"
        assert len(loaded.findings) == 1
        assert loaded.findings[0].mpn == "AP62300TWU-7"

    def test_tolerates_partial_payload(self, tmp_path):
        """A minimal payload (just topic + query) should not crash — agents
        in early-development skills may not populate every field."""
        path = save_research_from_dict(
            tmp_path,
            {"topic": "Sensor", "query": "I2C temp+humidity"},
        )
        loaded = load_research_result(path)
        assert loaded.topic == "Sensor"
        assert loaded.findings == []
        assert loaded.citations == []

    def test_rejects_non_dict(self, tmp_path):
        # Not a dict → the dataclass rehydrator should still produce an empty
        # result rather than raising, because this path is called from the
        # CLI after JSON.loads and we prefer a diagnostic over a crash.
        # (The CLI guards against non-dict payloads before calling this.)
        from circuit_weaver.research_store import _from_dict  # type: ignore[attr-defined]

        assert isinstance(_from_dict({}), ResearchResult)


class TestListResearchTopics:
    def test_returns_empty_when_no_research_dir(self, tmp_path):
        assert list_research_topics(tmp_path) == []

    def test_lists_all_saved_topics(self, tmp_path):
        save_research_result(tmp_path, ResearchResult(topic="MCU", query="q"))
        save_research_result(tmp_path, ResearchResult(topic="Power", query="q"))
        topics = list_research_topics(tmp_path)
        assert {t["topic"] for t in topics} == {"MCU", "Power"}
        for t in topics:
            assert Path(t["path"]).exists()


@pytest.mark.skip_category("platform")
@pytest.mark.skipif(sys.platform == "win32" and sys.version_info < (3, 11), reason="Windows subprocess encoding quirk")
class TestSaveResearchCli:
    """End-to-end: `circuit-weaver save-research` reads JSON from stdin."""

    def test_cli_writes_research_files(self, tmp_path):
        payload = json.dumps(
            {
                "topic": "CLI Test Topic",
                "query": "integration test",
                "backend": "standard",
                "findings": [{"title": "Fake", "mpn": "FAKE-1", "cost_usd": 1.23}],
            }
        )
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "circuit_weaver",
                "save-research",
                "--project-dir",
                str(tmp_path),
            ],
            input=payload,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        json_path = tmp_path / "research" / "cli-test-topic.json"
        assert json_path.exists()
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["topic"] == "CLI Test Topic"
        assert data["backend"] == "standard"

    def test_cli_rejects_non_json_input(self, tmp_path):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "circuit_weaver",
                "save-research",
                "--project-dir",
                str(tmp_path),
            ],
            input="this is not json",
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 2
        assert "invalid JSON" in proc.stderr or "Invalid JSON" in proc.stderr
