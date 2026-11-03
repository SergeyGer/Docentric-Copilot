"""Pricing honesty, routing traces, benchmark arithmetic and recommendation."""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from docentric_copilot.api.app import create_app
from docentric_copilot.api.routing import (
    build_trace,
    decide,
    new_run_id,
    trace_document,
    write_trace,
)
from docentric_copilot.config import ProviderSettings, get_settings
from docentric_copilot.ddsp_parser import parse_ddsp
from docentric_copilot.evaluation import (
    EvaluationCase,
    ProviderScore,
    aggregate_cost,
    display_cost,
    evaluate,
    field_metrics,
    percentile,
    quality_score,
    recommend_provider,
)
from docentric_copilot.llm import estimate_cost, price_for
from docentric_copilot.planner import Complexity, RouteDecision
from fastapi.testclient import TestClient

from tests.conftest import EXAMPLES


def _quotation_schema():
    package = EXAMPLES / "quotation" / "sales-quotation.ddsp"
    return parse_ddsp(package.read_bytes(), package.name).schema


# --------------------------------------------------------------------------- #
# Pricing
# --------------------------------------------------------------------------- #
def test_unknown_price_is_none_not_zero() -> None:
    price, known = price_for("future-model-without-a-price")
    assert price is None and known is False
    assert estimate_cost("future-model-without-a-price", 1000, 1000) is None


def test_mock_is_genuinely_free() -> None:
    assert estimate_cost("mock-planner-v1", 1000, 1000) == 0.0
    assert aggregate_cost([0.0]) == 0.0


def test_aggregate_cost_is_na_when_any_price_is_unknown() -> None:
    assert aggregate_cost([0.1, 0.2]) == pytest.approx(0.3)
    assert aggregate_cost([0.1, None]) is None
    assert aggregate_cost([]) is None
    assert display_cost(None) == "N/A"
    assert display_cost(0.0) == "$0.000000"


def test_compare_helper_renders_unknown_as_na() -> None:
    from docentric_copilot.api.routes.quality import _usage_cost

    class Usage:
        estimated_cost_usd = None

    class Generation:
        usage = Usage()
        provider = "openai"

    assert _usage_cost(Generation()) is None


def test_evaluation_cost_metric_is_na_for_unknown_prices() -> None:
    known = EvaluationCase(
        case_id="a",
        schema_id="s",
        prompt="p",
        requirements=1,
        covered_requirements=1,
        compiled=True,
        cost_usd=0.5,
    )
    unknown = EvaluationCase(
        case_id="b",
        schema_id="s",
        prompt="p",
        requirements=1,
        covered_requirements=1,
        compiled=True,
        cost_usd=None,
    )
    report = evaluate([known, unknown])
    metric = report.metrics["cost_per_valid_template_usd"]
    assert metric.value is None
    assert metric.display == "n/a"


def test_field_metrics_handle_empty_denominators() -> None:
    precision, recall, tp = field_metrics([], ["A"])
    assert precision == 0.0 and recall is None and tp == 0
    precision, recall, tp = field_metrics(["A", "B"], ["A", "C"])
    assert precision == 0.5 and recall == 0.5 and tp == 1


def test_percentile_linear_interpolation() -> None:
    assert percentile([], 0.5) is None
    assert percentile([10.0], 0.95) == 10.0
    assert percentile([10.0, 20.0], 0.5) == 15.0


# --------------------------------------------------------------------------- #
# Recommendation
# --------------------------------------------------------------------------- #
def test_recommendation_is_quality_first() -> None:
    scores = [
        ProviderScore("cheap", "m", quality=0.6, cost_usd=0.01, latency_p50_ms=10),
        ProviderScore("good", "m", quality=0.9, cost_usd=0.20, latency_p50_ms=90),
    ]
    assert recommend_provider(scores) == "good"


def test_recommendation_uses_budget_then_latency() -> None:
    scores = [
        ProviderScore("slow-cheap", "m", quality=0.8, cost_usd=0.01, latency_p50_ms=400),
        ProviderScore("fast-cheap", "m", quality=0.8, cost_usd=0.01, latency_p50_ms=100),
        ProviderScore("fast-expensive", "m", quality=0.8, cost_usd=0.09, latency_p50_ms=50),
        ProviderScore("unpriced", "m", quality=0.8, cost_usd=None, latency_p50_ms=1),
    ]
    assert recommend_provider(scores) == "fast-cheap"


def test_recommendation_refuses_when_nothing_validates() -> None:
    scores = [ProviderScore("a", "m", quality=0.0, cost_usd=0.0, latency_p50_ms=1)]
    assert recommend_provider(scores) is None


def test_quality_score_is_gated_by_validation() -> None:
    assert quality_score(precision=1.0, recall=1.0, coverage=1.0, validation_pass_rate=0.0) == 0.0
    assert quality_score(precision=1.0, recall=1.0, coverage=1.0, validation_pass_rate=1.0) == 1.0


# --------------------------------------------------------------------------- #
# Routing decisions and traces
# --------------------------------------------------------------------------- #
def test_decide_routes_one_requirement_against_configured_providers() -> None:
    settings = dataclasses.replace(
        get_settings(),
        providers={
            "mock": ProviderSettings(
                name="mock", api_key="deterministic", default_model="mock-planner-v1"
            ),
            "openai": ProviderSettings(name="openai", api_key="k", default_model="gpt-6-sol"),
            "gemini": ProviderSettings(
                name="gemini", api_key="k", default_model="gemini-3.1-flash-lite"
            ),
        },
    )
    decision, requirements = decide(_quotation_schema(), "Add the company name.", settings)
    # The quotation schema has one collection, so the observable facts say
    # "standard", not "simple"; the balanced tier prefers OpenAI.
    assert decision.complexity is Complexity.STANDARD
    assert decision.provider == "openai"
    assert decision.fallback_used is False
    assert requirements == 1


def test_trace_marks_match_and_fallback() -> None:
    decision = RouteDecision(
        complexity=Complexity.SIMPLE,
        provider="gemini",
        model="gemini-3.1-flash-lite",
        budget_usd=0.02,
        fallback_used=False,
    )
    now = datetime.now(UTC)
    trace = build_trace(
        run_id="run_test",
        decision=decision,
        started_at=now,
        finished_at=now + timedelta(seconds=1),
        prompt="Add the company name.",
        generation=None,
        actual_provider="gemini",
        actual_model="gemini-3.1-flash-lite",
    )
    assert trace.match is True and trace.fallback is False
    mismatch = build_trace(
        run_id="run_test2",
        decision=decision,
        started_at=now,
        finished_at=now + timedelta(seconds=1),
        prompt="Add the company name.",
        generation=None,
        actual_provider="mock",
        actual_model="mock-planner-v1",
    )
    assert mismatch.match is False


def test_trace_file_is_sanitized(tmp_path: Path) -> None:
    decision = RouteDecision(
        complexity=Complexity.SIMPLE,
        provider="openai",
        model="gpt-6-sol",
        budget_usd=0.02,
        fallback_used=True,
    )
    now = datetime.now(UTC)
    document = trace_document(
        run_id=new_run_id(),
        decision=decision,
        started_at=now,
        finished_at=now,
        prompt="Use OPENAI_API_KEY=sk-super-secret and print the brief",
        actual_provider="openai",
        actual_model="gpt-6-sol",
        generation=None,
        report=None,
        ir_digest=None,
        request_budget_usd=0.5,
        status="failed",
        error={
            "code": "provider_error",
            "message": "rejected key OPENAI_API_KEY=sk-super-secret",
        },
    )
    settings = dataclasses.replace(get_settings(), routing_trace_dir=tmp_path)
    path = write_trace(settings, document)
    assert path is not None and path.exists()
    text = path.read_text(encoding="utf-8")
    assert "sk-super-secret" not in text
    assert "print the brief" not in text
    payload = json.loads(text)
    assert payload["prompt"]["sha256"]
    assert payload["prompt"]["chars"] > 0
    assert payload["decision"]["provider"] == "openai"


def test_auto_plan_returns_and_persists_a_trace(tmp_path: Path) -> None:
    settings = dataclasses.replace(
        get_settings(),
        data_dir=tmp_path / "data",
        routing_trace_dir=tmp_path / "runs",
        providers={
            "mock": ProviderSettings(
                name="mock", api_key="deterministic", default_model="mock-planner-v1"
            )
        },
    )
    app = create_app(settings)
    with TestClient(app) as client:
        payload = (EXAMPLES / "quotation" / "sales-quotation.ddsp").read_bytes()
        source = client.post(
            "/api/v1/sources",
            files={"file": ("sales-quotation.ddsp", payload, "application/octet-stream")},
        ).json()
        response = client.post(
            "/api/v1/templates/plan",
            json={
                "source_id": source["source_id"],
                "prompt": "Add the company name.",
                "routing": "auto",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        routing = body["routing"]
        assert routing is not None
        assert routing["decision"]["provider"] == "mock"
        assert routing["actual_provider"] == "mock"
        assert routing["match"] is True
        assert routing["fallback"] is True
        assert routing["run_id"].startswith("run_")
        assert routing["started_at"] and routing["finished_at"]
        trace_files = list((tmp_path / "runs").glob("*.json"))
        assert len(trace_files) == 1
        trace = json.loads(trace_files[0].read_text(encoding="utf-8"))
        assert trace["run_id"] == routing["run_id"]
        assert trace["validation_overall"] is not None
        assert trace["usage"]["estimated_cost_usd"] == 0.0
        assert "prompt" in trace and "sha256" in trace["prompt"]


def test_explicit_plan_keeps_the_old_contract(tmp_path: Path) -> None:
    settings = dataclasses.replace(
        get_settings(), data_dir=tmp_path / "data", routing_trace_dir=tmp_path / "runs"
    )
    app = create_app(settings)
    with TestClient(app) as client:
        payload = (EXAMPLES / "quotation" / "sales-quotation.ddsp").read_bytes()
        source = client.post(
            "/api/v1/sources",
            files={"file": ("sales-quotation.ddsp", payload, "application/octet-stream")},
        ).json()
        response = client.post(
            "/api/v1/templates/plan",
            json={"source_id": source["source_id"], "prompt": "Add the company name."},
        )
        assert response.status_code == 200, response.text
        assert response.json()["routing"] is None
        assert not (tmp_path / "runs").exists()
