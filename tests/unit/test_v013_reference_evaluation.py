"""V013-05: committed reference evaluation aggregates."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def test_reference_evaluation_aggregates_are_present_and_valid() -> None:
    data = json.loads(
        (ROOT / "benchmarks" / "reference_evaluation_v013.json").read_text(encoding="utf-8")
    )
    assert data["schema"] == "reference-evaluation/v1"
    assert data["corpus"]["documents"] == 17
    assert data["corpus"]["controls"] == 672
    metrics = data["metrics"]
    for key in (
        "parsing_success_rate",
        "reference_resolution_rate",
        "binding_evidence_rate",
        "collection_scope_resolution_rate",
        "image_binding_resolution_rate",
        "table_structure_accuracy",
        "ir_coverage",
        "import_validation_rate",
        "compilation_success_rate",
    ):
        metric = metrics[key]
        assert 0.0 <= metric["value"] <= 1.0
        assert metric["denominator"] >= metric["numerator"] >= 0
    assert metrics["parsing_success_rate"]["value"] == 1.0
    assert metrics["reference_resolution_rate"]["value"] == 0.9673
    assert metrics["image_binding_resolution_rate"]["numerator"] == 14
    assert "No independent human" not in json.dumps(data)
    assert data["limitations"]


def test_reference_evaluation_markdown_is_current() -> None:
    from scripts.reference_evaluation import main

    assert main(["--check"]) == 0
    markdown = (ROOT / "docs" / "REFERENCE_EVALUATION_V013.md").read_text(encoding="utf-8")
    assert "## Metrics" in markdown
    assert "Compilation success rate" in markdown
    assert "## Limitations" in markdown


def test_reference_evaluation_has_no_private_paths_or_secrets() -> None:
    text = (ROOT / "benchmarks" / "reference_evaluation_v013.json").read_text(encoding="utf-8")
    for marker in (
        ".tools/",
        "reference-corpus",
        "Docentric AX Examples.zip",
        "sk-proj",
        "sk-ant-",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
    ):
        assert marker not in text
