"""Golden-file regression tests (SRS section 8.2).

Each fixture is parsed, planned, validated and compiled, then compared against a
reviewed expectation. Update the expectations deliberately:

    python -m tests.golden_files.update_golden

Never edit expected files by hand without reviewing the diff.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from docentric_copilot.ddsp_parser import parse_ddsp
from docentric_copilot.docx_compiler import CompileOptions, GenericDocxCompiler
from docentric_copilot.llm import LLMGateway
from docentric_copilot.planner import PlanOptions, TemplatePlanner
from docentric_copilot.template_ir import canonical_ir_json
from docentric_copilot.template_validator import ValidationEngine

from tests.golden_files.fixtures import FIXTURES, GOLDEN_ROOT
from tests.golden_files.normalize import normalize_docx


def _expected(directory, filename: str) -> str:
    path = directory / filename
    if not path.exists():
        pytest.fail(
            f"Missing golden file {path}. "
            "Run `python -m tests.golden_files.update_golden` and review the diff."
        )
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_golden_fixture(name: str) -> None:
    fixture = FIXTURES[name]
    directory = GOLDEN_ROOT / name

    parsed = parse_ddsp(fixture.package, f"{name}.ddsp")
    planner = TemplatePlanner(LLMGateway())
    outcome = asyncio.run(
        planner.plan(
            parsed.schema,
            fixture.prompt,
            provider="mock",
            options=PlanOptions(language=fixture.language),
        )
    )
    report = ValidationEngine().validate(
        outcome.document, parsed.schema, sample_data=parsed.sample_data
    )
    compiled = GenericDocxCompiler().compile(
        outcome.document,
        parsed.schema,
        CompileOptions(document_name=f"{name}.docx"),
        sample_data=parsed.sample_data,
    )
    package_report = ValidationEngine().validate(
        outcome.document, parsed.schema, sample_data=parsed.sample_data, package=compiled.content
    )

    assert json.dumps(
        parsed.schema.model_dump(mode="json"), indent=2, sort_keys=True
    ) + "\n" == _expected(directory, "schema.json"), "normalized schema changed"
    assert canonical_ir_json(outcome.document) + "\n" == _expected(directory, "ir.json"), (
        "generated IR changed"
    )
    assert json.dumps(
        outcome.mapping.model_dump(mode="json"), indent=2, sort_keys=True
    ) + "\n" == _expected(directory, "mapping.json"), "mapping report changed"

    expected_validation = json.loads(_expected(directory, "validation.json"))
    actual_validation = {
        "statuses": report.statuses(),
        "overall": report.overall,
        "findings": sorted(finding.code for check in report.checks for finding in check.findings),
        "package_statuses": package_report.statuses(),
    }
    assert actual_validation == expected_validation, "validation outcome changed"

    expected_docx = json.loads(_expected(directory, "docx.json"))
    actual_docx = normalize_docx(compiled.content)
    assert actual_docx == expected_docx, "DOCX structure changed"


def test_all_expectations_are_present() -> None:
    for name in FIXTURES:
        directory = GOLDEN_ROOT / name
        for filename in ("schema.json", "ir.json", "mapping.json", "validation.json", "docx.json"):
            assert (directory / filename).exists(), f"{name}/{filename} is missing"
