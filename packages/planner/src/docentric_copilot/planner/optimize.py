"""Typed, reviewable layout optimisation (Initiative 2).

Only structural changes that the IR can express are applied: column widths,
table font sizes, image widths and repeated table headers. The optimised document
is written as a new version and re-validated, so the reviewer sees a diff, not a
silent edit.
"""

from __future__ import annotations

from typing import Any

from docentric_copilot.ddsp_parser.models import NormalizedSchema
from docentric_copilot.planner.quality import (
    QualityReport,
    QualityStatus,
    analyze_quality,
    required_width_mm,
    table_font_size,
    text_fit_issues_for_table,
)
from docentric_copilot.template_ir import (
    Block,
    Conditional,
    Document,
    ImageBinding,
    Repeat,
    Table,
    TableStyle,
)
from pydantic import BaseModel, ConfigDict

_MIN_COLUMN_WIDTH_MM = 12.0
_MIN_TABLE_FONT_PT = 8.0
_FONT_STEP_PT = 0.5
_MIN_WIDTH_CHANGE_MM = 0.05


class LayoutFix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    message: str
    path: str | None = None
    before: float | None = None
    after: float | None = None


class LayoutOptimization(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: Document
    fixes: list[LayoutFix]
    before: QualityReport
    after: QualityReport


def _column_widths(table: Table, text_width: float) -> list[float]:
    fallback = text_width / max(1, len(table.columns))
    return [column.width_mm or fallback for column in table.columns]


def _rebalance_column(
    table: Table,
    table_path: str,
    column_index: int,
    needed_width_mm: float,
    text_width: float,
    fixes: list[LayoutFix],
) -> Table:
    """Widen one column by shrinking the slack of the other columns."""
    widths = _column_widths(table, text_width)
    count = len(widths)
    if count < 2 or column_index >= count:
        return table
    current = widths[column_index]
    current_total = sum(widths)
    min_other_total = _MIN_COLUMN_WIDTH_MM * (count - 1)
    max_target = max(current, text_width - min_other_total)
    target = min(max(current, needed_width_mm), max_target)
    desired_delta = target - current
    if desired_delta <= _MIN_WIDTH_CHANGE_MM:
        return table

    free_space = max(0.0, text_width - current_total)
    from_others = max(0.0, desired_delta - free_space)
    other_indices = [index for index in range(count) if index != column_index]
    slack = {index: max(0.0, widths[index] - _MIN_COLUMN_WIDTH_MM) for index in other_indices}
    total_slack = sum(slack.values())
    from_others = min(from_others, total_slack)
    actual_delta = min(desired_delta, free_space + from_others)
    if actual_delta <= _MIN_WIDTH_CHANGE_MM:
        return table

    new_widths = list(widths)
    if from_others > 0 and total_slack > 0:
        for index in other_indices:
            share = from_others * slack[index] / total_slack
            new_widths[index] = max(_MIN_COLUMN_WIDTH_MM, round(widths[index] - share, 1))
    room = text_width - sum(new_widths[index] for index in other_indices)
    new_target = round(min(current + actual_delta, room), 1)
    if new_target - current <= _MIN_WIDTH_CHANGE_MM:
        return table
    new_widths[column_index] = new_target

    header = table.columns[column_index].header or f"column {column_index + 1}"
    fixes.append(
        LayoutFix(
            id="fit_text_width",
            message=(
                f"widened {header} from {current:.1f} mm to {new_target:.1f} mm "
                "by rebalancing the other columns"
            ),
            path=f"{table_path}.columns[{column_index}].width_mm",
            before=round(current, 1),
            after=new_target,
        )
    )
    columns = [
        column.model_copy(update={"width_mm": round(width, 1)})
        for column, width in zip(table.columns, new_widths, strict=True)
    ]
    return table.model_copy(update={"columns": columns})


def _apply_text_fit(
    table: Table,
    table_path: str,
    text_width: float,
    sample_data: dict[str, Any] | None,
    fixes: list[LayoutFix],
) -> Table:
    """Widen over-long text columns, then lower the table font if still needed."""
    issues = text_fit_issues_for_table(table, table_path, sample_data, text_width)
    if not issues:
        return table

    for column_index in sorted({issue.column_index for issue in issues}):
        column_issues = [issue for issue in issues if issue.column_index == column_index]
        worst = max(column_issues, key=lambda issue: (issue.lines, issue.characters))
        needed = required_width_mm(worst.characters, table_font_size(table))
        table = _rebalance_column(table, table_path, column_index, needed, text_width, fixes)
        issues = text_fit_issues_for_table(table, table_path, sample_data, text_width)

    while table_font_size(table) > _MIN_TABLE_FONT_PT:
        if not text_fit_issues_for_table(table, table_path, sample_data, text_width):
            break
        previous = table_font_size(table)
        following = max(_MIN_TABLE_FONT_PT, round(previous - _FONT_STEP_PT, 1))
        if following >= previous:
            break
        style = (
            table.style.model_copy(update={"font_size_pt": following})
            if table.style is not None
            else TableStyle(font_size_pt=following)
        )
        table = table.model_copy(update={"style": style})
        fixes.append(
            LayoutFix(
                id="fit_text_font",
                message=f"reduced the table font from {previous:.1f} pt to {following:.1f} pt",
                path=f"{table_path}.style.font_size_pt",
                before=previous,
                after=following,
            )
        )
    return table


def _optimise_blocks(
    blocks: list[Block],
    text_width: float,
    fixes: list[LayoutFix],
    *,
    sample_data: dict[str, Any] | None,
    prefix: str,
) -> list[Block]:
    result: list[Block] = []
    for position, block in enumerate(blocks):
        path = f"{prefix}[{position}]"
        if isinstance(block, Table):
            declared = sum(column.width_mm or 0 for column in block.columns)
            if declared > text_width and declared:
                factor = text_width / declared
                columns = [
                    column.model_copy(
                        update={"width_mm": round((column.width_mm or 20.0) * factor, 1)}
                    )
                    for column in block.columns
                ]
                block = block.model_copy(
                    update={
                        "columns": columns,
                        "show_header": block.show_header or block.repeat is not None,
                    }
                )
                fixes.append(
                    LayoutFix(
                        id="fit_table",
                        message=f"scaled columns from {declared:.0f} mm to {text_width:.0f} mm",
                        path=block.repeat.path if block.repeat else None,
                        before=round(declared, 1),
                        after=round(sum(column.width_mm or 0 for column in columns), 1),
                    )
                )
            result.append(_apply_text_fit(block, path, text_width, sample_data, fixes))
        elif isinstance(block, ImageBinding):
            if (block.width_mm or 0) > text_width:
                previous = block.width_mm or 0.0
                fixes.append(
                    LayoutFix(
                        id="fit_image",
                        message=f"capped image at {text_width:.0f} mm",
                        path=block.path,
                        before=round(previous, 1),
                        after=round(text_width, 1),
                    )
                )
                block = block.model_copy(update={"width_mm": round(text_width, 1)})
            result.append(block)
        elif isinstance(block, Repeat):
            result.append(
                block.model_copy(
                    update={
                        "blocks": _optimise_blocks(
                            block.blocks,
                            text_width,
                            fixes,
                            sample_data=sample_data,
                            prefix=f"{path}.blocks",
                        )
                    }
                )
            )
        elif isinstance(block, Conditional):
            result.append(
                block.model_copy(
                    update={
                        "then_blocks": _optimise_blocks(
                            block.then_blocks,
                            text_width,
                            fixes,
                            sample_data=sample_data,
                            prefix=f"{path}.then_blocks",
                        ),
                        "else_blocks": _optimise_blocks(
                            list(block.else_blocks or []),
                            text_width,
                            fixes,
                            sample_data=sample_data,
                            prefix=f"{path}.else_blocks",
                        )
                        or None,
                    }
                )
            )
        else:
            result.append(block)
    return result


def optimize_layout(
    document: Document,
    schema: NormalizedSchema,
    *,
    sample_data: dict[str, Any] | None = None,
) -> LayoutOptimization:
    before = analyze_quality(document, schema, sample_data=sample_data)
    text_width = before.metrics.text_width_mm
    fixes: list[LayoutFix] = []
    sections = []
    for index, section in enumerate(document.sections):
        sections.append(
            section.model_copy(
                update={
                    "body": _optimise_blocks(
                        list(section.body),
                        text_width,
                        fixes,
                        sample_data=sample_data,
                        prefix=f"sections[{index}].body",
                    ),
                    "header": _optimise_blocks(
                        list(section.header or []),
                        text_width,
                        fixes,
                        sample_data=sample_data,
                        prefix=f"sections[{index}].header",
                    )
                    or None,
                    "first_page_header": (
                        _optimise_blocks(
                            list(section.first_page_header),
                            text_width,
                            fixes,
                            sample_data=sample_data,
                            prefix=f"sections[{index}].first_page_header",
                        )
                        or None
                        if section.first_page_header is not None
                        else None
                    ),
                    "footer": _optimise_blocks(
                        list(section.footer or []),
                        text_width,
                        fixes,
                        sample_data=sample_data,
                        prefix=f"sections[{index}].footer",
                    )
                    or None,
                }
            )
        )
    updated = document.model_copy(update={"sections": sections})
    after = analyze_quality(updated, schema, sample_data=sample_data)
    if after.overall is QualityStatus.FAILED and before.overall is not QualityStatus.FAILED:
        # Never trade a warning for a failure; keep the original document.
        return LayoutOptimization(document=document, fixes=[], before=before, after=before)
    return LayoutOptimization(document=updated, fixes=fixes, before=before, after=after)


__all__ = ["LayoutFix", "LayoutOptimization", "optimize_layout"]
