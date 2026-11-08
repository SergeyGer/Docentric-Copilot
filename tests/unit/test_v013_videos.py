"""T-02/T-03 draft video production kit."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def test_video_kit_has_target_durations_and_av_streams() -> None:
    data = json.loads((ROOT / "docs" / "media" / "v013-video-kit.json").read_text(encoding="utf-8"))
    assert data["status"] == "draft_production_kit"
    assert data["human_review"] is False
    assert data["youtube_published"] is False
    product = data["product"]
    technical = data["technical"]
    assert 150 <= product["duration_seconds"] <= 180
    assert 300 <= technical["duration_seconds"] <= 420
    for item in (product, technical):
        assert (ROOT / item["mp4"]).is_file()
        assert (ROOT / item["srt"]).is_file()
        assert item["bytes"] > 1_000_000
        streams = {stream["codec_type"]: stream for stream in item["probe"]["streams"]}
        assert streams["video"]["codec_name"] == "h264"
        assert streams["video"]["width"] == 1920
        assert streams["video"]["height"] == 1080
        assert streams["audio"]["codec_name"] == "aac"


def test_video_kit_does_not_claim_publication() -> None:
    text = (ROOT / "docs" / "VIDEOS_V013.md").read_text(encoding="utf-8")
    assert "publication blocked" in text
    assert "human_review: false" in text
    assert "youtube_published: false" in text
