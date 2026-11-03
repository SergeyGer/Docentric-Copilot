"""Auto-routing decisions and sanitized execution traces (VID-01).

The router itself lives in :mod:`docentric_copilot.planner.routing`; this module
adapts it to the HTTP contract, records what actually happened, and persists a
trace that contains **no prompt text, no model output and no credentials**.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from docentric_copilot.config import Settings
from docentric_copilot.ddsp_parser.models import NormalizedSchema
from docentric_copilot.llm.models import GenerationResult
from docentric_copilot.llm.pricing import price_table_metadata
from docentric_copilot.logging import get_logger
from docentric_copilot.planner import RouteDecision, classify, route
from docentric_copilot.schema_resolver import parse_requirements
from docentric_copilot.template_validator import ValidationReport

from .schemas import RoutingExecutionTrace

logger = get_logger(__name__)

_SECRET_PATTERN = re.compile(r"(?i)(api[-_]?key|authorization|bearer|x-goog-api-key)\s*[=:]\s*\S+")


def new_run_id() -> str:
    """Return a short, unique, non-guessable run identifier."""
    return f"run_{uuid.uuid4().hex[:20]}"


def configured_providers(settings: Settings) -> set[str]:
    """Names of providers that can actually serve a request right now."""
    return {name for name, provider in settings.providers.items() if provider.configured}


def decide(
    schema: NormalizedSchema,
    prompt: str,
    settings: Settings,
) -> tuple[RouteDecision, int]:
    """Classify ``prompt`` and route it against the configured providers."""
    requirements = parse_requirements(prompt).requirements
    complexity, reasons = classify(schema, requirements)
    decision = route(complexity, configured=configured_providers(settings))
    decision = decision.model_copy(update={"reason": [*reasons, *decision.reason]})
    return decision, len(requirements)


def prompt_fingerprint(prompt: str) -> str:
    """A digest that lets two traces be correlated without storing the brief."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _redact(text: str) -> str:
    return _SECRET_PATTERN.sub("[redacted]", text)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _usage_payload(generation: GenerationResult | None) -> dict[str, Any] | None:
    if generation is None:
        return None
    return generation.usage.model_dump(mode="json")


def _pricing_payload(usage: dict[str, Any] | None) -> dict[str, Any]:
    cost = usage.get("estimated_cost_usd") if usage else None
    return {
        **price_table_metadata(),
        "estimated_cost_usd": cost,
        "pricing_known": cost is not None,
    }


def build_trace(
    *,
    run_id: str,
    decision: RouteDecision,
    started_at: datetime,
    finished_at: datetime,
    prompt: str,
    generation: GenerationResult | None,
    actual_provider: str,
    actual_model: str | None,
) -> RoutingExecutionTrace:
    """Build the public trace object returned by ``POST /templates/plan``."""
    usage = _usage_payload(generation)
    return RoutingExecutionTrace(
        decision=decision.model_dump(mode="json"),
        actual_provider=actual_provider,
        actual_model=actual_model,
        fallback=decision.fallback_used,
        match=decision.provider == actual_provider,
        run_id=run_id,
        started_at=started_at,
        finished_at=finished_at,
        usage=usage,
    )


def trace_document(
    *,
    run_id: str,
    decision: RouteDecision,
    started_at: datetime,
    finished_at: datetime,
    prompt: str,
    actual_provider: str,
    actual_model: str | None,
    generation: GenerationResult | None,
    report: ValidationReport | None,
    ir_digest: str | None,
    request_budget_usd: float | None,
    status: str,
    error: dict[str, str] | None = None,
) -> dict[str, Any]:
    """The sanitized on-disk trace. Safe to inspect and archive locally."""
    usage = _usage_payload(generation)
    document: dict[str, Any] = {
        "schema": "routing-trace/v1",
        "run_id": run_id,
        "status": status,
        "created_at": _iso(finished_at),
        "started_at": _iso(started_at),
        "finished_at": _iso(finished_at),
        "duration_ms": int((finished_at - started_at).total_seconds() * 1000),
        "prompt": {
            "chars": len(prompt),
            "sha256": prompt_fingerprint(prompt),
        },
        "decision": decision.model_dump(mode="json"),
        "recommended": {"provider": decision.provider, "model": decision.model},
        "executed": {"provider": actual_provider, "model": actual_model},
        "match": decision.provider == actual_provider,
        "fallback": decision.fallback_used,
        "complexity": decision.complexity.value,
        "budget_usd": decision.budget_usd,
        "request_budget_usd": request_budget_usd,
        "usage": usage,
        "pricing": _pricing_payload(usage),
        "validation": report.statuses() if report is not None else {},
        "validation_overall": report.overall if report is not None else None,
        "ir_digest": ir_digest,
        "error": error,
    }
    if error is not None:
        document["error"] = {
            "code": error.get("code", "provider_error"),
            "message": _redact(error.get("message", ""))[:500],
        }
    return document


def write_trace(settings: Settings, document: dict[str, Any]) -> Path | None:
    """Persist one trace under ``settings.routing_trace_dir`` (best effort)."""
    directory_value = str(settings.routing_trace_dir).strip()
    if not directory_value:
        return None
    directory = Path(directory_value)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{document['run_id']}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.replace(path)
        return path
    except OSError as exc:  # pragma: no cover - disk failures must not break planning
        logger.warning(
            "routing.trace_write_failed",
            extra={"context": {"run_id": document.get("run_id"), "error": type(exc).__name__}},
        )
        return None


__all__ = [
    "build_trace",
    "configured_providers",
    "decide",
    "new_run_id",
    "prompt_fingerprint",
    "trace_document",
    "write_trace",
]
