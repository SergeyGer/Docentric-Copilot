#!/usr/bin/env python3
"""Build and verify the v0.12 full-benchmark manifest (V012-02).

The runner writes a per-run JSONL file and an aggregate JSON report. This module
turns those artifacts into the release manifest required by the TZ: a unique
logical run for every ``case x provider x repeat``, its status, retry/attempt
history, tokens, cost, latency, model id and commit.

The manifest is public: it contains no prompts, raw provider output, API keys,
private corpus paths or customer data.

Usage::

    python benchmarks/benchmark_manifest.py --write
    python benchmarks/benchmark_manifest.py --check
    python benchmarks/benchmark_manifest.py --check --json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # pragma: no cover - import bootstrap when run as a script
    sys.path.insert(0, str(ROOT))

from docentric_copilot import __version__  # noqa: E402

from benchmarks.gold_audit import benchmark_dataset_snapshot  # noqa: E402
from benchmarks.gold_dataset import load_gold_dataset  # noqa: E402
from benchmarks.versions import (  # noqa: E402
    BENCHMARK_RUNNER_VERSION,
    COMPACT_PROMPT_VERSION,
    EVALUATOR_VERSION,
    FULL_PROMPT_VERSION,
    PLANNER_VERSION,
)

DEFAULT_RUNS = ROOT / "benchmarks" / "gold_runs_v012.jsonl"
DEFAULT_REPORT = ROOT / "benchmarks" / "gold_report_v012.json"
DEFAULT_OUTPUT = ROOT / "benchmarks" / "gold_manifest_v012.json"
DEFAULT_CASES = ROOT / "benchmarks" / "gold_cases.json"
DEFAULT_V010 = ROOT / "benchmarks" / "gold_report.json"
DEFAULT_V011 = ROOT / "benchmarks" / "gold_report_v011_subset.json"
MANIFEST_SCHEMA: Final = "gold-benchmark-manifest/v1"
MANIFEST_VERSION: Final = "1.0.0"
EXPECTED_CASES: Final = 32
EXPECTED_PROVIDERS: Final = 3
EXPECTED_REPEATS: Final = 3
EXPECTED_RUNS: Final = EXPECTED_CASES * EXPECTED_PROVIDERS * EXPECTED_REPEATS

METRIC_DEFINITIONS: Final = {
    "semantic_precision": "correct predicted bindings / all predicted bindings",
    "semantic_recall": "correct predicted bindings / all expected bindings",
    "valid_template_rate": (
        "completed logical runs whose plan parsed, expanded and passed IR/schema validation, "
        "before compilation"
    ),
    "semantic_pass_rate": "logical runs passing every semantic assertion / evaluable runs",
    "wrong_binding_rate": "incorrect predicted bindings / all predicted bindings",
    "abstention_rate": "runs with at least one needs-review requirement and no selected path",
    "review_rate": "runs with at least one review row / executed runs",
    "cost_per_template_usd": "cost / completed logical run; separate per semantically passed run",
    "latency_p50_p95_ms": "p50/p95 latency over completed logical runs",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"{path} must contain a JSON object")
    return value


def _load_runs(path: Path) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SystemExit(f"cannot read runs file {path}: {exc}") from exc
    for index, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            run = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{index}: invalid JSON: {exc}") from exc
        if not isinstance(run, dict):
            raise SystemExit(f"{path}:{index}: run must be a JSON object")
        runs.append(run)
    return runs


def _relative(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def _provider_metrics(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    metrics: dict[str, dict[str, Any]] = {}
    for provider in report.get("providers") or []:
        if not isinstance(provider, dict):
            continue
        values = provider.get("metrics") or {}
        if not isinstance(values, dict):
            continue
        keys = (
            "runs",
            "planned_runs",
            "precision",
            "recall",
            "f1",
            "semantic_pass_rate",
            "valid_template_rate",
            "compilation_success_rate",
            "wrong_binding_rate",
            "abstention_rate",
            "review_rate",
            "cost_per_correct_result_usd",
            "cost_usd",
            "cost_status",
            "latency_p50_ms",
            "latency_p95_ms",
            "error_counts",
            "primary_error_counts",
        )
        metrics[str(provider.get("provider"))] = {
            "requested_model": provider.get("requested_model"),
            "observed_models": provider.get("observed_models") or [],
            **{key: values.get(key) for key in keys if key in values},
        }
    return metrics


def _report_comparison(path: Path, label: str) -> dict[str, Any]:
    report = _load_json(path)
    sample = report.get("sample_size") or {}
    dataset = report.get("dataset") or {}
    return {
        "label": label,
        "file": _relative(path),
        "sha256": _sha256(path),
        "generated_at": report.get("generated_at"),
        "dataset_version": dataset.get("version"),
        "dataset_schema": dataset.get("schema"),
        "dataset_sha256": dataset.get("file_sha256") or dataset.get("sha256"),
        "cases": sample.get("cases"),
        "providers": sample.get("providers"),
        "repeats": sample.get("repeats"),
        "planned_runs": sample.get("planned_runs"),
        "completed_runs": sample.get("completed_runs"),
        "aggregate": report.get("aggregate"),
        "provider_metrics": _provider_metrics(report),
        "settings": report.get("settings"),
    }


def _expected_combinations(dataset: Any, report: dict[str, Any]) -> list[tuple[str, str, int]]:
    models = (report.get("settings") or {}).get("models") or []
    configured = [item for item in models if isinstance(item, dict) and item.get("configured")]
    if not configured:
        raise SystemExit("report settings do not list any configured provider")
    combinations: list[tuple[str, str, int]] = []
    for case in dataset.cases:
        case_id = str(case.get("id"))
        for model in configured:
            provider = str(model.get("provider"))
            repeats = int(model.get("repeats") or report.get("settings", {}).get("repeats") or 0)
            for repeat in range(1, repeats + 1):
                combinations.append((case_id, provider, repeat))
    return combinations


def _run_status(run: dict[str, Any]) -> str:
    return "completed" if run.get("ok") else "technical_failure"


def _run_entry(run: dict[str, Any]) -> dict[str, Any]:
    usage = run.get("usage") or {}
    attempts = int(run.get("attempts") or 0)
    return {
        "run_id": run.get("run_id"),
        "case_id": run.get("case_id"),
        "repeat_index": run.get("repeat"),
        "provider": run.get("provider"),
        "model_id": run.get("actual_model") or run.get("requested_model"),
        "timestamp": run.get("started_at"),
        "finished_at": run.get("finished_at"),
        "status": _run_status(run),
        "technical_failure": not bool(run.get("ok")),
        "technical_reason": ((run.get("error") or {}).get("code") if not run.get("ok") else None),
        "gateway_attempts": attempts,
        "retries": max(0, attempts - 1),
        "valid_template": bool(run.get("valid_template")),
        "semantic_pass": bool(run.get("semantic_pass")),
        "correct": bool(run.get("correct")),
        "semantic_excluded": bool(run.get("semantic_excluded")),
        "tokens": {
            "prompt": usage.get("prompt_tokens") or usage.get("input_tokens"),
            "completion": usage.get("completion_tokens") or usage.get("output_tokens"),
            "total": usage.get("total_tokens"),
        },
        "cost_usd": run.get("cost_usd"),
        "cost_status": run.get("cost_status"),
        "latency_ms": run.get("latency_ms"),
        "finish_reason": run.get("finish_reason"),
        "error_codes": list(run.get("error_codes") or []),
        "primary_error": run.get("primary_error"),
        "compact_ir": bool(run.get("compact_ir")),
        "compact_version": run.get("compact_version"),
        "prompt_version": run.get("prompt_version"),
        "forbidden_hits": len(run.get("forbidden_hits") or []),
        "missing_requirements": len(run.get("missing_requirements") or []),
        "wrong_paths": len(run.get("wrong_paths") or []),
        "abstained": bool(run.get("abstained")),
        "review_requirements": len(run.get("review_requirements") or []),
    }


def _placeholder(case_id: str, provider: str, repeat: int, reason: str) -> dict[str, Any]:
    return {
        "run_id": f"gold_skipped_{provider}_{case_id}_{repeat}".replace(".", "-"),
        "case_id": case_id,
        "repeat_index": repeat,
        "provider": provider,
        "model_id": None,
        "timestamp": None,
        "finished_at": None,
        "status": "skipped",
        "technical_failure": False,
        "technical_reason": None,
        "skip_reason": reason,
        "gateway_attempts": 0,
        "retries": 0,
        "valid_template": False,
        "semantic_pass": False,
        "correct": False,
        "semantic_excluded": False,
        "tokens": {"prompt": None, "completion": None, "total": None},
        "cost_usd": None,
        "cost_status": "unavailable",
        "latency_ms": None,
        "finish_reason": None,
        "error_codes": [],
        "primary_error": None,
        "compact_ir": provider == "gemini",
        "compact_version": "v2" if provider == "gemini" else None,
        "prompt_version": None,
        "forbidden_hits": 0,
        "missing_requirements": 0,
        "wrong_paths": 0,
        "abstained": False,
        "review_requirements": 0,
    }


def _manifest_hash(manifest: dict[str, Any]) -> str:
    body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def build_manifest(
    *,
    runs_path: Path = DEFAULT_RUNS,
    report_path: Path = DEFAULT_REPORT,
    cases_path: Path = DEFAULT_CASES,
    v010_path: Path = DEFAULT_V010,
    v011_path: Path = DEFAULT_V011,
    run_commit: str | None = None,
    dirty_paths: list[str] | None = None,
) -> dict[str, Any]:
    dataset = load_gold_dataset(cases_path)
    report = _load_json(report_path)
    runs = _load_runs(runs_path)
    combinations = _expected_combinations(dataset, report)
    expected_keys = {(case_id, provider, repeat) for case_id, provider, repeat in combinations}

    by_key: dict[tuple[str, str, int], dict[str, Any]] = {}
    duplicate_keys: list[str] = []
    seen_run_ids: Counter[str] = Counter()
    for run in runs:
        key = (str(run.get("case_id")), str(run.get("provider")), int(run.get("repeat") or 0))
        if key in by_key:
            duplicate_keys.append(f"{key[1]}/{key[0]}/r{key[2]}")
        by_key[key] = run
        seen_run_ids[str(run.get("run_id"))] += 1
    duplicate_run_ids = sorted(run_id for run_id, count in seen_run_ids.items() if count > 1)

    entries: list[dict[str, Any]] = []
    for case_id, provider, repeat in combinations:
        run = by_key.get((case_id, provider, repeat))
        if run is None:
            entries.append(
                _placeholder(case_id, provider, repeat, "no run record was written by the runner")
            )
        else:
            entries.append(_run_entry(run))

    completed = [entry for entry in entries if entry["status"] == "completed"]
    technical = [entry for entry in entries if entry["status"] == "technical_failure"]
    skipped = [entry for entry in entries if entry["status"] == "skipped"]
    semantic_failures = [entry for entry in completed if not entry["semantic_pass"]]
    counters = {
        "planned_runs": len(combinations),
        "completed_runs": len(completed),
        "technical_failures": len(technical),
        "skipped_runs": len(skipped),
        "blocked_runs": 0,
        "valid_template_runs": sum(1 for entry in entries if entry["valid_template"]),
        "semantic_pass_runs": sum(1 for entry in entries if entry["semantic_pass"]),
        "correct_runs": sum(1 for entry in entries if entry["correct"]),
        "semantic_failures": len(semantic_failures),
        "failed_runs": len(technical),
        "unique_run_ids": len(seen_run_ids),
    }
    report_counters = report.get("counters") or {}
    invariants = {
        "planned_equals_completed_plus_technical_plus_skipped": (
            counters["planned_runs"]
            == counters["completed_runs"]
            + counters["technical_failures"]
            + counters["skipped_runs"]
        ),
        "all_expected_combinations_present": len(entries) == len(expected_keys),
        "all_run_ids_unique": not duplicate_run_ids and len(seen_run_ids) == len(runs),
        "no_duplicate_combinations": not duplicate_keys,
        "report_planned_matches_manifest": report_counters.get("planned_runs")
        in (None, counters["planned_runs"]),
        "report_executed_matches_completed_plus_technical": report_counters.get("executed_runs")
        in (None, counters["completed_runs"] + counters["technical_failures"]),
        "report_failed_matches_technical": report_counters.get("failed_runs")
        in (None, counters["technical_failures"]),
        "counters_are_explained": not skipped or all(entry.get("skip_reason") for entry in skipped),
    }

    settings = report.get("settings") or {}
    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "manifest_version": MANIFEST_VERSION,
        "created_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "dataset": benchmark_dataset_snapshot(dataset),
        "plan": {
            "cases": len(dataset.cases),
            "providers": len({provider for _, provider, _ in combinations}),
            "repeats": sorted({repeat for _, _, repeat in combinations}),
            "runs": len(combinations),
        },
        "versions": {
            "prompt_version": FULL_PROMPT_VERSION,
            "compact_prompt_version": COMPACT_PROMPT_VERSION,
            "planner_version": PLANNER_VERSION,
            "evaluator_version": EVALUATOR_VERSION,
            "benchmark_runner_version": BENCHMARK_RUNNER_VERSION,
            "app_version": __version__,
            "app_commit": run_commit or _git("rev-parse", "HEAD"),
            "working_tree_dirty": bool(dirty_paths) or bool(_git("status", "--porcelain")),
            "dirty_paths": sorted(dirty_paths or []),
            "manifest_generated_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
            "manifest_version": MANIFEST_VERSION,
        },
        "generation": {
            "temperature": settings.get("temperature"),
            "max_output_tokens": settings.get("max_output_tokens"),
            "transport_retries": settings.get("transport_retries"),
            "timeout_seconds": settings.get("timeout_seconds"),
            "repair_attempts": settings.get("repair_attempts"),
            "paid_repeats": settings.get("paid_repeats"),
            "pricing": settings.get("pricing"),
            "candidate_filter": settings.get("candidate_filter"),
            "candidate_filter_version": settings.get("candidate_filter_version"),
            "gemini_compact_version": settings.get("gemini_compact_version"),
        },
        "models": [
            {
                "provider": model.get("provider"),
                "requested_model": model.get("requested_model"),
                "compact_ir": model.get("compact_ir"),
                "compact_version": model.get("compact_version"),
                "repair_attempts": model.get("repair_attempts"),
                "repeats": model.get("repeats"),
            }
            for model in settings.get("models") or []
            if isinstance(model, dict)
        ],
        "artifacts": {
            "runs_file": _relative(runs_path),
            "runs_sha256": _sha256(runs_path),
            "runs_records": len(runs),
            "report_file": _relative(report_path),
            "report_sha256": _sha256(report_path),
            "report_schema": report.get("schema"),
            "report_generated_at": report.get("generated_at"),
        },
        "counters": counters,
        "invariants": invariants,
        "runs": entries,
        "aggregate": report.get("aggregate"),
        "report_counters": report_counters,
        "providers": _provider_metrics(report),
        "error_taxonomy": report.get("error_taxonomy"),
        "metric_definitions": METRIC_DEFINITIONS,
        "comparison": {
            "v0_10_full": _report_comparison(v010_path, "v0.10 full report"),
            "v0_11_subset": _report_comparison(v011_path, "v0.11 affected subset"),
            "v0_12_full": _report_comparison(report_path, "v0.12 full report"),
            "differences": [
                "Dataset: v0.10 used gold-cases/v1 version 1.0.0; v0.12 uses "
                "gold-cases/v2 version 2.0.0 with provenance and 32 verified labels.",
                "Prompts/evaluator: v0.11 introduced candidate filtering (v0.11.1) and the v2 "
                f"provenance-aware labels; v0.12 pins prompt {FULL_PROMPT_VERSION} / compact "
                f"{COMPACT_PROMPT_VERSION} and evaluator {EVALUATOR_VERSION}.",
                "Coverage: v0.10 was a full 32-case x 3-provider x 3-repeat matrix; v0.11 was a "
                "12-case affected subset x 3 providers x 2 repeats; v0.12 is a full 32 x 3 x 3 "
                "matrix again.",
                "Models: requests are gpt-6-sol, claude-sonnet-5-5 and gemini-3.6-flash; the "
                "manifest records the observed model ids.",
                "The three reports are shown side by side and are not spliced into one aggregate.",
            ],
        },
        "governance": {
            "at07_status": "partial",
            "second_human_annotator": False,
            "note": (
                "Labels are author judgement plus a deterministic adjudicator proxy; "
                "no independent human review was performed."
            ),
            "dataset_audit": "docs/GOLD_AUDIT.md",
        },
        "limitations": [
            "The benchmark measures agreement with this project's 32-case labels, "
            "not absolute truth.",
            "Three repeats show run-to-run variation; they are not a population sample.",
            "Provider models and prices change; results are pinned to the recorded ids and date.",
            "Docentric AX runtime compatibility remains not_tested.",
            "No independent human review was performed; AT-07 stays partial.",
        ],
    }
    manifest["manifest_sha256"] = _manifest_hash(manifest)
    return manifest


def validate_manifest(
    manifest: Any,
    *,
    runs_path: Path = DEFAULT_RUNS,
    report_path: Path = DEFAULT_REPORT,
    cases_path: Path = DEFAULT_CASES,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return ["manifest must be a JSON object"]
    if manifest.get("schema") != MANIFEST_SCHEMA:
        errors.append(f"manifest schema is {manifest.get('schema')!r}")
    runs = manifest.get("runs")
    if not isinstance(runs, list):
        return [*errors, "manifest runs must be a list"]
    if len(runs) != EXPECTED_RUNS:
        errors.append(f"manifest has {len(runs)} runs, expected {EXPECTED_RUNS}")
    run_ids = [str(entry.get("run_id")) for entry in runs if isinstance(entry, dict)]
    if len(set(run_ids)) != len(run_ids):
        errors.append("manifest contains duplicate run ids")
    combos = Counter(
        (entry.get("case_id"), entry.get("provider"), entry.get("repeat_index"))
        for entry in runs
        if isinstance(entry, dict)
    )
    if len(combos) != EXPECTED_RUNS:
        errors.append(f"manifest has {len(combos)} unique combinations, expected {EXPECTED_RUNS}")
    if any(count != 1 for count in combos.values()):
        errors.append("a logical case/provider/repeat combination is not unique")
    cases = {str(entry.get("case_id")) for entry in runs if isinstance(entry, dict)}
    if len(cases) != EXPECTED_CASES:
        errors.append(f"manifest covers {len(cases)} cases, expected {EXPECTED_CASES}")
    providers = {str(entry.get("provider")) for entry in runs if isinstance(entry, dict)}
    if len(providers) != EXPECTED_PROVIDERS:
        errors.append(f"manifest covers {len(providers)} providers, expected {EXPECTED_PROVIDERS}")
    for provider in providers:
        provider_entries = [
            entry for entry in runs if isinstance(entry, dict) and entry.get("provider") == provider
        ]
        if len(provider_entries) != EXPECTED_CASES * EXPECTED_REPEATS:
            errors.append(
                f"provider {provider!r} has {len(provider_entries)} runs, "
                f"expected {EXPECTED_CASES * EXPECTED_REPEATS}"
            )

    counters = manifest.get("counters") or {}
    status_counts = Counter(str(entry.get("status")) for entry in runs if isinstance(entry, dict))
    if counters.get("planned_runs") != len(runs):
        errors.append("counters.planned_runs does not match the runs list")
    if counters.get("completed_runs") != status_counts.get("completed", 0):
        errors.append("counters.completed_runs does not match the completed statuses")
    if counters.get("technical_failures") != status_counts.get("technical_failure", 0):
        errors.append("counters.technical_failures does not match the failed statuses")
    if counters.get("skipped_runs") != status_counts.get("skipped", 0):
        errors.append("counters.skipped_runs does not match the skipped statuses")
    if counters.get("completed_runs", 0) + counters.get("technical_failures", 0) + counters.get(
        "skipped_runs", 0
    ) != counters.get("planned_runs", -1):
        errors.append("completed + technical + skipped does not equal planned")
    if any(
        entry.get("status") == "skipped" and not entry.get("skip_reason")
        for entry in runs
        if isinstance(entry, dict)
    ):
        errors.append("a skipped run has no explicit reason")

    invariants = manifest.get("invariants") or {}
    for key, value in invariants.items():
        if value is not True:
            errors.append(f"manifest invariant {key!r} is not true")

    dataset = load_gold_dataset(cases_path)
    if manifest.get("dataset") != benchmark_dataset_snapshot(dataset):
        errors.append("manifest dataset identity does not match the committed dataset")
    artifacts = manifest.get("artifacts") or {}
    if artifacts.get("runs_sha256") != _sha256(runs_path):
        errors.append("manifest runs_sha256 does not match the runs file")
    if artifacts.get("report_sha256") != _sha256(report_path):
        errors.append("manifest report_sha256 does not match the report file")
    if manifest.get("manifest_sha256") != _manifest_hash(manifest):
        errors.append("manifest_sha256 does not reproduce")

    versions = manifest.get("versions") or {}
    for key in (
        "prompt_version",
        "compact_prompt_version",
        "planner_version",
        "evaluator_version",
        "benchmark_runner_version",
    ):
        if not isinstance(versions.get(key), str) or not versions.get(key):
            errors.append(f"versions.{key} is required")
    comparison = manifest.get("comparison") or {}
    for key in ("v0_10_full", "v0_11_subset", "v0_12_full"):
        if not isinstance(comparison.get(key), dict):
            errors.append(f"comparison.{key} is missing")
    governance = manifest.get("governance") or {}
    if governance.get("at07_status") != "partial":
        errors.append("governance.at07_status must stay partial")
    if governance.get("second_human_annotator") is not False:
        errors.append("governance.second_human_annotator must be false")
    report = _load_json(report_path)
    report_counters = report.get("counters") or {}
    if report_counters.get("planned_runs") not in (None, counters.get("planned_runs")):
        errors.append("report counters do not match the manifest")
    return errors


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--v010", type=Path, default=DEFAULT_V010)
    parser.add_argument("--v011", type=Path, default=DEFAULT_V011)
    parser.add_argument(
        "--run-commit",
        default=None,
        help="commit SHA the benchmark generation code ran from (default: current HEAD)",
    )
    parser.add_argument(
        "--dirty-paths",
        default="",
        help="comma-separated paths dirty at benchmark time (recorded, not hidden)",
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--write", action="store_true", help="build and write the manifest")
    action.add_argument("--check", action="store_true", help="verify the committed manifest")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not args.write and not args.check:
        args.check = True
    dirty_paths = [item.strip() for item in args.dirty_paths.split(",") if item.strip()]
    if args.write:
        manifest = build_manifest(
            runs_path=args.runs,
            report_path=args.report,
            cases_path=args.cases,
            v010_path=args.v010,
            v011_path=args.v011,
            run_commit=args.run_commit,
            dirty_paths=dirty_paths,
        )
        errors = validate_manifest(
            manifest, runs_path=args.runs, report_path=args.report, cases_path=args.cases
        )
        if errors:
            print("refusing to write an inconsistent manifest:", file=sys.stderr)
            for error in errors:
                print(f"  - {error}", file=sys.stderr)
            return 1
        _write_json(args.output, manifest)
        print(
            f"wrote {args.output}: {manifest['counters']['planned_runs']} runs, "
            f"{manifest['counters']['completed_runs']} completed, "
            f"{manifest['counters']['technical_failures']} technical, "
            f"{manifest['counters']['skipped_runs']} skipped"
        )
        return 0
    try:
        manifest = json.loads(args.output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read manifest {args.output}: {exc}", file=sys.stderr)
        return 1
    errors = validate_manifest(
        manifest, runs_path=args.runs, report_path=args.report, cases_path=args.cases
    )
    payload = {
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "manifest": str(args.output),
        "counters": manifest.get("counters") if isinstance(manifest, dict) else None,
        "dataset": manifest.get("dataset") if isinstance(manifest, dict) else None,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    elif errors:
        print(f"benchmark manifest is invalid ({len(errors)} problem(s)):", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
    else:
        counters = payload["counters"] or {}
        print(
            "benchmark manifest ok: "
            f"{counters.get('planned_runs')} planned, "
            f"{counters.get('completed_runs')} completed, "
            f"{counters.get('technical_failures')} technical, "
            f"{counters.get('skipped_runs')} skipped"
        )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
