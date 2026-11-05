"""Unit tests for the pure semantic scorer (P0)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from benchmarks.semantic_scoring import (
    ERROR_TAXONOMY,
    ProducedBinding,
    SemanticScore,
    _type_check,
    classify_exception,
    forbidden_paths_from_case,
    requirements_from_case,
    score_run,
    taxonomy_for_validation_codes,
    validate_cases,
)
from docentric_copilot.ddsp_parser import parse_ddsp
from docentric_copilot.errors import ProviderError

ROOT = Path(__file__).resolve().parent.parent.parent
CASES = ROOT / "benchmarks" / "semantic_cases.json"


def _case(
    *,
    requirements: list[dict] | None = None,
    forbidden: list[str] | None = None,
    blocks: list[dict] | None = None,
) -> dict:
    return {
        "id": "synthetic-case",
        "prompt": "Synthetic prompt.",
        "package": "examples/quotation/sales-quotation.ddsp",
        "required_bindings": requirements
        if requirements is not None
        else [
            {
                "id": "customer_name",
                "concept": "customer_name",
                "expected_paths": ["MainData.Quotation.Customer.Name"],
                "allowed_alternatives": [],
                "required": True,
                "expected_type": "string",
                "expected_context": "body",
            }
        ],
        "forbidden_paths": forbidden or [],
        "expected_blocks": blocks or [],
        "labels": ["synthetic"],
    }


def _binding(
    path: str,
    *,
    data_type: str = "string",
    context: str = "body",
    concept: str | None = None,
    role: str = "field",
) -> ProducedBinding:
    return ProducedBinding(
        path=path,
        concept=concept,
        data_type=data_type,
        contexts=(context,),
        role=role,
    )


def _all_cases() -> list[dict]:
    return json.loads(CASES.read_text(encoding="utf-8"))


def _schema_paths() -> dict[str, str]:
    result: dict[str, str] = {}
    for case in _all_cases():
        package = ROOT / case["package"]
        parsed = parse_ddsp(package.read_bytes(), package.name)
        for path in parsed.schema.paths:
            node = parsed.schema.node(path)
            assert node is not None
            result[path] = node.data_type
    return result


def test_dataset_is_twenty_valid_cases() -> None:
    cases = _all_cases()
    assert len(cases) == 20
    assert len({case["id"] for case in cases}) == 20
    errors = validate_cases(cases, schema_paths=_schema_paths())
    assert errors == []


def test_dataset_covers_requested_families() -> None:
    labels = {label for case in _all_cases() for label in case["labels"]}
    required = {
        "fields",
        "images",
        "collections",
        "nested_lists",
        "conditions",
        "missing_requirement",
        "ambiguous",
        "multilingual",
    }
    assert required <= labels


def test_expected_path_is_true_positive() -> None:
    case = _case()
    score = score_run(
        case,
        [_binding("MainData.Quotation.Customer.Name", concept="customer_name")],
    )
    assert score.true_positives == 1
    assert score.false_positives == 0
    assert score.false_negatives == 0
    assert score.precision == 1.0
    assert score.recall == 1.0
    assert score.requirement_coverage == 1.0
    assert score.type_context_correctness == 1.0
    assert score.semantic_pass is True
    assert score.outcomes[0].matched_via == "expected"


def test_allowed_alternative_is_a_true_positive() -> None:
    case = _case(
        requirements=[
            {
                "id": "vat",
                "concept": "vat_number",
                "expected_paths": ["MainData.Quotation.Customer.VatNumber"],
                "allowed_alternatives": ["GeneralData.Company.VatNumber"],
                "required": True,
            }
        ]
    )
    score = score_run(case, [_binding("GeneralData.Company.VatNumber", concept="vat_number")])
    assert score.true_positives == 1
    assert score.recall == 1.0
    assert score.outcomes[0].matched_via == "alternative"
    assert score.semantic_pass is True


def test_two_acceptable_variants_are_not_a_false_positive() -> None:
    case = _case(
        requirements=[
            {
                "id": "vat",
                "concept": "vat_number",
                "expected_paths": ["MainData.Quotation.Customer.VatNumber"],
                "allowed_alternatives": ["GeneralData.Company.VatNumber"],
                "required": True,
            }
        ]
    )
    score = score_run(
        case,
        [
            _binding("MainData.Quotation.Customer.VatNumber", concept="vat_number"),
            _binding("GeneralData.Company.VatNumber", concept="vat_number"),
        ],
    )
    # Producing both acceptable answers is redundant, not wrong.
    assert score.true_positives == 1
    assert score.false_positives == 0
    assert score.precision == 1.0
    assert score.semantic_pass is True


def test_forbidden_path_reduces_precision_and_fails_semantics() -> None:
    case = _case(forbidden=["MainData.Quotation.BankDetails.BankName"])
    score = score_run(
        case,
        [
            _binding("MainData.Quotation.Customer.Name", concept="customer_name"),
            _binding("MainData.Quotation.BankDetails.BankName", concept="bank_name"),
        ],
    )
    assert score.true_positives == 1
    assert score.false_positives == 1
    assert score.precision == 0.5
    assert score.recall == 1.0
    assert score.forbidden_hits == ("MainData.Quotation.BankDetails.BankName",)
    assert "wrong_binding" in score.error_codes
    assert score.semantic_pass is False


def test_missing_required_binding_is_false_negative() -> None:
    case = _case()
    score = score_run(case, [])
    assert score.true_positives == 0
    assert score.false_negatives == 1
    assert score.recall == 0.0
    assert score.requirement_coverage == 0.0
    assert score.precision is None
    assert "missing_field" in score.error_codes
    assert score.semantic_pass is False


def test_wrong_context_keeps_binding_but_fails_context_metric() -> None:
    case = _case(
        requirements=[
            {
                "id": "company_name",
                "concept": "company_name",
                "expected_paths": ["GeneralData.Company.Name"],
                "allowed_alternatives": [],
                "required": True,
                "expected_type": "string",
                "expected_context": "header",
            }
        ]
    )
    score = score_run(
        case,
        [_binding("GeneralData.Company.Name", context="body", concept="company_name")],
    )
    assert score.true_positives == 1
    assert score.outcomes[0].type_ok is True
    assert score.outcomes[0].context_ok is False
    assert score.type_context_correctness == 0.5
    assert "wrong_context" in score.error_codes
    assert score.semantic_pass is False


def test_object_or_collection_used_as_scalar_counts_as_wrong_context() -> None:
    case = _case(
        requirements=[
            {
                "id": "line_description",
                "concept": "line_description",
                "expected_paths": ["MainData.QuotationLines.Line.Description"],
                "allowed_alternatives": [],
                "required": True,
                "expected_type": "string",
                "expected_context": "repeat",
            }
        ]
    )
    score = score_run(
        case,
        [
            _binding(
                "MainData.QuotationLines.Line",
                data_type="collection",
                context="body",
                concept="line_description",
            )
        ],
    )
    assert score.true_positives == 0
    assert score.false_negatives == 1
    assert score.false_positives == 1
    assert score.type_context_correctness == 0.0
    assert "wrong_context" in score.error_codes
    assert score.semantic_pass is False


def test_unsatisfiable_requirement_is_excluded_from_recall_and_coverage() -> None:
    case = _case(
        requirements=[
            {
                "id": "vendor_name",
                "concept": "vendor_name",
                "expected_paths": ["MainData.Quotation.Customer.Name"],
                "allowed_alternatives": [],
                "required": True,
            },
            {
                "id": "requisition",
                "concept": "purchase_requisition_number",
                "expected_paths": [],
                "allowed_alternatives": [],
                "required": True,
                "satisfiable": False,
            },
        ]
    )
    score = score_run(case, [_binding("MainData.Quotation.Customer.Name", concept="vendor_name")])
    assert score.unsatisfiable_requirements == 1
    assert score.required_requirements == 1
    assert score.satisfiable_requirements == 1
    assert score.recall == 1.0
    assert score.requirement_coverage == 1.0
    assert score.false_negatives == 0
    assert score.semantic_pass is True


def test_claim_for_unsatisfiable_requirement_is_wrong_binding() -> None:
    case = _case(
        requirements=[
            {
                "id": "requisition",
                "concept": "purchase_requisition_number",
                "expected_paths": [],
                "allowed_alternatives": [],
                "required": True,
                "satisfiable": False,
            }
        ]
    )
    score = score_run(
        case,
        [_binding("MainData.Quotation.QuotationId", concept="purchase_requisition_number")],
    )
    assert score.semantic_pass is False
    assert "wrong_binding" in score.error_codes
    assert score.outcomes[0].status == "unsatisfiable"
    assert score.outcomes[0].matched_path == "MainData.Quotation.QuotationId"


def test_optional_missing_requirement_affects_coverage_not_recall() -> None:
    case = _case(
        requirements=[
            {
                "id": "customer_name",
                "concept": "customer_name",
                "expected_paths": ["MainData.Quotation.Customer.Name"],
                "allowed_alternatives": [],
                "required": True,
            },
            {
                "id": "customer_address",
                "concept": "customer_address",
                "expected_paths": ["MainData.Quotation.Customer.Address"],
                "allowed_alternatives": [],
                "required": False,
            },
        ]
    )
    score = score_run(case, [_binding("MainData.Quotation.Customer.Name")])
    assert score.recall == 1.0
    assert score.requirement_coverage == 0.5
    assert score.semantic_pass is True
    assert score.outcomes[1].status == "optional_missing"


def test_duplicate_produced_paths_are_counted_once() -> None:
    case = _case()
    produced = [
        _binding("MainData.Quotation.Customer.Name", concept="customer_name"),
        _binding("MainData.Quotation.Customer.Name", data_type="string"),
    ]
    score = score_run(case, produced)
    assert score.true_positives == 1
    assert score.false_positives == 0
    assert score.precision == 1.0


def test_block_coverage_reports_missing_conditional() -> None:
    case = _case(
        requirements=[],
        blocks=[{"kind": "conditional", "required": True}],
    )
    score = score_run(case, [], produced_blocks=[])
    assert score.block_total == 1
    assert score.block_satisfied == 0
    assert score.block_coverage == 0.0
    assert "unsupported_expression" in score.error_codes
    assert score.semantic_pass is False


def test_condition_binding_is_not_a_false_positive() -> None:
    case = _case()
    score = score_run(
        case,
        [
            _binding("MainData.Quotation.Customer.Name", concept="customer_name"),
            _binding(
                "MainData.Quotation.Customer.IsEU",
                data_type="boolean",
                context="conditional",
                concept="customer_is_eu",
                role="condition",
            ),
        ],
    )
    assert score.precision == 1.0
    assert score.false_positives == 0
    assert score.semantic_pass is True


def test_validation_codes_map_to_the_shared_taxonomy() -> None:
    assert taxonomy_for_validation_codes(["V2-002"]) == ("wrong_context",)
    assert taxonomy_for_validation_codes(["V3-003", "V3-004"]) == (
        "wrong_binding",
        "wrong_context",
    )
    assert taxonomy_for_validation_codes(["V1-001"]) == ("structured_output",)


def test_provider_errors_map_to_quota_timeout_and_api() -> None:
    quota = ProviderError("slow down", details={"status": 429})
    assert classify_exception(quota)[0] == "quota"
    timeout = ProviderError("timed out", code="provider_timeout")
    assert classify_exception(timeout)[0] == "timeout"
    api = ProviderError("boom")
    assert classify_exception(api)[0] == "provider_api"


def test_taxonomy_is_the_documented_set() -> None:
    assert ERROR_TAXONOMY == (
        "provider_api",
        "quota",
        "timeout",
        "structured_output",
        "missing_field",
        "wrong_binding",
        "wrong_context",
        "unsupported_expression",
        "compilation",
        "renderer",
        "harness",
    )


def test_requirement_and_forbidden_parsing() -> None:
    requirements = requirements_from_case(
        _case(
            forbidden=[{"path": "MainData.Quotation.BankDetails.Iban"}],
        )
    )
    assert requirements[0].concept == "customer_name"
    assert forbidden_paths_from_case(
        _case(forbidden=[{"path": "MainData.Quotation.BankDetails.Iban"}])
    ) == ("MainData.Quotation.BankDetails.Iban",)


def test_invalid_case_is_rejected() -> None:
    case = _case(
        requirements=[
            {
                "id": "customer_name",
                "concept": "customer_name",
                "expected_paths": ["MainData.Quotation.Customer.Name"],
                "allowed_alternatives": [],
                "required": True,
            }
        ],
        forbidden=["MainData.Quotation.Customer.Name"],
    )
    errors = validate_cases([case], schema_paths=_schema_paths())
    assert any("forbidden" in error for error in errors)


def test_score_serializes_to_json() -> None:
    score: SemanticScore = score_run(_case(), [])
    payload = score.as_dict()
    assert json.loads(json.dumps(payload))["semantic_pass"] is False
    assert "requirements" in payload
    assert "precision" in payload


@pytest.mark.parametrize(
    ("expected", "actual", "value"),
    [
        ("string", "string", True),
        ("date", "string", True),
        ("number", "string", False),
        ("collection", "object", False),
    ],
)
def test_type_compatibility_matrix(expected: str, actual: str, value: bool) -> None:
    assert _type_check(expected, actual)[0] is value
