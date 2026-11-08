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
    classification = data["table_classification"]
    assert classification["observed"] == 30
    assert (
        classification["accepted"]
        + classification["deliberately_unsupported"]
        + classification["defect"]
        + classification["not_evaluable"]
        == 30
    )
    assert classification["rejected_by_reason"]
    assert data["failure_classification"]
    assert {item["error"] for item in data["failure_classification"]} == {
        "CompilationFailedError",
        "ReferenceImportEmptyError",
    }
    assert "No independent human" not in json.dumps(data)
    assert data["limitations"]


def test_reference_evaluation_markdown_is_current() -> None:
    from scripts.reference_evaluation import main

    assert main(["--check"]) == 0
    markdown = (ROOT / "docs" / "REFERENCE_EVALUATION_V013.md").read_text(encoding="utf-8")
    assert "## Metrics" in markdown
    assert "Compilation success rate" in markdown
    assert "## Table classification" in markdown
    assert "## Failure classification" in markdown
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


def test_nested_collection_is_refused_at_root() -> None:
    import pytest
    from docentric_copilot.ddsp_parser.models import NormalizedSchema, SchemaNode, SchemaSection
    from docentric_copilot.docx_compiler import CompileOptions, GenericDocxCompiler
    from docentric_copilot.errors import CompilationFailedError
    from docentric_copilot.template_ir import (
        Document,
        DocumentMetadata,
        Paragraph,
        Repeat,
        Section,
        TextRun,
    )

    nested = SchemaNode(
        name="Nested",
        path="MainData.PurchTable.PurchRFQTable.Nested",
        data_type="collection",
        collection=True,
        children=[
            SchemaNode(
                name="Id",
                path="MainData.PurchTable.PurchRFQTable.Nested.Id",
                data_type="string",
            )
        ],
    )
    schema = NormalizedSchema(
        schema_id="nested",
        sections=[
            SchemaSection(
                name="MainData",
                nodes=[
                    SchemaNode(
                        name="PurchTable",
                        path="MainData.PurchTable",
                        data_type="object",
                        children=[
                            SchemaNode(
                                name="PurchRFQTable",
                                path="MainData.PurchTable.PurchRFQTable",
                                data_type="collection",
                                collection=True,
                                children=[nested],
                            )
                        ],
                    )
                ],
            )
        ],
    )
    document = Document(
        title="Nested boundary",
        metadata=DocumentMetadata(
            template_name="nested_boundary",
            source_schema_id="nested",
        ),
        sections=[
            Section(
                name="Main",
                body=[
                    Repeat(
                        path="MainData.PurchTable.PurchRFQTable.Nested",
                        alias="nested",
                        blocks=[Paragraph(runs=[TextRun(text="x")])],
                    )
                ],
            )
        ],
    )
    with pytest.raises(CompilationFailedError):
        GenericDocxCompiler().compile(document, schema, CompileOptions(render_mode="placeholder"))
