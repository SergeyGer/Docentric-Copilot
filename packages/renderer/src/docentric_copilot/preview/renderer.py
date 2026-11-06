"""Independent HTML preview (FR-06).

This renderer never claims to reproduce Word or Docentric layout: it is a
data-substitution preview used to review content and bindings. Pagination,
fonts and Docentric tagging behaviour are out of scope and explicitly labelled
as such in the output.
"""

from __future__ import annotations

import base64
import binascii
import html
import re
from dataclasses import dataclass, field
from typing import Any

from docentric_copilot.ddsp_parser.models import NormalizedSchema
from docentric_copilot.docx_compiler.context import SampleContext
from docentric_copilot.docx_compiler.expression import evaluate
from docentric_copilot.docx_compiler.formatting import format_value
from docentric_copilot.schema_resolver.paths import PathResolutionError, Scope, resolve_collection
from docentric_copilot.template_ir import (
    Alignment,
    Block,
    Cell,
    Conditional,
    Document,
    FieldBinding,
    Heading,
    ImageBinding,
    PageBreak,
    Paragraph,
    Repeat,
    Table,
    TextStyle,
)
from jinja2 import Template
from pydantic import BaseModel, ConfigDict

_TEMPLATE = Template(
    """<!DOCTYPE html>
<html lang="{{ language }}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }} · preview</title>
<style>
  *, *::before, *::after { box-sizing: border-box; }
  body { margin: 0; padding: 24px; background: #eef1f5;
         font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; }
  .toolbar { max-width: 210mm; margin: 0 auto 12px; display: flex; gap: 12px;
             align-items: center; justify-content: space-between; font-size: 12px; color: #475569; }
  .toolbar .badge { display: inline-block; padding: 2px 8px; border-radius: 999px;
                    background: #fef3c7; color: #92400e; font-weight: 600; }
  .page { width: 210mm; min-height: 297mm; margin: 0 auto 22px; background: #fff;
          box-shadow: 0 2px 10px rgba(15, 23, 42, .16); padding: {{ margins.top }}mm {{ margins.right }}mm
          {{ margins.bottom }}mm {{ margins.left }}mm; position: relative; display: flex;
          flex-direction: column; }
  .page.landscape { width: 297mm; min-height: 210mm; }
  .page-header { display: flex; justify-content: space-between; align-items: baseline;
                 border-bottom: 1px solid #cbd5e1; padding-bottom: 6px; margin-bottom: 18px;
                 font-size: 8pt; letter-spacing: .08em; text-transform: uppercase; color: #64748b; }
  .page-body { flex: 1; }
  .page-footer { display: flex; justify-content: space-between; border-top: 1px solid #cbd5e1;
                 margin-top: 22px; padding-top: 7px; font-size: 8pt; color: #64748b; }
  .page-break { break-before: page; }
  table.plain { border-collapse: collapse; width: auto; }
  table.plain td { border: none !important; padding: 2px 10px; }
  table.plain tr:last-child td { border-top: 1.5px solid #0f2a54 !important; font-weight: 700; }
  table.parties tr:last-child td { border-top: none !important; font-weight: 400; }
  .doc-value { border-bottom: 1px dashed transparent; border-radius: 2px; cursor: help; }
  .doc-value:hover, .doc-value.is-active { border-bottom-color: #2563eb; background: #eff6ff; }
  @media print {
    body { background: #fff; padding: 0; }
    .toolbar, .notice { display: none; }
    .page { box-shadow: none; margin: 0; width: auto; min-height: 0; padding: 0; }
    h1, h2, h3 { break-after: avoid; }
    tr { break-inside: avoid; }
  }
  @page { size: A4; margin: 16mm 18mm; }
  .doc-header { border-bottom: 1px solid #e2e8f0; padding-bottom: 8px; margin-bottom: 18px; }
  .doc-footer { border-top: 1px solid #e2e8f0; padding-top: 8px; margin-top: 24px;
                font-size: 9pt; color: #475569; }
  h1 { font-size: 20pt; margin: 0 0 6px; }
  h2 { font-size: 12pt; margin: 16px 0 6px; }
  h3 { font-size: 11pt; margin: 14px 0 4px; }
  p { margin: 0 0 6px; line-height: 1.42; font-size: 10.5pt; }
  table { width: 100%; border-collapse: collapse; margin: 10px 0 14px; font-size: 9.5pt; }
  th, td { border: 1px solid #cbd5e1; padding: 6px 8px; text-align: left; vertical-align: top; }
  th { background: #eef2f7; font-weight: 600; }
  tbody tr:nth-child(even) td { background: #f8fafc; }
  .img-placeholder { display: inline-flex; align-items: center; justify-content: center;
                     width: 42mm; height: 16mm; border: 1px dashed #94a3b8; color: #64748b;
                     font-size: 9px; background: #f8fafc; }
  .ph { color: #b45309; background: #fef3c7; padding: 0 3px; border-radius: 3px; font-size: 9pt; }
  .notice { max-width: 210mm; margin: 16px auto 0; font-size: 11px; color: #64748b; text-align: center; }
</style>
</head>
<body>
  <div class="toolbar">
    <span>Independent preview · layout differs from Word/Docentric pagination</span>
    <span class="badge">Docentric AX compatibility: not verified</span>
  </div>
  {{ body|safe }}
  <p class="notice">Rendered by Docentric Copilot from the validated Template IR and DDSP sample data.</p>
</body>
</html>
"""
)

_ALIGN = {
    Alignment.LEFT: "left",
    Alignment.CENTER: "center",
    Alignment.RIGHT: "right",
    Alignment.JUSTIFY: "justify",
}


class PreviewOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_repeat_items: int = 200
    show_placeholders: bool = True


@dataclass
class PreviewResult:
    html: str
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


class _PreviewRenderer:
    def __init__(
        self,
        schema: NormalizedSchema,
        sample: dict[str, Any] | None,
        options: PreviewOptions,
    ) -> None:
        self._schema = schema
        self._sample = sample
        self._options = options
        self._warnings: list[str] = []
        self._stats = {"paragraphs": 0, "tables": 0, "images": 0, "repeats": 0, "placeholders": 0}
        self._use_sample = sample is not None

    @property
    def warnings(self) -> list[str]:
        return self._warnings

    @property
    def stats(self) -> dict[str, int]:
        return dict(self._stats)

    # ------------------------------------------------------------------ public
    def render(self, document: Document) -> PreviewResult:
        context = SampleContext(sample=self._sample or {}, schema=self._schema, scope=Scope())
        section = document.sections[0]
        header = self._render_blocks(section.header or [], context)
        first_header = (
            self._render_blocks(section.first_page_header, context)
            if section.first_page_header is not None
            else None
        )
        footer = self._render_blocks(section.footer or [], context)
        body_parts = [self._render_blocks(section.body, context)]
        for extra in document.sections[1:]:
            body_parts.append(
                '<div style="page-break-before: always; border-top: 1px dashed #e2e8f0; '
                'margin-top: 24px; padding-top: 16px;"></div>'
            )
            body_parts.append(self._render_blocks(extra.body, context))
        raw_body = "".join(body_parts)
        chunks = list(raw_body.split('<div class="page-break" aria-hidden="true"></div>'))
        total_pages = max(1, len(chunks))
        fallback_header = (
            f"<span>{html.escape(document.title)}</span>"
            f"<span>{html.escape(document.metadata.template_name.replace('_', ' ').title())}</span>"
        )
        pages_html = []
        for index, chunk in enumerate(chunks):
            use_first = index == 0 and first_header is not None
            page_header = first_header if use_first else header
            header_html = page_header if page_header else fallback_header
            footer_html = (
                f"<span>{footer}</span>"
                if footer
                else "<span>Generated by Docentric Copilot</span>"
            )
            pages_html.append(
                '<section class="page">'
                f'<div class="page-header">{header_html}</div>'
                f'<div class="page-body">{chunk}</div>'
                '<div class="page-footer">'
                f"{footer_html}"
                f"<span>Page {index + 1} of {total_pages}</span>"
                "</div>"
                "</section>"
            )
        body_html = "".join(pages_html)
        page = document.page
        return PreviewResult(
            html=_TEMPLATE.render(
                title=html.escape(document.title),
                language=document.language,
                landscape=page.orientation == "landscape",
                margins={
                    "top": page.margin_top_mm,
                    "right": page.margin_right_mm,
                    "bottom": page.margin_bottom_mm,
                    "left": page.margin_left_mm,
                },
                header=header,
                body=body_html,
                footer=footer,
            ),
            warnings=self._warnings,
            stats=self._stats,
        )

    # ----------------------------------------------------------------- helpers
    def _render_blocks(self, blocks: list[Block], context: SampleContext) -> str:
        return "".join(self._render_block(block, context) for block in blocks)

    def _render_block(self, block: Block, context: SampleContext) -> str:
        if isinstance(block, Paragraph):
            self._stats["paragraphs"] += 1
            return self._paragraph(block, context)
        if isinstance(block, Heading):
            self._stats["paragraphs"] += 1
            level = max(1, min(3, block.level))
            return f"<h{level}>{self._runs(block.runs, context, block.style)}</h{level}>"
        if isinstance(block, ImageBinding):
            return self._image(block, context)
        if isinstance(block, Repeat):
            return self._repeat(block, context)
        if isinstance(block, Conditional):
            return self._conditional(block, context)
        if isinstance(block, PageBreak):
            return self._page_break()
        if isinstance(block, Table):
            return self._table(block, context)
        raise ValueError(
            f"unsupported block kind: {getattr(block, 'kind', '?')}"
        )  # pragma: no cover

    def _page_break(self) -> str:
        self._stats["page_breaks"] = self._stats.get("page_breaks", 0) + 1
        return '<div class="page-break" aria-hidden="true"></div>'

    def _paragraph(self, block: Paragraph, context: SampleContext) -> str:
        style = _css(block.style)
        space = (
            f"margin-bottom:{block.space_after_pt}pt;" if block.space_after_pt is not None else ""
        )
        return (
            f'<p style="{space}">{self._runs(block.runs, context, None, wrapper_style=style)}</p>'
        )

    def _runs(
        self,
        runs: list[Any],
        context: SampleContext,
        style: TextStyle | None = None,
        *,
        wrapper_style: str = "",
    ) -> str:
        parts: list[str] = []
        for run in runs:
            if isinstance(run, FieldBinding):
                parts.append(self._binding(run, context))
            else:
                parts.append(f"<span>{html.escape(run.text)}</span>")
        inner = "".join(parts) or "&nbsp;"
        combined = f"{wrapper_style}{_css(style)}"
        return f'<span style="{combined}">{inner}</span>' if combined else inner

    def _binding(self, binding: FieldBinding, context: SampleContext) -> str:
        if not self._use_sample:
            self._stats["placeholders"] += 1
            return self._placeholder(binding.path)
        value = context.value(binding.path)
        if value is None:
            self._stats["placeholders"] += 1
            return self._placeholder(binding.path)
        absolute = context.absolute(binding.path) or binding.path
        return (
            f'<span class="doc-value" data-path="{html.escape(absolute)}">'
            f"{html.escape(format_value(value, binding))}</span>"
        )

    def _placeholder(self, path: str) -> str:
        return f'<span class="ph">{html.escape(path)}</span>'

    def _image(self, block: ImageBinding, context: SampleContext) -> str:
        value = context.value(block.path) if self._use_sample else None
        source = _data_uri(value)
        if source is None:
            self._stats["placeholders"] += 1
            return f'<p><span class="img-placeholder">image · {html.escape(block.path)}</span></p>'
        self._stats["images"] += 1
        width = f"width:{block.width_mm}mm;" if block.width_mm else "max-width:60mm;"
        absolute = context.absolute(block.path) or block.path
        return (
            f'<p><img class="doc-value" data-path="{html.escape(absolute)}" src="{source}" '
            f'alt="{html.escape(block.alt_text or block.path)}" style="{width}height:auto;"></p>'
        )

    def _repeat(self, block: Repeat, context: SampleContext) -> str:
        try:
            collection = resolve_collection(self._schema, block.path, context.scope)
        except PathResolutionError as exc:
            self._warnings.append(f"Repeat '{block.path}' could not be resolved: {exc.message}")
            return ""
        items = context.collection(block.path) if self._use_sample else []
        if not items:
            if block.empty_message:
                return f"<p><em>{html.escape(block.empty_message)}</em></p>"
            return ""
        limit = min(len(items), block.max_items or self._options.max_repeat_items)
        if limit < len(items):
            self._warnings.append(
                f"Repeat '{block.path}' truncated to {limit} of {len(items)} items"
            )
        rendered = []
        for item in items[:limit]:
            self._stats["repeats"] += 1
            child = context.child(block.alias, collection.absolute, item)
            rendered.append(self._render_blocks(block.blocks, child))
        return "".join(rendered)

    def _conditional(self, block: Conditional, context: SampleContext) -> str:
        if not self._use_sample:
            return self._render_blocks(block.then_blocks, context)
        if evaluate(block.condition, context):
            return self._render_blocks(block.then_blocks, context)
        if block.else_blocks:
            return self._render_blocks(block.else_blocks, context)
        return ""

    def _table(self, block: Table, context: SampleContext) -> str:
        self._stats["tables"] += 1
        rows: list[str] = []
        if block.show_header:
            headers = "".join(
                f'<th style="width:{column.width_mm}mm;text-align:{(_ALIGN[column.alignment] if column.alignment else "left")}">'
                f"{html.escape(column.header)}</th>"
                if column.width_mm
                else f'<th style="text-align:{(_ALIGN[column.alignment] if column.alignment else "left")}">'
                f"{html.escape(column.header)}</th>"
                for column in block.columns
            )
            rows.append(f"<thead><tr>{headers}</tr></thead>")
        body_rows: list[str] = []
        for row in block.rows:
            body_rows.append(self._row(row.cells, context))
        if block.repeat is not None and block.row_template is not None and self._use_sample:
            try:
                collection = resolve_collection(self._schema, block.repeat.path, context.scope)
            except PathResolutionError as exc:
                self._warnings.append(f"Table repeat '{block.repeat.path}' failed: {exc.message}")
                collection = None
            if collection is not None:
                items = context.collection(block.repeat.path)
                limit = min(len(items), block.repeat.max_items or self._options.max_repeat_items)
                for item in items[:limit]:
                    self._stats["repeats"] += 1
                    child = context.child(block.repeat.alias, collection.absolute, item)
                    body_rows.append(self._row(block.row_template, child))
        plain = " plain" if (block.style is not None and not block.style.borders) else ""
        if (
            plain
            and block.columns
            and block.columns[0].width_mm
            and block.columns[0].width_mm >= 80
        ):
            plain += " parties"
        return f'<table class="doc-table{plain}">{"".join(rows)}<tbody>{"".join(body_rows)}</tbody></table>'

    def _row(self, cells: list[Cell], context: SampleContext) -> str:
        rendered = []
        for cell in cells:
            inner = "".join(self._render_block(block, context) for block in cell.blocks) or "&nbsp;"
            rendered.append(f"<td>{inner}</td>")
        return f"<tr>{''.join(rendered)}</tr>"


def _css(style: TextStyle | None) -> str:
    if style is None:
        return ""
    parts: list[str] = []
    if style.bold:
        parts.append("font-weight:600")
    if style.italic:
        parts.append("font-style:italic")
    if style.underline:
        parts.append("text-decoration:underline")
    if style.font_size_pt:
        parts.append(f"font-size:{style.font_size_pt}pt")
    if style.color:
        parts.append(f"color:{style.color}")
    if style.alignment:
        parts.append(f"text-align:{_ALIGN[style.alignment]}")
    return ";".join(parts) + ";" if parts else ""


_DATA_URI = re.compile(r"^data:image/[a-z0-9.+-]+;base64,[A-Za-z0-9+/=\s]+$", re.IGNORECASE)
_BASE64 = re.compile(r"^[A-Za-z0-9+/=\s]+$")


def _data_uri(value: Any) -> str | None:
    """Return a safe ``data:`` URI for an inline image value, or ``None``."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if _DATA_URI.match(raw):
        return re.sub(r"\s+", "", raw)
    if not _BASE64.match(raw) or len(raw) < 32:
        return None
    compact = re.sub(r"\s+", "", raw)
    try:
        decoded = base64.b64decode(compact[:64] + "=" * (-len(compact[:64]) % 4), validate=False)
    except (binascii.Error, ValueError):
        return None
    if not decoded or not any(
        decoded.startswith(magic) for magic in (b"\x89PNG", b"\xff\xd8", b"GIF8", b"BM")
    ):
        return None
    return f"data:image/png;base64,{compact}"


def render_preview(
    document: Document,
    schema: NormalizedSchema,
    *,
    sample_data: dict[str, Any] | None = None,
    options: PreviewOptions | None = None,
) -> PreviewResult:
    renderer = _PreviewRenderer(schema, sample_data, options or PreviewOptions())
    return renderer.render(document)


__all__ = ["PreviewOptions", "PreviewResult", "render_preview"]
