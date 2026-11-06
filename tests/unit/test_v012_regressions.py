"""V012-05 regressions: nested compact tables, alias scopes and structure."""

from __future__ import annotations

from pathlib import Path

import pytest
from docentric_copilot.ddsp_parser import parse_ddsp
from docentric_copilot.docx_compiler import CompileOptions, GenericDocxCompiler
from docentric_copilot.errors import PlanInvalidError
from docentric_copilot.llm import LLMGateway
from docentric_copilot.planner import TemplatePlanner
from docentric_copilot.planner.aliases import resolve_alias_conflicts
from docentric_copilot.planner.compact_ir_v2 import expand_compact_v2
from docentric_copilot.planner.structure import (
    requirement_expects_table,
    structural_findings,
)
from docentric_copilot.template_ir import Repeat, Table
from docentric_copilot.template_validator import ValidationEngine

ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="module")
def quotation():
    path = ROOT / "examples" / "quotation" / "sales-quotation.ddsp"
    return parse_ddsp(path.read_bytes(), path.name)


@pytest.fixture(scope="module")
def service_order():
    path = ROOT / "benchmarks" / "fixtures" / "field-service.ddsp"
    return parse_ddsp(path.read_bytes(), path.name)


def _nested_payload():
    return {
        "t": "Service order",
        "l": "en",
        "s": [
            {
                "n": "Main",
                "b": [
                    [
                        "tbl",
                        "MainData.ServiceOrderLines.Line",
                        [
                            ["Item", "line.ItemId"],
                            {
                                "h": "Tasks",
                                "cell": [
                                    [
                                        "rep",
                                        "line.Tasks.Task",
                                        "task",
                                        [
                                            ["p", {"f": "task.TaskId"}],
                                            ["p", {"f": "task.Hours"}],
                                        ],
                                    ]
                                ],
                            },
                        ],
                        True,
                        "line",
                    ]
                ],
            }
        ],
    }


def test_compact_v2_object_column_expands_to_a_nested_table(service_order) -> None:
    document = expand_compact_v2(_nested_payload(), service_order.schema)
    table = document.sections[0].body[0]
    assert isinstance(table, Table)
    assert table.repeat is not None and table.repeat.alias == "line"
    assert len(table.row_template or []) == 2
    nested = table.row_template[1].blocks[0]
    assert isinstance(nested, Repeat)
    assert nested.alias == "task"
    assert nested.path == "line.Tasks.Task"
    assert nested.blocks

    report = ValidationEngine().validate(
        document, service_order.schema, sample_data=service_order.sample_data
    )
    statuses = report.statuses()
    assert statuses["structural"] == "passed"
    assert statuses["semantic"] == "passed"
    assert statuses["logical"] == "passed"
    assert report.can_compile is True

    compiled = GenericDocxCompiler().compile(
        document,
        service_order.schema,
        CompileOptions(document_name="nested.docx"),
        sample_data=service_order.sample_data,
    )
    assert compiled.content.startswith(b"PK")
    assert structural_findings(document, "Create a service order table with nested tasks") == []


def test_object_column_schema_rejects_unknown_keys(service_order) -> None:
    payload = _nested_payload()
    table = payload["s"][0]["b"][0]
    table[2][1]["unexpected"] = True
    with pytest.raises(PlanInvalidError) as excinfo:
        expand_compact_v2(payload, service_order.schema)
    assert "unknown key" in str(excinfo.value)


def test_duplicate_alias_on_siblings_is_renamed_and_paths_rewritten(quotation) -> None:
    payload = {
        "t": "Quotation",
        "s": [
            {
                "n": "Main",
                "b": [
                    ["rep", "MainData.QuotationLines.Line", [["p", {"f": "line.ItemId"}]]],
                    ["rep", "MainData.QuotationLines.Line", [["p", {"f": "line.Description"}]]],
                ],
            }
        ],
    }
    document = expand_compact_v2(payload, quotation.schema)
    resolved, notes = resolve_alias_conflicts(document)
    repeats = [block for block in resolved.sections[0].body if isinstance(block, Repeat)]
    assert [repeat.alias for repeat in repeats] == ["line", "line_2"]
    second_run = repeats[1].blocks[0].runs[0]
    assert second_run.path == "line_2.Description"
    assert len(notes) == 1
    assert "alias_conflict_resolved" in notes[0]
    assert "line_2" in notes[0]

    report = ValidationEngine().validate(resolved, quotation.schema)
    assert report.statuses()["logical"] == "passed"


def test_duplicate_alias_in_conditional_branches_is_allowed(quotation) -> None:
    payload = {
        "t": "Quotation",
        "s": [
            {
                "n": "Main",
                "b": [
                    [
                        "if",
                        "MainData.Quotation.Customer.IsEU",
                        "eq",
                        True,
                        [["rep", "MainData.QuotationLines.Line", [["p", {"f": "line.ItemId"}]]]],
                        [
                            [
                                "rep",
                                "MainData.QuotationLines.Line",
                                [["p", {"f": "line.Description"}]],
                            ]
                        ],
                    ]
                ],
            }
        ],
    }
    document = expand_compact_v2(payload, quotation.schema)
    resolved, notes = resolve_alias_conflicts(document)
    assert notes == []
    assert resolved == document
    report = ValidationEngine().validate(resolved, quotation.schema)
    assert report.statuses()["logical"] == "passed"


def test_duplicate_alias_in_independent_table_cells_is_allowed(service_order) -> None:
    payload = {
        "t": "Service order",
        "s": [
            {
                "n": "Main",
                "b": [
                    [
                        "tbl",
                        "MainData.ServiceOrderLines.Line",
                        [
                            ["Item", "line.ItemId"],
                            {
                                "h": "A",
                                "cell": [
                                    [
                                        "rep",
                                        "line.Tasks.Task",
                                        [["p", {"f": "task.TaskId"}]],
                                    ]
                                ],
                            },
                            {
                                "h": "B",
                                "cell": [
                                    [
                                        "rep",
                                        "line.Tasks.Task",
                                        [["p", {"f": "task.Hours"}]],
                                    ]
                                ],
                            },
                        ],
                    ]
                ],
            }
        ],
    }
    document = expand_compact_v2(payload, service_order.schema)
    resolved, notes = resolve_alias_conflicts(document)
    assert notes == []
    table = resolved.sections[0].body[0]
    assert isinstance(table, Table)
    assert table.repeat is not None and table.repeat.alias == "line"
    nested_cells = (table.row_template or [])[1:]
    assert len(nested_cells) == 2
    for cell in nested_cells:
        nested = cell.blocks[0]
        assert isinstance(nested, Repeat)
        assert nested.alias == "task"
    report = ValidationEngine().validate(resolved, service_order.schema)
    assert report.statuses()["logical"] == "passed"


def test_duplicate_table_repeat_alias_is_renamed(quotation) -> None:
    payload = {
        "t": "Quotation",
        "s": [
            {
                "n": "Main",
                "b": [
                    [
                        "tbl",
                        "MainData.QuotationLines.Line",
                        [["Item", "line.ItemId"]],
                        True,
                        "line",
                    ],
                    [
                        "tbl",
                        "MainData.QuotationLines.Line",
                        [["Description", "line.Description"]],
                        True,
                        "line",
                    ],
                ],
            }
        ],
    }
    document = expand_compact_v2(payload, quotation.schema)
    resolved, notes = resolve_alias_conflicts(document)
    tables = [block for block in resolved.sections[0].body if isinstance(block, Table)]
    assert [table.repeat.alias for table in tables if table.repeat] == ["line", "line_2"]
    assert tables[1].row_template[0].blocks[0].runs[0].path == "line_2.Description"
    assert len(notes) == 1
    report = ValidationEngine().validate(resolved, quotation.schema)
    assert report.statuses()["logical"] == "passed"


def test_structural_table_requirement_is_detected() -> None:
    assert requirement_expects_table("Create a table with three columns") is True
    assert requirement_expects_table("Erstelle eine Tabelle mit Spalten") is True
    assert requirement_expects_table("Créer un tableau des lignes") is True
    assert requirement_expects_table("Create a table of contents") is False
    assert requirement_expects_table("Create a short letter") is False


def test_structural_validator_rejects_a_repeat_instead_of_a_table(quotation) -> None:
    payload = {
        "t": "Quotation",
        "s": [
            {
                "n": "Main",
                "b": [["rep", "MainData.QuotationLines.Line", [["p", {"f": "line.ItemId"}]]]],
            }
        ],
    }
    document = expand_compact_v2(payload, quotation.schema)
    findings = structural_findings(document, "Create a table of the quotation lines")
    assert [finding["code"] for finding in findings] == ["plan_table_hierarchy"]
    assert findings[0]["severity"] == "error"


def test_structural_validator_rejects_same_collection_wrapper(quotation) -> None:
    payload = {
        "t": "Quotation",
        "s": [
            {
                "n": "Main",
                "b": [
                    [
                        "rep",
                        "MainData.QuotationLines.Line",
                        [
                            [
                                "tbl",
                                "MainData.QuotationLines.Line",
                                [["Item", "line.ItemId"]],
                                True,
                                "line",
                            ]
                        ],
                    ]
                ],
            }
        ],
    }
    document = expand_compact_v2(payload, quotation.schema)
    findings = structural_findings(document, "Create a table of the quotation lines")
    assert any(finding["code"] == "plan_nested_table_wrapper" for finding in findings)


def test_structural_validator_rejects_a_table_without_rows(quotation) -> None:
    payload = {
        "t": "Quotation",
        "s": [
            {
                "n": "Main",
                "b": [
                    [
                        "tbl",
                        "MainData.QuotationLines.Line",
                        [["Item", "line.ItemId"]],
                        True,
                        "line",
                    ]
                ],
            }
        ],
    }
    document = expand_compact_v2(payload, quotation.schema)
    table = document.sections[0].body[0]
    document = document.model_copy(
        update={
            "sections": [
                document.sections[0].model_copy(
                    update={
                        "body": [
                            table.model_copy(update={"row_template": None}),
                        ]
                    }
                )
            ]
        }
    )
    findings = structural_findings(document, "Create a table")
    assert any(finding["code"] == "plan_table_without_rows" for finding in findings)


def test_planner_wires_structural_findings_into_the_typed_error(quotation, monkeypatch) -> None:
    finding = {
        "code": "plan_table_hierarchy",
        "severity": "error",
        "location": "document",
        "message": "synthetic structural finding",
    }
    monkeypatch.setattr(
        "docentric_copilot.planner.service.structural_findings",
        lambda document, requirement: [finding],
    )
    planner = TemplatePlanner(LLMGateway())
    with pytest.raises(PlanInvalidError) as excinfo:
        import asyncio

        asyncio.run(
            planner.plan(
                quotation.schema,
                "Create a table",
                provider="mock",
            )
        )
    assert "requested table structure" in str(excinfo.value)
    assert excinfo.value.details["errors"][0]["code"] == "plan_table_hierarchy"
