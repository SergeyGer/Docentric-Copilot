"""Token pricing used for *estimated* cost telemetry (NFR-06).

Prices change frequently and are not a contract. A model that has no entry in
:data:`PRICES` is **unpriced**, not free: every consumer reports ``None`` / N/A
for an unknown price and only the deterministic mock keeps a measured ``0.0``.
The versioned table and its sources live in ``docs/PRICING.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

PER_MILLION = 1_000_000

#: Bump this whenever :data:`PRICES` changes. Reports quote this value so a
#: number can be traced back to the table that produced it.
PRICING_VERSION = "2026-11-03"
PRICING_AS_OF = "2026-11-03"
PRICING_SOURCE = "docs/PRICING.md"


@dataclass(frozen=True, slots=True)
class Price:
    input_per_mtok: float
    output_per_mtok: float


#: Prefix match, longest prefix wins. Values are USD per million tokens and
#: follow the standard (non-batch, short-context) provider tiers as of
#: :data:`PRICING_AS_OF`.
PRICES: dict[str, Price] = {
    "gpt-4o-mini": Price(0.15, 0.60),
    "gpt-4o": Price(2.50, 10.00),
    "gpt-4.1-mini": Price(0.40, 1.60),
    "gpt-4.1": Price(2.00, 8.00),
    "gpt-6-sol": Price(2.00, 10.00),
    "o4-mini": Price(1.10, 4.40),
    "claude-3-5-haiku": Price(0.80, 4.00),
    "claude-3-5-sonnet": Price(3.00, 15.00),
    "claude-sonnet-4": Price(3.00, 15.00),
    "claude-sonnet-5-5": Price(2.00, 10.00),
    "claude-opus-4": Price(15.00, 75.00),
    "gemini-2.0-flash": Price(0.10, 0.40),
    "gemini-2.5-flash": Price(0.30, 2.50),
    "gemini-2.5-pro": Price(1.25, 10.00),
    "gemini-3-flash-preview": Price(0.50, 3.00),
    "gemini-3.1-flash-lite": Price(0.25, 1.50),
    "gemini-3.1-pro-preview": Price(2.00, 12.00),
    "gemini-3.8-flash": Price(0.75, 3.75),
    "mock-planner": Price(0.0, 0.0),
}


def price_table_metadata() -> dict[str, str]:
    """Version and provenance stamped into benchmark reports."""
    return {
        "pricing_version": PRICING_VERSION,
        "pricing_as_of": PRICING_AS_OF,
        # Short alias used by report consumers that only need the date.
        "as_of": PRICING_AS_OF,
        "pricing_source": PRICING_SOURCE,
    }


def price_for(model: str) -> tuple[Price | None, bool]:
    """Return ``(price, pricing_known)`` for a model identifier."""
    lowered = model.lower()
    matches = [prefix for prefix in PRICES if lowered.startswith(prefix)]
    if not matches:
        return None, False
    best = max(matches, key=len)
    return PRICES[best], True


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Return the estimated USD cost, or ``None`` when the price is unknown.

    Unknown is deliberately distinct from free. Callers must render ``None`` as
    ``N/A`` and must never substitute ``0.0`` for a hosted model.
    """
    price, known = price_for(model)
    if not known or price is None:
        return None
    return round(
        (prompt_tokens / PER_MILLION) * price.input_per_mtok
        + (completion_tokens / PER_MILLION) * price.output_per_mtok,
        6,
    )


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Backward-compatible alias of :func:`estimate_cost`."""
    return estimate_cost(model, prompt_tokens, completion_tokens)


def worst_case_cost_usd(model: str, prompt_tokens: int, max_output_tokens: int) -> float | None:
    return estimate_cost(model, prompt_tokens, max_output_tokens)


__all__ = [
    "PER_MILLION",
    "PRICES",
    "PRICING_AS_OF",
    "PRICING_SOURCE",
    "PRICING_VERSION",
    "Price",
    "estimate_cost",
    "estimate_cost_usd",
    "price_for",
    "price_table_metadata",
    "worst_case_cost_usd",
]
