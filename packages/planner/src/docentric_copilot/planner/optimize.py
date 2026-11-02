"""Typed, reviewable layout optimisation (Initiative 2).

Only structural changes that the IR can express are applied: column widths,
image widths and repeated table headers. The optimised document is written as a
new version and re-validated, so the reviewer sees a diff, not a silent edit.
"""

from __future__ import annotations

from typing import Any

from docentric_copilot.ddsp_parser.models import NormalizedSchema
from docentric_copilot.planner.quality import QualityReport, QualityStatus, analyze_quality
from docentric_copilot.template_ir import (
    Block,
    Conditional,
    Document,
    ImageBinding,
    Repeat,
    Table,
)
from pydantic import BaseModel, ConfigDict


class LayoutFix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    message: str
    path: str | None = None


class LayoutOptimization(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: Document
    fixes: list[LayoutFix]
    before: QualityReport
    after: QualityReport


def _optimise_blocks(blocks: list[Block], text_width: float, fixes: list[LayoutFix]) -> list[Block]:
    result: list[Block] = []
    for block in blocks:
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
                    )
                )
            result.append(block)
        elif isinstance(block, ImageBinding):
            if (block.width_mm or 0) > text_width:
                fixes.append(
                    LayoutFix(
                        id="fit_image",
                        message=f"capped image at {text_width:.0f} mm",
                        path=block.path,
                    )
                )
                block = block.model_copy(update={"width_mm": round(text_width, 1)})
            result.append(block)
        elif isinstance(block, Repeat):
            result.append(
                block.model_copy(
                    update={"blocks": _optimise_blocks(block.blocks, text_width, fixes)}
                )
            )
        elif isinstance(block, Conditional):
            result.append(
                block.model_copy(
                    update={
                        "then_blocks": _optimise_blocks(block.then_blocks, text_width, fixes),
                        "else_blocks": _optimise_blocks(
                            list(block.else_blocks or []), text_width, fixes
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
    for section in document.sections:
        sections.append(
            section.model_copy(
                update={
                    "body": _optimise_blocks(list(section.body), text_width, fixes),
                    "header": _optimise_blocks(list(section.header or []), text_width, fixes)
                    or None,
                    "footer": _optimise_blocks(list(section.footer or []), text_width, fixes)
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
