"""AI evaluation metrics (SRS section 8.3).

Compilation success and *verified* compatibility are separate metrics on purpose:
a template that compiles is not a template that Docentric AX has executed.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

ZERO_DIVISION_GUARD = 1e-9


class MetricValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    value: float | None
    numerator: float = 0.0
    denominator: float = 0.0
    definition: str

    @property
    def display(self) -> str:
        if self.value is None:
            return "n/a"
        return f"{self.value:.3f}"


class EvaluationCase(BaseModel):
    """One benchmark task with its ground truth."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=80)
    schema_id: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=5_000)
    expected_paths: list[str] = Field(default_factory=list, max_length=200)
    actual_paths: list[str] = Field(default_factory=list, max_length=200)
    requirements: int = Field(default=0, ge=0)
    covered_requirements: int = Field(default=0, ge=0)
    compiled: bool = False
    clarifications: int = Field(default=0, ge=0)
    corrections: int = Field(default=0, ge=0)
    verified_compatible: bool = False
    cost_usd: float = Field(default=0.0, ge=0.0)

    def true_positives(self) -> int:
        return len(set(self.expected_paths) & set(self.actual_paths))


class MetricsReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = "mock"
    model: str | None = None
    cases: list[EvaluationCase] = Field(default_factory=list)
    metrics: dict[str, MetricValue] = Field(default_factory=dict)

    def summary(self) -> dict[str, str]:
        return {name: metric.display for name, metric in self.metrics.items()}


def _metric(name: str, numerator: float, denominator: float, definition: str) -> MetricValue:
    value = None if denominator <= 0 else round(numerator / denominator, 6)
    return MetricValue(
        name=name, value=value, numerator=numerator, denominator=denominator, definition=definition
    )


def evaluate(
    cases: list[EvaluationCase], *, provider: str = "mock", model: str | None = None
) -> MetricsReport:
    """Compute the SRS metrics over a set of evaluated plans."""
    true_positives = sum(case.true_positives() for case in cases)
    selected = sum(len(case.actual_paths) for case in cases)
    expected = sum(len(case.expected_paths) for case in cases)

    metrics = {
        "field_selection_precision": _metric(
            "field_selection_precision",
            true_positives,
            selected,
            "Correct bindings divided by all bindings selected by the planner.",
        ),
        "field_selection_recall": _metric(
            "field_selection_recall",
            true_positives,
            expected,
            "Required fields correctly bound divided by all required fields.",
        ),
        "requirement_coverage": _metric(
            "requirement_coverage",
            sum(case.covered_requirements for case in cases),
            sum(case.requirements for case in cases),
            "Share of user requirements represented in the IR.",
        ),
        "compilation_success_rate": _metric(
            "compilation_success_rate",
            sum(1 for case in cases if case.compiled),
            len(cases),
            "Share of plans that compile without errors.",
        ),
        "clarification_rate": _metric(
            "clarification_rate",
            sum(case.clarifications for case in cases),
            sum(case.requirements for case in cases),
            "Clarification questions per requirement.",
        ),
        "correction_rate": _metric(
            "correction_rate",
            sum(case.corrections for case in cases),
            len(cases),
            "Share of plans that needed manual correction.",
        ),
        "verified_compatibility_rate": _metric(
            "verified_compatibility_rate",
            sum(1 for case in cases if case.verified_compatible),
            len(cases),
            "Share of templates proven to execute in Docentric AX (0 until the gate passes).",
        ),
        "cost_per_valid_template_usd": _metric(
            "cost_per_valid_template_usd",
            sum(case.cost_usd for case in cases),
            max(1, sum(1 for case in cases if case.compiled)),
            "Generation cost divided by the number of successfully validated templates.",
        ),
    }
    return MetricsReport(provider=provider, model=model, cases=cases, metrics=metrics)


__all__ = ["EvaluationCase", "MetricValue", "MetricsReport", "evaluate"]
