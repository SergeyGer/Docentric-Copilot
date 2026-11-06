"""V013-07: confirmation state and download gating."""

from __future__ import annotations

from docentric_copilot.api.demo_state import apply_confirmations, compile_ready
from docentric_copilot.schema_resolver.mapping import (
    FieldMapping,
    MappingReport,
    MappingStatus,
)


def _report(status: MappingStatus) -> MappingReport:
    return MappingReport(
        mappings=[
            FieldMapping(
                requirement_id="req_00",
                requirement="Choose a customer",
                selected_field_path="MainData.Customer.Name",
                status=status,
                explanation="Ambiguous between customer and company.",
            )
        ]
    )


def test_unresolved_mapping_blocks_download() -> None:
    report = _report(MappingStatus.NEEDS_REVIEW)
    assert not compile_ready(report)


def test_confirmation_marks_the_mapping_resolved_and_unblocks_download() -> None:
    report = _report(MappingStatus.NEEDS_REVIEW)
    confirmed = apply_confirmations(report, {"req_00": "Customer name is correct."})
    assert confirmed.mappings[0].status is MappingStatus.CONFIRMED
    assert "Customer name is correct." in confirmed.mappings[0].explanation
    assert compile_ready(confirmed)
    assert confirmed.counts()["confirmed"] == 1
    assert confirmed.counts()["needs_review"] == 0


def test_missing_mapping_cannot_be_confirmed_without_a_field() -> None:
    report = _report(MappingStatus.MISSING)
    confirmed = apply_confirmations(report, {"req_00": "I accept the risk."})
    assert confirmed.mappings[0].status is MappingStatus.MISSING
    assert not compile_ready(confirmed)


def test_confirmation_state_is_idempotent() -> None:
    report = _report(MappingStatus.NEEDS_REVIEW)
    once = apply_confirmations(report, {"req_00": "ok"})
    twice = apply_confirmations(once, {"req_00": "ok"})
    assert twice.mappings[0].status is MappingStatus.CONFIRMED
    assert twice.mappings[0].explanation.count("ok") == 1
