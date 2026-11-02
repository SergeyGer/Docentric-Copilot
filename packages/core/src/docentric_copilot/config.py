"""Process configuration.

All values are read from environment variables exactly once per process. Nothing
in this module ever echoes a secret: :meth:`Settings.public_view` is the only
structure meant to leave the backend boundary.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _load_local_env() -> None:
    """Load a local ``.env`` from the working directory, without overriding the real env."""
    if os.environ.get("DC_ENV") == "test":
        # Tests must never pick up a developer's real keys from .env.
        return
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:  # pragma: no cover - optional convenience
        return
    path = find_dotenv(usecwd=True)
    if path:
        load_dotenv(path, override=False)


_load_local_env()


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def _env_int(name: str, default: int, *, minimum: int = 0, maximum: int | None = None) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value < minimum:
        return minimum
    if maximum is not None and value > maximum:
        return maximum
    return value


def _env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(minimum, value)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    lowered = raw.strip().lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    return default


def _env_list(name: str) -> list[str]:
    raw = os.environ.get(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True, slots=True)
class ProviderSettings:
    """Credentials and defaults for one LLM provider."""

    name: str
    api_key: str | None = None
    base_url: str | None = None
    default_model: str | None = None
    models: tuple[str, ...] = ()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def public_view(self) -> dict[str, object]:
        return {
            "name": self.name,
            "configured": self.configured,
            "default_model": self.default_model,
            "models": list(self.models),
        }


@dataclass(frozen=True, slots=True)
class Limits:
    """Hard safety limits for untrusted input processing."""

    max_ddsp_bytes: int = 10 * 1024 * 1024
    max_uncompressed_bytes: int = 64 * 1024 * 1024
    max_compression_ratio: int = 120
    max_zip_entries: int = 512
    max_xml_nodes: int = 250_000
    max_xml_depth: int = 64
    max_schema_nodes: int = 5_000
    max_ir_blocks: int = 5_000
    max_ir_depth: int = 24
    max_text_length: int = 20_000


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str = "Docentric Copilot API"
    environment: str = "development"
    data_dir: Path = Path(".data")
    limits: Limits = field(default_factory=Limits)
    artifact_ttl_seconds: int = 3600
    cors_origins: tuple[str, ...] = ("http://localhost:3000",)
    enable_docentric_ax_adapter: bool = False
    providers: dict[str, ProviderSettings] = field(default_factory=dict)
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2
    llm_max_generation_cost_usd: float = 0.50
    llm_max_output_tokens: int = 8_000
    log_level: str = "INFO"
    log_json: bool = True

    # ------------------------------------------------------------------ views
    def provider(self, name: str) -> ProviderSettings:
        return self.providers.get(name) or ProviderSettings(name=name)

    @property
    def provider_names(self) -> tuple[str, ...]:
        return tuple(sorted(self.providers))

    def public_view(self) -> dict[str, object]:
        """Safe projection used by ``GET /api/v1/providers`` and startup logs."""
        return {
            "environment": self.environment,
            "docentric_ax_adapter_enabled": self.enable_docentric_ax_adapter,
            "artifact_ttl_seconds": self.artifact_ttl_seconds,
            "providers": [
                p.public_view() for p in sorted(self.providers.values(), key=lambda p: p.name)
            ],
            "limits": {
                "max_ddsp_bytes": self.limits.max_ddsp_bytes,
                "max_uncompressed_bytes": self.limits.max_uncompressed_bytes,
                "max_schema_nodes": self.limits.max_schema_nodes,
            },
        }


def _build_providers() -> dict[str, ProviderSettings]:
    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    return {
        "mock": ProviderSettings(
            name="mock",
            api_key="deterministic",
            default_model="mock-planner-v1",
            models=("mock-planner-v1",),
        ),
        "openai": ProviderSettings(
            name="openai",
            api_key=os.environ.get("OPENAI_API_KEY") or None,
            base_url=_env_str("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            default_model=os.environ.get("DC_OPENAI_MODEL") or None,
            models=tuple(_env_list("DC_OPENAI_MODELS")),
        ),
        "anthropic": ProviderSettings(
            name="anthropic",
            api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
            base_url=_env_str("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1"),
            default_model=os.environ.get("DC_ANTHROPIC_MODEL") or None,
            models=tuple(_env_list("DC_ANTHROPIC_MODELS")),
        ),
        "gemini": ProviderSettings(
            name="gemini",
            api_key=gemini_key or None,
            base_url=_env_str(
                "GEMINI_BASE_URL",
                "https://generativelanguage.googleapis.com/v1beta",
            ),
            default_model=os.environ.get("DC_GEMINI_MODEL") or None,
            models=tuple(_env_list("DC_GEMINI_MODELS")),
        ),
    }


def _build_settings() -> Settings:
    data_dir = Path(_env_str("DC_DATA_DIR", ".data")).expanduser()
    origins = _env_list("DC_CORS_ORIGINS") or ["http://localhost:3000"]
    return Settings(
        environment=_env_str("DC_ENV", "development"),
        data_dir=data_dir,
        limits=Limits(
            max_ddsp_bytes=_env_int("DC_MAX_DDSP_BYTES", 10 * 1024 * 1024, minimum=1024),
            max_uncompressed_bytes=_env_int(
                "DC_MAX_UNCOMPRESSED_BYTES", 64 * 1024 * 1024, minimum=1024
            ),
            max_compression_ratio=_env_int("DC_MAX_COMPRESSION_RATIO", 120, minimum=1),
            max_zip_entries=_env_int("DC_MAX_ZIP_ENTRIES", 512, minimum=1),
            max_xml_nodes=_env_int("DC_MAX_XML_NODES", 250_000, minimum=100),
            max_xml_depth=_env_int("DC_MAX_XML_DEPTH", 64, minimum=4),
            max_schema_nodes=_env_int("DC_MAX_SCHEMA_NODES", 5_000, minimum=10),
            max_ir_blocks=_env_int("DC_MAX_IR_BLOCKS", 5_000, minimum=10),
            max_ir_depth=_env_int("DC_MAX_IR_DEPTH", 24, minimum=2, maximum=64),
            max_text_length=_env_int("DC_MAX_TEXT_LENGTH", 20_000, minimum=100),
        ),
        artifact_ttl_seconds=_env_int("DC_ARTIFACT_TTL_SECONDS", 3600, minimum=60),
        cors_origins=tuple(origins),
        enable_docentric_ax_adapter=_env_bool("DC_ENABLE_AX_ADAPTER", False),
        providers=_build_providers(),
        llm_timeout_seconds=_env_float("DC_LLM_TIMEOUT_SECONDS", 60.0, minimum=1.0),
        llm_max_retries=_env_int("DC_LLM_MAX_RETRIES", 2, minimum=0, maximum=5),
        llm_max_generation_cost_usd=_env_float("DC_LLM_MAX_GENERATION_COST_USD", 0.50, minimum=0.0),
        llm_max_output_tokens=_env_int("DC_LLM_MAX_OUTPUT_TOKENS", 16_000, minimum=256),
        log_level=_env_str("DC_LOG_LEVEL", "INFO").upper(),
        log_json=_env_bool("DC_LOG_JSON", True),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process settings (cached). Tests call ``get_settings.cache_clear()``."""
    return _build_settings()


__all__ = ["Limits", "ProviderSettings", "Settings", "get_settings"]
