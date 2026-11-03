#!/usr/bin/env python3
"""Live multi-provider evaluation for the template planner (VID-02).

Every case is planned ``--repeats`` times per provider with the same prompt and
schema. The harness records field precision/recall, requirement coverage,
validation and compilation success, latency (p50/p95), tokens and cost.

Cost is deliberately three-valued:

* ``observed`` - the provider reported token usage and the model has a
  published price in the versioned price table;
* ``estimated`` - the model is unpriced (Gemini 3.6-flash) but a documented,
  conservative proxy rate exists; the proxy is recorded with the report;
* ``unavailable`` - neither a price nor a proxy exists.

Unknown is never rendered as ``$0.00``. The budget guard aborts when the next
call's worst case could cross ``--max-spend`` (default $5) or when the running
known + estimated spend already crossed it. Unknown-cost calls are logged.

Usage::

    python benchmarks/live_evaluation.py \
        --providers openai:gpt-6-sol,anthropic:claude-sonnet-5-5,gemini:gemini-3.6-flash \
        --repeats 2 --allow-unpriced --max-spend 5 \
        --repair-attempts 2 --max-output-tokens 32000

Generated reports are ``benchmarks/live_report.json`` and ``.md``. Per-run
traces go to the git-ignored ``docs/media/runs/`` directory and contain no
prompt text or credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import re
import sys
import time
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

from docentric_copilot.config import get_settings  # noqa: E402
from docentric_copilot.ddsp_parser import parse_ddsp  # noqa: E402
from docentric_copilot.docx_compiler import CompileOptions, GenericDocxCompiler  # noqa: E402
from docentric_copilot.errors import (  # noqa: E402
    CompilationFailedError,
    InvalidInputError,
    PlanInvalidError,
    ProviderError,
    ValidationFailedError,
)
from docentric_copilot.evaluation import (  # noqa: E402
    ProviderScore,
    display_cost,
    field_metrics,
    percentile,
    quality_score,
    recommend_provider,
)
from docentric_copilot.llm import LLMGateway  # noqa: E402
from docentric_copilot.llm.pricing import (  # noqa: E402
    estimate_cost,
    price_for,
    price_table_metadata,
)
from docentric_copilot.planner import (  # noqa: E402
    PlanOptions,
    TemplatePlanner,
    absolute_bindings,
    build_compact_messages,
    build_compact_messages_v2,
    build_messages,
)
from docentric_copilot.template_ir import ir_digest  # noqa: E402
from docentric_copilot.template_validator import ValidationEngine  # noqa: E402

DEFAULT_CASES = ROOT / "benchmarks" / "live_cases.json"
DEFAULT_JSON = ROOT / "benchmarks" / "live_report.json"
DEFAULT_MD = ROOT / "benchmarks" / "live_report.md"
DEFAULT_TRACE_DIR = ROOT / "docs" / "media" / "runs"
DEFAULT_MAX_SPEND = 5.0
DEFAULT_REPEATS = 3
_MAX_TOKENS_PER_CHAR = 0.35
_SECRET = re.compile(r"(?i)(api[-_]?key|authorization|bearer)\s*[=:]\s*\S+")

#: Taxonomy for a failed run. One code per run, so counts add up to runs.
ERROR_CODES = (
    "api_error",
    "quota",
    "timeout",
    "truncated",
    "schema_invalid",
    "binding_invalid",
    "validation_failed",
    "compilation_failed",
    "harness_error",
)

#: Conservative proxy rates for models the product price table deliberately
#: leaves unpriced. These are *not* list prices and are recorded as estimated.
#: gemini-3.6-flash is proxied by the published gemini-3.8-flash rate, which is
#: the nearest known Gemini 3.x Flash tier in the versioned table.
PROXY_PRICES: dict[str, dict[str, Any]] = {
    "gemini-3.6-flash": {
        "proxy_for": "gemini-3.8-flash",
        "input_per_mtok": 0.75,
        "output_per_mtok": 3.75,
        "as_of": "2026-11-03",
        "source": "docs/PRICING.md (gemini-3.8-flash introductory rate)",
    }
}


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _prompt_digest(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _redact(text: str) -> str:
    return _SECRET.sub("[redacted]", text)[:500]


def _parse_providers(raw: str) -> list[tuple[str, str | None]]:
    targets: list[tuple[str, str | None]] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        provider, _, model = item.partition(":")
        provider = provider.strip()
        model = model.strip() or None
        if not provider:
            raise SystemExit(f"Invalid provider specification: {item!r}")
        targets.append((provider, model))
    if not targets:
        raise SystemExit("At least one provider is required")
    return targets


def _compact_enabled(mode: str, provider: str) -> bool:
    """Resolve --compact-ir for one provider (auto = Gemini only)."""
    if mode == "on":
        return True
    if mode == "off":
        return False
    return provider == "gemini"


def _proxy_for(model: str) -> dict[str, Any] | None:
    lowered = model.lower()
    matches = [prefix for prefix in PROXY_PRICES if lowered.startswith(prefix)]
    if not matches:
        return None
    return PROXY_PRICES[max(matches, key=len)]


def _messages_for(schema: Any, prompt: str, compact: bool, version: str) -> list[Any]:
    if compact:
        builder = build_compact_messages_v2 if version == "v2" else build_compact_messages
        return builder(schema, prompt)
    return build_messages(schema, prompt)


def _usage_cost(
    usage: dict[str, Any] | None, model: str
) -> tuple[float | None, str, dict[str, Any] | None]:
    """Return ``(cost_usd, observed|estimated|unavailable, proxy)``."""
    if not usage:
        return None, "unavailable", None
    known = usage.get("estimated_cost_usd")
    if known is not None:
        return float(known), "observed", None
    proxy = _proxy_for(model)
    if proxy is None:
        return None, "unavailable", None
    prompt_tokens = int(usage.get("prompt_tokens", 0))
    completion_tokens = int(usage.get("completion_tokens", 0))
    cost = round(
        prompt_tokens / 1_000_000 * float(proxy["input_per_mtok"])
        + completion_tokens / 1_000_000 * float(proxy["output_per_mtok"]),
        6,
    )
    return cost, "estimated", proxy


def _worst_case_cost(
    messages: list[Any], model: str, max_output_tokens: int, *, calls: int = 1
) -> float | None:
    prompt_tokens = int(sum(len(message.content) for message in messages) * _MAX_TOKENS_PER_CHAR)
    _price, known = price_for(model)
    if known:
        per_call = estimate_cost(model, prompt_tokens, max_output_tokens)
    else:
        proxy = _proxy_for(model)
        if proxy is None:
            return None
        per_call = round(
            prompt_tokens / 1_000_000 * float(proxy["input_per_mtok"])
            + max_output_tokens / 1_000_000 * float(proxy["output_per_mtok"]),
            6,
        )
    if per_call is None:
        return None
    return round(per_call * max(1, calls), 6)


def _dataset_metadata(definitions: list[dict[str, Any]], path: Path) -> dict[str, Any]:
    canonical = json.dumps(definitions, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    categories = Counter(str(item.get("category")) for item in definitions)
    return {
        "file": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "sha256": digest,
        "hash": digest[:16],
        "case_count": len(definitions),
        "categories": dict(sorted(categories.items())),
    }


def _classify_exception(exc: BaseException) -> tuple[str, str]:
    """Map an exception to the stable per-run error taxonomy."""
    if isinstance(exc, PlanInvalidError):
        message = exc.message.lower()
        structural = any(
            marker in message
            for marker in (
                "unknown key",
                "unknown block",
                "unknown form",
                "unknown format",
                "unknown operator",
                "takes",
                "expected an array",
                "expected a block",
                "missing required key",
                "mixes forms",
            )
        )
        code = "schema_invalid" if structural else "binding_invalid"
        return code, _redact(exc.message)
    if isinstance(exc, ProviderError):
        details = exc.details or {}
        reason = str(details.get("reason", ""))
        status = details.get("status")
        if reason == "output_truncated" or exc.code == "output_truncated":
            return "truncated", _redact(exc.message)
        if exc.code == "provider_timeout":
            return "timeout", _redact(exc.message)
        if status == 429 or exc.code in {"quota_exceeded", "rate_limited"}:
            return "quota", _redact(exc.message)
        if exc.code in {"provider_invalid_output", "plan_invalid"}:
            return "schema_invalid", _redact(exc.message)
        return "api_error", _redact(exc.message)
    if isinstance(exc, (ValidationFailedError, CompilationFailedError)):
        code = (
            "validation_failed" if isinstance(exc, ValidationFailedError) else "compilation_failed"
        )
        return code, _redact(str(exc))
    if isinstance(exc, TimeoutError):
        return "timeout", "the provider did not respond in time"
    if isinstance(exc, InvalidInputError):
        if "no usable content" in exc.message.lower():
            return "validation_failed", _redact(exc.message)
        return "harness_error", _redact(exc.message)
    return "harness_error", _redact(f"{type(exc).__name__}: {exc}")


def _write_trace(trace_dir: Path | None, document: dict[str, Any]) -> Path | None:
    if trace_dir is None:
        return None
    try:
        trace_dir.mkdir(parents=True, exist_ok=True)
        path = trace_dir / f"{document['run_id']}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.replace(path)
        return path
    except OSError:
        return None


def _compile(document, schema, sample_data: dict | None, case_id: str) -> tuple[bool, str | None]:
    try:
        result = GenericDocxCompiler().compile(
            document,
            schema,
            CompileOptions(document_name=f"{case_id}.docx"),
            sample_data=sample_data,
        )
        return bool(result.success), None
    except Exception as exc:  # pragma: no cover - compiler failures are data
        return False, _redact(f"{type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------- #
# One run
# --------------------------------------------------------------------------- #
def _run_one(
    *,
    planner: TemplatePlanner,
    validator: ValidationEngine,
    parsed,
    definition: dict[str, Any],
    provider: str,
    model: str | None,
    provider_configured: bool,
    repeat: int,
    repair_attempts: int,
    compact_ir: bool,
    compact_version: str,
) -> dict[str, Any]:
    case_id = definition["case_id"]
    prompt = definition["prompt"]
    expected = sorted(set(definition.get("expected_paths", [])))
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    run_id = f"bench_{uuid.uuid4().hex[:16]}"
    base: dict[str, Any] = {
        "schema": "live-benchmark-run/v2",
        "run_id": run_id,
        "repeat": repeat,
        "started_at": _iso(started_at),
        "case_id": case_id,
        "category": definition.get("category"),
        "provider": provider,
        "requested_model": model,
        "actual_provider": None,
        "actual_model": None,
        "ok": False,
        "valid": False,
        "error": None,
        "latency_ms": 0,
        "usage": None,
        "cost_usd": None,
        "cost_status": "unavailable",
        "cost_known": False,
        "cost_proxy": None,
        "compact_ir": compact_ir,
        "compact_version": compact_version if compact_ir else None,
        "validation": {},
        "validation_passed": False,
        "compiled": False,
        "compile_error": None,
        "requirements": 0,
        "covered_requirements": 0,
        "requirement_coverage": None,
        "precision": None,
        "recall": None,
        "precision_applicable": bool(expected),
        "true_positives": 0,
        "expected_fields": len(expected),
        "selected_fields": 0,
        "actual_paths": [],
        "removed_bindings": 0,
        "ir_digest": None,
        "finish_reason": None,
        "attempts": 0,
        "prompt_chars": len(prompt),
        "prompt_sha256": _prompt_digest(prompt),
    }

    if not provider_configured:
        base["error"] = {
            "code": "harness_error",
            "message": f"Provider '{provider}' has no API key configured",
            "source": "provider_not_configured",
        }
        base["finished_at"] = _iso(datetime.now(UTC))
        return base

    try:
        outcome = asyncio.run(
            planner.plan(
                parsed.schema,
                prompt,
                provider=provider,
                model=model,
                options=PlanOptions(
                    max_repair_attempts=repair_attempts,
                    compact_ir=compact_ir,
                    compact_version=compact_version,  # type: ignore[arg-type]
                ),
            )
        )
    except Exception as exc:
        code, message = _classify_exception(exc)
        base["error"] = {"code": code, "message": message}
        base["latency_ms"] = int((time.perf_counter() - started) * 1000)
        base["finished_at"] = _iso(datetime.now(UTC))
        return base

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    report = validator.validate(outcome.document, parsed.schema, sample_data=parsed.sample_data)
    actual_paths = absolute_bindings(outcome.document, parsed.schema)
    if expected:
        precision, recall, true_positives = field_metrics(expected, actual_paths)
    else:
        # The missing-field case has no expected binding set: precision and
        # recall are undefined and must not drag the aggregate to zero.
        precision, recall, true_positives = None, None, 0
    counts = outcome.mapping.counts()
    requirements = len(outcome.mapping.mappings)
    covered = counts.get("confirmed", 0) + counts.get("schema_valid", 0)
    compiled, compile_error = (False, None)
    if report.can_compile:
        compiled, compile_error = _compile(
            outcome.document, parsed.schema, parsed.sample_data, case_id
        )
    generation = outcome.generation
    usage = generation.usage.model_dump(mode="json") if generation is not None else None
    public = generation.public_view() if generation is not None else {}
    cost, cost_status, proxy = _usage_cost(usage, model or "")
    valid = bool(report.can_compile and compiled)
    if not report.can_compile:
        failed = sorted(name for name, status in report.statuses().items() if status == "failed")
        error: dict[str, str] | None = {
            "code": "validation_failed",
            "message": "validation failed: " + (", ".join(failed) or "unknown stage"),
        }
    elif not compiled:
        error = {
            "code": "compilation_failed",
            "message": compile_error or "the compiler refused the document",
        }
    else:
        error = None

    base.update(
        {
            "ok": True,
            "valid": valid,
            "error": error,
            "actual_provider": public.get("provider"),
            "actual_model": public.get("model"),
            "latency_ms": elapsed_ms,
            "usage": usage,
            "cost_usd": cost,
            "cost_status": cost_status,
            "cost_known": cost is not None,
            "cost_proxy": proxy,
            "validation": report.statuses(),
            "validation_passed": report.can_compile,
            "compiled": compiled,
            "compile_error": compile_error,
            "requirements": requirements,
            "covered_requirements": covered,
            "requirement_coverage": (round(covered / requirements, 6) if requirements else None),
            "precision": precision,
            "recall": recall,
            "true_positives": true_positives,
            "expected_fields": len(expected),
            "selected_fields": len(actual_paths),
            "actual_paths": actual_paths[:60],
            "removed_bindings": len(outcome.removed_bindings),
            "ir_digest": ir_digest(outcome.document),
            "finish_reason": generation.finish_reason if generation is not None else None,
            "attempts": generation.attempts if generation is not None else 0,
        }
    )
    base["finished_at"] = _iso(datetime.now(UTC))
    return base


# --------------------------------------------------------------------------- #
# Aggregates and report
# --------------------------------------------------------------------------- #
def _aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    planned = [run for run in runs if run["ok"]]
    valid = [run for run in planned if run["valid"]]
    metric_runs = [run for run in planned if run["precision_applicable"]]
    true_positives = sum(run["true_positives"] for run in metric_runs)
    selected = sum(run["selected_fields"] for run in metric_runs)
    expected = sum(run["expected_fields"] for run in metric_runs)
    coverage_runs = [run for run in planned if run["requirements"]]
    covered = sum(run["covered_requirements"] for run in coverage_runs)
    requirements = sum(run["requirements"] for run in coverage_runs)
    validations = sum(1 for run in planned if run["validation_passed"])
    compilations = sum(1 for run in planned if run["compiled"])
    precision = round(true_positives / selected, 6) if selected else None
    recall = round(true_positives / expected, 6) if expected else None
    coverage = round(covered / requirements, 6) if requirements else None
    validation_rate = validations / len(planned) if planned else 0.0
    latencies = [float(run["latency_ms"]) for run in planned]

    observed_costs = [
        run["cost_usd"]
        for run in runs
        if run["cost_status"] == "observed" and run["cost_usd"] is not None
    ]
    estimated_costs = [
        run["cost_usd"]
        for run in runs
        if run["cost_status"] == "estimated" and run["cost_usd"] is not None
    ]
    unavailable_runs = sum(1 for run in runs if run["cost_status"] == "unavailable")
    valid_costs = [run["cost_usd"] for run in valid if run["cost_usd"] is not None]
    if not valid or len(valid_costs) != len(valid):
        cost_per_valid: float | None = None
        cost_per_valid_status = "unavailable"
    else:
        cost_per_valid = round(sum(valid_costs) / len(valid), 6)
        if any(run["cost_status"] == "estimated" for run in valid):
            cost_per_valid_status = "estimated"
        else:
            cost_per_valid_status = "observed"

    observed = any(run["cost_status"] == "observed" for run in runs)
    estimated = any(run["cost_status"] == "estimated" for run in runs)
    return {
        "runs": len(runs),
        "planned_runs": len(planned),
        "valid_runs": len(valid),
        "failed_runs": len(runs) - len(planned),
        "validation_pass_rate": round(validation_rate, 6),
        "compilation_success_rate": (round(compilations / len(planned), 6) if planned else 0.0),
        "valid_run_rate": round(len(valid) / len(runs), 6) if runs else 0.0,
        "field_precision": precision,
        "field_recall": recall,
        "requirement_coverage": coverage,
        "quality_score": quality_score(
            precision=precision,
            recall=recall,
            coverage=coverage,
            validation_pass_rate=validation_rate,
        ),
        "latency_ms": {
            "p50": percentile(latencies, 0.5),
            "p95": percentile(latencies, 0.95),
            "samples": len(latencies),
        },
        "tokens": {
            "prompt": sum((run["usage"] or {}).get("prompt_tokens", 0) for run in planned),
            "completion": sum((run["usage"] or {}).get("completion_tokens", 0) for run in planned),
        },
        "cost_usd": round(sum(observed_costs) + sum(estimated_costs), 6),
        "known_cost_usd": round(sum(observed_costs), 6),
        "estimated_cost_usd": round(sum(estimated_costs), 6),
        "unknown_cost_runs": unavailable_runs,
        "cost_status": ("estimated" if estimated else ("observed" if observed else "unavailable")),
        "cost_per_valid_template_usd": cost_per_valid,
        "cost_per_valid_template_status": cost_per_valid_status,
        "error_taxonomy": dict(
            sorted(Counter(run["error"]["code"] for run in runs if run["error"]).items())
        ),
    }


def _num(value: float | None, digits: int = 3) -> str:
    return "N/A" if value is None else f"{value:.{digits}f}"


def _pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.0%}"


def _cost(value: float | None, status: str | None = None) -> str:
    rendered = display_cost(value)
    return f"{rendered} ({status})" if status and value is not None else rendered


def _markdown(report: dict[str, Any]) -> str:
    metadata = report["metadata"]
    budget = report["budget"]
    lines: list[str] = [
        "# Live multi-provider evaluation",
        "",
        f"Generated {report['generated_at']} by `benchmarks/live_evaluation.py`.",
        "",
        "Costs are estimates from the versioned price table "
        f"`{report['pricing']['version']}` (as of {report['pricing']['as_of']}). "
        "`observed` means the provider reported token usage and the model has a "
        "published price; `estimated` means a documented proxy rate was used; "
        "`unavailable` means neither exists, which is **not** the same as free.",
        "",
        "## Run metadata",
        "",
        f"- Dataset: `{metadata['dataset']['file']}` "
        f"({metadata['dataset']['case_count']} cases, hash `{metadata['dataset']['hash']}`)",
        f"- Repeats per case and provider: {metadata['repeats']}",
        f"- Repair attempts per plan: {metadata['repair_attempts']} "
        f"(max output {metadata['max_output_tokens']} tokens, timeout {metadata['timeout_seconds']:.0f}s)",
        f"- Compact mode: {metadata['compact_mode']} "
        f"(version {metadata['compact_version'] or 'n/a'})",
        f"- Pricing as of {report['pricing']['as_of']} (table `{report['pricing']['version']}`)",
        f"- Providers: {', '.join(item['provider'] + (':' + item['model'] if item['model'] else '') for item in report['providers'])}",
        "",
        "## Budget guard",
        "",
        f"- Cap: {display_cost(budget['max_spend_usd'])}",
        f"- Known spend (published prices): {display_cost(budget['known_spend_usd'])}",
        f"- Estimated spend (proxy rates): {display_cost(budget['estimated_spend_usd'])}",
        f"- Total (known + estimated): {display_cost(budget['total_spend_usd'])}",
        f"- Unknown-cost runs: {budget['unknown_cost_runs']}",
        f"- Allow unpriced: {'yes' if budget['allow_unpriced'] else 'no'}",
        f"- Aborted early: {'yes' if budget['aborted'] else 'no'}",
    ]
    if budget["aborted"]:
        lines += [f"> Aborted: {budget['abort_reason']}", ""]
    lines.append("")

    lines += [
        "## Provider summary",
        "",
        "| Provider | Model | Runs | Planned | Valid | Precision | Recall | Coverage | Validation | Compile | p50 | p95 | Cost | Cost/valid | Cost status |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for aggregate in report["aggregates"]:
        lines.append(
            "| {provider} | {model} | {runs} | {planned} | {valid} | {precision} | {recall} | "
            "{coverage} | {validation} | {compile} | {p50} | {p95} | {cost} | {cost_valid} | "
            "{cost_status} |".format(
                provider=aggregate["provider"],
                model=aggregate["model"] or "(default)",
                runs=aggregate["runs"],
                planned=aggregate["planned_runs"],
                valid=aggregate["valid_runs"],
                precision=_num(aggregate["field_precision"]),
                recall=_num(aggregate["field_recall"]),
                coverage=_num(aggregate["requirement_coverage"]),
                validation=_pct(aggregate["validation_pass_rate"]),
                compile=_pct(aggregate["compilation_success_rate"]),
                p50=(
                    f"{aggregate['latency_ms']['p50']:.0f} ms"
                    if aggregate["latency_ms"]["p50"] is not None
                    else "N/A"
                ),
                p95=(
                    f"{aggregate['latency_ms']['p95']:.0f} ms"
                    if aggregate["latency_ms"]["p95"] is not None
                    else "N/A"
                ),
                cost=_cost(aggregate["cost_usd"], aggregate["cost_status"]),
                cost_valid=_cost(
                    aggregate["cost_per_valid_template_usd"],
                    aggregate["cost_per_valid_template_status"],
                ),
                cost_status=aggregate["cost_per_valid_template_status"],
            )
        )
    lines += [
        "",
        f"Recommendation: **{report['recommendation']['provider'] or 'none'}**",
        "",
        report["recommendation"]["rationale"],
        "",
        "## Error taxonomy",
        "",
        f"Codes: {', '.join(report['error_codes'])}.",
        "",
        "| Provider | " + " | ".join(report["error_codes"]) + " |",
        "| --- | " + " | ".join("---:" for _ in report["error_codes"]) + " |",
    ]
    for aggregate in report["aggregates"]:
        taxonomy = aggregate["error_taxonomy"]
        lines.append(
            "| {provider} | {cells} |".format(
                provider=aggregate["provider"],
                cells=" | ".join(str(taxonomy.get(code, 0)) for code in report["error_codes"]),
            )
        )
    totals = report["error_taxonomy"]
    lines.append(
        "| **total** | {cells} |".format(
            cells=" | ".join(str(totals.get(code, 0)) for code in report["error_codes"])
        )
    )
    lines += [""]

    lines += [
        "## Per-case results",
        "",
        "| Case | Repeat | Provider | Precision | Recall | Coverage | Validation | Compiled | Latency | Cost | Error |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for run in report["runs"]:
        lines.append(
            "| {case} | {repeat} | {provider} | {precision} | {recall} | {coverage} | "
            "{validation} | {compiled} | {latency} ms | {cost} | {error} |".format(
                case=run["case_id"],
                repeat=run["repeat"],
                provider=run["provider"]
                + (f":{run['requested_model']}" if run["requested_model"] else ""),
                precision=_num(run["precision"]),
                recall=_num(run["recall"]),
                coverage=_num(run["requirement_coverage"]),
                validation="pass" if run["validation_passed"] else "fail",
                compiled="yes" if run["compiled"] else "no",
                latency=run["latency_ms"],
                cost=_cost(run["cost_usd"], run["cost_status"]),
                error=(run["error"] or {}).get("message", "")[:120].replace("|", "/"),
            )
        )
    lines += [
        "",
        "## Caveats",
        "",
        f"- {metadata['repeats']} repeats per case and provider: these are observations, not a "
        "statistically significant benchmark.",
        "- Latency includes prompt assembly, the provider call and deterministic repair, but not HTTP "
        "transport to this harness.",
        "- The recommendation is lexicographic: quality first, then cost per valid template, then p50 "
        "latency. Estimated proxy costs count as a budget number but keep their status in the report.",
        "- The missing-field case has no expected binding set, so it is excluded from precision/recall; "
        "its requirement coverage is still reported.",
        "- Per-run traces are written under `docs/media/runs/` (git-ignored) and contain no prompt text.",
        "",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--providers", default="mock:mock-planner-v1")
    parser.add_argument("--limit", type=int, default=None, help="first N cases")
    parser.add_argument("--case-ids", default="", help="comma-separated case ids")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_MD)
    parser.add_argument("--trace-dir", type=Path, default=DEFAULT_TRACE_DIR)
    parser.add_argument("--no-traces", action="store_true")
    parser.add_argument(
        "--max-spend",
        "--max-spend-usd",
        dest="max_spend_usd",
        type=float,
        default=DEFAULT_MAX_SPEND,
        help="abort when known + estimated spend or the next worst case would exceed this",
    )
    parser.add_argument(
        "--repeats", type=int, default=DEFAULT_REPEATS, help="runs per case/provider"
    )
    parser.add_argument("--allow-unpriced", action="store_true")
    parser.add_argument("--max-output-tokens", type=int, default=None)
    parser.add_argument(
        "--compact-ir",
        choices=["auto", "on", "off"],
        default="auto",
        help=(
            "auto (default) uses the compact wire format for Gemini and full IR for "
            "other providers; on forces compact for every provider; off forces full IR"
        ),
    )
    parser.add_argument(
        "--compact-version",
        choices=["v1", "v2"],
        default="v2",
        help="compact wire-format revision (v2 is the ultra-compact array format)",
    )
    parser.add_argument(
        "--repair-attempts",
        type=int,
        default=1,
        choices=[0, 1, 2],
        help="0 = exactly one generation; 1-2 allow the planner's repair calls",
    )
    args = parser.parse_args(argv)
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")

    definitions = json.loads(args.cases.read_text(encoding="utf-8"))
    if args.case_ids:
        wanted = {item.strip() for item in args.case_ids.split(",") if item.strip()}
        definitions = [item for item in definitions if item["case_id"] in wanted]
    if args.limit is not None:
        definitions = definitions[: max(0, args.limit)]
    if not definitions:
        print("No cases selected", file=sys.stderr)
        return 2

    targets = _parse_providers(args.providers)
    base_settings = get_settings()
    settings = dataclasses.replace(
        base_settings,
        llm_max_retries=0,
        llm_max_output_tokens=args.max_output_tokens or base_settings.llm_max_output_tokens,
    )
    gateway = LLMGateway(settings)
    planner = TemplatePlanner(gateway)
    validator = ValidationEngine(
        max_blocks=settings.limits.max_ir_blocks,
        max_depth=settings.limits.max_ir_depth,
        max_text_length=settings.limits.max_text_length,
    )
    trace_dir = None if args.no_traces else args.trace_dir

    parsed_packages: dict[str, Any] = {}
    provider_state: list[dict[str, Any]] = []
    for provider, model in targets:
        configured = True
        try:
            gateway.get(provider)
        except ProviderError:
            configured = False
        resolved_model = gateway.resolve_model(provider, model) if configured else model
        compact_ir = _compact_enabled(args.compact_ir, provider)
        provider_state.append(
            {
                "provider": provider,
                "model": model,
                "requested_model": resolved_model,
                "configured": configured,
                "compact_ir": compact_ir,
                "compact_version": args.compact_version if compact_ir else None,
            }
        )
        if not configured:
            print(f"warning: provider '{provider}' is not configured; runs will be failures")

    runs: list[dict[str, Any]] = []
    known_spend = 0.0
    estimated_spend = 0.0
    aborted = False
    abort_reason = ""
    stop = False

    for repeat in range(1, args.repeats + 1):
        if stop:
            break
        for definition in definitions:
            if stop:
                break
            package = ROOT / definition["package"]
            parsed = parsed_packages.get(str(package))
            if parsed is None:
                parsed = parse_ddsp(package.read_bytes(), package.name)
                parsed_packages[str(package)] = parsed
            for state in provider_state:
                provider = state["provider"]
                model = state["model"]
                requested_model = state["requested_model"]
                if not state["configured"]:
                    run = _run_one(
                        planner=planner,
                        validator=validator,
                        parsed=parsed,
                        definition=definition,
                        provider=provider,
                        model=model,
                        provider_configured=False,
                        repeat=repeat,
                        repair_attempts=args.repair_attempts,
                        compact_ir=state["compact_ir"],
                        compact_version=args.compact_version,
                    )
                    runs.append(run)
                    continue

                compact_ir = state["compact_ir"]
                compact_version = args.compact_version if compact_ir else "v1"
                messages = _messages_for(
                    parsed.schema, definition["prompt"], compact_ir, compact_version
                )
                _price, pricing_known = price_for(requested_model or model or "")
                if not pricing_known and not args.allow_unpriced:
                    aborted = True
                    abort_reason = (
                        f"refusing to call unpriced model '{requested_model or model}': the budget "
                        "guard cannot bound the spend (use --allow-unpriced to override)"
                    )
                    stop = True
                    break
                if not pricing_known:
                    print(
                        f"warning: {requested_model or model} is unpriced; "
                        "budget guard uses the documented proxy rate"
                        if _proxy_for(requested_model or model or "")
                        else f"warning: {requested_model or model} is unpriced and has no proxy; "
                        "budget guard is advisory"
                    )
                worst_case = _worst_case_cost(
                    messages,
                    requested_model or model or "",
                    settings.llm_max_output_tokens,
                    calls=args.repair_attempts + 1,
                )
                spent_total = round(known_spend + estimated_spend, 6)
                if worst_case is not None and spent_total + worst_case > args.max_spend_usd:
                    aborted = True
                    abort_reason = (
                        f"next call plus repairs could cost up to {display_cost(worst_case)}; "
                        f"running spend {display_cost(spent_total)} would exceed the "
                        f"{display_cost(args.max_spend_usd)} cap"
                    )
                    stop = True
                    break

                run = _run_one(
                    planner=planner,
                    validator=validator,
                    parsed=parsed,
                    definition=definition,
                    provider=provider,
                    model=requested_model,
                    provider_configured=True,
                    repeat=repeat,
                    repair_attempts=args.repair_attempts,
                    compact_ir=compact_ir,
                    compact_version=compact_version,
                )
                runs.append(run)
                if run["cost_status"] == "observed" and run["cost_usd"] is not None:
                    known_spend = round(known_spend + run["cost_usd"], 6)
                elif run["cost_status"] == "estimated" and run["cost_usd"] is not None:
                    estimated_spend = round(estimated_spend + run["cost_usd"], 6)

                _write_trace(
                    trace_dir,
                    {
                        "schema": "live-benchmark-trace/v2",
                        **{
                            key: run[key]
                            for key in (
                                "run_id",
                                "repeat",
                                "case_id",
                                "category",
                                "provider",
                                "requested_model",
                                "actual_provider",
                                "actual_model",
                                "ok",
                                "valid",
                                "error",
                                "latency_ms",
                                "usage",
                                "cost_usd",
                                "cost_status",
                                "compact_ir",
                                "compact_version",
                                "validation",
                                "validation_passed",
                                "compiled",
                                "requirement_coverage",
                                "precision",
                                "recall",
                                "true_positives",
                                "expected_fields",
                                "selected_fields",
                                "actual_paths",
                                "removed_bindings",
                                "ir_digest",
                                "prompt_chars",
                                "prompt_sha256",
                                "finish_reason",
                                "finished_at",
                            )
                        },
                        "pricing": price_table_metadata(),
                        "proxy_pricing": PROXY_PRICES,
                    },
                )
                status = (
                    "valid"
                    if run["valid"]
                    else (
                        "planned" if run["ok"] else f"FAILED ({(run['error'] or {}).get('code')})"
                    )
                )
                spent_total = round(known_spend + estimated_spend, 6)
                print(
                    f"{definition['case_id']:<32} r{repeat} {provider:<10} {status:<22} "
                    f"{display_cost(run['cost_usd']):>11}  running {display_cost(spent_total)}"
                )
                if run["cost_status"] == "unavailable":
                    print("  cost unknown (N/A): no published price or proxy")
                if spent_total > args.max_spend_usd:
                    aborted = True
                    abort_reason = (
                        f"running spend {display_cost(spent_total)} exceeded the "
                        f"{display_cost(args.max_spend_usd)} cap"
                    )
                    stop = True
                    break
                if run["error"] and run["error"]["code"] in {"quota"}:
                    aborted = True
                    abort_reason = "the provider reported a quota error; stopping"
                    stop = True
                    break

    aggregates: list[dict[str, Any]] = []
    for state in provider_state:
        provider_runs = [
            run
            for run in runs
            if run["provider"] == state["provider"]
            and run["requested_model"] == state["requested_model"]
        ]
        aggregate = _aggregate(provider_runs)
        aggregate.update(
            {
                "provider": state["provider"],
                "model": state["model"],
                "requested_model": state["requested_model"],
                "compact_ir": state["compact_ir"],
                "compact_version": state["compact_version"],
                "observed_models": sorted(
                    {run["actual_model"] for run in provider_runs if run["actual_model"]}
                ),
            }
        )
        aggregates.append(aggregate)
    for state in provider_state:
        state["observed_models"] = sorted(
            {
                run["actual_model"]
                for run in runs
                if run["provider"] == state["provider"] and run["actual_model"]
            }
        )

    scored = [
        ProviderScore(
            provider=item["provider"],
            model=item["model"],
            quality=item["quality_score"],
            cost_usd=item["cost_per_valid_template_usd"],
            latency_p50_ms=item["latency_ms"]["p50"],
        )
        for item in aggregates
    ]
    recommended = recommend_provider(scored)
    rationale = (
        "Quality first (weighted precision, recall and coverage, gated by validation), "
        "then cost per valid template, then p50 latency. Estimated proxy costs count as "
        "budget numbers but keep their status; unavailable costs sort last."
    )
    overall_taxonomy = dict(
        sorted(Counter(run["error"]["code"] for run in runs if run["error"]).items())
    )
    unknown_cost_runs = sum(1 for run in runs if run["cost_status"] == "unavailable")
    generated_at = _iso(datetime.now(UTC))
    report = {
        "schema": "live-benchmark/v2",
        "generated_by": "benchmarks/live_evaluation.py",
        "generated_at": generated_at,
        "metadata": {
            "dataset": _dataset_metadata(definitions, args.cases),
            "repeats": args.repeats,
            "repair_attempts": args.repair_attempts,
            "max_output_tokens": settings.llm_max_output_tokens,
            "timeout_seconds": settings.llm_timeout_seconds,
            "compact_mode": args.compact_ir,
            "compact_version": (
                args.compact_version
                if any(state["compact_ir"] for state in provider_state)
                else None
            ),
            "provider_versions": provider_state,
        },
        "pricing": {
            **price_table_metadata(),
            "version": price_table_metadata()["pricing_version"],
            "as_of": price_table_metadata()["pricing_as_of"],
            "source": price_table_metadata()["pricing_source"],
            "proxy_pricing": PROXY_PRICES,
        },
        "pricing_version": price_table_metadata()["pricing_version"],
        "pricing_as_of": price_table_metadata()["pricing_as_of"],
        "pricing_source": price_table_metadata()["pricing_source"],
        "cases_file": _dataset_metadata(definitions, args.cases)["file"],
        "case_count": len(definitions),
        "cases_run": len({run["case_id"] for run in runs}),
        "repair_attempts": args.repair_attempts,
        "compact_ir": args.compact_ir,
        "compact_version": (
            args.compact_version if any(state["compact_ir"] for state in provider_state) else None
        ),
        "max_output_tokens": settings.llm_max_output_tokens,
        "providers": provider_state,
        "budget": {
            "max_spend_usd": args.max_spend_usd,
            "known_spend_usd": round(known_spend, 6),
            "estimated_spend_usd": round(estimated_spend, 6),
            "total_spend_usd": round(known_spend + estimated_spend, 6),
            "unknown_cost_runs": unknown_cost_runs,
            "allow_unpriced": args.allow_unpriced,
            "aborted": aborted,
            "abort_reason": abort_reason,
        },
        "runs": runs,
        "aggregates": aggregates,
        "error_taxonomy": overall_taxonomy,
        "error_codes": list(ERROR_CODES),
        "recommendation": {
            "provider": recommended,
            "quality_first": True,
            "utility": "quality > cost per valid template > p50 latency",
            "rationale": rationale,
        },
    }

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(_markdown(report), encoding="utf-8")

    print()
    for aggregate in aggregates:
        print(
            f"{aggregate['provider']}: quality {aggregate['quality_score']:.3f} "
            f"valid {aggregate['valid_runs']}/{aggregate['runs']} "
            f"precision {aggregate['field_precision']} recall {aggregate['field_recall']} "
            f"coverage {aggregate['requirement_coverage']} "
            f"p50 {aggregate['latency_ms']['p50']} ms "
            f"cost {display_cost(aggregate['cost_usd'])} "
            f"cost/valid {display_cost(aggregate['cost_per_valid_template_usd'])} "
            f"({aggregate['cost_per_valid_template_status']})"
        )
    print(f"recommended: {recommended or 'none'}")
    print(
        f"spend: known {display_cost(known_spend)}, estimated {display_cost(estimated_spend)}, "
        f"total {display_cost(known_spend + estimated_spend)} "
        f"(unknown-cost runs: {unknown_cost_runs})"
    )
    print(f"written to {args.output_json} and {args.output_md}")
    return 1 if aborted else 0


if __name__ == "__main__":
    raise SystemExit(main())
