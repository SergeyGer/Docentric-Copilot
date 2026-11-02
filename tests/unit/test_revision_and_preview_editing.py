"""Coverage for the smaller structural edits and preview details."""

from __future__ import annotations

import asyncio

import pytest
from docentric_copilot.ddsp_parser import parse_ddsp
from docentric_copilot.llm import LLMGateway
from docentric_copilot.planner import TemplatePlanner
from docentric_copilot.planner.rebind import rebind_paths
from docentric_copilot.planner.revision_ops import apply_revision
from docentric_copilot.preview import render_preview

from tests.conftest import EXAMPLES


@pytest.fixture(scope="module")
def planned():
    source = parse_ddsp((EXAMPLES / "quotation" / "sales-quotation.ddsp").read_bytes(), "q.ddsp")
    outcome = asyncio.run(
        TemplatePlanner(LLMGateway()).plan(
            source.schema, (EXAMPLES / "quotation" / "prompt.txt").read_text()
        )
    )
    return source, outcome


def test_rename_title_uses_the_quoted_name(planned) -> None:
    source, outcome = planned
    result = apply_revision(
        outcome.document, 'Rename the document to "Service Proposal"', source.schema
    )
    assert result is not None and result.operations == ["rename_title"]
    assert result.document.title == "Service Proposal"


def test_unknown_subject_falls_back(planned) -> None:
    source, outcome = planned
    assert (
        apply_revision(outcome.document, "Move the flux capacitor to the footer", source.schema)
        is None
    )


def test_compact_requires_a_table_subject(planned) -> None:
    source, outcome = planned
    assert apply_revision(outcome.document, "Make it compact", source.schema) is None


def test_rebind_in_header_and_footer(planned) -> None:
    source, outcome = planned
    updated, changed = rebind_paths(
        outcome.document,
        source.schema,
        "GeneralData.Company.Name",
        "MainData.Quotation.Customer.Name",
    )
    assert changed >= 1
    assert "GeneralData.Company.Name" not in updated.model_dump_json()


def test_preview_marks_plain_tables_and_pages(planned) -> None:
    source, outcome = planned
    html = render_preview(outcome.document, source.schema, sample_data=source.sample_data).html
    assert 'class="doc-table plain' in html
    assert html.count('class="page"') >= 2
    assert "Page 1 of" in html
