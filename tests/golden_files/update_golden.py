"""Regenerate golden expectations.

Usage::

    python -m tests.golden_files.update_golden [--check]

The resulting files are reviewed and committed; the regression test never
rewrites them.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from docentric_copilot.ddsp_parser import parse_ddsp
from docentric_copilot.docx_compiler import CompileOptions, GenericDocxCompiler
from docentric_copilot.llm import LLMGateway
from docentric_copilot.planner import PlanOptions, TemplatePlanner
from docentric_copilot.template_ir import canonical_ir_json
from docentric_copilot.template_validator import ValidationEngine

from tests.golden_files.fixtures import FIXTURES, GOLDEN_ROOT, Fixture
from tests.golden_files.normalize import normalize_docx


def build_expectations(fixture: Fixture) -> dict[str, str]:
    parsed = parse_ddsp(fixture.package, f"{fixture.name}.ddsp")
    planner = TemplatePlanner(LLMGateway())
    options = PlanOptions(language=fixture.language)
    outcome = asyncio.run(
        planner.plan(parsed.schema, fixture.prompt, provider="mock", options=options)
    )
    report = ValidationEngine().validate(
        outcome.document, parsed.schema, sample_data=parsed.sample_data
    )
    compiled = GenericDocxCompiler().compile(
        outcome.document,
        parsed.schema,
        CompileOptions(document_name=f"{fixture.name}.docx"),
        sample_data=parsed.sample_data,
    )
    package_report = ValidationEngine().validate(
        outcome.document, parsed.schema, sample_data=parsed.sample_data, package=compiled.content
    )
    return {
        "schema.json": json.dumps(parsed.schema.model_dump(mode="json"), indent=2, sort_keys=True)
        + "\n",
        "ir.json": canonical_ir_json(outcome.document) + "\n",
        "mapping.json": json.dumps(
            outcome.mapping.model_dump(mode="json"), indent=2, sort_keys=True
        )
        + "\n",
        "validation.json": json.dumps(
            {
                "statuses": report.statuses(),
                "overall": report.overall,
                "findings": sorted(
                    finding.code for check in report.checks for finding in check.findings
                ),
                "package_statuses": package_report.statuses(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        "docx.json": json.dumps(normalize_docx(compiled.content), indent=2, sort_keys=True) + "\n",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if files are out of date")
    args = parser.parse_args(argv)

    failures = 0
    for name, fixture in FIXTURES.items():
        directory = GOLDEN_ROOT / name
        outputs = build_expectations(fixture)
        for filename, content in outputs.items():
            path = directory / filename
            if args.check:
                if not path.exists() or path.read_text(encoding="utf-8") != content:
                    print(f"out of date: {path.relative_to(GOLDEN_ROOT.parent.parent)}")
                    failures += 1
                continue
            directory.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            print(f"wrote {path.relative_to(GOLDEN_ROOT.parent.parent)}")
    if args.check and failures:
        print(f"{failures} golden file(s) out of date", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
