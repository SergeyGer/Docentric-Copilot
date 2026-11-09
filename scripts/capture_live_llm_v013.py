#!/usr/bin/env python3
"""Capture one new live Auto plan from the real web workspace.

Opt-in and paid: it presses Plan once with routing=auto. The result is a short
screen recording, a scrubbed response, and a summary with the real model/run id.
It does not overwrite the demo-v4 assets.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".tools" / "pw-browsers"))
sys.path.insert(0, str(ROOT))
import imageio_ffmpeg  # type: ignore[import-untyped]  # noqa: E402
import scripts.capture_auto_scene_v4 as capture  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

OUT = ROOT / "docs" / "media" / "live-v013"
WORK = ROOT / ".tools" / "live-v013"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
FFPROBE = (
    ROOT
    / ".tools"
    / "ffprobe-tool"
    / "node_modules"
    / "@ffprobe-installer"
    / "linux-x64"
    / "ffprobe"
)
URL = "http://127.0.0.1:3000"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--force-color-profile=srgb"])
        context = browser.new_context(
            viewport={"width": 1600, "height": 1000},
            record_video_dir=str(WORK / "recording"),
            record_video_size={"width": 1600, "height": 1000},
        )
        page = context.new_page()
        page.set_default_timeout(30_000)
        capture.run_demo(page)
        capture.select_auto(page)
        started = time.monotonic()
        click_at = time.monotonic()
        with page.expect_response(
            lambda response: (
                response.request.method == "POST" and "/templates/plan" in response.url
            ),
            timeout=240_000,
        ) as response_info:
            page.get_by_role("button", name="Plan template").click()
        response = response_info.value
        responded = time.monotonic()
        page.get_by_role("heading", name="Routing decision").wait_for(timeout=60_000)
        page.wait_for_timeout(1500)
        capture.dismiss_toast(page)
        page.locator("section:has(#routing-decision-title)").last.scroll_into_view_if_needed()
        page.wait_for_timeout(600)
        page.screenshot(path=str(OUT / "live-result.png"), full_page=False)
        payload = response.json()
        findings = capture.scan_for_secrets(payload)
        if findings:
            raise SystemExit(f"secret-like strings found: {findings}")
        (OUT / "plan-response.json").write_text(
            json.dumps(capture.scrub(payload), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        routing = payload.get("routing") or {}
        decision = routing.get("decision") or {}
        summary = {
            "schema": "live-llm-capture/v1",
            "http_status": response.status,
            "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
            "elapsed_seconds": round(responded - click_at, 2),
            "run_id": routing.get("run_id"),
            "complexity": decision.get("complexity"),
            "recommended_provider": decision.get("provider"),
            "actual_provider": routing.get("actual_provider"),
            "actual_model": routing.get("actual_model"),
            "match": routing.get("match"),
            "fallback": routing.get("fallback"),
            "validation": payload.get("validation"),
            "ir_version": (payload.get("ir") or {}).get("ir_version"),
            "screenshot": "docs/media/live-v013/live-result.png",
        }
        context.close()
        video = page.video.path() if page.video else None
        browser.close()
    if not video:
        raise SystemExit("no video recorded")
    video_path = Path(video)
    duration = float(
        subprocess.run(
            [
                str(FFPROBE),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )
    start = max(0.0, (click_at - started) - 2.5)
    length = min(duration - start, (responded - click_at) + 9.0)
    mp4 = OUT / "live-call.mp4"
    subprocess.run(
        [
            str(FFMPEG),
            "-y",
            "-ss",
            f"{start:.2f}",
            "-i",
            str(video_path),
            "-t",
            f"{length:.2f}",
            "-vf",
            "fps=30,scale=1600:1000,format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-an",
            "-movflags",
            "+faststart",
            str(mp4),
        ],
        check=True,
        capture_output=True,
    )
    summary["video"] = "docs/media/live-v013/live-call.mp4"
    summary["video_seconds"] = round(length, 2)
    summary["recording_seconds"] = round(duration, 2)
    (OUT / "manifest.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
