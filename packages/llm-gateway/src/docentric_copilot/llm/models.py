"""Provider-independent generation contracts (FR-03, section 5.3 of the SRS)."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class Message(BaseModel):
    """One chat message. Content is never logged."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Role
    content: str = Field(min_length=1, max_length=200_000)


class GenerationSettings(BaseModel):
    """Per-call generation parameters with safe defaults."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = Field(min_length=1, max_length=120)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_output_tokens: int = Field(default=8_000, ge=128, le=100_000)
    timeout_seconds: float = Field(default=60.0, ge=1.0, le=600.0)
    retries: int = Field(default=2, ge=0, le=5)
    budget_usd: float | None = Field(default=0.5, ge=0.0)
    prompt_version: str = Field(default="planner-v1", max_length=40)


class Usage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    #: ``None`` means the model has no entry in the price table. That is not the
    #: same as free: the UI and reports render it as N/A. The deterministic mock
    #: is genuinely free and reports 0.0.
    estimated_cost_usd: float | None = Field(default=None, ge=0.0)

    @property
    def cost_known(self) -> bool:
        return self.estimated_cost_usd is not None

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class GenerationResult(BaseModel):
    """Structured output plus telemetry. ``raw_text`` stays in memory only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    model: str
    content: dict[str, Any]
    usage: Usage = Field(default_factory=Usage)
    latency_ms: int = Field(default=0, ge=0)
    finish_reason: str | None = Field(default=None, max_length=60)
    attempts: int = Field(default=1, ge=1)
    raw_text: str | None = Field(default=None, exclude=True, repr=False)

    def public_view(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "usage": self.usage.model_dump(),
            "latency_ms": self.latency_ms,
            "finish_reason": self.finish_reason,
            "attempts": self.attempts,
        }


__all__ = ["GenerationResult", "GenerationSettings", "Message", "Role", "Usage"]
