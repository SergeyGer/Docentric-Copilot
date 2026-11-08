#!/usr/bin/env python3
"""T-08: verify the deployed Streamlit demo with Playwright.

Requires network access and the pinned Chromium. This is an explicit,
manually-invoked smoke test; it is not part of CI. It wakes a sleeping app,
runs the three release scenarios, downloads each DOCX, saves screenshots and
records version/commit/metadata and DOCX hashes.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "media" / "v013-demo"
URL = "https://docentric-copilot-bqpx8652tmmliwk9c2d5rq.streamlit.app"
SCENARIOS = (
    ("quotation", "Sales quotation"),
    ("invoice", "Tax invoice"),
    ("purchase-order", "Purchase order"),
)


def _app_frame(page: Page):
    page.wait_for_timeout(15000)
    for frame in page.frames:
        if frame.url.endswith("/~/+/"):
            return frame
    return None


def _select(frame, title: str) -> None:
    frame.locator('[data-testid="stSelectbox"]').first.click()
    frame.page.wait_for_timeout(800)
    frame.get_by_role("option", name=title).click()
    frame.page.wait_for_timeout(5000)


def run() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    metadata = ""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 1200}, accept_downloads=True)
        page.goto(URL, wait_until="domcontentloaded", timeout=90000)
        # A sleeping app exposes a wake button; click it if present.
        with contextlib.suppress(Exception):
            page.get_by_text("Yes, get this app back up!").click(timeout=5000)
        frame = _app_frame(page)
        if frame is None:
            raise SystemExit("deployed app iframe did not load")
        body_text = frame.locator("body").inner_text()
        metadata_lines = []
        capture = False
        for line in body_text.splitlines():
            if line.startswith("Application:"):
                capture = True
            if capture:
                metadata_lines.append(line)
                if line.startswith("Compatibility:"):
                    break
        metadata = "\n".join(metadata_lines)
        for case_id, title in SCENARIOS:
            _select(frame, title)
            frame.get_by_role("tab", name="2 · Mapping review").click()
            page.wait_for_timeout(2000)
            confirms = frame.get_by_role("button", name="Confirm this binding").count()
            if confirms:
                frame.get_by_role("button", name="Confirm this binding").first.click()
                page.wait_for_timeout(5000)
            frame.get_by_role("tab", name="3 · Preview & DOCX").click()
            page.wait_for_timeout(3000)
            available = frame.get_by_role("button", name="Download DOCX").count()
            docx = OUT / f"deployed-{case_id}.docx"
            size = sha = None
            if available:
                with page.expect_download(timeout=30000) as download:
                    frame.get_by_role("button", name="Download DOCX").first.click()
                download.value.save_as(docx)
                data = docx.read_bytes()
                size = len(data)
                sha = hashlib.sha256(data).hexdigest()
            page.screenshot(path=str(OUT / f"deployed-{case_id}.png"))
            results.append(
                {
                    "case_id": case_id,
                    "title": title,
                    "download_available": bool(available),
                    "confirmations_visible": confirms,
                    "docx_size_bytes": size,
                    "docx_sha256": sha,
                    "screenshot": f"media/v013-demo/deployed-{case_id}.png",
                }
            )
        browser.close()
    commit = re.search(r"Git Commit: ([0-9a-f]+)", metadata)
    version = re.search(r"Application: v([0-9.]+)", metadata)
    return {
        "schema": "deployed-demo-smoke/v1",
        "verified_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "url": URL,
        "application_version": version.group(1) if version else None,
        "git_commit": commit.group(1) if commit else None,
        "metadata_panel": metadata,
        "scenarios": results,
        "note": (
            "Deployed Streamlit build may be ahead of the release tag; the recorded "
            "commit is the actual demo build. DOCX hashes are compared with the local "
            "deterministic smoke output."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    data = run()
    if args.write:
        (OUT / "manifest.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
