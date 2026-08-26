import json
import os
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import circuit_weaver.repair_service as repair_service
from circuit_weaver.evidence import EvidenceLedger, EvidenceSource
from circuit_weaver.finding_model import FindingLocation, FindingObservation, RemediationOption, UnifiedFinding
from circuit_weaver.repair_service import (
    RepairRejected,
    _exclusive_file_lock,
    _metadata_integrity,
    _publish_staged,
    _source_lock_path,
    apply_no_connect,
    build_no_connect_metadata,
    no_connect_finding_from_intent,
    preview_no_connect,
    verify_no_connect,
)

SAMPLE = Path(__file__).parents[1] / "samples" / "led_power_indicator" / "led_power_indicator.kicad_sch"
U1_UUID = "08f8f6e8-0143-5cf9-bc58-b62360c40c0c"
NC_UUID = "e4a10e85-3223-5a4d-99e3-032389e612b8"
CLAIM = "Pin U1.4 is intentionally unused and should be marked no-connect."

EVIDENCE = EvidenceLedger()
EVIDENCE_ID = EVIDENCE.record(
    subject_ref="pin:U1.4",
    claim=CLAIM,
    kind="user",
    source=EvidenceSource(doc_id="repair-review-alice", extraction_method="human-review"),
    confidence="verified",
    freshness="current",
)
FINDING = UnifiedFinding(
    rule_id="CW-ERC-001",
    root_cause_key="explicit-no-connect:U1.4",
    message="U1.4 is intentionally unused and needs an explicit no-connect marker.",
    severity="major",
    detection_confidence="verified",
    location=FindingLocation(
        artifact_kind="schematic",
        artifact_path="led_power_indicator.kicad_sch",
        object_type="pin",
        object_id="U1.4",
        ref="U1",
        x_mm=242.57,
        y_mm=83.82,
    ),
    observations=(
        FindingObservation(
            source="human.review",
            source_finding_id="unused-pin-u1-4",
            message="U1.4 is intentionally unused and needs an explicit no-connect marker.",
            severity="major",
            detection_confidence="verified",
            location=FindingLocation(
                artifact_kind="schematic",
                artifact_path="led_power_indicator.kicad_sch",
                object_type="pin",
                object_id="U1.4",
                ref="U1",
                x_mm=242.57,
                y_mm=83.82,
            ),
            evidence_ids=(EVIDENCE_ID,),
            observed_value="human-reviewed intentionally unused pin",
        ),
    ),
    evidence_ids=(EVIDENCE_ID,),
    remediation_options=(
        RemediationOption(
            id="REM-explicit-no-connect",
            summary="Insert one explicit no-connect marker at U1.4.",
            kind="repair_plan",
            risk="low",
            supported=True,
        ),
    ),
)
FINDING_ID = FINDING.id


def fixture(tmp_path: Path) -> Path:
    target = tmp_path / "led_power_indicator.kicad_sch"
    target.parent.mkdir(parents=True, exist_ok=True)
    text = SAMPLE.read_text(encoding="utf-8")
    text = text.replace(f'  (no_connect (at 242.57 83.82) (uuid "{NC_UUID}"))\n', "")
    target.write_text(text, encoding="utf-8")
    return target


def analysis():
    return {
        "components": [
            {
                "reference": "U1",
                "uuid": U1_UUID,
                "lib_id": "TLV75518",
                "pins": [{"number": "4", "type": "passive", "x": 242.57, "y": 83.82}],
            }
        ]
    }


def metadata(source: Path):
    return build_no_connect_metadata(
        source,
        analysis(),
        FINDING,
        EVIDENCE.to_manifest(),
        ref="U1",
        pin="4",
    )


def reseal(metadata_payload: dict) -> dict:
    metadata_payload["content_integrity"] = _metadata_integrity(metadata_payload)
    return metadata_payload


def plan_for(source: Path) -> dict:
    return preview_no_connect(
        source,
        metadata(source),
        ref="U1",
        pin="4",
        finding_id=FINDING_ID,
        evidence_ids=(EVIDENCE_ID,),
    )


def apply_plan(source: Path, plan: dict, **kwargs):
    return apply_no_connect(
        plan,
        metadata(source),
        approved_plan_hash=plan["plan_sha256"],
        reviewer="alice",
        finding_id=FINDING_ID,
        evidence_ids=(EVIDENCE_ID,),
        **kwargs,
    )


def test_real_fixture_preview_apply_verify_idempotent(tmp_path: Path):
    source = fixture(tmp_path)
    plan = preview_no_connect(
        source,
        metadata(source),
        ref="U1",
        pin="4",
        finding_id=FINDING_ID,
        evidence_ids=(EVIDENCE_ID,),
    )
    assert plan["risk"] == "low"
    assert plan["prerequisites"]["component_identity"]["uuid"] == U1_UUID
    assert plan["semantic_post"]["no_connects"] == plan["semantic_pre"]["no_connects"] + 1
    assert plan["expected_postconditions"]["source_sha256"] == plan["post_sha256"]
    assert plan["rollback"]["source_sha256"] == plan["source_sha256"]
    result = apply_no_connect(
        plan,
        metadata(source),
        approved_plan_hash=plan["plan_sha256"],
        reviewer="alice",
        finding_id=FINDING_ID,
        evidence_ids=(EVIDENCE_ID,),
    )
    assert result["status"] == "applied"
    assert verify_no_connect(source, plan)
    assert (
        apply_no_connect(
            plan,
            metadata(source),
            approved_plan_hash=plan["plan_sha256"],
            reviewer="alice",
            finding_id=FINDING_ID,
            evidence_ids=(EVIDENCE_ID,),
        )["status"]
        == "already_applied"
    )
    assert (source.parent / ".circuit-weaver" / "repair-audit.jsonl").is_file()
    audit = json.loads((source.parent / ".circuit-weaver" / "repair-audit.jsonl").read_text().splitlines()[-1])
    assert audit["source_sha256_before"] != audit["source_sha256_after"]
    assert audit["approved_plan_hash"] == plan["plan_sha256"]
    assert audit["finding_id"] == FINDING_ID
    assert audit["evidence_ids"] == [EVIDENCE_ID]
    assert audit["state"] == "committed"
    assert audit["package_version"]
    assert audit["timestamp"].endswith("+00:00")

    copied = tmp_path / "copied-post-image.kicad_sch"
    copied.write_bytes(source.read_bytes())
    assert verify_no_connect(copied, plan) is False

    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert verify_no_connect(source, plan) is False
    with pytest.raises(RepairRejected, match="source changed"):
        apply_no_connect(
            plan,
            metadata(source),
            approved_plan_hash=plan["plan_sha256"],
            reviewer="alice",
            finding_id=FINDING_ID,
            evidence_ids=(EVIDENCE_ID,),
        )


def test_rejects_missing_or_wrong_identity_and_connected_pin(tmp_path: Path):
    source = fixture(tmp_path)
    bad = metadata(source)
    bad["analysis"]["components"][0].pop("uuid")
    reseal(bad)
    with pytest.raises(RepairRejected):
        preview_no_connect(
            source,
            bad,
            ref="U1",
            pin="4",
            finding_id=FINDING_ID,
            evidence_ids=(EVIDENCE_ID,),
        )
    bad = metadata(source)
    bad["analysis"]["components"][0]["uuid"] = "wrong"
    reseal(bad)
    with pytest.raises(RepairRejected):
        preview_no_connect(
            source,
            bad,
            ref="U1",
            pin="4",
            finding_id=FINDING_ID,
            evidence_ids=(EVIDENCE_ID,),
        )
    bad = metadata(source)
    bad["analysis"]["components"][0]["pins"][0]["x"] = 212.09
    reseal(bad)
    with pytest.raises(RepairRejected):
        preview_no_connect(
            source,
            bad,
            ref="U1",
            pin="4",
            finding_id=FINDING_ID,
            evidence_ids=(EVIDENCE_ID,),
        )


def test_repair_metadata_is_source_bound_and_tamper_evident(tmp_path: Path) -> None:
    source = fixture(tmp_path)
    trusted = metadata(source)
    tampered = json.loads(json.dumps(trusted))
    tampered["assertion"]["pin"] = "5"

    with pytest.raises(RepairRejected, match="content_integrity"):
        preview_no_connect(
            source,
            tampered,
            ref="U1",
            pin="4",
            finding_id=FINDING_ID,
            evidence_ids=(EVIDENCE_ID,),
        )

    forged_evidence = json.loads(json.dumps(trusted))
    forged_evidence["evidence_manifest"]["records"][0]["claim"] = "fabricated intent"
    reseal(forged_evidence)
    with pytest.raises(RepairRejected, match="evidence manifest"):
        preview_no_connect(
            source,
            forged_evidence,
            ref="U1",
            pin="4",
            finding_id=FINDING_ID,
            evidence_ids=(EVIDENCE_ID,),
        )

    other = fixture(tmp_path / "other")
    with pytest.raises(RepairRejected, match="exact source bytes"):
        preview_no_connect(
            other,
            trusted,
            ref="U1",
            pin="4",
            finding_id=FINDING_ID,
            evidence_ids=(EVIDENCE_ID,),
        )


def test_trusted_intent_producer_consumes_production_analyzer_shape(tmp_path: Path) -> None:
    source = fixture(tmp_path)
    finding = no_connect_finding_from_intent(
        source,
        analysis(),
        EVIDENCE.to_manifest(),
        ref="U1",
        pin="4",
    )
    bound = build_no_connect_metadata(
        source,
        analysis(),
        finding,
        EVIDENCE.to_manifest(),
        ref="U1",
        pin="4",
    )

    plan = preview_no_connect(
        source,
        bound,
        ref="U1",
        pin="4",
        finding_id=finding.id,
        evidence_ids=finding.evidence_ids,
    )

    assert plan["status"] == "proposed"
    assert plan["finding_id"] == finding.id


def test_rejects_tamper_stale_and_approval_failures(tmp_path: Path):
    source = fixture(tmp_path)
    plan = preview_no_connect(
        source,
        metadata(source),
        ref="U1",
        pin="4",
        finding_id=FINDING_ID,
        evidence_ids=(EVIDENCE_ID,),
    )
    with pytest.raises(RepairRejected, match="approved_plan_hash"):
        apply_no_connect(
            plan,
            metadata(source),
            approved_plan_hash="wrong",
            reviewer="a",
            finding_id=FINDING_ID,
            evidence_ids=(EVIDENCE_ID,),
        )
    assert not _source_lock_path(source.resolve()).exists()
    tampered = {**plan, "risk": "medium"}
    with pytest.raises(RepairRejected, match="tampered repair plan"):
        apply_no_connect(
            tampered,
            metadata(source),
            approved_plan_hash=plan["plan_sha256"],
            reviewer="a",
            finding_id=FINDING_ID,
            evidence_ids=(EVIDENCE_ID,),
        )
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(RepairRejected, match="source changed"):
        apply_no_connect(
            plan,
            metadata(source),
            approved_plan_hash=plan["plan_sha256"],
            reviewer="a",
            finding_id=FINDING_ID,
            evidence_ids=(EVIDENCE_ID,),
        )


def test_rejects_no_pin_metadata(tmp_path: Path):
    source = fixture(tmp_path)
    bad = metadata(source)
    bad["analysis"]["components"][0]["pins"] = []
    reseal(bad)
    with pytest.raises(RepairRejected):
        preview_no_connect(
            source,
            bad,
            ref="U1",
            pin="4",
            finding_id=FINDING_ID,
            evidence_ids=(EVIDENCE_ID,),
        )


def test_rejects_wire_and_label_connectivity(tmp_path: Path):
    source = fixture(tmp_path)
    base = source.read_text(encoding="utf-8")
    for connection in (
        '  (wire (pts (xy 242.57 83.82) (xy 250 83.82)) (stroke (width 0) (type default)) (uuid "wire-1"))\n',
        '  (wire (pts (xy 235 76.25) (xy 250.14 91.39)) (stroke (width 0) (type default)) (uuid "wire-2"))\n',
        '  (global_label "CONNECTED" (shape input) (at 242.57 83.82 0) (effects (font (size 1 1))) (uuid "label-1"))\n',
    ):
        source.write_text(base[: base.rfind(")")] + connection + base[base.rfind(")") :], encoding="utf-8")
        with pytest.raises(RepairRejected):
            preview_no_connect(
                source,
                metadata(source),
                ref="U1",
                pin="4",
                finding_id=FINDING_ID,
                evidence_ids=(EVIDENCE_ID,),
            )
        source.write_text(base, encoding="utf-8")


@pytest.mark.parametrize(
    "connection",
    [
        """  (symbol (lib_id "VBUS_5V") (at 242.57 83.82 0) (unit 1)
    (property "Reference" "#PWR099" (at 242.57 87.63 0))
    (property "Value" "VBUS_5V" (at 242.57 86.36 0))
    (uuid "10000000-0000-0000-0000-000000000001")
    (pin "1" (uuid "10000000-0000-0000-0000-000000000002"))
  )
""",
        """  (symbol (lib_id "C_Review") (at 247.65 83.82 0) (unit 1)
    (property "Reference" "C99" (at 247.65 86.36 0))
    (property "Value" "C_Review" (at 247.65 81.28 0))
    (uuid "20000000-0000-0000-0000-000000000001")
    (pin "1" (uuid "20000000-0000-0000-0000-000000000002"))
    (pin "2" (uuid "20000000-0000-0000-0000-000000000003"))
  )
""",
        '  (junction (at 242.57 83.82) (diameter 0) (color 0 0 0 0) (uuid "junction-1"))\n',
        """  (sheet (at 250.19 78.74) (size 7.62 10.16)
    (stroke (width 0) (type default))
    (fill (color 0 0 0 0.0000))
    (uuid "30000000-0000-0000-0000-000000000001")
    (property "Sheetname" "Review" (at 250.19 77.95 0) (effects (font (size 1.27 1.27))))
    (property "Sheetfile" "review.kicad_sch" (at 250.19 89.69 0) (effects (font (size 1.27 1.27))))
    (pin "SIG" input (at 242.57 83.82 0) (effects (font (size 1.27 1.27)))
      (uuid "30000000-0000-0000-0000-000000000002")
    )
  )
""",
    ],
)
def test_rejects_implicit_pin_power_and_junction_connections(tmp_path: Path, connection: str) -> None:
    source = fixture(tmp_path)
    base = source.read_text(encoding="utf-8")
    source.write_text(base[: base.rfind(")")] + connection + base[base.rfind(")") :], encoding="utf-8")

    with pytest.raises(RepairRejected, match="(implicitly connected|connected by a junction|sheet pin)"):
        preview_no_connect(
            source,
            metadata(source),
            ref="U1",
            pin="4",
            finding_id=FINDING_ID,
            evidence_ids=(EVIDENCE_ID,),
        )


def test_rejects_malformed_or_trailing_schematic_roots(tmp_path: Path) -> None:
    source = fixture(tmp_path)
    source.write_text(source.read_text(encoding="utf-8") + "\n(extra_root)\n", encoding="utf-8")

    with pytest.raises(RepairRejected, match="trailing root"):
        build_no_connect_metadata(
            source,
            analysis(),
            FINDING,
            EVIDENCE.to_manifest(),
            ref="U1",
            pin="4",
        )


def test_rejects_near_prefix_schematic_root_atom(tmp_path: Path) -> None:
    source = fixture(tmp_path)
    source.write_text(
        source.read_text(encoding="utf-8").replace("(kicad_sch", "(kicad_schematic", 1),
        encoding="utf-8",
    )

    with pytest.raises(RepairRejected, match="one kicad_sch root"):
        build_no_connect_metadata(
            source,
            analysis(),
            FINDING,
            EVIDENCE.to_manifest(),
            ref="U1",
            pin="4",
        )


@pytest.mark.parametrize(
    "placed_symbol",
    [
        '(symbol (lib_id "TLV75518") (at 212.09 101.60 90) (unit 1)',
        '(symbol (lib_id "TLV75518") (at 212.09 101.60 0) (unit 1) (mirror x)',
    ],
)
def test_rejects_rotated_or_mirrored_target_symbol(tmp_path: Path, placed_symbol: str) -> None:
    source = fixture(tmp_path)
    text = source.read_text(encoding="utf-8").replace(
        '(symbol (lib_id "TLV75518") (at 212.09 101.60 0) (unit 1)',
        placed_symbol,
        1,
    )
    source.write_text(text, encoding="utf-8")

    with pytest.raises(RepairRejected, match="(rotated|mirrored) symbols"):
        preview_no_connect(
            source,
            metadata(source),
            ref="U1",
            pin="4",
            finding_id=FINDING_ID,
            evidence_ids=(EVIDENCE_ID,),
        )


def test_audit_failure_rolls_back(tmp_path: Path, monkeypatch):
    source = fixture(tmp_path)
    original = source.read_bytes()
    plan = preview_no_connect(
        source,
        metadata(source),
        ref="U1",
        pin="4",
        finding_id=FINDING_ID,
        evidence_ids=(EVIDENCE_ID,),
    )
    append_event = repair_service._append_audit_event

    def fail_commit(path: Path, event: dict) -> None:
        if event.get("state") == "committed":
            raise OSError("disk")
        append_event(path, event)

    monkeypatch.setattr(repair_service, "_append_audit_event", fail_commit)
    with pytest.raises(OSError):
        apply_no_connect(
            plan,
            metadata(source),
            approved_plan_hash=plan["plan_sha256"],
            reviewer="a",
            finding_id=FINDING_ID,
            evidence_ids=(EVIDENCE_ID,),
        )
    assert source.read_bytes() == original


def test_invalid_existing_audit_log_rejects_and_rolls_back(tmp_path: Path) -> None:
    source = fixture(tmp_path)
    original = source.read_bytes()
    audit = source.parent / ".circuit-weaver" / "repair-audit.jsonl"
    audit.parent.mkdir()
    audit.write_text("partial-record", encoding="utf-8")
    plan = preview_no_connect(
        source,
        metadata(source),
        ref="U1",
        pin="4",
        finding_id=FINDING_ID,
        evidence_ids=(EVIDENCE_ID,),
    )

    with pytest.raises(RepairRejected, match="audit log"):
        apply_no_connect(
            plan,
            metadata(source),
            approved_plan_hash=plan["plan_sha256"],
            reviewer="alice",
            finding_id=FINDING_ID,
            evidence_ids=(EVIDENCE_ID,),
        )

    assert source.read_bytes() == original
    assert audit.read_text(encoding="utf-8") == "partial-record"


def test_audit_path_aliases_are_rejected_before_mutation(tmp_path: Path) -> None:
    source = fixture(tmp_path)
    original = source.read_bytes()
    plan = plan_for(source)

    with pytest.raises(RepairRejected, match="audit path"):
        apply_plan(source, plan, audit_path=source)
    assert source.read_bytes() == original

    hardlink = tmp_path / "audit-hardlink.jsonl"
    os.link(source, hardlink)
    with pytest.raises(RepairRejected, match="(audit path|hardlinks)"):
        apply_plan(source, plan, audit_path=hardlink)
    assert source.read_bytes() == original


def test_source_lock_rejects_a_second_repair_process(tmp_path: Path) -> None:
    source = fixture(tmp_path)
    plan = plan_for(source)

    with _exclusive_file_lock(_source_lock_path(source.resolve()), purpose="test holder"):
        with pytest.raises(RepairRejected, match="locked by another repair process"):
            apply_plan(source, plan)


def test_source_lock_hardlink_is_rejected_without_touching_alias_target(tmp_path: Path) -> None:
    source = fixture(tmp_path)
    plan = plan_for(source)
    unrelated = tmp_path / "unrelated-source-lock-target"
    unrelated.write_bytes(b"")
    os.link(unrelated, _source_lock_path(source.resolve()))

    with pytest.raises(RepairRejected, match="unaliased regular file"):
        apply_plan(source, plan)

    assert unrelated.read_bytes() == b""


def test_audit_lock_hardlink_is_rejected_without_touching_alias_target(tmp_path: Path) -> None:
    source = fixture(tmp_path)
    plan = plan_for(source)
    audit = tmp_path / "audit" / "repair-audit.jsonl"
    audit.parent.mkdir()
    unrelated = tmp_path / "unrelated-audit-lock-target"
    unrelated.write_bytes(b"")
    os.link(unrelated, repair_service._audit_lock_path(audit))

    with pytest.raises(RepairRejected, match="unaliased regular file"):
        apply_plan(source, plan, audit_path=audit)

    assert unrelated.read_bytes() == b""


def test_default_audit_sidecar_reparse_is_rejected(tmp_path: Path) -> None:
    source = fixture(tmp_path / "project")
    original = source.read_bytes()
    plan = plan_for(source)
    outside = tmp_path / "outside"
    outside.mkdir()
    sidecar = source.parent / ".circuit-weaver"
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(sidecar), str(outside)],
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        sidecar.symlink_to(outside, target_is_directory=True)

    with pytest.raises(RepairRejected, match="symlink or reparse point"):
        apply_plan(source, plan)

    assert source.read_bytes() == original
    assert list(outside.iterdir()) == []


def test_edit_in_publication_window_is_detected_and_restored(tmp_path: Path, monkeypatch) -> None:
    source = fixture(tmp_path)
    plan = plan_for(source)
    concurrent = source.read_bytes() + b"\n"

    def race(staged: Path, target: Path) -> None:
        target.write_bytes(concurrent)
        _publish_staged(staged, target)

    monkeypatch.setattr(repair_service, "_publish_staged", race)
    with pytest.raises(RepairRejected, match="during atomic publication"):
        apply_plan(source, plan)
    assert source.read_bytes() == concurrent


def test_edit_after_publication_is_preserved_without_rollback(tmp_path: Path, monkeypatch) -> None:
    source = fixture(tmp_path)
    plan = plan_for(source)
    concurrent: bytes | None = None

    def race(staged: Path, target: Path) -> None:
        nonlocal concurrent
        _publish_staged(staged, target)
        concurrent = target.read_bytes() + b"\n"
        target.write_bytes(concurrent)

    monkeypatch.setattr(repair_service, "_publish_staged", race)
    with pytest.raises(RepairRejected, match="user bytes were preserved"):
        apply_plan(source, plan)
    assert concurrent is not None
    assert source.read_bytes() == concurrent


def test_interrupted_commit_is_recovered_into_audit_on_retry(tmp_path: Path, monkeypatch) -> None:
    source = fixture(tmp_path)
    plan = plan_for(source)
    append_event = repair_service._append_audit_event

    def crash_after_publish(path: Path, event: dict) -> None:
        if event.get("state") == "committed":
            raise SystemExit("simulated process exit")
        append_event(path, event)

    monkeypatch.setattr(repair_service, "_append_audit_event", crash_after_publish)
    with pytest.raises(SystemExit, match="simulated process exit"):
        apply_plan(source, plan)
    assert verify_no_connect(source, plan)

    monkeypatch.setattr(repair_service, "_append_audit_event", append_event)
    assert apply_plan(source, plan)["status"] == "already_applied"
    events = [
        json.loads(line) for line in (source.parent / ".circuit-weaver" / "repair-audit.jsonl").read_text().splitlines()
    ]
    assert [event["state"] for event in events] == ["prepared", "committed"]
    assert events[-1]["event"] == "repair_recovered"


def test_recovery_uses_latest_effective_audit_state(tmp_path: Path, monkeypatch) -> None:
    source = fixture(tmp_path)
    plan = plan_for(source)
    verify = repair_service.verify_no_connect

    monkeypatch.setattr(repair_service, "verify_no_connect", lambda *_args, **_kwargs: False)
    with pytest.raises(RepairRejected, match="post-audit schematic verification failed"):
        apply_plan(source, plan)

    monkeypatch.setattr(repair_service, "verify_no_connect", verify)
    append_event = repair_service._append_audit_event

    def crash_after_second_publish(path: Path, event: dict) -> None:
        if event.get("state") == "committed":
            raise SystemExit("simulated second process exit")
        append_event(path, event)

    monkeypatch.setattr(repair_service, "_append_audit_event", crash_after_second_publish)
    with pytest.raises(SystemExit, match="simulated second process exit"):
        apply_plan(source, plan)
    assert verify_no_connect(source, plan)

    monkeypatch.setattr(repair_service, "_append_audit_event", append_event)
    assert apply_plan(source, plan)["status"] == "already_applied"
    events = [
        json.loads(line) for line in (source.parent / ".circuit-weaver" / "repair-audit.jsonl").read_text().splitlines()
    ]
    assert [event["state"] for event in events] == [
        "prepared",
        "committed",
        "rolled_back",
        "prepared",
        "committed",
    ]
    assert events[-1]["event"] == "repair_recovered"


def test_shared_audit_lock_preserves_concurrent_repair_records(tmp_path: Path) -> None:
    first = fixture(tmp_path / "first")
    second = fixture(tmp_path / "second")
    first_plan = plan_for(first)
    second_plan = plan_for(second)
    shared_audit = tmp_path / "shared" / "repair-audit.jsonl"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(apply_plan, first, first_plan, audit_path=shared_audit),
            executor.submit(apply_plan, second, second_plan, audit_path=shared_audit),
        ]
        assert [future.result()["status"] for future in futures] == ["applied", "applied"]

    events = [json.loads(line) for line in shared_audit.read_text().splitlines()]
    committed = [event for event in events if event["state"] == "committed"]
    assert {event["plan_sha256"] for event in committed} == {
        first_plan["plan_sha256"],
        second_plan["plan_sha256"],
    }


def test_publication_preserves_supported_source_metadata(tmp_path: Path) -> None:
    source = fixture(tmp_path)
    source.chmod(stat.S_IRUSR | stat.S_IWUSR)
    original = source.stat()
    plan = plan_for(source)

    apply_plan(source, plan)

    published = source.stat()
    assert stat.S_IMODE(published.st_mode) == stat.S_IMODE(original.st_mode)
    assert published.st_mtime_ns == original.st_mtime_ns


@pytest.mark.skip_category("platform")
@pytest.mark.skipif(os.name != "nt", reason="Windows security descriptor regression")
def test_windows_security_metadata_is_preserved_for_source_and_audit(tmp_path: Path) -> None:
    source = fixture(tmp_path)
    audit = tmp_path / "audit" / "repair-audit.jsonl"
    audit.parent.mkdir()
    audit.write_bytes(b"")
    for target in (source, audit):
        subprocess.run(
            ["icacls", str(target), "/grant", "*S-1-1-0:(R)"],
            check=True,
            capture_output=True,
            text=True,
        )
    source_security = repair_service._windows_security_descriptor(source)
    audit_security = repair_service._windows_security_descriptor(audit)
    plan = plan_for(source)

    apply_plan(source, plan, audit_path=audit)

    assert repair_service._windows_security_descriptor(source) == source_security
    assert repair_service._windows_security_descriptor(audit) == audit_security


@pytest.mark.skip_category("platform")
@pytest.mark.skipif(os.name != "nt", reason="Windows security descriptor regression")
def test_windows_post_publication_security_read_failure_restores_source(tmp_path: Path, monkeypatch) -> None:
    source = fixture(tmp_path)
    original = source.read_bytes()
    plan = plan_for(source)
    read_security = repair_service._windows_security_descriptor
    source_reads = 0

    def fail_second_source_read(path: Path) -> str:
        nonlocal source_reads
        if Path(path).resolve() == source.resolve():
            source_reads += 1
            if source_reads == 2:
                raise OSError("simulated post-publication security read failure")
        return read_security(path)

    monkeypatch.setattr(repair_service, "_windows_security_descriptor", fail_second_source_read)
    with pytest.raises(OSError, match="post-publication security read failure"):
        apply_plan(source, plan)

    assert source.read_bytes() == original
    assert not verify_no_connect(source, plan)
    assert not list(source.parent.glob("*.replace-backup"))
    assert not list(source.parent.glob("*.rollback-link"))


@pytest.mark.parametrize(
    ("finding_id", "evidence_ids"),
    [
        ("FND-ABCDEF000001", (EVIDENCE_ID,)),
        (FINDING_ID, ("EV-000000000001",)),
        (FINDING_ID, ()),
    ],
)
def test_preview_requires_real_finding_and_evidence_contract_ids(
    tmp_path: Path, finding_id: str, evidence_ids: tuple[str, ...]
) -> None:
    source = fixture(tmp_path)
    with pytest.raises(RepairRejected):
        preview_no_connect(
            source,
            metadata(source),
            ref="U1",
            pin="4",
            finding_id=finding_id,
            evidence_ids=evidence_ids,
        )


def test_existing_marker_is_a_verifiable_idempotent_plan(tmp_path: Path) -> None:
    source = tmp_path / SAMPLE.name
    source.write_bytes(SAMPLE.read_bytes())

    plan = preview_no_connect(
        source,
        metadata(source),
        ref="U1",
        pin="4",
        finding_id=FINDING_ID,
        evidence_ids=(EVIDENCE_ID,),
    )

    assert plan["status"] == "already_applied"
    assert plan["semantic_pre"] == plan["semantic_post"]
    assert verify_no_connect(source, plan)
    result = apply_no_connect(
        plan,
        metadata(source),
        approved_plan_hash=plan["plan_sha256"],
        reviewer="alice",
        finding_id=FINDING_ID,
        evidence_ids=(EVIDENCE_ID,),
    )
    assert result["status"] == "already_applied"


def _run_cli(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    source_root = str(Path(__file__).parents[1] / "src")
    env["PYTHONPATH"] = source_root + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "circuit_weaver", *arguments],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def test_cli_requires_out_of_band_approval_before_mutation(tmp_path: Path) -> None:
    source = fixture(tmp_path)
    original = source.read_bytes()
    metadata_path = tmp_path / "metadata.json"
    plan_path = tmp_path / "repair-plan.json"
    metadata_path.write_text(json.dumps(metadata(source)), encoding="utf-8")

    suggested = _run_cli(
        [
            "repair",
            "suggest",
            str(source),
            str(metadata_path),
            "--ref",
            "U1",
            "--pin",
            "4",
            "--finding-id",
            FINDING_ID,
            "--evidence-id",
            EVIDENCE_ID,
            "--output",
            str(plan_path),
        ]
    )
    assert suggested.returncode == 0, suggested.stderr
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    unapproved = _run_cli(
        [
            "repair",
            "apply",
            str(plan_path),
            str(metadata_path),
            "--reviewer",
            "alice",
            "--finding-id",
            FINDING_ID,
            "--evidence-id",
            EVIDENCE_ID,
        ]
    )
    assert unapproved.returncode != 0
    assert "--approved-plan-hash" in unapproved.stderr
    assert source.read_bytes() == original

    applied = _run_cli(
        [
            "repair",
            "apply",
            str(plan_path),
            str(metadata_path),
            "--approved-plan-hash",
            plan["plan_sha256"],
            "--reviewer",
            "alice",
            "--finding-id",
            FINDING_ID,
            "--evidence-id",
            EVIDENCE_ID,
        ]
    )
    assert applied.returncode == 0, applied.stderr
    verified = _run_cli(["repair", "verify", str(source), str(plan_path)])
    assert verified.returncode == 0, verified.stderr
    assert json.loads(verified.stdout)["verified"] is True


@pytest.mark.parametrize("alias", ["source", "metadata"])
def test_cli_suggest_rejects_output_aliases_before_write(tmp_path: Path, alias: str) -> None:
    source = fixture(tmp_path)
    original = source.read_bytes()
    metadata_path = tmp_path / "metadata.json"
    metadata_bytes = json.dumps(metadata(source)).encode("utf-8")
    metadata_path.write_bytes(metadata_bytes)
    output = source if alias == "source" else metadata_path

    result = _run_cli(
        [
            "repair",
            "suggest",
            str(source),
            str(metadata_path),
            "--ref",
            "U1",
            "--pin",
            "4",
            "--finding-id",
            FINDING_ID,
            "--evidence-id",
            EVIDENCE_ID,
            "--output",
            str(output),
        ]
    )

    assert result.returncode != 0
    assert "cannot alias" in result.stderr
    assert source.read_bytes() == original
    assert metadata_path.read_bytes() == metadata_bytes


def test_cli_output_hardlink_alias_is_rejected(tmp_path: Path) -> None:
    source = fixture(tmp_path)
    original = source.read_bytes()
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps(metadata(source)), encoding="utf-8")
    hardlink = tmp_path / "result.json"
    os.link(source, hardlink)

    result = _run_cli(
        [
            "repair",
            "suggest",
            str(source),
            str(metadata_path),
            "--ref",
            "U1",
            "--pin",
            "4",
            "--finding-id",
            FINDING_ID,
            "--evidence-id",
            EVIDENCE_ID,
            "--output",
            str(hardlink),
        ]
    )

    assert result.returncode != 0
    assert "cannot alias" in result.stderr
    assert source.read_bytes() == original


@pytest.mark.parametrize("alias", ["source", "plan", "metadata", "audit"])
def test_cli_apply_rejects_output_aliases_before_mutation(tmp_path: Path, alias: str) -> None:
    source = fixture(tmp_path)
    original = source.read_bytes()
    plan = plan_for(source)
    plan_path = tmp_path / "plan.json"
    metadata_path = tmp_path / "metadata.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    metadata_path.write_text(json.dumps(metadata(source)), encoding="utf-8")
    aliases = {
        "source": source,
        "plan": plan_path,
        "metadata": metadata_path,
        "audit": source.parent / ".circuit-weaver" / "repair-audit.jsonl",
    }

    result = _run_cli(
        [
            "repair",
            "apply",
            str(plan_path),
            str(metadata_path),
            "--approved-plan-hash",
            plan["plan_sha256"],
            "--reviewer",
            "alice",
            "--finding-id",
            FINDING_ID,
            "--evidence-id",
            EVIDENCE_ID,
            "--output",
            str(aliases[alias]),
        ]
    )

    assert result.returncode != 0
    assert "cannot alias" in result.stderr
    assert source.read_bytes() == original
    assert not (source.parent / ".circuit-weaver" / "repair-audit.jsonl").exists()


@pytest.mark.parametrize("alias", ["source", "plan"])
def test_cli_verify_rejects_output_aliases(tmp_path: Path, alias: str) -> None:
    source = fixture(tmp_path)
    original = source.read_bytes()
    plan_path = tmp_path / "plan.json"
    plan_bytes = json.dumps(plan_for(source)).encode("utf-8")
    plan_path.write_bytes(plan_bytes)
    output = source if alias == "source" else plan_path

    result = _run_cli(["repair", "verify", str(source), str(plan_path), "--output", str(output)])

    assert result.returncode != 0
    assert "cannot alias" in result.stderr
    assert source.read_bytes() == original
    assert plan_path.read_bytes() == plan_bytes
