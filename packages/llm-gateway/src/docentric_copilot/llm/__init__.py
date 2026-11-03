"""Provider-independent structured generation gateway (FR-03, SRS 5.3)."""

from __future__ import annotations

from .gateway import LLMGateway
from .models import GenerationResult, GenerationSettings, Message, Role, Usage
from .pricing import (
    PRICING_AS_OF,
    PRICING_SOURCE,
    PRICING_VERSION,
    estimate_cost,
    estimate_cost_usd,
    price_for,
    price_table_metadata,
)
from .providers import (
    AnthropicProvider,
    BaseHTTPProvider,
    GeminiProvider,
    MockProvider,
    OpenAIProvider,
    extract_json_object,
    to_gemini_schema,
)

__all__ = [
    "PRICING_AS_OF",
    "PRICING_SOURCE",
    "PRICING_VERSION",
    "AnthropicProvider",
    "BaseHTTPProvider",
    "GeminiProvider",
    "GenerationResult",
    "GenerationSettings",
    "LLMGateway",
    "Message",
    "MockProvider",
    "OpenAIProvider",
    "Role",
    "Usage",
    "estimate_cost",
    "estimate_cost_usd",
    "extract_json_object",
    "price_for",
    "price_table_metadata",
    "to_gemini_schema",
]
