"""Responsive viewport coverage for the Reference Inspector (V012-10).

Desktop, tablet and narrow widths are checked for horizontal overflow, visible
primary actions and all four reference tabs. The narrow fixture is 390 px; if a
future change cannot support it, the documented minimum must be raised and this
test updated — the status cannot silently become "responsive supported".
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.reference_fixtures import (
    ControlSpec,
    ElementSpec,
    build_docx,
    build_embedded_project_data,
    project_data_parts,
)

from .conftest import wait_for_saved_report

pytestmark = pytest.mark.e2e


@pytest.fixture
def responsive_docx(tmp_path: Path) -> Path:
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
    payload = build_docx(
        document_controls=controls,
        custom_parts=project_data_parts(build_embedded_project_data(elements), item_index=1),
    )
    path = tmp_path / "responsive-reference.docx"
    path.write_bytes(payload)
    return path


def _overflow(page: Page) -> dict[str, int]:
    return page.evaluate(
        """() => ({
            documentWidth: document.documentElement.scrollWidth,
            bodyWidth: document.body.scrollWidth,
            viewportWidth: window.innerWidth,
        })"""
    )


def _assert_no_overflow(page: Page, label: str) -> None:
    metrics = _overflow(page)
    assert metrics["documentWidth"] <= metrics["viewportWidth"] + 1, (label, metrics)
    assert metrics["bodyWidth"] <= metrics["viewportWidth"] + 1, (label, metrics)


@pytest.mark.parametrize(
    ("label", "width", "height"),
    (("desktop", 1280, 900), ("tablet", 768, 1024), ("narrow", 390, 844)),
)
def test_reference_inspector_at_each_viewport(
    page: Page,
    base_url: str,
    responsive_docx: Path,
    label: str,
    width: int,
    height: int,
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{base_url}/reference", wait_until="domcontentloaded")
    expect(page.get_by_role("heading", name="Reference template inspector")).to_be_visible()
    expect(page.get_by_test_id("reference-inspect-button")).to_be_visible()
    _assert_no_overflow(page, f"{label}-initial")

    page.get_by_test_id("reference-template-file-input").set_input_files(str(responsive_docx))
    page.get_by_test_id("reference-inspect-button").click()
    report_id = wait_for_saved_report(page)
    assert report_id
    expect(page.get_by_test_id("reference-saved-report")).to_be_visible()
    expect(page.get_by_test_id("reference-export-button")).to_be_visible()
    _assert_no_overflow(page, f"{label}-overview")

    page.get_by_test_id("reference-tab-controls").click()
    expect(page.get_by_text("OrderNumber", exact=True).first).to_be_visible()
    _assert_no_overflow(page, f"{label}-controls")

    page.get_by_test_id("reference-tab-graph").click()
    expect(page.get_by_text("Unresolved", exact=True).first).to_be_visible()
    _assert_no_overflow(page, f"{label}-graph")

    page.get_by_test_id("reference-tab-diff").click()
    expect(page.get_by_text("Compare two references", exact=False).first).to_be_visible()
    expect(page.get_by_test_id("reference-diff-compare")).to_be_visible()
    _assert_no_overflow(page, f"{label}-diff")

    expect(page.get_by_text("Reference inspection failed", exact=False)).to_have_count(0)
