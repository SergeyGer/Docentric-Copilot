"""Unit tests for shared core primitives: errors, ids, serialization, logging, config."""

from __future__ import annotations

import json

import pytest
from docentric_copilot.config import Limits, Settings, get_settings
from docentric_copilot.errors import (
    CopilotError,
    InvalidInputError,
    NotFoundError,
    SecurityViolationError,
    UnsupportedTargetError,
)
from docentric_copilot.ids import is_valid_id, new_id
from docentric_copilot.logging import REDACTED, configure_logging, redact
from docentric_copilot.serialization import canonical_json, digest, pretty_json, to_plain


def test_error_envelope_shape() -> None:
    error = InvalidInputError("bad input", details={"field": "x"})
    payload = error.to_dict()
    assert payload == {
        "error": {"code": "input_invalid", "message": "bad input", "details": {"field": "x"}}
    }
    assert error.http_status == 400
    # 2 is reserved for CLI usage errors; invalid input files exit with 3.
    assert error.exit_code == 3


def test_error_codes_are_distinct() -> None:
    assert SecurityViolationError.code == "security_violation"
    assert NotFoundError.http_status == 404
    assert UnsupportedTargetError.exit_code == 4
    assert CopilotError("x").http_status == 500


def test_new_id_is_prefixed_and_valid() -> None:
    identifier = new_id("job")
    assert identifier.startswith("job_")
    assert is_valid_id(identifier, "job")
    assert not is_valid_id(identifier, "src")
    assert len({new_id("art") for _ in range(20)}) == 20
    with pytest.raises(ValueError):
        new_id("")


def test_canonical_json_is_order_independent() -> None:
    left = {"b": 1, "a": [{"y": 2, "x": 1}]}
    right = {"a": [{"x": 1, "y": 2}], "b": 1}
    assert canonical_json(left) == canonical_json(right)
    assert digest(left) == digest(right)
    assert "\n" not in canonical_json(left)
    assert pretty_json(left).endswith("\n")


def test_to_plain_handles_nested_structures() -> None:
    payload = {"tuple": (1, 2), "list": [{"a": None}], "text": "café"}
    assert to_plain(payload) == {"tuple": [1, 2], "list": [{"a": None}], "text": "café"}


def test_redaction_protects_keys_but_not_token_counts() -> None:
    payload = {
        "api_key": "secret",
        "access_token": "secret",
        "authorization": "Bearer x",
        "prompt_tokens": 12,
        "completion_tokens": 3,
        "nested": [{"password": "p"}],
        "text": "token sk-abcdefghijkl leaked",
    }
    redacted = redact(payload)
    assert redacted["api_key"] == REDACTED
    assert redacted["access_token"] == REDACTED
    assert redacted["authorization"] == REDACTED
    assert redacted["prompt_tokens"] == 12
    assert redacted["completion_tokens"] == 3
    assert redacted["nested"][0]["password"] == REDACTED
    assert "sk-abcdefghijkl" not in redacted["text"]


def test_json_formatter_emits_one_object_per_line(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json_output=True)
    import logging

    logging.getLogger("test.logger").info("hello", extra={"context": {"api_key": "nope"}})
    line = capsys.readouterr().err.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["message"] == "hello"
    assert payload["context"]["api_key"] == REDACTED


def test_settings_defaults_and_public_view(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings()
    view = settings.public_view()
    assert "providers" in view
    assert "limits" in view
    assert settings.limits.max_ddsp_bytes == Limits().max_ddsp_bytes
    monkeypatch.setenv("DC_MAX_DDSP_BYTES", "2048")
    monkeypatch.setenv("DC_ENABLE_AX_ADAPTER", "true")
    monkeypatch.setenv("DC_CORS_ORIGINS", "http://localhost:3000,http://example.test")
    get_settings.cache_clear()
    refreshed = get_settings()
    assert refreshed.limits.max_ddsp_bytes == 2048
    assert refreshed.enable_docentric_ax_adapter is True
    assert refreshed.cors_origins == ("http://localhost:3000", "http://example.test")


def test_provider_configuration_is_reported_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-value-1234567890")
    get_settings.cache_clear()
    settings = get_settings()
    view = settings.public_view()
    openai_entries = [item for item in view["providers"] if item["name"] == "openai"]
    assert openai_entries and openai_entries[0]["configured"] is True
    assert "sk-test-value" not in json.dumps(view)
