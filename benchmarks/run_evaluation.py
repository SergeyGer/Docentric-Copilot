#!/usr/bin/env python3
"""Run the AI evaluation harness over the example fixtures (SRS 8.3).

The default provider is the deterministic ``mock`` baseline, so the numbers are
reproducible and require no credentials. Pass ``--provider``/``--model`` to
compare a real LLM against the same ground truth.

Usage::

    python benchmarks/run_evaluation.py
    python benchmarks/run_evaluation.py --provider openai --model gpt-4o-mini
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

from docentric_copilot.ddsp_parser import parse_ddsp  # noqa: E402
from docentric_copilot.docx_compiler import CompileOptions, GenericDocxCompiler  # noqa: E402
from docentric_copilot.evaluation import EvaluationCase, evaluate  # noqa: E402
from docentric_copilot.llm import LLMGateway  # noqa: E402
from docentric_copilot.planner import PlanOptions, TemplatePlanner  # noqa: E402
from docentric_copilot.planner.service import absolute_bindings  # noqa: E402
from docentric_copilot.template_validator import ValidationEngine  # noqa: E402

CASES_FILE = ROOT / "benchmarks" / "evaluation_cases.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="mock")
    parser.add_argument("--model", default=None)
    parser.add_argument("--cases", type=Path, default=CASES_FILE)
    parser.add_argument("--output", type=Path, default=ROOT / "benchmarks" / "evaluation.json")
    args = parser.parse_args(argv)

    case_definitions = json.loads(args.cases.read_text(encoding="utf-8"))
    planner = TemplatePlanner(LLMGateway())
    validator = ValidationEngine()
    compiler = GenericDocxCompiler()

    cases: list[EvaluationCase] = []
    for definition in case_definitions:
        package = ROOT / definition["package"]
        prompt = (ROOT / definition["prompt_file"]).read_text(encoding="utf-8")
        parsed = parse_ddsp(package.read_bytes(), package.name)
        outcome = asyncio.run(
            planner.plan(
                parsed.schema,
                prompt,
                provider=args.provider,
                model=args.model,
                options=PlanOptions(language=definition.get("language", "en")),
            )
        )
        report = validator.validate(outcome.document, parsed.schema, sample_data=parsed.sample_data)
        compiled = False
        if report.can_compile:
            result = compiler.compile(
                outcome.document,
                parsed.schema,
                CompileOptions(document_name=f"{definition['case_id']}.docx"),
                sample_data=parsed.sample_data,
            )
            compiled = result.success
        counts = outcome.mapping.counts()
        cases.append(
            EvaluationCase(
                case_id=definition["case_id"],
                schema_id=parsed.schema.schema_id,
                prompt=prompt.strip(),
                expected_paths=sorted(set(definition["expected_paths"])),
                actual_paths=absolute_bindings(outcome.document, parsed.schema),
                requirements=len(outcome.mapping.mappings),
                covered_requirements=counts.get("confirmed", 0) + counts.get("schema_valid", 0),
                compiled=compiled,
                clarifications=counts.get("needs_review", 0) + counts.get("conflict", 0),
                corrections=1
                if outcome.removed_bindings
                or counts.get("invalid", 0)
                or counts.get("needs_review", 0)
                else 0,
                verified_compatible=False,
                cost_usd=(
                    outcome.generation.usage.estimated_cost_usd if outcome.generation else 0.0
                ),
            )
        )

    report = evaluate(cases, provider=args.provider, model=args.model)
    payload = json.loads(report.model_dump_json())
    payload["generated_by"] = "benchmarks/run_evaluation.py"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"provider: {args.provider} · cases: {len(cases)}")
    for name, value in report.summary().items():
        print(f"  {name:<32}{value:>10}")
    print(f"\nwritten to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
