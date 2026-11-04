#!/usr/bin/env python3
"""Live semantic-quality evaluation for the template planner (P0).

This runner separates *technically valid* from *semantically correct*:

* ``valid_template_rate`` is the deterministic validation + compilation rate;
* ``precision``, ``recall``, ``requirement_coverage``, ``type_context_correctness``
  and ``block_coverage`` are computed against ``benchmarks/semantic_cases.json``
  by :mod:`benchmarks.semantic_scoring` and are reported separately.

Each case is planned ``--repeats`` times per provider with the same prompt and
schema. Every run is appended to ``benchmarks/semantic_runs.jsonl`` (no secrets,
no raw provider output) and the aggregate is written to JSON, CSV and a
self-contained HTML report.

Cost is three-valued, as in the existing live harness:

* ``verified`` - the provider reported token usage and the model has a published
  price in the versioned price table;
* ``estimated`` - the model is unpriced (Gemini 3.6-flash) and a documented
  proxy rate is used; the proxy is named in the report;
* ``unavailable`` - neither exists. Unknown is never rendered as ``$0.00``.

The report deliberately does not name a single winner. It shows the leader for
each metric, ties included, and says that the counts are observations from a
small sample, not statistical significance.

Usage::

    .venv/bin/python benchmarks/semantic_evaluation.py \
        --providers openai:gpt-6-sol,anthropic:claude-sonnet-5-5,gemini:gemini-3.6-flash \
        --repeats 3 --allow-unpriced --max-spend 6 --warn-spend 5

Gemini always uses the compact v2 wire format and ``max_repair_attempts=2``;
other providers use the full IR contract and the same repair budget.
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
from docentric_copilot.schema_resolver.paths import (  # noqa: E402
    PathResolutionError,
    Scope,
    resolve_collection,
    resolve_value,
)
from docentric_copilot.template_ir import (  # noqa: E402
    Conditional,
    Document,
    FieldBinding,
    Heading,
    ImageBinding,
    Paragraph,
    Repeat,
    Table,
    ir_digest,
    iter_expressions,
)
from docentric_copilot.template_validator import ValidationEngine  # noqa: E402

from benchmarks.semantic_scoring import (  # noqa: E402
    ERROR_TAXONOMY,
    ProducedBinding,
    ProducedBlock,
    SemanticScore,
    classify_exception,
    score_run,
    taxonomy_for_validation_codes,
    validate_cases,
)

DEFAULT_CASES = ROOT / "benchmarks" / "semantic_cases.json"
DEFAULT_RUNS = ROOT / "benchmarks" / "semantic_runs.jsonl"
DEFAULT_JSON = ROOT / "benchmarks" / "semantic_report.json"
DEFAULT_CSV = ROOT / "benchmarks" / "semantic_report.csv"
DEFAULT_HTML = ROOT / "benchmarks" / "semantic_report.html"
DEFAULT_MAX_SPEND = 6.0
DEFAULT_WARN_SPEND = 5.0
DEFAULT_REPEATS = 3
DEFAULT_REPAIR_ATTEMPTS = 2
MAX_OUTPUT_TOKENS = 16_000
_MAX_TOKENS_PER_CHAR = 0.35
_SECRET = re.compile(r"(?i)(api[-_]?key|authorization|bearer)\s*[=:]\s*\S+")

#: Conservatively proxied prices for models the product price table deliberately
#: leaves unpriced. These are *not* list prices and are recorded as estimated.
PROXY_PRICES: dict[str, dict[str, Any]] = {
    "gemini-3.6-flash": {
        "proxy_for": "gemini-3.8-flash",
        "input_per_mtok": 0.75,
        "output_per_mtok": 3.75,
        "as_of": "2026-11-03",
        "source": "docs/PRICING.md (gemini-3.8-flash introductory rate)",
    }
}

OBSERVATIONS_NOTE = (
    "These are observations from a fixed, synthetic case set, not statistical "
    "significance. Repeats are not independent samples of a population; they "
    "show run-to-run variation for the same prompt. No single winner is declared: "
    "each metric has its own leader, and ties are shown."
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


def _ordered_codes(codes: Iterable[str]) -> list[str]:
    unique = {code for code in codes if code}
    return sorted(unique, key=lambda code: ERROR_TAXONOMY.index(code))


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


def _messages_for(schema: Any, prompt: str, *, compact: bool, language: str) -> list[Any]:
    if compact:
        return build_compact_messages_v2(schema, prompt, language=language)
    return build_messages(schema, prompt, language=language)


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


def _dataset_metadata(definitions: Sequence[Mapping[str, Any]], path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    canonical = json.dumps(definitions, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    canonical_sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    families: Counter[str] = Counter()
    languages: Counter[str] = Counter()
    for case in definitions:
        for label in case.get("labels", []):
            families[str(label)] += 1
        languages[str(case.get("language", "en"))] += 1
    return {
        "file": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        "canonical_sha256": canonical_sha,
        "hash": canonical_sha[:16],
        "case_count": len(definitions),
        "families": dict(sorted(families.items())),
        "languages": dict(sorted(languages.items())),
    }


# --------------------------------------------------------------------------- #
# IR observation
# --------------------------------------------------------------------------- #
def _contexts(base: str, in_repeat: bool, in_conditional: bool) -> tuple[str, ...]:
    values = [base]
    if in_repeat:
        values.append("repeat")
    if in_conditional:
        values.append("conditional")
    return tuple(values)


def _resolve_field(schema: Any, path: str, scope: Scope) -> Any | None:
    try:
        return resolve_value(schema, path, scope)
    except PathResolutionError:
        return None


def _resolve_collection(schema: Any, path: str, scope: Scope) -> Any | None:
    try:
        return resolve_collection(schema, path, scope)
    except PathResolutionError:
        return None


def collect_produced_bindings(
    document: Document, schema: Any, mapping: Any | None = None
) -> list[ProducedBinding]:
    """Collect every field/image/condition binding with its absolute path/context.

    Conditions count as semantic bindings because a conditional requirement is
    satisfied by an expression over a field, not by visible text. They are
    marked ``role="condition"`` so unused condition fields are not charged as
    false positives.
    """
    collected: list[ProducedBinding] = []

    def add(
        path: str,
        *,
        data_type: str | None,
        contexts: tuple[str, ...],
        role: str,
        concept: str | None = None,
    ) -> None:
        collected.append(
            ProducedBinding(
                path=path,
                concept=concept,
                data_type=data_type,
                contexts=contexts,
                role=role,
            )
        )

    def visit(
        blocks: Sequence[Any],
        scope: Scope,
        base: str,
        *,
        in_repeat: bool,
        in_conditional: bool,
    ) -> None:
        for block in blocks:
            if isinstance(block, Paragraph | Heading):
                for run in block.runs:
                    if not isinstance(run, FieldBinding):
                        continue
                    resolved = _resolve_field(schema, run.path, scope)
                    if resolved is None:
                        continue
                    add(
                        resolved.absolute,
                        data_type=resolved.node.data_type,
                        contexts=_contexts(base, in_repeat, in_conditional),
                        role="field",
                    )
            elif isinstance(block, ImageBinding):
                resolved = _resolve_field(schema, block.path, scope)
                if resolved is not None:
                    add(
                        resolved.absolute,
                        data_type="image",
                        contexts=_contexts(base, in_repeat, in_conditional),
                        role="image",
                    )
            elif isinstance(block, Repeat):
                collection = _resolve_collection(schema, block.path, scope)
                if collection is None:
                    continue
                visit(
                    block.blocks,
                    scope.push(block.alias, collection.absolute),
                    base,
                    in_repeat=True,
                    in_conditional=in_conditional,
                )
            elif isinstance(block, Conditional):
                for expression in iter_expressions(block.condition):
                    if expression.field is None:
                        continue
                    resolved = _resolve_field(schema, expression.field, scope)
                    if resolved is None:
                        continue
                    add(
                        resolved.absolute,
                        data_type=resolved.node.data_type,
                        contexts=_contexts(base, in_repeat, True),
                        role="condition",
                    )
                visit(
                    block.then_blocks,
                    scope,
                    base,
                    in_repeat=in_repeat,
                    in_conditional=True,
                )
                visit(
                    list(block.else_blocks or []),
                    scope,
                    base,
                    in_repeat=in_repeat,
                    in_conditional=True,
                )
            elif isinstance(block, Table):
                row_scope = scope
                if block.repeat is not None:
                    collection = _resolve_collection(schema, block.repeat.path, scope)
                    if collection is not None:
                        row_scope = scope.push(block.repeat.alias, collection.absolute)
                for row in block.rows:
                    for cell in row.cells:
                        visit(
                            cell.blocks,
                            scope,
                            base,
                            in_repeat=in_repeat,
                            in_conditional=in_conditional,
                        )
                for cell in block.row_template or []:
                    visit(
                        cell.blocks,
                        row_scope,
                        base,
                        in_repeat=in_repeat or block.repeat is not None,
                        in_conditional=in_conditional,
                    )

    for section in document.sections:
        visit(section.body, Scope(), "body", in_repeat=False, in_conditional=False)
        visit(list(section.header or []), Scope(), "header", in_repeat=False, in_conditional=False)
        visit(list(section.footer or []), Scope(), "footer", in_repeat=False, in_conditional=False)

    # Planner mappings add concept evidence and can also expose a proposed path
    # that the deterministic sanitiser removed. Keep both: the former enriches
    # matching, the latter is charged as a mapping false positive.
    concepts: dict[str, str] = {}
    if mapping is not None:
        for item in getattr(mapping, "mappings", []):
            path = getattr(item, "selected_field_path", None)
            concept = getattr(item, "concept", None)
            if path and concept:
                concepts.setdefault(path, concept)
            if not path:
                continue
            if not any(binding.path == path for binding in collected):
                node = schema.node(path)
                collected.append(
                    ProducedBinding(
                        path=path,
                        concept=concept,
                        data_type=node.data_type
                        if node is not None
                        else getattr(item, "data_type", None),
                        contexts=(),
                        role="mapping",
                        status=getattr(getattr(item, "status", None), "value", None),
                    )
                )
    return [
        ProducedBinding(
            path=binding.path,
            concept=binding.concept or concepts.get(binding.path),
            data_type=binding.data_type,
            contexts=binding.contexts,
            role=binding.role,
            status=binding.status,
        )
        for binding in collected
    ]


def collect_produced_blocks(document: Document, schema: Any) -> list[ProducedBlock]:
    """Collect repeats, tables, conditionals and images with absolute paths."""
    collected: list[ProducedBlock] = []
    seen: set[tuple[str, str | None, tuple[str, ...]]] = set()

    def add(block: ProducedBlock) -> None:
        key = (block.kind, block.path, block.condition_paths)
        if key not in seen:
            seen.add(key)
            collected.append(block)

    def visit(blocks: Sequence[Any], scope: Scope) -> None:
        for block in blocks:
            if isinstance(block, Repeat):
                collection = _resolve_collection(schema, block.path, scope)
                if collection is not None:
                    add(ProducedBlock(kind="repeat", path=collection.absolute))
                    visit(block.blocks, scope.push(block.alias, collection.absolute))
            elif isinstance(block, Conditional):
                paths: list[str] = []
                for expression in iter_expressions(block.condition):
                    if expression.field is None:
                        continue
                    resolved = _resolve_field(schema, expression.field, scope)
                    if resolved is not None:
                        paths.append(resolved.absolute)
                add(ProducedBlock(kind="conditional", condition_paths=tuple(paths)))
                visit(block.then_blocks, scope)
                visit(list(block.else_blocks or []), scope)
            elif isinstance(block, Table):
                if block.repeat is not None:
                    collection = _resolve_collection(schema, block.repeat.path, scope)
                    if collection is not None:
                        add(ProducedBlock(kind="table", path=collection.absolute))
                        add(ProducedBlock(kind="repeat", path=collection.absolute))
                        row_scope = scope.push(block.repeat.alias, collection.absolute)
                        for cell in block.row_template or []:
                            visit(cell.blocks, row_scope)
                for row in block.rows:
                    for cell in row.cells:
                        visit(cell.blocks, scope)
            elif isinstance(block, ImageBinding):
                resolved = _resolve_field(schema, block.path, scope)
                if resolved is not None:
                    add(ProducedBlock(kind="image", path=resolved.absolute))

    for section in document.sections:
        visit(section.body, Scope())
        visit(list(section.header or []), Scope())
        visit(list(section.footer or []), Scope())
    return collected


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
    provider_configured: bool,
    repeat: int,
    repair_attempts: int,
    compact_ir: bool,
    compact_version: str | None,
) -> dict[str, Any]:
    case_id = str(case["id"])
    prompt = str(case["prompt"])
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    run_id = f"sem_{uuid.uuid4().hex[:16]}"
    record: dict[str, Any] = {
        "schema": "semantic-run/v1",
        "run_id": run_id,
        "repeat": repeat,
        "started_at": _iso(started_at),
        "case_id": case_id,
        "labels": list(case.get("labels", [])),
        "package": case.get("package"),
        "provider": provider,
        "requested_model": model,
        "actual_provider": None,
        "actual_model": None,
        "configured": provider_configured,
        "compact_ir": compact_ir,
        "compact_version": compact_version,
        "repair_attempts": repair_attempts,
        "prompt_version": COMPACT_V2_GENERATOR if compact_ir else PROMPT_VERSION,
        "prompt_sha256": _digest(prompt),
        "prompt_chars": len(prompt),
        "ok": False,
        "valid_template": False,
        "semantic_pass": False,
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
    }

    if not provider_configured:
        record["error"] = {
            "code": "provider_api",
            "message": f"Provider '{provider}' has no API key configured",
        }
        record["error_codes"] = ["provider_api"]
        record["primary_error"] = "provider_api"
        record["finished_at"] = _iso(datetime.now(UTC))
        return record

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
    score: SemanticScore = score_run(case, produced, produced_blocks=blocks)

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
        outcome.requirement_id
        for outcome in score.outcomes
        if outcome.required and outcome.satisfiable and not outcome.satisfied
    ]
    wrong_paths = [
        outcome.requirement_id for outcome in score.outcomes if outcome.matched_via == "wrong_path"
    ]
    record.update(
        {
            "ok": True,
            "valid_template": valid_template,
            "semantic_pass": score.semantic_pass,
            "semantic": score.as_dict(),
            "validation": report.statuses(),
            "validation_passed": report.can_compile,
            "validation_codes": validation_codes,
            "compiled": compiled,
            "compile_error": compile_error,
            "error": (
                None
                if valid_template and not ordered_codes
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
            "ir_digest": ir_digest(outcome.document),
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
def _ratio(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _aggregate(runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    planned = [run for run in runs if run.get("ok")]
    semantic = [run["semantic"] for run in planned if run.get("semantic")]
    valid = [run for run in planned if run.get("valid_template")]

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
    cost_per_valid = round(total_cost / len(valid), 6) if valid and complete_cost else None
    cost_per_valid_status = (
        "unavailable"
        if cost_per_valid is None
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
        "precision": _ratio(precision_tp, precision_den),
        "precision_numerator": precision_tp,
        "precision_denominator": precision_den,
        "recall": _ratio(matched_required, required_den),
        "recall_numerator": matched_required,
        "recall_denominator": required_den,
        "requirement_coverage": _ratio(matched, coverage_den),
        "coverage_numerator": matched,
        "coverage_denominator": coverage_den,
        "type_context_correctness": _ratio(type_correct, type_checks),
        "type_context_numerator": type_correct,
        "type_context_denominator": type_checks,
        "block_coverage": _ratio(block_satisfied, block_total),
        "block_numerator": block_satisfied,
        "block_denominator": block_total,
        "semantic_pass_rate": _ratio(semantic_passes, len(runs)),
        "semantic_passes": semantic_passes,
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
        "cost_per_valid_template_usd": cost_per_valid,
        "cost_per_valid_template_status": cost_per_valid_status,
        "error_counts": dict(sorted(error_counts.items())),
        "primary_error_counts": dict(sorted(primary_counts.items())),
    }


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
    result = ordered[lower] * (1 - weight) + ordered[upper] * weight
    return round(result, 3)


def _provider_report(
    provider: Mapping[str, Any], runs: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    metrics = _aggregate(runs)
    models = sorted(
        {str(run["actual_model"] or run["requested_model"]) for run in runs if run.get("ok")}
    )
    return {
        "provider": provider["provider"],
        "requested_model": provider["model"],
        "model": provider["requested_model"],
        "observed_models": models,
        "configured": provider["configured"],
        "compact_ir": provider["compact_ir"],
        "compact_version": provider["compact_version"],
        "repair_attempts": provider["repair_attempts"],
        "metrics": metrics,
        "cost": {
            "verified_usd": metrics["verified_cost_usd"],
            "estimated_usd": metrics["estimated_cost_usd"],
            "total_usd": metrics["cost_usd"],
            "status": metrics["cost_status"],
            "unknown_runs": metrics["unknown_cost_runs"],
            "per_valid_template_usd": metrics["cost_per_valid_template_usd"],
            "per_valid_template_status": metrics["cost_per_valid_template_status"],
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
        ("requirement_coverage", "higher"),
        ("type_context_correctness", "higher"),
        ("semantic_pass_rate", "higher"),
        ("valid_template_rate", "higher"),
        ("cost_per_valid_template_usd", "lower"),
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


def _display_path(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def _write_json(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _csv_rows(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for provider in report["providers"]:
        metrics = provider["metrics"]
        rows.append(
            {
                "scope": "provider",
                "provider": provider["provider"],
                "model": provider["model"],
                "case_id": "",
                "runs": metrics["runs"],
                "planned_runs": metrics["planned_runs"],
                "valid_runs": metrics["valid_runs"],
                "precision": metrics["precision"],
                "recall": metrics["recall"],
                "requirement_coverage": metrics["requirement_coverage"],
                "type_context_correctness": metrics["type_context_correctness"],
                "block_coverage": metrics["block_coverage"],
                "semantic_pass_rate": metrics["semantic_pass_rate"],
                "valid_template_rate": metrics["valid_template_rate"],
                "validation_pass_rate": metrics["validation_pass_rate"],
                "latency_p50_ms": metrics["latency_p50_ms"],
                "latency_p95_ms": metrics["latency_p95_ms"],
                "cost_usd": metrics["cost_usd"],
                "cost_status": metrics["cost_status"],
                "verified_cost_usd": metrics["verified_cost_usd"],
                "estimated_cost_usd": metrics["estimated_cost_usd"],
                "unknown_cost_runs": metrics["unknown_cost_runs"],
            }
        )
    provider_models = {
        str(provider["provider"]): str(provider["model"] or "") for provider in report["providers"]
    }
    for case in report["per_case"]:
        for provider, metrics in case["providers"].items():
            rows.append(
                {
                    "scope": "case",
                    "provider": provider,
                    "model": provider_models.get(provider, ""),
                    "case_id": case["case_id"],
                    "runs": metrics["runs"],
                    "planned_runs": metrics["planned_runs"],
                    "valid_runs": metrics["valid_runs"],
                    "precision": metrics["precision"],
                    "recall": metrics["recall"],
                    "requirement_coverage": metrics["requirement_coverage"],
                    "type_context_correctness": metrics["type_context_correctness"],
                    "block_coverage": metrics["block_coverage"],
                    "semantic_pass_rate": metrics["semantic_pass_rate"],
                    "valid_template_rate": metrics["valid_template_rate"],
                    "validation_pass_rate": metrics["validation_pass_rate"],
                    "latency_p50_ms": metrics["latency_p50_ms"],
                    "latency_p95_ms": metrics["latency_p95_ms"],
                    "cost_usd": metrics["cost_usd"],
                    "cost_status": metrics["cost_status"],
                    "verified_cost_usd": metrics["verified_cost_usd"],
                    "estimated_cost_usd": metrics["estimated_cost_usd"],
                    "unknown_cost_runs": metrics["unknown_cost_runs"],
                }
            )
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


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]], *, css: str = "") -> str:
    head = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f'<table class="{css}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def _write_html(path: Path, report: Mapping[str, Any]) -> None:
    dataset = report["dataset"]
    sample = report["sample_size"]
    cost = report["cost"]
    leaders = report["leaders"]
    provider_rows = []
    for provider in report["providers"]:
        metrics = provider["metrics"]
        provider_rows.append(
            [
                f"<strong>{html.escape(provider['provider'])}</strong>"
                f"<br><span class='muted'>{html.escape(provider['model'] or '')}</span>",
                str(metrics["runs"]),
                _fmt(metrics["precision"]),
                _fmt(metrics["recall"]),
                _fmt(metrics["requirement_coverage"]),
                _fmt(metrics["type_context_correctness"]),
                _fmt(metrics["block_coverage"]),
                _pct(metrics["semantic_pass_rate"]),
                _pct(metrics["valid_template_rate"]),
                _fmt(metrics["latency_p50_ms"], 1),
                _money(metrics["cost_usd"], metrics["cost_status"]),
            ]
        )
    leader_rows = []
    for leader in leaders:
        leader_rows.append(
            [
                html.escape(leader["metric"]),
                html.escape(leader["direction"]),
                _fmt(leader["value"]),
                ", ".join(html.escape(name) for name in leader["leaders"]) or "N/A",
            ]
        )
    case_rows = []
    for case in report["per_case"]:
        for provider, metrics in case["providers"].items():
            case_rows.append(
                [
                    f"<strong>{html.escape(case['case_id'])}</strong>"
                    f"<br><span class='muted'>{html.escape(', '.join(case['labels']))}</span>",
                    html.escape(provider),
                    _fmt(metrics["precision"]),
                    _fmt(metrics["recall"]),
                    _fmt(metrics["requirement_coverage"]),
                    _fmt(metrics["type_context_correctness"]),
                    _pct(metrics["semantic_pass_rate"]),
                    _pct(metrics["valid_template_rate"]),
                ]
            )
    taxonomy_rows = [
        [html.escape(code), str(count), str(report["primary_error_counts"].get(code, 0))]
        for code, count in sorted(
            report["error_taxonomy"].items(), key=lambda item: ERROR_TAXONOMY.index(item[0])
        )
    ]
    provider_cards = []
    for provider in report["providers"]:
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
        provider_cards.append(
            f"""
            <section class="card">
              <h2>{html.escape(provider["provider"])} <span class="muted">{html.escape(provider["model"] or "")}</span></h2>
              <p class="muted">Runs: {metrics["runs"]} · planned: {metrics["planned_runs"]} · valid templates: {metrics["valid_runs"]} · cost: {_money(metrics["cost_usd"], metrics["cost_status"])}</p>
              <p>Precision {_fmt(metrics["precision"])} · Recall {_fmt(metrics["recall"])} · Coverage {_fmt(metrics["requirement_coverage"])} · Type/context {_fmt(metrics["type_context_correctness"])} · Semantic pass {_pct(metrics["semantic_pass_rate"])}</p>
              <p>Valid template rate <strong>{_pct(metrics["valid_template_rate"])}</strong> is reported separately from the semantic metrics.</p>
              {proxy_note}
            </section>
            """
        )
    html_text = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Semantic quality evaluation</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ margin: 0; padding: 32px 20px 64px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; color: #172033; background: #f5f7fb; line-height: 1.45; }}
  main {{ max-width: 1180px; margin: 0 auto; }}
  h1 {{ font-size: 30px; margin: 0 0 6px; }}
  h2 {{ font-size: 19px; margin: 0 0 8px; }}
  .muted {{ color: #64748b; font-weight: 400; font-size: 13px; }}
  .note {{ background: #fff7ed; border: 1px solid #fed7aa; border-left: 5px solid #ea580c; padding: 14px 18px; border-radius: 8px; margin: 18px 0; }}
  .note strong {{ color: #9a3412; }}
  .card {{ background: #fff; border: 1px solid #dfe5ef; border-radius: 10px; padding: 16px 18px; margin: 14px 0; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #dfe5ef; border-radius: 8px; overflow: hidden; margin: 12px 0 24px; font-size: 13px; }}
  th, td {{ padding: 8px 10px; border-bottom: 1px solid #edf1f7; text-align: left; vertical-align: top; }}
  th {{ background: #eef3fa; font-size: 12px; text-transform: uppercase; letter-spacing: .03em; color: #475569; }}
  tr:last-child td {{ border-bottom: none; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; }}
  .kv {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 12px; }}
  .kv b {{ display: block; font-size: 11px; text-transform: uppercase; color: #64748b; letter-spacing: .04em; }}
  .ok {{ color: #166534; font-weight: 700; }}
  .warn {{ color: #b45309; font-weight: 700; }}
  footer {{ color: #64748b; font-size: 12px; margin-top: 28px; }}
</style>
</head>
<body>
<main>
  <h1>Semantic quality evaluation</h1>
  <p class="muted">Technical validity and semantic correctness are reported separately. Generated {
        html.escape(report["generated_at"])
    }.</p>
  <div class="note"><strong>Observations, not significance.</strong> {
        html.escape(report["observations_not_significance"])
    }</div>

  <div class="grid">
    <div class="kv"><b>Dataset cases</b>{dataset["case_count"]}</div>
    <div class="kv"><b>Runs completed / planned</b>{sample["completed_runs"]} / {
        sample["planned_runs"]
    }</div>
    <div class="kv"><b>Repeats per case × provider</b>{report["settings"]["repeats"]}</div>
    <div class="kv"><b>Dataset SHA-256</b><span class="muted">{
        dataset["canonical_sha256"][:24]
    }…</span></div>
    <div class="kv"><b>Known + estimated spend</b>{_money(cost["total_usd"], cost["status"])}</div>
    <div class="kv"><b>Budget</b>{_money(report["budget"]["max_spend_usd"])} cap · warning at {
        _money(report["budget"]["warn_spend_usd"])
    }</div>
  </div>

  <h2>Per-provider observations</h2>
  {
        _table(
            [
                "Provider",
                "Runs",
                "Precision",
                "Recall",
                "Coverage",
                "Type/context",
                "Blocks",
                "Semantic pass",
                "Valid template",
                "p50 ms",
                "Cost",
            ],
            provider_rows,
        )
    }

  <h2>Per-metric leaders (no single winner)</h2>
  {_table(["Metric", "Direction", "Best", "Leaders (ties included)"], leader_rows)}

  <h2>Error taxonomy (runs)</h2>
  {_table(["Code", "Runs with code", "Primary code runs"], taxonomy_rows)}
  <p class="muted">A run can carry several semantic codes. Primary counts assign one dominant code per run with at least one code, including semantic misses that still produced a valid template; the primary column is not the failed-run count.</p>

  <h2>Cost and status</h2>
  <div class="card">
    <p>Verified cost: {_money(cost["verified_usd"])} · Estimated cost: {
        _money(cost["estimated_usd"])
    } · Unknown runs: {cost["unknown_runs"]}</p>
    <p>Gemini 3.6-flash is unpriced in the product price table. It is reported as <strong>estimated</strong> using the documented proxy, never as $0.00. Unknown cost is rendered as N/A.</p>
  </div>

  <h2>Cases</h2>
  {
        _table(
            [
                "Case",
                "Provider",
                "Precision",
                "Recall",
                "Coverage",
                "Type/context",
                "Semantic pass",
                "Valid template",
            ],
            case_rows,
        )
    }

  <h2>Per provider</h2>
  {"".join(provider_cards)}

  <h2>Settings</h2>
  <div class="card">
    <p>Prompt: {html.escape(report["settings"]["prompt_version"])} · Gemini: compact {
        html.escape(report["settings"]["gemini_compact_version"])
    } · Repair attempts: {report["settings"]["max_repair_attempts"]} · Max output tokens: {
        report["settings"]["max_output_tokens"]
    } · Temperature: {report["settings"]["temperature"]}</p>
    <p>Pricing: {html.escape(report["settings"]["pricing"]["pricing_version"])} ({
        html.escape(report["settings"]["pricing"]["as_of"])
    }) · Source: {html.escape(report["settings"]["pricing"]["pricing_source"])}</p>
    <p>Runs file: {html.escape(report["runs_file"])} · SHA-256 {
        html.escape(report["runs_sha256"][:24])
    }…</p>
  </div>

  <h2>Limits</h2>
  <div class="card">
    <p>Ground truth is authored for synthetic fixtures and encodes this project's judgement, not a customer's. Repeats show run-to-run variation only; they are not a population sample. LibreOffice, Word and Docentric pagination are out of scope here. Verified Docentric AX compatibility remains <strong>not_tested</strong>.</p>
  </div>
  <footer>Generated by benchmarks/semantic_evaluation.py · no credentials or raw model output are stored in this report.</footer>
</main>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_text, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def _configure_provider(
    gateway: LLMGateway, provider: str, model: str | None, repair_attempts: int
) -> dict[str, Any]:
    configured = True
    try:
        gateway.get(provider)
    except Exception:
        configured = False
    resolved_model = gateway.resolve_model(provider, model) if configured else model
    compact = provider == "gemini"
    return {
        "provider": provider,
        "model": model,
        "requested_model": resolved_model,
        "configured": configured,
        "compact_ir": compact,
        "compact_version": "v2" if compact else None,
        "repair_attempts": 2 if compact else repair_attempts,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--providers", default="mock:mock-planner-v1")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--runs-file", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--output-html", type=Path, default=DEFAULT_HTML)
    parser.add_argument(
        "--repeats",
        type=int,
        default=DEFAULT_REPEATS,
        help="runs per case and provider (default 3; Gemini always gets at least 3)",
    )
    parser.add_argument("--limit", type=int, default=None, help="first N cases")
    parser.add_argument("--case-ids", default="", help="comma-separated case ids")
    parser.add_argument(
        "--max-spend",
        type=float,
        default=DEFAULT_MAX_SPEND,
        help="abort before a call whose worst case could cross this USD cap (default 6)",
    )
    parser.add_argument(
        "--warn-spend",
        type=float,
        default=DEFAULT_WARN_SPEND,
        help="print a warning once spent known+estimated crosses this value (default 5)",
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
        default=DEFAULT_REPAIR_ATTEMPTS,
        choices=[0, 1, 2],
        help="planner repair calls (Gemini is always pinned to 2)",
    )
    args = parser.parse_args(argv)
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    if args.max_spend <= 0 or args.warn_spend < 0:
        parser.error("--max-spend must be positive and --warn-spend non-negative")

    definitions = json.loads(args.cases.read_bytes())
    if args.case_ids:
        wanted = {item.strip() for item in args.case_ids.split(",") if item.strip()}
        definitions = [case for case in definitions if case["id"] in wanted]
    if args.limit is not None:
        definitions = definitions[: max(0, args.limit)]
    if not definitions:
        print("No cases selected", file=sys.stderr)
        return 2

    parsed_packages: dict[str, Any] = {}
    schema_paths: dict[str, str] = {}
    for case in definitions:
        package = ROOT / str(case["package"])
        parsed = parse_ddsp(package.read_bytes(), package.name)
        parsed_packages[str(package)] = parsed
        for path in parsed.schema.paths:
            node = parsed.schema.node(path)
            if node is not None:
                schema_paths[path] = node.data_type
    dataset_errors = validate_cases(definitions, schema_paths=schema_paths)
    if dataset_errors:
        print("semantic dataset is invalid:", file=sys.stderr)
        for error in dataset_errors:
            print(f"  - {error}", file=sys.stderr)
        return 2

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
        _configure_provider(gateway, provider, model, args.repair_attempts)
        for provider, model in targets
    ]
    for state in provider_state:
        if not state["configured"]:
            print(
                f"warning: provider '{state['provider']}' is not configured; runs will be recorded as failures",
                file=sys.stderr,
            )
        if state["compact_ir"]:
            print(
                f"note: {state['provider']} uses compact {state['compact_version']} "
                f"with max_repair_attempts={state['repair_attempts']}",
                file=sys.stderr,
            )

    planned_runs = len(definitions) * len(provider_state) * args.repeats
    print(
        f"semantic evaluation: {len(definitions)} cases × {len(provider_state)} providers × "
        f"{args.repeats} repeats = {planned_runs} planned runs"
    )

    args.runs_file.parent.mkdir(parents=True, exist_ok=True)
    args.runs_file.write_text("", encoding="utf-8")
    runs: list[dict[str, Any]] = []
    known_spend = 0.0
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
                    provider = str(state["provider"])
                    repair_attempts = int(state["repair_attempts"])
                    if not state["configured"]:
                        run = _run_one(
                            planner=planner,
                            validator=validator,
                            compiler=compiler,
                            parsed=parsed,
                            case=case,
                            provider=provider,
                            model=state["model"],
                            provider_configured=False,
                            repeat=repeat,
                            repair_attempts=repair_attempts,
                            compact_ir=bool(state["compact_ir"]),
                            compact_version=state["compact_version"],
                        )
                        runs.append(run)
                        handle.write(json.dumps(run, sort_keys=True, ensure_ascii=False) + "\n")
                        handle.flush()
                        continue

                    language = str(case.get("language", "en"))
                    messages = _messages_for(
                        parsed.schema,
                        str(case["prompt"]),
                        compact=bool(state["compact_ir"]),
                        language=language,
                    )
                    requested_model = str(state["requested_model"] or state["model"] or "")
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
                        calls=repair_attempts + 1,
                    )
                    spent_total = round(known_spend + estimated_spend, 6)
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
                        provider_configured=True,
                        repeat=repeat,
                        repair_attempts=repair_attempts,
                        compact_ir=bool(state["compact_ir"]),
                        compact_version=state["compact_version"],
                    )
                    runs.append(run)
                    handle.write(json.dumps(run, sort_keys=True, ensure_ascii=False) + "\n")
                    handle.flush()
                    if run["cost_status"] == "verified" and run["cost_usd"] is not None:
                        known_spend = round(known_spend + float(run["cost_usd"]), 6)
                    elif run["cost_status"] == "estimated" and run["cost_usd"] is not None:
                        estimated_spend = round(estimated_spend + float(run["cost_usd"]), 6)
                    if not warned and round(known_spend + estimated_spend, 6) >= args.warn_spend:
                        warned = True
                        print(
                            f"WARNING: known+estimated spend ${known_spend + estimated_spend:.4f} "
                            f"reached the ${args.warn_spend:.2f} warning line",
                            file=sys.stderr,
                        )
                    status = "semantic-pass" if run["semantic_pass"] else "semantic-miss"
                    if not run["ok"]:
                        status = f"FAILED ({(run['error'] or {}).get('code')})"
                    elif not run["valid_template"]:
                        status = "valid-miss"
                    print(
                        f"{run['case_id']:<32} r{repeat} {provider:<10} {status:<24} "
                        f"P={_fmt((run['semantic'] or {}).get('precision'))} "
                        f"R={_fmt((run['semantic'] or {}).get('recall'))} "
                        f"{run['latency_ms'] / 1000:.1f}s "
                        f"{_money(run['cost_usd'], run['cost_status'])}"
                    )
        finished_all = datetime.now(UTC)

    runs_sha = hashlib.sha256(args.runs_file.read_bytes()).hexdigest()
    dataset = _dataset_metadata(definitions, args.cases)
    provider_reports = [
        _provider_report(state, [run for run in runs if run["provider"] == state["provider"]])
        for state in provider_state
    ]
    per_case = []
    for case in definitions:
        case_runs = [run for run in runs if run["case_id"] == case["id"]]
        per_case.append(
            {
                "case_id": case["id"],
                "labels": list(case.get("labels", [])),
                "language": case.get("language", "en"),
                "package": case.get("package"),
                "sample_size": len(case_runs),
                "providers": {
                    state["provider"]: _aggregate(
                        [run for run in case_runs if run["provider"] == state["provider"]]
                    )
                    for state in provider_state
                },
            }
        )
    total_aggregate = _aggregate(runs)
    verified = sum(float(run["cost_usd"]) for run in runs if run["cost_status"] == "verified")
    estimated = sum(float(run["cost_usd"]) for run in runs if run["cost_status"] == "estimated")
    overall_cost_status = (
        "estimated"
        if any(run["cost_status"] == "estimated" for run in runs)
        else "verified"
        if any(run["cost_status"] == "verified" for run in runs)
        else "unavailable"
    )
    report = {
        "schema": "semantic-report/v1",
        "generated_at": _iso(datetime.now(UTC)),
        "generated_by": "benchmarks/semantic_evaluation.py",
        "observations_not_significance": OBSERVATIONS_NOTE,
        "dataset": dataset,
        "sample_size": {
            "planned_runs": planned_runs,
            "completed_runs": len(runs),
            "planned_per_provider": {
                state["provider"]: len(definitions) * args.repeats for state in provider_state
            },
            "completed_per_provider": {
                state["provider"]: sum(1 for run in runs if run["provider"] == state["provider"])
                for state in provider_state
            },
            "cases": len(definitions),
            "repeats": args.repeats,
            "providers": len(provider_state),
        },
        "settings": {
            "prompt_version": PROMPT_VERSION,
            "gemini_compact_version": "v2",
            "compact_mode": "gemini-only",
            "max_repair_attempts": args.repair_attempts,
            "max_output_tokens": settings.llm_max_output_tokens,
            "temperature": 0.0,
            "timeout_seconds": settings.llm_timeout_seconds,
            "transport_retries": settings.llm_max_retries,
            "repeats": args.repeats,
            "budget_per_call_usd": settings.llm_max_generation_cost_usd,
            "pricing": price_table_metadata(),
            "proxy_pricing": PROXY_PRICES,
            "models": [
                {
                    "provider": state["provider"],
                    "requested_model": state["requested_model"],
                    "compact_ir": state["compact_ir"],
                    "compact_version": state["compact_version"],
                    "repair_attempts": state["repair_attempts"],
                }
                for state in provider_state
            ],
        },
        "providers": provider_reports,
        "per_case": per_case,
        "leaders": _leaders(provider_reports),
        "error_taxonomy": total_aggregate["error_counts"],
        "primary_error_counts": total_aggregate["primary_error_counts"],
        "aggregate": total_aggregate,
        "cost": {
            "verified_usd": round(verified, 6),
            "estimated_usd": round(estimated, 6),
            "total_usd": round(verified + estimated, 6),
            "status": overall_cost_status,
            "unknown_runs": sum(1 for run in runs if run["cost_status"] == "unavailable"),
            "cost_per_valid_template_usd": total_aggregate["cost_per_valid_template_usd"],
            "cost_per_valid_template_status": total_aggregate["cost_per_valid_template_status"],
        },
        "budget": {
            "max_spend_usd": args.max_spend,
            "warn_spend_usd": args.warn_spend,
            "allow_unpriced": args.allow_unpriced,
            "known_spend_usd": round(known_spend, 6),
            "estimated_spend_usd": round(estimated_spend, 6),
            "total_spend_usd": round(known_spend + estimated_spend, 6),
            "warned": warned,
            "aborted": aborted,
            "abort_reason": abort_reason,
        },
        "started_at": _iso(started_all),
        "finished_at": _iso(finished_all),
        "runs_file": str(args.runs_file.relative_to(ROOT))
        if args.runs_file.is_relative_to(ROOT)
        else str(args.runs_file),
        "runs_sha256": runs_sha,
        "notes": [
            OBSERVATIONS_NOTE,
            "valid_template_rate is the deterministic validation + compilation rate and is never folded into precision or recall.",
            "Gemini 3.6-flash is unpriced; its cost is estimated with the named proxy and is never reported as $0.00.",
            "Ground truth is authored for synthetic fixtures and reflects this project's judgement.",
            "Verified Docentric AX compatibility is not tested by this harness.",
        ],
    }
    _write_json(args.output_json, report)
    _write_csv(args.output_csv, report)
    _write_html(args.output_html, report)
    print(
        f"\ncompleted {len(runs)}/{planned_runs} runs · known spend "
        f"${known_spend:.4f} · estimated ${estimated_spend:.4f} · "
        f"total ${known_spend + estimated_spend:.4f}"
    )
    print(
        f"wrote {_display_path(args.output_json)}, "
        f"{_display_path(args.output_csv)}, {_display_path(args.output_html)}"
    )
    if aborted:
        print(f"ABORTED: {abort_reason}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
