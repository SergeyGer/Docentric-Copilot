"""Provider adapters: OpenAI, Anthropic, Gemini and a deterministic mock.

Every adapter speaks the same contract: :meth:`generate_structured` returns a
JSON object that validates against the caller's pydantic model. API differences
(structured output mechanisms, usage fields, tool calling) are contained here and
never leak into the planner.
"""

from __future__ import annotations

import abc
import asyncio
import inspect
import json
import re
import time
from collections.abc import Callable
from typing import Any

import httpx
from docentric_copilot.errors import ProviderError, ProviderNotConfiguredError

from .models import GenerationResult, GenerationSettings, Message, Role, Usage
from .pricing import estimate_cost_usd, price_for, worst_case_cost_usd

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}
_MAX_BODY_CHARS = 400
_MAX_TOKENS_PER_CHAR = 0.35  # rough pre-flight estimate for budget checks


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first JSON object from a model response.

    Handles bare JSON, fenced blocks and leading prose. Raises ``ProviderError``
    with a truncated, redaction-safe reason when nothing parses.
    """
    candidates: list[str] = [text.strip()]
    candidates.extend(match.strip() for match in _JSON_FENCE.findall(text))
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ProviderError(
        "The model did not return a JSON object",
        details={"reason": "structured_output_unparseable", "preview": text[:120]},
    )


def _truncate(value: str, limit: int = _MAX_BODY_CHARS) -> str:
    return value if len(value) <= limit else value[:limit] + "..."


class BaseHTTPProvider(abc.ABC):
    """Shared HTTP plumbing: retries, timeouts, error normalization, telemetry."""

    name: str = "http"
    retry_backoff_seconds: float = 0.5
    max_retry_after_seconds: float = 4.0

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    # ------------------------------------------------------------- transport
    async def _post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        settings: GenerationSettings,
    ) -> httpx.Response:
        attempts = settings.retries + 1
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                if self._client is not None:
                    response = await self._client.post(
                        url, headers=headers, json=payload, timeout=settings.timeout_seconds
                    )
                else:
                    async with httpx.AsyncClient(timeout=settings.timeout_seconds) as client:
                        response = await client.post(url, headers=headers, json=payload)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt >= attempts:
                    raise ProviderError(
                        "The provider did not respond in time",
                        code="provider_timeout",
                        details={"provider": self.name, "attempts": attempt},
                    ) from exc
                await asyncio.sleep(self._backoff(attempt, None))
                continue

            if response.status_code in _RETRYABLE_STATUS and attempt < attempts:
                await asyncio.sleep(self._backoff(attempt, response))
                continue
            if response.status_code >= 400:
                raise ProviderError(
                    "The provider rejected the request",
                    code="provider_bad_response",
                    details={
                        "provider": self.name,
                        "status": response.status_code,
                        "reason": _truncate(response.text),
                    },
                )
            return response

        raise ProviderError(  # pragma: no cover - defensive
            "The provider request failed after retries",
            code="provider_error",
            details={"provider": self.name, "error": str(last_error)[:120]},
        )

    def _backoff(self, attempt: int, response: httpx.Response | None) -> float:
        if response is not None:
            retry_after = response.headers.get("retry-after")
            if retry_after:
                try:
                    return min(float(retry_after), self.max_retry_after_seconds)
                except ValueError:
                    pass
        return min(self.retry_backoff_seconds * (2 ** (attempt - 1)), self.max_retry_after_seconds)

    # ------------------------------------------------------------- interface
    @abc.abstractmethod
    async def generate_structured(
        self,
        *,
        messages: list[Message],
        schema: dict[str, Any],
        settings: GenerationSettings,
    ) -> GenerationResult: ...

    # --------------------------------------------------------------- helpers
    def _ensure_configured(self) -> str:
        if not self._api_key:
            raise ProviderNotConfiguredError(
                f"Provider '{self.name}' has no API key configured",
                details={"provider": self.name, "env_hint": f"{self.name.upper()}_API_KEY"},
            )
        return self._api_key

    def _preflight_budget(
        self, messages: list[Message], settings: GenerationSettings, schema: dict[str, Any]
    ) -> None:
        if settings.budget_usd is None:
            return
        approx_prompt_tokens = int(
            sum(len(message.content) for message in messages) * _MAX_TOKENS_PER_CHAR
            + len(json.dumps(schema)) * 0.5
        )
        worst_case = worst_case_cost_usd(
            settings.model, approx_prompt_tokens, settings.max_output_tokens
        )
        _, known = price_for(settings.model)
        if known and worst_case is not None and worst_case > settings.budget_usd:
            from docentric_copilot.errors import BudgetExceededError

            raise BudgetExceededError(
                "The generation would exceed the configured cost budget",
                details={
                    "provider": self.name,
                    "model": settings.model,
                    "worst_case_usd": round(worst_case, 4),
                    "budget_usd": settings.budget_usd,
                },
            )

    def _result(
        self,
        *,
        content: dict[str, Any],
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
        finish_reason: str | None,
        raw_text: str | None,
        attempts: int = 1,
    ) -> GenerationResult:
        return GenerationResult(
            provider=self.name,
            model=model,
            content=content,
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                estimated_cost_usd=estimate_cost_usd(model, prompt_tokens, completion_tokens),
            ),
            latency_ms=latency_ms,
            finish_reason=finish_reason,
            attempts=attempts,
            raw_text=raw_text,
        )


# --------------------------------------------------------------------------- #
# OpenAI
# --------------------------------------------------------------------------- #
class OpenAIProvider(BaseHTTPProvider):
    name = "openai"

    async def generate_structured(
        self,
        *,
        messages: list[Message],
        schema: dict[str, Any],
        settings: GenerationSettings,
    ) -> GenerationResult:
        api_key = self._ensure_configured()
        self._preflight_budget(messages, settings, schema)
        url = f"{self._base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload: dict[str, Any] = {
            "model": settings.model,
            "messages": [{"role": m.role.value, "content": m.content} for m in messages],
            "temperature": settings.temperature,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "template_ir", "strict": False, "schema": schema},
            },
        }
        if settings.max_output_tokens:
            payload["max_tokens"] = settings.max_output_tokens

        started = time.perf_counter()
        response = None
        for _attempt in range(3):
            try:
                response = await self._post(
                    url, headers=headers, payload=payload, settings=settings
                )
                break
            except ProviderError as exc:
                detail = str(exc.details)
                if "max_tokens" in detail and "Unsupported parameter" in detail:
                    payload.pop("max_tokens", None)
                    payload["max_completion_tokens"] = settings.max_output_tokens
                elif "temperature" in detail and "Unsupported value" in detail:
                    payload.pop("temperature", None)
                elif exc.code == "provider_bad_response" and "response_format" in detail:
                    payload.pop("response_format", None)
                    payload["messages"] = [
                        {
                            "role": "system",
                            "content": "Respond with a single JSON object and no prose.",
                        },
                        *payload["messages"],
                    ]
                else:
                    raise
        if response is None:
            raise ProviderError(
                "The provider rejected the request", details={"provider": self.name}
            )
        latency_ms = int((time.perf_counter() - started) * 1000)

        body = response.json()
        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                "Provider response is missing a completion",
                details={"provider": self.name},
            ) from exc
        usage = body.get("usage") or {}
        finish_reason = body["choices"][0].get("finish_reason")
        if finish_reason == "length":
            raise ProviderError(
                "The model stopped before finishing the document",
                details={
                    "reason": "output_truncated",
                    "hint": "increase DC_LLM_MAX_OUTPUT_TOKENS or use a smaller schema",
                },
            )
        return self._result(
            content=extract_json_object(text or ""),
            model=body.get("model") or settings.model,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            latency_ms=latency_ms,
            finish_reason=finish_reason,
            raw_text=text,
        )


# --------------------------------------------------------------------------- #
# Anthropic
# --------------------------------------------------------------------------- #
class AnthropicProvider(BaseHTTPProvider):
    name = "anthropic"
    API_VERSION = "2023-06-01"

    async def generate_structured(
        self,
        *,
        messages: list[Message],
        schema: dict[str, Any],
        settings: GenerationSettings,
    ) -> GenerationResult:
        api_key = self._ensure_configured()
        self._preflight_budget(messages, settings, schema)
        url = f"{self._base_url}/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": self.API_VERSION,
            "Content-Type": "application/json",
        }
        system = "\n\n".join(message.content for message in messages if message.role is Role.SYSTEM)
        dialogue = [
            {"role": message.role.value, "content": message.content}
            for message in messages
            if message.role is not Role.SYSTEM
        ]
        payload: dict[str, Any] = {
            "model": settings.model,
            "max_tokens": settings.max_output_tokens,
            # Newer Claude models reject `temperature`; the gateway does not need
            # it because validation, not sampling, decides what is acceptable.
            "messages": dialogue,
            "tools": [
                {
                    "name": "emit_template_ir",
                    "description": "Return the template plan as structured data.",
                    "input_schema": schema,
                }
            ],
            "tool_choice": {"type": "tool", "name": "emit_template_ir"},
        }
        if system:
            payload["system"] = system

        started = time.perf_counter()
        try:
            response = await self._post(url, headers=headers, payload=payload, settings=settings)
        except ProviderError as exc:
            # Some newer Claude models reject forced tool choice. Ask the model to
            # use the tool instead of forcing it; validation still decides.
            reason = str(exc.details.get("reason", ""))
            if exc.details.get("status") == 400 and "tool_choice" in reason:
                payload.pop("tool_choice", None)
                response = await self._post(
                    url, headers=headers, payload=payload, settings=settings
                )
            else:
                raise
        latency_ms = int((time.perf_counter() - started) * 1000)

        body = response.json()
        blocks = body.get("content") or []
        tool_input: dict[str, Any] | None = None
        text_parts: list[str] = []
        for block in blocks:
            if block.get("type") == "tool_use" and isinstance(block.get("input"), dict):
                tool_input = block["input"]
            elif block.get("type") == "text":
                text_parts.append(str(block.get("text", "")))
        raw_text = "".join(text_parts)
        if tool_input is None:
            if not raw_text:
                raise ProviderError(
                    "Provider response contains neither tool output nor text",
                    details={"provider": self.name},
                )
            tool_input = extract_json_object(raw_text)
        usage = body.get("usage") or {}
        return self._result(
            content=tool_input,
            model=body.get("model") or settings.model,
            prompt_tokens=int(usage.get("input_tokens", 0)),
            completion_tokens=int(usage.get("output_tokens", 0)),
            latency_ms=latency_ms,
            finish_reason=body.get("stop_reason"),
            raw_text=raw_text or None,
        )


# --------------------------------------------------------------------------- #
# Google Gemini
# --------------------------------------------------------------------------- #
_GEMINI_ALLOWED_KEYS = {
    "type",
    "format",
    "description",
    "nullable",
    "enum",
    "items",
    "properties",
    "required",
    "anyOf",
    "const",
    "minimum",
    "maximum",
    "minItems",
    "minLength",
    "maxLength",
    "pattern",
}

#: Gemini rejects `maxItems` with a bare 400 INVALID_ARGUMENT once the limit is
#: "too large for the schema"; the threshold varies with schema size and is not
#: documented. Omitting the keyword keeps the structural schema and removes the
#: failure mode. Array limits remain enforced by the IR model and validator.
_GEMINI_DROP_KEYS = {"maxItems"}
#: A discriminated union of block kinds cannot be sent as-is (Gemini accepts
#: `anyOf`, but the full IR union is far too large). Variants of the same object
#: shape are merged into one permissive object schema; beyond this depth the
#: union degrades to a free-form object so the request stays finite.
_GEMINI_UNION_DEPTH = 8
_GEMINI_MAX_REF_DEPTH = 24


def to_gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Convert a JSON Schema document to the subset Gemini accepts.

    Two pragmatic transformations keep the request valid on Gemini 3.x:

    * ``maxItems`` is removed. The API rejects sufficiently large array limits
      with an uninformative 400; the limit depends on the whole schema.
    * object unions (the ``Block`` discriminated union) are merged instead of
      emitted as ``oneOf`` (which Gemini ignores) or a huge ``anyOf``. The
      resulting schema is permissive but still names every block property.
    """
    definitions = schema.get("$defs", {})

    def shallow(node: Any, depth: int = 0) -> Any:
        """One-level projection used when the full union recursion budget is spent."""
        if depth > _GEMINI_MAX_REF_DEPTH or not isinstance(node, dict):
            return {"type": "string"}
        if "$ref" in node:
            ref = str(node["$ref"]).rsplit("/", 1)[-1]
            return shallow(definitions.get(ref, {}), depth + 1)
        union = node.get("anyOf") or node.get("oneOf")
        if union is not None:
            variants = [shallow(item, depth + 1) for item in union]
            non_null = [item for item in variants if item.get("type") != "null"]
            if len(non_null) == 1:
                merged = dict(non_null[0])
                merged["nullable"] = True
                return merged
            return {"type": "object"}
        result: dict[str, Any] = {}
        if "type" in node:
            result["type"] = node["type"]
        if "enum" in node:
            result["enum"] = [str(item) for item in node["enum"]]
        if "const" in node:
            result["enum"] = [str(node["const"])]
        if "format" in node:
            result["format"] = node["format"]
        if "items" in node:
            result["items"] = {"type": "string"}
            result["type"] = "array"
        if "properties" in node:
            properties: dict[str, Any] = {}
            for name, prop in node["properties"].items():
                if not isinstance(prop, dict):
                    properties[name] = {"type": "string"}
                    continue
                resolved = shallow(prop, depth + 1)
                if resolved.get("type") == "array":
                    resolved = {"type": "array", "items": {"type": "string"}}
                properties[name] = resolved
            result["properties"] = properties
            result["type"] = "object"
        if "type" not in result:
            result["type"] = "string"
        return result

    def convert(node: Any, depth: int = 0) -> Any:
        if depth > _GEMINI_MAX_REF_DEPTH or not isinstance(node, dict):
            return {"type": "string"}
        if "$ref" in node:
            ref = str(node["$ref"]).rsplit("/", 1)[-1]
            target = definitions.get(ref, {})
            return convert(target, depth + 1)
        union = node.get("anyOf") or node.get("oneOf")
        if union is not None:
            refs = {str(item.get("$ref")) for item in union if isinstance(item, dict)}
            if refs == {"#/$defs/TextRun", "#/$defs/FieldBinding"}:
                # Inline runs are a small union and must stay discriminable:
                # a merged object let the model emit empty run objects.
                variants = [convert(item, depth + 1) for item in union]
                non_null_inline = [item for item in variants if item.get("type") != "null"]
                return {"anyOf": non_null_inline}
            if depth >= _GEMINI_UNION_DEPTH:
                shallow_variants = [shallow(item) for item in union]
                shallow_non_null = [item for item in shallow_variants if item.get("type") != "null"]
                if len(shallow_non_null) == 1:
                    merged = dict(shallow_non_null[0])
                    merged["nullable"] = True
                    return merged
                return {"type": "object"}
            variants = [convert(item, depth + 1) for item in union]
            non_null = [item for item in variants if item.get("type") != "null"]
            if not non_null:
                return {"type": "string"}
            if len(non_null) == 1:
                merged = dict(non_null[0])
                merged["nullable"] = True
                return merged
            if all(item.get("type") == "object" for item in non_null):
                properties: dict[str, Any] = {}
                kind_values: set[str] = set()
                for item in non_null:
                    if "kind" in item.get("properties", {}):
                        kind_values.update(item["properties"]["kind"].get("enum", []))
                    properties.update(item.get("properties", {}))
                if kind_values:
                    properties["kind"] = {"type": "string", "enum": sorted(kind_values)}
                return {
                    "type": "object",
                    "properties": properties,
                    "required": ["kind"],
                }
            return {"anyOf": non_null}
        result: dict[str, Any] = {}
        for key, value in node.items():
            if key not in _GEMINI_ALLOWED_KEYS or key in _GEMINI_DROP_KEYS:
                continue
            if key == "properties":
                result["properties"] = {
                    name: convert(prop, depth + 1) for name, prop in value.items()
                }
            elif key == "items":
                result["items"] = convert(value, depth + 1)
            elif key == "enum":
                result["enum"] = [str(item) for item in value]
            elif key == "const":
                result["enum"] = [str(value)]
            else:
                result[key] = value
        if "type" not in result and "properties" in result:
            result["type"] = "object"
        if "kind" in result.get("properties", {}):
            # Pydantic's discriminator rejects a block or run without `kind`,
            # even though the IR field has a default.
            required = [str(item) for item in result.get("required", [])]
            if "kind" not in required:
                required.insert(0, "kind")
            result["required"] = required
        return result

    converted = convert(schema)
    if converted.get("type") == "object":
        converted.pop("nullable", None)
    return converted


def _gemini_generation_config(
    settings: GenerationSettings, schema: dict[str, Any]
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "temperature": settings.temperature,
        "maxOutputTokens": settings.max_output_tokens,
        "responseMimeType": "application/json",
        "responseSchema": to_gemini_schema(schema),
    }
    if settings.model.startswith("gemini-3"):
        # Thinking tokens are billed as output and are drawn from the same
        # completion budget. Minimal thinking keeps a large IR from being
        # truncated; validation, not the model, decides whether it is usable.
        config["thinkingConfig"] = {"thinkingLevel": "minimal"}
    return config


class GeminiProvider(BaseHTTPProvider):
    name = "gemini"

    async def generate_structured(
        self,
        *,
        messages: list[Message],
        schema: dict[str, Any],
        settings: GenerationSettings,
    ) -> GenerationResult:
        api_key = self._ensure_configured()
        self._preflight_budget(messages, settings, schema)
        url = f"{self._base_url}/models/{settings.model}:generateContent"
        headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
        system = "\n\n".join(message.content for message in messages if message.role is Role.SYSTEM)
        contents = [
            {
                "role": "model" if message.role is Role.ASSISTANT else "user",
                "parts": [{"text": message.content}],
            }
            for message in messages
            if message.role is not Role.SYSTEM
        ]
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": _gemini_generation_config(settings, schema),
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        started = time.perf_counter()
        retried = False
        try:
            response = await self._post(url, headers=headers, payload=payload, settings=settings)
        except ProviderError as exc:
            # Gemini 3.x rejects some generationConfig combinations with a bare
            # 400 and no field name. Drop one capability at a time so the schema
            # (which keeps the output shape) survives as long as possible.
            if exc.code != "provider_bad_response" or exc.details.get("status") != 400:
                raise
            config = payload["generationConfig"]
            for key in ("thinkingConfig", "temperature", "responseSchema"):
                config.pop(key, None)
                retried = True
                try:
                    response = await self._post(url, headers=headers, payload=payload, settings=settings)
                    break
                except ProviderError as retry_exc:
                    if retry_exc.code != "provider_bad_response" or retry_exc.details.get("status") != 400:
                        raise
            else:
                raise
        latency_ms = int((time.perf_counter() - started) * 1000)
        latency_ms = int((time.perf_counter() - started) * 1000)

        body = response.json()
        try:
            candidate = body["candidates"][0]
            parts = candidate["content"]["parts"]
            text = "".join(str(part.get("text", "")) for part in parts)
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                "Provider response is missing a completion",
                details={"provider": self.name},
            ) from exc
        finish_reason = candidate.get("finishReason") or None
        if finish_reason == "MAX_TOKENS":
            raise ProviderError(
                "The model stopped before finishing the document",
                details={
                    "provider": self.name,
                    "reason": "output_truncated",
                    "hint": "increase DC_LLM_MAX_OUTPUT_TOKENS or use a smaller schema",
                    "retried_without_schema": retried,
                },
            )
        usage = body.get("usageMetadata") or {}
        return self._result(
            content=extract_json_object(text),
            model=body.get("modelVersion") or settings.model,
            prompt_tokens=int(usage.get("promptTokenCount", 0)),
            completion_tokens=int(usage.get("candidatesTokenCount", 0)),
            latency_ms=latency_ms,
            finish_reason=finish_reason,
            raw_text=text,
            attempts=2 if retried else 1,
        )


# --------------------------------------------------------------------------- #
# Deterministic mock
# --------------------------------------------------------------------------- #
Responder = Callable[[list[Message], dict[str, Any]], dict[str, Any]]


class MockProvider:
    """A provider that never touches the network.

    The planner registers a deterministic responder so the full pipeline (prompt
    assembly, schema validation, repair loop) is exercised in tests and demos
    without any API key, and with byte-identical output.
    """

    name = "mock"

    def __init__(self, responder: Responder | None = None) -> None:
        self._responder = responder
        self.calls: list[dict[str, Any]] = []

    @property
    def configured(self) -> bool:
        return True

    def set_responder(self, responder: Responder) -> None:
        self._responder = responder

    async def generate_structured(
        self,
        *,
        messages: list[Message],
        schema: dict[str, Any],
        settings: GenerationSettings,
    ) -> GenerationResult:
        if self._responder is None:  # pragma: no cover - planner always registers one
            raise ProviderNotConfiguredError(
                "The mock provider has no responder installed",
                details={"provider": "mock"},
            )
        started = time.perf_counter()
        outcome = self._responder(messages, schema)
        content = await outcome if inspect.isawaitable(outcome) else outcome
        latency_ms = int((time.perf_counter() - started) * 1000)
        self.calls.append(
            {
                "model": settings.model,
                "messages": len(messages),
                "prompt_chars": sum(len(message.content) for message in messages),
            }
        )
        return GenerationResult(
            provider=self.name,
            model=settings.model,
            content=content,
            # The deterministic baseline makes no paid call: its zero is real.
            usage=Usage(estimated_cost_usd=0.0),
            latency_ms=latency_ms,
            finish_reason="stop",
            raw_text=None,
        )


__all__ = [
    "AnthropicProvider",
    "BaseHTTPProvider",
    "GeminiProvider",
    "MockProvider",
    "OpenAIProvider",
    "extract_json_object",
    "to_gemini_schema",
]
