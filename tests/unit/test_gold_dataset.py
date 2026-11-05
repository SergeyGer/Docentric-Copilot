"""Unit tests for the versioned gold dataset and its deterministic rule pass."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from benchmarks.gold_dataset import (
    DEFAULT_CASES,
    EXPECTED_FAMILY_COUNTS,
    EXPECTED_SPLIT_SIZES,
    GOLD_FAMILIES,
    GoldDataset,
    canonical_cases_sha256,
    cases_for_split,
    dataset_metadata,
    load_gold_dataset,
    validate_gold_dataset,
)

ROOT = Path(__file__).resolve().parent.parent.parent


def _case(case_id: str = "po-flat-order-identity") -> dict:
    dataset = load_gold_dataset(DEFAULT_CASES)
    return copy.deepcopy(next(case for case in dataset.cases if case["id"] == case_id))


def _dataset_with(cases: list[dict], *, version: str = "1.0.0") -> GoldDataset:
    return GoldDataset(
        path=DEFAULT_CASES,
        version=version,
        created_at="2026-11-05",
        cases=tuple(cases),
        document={"provenance": {}, "split_policy": ""},
    )


def test_dataset_loads_with_the_required_contract() -> None:
    dataset = load_gold_dataset(DEFAULT_CASES)
    assert dataset.version == "1.0.0"
    assert len(dataset.cases) == 32
    assert len({case["id"] for case in dataset.cases}) == 32
    assert len(dataset.canonical_sha256) == 64
    assert len(dataset.file_sha256) == 64
    assert dataset.cases == tuple(json.loads(DEFAULT_CASES.read_text(encoding="utf-8"))["cases"])


def test_dataset_passes_the_deterministic_rule_pass() -> None:
    dataset = load_gold_dataset(DEFAULT_CASES)
    assert validate_gold_dataset(dataset) == []


def test_dataset_split_and_family_composition() -> None:
    dataset = load_gold_dataset(DEFAULT_CASES)
    metadata = dataset_metadata(dataset)
    assert metadata["case_count"] == 32
    assert metadata["splits"] == EXPECTED_SPLIT_SIZES
    assert metadata["families"] == EXPECTED_FAMILY_COUNTS
    assert set(metadata["families"]) == set(GOLD_FAMILIES)
    assert len(cases_for_split(dataset, "calibration")) == 20
    assert len(cases_for_split(dataset, "holdout")) == 12
    assert len(cases_for_split(dataset, "all")) == 32


def test_every_case_has_an_explicit_family_difficulty_and_split() -> None:
    dataset = load_gold_dataset(DEFAULT_CASES)
    for case in dataset.cases:
        assert case["family"] in GOLD_FAMILIES
        assert case["family"] in case["labels"]
        assert case["difficulty"] in {"easy", "medium", "hard"}
        assert case["split"] in {"calibration", "holdout"}
        assert case["prompt"]
        assert case["package"].endswith(".ddsp")
        assert case["required_bindings"] or case["expected_blocks"]


def test_holdout_is_stratified_across_families() -> None:
    dataset = load_gold_dataset(DEFAULT_CASES)
    holdout = {case["family"] for case in cases_for_split(dataset, "holdout")}
    assert holdout == set(GOLD_FAMILIES)


def test_canonical_hash_is_independent_of_key_order() -> None:
    dataset = load_gold_dataset(DEFAULT_CASES)
    first = {"id": "a", "prompt": "one", "nested": {"b": 2, "a": 1}}
    second = {"nested": {"a": 1, "b": 2}, "prompt": "one", "id": "a"}
    assert canonical_cases_sha256([first]) == canonical_cases_sha256([second])
    assert dataset.canonical_sha256 == canonical_cases_sha256(dataset.cases)


def test_missing_path_is_rejected() -> None:
    case = _case()
    case["required_bindings"][0]["expected_paths"] = ["MainData.PurchaseOrder.NotAField"]
    errors = validate_gold_dataset(_dataset_with([case]), check_counts=False)
    assert any("NotAField" in error for error in errors)


def test_shared_expected_path_is_rejected() -> None:
    case = _case()
    case["required_bindings"][1]["expected_paths"] = ["MainData.PurchaseOrder.OrderId"]
    errors = validate_gold_dataset(_dataset_with([case]), check_counts=False)
    assert any("shared" in error for error in errors)


def test_forbidden_path_that_is_also_expected_is_rejected() -> None:
    case = _case()
    case["forbidden_paths"] = ["MainData.PurchaseOrder.OrderId"]
    errors = validate_gold_dataset(_dataset_with([case]), check_counts=False)
    assert any("forbidden" in error.lower() for error in errors)


def test_block_path_must_be_a_collection() -> None:
    case = _case("po-collection-line-items")
    case["expected_blocks"][0]["path"] = "MainData.PurchaseOrderLines.Line.ItemId"
    errors = validate_gold_dataset(_dataset_with([case]), check_counts=False)
    assert any("not a collection" in error for error in errors)


def test_image_block_path_must_be_an_image() -> None:
    case = _case("po-image-logo-header")
    case["expected_blocks"][0]["path"] = "GeneralData.Company.Name"
    errors = validate_gold_dataset(_dataset_with([case]), check_counts=False)
    assert any("not an image" in error for error in errors)


def test_family_invariants_are_enforced() -> None:
    case = _case("adv-missing-requisition-number")
    case["required_bindings"] = [
        requirement
        for requirement in case["required_bindings"]
        if requirement.get("satisfiable", True)
    ]
    errors = validate_gold_dataset(_dataset_with([case]), check_counts=False)
    assert any("unsatisfiable" in error for error in errors)


def test_invalid_split_is_rejected() -> None:
    case = _case()
    case["split"] = "development"
    errors = validate_gold_dataset(_dataset_with([case]), check_counts=False)
    assert any("invalid split" in error for error in errors)


def test_missing_package_is_reported_without_crashing() -> None:
    case = _case()
    case["package"] = "benchmarks/fixtures/does-not-exist.ddsp"
    errors = validate_gold_dataset(_dataset_with([case]), check_counts=False)
    assert any("does not exist" in error for error in errors)


def test_private_corpus_path_is_rejected() -> None:
    case = _case()
    case["package"] = ".tools/reference-corpus/case.ddsp"
    errors = validate_gold_dataset(_dataset_with([case]), check_counts=False)
    assert any("private corpus" in error for error in errors)


def test_duplicate_id_is_rejected() -> None:
    case = _case()
    errors = validate_gold_dataset(_dataset_with([case, copy.deepcopy(case)]), check_counts=False)
    assert any("duplicate case id" in error for error in errors)


def test_wrong_dataset_version_is_reported_when_counts_are_checked() -> None:
    dataset = load_gold_dataset(DEFAULT_CASES)
    errors = validate_gold_dataset(_dataset_with(list(dataset.cases), version="0.9.0"))
    assert any("dataset version" in error for error in errors)
