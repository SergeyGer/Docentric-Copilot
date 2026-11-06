"""Schema resolution, semantic mapping and Template IR contract tests."""

from __future__ import annotations

import pytest
from docentric_copilot.errors import InvalidInputError
from docentric_copilot.schema_resolver import (
    FieldMapping,
    MappingStatus,
    PathResolutionError,
    Scope,
    decide_status,
    infer_kind,
    is_type_compatible,
    resolve_collection,
    resolve_value,
    search_candidates,
    validate_mapping,
)
from docentric_copilot.template_ir import (
    Document,
    Expression,
    FieldBinding,
    IRMigrationError,
    TextRun,
    canonical_ir_json,
    count_blocks,
    document_json_schema,
    ir_digest,
    load_document,
    migrate,
)
from docentric_copilot.template_ir.models import Cell, Paragraph, Table, TableColumn, TableRow
from pydantic import ValidationError


def _minimal(**overrides) -> dict:
    payload = {
        "title": "Quotation",
        "metadata": {"template_name": "quotation", "source_schema_id": "sales_quotation"},
        "sections": [
            {
                "name": "Main",
                "body": [{"kind": "paragraph", "runs": [{"kind": "text", "text": "Hi"}]}],
            }
        ],
    }
    payload.update(overrides)
    return payload


class TestPathResolution:
    def test_absolute_scalar(self, schema) -> None:
        resolved = resolve_value(schema, "MainData.Quotation.TotalAmount")
        assert resolved.absolute == "MainData.Quotation.TotalAmount"
        assert resolved.node.data_type == "number"

    def test_alias_resolution(self, schema) -> None:
        scope = Scope().push("line", "MainData.QuotationLines.Line")
        resolved = resolve_value(schema, "line.UnitPrice", scope)
        assert resolved.absolute == "MainData.QuotationLines.Line.UnitPrice"
        assert resolved.alias == "line"

    def test_unknown_path(self, schema) -> None:
        with pytest.raises(PathResolutionError) as exc:
            resolve_value(schema, "MainData.Quotation.Discount")
        assert exc.value.code == "path_not_found"

    def test_complex_object_cannot_be_scalar(self, schema) -> None:
        with pytest.raises(PathResolutionError) as exc:
            resolve_value(schema, "MainData.Quotation")
        assert exc.value.code == "type_mismatch"

    def test_collection_cannot_be_scalar(self, schema) -> None:
        with pytest.raises(PathResolutionError) as exc:
            resolve_value(schema, "MainData.QuotationLines.Line")
        assert exc.value.code == "type_mismatch"

    def test_context_violation_without_repeat(self, schema) -> None:
        with pytest.raises(PathResolutionError) as exc:
            resolve_value(schema, "MainData.QuotationLines.Line.Description", Scope())
        assert exc.value.code == "context_violation"

    def test_collection_resolution(self, schema) -> None:
        resolved = resolve_collection(schema, "MainData.QuotationLines.Line")
        assert resolved.node.collection is True
        with pytest.raises(PathResolutionError):
            resolve_collection(schema, "MainData.Quotation.TotalAmount")

    def test_type_compatibility(self) -> None:
        assert is_type_compatible("string", "string")
        assert is_type_compatible("date", "string")
        assert is_type_compatible("any", "boolean")
        assert not is_type_compatible("number", "string")


class TestSemanticMapping:
    def test_search_ranks_the_obvious_field_first(self, schema) -> None:
        cases = {
            "company logo": "GeneralData.Company.CompanyLogo",
            "customer name": "MainData.Quotation.Customer.Name",
            "quotation date": "MainData.Quotation.QuotationDate",
            "unit price": "MainData.QuotationLines.Line.UnitPrice",
            "final total amount": "MainData.Quotation.TotalAmount",
        }
        for requirement, expected in cases.items():
            candidates = search_candidates(schema, requirement, kind=infer_kind(requirement))
            assert candidates, requirement
            assert candidates[0].path == expected, (requirement, candidates[0].path)

    def test_collection_search(self, schema) -> None:
        candidates = search_candidates(
            schema, "product lines", kind=infer_kind("product lines"), include_collections=True
        )
        assert candidates[0].path == "MainData.QuotationLines.Line"
        assert candidates[0].collection is True

    def test_ambiguity_detection(self, schema) -> None:
        candidates = search_candidates(schema, "vat number")
        assert decide_status(candidates) == "ambiguous"

    def test_missing_when_nothing_matches(self, schema) -> None:
        assert search_candidates(schema, "banana smoothie recipe") == []
        assert decide_status([]) == "missing"

    def test_validate_mapping_rejects_unknown_path(self, schema) -> None:
        mapping = FieldMapping(
            requirement_id="req_00",
            requirement="Customer name",
            selected_field_path="MainData.Quotation.Customer.Imaginary",
            status=MappingStatus.SCHEMA_VALID,
        )
        validated = validate_mapping(schema, mapping)
        assert validated.status is MappingStatus.INVALID
        assert "does not exist" in validated.explanation

    def test_validate_mapping_rejects_type_mismatch(self, schema) -> None:
        mapping = FieldMapping(
            requirement_id="req_01",
            requirement="Amount",
            selected_field_path="MainData.Quotation.Customer.Name",
            data_type="number",
            status=MappingStatus.SCHEMA_VALID,
        )
        assert validate_mapping(schema, mapping).status is MappingStatus.INVALID

    def test_validate_mapping_accepts_compatible_path(self, schema) -> None:
        mapping = FieldMapping(
            requirement_id="req_02",
            requirement="Total",
            selected_field_path="MainData.Quotation.TotalAmount",
            data_type="number",
            status=MappingStatus.SCHEMA_VALID,
        )
        validated = validate_mapping(schema, mapping)
        assert validated.status is MappingStatus.SCHEMA_VALID
        assert validated.schema_evidence.startswith("MainData.Quotation.TotalAmount")


class TestTemplateIR:
    def test_roundtrip_and_digest(self) -> None:
        document = load_document(_minimal())
        payload = document.model_dump(mode="json")
        assert load_document(payload) == document
        assert ir_digest(document) == ir_digest(load_document(payload))
        assert canonical_ir_json(document) == canonical_ir_json(load_document(payload))

    def test_unknown_key_is_rejected(self) -> None:
        with pytest.raises(InvalidInputError):
            load_document(_minimal(sections=[{"name": "Main", "body": [], "surprise": 1}]))

    def test_invalid_path_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FieldBinding(path="Main Data..Name")

    def test_unknown_ir_version(self) -> None:
        with pytest.raises(IRMigrationError):
            migrate({"ir_version": "9.9"}, "9.9")

    def test_empty_document_rejected(self) -> None:
        with pytest.raises(InvalidInputError):
            load_document(_minimal(sections=[]))

    def test_expression_operator_rules(self) -> None:
        with pytest.raises(ValidationError):
            Expression(operator="and", operands=[])
        with pytest.raises(ValidationError):
            Expression(operator="equals", field="MainData.A")
        with pytest.raises(ValidationError):
            Expression(operator="not_null", field="MainData.A", value=1)
        with pytest.raises(ValidationError):
            Expression(operator="contains", field="MainData.A", value=1)

    def test_expression_depth_limit(self) -> None:
        current = Expression(operator="not_null", field="MainData.A")
        for _ in range(8):
            current = Expression(operator="not", operands=[current])
        with pytest.raises(ValidationError):
            Expression(operator="not", operands=[current])

    def test_table_shape_validation(self) -> None:
        with pytest.raises(ValidationError):
            Table(
                columns=[TableColumn(header="A"), TableColumn(header="B")],
                rows=[TableRow(cells=[Cell(blocks=[])])],
            )
        with pytest.raises(ValidationError):
            Table(columns=[TableColumn(header="A")], repeat={"path": "MainData.X", "alias": "x"})

    def test_json_schema_is_exported(self) -> None:
        schema = document_json_schema()
        assert schema["$id"].endswith("template-ir-v1.2.json")
        assert "properties" in schema and "$defs" in schema

    def test_traversal(self) -> None:
        document = load_document(
            _minimal(
                sections=[
                    {
                        "name": "Main",
                        "body": [
                            {"kind": "paragraph", "runs": [{"kind": "text", "text": "a"}]},
                            {
                                "kind": "repeat",
                                "path": "MainData.Lines",
                                "alias": "line",
                                "blocks": [
                                    {
                                        "kind": "paragraph",
                                        "runs": [{"kind": "field", "path": "line.Description"}],
                                    }
                                ],
                            },
                        ],
                    }
                ]
            )
        )
        assert count_blocks(document) == 3
        assert isinstance(document.sections[0].body[0].runs[0], TextRun)

    def test_alias_pattern(self) -> None:
        with pytest.raises(ValidationError):
            Document.model_validate(
                _minimal(
                    sections=[
                        {
                            "name": "Main",
                            "body": [
                                {
                                    "kind": "repeat",
                                    "path": "MainData.Lines",
                                    "alias": "Line-Items",
                                    "blocks": [
                                        {
                                            "kind": "paragraph",
                                            "runs": [{"kind": "text", "text": "x"}],
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                )
            )

    def test_paragraph_requires_known_inline_kind(self) -> None:
        with pytest.raises(ValidationError):
            Paragraph.model_validate({"runs": [{"kind": "image", "path": "MainData.A"}]})
