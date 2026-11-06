"""Reference Inspector browser E2E (V012-08).

Happy path: open /reference → upload a synthetic DOCX → inspect and save →
Overview / Controls / Graph / Diff → reload → reopen by id → export JSON and
HTML.

Negative paths: invalid archive, oversized upload, unknown report id and a
simulated report-store failure. Unsupported material must stay visible instead
of crashing the page.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.reference_fixtures import (
    ControlSpec,
    ElementSpec,
    build_docx,
    build_embedded_project_data,
    build_project_data,
    project_data_parts,
)

from .conftest import wait_for_saved_report

pytestmark = pytest.mark.e2e


def _goto_reference(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/reference", wait_until="domcontentloaded")
    expect(page.get_by_role("heading", name="Reference template inspector")).to_be_visible()


def _upload_reference(page: Page, path: Path) -> None:
    page.get_by_test_id("reference-template-file-input").set_input_files(str(path))


def _inspect(page: Page) -> str:
    page.get_by_test_id("reference-inspect-button").click()
    return wait_for_saved_report(page)


def _assert_no_error_alert(page: Page) -> None:
    expect(page.get_by_text("Reference inspection failed", exact=False)).to_have_count(0)


@pytest.fixture
def synthetic_docx(tmp_path: Path) -> Path:
    elements = (
        ElementSpec(1, "Field", "MainData", "@Number", "System.String"),
        ElementSpec(2, "List", "MainData", "Lines/Line", None, child_ids=(3,)),
        ElementSpec(3, "Field", ".", "@ItemId", "System.String"),
    )
    controls = (
        ControlSpec(alias="OrderNumber", tag="OrderNumber", sdt_id=1, text="T-1"),
        ControlSpec(alias="LineList", tag="LineList", sdt_id=2, text="lines"),
        ControlSpec(alias="LineItem", tag="LineItem", sdt_id=3, text="A"),
    )
    project_data = build_embedded_project_data(elements)
    payload = build_docx(
        document_controls=controls,
        header_controls=(ControlSpec(alias="HeaderField", tag="HeaderField", sdt_id=4),),
        custom_parts=project_data_parts(project_data, item_index=1),
    )
    path = tmp_path / "synthetic-reference.docx"
    path.write_bytes(payload)
    return path


@pytest.fixture
def invalid_docx(tmp_path: Path) -> Path:
    path = tmp_path / "broken.docx"
    path.write_bytes(b"this is not a zip archive")
    return path


@pytest.fixture
def oversized_docx(tmp_path: Path) -> Path:
    path = tmp_path / "large.docx"
    path.write_bytes(b"PK\x03\x04" + b"x" * 70_000)
    return path


@pytest.fixture
def unsupported_docx(tmp_path: Path) -> Path:
    controls = (
        ControlSpec(
            alias="Barcode",
            tag="Barcode",
            sdt_id=42,
            control_type="picture",
            text="unsupported",
        ),
    )
    project_data = build_project_data(
        elements=(ElementSpec(42, "Barcode", "MainData", "@Code", "System.String"),),
        data_sources=("MainData",),
    )
    payload = build_docx(
        document_controls=controls,
        custom_parts=project_data_parts(project_data, item_index=3),
    )
    path = tmp_path / "unsupported.docx"
    path.write_bytes(payload)
    return path


def test_reference_happy_path_upload_save_reload_and_export(
    page: Page, base_url: str, synthetic_docx: Path, page_errors: list[str]
) -> None:
    _goto_reference(page, base_url)
    _upload_reference(page, synthetic_docx)
    expect(page.get_by_text("synthetic-reference.docx", exact=True)).to_be_visible()

    report_id = _inspect(page)
    assert report_id
    assert f"id={report_id}" in page.url

    # Overview: the report is rendered and the limitation is visible.
    expect(page.get_by_text("Resolved control coverage")).to_be_visible()
    expect(
        page.get_by_text("Docentric AX runtime compatibility: not tested", exact=True)
    ).to_be_visible()
    _assert_no_error_alert(page)

    # Controls tab shows the controls from the uploaded template.
    page.get_by_test_id("reference-tab-controls").click()
    expect(page.get_by_text("OrderNumber", exact=True).first).to_be_visible()

    # Graph tab renders a graph summary without an error.
    page.get_by_test_id("reference-tab-graph").click()
    expect(page.get_by_text("Unresolved", exact=True).first).to_be_visible()
    expect(page.get_by_text("Edge coverage", exact=False).first).to_be_visible()
    _assert_no_error_alert(page)

    # Diff tab: compare the same document with itself, a deterministic no-change diff.
    page.get_by_test_id("reference-tab-diff").click()
    page.get_by_test_id("reference-diff-left-input").set_input_files(str(synthetic_docx))
    page.get_by_test_id("reference-diff-right-input").set_input_files(str(synthetic_docx))
    page.get_by_test_id("reference-diff-compare").click()
    expect(page.get_by_text("Read-only ReferenceDiff", exact=False).first).to_be_visible(
        timeout=60_000
    )
    _assert_no_error_alert(page)

    # Reload and reopen the saved report by id.
    page.get_by_test_id("reference-tab-overview").click()
    page.reload(wait_until="domcontentloaded")
    reopened = wait_for_saved_report(page)
    assert reopened == report_id
    expect(page.get_by_text("Resolved control coverage")).to_be_visible()

    # JSON export.
    page.get_by_test_id("reference-export-format").select_option("json")
    with page.expect_download() as download_info:
        page.get_by_test_id("reference-export-button").click()
    download = download_info.value
    assert download.path() is not None
    payload = json.loads(Path(download.path()).read_text(encoding="utf-8"))
    assert payload["id"] == report_id
    assert payload["kind"] == "inspection"
    assert payload["runtime_compatibility"] == "not_tested"
    assert payload["report"]["counts"]["controls_total"] >= 1

    # HTML export.
    page.get_by_test_id("reference-export-format").select_option("html")
    with page.expect_download() as html_info:
        page.get_by_test_id("reference-export-button").click()
    html = Path(html_info.value.path()).read_text(encoding="utf-8")
    assert html.lstrip().lower().startswith("<!doctype html>")
    assert report_id in html
    assert "not_tested" in html

    assert page_errors == []


def test_invalid_docx_shows_a_clear_error(page: Page, base_url: str, invalid_docx: Path) -> None:
    _goto_reference(page, base_url)
    _upload_reference(page, invalid_docx)
    page.get_by_test_id("reference-inspect-button").click()
    alert = page.get_by_role("alert").first
    expect(alert).to_be_visible(timeout=30_000)
    assert "failed" in alert.inner_text().lower()
    expect(page.get_by_test_id("reference-saved-report")).to_have_count(0)


def test_oversized_upload_is_rejected_before_the_api(
    page: Page, base_url: str, oversized_docx: Path
) -> None:
    _goto_reference(page, base_url)
    expect(page.get_by_text(re.compile("Maximum upload size", re.IGNORECASE)).first).to_be_visible()
    _upload_reference(page, oversized_docx)
    page.get_by_test_id("reference-inspect-button").click()
    alert = page.get_by_role("alert").first
    expect(alert).to_be_visible()
    assert "larger than" in alert.inner_text().lower()
    expect(page.get_by_test_id("reference-saved-report")).to_have_count(0)


def test_unknown_report_id_is_reported_and_cleared(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/reference?id=missing-report-000", wait_until="domcontentloaded")
    expect(page.get_by_text("Reference inspection failed", exact=False)).to_be_visible(
        timeout=30_000
    )
    expect(page.get_by_text("Reference report not found", exact=True)).to_be_visible()
    assert "id=missing-report-000" not in page.url
    expect(page.get_by_role("heading", name="Reference template inspector")).to_be_visible()


def test_report_store_failure_is_shown_without_a_saved_report(
    page: Page, base_url: str, synthetic_docx: Path
) -> None:
    page.route(
        re.compile(r".*/api/v1/reference/reports\?kind=inspection$"),
        lambda route: route.fulfill(
            status=500,
            content_type="application/json",
            body=json.dumps(
                {
                    "error": {
                        "code": "storage_unavailable",
                        "message": "The report store is unavailable",
                        "details": {},
                    }
                }
            ),
        ),
    )
    _goto_reference(page, base_url)
    _upload_reference(page, synthetic_docx)
    page.get_by_test_id("reference-inspect-button").click()
    alert = page.get_by_role("alert").first
    expect(alert).to_be_visible(timeout=30_000)
    assert "report store is unavailable" in alert.inner_text().lower()
    expect(page.get_by_test_id("reference-saved-report")).to_have_count(0)


def test_unsupported_construct_is_kept_visible(
    page: Page, base_url: str, unsupported_docx: Path
) -> None:
    _goto_reference(page, base_url)
    _upload_reference(page, unsupported_docx)
    report_id = _inspect(page)
    assert report_id
    _assert_no_error_alert(page)
    page.get_by_test_id("reference-tab-controls").click()
    expect(page.get_by_role("cell", name="Barcode", exact=True)).to_be_visible()
