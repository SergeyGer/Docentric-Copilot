"""Adaptive model routing (Initiative 1).

The router inspects the brief, the schema and the draft mapping, classifies the
task, and picks the cheapest provider that is expected to meet the quality bar.
The deterministic validator remains the final gate: routing never bypasses it.

No provider secrets are read here. The policy names *preferences*; the gateway
reports what is actually configured, and the router falls back to the
deterministic baseline with an explicit reason.
"""

from __future__ import annotations

from enum import Enum

from docentric_copilot.ddsp_parser.models import NormalizedSchema
from docentric_copilot.schema_resolver.requirements import Concept, Requirement
from pydantic import BaseModel, ConfigDict, Field

_MOCK = "mock"
_TIER_PROVIDERS: dict[str, tuple[str, ...]] = {
    "fast": ("gemini", "openai", _MOCK),
    "balanced": ("openai", "anthropic", _MOCK),
    "advanced": ("anthropic", "openai", _MOCK),
}
_TIER_BUDGET_USD: dict[str, float] = {
    "fast": 0.02,
    "balanced": 0.10,
    "advanced": 0.30,
}
_AMBIGUOUS_CONCEPTS = {
    Concept.CUSTOMER_VAT,
    Concept.CUSTOMER_ADDRESS,
    Concept.CUSTOMER_NAME,
}


class Complexity(str, Enum):
    SIMPLE = "simple"
    STANDARD = "standard"
    COMPLEX = "complex"
    AMBIGUOUS = "ambiguous"


class RouteDecision(BaseModel):
    """A reproducible explanation of one routing decision."""

    model_config = ConfigDict(extra="forbid")

    complexity: Complexity
    provider: str
    model: str | None = None
    reason: list[str] = Field(default_factory=list)
    budget_usd: float = Field(ge=0)
    requires_review: bool = False
    fallback_used: bool = False


def routing_policy() -> dict[str, dict[str, object]]:
    """Describe the policy for the UI and the documentation."""
    return {
        "simple": {
            "tier": "fast",
            "providers": list(_TIER_PROVIDERS["fast"]),
            "budget_usd": _TIER_BUDGET_USD["fast"],
            "strategy": "cheapest provider that matches the benchmark quality bar",
        },
        "standard": {
            "tier": "balanced",
            "providers": list(_TIER_PROVIDERS["balanced"]),
            "budget_usd": _TIER_BUDGET_USD["balanced"],
            "strategy": "balanced quality and cost within the budget",
        },
        "complex": {
            "tier": "advanced",
            "providers": list(_TIER_PROVIDERS["advanced"]),
            "budget_usd": _TIER_BUDGET_USD["advanced"],
            "strategy": "strongest available model, stricter validation",
        },
        "ambiguous": {
            "tier": "advanced",
            "providers": list(_TIER_PROVIDERS["advanced"]),
            "budget_usd": _TIER_BUDGET_USD["advanced"],
            "strategy": "analyse, then escalate to human review instead of guessing",
        },
    }


def classify(
    schema: NormalizedSchema,
    requirements: list[Requirement],
    *,
    needs_review: int = 0,
) -> tuple[Complexity, list[str]]:
    """Classify the task from observable facts, never from the prompt alone."""
    reasons: list[str] = []
    ambiguous = [
        item
        for item in requirements
        if item.concept in _AMBIGUOUS_CONCEPTS
        and not item.text.lower().count("customer")
        and not item.text.lower().count("vendor")
    ]
    if needs_review or ambiguous:
        reasons.append(
            f"ambiguous binding(s): {needs_review} flagged, {len(ambiguous)} party-scoped requirement(s)"
        )
        return Complexity.AMBIGUOUS, reasons

    collections = schema.stats().collection_count
    conditionals = sum(1 for item in requirements if item.negated)
    depth = schema.stats().max_depth
    reasons.append(
        f"{len(requirements)} requirement(s), {collections} collection(s), depth {depth}"
    )

    if len(requirements) <= 4 and collections == 0:
        reasons.append("small flat document: a fast model is sufficient")
        return Complexity.SIMPLE, reasons
    if collections > 1 or len(requirements) > 8 or depth >= 4 or conditionals:
        reasons.append("nested collections, many requirements or conditional logic")
        return Complexity.COMPLEX, reasons
    reasons.append("standard commercial document")
    return Complexity.STANDARD, reasons


def route(
    complexity: Complexity,
    *,
    configured: set[str],
    request_review: bool = False,
) -> RouteDecision:
    """Pick a provider from the configured set, falling back deterministically."""
    tier = (
        "fast"
        if complexity is Complexity.SIMPLE
        else "balanced"
        if complexity is Complexity.STANDARD
        else "advanced"
    )
    preference = _TIER_PROVIDERS[tier]
    available = [name for name in preference if name in configured]
    fallback = not available or (available[0] == _MOCK and len(configured) == 1)
    provider = available[0] if available else _MOCK
    reason = [f"tier '{tier}' prefers {', '.join(preference)}"]
    if provider == _MOCK:
        reason.append("deterministic baseline selected: no cloud provider is configured")
    return RouteDecision(
        complexity=complexity,
        provider=provider,
        model=None,
        reason=reason,
        budget_usd=_TIER_BUDGET_USD[tier],
        requires_review=request_review or complexity is Complexity.AMBIGUOUS,
        fallback_used=fallback,
    )


__all__ = [
    "Complexity",
    "RouteDecision",
    "classify",
    "route",
    "routing_policy",
]
