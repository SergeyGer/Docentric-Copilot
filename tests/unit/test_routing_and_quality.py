"""Adaptive routing, layout quality and the compatibility-gated AX adapter."""

from __future__ import annotations

import asyncio

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
from docentric_copilot.schema_resolver import parse_requirements
from docentric_copilot.template_ir import ImageBinding, TableColumn

from tests.conftest import EXAMPLES

PROMPT = (EXAMPLES / "quotation" / "prompt.txt").read_text()


@pytest.fixture(scope="module")
def planned():
    source = parse_ddsp((EXAMPLES / "quotation" / "sales-quotation.ddsp").read_bytes(), "q.ddsp")
    outcome = asyncio.run(TemplatePlanner(LLMGateway()).plan(source.schema, PROMPT))
    return source, outcome


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
