"""Tests for requirement understanding, concept matching and targeted revisions."""

from __future__ import annotations

import asyncio

import pytest
from docentric_copilot.ddsp_parser import parse_ddsp
from docentric_copilot.llm import LLMGateway
from docentric_copilot.planner import TemplatePlanner
from docentric_copilot.planner.rebind import rebind_paths
from docentric_copilot.planner.revision_ops import apply_revision
from docentric_copilot.schema_resolver import (
    Concept,
    MappingStatus,
    RequirementKind,
    parse_requirements,
    paths_for_concept,
    split_clauses,
)
from docentric_copilot.schema_resolver.concept_match import matches_kind
from docentric_copilot.template_ir import FieldBinding, load_document

from tests.conftest import EXAMPLES

BRIEF = (
    "Create a professional sales quotation with the company logo, customer details, "
    "quotation number and date, product lines with quantities and unit prices, the VAT number, "
    "bank details in the footer, and an EU VAT notice when the customer is in the EU."
)


@pytest.fixture(scope="module")
def source():
    return parse_ddsp((EXAMPLES / "quotation" / "sales-quotation.ddsp").read_bytes(), "q.ddsp")


@pytest.fixture(scope="module")
def planned(source):
    return asyncio.run(TemplatePlanner(LLMGateway()).plan(source.schema, BRIEF))


def test_requirement_parser_finds_concepts() -> None:
    parsed = parse_requirements(BRIEF)
    concepts = {item.concept for item in parsed}
    assert Concept.COMPANY_LOGO in concepts
    assert Concept.LINE_ITEMS in concepts
    assert Concept.BANK_DETAILS in concepts
    assert Concept.CUSTOMER_VAT in concepts
    bank = parsed.by_concept(Concept.BANK_DETAILS)
    assert bank is not None and bank.placement is not None


def test_split_clauses_drops_empty_fragments() -> None:
    assert split_clauses("Create a quotation.  ") == ["Create a quotation"]


def test_concept_matching_rejects_collections_and_types(source) -> None:
    schema = source.schema
    collection = schema.node("MainData.QuotationLines.Line")
    assert collection is not None
    assert matches_kind(RequirementKind.COLLECTION, collection)
    total = schema.node("MainData.Quotation.TotalAmount")
    assert total is not None
    assert not matches_kind(RequirementKind.DATE, total)


def test_paths_for_concept_uses_context(source) -> None:
    bound = {"MainData.Quotation.Customer.Name", "MainData.Quotation.BankDetails.BankName"}
    assert paths_for_concept(source.schema, Concept.CUSTOMER_NAME, bound) == [
        "MainData.Quotation.Customer.Name"
    ]


def test_mapping_reports_ambiguity(planned) -> None:
    counts = planned.mapping.counts()
    assert counts["confirmed"] >= 7
    assert counts["needs_review"] + counts["conflict"] >= 1
    review = [
        item
        for item in planned.mapping.mappings
        if item.status in {MappingStatus.NEEDS_REVIEW, MappingStatus.CONFLICT}
    ]
    assert review
    assert len(review[0].candidate_field_paths) >= 2
    assert review[0].confidence_score is not None and review[0].confidence_score < 0.9


def test_targeted_revision_operations(source, planned) -> None:
    document = planned.document
    moved = apply_revision(document, "Move the payment terms to the footer", source.schema)
    assert moved is not None and moved.operations == ["move_blocks"]
    assert moved.document.sections[0].footer

    compact = apply_revision(document, "Make the product table more compact", source.schema)
    assert compact is not None and compact.operations == ["compact_tables"]

    language = apply_revision(document, "Translate the document into German", source.schema)
    assert language is not None and language.document.language == "de"

    assert apply_revision(document, "make it nicer somehow", source.schema) is None


def test_rebind_replaces_resolved_paths(source, planned) -> None:
    updated, changed = rebind_paths(
        planned.document,
        source.schema,
        "MainData.Quotation.Customer.VatNumber",
        "GeneralData.Company.VatNumber",
    )
    assert changed >= 1
    assert "GeneralData.Company.VatNumber" in updated.model_dump_json()


def test_page_break_roundtrips() -> None:
    document = load_document(
        {
            "title": "Two pages",
            "metadata": {"template_name": "t", "source_schema_id": "s"},
            "sections": [
                {
                    "name": "Main",
                    "body": [
                        {"kind": "paragraph", "runs": [{"kind": "text", "text": "one"}]},
                        {"kind": "page_break"},
                        {"kind": "paragraph", "runs": [{"kind": "text", "text": "two"}]},
                    ],
                }
            ],
        }
    )
    assert document.sections[0].body[1].kind == "page_break"


def test_revision_falls_back_to_replanning(source, planned) -> None:
    outcome = asyncio.run(
        TemplatePlanner(LLMGateway()).revise(
            source.schema, planned.document, "Make it friendlier in tone"
        )
    )
    assert outcome.changed


@pytest.mark.parametrize(
    ("package", "prompt", "document_type"),
    [
        ("invoice/sales-invoice.ddsp", "invoice/prompt.txt", "Invoice"),
        ("purchase-order/purchase-order.ddsp", "purchase-order/prompt.txt", "PurchaseOrder"),
    ],
)
def test_company_roles_bind_their_own_field(package: str, prompt: str, document_type: str) -> None:
    """The logo must never satisfy the company address or VAT role."""
    from docentric_copilot.preview import render_preview

    source = parse_ddsp((EXAMPLES / package).read_bytes(), "x.ddsp")
    outcome = asyncio.run(
        TemplatePlanner(LLMGateway()).plan(source.schema, (EXAMPLES / prompt).read_text())
    )
    header_paths = [
        run.path
        for block in outcome.document.sections[0].header or []
        for run in getattr(block, "runs", [])
        if isinstance(run, FieldBinding)
    ]
    assert "GeneralData.Company.CompanyLogo" not in header_paths
    html = render_preview(outcome.document, source.schema, sample_data=source.sample_data).html
    assert ">iVBOR" not in html
    assert html.count('src="data:image/png;base64,') == 1
