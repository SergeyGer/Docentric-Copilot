#!/usr/bin/env python3
"""Build synthetic v0.13 feature captures used in the product video.

These are honest feature fixtures, not the private reference corpus:
* a repeated table with one product image per row;
* a reference DOCX table with header/data/footer rows, inferred into typed IR
  and compiled again.
"""

from __future__ import annotations

import base64
import io
import json
import subprocess
from pathlib import Path

from docentric_copilot.ddsp_parser.models import NormalizedSchema, SchemaNode, SchemaSection
from docentric_copilot.docx_compiler import CompileOptions, GenericDocxCompiler
from docentric_copilot.reference.docx_controls import ElementKind
from docentric_copilot.reference.graph import GraphStatus
from docentric_copilot.reference.projection import (
    ProjectionElement,
    ReferenceCapability,
    SourceLocation,
)
from docentric_copilot.reference.table_inference import infer_tables
from docentric_copilot.template_ir import (
    Alignment,
    Cell,
    Document,
    DocumentMetadata,
    FieldBinding,
    Heading,
    ImageBinding,
    Paragraph,
    Section,
    Table,
    TableColumn,
    TableRepeat,
    TextRun,
    ValueFormat,
)
from docx import Document as DocxDocument
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "media" / "features"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _image_uri(color: str, label: str) -> str:
    image = Image.new("RGB", (360, 260), color)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((12, 12, 348, 248), radius=18, outline="#FFFFFF", width=4)
    draw.text((34, 90), label, font=ImageFont.truetype(BOLD, 44), fill="#FFFFFF")
    draw.text((34, 150), "product image", font=ImageFont.truetype(BOLD, 22), fill="#F8FAFC")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def _pdf_and_png(docx_path: Path, stem: str) -> Path:
    subprocess.run(
        [
            "soffice",
            "--headless",
            "-env:UserInstallation=file:///tmp/dc-feature-lo",
            "--convert-to",
            "pdf",
            "--outdir",
            str(OUT),
            str(docx_path),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "pdftoppm",
            "-f",
            "1",
            "-l",
            "1",
            "-png",
            "-r",
            "130",
            str(OUT / f"{stem}.pdf"),
            str(OUT / stem),
        ],
        check=True,
        capture_output=True,
    )
    candidates = sorted(OUT.glob(f"{stem}-*.png"))
    if candidates and candidates[0].name != f"{stem}.png":
        candidates[0].rename(OUT / f"{stem}.png")
    return OUT / f"{stem}.png"


def product_images() -> dict[str, object]:
    schema = NormalizedSchema(
        schema_id="product-images",
        sections=[
            SchemaSection(
                name="MainData",
                nodes=[
                    SchemaNode(
                        name="Lines",
                        path="MainData.Lines",
                        data_type="object",
                        children=[
                            SchemaNode(
                                name="Line",
                                path="MainData.Lines.Line",
                                data_type="collection",
                                collection=True,
                                children=[
                                    SchemaNode(
                                        name="ItemId",
                                        path="MainData.Lines.Line.ItemId",
                                        data_type="string",
                                    ),
                                    SchemaNode(
                                        name="Description",
                                        path="MainData.Lines.Line.Description",
                                        data_type="string",
                                    ),
                                    SchemaNode(
                                        name="ProductImage",
                                        path="MainData.Lines.Line.ProductImage",
                                        data_type="image",
                                    ),
                                    SchemaNode(
                                        name="Amount",
                                        path="MainData.Lines.Line.Amount",
                                        data_type="decimal",
                                    ),
                                ],
                            )
                        ],
                    )
                ],
            )
        ],
    )
    rows = [
        ("A-1", "Field service kit", _image_uri("#1D4ED8", "KIT"), "1,240.00"),
        ("B-2", "Replacement sensor", _image_uri("#0F766E", "SENSOR"), "380.00"),
        ("C-3", "Calibration module", _image_uri("#7C3AED", "MODULE"), "620.00"),
    ]
    sample = {
        "MainData": {
            "Lines": {
                "Line": [
                    {
                        "ItemId": item,
                        "Description": description,
                        "ProductImage": image,
                        "Amount": amount,
                    }
                    for item, description, image, amount in rows
                ]
            }
        }
    }
    document = Document(
        title="Order lines with product images",
        metadata=DocumentMetadata(
            template_name="Product images", source_schema_id=schema.schema_id
        ),
        sections=[
            Section(
                name="Main",
                body=[
                    Heading(level=1, runs=[TextRun(text="Order lines")]),
                    Paragraph(
                        runs=[
                            TextRun(
                                text="One image per repeated line item, sourced from the schema."
                            )
                        ]
                    ),
                    Table(
                        columns=[
                            TableColumn(header="Item", width_mm=24),
                            TableColumn(header="Image", width_mm=42),
                            TableColumn(header="Description", width_mm=80),
                            TableColumn(header="Amount", width_mm=30, alignment=Alignment.RIGHT),
                        ],
                        repeat=TableRepeat(path="MainData.Lines.Line", alias="line"),
                        row_template=[
                            Cell(blocks=[Paragraph(runs=[FieldBinding(path="line.ItemId")])]),
                            Cell(blocks=[ImageBinding(path="line.ProductImage", width_mm=34)]),
                            Cell(blocks=[Paragraph(runs=[FieldBinding(path="line.Description")])]),
                            Cell(
                                blocks=[
                                    Paragraph(
                                        runs=[
                                            FieldBinding(
                                                path="line.Amount",
                                                format=ValueFormat.CURRENCY,
                                                currency_code="EUR",
                                            )
                                        ]
                                    )
                                ]
                            ),
                        ],
                    ),
                ],
            )
        ],
    )
    compiled = GenericDocxCompiler().compile(
        document,
        schema,
        CompileOptions(document_name="product-images.docx"),
        sample_data=sample,
    )
    docx_path = OUT / "product-images.docx"
    docx_path.write_bytes(compiled.content)
    png = _pdf_and_png(docx_path, "product-images")
    return {
        "docx": str(docx_path.relative_to(ROOT)),
        "png": str(png.relative_to(ROOT)),
        "image_count": compiled.stats["images"],
        "rows": len(rows),
    }


def _sdt(text: str) -> object:
    return parse_xml(
        f'<w:sdt {nsdecls("w")}><w:sdtPr><w:tag w:val="field"/></w:sdtPr>'
        f"<w:sdtContent><w:r><w:t>{text}</w:t></w:r></w:sdtContent></w:sdt>"
    )


def _element(
    ordinal: int, path: str, *, collection: bool = False, label: str = "Field"
) -> ProjectionElement:
    return ProjectionElement(
        id=f"control:document:{ordinal}",
        display_label=label,
        kind=ElementKind.FIELD,
        binding_path=path,
        status=GraphStatus.RESOLVED,
        capability=ReferenceCapability.RESOLVED,
        source_location=SourceLocation(
            part="word/document.xml", ordinal=ordinal, paragraph_index=0
        ),
        schema_path=path,
        data_type="string",
        collection=collection,
    )


def reference_table() -> dict[str, object]:
    document = DocxDocument()
    table = document.add_table(rows=3, cols=3)
    headers = ("SKU", "Description", "Amount")
    for column, header in enumerate(headers):
        table.cell(0, column).text = header
    values = [("A-1", "Field service kit", "1240.00")]
    for row_index, row_values in enumerate(values, start=1):
        for column, value in enumerate(row_values):
            table.cell(row_index, column).paragraphs[0]._p.append(_sdt(value))
    table.cell(2, 0).text = ""
    table.cell(2, 1).text = "Total"
    table.cell(2, 2).text = "1,240.00"
    buffer = io.BytesIO()
    document.save(buffer)
    source_bytes = buffer.getvalue()
    source_path = OUT / "reference-table-source.docx"
    source_path.write_bytes(source_bytes)
    source_png = _pdf_and_png(source_path, "reference-table-source")

    elements = [
        _element(0, "MainData.Lines.Line.ItemId", label="SKU"),
        _element(1, "MainData.Lines.Line.Description", label="Description"),
        _element(2, "MainData.Lines.Line.Amount", label="Amount"),
        _element(99, "MainData.Lines.Line", collection=True, label="Lines"),
    ]
    result = infer_tables(source_bytes, elements)
    if not result.tables:
        raise RuntimeError(f"table inference returned no table: {result.diagnostics}")
    inferred = result.tables[0].table
    schema = NormalizedSchema(
        schema_id="reference-table",
        sections=[
            SchemaSection(
                name="MainData",
                nodes=[
                    SchemaNode(
                        name="Lines",
                        path="MainData.Lines",
                        data_type="object",
                        children=[
                            SchemaNode(
                                name="Line",
                                path="MainData.Lines.Line",
                                data_type="collection",
                                collection=True,
                                children=[
                                    SchemaNode(
                                        name="ItemId",
                                        path="MainData.Lines.Line.ItemId",
                                        data_type="string",
                                    ),
                                    SchemaNode(
                                        name="Description",
                                        path="MainData.Lines.Line.Description",
                                        data_type="string",
                                    ),
                                    SchemaNode(
                                        name="Amount",
                                        path="MainData.Lines.Line.Amount",
                                        data_type="decimal",
                                    ),
                                ],
                            )
                        ],
                    )
                ],
            )
        ],
    )
    sample = {
        "MainData": {
            "Lines": {
                "Line": [
                    {"ItemId": "A-1", "Description": "Field service kit", "Amount": "1240.00"},
                ]
            }
        }
    }
    output_doc = Document(
        title="Inferred table",
        metadata=DocumentMetadata(
            template_name="Inferred table", source_schema_id=schema.schema_id
        ),
        sections=[
            Section(
                name="Main",
                body=[
                    Heading(level=1, runs=[TextRun(text="Reference table, inferred")]),
                    inferred,
                ],
            )
        ],
    )
    compiled = GenericDocxCompiler().compile(
        output_doc,
        schema,
        CompileOptions(document_name="reference-table-output.docx"),
        sample_data=sample,
    )
    output_path = OUT / "reference-table-output.docx"
    output_path.write_bytes(compiled.content)
    output_png = _pdf_and_png(output_path, "reference-table-output")
    (OUT / "reference-table-ir.json").write_text(
        json.dumps(inferred.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8"
    )
    return {
        "source_docx": str(source_path.relative_to(ROOT)),
        "source_png": str(source_png.relative_to(ROOT)),
        "output_docx": str(output_path.relative_to(ROOT)),
        "output_png": str(output_png.relative_to(ROOT)),
        "ir": str((OUT / "reference-table-ir.json").relative_to(ROOT)),
        "columns": [column.header for column in inferred.columns],
        "footer_rows": len(inferred.footer_rows),
        "diagnostics": [item.code for item in result.diagnostics],
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "v013-feature-assets/v1",
        "product_images": product_images(),
        "reference_table": reference_table(),
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
