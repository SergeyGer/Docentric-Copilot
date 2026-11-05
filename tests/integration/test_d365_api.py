"""HTTP tests for ``POST /api/v1/reference/d365`` (PR-02/PR-03)."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from docentric_copilot.api.app import create_app
from docentric_copilot.config import get_settings
from fastapi.testclient import TestClient

from tests.reference_fixtures import (
    ElementSpec,
    build_ddsp,
    build_docx,
    build_embedded_docx,
    build_project_data,
    build_zip,
    project_data_parts,
)


def _embedded() -> bytes:
    return build_embedded_docx(
        (
            ElementSpec(1, "Field", "MainData", "@Number", "System.String"),
            ElementSpec(2, "List", "MainData", "Lines/Line", None, child_ids=(3,)),
            ElementSpec(3, "Field", ".", "@ItemId", "System.String"),
        )
    )


def _no_schema() -> bytes:
    elements = (ElementSpec(1, "Field", "MainData", "@Number", "System.String"),)
    return build_docx(custom_parts=project_data_parts(build_project_data(elements)))


def _corrupted() -> bytes:
    return build_docx(
        custom_parts={
            "customXml/item1.xml": (
                b'<ProjectData xmlns="http://Docentric.org/ProjectData.xml"><DataSources>'
            )
        }
    )


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "Synthetic.Report.docx").write_bytes(_embedded())
    (root / "NoSchema.docx").write_bytes(_no_schema())
    return root


@pytest.fixture
def client(tmp_path: Path, corpus: Path):
    settings = dataclasses.replace(
        get_settings(),
        data_dir=tmp_path / "api-data",
        reference_corpus_roots=(corpus,),
    )
    application = create_app(settings)
    with TestClient(application) as test_client:
        yield test_client


def _upload(client: TestClient, payload: bytes, name: str = "Synthetic.Report.docx"):
    return client.post(
        "/api/v1/reference/d365",
        files={"file": (name, payload, "application/octet-stream")},
    )


def test_upload_returns_the_binding_contract(client: TestClient) -> None:
    response = _upload(client, _embedded())
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["platform"] == "D365FO"
    assert payload["schema_source"] == "projectdata"
    assert payload["runtime_compatibility"] == "not_tested"
    assert payload["schema_evidence"]
    assert payload["counts"]["total"] == 3
    assert payload["counts"]["resolved"] == 3
    assert payload["counts"]["resolved_with_evidence"] == 3
    assert payload["counts"]["ambiguous"] == 0
    assert payload["schema_summary"]["fields"] > 0
    statuses = {item["status"] for item in payload["binding_results"]}
    assert statuses == {"resolved"}
    for item in payload["binding_results"]:
        assert item["source_id"]
        assert item["evidence"]


def test_corpus_path_inside_allowed_root(client: TestClient, corpus: Path) -> None:
    absolute = client.post(
        "/api/v1/reference/d365",
        params={"path": str(corpus / "Synthetic.Report.docx")},
    )
    assert absolute.status_code == 200, absolute.text
    relative = client.post(
        "/api/v1/reference/d365",
        params={"path": "Synthetic.Report.docx"},
    )
    assert relative.status_code == 200, relative.text
    assert relative.json()["counts"]["resolved"] == 3


def test_corpus_path_outside_allowed_root_is_rejected(
    client: TestClient, tmp_path: Path, corpus: Path
) -> None:
    outside = tmp_path / "outside.docx"
    outside.write_bytes(_embedded())
    response = client.post(
        "/api/v1/reference/d365",
        params={"path": str(outside)},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "reference_path_forbidden"

    traversal = client.post(
        "/api/v1/reference/d365",
        params={"path": "../outside.docx"},
    )
    assert traversal.status_code == 400
    assert traversal.json()["error"]["code"] == "reference_path_forbidden"


def test_missing_corpus_path_returns_not_found(client: TestClient) -> None:
    response = client.post(
        "/api/v1/reference/d365",
        params={"path": "does-not-exist.docx"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "reference_path_not_found"


def test_requires_exactly_one_source(client: TestClient) -> None:
    missing = client.post("/api/v1/reference/d365")
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "input_invalid"

    both = client.post(
        "/api/v1/reference/d365",
        params={"path": "Synthetic.Report.docx"},
        files={"file": ("Synthetic.Report.docx", _embedded(), "application/octet-stream")},
    )
    assert both.status_code == 400
    assert both.json()["error"]["code"] == "input_invalid"


def test_rejects_unsupported_extension(client: TestClient) -> None:
    response = _upload(client, b"MZ-not-a-template", name="payload.exe")
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "input_unsupported"


def test_rejects_ddsp_without_file(client: TestClient) -> None:
    response = client.post(
        "/api/v1/reference/d365",
        params={"path": "Synthetic.Report.docx"},
        files={"ddsp": ("schema.ddsp", build_ddsp(), "application/xml")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "input_invalid"


def test_ddsp_upload_is_used_when_embedded_schema_is_absent(client: TestClient) -> None:
    response = client.post(
        "/api/v1/reference/d365",
        files={
            "file": ("NoSchema.docx", _no_schema(), "application/octet-stream"),
            "ddsp": ("Synthetic.ddsp", build_ddsp(), "application/xml"),
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema_source"] == "ddsp"
    assert payload["counts"]["resolved"] == 1
    assert payload["binding_results"][0]["evidence"].startswith("Synthetic.ddsp#")


def test_corrupted_project_data_is_reported_not_raised(client: TestClient) -> None:
    response = _upload(client, _corrupted(), name="Corrupted.docx")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema_source"] == "unavailable"
    assert payload["counts"]["total"] == 0
    assert payload["runtime_compatibility"] == "not_tested"
    assert any(item["code"] == "custom_xml_unreadable" for item in payload["diagnostics"])


def test_multiple_documents_in_one_package_are_rejected(client: TestClient) -> None:
    package = build_zip({"A.docx": _embedded(), "B.docx": _embedded()})
    response = _upload(client, package, name="Package.axpp")
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "reference_d365_multiple_documents"


def test_upload_size_limit_is_enforced(tmp_path: Path) -> None:
    settings = get_settings()
    limited = dataclasses.replace(
        settings,
        data_dir=tmp_path / "api-data",
        reference_corpus_roots=(tmp_path,),
        limits=dataclasses.replace(settings.limits, max_ddsp_bytes=64),
    )
    application = create_app(limited)
    with TestClient(application) as test_client:
        response = _upload(test_client, _embedded())
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "reference_input_too_large"


def test_response_contains_no_absolute_paths(client: TestClient, corpus: Path) -> None:
    response = client.post(
        "/api/v1/reference/d365",
        params={"path": str(corpus / "Synthetic.Report.docx")},
    )
    assert response.status_code == 200, response.text
    serialized = json.dumps(response.json())
    assert str(corpus) not in serialized
    assert "/root/" not in serialized
    assert "/home/" not in serialized


def test_capabilities_advertise_d365_bindings(client: TestClient) -> None:
    payload = client.get("/api/v1/capabilities").json()
    assert payload["features"]["reference_d365_bindings"] is True
    assert payload["features"]["reference_inspector"] is True
    assert payload["features"]["verified_compatibility"] is False
