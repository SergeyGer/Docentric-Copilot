"""Edge cases for D365 extraction and binding resolution.

These fixtures exercise the bounded walker, DDSP fallback sections and the
path-expression grammar. They are entirely synthetic.
"""

from __future__ import annotations

from docentric_copilot.reference import (
    BindingStatus,
    ReferenceLimits,
    SchemaSourceKind,
    analyze_d365_bytes,
    extract_d365_schema,
)

from tests.reference_fixtures import (
    DDSP_NS,
    ElementSpec,
    EmbeddedDataSourceSpec,
    build_docx,
    build_embedded_docx,
    build_embedded_project_data,
    build_project_data,
    project_data_parts,
)


def _statuses(report) -> dict[str, str]:
    return {item.element_id: item.status.value for item in report.binding_results}


def _ddsp(sections: str, *, version: str = "1.4.0.0") -> bytes:
    return (
        f'<dsp:dataSourcePackage xmlns:dsp="{DDSP_NS}">'
        f'<dsp:systemInfo dsp:productVersion="{version}"/>'
        f"<dsp:dataSections>{sections}</dsp:dataSections>"
        "</dsp:dataSourcePackage>"
    ).encode()


def test_ddsp_with_a_schemaless_section_is_flagged_but_usable() -> None:
    ddsp = _ddsp(
        '<dsp:dataSection dsp:type="Empty"/>'
        '<dsp:dataSection dsp:type="MainData">'
        "<dsp:schema>"
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        '<xs:element name="Root"><xs:complexType>'
        '<xs:attribute name="Number" type="xs:string"/>'
        "</xs:complexType></xs:element>"
        "</xs:schema>"
        "</dsp:schema>"
        '<dsp:data><dsp:Root Number="1"/></dsp:data>'
        "</dsp:dataSection>"
    )
    elements = (ElementSpec(1, "Field", "MainData", "@Number"),)
    custom = project_data_parts(build_project_data(elements))
    report = analyze_d365_bytes(
        build_docx(custom_parts=custom),
        filename="Fallback.docx",
        ddsp_data=ddsp,
        ddsp_name="Fallback.ddsp",
    )
    assert report.schema_source is SchemaSourceKind.DDSP
    assert report.schema_summary.sources == 2
    assert _statuses(report) == {"1": "resolved"}
    document = extract_d365_schema(
        build_docx(custom_parts=custom),
        filename="Fallback.docx",
        ddsp_data=ddsp,
        ddsp_name="Fallback.ddsp",
    )
    assert any(item.code == "data_section_schema_missing" for item in document.diagnostics)
    assert document.contract_version == "1.4.0.0"
    assert any(source.provenance.part == "Fallback.ddsp" for source in document.canonical.sources)


def test_ddsp_without_data_sections_is_unavailable() -> None:
    elements = (ElementSpec(1, "Field", "MainData", "@Number"),)
    custom = project_data_parts(build_project_data(elements))
    report = analyze_d365_bytes(
        build_docx(custom_parts=custom),
        filename="NoSections.docx",
        ddsp_data=_ddsp(""),
        ddsp_name="NoSections.ddsp",
    )
    assert report.schema_source is SchemaSourceKind.UNAVAILABLE
    assert report.counts.schema_unavailable == 1
    assert any(item.code == "ddsp_no_data_sections" for item in report.diagnostics)


def test_multiple_project_data_parts_make_duplicate_sources_ambiguous() -> None:
    elements = (ElementSpec(1, "Field", "MainData", "@Number"),)
    first = project_data_parts(build_embedded_project_data(elements), item_index=1)
    second = project_data_parts(build_embedded_project_data(), item_index=2)
    custom = {**first, **second}
    report = analyze_d365_bytes(build_docx(custom_parts=custom), filename="TwoParts.docx")
    assert report.counts.total == 1
    assert report.counts.ambiguous == 1
    assert report.counts.resolved == 0
    assert "duplicate_source_name" in report.binding_results[0].diagnostic_codes


def test_element_and_source_limit_diagnostics() -> None:
    elements = tuple(ElementSpec(index, "Field", "MainData", "@Number") for index in range(1, 5))
    docx = build_embedded_docx(elements)
    document = extract_d365_schema(
        docx,
        filename="Limited.docx",
        limits=ReferenceLimits(max_schema_nodes=2),
    )
    assert any(item.code == "project_data_element_limit" for item in document.diagnostics)

    sources = tuple(
        EmbeddedDataSourceSpec(
            name=f"Source{index}",
            data_section_type=str(index),
            preview=None,
        )
        for index in range(1, 66)
    )
    huge_docx = build_embedded_docx((), sources=sources)
    huge = extract_d365_schema(huge_docx, filename="ManySources.docx")
    assert len(huge.canonical.sources) == 64
    assert any(item.code == "data_source_limit" for item in huge.diagnostics)


def test_invalid_and_duplicate_elements_are_reported() -> None:
    elements = (
        ElementSpec(1, "Field", "MainData", "@Number"),
        ElementSpec(1, "Field", "MainData", "@Number"),
        ElementSpec(2, "Field", "MainData", "@Missing"),
    )
    document = extract_d365_schema(build_embedded_docx(elements), filename="Duplicates.docx")
    assert any(item.code == "duplicate_element_id" for item in document.diagnostics)
    assert len(document.elements) == 3


def test_unnamed_data_source_gets_an_explicit_diagnostic() -> None:
    source = EmbeddedDataSourceSpec(name="", preview=None)
    document = extract_d365_schema(
        build_embedded_docx(
            (ElementSpec(1, "Field", "DataSource1", "@Number"),),
            sources=(source,),
        ),
        filename="Unnamed.docx",
    )
    assert any(item.code == "data_source_name_missing" for item in document.diagnostics)
    assert document.canonical.sources[0].name == "DataSource1"


def test_named_types_groups_extension_any_and_multiple_roots() -> None:
    xsd = """
    <xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
      <xs:group name="Common">
        <xs:sequence>
          <xs:attribute name="GroupAttr" type="xs:string"/>
        </xs:sequence>
      </xs:group>
      <xs:complexType name="Base">
        <xs:attribute name="Number" type="xs:string"/>
      </xs:complexType>
      <xs:complexType name="Derived">
        <xs:complexContent>
          <xs:extension base="Base">
            <xs:attribute name="Extra" type="xs:string"/>
          </xs:extension>
        </xs:complexContent>
      </xs:complexType>
      <xs:complexType name="TextValue">
        <xs:simpleContent>
          <xs:extension base="xs:string">
            <xs:attribute name="Lang" type="xs:string"/>
          </xs:extension>
        </xs:simpleContent>
      </xs:complexType>
      <xs:complexType name="Recursive">
        <xs:sequence>
          <xs:element name="Child" type="Recursive" minOccurs="0"/>
        </xs:sequence>
      </xs:complexType>
      <xs:element name="Root">
        <xs:complexType>
          <xs:sequence>
            <xs:group ref="Common"/>
            <xs:any minOccurs="0" maxOccurs="unbounded"/>
            <xs:element name="Child" type="Derived" minOccurs="0"/>
            <xs:element name="Text" type="TextValue" minOccurs="0"/>
            <xs:element name="Node" type="Recursive" minOccurs="0"/>
          </xs:sequence>
          <xs:attribute name="Number" type="xs:string"/>
          <xs:anyAttribute/>
        </xs:complexType>
      </xs:element>
      <xs:element name="OtherRoot">
        <xs:complexType>
          <xs:attribute name="Number" type="xs:string"/>
        </xs:complexType>
      </xs:element>
    </xs:schema>
    """
    source = EmbeddedDataSourceSpec(xsd=xsd, preview=None)
    document = extract_d365_schema(
        build_embedded_docx((), sources=(source,)),
        filename="Features.docx",
    )
    raw_paths = {field.raw_path for field in document.canonical.fields}
    assert "Root/Child/@Number" in raw_paths
    assert "Root/Child/@Extra" in raw_paths
    assert "Root/Text/@Lang" in raw_paths
    assert "Root/@GroupAttr" in raw_paths
    assert "Root/Number" not in raw_paths
    assert any(item.code == "xsd_any_not_supported" for item in document.diagnostics)
    assert any(item.code == "xsd_any_attribute_not_supported" for item in document.diagnostics)
    assert any("recursive_schema_type" in warning for warning in document.warnings)
    assert document.canonical.sources[0].root_names == ["OtherRoot", "Root"]

    report = analyze_d365_bytes(
        build_embedded_docx(
            (ElementSpec(1, "Field", "MainData", "@Number"),),
            sources=(source,),
        ),
        filename="AmbiguousRoots.docx",
    )
    assert report.binding_results[0].status is BindingStatus.AMBIGUOUS
    assert "duplicate_schema_path" in report.binding_results[0].diagnostic_codes


def test_path_grammar_accepts_documented_forms_and_rejects_expressions() -> None:
    elements = (
        ElementSpec(1, "Field", "MainData", "Root.@Number", "System.String"),
        ElementSpec(2, "Field", "MainData", "/@Number", "System.String"),
        ElementSpec(3, "Field", "MainData", "'@Number'", "System.String"),
        ElementSpec(4, "Field", " MainData ", "@Number", "System.String"),
        ElementSpec(5, "Field", "MainData", "@Number/Child", "System.String"),
        ElementSpec(6, "Field", "MainData", "../../@Number", "System.String"),
        ElementSpec(7, "Field", "MainData", "@Number extra", "System.String"),
    )
    report = analyze_d365_bytes(build_embedded_docx(elements), filename="Paths.docx")
    statuses = _statuses(report)
    assert statuses["1"] == "resolved"
    assert statuses["2"] == "resolved"
    assert statuses["3"] == "resolved"
    assert statuses["4"] == "resolved"
    assert statuses["5"] == "unsupported_expression"
    assert statuses["6"] == "unknown_path"
    assert statuses["7"] == "unsupported_expression"


def test_relative_navigation_out_of_scope_is_unknown() -> None:
    elements = (
        ElementSpec(1, "List", "MainData", "Lines/Line", None, child_ids=(2,)),
        ElementSpec(2, "Field", ".", "../../../../@Number", "System.String"),
    )
    report = analyze_d365_bytes(build_embedded_docx(elements), filename="Navigation.docx")
    assert _statuses(report) == {"1": "resolved", "2": "unknown_path"}
    assert "path_navigation_invalid" in report.binding_results[1].diagnostic_codes


def test_unresolved_schema_type_is_not_reported_as_resolved() -> None:
    xsd = """
    <xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
      <xs:element name="Root">
        <xs:complexType>
          <xs:attribute name="Number" type="MissingNamedType"/>
        </xs:complexType>
      </xs:element>
    </xs:schema>
    """
    source = EmbeddedDataSourceSpec(xsd=xsd, preview=None)
    report = analyze_d365_bytes(
        build_embedded_docx(
            (ElementSpec(1, "Field", "MainData", "@Number", "System.String"),),
            sources=(source,),
        ),
        filename="UnknownType.docx",
    )
    assert report.binding_results[0].status is BindingStatus.UNSUPPORTED_EXPRESSION
    assert "schema_type_unresolved" in report.binding_results[0].diagnostic_codes
