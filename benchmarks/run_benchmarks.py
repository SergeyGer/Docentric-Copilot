#!/usr/bin/env python3
"""Latency benchmark for the deterministic core (NFR-03, NFR-04).

Measures parse, plan (mock provider), validate and compile latency over a fixed
fixture set and reports p50/p95. The LLM round trip is deliberately excluded from
the local processing numbers; pass ``--provider`` to measure it separately.

Usage::

    python benchmarks/run_benchmarks.py --runs 100
    python benchmarks/run_benchmarks.py --runs 20 --provider openai --model gpt-4o-mini
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "core" / "src"))

from docentric_copilot.ddsp_parser import parse_ddsp  # noqa: E402
from docentric_copilot.docx_compiler import CompileOptions, GenericDocxCompiler  # noqa: E402
from docentric_copilot.llm import LLMGateway  # noqa: E402
from docentric_copilot.planner import TemplatePlanner  # noqa: E402
from docentric_copilot.template_validator import ValidationEngine  # noqa: E402

EXAMPLES = [
    (
        "quotation",
        ROOT / "examples" / "quotation" / "sales-quotation.ddsp",
        ROOT / "examples" / "quotation" / "prompt.txt",
    ),
    (
        "invoice",
        ROOT / "examples" / "invoice" / "sales-invoice.ddsp",
        ROOT / "examples" / "invoice" / "prompt.txt",
    ),
    (
        "purchase-order",
        ROOT / "examples" / "purchase-order" / "purchase-order.ddsp",
        ROOT / "examples" / "purchase-order" / "prompt.txt",
    ),
]


@dataclass
class Stats:
    name: str
    runs: int
    min_ms: float
    mean_ms: float
    p50_ms: float
    p95_ms: float
    max_ms: float
    budget_ms: float | None = None

    @property
    def within_budget(self) -> bool | None:
        if self.budget_ms is None:
            return None
        return self.p95_ms <= self.budget_ms


def summarize(name: str, samples: list[float], budget_ms: float | None = None) -> Stats:
    ordered = sorted(samples)
    return Stats(
        name=name,
        runs=len(ordered),
        min_ms=round(min(ordered), 2),
        mean_ms=round(statistics.fmean(ordered), 2),
        p50_ms=round(_percentile(ordered, 0.50), 2),
        p95_ms=round(_percentile(ordered, 0.95), 2),
        max_ms=round(max(ordered), 2),
        budget_ms=budget_ms,
    )


def _percentile(ordered: list[float], fraction: float) -> float:
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=100)
    parser.add_argument("--provider", default="mock")
    parser.add_argument("--model", default=None)
    parser.add_argument("--output", type=Path, default=ROOT / "benchmarks" / "results.json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    planner = TemplatePlanner(LLMGateway())
    validator = ValidationEngine()
    compiler = GenericDocxCompiler()

    per_example: dict[str, dict[str, Stats]] = {}
    all_samples: dict[str, list[float]] = {}

    for name, package, prompt_file in EXAMPLES:
        payload = package.read_bytes()
        prompt = prompt_file.read_text(encoding="utf-8")
        parsed = parse_ddsp(payload, package.name)
        document = asyncio.run(
            planner.plan(parsed.schema, prompt, provider=args.provider, model=args.model)
        ).document

        timings: dict[str, list[float]] = {"parse": [], "plan": [], "validate": [], "compile": []}
        for _ in range(args.runs):
            started = time.perf_counter()
            parsed = parse_ddsp(payload, package.name)
            timings["parse"].append((time.perf_counter() - started) * 1000)

            started = time.perf_counter()
            asyncio.run(
                planner.plan(parsed.schema, prompt, provider=args.provider, model=args.model)
            )
            timings["plan"].append((time.perf_counter() - started) * 1000)

            started = time.perf_counter()
            validator.validate(document, parsed.schema, sample_data=parsed.sample_data)
            timings["validate"].append((time.perf_counter() - started) * 1000)

            started = time.perf_counter()
            compiler.compile(
                document,
                parsed.schema,
                CompileOptions(document_name=f"{name}.docx"),
                sample_data=parsed.sample_data,
            )
            timings["compile"].append((time.perf_counter() - started) * 1000)

        per_example[name] = {
            key: summarize(f"{name}.{key}", samples) for key, samples in timings.items()
        }
        for key, samples in timings.items():
            all_samples.setdefault(key, []).extend(samples)

    # Aggregates are computed over every sample of every fixture, not over the
    # per-example p95 values.
    aggregate = {
        "parse": summarize("parse", all_samples["parse"], 2000),
        "plan": summarize("plan", all_samples["plan"]),
        "validate": summarize("validate", all_samples["validate"]),
        "compile": summarize("compile", all_samples["compile"], 5000),
    }

    payload = {
        "generated_by": "benchmarks/run_benchmarks.py",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "runs_per_example": args.runs,
        "provider": args.provider,
        "model": args.model,
        "aggregate": {key: asdict(value) for key, value in aggregate.items()},
        "per_example": {
            example: {key: asdict(value) for key, value in stats.items()}
            for example, stats in per_example.items()
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"runs per example: {args.runs} · provider: {args.provider}")
        print(f"{'stage':<10}{'p50 (ms)':>10}{'p95 (ms)':>10}{'max (ms)':>10}{'budget':>10}")
        for key, stats in aggregate.items():
            budget = "-" if stats.budget_ms is None else f"{stats.budget_ms:.0f}"
            print(f"{key:<10}{stats.p50_ms:>10}{stats.p95_ms:>10}{stats.max_ms:>10}{budget:>10}")
        print(f"\nwritten to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
