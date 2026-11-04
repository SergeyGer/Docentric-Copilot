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


def _graph_upload(client: TestClient, payload: bytes, *, with_ddsp: bool = True):
    files = {
        "file": (
            "Synthetic.Report.docx",
            payload,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }
    if with_ddsp:
        files["ddsp"] = ("Synthetic.Report.ddsp", build_ddsp(), "application/xml")
    return client.post("/api/v1/reference/graph", files=files)


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


def test_graph_upload_returns_a_read_only_graph(client: TestClient) -> None:
    response = _graph_upload(client, _docx())
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["graph_version"] == "1.0"
    assert payload["reference_version"] == "1.0"
    assert payload["runtime_compatibility"] == "not_tested"
    assert payload["ir_kind"] == "reference"
    assert payload["compilable"] is False
    assert payload["summary"]["controls_total"] == 3
    assert payload["summary"]["controls_resolved"] >= 1
    assert payload["summary"]["controls_unknown"] >= 1
    assert payload["schema_source"] == "ddsp"
    assert {edge["type"] for edge in payload["edges"]} >= {"bound_to", "resolves_to"}
    assert all(edge["status"] in {"resolved", "ambiguous", "unknown"} for edge in payload["edges"])
    assert payload["graph_digest"] != "0" * 64


def test_graph_path_inside_allowed_root(client: TestClient, corpus: Path) -> None:
    response = client.post(
        "/api/v1/reference/graph",
        params={"path": "Synthetic.Report.docx"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["source_name"] == "Synthetic.Report.docx"
    assert payload["summary"]["controls_total"] == 3


def test_graph_path_outside_allowed_root_is_rejected(client: TestClient, tmp_path: Path) -> None:
    outside = tmp_path / "outside.docx"
    outside.write_bytes(_docx())
    response = client.post(
        "/api/v1/reference/graph",
        params={"path": str(outside)},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "reference_path_forbidden"


def test_graph_requires_exactly_one_source(client: TestClient) -> None:
    missing = client.post("/api/v1/reference/graph")
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "input_invalid"
    both = client.post(
        "/api/v1/reference/graph",
        params={"path": "Synthetic.Report.docx"},
        files={"file": ("Synthetic.Report.docx", _docx(), "application/octet-stream")},
    )
    assert both.status_code == 400
    assert both.json()["error"]["code"] == "input_invalid"


def test_graph_never_returns_absolute_paths(client: TestClient, corpus: Path) -> None:
    response = client.post(
        "/api/v1/reference/graph",
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
    assert payload["features"]["reference_graph"] is True
    ax = next(item for item in payload["compilers"] if item["target"] == "docentric-ax")
    assert ax["available"] is False and ax["verified"] is False


def _diff_docx(*, extra: bool = False, number_path: str = "@Number") -> bytes:
    elements = [ElementSpec(2330169809, "Field", "MainData", number_path)]
    controls = [ControlSpec(alias="Field", tag="Field", sdt_id=-1964797487, text=number_path)]
    if extra:
        elements.append(ElementSpec(42, "Field", "MainData", "@Number"))
        controls.append(ControlSpec(alias="Field", tag="Field", sdt_id=42, text="@Number"))
    custom = project_data_parts(build_project_data(tuple(elements)))
    return build_docx(document_controls=tuple(controls), custom_parts=custom)


def test_diff_upload_reports_structural_and_semantic_changes(client: TestClient) -> None:
    response = client.post(
        "/api/v1/reference/diff",
        files={
            "left": ("Synthetic.Left.docx", _diff_docx(), "application/octet-stream"),
            "right": (
                "Synthetic.Right.docx",
                _diff_docx(extra=True, number_path="@NetAmount"),
                "application/octet-stream",
            ),
            "ddsp": ("Synthetic.ddsp", build_ddsp(), "application/xml"),
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["diff_version"] == "1.0"
    assert payload["reference_version"] == "1.0"
    assert payload["runtime_compatibility"] == "not_tested"
    assert payload["compilable"] is False
    assert payload["summary"]["added"] >= 1
    assert payload["summary"]["changed"] >= 1
    assert payload["structural"]["total"] == payload["summary"]["structural"]
    assert payload["semantic"]["total"] == payload["summary"]["semantic"]
    assert payload["coverage_delta"]["edge_delta"] is not None
    assert isinstance(payload["unresolved_delta"], int)
    assert payload["summary"]["status_transitions"]
    assert any(
        item["kind"] == "control"
        and item["change"] == "added"
        and item["dimension"] == "structural"
        for item in payload["items"]
    )
    assert any(
        item["change"] == "changed" and item["dimension"] == "semantic" for item in payload["items"]
    )
    serialized = json.dumps(payload)
    assert "/root/" not in serialized
    assert "/home/" not in serialized


def test_diff_corpus_paths_inside_allowed_root(client: TestClient, corpus: Path) -> None:
    left = corpus / "Synthetic.Left.docx"
    right = corpus / "Synthetic.Right.docx"
    left.write_bytes(_diff_docx())
    right.write_bytes(_diff_docx(extra=True))
    response = client.post(
        "/api/v1/reference/diff",
        params={
            "left_path": str(left),
            "right_path": str(right),
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["left"]["source_name"] == "Synthetic.Left.docx"
    assert response.json()["right"]["source_name"] == "Synthetic.Right.docx"


def test_diff_requires_exactly_two_sources(client: TestClient) -> None:
    none = client.post("/api/v1/reference/diff")
    assert none.status_code == 400
    assert none.json()["error"]["code"] == "input_invalid"

    one = client.post(
        "/api/v1/reference/diff",
        files={"left": ("Synthetic.Left.docx", _diff_docx(), "application/octet-stream")},
    )
    assert one.status_code == 400
    assert one.json()["error"]["code"] == "input_invalid"

    mixed = client.post(
        "/api/v1/reference/diff",
        params={"left_path": "Synthetic.Report.docx"},
        files={"right": ("Synthetic.Right.docx", _diff_docx(), "application/octet-stream")},
    )
    assert mixed.status_code == 400
    assert mixed.json()["error"]["code"] == "input_invalid"


def test_diff_path_outside_allowed_root_is_rejected(
    client: TestClient, tmp_path: Path, corpus: Path
) -> None:
    outside = tmp_path / "outside.docx"
    outside.write_bytes(_diff_docx())
    left = corpus / "Synthetic.Left.docx"
    left.write_bytes(_diff_docx())
    response = client.post(
        "/api/v1/reference/diff",
        params={"left_path": str(left), "right_path": str(outside)},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "reference_path_forbidden"


def test_diff_rejects_ddsp_with_corpus_paths(client: TestClient, corpus: Path) -> None:
    left = corpus / "Synthetic.Left.docx"
    right = corpus / "Synthetic.Right.docx"
    left.write_bytes(_diff_docx())
    right.write_bytes(_diff_docx(extra=True))
    response = client.post(
        "/api/v1/reference/diff",
        params={"left_path": str(left), "right_path": str(right)},
        files={"ddsp": ("Synthetic.ddsp", build_ddsp(), "application/xml")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "input_invalid"


def test_diff_rejects_unsupported_extension(client: TestClient) -> None:
    response = client.post(
        "/api/v1/reference/diff",
        files={
            "left": ("left.exe", b"MZ....", "application/octet-stream"),
            "right": ("right.docx", _diff_docx(), "application/octet-stream"),
        },
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "input_unsupported"
