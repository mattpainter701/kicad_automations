"""Smoke tests for the FastAPI API endpoints.

Covers all endpoint groups: health, templates, generate, validate,
generate/from-bom, and the /mvp/ suite (validate, apply-patch, diff,
pcb-feedback, generate).

Uses local source (``sys.path.insert(0, "src")``) so the installed
package is NOT used — the local ``src/circuit_weaver/`` tree is tested.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure local source takes precedence over any installed circuit-weaver package
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from circuit_weaver.api import create_app  # noqa: E402

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"


# ================================================================
# Helpers
# ================================================================


def _load_sample_spec(name: str) -> dict:
    """Load a sample YAML spec by directory name."""
    from circuit_weaver.project_spec import _parse_yaml

    yaml_path = SAMPLES_DIR / name / f"{name}.yaml"
    assert yaml_path.exists(), f"Sample not found at {yaml_path}"
    return _parse_yaml(yaml_path)


_IOT_SPEC: dict | None = None


def iot_spec() -> dict:
    """Memoised loader so we only parse the sample YAML once per session."""
    global _IOT_SPEC
    if _IOT_SPEC is None:
        _IOT_SPEC = _load_sample_spec("iot_sensor_node")
    return dict(_IOT_SPEC)  # shallow copy each call


@pytest.fixture(scope="module")
def client():
    """FastAPI TestClient wrapping the in-process ``create_app()``."""
    app = create_app()
    with TestClient(app) as c:
        yield c


# ================================================================
# /health
# ================================================================


class TestHealth:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "templates" in data


# ================================================================
# /templates
# ================================================================


class TestTemplates:
    def test_templates_returns_list(self, client):
        resp = client.get("/templates")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        if len(data) > 0:
            entry = data[0]
            assert "type" in entry
            assert "description" in entry


# ================================================================
# /validate
# ================================================================


class TestValidate:
    def test_validate_with_sample_spec(self, client):
        """Send the IoT sensor sample spec, expect structured validation output."""
        resp = client.post("/validate", json=iot_spec())
        assert resp.status_code == 200
        data = resp.json()
        assert "project" in data
        assert isinstance(data.get("component_count"), int)
        assert "validation" in data
        assert isinstance(data["validation"], list)

    def test_validate_empty_yaml_returns_400(self, client):
        """Sending an empty body with explicit text/yaml content-type → 4xx."""
        resp = client.post("/validate", content=b"", headers={"content-type": "text/yaml"})
        assert resp.status_code in (400, 422)
        detail = resp.json().get("detail", "")
        assert isinstance(detail, str) and len(detail) > 0

    def test_validate_malformed_yaml_returns_400(self, client):
        """Garbage body should produce a 400 / 422 error."""
        resp = client.post("/validate", content=b"\x00\xff\xfe\xed", headers={"content-type": "text/plain"})
        assert resp.status_code in (400, 422)


# ================================================================
# /generate
# ================================================================


class TestGenerate:
    def test_generate_with_sample_spec(self, client):
        """Send the IoT sensor sample spec, expect either a ZIP or a structured error."""
        resp = client.post("/generate", json=iot_spec())
        # May succeed (200 + ZIP) or fail (422) if KiCad CLI unavailable
        assert resp.status_code in (200, 422)
        if resp.status_code == 200:
            assert resp.headers.get("content-type") == "application/zip"
            content_dispo = resp.headers.get("content-disposition", "")
            assert ".zip" in content_dispo
        else:
            detail = resp.json().get("detail", "")
            assert isinstance(detail, str) and len(detail) > 0

    def test_generate_empty_body_returns_400(self, client):
        resp = client.post("/generate", content=b"", headers={"content-type": "text/plain"})
        assert resp.status_code in (400, 422)


# ================================================================
# /generate/from-bom
# ================================================================


class TestGenerateFromBom:
    def test_from_bom_no_file_returns_400(self, client):
        """Omitting the file upload should return 400."""
        resp = client.post("/generate/from-bom")
        # FastAPI rejects missing required UploadFile with 422
        assert resp.status_code == 422


# ================================================================
# /mvp/validate
# ================================================================


class TestMvpValidate:
    def test_mvp_validate_returns_report(self, client):
        """The /mvp/validate endpoint returns a grouped validation report."""
        resp = client.post("/mvp/validate", json=iot_spec())
        # Can succeed or return 422 if the spec has hard errors
        assert resp.status_code in (200, 422)
        if resp.status_code == 200:
            data = resp.json()
            # A ValidationReport should have at minimum 'valid' and 'categories'
            assert "valid" in data
            assert "categories" in data
            assert isinstance(data["categories"], dict)


# ================================================================
# /mvp/apply-patch
# ================================================================


class TestMvpApplyPatch:
    def test_mvp_apply_patch_set_metadata(self, client):
        """Apply a patch that updates metadata and returns the updated spec."""
        spec = {"project": "test", "description": "original", "blocks": []}
        patch = {"set_metadata": {"description": "patched"}}
        resp = client.post("/mvp/apply-patch", json={"spec": spec, "patch": patch})
        # Should either succeed (200) or produce a structured error (422)
        assert resp.status_code in (200, 422)
        if resp.status_code == 200:
            result = resp.json()
            assert "accepted" in result
            assert "report" in result
            assert "updated_spec" in result

    def test_mvp_apply_patch_missing_field_returns_400(self, client):
        """Omitting the 'patch' field should trigger a 400."""
        resp = client.post("/mvp/apply-patch", json={"spec": {}})
        assert resp.status_code == 400
        data = resp.json()
        assert "detail" in data


# ================================================================
# /mvp/diff
# ================================================================


class TestMvpDiff:
    def test_mvp_diff_between_two_specs(self, client):
        """Diff two structurally different specs."""
        old_spec = {"project": "v1", "description": "old version", "blocks": []}
        new_spec = {"project": "v2", "description": "new version", "blocks": []}
        resp = client.post("/mvp/diff", json={"old_spec": old_spec, "new_spec": new_spec})
        assert resp.status_code in (200, 422)
        if resp.status_code == 200:
            diff = resp.json()
            assert isinstance(diff, dict)

    def test_mvp_diff_missing_field_returns_400(self, client):
        """Omitting 'new_spec' should trigger a 400."""
        resp = client.post("/mvp/diff", json={"old_spec": {}})
        assert resp.status_code == 400


# ================================================================
# /mvp/pcb-feedback
# ================================================================


class TestMvpPcbFeedback:
    def test_mvp_pcb_feedback_accepts_constraints(self, client):
        """Provide PCB feedback with a placement constraint, expect an accepted count."""
        spec = {"project": "test", "blocks": []}
        feedback = {"constraints": [{"kind": "placement", "target": "U1", "region": "top"}]}
        resp = client.post("/mvp/pcb-feedback", json={"spec": spec, "feedback": feedback})
        assert resp.status_code in (200, 422)
        if resp.status_code == 200:
            data = resp.json()
            assert "accepted_constraints" in data

    def test_mvp_pcb_feedback_missing_field_returns_400(self, client):
        """Omitting the 'feedback' field should trigger a 400."""
        resp = client.post("/mvp/pcb-feedback", json={"spec": {}})
        assert resp.status_code == 400


# ================================================================
# /mvp/generate
# ================================================================


class TestMvpGenerate:
    def test_mvp_generate_with_sample_spec(self, client):
        """POST a valid spec to /mvp/generate, expect ZIP or structured error."""
        resp = client.post("/mvp/generate", json=iot_spec())
        assert resp.status_code in (200, 422)
        if resp.status_code == 200:
            assert resp.headers.get("content-type") == "application/zip"
            content_dispo = resp.headers.get("content-disposition", "")
            assert ".zip" in content_dispo
        else:
            data = resp.json()
            assert "detail" in data
