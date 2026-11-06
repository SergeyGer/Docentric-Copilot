"""Tests for the v0.12 full-benchmark manifest (V012-02)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from benchmarks.benchmark_manifest import (
    DEFAULT_OUTPUT,
    DEFAULT_REPORT,
    DEFAULT_RUNS,
    EXPECTED_RUNS,
    main,
    validate_manifest,
)

ROOT = Path(__file__).resolve().parent.parent.parent


def _manifest() -> dict:
    return json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))


def _errors(manifest: dict) -> list[str]:
    return validate_manifest(
        manifest,
        runs_path=DEFAULT_RUNS,
        report_path=DEFAULT_REPORT,
    )


def test_committed_manifest_is_valid() -> None:
    manifest = _manifest()
    assert _errors(manifest) == []
    assert manifest["schema"] == "gold-benchmark-manifest/v1"


def test_manifest_covers_every_logical_run_exactly_once() -> None:
    manifest = _manifest()
    runs = manifest["runs"]
    assert len(runs) == EXPECTED_RUNS == 288
    assert len({run["run_id"] for run in runs}) == 288
    combos = {(run["case_id"], run["provider"], run["repeat_index"]) for run in runs}
    assert len(combos) == 288
    assert len({run["case_id"] for run in runs}) == 32
    assert {run["provider"] for run in runs} == {"openai", "anthropic", "gemini"}
    for provider in ("openai", "anthropic", "gemini"):
        assert sum(1 for run in runs if run["provider"] == provider) == 96


def test_counters_match_the_report_and_are_explained() -> None:
    manifest = _manifest()
    counters = manifest["counters"]
    assert counters["planned_runs"] == 288
    assert counters["completed_runs"] == 284
    assert counters["technical_failures"] == 4
    assert counters["skipped_runs"] == 0
    assert counters["valid_template_runs"] == 283
    assert counters["semantic_pass_runs"] == 277
    assert counters["correct_runs"] == 276
    assert counters["semantic_failures"] == 7
    assert counters["completed_runs"] + counters["technical_failures"] == 288
    assert all(manifest["invariants"].values())
    assert manifest["aggregate"]["semantic_pass_rate"] == 0.975352
    assert manifest["aggregate"]["valid_template_rate"] == 0.996479
    technical = [run for run in manifest["runs"] if run["status"] == "technical_failure"]
    assert len(technical) == 4
    assert {run["technical_reason"] for run in technical} == {"structured_output"}
    assert all(run["retries"] >= 0 for run in manifest["runs"])


def test_manifest_pins_versions_dataset_and_comparison() -> None:
    manifest = _manifest()
    assert manifest["dataset"]["version"] == "2.0.0"
    assert manifest["dataset"]["sha256"] == (
        "8489e4c07f9a8c87e76c0e7fa4a7da8c7f9d6ec0ca0b04eb36cfcd4fe003fd4b"
    )
    assert manifest["versions"]["prompt_version"] == "planner-v1"
    assert manifest["versions"]["compact_prompt_version"] == "compact-ir-v2"
    assert manifest["versions"]["evaluator_version"] == "1.0.1"
    assert manifest["versions"]["app_commit"] == ("05bb71325e10720b3c47822e1dec31610edeab02")
    assert manifest["versions"]["working_tree_dirty"] is True
    assert manifest["versions"]["dirty_paths"] == [
        "benchmarks/gold_evaluation.py",
        "benchmarks/versions.py",
    ]
    comparison = manifest["comparison"]
    assert comparison["v0_10_full"]["dataset_version"] == "1.0.0"
    assert comparison["v0_11_subset"]["cases"] == 12
    assert comparison["v0_11_subset"]["repeats"] == 2
    assert comparison["v0_12_full"]["cases"] == 32
    assert comparison["v0_12_full"]["repeats"] == 3
    assert len(comparison["differences"]) >= 4


def test_manifest_is_public_safe() -> None:
    text = DEFAULT_OUTPUT.read_text(encoding="utf-8")
    for marker in (
        "sk-proj",
        "sk-ant-",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "reference-corpus",
        ".tools/",
        "raw_output",
        "messages",
    ):
        assert marker not in text
    assert "Create a professional" not in text
    assert "Create a service order" not in text
    assert "Rationale" not in text


def test_missing_run_is_detected() -> None:
    manifest = _manifest()
    manifest["runs"] = manifest["runs"][:-1]
    errors = _errors(manifest)
    assert any("288" in error or "expected" in error for error in errors)


def test_duplicate_run_id_is_detected() -> None:
    manifest = _manifest()
    manifest["runs"] = copy.deepcopy(manifest["runs"])
    manifest["runs"][1]["run_id"] = manifest["runs"][0]["run_id"]
    errors = _errors(manifest)
    assert any("duplicate run ids" in error for error in errors)


def test_counter_drift_is_detected() -> None:
    manifest = _manifest()
    manifest["counters"]["completed_runs"] = 283
    errors = _errors(manifest)
    assert any("completed_runs" in error for error in errors)


def test_hash_tampering_is_detected() -> None:
    manifest = _manifest()
    manifest["artifacts"]["runs_sha256"] = "0" * 64
    errors = _errors(manifest)
    assert any("runs_sha256" in error for error in errors)

    manifest = _manifest()
    manifest["manifest_sha256"] = "0" * 64
    errors = _errors(manifest)
    assert any("manifest_sha256" in error for error in errors)


def test_skipped_run_without_reason_is_detected() -> None:
    manifest = _manifest()
    manifest["runs"] = copy.deepcopy(manifest["runs"])
    manifest["runs"][0]["status"] = "skipped"
    manifest["runs"][0]["skip_reason"] = None
    errors = _errors(manifest)
    assert any("skipped run has no explicit reason" in error for error in errors)


def test_manifest_invariants_cannot_be_flipped() -> None:
    manifest = _manifest()
    manifest["invariants"]["all_run_ids_unique"] = False
    errors = _errors(manifest)
    assert any("all_run_ids_unique" in error for error in errors)


def test_cli_check_passes(capsys) -> None:
    assert main(["--check"]) == 0
    assert "benchmark manifest ok" in capsys.readouterr().out
