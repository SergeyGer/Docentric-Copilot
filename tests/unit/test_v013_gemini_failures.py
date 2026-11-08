"""T-06: Gemini technical-failure classification."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def test_gemini_failure_report_is_complete() -> None:
    data = json.loads(
        (ROOT / "benchmarks" / "gemini_failures_v013.json").read_text(encoding="utf-8")
    )
    summary = data["summary"]
    assert summary["v013_technical"] == 10
    assert summary["v012_technical"] == 4
    assert summary["delta"] == 6
    assert summary["all_gemini"] and summary["all_structured_output"]
    assert summary["all_compact_v2"]
    assert sum(data["by_family"].values()) == 10
    assert sum(data["by_error_class"].values()) == 10
    assert len(data["failures"]) == 10
    assert "nested_lists" in data["by_family"]
    assert data["actions"]


def test_gemini_failure_report_has_no_private_payloads() -> None:
    text = (ROOT / "benchmarks" / "gemini_failures_v013.json").read_text(encoding="utf-8")
    for marker in ("sk-proj", "sk-ant-", "GEMINI_API_KEY", "OPENAI_API_KEY", "reference-corpus"):
        assert marker not in text


def test_gemini_failure_markdown_is_current() -> None:
    from scripts.gemini_failures import main

    assert main([]) == 0
    markdown = (ROOT / "docs" / "GEMINI_FAILURES_V013.md").read_text(encoding="utf-8")
    assert "## By error class" in markdown
    assert "## Root-cause hypotheses" in markdown
    assert "v0.12" in markdown
