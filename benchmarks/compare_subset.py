#!/usr/bin/env python3
"""Add a reproducible v0.10 → v0.11 before/after block to the subset report.

The v0.10 full report is committed, so the baseline for the same 12 cases can be
read from its ``per_case`` rows without rerunning it or relying on the
git-ignored raw-run file. The baseline has three repeats; the v0.11 subset has
two. Precision/recall are ratios of summed numerators and denominators, so they
remain comparable as a per-label rate; the report states the repeat difference
and does not splice the two aggregate reports.

Usage::

    .venv/bin/python benchmarks/compare_subset.py
    .venv/bin/python benchmarks/compare_subset.py --check
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CURRENT = ROOT / "benchmarks" / "gold_report_v011_subset.json"
BASELINE = ROOT / "benchmarks" / "gold_report.json"
PROVIDERS = ("openai", "anthropic", "gemini")


def _ratio(numerator: int | float, denominator: int | float) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _baseline_rates(baseline: dict[str, Any], case_ids: set[str], provider: str) -> dict[str, Any]:
    precision_num = precision_den = recall_num = recall_den = 0
    semantic_passes = runs = 0
    for case in baseline.get("per_case") or []:
        if case.get("case_id") not in case_ids:
            continue
        metrics = (case.get("providers") or {}).get(provider, {}).get("metrics")
        if not metrics:
            continue
        precision_num += int(metrics.get("precision_numerator") or 0)
        precision_den += int(metrics.get("precision_denominator") or 0)
        recall_num += int(metrics.get("recall_numerator") or 0)
        recall_den += int(metrics.get("recall_denominator") or 0)
        semantic_passes += int(metrics.get("semantic_passes") or 0)
        runs += int(metrics.get("runs") or 0)
    return {
        "precision": _ratio(precision_num, precision_den),
        "recall": _ratio(recall_num, recall_den),
        "semantic_pass_rate": _ratio(semantic_passes, runs),
        "runs": runs,
        "image_semantic_pass_rate": _image_rate(baseline, provider),
    }


def _image_rate(report: dict[str, Any], provider: str) -> float | None:
    for family in report.get("per_family") or []:
        if family.get("family") != "images":
            continue
        for entry in family.get("providers") or []:
            if entry.get("provider") == provider:
                return (entry.get("metrics") or {}).get("semantic_pass_rate")
    return None


def _current_rates(report: dict[str, Any], provider: str) -> dict[str, Any]:
    for entry in report.get("providers") or []:
        if entry.get("provider") != provider:
            continue
        metrics = entry.get("metrics") or {}
        image_metrics = (report.get("image_family") or {}).get("providers", {}).get(provider, {})
        return {
            "precision": metrics.get("precision"),
            "recall": metrics.get("recall"),
            "semantic_pass_rate": metrics.get("semantic_pass_rate"),
            "abstention_rate": metrics.get("abstention_rate"),
            "review_rate": metrics.get("review_rate"),
            "pass_at_k": metrics.get("pass_at_k"),
            "runs": metrics.get("runs"),
            "image_semantic_pass_rate": image_metrics.get("semantic_pass_rate"),
        }
    return {}


def build_comparison(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    case_ids = {str(case["case_id"]) for case in current.get("per_case") or []}
    providers: dict[str, Any] = {}
    for provider in PROVIDERS:
        providers[provider] = {
            "before": _baseline_rates(baseline, case_ids, provider),
            "after": _current_rates(current, provider),
        }
    # Overall ratios from the current aggregate and the same baseline cases.
    before_precision_num = before_precision_den = 0
    before_recall_num = before_recall_den = 0
    before_passes = before_runs = 0
    for provider in PROVIDERS:
        # Recompute exact numerators from the baseline case rows for the overall.
        for case in baseline.get("per_case") or []:
            if case.get("case_id") not in case_ids:
                continue
            metrics = (case.get("providers") or {}).get(provider, {}).get("metrics")
            if not metrics:
                continue
            before_precision_num += int(metrics.get("precision_numerator") or 0)
            before_precision_den += int(metrics.get("precision_denominator") or 0)
            before_recall_num += int(metrics.get("recall_numerator") or 0)
            before_recall_den += int(metrics.get("recall_denominator") or 0)
            before_passes += int(metrics.get("semantic_passes") or 0)
            before_runs += int(metrics.get("runs") or 0)
    image_before_passes = 0
    image_before_runs = 0
    for family in baseline.get("per_family") or []:
        if family.get("family") != "images":
            continue
        for entry in family.get("providers") or []:
            metrics = entry.get("metrics") or {}
            image_before_passes += int(metrics.get("semantic_passes") or 0)
            image_before_runs += int(metrics.get("runs") or 0)
    image_after_passes = 0
    image_after_runs = 0
    for metrics in (current.get("image_family") or {}).get("providers", {}).values():
        image_after_passes += int(metrics.get("semantic_passes") or 0)
        image_after_runs += int(metrics.get("runs") or 0)
    overall = {
        "before": {
            "precision": _ratio(before_precision_num, before_precision_den),
            "recall": _ratio(before_recall_num, before_recall_den),
            "semantic_pass_rate": _ratio(before_passes, before_runs),
            "runs": before_runs,
            "image_semantic_pass_rate": _ratio(image_before_passes, image_before_runs),
        },
        "after": {
            "precision": current.get("aggregate", {}).get("precision"),
            "recall": current.get("aggregate", {}).get("recall"),
            "semantic_pass_rate": current.get("aggregate", {}).get("semantic_pass_rate"),
            "abstention_rate": current.get("aggregate", {}).get("abstention_rate"),
            "pass_at_k": current.get("aggregate", {}).get("pass_at_k"),
            "runs": current.get("aggregate", {}).get("runs"),
            "image_semantic_pass_rate": _ratio(image_after_passes, image_after_runs),
        },
    }
    return {
        "baseline": {
            "source": "benchmarks/gold_report.json",
            "dataset_version": "1.0.0",
            "repeats": 3,
            "case_count": len(case_ids),
            "note": (
                "The v0.10 full report is read case-by-case for the same 12 cases. The baseline "
                "has three repeats and the v0.11 subset has two; rates are label-weighted sums, "
                "not a splice of aggregate reports."
            ),
        },
        "current": {
            "source": "benchmarks/gold_report_v011_subset.json",
            "dataset_version": current.get("dataset", {}).get("version"),
            "repeats": current.get("sample_size", {}).get("repeats"),
            "case_count": len(case_ids),
        },
        "providers": providers,
        "overall": overall,
        "abstention": {
            "before": "not_measured",
            "after": current.get("aggregate", {}).get("abstention_rate"),
            "note": (
                "v0.10 had no abstention signal; needs_review/review counters were added in v0.11. "
                "The before value is therefore N/A, not 0."
            ),
        },
        "notes": [
            "Only the affected 12 cases are compared; the remaining 20 cases have no v0.11 rerun.",
            "The v0.10 prompts for cc-nested-service-tasks and cc-nested-task-effort are the old "
            "ones; the v0.11 label fixes are documented in docs/GOLD_LABELS.md.",
            "The image family scorecard is separate in both reports; the 0% → current change is "
            "the headline image-family result.",
            "These are observations on 72 runs, not statistical significance.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, default=CURRENT)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--check", action="store_true", help="fail if the comparison is stale")
    args = parser.parse_args(argv)
    current = json.loads(args.current.read_text(encoding="utf-8"))
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    comparison = build_comparison(current, baseline)
    changed = current.get("comparison") != comparison
    if args.check:
        if changed:
            print("subset comparison is out of date; run benchmarks/compare_subset.py")
            return 1
        print("subset comparison is up to date")
        return 0
    current["comparison"] = comparison
    temporary = args.current.with_suffix(args.current.suffix + ".tmp")
    temporary.write_text(
        json.dumps(current, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.current)
    print(
        f"comparison written: precision {comparison['overall']['before']['precision']} → "
        f"{comparison['overall']['after']['precision']}; "
        f"image {comparison['overall']['before']['image_semantic_pass_rate']} → "
        f"{comparison['overall']['after']['image_semantic_pass_rate']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
