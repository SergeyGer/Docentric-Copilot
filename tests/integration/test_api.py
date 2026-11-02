"""End-to-end HTTP API tests (upload → plan → validate → compile → download)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from docentric_copilot.api.app import create_app
from docentric_copilot.config import get_settings
from fastapi.testclient import TestClient

from tests.conftest import EXAMPLES

PROMPT = (EXAMPLES / "quotation" / "prompt.txt").read_text(encoding="utf-8")


@pytest.fixture
def client(tmp_path: Path):
    settings = dataclasses.replace(get_settings(), data_dir=tmp_path / "api-data")
    application = create_app(settings)
    with TestClient(application) as test_client:
        yield test_client


@pytest.fixture
def source(client: TestClient) -> dict:
    payload = (EXAMPLES / "quotation" / "sales-quotation.ddsp").read_bytes()
    response = client.post(
        "/api/v1/sources",
        files={"file": ("sales-quotation.ddsp", payload, "application/octet-stream")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_health_and_root(client: TestClient) -> None:
    assert client.get("/api/v1/health").json()["status"] == "ok"
    assert client.get("/").json()["docentric_ax_compatibility"] == "not_tested"


def test_openapi_is_available(client: TestClient) -> None:
    document = client.get("/openapi.json").json()
    assert "/api/v1/templates/plan" in document["paths"]
    assert "/api/v1/templates/compile" in document["paths"]


def test_providers_endpoint(client: TestClient) -> None:
    providers = client.get("/api/v1/providers").json()
    names = {entry["name"] for entry in providers}
    assert {"mock", "openai", "anthropic", "gemini"} <= names
    assert all("api_key" not in entry for entry in providers)


def test_capabilities_are_honest(client: TestClient) -> None:
    payload = client.get("/api/v1/capabilities").json()
    assert payload["features"]["docentric_ax_adapter"] is False
    assert payload["features"]["verified_compatibility"] is False
    ax = next(item for item in payload["compilers"] if item["target"] == "docentric-ax")
    assert ax["available"] is False and ax["verified"] is False


def test_upload_and_schema(client: TestClient, source: dict) -> None:
    assert source["schema_id"] == "sales_quotation"
    assert source["sections"] == ["MainData", "GeneralData", "Parameters"]
    schema = client.get(f"/api/v1/sources/{source['source_id']}/schema").json()
    assert schema["normalized_schema"]["schema_id"] == "sales_quotation"
    assert schema["stats"]["node_count"] > 20


def test_upload_rejects_unknown_extension(client: TestClient) -> None:
    response = client.post(
        "/api/v1/sources", files={"file": ("payload.exe", b"MZ....", "application/octet-stream")}
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "input_unsupported"


def test_upload_rejects_hostile_xml(client: TestClient) -> None:
    payload = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e "boom">]><MainData>&e;</MainData>'
    response = client.post(
        "/api/v1/sources", files={"file": ("evil.xml", payload, "application/xml")}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "XML001"


def test_unknown_source_returns_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/sources/src_00000000000000000000/schema")
    assert response.status_code == 404
    payload = response.json()
    assert payload["error"]["code"] == "not_found"


def test_report_validation_error_shape(client: TestClient) -> None:
    response = client.post("/api/v1/templates/plan", json={"source_id": "src_x"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "input_invalid"


def test_full_flow(client: TestClient, source: dict) -> None:
    source_id = source["source_id"]
    plan = client.post(
        "/api/v1/templates/plan",
        json={"source_id": source_id, "prompt": PROMPT, "provider": "mock"},
    )
    assert plan.status_code == 200, plan.text
    plan_body = plan.json()
    assert plan_body["validation"]["docentric_compatibility"] == "not_tested"
    assert plan_body["validation"]["semantic"] == "passed"
    artifact_kinds = {artifact["kind"] for artifact in plan_body["artifacts"]}
    assert {"ir", "mapping", "validation", "validation_html", "preview"} <= artifact_kinds

    job = client.get(f"/api/v1/jobs/{plan_body['job_id']}").json()
    assert job["status"] == "completed"

    validate = client.post(
        "/api/v1/templates/validate",
        json={"source_id": source_id, "template_id": plan_body["template_id"]},
    )
    assert validate.status_code == 200
    assert validate.json()["overall"] == "passed_unverified_compatibility"

    # One requirement is genuinely ambiguous (customer vs company VAT); a reviewer
    # confirms it before compilation is allowed.
    pending = [item for item in plan_body["mapping"]["mappings"] if item["status"] != "confirmed"]
    version = plan_body["version"]
    for item in pending:
        target = item.get("selected_field_path") or item["candidate_field_paths"][0]
        confirmed = client.post(
            f"/api/v1/templates/{plan_body['template_id']}/versions/{version}/mappings/{item['requirement_id']}/confirm",
            json={"selected_field_path": target, "note": "Confirmed in the integration test."},
        )
        assert confirmed.status_code == 200, confirmed.text
        version = confirmed.json()["version"]

    compile_response = client.post(
        "/api/v1/templates/compile",
        json={
            "source_id": source_id,
            "template_id": plan_body["template_id"],
            "version": version,
            "options": {"document_name": "quotation.docx"},
        },
    )
    assert compile_response.status_code == 200, compile_response.text
    compiled = compile_response.json()
    assert compiled["validation"]["structural"] == "passed"

    download = client.get(f"/api/v1/artifacts/{compiled['artifact_id']}")
    assert download.status_code == 200
    assert download.content.startswith(b"PK")
    assert download.headers["x-artifact-digest"]
    assert "attachment" in download.headers["content-disposition"]

    preview = client.post(
        "/api/v1/templates/preview",
        json={"source_id": source_id, "template_id": plan_body["template_id"]},
    )
    assert preview.status_code == 200
    assert "Example Customer GmbH" in preview.text
    assert "not verified" in preview.text


def test_revision_flow(client: TestClient, source: dict) -> None:
    source_id = source["source_id"]
    plan = client.post(
        "/api/v1/templates/plan",
        json={"source_id": source_id, "prompt": PROMPT, "provider": "mock"},
    ).json()
    revision = client.post(
        "/api/v1/templates/revise",
        json={
            "source_id": source_id,
            "template_id": plan["template_id"],
            "instruction": "Move the bank details to the footer and make the table compact.",
        },
    )
    assert revision.status_code == 200, revision.text
    body = revision.json()
    assert body["version"] == plan["version"] + 1
    assert "counts" in body["change_summary"]

    versions = client.get(f"/api/v1/templates/{plan['template_id']}/versions").json()
    assert [item["version"] for item in versions["versions"]] == [1, 2]

    export = client.get(f"/api/v1/templates/{plan['template_id']}/export/1").json()
    assert export["ir_digest"]


def test_compile_rejects_ax_target(client: TestClient, source: dict) -> None:
    source_id = source["source_id"]
    plan = client.post(
        "/api/v1/templates/plan",
        json={"source_id": source_id, "prompt": PROMPT, "provider": "mock"},
    ).json()
    for item in [m for m in plan["mapping"]["mappings"] if m["status"] != "confirmed"]:
        target = item.get("selected_field_path") or item["candidate_field_paths"][0]
        plan = client.post(
            f"/api/v1/templates/{plan['template_id']}/versions/{plan['version']}/mappings/{item['requirement_id']}/confirm",
            json={"selected_field_path": target},
        ).json()
    response = client.post(
        "/api/v1/templates/compile",
        json={
            "source_id": source_id,
            "template_id": plan["template_id"],
            "target": "docentric-ax",
        },
    )
    assert response.status_code == 409
    payload = response.json()["error"]
    assert payload["code"] == "target_unsupported"
    assert "gate" in payload["details"]


def test_artifact_view_is_sandboxed(client: TestClient, source: dict) -> None:
    source_id = source["source_id"]
    plan = client.post(
        "/api/v1/templates/plan",
        json={"source_id": source_id, "prompt": PROMPT, "provider": "mock"},
    ).json()
    preview_artifact = next(item for item in plan["artifacts"] if item["kind"] == "preview")
    response = client.get(f"/api/v1/artifacts/{preview_artifact['id']}/view")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_missing_artifact(client: TestClient) -> None:
    response = client.get("/api/v1/artifacts/art_00000000000000000000")
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "artifact_unavailable"


def test_plan_with_unknown_provider(client: TestClient, source: dict) -> None:
    response = client.post(
        "/api/v1/templates/plan",
        json={"source_id": source["source_id"], "prompt": PROMPT, "provider": "openai"},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_not_configured"


def test_quality_optimize_and_compare_link(client: TestClient) -> None:
    demo = client.post("/api/v1/demo/sessions", json={"case_id": "quotation-defect"}).json()
    assert demo["quality"]["overall"] == "warning"
    reference = {
        "source_id": demo["source_id"],
        "template_id": demo["template_id"],
        "version": demo["version"],
    }
    quality = client.post("/api/v1/templates/quality", json=reference).json()
    layout = next(c for c in quality["report"]["checks"] if c["id"] == "table_layout")
    assert layout["status"] == "warning"
    optimised = client.post("/api/v1/templates/optimize", json=reference)
    assert optimised.status_code == 200, optimised.text
    assert optimised.json()["after"]["overall"] != "warning"
    compare = client.post(
        "/api/v1/templates/compare",
        json={
            "source_id": demo["source_id"],
            "prompt": demo["case"]["prompt"],
            "targets": [{"provider": "mock"}, {"provider": "mock"}],
        },
    )
    assert compare.status_code == 200
    assert all(run["ok"] for run in compare.json()["runs"])
    assert compare.json()["recommended"] == "mock"
