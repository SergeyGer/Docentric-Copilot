"""T-02/T-03 publish-ready video drafts and Word desktop evidence."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def test_video_kit_has_target_durations_and_av_streams() -> None:
    data = json.loads((ROOT / "docs" / "media" / "v013-video-kit.json").read_text(encoding="utf-8"))
    assert data["status"] == "publish_ready_draft"
    assert data["human_review"] is False
    assert data["youtube_published"] is False
    product = data["product"]
    technical = data["technical"]
    assert 150 <= product["duration_seconds"] <= 180
    assert 300 <= technical["duration_seconds"] <= 420
    for item in (product, technical):
        assert (ROOT / item["mp4"]).is_file()
        assert (ROOT / item["srt"]).is_file()
        assert (ROOT / item["thumbnail"]).is_file()
        assert item["bytes"] > 1_000_000
        streams = {stream["codec_type"]: stream for stream in item["probe"]["streams"]}
        assert streams["video"]["codec_name"] == "h264"
        assert streams["video"]["width"] == 1920
        assert streams["video"]["height"] == 1080
        assert streams["audio"]["codec_name"] == "aac"


def test_video_content_rules_are_recorded_and_clean() -> None:
    data = json.loads((ROOT / "docs" / "media" / "v013-video-kit.json").read_text(encoding="utf-8"))
    rules = data["content_rules"]
    assert rules["spoken_version_numbers"] is False
    assert rules["on_screen_version_numbers"] is False
    assert rules["bullet_slides"] is False
    for name in ("demo", "technical"):
        text = (ROOT / "docs" / "media" / f"{name}-v013-narration.md").read_text(encoding="utf-8")
        assert not re.search(r"v0?\.\d+|zero thirteen|version\s+\d", text, flags=re.IGNORECASE)
    assert "docs/wiki/Architecture.md" in data["diagram_sources"]
    for diagram in data["diagrams"]:
        assert (ROOT / diagram).is_file()


def test_video_kit_does_not_claim_publication() -> None:
    text = (ROOT / "docs" / "VIDEOS_V013.md").read_text(encoding="utf-8")
    assert "not reviewed or published" in text
    assert "human_review: false" in text
    assert "youtube_published: false" in text


def test_word_desktop_evidence_is_distinct_from_word_web() -> None:
    data = json.loads(
        (
            ROOT / "docs" / "media" / "v013-wordweb" / "user-word-desktop" / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert data["status"] == "user_provided_manual_check"
    assert data["word_for_the_web"] is False
    assert data["checks"]["page_1_logo_present"] is True
    assert data["checks"]["pages_2_plus_logo_absent"] is True
    assert data["checks"]["footer_and_page_numbers"] is True
    assert data["document"]["pages"] == 2
