"""Provider-independent structured generation gateway (FR-03, SRS 5.3)."""

from __future__ import annotations

from .gateway import LLMGateway
from .models import GenerationResult, GenerationSettings, Message, Role, Usage
from .pricing import estimate_cost_usd, price_for
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
    "estimate_cost_usd",
    "extract_json_object",
    "price_for",
    "to_gemini_schema",
]
