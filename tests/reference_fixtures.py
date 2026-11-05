"""Synthetic reference fixtures generated entirely by test code.

No file, fragment or value from the Docentric example archive is used here. The
helpers build small DOCX, AXPP/ZIP and DDSP payloads in memory so the public
test suite never depends on the licensed corpus.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from html import escape
from typing import Final

from docx import Document
from docx.oxml import OxmlElement

W_NS: Final = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
DS_NS: Final = "http://schemas.openxmlformats.org/officeDocument/2006/customXml"
PROJECT_DATA_NS: Final = "http://Docentric.org/ProjectData.xml"
DDSP_NS: Final = "http://schemas.docentric.com/dynamics-ax/data-source-packages"
XSD_NS: Final = "http://www.w3.org/2001/XMLSchema"
DC_TEST_NS: Final = "urn:docentric:fixture"
FIXED_TIME: Final = (2024, 1, 1, 0, 0, 0)

STORE_ITEM_ID: Final = "{11111111-1111-1111-1111-111111111111}"
MISSING_STORE_ITEM_ID: Final = "{99999999-9999-9999-9999-999999999999}"


def _w(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


def _zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[name])
    return buffer.getvalue()


def _read_zip(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


@dataclass(frozen=True)
class ControlSpec:
    """One synthetic ``w:sdt`` inserted through OOXML."""

    alias: str | None = "Field"
    tag: str | None = "Field"
    sdt_id: int | str | None = 123456789
    text: str = ""
    control_type: str | None = None
    store_item_id: str | None = None
    xpath: str | None = None
    placeholder: str | None = "SYNTHETIC-PLACEHOLDER"
    dc_namespace: bool = False
    nested: tuple[ControlSpec, ...] = ()


def _control_element(spec: ControlSpec) -> object:
    sdt = OxmlElement("w:sdt")
    properties = OxmlElement("w:sdtPr")
    if spec.alias is not None:
        alias = OxmlElement("w:alias")
        alias.set(_w("val"), spec.alias)
        properties.append(alias)
    if spec.tag is not None:
        tag = OxmlElement("w:tag")
        tag.set(_w("val"), spec.tag)
        properties.append(tag)
    if spec.sdt_id is not None:
        identifier = OxmlElement("w:id")
        identifier.set(_w("val"), str(spec.sdt_id))
        properties.append(identifier)
    if spec.placeholder is not None:
        placeholder = OxmlElement("w:placeholder")
        doc_part = OxmlElement("w:docPart")
        doc_part.set(_w("val"), spec.placeholder)
        placeholder.append(doc_part)
        properties.append(placeholder)
    if spec.control_type is not None:
        type_tag = {
            "text": "text",
            "date": "date",
            "dropdown": "dropDownList",
            "picture": "picture",
            "rich_text": "richText",
            "checkbox": "checkbox",
            "group": "group",
        }.get(spec.control_type, spec.control_type)
        properties.append(OxmlElement(f"w:{type_tag}"))
    if spec.store_item_id is not None or spec.xpath is not None:
        binding = OxmlElement("w:dataBinding")
        if spec.xpath is not None:
            binding.set(_w("xpath"), spec.xpath)
        if spec.store_item_id is not None:
            binding.set(_w("storeItemID"), spec.store_item_id)
        properties.append(binding)
    if spec.dc_namespace:
        properties.set(f"{{{DC_TEST_NS}}}role", "synthetic-marker")
    content = OxmlElement("w:sdtContent")
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = spec.text
    text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    run.append(text)
    content.append(run)
    for nested in spec.nested:
        content.append(_control_element(nested))
    sdt.append(properties)
    sdt.append(content)
    return sdt


def build_docx(
    *,
    document_controls: tuple[ControlSpec, ...] = (),
    header_controls: tuple[ControlSpec, ...] = (),
    footer_controls: tuple[ControlSpec, ...] = (),
    custom_parts: dict[str, bytes] | None = None,
) -> bytes:
    """Build a small DOCX with document, header and footer content controls."""
    document = Document()
    document.add_paragraph("Synthetic reference template")
    for spec in document_controls:
        paragraph = document.add_paragraph()
        paragraph._p.append(_control_element(spec))
    header = document.sections[0].header
    header_paragraph = header.paragraphs[0]
    for spec in header_controls:
        header_paragraph._p.append(_control_element(spec))
    footer = document.sections[0].footer
    footer_paragraph = footer.paragraphs[0]
    for spec in footer_controls:
        footer_paragraph._p.append(_control_element(spec))
    buffer = io.BytesIO()
    document.save(buffer)
    files = _read_zip(buffer.getvalue())
    if custom_parts:
        files.update(custom_parts)
    return _zip(files)


@dataclass(frozen=True)
class ElementSpec:
    """One synthetic Docentric ProjectData Element."""

    element_id: int | str
    element_type: str = "Field"
    source: str | None = "MainData"
    path: str | None = "@Number"
    result_data_type: str | None = "System.String"
    child_ids: tuple[int | str, ...] = ()
    attributes: dict[str, str] = field(default_factory=dict)
    properties: dict[str, str] = field(default_factory=dict)


def _render_element(element: ElementSpec) -> str:
    attrs = {"Type": element.element_type, "Id": str(element.element_id)}
    attrs.update(element.attributes)
    rendered = " ".join(f'{key}="{escape(value)}"' for key, value in sorted(attrs.items()))
    children: list[str] = []
    if element.child_ids:
        refs = "".join(f'<ElementRef Id="{escape(str(item))}"/>' for item in element.child_ids)
        children.append(f"<ChildElements>{refs}</ChildElements>")
    if element.properties:
        rendered_properties = " ".join(
            f'{key}="{escape(value)}"' for key, value in sorted(element.properties.items())
        )
        children.append(f"<Value {rendered_properties}/>")
    if element.source is not None and element.path is not None:
        children.append(
            "<ValueBinding "
            f'DataKind="2" Source="{escape(element.source)}" '
            f'Path="{escape(element.path)}" '
            f'ResultDataType="{escape(element.result_data_type or "")}"/>'
        )
    return f"<Element {rendered}>{''.join(children)}</Element>"


def build_project_data(
    elements: tuple[ElementSpec, ...] = (),
    *,
    product_version: str = "3.0.0.998",
    data_sources: tuple[str, ...] = ("GeneralData", "MainData"),
) -> bytes:
    """Build a namespace-correct synthetic ProjectData XML document."""
    source_xml = "".join(f'<DataSource Name="{escape(name)}"/>' for name in data_sources)
    element_xml = "".join(_render_element(element) for element in elements)
    text = (
        f'<ProjectData xmlns="{PROJECT_DATA_NS}" ProductId="3" '
        f'ProductVersion="{escape(product_version)}">'
        '<UISettings xmlns=""/>'
        f'<DataSources xmlns="">{source_xml}</DataSources>'
        f'<Elements xmlns="">{element_xml}</Elements>'
        "</ProjectData>"
    )
    return text.encode("utf-8")


def project_data_parts(
    project_data: bytes,
    *,
    item_index: int = 5,
    store_item_id: str = STORE_ITEM_ID,
    decoy_item_index: int | None = None,
) -> dict[str, bytes]:
    """Assemble customXml item/itemProps parts; optionally place a decoy first."""
    parts: dict[str, bytes] = {}
    if decoy_item_index is not None:
        parts[f"customXml/item{decoy_item_index}.xml"] = (
            b'<b:Sources xmlns:b="http://schemas.openxmlformats.org/officeDocument/2006/bibliography" '
            b'xmlns="http://schemas.openxmlformats.org/officeDocument/2006/bibliography"/>'
        )
    parts[f"customXml/item{item_index}.xml"] = project_data
    parts[f"customXml/itemProps{item_index}.xml"] = (
        f'<ds:datastoreItem xmlns:ds="{DS_NS}" ds:itemID="{store_item_id}">'
        "<ds:schemaRefs/>"
        "</ds:datastoreItem>"
    ).encode()
    return parts


_SIMPLE_MAIN_XSD: Final = """
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="Root">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="Line" maxOccurs="unbounded">
          <xs:complexType>
            <xs:attribute name="ItemId" type="xs:string"/>
            <xs:attribute name="Amount" type="xs:decimal"/>
          </xs:complexType>
        </xs:element>
      </xs:sequence>
      <xs:attribute name="Number" type="xs:string"/>
    </xs:complexType>
  </xs:element>
</xs:schema>
"""

_SIMPLE_GENERAL_XSD: Final = """
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="GeneralData">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="CurrentCompany">
          <xs:complexType>
            <xs:attribute name="Name" type="xs:string"/>
          </xs:complexType>
        </xs:element>
      </xs:sequence>
    </xs:complexType>
  </xs:element>
</xs:schema>
"""


def build_ddsp(
    *,
    product_version: str = "1.4.1.0",
    main_xsd: str = _SIMPLE_MAIN_XSD,
    general_xsd: str = _SIMPLE_GENERAL_XSD,
) -> bytes:
    """Build a bare DDSP XML document with GeneralData and MainData sections."""
    text = (
        f'<dsp:dataSourcePackage xmlns:dsp="{DDSP_NS}" '
        'xmlns:xse="http://schemas.docentric.com/xml-schema-extensions">'
        f'<dsp:systemInfo dsp:productVersion="{escape(product_version)}" '
        'dsp:flavourLabel="Mail Merge"/>'
        "<dsp:dataSections>"
        f'<dsp:dataSection dsp:type="GeneralData"><dsp:schema>{general_xsd}</dsp:schema>'
        "</dsp:dataSection>"
        f'<dsp:dataSection dsp:type="MainData"><dsp:schema>{main_xsd}</dsp:schema>'
        "</dsp:dataSection>"
        "</dsp:dataSections>"
        "</dsp:dataSourcePackage>"
    )
    return text.encode("utf-8")


def build_axpp(
    docx: bytes,
    *,
    extra_xml: bytes | None = None,
    product_version: str = "4.0.1.1128",
) -> bytes:
    """Build a fake AXPP whose members use AXPP-style backslash names."""
    files = {
        "Project\\Synthetic.rnrproj": b'<Project Name="Synthetic"/>',
        "ProjectItem\\AxResource\\ResourceContent\\Data\\Synthetic.Report.docx": docx,
        "ProjectItem\\AxResource\\Synthetic.Report.xml": (
            extra_xml
            if extra_xml is not None
            else build_project_data(product_version=product_version)
        ),
    }
    return _zip(files)


_REFERENCE_DDSP_TEMPLATE: Final = """<?xml version="1.0" encoding="utf-8"?>
<dsp:dataSourcePackage xmlns:dsp="{ddsp_ns}" xmlns:xse="{xse_ns}">
  <dsp:design>
    <dsp:languages>
      <dsp:language dsp:value="EN-US"/>
      <dsp:language dsp:value="de"/>
    </dsp:languages>
  </dsp:design>
  <dsp:systemInfo dsp:productVersion="1.4.9.0" dsp:flavour="Mail Merge"
      dsp:flavourLabel="Synthetic Mail Merge" dsp:language="EN-US">
    <dsp:mailMerge dsp:templateId="SyntheticTemplate" dsp:docuTypeId="SyntheticDocType"/>
  </dsp:systemInfo>
  <dsp:labels>
    <dsp:label dsp:code="@SYN001">
      <dsp:text dsp:language="EN-US" dsp:value="Order lines"/>
      <dsp:text dsp:language="de" dsp:value="Auftragszeilen"/>
    </dsp:label>
    <dsp:label dsp:code="@SYN002">
      <dsp:text dsp:language="EN-US" dsp:value="Order number"/>
    </dsp:label>
  </dsp:labels>
  <dsp:dataSections>
    <dsp:dataSection dsp:type="GeneralData">
      <dsp:schema>
        <xs:schema xmlns:xs="{xsd_ns}" xmlns:xse="{xse_ns}">
          <xs:element name="GeneralData">
            <xs:complexType>
              <xs:sequence>
                <xs:element name="Company">
                  <xs:complexType>
                    <xs:attribute name="Name" type="xs:string" use="required">
                      <xs:annotation><xs:appinfo>
                        <xse:label xse:text="Company name"/>
                      </xs:appinfo></xs:annotation>
                    </xs:attribute>
                    <xs:attribute name="Logo" type="xs:base64Binary"/>
                  </xs:complexType>
                </xs:element>
              </xs:sequence>
            </xs:complexType>
          </xs:element>
        </xs:schema>
      </dsp:schema>
      <dsp:data>
        <dsp:GeneralData>
          <dsp:Company Name="Synthetic Company" Logo="U1lOVEhFVElD"/>
        </dsp:GeneralData>
      </dsp:data>
    </dsp:dataSection>
    <dsp:dataSection dsp:type="MainData">
      <dsp:schema>
        <xs:schema xmlns:xs="{xsd_ns}" xmlns:xse="{xse_ns}">
          <xs:complexType name="TaxRecord">
            <xs:attribute name="Code" type="xs:string" use="optional"/>
            <xs:attribute name="Rate" type="xs:decimal" use="optional"/>
          </xs:complexType>
          <xs:element name="Order">
            <xs:complexType>
              <xs:sequence>
                <xs:element name="Lines">
                  <xs:complexType>
                    <xs:choice minOccurs="0" maxOccurs="unbounded">
                      <xs:element name="Line">
                        <xs:annotation><xs:appinfo>
                          <xse:label xse:text="Order lines" xse:refCode="@SYN001"/>
                        </xs:appinfo></xs:annotation>
                        <xs:complexType>
                          <xs:sequence>
                            <xs:element name="Taxes" minOccurs="0">
                              <xs:complexType>
                                <xs:choice minOccurs="0" maxOccurs="unbounded">
                                  <xs:element name="Tax" type="TaxRecord"/>
                                </xs:choice>
                              </xs:complexType>
                            </xs:element>
                          </xs:sequence>
                          <xs:attribute name="Sku" type="xs:string" use="required"/>
                          <xs:attribute name="Quantity" type="xs:long"/>
                          <xs:attribute name="Price" type="xs:decimal"/>
                        </xs:complexType>
                      </xs:element>
                    </xs:choice>
                  </xs:complexType>
                </xs:element>
                <xs:any minOccurs="0"/>
              </xs:sequence>
              <xs:attribute name="Number" type="xs:string" use="required"/>
              <xs:attribute name="IssuedOn" type="xs:date"/>
              <xs:attribute name="UpdatedAt" type="xs:dateTime"/>
              <xs:attribute name="NetAmount" type="xs:decimal"/>
              <xs:attribute name="IsPaid" type="xs:boolean"/>
              <xs:attribute name="Logo" type="xs:base64Binary"/>
              <xs:attribute name="Website" type="xs:anyURI"/>
              <xs:attribute name="CopyCount" type="xs:integer"/>
            </xs:complexType>
          </xs:element>
        </xs:schema>
      </dsp:schema>
      <dsp:data>
        <dsp:Order Number="SO-1" IssuedOn="2026-01-15" UpdatedAt="2026-01-15T10:00:00Z"
            NetAmount="123.45" IsPaid="true" Logo="U1lOVEhFVElD"
            Website="https://example.invalid" CopyCount="2">
          <dsp:Lines>
            <dsp:Line Sku="A-1" Quantity="2" Price="10.50">
              <dsp:Taxes><dsp:Tax Code="VAT" Rate="20"/></dsp:Taxes>
            </dsp:Line>
            <dsp:Line Sku="B-2" Quantity="1" Price="99.00">
              <dsp:Taxes><dsp:Tax Code="VAT" Rate="20"/><dsp:Tax Code="LOCAL" Rate="5"/></dsp:Taxes>
            </dsp:Line>
          </dsp:Lines>
        </dsp:Order>
      </dsp:data>
    </dsp:dataSection>
    <dsp:dataSection dsp:type="Parameters">
      <dsp:schema>
        <xs:schema xmlns:xs="{xsd_ns}">
          <xs:element name="Parameters">
            <xs:complexType>
              <xs:attribute name="IncludeDraft" type="xs:boolean"/>
              <xs:attribute name="CopyCount" type="xs:integer"/>
            </xs:complexType>
          </xs:element>
        </xs:schema>
      </dsp:schema>
      <dsp:data>
        <dsp:Parameters IncludeDraft="false" CopyCount="2"/>
      </dsp:data>
    </dsp:dataSection>
  </dsp:dataSections>
</dsp:dataSourcePackage>
"""


EMBEDDED_MAIN_XSD: Final = """
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           xmlns:xse="http://schemas.docentric.com/xml-schema-extensions">
  <xs:complexType name="Enum">
    <xs:attribute name="Value" type="xs:integer"/>
    <xs:attribute name="Text" type="xs:string"/>
  </xs:complexType>
  <xs:element name="Root">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="Lines" minOccurs="0">
          <xs:complexType>
            <xs:choice minOccurs="0" maxOccurs="unbounded">
              <xs:element name="Line">
                <xs:annotation><xs:appinfo>
                  <xse:label xse:text="Order line" xse:refCode="@SYN010"/>
                </xs:appinfo></xs:annotation>
                <xs:complexType>
                  <xs:attribute name="ItemId" type="xs:string"/>
                  <xs:attribute name="Amount" type="xs:decimal"/>
                  <xs:attribute name="Quantity" type="xs:integer"/>
                </xs:complexType>
              </xs:element>
            </xs:choice>
          </xs:complexType>
        </xs:element>
        <xs:element name="Status" type="Enum" minOccurs="0"/>
      </xs:sequence>
      <xs:attribute name="Number" type="xs:string">
        <xs:annotation><xs:appinfo>
          <xse:label xse:text="Order number" xse:refCode="@SYN011"/>
        </xs:appinfo></xs:annotation>
      </xs:attribute>
      <xs:attribute name="IssuedOn" type="xs:date"/>
      <xs:attribute name="IsPaid" type="xs:boolean"/>
      <xs:attribute name="Logo" type="xs:base64Binary"/>
      <xs:attribute name="Name" type="xs:string"/>
      <xs:attribute name="Total" type="xs:decimal"/>
    </xs:complexType>
  </xs:element>
</xs:schema>
"""

EMBEDDED_GENERAL_XSD: Final = """
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="GeneralData">
    <xs:complexType>
      <xs:attribute name="Company" type="xs:string"/>
    </xs:complexType>
  </xs:element>
</xs:schema>
"""

EMBEDDED_MAIN_PREVIEW: Final = (
    '<Root Number="T-1" IssuedOn="2026-01-15" IsPaid="true" Name="Synthetic" Total="9.50">'
    '<Lines><Line ItemId="A" Amount="1.50" Quantity="1"/>'
    '<Line ItemId="B" Amount="8.00" Quantity="2"/></Lines>'
    '<Status Value="1" Text="Open"/>'
    "</Root>"
)


@dataclass(frozen=True)
class EmbeddedDataSourceSpec:
    """One DataSource with an embedded XSD and optional PreviewData."""

    name: str = "MainData"
    xsd: str = EMBEDDED_MAIN_XSD
    data_section_type: str | None = "1"
    preview: str | None = EMBEDDED_MAIN_PREVIEW
    include_schema: bool = True
    namespace_mappings: tuple[tuple[str, str], ...] = (("xs", "http://www.w3.org/2001/XMLSchema"),)


def build_embedded_project_data(
    elements: tuple[ElementSpec, ...] = (),
    *,
    sources: tuple[EmbeddedDataSourceSpec, ...] = (EmbeddedDataSourceSpec(),),
    product_version: str = "3.0.0.998",
) -> bytes:
    """Build ProjectData with real DataSource/Schema/XsdList/SampleXml parts."""
    rendered_sources: list[str] = []
    for source in sources:
        attrs = f'Name="{escape(source.name)}" DataKind="2"'
        if source.data_section_type is not None:
            attrs += f' dataSectionType="{escape(source.data_section_type)}"'
        children: list[str] = []
        if source.include_schema:
            mappings = "".join(
                f'<XmlNamespaceMapping Prefix="{escape(prefix)}" Name="{escape(uri)}"/>'
                for prefix, uri in source.namespace_mappings
            )
            children.append(
                '<Schema Origin="2">'
                f"<XsdList><MainXsd>{source.xsd}</MainXsd></XsdList>"
                f"<XmlNamespaceMappings>{mappings}</XmlNamespaceMappings>"
                "</Schema>"
            )
        if source.preview is not None:
            children.append(f"<PreviewData><SampleXml>{source.preview}</SampleXml></PreviewData>")
        rendered_sources.append(f"<DataSource {attrs}>{''.join(children)}</DataSource>")
    element_xml = "".join(_render_element(element) for element in elements)
    text = (
        f'<ProjectData xmlns="{PROJECT_DATA_NS}" ProductId="3" '
        f'ProductVersion="{escape(product_version)}">'
        '<UISettings xmlns=""/>'
        f'<DataSources xmlns="">{"".join(rendered_sources)}</DataSources>'
        f'<Elements xmlns="">{element_xml}</Elements>'
        "</ProjectData>"
    )
    return text.encode("utf-8")


def build_embedded_docx(
    elements: tuple[ElementSpec, ...] = (),
    *,
    sources: tuple[EmbeddedDataSourceSpec, ...] = (EmbeddedDataSourceSpec(),),
    item_index: int = 1,
) -> bytes:
    """Build a synthetic DOCX whose customXml carries an embedded schema."""
    project_data = build_embedded_project_data(elements, sources=sources)
    return build_docx(custom_parts=project_data_parts(project_data, item_index=item_index))


def build_reference_ddsp() -> bytes:
    """Build a synthetic, realistic bare DDSP with nested collections and labels.

    This is entirely fixture code: no fragment, label text or value from the
    Docentric example archive is used.
    """
    return _REFERENCE_DDSP_TEMPLATE.format(
        ddsp_ns=DDSP_NS,
        xse_ns="http://schemas.docentric.com/xml-schema-extensions",
        xsd_ns=XSD_NS,
    ).encode("utf-8")


def build_story_part(root: str, controls: tuple[ControlSpec, ...]) -> bytes:
    """Build a minimal Word story part containing synthetic content controls."""
    from lxml import etree

    rendered = "".join(
        etree.tostring(_control_element(control), encoding="unicode") for control in controls
    )
    text = f'<w:{root} xmlns:w="{W_NS}"><w:p>{rendered}</w:p></w:{root}>'
    return text.encode("utf-8")


def build_zip(files: dict[str, bytes]) -> bytes:
    """Build a deterministic synthetic ZIP."""
    return _zip(files)


__all__ = [
    "EMBEDDED_GENERAL_XSD",
    "EMBEDDED_MAIN_PREVIEW",
    "EMBEDDED_MAIN_XSD",
    "MISSING_STORE_ITEM_ID",
    "STORE_ITEM_ID",
    "ControlSpec",
    "ElementSpec",
    "EmbeddedDataSourceSpec",
    "build_axpp",
    "build_ddsp",
    "build_docx",
    "build_embedded_docx",
    "build_embedded_project_data",
    "build_project_data",
    "build_reference_ddsp",
    "build_story_part",
    "build_zip",
    "project_data_parts",
]
