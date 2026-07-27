"""Structural contract for the versioned electrical benchmark fixtures."""

from __future__ import annotations

import json
import re
from pathlib import Path

CORPUS = Path(__file__).parents[1] / "benchmarks" / "electrical"
DOMAINS = {
    "power",
    "clock",
    "usb",
    "i2c",
    "spi",
    "uart",
    "analog",
    "protection",
    "manufacturing",
    "identity",
    "passives",
}
RULE_ID = re.compile(r"^CW-[A-Z0-9]+-[0-9]{3}$")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_every_domain_has_one_positive_and_negative_fixture_pair():
    for polarity in ("positive", "negative"):
        found = {path.name for path in (CORPUS / polarity).iterdir() if path.is_dir()}
        assert found == DOMAINS
        for domain in DOMAINS:
            fixture = CORPUS / polarity / domain
            direct_pair = (fixture / "design.json").is_file() and (fixture / "expected-findings.json").is_file()
            nested_pairs = list(fixture.glob("*/expected-findings.json"))
            assert direct_pair or nested_pairs


def test_oracles_follow_the_v1_contract_and_keep_authorship_separate():
    schema = _read_json(CORPUS / "fixture.schema.json")
    required = set(schema["required"])
    for polarity in ("positive", "negative"):
        for domain in DOMAINS:
            fixture = CORPUS / polarity / domain
            if not (fixture / "expected-findings.json").is_file():
                continue
            design = _read_json(fixture / "design.json")
            oracle = _read_json(fixture / "expected-findings.json")
            assert required <= set(oracle)
            assert oracle["schema_version"] == "circuit-weaver-electrical-benchmark/v1"
            assert oracle["domain"] == domain
            assert oracle["polarity"] == polarity
            assert oracle["authoring_source"] == (
                "generator_authored" if polarity == "positive" else "independent_reference"
            )
            assert set(oracle["provenance"]) >= {"source_type", "source_ref", "license"}
            assert design["benchmark_intent"]["domain"] == domain
            assert design["benchmark_intent"]["polarity"] == polarity
            rule_ids = set(oracle["expected_absent_rule_ids"])
            rule_ids.update(finding["rule_id"] for finding in oracle["expected_findings"])
            assert rule_ids and all(RULE_ID.fullmatch(rule_id) for rule_id in rule_ids)
            if polarity == "positive":
                assert oracle["expected_findings"] == []
            else:
                assert oracle["expected_findings"]
                assert {finding["expectation"] for finding in oracle["expected_findings"]} <= {
                    "detected",
                    "unsupported",
                }


def test_nested_domain_cases_follow_the_same_contract():
    for polarity in ("positive", "negative"):
        for expected_path in (CORPUS / polarity).glob("*/*/expected-findings.json"):
            oracle = _read_json(expected_path)
            design = _read_json(expected_path.with_name("design.json"))
            assert oracle["domain"] == expected_path.parents[1].name
            assert oracle["polarity"] == polarity
            intent = design.get("benchmark_intent")
            if intent is None:
                assert oracle["domain"] == "identity" and "identity_handoff" in design
            else:
                assert intent["domain"] == oracle["domain"]
                assert intent["polarity"] == polarity
