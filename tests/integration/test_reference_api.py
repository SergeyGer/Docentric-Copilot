"""HTTP tests for the read-only reference inspection endpoint."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from docentric_copilot.api.app import create_app
from docentric_copilot.config import get_settings
from fastapi.testclient import TestClient

from tests.reference_fixtures import (
    ControlSpec,
    ElementSpec,
    build_ddsp,
    build_docx,
    build_project_data,
    project_data_parts,
)


def _docx(*, macro: bool = False) -> bytes:
    elements = (
        ElementSpec(2330169809, "Field", "MainData", "@Number"),
        ElementSpec(999, "Field", "MainData", "@Number"),
    )
    controls = (
        ControlSpec(alias="Field", tag="Field", sdt_id=-1964797487, text="@Number"),
        ControlSpec(alias="Field", tag="Field", sdt_id=999, text="@Number"),
        ControlSpec(alias="Plain", tag="plain", sdt_id=777, text="unknown"),
    )
    custom = project_data_parts(build_project_data(elements))
    if macro:
        custom["word/vbaProject.bin"] = b"macro-bytes"
    return build_docx(document_controls=controls, custom_parts=custom)


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "Synthetic.Report.docx").write_bytes(_docx())
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
        "/api/v1/reference/inspect",
        files={
            "file": (
                name,
                payload,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )


def test_upload_returns_report_and_never_claims_runtime(client: TestClient) -> None:
    response = _upload(client, _docx())
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["reference_version"] == "1.0"
    assert payload["runtime_compatibility"] == "not_tested"
    assert payload["source_type"] == "docx"
    assert payload["source_name"] == "Synthetic.Report.docx"
    assert payload["counts"]["controls_total"] == 3
    assert payload["counts"]["distinct_docx"] == 1
    assert len(payload["documents"]) == 1
    assert payload["documents"][0]["control_count"] == 3


def test_upload_with_ddsp_validates_paths(client: TestClient) -> None:
    response = client.post(
        "/api/v1/reference/inspect",
        files={
            "file": ("Synthetic.Report.docx", _docx(), "application/octet-stream"),
            "ddsp": ("Synthetic.Report.ddsp", build_ddsp(), "application/xml"),
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    document = payload["documents"][0]
    assert document["schema_source"] == "ddsp"
    assert document["schema_sections"] == ["GeneralData", "MainData"]
    assert payload["counts"]["resolved"] >= 1


def test_corpus_path_inside_allowed_root(client: TestClient, corpus: Path) -> None:
    response = client.post(
        "/api/v1/reference/inspect",
        params={"path": str(corpus / "Synthetic.Report.docx")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["source_name"] == "Synthetic.Report.docx"
    response = client.post(
        "/api/v1/reference/inspect",
        params={"path": "Synthetic.Report.docx"},
    )
    assert response.status_code == 200, response.text


def test_corpus_path_outside_allowed_root_is_rejected(
    client: TestClient, tmp_path: Path, corpus: Path
) -> None:
    outside = tmp_path / "outside.docx"
    outside.write_bytes(_docx())
    response = client.post(
        "/api/v1/reference/inspect",
        params={"path": str(outside)},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "reference_path_forbidden"

    traversal = client.post(
        "/api/v1/reference/inspect",
        params={"path": "../outside.docx"},
    )
    assert traversal.status_code == 400
    assert traversal.json()["error"]["code"] == "reference_path_forbidden"
    assert corpus.exists()


def test_missing_corpus_path_returns_not_found(client: TestClient) -> None:
    response = client.post(
        "/api/v1/reference/inspect",
        params={"path": "does-not-exist.docx"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "reference_path_not_found"


def test_requires_exactly_one_source(client: TestClient, corpus: Path) -> None:
    missing = client.post("/api/v1/reference/inspect")
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "input_invalid"

    both = client.post(
        "/api/v1/reference/inspect",
        params={"path": "Synthetic.Report.docx"},
        files={"file": ("Synthetic.Report.docx", _docx(), "application/octet-stream")},
    )
    assert both.status_code == 400
    assert both.json()["error"]["code"] == "input_invalid"


def test_rejects_unsupported_extension(client: TestClient) -> None:
    response = client.post(
        "/api/v1/reference/inspect",
        files={"file": ("payload.exe", b"MZ....", "application/octet-stream")},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "input_unsupported"


def test_rejects_ddsp_without_file(client: TestClient) -> None:
    response = client.post(
        "/api/v1/reference/inspect",
        params={"path": "Synthetic.Report.docx"},
        files={"ddsp": ("schema.ddsp", build_ddsp(), "application/xml")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "input_invalid"


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
        response = _upload(test_client, _docx())
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "reference_input_too_large"


def test_macros_are_flagged_and_not_executed(client: TestClient) -> None:
    response = _upload(client, _docx(macro=True))
    assert response.status_code == 200, response.text
    document = response.json()["documents"][0]
    assert document["has_macros"] is True


def test_response_contains_no_absolute_paths(client: TestClient, corpus: Path) -> None:
    response = client.post(
        "/api/v1/reference/inspect",
        params={"path": str(corpus / "Synthetic.Report.docx")},
    )
    assert response.status_code == 200, response.text
    serialized = json.dumps(response.json())
    assert str(corpus) not in serialized
    assert "/root/" not in serialized
    assert "/home/" not in serialized


def test_capabilities_advertise_the_read_only_inspector(client: TestClient) -> None:
    payload = client.get("/api/v1/capabilities").json()
    assert payload["features"]["reference_inspector"] is True
    ax = next(item for item in payload["compilers"] if item["target"] == "docentric-ax")
    assert ax["available"] is False and ax["verified"] is False
