"""HTTP tests for ``POST /api/v1/reference/import-ir`` (#27)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from docentric_copilot.api.app import create_app
from docentric_copilot.config import get_settings
from fastapi.testclient import TestClient

from tests.reference_fixtures import (
    ControlSpec,
    ElementSpec,
    build_docx,
    build_embedded_project_data,
    project_data_parts,
)


def _docx(elements: tuple[ElementSpec, ...], *, unknown_control: bool = False) -> bytes:
    project_data = build_embedded_project_data(elements)
    custom = project_data_parts(project_data, item_index=1)
    controls = [
        ControlSpec(alias=element.element_type, tag=element.element_type, sdt_id=element.element_id)
        for element in elements
    ]
    if unknown_control:
        controls.append(ControlSpec(alias="Plain", tag="plain", sdt_id=999))
    return build_docx(document_controls=tuple(controls), custom_parts=custom)


def _supported() -> bytes:
    return _docx(
        (
            ElementSpec(1, "Field", "MainData", "@Number", "System.String"),
            ElementSpec(2, "List", "MainData", "Lines/Line", None, child_ids=(3,)),
            ElementSpec(3, "Field", ".", "@ItemId", "System.String"),
        )
    )


def _mixed() -> bytes:
    return _docx(
        (
            ElementSpec(1, "Field", "MainData", "@Number", "System.String"),
            ElementSpec(2, "Barcode", "MainData", "@Number", "System.String"),
            ElementSpec(3, "Field", "MainData", "@Missing", "System.String"),
        ),
        unknown_control=True,
    )


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "Supported.docx").write_bytes(_supported())
    (root / "Mixed.docx").write_bytes(_mixed())
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


def _upload(client: TestClient, payload: bytes, name: str, **params):
    return client.post(
        "/api/v1/reference/import-ir",
        params=params,
        files={"file": (name, payload, "application/octet-stream")},
    )


def test_supported_reference_projects_generic_ir(client: TestClient) -> None:
    response = _upload(client, _supported(), "Supported.docx")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["import_version"] == "1.0"
    assert payload["runtime_compatibility"] == "not_tested"
    assert payload["target"] == "generic-docx"
    assert payload["ir"]["target"] == "generic-docx"
    assert payload["ir"]["kind"] == "document"
    assert payload["skipped"] == []
    assert payload["validation"]["can_compile"] is True
    assert payload["validation"]["statuses"]["docentric_compatibility"] == "not_tested"
    assert payload["summary"]["imported"] >= 2
    assert payload["provenance"]
    text = response.text
    assert "docentric-ax" not in text
    assert "runtime_compatible" not in text


def test_strict_import_rejects_unsupported_and_ambiguous(client: TestClient) -> None:
    response = _upload(client, _mixed(), "Mixed.docx")
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "reference_import_blocked"
    assert error["details"]["skipped_total"] >= 3
    codes = {item["code"] for item in error["details"]["skipped"]}
    assert {"UNSUPPORTED_ELEMENT_KIND", "UNKNOWN_PATH", "UNKNOWN_ELEMENT"} <= codes


def test_allow_unsupported_imports_subset_and_lists_skips(client: TestClient) -> None:
    response = _upload(client, _mixed(), "Mixed.docx", allow_unsupported="true")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["allow_unsupported"] is True
    assert payload["runtime_compatibility"] == "not_tested"
    assert payload["ir"]["target"] == "generic-docx"
    assert payload["summary"]["imported"] >= 1
    assert payload["skipped"]
    codes = {item["code"] for item in payload["skipped"]}
    assert {"UNSUPPORTED_ELEMENT_KIND", "UNKNOWN_PATH", "UNKNOWN_ELEMENT"} <= codes
    assert payload["summary"]["by_skip_code"]
    assert all(item["reason"] for item in payload["skipped"])
    assert payload["validation"]["can_compile"] is True


def test_corpus_path_is_supported(client: TestClient, corpus: Path) -> None:
    response = client.post(
        "/api/v1/reference/import-ir",
        params={"path": "Supported.docx"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["source_name"] == "Supported.docx"


def test_input_validation(client: TestClient) -> None:
    missing = client.post("/api/v1/reference/import-ir")
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "input_invalid"

    both = client.post(
        "/api/v1/reference/import-ir",
        params={"path": "Supported.docx"},
        files={"file": ("Supported.docx", _supported(), "application/octet-stream")},
    )
    assert both.status_code == 400
    assert both.json()["error"]["code"] == "input_invalid"

    unsupported = _upload(client, b"MZ", "payload.exe")
    assert unsupported.status_code == 415
    assert unsupported.json()["error"]["code"] == "input_unsupported"
