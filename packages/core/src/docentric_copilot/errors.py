"""Typed error hierarchy shared by every layer.

Every public error carries a stable machine readable ``code``, a human readable
message and optional structured ``details``. The API layer maps these to HTTP
status codes and to the error envelope documented in ``docs/API_SPEC.md``:

.. code-block:: json

    {"error": {"code": "input_unsupported", "message": "...", "details": {...}}}
"""

from __future__ import annotations

from typing import Any


class CopilotError(Exception):
    """Base class for all expected (non-bug) failures."""

    code: str = "internal_error"
    http_status: int = 500
    exit_code: int = 1

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        code: str | None = None,
        location: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}
        self.location = location
        if location and "location" not in self.details:
            self.details["location"] = location
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return {"error": payload}

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"{type(self).__name__}(code={self.code!r}, message={self.message!r})"


class InvalidInputError(CopilotError):
    """The caller supplied something structurally wrong (bad JSON, bad field)."""

    code = "input_invalid"
    http_status = 400
    exit_code = 3


class UnsupportedInputError(CopilotError):
    """The input is well formed but outside the supported subset."""

    code = "input_unsupported"
    http_status = 415
    exit_code = 3


class SecurityViolationError(CopilotError):
    """Untrusted content attempted something the threat model forbids."""

    code = "security_violation"
    http_status = 400
    exit_code = 3


class NotFoundError(CopilotError):
    """A job, source, artifact or template does not exist."""

    code = "not_found"
    http_status = 404
    exit_code = 6


class ValidationFailedError(CopilotError):
    """Validation rejected the input; the payload is a validation report."""

    code = "validation_failed"
    http_status = 422
    exit_code = 1


class CompilationFailedError(CopilotError):
    """The compiler refused to emit a document (fail closed)."""

    code = "compilation_failed"
    http_status = 422
    exit_code = 1


class UnsupportedTargetError(CopilotError):
    """The requested compilation target is not enabled or not verified."""

    code = "target_unsupported"
    http_status = 409
    exit_code = 4


class ProviderError(CopilotError):
    """An LLM provider failed, timed out or returned unusable output."""

    code = "provider_error"
    http_status = 502
    exit_code = 5


class ProviderNotConfiguredError(ProviderError):
    """The requested provider has no credentials configured."""

    code = "provider_not_configured"
    http_status = 503
    exit_code = 5


class BudgetExceededError(ProviderError):
    """A hard token/cost budget would be exceeded."""

    code = "budget_exceeded"
    http_status = 402
    exit_code = 5


class ArtifactError(CopilotError):
    """An artifact is missing, expired or not downloadable."""

    code = "artifact_unavailable"
    http_status = 410
    exit_code = 6


__all__ = [
    "ArtifactError",
    "BudgetExceededError",
    "CompilationFailedError",
    "CopilotError",
    "InvalidInputError",
    "NotFoundError",
    "ProviderError",
    "ProviderNotConfiguredError",
    "SecurityViolationError",
    "UnsupportedInputError",
    "UnsupportedTargetError",
    "ValidationFailedError",
]
