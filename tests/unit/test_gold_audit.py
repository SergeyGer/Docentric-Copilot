"""Tests for the v0.12 gold dataset audit trail and its consistency checker."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from benchmarks.gold_audit import (
    DEFAULT_CASES,
    DEFAULT_LOG,
    DEFAULT_MANIFEST,
    DEFAULT_REPORT,
    benchmark_dataset_snapshot,
    canonical_sha256,
    case_snapshot,
    check_all,
    main,
    manifest_sha256,
    render_report,
)
from benchmarks.gold_dataset import load_gold_dataset
from benchmarks.versions import (
    COMPACT_PROMPT_VERSION,
    FULL_PROMPT_VERSION,
    PLANNER_VERSION,
)
from docentric_copilot.planner import COMPACT_V2_GENERATOR, PROMPT_VERSION

ROOT = Path(__file__).resolve().parent.parent.parent


def _dataset():
    return load_gold_dataset(DEFAULT_CASES)


def _load_audit():
    return json.loads(DEFAULT_LOG.read_text(encoding="utf-8"))


def _load_manifest():
    return json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))


def _report_text(log, manifest):
    return render_report(_dataset(), log, manifest)


def _errors(log, manifest, report=None):
    return check_all(
        _dataset(),
        log,
        manifest,
        _report_text(log, manifest) if report is None else report,
        log_path=DEFAULT_LOG,
    )


def test_committed_audit_trail_passes_every_check() -> None:
    log = _load_audit()
    manifest = _load_manifest()
    report = DEFAULT_REPORT.read_text(encoding="utf-8")
    assert _errors(log, manifest, report) == []


def test_committed_trail_covers_all_32_cases() -> None:
    log = _load_audit()
    dataset = _dataset()
    assert [entry["case_id"] for entry in log["entries"]] == [case["id"] for case in dataset.cases]
    assert log["summary"]["cases"] == 32
    assert log["summary"]["requirements_audited"] == 98
    assert log["summary"]["unresolved"] == 0
    assert log["reviewer"]["independent_human_review"] is False
    assert log["reviewer"]["second_human_annotator"] is False
    assert log["reviewer"]["at07_status"] == "partial"


def test_dataset_and_manifest_hashes_are_pinned_and_reproducible() -> None:
    dataset = _dataset()
    manifest = _load_manifest()
    assert manifest["dataset"]["sha256"] == dataset.file_sha256
    assert manifest["dataset"]["canonical_sha256"] == dataset.canonical_sha256
    assert manifest["dataset"]["canonical_sha256"] == (
        "a36cf286c0c8cad59a4e770927488f6d5a931d2d2423740277d5c7a3c77943ed"
    )
    assert manifest["dataset"]["sha256"] == (
        "8489e4c07f9a8c87e76c0e7fa4a7da8c7f9d6ec0ca0b04eb36cfcd4fe003fd4b"
    )
    assert manifest["manifest_sha256"] == manifest_sha256(manifest)


def test_hash_changes_with_data_and_is_stable_for_unchanged_data(tmp_path) -> None:
    dataset = _dataset()
    first = case_snapshot(dataset.cases[0])
    second = case_snapshot(copy.deepcopy(dataset.cases[0]))
    assert canonical_sha256(first) == canonical_sha256(second)

    document = json.loads(DEFAULT_CASES.read_text(encoding="utf-8"))
    document["cases"][0]["prompt"] = document["cases"][0]["prompt"] + " Changed."
    changed = tmp_path / "gold_cases.json"
    changed.write_text(json.dumps(document), encoding="utf-8")
    changed_dataset = load_gold_dataset(changed)
    assert changed_dataset.file_sha256 != dataset.file_sha256
    assert changed_dataset.canonical_sha256 != dataset.canonical_sha256


def test_missing_case_entry_is_detected() -> None:
    log = _load_audit()
    log["entries"].pop(0)
    errors = _errors(log, _load_manifest())
    assert any("missing case id" in error for error in errors)
    assert any("coverage" in error for error in errors)


def test_expected_forbidden_conflict_is_detected() -> None:
    log = _load_audit()
    entry = next(item for item in log["entries"] if item["case_id"] == "po-flat-vendor-identity")
    for side in ("before", "after"):
        entry[side]["expected_paths"] = sorted(
            [*entry[side]["expected_paths"], *entry[side]["forbidden_paths"]]
        )
    errors = _errors(log, _load_manifest())
    assert any("expected/forbidden conflict" in error for error in errors)


def test_change_without_rationale_is_detected() -> None:
    log = _load_audit()
    entry = next(item for item in log["entries"] if item["change_type"] == "clarification")
    entry["rationale"] = ""
    errors = _errors(log, _load_manifest())
    assert any("rationale is required" in error for error in errors)


def test_short_or_placeholder_rationale_is_detected() -> None:
    log = _load_audit()
    log["entries"][0]["rationale"] = "TBD"
    errors = _errors(log, _load_manifest())
    assert any("placeholder" in error or "shorter" in error for error in errors)


def test_clarification_with_label_difference_is_detected() -> None:
    log = _load_audit()
    entry = next(item for item in log["entries"] if item["change_type"] == "clarification")
    entry["after"] = copy.deepcopy(entry["after"])
    case = next(case for case in _dataset().cases if case["id"] == entry["case_id"])
    valid_path = next(iter(case_snapshot(case)["expected_paths"]))
    entry["after"]["expected_paths"] = sorted(
        {*entry["after"]["expected_paths"], valid_path + "-extra"}
    )
    errors = _errors(log, _load_manifest())
    assert any("must keep before == after" in error for error in errors)


def test_label_correction_requires_a_real_diff() -> None:
    log = _load_audit()
    log["entries"][0]["change_type"] = "label_correction"
    errors = _errors(log, _load_manifest())
    assert any("must record a before/after diff" in error for error in errors)


def test_invalid_timestamp_and_status_are_detected() -> None:
    log = _load_audit()
    log["entries"][0]["timestamp"] = "2026-11-06T00:00:00"
    log["entries"][1]["audit_status"] = "looks_fine"
    errors = _errors(log, _load_manifest())
    assert any("UTC offset" in error for error in errors)
    assert any("invalid audit_status" in error for error in errors)


def test_fake_independent_review_is_rejected() -> None:
    log = _load_audit()
    log["reviewer"]["independent_human_review"] = True
    log["reviewer"]["second_human_annotator"] = True
    errors = _errors(log, _load_manifest())
    assert any("independent_human_review must be false" in error for error in errors)
    assert any("second_human_annotator must be false" in error for error in errors)


def test_manifest_tampering_is_detected() -> None:
    manifest = _load_manifest()
    manifest["manifest_sha256"] = "0" * 64
    errors = _errors(_load_audit(), manifest)
    assert any("manifest_sha256 does not reproduce" in error for error in errors)

    manifest = _load_manifest()
    manifest["audit"]["sha256"] = "0" * 64
    errors = _errors(_load_audit(), manifest)
    assert any("audit sha256 does not match" in error for error in errors)


def test_report_drift_is_detected() -> None:
    log = _load_audit()
    manifest = _load_manifest()
    report = _report_text(log, manifest) + "\nextra line\n"
    errors = _errors(log, manifest, report)
    assert any("does not match the generated report" in error for error in errors)


def test_after_snapshot_must_match_the_committed_labels() -> None:
    log = _load_audit()
    entry = next(item for item in log["entries"] if item["case_id"] == "po-flat-order-identity")
    for side in ("before", "after"):
        entry[side] = copy.deepcopy(entry[side])
        entry[side]["expected_paths"] = entry[side]["expected_paths"][:-1]
    errors = _errors(log, _load_manifest())
    assert any("does not match the committed labels" in error for error in errors)


def test_unknown_path_is_detected() -> None:
    log = _load_audit()
    entry = log["entries"][0]
    entry["after"] = copy.deepcopy(entry["after"])
    entry["after"]["expected_paths"] = sorted(
        [*entry["after"]["expected_paths"], "MainData.NotAField"]
    )
    errors = _errors(log, _load_manifest())
    assert any("is not in the DDSP schema" in error for error in errors)


def test_summary_drift_is_detected() -> None:
    log = _load_audit()
    log["summary"]["clarifications"] += 1
    errors = _errors(log, _load_manifest())
    assert any("summary does not match" in error for error in errors)


def test_versions_are_imported_from_the_product_code() -> None:
    assert FULL_PROMPT_VERSION == PROMPT_VERSION == "planner-v1"
    assert COMPACT_PROMPT_VERSION == COMPACT_V2_GENERATOR == "compact-ir-v2"
    assert PLANNER_VERSION == "0.13.0"


def test_seed_and_check_round_trip(tmp_path) -> None:
    log_path = tmp_path / "log.json"
    manifest_path = tmp_path / "manifest.json"
    report_path = tmp_path / "GOLD_AUDIT.md"
    arguments = [
        "--seed",
        "--log",
        str(log_path),
        "--manifest",
        str(manifest_path),
        "--report",
        str(report_path),
    ]
    assert main(arguments) == 0
    assert log_path.exists() and manifest_path.exists() and report_path.exists()
    check = [
        "--check",
        "--log",
        str(log_path),
        "--manifest",
        str(manifest_path),
        "--report",
        str(report_path),
    ]
    assert main(check) == 0
    assert main(arguments) == 2  # refuses to overwrite without --force


def test_report_names_every_case_and_the_limitation() -> None:
    report = DEFAULT_REPORT.read_text(encoding="utf-8")
    dataset = _dataset()
    for case in dataset.cases:
        assert f"`{case['id']}`" in report
    assert "independent human reviewer was involved" in report.casefold()
    assert "not performed" in report.casefold()
    assert "AT-07 remains **partial**" in report
    assert "Docentric AX runtime compatibility remains **not_tested**" in report


def test_benchmark_snapshot_is_public_safe() -> None:
    snapshot = benchmark_dataset_snapshot(_dataset())
    assert snapshot["version"] == "2.0.0"
    assert snapshot["case_count"] == 32
    assert set(snapshot) == {"version", "schema", "sha256", "canonical_sha256", "case_count"}
    assert "corpus" not in json.dumps(snapshot)
