"""Synthetic tests for the REF-05 reference-based evaluation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from benchmarks.reference_evaluation import derive_reference_concepts, main
from benchmarks.reference_fixtures import CASES, build_all
from docentric_copilot.reference import build_reference_graph, inspect_reference_bundle

from tests.reference_fixtures import build_zip


def _run(tmp_path: Path, *args: str) -> tuple[int, Path]:
    output = tmp_path / "reference-report.json"
    code = main(
        [
            *args,
            "--output-json",
            str(output),
            "--output-csv",
            str(tmp_path / "reference-report.csv"),
            "--output-html",
            str(tmp_path / "reference-report.html"),
        ]
    )
    return code, output


def test_synthetic_cases_report_is_separate_and_self_describing(tmp_path: Path, capsys) -> None:
    code, output = _run(tmp_path, "--limit", "3", "--provider", "mock")
    assert code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema"] == "reference-evaluation/v1"
    assert report["mode"] == "cases"
    assert report["provenance"]["kind"] == "synthetic"
    assert report["provenance"]["committed"] is True
    assert report["provenance"]["corpus_content_included"] is False
    assert report["dataset"]["case_count"] == 3
    assert report["sample_size"]["cases"] == 3
    assert report["sample_size"]["completed_runs"] == 3
    assert report["metrics"]["valid_template_rate"] == 1.0
    assert report["valid_template_rate"] == 1.0
    assert report["valid_templates"]["rate"] == 1.0
    assert "separately" in report["valid_templates"]["note"].casefold()
    assert report["metrics"]["precision"] is not None
    assert report["metrics"]["recall"] is not None
    assert report["metrics"]["coverage"] is not None
    assert report["metrics"]["type_context_correctness"] is not None
    assert report["cost"]["status"] == "verified"
    assert report["cost"]["paid_calls"] is False
    assert report["cost"]["total_usd"] == 0.0
    assert report["error_taxonomy"]
    assert report["notes"]
    assert all(case["consistency"]["matches"] for case in report["per_case"])
    csv_text = (tmp_path / "reference-report.csv").read_text(encoding="utf-8")
    assert csv_text.startswith("scope,case_id,provider")
    page = (tmp_path / "reference-report.html").read_text(encoding="utf-8")
    assert "Reference-based evaluation" in page
    assert "reported separately" in page.casefold()
    captured = capsys.readouterr()
    assert "reference evaluation" in captured.out


def test_reference_mode_derives_patterns_and_keeps_corpus_paths_private(
    tmp_path: Path,
) -> None:
    fixture = Path("benchmarks/fixtures/reference/ref-mixed-invoice.docx")
    schema = Path("benchmarks/fixtures/reference/ref-mixed-invoice.ddsp")
    code, output = _run(
        tmp_path,
        "--reference",
        str(fixture),
        "--ddsp",
        str(schema),
        "--provider",
        "mock",
    )
    assert code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["mode"] == "reference"
    assert report["provenance"]["kind"] == "local-corpus"
    assert report["provenance"]["committed"] is False
    assert report["provenance"]["corpus_content_included"] is False
    assert report["sample_size"]["reference_concepts"] >= 10
    assert {item["concept"] for item in report["per_case"][0]["runs"][0]["score"]["concepts"]} >= {
        "scalar",
        "collection",
        "condition",
        "image",
        "text",
    }
    serialized = json.dumps(report)
    assert str(Path.cwd()) not in serialized
    assert "/root/" not in serialized
    assert "/home/" not in serialized


def test_reference_zip_uses_embedded_ddsp_schema(tmp_path: Path) -> None:
    reference = Path("benchmarks/fixtures/reference/ref-mixed-invoice.docx")
    schema = Path("benchmarks/fixtures/reference/ref-mixed-invoice.ddsp")
    archive = tmp_path / "reference.zip"
    archive.write_bytes(
        build_zip(
            {
                "Template.docx": reference.read_bytes(),
                "Template.ddsp": schema.read_bytes(),
            }
        )
    )
    code, output = _run(tmp_path, "--reference", str(archive), "--provider", "mock")
    assert code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["sample_size"]["reference_concepts"] >= 10
    assert report["dataset"]["path_normalization"]["applied"] is False
    assert report["provenance"]["kind"] == "local-corpus"


def test_reference_mode_requires_a_plan_or_schema(tmp_path: Path) -> None:
    fixture = Path("benchmarks/fixtures/reference/ref-field-scalar.docx")
    code, _output = _run(tmp_path, "--reference", str(fixture), "--provider", "mock")
    assert code == 1


def test_all_committed_case_fixtures_match_the_builder() -> None:
    for relative, content in build_all().items():
        target = Path(relative)
        assert target.exists(), relative
        assert target.read_bytes() == content, relative


def test_expected_concepts_are_derived_from_each_synthetic_reference() -> None:
    for case in CASES:
        bundle = inspect_reference_bundle(
            case.reference_file,
            ddsp_path=case.schema_file,
        )
        graph = build_reference_graph(bundle.report, bundle.schemas)
        derived = derive_reference_concepts(graph)
        expected_ids = {f"{concept.concept}:{concept.path}" for concept in case.concepts}
        derived_ids = {concept.identifier for concept in derived.concepts}
        assert expected_ids == derived_ids, case.case_id


def test_live_provider_requires_explicit_paid_opt_in() -> None:
    with pytest.raises(SystemExit):
        main(["--provider", "openai"])
