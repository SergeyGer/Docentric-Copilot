"""Compact IR planning: expansion, validation and planner/API integration."""

from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path
from typing import Any

import pytest
from docentric_copilot.api.app import create_app
from docentric_copilot.app.service import TemplateService
from docentric_copilot.config import get_settings
from docentric_copilot.errors import InvalidInputError, PlanInvalidError
from docentric_copilot.llm.models import GenerationResult, Usage
from docentric_copilot.planner import (
    COMPACT_SYSTEM_PROMPT,
    COMPACT_TEMPLATE_NAME,
    COMPACT_V2_SCHEMA_TITLE,
    COMPACT_V2_SYSTEM_PROMPT,
    PlanOptions,
    TemplatePlanner,
    absolute_bindings,
    build_document,
    compact_schema,
    compact_schema_v2,
    expand_compact,
    expand_compact_v2,
)
from docentric_copilot.template_ir import (
    Alignment,
    Conditional,
    Document,
    FieldBinding,
    Heading,
    ImageBinding,
    PageBreak,
    Paragraph,
    Repeat,
    Table,
    ValueFormat,
)
from docentric_copilot.template_validator import validate_document
from fastapi.testclient import TestClient


def _run(coro):
    return asyncio.run(coro)


def _full_feature_payload() -> dict[str, Any]:
    return {
        "title": "Sales Quotation",
        "language": "en",
        "sections": [
            {
                "name": "Main",
                "body": [
                    {"h": 1, "t": "Sales Quotation"},
                    {
                        "p": [
                            "Quotation ",
                            {"f": "MainData.Quotation.QuotationId"},
                            " · ",
                            {
                                "f": "MainData.Quotation.QuotationDate",
                                "fmt": "date_iso",
                            },
                        ]
                    },
                    {
                        "img": {
                            "f": "GeneralData.Company.CompanyLogo",
                            "w": 42,
                            "alt": "Company logo",
                        }
                    },
                    {
                        "tbl": {
                            "repeat": "MainData.QuotationLines.Line",
                            "alias": "line",
                            "hdr": True,
                            "cols": [
                                {"h": "SKU", "f": "line.ItemId", "w": 24},
                                {
                                    "h": "Amount",
                                    "f": "line.LineAmount",
                                    "w": 30,
                                    "fmt": "number",
                                    "d": 2,
                                    "align": "right",
                                },
                            ],
                            "rows": [],
                        }
                    },
                    {
                        "if": {
                            "field": "MainData.Quotation.Customer.IsEU",
                            "op": "equals",
                            "value": True,
                        },
                        "then": [{"p": ["EU customer"]}],
                        "else": [{"p": ["Non-EU customer"]}],
                    },
                    {"pb": True},
                ],
                "header": [
                    {
                        "img": {
                            "f": "GeneralData.Company.CompanyLogo",
                            "alt": "Company logo",
                        }
                    }
                ],
                "footer": [{"p": [{"f": "GeneralData.Company.Name"}]}],
            }
        ],
    }


class _FakeGateway:
    """Unit-level provider double: records calls and returns queued payloads."""

    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self._payloads = list(payloads)
        self.calls: list[dict[str, Any]] = []

    async def generate_structured(self, **kwargs: Any) -> GenerationResult:
        self.calls.append(kwargs)
        content = self._payloads[min(len(self.calls) - 1, len(self._payloads) - 1)]
        return GenerationResult(
            provider="gemini",
            model=kwargs.get("model") or "gemini-3.6-flash",
            content=content,
            usage=Usage(),
        )

    async def aclose(self) -> None:
        return None


def _compact_payload() -> dict[str, Any]:
    """The v2 ultra-compact payload the planner now asks providers for."""
    return {
        "t": "Sales Quotation",
        "l": "en",
        "s": [
            {
                "n": "Main",
                "b": [
                    ["h", 1, "Sales Quotation"],
                    ["p", "Quotation ", {"f": "MainData.Quotation.QuotationId"}],
                    [
                        "tbl",
                        "MainData.QuotationLines.Line",
                        [
                            ["SKU", "line.ItemId"],
                            ["Amount", "line.LineAmount", 30, "n", 2],
                        ],
                    ],
                ],
            }
        ],
    }


def _compact_v1_payload() -> dict[str, Any]:
    return {
        "title": "Sales Quotation",
        "language": "en",
        "sections": [
            {
                "name": "Main",
                "body": [
                    {"h": 1, "t": "Sales Quotation"},
                    {
                        "p": [
                            "Quotation ",
                            {"f": "MainData.Quotation.QuotationId"},
                        ]
                    },
                    {
                        "tbl": {
                            "repeat": "MainData.QuotationLines.Line",
                            "alias": "line",
                            "cols": [
                                {"h": "SKU", "f": "line.ItemId"},
                                {
                                    "h": "Amount",
                                    "f": "line.LineAmount",
                                    "fmt": "number",
                                    "d": 2,
                                },
                            ],
                        }
                    },
                ],
            }
        ],
    }


# --------------------------------------------------------------------------- #
# Expansion
# --------------------------------------------------------------------------- #
class TestExpandCompact:
    def test_full_feature_payload_becomes_a_valid_document(self, schema) -> None:
        document = expand_compact(_full_feature_payload(), schema)

        assert isinstance(document, Document)
        assert document.title == "Sales Quotation"
        assert document.language == "en"
        assert document.ir_version == "1.0"
        assert document.target.value == "generic-docx"
        assert document.metadata.template_name == COMPACT_TEMPLATE_NAME
        assert document.metadata.source_schema_id == schema.schema_id
        assert document.metadata.generator
        assert document.page.margin_top_mm == 20.0

        body = document.sections[0].body
        kinds = [block.kind for block in body]
        assert kinds == [
            "heading",
            "paragraph",
            "image",
            "table",
            "conditional",
            "page_break",
        ]
        assert isinstance(body[0], Heading) and body[0].level == 1
        assert isinstance(body[1], Paragraph)
        assert body[1].runs[0].kind == "text"
        assert body[1].runs[1].path == "MainData.Quotation.QuotationId"
        assert body[1].runs[3].format is ValueFormat.DATE_ISO
        assert isinstance(body[2], ImageBinding)
        assert body[2].width_mm == 42
        assert body[2].alt_text == "Company logo"
        assert isinstance(body[3], Table)
        assert isinstance(body[4], Conditional)
        assert body[4].condition.operator.value == "equals"
        assert isinstance(body[5], PageBreak)
        assert document.sections[0].header
        assert document.sections[0].footer

        report = validate_document(document, schema)
        assert report.can_compile
        assert report.statuses()["structural"] == "passed"
        assert report.statuses()["semantic"] == "passed"
        assert report.statuses()["logical"] == "passed"

    def test_missing_language_defaults_to_english(self, schema) -> None:
        payload = _full_feature_payload()
        payload.pop("language")
        assert expand_compact(payload, schema).language == "en"

    def test_full_ir_is_passed_through_unchanged(self, schema, quotation_request) -> None:
        original = build_document(schema, quotation_request)
        expanded = expand_compact(original.model_dump(mode="json"), schema)
        assert expanded.model_dump(mode="json") == original.model_dump(mode="json")

    def test_unknown_block_key_is_rejected_with_its_path(self, schema) -> None:
        payload = {
            "title": "T",
            "sections": [{"name": "Main", "body": [{"p": ["x"], "zz": 1}]}],
        }
        with pytest.raises(PlanInvalidError) as info:
            expand_compact(payload, schema)
        assert "sections[0].body[0].zz" in info.value.message
        assert "sections[0].body[0].zz" in info.value.details["path"]
        assert isinstance(info.value, InvalidInputError)

    def test_unknown_block_form_is_rejected(self, schema) -> None:
        payload = {
            "title": "T",
            "sections": [{"name": "Main", "body": [{"zz": 1}]}],
        }
        with pytest.raises(PlanInvalidError) as info:
            expand_compact(payload, schema)
        assert "sections[0].body[0]" in info.value.message

    def test_unknown_format_is_rejected(self, schema) -> None:
        payload = {
            "title": "T",
            "sections": [
                {
                    "name": "Main",
                    "body": [
                        {
                            "p": [
                                {
                                    "f": "MainData.Quotation.QuotationId",
                                    "fmt": "bogus",
                                }
                            ]
                        }
                    ],
                }
            ],
        }
        with pytest.raises(PlanInvalidError) as info:
            expand_compact(payload, schema)
        assert info.value.details["path"].endswith(".p[0].fmt")
        assert "unknown format" in info.value.message

    def test_unknown_top_level_key_is_rejected(self, schema) -> None:
        payload = {"title": "T", "sections": [], "metadata": {}}
        with pytest.raises(PlanInvalidError) as info:
            expand_compact(payload, schema)
        assert info.value.details["path"] == "$.metadata"


class TestTableExpansion:
    def test_columns_expand_to_one_cell_each(self, schema) -> None:
        payload = {
            "title": "T",
            "sections": [
                {
                    "name": "Main",
                    "body": [
                        {
                            "tbl": {
                                "repeat": "MainData.QuotationLines.Line",
                                "alias": "line",
                                "cols": [
                                    {"h": "Description", "f": "line.Description"},
                                    {
                                        "h": "Amount",
                                        "f": "line.LineAmount",
                                        "fmt": "number",
                                        "d": 2,
                                    },
                                    {
                                        "h": "Qty",
                                        "f": "line.Quantity",
                                        "fmt": "number",
                                        "d": 0,
                                    },
                                ],
                            }
                        }
                    ],
                }
            ],
        }
        table = expand_compact(payload, schema).sections[0].body[0]
        assert isinstance(table, Table)
        assert len(table.columns) == 3
        assert table.row_template is not None
        assert len(table.row_template) == 3
        assert [cell.blocks[0].runs[0].path for cell in table.row_template] == [
            "line.Description",
            "line.LineAmount",
            "line.Quantity",
        ]
        assert table.columns[0].width_mm == 62.0
        assert table.columns[1].width_mm == 30.0
        assert table.columns[2].width_mm == 24.0
        assert table.columns[1].alignment is Alignment.RIGHT
        amount = table.row_template[1].blocks[0].runs[0]
        assert isinstance(amount, FieldBinding)
        assert amount.format is ValueFormat.NUMBER
        assert amount.decimals == 2
        assert amount.style is not None
        assert amount.style.alignment is Alignment.RIGHT

    def test_static_rows_use_the_cell_shorthand(self, schema) -> None:
        payload = {
            "title": "T",
            "sections": [
                {
                    "name": "Main",
                    "body": [
                        {
                            "tbl": {
                                "cols": [{"h": "Label", "f": "x"}],
                                "rows": [
                                    ["Hello"],
                                    [{"f": "MainData.Quotation.QuotationId"}],
                                    [{"p": ["Nested"]}],
                                ],
                            }
                        }
                    ],
                }
            ],
        }
        table = expand_compact(payload, schema).sections[0].body[0]
        assert isinstance(table, Table)
        assert len(table.rows) == 3
        assert table.rows[0].cells[0].blocks[0].runs[0].text == "Hello"
        assert table.rows[1].cells[0].blocks[0].runs[0].kind == "field"
        assert table.rows[2].cells[0].blocks[0].runs[0].text == "Nested"


# --------------------------------------------------------------------------- #
# Planner integration
# --------------------------------------------------------------------------- #
class TestPlannerCompact:
    def test_mock_provider_still_works_end_to_end(
        self, planner: TemplatePlanner, schema, quotation_request
    ) -> None:
        outcome = _run(
            planner.plan(
                schema,
                quotation_request,
                provider="mock",
                options=PlanOptions(compact_ir=True),
            )
        )
        assert outcome.document.sections
        assert outcome.mapping.counts()["invalid"] == 0
        report = validate_document(outcome.document, schema)
        assert report.can_compile

    def test_compact_schema_and_prompt_are_used(self, schema) -> None:
        gateway = _FakeGateway([_compact_payload()])
        planner = TemplatePlanner(gateway)  # type: ignore[arg-type]
        outcome = _run(
            planner.plan(
                schema,
                "Create a sales quotation.",
                provider="gemini",
                options=PlanOptions(compact_ir=True),
            )
        )

        call = gateway.calls[0]
        assert isinstance(call["schema"], dict)
        assert call["schema"]["title"] == COMPACT_V2_SCHEMA_TITLE
        assert call["schema"] == compact_schema_v2()
        assert call["messages"][0].content == COMPACT_V2_SYSTEM_PROMPT
        assert outcome.document.metadata.template_name == COMPACT_TEMPLATE_NAME
        assert outcome.document.sections[0].body

    def test_compact_repair_reuses_the_schema_and_reports_the_path(self, schema) -> None:
        invalid = {"t": "T", "s": [{"n": "Main", "b": [["zz", 1]]}]}
        gateway = _FakeGateway([invalid, _compact_payload()])
        planner = TemplatePlanner(gateway)  # type: ignore[arg-type]
        outcome = _run(
            planner.plan(
                schema,
                "Create a sales quotation.",
                provider="gemini",
                options=PlanOptions(compact_ir=True, max_repair_attempts=1),
            )
        )

        assert len(gateway.calls) == 2
        assert all(call["schema"]["title"] == COMPACT_V2_SCHEMA_TITLE for call in gateway.calls)
        repair = gateway.calls[1]["messages"][-1].content
        assert "$.s[0].b[0][0]" in repair
        assert outcome.document.sections[0].body

    def test_revision_replans_compact_documents_with_compact_mode(self, schema) -> None:
        compact_document = expand_compact_v2(_compact_payload(), schema)
        gateway = _FakeGateway([_compact_payload()])
        planner = TemplatePlanner(gateway)  # type: ignore[arg-type]
        _run(
            planner.revise(
                schema,
                compact_document,
                "Add a friendly introduction paragraph.",
                provider="gemini",
            )
        )
        assert gateway.calls
        assert gateway.calls[0]["schema"]["title"] == COMPACT_V2_SCHEMA_TITLE

    def test_v1_compact_version_keeps_the_readable_format(self, schema) -> None:
        gateway = _FakeGateway([_compact_v1_payload()])
        planner = TemplatePlanner(gateway)  # type: ignore[arg-type]
        outcome = _run(
            planner.plan(
                schema,
                "Create a sales quotation.",
                provider="gemini",
                options=PlanOptions(compact_ir=True, compact_version="v1"),
            )
        )
        assert gateway.calls[0]["schema"] == compact_schema()
        assert gateway.calls[0]["messages"][0].content == COMPACT_SYSTEM_PROMPT
        assert outcome.document.sections[0].body


# --------------------------------------------------------------------------- #
# API/service auto-enable
# --------------------------------------------------------------------------- #
class TestApiAutoCompact:
    def test_plan_options_default_is_full_ir(self) -> None:
        assert PlanOptions().compact_ir is False
        assert PlanOptions().compact_version == "v2"

    def test_plan_request_default_is_auto(self) -> None:
        from docentric_copilot.api.schemas import PlanRequest

        request = PlanRequest(
            source_id="src_00000000000000000000",
            prompt="Create a sales quotation.",
        )
        assert request.compact_ir is None

    def test_gemini_is_auto_compact_in_the_service_path(self, schema) -> None:
        gateway = _FakeGateway([_compact_payload()])
        service = TemplateService(gateway=gateway, settings=get_settings())  # type: ignore[arg-type]
        outcome, report = _run(
            service.plan(
                schema,
                "Create a sales quotation.",
                provider="gemini",
                model="gemini-3.6-flash",
            )
        )
        assert isinstance(gateway.calls[0]["schema"], dict)
        assert gateway.calls[0]["schema"]["title"] == COMPACT_V2_SCHEMA_TITLE
        assert outcome.document.metadata.template_name == COMPACT_TEMPLATE_NAME
        assert report.can_compile

    def test_plan_endpoint_auto_compacts_gemini(
        self, tmp_path: Path, quotation_path: Path, quotation_request: str
    ) -> None:
        settings = dataclasses.replace(get_settings(), data_dir=tmp_path / "api-data")
        gateway = _FakeGateway([_compact_payload()])
        service = TemplateService(gateway=gateway, settings=settings)  # type: ignore[arg-type]
        app = create_app(settings, service=service)
        with TestClient(app) as client:
            upload = client.post(
                "/api/v1/sources",
                files={
                    "file": (
                        quotation_path.name,
                        quotation_path.read_bytes(),
                        "application/octet-stream",
                    )
                },
            )
            assert upload.status_code == 201, upload.text
            plan = client.post(
                "/api/v1/templates/plan",
                json={
                    "source_id": upload.json()["source_id"],
                    "prompt": quotation_request,
                    "provider": "gemini",
                    "model": "gemini-3.6-flash",
                },
            )
        assert plan.status_code == 200, plan.text
        body = plan.json()
        assert body["ir"]["metadata"]["template_name"] == COMPACT_TEMPLATE_NAME
        assert isinstance(gateway.calls[0]["schema"], dict)
        assert gateway.calls[0]["schema"]["title"] == COMPACT_V2_SCHEMA_TITLE

    def test_explicit_false_override_keeps_full_ir(self, schema, quotation_request) -> None:
        gateway = _FakeGateway([build_document(schema, quotation_request).model_dump(mode="json")])
        service = TemplateService(gateway=gateway, settings=get_settings())  # type: ignore[arg-type]
        _run(
            service.plan(
                schema,
                quotation_request,
                provider="gemini",
                model="gemini-3.6-flash",
                compact_ir=False,
            )
        )
        assert gateway.calls[0]["schema"] is Document

    def test_non_gemini_is_not_auto_compact(self, schema, quotation_request) -> None:
        gateway = _FakeGateway([build_document(schema, quotation_request).model_dump(mode="json")])
        service = TemplateService(gateway=gateway, settings=get_settings())  # type: ignore[arg-type]
        _run(service.plan(schema, quotation_request, provider="openai", model="gpt-5"))
        assert gateway.calls[0]["schema"] is Document


# --------------------------------------------------------------------------- #
# v2 ultra-compact format
# --------------------------------------------------------------------------- #
def _v2_full_feature_payload() -> dict[str, Any]:
    return {
        "t": "Sales Quotation",
        "l": "en",
        "s": [
            {
                "n": "Main",
                "b": [
                    ["h", 1, "Sales Quotation"],
                    [
                        "p",
                        "Quotation ",
                        {"f": "MainData.Quotation.QuotationId"},
                        " · ",
                        {"f": "MainData.Quotation.QuotationDate", "fmt": "d"},
                    ],
                    ["img", "GeneralData.Company.CompanyLogo", 42, "Company logo"],
                    [
                        "tbl",
                        "MainData.QuotationLines.Line",
                        [
                            ["SKU", "line.ItemId"],
                            ["Description", "line.Description"],
                            ["Qty", "line.Quantity", "n", 0],
                            ["Amount", "line.LineAmount", None, "n", 2, "r"],
                        ],
                    ],
                    [
                        "if",
                        "MainData.Quotation.Customer.IsEU",
                        "eq",
                        True,
                        [["p", "EU customer"]],
                        [["p", "Non-EU customer"]],
                    ],
                    ["pb"],
                ],
                "h": [["img", "GeneralData.Company.CompanyLogo"]],
                "f": [["p", {"f": "GeneralData.Company.Name"}]],
            }
        ],
    }


class TestExpandCompactV2:
    def test_full_feature_payload_becomes_a_valid_document(self, schema) -> None:
        document = expand_compact_v2(_v2_full_feature_payload(), schema)

        assert isinstance(document, Document)
        assert document.title == "Sales Quotation"
        assert document.language == "en"
        assert document.metadata.template_name == COMPACT_TEMPLATE_NAME
        assert document.metadata.source_schema_id == schema.schema_id
        assert document.page.margin_top_mm == 20.0

        body = document.sections[0].body
        assert [block.kind for block in body] == [
            "heading",
            "paragraph",
            "image",
            "table",
            "conditional",
            "page_break",
        ]
        assert isinstance(body[1], Paragraph)
        assert body[1].runs[1].path == "MainData.Quotation.QuotationId"
        assert body[1].runs[3].format is ValueFormat.DATE_ISO
        assert isinstance(body[2], ImageBinding) and body[2].width_mm == 42
        table = body[3]
        assert isinstance(table, Table)
        assert table.repeat is not None and table.repeat.alias == "line"
        assert table.row_template is not None and len(table.row_template) == 4
        conditional = body[4]
        assert isinstance(conditional, Conditional)
        assert conditional.condition.operator.value == "equals"
        assert conditional.else_blocks
        assert document.sections[0].header and document.sections[0].footer

        report = validate_document(document, schema)
        assert report.can_compile
        assert report.statuses()["structural"] == "passed"
        assert report.statuses()["semantic"] == "passed"

    def test_defaults_are_filled_by_the_expander(self, schema) -> None:
        payload = {
            "t": "T",
            "s": [
                {
                    "n": "Main",
                    "b": [
                        [
                            "tbl",
                            "MainData.QuotationLines.Line",
                            [["Amount", "line.LineAmount", "n", 2]],
                        ]
                    ],
                }
            ],
        }
        document = expand_compact_v2(payload, schema)
        table = document.sections[0].body[0]
        assert isinstance(table, Table)
        assert document.language == "en"
        assert table.show_header is True
        assert table.repeat is not None and table.repeat.alias == "line"
        assert table.columns[0].width_mm == 30.0
        assert table.columns[0].alignment is Alignment.RIGHT
        binding = table.row_template[0].blocks[0].runs[0]
        assert isinstance(binding, FieldBinding)
        assert binding.format is ValueFormat.NUMBER and binding.decimals == 2
        assert binding.style is not None and binding.style.alignment is Alignment.RIGHT

    def test_v2_binds_every_expected_path(self, schema) -> None:
        v1_document = expand_compact(_full_feature_payload(), schema)
        v2_document = expand_compact_v2(_v2_full_feature_payload(), schema)
        assert [block.kind for block in v1_document.sections[0].body] == [
            block.kind for block in v2_document.sections[0].body
        ]
        assert set(absolute_bindings(v2_document, schema)) == {
            "GeneralData.Company.CompanyLogo",
            "GeneralData.Company.Name",
            "MainData.Quotation.Customer.IsEU",
            "MainData.Quotation.QuotationDate",
            "MainData.Quotation.QuotationId",
            "MainData.QuotationLines.Line",
            "MainData.QuotationLines.Line.Description",
            "MainData.QuotationLines.Line.ItemId",
            "MainData.QuotationLines.Line.LineAmount",
            "MainData.QuotationLines.Line.Quantity",
        }

    def test_expanded_document_round_trips_through_the_full_ir_passthrough(self, schema) -> None:
        document = expand_compact_v2(_v2_full_feature_payload(), schema)
        restored = expand_compact_v2(document.model_dump(mode="json"), schema)
        assert restored.model_dump(mode="json") == document.model_dump(mode="json")

    def test_conditional_accepts_long_operator_and_omits_else(self, schema) -> None:
        payload = {
            "t": "T",
            "s": [
                {
                    "n": "Main",
                    "b": [
                        [
                            "if",
                            "MainData.Quotation.Customer.IsEU",
                            "equals",
                            True,
                            [["p", "EU"]],
                        ],
                        [
                            "if",
                            "MainData.Quotation.Customer.IsEU",
                            "notnull",
                            None,
                            [["p", "has flag"]],
                        ],
                    ],
                }
            ],
        }
        document = expand_compact_v2(payload, schema)
        first, second = document.sections[0].body
        assert isinstance(first, Conditional) and first.else_blocks is None
        assert isinstance(second, Conditional)
        assert second.condition.operator.value == "not_null"

    def test_repeat_block_derives_its_alias(self, schema) -> None:
        payload = {
            "t": "T",
            "s": [
                {
                    "n": "Main",
                    "b": [
                        [
                            "rep",
                            "MainData.QuotationLines.Line",
                            [["p", "Item ", {"f": "line.ItemId"}]],
                        ]
                    ],
                }
            ],
        }
        repeat = expand_compact_v2(payload, schema).sections[0].body[0]
        assert isinstance(repeat, Repeat)
        assert repeat.alias == "line"
        assert repeat.blocks[0].kind == "paragraph"

    def test_unknown_block_object_is_rejected(self, schema) -> None:
        payload = {"t": "T", "s": [{"n": "Main", "b": [{"p": ["x"]}]}]}
        with pytest.raises(PlanInvalidError) as info:
            expand_compact_v2(payload, schema)
        assert "$.s[0].b[0]" in info.value.message
        assert "block array" in info.value.message

    def test_unknown_form_is_rejected_with_its_path(self, schema) -> None:
        payload = {"t": "T", "s": [{"n": "Main", "b": [["zz", 1]]}]}
        with pytest.raises(PlanInvalidError) as info:
            expand_compact_v2(payload, schema)
        assert info.value.details["path"] == "$.s[0].b[0][0]"
        assert "unknown block form" in info.value.message

    def test_wrong_heading_arity_is_rejected(self, schema) -> None:
        payload = {"t": "T", "s": [{"n": "Main", "b": [["h", 1]]}]}
        with pytest.raises(PlanInvalidError) as info:
            expand_compact_v2(payload, schema)
        assert info.value.details["path"] == "$.s[0].b[0]"

    def test_unknown_field_run_key_is_rejected(self, schema) -> None:
        payload = {
            "t": "T",
            "s": [
                {
                    "n": "Main",
                    "b": [
                        ["p", {"f": "MainData.Quotation.QuotationId", "style": "bold"}],
                    ],
                }
            ],
        }
        with pytest.raises(PlanInvalidError) as info:
            expand_compact_v2(payload, schema)
        assert info.value.details["path"] == "$.s[0].b[0][1].style"

    def test_empty_paragraph_is_a_spacer(self, schema) -> None:
        payload = {"t": "T", "s": [{"n": "Main", "b": [["p"], ["p", "x"]]}]}
        document = expand_compact_v2(payload, schema)
        assert document.sections[0].body[0].kind == "paragraph"
        assert document.sections[0].body[0].runs == []
        assert document.sections[0].body[1].runs[0].text == "x"

    def test_show_header_may_precede_the_columns(self, schema) -> None:
        payload = {
            "t": "T",
            "s": [
                {
                    "n": "Main",
                    "b": [
                        [
                            "tbl",
                            "MainData.QuotationLines.Line",
                            False,
                            [["Amount", "line.LineAmount", "n", 2]],
                        ]
                    ],
                }
            ],
        }
        table = expand_compact_v2(payload, schema).sections[0].body[0]
        assert isinstance(table, Table)
        assert table.show_header is False
        assert len(table.columns) == 1

    def test_v1_run_key_aliases_are_accepted(self, schema) -> None:
        payload = {
            "t": "T",
            "s": [
                {
                    "n": "Main",
                    "b": [
                        [
                            "p",
                            {
                                "f": "MainData.Quotation.TotalAmount",
                                "fmt": "n",
                                "d": 2,
                                "align": "r",
                            },
                        ]
                    ],
                }
            ],
        }
        run = expand_compact_v2(payload, schema).sections[0].body[0].runs[0]
        assert isinstance(run, FieldBinding)
        assert run.decimals == 2
        assert run.style is not None and run.style.alignment is Alignment.RIGHT

    def test_unknown_format_is_rejected(self, schema) -> None:
        payload = {
            "t": "T",
            "s": [{"n": "Main", "b": [["p", {"f": "MainData.Quotation.QuotationId", "fmt": "x"}]]}],
        }
        with pytest.raises(PlanInvalidError) as info:
            expand_compact_v2(payload, schema)
        assert info.value.details["path"] == "$.s[0].b[0][1].fmt"
        assert "unknown format" in info.value.message

    def test_extra_column_item_is_rejected(self, schema) -> None:
        payload = {
            "t": "T",
            "s": [
                {
                    "n": "Main",
                    "b": [
                        [
                            "tbl",
                            "MainData.QuotationLines.Line",
                            [["Amount", "line.LineAmount", 30, "n", 2, "r", "extra"]],
                        ]
                    ],
                }
            ],
        }
        with pytest.raises(PlanInvalidError) as info:
            expand_compact_v2(payload, schema)
        assert info.value.details["path"].endswith("[2][0]")

    def test_static_table_without_a_collection_is_rejected(self, schema) -> None:
        payload = {
            "t": "T",
            "s": [{"n": "Main", "b": [["tbl", None, [["A", "MainData.Quotation.QuotationId"]]]]}],
        }
        with pytest.raises(PlanInvalidError) as info:
            expand_compact_v2(payload, schema)
        assert info.value.details["path"] == "$.s[0].b[0][1]"

    def test_notnull_with_a_value_is_rejected(self, schema) -> None:
        payload = {
            "t": "T",
            "s": [
                {
                    "n": "Main",
                    "b": [
                        [
                            "if",
                            "MainData.Quotation.Customer.IsEU",
                            "notnull",
                            True,
                            [["p", "x"]],
                        ]
                    ],
                }
            ],
        }
        with pytest.raises(PlanInvalidError) as info:
            expand_compact_v2(payload, schema)
        assert info.value.details["path"] == "$.s[0].b[0][3]"

    def test_unknown_top_level_key_is_rejected(self, schema) -> None:
        payload = {"t": "T", "s": [], "title": "T"}
        with pytest.raises(PlanInvalidError) as info:
            expand_compact_v2(payload, schema)
        assert info.value.details["path"] == "$.title"
