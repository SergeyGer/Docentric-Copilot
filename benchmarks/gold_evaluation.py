#!/usr/bin/env python3
"""Gold semantic benchmark runner (v0.10 PR-05).

This runner measures business semantics, not only compilation. Each case from
``benchmarks/gold_cases.json`` is planned ``--repeats`` times per provider; the
produced IR is scored against concept-level gold bindings, forbidden paths and
required blocks. Precision, recall, F1, requirement coverage, type/context
correctness and block coverage are reported separately from the deterministic
``valid_template_rate``.

Cost is three-valued:

* ``verified`` - the provider reported usage and the model has a published price
  in the versioned price table;
* ``estimated`` - the model is unpriced (Gemini 3.6-flash) and a documented
  proxy rate is used; the proxy is named in the report;
* ``unavailable`` - neither exists. Unknown is never rendered as ``$0.00``.

The budget guard warns at ``--warn-spend`` and aborts before a call whose
worst case could cross ``--max-spend``. The default prompt settings follow the
product contract: Gemini uses compact v2 with two repair calls, the other
providers use the full IR contract with one repair call.

Usage::

    .venv/bin/python benchmarks/gold_evaluation.py \
        --providers openai:gpt-6-sol,anthropic:claude-sonnet-5-5,gemini:gemini-3.6-flash \
        --repeats 3 --split all --max-spend 10 --warn-spend 5 --allow-unpriced

Per-run records are appended to the git-ignored ``benchmarks/gold_runs.jsonl``
(no prompt text, no raw provider output). Aggregates are written to
``benchmarks/gold_report.json``, ``.csv`` and a self-contained ``.html``.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import dataclasses
import hashlib
import html
import io
import json
import re
import sys
import time
import uuid
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # pragma: no cover - import bootstrap when run as a script
    sys.path.insert(0, str(ROOT))

from docentric_copilot.config import get_settings  # noqa: E402
from docentric_copilot.ddsp_parser import parse_ddsp  # noqa: E402
from docentric_copilot.docx_compiler import CompileOptions, GenericDocxCompiler  # noqa: E402
from docentric_copilot.llm import LLMGateway  # noqa: E402
from docentric_copilot.llm.pricing import (  # noqa: E402
    estimate_cost,
    price_for,
    price_table_metadata,
)
from docentric_copilot.planner import (  # noqa: E402
    COMPACT_V2_GENERATOR,
    PROMPT_VERSION,
    PlanOptions,
    TemplatePlanner,
    build_compact_messages_v2,
    build_messages,
)
from docentric_copilot.template_validator import ValidationEngine  # noqa: E402

from benchmarks.gold_dataset import (  # noqa: E402
    DEFAULT_CASES,
    GOLD_SPLITS,
    cases_for_split,
    dataset_metadata,
    load_gold_dataset,
    validate_gold_dataset,
)
from benchmarks.semantic_evaluation import (  # noqa: E402
    OBSERVATIONS_NOTE,
    PROXY_PRICES,
    collect_produced_bindings,
    collect_produced_blocks,
)
from benchmarks.semantic_scoring import (  # noqa: E402
    ERROR_TAXONOMY,
    classify_exception,
    score_run,
    taxonomy_for_validation_codes,
)

DEFAULT_CASES = DEFAULT_CASES
DEFAULT_RUNS = ROOT / "benchmarks" / "gold_runs.jsonl"
DEFAULT_JSON = ROOT / "benchmarks" / "gold_report.json"
DEFAULT_CSV = ROOT / "benchmarks" / "gold_report.csv"
DEFAULT_HTML = ROOT / "benchmarks" / "gold_report.html"
DEFAULT_MAX_SPEND = 10.0
DEFAULT_WARN_SPEND = 5.0
DEFAULT_REPEATS = 3
DEFAULT_PAID_REPAIR_ATTEMPTS = 1
GEMINI_REPAIR_ATTEMPTS = 2
MAX_OUTPUT_TOKENS = 16_000
_MAX_TOKENS_PER_CHAR = 0.35
_SECRET = re.compile(r"(?i)(api[-_]?key|authorization|bearer)\s*[=:]\s*\S+")

#: Metrics shown per provider and per task family.
METRIC_KEYS = (
    "precision",
    "recall",
    "f1",
    "requirement_coverage",
    "type_context_correctness",
    "block_coverage",
    "semantic_pass_rate",
    "valid_template_rate",
    "validation_pass_rate",
    "compilation_success_rate",
)


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _redact(text: str) -> str:
    return _SECRET.sub("[redacted]", text)[:500]


def _ratio(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 3)


def _ordered_codes(codes: Iterable[str]) -> tuple[str, ...]:
    unique = {code for code in codes if code}
    unknown = unique - set(ERROR_TAXONOMY)
    if unknown:
        raise ValueError(f"unknown error codes: {sorted(unknown)}")
    return tuple(sorted(unique, key=ERROR_TAXONOMY.index))


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


def _proxy_for(model: str) -> dict[str, Any] | None:
    lowered = model.lower()
    matches = [prefix for prefix in PROXY_PRICES if lowered.startswith(prefix)]
    if not matches:
        return None
    return PROXY_PRICES[max(matches, key=len)]


def _usage_cost(
    usage: dict[str, Any] | None, model: str
) -> tuple[float | None, str, dict[str, Any] | None]:
    """Return ``(cost_usd, verified|estimated|unavailable, proxy)``."""
    if not usage:
        return None, "unavailable", None
    known = usage.get("estimated_cost_usd")
    if known is not None:
        return float(known), "verified", None
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
    messages: Sequence[Any], model: str, max_output_tokens: int, *, calls: int
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


def _messages_for(schema: Any, prompt: str, *, compact: bool, language: str) -> list[Any]:
    if compact:
        return build_compact_messages_v2(schema, prompt, language=language)
    return build_messages(schema, prompt, language=language)


def _write_json(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _display_path(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


# --------------------------------------------------------------------------- #
# Provider configuration
# --------------------------------------------------------------------------- #
def _configure_provider(
    gateway: LLMGateway,
    provider: str,
    model: str | None,
    *,
    repeats: int,
    paid_repeats: int | None,
    paid_repair_attempts: int,
) -> dict[str, Any]:
    configured = True
    try:
        gateway.get(provider)
    except Exception:
        configured = False
    resolved_model = gateway.resolve_model(provider, model) if configured else model
    compact = provider == "gemini"
    repair_attempts = GEMINI_REPAIR_ATTEMPTS if compact else paid_repair_attempts
    provider_repeats = repeats if compact or paid_repeats is None else min(repeats, paid_repeats)
    priced, known_price = price_for(resolved_model or model or "")
    return {
        "provider": provider,
        "model": model,
        "requested_model": resolved_model,
        "configured": configured,
        "compact_ir": compact,
        "compact_version": "v2" if compact else None,
        "repair_attempts": repair_attempts,
        "repeats": provider_repeats,
        "priced": known_price,
        "price": {
            "input_per_mtok": priced.input_per_mtok,
            "output_per_mtok": priced.output_per_mtok,
        }
        if priced is not None
        else None,
    }


# --------------------------------------------------------------------------- #
# One run
# --------------------------------------------------------------------------- #
def _run_one(
    *,
    planner: TemplatePlanner,
    validator: ValidationEngine,
    compiler: GenericDocxCompiler,
    parsed: Any,
    case: Mapping[str, Any],
    provider: str,
    model: str | None,
    repeat: int,
    repair_attempts: int,
    compact_ir: bool,
    compact_version: str | None,
) -> dict[str, Any]:
    case_id = str(case["id"])
    prompt = str(case["prompt"])
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    run_id = f"gold_{uuid.uuid4().hex[:16]}"
    record: dict[str, Any] = {
        "schema": "gold-run/v1",
        "run_id": run_id,
        "repeat": repeat,
        "started_at": _iso(started_at),
        "case_id": case_id,
        "family": case.get("family"),
        "category": case.get("category"),
        "split": case.get("split"),
        "difficulty": case.get("difficulty"),
        "language": case.get("language", "en"),
        "package": case.get("package"),
        "provider": provider,
        "requested_model": model,
        "actual_provider": None,
        "actual_model": None,
        "compact_ir": compact_ir,
        "compact_version": compact_version,
        "repair_attempts": repair_attempts,
        "prompt_version": COMPACT_V2_GENERATOR if compact_ir else PROMPT_VERSION,
        "prompt_sha256": _digest(prompt),
        "prompt_chars": len(prompt),
        "ok": False,
        "valid_template": False,
        "semantic_pass": False,
        "correct": False,
        "semantic": None,
        "validation": {},
        "validation_passed": False,
        "validation_codes": [],
        "compiled": False,
        "compile_error": None,
        "error": None,
        "error_codes": [],
        "primary_error": None,
        "latency_ms": 0,
        "usage": None,
        "cost_usd": None,
        "cost_status": "unavailable",
        "cost_known": False,
        "cost_proxy": None,
        "ir_digest": None,
        "finish_reason": None,
        "attempts": 0,
        "produced_paths": [],
        "forbidden_hits": [],
        "missing_requirements": [],
        "wrong_paths": [],
        "mapping_counts": {},
        "review_requirements": [],
        "abstained": False,
        "semantic_excluded": False,
        "candidate_summary": {},
        "binding_review_counts": {},
    }

    try:
        outcome = asyncio.run(
            planner.plan(
                parsed.schema,
                prompt,
                provider=provider,
                model=model,
                options=PlanOptions(
                    language=str(case.get("language", "en")),
                    max_repair_attempts=repair_attempts,
                    compact_ir=compact_ir,
                    compact_version=compact_version or "v2",  # type: ignore[arg-type]
                ),
            )
        )
    except Exception as exc:
        code, message = classify_exception(exc)
        record["error"] = {"code": code, "message": message}
        record["error_codes"] = [code]
        record["primary_error"] = code
        record["latency_ms"] = int((time.perf_counter() - started) * 1000)
        record["finished_at"] = _iso(datetime.now(UTC))
        return record

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    report = validator.validate(outcome.document, parsed.schema, sample_data=parsed.sample_data)
    validation_codes = sorted({finding.code for finding in report.errors()})
    compiled = False
    compile_error: str | None = None
    if report.can_compile:
        try:
            result = compiler.compile(
                outcome.document,
                parsed.schema,
                CompileOptions(document_name=f"{case_id}.docx"),
                sample_data=parsed.sample_data,
            )
            compiled = bool(result.success)
        except Exception as exc:
            compile_error = _redact(f"{type(exc).__name__}: {exc}")

    produced = collect_produced_bindings(outcome.document, parsed.schema, outcome.mapping)
    blocks = collect_produced_blocks(outcome.document, parsed.schema)
    score = score_run(case, produced, produced_blocks=blocks)
    mapping_counts = outcome.mapping.counts()
    review_requirements = [
        mapping.requirement_id
        for mapping in outcome.mapping.mappings
        if getattr(mapping.status, "value", mapping.status) == "needs_review"
    ]
    abstained = any(
        getattr(mapping.status, "value", mapping.status) == "needs_review"
        and mapping.selected_field_path is None
        for mapping in outcome.mapping.mappings
    )
    review_counts = Counter(str(review.get("status")) for review in (outcome.binding_reviews or []))
    semantic_passed = bool(score.semantic_pass and not score.excluded_from_semantic)

    codes = list(score.error_codes)
    if not report.can_compile:
        codes.extend(taxonomy_for_validation_codes(validation_codes))
    elif not compiled:
        codes.append("compilation")
    ordered_codes = _ordered_codes(codes)
    if not report.can_compile:
        primary = next(
            (code for code in ordered_codes if code not in score.error_codes),
            ordered_codes[0] if ordered_codes else "wrong_context",
        )
    elif not compiled:
        primary = "compilation"
    elif ordered_codes:
        primary = ordered_codes[0]
    else:
        primary = None

    generation = outcome.generation
    usage = generation.usage.model_dump(mode="json") if generation is not None else None
    public = generation.public_view() if generation is not None else {}
    cost, cost_status, proxy = _usage_cost(usage, model or "")
    valid_template = bool(report.can_compile and compiled)
    missing = [
        outcome_item.requirement_id
        for outcome_item in score.outcomes
        if outcome_item.required and outcome_item.satisfiable and not outcome_item.satisfied
    ]
    wrong_paths = [
        outcome_item.requirement_id
        for outcome_item in score.outcomes
        if outcome_item.matched_via == "wrong_path"
    ]
    record.update(
        {
            "ok": True,
            "valid_template": valid_template,
            "semantic_pass": semantic_passed,
            "semantic_excluded": score.excluded_from_semantic,
            "correct": bool(semantic_passed and valid_template),
            "semantic": score.as_dict(),
            "mapping_counts": mapping_counts,
            "review_requirements": review_requirements,
            "abstained": abstained,
            "candidate_summary": outcome.candidate_summary,
            "binding_review_counts": dict(sorted(review_counts.items())),
            "validation": report.statuses(),
            "validation_passed": report.can_compile,
            "validation_codes": validation_codes,
            "compiled": compiled,
            "compile_error": compile_error,
            "error": (
                None
                if semantic_passed and valid_template and not ordered_codes
                else {
                    "code": primary or "harness",
                    "message": (
                        "semantic requirements unmet: " + ", ".join(missing)
                        if missing
                        else "deterministic validation/compilation or semantic checks failed"
                    ),
                }
            ),
            "error_codes": ordered_codes,
            "primary_error": primary,
            "actual_provider": public.get("provider"),
            "actual_model": public.get("model"),
            "latency_ms": elapsed_ms,
            "usage": usage,
            "cost_usd": cost,
            "cost_status": cost_status,
            "cost_known": cost is not None,
            "cost_proxy": proxy,
            "finish_reason": generation.finish_reason if generation is not None else None,
            "attempts": generation.attempts if generation is not None else 0,
            "produced_paths": sorted({binding.path for binding in produced})[:80],
            "forbidden_hits": list(score.forbidden_hits),
            "missing_requirements": missing,
            "wrong_paths": wrong_paths,
        }
    )
    record["finished_at"] = _iso(datetime.now(UTC))
    return record


# --------------------------------------------------------------------------- #
# Aggregates
# --------------------------------------------------------------------------- #
def _pass_at_k(runs: Sequence[Mapping[str, Any]], max_k: int) -> dict[str, float | None]:
    """Pass@k over (provider, case) groups.

    The rate is the fraction of groups with at least one semantic pass among the
    first k executed repeats. A group with fewer than k runs is excluded from
    that k's denominator and the report says so; it is never silently treated as
    a failure. Runs whose case is excluded by ``label_status: gap`` are not in
    the numerator or denominator.
    """
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for run in runs:
        semantic = run.get("semantic") or {}
        if semantic.get("excluded_from_semantic"):
            continue
        groups.setdefault((str(run["provider"]), str(run["case_id"])), []).append(run)
    result: dict[str, float | None] = {}
    for k in range(1, max_k + 1):
        eligible = [group for group in groups.values() if len(group) >= k]
        if not eligible:
            result[str(k)] = None
            continue
        passed = 0
        for group in eligible:
            ordered = sorted(group, key=lambda run: int(run.get("repeat") or 0))[:k]
            passed += 1 if any(run.get("semantic_pass") for run in ordered) else 0
        result[str(k)] = round(passed / len(eligible), 6)
    return result


def _aggregate(runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    planned = [run for run in runs if run.get("ok")]
    all_semantic = [run["semantic"] for run in planned if run.get("semantic")]
    semantic = [item for item in all_semantic if not item.get("excluded_from_semantic")]
    excluded_semantic = len(all_semantic) - len(semantic)
    valid = [run for run in planned if run.get("valid_template")]
    correct = [run for run in planned if run.get("correct")]
    abstained_runs = sum(1 for run in runs if run.get("abstained"))
    review_runs = sum(1 for run in runs if run.get("review_requirements"))

    precision_tp = sum(int(item["true_positives"]) for item in semantic)
    precision_den = sum(
        int(item["true_positives"]) + int(item["false_positives"]) for item in semantic
    )
    required_den = sum(int(item["required_requirements"]) for item in semantic)
    matched_required = sum(int(item["matched_required"]) for item in semantic)
    coverage_den = sum(int(item["satisfiable_requirements"]) for item in semantic)
    matched = sum(int(item["matched_requirements"]) for item in semantic)
    type_checks = sum(int(item["type_context_checks"]) for item in semantic)
    type_correct = sum(int(item["type_context_correct"]) for item in semantic)
    block_total = sum(int(item["block_total"]) for item in semantic)
    block_satisfied = sum(int(item["block_satisfied"]) for item in semantic)
    semantic_passes = sum(1 for item in semantic if item["semantic_pass"])

    precision = _ratio(precision_tp, precision_den)
    recall = _ratio(matched_required, required_den)
    f1 = (
        None
        if precision is None or recall is None
        else (
            0.0
            if precision + recall == 0
            else round(2 * precision * recall / (precision + recall), 6)
        )
    )

    verified_costs = [float(run["cost_usd"]) for run in planned if run["cost_status"] == "verified"]
    estimated_costs = [
        float(run["cost_usd"]) for run in planned if run["cost_status"] == "estimated"
    ]
    unknown_runs = sum(1 for run in runs if run.get("cost_status") == "unavailable")
    total_cost = round(sum(verified_costs) + sum(estimated_costs), 6)
    if estimated_costs:
        cost_status = "estimated"
    elif verified_costs:
        cost_status = "verified"
    else:
        cost_status = "unavailable"
    complete_cost = bool(planned) and unknown_runs == 0
    cost_per_correct = round(total_cost / len(correct), 6) if correct and complete_cost else None
    cost_per_correct_status = (
        "unavailable"
        if cost_per_correct is None
        else ("estimated" if estimated_costs else "verified")
    )
    latencies = [float(run["latency_ms"]) for run in planned]
    error_counts: Counter[str] = Counter()
    primary_counts: Counter[str] = Counter()
    for run in runs:
        for code in run.get("error_codes", []):
            error_counts[code] += 1
        primary = run.get("primary_error")
        if primary:
            primary_counts[primary] += 1

    return {
        "runs": len(runs),
        "planned_runs": len(planned),
        "failed_runs": len(runs) - len(planned),
        "valid_runs": len(valid),
        "correct_runs": len(correct),
        "precision": precision,
        "precision_numerator": precision_tp,
        "precision_denominator": precision_den,
        "recall": recall,
        "recall_numerator": matched_required,
        "recall_denominator": required_den,
        "f1": f1,
        "requirement_coverage": _ratio(matched, coverage_den),
        "coverage_numerator": matched,
        "coverage_denominator": coverage_den,
        "type_context_correctness": _ratio(type_correct, type_checks),
        "type_context_numerator": type_correct,
        "type_context_denominator": type_checks,
        "block_coverage": _ratio(block_satisfied, block_total),
        "block_numerator": block_satisfied,
        "block_denominator": block_total,
        "semantic_pass_rate": _ratio(semantic_passes, max(0, len(runs) - excluded_semantic)),
        "semantic_passes": semantic_passes,
        "semantic_excluded_runs": excluded_semantic,
        "semantic_denominator": max(0, len(runs) - excluded_semantic),
        "abstained_runs": abstained_runs,
        "abstention_rate": _ratio(abstained_runs, len(runs)),
        "review_runs": review_runs,
        "review_rate": _ratio(review_runs, len(runs)),
        "review_requirements": sum(len(run.get("review_requirements") or []) for run in runs),
        "pass_at_k": _pass_at_k(
            runs, max((int(run.get("repeat") or 1) for run in runs), default=1)
        ),
        "succeeded_runs": len(planned),
        "valid_template_rate": _ratio(len(valid), len(runs)),
        "validation_pass_rate": _ratio(
            sum(1 for run in planned if run.get("validation_passed")), len(planned)
        ),
        "compilation_success_rate": _ratio(
            sum(1 for run in planned if run.get("compiled")), len(planned)
        ),
        "latency_p50_ms": _percentile(latencies, 0.5),
        "latency_p95_ms": _percentile(latencies, 0.95),
        "latency_samples": len(latencies),
        "tokens": {
            "prompt": sum(int((run.get("usage") or {}).get("prompt_tokens", 0)) for run in planned),
            "completion": sum(
                int((run.get("usage") or {}).get("completion_tokens", 0)) for run in planned
            ),
        },
        "verified_cost_usd": round(sum(verified_costs), 6),
        "estimated_cost_usd": round(sum(estimated_costs), 6),
        "cost_usd": total_cost,
        "cost_status": cost_status,
        "unknown_cost_runs": unknown_runs,
        "cost_complete": complete_cost,
        "cost_per_correct_result_usd": cost_per_correct,
        "cost_per_correct_result_status": cost_per_correct_status,
        "error_counts": dict(sorted(error_counts.items())),
        "primary_error_counts": dict(sorted(primary_counts.items())),
    }


def _provider_report(state: Mapping[str, Any], runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    metrics = _aggregate(runs)
    models = sorted(
        {str(run["actual_model"] or run["requested_model"]) for run in runs if run.get("ok")}
    )
    status = "not_run" if not state.get("configured") else "run"
    reason = None
    if not state.get("configured"):
        reason = f"provider '{state['provider']}' has no API key configured"
    return {
        "provider": state["provider"],
        "requested_model": state["model"],
        "model": state["requested_model"],
        "observed_models": models,
        "configured": bool(state.get("configured")),
        "status": status,
        "not_run_reason": reason,
        "compact_ir": state["compact_ir"],
        "compact_version": state["compact_version"],
        "repair_attempts": state["repair_attempts"],
        "repeats": state["repeats"],
        "priced": state["priced"],
        "metrics": metrics,
        "cost": {
            "verified_usd": metrics["verified_cost_usd"],
            "estimated_usd": metrics["estimated_cost_usd"],
            "total_usd": metrics["cost_usd"],
            "status": metrics["cost_status"],
            "unknown_runs": metrics["unknown_cost_runs"],
            "per_correct_result_usd": metrics["cost_per_correct_result_usd"],
            "per_correct_result_status": metrics["cost_per_correct_result_status"],
        },
        "error_taxonomy": {
            "runs_with_code": metrics["error_counts"],
            "primary_counts": metrics["primary_error_counts"],
        },
        "proxies": {model: _proxy_for(model) for model in models if _proxy_for(model) is not None},
    }


def _leaders(providers: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    metrics = (
        ("precision", "higher"),
        ("recall", "higher"),
        ("f1", "higher"),
        ("requirement_coverage", "higher"),
        ("type_context_correctness", "higher"),
        ("semantic_pass_rate", "higher"),
        ("valid_template_rate", "higher"),
        ("cost_per_correct_result_usd", "lower"),
        ("latency_p50_ms", "lower"),
    )
    leaders: list[dict[str, Any]] = []
    for name, direction in metrics:
        values: list[tuple[str, float]] = []
        for provider in providers:
            value = provider["metrics"].get(name)
            if value is not None:
                values.append((str(provider["provider"]), float(value)))
        if not values:
            leaders.append({"metric": name, "direction": direction, "value": None, "leaders": []})
            continue
        best = (
            max(value for _provider, value in values)
            if direction == "higher"
            else min(value for _provider, value in values)
        )
        tied = sorted(provider for provider, value in values if abs(value - best) < 1e-9)
        leaders.append({"metric": name, "direction": direction, "value": best, "leaders": tied})
    return leaders


# --------------------------------------------------------------------------- #
# Report writers
# --------------------------------------------------------------------------- #
def _fmt(value: float | None, digits: int = 3) -> str:
    return "N/A" if value is None else f"{value:.{digits}f}"


def _pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.1%}"


def _money(value: float | None, status: str | None = None) -> str:
    if value is None:
        return "N/A" if not status else f"N/A ({status})"
    rendered = f"${value:.4f}"
    return f"{rendered} ({status})" if status else rendered


def _cost_cell(metrics: Mapping[str, Any]) -> str:
    """No run means no cost evidence; never render that as $0.00."""
    if not metrics.get("runs"):
        return "N/A"
    return _money(metrics.get("cost_usd"), metrics.get("cost_status"))


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]], *, css: str = "") -> str:
    head = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f'<table class="{css}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def _metric_cells(metrics: Mapping[str, Any]) -> list[str]:
    return [
        _fmt(metrics.get("precision")),
        _fmt(metrics.get("recall")),
        _fmt(metrics.get("f1")),
        _fmt(metrics.get("requirement_coverage")),
        _fmt(metrics.get("type_context_correctness")),
        _fmt(metrics.get("block_coverage")),
        _pct(metrics.get("semantic_pass_rate")),
        _pct(metrics.get("valid_template_rate")),
        _fmt(metrics.get("latency_p50_ms"), 1),
        _cost_cell(metrics),
    ]


def _csv_rows(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add(
        scope: str,
        split: str,
        family: str,
        category: str,
        provider: Mapping[str, Any],
        case_id: str,
    ) -> None:
        metrics = provider["metrics"]
        rows.append(
            {
                "scope": scope,
                "split": split,
                "family": family,
                "category": category,
                "provider": provider["provider"],
                "model": provider["model"] or "",
                "case_id": case_id,
                "runs": metrics["runs"],
                "planned_runs": metrics["planned_runs"],
                "valid_runs": metrics["valid_runs"],
                "correct_runs": metrics["correct_runs"],
                "precision": metrics["precision"],
                "recall": metrics["recall"],
                "f1": metrics["f1"],
                "requirement_coverage": metrics["requirement_coverage"],
                "type_context_correctness": metrics["type_context_correctness"],
                "block_coverage": metrics["block_coverage"],
                "semantic_pass_rate": metrics["semantic_pass_rate"],
                "valid_template_rate": metrics["valid_template_rate"],
                "validation_pass_rate": metrics["validation_pass_rate"],
                "compilation_success_rate": metrics["compilation_success_rate"],
                "latency_p50_ms": metrics["latency_p50_ms"],
                "latency_p95_ms": metrics["latency_p95_ms"],
                "prompt_tokens": metrics["tokens"]["prompt"],
                "completion_tokens": metrics["tokens"]["completion"],
                "cost_usd": metrics["cost_usd"],
                "cost_status": metrics["cost_status"],
                "verified_cost_usd": metrics["verified_cost_usd"],
                "estimated_cost_usd": metrics["estimated_cost_usd"],
                "unknown_cost_runs": metrics["unknown_cost_runs"],
                "cost_per_correct_result_usd": metrics["cost_per_correct_result_usd"],
                "cost_per_correct_result_status": metrics["cost_per_correct_result_status"],
            }
        )

    for provider in report["providers"]:
        add("provider", "all", "", "", provider, "")
    for split in ("calibration", "holdout"):
        for provider in report["by_split"].get(split, []):
            add("split", split, "", "", provider, "")
    for family in report["per_family"]:
        for provider in family["providers"]:
            add("family", "", family["family"], "", provider, "")
    for category in report["per_category"]:
        for provider in category["providers"]:
            add("category", "", "", category["category"], provider, "")
    for case in report["per_case"]:
        for provider in case["providers"].values():
            add("case", case["split"], case["family"], case["category"], provider, case["case_id"])
    return rows


def _write_csv(path: Path, report: Mapping[str, Any]) -> None:
    rows = _csv_rows(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0]) if rows else ["scope", "provider", "case_id"]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(buffer.getvalue(), encoding="utf-8")


CSS = """
:root { color-scheme: light; }
body { margin: 0; padding: 32px 20px 64px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; color: #172033; background: #f5f7fb; line-height: 1.45; }
main { max-width: 1240px; margin: 0 auto; }
h1 { font-size: 30px; margin: 0 0 6px; }
h2 { font-size: 19px; margin: 0 0 8px; }
.muted { color: #64748b; font-weight: 400; font-size: 13px; }
.note { background: #fff7ed; border: 1px solid #fed7aa; border-left: 5px solid #ea580c; padding: 14px 18px; border-radius: 8px; margin: 18px 0; }
.note strong { color: #9a3412; }
.card { background: #fff; border: 1px solid #dfe5ef; border-radius: 10px; padding: 16px 18px; margin: 14px 0; }
table { width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #dfe5ef; border-radius: 8px; overflow: hidden; margin: 12px 0 24px; font-size: 13px; }
th, td { padding: 8px 10px; border-bottom: 1px solid #edf1f7; text-align: left; vertical-align: top; }
th { background: #eef3fa; font-size: 12px; text-transform: uppercase; letter-spacing: .03em; color: #475569; }
tr:last-child td { border-bottom: none; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; }
.kv { background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 12px; }
.kv b { display: block; font-size: 11px; text-transform: uppercase; color: #64748b; letter-spacing: .04em; }
footer { color: #64748b; font-size: 12px; margin-top: 28px; }
"""


def _write_html(path: Path, report: Mapping[str, Any]) -> None:
    dataset = report["dataset"]
    sample = report["sample_size"]
    cost = report["cost"]
    providers = report["providers"]

    provider_rows = [
        [
            f"<strong>{html.escape(provider['provider'])}</strong><br><span class='muted'>{html.escape(provider['model'] or '')}</span>",
            str(provider["metrics"]["runs"]),
            *_metric_cells(provider["metrics"]),
        ]
        for provider in providers
    ]
    split_rows = []
    for split in ("calibration", "holdout"):
        for provider in report["by_split"].get(split, []):
            metrics = provider["metrics"]
            split_rows.append(
                [
                    html.escape(split),
                    html.escape(provider["provider"]),
                    str(metrics["runs"]),
                    _fmt(metrics["precision"]),
                    _fmt(metrics["recall"]),
                    _fmt(metrics["f1"]),
                    _fmt(metrics["requirement_coverage"]),
                    _fmt(metrics["type_context_correctness"]),
                    _pct(metrics["semantic_pass_rate"]),
                    _pct(metrics["valid_template_rate"]),
                    _cost_cell(metrics),
                ]
            )
    family_rows = []
    for family in report["per_family"]:
        for provider in family["providers"]:
            metrics = provider["metrics"]
            family_rows.append(
                [
                    html.escape(family["family"]),
                    str(family["cases"]),
                    html.escape(provider["provider"]),
                    _fmt(metrics["precision"]),
                    _fmt(metrics["recall"]),
                    _fmt(metrics["f1"]),
                    _fmt(metrics["requirement_coverage"]),
                    _fmt(metrics["type_context_correctness"]),
                    _pct(metrics["semantic_pass_rate"]),
                    _pct(metrics["valid_template_rate"]),
                ]
            )
    case_rows = []
    for case in report["per_case"]:
        for provider, provider_report in case["providers"].items():
            metrics = provider_report["metrics"]
            case_rows.append(
                [
                    f"<strong>{html.escape(case['case_id'])}</strong><br><span class='muted'>{html.escape(case['family'])} · {html.escape(case['split'])} · {html.escape(case['difficulty'])}</span>",
                    html.escape(provider),
                    _fmt(metrics["precision"]),
                    _fmt(metrics["recall"]),
                    _fmt(metrics["requirement_coverage"]),
                    _fmt(metrics["type_context_correctness"]),
                    _pct(metrics["semantic_pass_rate"]),
                    _pct(metrics["valid_template_rate"]),
                    _cost_cell(metrics),
                ]
            )
    taxonomy_rows = [
        [html.escape(code), str(count), str(report["primary_error_counts"].get(code, 0))]
        for code, count in sorted(
            report["error_taxonomy"].items(), key=lambda item: ERROR_TAXONOMY.index(item[0])
        )
    ]
    provider_cards = []
    for provider in providers:
        metrics = provider["metrics"]
        proxy = provider.get("proxies") or {}
        proxy_note = ""
        if proxy:
            proxy_note = (
                "<p class='muted'>Cost proxy: "
                + ", ".join(
                    f"{html.escape(model)} → {html.escape(str(details['proxy_for']))}"
                    for model, details in proxy.items()
                )
                + "</p>"
            )
        status_note = (
            f"<p class='muted'>Not run: {html.escape(provider.get('not_run_reason') or '')}</p>"
            if provider.get("status") == "not_run"
            else ""
        )
        provider_cards.append(
            f"""
            <section class="card">
              <h2>{html.escape(provider["provider"])} <span class="muted">{html.escape(provider["model"] or "")}</span></h2>
              <p class="muted">Runs: {metrics["runs"]} · planned: {metrics["planned_runs"]} · valid templates: {metrics["valid_runs"]} · correct: {metrics["correct_runs"]} · cost: {_cost_cell(metrics)}</p>
              <p>Precision {_fmt(metrics["precision"])} · Recall {_fmt(metrics["recall"])} · F1 {_fmt(metrics["f1"])} · Coverage {_fmt(metrics["requirement_coverage"])} · Type/context {_fmt(metrics["type_context_correctness"])} · Semantic pass {_pct(metrics["semantic_pass_rate"])}</p>
              <p>Valid template rate <strong>{_pct(metrics["valid_template_rate"])}</strong> is reported separately from the semantic metrics.</p>
              {proxy_note}{status_note}
            </section>
            """
        )

    html_text = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gold semantic benchmark</title>
<style>{CSS}</style>
</head>
<body>
<main>
  <h1>Gold semantic benchmark</h1>
  <p class="muted">Dataset version {html.escape(dataset["version"])} · {dataset["case_count"]} cases · split {html.escape(report["split"])} · generated {html.escape(report["generated_at"])}.</p>
  <div class="note"><strong>Observations, not significance.</strong> {html.escape(report["observations_not_significance"])}</div>

  <div class="grid">
    <div class="kv"><b>Dataset cases</b>{dataset["case_count"]}<br><span class="muted">calibration {dataset["splits"].get("calibration", 0)} · holdout {dataset["splits"].get("holdout", 0)}</span></div>
    <div class="kv"><b>Runs completed / planned</b>{sample["completed_runs"]} / {sample["planned_runs"]}</div>
    <div class="kv"><b>Repeats</b>{html.escape(json.dumps(sample["repeats_per_provider"]))}</div>
    <div class="kv"><b>Dataset SHA-256</b><span class="muted">{dataset["sha256"][:24]}…</span></div>
    <div class="kv"><b>Verified + estimated spend</b>{_money(cost["total_usd"], cost["status"])}</div>
    <div class="kv"><b>Budget</b>{_money(report["budget"]["max_spend_usd"])} cap · warning at {_money(report["budget"]["warn_spend_usd"])}</div>
  </div>

  <h2>Per-provider observations</h2>
  {_table(["Provider", "Runs", "Precision", "Recall", "F1", "Coverage", "Type/context", "Blocks", "Semantic pass", "Valid template", "p50 ms", "Cost"], provider_rows)}

  <h2>Calibration vs holdout</h2>
  {_table(["Split", "Provider", "Runs", "Precision", "Recall", "F1", "Coverage", "Type/context", "Semantic pass", "Valid template", "Cost"], split_rows)}

  <h2>Error taxonomy (runs)</h2>
  {_table(["Code", "Runs with code", "Primary code runs"], taxonomy_rows)}
  <p class="muted">A run can carry several semantic codes. Primary counts assign one dominant code per run with at least one code; the primary column is not the failed-run count.</p>

  <h2>Cost and status</h2>
  <div class="card">
    <p>Verified cost: {_money(cost["verified_usd"])} · Estimated cost: {_money(cost["estimated_usd"])} · Unknown runs: {cost["unknown_runs"]}</p>
    <p>Gemini 3.6-flash is unpriced in the product price table. Its cost is <strong>estimated</strong> with the documented proxy, never reported as $0.00. Unknown cost is rendered as N/A.</p>
  </div>

  <h2>By task family</h2>
  {_table(["Family", "Cases", "Provider", "Precision", "Recall", "F1", "Coverage", "Type/context", "Semantic pass", "Valid template"], family_rows)}

  <h2>Cases</h2>
  {_table(["Case", "Provider", "Precision", "Recall", "Coverage", "Type/context", "Semantic pass", "Valid template", "Cost"], case_rows)}

  <h2>Per provider</h2>
  {"".join(provider_cards)}

  <h2>Settings</h2>
  <div class="card">
    <p>Full prompt: {html.escape(report["settings"]["prompt_version"])} · Gemini: compact {html.escape(report["settings"]["gemini_compact_version"])} · Repair attempts: Gemini {report["settings"]["repair_attempts"]["gemini"]}, other {report["settings"]["repair_attempts"]["other"]} · Max output tokens: {report["settings"]["max_output_tokens"]} · Temperature: {report["settings"]["temperature"]}</p>
    <p>Pricing: {html.escape(report["settings"]["pricing"]["pricing_version"])} ({html.escape(report["settings"]["pricing"]["as_of"])}) · Source: {html.escape(report["settings"]["pricing"]["pricing_source"])}</p>
    <p>Runs file: {html.escape(report["runs_file"])} · SHA-256 {html.escape(report["runs_sha256"][:24])}…</p>
  </div>

  <h2>Limits</h2>
  <div class="card">
    <p>Ground truth is authored by the implementer for synthetic fixtures and validated by a deterministic rule pass; there was no independent human double review. The labels encode this project's judgement, not a customer's. Repeats show run-to-run variation only; they are not a population sample. Verified Docentric AX compatibility remains <strong>not_tested</strong>.</p>
  </div>
  <footer>Generated by benchmarks/gold_evaluation.py · no credentials or raw model output are stored in this report.</footer>
</main>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_text, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--providers", default="mock:mock-planner-v1")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--split", choices=[*GOLD_SPLITS, "all"], default="all")
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    parser.add_argument(
        "--paid-repeats",
        type=int,
        default=None,
        help=(
            "repeats for priced providers (default: same as --repeats); "
            "Gemini keeps --repeats repeats"
        ),
    )
    parser.add_argument("--limit", type=int, default=None, help="first N selected cases")
    parser.add_argument("--case-ids", default="", help="comma-separated case ids")
    parser.add_argument("--runs-file", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--output-html", type=Path, default=DEFAULT_HTML)
    parser.add_argument(
        "--max-spend",
        type=float,
        default=DEFAULT_MAX_SPEND,
        help="abort before a call whose worst case could cross this USD cap (default 10)",
    )
    parser.add_argument(
        "--warn-spend",
        type=float,
        default=DEFAULT_WARN_SPEND,
        help="print a warning once known+estimated spend crosses this value (default 5)",
    )
    parser.add_argument("--allow-unpriced", action="store_true")
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=MAX_OUTPUT_TOKENS,
        help="provider output cap used for the pre-flight worst-case guard",
    )
    parser.add_argument(
        "--repair-attempts",
        type=int,
        default=DEFAULT_PAID_REPAIR_ATTEMPTS,
        choices=[0, 1, 2],
        help="repair calls for priced providers (Gemini is pinned to 2)",
    )
    args = parser.parse_args(argv)
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    if args.paid_repeats is not None and args.paid_repeats < 1:
        parser.error("--paid-repeats must be at least 1")
    if args.max_spend <= 0 or args.warn_spend < 0:
        parser.error("--max-spend must be positive and --warn-spend non-negative")

    try:
        dataset = load_gold_dataset(args.cases)
    except ValueError as exc:
        print(f"gold dataset error: {exc}", file=sys.stderr)
        return 2
    dataset_errors = validate_gold_dataset(dataset)
    if dataset_errors:
        print("gold dataset is invalid:", file=sys.stderr)
        for error in dataset_errors:
            print(f"  - {error}", file=sys.stderr)
        return 2

    definitions = list(cases_for_split(dataset, args.split))
    if args.case_ids:
        wanted = {item.strip() for item in args.case_ids.split(",") if item.strip()}
        definitions = [case for case in definitions if case["id"] in wanted]
    if args.limit is not None:
        definitions = definitions[: max(0, args.limit)]
    if not definitions:
        print("No cases selected", file=sys.stderr)
        return 2

    parsed_packages: dict[str, Any] = {}
    for case in definitions:
        package = ROOT / str(case["package"])
        parsed_packages[str(package)] = parse_ddsp(package.read_bytes(), package.name)

    targets = _parse_providers(args.providers)
    base_settings = get_settings()
    settings = dataclasses.replace(
        base_settings,
        llm_max_retries=0,
        llm_max_output_tokens=args.max_output_tokens,
    )
    gateway = LLMGateway(settings)
    planner = TemplatePlanner(gateway)
    validator = ValidationEngine(
        max_blocks=settings.limits.max_ir_blocks,
        max_depth=settings.limits.max_ir_depth,
        max_text_length=settings.limits.max_text_length,
    )
    compiler = GenericDocxCompiler()

    provider_state = [
        _configure_provider(
            gateway,
            provider,
            model,
            repeats=args.repeats,
            paid_repeats=args.paid_repeats,
            paid_repair_attempts=args.repair_attempts,
        )
        for provider, model in targets
    ]
    for state in provider_state:
        if not state["configured"]:
            print(
                f"warning: provider '{state['provider']}' is not configured; "
                "it is reported as not_run, not mocked",
                file=sys.stderr,
            )
            continue
        if state["compact_ir"]:
            print(
                f"note: {state['provider']} uses compact {state['compact_version']} "
                f"with max_repair_attempts={state['repair_attempts']}",
                file=sys.stderr,
            )

    runs_per_provider = {
        state["provider"]: len(definitions) * int(state["repeats"])
        for state in provider_state
        if state["configured"]
    }
    repeats_per_provider = {state["provider"]: int(state["repeats"]) for state in provider_state}
    planned_runs = sum(runs_per_provider.values())
    split_counts = Counter(str(case.get("split")) for case in definitions)
    print(
        f"gold evaluation: {len(definitions)} cases × {len(provider_state)} providers "
        f"= {planned_runs} planned runs "
        f"(calibration {split_counts.get('calibration', 0)}, "
        f"holdout {split_counts.get('holdout', 0)}; repeats "
        f"{ {state['provider']: state['repeats'] for state in provider_state} })"
    )

    args.runs_file.parent.mkdir(parents=True, exist_ok=True)
    args.runs_file.write_text("", encoding="utf-8")
    runs: list[dict[str, Any]] = []
    verified_spend = 0.0
    estimated_spend = 0.0
    warned = False
    warned_unpriced: set[str] = set()
    aborted = False
    abort_reason = ""
    started_all = datetime.now(UTC)
    finished_all = started_all
    stop = False

    with args.runs_file.open("a", encoding="utf-8") as handle:
        for repeat in range(1, args.repeats + 1):
            if stop:
                break
            for case in definitions:
                if stop:
                    break
                parsed = parsed_packages[str(ROOT / str(case["package"]))]
                for state in provider_state:
                    if stop:
                        break
                    if not state["configured"]:
                        continue
                    if repeat > int(state["repeats"]):
                        continue
                    provider = str(state["provider"])
                    requested_model = str(state["requested_model"] or state["model"] or "")
                    messages = _messages_for(
                        parsed.schema,
                        str(case["prompt"]),
                        compact=bool(state["compact_ir"]),
                        language=str(case.get("language", "en")),
                    )
                    _price, known = price_for(requested_model)
                    if not known and not args.allow_unpriced:
                        aborted = True
                        abort_reason = (
                            f"refusing to call unpriced model '{requested_model}': the budget "
                            "guard cannot bound the spend (use --allow-unpriced to override)"
                        )
                        stop = True
                        break
                    if not known and requested_model not in warned_unpriced:
                        warned_unpriced.add(requested_model)
                        proxy = _proxy_for(requested_model)
                        print(
                            f"warning: {requested_model} is unpriced; cost uses "
                            + (
                                f"the documented proxy {proxy['proxy_for']}"
                                if proxy
                                else "no proxy"
                            )
                            + " and is reported as estimated/unavailable",
                            file=sys.stderr,
                        )
                    worst_case = _worst_case_cost(
                        messages,
                        requested_model,
                        settings.llm_max_output_tokens,
                        calls=int(state["repair_attempts"]) + 1,
                    )
                    spent_total = round(verified_spend + estimated_spend, 6)
                    if worst_case is not None and spent_total + worst_case > args.max_spend:
                        aborted = True
                        abort_reason = (
                            f"next call plus repairs could cost up to ${worst_case:.4f}; "
                            f"running spend ${spent_total:.4f} would exceed the "
                            f"${args.max_spend:.2f} cap"
                        )
                        stop = True
                        break

                    run = _run_one(
                        planner=planner,
                        validator=validator,
                        compiler=compiler,
                        parsed=parsed,
                        case=case,
                        provider=provider,
                        model=requested_model,
                        repeat=repeat,
                        repair_attempts=int(state["repair_attempts"]),
                        compact_ir=bool(state["compact_ir"]),
                        compact_version=state["compact_version"],
                    )
                    runs.append(run)
                    handle.write(json.dumps(run, sort_keys=True, ensure_ascii=False) + "\n")
                    handle.flush()
                    if run["cost_status"] == "verified" and run["cost_usd"] is not None:
                        verified_spend = round(verified_spend + float(run["cost_usd"]), 6)
                    elif run["cost_status"] == "estimated" and run["cost_usd"] is not None:
                        estimated_spend = round(estimated_spend + float(run["cost_usd"]), 6)
                    spent_total = round(verified_spend + estimated_spend, 6)
                    if not warned and spent_total >= args.warn_spend:
                        warned = True
                        print(
                            f"WARNING: known+estimated spend ${spent_total:.4f} reached "
                            f"the ${args.warn_spend:.2f} warning line",
                            file=sys.stderr,
                        )
                    status = "correct" if run["correct"] else "semantic-miss"
                    if not run["ok"]:
                        status = f"FAILED ({(run['error'] or {}).get('code')})"
                    elif not run["valid_template"]:
                        status = "valid-miss"
                    semantic = run["semantic"] or {}
                    print(
                        f"{run['case_id']:<34} r{repeat} {provider:<10} {status:<22} "
                        f"P={_fmt(semantic.get('precision'))} R={_fmt(semantic.get('recall'))} "
                        f"{run['latency_ms'] / 1000:.1f}s {_money(run['cost_usd'], run['cost_status'])} "
                        f"| known ${verified_spend:.4f} + est ${estimated_spend:.4f} = ${spent_total:.4f}"
                    )
                    if spent_total > args.max_spend:
                        aborted = True
                        abort_reason = (
                            f"running spend ${spent_total:.4f} exceeded the "
                            f"${args.max_spend:.2f} cap"
                        )
                        stop = True
                        break
                    if run["error"] and run["error"]["code"] == "quota":
                        aborted = True
                        abort_reason = "the provider reported a quota error; stopping"
                        stop = True
                        break
        finished_all = datetime.now(UTC)

    runs_sha = hashlib.sha256(args.runs_file.read_bytes()).hexdigest()
    metadata = dataset_metadata(dataset)
    provider_reports = [
        _provider_report(state, [run for run in runs if run["provider"] == state["provider"]])
        for state in provider_state
    ]
    by_split: dict[str, list[dict[str, Any]]] = {}
    for split in GOLD_SPLITS:
        split_ids = {str(case["id"]) for case in definitions if str(case.get("split")) == split}
        split_runs = [run for run in runs if run["case_id"] in split_ids]
        by_split[split] = [
            _provider_report(
                state, [run for run in split_runs if run["provider"] == state["provider"]]
            )
            for state in provider_state
        ]

    family_order = [
        family for family in dataset.document.get("families", []) if isinstance(family, str)
    ]
    if not family_order:
        family_order = sorted({str(case.get("family")) for case in definitions})
    selected_families = {str(case.get("family")) for case in definitions}
    per_family = []
    for family in family_order:
        if family not in selected_families:
            continue
        family_ids = {str(case["id"]) for case in definitions if str(case.get("family")) == family}
        family_runs = [run for run in runs if run["case_id"] in family_ids]
        per_family.append(
            {
                "family": family,
                "cases": len(family_ids),
                "providers": [
                    _provider_report(
                        state, [run for run in family_runs if run["provider"] == state["provider"]]
                    )
                    for state in provider_state
                ],
            }
        )
    category_order = [
        category for category in dataset.document.get("categories", []) if isinstance(category, str)
    ]
    if not category_order:
        category_order = sorted({str(case.get("category")) for case in definitions})
    selected_categories = {str(case.get("category")) for case in definitions}
    per_category = []
    for category in category_order:
        if category not in selected_categories:
            continue
        category_ids = {
            str(case["id"]) for case in definitions if str(case.get("category")) == category
        }
        category_runs = [run for run in runs if run["case_id"] in category_ids]
        per_category.append(
            {
                "category": category,
                "cases": len(category_ids),
                "providers": [
                    _provider_report(
                        state,
                        [run for run in category_runs if run["provider"] == state["provider"]],
                    )
                    for state in provider_state
                ],
            }
        )

    per_case = []
    for case in definitions:
        case_runs = [run for run in runs if run["case_id"] == case["id"]]
        per_case.append(
            {
                "case_id": case["id"],
                "family": case["family"],
                "category": case["category"],
                "difficulty": case["difficulty"],
                "split": case["split"],
                "language": case.get("language", "en"),
                "package": case.get("package"),
                "sample_size": len(case_runs),
                "providers": {
                    state["provider"]: _provider_report(
                        state,
                        [run for run in case_runs if run["provider"] == state["provider"]],
                    )
                    for state in provider_state
                },
            }
        )
    total_aggregate = _aggregate(runs)
    family_semantic_pass: dict[str, dict[str, Any]] = {}
    for family_entry in per_family:
        family_name = str(family_entry["family"])
        family_semantic_pass[family_name] = {
            "cases": family_entry["cases"],
            "providers": {
                str(provider["provider"]): {
                    "semantic_pass_rate": provider["metrics"]["semantic_pass_rate"],
                    "pass_at_k": provider["metrics"]["pass_at_k"],
                    "runs": provider["metrics"]["runs"],
                }
                for provider in family_entry["providers"]
            },
        }
    image_cases = [case for case in definitions if str(case.get("family")) == "images"]
    image_case_reports: list[dict[str, Any]] = []
    for case in image_cases:
        expected_image_paths = [
            path
            for binding in case.get("required_bindings") or []
            if isinstance(binding, Mapping) and binding.get("expected_type") == "image"
            for path in (binding.get("expected_paths") or [])
        ]
        case_runs = [run for run in runs if run.get("case_id") == case["id"]]
        image_case_reports.append(
            {
                "case_id": case["id"],
                "label_status": case.get("label_status", "verified"),
                "image_subtype": case.get("image_subtype", "unspecified"),
                "expected_image_paths": expected_image_paths,
                "image_binding_present_runs": sum(
                    1
                    for run in case_runs
                    if any(
                        path in (run.get("produced_paths") or []) for path in expected_image_paths
                    )
                ),
                "runs": len(case_runs),
                "semantic_pass_by_provider": {
                    state["provider"]: _provider_report(
                        state,
                        [run for run in case_runs if run["provider"] == state["provider"]],
                    )["metrics"]["semantic_pass_rate"]
                    for state in provider_state
                },
                "forbidden_hits": sorted(
                    {path for run in case_runs for path in run.get("forbidden_hits") or []}
                ),
            }
        )
    image_family = {
        "decision": (
            "labels_verified_no_gap"
            if all(case.get("label_status", "verified") == "verified" for case in image_cases)
            else "label_gap_present"
        ),
        "label_status": {case["id"]: case.get("label_status", "verified") for case in image_cases},
        "cases": image_case_reports,
        "providers": {
            state["provider"]: _provider_report(
                state,
                [
                    run
                    for run in runs
                    if run.get("family") == "images" and run["provider"] == state["provider"]
                ],
            )["metrics"]
            for state in provider_state
        },
        "note": (
            "Image-family adjudication: each committed image case asks for the company logo and "
            "the schema exposes that exact image path; the v0.10 0% semantic pass was caused by "
            "forbidden-scope contamination, not an inexpressible label. No case is a gap. The "
            "image scorecard is reported separately so the aggregate cannot hide it."
        ),
    }
    counters = {
        "planned_runs": planned_runs,
        "executed_runs": len(runs),
        "skipped_runs": max(0, planned_runs - len(runs)),
        "succeeded_runs": total_aggregate["succeeded_runs"],
        "failed_runs": total_aggregate["failed_runs"],
        "valid_template_runs": total_aggregate["valid_runs"],
        "semantic_pass_runs": total_aggregate["semantic_passes"],
        "semantic_excluded_runs": total_aggregate["semantic_excluded_runs"],
        "abstained_runs": total_aggregate["abstained_runs"],
        "abstention_rate": total_aggregate["abstention_rate"],
        "review_runs": total_aggregate["review_runs"],
        "review_rate": total_aggregate["review_rate"],
        "pass_at_k": total_aggregate["pass_at_k"],
        "invariants": {
            "planned_equals_executed_plus_skipped": planned_runs
            == len(runs) + max(0, planned_runs - len(runs)),
            "executed_equals_succeeded_plus_failed": len(runs)
            == total_aggregate["succeeded_runs"] + total_aggregate["failed_runs"],
        },
    }
    overall_cost_status = (
        "estimated"
        if any(run["cost_status"] == "estimated" for run in runs)
        else "verified"
        if any(run["cost_status"] == "verified" for run in runs)
        else "unavailable"
    )
    report = {
        "schema": "gold-report/v1",
        "generated_at": _iso(datetime.now(UTC)),
        "generated_by": "benchmarks/gold_evaluation.py",
        "observations_not_significance": OBSERVATIONS_NOTE,
        "dataset": metadata,
        "split": args.split,
        "sample_size": {
            "planned_runs": planned_runs,
            "completed_runs": len(runs),
            "cases": len(definitions),
            "providers": len(provider_state),
            "repeats": args.repeats,
            "paid_repeats": args.paid_repeats,
            "repeats_per_provider": repeats_per_provider,
            "planned_per_provider": {
                state["provider"]: len(definitions) * int(state["repeats"])
                for state in provider_state
                if state["configured"]
            },
            "completed_per_provider": {
                state["provider"]: sum(1 for run in runs if run["provider"] == state["provider"])
                for state in provider_state
            },
            "splits": dict(sorted(Counter(str(case.get("split")) for case in definitions).items())),
            "skipped_runs": max(0, planned_runs - len(runs)),
            "failed_runs": total_aggregate["failed_runs"],
            "succeeded_runs": total_aggregate["succeeded_runs"],
            "gap_cases": list(metadata.get("gap_cases") or []),
            "families": dict(
                sorted(Counter(str(case.get("family")) for case in definitions).items())
            ),
            "categories": dict(
                sorted(Counter(str(case.get("category")) for case in definitions).items())
            ),
        },
        "settings": {
            "prompt_version": PROMPT_VERSION,
            "gemini_compact_version": "v2",
            "compact_mode": "gemini-only",
            "candidate_filter": True,
            "candidate_filter_version": "v0.11.1",
            "candidate_limits": {"max_candidates": 24, "max_per_requirement": 4},
            "repair_attempts": {
                "gemini": GEMINI_REPAIR_ATTEMPTS,
                "other": args.repair_attempts,
            },
            "max_output_tokens": settings.llm_max_output_tokens,
            "temperature": 0.0,
            "timeout_seconds": settings.llm_timeout_seconds,
            "transport_retries": settings.llm_max_retries,
            "repeats": args.repeats,
            "paid_repeats": args.paid_repeats,
            "pricing": price_table_metadata(),
            "proxy_pricing": PROXY_PRICES,
            "models": [
                {
                    "provider": state["provider"],
                    "requested_model": state["requested_model"],
                    "compact_ir": state["compact_ir"],
                    "compact_version": state["compact_version"],
                    "repair_attempts": state["repair_attempts"],
                    "repeats": state["repeats"],
                    "configured": state["configured"],
                }
                for state in provider_state
            ],
        },
        "providers": provider_reports,
        "counters": counters,
        "family_semantic_pass": family_semantic_pass,
        "image_family": image_family,
        "governance": {
            "at07_status": metadata.get("at07_status", "partial"),
            "second_human_annotator": False,
            "deterministic_adjudicator": (metadata.get("labels_provenance") or {}).get(
                "adjudicator"
            ),
            "adjudication_report": (metadata.get("labels_provenance") or {}).get(
                "adjudication_report"
            ),
            "note": (
                "AT-07 remains partial: the deterministic adjudicator is a proxy, not human "
                "double review."
            ),
        },
        "by_split": by_split,
        "per_family": per_family,
        "per_category": per_category,
        "per_case": per_case,
        "leaders": _leaders(provider_reports),
        "error_taxonomy": total_aggregate["error_counts"],
        "primary_error_counts": total_aggregate["primary_error_counts"],
        "aggregate": total_aggregate,
        "cost": {
            "verified_usd": round(verified_spend, 6),
            "estimated_usd": round(estimated_spend, 6),
            "total_usd": round(verified_spend + estimated_spend, 6),
            "status": overall_cost_status,
            "unknown_runs": sum(1 for run in runs if run["cost_status"] == "unavailable"),
            "cost_per_correct_result_usd": total_aggregate["cost_per_correct_result_usd"],
            "cost_per_correct_result_status": total_aggregate["cost_per_correct_result_status"],
        },
        "budget": {
            "max_spend_usd": args.max_spend,
            "warn_spend_usd": args.warn_spend,
            "allow_unpriced": args.allow_unpriced,
            "known_spend_usd": round(verified_spend, 6),
            "estimated_spend_usd": round(estimated_spend, 6),
            "total_spend_usd": round(verified_spend + estimated_spend, 6),
            "warned": warned,
            "aborted": aborted,
            "abort_reason": abort_reason,
        },
        "started_at": _iso(started_all),
        "finished_at": _iso(finished_all),
        "runs_file": _display_path(args.runs_file),
        "runs_sha256": runs_sha,
        "notes": [
            OBSERVATIONS_NOTE,
            "Labels were authored by the implementer and adjudicated by benchmarks/adjudicate_labels.py, a deterministic independent proxy. No second human annotator exists, so AT-07 remains partial.",
            "valid_template_rate is the deterministic validation + compilation rate and is never folded into precision, recall or F1.",
            "Gemini 3.6-flash is unpriced; its cost is estimated with the named proxy and is never reported as $0.00.",
            "Ground truth is authored for synthetic fixtures and reflects this project's judgement.",
            "Image-family labels are reported separately; no image case is excluded as a label gap.",
            "Verified Docentric AX compatibility is not tested by this harness.",
            "Per-run records live in the git-ignored gold_runs.jsonl; no prompt text or raw provider output is committed.",
        ],
    }
    _write_json(args.output_json, report)
    _write_csv(args.output_csv, report)
    _write_html(args.output_html, report)

    print()
    for aggregate in provider_reports:
        metrics = aggregate["metrics"]
        print(
            f"{aggregate['provider']}: runs {metrics['runs']} "
            f"valid {metrics['valid_runs']} correct {metrics['correct_runs']} "
            f"precision {_fmt(metrics['precision'])} recall {_fmt(metrics['recall'])} "
            f"F1 {_fmt(metrics['f1'])} coverage {_fmt(metrics['requirement_coverage'])} "
            f"semantic {_pct(metrics['semantic_pass_rate'])} "
            f"p50 {metrics['latency_p50_ms']} ms "
            f"cost {_cost_cell(metrics)}"
        )
    print(
        f"spend: verified ${verified_spend:.4f}, estimated ${estimated_spend:.4f}, "
        f"total ${verified_spend + estimated_spend:.4f} "
        f"(unknown-cost runs: {sum(1 for run in runs if run['cost_status'] == 'unavailable')})"
    )
    print(
        f"wrote {_display_path(args.output_json)}, {_display_path(args.output_csv)}, "
        f"{_display_path(args.output_html)}"
    )
    if aborted:
        print(f"ABORTED: {abort_reason}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
