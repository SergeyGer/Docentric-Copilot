"""Generic DOCX compiler (FR-05).

Deterministic by construction: no model calls, no clock, no randomness. The same
IR, schema, sample data and compiler version always produce a byte identical
package, which is what NFR-01 and the golden-file suite assert.

The produced document is a **generic DOCX**. It is explicitly *not* a verified
Docentric AX template; that claim requires the compatibility gate described in
``docs/DOCENTRIC_AX_COMPATIBILITY.md``.
"""

from __future__ import annotations

import base64
import binascii
import io
import re
from datetime import datetime
from typing import Any, Literal

from docentric_copilot.ddsp_parser.models import NormalizedSchema
from docentric_copilot.errors import CompilationFailedError, UnsupportedTargetError
from docentric_copilot.schema_resolver.paths import (
    PathResolutionError,
    Scope,
    resolve_collection,
)
from docentric_copilot.template_ir import (
    Alignment,
    Block,
    Cell,
    CompileTarget,
    Conditional,
    Document,
    FieldBinding,
    Heading,
    ImageBinding,
    Paragraph,
    Repeat,
    Section,
    Table,
    TextStyle,
    ir_digest,
)
from docx import Document as DocxDocument
from docx.document import Document as DocxDocumentType
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
from docx.shared import Mm, Pt, RGBColor
from docx.table import Table as DocxTable
from docx.table import _Cell
from pydantic import BaseModel, ConfigDict, Field

from .context import SampleContext
from .expression import evaluate
from .formatting import format_value
from .package import DocxPackageInfo, inspect_package, normalize_package

FIXED_DATETIME = datetime(2024, 1, 1, 0, 0, 0)
MAX_IMAGE_BYTES = 5 * 1024 * 1024
_IMAGE_MAGIC = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"BM")
_ALIGN = {
    Alignment.LEFT: WD_ALIGN_PARAGRAPH.LEFT,
    Alignment.CENTER: WD_ALIGN_PARAGRAPH.CENTER,
    Alignment.RIGHT: WD_ALIGN_PARAGRAPH.RIGHT,
    Alignment.JUSTIFY: WD_ALIGN_PARAGRAPH.JUSTIFY,
}
_PAGE_SIZES = {"A4": (210.0, 297.0), "LETTER": (215.9, 279.4)}


class CompileOptions(BaseModel):
    """Deterministic compilation parameters."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target: CompileTarget = CompileTarget.GENERIC_DOCX
    render_mode: Literal["auto", "sample", "placeholder"] = "auto"
    include_compatibility_stamp: bool = False
    max_repeat_items: int = Field(default=200, ge=1, le=1_000)
    document_name: str = Field(default="document.docx", max_length=120)


class CompilationResult(BaseModel):
    """Result of a compilation. ``content`` is never serialized."""

    model_config = ConfigDict(extra="forbid")

    success: bool = True
    target: str
    filename: str
    ir_digest: str
    compatibility: str = "not_tested"
    warnings: list[str] = Field(default_factory=list)
    stats: dict[str, int] = Field(default_factory=dict)
    package: dict[str, Any] | None = None
    content: bytes = Field(default=b"", exclude=True, repr=False)

    @property
    def size_bytes(self) -> int:
        return len(self.content)


class GenericDocxCompiler:
    """Render a validated IR into a standards-compliant DOCX package."""

    name = "generic-docx"
    target = CompileTarget.GENERIC_DOCX
    verified_compatibility = False

    def compile(
        self,
        template: Document,
        schema: NormalizedSchema,
        options: CompileOptions | None = None,
        *,
        sample_data: dict[str, Any] | None = None,
    ) -> CompilationResult:
        resolved_options = options or CompileOptions()
        target = CompileTarget(template.target)
        if target is not CompileTarget.GENERIC_DOCX and not self.verified_compatibility:
            raise UnsupportedTargetError(
                "This compiler only produces generic DOCX documents",
                details={"target": target.value},
            )

        renderer = _Renderer(
            schema=schema,
            sample_data=sample_data,
            options=resolved_options,
            document=template,
        )
        document = renderer.render()
        buffer = io.BytesIO()
        document.save(buffer)
        content = normalize_package(buffer.getvalue())
        info: DocxPackageInfo = inspect_package(content)
        if not info.is_valid:
            raise CompilationFailedError(
                "Compiled package failed structural inspection",
                details=info.as_dict(),
            )
        return CompilationResult(
            target=self.target.value,
            filename=resolved_options.document_name,
            ir_digest=ir_digest(template),
            compatibility="not_tested",
            warnings=renderer.warnings,
            stats=renderer.stats,
            package=info.as_dict(),
            content=content,
        )


class _Renderer:
    """Stateless renderer for one compilation."""

    def __init__(
        self,
        *,
        schema: NormalizedSchema,
        sample_data: dict[str, Any] | None,
        options: CompileOptions,
        document: Document,
    ) -> None:
        self._schema = schema
        self._sample = sample_data
        self._options = options
        self._oriented = document.page.orientation == "landscape"
        self._document = document
        self._warnings: list[str] = []
        self._stats = {
            "paragraphs": 0,
            "tables": 0,
            "images": 0,
            "bindings_rendered": 0,
            "repeats_expanded": 0,
            "placeholders": 0,
        }
        if options.render_mode == "sample" and sample_data is None:
            self._warnings.append(
                "Sample render mode requested without sample data; placeholders were used"
            )
        self._use_sample = options.render_mode != "placeholder" and (
            sample_data is not None or options.render_mode == "sample"
        )

    @property
    def warnings(self) -> list[str]:
        return self._warnings

    @property
    def stats(self) -> dict[str, int]:
        return dict(self._stats)

    # ------------------------------------------------------------------ setup
    def render(self) -> DocxDocumentType:
        doc = DocxDocument()
        self._apply_page_settings(doc)
        self._apply_core_properties(doc)

        first_section = self._document.sections[0]
        self._render_header_footer(doc, first_section, is_header=True)
        self._render_header_footer(doc, first_section, is_header=False)

        context = SampleContext(sample=self._sample or {}, schema=self._schema, scope=Scope())
        for index, section in enumerate(self._document.sections):
            if index:
                doc.add_page_break()
                if section.header or section.footer:
                    self._warnings.append(
                        "Headers and footers of secondary sections are not rendered "
                        "(single Word section output)"
                    )
            self._render_blocks(doc, section.body, context)

        if self._options.include_compatibility_stamp:
            doc.add_paragraph()
            paragraph = doc.add_paragraph()
            paragraph.add_run(
                "Generic DOCX generated by Docentric Copilot. "
                "Docentric AX compatibility: not verified."
            ).italic = True
        return doc

    def _apply_page_settings(self, doc: DocxDocumentType) -> None:
        page = self._document.page
        width, height = _PAGE_SIZES[page.size]
        if self._oriented:
            width, height = height, width
        for section in doc.sections:
            section.page_width = Mm(width)
            section.page_height = Mm(height)
            section.top_margin = Mm(page.margin_top_mm)
            section.right_margin = Mm(page.margin_right_mm)
            section.bottom_margin = Mm(page.margin_bottom_mm)
            section.left_margin = Mm(page.margin_left_mm)

    def _apply_core_properties(self, doc: DocxDocumentType) -> None:
        metadata = self._document.metadata
        props = doc.core_properties
        props.title = self._document.title
        props.subject = metadata.template_name
        props.author = "Docentric Copilot"
        props.last_modified_by = "Docentric Copilot"
        props.comments = (
            "Generated by Docentric Copilot. This is a generic DOCX document; "
            "Docentric AX compatibility is not verified (status: not_tested)."
        )
        props.keywords = (
            f"docentric-copilot;ir={self._document.ir_version};"
            f"target={self._document.target.value};"
            f"schema={metadata.source_schema_id};digest={ir_digest(self._document)[:32]};"
            "docentric-compatibility=not_tested"
        )
        props.category = f"template/{metadata.template_name}"
        props.created = FIXED_DATETIME
        props.modified = FIXED_DATETIME
        props.revision = 1
        props.language = self._document.language

    def _render_header_footer(
        self, doc: DocxDocumentType, section: Section, *, is_header: bool
    ) -> None:
        blocks = section.header if is_header else section.footer
        if not blocks:
            return
        word_section = doc.sections[0]
        container = word_section.header if is_header else word_section.footer
        context = SampleContext(sample=self._sample or {}, schema=self._schema, scope=Scope())
        first = True
        for block in blocks:
            if isinstance(block, Paragraph | Heading | ImageBinding):
                self._render_block(container, block, context, first_paragraph=first)
                first = False
            else:
                self._warnings.append(
                    f"Block kind '{block.kind}' is not supported in headers/footers and was skipped"
                )

    # ---------------------------------------------------------------- blocks
    def _render_blocks(
        self,
        container: Any,
        blocks: list[Block],
        context: SampleContext,
        *,
        first_paragraph: bool = False,
    ) -> None:
        for block in blocks:
            self._render_block(container, block, context, first_paragraph=first_paragraph)
            first_paragraph = False

    def _render_block(
        self,
        container: Any,
        block: Block,
        context: SampleContext,
        *,
        first_paragraph: bool = False,
    ) -> None:
        if isinstance(block, Paragraph):
            self._render_paragraph(container, block, context, first_paragraph=first_paragraph)
        elif isinstance(block, Heading):
            self._render_heading(container, block, context, first_paragraph=first_paragraph)
        elif isinstance(block, ImageBinding):
            self._render_image(container, block, context, first_paragraph=first_paragraph)
        elif isinstance(block, Repeat):
            self._render_repeat(container, block, context)
        elif isinstance(block, Conditional):
            self._render_conditional(container, block, context)
        elif isinstance(block, Table):
            self._render_table(container, block, context)
        else:  # pragma: no cover - defensive against future block kinds
            raise CompilationFailedError(f"Unsupported block kind: {getattr(block, 'kind', '?')}")

    def _new_paragraph(self, container: Any, *, first_paragraph: bool) -> Any:
        if first_paragraph and hasattr(container, "paragraphs") and container.paragraphs:
            return container.paragraphs[0]
        self._stats["paragraphs"] += 1
        return container.add_paragraph()

    def _render_paragraph(
        self,
        container: Any,
        block: Paragraph,
        context: SampleContext,
        *,
        first_paragraph: bool,
    ) -> None:
        paragraph = self._new_paragraph(container, first_paragraph=first_paragraph)
        self._apply_paragraph_style(paragraph, block.style)
        if block.space_after_pt is not None:
            paragraph.paragraph_format.space_after = Pt(block.space_after_pt)
        for run in block.runs:
            if isinstance(run, FieldBinding):
                text = self._binding_text(run, context)
                added = paragraph.add_run(text)
                self._apply_run_style(added, run.style)
            else:
                added = paragraph.add_run(run.text)
                self._apply_run_style(added, run.style)

    def _render_heading(
        self,
        container: Any,
        block: Heading,
        context: SampleContext,
        *,
        first_paragraph: bool,
    ) -> None:
        if first_paragraph and hasattr(container, "paragraphs") and container.paragraphs:
            paragraph = container.paragraphs[0]
            self._stats["paragraphs"] += 1
        else:
            self._stats["paragraphs"] += 1
            paragraph = container.add_paragraph()
        paragraph.style = f"Heading {block.level}"
        self._apply_paragraph_style(paragraph, block.style)
        for run in block.runs:
            if isinstance(run, FieldBinding):
                added = paragraph.add_run(self._binding_text(run, context))
                self._apply_run_style(added, run.style)
            else:
                added = paragraph.add_run(run.text)
                self._apply_run_style(added, run.style)

    def _render_image(
        self,
        container: Any,
        block: ImageBinding,
        context: SampleContext,
        *,
        first_paragraph: bool,
    ) -> None:
        value = context.value(block.path) if self._use_sample else None
        payload = _decode_image(value)
        paragraph = self._new_paragraph(container, first_paragraph=first_paragraph)
        if block.alignment:
            paragraph.alignment = _ALIGN[block.alignment]
        if payload is None:
            placeholder = f"[[{block.path}]]"
            paragraph.add_run(f"{placeholder}").italic = True
            self._stats["placeholders"] += 1
            if value is not None:
                self._warnings.append(
                    f"Image value for '{block.path}' is not a decodable PNG/JPEG/GIF payload"
                )
            return
        run = paragraph.add_run()
        try:
            if block.width_mm:
                run.add_picture(io.BytesIO(payload), width=Mm(block.width_mm))
            elif block.height_mm:
                run.add_picture(io.BytesIO(payload), height=Mm(block.height_mm))
            else:
                run.add_picture(io.BytesIO(payload), width=Mm(42))
            self._stats["images"] += 1
        except Exception:
            paragraph.add_run(f"[[{block.path}]]").italic = True
            self._stats["placeholders"] += 1
            self._warnings.append(f"Image for '{block.path}' could not be embedded")

    def _render_repeat(self, container: Any, block: Repeat, context: SampleContext) -> None:
        try:
            collection = resolve_collection(self._schema, block.path, context.scope)
        except PathResolutionError as exc:
            raise CompilationFailedError(
                "Repeat block references an unknown collection",
                details={"path": block.path, "reason": exc.message},
            ) from exc
        items = context.collection(block.path) if self._use_sample else []
        if not self._use_sample:
            self._render_blocks(container, block.blocks, context)
            return
        if not items:
            if block.empty_message:
                paragraph = container.add_paragraph()
                paragraph.add_run(block.empty_message).italic = True
            return
        limit = min(len(items), block.max_items or self._options.max_repeat_items)
        if limit < len(items):
            self._warnings.append(
                f"Repeat '{block.path}' truncated to {limit} items (limit {self._options.max_repeat_items})"
            )
        for item in items[:limit]:
            self._stats["repeats_expanded"] += 1
            child = context.child(block.alias, collection.absolute, item)
            self._render_blocks(container, block.blocks, child)

    def _render_conditional(
        self, container: Any, block: Conditional, context: SampleContext
    ) -> None:
        if not self._use_sample:
            self._render_blocks(container, block.then_blocks, context)
            self._warnings.append(
                "Conditional content was rendered without data because no sample data was supplied"
            )
            return
        if evaluate(block.condition, context):
            self._render_blocks(container, block.then_blocks, context)
        elif block.else_blocks:
            self._render_blocks(container, block.else_blocks, context)

    def _render_table(self, container: Any, block: Table, context: SampleContext) -> None:
        if not hasattr(container, "add_table"):
            self._warnings.append("Tables are not supported in this container and were skipped")
            return
        self._stats["tables"] += 1
        table: DocxTable = container.add_table(rows=0, cols=len(block.columns))
        table.autofit = False
        if block.style and block.style.borders:
            table.style = "Table Grid"

        if block.show_header:
            header_row = table.add_row()
            for index, column in enumerate(block.columns):
                cell = header_row.cells[index]
                paragraph = cell.paragraphs[0]
                run = paragraph.add_run(column.header)
                run.bold = True
                if block.style and block.style.font_size_pt:
                    run.font.size = Pt(block.style.font_size_pt)
                if column.alignment:
                    paragraph.alignment = _ALIGN[column.alignment]
                if block.style and block.style.header_background:
                    _shade_cell(cell, block.style.header_background)
                if column.width_mm is not None:
                    cell.width = Mm(float(column.width_mm))

        for row in block.rows:
            docx_row = table.add_row()
            for index, source_cell in enumerate(row.cells):
                self._render_cell(docx_row.cells[index], source_cell, context)
                column_width = block.columns[index].width_mm
                if column_width is not None:
                    docx_row.cells[index].width = Mm(float(column_width))

        if block.repeat is not None and block.row_template is not None:
            try:
                collection = resolve_collection(self._schema, block.repeat.path, context.scope)
            except PathResolutionError as exc:
                raise CompilationFailedError(
                    "Table repeat references an unknown collection",
                    details={"path": block.repeat.path, "reason": exc.message},
                ) from exc
            items = context.collection(block.repeat.path) if self._use_sample else []
            limit = min(len(items), block.repeat.max_items or self._options.max_repeat_items)
            if self._use_sample and limit < len(items):
                self._warnings.append(
                    f"Table repeat '{block.repeat.path}' truncated to {limit} items"
                )
            if self._use_sample and not items:
                self._warnings.append(f"Table repeat '{block.repeat.path}' produced no rows")
            for position, item in enumerate(items[:limit] if self._use_sample else []):
                docx_row = table.add_row()
                self._stats["repeats_expanded"] += 1
                child = context.child(block.repeat.alias, collection.absolute, item)
                for index, template_cell in enumerate(block.row_template):
                    self._render_cell(docx_row.cells[index], template_cell, child)
                    template_width = block.columns[index].width_mm
                    if template_width is not None:
                        docx_row.cells[index].width = Mm(float(template_width))
                    elif block.style and block.style.zebra and position % 2 == 1:
                        _shade_cell(docx_row.cells[index], "F7F9FC")

    def _render_cell(self, docx_cell: _Cell, source: Cell, context: SampleContext) -> None:
        docx_cell.paragraphs[0].text = ""
        self._render_blocks(docx_cell, source.blocks, context, first_paragraph=True)

    # ---------------------------------------------------------------- styles
    def _binding_text(self, binding: FieldBinding, context: SampleContext) -> str:
        if not self._use_sample:
            self._stats["placeholders"] += 1
            return f"[[{binding.path}]]"
        value = context.value(binding.path)
        if value is None:
            self._stats["placeholders"] += 1
            return f"[[{binding.path}]]"
        self._stats["bindings_rendered"] += 1
        return format_value(value, binding)

    def _apply_paragraph_style(self, paragraph: Any, style: TextStyle | None) -> None:
        if style is None:
            return
        if style.alignment is not None:
            paragraph.alignment = _ALIGN[style.alignment]

    def _apply_run_style(self, run: Any, style: TextStyle | None) -> None:
        if style is None:
            return
        if style.bold is not None:
            run.bold = style.bold
        if style.italic is not None:
            run.italic = style.italic
        if style.underline is not None:
            run.underline = style.underline
        if style.font_size_pt is not None:
            run.font.size = Pt(style.font_size_pt)
        if style.color is not None:
            run.font.color.rgb = RGBColor.from_string(style.color.lstrip("#").upper())


def _shade_cell(cell: _Cell, hex_color: str) -> None:
    color = hex_color.lstrip("#").upper()
    cell._tc.get_or_add_tcPr().append(
        parse_xml(rf'<w:shd {nsdecls("w")} w:val="clear" w:color="auto" w:fill="{color}"/>')
    )


def _decode_image(value: Any) -> bytes | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.startswith("data:"):
        header, _, payload = raw.partition(",")
        if "base64" not in header:
            return None
    else:
        payload = raw
    compact = re.sub(r"\s+", "", payload)
    try:
        data = base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError):
        return None
    if not data or len(data) > MAX_IMAGE_BYTES:
        return None
    if not data.startswith(_IMAGE_MAGIC):
        return None
    return data


class DocentricAXCompiler:
    """Placeholder for the gated Docentric AX adapter (never enabled by default)."""

    name = "docentric-ax"
    target = CompileTarget.DOCENTRIC_AX
    verified_compatibility = False
    gate_status = "blocked: feasibility gate M0 has not been passed"

    def compile(  # pragma: no cover - always raises
        self,
        template: Document,
        schema: NormalizedSchema,
        options: CompileOptions | None = None,
        *,
        sample_data: dict[str, Any] | None = None,
    ) -> CompilationResult:
        raise UnsupportedTargetError(
            "The Docentric AX compiler is not available: autonomous generation of "
            "Docentric tagging elements has not been verified in a licensed environment",
            details={
                "target": CompileTarget.DOCENTRIC_AX.value,
                "gate": self.gate_status,
                "documentation": "docs/DOCENTRIC_AX_COMPATIBILITY.md",
            },
        )


__all__ = [
    "CompilationResult",
    "CompileOptions",
    "DocentricAXCompiler",
    "GenericDocxCompiler",
]
