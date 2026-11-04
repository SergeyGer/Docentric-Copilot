"""Synthetic REF-01 tests for the real DDSP adapter and schema dispatcher."""

from __future__ import annotations

import pytest
from docentric_copilot.errors import (
    InvalidInputError,
    SecurityViolationError,
    UnsupportedInputError,
)
from docentric_copilot.reference import (
    ReferenceLimits,
    inspect_reference_bytes,
    parse_ddsp_schema,
    parse_real_ddsp,
)

from tests.reference_fixtures import (
    DDSP_NS,
    ControlSpec,
    ElementSpec,
    build_ddsp,
    build_docx,
    build_project_data,
    build_reference_ddsp,
    build_zip,
    project_data_parts,
)

LIMITS = ReferenceLimits()

_SIMPLE_XSD = b"""<?xml version="1.0" encoding="utf-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="MainData">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="Line" maxOccurs="unbounded">
          <xs:complexType>
            <xs:attribute name="Sku" type="xs:string"/>
            <xs:attribute name="Amount" type="xs:decimal"/>
          </xs:complexType>
        </xs:element>
      </xs:sequence>
      <xs:attribute name="Number" type="xs:string"/>
    </xs:complexType>
  </xs:element>
</xs:schema>
"""

_SIMPLE_SAMPLE = b"""<?xml version="1.0" encoding="utf-8"?>
<MainData Number="S-1"><Line Sku="A" Amount="1.5"/></MainData>
"""


@pytest.fixture(scope="module")
def artifact():
    return parse_real_ddsp(build_reference_ddsp(), name="Synthetic.ddsp", limits=LIMITS)


def test_real_ddsp_sections_paths_and_types(artifact) -> None:
    schema = artifact.schema
    assert schema.source == "docentric-ax-ddsp"
    assert schema.container_format == "xml"
    assert schema.section_names == ["GeneralData", "MainData", "Parameters"]
    assert schema.has_path("MainData.Order.@Number")
    assert schema.has_path("MainData.Order.Lines.Line.@Sku")
    assert schema.has_path("MainData.Order.Lines.Line.Taxes.Tax.@Code")
    assert schema.has_path("Parameters.Parameters.@IncludeDraft")

    types = {
        "MainData.Order.@Number": "string",
        "MainData.Order.@IssuedOn": "date",
        "MainData.Order.@UpdatedAt": "date",
        "MainData.Order.@NetAmount": "number",
        "MainData.Order.@IsPaid": "boolean",
        "MainData.Order.@Logo": "image",
        "MainData.Order.@Website": "string",
        "MainData.Order.@CopyCount": "number",
    }
    for path, expected in types.items():
        assert schema.node(path) is not None
        assert schema.node(path).data_type == expected, path


def test_real_ddsp_collections_are_nested(artifact) -> None:
    schema = artifact.schema
    lines = schema.node("MainData.Order.Lines.Line")
    taxes = schema.node("MainData.Order.Lines.Line.Taxes.Tax")
    assert lines is not None and lines.collection is True
    assert taxes is not None and taxes.collection is True
    assert schema.node("MainData.Order.Lines") is not None
    assert schema.node("MainData.Order.Lines").collection is False
    assert "MainData.Order.Lines.Line" in artifact.evidence.repeating_sections
    assert "MainData.Order.Lines.Line.Taxes.Tax" in artifact.evidence.repeating_sections


def test_real_ddsp_sample_values_are_coerced(artifact) -> None:
    schema = artifact.schema
    assert schema.sample_data_available is True
    assert schema.node("MainData.Order.@Number").sample_value == "SO-1"
    assert schema.node("MainData.Order.@NetAmount").sample_value == 123.45
    assert schema.node("MainData.Order.@IsPaid").sample_value is True
    assert schema.node("MainData.Order.Lines.Line.@Sku").sample_value == "A-1"
    assert schema.node("MainData.Order.Lines.Line.Taxes.Tax.@Code").sample_value == "VAT"
    assert schema.node("MainData.Order.@Logo").sample_value is None


def test_real_ddsp_evidence(artifact) -> None:
    evidence = artifact.evidence
    assert evidence.schema_format == "bare-ddsp"
    assert evidence.root_element == "dataSourcePackage"
    assert evidence.namespace == DDSP_NS
    assert evidence.product_version == "1.4.9.0"
    assert evidence.contract_version == "1.4.9.0"
    assert evidence.flavour == "Mail Merge"
    assert evidence.flavour_label == "Synthetic Mail Merge"
    assert evidence.language == "EN-US"
    assert evidence.template_id == "SyntheticTemplate"
    assert evidence.locales == ["EN-US", "de"]
    assert evidence.label_count == 2
    assert evidence.field_count == 17
    assert evidence.collection_count == 2
    assert evidence.sample_values_present is True
    assert "xsd:any" in evidence.unsupported_constructs
    assert evidence.schema_digest == artifact.schema.digest()
    assert evidence.stats.node_count == len(artifact.schema.paths)


def test_labels_are_bound_to_declarations_without_leaking(artifact) -> None:
    schema = artifact.schema
    assert schema.node("MainData.Order.Lines.Line").description == "Order lines"
    assert schema.node("GeneralData.GeneralData.Company.@Name").description == "Company name"
    assert schema.node("MainData.Order").description is None


def test_schema_index_contains_attribute_paths(artifact) -> None:
    match = artifact.index.match("MainData", "Lines/Line/@Sku")
    assert match.status.value == "matched"
    assert match.normalized_path == "MainData.Order.Lines.Line.@Sku"
    assert artifact.index.match("Parameters", "@IncludeDraft").status.value == "matched"


def test_parsing_is_deterministic(artifact) -> None:
    second = parse_real_ddsp(build_reference_ddsp(), name="Synthetic.ddsp", limits=LIMITS)
    assert second.schema.digest() == artifact.schema.digest()
    assert second.evidence == artifact.evidence


def test_malformed_xml_is_rejected() -> None:
    with pytest.raises(InvalidInputError):
        parse_real_ddsp(b"<dsp:dataSourcePackage", name="broken.ddsp", limits=LIMITS)


def test_doctype_is_rejected() -> None:
    payload = (
        b'<?xml version="1.0"?><!DOCTYPE dsp:dataSourcePackage>'
        b'<dsp:dataSourcePackage xmlns:dsp="' + DDSP_NS.encode() + b'"/>'
    )
    with pytest.raises(SecurityViolationError):
        parse_real_ddsp(payload, name="hostile.ddsp", limits=LIMITS)


def test_size_and_depth_limits_are_enforced() -> None:
    payload = build_reference_ddsp()
    with pytest.raises(UnsupportedInputError):
        parse_real_ddsp(payload, name="large.ddsp", limits=ReferenceLimits(max_file_bytes=64))
    with pytest.raises(SecurityViolationError):
        parse_real_ddsp(payload, name="deep.ddsp", limits=ReferenceLimits(max_xml_depth=4))


def test_wrong_root_and_namespace_are_explicit() -> None:
    with pytest.raises(UnsupportedInputError):
        parse_real_ddsp(b'<notADdsp xmlns="urn:synthetic"/>', name="x.ddsp", limits=LIMITS)
    with pytest.raises(UnsupportedInputError):
        parse_real_ddsp(
            b'<dsp:dataSourcePackage xmlns:dsp="urn:synthetic"/>',
            name="x.ddsp",
            limits=LIMITS,
        )


def test_missing_data_sections_is_explicit() -> None:
    payload = (
        b'<dsp:dataSourcePackage xmlns:dsp="' + DDSP_NS.encode() + b'"></dsp:dataSourcePackage>'
    )
    with pytest.raises(UnsupportedInputError):
        parse_real_ddsp(payload, name="empty.ddsp", limits=LIMITS)


def test_dispatcher_accepts_a_simple_xsd() -> None:
    artifact = parse_ddsp_schema(_SIMPLE_XSD, name="schema.xsd", limits=LIMITS)
    assert artifact.evidence.schema_format == "xsd"
    assert artifact.schema.section_names == ["MainData"]
    assert artifact.evidence.root_element is None
    assert artifact.index.match("MainData", "Line/@Amount").status.value == "matched"
    assert artifact.index.match("MainData", "Line/@Sku").status.value == "matched"


def test_dispatcher_accepts_sample_inference() -> None:
    artifact = parse_ddsp_schema(_SIMPLE_SAMPLE, name="sample.xml", limits=LIMITS)
    assert artifact.evidence.schema_format == "sample-inferred"
    assert artifact.schema.has_path("MainData.Line")
    line = artifact.schema.node("MainData.Line")
    assert line is not None
    assert {attribute.name for attribute in line.attributes} == {"Amount", "Sku"}


def test_dispatcher_accepts_a_synthetic_zip() -> None:
    payload = build_zip(
        {
            "schema.xsd": _SIMPLE_XSD,
            "sample.xml": _SIMPLE_SAMPLE,
            "manifest.json": b'{"format":"docentric-ax-ddsp","name":"compact"}',
        }
    )
    artifact = parse_ddsp_schema(payload, name="compact.ddsp", limits=LIMITS)
    assert artifact.evidence.schema_format == "synthetic-ddsp"
    assert artifact.schema.schema_id == "compact"


def test_dispatcher_still_parses_the_legacy_synthetic_ddsp() -> None:
    artifact = parse_ddsp_schema(build_ddsp(), name="Legacy.ddsp", limits=LIMITS)
    assert artifact.evidence.schema_format == "bare-ddsp"
    assert artifact.schema.section_names == ["GeneralData", "MainData"]


def test_report_includes_schema_evidence() -> None:
    elements = (ElementSpec(1000, "Field", "MainData", "@Number"),)
    controls = (ControlSpec(alias="Field", tag="Field", sdt_id=1000, text="@Number"),)
    docx = build_docx(
        document_controls=controls,
        custom_parts=project_data_parts(build_project_data(elements)),
    )
    report = inspect_reference_bytes(
        docx,
        filename="Synthetic.Report.docx",
        limits=LIMITS,
        ddsp_data=build_reference_ddsp(),
        ddsp_name="Synthetic.Report.ddsp",
    )
    document = report.documents[0]
    assert document.schema_evidence is not None
    assert document.schema_evidence.schema_format == "bare-ddsp"
    assert document.schema_evidence.product_version == "1.4.9.0"
    assert document.schema_evidence.sections == ["GeneralData", "MainData", "Parameters"]
    assert document.schema_sections == ["GeneralData", "MainData", "Parameters"]
    assert document.schema_paths > 0
    assert document.schema_evidence.unsupported_constructs == ["xsd:any"]


_RICH_XSD = b"""<?xml version="1.0" encoding="utf-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:import namespace="urn:synthetic" schemaLocation="synthetic.xsd"/>
  <xs:simpleType name="CodeType"><xs:restriction base="xs:string"/></xs:simpleType>
  <xs:simpleType name="UnionType"><xs:union memberTypes="xs:string xs:int"/></xs:simpleType>
  <xs:attributeGroup name="CommonAttrs">
    <xs:attribute name="Common" type="xs:long"/>
  </xs:attributeGroup>
  <xs:group name="GroupFields">
    <xs:sequence><xs:element name="Grouped" type="xs:string"/></xs:sequence>
  </xs:group>
  <xs:complexType name="BaseType">
    <xs:attribute name="BaseAttr" type="xs:boolean"/>
  </xs:complexType>
  <xs:complexType name="RecursiveType">
    <xs:sequence><xs:element name="Child" type="RecursiveType"/></xs:sequence>
  </xs:complexType>
  <xs:element name="Root">
    <xs:complexType>
      <xs:complexContent>
        <xs:extension base="BaseType">
          <xs:sequence>
            <xs:group ref="GroupFields"/>
            <xs:element name="Unknown" type="xs:anyType"/>
            <xs:element name="Code" type="CodeType"/>
            <xs:element name="Union" type="UnionType"/>
            <xs:element name="Recursive" type="RecursiveType"/>
            <xs:choice minOccurs="0" maxOccurs="unbounded">
              <xs:element name="Alias" type="CodeType"/>
              <xs:element name="Alias" type="xs:string"/>
            </xs:choice>
          </xs:sequence>
          <xs:attributeGroup ref="CommonAttrs"/>
          <xs:attribute name="Inline">
            <xs:simpleType><xs:restriction base="xs:decimal"/></xs:simpleType>
          </xs:attribute>
          <xs:anyAttribute/>
        </xs:extension>
      </xs:complexContent>
    </xs:complexType>
  </xs:element>
</xs:schema>
"""


def _ddsp_with_xsd(xsd: bytes) -> bytes:
    if xsd.lstrip().startswith(b"<?xml"):
        xsd = xsd.split(b"?>", 1)[1]
    return (
        b'<dsp:dataSourcePackage xmlns:dsp="'
        + DDSP_NS.encode()
        + b'" xmlns:xse="http://schemas.docentric.com/xml-schema-extensions">'
        + b'<dsp:dataSections><dsp:dataSection dsp:type="MainData"><dsp:schema>'
        + xsd
        + b"</dsp:schema></dsp:dataSection></dsp:dataSections></dsp:dataSourcePackage>"
    )


def test_xsd_constructs_are_mapped_or_listed_as_unsupported() -> None:
    artifact = parse_real_ddsp(_ddsp_with_xsd(_RICH_XSD), name="rich.ddsp", limits=LIMITS)
    schema = artifact.schema
    assert schema.has_path("MainData.Root.@BaseAttr")
    assert schema.has_path("MainData.Root.@Common")
    assert schema.has_path("MainData.Root.@Inline")
    assert schema.node("MainData.Root.@Inline").data_type == "number"
    assert schema.has_path("MainData.Root.Grouped")
    assert schema.has_path("MainData.Root.Unknown")
    assert schema.node("MainData.Root.Unknown").data_type == "string"
    assert schema.has_path("MainData.Root.Code")
    assert schema.has_path("MainData.Root.Union")
    assert schema.has_path("MainData.Root.Recursive.Child")
    assert schema.node("MainData.Root.Recursive.Child").data_type == "any"
    aliases = [path for path in schema.paths if ".Alias" in path]
    assert len(aliases) >= 2
    assert "MainData.Root.Alias_2" in schema.paths
    unsupported = set(artifact.evidence.unsupported_constructs)
    assert {
        "xsd:anyAttribute",
        "xsd:union",
        "xsd:attributeGroup",
        "xsd:type:anyType",
        "xsd:import",
    } <= unsupported
    codes = {diagnostic.code.value for diagnostic in schema.diagnostics}
    assert "SCHEMA003" in codes
    assert "SCHEMA004" in codes
    assert "SCHEMA002" in codes


def test_missing_section_schema_is_explicit() -> None:
    payload = (
        b'<dsp:dataSourcePackage xmlns:dsp="'
        + DDSP_NS.encode()
        + b'"><dsp:dataSections><dsp:dataSection dsp:type="MainData"/></dsp:dataSections>'
        + b"</dsp:dataSourcePackage>"
    )
    with pytest.raises(UnsupportedInputError):
        parse_real_ddsp(payload, name="missing.ddsp", limits=LIMITS)


def test_data_section_without_root_element_is_skipped_explicitly() -> None:
    payload = _ddsp_with_xsd(
        b'<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        b'<xs:complexType name="OnlyType"/></xs:schema>'
    )
    with pytest.raises(UnsupportedInputError):
        parse_real_ddsp(payload, name="empty-root.ddsp", limits=LIMITS)
