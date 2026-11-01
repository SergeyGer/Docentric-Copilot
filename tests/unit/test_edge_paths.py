"""Additional edge-case coverage for parser, renderer and compiler paths."""

from __future__ import annotations

import io

import pytest
from docentric_copilot.config import Limits
from docentric_copilot.ddsp_parser import parse_ddsp
from docentric_copilot.docx_compiler import CompileOptions, GenericDocxCompiler
from docentric_copilot.errors import UnsupportedInputError
from docentric_copilot.planner import build_document
from docentric_copilot.preview import render_preview
from docentric_copilot.template_ir import load_document
from docx import Document as DocxDocument

from tests.conftest import build_zip
from tests.golden_files.fixtures import FIXTURES, VAT_SAMPLE, VAT_XSD


def _minimal_schema():
    return parse_ddsp(
        build_zip({"schema.xsd": VAT_XSD.encode(), "sample.xml": VAT_SAMPLE.encode()}), "v.ddsp"
    )


def test_manifest_with_invalid_json_is_ignored() -> None:
    package = build_zip(
        {
            "manifest.json": b"{not json",
            "schema.xsd": VAT_XSD.encode(),
            "sample.xml": VAT_SAMPLE.encode(),
        }
    )
    parsed = parse_ddsp(package, "broken-manifest.ddsp")
    assert parsed.schema.has_path("MainData.Invoice.TotalAmount")
    assert any("not valid JSON" in item.message for item in parsed.schema.diagnostics)


def test_manifest_with_non_object_root_is_ignored() -> None:
    package = build_zip(
        {
            "manifest.json": b"[1,2,3]",
            "schema.xsd": VAT_XSD.encode(),
            "sample.xml": VAT_SAMPLE.encode(),
        }
    )
    parsed = parse_ddsp(package, "list-manifest.ddsp")
    assert parsed.schema.has_path("MainData.Invoice.TotalAmount")


def test_multiple_schema_documents_use_the_first() -> None:
    package = build_zip(
        {
            "a/schema.xsd": VAT_XSD.encode(),
            "b/schema2.xsd": VAT_XSD.encode(),
            "sample.xml": VAT_SAMPLE.encode(),
        }
    )
    parsed = parse_ddsp(package, "two-schemas.ddsp")
    assert any("Multiple XSD documents" in item.message for item in parsed.schema.diagnostics)


def test_sample_without_matching_sections() -> None:
    sample = b"<Root><Other><A>1</A></Other></Root>"
    package = build_zip({"schema.xsd": VAT_XSD.encode(), "sample.xml": sample})
    parsed = parse_ddsp(package, "mismatch.ddsp")
    assert any(item.code.value == "SAMPLE002" for item in parsed.schema.diagnostics)


def test_empty_collection_renders_empty_message() -> None:
    parsed = _minimal_schema()
    document = build_document(parsed.schema, "Create an invoice with customer name")
    preview = render_preview(
        document,
        parsed.schema,
        sample_data={"MainData": {"Invoice": {"CustomerName": "X", "IsEU": False}}},
    )
    assert preview.html


def test_preview_static_table_rows() -> None:
    parsed = _minimal_schema()
    document = load_document(
        {
            "title": "Static",
            "metadata": {"template_name": "t", "source_schema_id": "s"},
            "sections": [
                {
                    "name": "Main",
                    "body": [
                        {
                            "kind": "table",
                            "columns": [{"header": "A"}, {"header": "B"}],
                            "rows": [
                                {
                                    "cells": [
                                        {
                                            "blocks": [
                                                {
                                                    "kind": "paragraph",
                                                    "runs": [{"kind": "text", "text": "1"}],
                                                }
                                            ]
                                        },
                                        {
                                            "blocks": [
                                                {
                                                    "kind": "paragraph",
                                                    "runs": [{"kind": "text", "text": "2"}],
                                                }
                                            ]
                                        },
                                    ]
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )
    preview = render_preview(document, parsed.schema, sample_data={"MainData": {}})
    assert "<table>" in preview.html and "<td>" in preview.html
    assert "<span>1</span>" in preview.html and "<span>2</span>" in preview.html
    compiled = GenericDocxCompiler().compile(
        document, parsed.schema, CompileOptions(), sample_data={"MainData": {}}
    )
    tables = DocxDocument(io.BytesIO(compiled.content)).tables
    assert len(tables) == 1 and len(tables[0].rows) == 2


def test_preview_rejects_non_image_payload() -> None:
    parsed = _minimal_schema()
    document = load_document(
        {
            "title": "Img",
            "metadata": {"template_name": "t", "source_schema_id": "s"},
            "sections": [
                {
                    "name": "Main",
                    "body": [
                        {"kind": "image", "path": "MainData.Invoice.CustomerName"},
                        {"kind": "paragraph", "runs": [{"kind": "text", "text": "x"}]},
                    ],
                }
            ],
        }
    )
    preview = render_preview(
        document,
        parsed.schema,
        sample_data={"MainData": {"Invoice": {"CustomerName": "not-an-image"}}},
    )
    assert "img-placeholder" in preview.html


def test_multiple_sections_and_heading_levels() -> None:
    parsed = _minimal_schema()
    document = load_document(
        {
            "title": "Multi",
            "metadata": {"template_name": "t", "source_schema_id": "s"},
            "sections": [
                {
                    "name": "First",
                    "body": [
                        {"kind": "heading", "level": 2, "runs": [{"kind": "text", "text": "One"}]},
                        {"kind": "heading", "level": 3, "runs": [{"kind": "text", "text": "Two"}]},
                    ],
                },
                {
                    "name": "Second",
                    "body": [{"kind": "paragraph", "runs": [{"kind": "text", "text": "page two"}]}],
                    "footer": [{"kind": "table", "columns": [{"header": "A"}]}],
                },
            ],
        }
    )
    compiled = GenericDocxCompiler().compile(
        document, parsed.schema, CompileOptions(), sample_data={"MainData": {}}
    )
    docx = DocxDocument(io.BytesIO(compiled.content))
    headings = [
        paragraph.style.name
        for paragraph in docx.paragraphs
        if paragraph.style.name.startswith("Heading")
    ]
    assert headings == ["Heading 2", "Heading 3"]
    assert any("page two" in paragraph.text for paragraph in docx.paragraphs)


def test_compile_with_compatibility_stamp() -> None:
    parsed = _minimal_schema()
    document = build_document(parsed.schema, "Create a simple invoice document")
    result = GenericDocxCompiler().compile(
        document,
        parsed.schema,
        CompileOptions(include_compatibility_stamp=True),
        sample_data=parsed.sample_data,
    )
    text = "\n".join(p.text for p in DocxDocument(io.BytesIO(result.content)).paragraphs)
    assert "Docentric AX compatibility: not verified" in text


def test_parser_respects_custom_limits() -> None:
    package = build_zip({"schema.xsd": VAT_XSD.encode(), "sample.xml": VAT_SAMPLE.encode()})
    # A truncated schema is a failure, not a silent partial result (fail closed).
    with pytest.raises(UnsupportedInputError) as exc:
        parse_ddsp(package, "v.ddsp", limits=Limits(max_schema_nodes=5))
    assert exc.value.code == "SCHEMA005"


def test_fixture_packages_are_stable() -> None:
    for name, fixture in FIXTURES.items():
        first = parse_ddsp(fixture.package, f"{name}.ddsp")
        second = parse_ddsp(fixture.package, f"{name}.ddsp")
        assert first.schema.digest() == second.schema.digest()
