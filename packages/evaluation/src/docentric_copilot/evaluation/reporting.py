"""Shared benchmark arithmetic: costs, percentiles and provider recommendation.

The rules here are deliberately explicit so a report can be reproduced by hand:

* an unknown price is ``None`` (rendered ``N/A``) and never participates as
  ``0.0``;
* the recommendation is lexicographic: quality first, then known budget, then
  latency. An unpriced provider cannot win a budget comparison.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Quality is a weighted sum of the measured field metrics. Validation is a
#: gate, not a bonus: a provider with no validating plan has quality 0.
QUALITY_PRECISION_WEIGHT = 0.4
QUALITY_RECALL_WEIGHT = 0.4
QUALITY_COVERAGE_WEIGHT = 0.2


def display_cost(value: float | None) -> str:
    """Render a cost, preserving the difference between free and unknown."""
    if value is None:
        return "N/A"
    return f"${value:.6f}"


def aggregate_cost(costs: list[float | None]) -> float | None:
    """Sum known costs; one unknown cost makes the total unknown (N/A)."""
    if not costs or any(cost is None for cost in costs):
        return None
    return round(sum(cost for cost in costs if cost is not None), 6)


def free_cost(value: float | None) -> bool:
    """True only for a known, exactly zero cost (the deterministic baseline)."""
    return value is not None and value == 0.0


def field_metrics(
    expected_paths: list[str] | set[str],
    actual_paths: list[str] | set[str],
) -> tuple[float | None, float | None, int]:
    """Return ``(precision, recall, true_positives)`` or ``None`` denominators."""
    expected = set(expected_paths)
    actual = set(actual_paths)
    true_positives = len(expected & actual)
    precision = None if not actual else round(true_positives / len(actual), 6)
    recall = None if not expected else round(true_positives / len(expected), 6)
    return precision, recall, true_positives


def percentile(values: list[float], fraction: float) -> float | None:
    """Linear-interpolated percentile; ``None`` for an empty sample."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    position = (len(ordered) - 1) * min(max(fraction, 0.0), 1.0)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * weight, 3)


def quality_score(
    *,
    precision: float | None,
    recall: float | None,
    coverage: float | None,
    validation_pass_rate: float,
) -> float:
    """One number for ranking: weighted metrics, gated by validation."""
    if validation_pass_rate <= 0:
        return 0.0
    score = (
        QUALITY_PRECISION_WEIGHT * (precision or 0.0)
        + QUALITY_RECALL_WEIGHT * (recall or 0.0)
        + QUALITY_COVERAGE_WEIGHT * (coverage or 0.0)
    )
    return round(score * validation_pass_rate, 6)


@dataclass(frozen=True, slots=True)
class ProviderScore:
    """One provider's measured quality, budget and latency."""

    provider: str
    model: str | None
    quality: float
    cost_usd: float | None
    latency_p50_ms: float | None


def recommendation_key(score: ProviderScore) -> tuple[float, float, float, float]:
    """Sort key: higher quality, then lower known cost, then lower latency.

    Unknown cost sorts after every known cost: it cannot be compared on budget.
    """
    quality = -score.quality
    cost_rank = float("inf") if score.cost_usd is None else score.cost_usd
    latency_rank = score.latency_p50_ms if score.latency_p50_ms is not None else float("inf")
    return quality, cost_rank, latency_rank, 0.0


def recommend_provider(scores: list[ProviderScore]) -> str | None:
    """Return the best provider, or ``None`` when nothing validates."""
    eligible = [score for score in scores if score.quality > 0]
    if not eligible:
        return None
    return min(eligible, key=recommendation_key).provider


__all__ = [
    "QUALITY_COVERAGE_WEIGHT",
    "QUALITY_PRECISION_WEIGHT",
    "QUALITY_RECALL_WEIGHT",
    "ProviderScore",
    "aggregate_cost",
    "display_cost",
    "field_metrics",
    "free_cost",
    "percentile",
    "quality_score",
    "recommend_provider",
    "recommendation_key",
]
