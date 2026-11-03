"""Validation engine and DOCX compiler tests."""

from __future__ import annotations

import io
import zipfile

import pytest
from docentric_copilot.docx_compiler import (
    CompileOptions,
    GenericDocxCompiler,
    SampleContext,
    evaluate,
    format_value,
    inspect_package,
    normalize_package,
)
from docentric_copilot.errors import CompilationFailedError, UnsupportedTargetError
from docentric_copilot.template_ir import (
    Expression,
    FieldBinding,
    ValueFormat,
    load_document,
)
from docentric_copilot.template_validator import ValidationEngine
from docx import Document as DocxDocument


def _doc(**overrides):
    payload = {
        "title": "Doc",
        "metadata": {"template_name": "doc", "source_schema_id": "sales_quotation"},
        "sections": [
            {
                "name": "Main",
                "body": [{"kind": "paragraph", "runs": [{"kind": "text", "text": "x"}]}],
            }
        ],
    }
    payload.update(overrides)
    return load_document(payload)


def _paragraph_path(path: str) -> dict:
    return {"kind": "paragraph", "runs": [{"kind": "field", "path": path}]}


class TestValidationLevels:
    def test_happy_path(self, validation) -> None:
        statuses = validation.statuses()
        assert statuses == {
            "structural": "passed",
            "semantic": "passed",
            "logical": "passed",
            "visual": "passed",
            "docentric_compatibility": "not_tested",
        }
        assert validation.can_compile is True
        assert validation.overall == "passed_unverified_compatibility"

    def test_compatibility_is_never_passed(self, validation) -> None:
        assert validation.statuses()["docentric_compatibility"] != "passed"
        assert validation.overall != "passed"

    def test_unknown_binding_blocks_compilation(self, schema) -> None:
        document = _doc(
            sections=[{"name": "Main", "body": [_paragraph_path("MainData.Nope.Missing")]}]
        )
        report = ValidationEngine().validate(document, schema)
        assert report.statuses()["semantic"] == "failed"
        assert report.can_compile is False
        assert any(finding.code == "V2-001" for finding in report.errors())

    def test_collection_context_violation(self, schema) -> None:
        document = _doc(
            sections=[
                {
                    "name": "Main",
                    "body": [_paragraph_path("MainData.QuotationLines.Line.Description")],
                }
            ]
        )
        report = ValidationEngine().validate(document, schema)
        assert report.statuses()["semantic"] == "failed"
        assert any(finding.code == "V2-003" for finding in report.errors())

    def test_format_type_mismatch(self, schema) -> None:
        document = _doc(
            sections=[
                {
                    "name": "Main",
                    "body": [
                        {
                            "kind": "paragraph",
                            "runs": [
                                {
                                    "kind": "field",
                                    "path": "MainData.Quotation.Customer.Name",
                                    "format": "number",
                                }
                            ],
                        }
                    ],
                }
            ]
        )
        report = ValidationEngine().validate(document, schema)
        assert any(finding.code == "V2-004" for finding in report.errors())

    def test_boolean_comparison_on_string_field(self, schema) -> None:
        document = _doc(
            sections=[
                {
                    "name": "Main",
                    "body": [
                        {
                            "kind": "conditional",
                            "condition": {
                                "operator": "equals",
                                "field": "MainData.Quotation.Customer.Name",
                                "value": True,
                            },
                            "then_blocks": [
                                {"kind": "paragraph", "runs": [{"kind": "text", "text": "y"}]}
                            ],
                        }
                    ],
                }
            ]
        )
        report = ValidationEngine().validate(document, schema)
        assert any(finding.code == "V3-003" for finding in report.errors())

    def test_repeat_on_scalar_is_invalid(self, schema) -> None:
        document = _doc(
            sections=[
                {
                    "name": "Main",
                    "body": [
                        {
                            "kind": "repeat",
                            "path": "MainData.Quotation.TotalAmount",
                            "alias": "row",
                            "blocks": [
                                {"kind": "paragraph", "runs": [{"kind": "text", "text": "x"}]}
                            ],
                        }
                    ],
                }
            ]
        )
        report = ValidationEngine().validate(document, schema)
        assert report.statuses()["logical"] == "failed"

    def test_table_width_warning(self, schema, sample_data) -> None:
        document = _doc(
            sections=[
                {
                    "name": "Main",
                    "body": [
                        {
                            "kind": "table",
                            "columns": [
                                {"header": "A", "width_mm": 150},
                                {"header": "B", "width_mm": 150},
                            ],
                            "rows": [{"cells": [{"blocks": []}, {"blocks": []}]}],
                        }
                    ],
                }
            ]
        )
        report = ValidationEngine().validate(document, schema, sample_data=sample_data)
        assert report.statuses()["visual"] == "warning"

    def test_visual_is_skipped_without_sample_data(self, schema) -> None:
        report = ValidationEngine().validate(_doc(), schema)
        assert report.statuses()["visual"] == "skipped"

    def test_package_without_required_entries(self, schema) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("hello.txt", "not a docx")
        report = ValidationEngine().validate(_doc(), schema, package=buffer.getvalue())
        assert report.statuses()["structural"] == "failed"
        assert any(finding.code == "V1-006" for finding in report.errors())

    def test_package_with_macros(self, schema, compiled) -> None:
        source = zipfile.ZipFile(io.BytesIO(compiled.content))
        buffer = io.BytesIO()
        with source, zipfile.ZipFile(buffer, "w") as target:
            for name in source.namelist():
                target.writestr(name, source.read(name))
            target.writestr("word/vbaProject.bin", b"\x00")
        report = ValidationEngine().validate(_doc(), schema, package=buffer.getvalue())
        assert any(finding.code == "V1-007" for finding in report.errors())

    def test_duplicate_section_names(self, schema) -> None:
        document = _doc(
            sections=[
                {"name": "Main", "body": [{"kind": "paragraph", "runs": []}]},
                {"name": "Main", "body": [{"kind": "paragraph", "runs": []}]},
            ]
        )
        report = ValidationEngine().validate(document, schema)
        assert any(finding.code == "V1-003" for finding in report.errors())


class TestCompiler:
    def test_byte_identical_output(self, planned, schema, sample_data) -> None:
        compiler = GenericDocxCompiler()
        first = compiler.compile(
            planned.document, schema, CompileOptions(), sample_data=sample_data
        )
        second = compiler.compile(
            planned.document, schema, CompileOptions(), sample_data=sample_data
        )
        assert first.content == second.content
        assert first.ir_digest == second.ir_digest

    def test_document_content(self, compiled) -> None:
        document = DocxDocument(io.BytesIO(compiled.content))
        texts = [paragraph.text for paragraph in document.paragraphs]
        cell_texts = [
            cell.text for table in document.tables for row in table.rows for cell in row.cells
        ]
        corpus = "\n".join(texts + cell_texts)
        assert "Sales Quotation" in texts
        assert "SQ-100245" in corpus
        assert "Example Customer GmbH" in corpus
        assert "1,980.00" in corpus
        assert "SKU" in corpus
        assert document.tables, "the item table is required"
        items_table = next(
            table
            for table in document.tables
            if any("SKU" in cell.text for cell in table.rows[0].cells)
        )
        rows = items_table.rows
        assert len(rows) == 3  # header + two lines
        assert rows[1].cells[0].text == "ES-100"
        footer_text = " ".join(
            paragraph.text for paragraph in document.sections[0].footer.paragraphs
        )
        body_text = " ".join(paragraph.text for paragraph in document.paragraphs)
        assert "DE44 5001 0517 5407 3249 31" in f"{footer_text} {body_text}"

    def test_table_grid_follows_ir_widths(self, compiled, planned) -> None:
        document = DocxDocument(io.BytesIO(compiled.content))
        items_table = next(
            table
            for table in document.tables
            if any("SKU" in cell.text for cell in table.rows[0].cells)
        )
        ir_table = next(
            block
            for block in planned.document.sections[0].body
            if block.kind == "table" and block.repeat is not None
        )
        assert [round(column.width.mm, 1) for column in items_table.columns] == [
            column.width_mm for column in ir_table.columns
        ]

    def test_logo_is_embedded(self, compiled) -> None:
        assert any(name.startswith("word/media/") for name in compiled.package["entries"])
        assert compiled.stats["images"] == 1

    def test_package_is_valid(self, compiled) -> None:
        info = inspect_package(compiled.content)
        assert info.is_valid
        assert not info.has_macros
        assert compiled.compatibility == "not_tested"

    def test_core_properties_are_deterministic(self, compiled) -> None:
        document = DocxDocument(io.BytesIO(compiled.content))
        properties = document.core_properties
        assert properties.title == "Sales Quotation"
        assert "not_tested" in properties.keywords
        assert properties.author == "Docentric Copilot"

    def test_placeholder_mode_without_sample_data(self, planned, schema) -> None:
        result = GenericDocxCompiler().compile(planned.document, schema, CompileOptions())
        document = DocxDocument(io.BytesIO(result.content))
        joined = "\n".join(paragraph.text for paragraph in document.paragraphs)
        assert "[[MainData.Quotation.QuotationId]]" in joined
        assert result.stats["placeholders"] > 0

    def test_conditional_false_hides_notice(self, planned, schema, sample_data) -> None:
        modified = {
            **sample_data,
            "MainData": {
                **sample_data["MainData"],
                "Quotation": {
                    **sample_data["MainData"]["Quotation"],
                    "Customer": {
                        **sample_data["MainData"]["Quotation"]["Customer"],
                        "IsEU": False,
                    },
                },
            },
        }
        result = GenericDocxCompiler().compile(
            planned.document, schema, CompileOptions(), sample_data=modified
        )
        text = "\n".join(
            paragraph.text for paragraph in DocxDocument(io.BytesIO(result.content)).paragraphs
        )
        assert "VAT notice" not in text

    def test_invalid_image_becomes_placeholder(self, planned, schema, sample_data) -> None:
        modified = {
            **sample_data,
            "GeneralData": {
                **sample_data["GeneralData"],
                "Company": {
                    **sample_data["GeneralData"]["Company"],
                    "CompanyLogo": "not-an-image",
                },
            },
        }
        result = GenericDocxCompiler().compile(
            planned.document, schema, CompileOptions(), sample_data=modified
        )
        assert any("not a decodable" in warning for warning in result.warnings)
        assert result.stats["images"] == 0

    def test_docentric_target_fails_closed(self, planned, schema) -> None:
        with pytest.raises(UnsupportedTargetError) as exc:
            GenericDocxCompiler().compile(
                planned.document.model_copy(update={"target": "docentric-ax"}),
                schema,
                CompileOptions(),
            )
        assert exc.value.http_status == 409

    def test_unsupported_compiler_is_gated(self, planned, schema) -> None:
        from docentric_copilot.docx_compiler.generic import DocentricAXCompiler

        with pytest.raises(UnsupportedTargetError) as exc:
            DocentricAXCompiler().compile(planned.document, schema, CompileOptions())
        assert "gate" in exc.value.details

    def test_render_mode_placeholder_ignores_sample(self, planned, schema, sample_data) -> None:
        result = GenericDocxCompiler().compile(
            planned.document,
            schema,
            CompileOptions(render_mode="placeholder"),
            sample_data=sample_data,
        )
        document = DocxDocument(io.BytesIO(result.content))
        joined = "\n".join(paragraph.text for paragraph in document.paragraphs)
        assert "[[MainData.Quotation.QuotationId]]" in joined

    def test_normalize_package_is_stable(self, compiled) -> None:
        assert normalize_package(compiled.content) == compiled.content

    def test_normalize_rejects_garbage(self) -> None:
        with pytest.raises(CompilationFailedError):
            normalize_package(b"not a zip at all")


class TestFormatting:
    def _binding(self, **kwargs) -> FieldBinding:
        return FieldBinding(path="MainData.Quotation.TotalAmount", **kwargs)

    def test_numbers(self) -> None:
        assert format_value(1234.5, self._binding(format=ValueFormat.NUMBER)) == "1,234.50"
        assert format_value(1234.5, self._binding(format=ValueFormat.NUMBER, decimals=0)) == "1,234"
        assert (
            format_value(12, self._binding(format=ValueFormat.CURRENCY, currency_code="EUR"))
            == "12.00 EUR"
        )

    def test_dates(self) -> None:
        assert (
            format_value("2026-03-02", self._binding(format=ValueFormat.DATE_ISO)) == "2026-03-02"
        )
        assert (
            format_value("2026-03-02", self._binding(format=ValueFormat.DATE_SHORT))
            == "02 Mar 2026"
        )
        assert (
            format_value("2026-03-02", self._binding(format=ValueFormat.DATE_LONG))
            == "2 March 2026"
        )
        assert (
            format_value(
                "2026-03-02",
                self._binding(format=ValueFormat.DATE_SHORT, date_pattern="DD.MM.YYYY"),
            )
            == "02.03.2026"
        )

    def test_booleans_and_text(self) -> None:
        assert format_value(True, self._binding(format=ValueFormat.BOOLEAN_YES_NO)) == "Yes"
        assert format_value(False, self._binding(format=ValueFormat.BOOLEAN_YES_NO)) == "No"
        assert format_value("abc", self._binding(format=ValueFormat.UPPERCASE)) == "ABC"
        assert format_value(0.5, self._binding(format=ValueFormat.PERCENT)) == "50.0%"
        assert format_value(None, self._binding()) == ""
        assert format_value("text", self._binding()) == "text"


class TestExpressions:
    def _context(self) -> SampleContext:
        return SampleContext(
            sample={
                "MainData": {
                    "Quotation": {
                        "TotalAmount": 100,
                        "Customer": {"IsEU": True, "VatNumber": "DE1", "Name": "ACME"},
                    }
                }
            }
        )

    def test_equals_and_null(self) -> None:
        context = self._context()
        assert evaluate(
            Expression(operator="equals", field="MainData.Quotation.TotalAmount", value=100),
            context,
        )
        assert not evaluate(
            Expression(operator="equals", field="MainData.Quotation.TotalAmount", value=101),
            context,
        )
        assert evaluate(
            Expression(operator="not_null", field="MainData.Quotation.Customer.Name"), context
        )
        assert evaluate(
            Expression(operator="is_null", field="MainData.Quotation.Customer.Missing"), context
        )

    def test_logical_composition(self) -> None:
        context = self._context()
        expression = Expression(
            operator="and",
            operands=[
                Expression(operator="equals", field="MainData.Quotation.Customer.IsEU", value=True),
                Expression(operator="not_null", field="MainData.Quotation.Customer.VatNumber"),
            ],
        )
        assert evaluate(expression, context)
        negated = Expression(operator="not", operands=[expression])
        assert evaluate(negated, context) is False

    def test_numeric_and_string_comparisons(self) -> None:
        context = self._context()
        assert evaluate(
            Expression(operator="greater_than", field="MainData.Quotation.TotalAmount", value=10),
            context,
        )
        assert evaluate(
            Expression(operator="contains", field="MainData.Quotation.Customer.Name", value="CME"),
            context,
        )
        assert not evaluate(
            Expression(
                operator="greater_than", field="MainData.Quotation.Customer.Missing", value=1
            ),
            context,
        )
