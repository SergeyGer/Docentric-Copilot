"""End-to-end test of the gold benchmark runner with the offline baseline."""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.gold_dataset import DEFAULT_CASES, load_gold_dataset
from benchmarks.gold_evaluation import main


def test_committed_v010_report_is_preserved_as_a_historical_artifact() -> None:
    """The v0.10 full report is history; the v0.11 dataset version is 2.0.0."""
    report = json.loads(Path("benchmarks/gold_report.json").read_text(encoding="utf-8"))
    dataset = load_gold_dataset(DEFAULT_CASES)
    assert report["dataset"]["version"] == "1.0.0"
    assert report["dataset"]["sha256"] == (
        "c2b1d89c70f96f14884de54792784d0dbd3ffaa71d0700d5f73c5c24e93ece30"
    )
    assert report["dataset"]["case_count"] == 32
    assert dataset.version == "2.0.0"
    assert report["sample_size"]["planned_runs"] == 288
    assert report["sample_size"]["completed_runs"] == 288
    assert report["sample_size"]["splits"] == {"calibration": 20, "holdout": 12}
    assert len(report["providers"]) == 3
    assert all(provider["metrics"]["runs"] == 96 for provider in report["providers"])
    assert report["by_split"]["calibration"][0]["metrics"]["runs"] == 60
    assert report["by_split"]["holdout"][0]["metrics"]["runs"] == 36
    assert report["budget"]["aborted"] is False
    assert report["budget"]["total_spend_usd"] <= report["budget"]["max_spend_usd"]
    assert report["cost"]["unknown_runs"] == 3
    assert report["cost"]["verified_usd"] > 0
    assert report["cost"]["estimated_usd"] >= 0

    serialized = json.dumps(report, ensure_ascii=False)
    for case in dataset.cases:
        assert case["prompt"] not in serialized
    assert "api_key" not in serialized.casefold()
    csv_text = Path("benchmarks/gold_report.csv").read_text(encoding="utf-8")
    assert "scope,split,family,category,provider,model,case_id" in csv_text
    assert "provider,all" in csv_text
    assert "split,holdout" in csv_text
    page = Path("benchmarks/gold_report.html").read_text(encoding="utf-8")
    assert "Observations, not significance" in page
    assert "http://" not in page and "https://" not in page


def test_mock_gold_report_is_written_and_self_describing(tmp_path: Path, capsys) -> None:
    json_path = tmp_path / "report.json"
    csv_path = tmp_path / "report.csv"
    html_path = tmp_path / "report.html"
    runs_path = tmp_path / "runs.jsonl"
    exit_code = main(
        [
            "--providers",
            "mock:mock-planner-v1",
            "--repeats",
            "1",
            "--limit",
            "2",
            "--split",
            "calibration",
            "--max-spend",
            "1",
            "--runs-file",
            str(runs_path),
            "--output-json",
            str(json_path),
            "--output-csv",
            str(csv_path),
            "--output-html",
            str(html_path),
        ]
    )
    assert exit_code == 0
    report = json.loads(json_path.read_text(encoding="utf-8"))
    assert report["schema"] == "gold-report/v1"
    assert report["dataset"]["version"] == "2.0.0"
    assert report["dataset"]["label_status"] == {"verified": 32}
    assert len(report["dataset"]["sha256"]) == 64
    assert report["dataset"]["case_count"] == 32
    assert report["dataset"]["splits"] == {"calibration": 20, "holdout": 12}
    assert report["split"] == "calibration"
    assert report["sample_size"]["completed_runs"] == 2
    assert report["sample_size"]["cases"] == 2
    assert report["providers"][0]["metrics"]["runs"] == 2
    assert report["providers"][0]["metrics"]["valid_template_rate"] == 1.0
    assert report["providers"][0]["status"] == "run"
    assert report["by_split"]["calibration"][0]["metrics"]["runs"] == 2
    assert report["by_split"]["holdout"][0]["metrics"]["runs"] == 0
    assert report["cost"]["status"] == "verified"
    assert report["cost"]["total_usd"] == 0.0
    assert report["budget"]["max_spend_usd"] == 1.0
    assert report["budget"]["warn_spend_usd"] == 5.0
    assert report["observations_not_significance"]
    assert report["counters"]["invariants"]["planned_equals_executed_plus_skipped"] is True
    assert report["counters"]["invariants"]["executed_equals_succeeded_plus_failed"] is True
    assert report["counters"]["pass_at_k"]["1"] is not None
    assert report["governance"]["at07_status"] == "partial"
    assert report["governance"]["second_human_annotator"] is False
    assert report["image_family"]["decision"] in {"labels_verified_no_gap", "label_gap_present"}
    assert report["family_semantic_pass"]
    assert report["leaders"]
    assert report["per_family"]
    assert report["per_case"]
    assert report["notes"]

    runs = [json.loads(line) for line in runs_path.read_text(encoding="utf-8").splitlines()]
    assert len(runs) == 2
    assert runs[0]["schema"] == "gold-run/v1"
    assert "api_key" not in runs_path.read_text(encoding="utf-8").casefold()

    csv_text = csv_path.read_text(encoding="utf-8")
    assert csv_text.startswith("scope,split,family,category,provider,model,case_id")
    assert "provider,all" in csv_text

    page = html_path.read_text(encoding="utf-8")
    assert "Observations, not significance" in page
    assert "Calibration vs holdout" in page
    assert "valid template" in page.casefold()
    assert "<table" in page
    assert "http://" not in page and "https://" not in page

    captured = capsys.readouterr()
    assert "gold evaluation" in captured.out


def test_committed_v011_subset_report_is_complete() -> None:
    report = json.loads(Path("benchmarks/gold_report_v011_subset.json").read_text(encoding="utf-8"))
    dataset = load_gold_dataset(DEFAULT_CASES)
    assert report["dataset"]["version"] == dataset.version
    assert report["dataset"]["sha256"] == dataset.canonical_sha256
    assert report["sample_size"]["cases"] == 12
    assert report["sample_size"]["planned_runs"] == 72
    assert report["sample_size"]["completed_runs"] == 72
    assert report["counters"]["planned_runs"] == 72
    assert report["counters"]["executed_runs"] + report["counters"]["skipped_runs"] == 72
    assert report["counters"]["invariants"]["executed_equals_succeeded_plus_failed"] is True
    assert report["governance"]["at07_status"] == "partial"
    assert report["image_family"]["decision"] == "labels_verified_no_gap"
    assert len(report["image_family"]["cases"]) == 3
    assert report["budget"]["max_spend_usd"] == 4.0
    assert report["budget"]["total_spend_usd"] <= 4.0
    assert set(report["family_semantic_pass"]) >= {
        "images",
        "ambiguous",
        "missing",
        "nested_lists",
        "forbidden_scope",
    }


def test_paid_repeats_reduce_only_priced_providers(tmp_path: Path) -> None:
    json_path = tmp_path / "report.json"
    runs_path = tmp_path / "runs.jsonl"
    exit_code = main(
        [
            "--providers",
            "mock:mock-planner-v1",
            "--repeats",
            "2",
            "--paid-repeats",
            "1",
            "--limit",
            "2",
            "--max-spend",
            "1",
            "--runs-file",
            str(runs_path),
            "--output-json",
            str(json_path),
            "--output-csv",
            str(tmp_path / "report.csv"),
            "--output-html",
            str(tmp_path / "report.html"),
        ]
    )
    assert exit_code == 0
    report = json.loads(json_path.read_text(encoding="utf-8"))
    assert report["sample_size"]["repeats"] == 2
    assert report["sample_size"]["paid_repeats"] == 1
    assert report["sample_size"]["repeats_per_provider"] == {"mock": 1}
    assert report["sample_size"]["completed_runs"] == 2


def test_case_ids_selects_a_single_case(tmp_path: Path) -> None:
    json_path = tmp_path / "report.json"
    exit_code = main(
        [
            "--providers",
            "mock:mock-planner-v1",
            "--repeats",
            "1",
            "--case-ids",
            "adv-missing-requisition-number",
            "--max-spend",
            "1",
            "--runs-file",
            str(tmp_path / "runs.jsonl"),
            "--output-json",
            str(json_path),
            "--output-csv",
            str(tmp_path / "report.csv"),
            "--output-html",
            str(tmp_path / "report.html"),
        ]
    )
    assert exit_code == 0
    report = json.loads(json_path.read_text(encoding="utf-8"))
    assert report["sample_size"]["cases"] == 1
    assert report["per_case"][0]["case_id"] == "adv-missing-requisition-number"
    assert report["per_case"][0]["family"] == "missing"


def test_pass_at_k_is_provider_case_grouped_and_skips_gap_runs() -> None:
    from benchmarks.gold_evaluation import _pass_at_k

    runs = [
        {"provider": "p", "case_id": "c1", "repeat": 1, "semantic_pass": False, "semantic": {}},
        {"provider": "p", "case_id": "c1", "repeat": 2, "semantic_pass": True, "semantic": {}},
        {"provider": "p", "case_id": "c2", "repeat": 1, "semantic_pass": True, "semantic": {}},
        {"provider": "p", "case_id": "c2", "repeat": 2, "semantic_pass": True, "semantic": {}},
        {
            "provider": "p",
            "case_id": "gap",
            "repeat": 1,
            "semantic_pass": False,
            "semantic": {"excluded_from_semantic": True},
        },
    ]
    assert _pass_at_k(runs, 2) == {"1": 0.5, "2": 1.0}
    # A group with fewer than k runs is not silently counted as a failure.
    short = [runs[0], runs[2]]
    assert _pass_at_k(short, 2) == {"1": 0.5, "2": None}


def _aggregate_record(
    *,
    case_id: str,
    passed: bool,
    abstained: bool = False,
    review: bool = False,
    excluded: bool = False,
) -> dict:
    semantic = {
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
        "requirement_coverage": 1.0,
        "type_context_correctness": 1.0,
        "block_coverage": 1.0,
        "semantic_pass": passed,
        "excluded_from_semantic": excluded,
        "true_positives": 1,
        "false_positives": 0,
        "false_negatives": 0,
        "matched_requirements": 1,
        "matched_required": 1,
        "required_requirements": 1,
        "satisfiable_requirements": 1,
        "unsatisfiable_requirements": 0,
        "type_context_checks": 1,
        "type_context_correct": 1,
        "block_total": 0,
        "block_satisfied": 0,
        "error_codes": [],
    }
    return {
        "ok": True,
        "provider": "p",
        "case_id": case_id,
        "repeat": 1,
        "semantic_pass": passed,
        "semantic": semantic,
        "valid_template": True,
        "correct": passed,
        "abstained": abstained,
        "review_requirements": ["req_x"] if review else [],
        "cost_status": "verified",
        "cost_usd": 0.0,
        "latency_ms": 1,
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        "validation_passed": True,
        "compiled": True,
        "error_codes": [],
        "primary_error": None,
    }


def test_aggregate_abstention_and_gap_counters() -> None:
    from benchmarks.gold_evaluation import _aggregate

    runs = [
        _aggregate_record(case_id="c1", passed=True),
        _aggregate_record(case_id="c2", passed=False, abstained=True, review=True),
        _aggregate_record(case_id="gap", passed=False, excluded=True),
    ]
    metrics = _aggregate(runs)
    assert metrics["abstained_runs"] == 1
    assert metrics["abstention_rate"] == round(1 / 3, 6)
    assert metrics["review_runs"] == 1
    assert metrics["semantic_excluded_runs"] == 1
    assert metrics["semantic_denominator"] == 2
    assert metrics["semantic_passes"] == 1
    assert metrics["succeeded_runs"] == 3
    assert metrics["failed_runs"] == 0
