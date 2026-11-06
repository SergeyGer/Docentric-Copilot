"""Document quality analysis on the validated Template IR (Initiative 2).

The checks are deterministic and explainable: each finding names the IR path it
belongs to, so the UI can point at the element instead of showing a vague score.
This is an IR-level analysis, not a Word pagination proof.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import Enum
from typing import Any

from docentric_copilot.ddsp_parser.models import NormalizedSchema
from docentric_copilot.template_ir import (
    Block,
    Cell,
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

# Text-fit estimation. The numbers are deliberately explicit so the rule stays
# explainable: a proportional font averages about half an em per character, and
# a 9.5 pt table cell therefore fits roughly 37 characters in a 62 mm column.
TEXT_FIT_MAX_LINES = 4
TEXT_FIT_AVG_CHAR_EM = 0.5
TEXT_FIT_CELL_PADDING_MM = 3.2  # 90 twips of left + right cell margin, as compiled
_DEFAULT_TABLE_FONT_PT = 9.5
_PT_TO_MM = 25.4 / 72.0

Resolver = Callable[[str], Any]


@dataclass(frozen=True, slots=True)
class TextFitIssue:
    """One table cell whose bound sample text would wrap over the line budget."""

    table_path: str
    cell_path: str
    column_index: int
    column_header: str
    field_path: str | None
    text: str
    lines: int
    width_mm: float
    font_size_pt: float

    @property
    def characters(self) -> int:
        return len(self.text)


def estimate_wrapped_lines(text: str, width_mm: float, font_size_pt: float) -> int:
    """Estimate greedy word-wrapped lines for a cell in a proportional font.

    Deterministic by construction: the average glyph is half an em, the usable
    cell width excludes the compiled left/right padding, and words are wrapped
    greedily. A word longer than the line is split, matching Word's behaviour for
    unbreakable text.
    """
    words = text.split()
    if not words:
        return 0
    usable_mm = max(width_mm - TEXT_FIT_CELL_PADDING_MM, 1.0)
    char_mm = max(font_size_pt, 1.0) * _PT_TO_MM * TEXT_FIT_AVG_CHAR_EM
    chars_per_line = max(1, math.floor(usable_mm / char_mm))
    lines = 1
    used = 0
    for word in words:
        length = len(word)
        if used == 0:
            while length > chars_per_line:
                lines += 1
                length -= chars_per_line
            used = length
        elif used + 1 + length <= chars_per_line:
            used += 1 + length
        else:
            lines += 1
            while length > chars_per_line:
                lines += 1
                length -= chars_per_line
            used = length
    return lines


def required_width_mm(
    characters: int, font_size_pt: float, max_lines: int = TEXT_FIT_MAX_LINES
) -> float:
    """Width that would hold ``characters`` in ``max_lines`` wrapped lines."""
    if characters <= 0 or max_lines <= 0:
        return 0.0
    char_mm = max(font_size_pt, 1.0) * _PT_TO_MM * TEXT_FIT_AVG_CHAR_EM
    chars_per_line = math.ceil(characters / max_lines) + 1
    return round(chars_per_line * char_mm + TEXT_FIT_CELL_PADDING_MM, 1)


def table_font_size(table: Table) -> float:
    """Effective table font size, with the compiler's default when unset."""
    if table.style is not None and table.style.font_size_pt is not None:
        return float(table.style.font_size_pt)
    return _DEFAULT_TABLE_FONT_PT


def _iter_block_paths(blocks: list[Block], prefix: str) -> Iterator[tuple[Block, str]]:
    """Yield ``(block, structural IR path)`` in document order."""
    for index, block in enumerate(blocks):
        path = f"{prefix}[{index}]"
        yield block, path
        if isinstance(block, Repeat):
            yield from _iter_block_paths(block.blocks, f"{path}.blocks")
        elif isinstance(block, Conditional):
            yield from _iter_block_paths(block.then_blocks, f"{path}.then_blocks")
            yield from _iter_block_paths(list(block.else_blocks or []), f"{path}.else_blocks")
        elif isinstance(block, Table):
            for row_index, row in enumerate(block.rows):
                for cell_index, cell in enumerate(row.cells):
                    yield from _iter_block_paths(
                        cell.blocks, f"{path}.rows[{row_index}].cells[{cell_index}].blocks"
                    )
            for cell_index, cell in enumerate(block.row_template or []):
                yield from _iter_block_paths(
                    cell.blocks, f"{path}.row_template[{cell_index}].blocks"
                )
            for row_index, row in enumerate(block.footer_rows):
                for cell_index, cell in enumerate(row.cells):
                    yield from _iter_block_paths(
                        cell.blocks, f"{path}.footer_rows[{row_index}].cells[{cell_index}].blocks"
                    )


def _alias_resolver(alias: str, item: dict[str, Any], collection_path: str) -> Resolver:
    def resolve(path: str) -> Any:
        head, _, tail = path.partition(".")
        if head == alias:
            return _resolve(item, tail) if tail else None
        prefix = f"{collection_path}."
        if path.startswith(prefix):
            return _resolve(item, path[len(prefix) :])
        return _resolve(item, path)

    return resolve


def _row_contexts(
    table: Table, sample_data: dict[str, Any] | None
) -> list[tuple[str, list[Cell], Resolver]]:
    """Return one ``(cell_path_suffix, cells, resolver)`` entry per data row."""
    if sample_data is None:
        return []
    contexts: list[tuple[str, list[Cell], Resolver]] = []
    for row_index, row in enumerate([*table.rows, *table.footer_rows]):
        contexts.append(
            (
                f"rows[{row_index}].cells",
                list(row.cells),
                lambda path: _resolve(sample_data, path),
            )
        )
    if table.repeat is not None and table.row_template is not None:
        items = _resolve(sample_data, table.repeat.path)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    contexts.append(
                        (
                            "row_template",
                            list(table.row_template),
                            _alias_resolver(table.repeat.alias, item, table.repeat.path),
                        )
                    )
    return contexts


def _cell_contents(
    cell: Cell, resolve: Resolver, width_mm: float, font_size_pt: float
) -> tuple[int, str, str | None]:
    """Estimate wrapped lines and collect the longest bound field in one cell."""
    lines = 0
    values: list[str] = []
    field_path: str | None = None
    longest_field = 0
    for block in cell.blocks:
        if not isinstance(block, Paragraph):
            continue
        parts: list[str] = []
        for run in block.runs:
            if isinstance(run, FieldBinding):
                value = resolve(run.path)
                if isinstance(value, str) and value.strip():
                    parts.append(value)
                    if len(value) > longest_field:
                        longest_field = len(value)
                        field_path = run.path
            else:
                parts.append(run.text)
        text = "".join(parts).strip()
        if text:
            values.append(text)
            lines += estimate_wrapped_lines(text, width_mm, font_size_pt)
    return lines, " ".join(values), field_path


def text_fit_issues_for_table(
    table: Table,
    table_path: str,
    sample_data: dict[str, Any] | None,
    text_width: float,
) -> list[TextFitIssue]:
    """Return every cell of ``table`` that would exceed the line budget."""
    font_size = table_font_size(table)
    fallback_width = text_width / max(1, len(table.columns))
    widths = [column.width_mm or fallback_width for column in table.columns]
    issues: list[TextFitIssue] = []
    for suffix, cells, resolve in _row_contexts(table, sample_data):
        for index, cell in enumerate(cells):
            if index >= len(table.columns):
                break
            lines, text, field_path = _cell_contents(cell, resolve, widths[index], font_size)
            if lines <= TEXT_FIT_MAX_LINES:
                continue
            if suffix == "row_template":
                cell_path = f"{table_path}.row_template[{index}]"
            else:
                cell_path = f"{table_path}.{suffix}[{index}]"
            issues.append(
                TextFitIssue(
                    table_path=table_path,
                    cell_path=cell_path,
                    column_index=index,
                    column_header=table.columns[index].header,
                    field_path=field_path,
                    text=text,
                    lines=lines,
                    width_mm=widths[index],
                    font_size_pt=font_size,
                )
            )
    return issues


def find_text_fit_issues(
    document: Document,
    sample_data: dict[str, Any] | None,
    text_width: float,
) -> list[TextFitIssue]:
    """Walk every table in the document and return its text-fit issues."""
    issues: list[TextFitIssue] = []
    for section_index, section in enumerate(document.sections):
        for name, blocks in (
            ("body", section.body),
            ("header", list(section.header or [])),
            ("first_page_header", list(section.first_page_header or [])),
            ("footer", list(section.footer or [])),
        ):
            if not blocks:
                continue
            for block, path in _iter_block_paths(list(blocks), f"sections[{section_index}].{name}"):
                if isinstance(block, Table):
                    issues.extend(text_fit_issues_for_table(block, path, sample_data, text_width))
    return sorted(issues, key=lambda issue: (-issue.lines, issue.cell_path, issue.column_index))


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
            for row in [*block.rows, *block.footer_rows]:
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

    text_fit_issues = find_text_fit_issues(document, sample_data, text_width)
    if text_fit_issues:
        worst = text_fit_issues[0]
        label = worst.column_header or f"column {worst.column_index + 1}"
        text_fit_message = (
            f"{len(text_fit_issues)} table cell(s) exceed {TEXT_FIT_MAX_LINES} estimated lines; "
            f"worst: {label} ~{worst.lines} lines at {worst.width_mm:.0f} mm / "
            f"{worst.font_size_pt:.1f} pt"
        )
        text_fit_path = worst.cell_path
    else:
        text_fit_message = f"no table cell exceeds {TEXT_FIT_MAX_LINES} estimated lines"
        text_fit_path = None
    checks.append(
        QualityCheck(
            id="text_fit",
            label="Text fit",
            status=QualityStatus.WARNING if text_fit_issues else QualityStatus.PASSED,
            message=text_fit_message,
            path=text_fit_path,
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

    headers_footers = [
        section
        for section in document.sections
        if section.header or section.first_page_header or section.footer
    ]
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
    "TEXT_FIT_AVG_CHAR_EM",
    "TEXT_FIT_CELL_PADDING_MM",
    "TEXT_FIT_MAX_LINES",
    "QualityCheck",
    "QualityMetrics",
    "QualityReport",
    "QualityStatus",
    "TextFitIssue",
    "analyze_quality",
    "estimate_wrapped_lines",
    "find_text_fit_issues",
    "required_width_mm",
    "table_font_size",
    "text_fit_issues_for_table",
]
