#!/usr/bin/env python3
"""Capture the demo v4 Auto-routing scene from a live web workspace.

The script is opt-in: without ``--live`` it stops after selecting Auto and takes
only the free "Auto selected" screenshot.  With ``--live`` it presses Plan once,
waits for the real routing decision, saves the API response and captures the
result.  At most one live model call is made per invocation.

Usage::

    PLAYWRIGHT_BROWSERS_PATH=.tools/pw-browsers .venv/bin/python \
        scripts/capture_auto_scene_v4.py --live
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".tools" / "pw-browsers"))
sys.path.insert(0, str(ROOT))

from playwright.sync_api import Page, sync_playwright  # noqa: E402

ASSETS = ROOT / "docs" / "assets"
MEDIA = ROOT / "docs" / "media"
WORK = ROOT / ".tools" / "v4" / "capture"
WORK.mkdir(parents=True, exist_ok=True)

URL = "http://127.0.0.1:3000"
VIEWPORT = {"width": 1600, "height": 1000}
PLAN_TIMEOUT_MS = 4 * 60 * 1000

_SECRET_PATTERN = re.compile(
    r"(?i)(api[-_]?key|authorization|bearer|x-goog-api-key|openai_api_key|"
    r"anthropic_api_key|gemini_api_key|google_api_key)\s*[=:]\s*\S+"
)
_SECRET_VALUE_PATTERN = re.compile(r"\b(sk-[A-Za-z0-9_\-]{8,}|AIza[0-9A-Za-z_\-]{20,})\b")


def dismiss_toast(page: Page) -> None:
    button = page.get_by_role("button", name="Dismiss notification")
    if button.count():
        button.first.click()
        page.wait_for_timeout(250)


def save_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def scrub(value: Any) -> Any:
    """Drop secret-looking keys and redact secret-looking values."""
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            if re.search(r"(?i)(api[-_]?key|authorization|secret|password)", str(key)):
                continue
            clean[key] = scrub(item)
        return clean
    if isinstance(value, list):
        return [scrub(item) for item in value]
    if isinstance(value, str):
        return _SECRET_VALUE_PATTERN.sub("[redacted]", _SECRET_PATTERN.sub("[redacted]", value))
    return value


def scan_for_secrets(data: Any) -> list[str]:
    blob = json.dumps(data)
    findings: list[str] = []
    for pattern in (_SECRET_PATTERN, _SECRET_VALUE_PATTERN):
        findings.extend(match.group(0)[:6] + "…" for match in pattern.finditer(blob))
    return findings


def run_demo(page: Page) -> None:
    page.goto(URL, wait_until="networkidle")
    page.get_by_role("button", name="Run demo", exact=False).click()
    page.get_by_role("button", name="Skip tour").wait_for(timeout=30_000)
    page.get_by_role("button", name="Skip tour").click()
    page.wait_for_timeout(800)
    # The demo hydrates a plan; wait until the prompt text is the recorded brief
    # and the source exists (Auto is enabled only with a source).
    page.wait_for_function(
        "() => document.querySelector('#prompt-input')?.value?.length > 200",
        timeout=30_000,
    )
    page.wait_for_timeout(500)
    dismiss_toast(page)


def select_auto(page: Page) -> None:
    page.locator('label[for$="-auto"]').click()
    page.wait_for_function(
        "() => document.querySelector('input[type=radio][value=auto]')?.checked === true",
        timeout=10_000,
    )
    page.wait_for_timeout(600)
    dismiss_toast(page)


def capture_selected(page: Page) -> None:
    # Keep the prompt panel and the routing control centred in the viewport.
    page.locator("#prompt-panel").scroll_into_view_if_needed()
    page.wait_for_timeout(700)
    dismiss_toast(page)
    page.screenshot(path=str(ASSETS / "auto-mode-selected.png"), full_page=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="press Plan once (costs a live call)")
    parser.add_argument(
        "--result-only",
        action="store_true",
        help="write a result JSON that already exists (no browser); for debugging only",
    )
    args = parser.parse_args()

    if args.result_only:
        raise SystemExit("nothing to do")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--force-color-profile=srgb"])
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=1)
        page.set_default_timeout(30_000)
        run_demo(page)
        select_auto(page)
        capture_selected(page)
        print("wrote docs/assets/auto-mode-selected.png")

        if not args.live:
            page.screenshot(path=str(WORK / "auto-selected-full.png"), full_page=True)
            browser.close()
            return 0

        requests: list[str] = []
        page.on(
            "request",
            lambda request: (
                requests.append(request.url)
                if request.method == "POST" and "/templates/plan" in request.url
                else None
            ),
        )
        started = time.monotonic()
        with page.expect_response(
            lambda response: (
                response.request.method == "POST" and "/templates/plan" in response.url
            ),
            timeout=PLAN_TIMEOUT_MS,
        ) as response_info:
            page.get_by_role("button", name="Plan template").click()
        response = response_info.value
        elapsed = time.monotonic() - started
        print(f"plan response: HTTP {response.status} in {elapsed:.1f}s ({response.url})")

        page.get_by_role("heading", name="Routing decision").wait_for(timeout=60_000)
        page.wait_for_timeout(900)
        dismiss_toast(page)

        payload = response.json()
        findings = scan_for_secrets(payload)
        if findings:
            raise SystemExit(f"secret-like strings found in plan response: {findings}")
        save_json(MEDIA / "auto-plan-response.json", scrub(payload))
        save_json(WORK / "plan-response.raw.json", payload)
        print("wrote docs/media/auto-plan-response.json")

        routing = payload.get("routing") or {}
        decision = routing.get("decision") or {}
        summary = {
            "http_status": response.status,
            "elapsed_seconds": round(elapsed, 2),
            "run_id": routing.get("run_id"),
            "complexity": decision.get("complexity"),
            "recommended_provider": decision.get("provider"),
            "recommended_model": decision.get("model"),
            "actual_provider": routing.get("actual_provider"),
            "actual_model": routing.get("actual_model"),
            "match": routing.get("match"),
            "fallback": routing.get("fallback"),
            "fallback_used": decision.get("fallback_used"),
            "requires_review": decision.get("requires_review"),
            "usage": routing.get("usage"),
            "plan_keys": sorted(payload.keys()),
        }
        save_json(WORK / "capture-summary.json", summary)
        print(json.dumps(summary, indent=2))

        card = page.locator("section:has(#routing-decision-title)").last
        card.scroll_into_view_if_needed()
        page.wait_for_timeout(600)
        dismiss_toast(page)
        page.screenshot(path=str(ASSETS / "auto-routing-result.png"), full_page=False)
        print("wrote docs/assets/auto-routing-result.png")

        # Extra, higher-resolution card capture used only for the video insert.
        card.screenshot(path=str(WORK / "auto-routing-card-2x.png"))
        page.screenshot(path=str(WORK / "auto-result-full.png"), full_page=True)
        browser.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
