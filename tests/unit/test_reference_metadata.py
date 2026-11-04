"""Synthetic REF-02 metadata-resolver tests (ProjectData join + DDSP paths)."""

from __future__ import annotations

import pytest
from docentric_copilot.errors import InvalidInputError
from docentric_copilot.reference import (
    Classification,
    ControlType,
    ElementKind,
    LinkStatus,
    PathStatus,
    ReferenceLimits,
    ResolutionStatus,
    load_project_data,
    resolve_controls,
    scan_docx,
    schema_from_ddsp,
)

from tests.reference_fixtures import (
    MISSING_STORE_ITEM_ID,
    STORE_ITEM_ID,
    ControlSpec,
    ElementSpec,
    build_ddsp,
    build_docx,
    build_project_data,
    project_data_parts,
)

LIMITS = ReferenceLimits()


def _fixture() -> tuple[object, bytes, bytes]:
    elements = (
        ElementSpec(2330169809, "Field", "MainData", "@Number"),
        ElementSpec(123456789, "Field", "MainData", "Line/@ItemId"),
        ElementSpec(1000, "List", "MainData", "Line", child_ids=(1001,)),
        ElementSpec(1001, "Field", ".", "@Amount"),
        ElementSpec(1002, "If", "MainData", "@Amount > 0"),
        ElementSpec(1003, "List", "MainData", "Line"),
        ElementSpec(1004, "Field", "MainData", "@DoesNotExist"),
        ElementSpec(555, "Field", "MainData", "@Number"),
        ElementSpec(555, "List", "MainData", "Line"),
        ElementSpec(777, "Field", "MainData", "@Number"),
        ElementSpec(777, "Field", "MainData", "@Number"),
    )
    project_data = build_project_data(elements)
    custom = project_data_parts(project_data, decoy_item_index=1)
    controls = (
        ControlSpec(alias="Field", tag="Field", sdt_id=-1964797487, text="@Number"),
        ControlSpec(
            alias="Field",
            tag="Field",
            sdt_id=123456789,
            store_item_id=STORE_ITEM_ID,
            text="@ItemId",
        ),
        ControlSpec(alias="Field", tag="Field", sdt_id=999, text="@Nope"),
        ControlSpec(
            alias="Field",
            tag="Field",
            sdt_id=111,
            store_item_id=MISSING_STORE_ITEM_ID,
            text="@Nope",
        ),
        ControlSpec(alias="Field", tag="Field", sdt_id=555, text="@Collision"),
        ControlSpec(alias="Field", tag="Field", sdt_id=1001, text="@Amount"),
        ControlSpec(alias="If", tag="If", sdt_id=1002, text="condition"),
        ControlSpec(alias="Field", tag="Field", sdt_id=1003, text="@TypeMismatch"),
        ControlSpec(alias="Field", tag="Field", sdt_id=1004, text="@UnknownPath"),
        ControlSpec(alias="Field", tag="Field", sdt_id=777, text="@Shared"),
        ControlSpec(alias="Field", tag="Field", sdt_id=None, text="@NoId"),
        ControlSpec(
            alias="Field",
            tag="Field",
            sdt_id=42,
            control_type="date",
            text="2024-01-01",
        ),
    )
    docx = build_docx(document_controls=controls, custom_parts=custom)
    ddsp = build_ddsp()
    return "ignored", docx, ddsp


@pytest.fixture
def fixture() -> tuple[object, bytes, bytes]:
    return _fixture()


def test_signed_id_maps_to_unsigned_project_data_id(fixture: tuple[object, bytes, bytes]) -> None:
    _unused, docx, ddsp = fixture
    scan = scan_docx(docx, LIMITS)
    bundle = load_project_data(docx, LIMITS)
    schema = schema_from_ddsp(ddsp, name="synthetic.ddsp", limits=LIMITS)
    assert schema is not None
    resolutions = resolve_controls(scan.controls, bundle, schema)
    by_id = {
        control.sdt_id_signed: resolution
        for control, resolution in zip(scan.controls, resolutions, strict=True)
    }

    first = by_id[-1964797487]
    assert first.status is ResolutionStatus.RESOLVED
    assert first.link_status is LinkStatus.RESOLVED_BY_ID
    assert first.path_status is PathStatus.MATCHED
    assert first.element_id_unsigned == "2330169809"
    assert first.normalized_path == "MainData.Root.@Number"


def test_project_data_found_by_namespace_in_item5(fixture: tuple[object, bytes, bytes]) -> None:
    _unused, docx, _ddsp = fixture
    bundle = load_project_data(docx, LIMITS)
    assert [part.summary.part for part in bundle.parts] == ["customXml/item5.xml"]
    assert bundle.parts[0].summary.store_item_id == STORE_ITEM_ID
    assert bundle.store_items[STORE_ITEM_ID] == ["customXml/item5.xml"]
    assert bundle.parts[0].summary.product_version == "3.0.0.998"


def test_store_item_selects_project_data_and_path(fixture: tuple[object, bytes, bytes]) -> None:
    _unused, docx, ddsp = fixture
    scan = scan_docx(docx, LIMITS)
    bundle = load_project_data(docx, LIMITS)
    schema = schema_from_ddsp(ddsp, name="synthetic.ddsp", limits=LIMITS)
    assert schema is not None
    resolutions = resolve_controls(scan.controls, bundle, schema)
    by_id = {
        control.sdt_id_signed: resolution
        for control, resolution in zip(scan.controls, resolutions, strict=True)
    }
    resolution = by_id[123456789]
    assert resolution.status is ResolutionStatus.RESOLVED
    assert resolution.normalized_path == "MainData.Root.Line.@ItemId"


def test_missing_store_item_and_unknown_ids_are_explicit(
    fixture: tuple[object, bytes, bytes],
) -> None:
    _unused, docx, ddsp = fixture
    scan = scan_docx(docx, LIMITS)
    bundle = load_project_data(docx, LIMITS)
    schema = schema_from_ddsp(ddsp, name="synthetic.ddsp", limits=LIMITS)
    assert schema is not None
    resolutions = resolve_controls(scan.controls, bundle, schema)
    by_id = {
        control.sdt_id_signed: resolution
        for control, resolution in zip(scan.controls, resolutions, strict=True)
    }

    assert by_id[111].status is ResolutionStatus.MISSING_PART
    assert by_id[111].link_status is LinkStatus.MISSING_STORE_ITEM
    assert "store_item_part_missing" in by_id[111].diagnostic_codes

    assert by_id[999].status is ResolutionStatus.UNKNOWN_PATH
    assert by_id[999].link_status is LinkStatus.NO_ELEMENT_FOR_ID
    assert by_id[999].element_id_unsigned == "999"

    assert by_id[None].status is ResolutionStatus.UNKNOWN_PATH
    assert by_id[None].link_status is LinkStatus.NO_SDT_ID


def test_duplicate_id_is_shared_but_conflicting_metadata_is_ambiguous(
    fixture: tuple[object, bytes, bytes],
) -> None:
    _unused, docx, ddsp = fixture
    scan = scan_docx(docx, LIMITS)
    bundle = load_project_data(docx, LIMITS)
    schema = schema_from_ddsp(ddsp, name="synthetic.ddsp", limits=LIMITS)
    assert schema is not None
    resolutions = resolve_controls(scan.controls, bundle, schema)
    by_id = {
        control.sdt_id_signed: resolution
        for control, resolution in zip(scan.controls, resolutions, strict=True)
    }
    shared = by_id[777]
    assert shared.status is ResolutionStatus.RESOLVED
    assert shared.link_status is LinkStatus.RESOLVED_BY_ID_SHARED
    assert "duplicate_sdt_id_shared_metadata" in shared.diagnostic_codes

    collision = by_id[555]
    assert collision.status is ResolutionStatus.AMBIGUOUS
    assert collision.link_status is LinkStatus.DUPLICATE_ID_COLLISION
    assert "duplicate_element_id_conflict" in collision.diagnostic_codes


def test_relative_list_binding_is_resolved_against_parent(
    fixture: tuple[object, bytes, bytes],
) -> None:
    _unused, docx, ddsp = fixture
    scan = scan_docx(docx, LIMITS)
    bundle = load_project_data(docx, LIMITS)
    schema = schema_from_ddsp(ddsp, name="synthetic.ddsp", limits=LIMITS)
    assert schema is not None
    resolutions = resolve_controls(scan.controls, bundle, schema)
    by_id = {
        control.sdt_id_signed: resolution
        for control, resolution in zip(scan.controls, resolutions, strict=True)
    }
    relative = by_id[1001]
    assert relative.status is ResolutionStatus.RESOLVED
    assert relative.source_binding is not None
    assert relative.source_binding.source == "MainData"
    assert relative.source_binding.path == "Line/@Amount"
    assert relative.source_binding_raw is not None
    assert relative.source_binding_raw.source == "."
    assert relative.normalized_path == "MainData.Root.Line.@Amount"
    assert "binding_relative_to_parent" in relative.diagnostic_codes


def test_expression_paths_are_not_evaluated(fixture: tuple[object, bytes, bytes]) -> None:
    _unused, docx, ddsp = fixture
    scan = scan_docx(docx, LIMITS)
    bundle = load_project_data(docx, LIMITS)
    schema = schema_from_ddsp(ddsp, name="synthetic.ddsp", limits=LIMITS)
    assert schema is not None
    resolutions = resolve_controls(scan.controls, bundle, schema)
    by_id = {
        control.sdt_id_signed: resolution
        for control, resolution in zip(scan.controls, resolutions, strict=True)
    }
    expression = by_id[1002]
    assert expression.status is ResolutionStatus.RESOLVED
    assert expression.path_status is PathStatus.NOT_CHECKED
    assert "expression_not_validated" in expression.diagnostic_codes


def test_type_mismatch_and_unknown_path_are_ambiguous_or_unknown(
    fixture: tuple[object, bytes, bytes],
) -> None:
    _unused, docx, ddsp = fixture
    scan = scan_docx(docx, LIMITS)
    bundle = load_project_data(docx, LIMITS)
    schema = schema_from_ddsp(ddsp, name="synthetic.ddsp", limits=LIMITS)
    assert schema is not None
    resolutions = resolve_controls(scan.controls, bundle, schema)
    by_id = {
        control.sdt_id_signed: resolution
        for control, resolution in zip(scan.controls, resolutions, strict=True)
    }
    mismatch = by_id[1003]
    assert mismatch.status is ResolutionStatus.AMBIGUOUS
    assert mismatch.link_status is LinkStatus.TYPE_MISMATCH
    assert "alias_metadata_type_mismatch" in mismatch.diagnostic_codes

    unknown = by_id[1004]
    assert unknown.status is ResolutionStatus.UNKNOWN_PATH
    assert unknown.path_status is PathStatus.UNKNOWN
    assert "binding_path_unknown" in unknown.diagnostic_codes


def test_without_schema_id_join_is_not_claimed_as_path_validation(
    fixture: tuple[object, bytes, bytes],
) -> None:
    _unused, docx, _ddsp = fixture
    scan = scan_docx(docx, LIMITS)
    bundle = load_project_data(docx, LIMITS)
    resolutions = resolve_controls(scan.controls, bundle, None)
    by_id = {
        control.sdt_id_signed: resolution
        for control, resolution in zip(scan.controls, resolutions, strict=True)
    }
    first = by_id[-1964797487]
    assert first.status is ResolutionStatus.RESOLVED
    assert first.path_status is PathStatus.NOT_CHECKED
    assert "schema_not_provided" in first.diagnostic_codes
    assert by_id[111].status is ResolutionStatus.MISSING_PART


def test_no_project_data_is_reported_not_discarded() -> None:
    docx = build_docx(
        document_controls=(ControlSpec(alias="Field", tag="Field", sdt_id=123, text="@Value"),)
    )
    scan = scan_docx(docx, LIMITS)
    bundle = load_project_data(docx, LIMITS)
    assert bundle.parts == []
    resolutions = resolve_controls(scan.controls, bundle, None)
    assert len(resolutions) == 1
    assert resolutions[0].status is ResolutionStatus.MISSING_PART
    assert resolutions[0].link_status is LinkStatus.NO_PROJECT_DATA


def test_schema_paths_and_display_forms() -> None:
    schema = schema_from_ddsp(build_ddsp(), name="synthetic.ddsp", limits=LIMITS)
    assert schema is not None
    assert schema.section_names == ["GeneralData", "MainData"]
    assert schema.path_count() > 5

    root_attribute = schema.match("MainData", "@Number")
    assert root_attribute.status is PathStatus.MATCHED
    assert root_attribute.normalized_path == "MainData.Root.@Number"

    root_prefixed = schema.match("MainData", "Root/Line/@ItemId")
    assert root_prefixed.status is PathStatus.MATCHED
    assert root_prefixed.normalized_path == "MainData.Root.Line.@ItemId"

    namespace_prefixed = schema.match("MainData", "/ns0:Root/ns0:Line/@ItemId")
    assert namespace_prefixed.status is PathStatus.MATCHED

    general = schema.match("GeneralData", "CurrentCompany/@Name")
    assert general.status is PathStatus.MATCHED
    assert general.normalized_path == "GeneralData.GeneralData.CurrentCompany.@Name"

    missing_section = schema.match("Parameters", "@Number")
    assert missing_section.status is PathStatus.SECTION_MISSING

    unknown = schema.match("MainData", "Line/@Missing")
    assert unknown.status is PathStatus.UNKNOWN
    assert unknown.suggestions


def test_schema_from_non_ddsp_xml_returns_none() -> None:
    assert schema_from_ddsp(b"<Root/>", name="not-ddsp.xml", limits=LIMITS) is None
    with pytest.raises(InvalidInputError):
        schema_from_ddsp(b"<broken", name="broken.ddsp", limits=LIMITS)


def test_classification_aliases_match_element_types(fixture: tuple[object, bytes, bytes]) -> None:
    _unused, docx, _ddsp = fixture
    scan = scan_docx(docx, LIMITS)
    assert scan.controls[0].classification is Classification.RECOGNIZED
    assert scan.controls[0].element_kind is ElementKind.FIELD
    assert any(control.control_type is ControlType.DATE for control in scan.controls)


def _single_section_ddsp(xsd: str) -> bytes:
    return (
        '<dsp:dataSourcePackage xmlns:dsp="http://schemas.docentric.com/dynamics-ax/data-source-packages">'
        '<dsp:systemInfo dsp:productVersion="1.4.1.0"/>'
        '<dsp:dataSections><dsp:dataSection dsp:type="MainData">'
        f"<dsp:schema>{xsd}</dsp:schema>"
        "</dsp:dataSection></dsp:dataSections>"
        "</dsp:dataSourcePackage>"
    ).encode()


_RICH_XSD = """
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:complexType name="LineType">
    <xs:sequence>
      <xs:element name="Description" type="xs:string"/>
    </xs:sequence>
    <xs:attribute name="ItemId" type="xs:string"/>
  </xs:complexType>
  <xs:element name="Root">
    <xs:complexType>
      <xs:choice>
        <xs:element name="Line" type="LineType" maxOccurs="unbounded"/>
      </xs:choice>
      <xs:attribute name="Number" type="xs:string"/>
    </xs:complexType>
  </xs:element>
</xs:schema>
"""

_SINGLE_SECTION_XSD = """
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="Root">
    <xs:complexType>
      <xs:attribute name="Number" type="xs:string"/>
      <xs:attribute name="Other" type="xs:string"/>
    </xs:complexType>
  </xs:element>
</xs:schema>
"""

_AMBIGUOUS_XSD = """
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="RootA">
    <xs:complexType><xs:attribute name="ItemId" type="xs:string"/></xs:complexType>
  </xs:element>
  <xs:element name="RootB">
    <xs:complexType><xs:attribute name="ItemId" type="xs:string"/></xs:complexType>
  </xs:element>
</xs:schema>
"""


def test_multiple_project_data_parts_are_ambiguous_or_selected_by_id() -> None:
    from tests.reference_fixtures import STORE_ITEM_ID, project_data_parts

    parts: dict[str, bytes] = {}
    parts.update(
        project_data_parts(
            build_project_data((ElementSpec(1, "Field", "MainData", "@Number"),)),
            item_index=5,
            store_item_id=STORE_ITEM_ID,
        )
    )
    parts.update(
        project_data_parts(
            build_project_data(
                (
                    ElementSpec(1, "Field", "MainData", "@Number"),
                    ElementSpec(2, "Field", "MainData", "@Number"),
                )
            ),
            item_index=7,
            store_item_id="{22222222-2222-2222-2222-222222222222}",
        )
    )
    controls = (
        ControlSpec(alias="Field", tag="Field", sdt_id=1),
        ControlSpec(alias="Field", tag="Field", sdt_id=2),
        ControlSpec(alias="Field", tag="Field", sdt_id=1, store_item_id=STORE_ITEM_ID),
    )
    docx = build_docx(document_controls=controls, custom_parts=parts)
    scan = scan_docx(docx, LIMITS)
    bundle = load_project_data(docx, LIMITS)
    assert len(bundle.parts) == 2
    resolutions = resolve_controls(scan.controls, bundle, None)
    by_ordinal = {
        control.ordinal: resolution
        for control, resolution in zip(scan.controls, resolutions, strict=True)
    }

    assert by_ordinal[0].status is ResolutionStatus.AMBIGUOUS
    assert by_ordinal[0].link_status is LinkStatus.MULTIPLE_PROJECT_DATA_PARTS
    assert by_ordinal[1].status is ResolutionStatus.RESOLVED
    assert "multiple_project_data_selected_by_id" in by_ordinal[1].diagnostic_codes
    assert by_ordinal[2].status is ResolutionStatus.RESOLVED


def test_project_data_with_wrong_namespace_is_not_trusted() -> None:
    parts = {
        "customXml/item6.xml": b'<ProjectData xmlns="urn:not-docentric" ProductVersion="9.9"/>'
    }
    bundle = load_project_data(build_docx(custom_parts=parts), LIMITS)
    assert bundle.parts == []
    assert any("project_data_namespace_unexpected" in warning for warning in bundle.warnings)


def test_invalid_element_ids_are_reported_not_dropped() -> None:
    bundle = load_project_data(
        build_docx(custom_parts=project_data_parts(build_project_data((ElementSpec("bad-id"),)))),
        LIMITS,
    )
    assert bundle.parts
    assert bundle.parts[0].summary.element_count == 0
    assert any("invalid_element_metadata" in warning for warning in bundle.warnings)


def test_direct_word_xpath_resolves_when_metadata_binding_is_absent() -> None:
    project_data = build_project_data((ElementSpec(500, "Field", source=None, path=None),))
    docx = build_docx(
        document_controls=(ControlSpec(alias="Field", tag="Field", sdt_id=500, xpath="@Number"),),
        custom_parts=project_data_parts(project_data),
    )
    schema = schema_from_ddsp(
        _single_section_ddsp(_SINGLE_SECTION_XSD), name="single.ddsp", limits=LIMITS
    )
    assert schema is not None
    scan = scan_docx(docx, LIMITS)
    resolution = resolve_controls(scan.controls, load_project_data(docx, LIMITS), schema)[0]
    assert resolution.status is ResolutionStatus.RESOLVED
    assert resolution.normalized_path == "MainData.Root.@Number"
    assert "path_resolved_from_word_binding" in resolution.diagnostic_codes


def test_conflicting_word_and_metadata_bindings_are_ambiguous() -> None:
    project_data = build_project_data((ElementSpec(501, "Field", "MainData", "@Number"),))
    docx = build_docx(
        document_controls=(ControlSpec(alias="Field", tag="Field", sdt_id=501, xpath="@Other"),),
        custom_parts=project_data_parts(project_data),
    )
    schema = schema_from_ddsp(
        _single_section_ddsp(_SINGLE_SECTION_XSD), name="single.ddsp", limits=LIMITS
    )
    assert schema is not None
    resolution = resolve_controls(
        scan_docx(docx, LIMITS).controls, load_project_data(docx, LIMITS), schema
    )[0]
    assert resolution.status is ResolutionStatus.AMBIGUOUS
    assert "conflicting_bindings" in resolution.diagnostic_codes


def test_missing_value_binding_and_unknown_section_are_explicit() -> None:
    project_data = build_project_data(
        (
            ElementSpec(502, "Field", "Parameters", "@Number"),
            ElementSpec(503, "Field", source=None, path=None),
        )
    )
    controls = (
        ControlSpec(alias="Field", tag="Field", sdt_id=502),
        ControlSpec(alias="Field", tag="Field", sdt_id=503),
    )
    docx = build_docx(document_controls=controls, custom_parts=project_data_parts(project_data))
    schema = schema_from_ddsp(build_ddsp(), name="multi.ddsp", limits=LIMITS)
    assert schema is not None
    resolutions = resolve_controls(
        scan_docx(docx, LIMITS).controls, load_project_data(docx, LIMITS), schema
    )
    section_missing, value_missing = resolutions
    assert section_missing.status is ResolutionStatus.UNKNOWN_PATH
    assert section_missing.path_status is PathStatus.SECTION_MISSING
    assert value_missing.status is ResolutionStatus.UNKNOWN_PATH
    assert "value_binding_missing" in value_missing.diagnostic_codes


def test_richer_xsd_type_references_are_indexed() -> None:
    schema = schema_from_ddsp(_single_section_ddsp(_RICH_XSD), name="rich.ddsp", limits=LIMITS)
    assert schema is not None
    line = schema.match("MainData", "Line/@ItemId")
    assert line.status is PathStatus.MATCHED
    description = schema.match("MainData", "Line/Description")
    assert description.status is PathStatus.MATCHED


def test_schema_match_ambiguous_dotted_and_quoted_paths() -> None:
    ambiguous = schema_from_ddsp(
        _single_section_ddsp(_AMBIGUOUS_XSD), name="ambiguous.ddsp", limits=LIMITS
    )
    assert ambiguous is not None
    assert ambiguous.match("MainData", "@ItemId").status is PathStatus.AMBIGUOUS

    schema = schema_from_ddsp(
        _single_section_ddsp(_SINGLE_SECTION_XSD), name="single.ddsp", limits=LIMITS
    )
    assert schema is not None
    assert schema.match("MainData", "Root.@Number").status is PathStatus.MATCHED
    assert schema.match("MainData", '"/Root/@Number"').status is PathStatus.MATCHED
    assert schema.match("MainData", None).status is PathStatus.UNKNOWN


def test_store_item_id_normalization() -> None:
    from docentric_copilot.reference import normalize_store_item_id

    assert normalize_store_item_id(None) is None
    assert normalize_store_item_id("   ") is None
    assert normalize_store_item_id(" abcd ") == "{ABCD}"
    assert normalize_store_item_id("{abcd}") == "{ABCD}"
    assert normalize_store_item_id("abcd") == "{ABCD}"


def test_ddsp_without_data_sections_returns_none() -> None:
    payload = (
        b'<dsp:dataSourcePackage xmlns:dsp="http://schemas.docentric.com/dynamics-ax/'
        b'data-source-packages"><dsp:systemInfo dsp:productVersion="1.0"/></dsp:dataSourcePackage>'
    )
    assert schema_from_ddsp(payload, name="empty.ddsp", limits=LIMITS) is None


def test_itemprops_relationship_is_used_for_store_item_mapping() -> None:
    from tests.reference_fixtures import DS_NS, STORE_ITEM_ID

    project_data = build_project_data((ElementSpec(600, "Field", "MainData", "@Number"),))
    parts = {
        "customXml/item5.xml": project_data,
        "customXml/itemProps9.xml": (
            f'<ds:datastoreItem xmlns:ds="{DS_NS}" ds:itemID="{STORE_ITEM_ID}">'
            "<ds:schemaRefs/></ds:datastoreItem>"
        ).encode(),
        "customXml/_rels/item5.xml.rels": (
            b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            b'<Relationship Id="rId1" '
            b'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXmlProps" '
            b'Target="itemProps9.xml"/>'
            b"</Relationships>"
        ),
    }
    docx = build_docx(
        document_controls=(
            ControlSpec(alias="Field", tag="Field", sdt_id=600, store_item_id=STORE_ITEM_ID),
        ),
        custom_parts=parts,
    )
    bundle = load_project_data(docx, LIMITS)
    assert bundle.store_items[STORE_ITEM_ID] == ["customXml/item5.xml"]
    resolution = resolve_controls(scan_docx(docx, LIMITS).controls, bundle, None)[0]
    assert resolution.status is ResolutionStatus.RESOLVED
