"""LLM gateway: one entry point for every provider (section 5.3, FR-03)."""

from __future__ import annotations

from typing import Any

import httpx
from docentric_copilot.config import ProviderSettings, Settings, get_settings
from docentric_copilot.errors import ProviderError, ProviderNotConfiguredError
from docentric_copilot.logging import get_logger
from pydantic import BaseModel, ValidationError

from .models import GenerationResult, GenerationSettings, Message
from .providers import (
    AnthropicProvider,
    BaseHTTPProvider,
    GeminiProvider,
    MockProvider,
    OpenAIProvider,
)

logger = get_logger(__name__)


class LLMGateway:
    """Owns provider construction, telemetry and error normalization."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._providers: dict[str, Any] = {}
        self._client = (
            httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(120.0))
            if transport is not None
            else None
        )
        self._build()

    # ------------------------------------------------------------------ setup
    def _build(self) -> None:
        settings = self._settings
        self._providers = {"mock": MockProvider()}
        for name, provider_settings in settings.providers.items():
            if name == "mock":
                continue
            self._providers[name] = self._make_http_provider(name, provider_settings)

    def _make_http_provider(self, name: str, provider_settings: ProviderSettings) -> Any:
        base_url = provider_settings.base_url or ""
        api_key = provider_settings.api_key
        if name == "openai":
            return OpenAIProvider(api_key=api_key, base_url=base_url, client=self._client)
        if name == "anthropic":
            return AnthropicProvider(api_key=api_key, base_url=base_url, client=self._client)
        if name == "gemini":
            return GeminiProvider(api_key=api_key, base_url=base_url, client=self._client)
        raise ProviderNotConfiguredError(  # pragma: no cover - defensive
            f"Unknown provider '{name}'",
            details={"provider": name},
        )

    # ----------------------------------------------------------------- access
    @property
    def mock(self) -> MockProvider:
        provider = self._providers["mock"]
        assert isinstance(provider, MockProvider)
        return provider

    def get(self, name: str) -> Any:
        provider = self._providers.get(name)
        if provider is None:
            raise ProviderNotConfiguredError(
                f"Provider '{name}' is not supported by this build",
                details={"provider": name, "available": sorted(self._providers)},
            )
        if isinstance(provider, BaseHTTPProvider) and not provider.configured:
            raise ProviderNotConfiguredError(
                f"Provider '{name}' has no API key configured",
                details={"provider": name},
            )
        return provider

    def describe(self) -> list[dict[str, Any]]:
        """Public provider catalogue for ``GET /api/v1/providers``."""
        catalogue: list[dict[str, Any]] = []
        for name in sorted(self._providers):
            provider = self._providers[name]
            provider_settings = self._settings.provider(name)
            configured = bool(getattr(provider, "configured", False))
            catalogue.append(
                {
                    "name": name,
                    "configured": configured,
                    "default_model": provider_settings.default_model,
                    "models": list(provider_settings.models),
                }
            )
        return catalogue

    def resolve_model(self, provider: str, model: str | None) -> str:
        if model:
            return model
        default = self._settings.provider(provider).default_model
        if default:
            return default
        raise ProviderError(
            "A model identifier is required for this provider",
            code="model_required",
            details={"provider": provider},
        )

    # ------------------------------------------------------------- generation
    async def generate_structured(
        self,
        *,
        provider: str,
        model: str | None,
        messages: list[Message],
        schema: type[BaseModel],
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        budget_usd: float | None = None,
    ) -> GenerationResult:
        """Generate JSON validated against ``schema`` through the chosen provider."""
        selected = self.get(provider)
        model_id = self.resolve_model(provider, model)
        settings = GenerationSettings(
            model=model_id,
            temperature=0.0 if temperature is None else temperature,
            max_output_tokens=max_output_tokens or self._settings.llm_max_output_tokens,
            timeout_seconds=self._settings.llm_timeout_seconds,
            retries=self._settings.llm_max_retries,
            budget_usd=self._settings.llm_max_generation_cost_usd
            if budget_usd is None
            else budget_usd,
        )
        try:
            result = await selected.generate_structured(
                messages=messages,
                schema=schema.model_json_schema(mode="validation"),
                settings=settings,
            )
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(
                "The provider failed unexpectedly",
                details={"provider": provider, "error": type(exc).__name__},
            ) from exc

        try:
            schema.model_validate(result.content)
        except ValidationError as exc:
            raise ProviderError(
                "Provider output does not satisfy the required schema",
                code="provider_invalid_output",
                details={
                    "provider": provider,
                    "errors": [
                        {
                            "location": ".".join(str(part) for part in error["loc"]),
                            "message": error["msg"],
                        }
                        for error in exc.errors()[:10]
                    ],
                },
            ) from exc

        logger.info(
            "llm.generation",
            extra={
                "context": {
                    **result.public_view(),
                    "prompt_version": settings.prompt_version,
                    "schema": schema.__name__,
                }
            },
        )
        return result

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()


__all__ = ["LLMGateway"]
