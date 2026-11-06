"""Proves that a failing E2E test leaves a screenshot and a Playwright trace.

The test is skipped in the normal suite. CI runs it with
``DC_E2E_ARTIFACT_PROBE=1`` and then asserts that the artifacts exist.
"""

from __future__ import annotations

import os

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


@pytest.mark.skipif(
    os.environ.get("DC_E2E_ARTIFACT_PROBE") != "1",
    reason="set DC_E2E_ARTIFACT_PROBE=1 to run the intentional artifact probe",
)
def test_failure_captures_screenshot_and_trace(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/reference", wait_until="domcontentloaded")
    expect(page.get_by_role("heading", name="Reference template inspector")).to_be_visible()
    assert False, "intentional E2E failure: the conftest must save failure.png and trace.zip"
