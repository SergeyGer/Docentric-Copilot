#!/usr/bin/env python3
"""Live multi-provider evaluation for the template planner (VID-02).

Every case is planned once per provider with the same prompt and schema. The
harness records field precision/recall, requirement coverage, validation and
compilation success, latency (p50/p95), tokens and cost. An unknown price is
reported as ``N/A`` and never as ``$0.00``.

Cost is a hard guard: the harness estimates the worst case before each call and
aborts when the running estimate would exceed ``--max-spend-usd`` (default $3).
It never retries a failed case/provider; the failure is recorded in the report.

Usage::

    python benchmarks/live_evaluation.py \
        --providers openai:gpt-6-sol,anthropic:claude-sonnet-5-5,gemini:gemini-3.1-flash-lite \
        --limit 4 --max-spend-usd 2.5

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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

from docentric_copilot.config import Settings, get_settings  # noqa: E402
from docentric_copilot.ddsp_parser import parse_ddsp  # noqa: E402
from docentric_copilot.docx_compiler import CompileOptions, GenericDocxCompiler  # noqa: E402
from docentric_copilot.errors import ProviderError  # noqa: E402
from docentric_copilot.evaluation import (  # noqa: E402
    ProviderScore,
    aggregate_cost,
    display_cost,
    field_metrics,
    percentile,
    quality_score,
    recommend_provider,
)
from docentric_copilot.llm import LLMGateway  # noqa: E402
from docentric_copilot.llm.pricing import estimate_cost, price_table_metadata  # noqa: E402
from docentric_copilot.planner import PlanOptions, TemplatePlanner  # noqa: E402
from docentric_copilot.planner.prompt import build_messages  # noqa: E402
from docentric_copilot.planner.service import absolute_bindings  # noqa: E402
from docentric_copilot.template_ir import ir_digest  # noqa: E402
from docentric_copilot.template_validator import ValidationEngine  # noqa: E402

DEFAULT_CASES = ROOT / "benchmarks" / "live_cases.json"
DEFAULT_JSON = ROOT / "benchmarks" / "live_report.json"
DEFAULT_MD = ROOT / "benchmarks" / "live_report.md"
DEFAULT_TRACE_DIR = ROOT / "docs" / "media" / "runs"
_MAX_TOKENS_PER_CHAR = 0.35
_SECRET = re.compile(r"(?i)(api[-_]?key|authorization|bearer)\s*[=:]\s*\S+")


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


def _worst_case_cost(schema, prompt: str, model: str, max_output_tokens: int) -> float | None:
    messages = build_messages(schema, prompt)
    chars = sum(len(message.content) for message in messages)
    prompt_tokens = int(chars * _MAX_TOKENS_PER_CHAR)
    return estimate_cost(model, prompt_tokens, max_output_tokens)


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


def _run_one(
    *,
    planner: TemplatePlanner,
    validator: ValidationEngine,
    settings: Settings,
    parsed,
    definition: dict[str, Any],
    provider: str,
    model: str | None,
    provider_configured: bool,
    repair_attempts: int = 0,
    compact_ir: bool = False,
) -> dict[str, Any]:
    case_id = definition["case_id"]
    prompt = definition["prompt"]
    expected = sorted(set(definition.get("expected_paths", [])))
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    run_id = f"bench_{uuid.uuid4().hex[:16]}"
    base: dict[str, Any] = {
        "schema": "live-benchmark-run/v1",
        "run_id": run_id,
        "started_at": _iso(started_at),
        "case_id": case_id,
        "category": definition.get("category"),
        "provider": provider,
        "model": model,
        "actual_provider": None,
        "actual_model": None,
        "ok": False,
        "error": None,
        "latency_ms": 0,
        "usage": None,
        "cost_usd": None,
        "cost_known": False,
        "compact_ir": compact_ir,
        "validation": {},
        "validation_passed": False,
        "compiled": False,
        "compile_error": None,
        "requirements": 0,
        "covered_requirements": 0,
        "requirement_coverage": None,
        "precision": None,
        "recall": None,
        "true_positives": 0,
        "expected_fields": len(expected),
        "selected_fields": 0,
        "actual_paths": [],
        "ir_digest": None,
        "prompt_chars": len(prompt),
        "prompt_sha256": _prompt_digest(prompt),
    }

    if not provider_configured:
        base["error"] = {
            "code": "provider_not_configured",
            "message": f"Provider '{provider}' has no API key configured",
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
                ),
            )
        )
    except Exception as exc:
        message = exc.message if isinstance(exc, ProviderError) else str(exc)
        base["error"] = {
            "code": exc.code if isinstance(exc, ProviderError) else "harness_error",
            "message": _redact(message),
        }
        base["latency_ms"] = int((time.perf_counter() - started) * 1000)
        base["finished_at"] = _iso(datetime.now(UTC))
        return base

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    report = validator.validate(outcome.document, parsed.schema, sample_data=parsed.sample_data)
    actual_paths = absolute_bindings(outcome.document, parsed.schema)
    precision, recall, true_positives = field_metrics(expected, actual_paths)
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
    cost = usage.get("estimated_cost_usd") if usage else None
    public = generation.public_view() if generation is not None else {}

    base.update(
        {
            "ok": True,
            "actual_provider": public.get("provider"),
            "actual_model": public.get("model"),
            "latency_ms": elapsed_ms,
            "usage": usage,
            "cost_usd": cost,
            "cost_known": cost is not None,
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
            "ir_digest": ir_digest(outcome.document),
        }
    )
    base["finished_at"] = _iso(datetime.now(UTC))
    return base


def _aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [run for run in runs if run["ok"]]
    tp = sum(run["true_positives"] for run in successful)
    selected = sum(run["selected_fields"] for run in successful)
    expected = sum(run["expected_fields"] for run in successful)
    covered = sum(run["covered_requirements"] for run in successful)
    requirements = sum(run["requirements"] for run in successful)
    validations = sum(1 for run in successful if run["validation_passed"])
    compilations = sum(1 for run in successful if run["compiled"])
    costs = [run["cost_usd"] for run in successful]
    cost = aggregate_cost(costs)
    p50 = percentile([float(run["latency_ms"]) for run in successful], 0.5)
    p95 = percentile([float(run["latency_ms"]) for run in successful], 0.95)
    precision = round(tp / selected, 6) if selected else None
    recall = round(tp / expected, 6) if expected else None
    coverage = round(covered / requirements, 6) if requirements else None
    validation_rate = validations / len(successful) if successful else 0.0
    return {
        "runs": len(runs),
        "successful_runs": len(successful),
        "failed_runs": len(runs) - len(successful),
        "field_precision": precision,
        "field_recall": recall,
        "requirement_coverage": coverage,
        "validation_pass_rate": round(validation_rate, 6),
        "compilation_success_rate": (
            round(compilations / len(successful), 6) if successful else 0.0
        ),
        "quality_score": quality_score(
            precision=precision,
            recall=recall,
            coverage=coverage,
            validation_pass_rate=validation_rate,
        ),
        "latency_ms": {"p50": p50, "p95": p95, "samples": len(successful)},
        "tokens": {
            "prompt": sum((run["usage"] or {}).get("prompt_tokens", 0) for run in successful),
            "completion": sum(
                (run["usage"] or {}).get("completion_tokens", 0) for run in successful
            ),
        },
        "cost_usd": cost,
        "cost_known": cost is not None,
        "unknown_cost_runs": sum(1 for run in successful if run["cost_usd"] is None),
    }


def _markdown(report: dict[str, Any]) -> str:
    lines: list[str] = [
        "# Live multi-provider evaluation",
        "",
        f"Generated {report['generated_at']} by `benchmarks/live_evaluation.py`.",
        "",
        "One run per case and provider. Cost is an estimate from the versioned price table "
        f"`{report['pricing_version']}` (as of {report['pricing_as_of']}); `N/A` means the model "
        "has no published price and is **not** a free call.",
        "",
        f"- Cases: {report['case_count']} from `{report['cases_file']}`",
        f"- Providers: {', '.join(item['provider'] + (':' + item['model'] if item['model'] else '') for item in report['providers'])}",
        f"- Estimated spend: {display_cost(report['budget']['estimated_spend_usd'])}"
        f" of {display_cost(report['budget']['max_spend_usd'])} cap"
        f" (unknown-cost runs: {report['budget']['unknown_cost_runs']})",
        f"- Aborted early: {'yes' if report['budget']['aborted'] else 'no'}",
        f"- Repair attempts per plan: {report.get('repair_attempts', 0)} "
        f"(max output {report.get('max_output_tokens', 'n/a')} tokens)",
        f"- Compact IR mode: {report.get('compact_ir', 'n/a')}",
        "",
    ]
    if report["budget"]["aborted"]:
        lines += [f"> Aborted: {report['budget']['abort_reason']}", ""]

    lines += [
        "## Provider summary",
        "",
        "| Provider | Model | Quality | Precision | Recall | Coverage | Validation | Compile | p50 | p95 | Tokens | Cost |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for aggregate in report["aggregates"]:
        lines.append(
            "| {provider} | {model} | {quality:.3f} | {precision} | {recall} | {coverage} | "
            "{validation:.0%} | {compile:.0%} | {p50} | {p95} | {tokens} | {cost} |".format(
                provider=aggregate["provider"],
                model=aggregate["model"] or "(default)",
                quality=aggregate["quality_score"],
                precision=(
                    f"{aggregate['field_precision']:.3f}"
                    if aggregate["field_precision"] is not None
                    else "N/A"
                ),
                recall=(
                    f"{aggregate['field_recall']:.3f}"
                    if aggregate["field_recall"] is not None
                    else "N/A"
                ),
                coverage=(
                    f"{aggregate['requirement_coverage']:.3f}"
                    if aggregate["requirement_coverage"] is not None
                    else "N/A"
                ),
                validation=aggregate["validation_pass_rate"],
                compile=aggregate["compilation_success_rate"],
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
                tokens=aggregate["tokens"]["prompt"] + aggregate["tokens"]["completion"],
                cost=display_cost(aggregate["cost_usd"]),
            )
        )
    lines += ["", f"Recommendation: {report['recommendation']['provider'] or 'none'}", ""]
    if report["recommendation"]["rationale"]:
        lines += [report["recommendation"]["rationale"], ""]

    lines += [
        "## Per-case results",
        "",
        "| Case | Provider | Precision | Recall | Coverage | Validation | Compiled | Latency | Cost | Error |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for run in report["runs"]:
        lines.append(
            "| {case} | {provider} | {precision} | {recall} | {coverage} | {validation} | "
            "{compiled} | {latency} ms | {cost} | {error} |".format(
                case=run["case_id"],
                provider=run["provider"] + (f":{run['model']}" if run["model"] else ""),
                precision=(f"{run['precision']:.3f}" if run["precision"] is not None else "N/A"),
                recall=f"{run['recall']:.3f}" if run["recall"] is not None else "N/A",
                coverage=(
                    f"{run['requirement_coverage']:.3f}"
                    if run["requirement_coverage"] is not None
                    else "N/A"
                ),
                validation="pass" if run["validation_passed"] else "fail",
                compiled="yes" if run["compiled"] else "no",
                latency=run["latency_ms"],
                cost=display_cost(run["cost_usd"]),
                error=(run["error"] or {}).get("message", "")[:120].replace("|", "/"),
            )
        )
    lines += [
        "",
        "## Caveats",
        "",
        "- One run per case and provider: these are observations, not a statistically significant benchmark.",
        "- Latency includes prompt assembly, the provider call and deterministic repair, but not HTTP "
        "transport to this harness.",
        "- The recommendation is lexicographic: quality first, then known cost, then p50 latency.",
        "- Cases with an empty expected set (the missing-field case) are excluded from precision/recall "
        "aggregates because the denominator is zero.",
        "- Per-run traces are written under `docs/media/runs/` (git-ignored) and contain no prompt text.",
        "",
    ]
    return "\n".join(lines) + "\n"


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
    parser.add_argument("--max-spend-usd", type=float, default=3.0)
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
        "--repair-attempts",
        type=int,
        default=0,
        choices=[0, 1],
        help=("0 = exactly one generation (default); 1 allows the planner's single repair call"),
    )
    args = parser.parse_args(argv)

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
        provider_state.append({"provider": provider, "model": model, "configured": configured})
        if not configured:
            print(f"warning: provider '{provider}' is not configured; runs will be failures")

    runs: list[dict[str, Any]] = []
    spent = 0.0
    unknown_cost_runs = 0
    aborted = False
    abort_reason = ""

    for definition in definitions:
        package = ROOT / definition["package"]
        parsed = parsed_packages.get(str(package))
        if parsed is None:
            parsed = parse_ddsp(package.read_bytes(), package.name)
            parsed_packages[str(package)] = parsed
        for provider, model in targets:
            configured = next(
                item["configured"]
                for item in provider_state
                if item["provider"] == provider and item["model"] == model
            )
            if not configured:
                run = _run_one(
                    planner=planner,
                    validator=validator,
                    settings=settings,
                    parsed=parsed,
                    definition=definition,
                    provider=provider,
                    model=model,
                    provider_configured=False,
                    repair_attempts=args.repair_attempts,
                    compact_ir=_compact_enabled(args.compact_ir, provider),
                )
                runs.append(run)
                continue

            resolved_model = gateway.resolve_model(provider, model)
            worst_case = _worst_case_cost(
                parsed.schema,
                definition["prompt"],
                resolved_model,
                settings.llm_max_output_tokens,
            )
            if worst_case is None:
                if not args.allow_unpriced:
                    aborted = True
                    abort_reason = (
                        f"refusing to call unpriced model '{resolved_model}': the budget guard "
                        "cannot bound the spend (use --allow-unpriced to override)"
                    )
                    break
                print(f"warning: {resolved_model} is unpriced; budget guard is advisory")
            elif spent + worst_case > args.max_spend_usd:
                aborted = True
                abort_reason = (
                    f"next call could cost up to {display_cost(worst_case)}; "
                    f"running spend {display_cost(spent)} would exceed the "
                    f"{display_cost(args.max_spend_usd)} cap"
                )
                break

            run = _run_one(
                planner=planner,
                validator=validator,
                settings=settings,
                parsed=parsed,
                definition=definition,
                provider=provider,
                model=model,
                provider_configured=True,
                repair_attempts=args.repair_attempts,
                compact_ir=_compact_enabled(args.compact_ir, provider),
            )
            runs.append(run)
            if run["cost_usd"] is not None:
                spent = round(spent + run["cost_usd"], 6)
            elif run["ok"]:
                unknown_cost_runs += 1

            _write_trace(
                trace_dir,
                {
                    "schema": "live-benchmark-trace/v1",
                    **{
                        key: run[key]
                        for key in (
                            "run_id",
                            "case_id",
                            "category",
                            "provider",
                            "model",
                            "actual_provider",
                            "actual_model",
                            "ok",
                            "error",
                            "latency_ms",
                            "usage",
                            "cost_usd",
                            "cost_known",
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
                            "ir_digest",
                            "prompt_chars",
                            "prompt_sha256",
                            "finished_at",
                        )
                    },
                    "pricing": price_table_metadata(),
                },
            )
            status = "ok" if run["ok"] else f"FAILED ({run['error']['code']})"
            print(
                f"{definition['case_id']:<32} {provider:<10} {status:<22} "
                f"{display_cost(run['cost_usd']):>11}  running {display_cost(spent)}"
            )
            if run["cost_usd"] is None and run["ok"]:
                print("  cost unknown (N/A): the model has no published price")
            if spent > args.max_spend_usd:
                aborted = True
                abort_reason = (
                    f"running spend {display_cost(spent)} exceeded the "
                    f"{display_cost(args.max_spend_usd)} cap"
                )
                break
        if aborted:
            break

    aggregates: list[dict[str, Any]] = []
    for state in provider_state:
        provider_runs = [
            run
            for run in runs
            if run["provider"] == state["provider"] and run["model"] == state["model"]
        ]
        aggregate = _aggregate(provider_runs)
        aggregate.update({"provider": state["provider"], "model": state["model"]})
        aggregates.append(aggregate)

    scored = [
        ProviderScore(
            provider=item["provider"],
            model=item["model"],
            quality=item["quality_score"],
            cost_usd=item["cost_usd"],
            latency_p50_ms=item["latency_ms"]["p50"],
        )
        for item in aggregates
    ]
    recommended = recommend_provider(scored)
    rationale = (
        "Quality first (weighted precision, recall and coverage, gated by validation), "
        "then known cost, then p50 latency. Unpriced providers sort after priced ones "
        "on the budget criterion."
    )
    generated_at = _iso(datetime.now(UTC))
    total_cost = aggregate_cost([run["cost_usd"] for run in runs if run["ok"]])
    report = {
        "schema": "live-benchmark/v1",
        "generated_by": "benchmarks/live_evaluation.py",
        "generated_at": generated_at,
        "pricing_version": price_table_metadata()["pricing_version"],
        "pricing_as_of": price_table_metadata()["pricing_as_of"],
        "pricing_source": price_table_metadata()["pricing_source"],
        "cases_file": str(args.cases.relative_to(ROOT)),
        "case_count": len({run["case_id"] for run in runs}),
        "repair_attempts": args.repair_attempts,
        "compact_ir": args.compact_ir,
        "max_output_tokens": settings.llm_max_output_tokens,
        "providers": provider_state,
        "budget": {
            "max_spend_usd": args.max_spend_usd,
            "estimated_spend_usd": total_cost,
            "known_spend_usd": spent,
            "unknown_cost_runs": unknown_cost_runs,
            "aborted": aborted,
            "abort_reason": abort_reason,
        },
        "runs": runs,
        "aggregates": aggregates,
        "recommendation": {
            "provider": recommended,
            "quality_first": True,
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
            f"precision {aggregate['field_precision']} recall {aggregate['field_recall']} "
            f"coverage {aggregate['requirement_coverage']} "
            f"p50 {aggregate['latency_ms']['p50']} ms "
            f"cost {display_cost(aggregate['cost_usd'])}"
        )
    print(f"recommended: {recommended or 'none'}")
    print(f"estimated spend: {display_cost(total_cost)} (unknown runs: {unknown_cost_runs})")
    print(f"written to {args.output_json} and {args.output_md}")
    return 1 if aborted else 0


if __name__ == "__main__":
    raise SystemExit(main())
