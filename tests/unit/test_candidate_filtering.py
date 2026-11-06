"""v0.11 semantic-precision tests: decomposition, candidate filtering, abstention.

These tests use synthetic schemas shaped like the v0.10 failure modes: a
plausible-but-wrong field (bank name for a customer name), a forbidden party
scope (company name for a customer), a genuinely ambiguous party attribute
(customer vs company VAT) and a missing concept the schema cannot express.
They exercise the deterministic pre-filter and post-validation directly; no
provider is called.
"""

from __future__ import annotations

from pathlib import Path

from docentric_copilot.ddsp_parser.models import NormalizedSchema, SchemaNode, SchemaSection
from docentric_copilot.planner import build_mapping_report, build_messages
from docentric_copilot.planner.candidates import (
    MAX_CANDIDATES,
    retrieve_candidates,
)
from docentric_copilot.planner.service import review_bindings
from docentric_copilot.template_ir import (
    Document,
    DocumentMetadata,
    FieldBinding,
    Paragraph,
    Section,
    TextRun,
)


def _node(
    name: str, path: str, data_type: str, *, collection: bool = False, children=None
) -> SchemaNode:
    return SchemaNode(
        name=name,
        path=path,
        data_type=data_type,
        collection=collection,
        children=children or [],
    )


def _schema(*, extra_line_fields: int = 0) -> NormalizedSchema:
    customer = _node(
        "Customer",
        "MainData.Customer",
        "object",
        children=[
            _node("Name", "MainData.Customer.Name", "string"),
            _node("VatNumber", "MainData.Customer.VatNumber", "string"),
            _node("AccountNum", "MainData.Customer.AccountNum", "string"),
        ],
    )
    company = _node(
        "Company",
        "MainData.Company",
        "object",
        children=[
            _node("Name", "MainData.Company.Name", "string"),
            _node("VatNumber", "MainData.Company.VatNumber", "string"),
            _node("Logo", "MainData.Company.Logo", "image"),
        ],
    )
    bank = _node(
        "BankDetails",
        "MainData.BankDetails",
        "object",
        children=[
            _node("BankName", "MainData.BankDetails.BankName", "string"),
            _node("Iban", "MainData.BankDetails.Iban", "string"),
        ],
    )
    line_children = [
        _node("ItemId", "MainData.Lines.Line.ItemId", "string"),
        _node("Description", "MainData.Lines.Line.Description", "string"),
        _node("Quantity", "MainData.Lines.Line.Quantity", "number"),
        _node("LineAmount", "MainData.Lines.Line.LineAmount", "number"),
        _node("Warehouse", "MainData.Lines.Line.Warehouse", "string"),
        _node("ProductImage", "MainData.Lines.Line.ProductImage", "image"),
    ]
    for index in range(extra_line_fields):
        line_children.append(
            _node(
                f"Extra{index:03d}",
                f"MainData.Lines.Line.Extra{index:03d}",
                "string",
            )
        )
    lines = _node(
        "Lines",
        "MainData.Lines",
        "object",
        children=[
            _node(
                "Line",
                "MainData.Lines.Line",
                "collection",
                collection=True,
                children=line_children,
            )
        ],
    )
    return NormalizedSchema(
        schema_id="synthetic",
        sections=[SchemaSection(name="MainData", nodes=[customer, company, bank, lines])],
    )


def _document(*paths: str) -> Document:
    runs = [TextRun(text="Static body text.")] + [FieldBinding(path=path) for path in paths]
    return Document(
        title="Synthetic",
        metadata=DocumentMetadata(
            template_name="Synthetic candidate test",
            source_schema_id="synthetic",
        ),
        sections=[Section(name="Main", body=[Paragraph(runs=runs)])],
    )


def test_bank_name_is_not_a_candidate_for_a_customer_name() -> None:
    candidates = retrieve_candidates(_schema(), "Show the customer name.")
    paths = set(candidates.paths)
    assert "MainData.Customer.Name" in paths
    assert "MainData.Company.Name" not in paths
    assert "MainData.BankDetails.BankName" not in paths


def test_forbidden_company_scope_is_not_a_candidate() -> None:
    candidates = retrieve_candidates(
        _schema(),
        "Create a sales order header with the customer name; do not use the company name as the customer.",
    )
    assert "MainData.Customer.Name" in candidates.paths
    assert "MainData.Company.Name" not in candidates.paths
    rendered = candidates.format_prompt()
    assert "MainData.Customer.Name" in rendered
    assert "MainData.Company.Name" not in rendered


def test_customer_bank_iban_is_unsatisfiable_and_not_substituted() -> None:
    candidates = retrieve_candidates(
        _schema(), "Show the customer's bank account IBAN so the customer can pay us."
    )
    assert candidates.missing_atoms()
    assert "MainData.BankDetails.Iban" not in candidates.paths
    assert "NO SUPPORTED BINDING" in candidates.format_prompt()


def test_ambiguous_vat_is_marked_needs_review() -> None:
    schema = _schema()
    candidates = retrieve_candidates(schema, "Show the VAT number.")
    assert candidates.ambiguous_atoms()
    assert set(candidates.paths) == {
        "MainData.Customer.VatNumber",
        "MainData.Company.VatNumber",
    }
    assert "AMBIGUOUS" in candidates.format_prompt()
    document = _document("MainData.Customer.VatNumber")
    report = build_mapping_report(
        schema,
        document,
        "Show the VAT number.",
        candidate_set=candidates,
    )
    review_rows = [mapping for mapping in report.mappings if mapping.status.value == "needs_review"]
    assert review_rows
    assert any("ambigu" in row.explanation.casefold() for row in review_rows)
    assert not report.blocking() or review_rows


def test_missing_requirement_abstains_without_a_guessed_path() -> None:
    schema = _schema()
    candidates = retrieve_candidates(schema, "Show the internal purchase requisition number.")
    assert candidates.missing_atoms()
    assert "NO SUPPORTED BINDING" in candidates.format_prompt()
    report = build_mapping_report(
        schema,
        _document(),
        "Show the internal purchase requisition number.",
        candidate_set=candidates,
    )
    abstentions = [
        mapping
        for mapping in report.mappings
        if mapping.status.value == "needs_review" and mapping.selected_field_path is None
    ]
    assert abstentions
    assert any("abstained" in row.explanation for row in abstentions)


def test_post_validation_flags_a_schema_valid_but_unsupported_path() -> None:
    schema = _schema()
    candidates = retrieve_candidates(schema, "Show the customer name.")
    reviews = review_bindings(
        _document("MainData.Customer.Name", "MainData.Company.Name"), schema, candidates
    )
    by_path = {review.path: review for review in reviews}
    assert by_path["MainData.Customer.Name"].status == "accepted"
    assert by_path["MainData.Company.Name"].status == "needs_review"
    assert "not supported" in by_path["MainData.Company.Name"].reason


def test_candidate_list_is_bounded_and_deterministic() -> None:
    schema = _schema(extra_line_fields=80)
    prompt = "Create a line table with item number and description for every line."
    first = retrieve_candidates(schema, prompt)
    second = retrieve_candidates(schema, prompt)
    assert len(first.candidates) <= MAX_CANDIDATES
    assert first.paths == second.paths
    assert [item.score for item in first.candidates] == [item.score for item in second.candidates]
    assert "MainData.Lines.Line.ItemId" in first.paths
    assert "MainData.Lines.Line.Description" in first.paths


def test_candidate_prompt_replaces_the_full_schema_and_states_the_constraint() -> None:
    schema = _schema()
    candidates = retrieve_candidates(schema, "Show the customer name.")
    messages = build_messages(
        schema, "Show the customer name.", candidates=candidates.format_prompt()
    )
    system, user = messages
    assert "candidate-mode rules" in system.content.casefold()
    assert "<candidate_bindings>" in user.content
    assert "<schema>" not in user.content
    assert "MainData.Customer.Name" in user.content
    assert "MainData.BankDetails.BankName" not in user.content


def test_candidate_evidence_does_not_mutate_the_dataset() -> None:
    dataset_path = Path("benchmarks/gold_cases.json")
    before = dataset_path.read_text(encoding="utf-8")
    retrieve_candidates(_schema(), "Show the customer name.")
    after = dataset_path.read_text(encoding="utf-8")
    assert before == after


def test_collection_scope_is_not_an_abstention() -> None:
    schema = _schema()
    prompt = "Create a line table with item number and description for every line."
    candidates = retrieve_candidates(schema, prompt)
    report = build_mapping_report(
        schema,
        _document("MainData.Lines.Line.ItemId", "MainData.Lines.Line.Description"),
        prompt,
        candidate_set=candidates,
    )
    false_abstentions = [
        mapping
        for mapping in report.mappings
        if mapping.status.value == "needs_review" and mapping.selected_field_path is None
    ]
    assert false_abstentions == []


def test_product_image_candidate_is_scoped_to_the_line_collection() -> None:
    candidates = retrieve_candidates(
        _schema(), "Add the product image for each line item in the table."
    )
    paths = set(candidates.paths)
    assert "MainData.Lines.Line.ProductImage" in paths
    assert "MainData.Company.Logo" not in paths


def test_company_logo_does_not_become_a_product_image() -> None:
    candidates = retrieve_candidates(_schema(), "Show the company logo in the first-page header.")
    paths = set(candidates.paths)
    assert "MainData.Company.Logo" in paths
    assert "MainData.Lines.Line.ProductImage" not in paths
