"""Validation engine V1-V5 (FR-07)."""

from __future__ import annotations

from docentric_copilot.ddsp_parser.models import NormalizedSchema
from docentric_copilot.template_ir import Document

from .engine import ValidationEngine
from .models import CheckResult, CheckStatus, Finding, Level, Severity, ValidationReport
from .report import render_report_html, render_report_json


def validate_document(
    document: Document,
    schema: NormalizedSchema,
    *,
    sample_data: dict | None = None,
    package: bytes | None = None,
) -> ValidationReport:
    """Convenience entry point: validate one document with the default engine."""
    return ValidationEngine().validate(document, schema, sample_data=sample_data, package=package)


__all__ = [
    "CheckResult",
    "CheckStatus",
    "Finding",
    "Level",
    "Severity",
    "ValidationEngine",
    "ValidationReport",
    "render_report_html",
    "render_report_json",
    "validate_document",
]
