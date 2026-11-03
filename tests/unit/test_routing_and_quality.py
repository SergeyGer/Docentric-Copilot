"""Adaptive routing, layout quality and the compatibility-gated AX adapter."""

from __future__ import annotations

import asyncio
import copy

import pytest
from docentric_copilot.ddsp_parser import parse_ddsp
from docentric_copilot.docx_compiler import AXAdapter, capability_matrix
from docentric_copilot.errors import UnsupportedTargetError
from docentric_copilot.llm import LLMGateway
from docentric_copilot.planner import (
    Complexity,
    TemplatePlanner,
    analyze_quality,
    classify,
    optimize_layout,
    route,
    routing_policy,
)
from docentric_copilot.planner.quality import (
    QualityStatus,
    estimate_wrapped_lines,
    required_width_mm,
)
from docentric_copilot.schema_resolver import parse_requirements
from docentric_copilot.template_ir import (
    ImageBinding,
    Table,
    TableColumn,
    TableStyle,
)

from tests.conftest import EXAMPLES, ROOT

PROMPT = (EXAMPLES / "quotation" / "prompt.txt").read_text()
DEMO_DIR = ROOT / "services" / "api" / "src" / "docentric_copilot" / "api" / "demo"


@pytest.fixture(scope="module")
def planned():
    source = parse_ddsp((EXAMPLES / "quotation" / "sales-quotation.ddsp").read_bytes(), "q.ddsp")
    outcome = asyncio.run(TemplatePlanner(LLMGateway()).plan(source.schema, PROMPT))
    return source, outcome


@pytest.fixture(scope="module")
def long_items():
    package = DEMO_DIR / "quotation-long-items.ddsp"
    source = parse_ddsp(package.read_bytes(), package.name)
    outcome = asyncio.run(TemplatePlanner(LLMGateway()).plan(source.schema, PROMPT))
    return source, outcome


def _check(report, check_id: str):
    return next(check for check in report.checks if check.id == check_id)


def test_text_fit_estimator_is_deterministic() -> None:
    text = " ".join(
        ["A long product description with normal words and spaces that wraps over several lines"]
        * 3
    )
    lines = estimate_wrapped_lines(text, 62.0, 9.5)
    assert lines == estimate_wrapped_lines(text, 62.0, 9.5)
    assert lines > 4
    assert estimate_wrapped_lines("Short item", 62.0, 9.5) == 1
    assert estimate_wrapped_lines("   ", 62.0, 9.5) == 0
    assert estimate_wrapped_lines(text, 120.0, 9.5) < lines
    assert required_width_mm(198, 9.5) > 62.0


def test_ambiguous_brief_routes_to_review() -> None:
    assert route(Complexity.AMBIGUOUS, configured={"mock"}).requires_review is True
    policy = routing_policy()
    assert policy["complex"]["budget_usd"] > policy["simple"]["budget_usd"]


def test_classification_uses_observable_facts(planned) -> None:
    source, _ = planned
    requirements = parse_requirements(PROMPT)
    complexity, reasons = classify(source.schema, requirements, needs_review=1)
    assert complexity is Complexity.AMBIGUOUS and reasons
    simple, _ = classify(source.schema, parse_requirements("Add the company logo."))
    assert simple in {Complexity.SIMPLE, Complexity.STANDARD}


def test_router_falls_back_to_the_deterministic_baseline() -> None:
    decision = route(Complexity.COMPLEX, configured={"mock"})
    assert decision.provider == "mock" and decision.fallback_used
    assert "deterministic baseline" in " ".join(decision.reason)


def test_quality_report_is_explainable(planned) -> None:
    source, outcome = planned
    report = analyze_quality(outcome.document, source.schema, sample_data=source.sample_data)
    assert report.overall.value in {"passed", "warning"}
    assert {"table_layout", "image_clipping", "typography"} <= {check.id for check in report.checks}
    assert report.metrics.text_width_mm > 0


def test_quality_detects_unbreakable_values(planned) -> None:
    source, outcome = planned
    sample = dict(source.sample_data)
    sample["GeneralData"] = {**sample.get("GeneralData", {}), "Company": {"Name": "X" * 200}}
    report = analyze_quality(outcome.document, source.schema, sample_data=sample)
    broken = [check for check in report.checks if check.id == "content_safety"]
    assert broken and broken[0].status.value == "failed"


def test_text_fit_warns_for_long_item_descriptions(long_items) -> None:
    source, outcome = long_items
    report = analyze_quality(outcome.document, source.schema, sample_data=source.sample_data)
    check = _check(report, "text_fit")
    assert check.status is QualityStatus.WARNING
    assert check.path is not None
    assert check.path.startswith("sections[0].body[")
    assert check.path.endswith(".row_template[1]")
    assert "Description" in check.message
    assert " lines" in check.message


def test_optimize_fixes_long_item_descriptions(long_items) -> None:
    source, outcome = long_items
    result = optimize_layout(outcome.document, source.schema, sample_data=source.sample_data)
    width_fix = next(fix for fix in result.fixes if fix.id == "fit_text_width")
    assert width_fix.path == "sections[0].body[4].columns[1].width_mm"
    assert width_fix.before == 62.0
    assert width_fix.after is not None and width_fix.after > width_fix.before
    font_fix = next(fix for fix in result.fixes if fix.id == "fit_text_font")
    assert font_fix.before == 9.5 and font_fix.after == 9.0
    assert _check(result.after, "text_fit").status is QualityStatus.PASSED
    table = next(
        block
        for block in result.document.sections[0].body
        if isinstance(block, Table) and block.repeat is not None
    )
    declared = sum(column.width_mm or 0 for column in table.columns)
    assert declared <= result.after.metrics.text_width_mm + 0.5


def test_optimize_lowers_table_font_when_width_is_exhausted(planned) -> None:
    source, outcome = planned
    assert source.sample_data is not None
    item_table = next(
        block
        for block in outcome.document.sections[0].body
        if isinstance(block, Table) and block.repeat is not None
    )
    assert item_table.row_template is not None
    table = Table(
        columns=[
            TableColumn(header="Description", width_mm=160.0),
            TableColumn(header="SKU", width_mm=10.0),
        ],
        rows=[],
        repeat=item_table.repeat,
        row_template=[item_table.row_template[1], item_table.row_template[0]],
        show_header=True,
        style=TableStyle(font_size_pt=9.5),
    )
    section = outcome.document.sections[0]
    document = outcome.document.model_copy(
        update={"sections": [section.model_copy(update={"body": [table]})]}
    )
    sample = copy.deepcopy(source.sample_data)
    sample["MainData"]["QuotationLines"]["Line"][0]["Description"] = " ".join(["delivery"] * 45)

    before = analyze_quality(document, source.schema, sample_data=sample)
    assert _check(before, "text_fit").status is QualityStatus.WARNING

    result = optimize_layout(document, source.schema, sample_data=sample)
    font_fixes = [fix for fix in result.fixes if fix.id == "fit_text_font"]
    assert [fix.after for fix in font_fixes] == [9.0, 8.5, 8.0]
    assert all(fix.before is not None for fix in font_fixes)
    assert all(fix.path == "sections[0].body[0].style.font_size_pt" for fix in font_fixes)
    assert _check(result.after, "text_fit").status is QualityStatus.PASSED


def test_optimize_fits_an_oversized_table(planned) -> None:
    source, outcome = planned
    document = outcome.document.model_copy(deep=True)
    section = document.sections[0]
    blocks = []
    for block in section.body:
        if block.kind == "table" and block.repeat is not None:
            block = block.model_copy(
                update={
                    "columns": [TableColumn(header="Wide", width_mm=200.0)] * len(block.columns)
                }
            )
        blocks.append(block)
    document = document.model_copy(
        update={"sections": [section.model_copy(update={"body": blocks})]}
    )
    result = optimize_layout(document, source.schema, sample_data=source.sample_data)
    assert any(fix.id == "fit_table" for fix in result.fixes)
    assert result.after.overall.value != "failed"


def test_optimize_caps_an_oversized_image(planned) -> None:
    source, outcome = planned
    document = outcome.document.model_copy(deep=True)
    section = document.sections[0]
    document = document.model_copy(
        update={
            "sections": [
                section.model_copy(
                    update={
                        "body": [
                            *section.body,
                            ImageBinding(path="GeneralData.Company.CompanyLogo", width_mm=200.0),
                        ]
                    }
                )
            ]
        }
    )
    result = optimize_layout(document, source.schema, sample_data=source.sample_data)
    assert any(fix.id == "fit_image" for fix in result.fixes)


def test_ax_adapter_fails_closed() -> None:
    matrix = capability_matrix()
    assert matrix["status"] == "not_tested" and matrix["verified"] is False
    assert len(matrix["capabilities"]) == 6
    with pytest.raises(UnsupportedTargetError):
        AXAdapter().compile(None)  # type: ignore[arg-type]


def test_unknown_price_is_reported_as_unknown() -> None:
    from docentric_copilot.api.routes.quality import _usage_cost

    class Usage:
        estimated_cost_usd = 0.0

    class Generation:
        usage = Usage()

        def __init__(self, provider: str) -> None:
            self.provider = provider

    assert _usage_cost(Generation("openai")) is None
    assert _usage_cost(Generation("mock")) == 0.0
