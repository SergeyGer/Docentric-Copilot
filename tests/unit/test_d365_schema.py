"""Tests for the D365 embedded schema extraction adapter (PR-02)."""

from __future__ import annotations

import hashlib

import pytest
from docentric_copilot.errors import (
    InvalidInputError,
    NotFoundError,
    UnsupportedInputError,
)
from docentric_copilot.reference import (
    DiagnosticSeverity,
    ReferenceLimits,
    SchemaSourceKind,
    extract_d365_schema,
    extract_d365_schema_path,
)

from tests.reference_fixtures import (
    EMBEDDED_MAIN_XSD,
    ElementSpec,
    EmbeddedDataSourceSpec,
    build_axpp,
    build_docx,
    build_embedded_docx,
    build_embedded_project_data,
    build_project_data,
    build_zip,
    project_data_parts,
)


def _elements() -> tuple[ElementSpec, ...]:
    return (
        ElementSpec(1, "Field", "MainData", "@Number", "System.String"),
        ElementSpec(2, "List", "MainData", "Lines/Line", None, child_ids=(3, 4)),
        ElementSpec(3, "Field", ".", "@ItemId", "System.String"),
        ElementSpec(4, "Field", ".", "@Amount", "System.Decimal"),
    )


def test_embedded_schema_is_extracted_with_ooxml_provenance() -> None:
    payload = build_embedded_docx(_elements())
    document = extract_d365_schema(payload, filename="Synthetic.Report.docx")

    assert document.schema_source is SchemaSourceKind.PROJECTDATA
    assert document.platform == "D365FO"
    assert document.schema_format == "d365-embedded-schema/1.0"
    assert document.template_id == hashlib.sha256(payload).hexdigest()
    assert document.contract_version == "3.0.0.998"
    assert len(document.schema_evidence) == 1
    assert document.schema_evidence[0].startswith("customXml/item1.xml#/ProjectData/")

    assert len(document.project_data_parts) == 1
    part = document.project_data_parts[0]
    assert part.part == "customXml/item1.xml"
    assert part.xpath.startswith("/ProjectData")
    assert part.has_schema is True
    assert part.has_preview_data is True
    assert part.data_source_names == ["MainData"]
    assert part.element_count == 4

    assert len(document.canonical.sources) == 1
    source = document.canonical.sources[0]
    assert source.name == "MainData"
    assert source.data_section_type == "1"
    assert source.root_names == ["Root"]
    assert source.has_schema is True
    assert source.namespace_mappings["xs"] == "http://www.w3.org/2001/XMLSchema"
    assert source.preview is not None
    assert source.preview.root_name == "Root"
    assert source.preview.repeated_paths == {"Root/Lines/Line": 2}
    assert source.schema_evidence is not None
    assert source.schema_evidence.startswith("customXml/item1.xml#/ProjectData/")
    assert source.provenance.part == "customXml/item1.xml"
    assert source.provenance.xpath.startswith("/ProjectData/DataSources/DataSource")
    assert source.provenance.source_id == source.source_id

    fields = {field.raw_path: field for field in document.canonical.fields}
    assert fields["Root"].node_kind == "complex"
    assert fields["Root/Lines/Line"].is_collection is True
    assert fields["Root/Lines/Line"].collection_scope is None
    assert fields["Root/Lines/Line/@ItemId"].type_family == "text"
    assert fields["Root/Lines/Line/@ItemId"].collection_scope == "MainData/Root/Lines/Line"
    assert fields["Root/@Number"].xsd_type == "xs:string"
    assert fields["Root/@Number"].field_metadata is not None
    assert fields["Root/@Number"].field_metadata.label == "Order number"
    assert fields["Root/@Number"].field_metadata.reference_code == "@SYN011"
    assert fields["Root/Status"].node_kind == "complex"
    assert fields["Root/Status"].type_family == "enum"

    collection = document.canonical.collections[0]
    assert collection.raw_path == "Root/Lines/Line"
    assert collection.scope is None
    assert collection.observed_occurrences == 2

    for field in document.canonical.fields:
        assert field.provenance.part == "customXml/item1.xml"
        assert field.provenance.xpath.startswith("/ProjectData/")
        assert field.source_id == "customXml/item1.xml#dataSource[1]"
        assert field.canonical_path == f"MainData/{field.raw_path}"
        assert field.namespace == ""

    # Every extracted element keeps its own OOXML path and ValueBinding evidence.
    by_id = {element.element_id: element for element in document.elements}
    assert by_id["2"].child_ids == ["3", "4"]
    assert by_id["3"].parent_ids == ["2"]
    assert by_id["3"].binding_evidence is not None
    assert by_id["3"].binding_evidence.startswith("customXml/item1.xml#/ProjectData/Elements/")


def test_axpp_single_document_and_multiple_document_rejection() -> None:
    docx = build_embedded_docx(_elements())
    document = extract_d365_schema(build_axpp(docx), filename="Synthetic.axpp")
    assert document.schema_source is SchemaSourceKind.PROJECTDATA
    assert document.container is not None
    assert document.container.endswith(".docx")
    assert "\\" not in document.container

    package = build_zip({"A.docx": docx, "B.docx": docx})
    with pytest.raises(UnsupportedInputError) as excinfo:
        extract_d365_schema(package, filename="TwoTemplates.zip")
    assert excinfo.value.code == "reference_d365_multiple_documents"


def test_no_schema_is_unavailable_and_ddsp_is_a_fallback() -> None:
    elements = (ElementSpec(1, "Field", "MainData", "@Number", "System.String"),)
    custom = project_data_parts(build_project_data(elements))
    docx = build_docx(custom_parts=custom)

    unavailable = extract_d365_schema(docx, filename="Synthetic.docx")
    assert unavailable.schema_source is SchemaSourceKind.UNAVAILABLE
    assert unavailable.schema_evidence == []
    assert unavailable.canonical.is_available() is False
    assert any(item.code == "schema_unavailable" for item in unavailable.diagnostics)

    # A DDSP supplied by the caller only becomes the schema when the embedded
    # ProjectData contains no usable schema.
    from tests.reference_fixtures import build_ddsp

    fallback = extract_d365_schema(
        docx,
        filename="Synthetic.docx",
        ddsp_data=build_ddsp(),
        ddsp_name="Synthetic.ddsp",
    )
    assert fallback.schema_source is SchemaSourceKind.DDSP
    assert fallback.canonical.is_available() is True
    assert {source.name for source in fallback.canonical.sources} == {"GeneralData", "MainData"}
    assert any(item.startswith("Synthetic.ddsp#") for item in fallback.schema_evidence)


def test_corrupted_project_data_is_a_diagnostic_not_a_crash() -> None:
    corrupted = (
        b'<ProjectData xmlns="http://Docentric.org/ProjectData.xml">'
        b"<DataSources><DataSource Name='MainData'"
    )
    docx = build_docx(custom_parts={"customXml/item1.xml": corrupted})
    document = extract_d365_schema(docx, filename="Broken.docx")
    assert document.schema_source is SchemaSourceKind.UNAVAILABLE
    assert document.canonical.fields == []
    assert any(item.code == "custom_xml_unreadable" for item in document.diagnostics)
    assert document.warnings

    doctype = (
        b'<!DOCTYPE ProjectData [<!ENTITY xxe "expanded">]>'
        b'<ProjectData xmlns="http://Docentric.org/ProjectData.xml" ProductId="3">'
        b"<DataSources/></ProjectData>"
    )
    doctype_docx = build_docx(custom_parts={"customXml/item1.xml": doctype})
    rejected = extract_d365_schema(doctype_docx, filename="Doctype.docx")
    assert rejected.schema_source is SchemaSourceKind.UNAVAILABLE
    diagnostics = [item for item in rejected.diagnostics if item.code == "custom_xml_unreadable"]
    assert diagnostics
    assert diagnostics[0].details["reason"] == "reference_doctype_rejected"


def test_schema_node_and_depth_limits_are_enforced() -> None:
    docx = build_embedded_docx(_elements())
    limited = extract_d365_schema(
        docx,
        filename="Synthetic.docx",
        limits=ReferenceLimits(max_schema_nodes=4),
    )
    assert len(limited.canonical.fields) <= 4
    assert any("schema_node_limit" in warning for warning in limited.warnings)

    deep = "".join(
        f'<xs:element name="E{index}"><xs:complexType><xs:sequence>' for index in range(20)
    )
    deep += "".join("</xs:sequence></xs:complexType></xs:element>" for _ in range(20))
    deep_xsd = f'<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">{deep}</xs:schema>'
    deep_docx = build_embedded_docx(
        sources=(
            EmbeddedDataSourceSpec(
                xsd=deep_xsd,
                preview=None,
            ),
        )
    )
    truncated = extract_d365_schema(
        deep_docx,
        filename="Deep.docx",
        limits=ReferenceLimits(max_xml_depth=12),
    )
    assert truncated.schema_source is SchemaSourceKind.UNAVAILABLE
    assert any(item.code == "custom_xml_unreadable" for item in truncated.diagnostics)


def test_invalid_containers_raise_clear_errors() -> None:
    with pytest.raises(InvalidInputError) as too_small:
        extract_d365_schema(b"", filename="empty.docx")
    assert too_small.value.code == "reference_input_too_small"

    with pytest.raises(InvalidInputError) as not_zip:
        extract_d365_schema(b"this is not a zip payload", filename="plain.docx")
    assert not_zip.value.code == "reference_container_invalid"

    with pytest.raises(InvalidInputError) as no_docx:
        extract_d365_schema(build_zip({"readme.txt": b"hello"}), filename="plain.zip")
    assert no_docx.value.code == "reference_d365_no_document"

    with pytest.raises(InvalidInputError) as broken_docx:
        extract_d365_schema(build_zip({"template.docx": b"not a docx"}), filename="broken.axpp")
    assert broken_docx.value.code == "reference_container_invalid"

    docx = build_docx(custom_parts=project_data_parts(build_project_data()))
    with pytest.raises(InvalidInputError) as malformed_ddsp:
        extract_d365_schema(docx, filename="Synthetic.docx", ddsp_data=b"<dataSourcePackage")
    assert malformed_ddsp.value.code == "reference_xml_invalid"

    with pytest.raises(UnsupportedInputError) as wrong_ddsp:
        extract_d365_schema(
            docx,
            filename="Synthetic.docx",
            ddsp_data=b'<notADdsp xmlns="urn:test"/>',
        )
    assert wrong_ddsp.value.code == "reference_ddsp_unrecognized"


def test_missing_path_raises_not_found(tmp_path) -> None:
    with pytest.raises(NotFoundError) as excinfo:
        extract_d365_schema_path(tmp_path / "missing.docx")
    assert excinfo.value.code == "reference_input_missing"


def test_namespace_is_preserved_and_mapped() -> None:
    xsd = EMBEDDED_MAIN_XSD.replace(
        "<xs:schema ",
        '<xs:schema targetNamespace="urn:synthetic:data" ',
        1,
    )
    source = EmbeddedDataSourceSpec(
        xsd=xsd,
        namespace_mappings=(("t", "urn:synthetic:data"),),
    )
    document = extract_d365_schema(
        build_embedded_docx(
            (ElementSpec(1, "Field", "MainData", "t:Root/@Number", "System.String"),),
            sources=(source,),
        ),
        filename="Namespaced.docx",
    )
    number = next(field for field in document.canonical.fields if field.raw_path == "Root/@Number")
    assert number.namespace == "urn:synthetic:data"
    assert document.canonical.sources[0].namespace_mappings["t"] == "urn:synthetic:data"
    assert number.provenance.xpath.endswith("/attribute[1]")


def test_extraction_is_deterministic() -> None:
    docx = build_embedded_docx(_elements())
    first = extract_d365_schema(docx, filename="Synthetic.docx")
    second = extract_d365_schema(docx, filename="Synthetic.docx")
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.schema_evidence == second.schema_evidence
    assert all(item.severity for item in first.diagnostics)


def test_embedded_project_data_builder_contains_schema_parts() -> None:
    payload = build_embedded_project_data(
        (ElementSpec(9, "Field", None, None, properties={"DataSection": "1"}),)
    )
    assert b"DataSources" in payload
    assert b"XsdList" in payload
    assert b"MainXsd" in payload
    assert b"PreviewData" in payload
    assert b"Element" in payload
    assert b'Id="9"' in payload


def test_diagnostic_severity_enum_is_public() -> None:
    assert DiagnosticSeverity.WARNING.value == "warning"
