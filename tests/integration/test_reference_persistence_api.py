"""HTTP tests for reference report persistence and export (#29)."""

from __future__ import annotations

import dataclasses
import json
import time
from pathlib import Path

import pytest
from docentric_copilot.api.app import create_app
from docentric_copilot.config import get_settings
from fastapi.testclient import TestClient

from tests.reference_fixtures import (
    ControlSpec,
    ElementSpec,
    build_docx,
    build_project_data,
    project_data_parts,
)


def _docx(*, extra: bool = False) -> bytes:
    elements = [ElementSpec(1, "Field", "MainData", "@Number")]
    controls = [ControlSpec(alias="Field", tag="Field", sdt_id=1)]
    if extra:
        elements.append(ElementSpec(2, "Field", "MainData", "@NetAmount"))
        controls.append(ControlSpec(alias="Field", tag="Field", sdt_id=2))
    custom = project_data_parts(build_project_data(tuple(elements)))
    return build_docx(document_controls=tuple(controls), custom_parts=custom)


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "Synthetic.Report.docx").write_bytes(_docx())
    (root / "Synthetic.Right.docx").write_bytes(_docx(extra=True))
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


def _persist(client: TestClient, *, name: str = "Synthetic.Report.docx", kind: str = "inspection"):
    return client.post(
        "/api/v1/reference/reports",
        params={"kind": kind},
        files={"file": (name, _docx(), "application/octet-stream")},
    )


def test_persist_get_and_export_round_trip(client: TestClient) -> None:
    persisted = _persist(client)
    assert persisted.status_code == 200, persisted.text
    envelope = persisted.json()
    report_id = envelope["id"]
    assert report_id.startswith("ref_")
    assert envelope["kind"] == "inspection"
    assert envelope["runtime_compatibility"] == "not_tested"
    assert envelope["report"] is not None
    assert envelope["graph"] is not None
    assert envelope["report"]["runtime_compatibility"] == "not_tested"
    assert envelope["expires_at"] > envelope["created_at"]

    reopened = client.get(f"/api/v1/reference/reports/{report_id}")
    assert reopened.status_code == 200, reopened.text
    payload = reopened.json()
    assert payload["id"] == report_id
    assert payload["report"]["report_digest"] == envelope["report"]["report_digest"]
    assert payload["graph"]["graph_digest"] == envelope["graph"]["graph_digest"]

    exported_json = client.get(
        f"/api/v1/reference/reports/{report_id}/export", params={"format": "json"}
    )
    assert exported_json.status_code == 200
    assert exported_json.headers["content-type"].startswith("application/json")
    assert "attachment" in exported_json.headers["content-disposition"]
    exported = json.loads(exported_json.text)
    assert exported["id"] == report_id
    assert exported["report"]["reference_version"] == "1.0"
    assert exported["runtime_compatibility"] == "not_tested"

    exported_html = client.get(
        f"/api/v1/reference/reports/{report_id}/export", params={"format": "html"}
    )
    assert exported_html.status_code == 200
    assert exported_html.headers["content-type"].startswith("text/html")
    assert report_id in exported_html.text
    assert "not_tested" in exported_html.text
    assert "<script" not in exported_html.text.lower()


def test_html_export_escapes_untrusted_names(client: TestClient) -> None:
    persisted = _persist(client, name="Synthetic <script>alert(1)</script>.docx")
    assert persisted.status_code == 200, persisted.text
    report_id = persisted.json()["id"]
    exported = client.get(
        f"/api/v1/reference/reports/{report_id}/export", params={"format": "html"}
    )
    assert exported.status_code == 200
    assert "<script>alert(1)</script>" not in exported.text
    assert "&gt;" in exported.text
    assert "<script" not in exported.text.lower()


def test_html_renderer_escapes_every_untrusted_field() -> None:
    from docentric_copilot.reference import (
        ReferenceReportKind,
        StoredReferenceReport,
        render_stored_report_html,
    )

    envelope = StoredReferenceReport(
        id="ref_test",
        kind=ReferenceReportKind.GRAPH,
        schema_version="1.0",
        created_at=1.0,
        expires_at=2.0,
        source_name="<script>alert(1)</script>",
        warnings=["<img src=x onerror=alert(1)>"],
    )
    rendered = render_stored_report_html(envelope)
    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "<img src=x" not in rendered
    assert "&lt;img src=x" in rendered


def test_graph_and_diff_persist_kinds(client: TestClient, corpus: Path) -> None:
    graph_only = _persist(client, kind="graph")
    assert graph_only.status_code == 200, graph_only.text
    assert graph_only.json()["report"] is None
    assert graph_only.json()["graph"] is not None

    diff = client.post(
        "/api/v1/reference/reports",
        params={
            "kind": "diff",
            "left_path": "Synthetic.Report.docx",
            "right_path": "Synthetic.Right.docx",
        },
    )
    assert diff.status_code == 200, diff.text
    payload = diff.json()
    assert payload["kind"] == "diff"
    assert payload["diff"] is not None
    assert payload["diff"]["runtime_compatibility"] == "not_tested"
    assert payload["report"] is None and payload["graph"] is None
    assert payload["source_name"].startswith("Synthetic.Report.docx")


def test_missing_expired_and_invalid_requests(client: TestClient) -> None:
    missing = client.get("/api/v1/reference/reports/ref_missing")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "reference_report_not_found"

    persisted = _persist(client)
    report_id = persisted.json()["id"]
    store = client.app.state.store
    store.purge_expired(now=time.time() + 10_000)
    expired = client.get(f"/api/v1/reference/reports/{report_id}")
    assert expired.status_code == 404
    assert expired.json()["error"]["code"] == "reference_report_not_found"

    bad_format = client.get(
        f"/api/v1/reference/reports/{report_id}/export", params={"format": "pdf"}
    )
    assert bad_format.status_code == 422

    none = client.post("/api/v1/reference/reports")
    assert none.status_code == 400
    assert none.json()["error"]["code"] == "input_invalid"


def test_persist_diff_requires_two_sources(client: TestClient) -> None:
    response = client.post(
        "/api/v1/reference/reports",
        params={"kind": "diff"},
        files={"left": ("Synthetic.Report.docx", _docx(), "application/octet-stream")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "input_invalid"


def test_persist_does_not_write_template_bytes(client: TestClient, tmp_path: Path) -> None:
    persisted = _persist(client)
    assert persisted.status_code == 200
    data_dir = tmp_path / "api-data"
    for path in data_dir.rglob("*"):
        if path.is_file() and path.name != "copilot.db":
            assert path.suffix not in {".docx", ".axpp", ".zip"}
