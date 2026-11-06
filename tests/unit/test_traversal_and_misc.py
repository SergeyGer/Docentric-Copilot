"""Coverage for traversal helpers, canonical serialization and IR diffs."""

from __future__ import annotations

import json

import pytest
from docentric_copilot.errors import InvalidInputError
from docentric_copilot.planner.revisions import diff_documents, summarize_changes
from docentric_copilot.serialization import canonical_json
from docentric_copilot.template_ir import (
    Document,
    IRMigrationError,
    canonical_ir_json,
    dump_document,
    ir_digest,
    iter_all_bindings,
    iter_conditions,
    iter_document_blocks,
    iter_field_bindings,
    iter_image_bindings,
    iter_inline,
    iter_section_blocks,
    iter_tables,
    load_document,
    max_block_depth,
    migrate,
    pretty_ir_json,
)
from docentric_copilot.template_ir.traversal import table_cell_blocks
from docentric_copilot.template_validator import CheckStatus, Level, ValidationReport

DOCUMENT = {
    "title": "Doc",
    "metadata": {"template_name": "doc", "source_schema_id": "sales_quotation"},
    "sections": [
        {
            "name": "Main",
            "header": [{"kind": "paragraph", "runs": [{"kind": "text", "text": "head"}]}],
            "footer": [
                {
                    "kind": "paragraph",
                    "runs": [{"kind": "field", "path": "MainData.Quotation.PaymentTerms"}],
                }
            ],
            "body": [
                {
                    "kind": "repeat",
                    "path": "MainData.QuotationLines.Line",
                    "alias": "line",
                    "blocks": [
                        {
                            "kind": "paragraph",
                            "runs": [{"kind": "field", "path": "line.Description"}],
                        },
                        {
                            "kind": "conditional",
                            "condition": {
                                "operator": "equals",
                                "field": "MainData.Quotation.Customer.IsEU",
                                "value": True,
                            },
                            "then_blocks": [
                                {
                                    "kind": "paragraph",
                                    "runs": [{"kind": "text", "text": "vat"}],
                                }
                            ],
                            "else_blocks": [
                                {
                                    "kind": "paragraph",
                                    "runs": [{"kind": "text", "text": "no vat"}],
                                }
                            ],
                        },
                    ],
                },
                {
                    "kind": "table",
                    "columns": [{"header": "A"}],
                    "rows": [{"cells": [{"blocks": [{"kind": "paragraph", "runs": []}]}]}],
                    "repeat": {"path": "MainData.QuotationLines.Line", "alias": "row"},
                    "row_template": [{"blocks": [{"kind": "paragraph", "runs": []}]}],
                },
                {"kind": "image", "path": "GeneralData.Company.CompanyLogo"},
            ],
        }
    ],
}


@pytest.fixture
def document() -> Document:
    return load_document(json.loads(json.dumps(DOCUMENT)))


def test_document_walkers(document: Document) -> None:
    blocks = list(iter_document_blocks(document))
    assert len(blocks) > 8
    assert len(list(iter_section_blocks(document.sections[0]))) == len(blocks)
    assert max_block_depth(document) >= 2

    fields = [binding.path for binding in iter_field_bindings(document)]
    assert "line.Description" in fields
    assert "MainData.Quotation.PaymentTerms" in fields
    images = list(iter_image_bindings(document))
    assert images and images[0].path == "GeneralData.Company.CompanyLogo"
    assert len(list(iter_all_bindings(document))) == len(fields) + len(images)

    conditions = list(iter_conditions(document))
    assert conditions and conditions[0].field == "MainData.Quotation.Customer.IsEU"

    tables = list(iter_tables(document.sections[0].body))
    assert len(tables) == 1
    assert len(list(table_cell_blocks(tables[0]))) == 2

    paragraph = document.sections[0].header[0]
    assert list(iter_inline(paragraph)) == []


def test_pretty_and_dump(document: Document) -> None:
    payload = dump_document(document)
    assert payload["ir_version"] == "1.1"
    pretty = pretty_ir_json(document)
    assert pretty.endswith("\n")
    assert json.loads(pretty)["title"] == "Doc"
    assert canonical_json(document) == canonical_ir_json(document)


def test_migrate_current_version_is_a_noop() -> None:
    payload = {"ir_version": "1.1", "title": "x"}
    assert migrate(payload)["ir_version"] == "1.1"


def test_migrate_v1_0_adds_v1_1_defaults() -> None:
    payload = {
        "ir_version": "1.0",
        "title": "x",
        "sections": [
            {
                "name": "Main",
                "body": [
                    {
                        "kind": "image",
                        "path": "MainData.Logo",
                    }
                ],
            }
        ],
    }
    migrated = migrate(payload)
    assert migrated["ir_version"] == "1.1"
    assert migrated["sections"][0]["first_page_header"] is None
    image = migrated["sections"][0]["body"][0]
    assert image["source"] == "schema"
    assert image["static_asset"] is None
    assert image["fallback"] == "placeholder"
    assert image["preserve_aspect"] is True


def test_migrate_without_path() -> None:
    with pytest.raises(IRMigrationError):
        migrate({"ir_version": "0.9"}, "0.9")


def test_load_document_rejects_bad_json() -> None:
    with pytest.raises(InvalidInputError):
        load_document("{not json")
    with pytest.raises(InvalidInputError):
        load_document(b"\xff\xfe\x00")
    with pytest.raises(InvalidInputError):
        load_document("[1, 2, 3]")


def test_ir_digest_ignores_key_order() -> None:
    left = load_document(json.loads(json.dumps(DOCUMENT)))
    reordered = {key: DOCUMENT[key] for key in reversed(list(DOCUMENT))}
    right = load_document(json.loads(json.dumps(reordered)))
    assert ir_digest(left) == ir_digest(right)


def test_diff_detects_add_remove_change() -> None:
    before = load_document(
        {
            "title": "A",
            "metadata": {"template_name": "t", "source_schema_id": "s"},
            "sections": [
                {
                    "name": "Main",
                    "body": [{"kind": "paragraph", "runs": [{"kind": "text", "text": "one"}]}],
                }
            ],
        }
    )
    after = load_document(
        {
            "title": "B",
            "metadata": {"template_name": "t", "source_schema_id": "s"},
            "sections": [
                {
                    "name": "Main",
                    "body": [
                        {
                            "kind": "paragraph",
                            "runs": [
                                {"kind": "text", "text": "two"},
                                {"kind": "field", "path": "X.Y"},
                            ],
                        }
                    ],
                }
            ],
        }
    )
    changes = diff_documents(before, after)
    paths = {change.path for change in changes}
    assert "title" in paths
    summary = summarize_changes(changes)
    assert summary["total"] == len(changes)
    assert summary["counts"]["changed"] >= 1
    assert summary["examples"]
    assert all(set(item) == {"path", "kind", "before", "after"} for item in summary["examples"])


def test_report_level_status_edge_cases(document: Document) -> None:
    empty = ValidationReport()
    assert empty.level_status(Level.VISUAL) is CheckStatus.SKIPPED
    # Fail closed: a report with no checks must never authorise compilation.
    assert empty.can_compile is False
    assert empty.overall == "failed"
    assert empty.counts() == {"errors": 0, "warnings": 0, "checks": 0}
    assert empty.errors() == []
