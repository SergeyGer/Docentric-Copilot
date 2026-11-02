"""Preview renderer and LLM gateway tests (no network access required)."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from docentric_copilot.config import ProviderSettings, Settings
from docentric_copilot.errors import BudgetExceededError, ProviderError, ProviderNotConfiguredError
from docentric_copilot.llm import (
    AnthropicProvider,
    GeminiProvider,
    GenerationSettings,
    LLMGateway,
    Message,
    OpenAIProvider,
    Role,
    estimate_cost_usd,
    extract_json_object,
    to_gemini_schema,
)
from docentric_copilot.preview import PreviewOptions, render_preview
from docentric_copilot.template_ir import Document, load_document


def _run(coro):
    return asyncio.run(coro)


def _messages() -> list[Message]:
    return [Message(role=Role.USER, content="hi")]


def _settings_for_client() -> GenerationSettings:
    return GenerationSettings(model="gpt-4o-mini", max_output_tokens=256, retries=1)


# --------------------------------------------------------------------------- #
# Preview
# --------------------------------------------------------------------------- #
class TestPreview:
    def test_renders_values(self, planned, schema, sample_data) -> None:
        result = render_preview(planned.document, schema, sample_data=sample_data)
        assert "Example Customer GmbH" in result.html
        assert "1,980.00" in result.html
        assert "Enterprise Subscription" in result.html
        assert result.stats["repeats"] == 2  # 2 table rows + 1 repeat block

    def test_escapes_user_content(self, planned, schema, sample_data) -> None:
        modified = {
            **sample_data,
            "MainData": {
                **sample_data["MainData"],
                "Quotation": {
                    **sample_data["MainData"]["Quotation"],
                    "Customer": {
                        **sample_data["MainData"]["Quotation"]["Customer"],
                        "Name": '<script>alert("xss")</script>',
                    },
                },
            },
        }
        result = render_preview(planned.document, schema, sample_data=modified)
        assert "<script>alert" not in result.html
        assert "&lt;script&gt;" in result.html

    def test_without_sample_data_uses_placeholders(self, planned, schema) -> None:
        result = render_preview(planned.document, schema, options=PreviewOptions())
        assert 'class="ph"' in result.html
        assert result.stats["placeholders"] > 0

    def test_conditional_is_respected(self, planned, schema, sample_data) -> None:
        modified = {
            **sample_data,
            "MainData": {
                **sample_data["MainData"],
                "Quotation": {
                    **sample_data["MainData"]["Quotation"],
                    "Customer": {
                        **sample_data["MainData"]["Quotation"]["Customer"],
                        "IsEU": False,
                    },
                },
            },
        }
        result = render_preview(planned.document, schema, sample_data=modified)
        assert "VAT notice" not in result.html

    def test_logo_is_inlined(self, planned, schema, sample_data) -> None:
        result = render_preview(planned.document, schema, sample_data=sample_data)
        assert "data:image/png;base64," in result.html
        assert result.stats["images"] == 1
        assert 'class="doc-value" data-path="GeneralData.Company.CompanyLogo"' in result.html

    def test_pages_and_binding_annotations(self, planned, schema, sample_data) -> None:
        result = render_preview(planned.document, schema, sample_data=sample_data)
        assert result.html.count('class="page"') >= 2
        assert "Page 1 of 2" in result.html
        assert 'data-path="MainData.Quotation.TotalAmount"' in result.html

    def test_landscape_page(self, schema, sample_data) -> None:
        document = load_document(
            {
                "title": "Landscape",
                "page": {"orientation": "landscape"},
                "metadata": {"template_name": "x", "source_schema_id": "s"},
                "sections": [
                    {
                        "name": "Main",
                        "body": [{"kind": "paragraph", "runs": [{"kind": "text", "text": "x"}]}],
                    }
                ],
            }
        )
        result = render_preview(document, schema, sample_data=sample_data)
        assert 'class="page"' in result.html


# --------------------------------------------------------------------------- #
# Structured output helpers
# --------------------------------------------------------------------------- #
class TestJsonExtraction:
    def test_bare_object(self) -> None:
        assert extract_json_object('{"a": 1}') == {"a": 1}

    def test_fenced_block(self) -> None:
        assert extract_json_object('Here you go:\n```json\n{"a": [1, 2]}\n```') == {"a": [1, 2]}

    def test_prose_wrapped(self) -> None:
        assert extract_json_object('answer: {"ok": true} done') == {"ok": True}

    def test_invalid(self) -> None:
        with pytest.raises(ProviderError):
            extract_json_object("no json here")

    def test_gemini_schema_resolution(self) -> None:
        schema = Document.model_json_schema()
        converted = to_gemini_schema(schema)
        assert converted["type"] == "object"
        assert "properties" in converted
        dumped = json.dumps(converted)
        assert "$defs" not in dumped and "$ref" not in dumped

    def test_cost_estimate(self) -> None:
        assert estimate_cost_usd("gpt-4o-mini", 1_000_000, 0) == pytest.approx(0.15)
        assert estimate_cost_usd("unknown-model", 1000, 1000) == 0.0


# --------------------------------------------------------------------------- #
# Provider adapters (httpx MockTransport)
# --------------------------------------------------------------------------- #
class TestOpenAIAdapter:
    def test_success(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["response_format"]["type"] == "json_schema"
            assert request.headers["authorization"] == "Bearer test-key"
            return httpx.Response(
                200,
                json={
                    "model": "gpt-4o-mini",
                    "choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                },
            )

        async def scenario() -> None:
            client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            provider = OpenAIProvider(
                api_key="test-key", base_url="https://api.test", client=client
            )
            result = await provider.generate_structured(
                messages=_messages(), schema={"type": "object"}, settings=_settings_for_client()
            )
            assert result.content == {"ok": True}
            assert result.usage.prompt_tokens == 10
            assert result.usage.estimated_cost_usd > 0
            await client.aclose()

        _run(scenario())

    def test_retry_then_success(self) -> None:
        calls = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["count"] += 1
            if calls["count"] == 1:
                return httpx.Response(429, headers={"retry-after": "0"}, text="slow down")
            return httpx.Response(
                200,
                json={
                    "model": "gpt-4o-mini",
                    "choices": [{"message": {"content": '{"ok": 1}'}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                },
            )

        async def scenario() -> None:
            client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            provider = OpenAIProvider(api_key="k", base_url="https://api.test", client=client)
            provider.retry_backoff_seconds = 0
            result = await provider.generate_structured(
                messages=_messages(), schema={}, settings=_settings_for_client()
            )
            assert result.content == {"ok": 1}
            assert calls["count"] == 2
            await client.aclose()

        _run(scenario())

    def test_error_is_normalized(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        async def scenario() -> None:
            client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            provider = OpenAIProvider(api_key="k", base_url="https://api.test", client=client)
            provider.retry_backoff_seconds = 0
            with pytest.raises(ProviderError) as exc:
                await provider.generate_structured(
                    messages=_messages(), schema={}, settings=_settings_for_client()
                )
            assert exc.value.code == "provider_bad_response"
            assert exc.value.details["status"] == 500
            await client.aclose()

        _run(scenario())

    def test_missing_key(self) -> None:
        provider = OpenAIProvider(api_key=None, base_url="https://api.test")
        with pytest.raises(ProviderNotConfiguredError):
            _run(
                provider.generate_structured(
                    messages=_messages(), schema={}, settings=_settings_for_client()
                )
            )

    def test_budget_preflight(self) -> None:
        provider = OpenAIProvider(api_key="k", base_url="https://api.test")
        settings = GenerationSettings(
            model="gpt-4o", max_output_tokens=100_000, budget_usd=0.01, timeout_seconds=1
        )
        with pytest.raises(BudgetExceededError):
            _run(provider.generate_structured(messages=_messages(), schema={}, settings=settings))


class TestAnthropicAdapter:
    def test_tool_use_is_parsed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["tool_choice"]["type"] == "tool"
            return httpx.Response(
                200,
                json={
                    "model": "claude-3-5-haiku",
                    "content": [
                        {"type": "text", "text": "thinking"},
                        {"type": "tool_use", "name": "emit_template_ir", "input": {"ok": True}},
                    ],
                    "usage": {"input_tokens": 7, "output_tokens": 3},
                    "stop_reason": "tool_use",
                },
            )

        async def scenario() -> None:
            client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            provider = AnthropicProvider(api_key="k", base_url="https://api.test", client=client)
            result = await provider.generate_structured(
                messages=_messages(),
                schema={"type": "object"},
                settings=GenerationSettings(model="claude-3-5-haiku", max_output_tokens=256),
            )
            assert result.content == {"ok": True}
            assert result.usage.prompt_tokens == 7
            await client.aclose()

        _run(scenario())


class TestGeminiAdapter:
    def test_text_json_is_parsed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["generationConfig"]["responseMimeType"] == "application/json"
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {"content": {"parts": [{"text": '{"ok": true}'}]}, "finishReason": "STOP"}
                    ],
                    "usageMetadata": {"promptTokenCount": 4, "candidatesTokenCount": 2},
                },
            )

        async def scenario() -> None:
            client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            provider = GeminiProvider(api_key="k", base_url="https://api.test", client=client)
            result = await provider.generate_structured(
                messages=_messages(),
                schema={"type": "object"},
                settings=GenerationSettings(model="gemini-2.0-flash", max_output_tokens=256),
            )
            assert result.content == {"ok": True}
            assert result.usage.prompt_tokens == 4
            await client.aclose()

        _run(scenario())


class TestGateway:
    def test_describe_reports_mock_as_configured(self) -> None:
        catalogue = LLMGateway().describe()
        mock = next(item for item in catalogue if item["name"] == "mock")
        assert mock["configured"] is True
        assert all("api_key" not in item for item in catalogue)

    def test_missing_provider_key(self) -> None:
        gateway = LLMGateway()
        with pytest.raises(ProviderNotConfiguredError):
            gateway.get("openai")

    def test_invalid_provider_output_is_rejected(self) -> None:
        gateway = LLMGateway()

        async def scenario() -> None:
            gateway.mock.set_responder(lambda _messages, _schema: {"not": "a document"})
            with pytest.raises(ProviderError) as exc:
                await gateway.generate_structured(
                    provider="mock", model=None, messages=_messages(), schema=Document
                )
            assert exc.value.code == "provider_invalid_output"

        _run(scenario())

    def test_mock_pipeline_runs_through_gateway(self, planned) -> None:
        assert planned.generation is not None
        assert planned.generation.provider == "mock"
        assert planned.generation.usage.estimated_cost_usd == 0.0

    def test_custom_transport_is_used(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "model": "gpt-4o-mini",
                    "choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                },
            )

        settings = Settings(
            providers={
                "mock": ProviderSettings(name="mock", api_key="x"),
                "openai": ProviderSettings(
                    name="openai",
                    api_key="k",
                    base_url="https://api.test",
                    default_model="gpt-4o-mini",
                ),
            }
        )
        gateway = LLMGateway(settings, transport=httpx.MockTransport(handler))
        assert gateway.get("openai") is not None
        _run(gateway.aclose())
