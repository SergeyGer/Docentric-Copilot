"""Token pricing used for *estimated* cost telemetry (NFR-06).

Prices change frequently and are not a contract. Unknown models are priced at
zero and reported as ``pricing_known == False`` so nobody mistakes the estimate
for an invoice.
"""

from __future__ import annotations

from dataclasses import dataclass

PER_MILLION = 1_000_000


@dataclass(frozen=True, slots=True)
class Price:
    input_per_mtok: float
    output_per_mtok: float


#: Prefix match, longest prefix wins. Values are USD per million tokens.
PRICES: dict[str, Price] = {
    "gpt-4o-mini": Price(0.15, 0.60),
    "gpt-4o": Price(2.50, 10.00),
    "gpt-4.1-mini": Price(0.40, 1.60),
    "gpt-4.1": Price(2.00, 8.00),
    "o4-mini": Price(1.10, 4.40),
    "claude-3-5-haiku": Price(0.80, 4.00),
    "claude-3-5-sonnet": Price(3.00, 15.00),
    "claude-sonnet-4": Price(3.00, 15.00),
    "claude-opus-4": Price(15.00, 75.00),
    "gemini-2.0-flash": Price(0.10, 0.40),
    "gemini-2.5-flash": Price(0.30, 2.50),
    "gemini-2.5-pro": Price(1.25, 10.00),
    "mock-planner": Price(0.0, 0.0),
}


def price_for(model: str) -> tuple[Price | None, bool]:
    """Return ``(price, pricing_known)`` for a model identifier."""
    lowered = model.lower()
    matches = [prefix for prefix in PRICES if lowered.startswith(prefix)]
    if not matches:
        return None, False
    best = max(matches, key=len)
    return PRICES[best], True


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    price, known = price_for(model)
    if not known or price is None:
        return 0.0
    return round(
        (prompt_tokens / PER_MILLION) * price.input_per_mtok
        + (completion_tokens / PER_MILLION) * price.output_per_mtok,
        6,
    )


def worst_case_cost_usd(model: str, prompt_tokens: int, max_output_tokens: int) -> float:
    return estimate_cost_usd(model, prompt_tokens, max_output_tokens)


__all__ = ["PRICES", "Price", "estimate_cost_usd", "price_for", "worst_case_cost_usd"]
