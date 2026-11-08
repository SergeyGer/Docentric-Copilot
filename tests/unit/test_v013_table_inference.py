"""V013-03: deterministic reference-to-IR table inference."""

from __future__ import annotations

import io

from docentric_copilot.reference.docx_controls import ElementKind
from docentric_copilot.reference.graph import GraphStatus
from docentric_copilot.reference.projection import (
    ProjectionElement,
    ReferenceCapability,
    SourceLocation,
)
from docentric_copilot.reference.table_inference import infer_tables
from docx import Document as DocxDocument
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls


def _sdt(text: str) -> object:
    return parse_xml(
        f'<w:sdt {nsdecls("w")}><w:sdtPr><w:tag w:val="field"/></w:sdtPr>'
        f"<w:sdtContent><w:r><w:t>{text}</w:t></w:r></w:sdtContent></w:sdt>"
    )


def _docx_with_table(*, controls: bool = True, nested: bool = False, rows: int = 2) -> bytes:
    document = DocxDocument()
    table = document.add_table(rows=rows, cols=2)
    table.cell(0, 0).text = "SKU"
    table.cell(0, 1).text = "Amount"
    if controls:
        for column, value in enumerate(("A-1", "10.00")):
            paragraph = table.cell(1, column).paragraphs[0]
            paragraph._p.append(_sdt(value))
        for row in range(2, rows):
            for column, value in enumerate((f"A-{row}", f"{row}0.00")):
                paragraph = table.cell(row, column).paragraphs[0]
                paragraph._p.append(_sdt(value))
    if nested:
        nested_table = table.cell(1, 0).add_table(rows=2, cols=1)
        nested_table.cell(0, 0).text = "Task"
        nested_table.cell(1, 0).text = "Done"
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _element(
    ordinal: int,
    path: str,
    *,
    collection: bool = False,
    label: str = "Field",
    kind: ElementKind = ElementKind.FIELD,
) -> ProjectionElement:
    return ProjectionElement(
        id=f"control:document:{ordinal}",
        display_label=label,
        kind=kind,
        binding_path=path,
        status=GraphStatus.RESOLVED,
        capability=ReferenceCapability.RESOLVED,
        source_location=SourceLocation(
            part="word/document.xml",
            ordinal=ordinal,
            paragraph_index=0,
        ),
        schema_path=path,
        data_type="string",
        collection=collection,
    )


def _elements() -> list[ProjectionElement]:
    return [
        _element(0, "MainData.Lines.Line.ItemId", label="SKU"),
        _element(1, "MainData.Lines.Line.Amount", label="Amount"),
        _element(99, "MainData.Lines.Line", collection=True, label="Lines"),
    ]


def _collection_paths(elements: list[ProjectionElement]) -> set[str]:
    return {
        element.schema_path for element in elements if element.collection and element.schema_path
    }


def test_header_and_repeated_row_become_a_table_repeat() -> None:
    elements = _elements()
    result = infer_tables(_docx_with_table(), elements)
    assert not result.diagnostics
    assert len(result.tables) == 1
    table = result.tables[0].table
    assert table.repeat is not None
    assert table.repeat.path == "MainData.Lines.Line"
    assert table.repeat.alias == "line"
    assert [column.header for column in table.columns] == ["SKU", "Amount"]
    assert table.row_template is not None
    assert len(table.row_template) == 2
    cell_text = table.row_template[0].blocks[0].model_dump(mode="json")
    assert "line.ItemId" in str(cell_text)
    assert result.ordinals == {("word/document.xml", 0), ("word/document.xml", 1)}


def test_static_table_has_no_repeat() -> None:
    result = infer_tables(_docx_with_table(controls=False), [])
    assert not result.diagnostics
    table = result.tables[0].table
    assert table.repeat is None
    assert table.row_template is None
    assert len(table.rows) == 1
    assert table.columns[0].header == "SKU"


def test_missing_collection_evidence_is_blocking_not_guessed() -> None:
    result = infer_tables(_docx_with_table(), _elements()[:2])
    assert not result.tables
    assert any(item.code == "TABLE_COLLECTION_NOT_EVIDENCED" for item in result.diagnostics)
    assert any(item.blocking for item in result.diagnostics)


def test_nested_table_is_preserved_in_the_cell() -> None:
    elements = _elements()
    result = infer_tables(_docx_with_table(nested=True), elements)
    assert result.tables
    # The nested static table is parsed recursively and attached to the row cell.
    table = result.tables[0].table
    assert table.row_template is not None
    nested_blocks = table.row_template[0].blocks
    assert any(getattr(block, "kind", "") == "table" for block in nested_blocks)


def test_import_integration_filters_table_controls_and_adds_table() -> None:
    import hashlib

    from docentric_copilot.reference.import_ir import project_to_template_ir
    from docentric_copilot.reference.inventory import PlatformHint, SourceType
    from docentric_copilot.reference.projection import (
        ProjectionSection,
        ProjectionSummary,
        ReferenceDocument,
    )

    payload = _docx_with_table()
    elements = _elements()
    digest = hashlib.sha256(payload).hexdigest()
    reference = ReferenceDocument(
        source_type=SourceType.DOCX,
        source_name="table.docx",
        source_sha256=digest,
        platform=PlatformHint.D365,
        sections=[
            ProjectionSection(
                name="table.docx",
                document_sha256=digest,
                elements=elements,
            )
        ],
        summary=ProjectionSummary(
            sections=1,
            elements=len(elements),
            resolved=len(elements),
            ambiguous=0,
            unknown=0,
            resolved_ratio=1.0,
            by_kind={"field": len(elements)},
            by_status={"resolved": len(elements)},
            by_capability={"resolved": len(elements)},
            lists=1,
            conditions=0,
            schema_fields=2,
        ),
    )
    result = project_to_template_ir(reference, allow_unsupported=True, docx_payload=payload)
    tables = [block for block in result.document.sections[0].body if block.kind == "table"]
    assert len(tables) == 1
    assert tables[0].repeat is not None
    assert tables[0].repeat.path == "MainData.Lines.Line"
    assert result.validation["statuses"]["semantic"] in {"passed", "warning"}


def _docx_with_optional_cell() -> bytes:
    document = DocxDocument()
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "SKU"
    table.cell(0, 1).text = "Note"
    table.cell(1, 0).paragraphs[0]._p.append(_sdt("A-1"))
    cell = table.cell(1, 1)
    cell.paragraphs[0]._p.append(_sdt("Show note"))
    cell.add_paragraph("Optional note")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_optional_cell_becomes_a_conditional() -> None:
    elements = [
        _element(0, "MainData.Lines.Line.ItemId", label="SKU"),
        _element(
            1,
            "MainData.Lines.Line.ShowNote",
            label="Show note",
            kind=ElementKind.IF,
        ),
        _element(99, "MainData.Lines.Line", collection=True, label="Lines"),
    ]
    result = infer_tables(_docx_with_optional_cell(), elements)
    assert result.tables
    table = result.tables[0].table
    assert table.row_template is not None
    blocks = table.row_template[1].blocks
    assert len(blocks) == 1
    assert blocks[0].kind == "conditional"
    assert blocks[0].condition.field == "line.ShowNote"
    assert any(getattr(block, "kind", "") == "paragraph" for block in blocks[0].then_blocks)


def test_extra_data_rows_are_diagnosed_not_silently_dropped() -> None:
    elements = [
        *_elements(),
        _element(2, "MainData.Lines.Line.ItemId", label="SKU"),
        _element(3, "MainData.Lines.Line.Amount", label="Amount"),
    ]
    result = infer_tables(_docx_with_table(rows=3), elements)
    assert result.tables
    assert any(
        item.code == "TABLE_MULTIPLE_REPEATED_ROWS" and item.blocking for item in result.diagnostics
    )


def test_static_row_after_data_becomes_a_footer_row() -> None:
    document = DocxDocument()
    table = document.add_table(rows=3, cols=2)
    table.cell(0, 0).text = "SKU"
    table.cell(0, 1).text = "Amount"
    table.cell(1, 0).paragraphs[0]._p.append(_sdt("A-1"))
    table.cell(1, 1).paragraphs[0]._p.append(_sdt("10.00"))
    table.cell(2, 0).text = "Total"
    table.cell(2, 1).text = "10.00"
    buffer = io.BytesIO()
    document.save(buffer)

    result = infer_tables(buffer.getvalue(), _elements())
    assert result.tables
    table_ir = result.tables[0].table
    assert table_ir.repeat is not None
    assert len(table_ir.footer_rows) == 1
    assert table_ir.footer_rows[0].cells[0].blocks[0].runs[0].text == "Total"


def test_footer_rows_render_after_the_repeated_rows(schema, sample_data) -> None:
    import io

    from docentric_copilot.docx_compiler import CompileOptions, GenericDocxCompiler
    from docentric_copilot.template_ir import (
        Cell,
        Document,
        DocumentMetadata,
        FieldBinding,
        Paragraph,
        Section,
        Table,
        TableColumn,
        TableRepeat,
        TableRow,
        TextRun,
    )

    document = Document(
        title="Footer rows",
        metadata=DocumentMetadata(
            template_name="footer_rows",
            source_schema_id=schema.schema_id,
        ),
        sections=[
            Section(
                name="Main",
                body=[
                    Table(
                        columns=[TableColumn(header="Item", width_mm=80)],
                        repeat=TableRepeat(path="MainData.QuotationLines.Line", alias="line"),
                        row_template=[
                            Cell(blocks=[Paragraph(runs=[FieldBinding(path="line.ItemId")])])
                        ],
                        footer_rows=[
                            TableRow(cells=[Cell(blocks=[Paragraph(runs=[TextRun(text="TOTAL")])])])
                        ],
                    )
                ],
            )
        ],
    )
    compiled = GenericDocxCompiler().compile(
        document,
        schema,
        CompileOptions(document_name="footer.docx"),
        sample_data=sample_data,
    )
    from docx import Document as DocxDocument

    rendered = DocxDocument(io.BytesIO(compiled.content))
    rows = [[cell.text for cell in row.cells] for row in rendered.tables[0].rows]
    assert rows[0] == ["Item"]
    assert rows[-1] == ["TOTAL"]
    assert len(rows) > 2


def test_nested_repeat_table_is_scoped_to_the_outer_row() -> None:
    document = DocxDocument()
    outer = document.add_table(rows=2, cols=1)
    outer.cell(0, 0).text = "Item"
    data_cell = outer.cell(1, 0)
    data_cell.paragraphs[0]._p.append(_sdt("A-1"))
    nested = data_cell.add_table(rows=2, cols=1)
    nested.cell(0, 0).text = "Task"
    nested.cell(1, 0).paragraphs[0]._p.append(_sdt("T-1"))
    buffer = io.BytesIO()
    document.save(buffer)

    elements = [
        _element(0, "MainData.Lines.Line.ItemId", label="SKU"),
        _element(1, "MainData.Lines.Line.Tasks.Task.TaskId", label="Task"),
        _element(99, "MainData.Lines.Line", collection=True, label="Lines"),
        _element(
            100,
            "MainData.Lines.Line.Tasks.Task",
            collection=True,
            label="Tasks",
        ),
    ]
    result = infer_tables(buffer.getvalue(), elements)
    assert result.tables
    outer_table = result.tables[0].table
    assert outer_table.row_template is not None
    nested_blocks = [
        block
        for block in outer_table.row_template[0].blocks
        if getattr(block, "kind", "") == "table"
    ]
    assert nested_blocks
    nested_table = nested_blocks[0]
    assert nested_table.repeat is not None
    assert nested_table.repeat.path == "line.Tasks.Task"
    assert nested_table.repeat.alias == "task"
    assert nested_table.row_template is not None
    assert "task.TaskId" in str(nested_table.row_template[0].blocks[0].model_dump(mode="json"))


def test_empty_collection_table_still_compiles_with_footer(schema, sample_data) -> None:
    from docentric_copilot.docx_compiler import CompileOptions, GenericDocxCompiler
    from docentric_copilot.template_ir import (
        Cell,
        Document,
        DocumentMetadata,
        FieldBinding,
        Paragraph,
        Section,
        Table,
        TableColumn,
        TableRepeat,
        TableRow,
        TextRun,
    )

    empty = {**sample_data, "MainData": {**sample_data["MainData"], "QuotationLines": {"Line": []}}}
    document = Document(
        title="Empty rows",
        metadata=DocumentMetadata(
            template_name="empty_rows",
            source_schema_id=schema.schema_id,
        ),
        sections=[
            Section(
                name="Main",
                body=[
                    Table(
                        columns=[TableColumn(header="Item", width_mm=80)],
                        repeat=TableRepeat(path="MainData.QuotationLines.Line", alias="line"),
                        row_template=[
                            Cell(blocks=[Paragraph(runs=[FieldBinding(path="line.ItemId")])])
                        ],
                        footer_rows=[
                            TableRow(cells=[Cell(blocks=[Paragraph(runs=[TextRun(text="EMPTY")])])])
                        ],
                    )
                ],
            )
        ],
    )
    compiled = GenericDocxCompiler().compile(
        document,
        schema,
        CompileOptions(document_name="empty.docx"),
        sample_data=empty,
    )
    assert compiled.package and not compiled.package["missing_entries"]
    assert any("produced no rows" in warning for warning in compiled.warnings)


def test_merged_cells_are_deliberately_unsupported() -> None:
    document = DocxDocument()
    table = document.add_table(rows=3, cols=2)
    table.cell(0, 0).merge(table.cell(0, 1))
    table.cell(1, 0).paragraphs[0]._p.append(_sdt("A-1"))
    table.cell(1, 1).paragraphs[0]._p.append(_sdt("10.00"))
    buffer = io.BytesIO()
    document.save(buffer)

    result = infer_tables(buffer.getvalue(), _elements())
    assert not result.tables
    assert result.outcomes
    assert "TABLE_MERGED_OR_RAGGED" in result.outcomes[0].reason_codes
    assert any(item.blocking for item in result.diagnostics)
