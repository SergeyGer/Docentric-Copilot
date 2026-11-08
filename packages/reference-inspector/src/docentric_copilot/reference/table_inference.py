"""Deterministic DOCX table inference for the Reference -> IR projection.

The ReferenceGraph is control-centric: it proves bindings, but it does not carry
Word table geometry. This module reads the bounded DOCX payload for one
document, maps content-control ordinals back to the projected elements, and
builds the Generic Template IR ``Table`` contract:

* a static header row becomes ``Table.columns``;
* a row with evidence-backed bindings becomes ``Table.row_template``;
* the collection is inferred only from a schema path that the projection marks
  as a collection — similar field names alone are never enough;
* static footer/extra rows are preserved as static rows where the IR supports
  them; unsupported geometry becomes an explicit, blocking diagnostic;
* nested tables are inferred recursively, including a nested collection when
  its path is under the outer row's collection scope.

Strict mode is enforced by the caller: any ``blocking`` diagnostic refuses the
import unless ``allow_unsupported=True``. Nothing is silently dropped.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace

from docentric_copilot.template_ir import (
    Alignment,
    Block,
    Cell,
    Conditional,
    Expression,
    ExpressionOperator,
    FieldBinding,
    ImageBinding,
    Paragraph,
    Table,
    TableColumn,
    TableRepeat,
    TableRow,
    TextRun,
)
from lxml import etree
from pydantic import BaseModel, ConfigDict, Field

from .projection import ProjectionElement

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_TABLE_PART = "word/document.xml"
_MAX_TABLE_BYTES = 50 * 1024 * 1024
_MAX_ROWS = 500
_MAX_COLUMNS = 20


def _q(tag: str) -> str:
    return f"{{{_W}}}{tag}"


class TableDiagnostic(BaseModel):
    """One explicit table inference finding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=400)
    part: str = Field(default=_TABLE_PART, max_length=240)
    table_ordinal: int | None = Field(default=None, ge=0)
    blocking: bool = False


@dataclass(frozen=True)
class TableOutcome:
    """One top-level table's acceptance decision and reason codes."""

    index: int
    accepted: bool
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class InferredTable:
    table: Table
    ordinals: frozenset[int]
    provenance: tuple[tuple[str, str], ...] = ()


@dataclass
class TableInferenceResult:
    tables: list[InferredTable] = field(default_factory=list)
    diagnostics: list[TableDiagnostic] = field(default_factory=list)
    outcomes: list[TableOutcome] = field(default_factory=list)
    ordinals: set[tuple[str, int]] = field(default_factory=set)

    @property
    def blocking(self) -> bool:
        return any(item.blocking for item in self.diagnostics)


@dataclass(frozen=True)
class _CellData:
    blocks: list[Block]
    text: str
    controls: tuple[ProjectionElement, ...]
    ordinals: frozenset[int]
    nested: tuple[InferredTable, ...] = ()
    nested_elements: tuple[etree._Element, ...] = ()


@dataclass(frozen=True)
class _RowData:
    cells: tuple[_CellData, ...]
    ordinals: frozenset[int]

    @property
    def controls(self) -> tuple[ProjectionElement, ...]:
        return tuple(control for cell in self.cells for control in cell.controls)

    @property
    def text(self) -> str:
        return " ".join(cell.text for cell in self.cells).strip()


def _parse_xml(payload: bytes) -> etree._Element:
    if not payload or len(payload) > _MAX_TABLE_BYTES:
        raise ValueError("DOCX payload is empty or too large for table inference")
    with zipfile.ZipFile(io.BytesIO(payload)) as package:
        xml = package.read(_TABLE_PART)
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    return etree.fromstring(xml, parser=parser)


def _cell_text(cell: etree._Element) -> str:
    parts: list[str] = []
    for paragraph in cell.findall(_q("p")):
        for node in paragraph.iter():
            if node.tag == _q("t") and node.text:
                parts.append(node.text)
    return " ".join("".join(parts).split())


def _paragraph_blocks(
    cell: etree._Element,
    by_ordinal: dict[int, ProjectionElement],
    rewrite: Callable[[str], str | None],
    *,
    skip_kinds: frozenset[str] = frozenset(),
) -> list[Block]:
    blocks: list[Block] = []
    for paragraph in cell.findall(_q("p")):
        controls: list[ProjectionElement] = []
        for sdt in paragraph.iter(_q("sdt")):
            ordinal = sdt.get("__dc_ordinal")
            if ordinal is None:
                continue
            element = by_ordinal.get(int(ordinal))
            if element is not None and element.kind.value not in skip_kinds:
                controls.append(element)
        if controls:
            for element in controls:
                block = _element_block(element, rewrite)
                if block is not None:
                    blocks.append(block)
        else:
            text = "".join(node.text or "" for node in paragraph.iter(_q("t")))
            text = " ".join(text.split())
            if text:
                blocks.append(Paragraph(runs=[TextRun(text=text)]))
    return blocks


def _element_block(
    element: ProjectionElement, rewrite: Callable[[str], str | None]
) -> Block | None:
    if element.kind.value == "image":
        path = element.schema_path or element.binding_path
        if not path:
            return None
        rewritten = rewrite(path)
        if rewritten is None:
            return None
        return ImageBinding(path=rewritten, alt_text=element.display_label, width_mm=32)
    if element.kind.value in {"field", "label"}:
        path = element.schema_path or element.binding_path
        if element.kind.value == "label" or not path:
            return Paragraph(runs=[TextRun(text=element.display_label)])
        rewritten = rewrite(path)
        if rewritten is None:
            return None
        return Paragraph(runs=[FieldBinding(path=rewritten)])
    return Paragraph(runs=[TextRun(text=element.display_label)])


def _collection_for(
    controls: Sequence[ProjectionElement], collection_paths: set[str]
) -> str | None:
    paths: list[str] = []
    for element in controls:
        value = element.schema_path or element.binding_path
        if value:
            paths.append(value)
    if not paths:
        return None
    matches = [
        path for path in collection_paths if all(item.startswith(f"{path}.") for item in paths)
    ]
    if not matches:
        return None
    return max(matches, key=len)


def _alias(path: str) -> str:
    segment = path.rsplit(".", 1)[-1].casefold()
    cleaned = "".join(character for character in segment if character.isalnum() or character == "_")
    if not cleaned:
        cleaned = "row"
    if not cleaned[0].isalpha():
        cleaned = f"row_{cleaned}"
    return cleaned[:31]


def _sanitize_path(path: str) -> str:
    """Convert a provider path (slash/XPath style) to a Template IR path."""
    segments: list[str] = []
    for raw in re.split(r"[./\\]+", path.strip()):
        if not raw:
            continue
        if raw.startswith("@"):
            raw = raw[1:]
        cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", raw).strip("_")
        if not cleaned:
            continue
        if not (cleaned[0].isalpha() or cleaned[0] == "_"):
            cleaned = f"_{cleaned}"
        segments.append(cleaned)
    return ".".join(segments)


def _rewriter(
    *,
    collection: str | None,
    alias: str | None,
    outer_collection: str | None = None,
    outer_alias: str | None = None,
) -> Callable[[str], str | None]:
    def rewrite(path: str) -> str | None:
        current = path
        if outer_collection and outer_alias and current.startswith(f"{outer_collection}."):
            current = f"{outer_alias}.{_sanitize_path(current[len(outer_collection) + 1 :])}"
        if collection and alias:
            if not current.startswith(f"{collection}."):
                return _sanitize_path(current)
            return f"{alias}.{_sanitize_path(current[len(collection) + 1 :])}"
        return _sanitize_path(current)

    return rewrite


class _TableParser:
    def __init__(
        self,
        elements: Sequence[ProjectionElement],
        diagnostics: list[TableDiagnostic],
        collection_paths: set[str] | None = None,
    ) -> None:
        self._by_ordinal = {element.source_location.ordinal: element for element in elements}
        self._collection_paths = collection_paths or {
            element.schema_path
            for element in elements
            if element.collection and element.schema_path
        }
        self._diagnostics = diagnostics
        self._table_ordinal = 0

    def parse(self, payload: bytes) -> TableInferenceResult:
        root = _parse_xml(payload)
        for ordinal, sdt in enumerate(root.iter(_q("sdt"))):
            sdt.set("__dc_ordinal", str(ordinal))
        result = TableInferenceResult()
        table_index = 0
        body = root.find(_q("body"))
        top_level_tables = body.findall(_q("tbl")) if body is not None else []
        for table_element in top_level_tables:
            if self._is_nested(table_element):
                continue
            before = len(self._diagnostics)
            inferred = self._parse_table(table_element, outer=None)
            new_codes = tuple(sorted({item.code for item in self._diagnostics[before:]}))
            result.outcomes.append(
                TableOutcome(
                    index=table_index,
                    accepted=inferred is not None,
                    reason_codes=() if inferred is not None else new_codes,
                )
            )
            table_index += 1
            if inferred is not None:
                result.tables.append(inferred)
        for item in result.tables:
            result.ordinals.update((_TABLE_PART, ordinal) for ordinal in item.ordinals)
        result.diagnostics = self._diagnostics
        return result

    @staticmethod
    def _is_nested(table: etree._Element) -> bool:
        parent = table.getparent()
        while parent is not None:
            if parent.tag == _q("tc"):
                return True
            if parent.tag == _q("tbl"):
                return True
            parent = parent.getparent()
        return False

    def _parse_table(
        self,
        table_element: etree._Element,
        *,
        outer: tuple[str, str] | None,
    ) -> InferredTable | None:
        self._table_ordinal += 1
        table_ordinal = self._table_ordinal
        row_elements = list(table_element.findall(_q("tr")))
        if not row_elements:
            self._diagnostics.append(
                TableDiagnostic(
                    code="TABLE_EMPTY",
                    message="A table has no rows and was skipped.",
                    table_ordinal=table_ordinal,
                    blocking=True,
                )
            )
            return None
        for row_element in row_elements:
            for cell_element in row_element.findall(_q("tc")):
                properties = cell_element.find(_q("tcPr"))
                if properties is not None and (
                    properties.find(_q("gridSpan")) is not None
                    or properties.find(_q("vMerge")) is not None
                ):
                    self._diagnostics.append(
                        TableDiagnostic(
                            code="TABLE_MERGED_OR_RAGGED",
                            message=(
                                "Merged table cells are not inferred; the table is listed as "
                                "deliberately unsupported."
                            ),
                            table_ordinal=table_ordinal,
                            blocking=True,
                        )
                    )
                    return None
        rows: list[_RowData] = []
        for row_element in row_elements:
            cells = [
                self._parse_cell(cell, table_ordinal=table_ordinal, outer=outer)
                for cell in row_element.findall(_q("tc"))
            ]
            if not cells:
                self._diagnostics.append(
                    TableDiagnostic(
                        code="TABLE_ROW_EMPTY",
                        message="A table row has no cells and was skipped.",
                        table_ordinal=table_ordinal,
                        blocking=True,
                    )
                )
                return None
            rows.append(
                _RowData(
                    cells=tuple(cells),
                    ordinals=frozenset(ordinal for cell in cells for ordinal in cell.ordinals),
                )
            )
        widths = {len(row.cells) for row in rows}
        if len(widths) != 1:
            self._diagnostics.append(
                TableDiagnostic(
                    code="TABLE_MERGED_OR_RAGGED",
                    message="Merged or ragged table cells are not inferred; the table was skipped.",
                    table_ordinal=table_ordinal,
                    blocking=True,
                )
            )
            return None
        column_count = widths.pop()
        if column_count > _MAX_COLUMNS:
            self._diagnostics.append(
                TableDiagnostic(
                    code="TABLE_TOO_WIDE",
                    message=f"Table has {column_count} columns; the IR limit is {_MAX_COLUMNS}.",
                    table_ordinal=table_ordinal,
                    blocking=True,
                )
            )
            return None
        data_index = next(
            (index for index, row in enumerate(rows) if row.controls),
            None,
        )
        if data_index is None:
            return self._static_table(rows, table_ordinal=table_ordinal)
        if data_index != 1 and data_index != 0:
            self._diagnostics.append(
                TableDiagnostic(
                    code="TABLE_HEADER_AMBIGUOUS",
                    message=(
                        "More than one static row precedes the first bound row; the table "
                        "header is ambiguous."
                    ),
                    table_ordinal=table_ordinal,
                    blocking=True,
                )
            )
            return None
        metadata_row = rows[0] if data_index == 1 else None
        data_row = rows[data_index]
        trailing = rows[data_index + 1 :]
        if any(row.controls for row in trailing):
            self._diagnostics.append(
                TableDiagnostic(
                    code="TABLE_MULTIPLE_REPEATED_ROWS",
                    message=(
                        "More than one bound row shape follows the header; only the first "
                        "repeated row is represented and the rest are listed as unsupported."
                    ),
                    table_ordinal=table_ordinal,
                    blocking=True,
                )
            )
            trailing = [row for row in trailing if not row.controls]
        collection_raw = _collection_for(data_row.controls, self._collection_paths)
        if collection_raw is None:
            self._diagnostics.append(
                TableDiagnostic(
                    code="TABLE_COLLECTION_NOT_EVIDENCED",
                    message=(
                        "The bound row has no schema-backed collection scope; it is kept as "
                        "a static row, not a Repeat."
                    ),
                    table_ordinal=table_ordinal,
                    blocking=True,
                )
            )
            return None
        if outer is not None:
            outer_raw, outer_alias = outer
            if collection_raw.startswith(f"{outer_raw}."):
                collection = f"{outer_alias}.{_sanitize_path(collection_raw[len(outer_raw) + 1 :])}"
            else:
                self._diagnostics.append(
                    TableDiagnostic(
                        code="TABLE_NESTED_REPEAT_UNSUPPORTED",
                        message=(
                            "A nested repeated table is not under the outer row collection; "
                            "it is listed as unsupported."
                        ),
                        table_ordinal=table_ordinal,
                        blocking=True,
                    )
                )
                return None
        else:
            collection = _sanitize_path(collection_raw)
        alias = _alias(collection)
        rewrite = _rewriter(collection=collection, alias=alias)
        data_row = self._attach_nested(
            data_row, outer=(collection_raw, alias), table_ordinal=table_ordinal
        )
        headers = (
            [cell.text for cell in metadata_row.cells]
            if metadata_row is not None
            else [control.display_label for control in data_row.controls]
        )
        headers = [header or f"Column {index + 1}" for index, header in enumerate(headers)]
        # Rebuild bound cell blocks with alias-relative paths. Conditional
        # cells keep their condition and then/else blocks.
        template = [Cell(blocks=self._relative_blocks(cell, rewrite)) for cell in data_row.cells]
        width_mm = round(180.0 / column_count, 1)
        table = Table(
            columns=[
                TableColumn(header=header, width_mm=width_mm, alignment=Alignment.LEFT)
                for header in headers
            ],
            footer_rows=[
                TableRow(cells=[Cell(blocks=cell.blocks) for cell in row.cells]) for row in trailing
            ],
            repeat=TableRepeat(path=collection, alias=alias),
            row_template=template,
            show_header=True,
        )
        return InferredTable(
            table=table,
            ordinals=(
                data_row.ordinals
                | (metadata_row.ordinals if metadata_row else frozenset())
                | frozenset(ordinal for row in trailing for ordinal in row.ordinals)
            ),
            provenance=(
                (f"table:{table_ordinal}", collection),
                (f"table:{table_ordinal}.header", "static-header"),
                (f"table:{table_ordinal}.repeat", collection),
            ),
        )

    def _relative_blocks(
        self, cell: _CellData, rewrite: Callable[[str], str | None]
    ) -> list[Block]:
        blocks = _relativize_blocks(cell.blocks, rewrite)
        blocks.extend(nested.table for nested in cell.nested)
        return blocks

    def _parse_cell(
        self,
        cell: etree._Element,
        *,
        table_ordinal: int,
        outer: tuple[str, str] | None,
    ) -> _CellData:
        ordinals: set[int] = set()
        for paragraph in cell.findall(_q("p")):
            for sdt in paragraph.iter(_q("sdt")):
                raw = sdt.get("__dc_ordinal")
                if raw is not None:
                    ordinals.add(int(raw))
        controls = tuple(
            element
            for ordinal in sorted(ordinals)
            if (element := self._by_ordinal.get(ordinal)) is not None
        )
        if_elements = [element for element in controls if element.kind.value == "if"]
        for element in controls:
            if element.kind.value == "list":
                self._diagnostics.append(
                    TableDiagnostic(
                        code="TABLE_CELL_STRUCTURE_UNSUPPORTED",
                        message=(
                            f"Cell control '{element.display_label}' (list) needs a nested "
                            "repeat cell, which is not inferred in v0.13."
                        ),
                        table_ordinal=table_ordinal,
                        blocking=False,
                    )
                )
        rewrite = _rewriter(
            collection=outer[0] if outer else None,
            alias=outer[1] if outer else None,
        )
        blocks = _paragraph_blocks(
            cell,
            self._by_ordinal,
            rewrite,
            skip_kinds=frozenset({"if"}),
        )
        if if_elements and blocks:
            condition_path = if_elements[0].schema_path or if_elements[0].binding_path
            if condition_path:
                condition_field = rewrite(condition_path) or _sanitize_path(condition_path)
                blocks = [
                    Conditional(
                        condition=Expression(
                            operator=ExpressionOperator.NOT_NULL,
                            field=condition_field,
                        ),
                        then_blocks=blocks,
                    )
                ]
        return _CellData(
            blocks=blocks,
            text=_cell_text(cell),
            controls=controls,
            ordinals=frozenset(ordinals),
            nested_elements=tuple(cell.findall(_q("tbl"))),
        )

    def _attach_nested(
        self,
        row: _RowData,
        *,
        outer: tuple[str, str] | None,
        table_ordinal: int,
    ) -> _RowData:
        cells: list[_CellData] = []
        for cell in row.cells:
            nested: list[InferredTable] = []
            for nested_element in cell.nested_elements:
                nested_result = self._parse_table(nested_element, outer=outer)
                if nested_result is not None:
                    nested.append(nested_result)
            ordinals = set(cell.ordinals)
            for nested_table in nested:
                ordinals.update(nested_table.ordinals)
            cells.append(
                replace(
                    cell,
                    nested=tuple(nested),
                    ordinals=frozenset(ordinals),
                )
            )
        return _RowData(
            cells=tuple(cells),
            ordinals=frozenset(ordinal for cell in cells for ordinal in cell.ordinals),
        )

    def _static_table(self, rows: list[_RowData], *, table_ordinal: int) -> InferredTable:
        rows = [self._attach_nested(row, outer=None, table_ordinal=table_ordinal) for row in rows]
        column_count = len(rows[0].cells)
        headers = [cell.text or f"Column {index + 1}" for index, cell in enumerate(rows[0].cells)]
        table = Table(
            columns=[
                TableColumn(header=header, width_mm=round(180.0 / column_count, 1))
                for header in headers
            ],
            rows=[
                TableRow(cells=[Cell(blocks=cell.blocks) for cell in row.cells]) for row in rows[1:]
            ],
            show_header=True,
        )
        return InferredTable(
            table=table,
            ordinals=frozenset(ordinal for row in rows for ordinal in row.ordinals),
            provenance=((f"table:{table_ordinal}", "static-table"),),
        )


def _relativize_blocks(
    blocks: Sequence[Block], rewrite: Callable[[str], str | None]
) -> list[Block]:
    result: list[Block] = []
    for block in blocks:
        if isinstance(block, Paragraph):
            runs: list[TextRun | FieldBinding] = []
            for run in block.runs:
                if isinstance(run, FieldBinding):
                    path = rewrite(run.path)
                    if path is None:
                        continue
                    runs.append(run.model_copy(update={"path": path}))
                else:
                    runs.append(run)
            if runs:
                result.append(block.model_copy(update={"runs": runs}))
        elif isinstance(block, ImageBinding):
            if block.source.value != "schema":
                result.append(block)
                continue
            path = rewrite(block.path)
            if path is not None:
                result.append(block.model_copy(update={"path": path}))
        elif isinstance(block, Conditional):
            field = block.condition.field
            new_condition = block.condition
            if field:
                rewritten = rewrite(field)
                if rewritten is not None:
                    new_condition = block.condition.model_copy(update={"field": rewritten})
            result.append(
                block.model_copy(
                    update={
                        "condition": new_condition,
                        "then_blocks": _relativize_blocks(block.then_blocks, rewrite),
                        "else_blocks": _relativize_blocks(block.else_blocks or [], rewrite) or None,
                    }
                )
            )
        else:
            result.append(block)
    return result


def infer_tables(
    payload: bytes,
    elements: Sequence[ProjectionElement],
    *,
    collection_paths: set[str] | None = None,
) -> TableInferenceResult:
    """Infer generic-IR tables from one DOCX payload and its projected elements."""
    return _TableParser(elements, [], collection_paths=collection_paths).parse(payload)


__all__ = [
    "InferredTable",
    "TableDiagnostic",
    "TableInferenceResult",
    "TableOutcome",
    "infer_tables",
]
