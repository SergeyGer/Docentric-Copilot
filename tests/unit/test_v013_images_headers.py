"""V013-02/V013-04: image family primitives and first-page headers."""

from __future__ import annotations

import base64
import io
import re
import zipfile

from docentric_copilot.docx_compiler import CompileOptions, GenericDocxCompiler
from docentric_copilot.template_ir import (
    ImageBinding,
    ImageFallback,
    ImageSource,
    PageBreak,
    Paragraph,
    Repeat,
    TextRun,
)
from docentric_copilot.template_validator import ValidationEngine
from docx import Document as DocxDocument

from tests.golden_files.fixtures import TINY_PNG_B64


def _png() -> bytes:
    return base64.b64decode(TINY_PNG_B64)


def _compile(document, schema, sample_data, **options):
    return GenericDocxCompiler().compile(
        document,
        schema,
        CompileOptions(document_name="v013.docx", **options),
        sample_data=sample_data,
    )


def _header_parts(content: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(content)) as package:
        return {
            name: package.read(name).decode("utf-8")
            for name in package.namelist()
            if name.startswith("word/header") and name.endswith(".xml")
        }


def _xml_text(content: bytes, prefix: str = "word/") -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as package:
        return "\n".join(
            package.read(name).decode("utf-8", errors="ignore")
            for name in package.namelist()
            if name.startswith(prefix) and name.endswith(".xml")
        )


def _codes(report) -> set[str]:
    return {finding.code for check in report.checks for finding in check.findings}


def _footer_parts(content: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(content)) as package:
        return {
            name: package.read(name).decode("utf-8")
            for name in package.namelist()
            if name.startswith("word/footer") and name.endswith(".xml")
        }


def test_first_page_header_uses_title_pg_and_a_separate_part(planned, schema, sample_data):
    document = planned.document.model_copy(deep=True)
    section = document.sections[0]
    section.header = [Paragraph(runs=[TextRun(text="DEFAULT HEADER")])]
    section.first_page_header = [Paragraph(runs=[TextRun(text="FIRST PAGE HEADER")])]

    compiled = _compile(document, schema, sample_data)
    with zipfile.ZipFile(io.BytesIO(compiled.content)) as package:
        xml = package.read("word/document.xml").decode("utf-8")
    assert "<w:titlePg/>" in xml
    assert re.search(r'<w:headerReference w:type="default"', xml)
    assert re.search(r'<w:headerReference w:type="first"', xml)
    headers = _header_parts(compiled.content)
    assert any("FIRST PAGE HEADER" in body for body in headers.values())
    assert any("DEFAULT HEADER" in body for body in headers.values())
    first = next(body for body in headers.values() if "FIRST PAGE HEADER" in body)
    default = next(body for body in headers.values() if "DEFAULT HEADER" in body)
    assert "DEFAULT HEADER" not in first
    assert "FIRST PAGE HEADER" not in default


def test_blank_first_page_header_suppresses_logo_on_page_one(planned, schema, sample_data):
    document = planned.document.model_copy(deep=True)
    section = document.sections[0]
    section.header = [Paragraph(runs=[TextRun(text="DEFAULT HEADER")])]
    section.first_page_header = []
    compiled = _compile(document, schema, sample_data)
    headers = _header_parts(compiled.content)
    assert any("DEFAULT HEADER" in body for body in headers.values())
    assert all("DEFAULT HEADER" not in body for name, body in headers.items() if "header2" in name)


def test_first_page_footer_keeps_page_fields(planned, schema, sample_data):
    document = planned.document.model_copy(deep=True)
    document.sections[0].first_page_header = [Paragraph(runs=[TextRun(text="LOGO ONLY")])]
    compiled = _compile(document, schema, sample_data)
    footers = _footer_parts(compiled.content)
    assert any('w:instrText="PAGE"' in body or "PAGE" in body for body in footers.values())
    assert any("NUMPAGES" in body for body in footers.values())


def test_preview_uses_first_header_only_on_first_page(planned, schema, sample_data):
    from docentric_copilot.preview import render_preview

    document = planned.document.model_copy(deep=True)
    section = document.sections[0]
    section.header = [Paragraph(runs=[TextRun(text="DEFAULT HEADER")])]
    section.first_page_header = [Paragraph(runs=[TextRun(text="FIRST HEADER")])]
    section.body.append(PageBreak())
    section.body.append(Paragraph(runs=[TextRun(text="PAGE TWO")]))
    preview = render_preview(document, schema, sample_data=sample_data)
    assert preview.html.count("FIRST HEADER") == 1
    assert preview.html.count("DEFAULT HEADER") >= 1
    assert preview.html.index("FIRST HEADER") < preview.html.index("PAGE TWO")


def test_static_image_asset_is_embedded(planned, schema, sample_data):
    document = planned.document.model_copy(deep=True)
    document.sections[0].body.append(
        ImageBinding(
            source=ImageSource.STATIC,
            static_asset="company_logo",
            width_mm=40,
            alt_text="Static logo",
        )
    )
    compiled = _compile(document, schema, sample_data, static_assets={"company_logo": _png()})
    with zipfile.ZipFile(io.BytesIO(compiled.content)) as package:
        media = [name for name in package.namelist() if name.startswith("word/media/")]
    assert media
    assert compiled.stats["images"] >= 1


def test_missing_static_asset_uses_blank_fallback(planned, schema, sample_data):
    document = planned.document.model_copy(deep=True)
    document.sections[0].body.append(
        ImageBinding(
            source=ImageSource.STATIC,
            static_asset="missing_logo",
            fallback=ImageFallback.BLANK,
        )
    )
    compiled = _compile(document, schema, sample_data)
    assert "[[missing_logo]]" not in _xml_text(compiled.content)
    assert any("missing_logo" in warning for warning in compiled.warnings)


def test_missing_dynamic_image_uses_alt_text(planned, schema, sample_data):
    document = planned.document.model_copy(deep=True)
    document.sections[0].body.append(
        ImageBinding(
            path="MainData.Company.Logo",
            fallback=ImageFallback.ALT_TEXT,
            alt_text="Logo unavailable",
        )
    )
    compiled = _compile(document, schema, sample_data)
    assert "Logo unavailable" in _xml_text(compiled.content)


def test_aspect_ratio_is_preserved_or_stretched(planned, schema, sample_data):
    def compile_with(preserve: bool):
        document = planned.document.model_copy(deep=True)
        document.sections[0].body.append(
            ImageBinding(
                source=ImageSource.STATIC,
                static_asset="logo",
                width_mm=40,
                height_mm=10,
                preserve_aspect=preserve,
            )
        )
        return _compile(document, schema, sample_data, static_assets={"logo": _png()})

    preserved = DocxDocument(io.BytesIO(compile_with(True).content))
    stretched = DocxDocument(io.BytesIO(compile_with(False).content))
    # The tiny PNG is 1:1, so preserving the aspect ratio makes a 40 mm square.
    assert round(preserved.inline_shapes[0].height.mm, 1) == 40.0
    assert round(stretched.inline_shapes[0].height.mm, 1) == 10.0


def test_wrong_type_image_binding_is_rejected(planned, schema, sample_data):
    document = planned.document.model_copy(deep=True)
    document.sections[0].body.append(ImageBinding(path="MainData.Quotation.QuotationId"))
    report = ValidationEngine().validate(document, schema, sample_data=sample_data)
    assert "V2-002" in _codes(report)


def test_image_in_first_page_header_is_validated(planned, schema):
    document = planned.document.model_copy(deep=True)
    document.sections[0].first_page_header = [ImageBinding(path="MainData.Company.DoesNotExist")]
    report = ValidationEngine().validate(document, schema)
    assert "V2-001" in _codes(report)


def test_static_images_expand_inside_repeat(planned, schema, sample_data):
    document = planned.document.model_copy(deep=True)
    document.sections[0].body.append(
        Repeat(
            path="MainData.QuotationLines.Line",
            alias="line",
            blocks=[
                ImageBinding(
                    source=ImageSource.STATIC,
                    static_asset="logo",
                    width_mm=20,
                )
            ],
        )
    )
    compiled = _compile(document, schema, sample_data, static_assets={"logo": _png()})
    assert compiled.stats["images"] >= 3


def _image_collection_schema():
    from docentric_copilot.ddsp_parser.models import NormalizedSchema, SchemaNode, SchemaSection

    line = SchemaNode(
        name="Line",
        path="MainData.Lines.Line",
        data_type="collection",
        collection=True,
        children=[
            SchemaNode(name="ItemId", path="MainData.Lines.Line.ItemId", data_type="string"),
            SchemaNode(
                name="ProductImage",
                path="MainData.Lines.Line.ProductImage",
                data_type="image",
            ),
        ],
    )
    return NormalizedSchema(
        schema_id="image-collection",
        sections=[
            SchemaSection(
                name="MainData",
                nodes=[
                    SchemaNode(
                        name="Lines",
                        path="MainData.Lines",
                        data_type="object",
                        children=[line],
                    )
                ],
            )
        ],
    )


def test_dynamic_image_collection_embeds_one_image_per_row() -> None:
    from docentric_copilot.template_ir import (
        Document,
        DocumentMetadata,
        FieldBinding,
        Section,
    )

    schema = _image_collection_schema()
    sample_data = {
        "MainData": {
            "Lines": {
                "Line": [
                    {"ItemId": "A-1", "ProductImage": TINY_PNG_B64},
                    {"ItemId": "A-2", "ProductImage": TINY_PNG_B64},
                ]
            }
        }
    }
    document = Document(
        title="Image collection",
        metadata=DocumentMetadata(
            template_name="Image collection",
            source_schema_id=schema.schema_id,
        ),
        sections=[
            Section(
                name="Main",
                body=[
                    Repeat(
                        path="MainData.Lines.Line",
                        alias="line",
                        blocks=[
                            Paragraph(runs=[FieldBinding(path="line.ItemId")]),
                            ImageBinding(path="line.ProductImage", width_mm=20),
                        ],
                    )
                ],
            )
        ],
    )
    compiled = _compile(document, schema, sample_data)
    assert compiled.stats["images"] == 2
    report = ValidationEngine().validate(document, schema, sample_data=sample_data)
    assert "V2-002" not in _codes(report)


def test_product_image_is_embedded_in_a_repeated_table_row() -> None:
    from docentric_copilot.template_ir import (
        Cell,
        Document,
        DocumentMetadata,
        FieldBinding,
        Section,
        Table,
        TableColumn,
        TableRepeat,
    )

    schema = _image_collection_schema()
    sample_data = {
        "MainData": {
            "Lines": {
                "Line": [
                    {"ItemId": "A-1", "ProductImage": TINY_PNG_B64},
                    {"ItemId": "A-2", "ProductImage": TINY_PNG_B64},
                ]
            }
        }
    }
    document = Document(
        title="Product images",
        metadata=DocumentMetadata(
            template_name="Product images",
            source_schema_id=schema.schema_id,
        ),
        sections=[
            Section(
                name="Main",
                body=[
                    Table(
                        columns=[
                            TableColumn(header="Item", width_mm=80),
                            TableColumn(header="Image", width_mm=40),
                        ],
                        repeat=TableRepeat(path="MainData.Lines.Line", alias="line"),
                        row_template=[
                            Cell(blocks=[Paragraph(runs=[FieldBinding(path="line.ItemId")])]),
                            Cell(blocks=[ImageBinding(path="line.ProductImage", width_mm=20)]),
                        ],
                    )
                ],
            )
        ],
    )
    compiled = _compile(document, schema, sample_data)
    assert compiled.stats["images"] == 2


def test_wrong_scope_image_is_rejected_inside_a_line_repeat() -> None:
    from docentric_copilot.ddsp_parser.models import NormalizedSchema, SchemaNode, SchemaSection
    from docentric_copilot.template_ir import Document, DocumentMetadata, Section

    base = _image_collection_schema()
    schema = NormalizedSchema(
        schema_id=base.schema_id,
        sections=[
            *base.sections,
            SchemaSection(
                name="GeneralData",
                nodes=[
                    SchemaNode(
                        name="Company",
                        path="GeneralData.Company",
                        data_type="object",
                        children=[
                            SchemaNode(
                                name="Logo",
                                path="GeneralData.Company.Logo",
                                data_type="image",
                            )
                        ],
                    )
                ],
            ),
        ],
    )
    document = Document(
        title="Wrong scope",
        metadata=DocumentMetadata(
            template_name="Wrong scope",
            source_schema_id=schema.schema_id,
        ),
        sections=[
            Section(
                name="Main",
                body=[
                    Repeat(
                        path="MainData.Lines.Line",
                        alias="line",
                        blocks=[ImageBinding(path="GeneralData.Company.Logo")],
                    )
                ],
            )
        ],
    )
    report = ValidationEngine().validate(document, schema)
    assert "V2-003" in _codes(report)


def test_multi_section_headers_and_footer_inheritance(planned, schema, sample_data):
    from docentric_copilot.template_ir import Document, DocumentMetadata, Section

    document = Document(
        title="Multi-section invoice",
        metadata=DocumentMetadata(
            template_name="multi_section",
            source_schema_id=schema.schema_id,
        ),
        sections=[
            Section(
                name="Main",
                body=[
                    Paragraph(runs=[TextRun(text="SECTION ONE")]),
                    PageBreak(),
                    Paragraph(runs=[TextRun(text="SECTION ONE PAGE TWO")]),
                ],
                header=[Paragraph(runs=[TextRun(text="DEFAULT-ONE")])],
                first_page_header=[Paragraph(runs=[TextRun(text="FIRST-ONE")])],
                footer=[Paragraph(runs=[TextRun(text="FOOTER-ONE")])],
            ),
            Section(
                name="Terms",
                body=[Paragraph(runs=[TextRun(text="SECTION TWO")])],
                header=[Paragraph(runs=[TextRun(text="SECOND-HEADER")])],
                footer=None,
            ),
        ],
    )
    compiled = _compile(document, schema, sample_data)
    with zipfile.ZipFile(io.BytesIO(compiled.content)) as package:
        xml = package.read("word/document.xml").decode("utf-8")
    assert xml.count("<w:sectPr") == 2
    assert xml.count("<w:titlePg") == 1
    headers = _header_parts(compiled.content)
    combined = "\n".join(headers.values())
    assert "FIRST-ONE" in combined
    assert "DEFAULT-ONE" in combined
    assert "SECOND-HEADER" in combined

    from docentric_copilot.preview import render_preview

    preview = render_preview(document, schema, sample_data=sample_data)
    html = preview.html
    assert html.count('class="page"') == 3
    assert html.count("FIRST-ONE") == 1
    assert html.count("DEFAULT-ONE") == 1  # page 2 of section 1
    assert html.count("SECOND-HEADER") == 1
    # Section 2 has no footer blocks; it inherits the previous footer in Word.
    assert html.count("FOOTER-ONE") == 2
    assert "Page 1 of 3" in html and "Page 3 of 3" in html
    assert html.index("FIRST-ONE") < html.index("DEFAULT-ONE") < html.index("SECOND-HEADER")


def test_multi_section_first_page_header_is_per_section(planned, schema, sample_data):
    from docentric_copilot.template_ir import Document, DocumentMetadata, Section

    document = Document(
        title="Two first pages",
        metadata=DocumentMetadata(
            template_name="two_first_pages",
            source_schema_id=schema.schema_id,
        ),
        sections=[
            Section(
                name="One",
                body=[Paragraph(runs=[TextRun(text="ONE")])],
                header=[Paragraph(runs=[TextRun(text="H1")])],
                first_page_header=[Paragraph(runs=[TextRun(text="F1")])],
            ),
            Section(
                name="Two",
                body=[Paragraph(runs=[TextRun(text="TWO")])],
                header=[Paragraph(runs=[TextRun(text="H2")])],
                first_page_header=[Paragraph(runs=[TextRun(text="F2")])],
            ),
        ],
    )
    compiled = _compile(document, schema, sample_data)
    with zipfile.ZipFile(io.BytesIO(compiled.content)) as package:
        xml = package.read("word/document.xml").decode("utf-8")
    assert xml.count("<w:titlePg") == 2
    headers = _header_parts(compiled.content)
    combined = "\n".join(headers.values())
    assert all(text in combined for text in ("F1", "H1", "F2", "H2"))
    from docentric_copilot.preview import render_preview

    preview = render_preview(document, schema, sample_data=sample_data)
    assert preview.html.count("F1") == 1
    assert preview.html.count("F2") == 1
    assert preview.html.count("H1") == 0
    assert preview.html.count("H2") == 0
