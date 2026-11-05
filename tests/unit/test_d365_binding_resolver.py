"""Tests for the canonical D365 binding resolver and its status taxonomy (PR-03)."""

from __future__ import annotations

import json

from docentric_copilot.reference import (
    BindingStatus,
    ReferenceLimits,
    SchemaSourceKind,
    analyze_d365_bytes,
    binding_report_json,
    build_binding_report,
    extract_d365_schema,
)

from tests.reference_fixtures import (
    EMBEDDED_MAIN_XSD,
    ElementSpec,
    EmbeddedDataSourceSpec,
    build_ddsp,
    build_docx,
    build_embedded_docx,
    build_embedded_project_data,
    build_project_data,
    project_data_parts,
)

ALL_STATUSES = {status.value for status in BindingStatus}


def _statuses(report) -> dict[str, str]:
    return {item.element_id: item.status.value for item in report.binding_results}


def _by_id(report) -> dict[str, object]:
    return {item.element_id: item for item in report.binding_results}


def test_resolved_bindings_carry_source_path_scope_type_and_evidence() -> None:
    elements = (
        ElementSpec(1, "Field", "MainData", "@Number", "System.String"),
        ElementSpec(2, "List", "MainData", "Lines/Line", None, child_ids=(3, 4)),
        ElementSpec(3, "Field", ".", "@ItemId", "System.String"),
        ElementSpec(4, "Field", ".", "@Amount", "System.Decimal"),
        ElementSpec(5, "If", "MainData", "@IsPaid", "System.Boolean"),
        ElementSpec(6, "Field", "MainData", "Status", "System.String"),
        ElementSpec(7, "SummaryField", "MainData", "Lines/Line", None),
    )
    payload = build_embedded_docx(elements)
    report = analyze_d365_bytes(payload, filename="Synthetic.Report.docx")

    assert report.schema_source is SchemaSourceKind.PROJECTDATA
    assert report.platform == "D365FO"
    assert report.runtime_compatibility == "not_tested"
    assert report.schema_evidence
    assert report.counts.total == 7
    assert report.counts.resolved == 7
    assert report.counts.resolved_with_evidence == 7
    assert report.counts.resolved_without_evidence == 0

    results = _by_id(report)
    number = results["1"]
    assert number.status is BindingStatus.RESOLVED
    assert number.raw_path == "@Number"
    assert number.canonical_path == "MainData/Root/@Number"
    assert number.source_id == "customXml/item1.xml#dataSource[1]"
    assert number.evidence is not None
    assert "customXml/item1.xml#" in number.evidence
    assert number.schema_type == "xs:string"
    assert number.result_data_type == "System.String"

    line = results["2"]
    assert line.status is BindingStatus.RESOLVED
    assert line.canonical_path == "MainData/Root/Lines/Line"
    assert line.collection_scope == "MainData/Root/Lines/Line"

    item = results["3"]
    assert item.status is BindingStatus.RESOLVED
    assert item.raw_source == "."
    assert item.canonical_path == "MainData/Root/Lines/Line/@ItemId"
    assert item.collection_scope == "MainData/Root/Lines/Line"

    assert results["5"].schema_type == "xs:boolean"
    assert results["6"].schema_type == "Enum"
    # A SummaryField is an aggregate over a collection, so a collection path is
    # a valid target rather than a scalar/collection conflict.
    assert results["7"].status is BindingStatus.RESOLVED

    for result in report.binding_results:
        assert result.status.value in ALL_STATUSES
        assert result.element_id
        assert result.element_part == "customXml/item1.xml"
        if result.status is BindingStatus.RESOLVED:
            assert result.source_id and result.canonical_path and result.evidence


def test_report_json_is_stable_and_has_the_spec_shape() -> None:
    payload = build_embedded_docx((ElementSpec(1, "Field", "MainData", "@Number"),))
    first = analyze_d365_bytes(payload, filename="Synthetic.docx")
    second = analyze_d365_bytes(payload, filename="Synthetic.docx")
    assert binding_report_json(first) == binding_report_json(second)
    text = binding_report_json(first)
    data = json.loads(text)
    assert {
        "template_id",
        "platform",
        "schema_source",
        "schema_evidence",
        "binding_results",
        "runtime_compatibility",
        "counts",
        "schema_summary",
        "diagnostics",
        "warnings",
    } <= set(data)
    assert data["platform"] == "D365FO"
    assert data["runtime_compatibility"] == "not_tested"
    assert data["counts"]["by_status"] == {
        "ambiguous": 0,
        "resolved": 1,
        "schema_unavailable": 0,
        "type_mismatch": 0,
        "unknown_path": 0,
        "unsupported_expression": 0,
    }
    binding = data["binding_results"][0]
    assert {"element_id", "status", "raw_path", "canonical_path", "source_id", "evidence"} <= set(
        binding
    )
    assert text.endswith("\n")


def test_label_data_path_uses_the_section_mapping() -> None:
    label = ElementSpec(
        1,
        "Label",
        None,
        None,
        properties={"DataSection": "1", "DataXPath": "@Number"},
    )
    report = analyze_d365_bytes(build_embedded_docx((label,)), filename="Label.docx")
    result = report.binding_results[0]
    assert result.binding_kind.value == "label_data_path"
    assert result.raw_source is None
    assert result.raw_path == "@Number"
    assert result.status is BindingStatus.RESOLVED
    assert result.canonical_path == "MainData/Root/@Number"

    missing_section = ElementSpec(
        2,
        "Label",
        None,
        None,
        properties={"DataSection": "9", "DataXPath": "@Number"},
    )
    missing = analyze_d365_bytes(build_embedded_docx((missing_section,)), filename="Label.docx")
    assert missing.binding_results[0].status is BindingStatus.UNKNOWN_PATH
    assert "data_section_source_missing" in missing.binding_results[0].diagnostic_codes


def test_ddsp_fallback_resolves_when_embedded_schema_is_missing() -> None:
    elements = (ElementSpec(1, "Field", "MainData", "@Number", "System.String"),)
    custom = project_data_parts(build_project_data(elements))
    docx = build_docx(custom_parts=custom)
    report = analyze_d365_bytes(
        docx,
        filename="Synthetic.docx",
        ddsp_data=build_ddsp(),
        ddsp_name="Synthetic.ddsp",
    )
    assert report.schema_source is SchemaSourceKind.DDSP
    assert report.binding_results[0].status is BindingStatus.RESOLVED
    assert report.binding_results[0].canonical_path == "MainData/Root/@Number"
    assert report.binding_results[0].evidence is not None
    assert report.binding_results[0].evidence.startswith("Synthetic.ddsp#")


def test_duplicate_sources_are_ambiguous_never_resolved() -> None:
    other_xsd = EMBEDDED_MAIN_XSD.replace('name="Root"', 'name="OtherRoot"', 1)
    sources = (
        EmbeddedDataSourceSpec(name="MainData", xsd=EMBEDDED_MAIN_XSD, data_section_type="1"),
        EmbeddedDataSourceSpec(
            name="MainData",
            xsd=other_xsd,
            data_section_type="2",
            preview=None,
        ),
    )
    elements = (ElementSpec(1, "Field", "MainData", "@Number", "System.String"),)
    report = analyze_d365_bytes(
        build_embedded_docx(elements, sources=sources),
        filename="DuplicateSources.docx",
    )
    assert _statuses(report) == {"1": "ambiguous"}
    result = report.binding_results[0]
    assert "duplicate_source_name" in result.diagnostic_codes
    assert result.canonical_path is None
    assert report.counts.resolved == 0


def test_duplicate_schema_paths_are_ambiguous_never_resolved() -> None:
    duplicate_xsd = """
    <xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
      <xs:element name="Root">
        <xs:complexType>
          <xs:attribute name="Number" type="xs:string"/>
          <xs:attribute name="Number" type="xs:decimal"/>
        </xs:complexType>
      </xs:element>
    </xs:schema>
    """
    source = EmbeddedDataSourceSpec(xsd=duplicate_xsd, preview=None)
    elements = (ElementSpec(1, "Field", "MainData", "@Number", "System.String"),)
    report = analyze_d365_bytes(
        build_embedded_docx(elements, sources=(source,)),
        filename="DuplicatePaths.docx",
    )
    assert _statuses(report) == {"1": "ambiguous"}
    assert "duplicate_schema_path" in report.binding_results[0].diagnostic_codes


def test_wrong_context_path_is_unknown_path() -> None:
    elements = (
        ElementSpec(1, "List", "MainData", "Missing/Line", None, child_ids=(2,)),
        ElementSpec(2, "Field", ".", "@ItemId", "System.String"),
    )
    report = analyze_d365_bytes(build_embedded_docx(elements), filename="WrongContext.docx")
    assert _statuses(report) == {"1": "unknown_path", "2": "unknown_path"}
    child = _by_id(report)["2"]
    assert "relative_context_unresolved" in child.diagnostic_codes


def test_non_collection_context_is_unknown_path_for_the_child() -> None:
    elements = (
        ElementSpec(1, "List", "MainData", "Lines", None, child_ids=(2,)),
        ElementSpec(2, "Field", ".", "@ItemId", "System.String"),
    )
    report = analyze_d365_bytes(build_embedded_docx(elements), filename="WrongScope.docx")
    assert _statuses(report) == {"1": "type_mismatch", "2": "unknown_path"}
    assert "list_requires_collection" in _by_id(report)["1"].diagnostic_codes
    assert "relative_context_unresolved" in _by_id(report)["2"].diagnostic_codes


def test_missing_field_and_source_are_unknown_path() -> None:
    elements = (
        ElementSpec(1, "Field", "MainData", "@Missing", "System.String"),
        ElementSpec(2, "Field", "NoSuchSource", "@Number", "System.String"),
    )
    report = analyze_d365_bytes(build_embedded_docx(elements), filename="Missing.docx")
    assert _statuses(report) == {"1": "unknown_path", "2": "unknown_path"}
    assert "path_not_found" in _by_id(report)["1"].diagnostic_codes
    assert "source_not_found" in _by_id(report)["2"].diagnostic_codes
    assert _by_id(report)["1"].suggestions


def test_type_mismatch_has_its_own_diagnostic() -> None:
    elements = (
        ElementSpec(1, "Field", "MainData", "@Total", "System.String"),
        ElementSpec(2, "If", "MainData", "@Number", None),
    )
    report = analyze_d365_bytes(build_embedded_docx(elements), filename="Types.docx")
    assert _statuses(report) == {"1": "type_mismatch", "2": "type_mismatch"}
    first = _by_id(report)["1"]
    assert "result_type_conflict" in first.diagnostic_codes
    assert first.canonical_path == "MainData/Root/@Total"
    assert first.evidence is not None
    assert "if_requires_boolean" in _by_id(report)["2"].diagnostic_codes


def test_list_and_scalar_collection_checks() -> None:
    elements = (
        ElementSpec(1, "List", "MainData", "@Number"),
        ElementSpec(2, "Field", "MainData", "Lines/Line", None),
        ElementSpec(3, "SummaryField", "MainData", "Lines/Line", None),
    )
    report = analyze_d365_bytes(build_embedded_docx(elements), filename="Scopes.docx")
    assert _statuses(report) == {
        "1": "type_mismatch",
        "2": "type_mismatch",
        "3": "resolved",
    }
    assert "list_requires_collection" in _by_id(report)["1"].diagnostic_codes
    assert "scalar_binding_to_collection" in _by_id(report)["2"].diagnostic_codes


def test_unsupported_expressions_are_explicit() -> None:
    elements = (
        ElementSpec(1, "Field", "MainData", "upper-case(@Name)", "System.String"),
        ElementSpec(2, "If", "MainData", "@Total != ''", "System.Boolean"),
        ElementSpec(3, "Field", "MainData", "Lines[1]/@Amount", "System.Decimal"),
        ElementSpec(4, "Field", "Main Data", "@Number", "System.String"),
    )
    report = analyze_d365_bytes(build_embedded_docx(elements), filename="Expressions.docx")
    assert set(_statuses(report).values()) == {"unsupported_expression"}
    assert report.counts.resolved == 0
    for result in report.binding_results:
        assert result.canonical_path is None
        assert result.status is BindingStatus.UNSUPPORTED_EXPRESSION


def test_namespace_prefixes_must_resolve_to_the_data_namespace() -> None:
    namespaced_xsd = EMBEDDED_MAIN_XSD.replace(
        "<xs:schema ",
        '<xs:schema targetNamespace="urn:synthetic:data" ',
        1,
    )
    resolved_source = EmbeddedDataSourceSpec(
        xsd=namespaced_xsd,
        namespace_mappings=(("t", "urn:synthetic:data"),),
    )
    resolved = analyze_d365_bytes(
        build_embedded_docx(
            (ElementSpec(1, "Field", "MainData", "t:Root/@Number", "System.String"),),
            sources=(resolved_source,),
        ),
        filename="Namespaced.docx",
    )
    assert resolved.binding_results[0].status is BindingStatus.RESOLVED

    mismatched = analyze_d365_bytes(
        build_embedded_docx(
            (ElementSpec(1, "Field", "MainData", "t:Root/@Number", "System.String"),),
            sources=(
                EmbeddedDataSourceSpec(
                    namespace_mappings=(("t", "urn:not-the-data-namespace"),),
                ),
            ),
        ),
        filename="MismatchedNamespace.docx",
    )
    assert mismatched.binding_results[0].status is BindingStatus.UNSUPPORTED_EXPRESSION
    assert "namespace_prefix_mismatch" in mismatched.binding_results[0].diagnostic_codes

    unresolved = analyze_d365_bytes(
        build_embedded_docx(
            (ElementSpec(1, "Field", "MainData", "zz:Root/@Number", "System.String"),)
        ),
        filename="UnknownPrefix.docx",
    )
    assert unresolved.binding_results[0].status is BindingStatus.UNSUPPORTED_EXPRESSION
    assert "namespace_prefix_unresolved" in unresolved.binding_results[0].diagnostic_codes


def test_absent_schema_is_explicit_schema_unavailable() -> None:
    elements = (
        ElementSpec(1, "Field", "MainData", "@Number", "System.String"),
        ElementSpec(2, "Field", "GeneralData", "@Company", "System.String"),
    )
    custom = project_data_parts(build_project_data(elements))
    docx = build_docx(custom_parts=custom)
    report = analyze_d365_bytes(docx, filename="NoSchema.docx")
    assert report.schema_source is SchemaSourceKind.UNAVAILABLE
    assert report.schema_evidence == []
    assert report.counts.total == 2
    assert report.counts.schema_unavailable == 2
    assert report.counts.resolved == 0
    assert all(item.status is BindingStatus.SCHEMA_UNAVAILABLE for item in report.binding_results)
    assert all(item.evidence is None for item in report.binding_results)


def test_corrupted_project_data_yields_schema_unavailable() -> None:
    corrupted = b'<ProjectData xmlns="http://Docentric.org/ProjectData.xml"><DataSources>'
    docx = build_docx(custom_parts={"customXml/item1.xml": corrupted})
    report = analyze_d365_bytes(docx, filename="Corrupted.docx")
    assert report.schema_source is SchemaSourceKind.UNAVAILABLE
    assert report.counts.total == 0
    assert report.counts.resolved == 0
    assert any(item.code == "custom_xml_unreadable" for item in report.diagnostics)


def test_ambiguous_data_section_source() -> None:
    sources = (
        EmbeddedDataSourceSpec(name="Alpha", data_section_type="1"),
        EmbeddedDataSourceSpec(name="Beta", data_section_type="1", preview=None),
    )
    label = ElementSpec(
        1,
        "Label",
        None,
        None,
        properties={"DataSection": "1", "DataXPath": "@Number"},
    )
    report = analyze_d365_bytes(
        build_embedded_docx((label,), sources=sources),
        filename="AmbiguousSection.docx",
    )
    assert _statuses(report) == {"1": "ambiguous"}
    assert "data_section_source_ambiguous" in report.binding_results[0].diagnostic_codes


def test_build_binding_report_accepts_an_extracted_document() -> None:
    docx = build_embedded_docx((ElementSpec(1, "Field", "MainData", "@Number"),))
    document = extract_d365_schema(docx, filename="Synthetic.docx")
    report = build_binding_report(document)
    assert report.template_id == document.template_id
    assert report.counts.total == 1
    assert report.schema_summary.sources == 1
    assert report.schema_summary.fields > 0
    assert report.schema_summary.collections == 1
    assert report.schema_summary.available is True
    assert report.schema_summary.preview_data_sources == 1


def test_empty_document_still_produces_a_report() -> None:
    docx = build_docx(custom_parts=project_data_parts(build_embedded_project_data()))
    report = analyze_d365_bytes(docx, filename="Empty.docx")
    assert report.counts.total == 0
    assert report.schema_source is SchemaSourceKind.PROJECTDATA
    assert any(item.code == "no_bindings_to_resolve" for item in report.diagnostics)


def test_limits_are_propagated_to_the_resolver() -> None:
    docx = build_embedded_docx((ElementSpec(1, "Field", "MainData", "@Number"),))
    report = analyze_d365_bytes(
        docx,
        filename="Synthetic.docx",
        limits=ReferenceLimits(max_schema_nodes=2),
    )
    assert report.schema_summary.fields <= 2
