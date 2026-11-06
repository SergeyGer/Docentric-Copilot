"""V013-01: feature coverage matrix consistency."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def test_feature_coverage_json_is_complete_and_rendered() -> None:
    from scripts.feature_coverage import LEVELS, STATUSES, load, validate

    data = load()
    assert not validate(data)
    assert len(data["features"]) == 15
    for feature in data["features"]:
        assert set(feature["levels"]) == set(LEVELS)
        assert all(status in STATUSES for status in feature["levels"].values())
        assert feature["evidence"]
    assert data["corpus"]["ax2012_examples"] == 6
    assert data["corpus"]["d365fo_entries"] == 11
    assert data["corpus"]["distinct_docx"] == 17
    assert data["corpus"]["controls"] == 672
    assert data["corpus"]["duplicate_occurrences"] > data["corpus"]["duplicate_groups"]


def test_feature_coverage_markdown_is_current() -> None:
    from scripts.feature_coverage import main

    assert main(["--check"]) == 0
    markdown = (ROOT / "docs" / "FEATURE_COVERAGE_V013.md").read_text(encoding="utf-8")
    assert "## Matrix" in markdown
    assert "Field / ValueBinding" in markdown
    assert "Nested Tables" in markdown
    assert "## Missing tests" in markdown
    assert "Supported" in markdown and "Partial" in markdown


def test_feature_coverage_contains_no_private_paths() -> None:
    text = (ROOT / "benchmarks" / "feature_coverage.json").read_text(encoding="utf-8")
    for marker in (".tools/", "reference-corpus", "Docentric AX Examples.zip", "Links.txt"):
        assert marker not in text
