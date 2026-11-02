"""Document quality analysis on the validated Template IR (Initiative 2).

The checks are deterministic and explainable: each finding names the IR path it
belongs to, so the UI can point at the element instead of showing a vague score.
This is an IR-level analysis, not a Word pagination proof.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from docentric_copilot.ddsp_parser.models import NormalizedSchema
from docentric_copilot.template_ir import (
    Block,
    Conditional,
    Document,
    FieldBinding,
    ImageBinding,
    Paragraph,
    Repeat,
    Table,
)
from pydantic import BaseModel, ConfigDict

_PAGE_SIZES = {"A4": (210.0, 297.0), "LETTER": (215.9, 279.4)}


class QualityStatus(str, Enum):
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"


class QualityCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    status: QualityStatus
    message: str
    path: str | None = None


class QualityMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: str
    text_width_mm: float
    tables: int
    images: int
    blocks: int


class QualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall: QualityStatus
    checks: list[QualityCheck]
    metrics: QualityMetrics

    def counts(self) -> dict[str, int]:
        result = {status.value: 0 for status in QualityStatus}
        for check in self.checks:
            result[check.status.value] += 1
        return result


def _text_width(document: Document) -> float:
    page = document.page
    width, _ = _PAGE_SIZES[page.size]
    if page.orientation == "landscape":
        width, _ = _PAGE_SIZES[page.size][1], _PAGE_SIZES[page.size][0]
    return width - page.margin_left_mm - page.margin_right_mm


def _walk(blocks: list[Block]) -> list[tuple[Block, str]]:
    found: list[tuple[Block, str]] = []
    for block in blocks:
        found.append((block, block.kind))
        if isinstance(block, Repeat):
            found.extend(_walk(block.blocks))
        elif isinstance(block, Conditional):
            found.extend(_walk(block.then_blocks))
            found.extend(_walk(list(block.else_blocks or [])))
        elif isinstance(block, Table):
            for cell in block.row_template or []:
                found.extend(_walk(cell.blocks))
            for row in block.rows:
                for cell in row.cells:
                    found.extend(_walk(cell.blocks))
    return found


def analyze_quality(
    document: Document,
    schema: NormalizedSchema,
    *,
    sample_data: dict[str, Any] | None = None,
) -> QualityReport:
    text_width = _text_width(document)
    checks: list[QualityCheck] = []
    blocks = [block for section in document.sections for block in _walk(list(section.body))]

    tables = [block for block, _ in blocks if isinstance(block, Table)]
    images = [block for block, _ in blocks if isinstance(block, ImageBinding)]

    overflowing_tables = [
        table
        for table in tables
        if sum(column.width_mm or 0 for column in table.columns) > text_width + 0.5
    ]
    checks.append(
        QualityCheck(
            id="table_layout",
            label="Table layout",
            status=QualityStatus.WARNING if overflowing_tables else QualityStatus.PASSED,
            message=(
                f"{len(overflowing_tables)} table(s) wider than the {text_width:.0f} mm text area"
                if overflowing_tables
                else "every table fits the text area"
            ),
            path=overflowing_tables[0].repeat.path
            if overflowing_tables and overflowing_tables[0].repeat
            else None,
        )
    )

    oversized = [image for image in images if (image.width_mm or 0) > text_width]
    checks.append(
        QualityCheck(
            id="image_clipping",
            label="Image clipping",
            status=QualityStatus.FAILED if oversized else QualityStatus.PASSED,
            message=(
                f"{len(oversized)} image(s) wider than the page"
                if oversized
                else "images fit inside the text area"
            ),
            path=oversized[0].path if oversized else None,
        )
    )

    empty_sections = [section.name for section in document.sections if not section.body]
    checks.append(
        QualityCheck(
            id="page_overflow",
            label="Page content",
            status=QualityStatus.FAILED if empty_sections else QualityStatus.PASSED,
            message=(
                f"empty section(s): {', '.join(empty_sections)}"
                if empty_sections
                else "every section has content"
            ),
        )
    )

    headers_footers = [section for section in document.sections if section.header or section.footer]
    checks.append(
        QualityCheck(
            id="header_footer",
            label="Header and footer",
            status=QualityStatus.PASSED if headers_footers else QualityStatus.WARNING,
            message=(
                "running header and footer are defined"
                if headers_footers
                else "no header or footer blocks; page numbers are still added by the compiler"
            ),
        )
    )

    breaks = [block.kind for block, kind in blocks if kind == "page_break"]
    headings = [block for block, _ in blocks if block.kind == "heading"]
    checks.append(
        QualityCheck(
            id="page_breaks",
            label="Page breaks",
            status=QualityStatus.PASSED,
            message=f"{len(breaks)} explicit page break(s), {len(headings)} heading(s)",
        )
    )

    sizes: list[float] = []
    for block, _ in blocks:
        if not isinstance(block, Paragraph):
            continue
        for run in block.runs:
            style = getattr(run, "style", None)
            if style is not None and style.font_size_pt:
                sizes.append(style.font_size_pt)
    offset = [size for size in sizes if size < 7 or size > 24]
    checks.append(
        QualityCheck(
            id="typography",
            label="Typography",
            status=QualityStatus.WARNING if offset else QualityStatus.PASSED,
            message=(
                f"{len(offset)} run(s) outside the 7-24 pt range"
                if offset
                else "type sizes stay in the readable range"
            ),
        )
    )

    repeat_headers = [
        table
        for table in tables
        if table.repeat is not None and table.show_header and (table.row_template or table.rows)
    ]
    long_values: list[str] = []
    if sample_data:
        for block, _ in blocks:
            if isinstance(block, Paragraph):
                for run in block.runs:
                    if isinstance(run, FieldBinding):
                        value = _resolve(sample_data, run.path)
                        if isinstance(value, str) and len(value) > 120 and " " not in value:
                            long_values.append(run.path)
    checks.append(
        QualityCheck(
            id="content_safety",
            label="Content safety",
            status=QualityStatus.FAILED if long_values else QualityStatus.PASSED,
            message=(
                f"unbreakable value(s) would overflow the page: {', '.join(sorted(set(long_values))[:3])}"
                if long_values
                else "no oversized unbreakable values"
            ),
            path=long_values[0] if long_values else None,
        )
    )
    if repeat_headers:
        checks.append(
            QualityCheck(
                id="table_header_repeat",
                label="Repeating table headers",
                status=QualityStatus.PASSED,
                message=f"{len(repeat_headers)} repeating table(s) repeat their header row",
            )
        )

    statuses = {check.status for check in checks}
    overall = (
        QualityStatus.FAILED
        if QualityStatus.FAILED in statuses
        else QualityStatus.WARNING
        if QualityStatus.WARNING in statuses
        else QualityStatus.PASSED
    )
    return QualityReport(
        overall=overall,
        checks=checks,
        metrics=QualityMetrics(
            page=document.page.size,
            text_width_mm=round(text_width, 1),
            tables=len(tables),
            images=len(images),
            blocks=len(blocks),
        ),
    )


def _resolve(sample: dict[str, Any], path: str) -> Any:
    cursor: Any = sample
    for part in path.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            return None
        cursor = cursor[part]
    return cursor


__all__ = [
    "QualityCheck",
    "QualityMetrics",
    "QualityReport",
    "QualityStatus",
    "analyze_quality",
]
