"""Synthetic OOXML tests for the reference content-control scanner."""

from __future__ import annotations

import pytest
from docentric_copilot.errors import InvalidInputError
from docentric_copilot.reference import (
    Classification,
    ControlType,
    ElementKind,
    ReferenceLimits,
    StoryPart,
    scan_docx,
)

from tests.reference_fixtures import (
    ControlSpec,
    build_docx,
    build_project_data,
    build_zip,
    project_data_parts,
)

LIMITS = ReferenceLimits()


def test_scans_document_header_footer_locations_and_types() -> None:
    document_controls = (
        ControlSpec(
            alias="Field",
            tag="Field",
            sdt_id=-1964797487,
            text="@Number",
            control_type="text",
            xpath="Root/@Number",
            store_item_id="{AAAA}",
        ),
        ControlSpec(
            alias="Date",
            tag="Date",
            sdt_id=42,
            text="2024-01-01",
            control_type="date",
        ),
    )
    header_controls = (
        ControlSpec(alias="Label", tag="Label", sdt_id=100, text="Header", control_type="dropdown"),
    )
    footer_controls = (
        ControlSpec(alias="Image", tag="Image", sdt_id=101, text="", control_type="picture"),
    )
    data = build_docx(
        document_controls=document_controls,
        header_controls=header_controls,
        footer_controls=footer_controls,
    )

    scan = scan_docx(data, LIMITS)

    assert len(scan.controls) == 4
    assert len({control.story for control in scan.controls}) == 3
    assert "word/document.xml" in scan.parts_scanned
    assert any(part.startswith("word/header") for part in scan.parts_scanned)
    assert any(part.startswith("word/footer") for part in scan.parts_scanned)

    field = next(control for control in scan.controls if control.alias == "Field")
    assert field.story is StoryPart.DOCUMENT
    assert field.part == "word/document.xml"
    assert field.paragraph_index == 1
    assert field.sdt_id_signed == -1964797487
    assert field.sdt_id_unsigned == "2330169809"
    assert field.tag == "Field"
    assert field.placeholder == "SYNTHETIC-PLACEHOLDER"
    assert field.control_type is ControlType.TEXT
    assert field.data_binding.xpath == "Root/@Number"
    assert field.data_binding.store_item_id == "{AAAA}"

    metadata_date = next(control for control in scan.controls if control.alias == "Date")
    assert metadata_date.control_type is ControlType.DATE

    header = next(control for control in scan.controls if control.story is StoryPart.HEADER)
    assert header.paragraph_index == 0
    assert header.control_type is ControlType.DROPDOWN

    footer = next(control for control in scan.controls if control.story is StoryPart.FOOTER)
    assert footer.control_type is ControlType.PICTURE


def test_classification_never_drops_controls() -> None:
    specs = (
        ControlSpec(alias="Field", tag="Field", sdt_id=1),
        ControlSpec(alias="List", tag="List", sdt_id=2),
        ControlSpec(alias="If", tag="If", sdt_id=3),
        ControlSpec(alias="Image", tag="Image", sdt_id=4),
        ControlSpec(alias="Label", tag="Label", sdt_id=5),
        ControlSpec(alias="Barcode", tag="Barcode", sdt_id=6),
        ControlSpec(alias="SummaryField", tag="SummaryField", sdt_id=7),
        ControlSpec(alias="SubDocument", tag="SubDocument", sdt_id=8),
        ControlSpec(alias="Group", tag="Group", sdt_id=9),
        ControlSpec(alias="Plain control", tag="plain", sdt_id=10),
        ControlSpec(alias="Field", tag="List", sdt_id=11),
        ControlSpec(alias="anything", tag="#SummaryField#", sdt_id=12),
        ControlSpec(alias="Field", tag="Field", sdt_id=13, dc_namespace=True),
        ControlSpec(alias="#SomeName#", tag=None, sdt_id=14),
    )
    scan = scan_docx(build_docx(document_controls=specs), LIMITS)

    assert len(scan.controls) == len(specs)
    by_id = {control.sdt_id_signed: control for control in scan.controls}

    expected = {
        1: ElementKind.FIELD,
        2: ElementKind.LIST,
        3: ElementKind.IF,
        4: ElementKind.IMAGE,
        5: ElementKind.LABEL,
        6: ElementKind.BARCODE,
        7: ElementKind.SUMMARY_FIELD,
        8: ElementKind.SUB_DOCUMENT,
        9: ElementKind.GROUP,
        12: ElementKind.SUMMARY_FIELD,
        13: ElementKind.FIELD,
    }
    for identifier, kind in expected.items():
        assert by_id[identifier].element_kind is kind
        assert by_id[identifier].classification is Classification.RECOGNIZED

    assert by_id[10].classification is Classification.UNKNOWN
    assert by_id[10].element_kind is ElementKind.UNKNOWN
    assert by_id[10].classification_reason == "no_docentric_marker"

    assert by_id[11].classification is Classification.AMBIGUOUS
    assert by_id[11].classification_reason == "conflicting_markers"

    assert by_id[14].classification is Classification.AMBIGUOUS
    assert by_id[14].classification_reason == "docentric_marker_without_type"

    counts = scan.counts_by_classification()
    assert counts == {"ambiguous": 2, "recognized": 11, "unknown": 1}
    assert sum(scan.counts_by_element_kind().values()) == len(specs)


def test_nested_sdt_instances_are_both_preserved() -> None:
    nested = ControlSpec(alias="Label", tag="Label", sdt_id=22, text="inner")
    outer = ControlSpec(
        alias="Group",
        tag="Group",
        sdt_id=21,
        text="outer",
        nested=(nested,),
    )
    scan = scan_docx(build_docx(document_controls=(outer,)), LIMITS)

    assert len(scan.controls) == 2
    assert [control.depth for control in scan.controls] == [0, 1]
    assert {control.sdt_id_signed for control in scan.controls} == {21, 22}


def test_macros_and_active_content_are_flagged_but_not_executed() -> None:
    custom = {
        "word/vbaProject.bin": b"not-a-real-macro",
        "word/activeX/activeX1.xml": b"<activeX/>",
        "word/embeddings/oleObject1.bin": b"\x00\x01",
        "word/_rels/document.xml.rels": (
            b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            b'<Relationship Id="rId9" Type="http://example.test/attachment" '
            b'Target="https://example.invalid/a.docx" TargetMode="External"/>'
            b"</Relationships>"
        ),
    }
    scan = scan_docx(build_docx(custom_parts=custom), LIMITS)

    assert scan.has_macros is True
    assert scan.has_active_x is True
    assert scan.has_embedded_objects is True
    assert scan.has_external_relationships is True


def test_docx_without_document_part_is_rejected() -> None:
    payload = build_zip({"word/settings.xml": b"<w:settings xmlns:w='urn:x'/>"})
    with pytest.raises(InvalidInputError, match=r"word/document\.xml"):
        scan_docx(payload, LIMITS)


def test_control_metadata_is_preserved_in_json() -> None:
    data = build_docx(
        document_controls=(
            ControlSpec(
                alias="Field",
                tag="Field",
                sdt_id=-1,
                text="#Field# @Name",
                store_item_id="{BBBB}",
                xpath="/ns0:Root/ns0:Line/@ItemId",
            ),
        )
    )
    scan = scan_docx(data, LIMITS)
    payload = scan.model_dump(mode="json")
    control = payload["controls"][0]
    assert control["sdt_id_signed"] == -1
    assert control["sdt_id_unsigned"] == str(2**32 - 1)
    assert control["data_binding"]["store_item_id"] == "{BBBB}"
    assert control["classification"] == "recognized"
    assert control["element_kind"] == "field"


def test_header_and_footer_are_scanned_even_without_document_controls() -> None:
    data = build_docx(
        header_controls=(ControlSpec(alias="Label", tag="Label", sdt_id=7),),
    )
    scan = scan_docx(data, LIMITS)
    assert len(scan.controls) == 1
    assert scan.controls[0].story is StoryPart.HEADER


def test_project_data_custom_xml_does_not_appear_as_control() -> None:
    parts = project_data_parts(
        build_project_data(
            (),
            product_version="3.0.0.998",
        )
    )
    scan = scan_docx(build_docx(custom_parts=parts), LIMITS)
    assert scan.controls == []


def test_control_type_variants_are_mapped() -> None:
    specs = (
        ControlSpec(alias="A", tag="A", sdt_id=1, control_type="rich_text"),
        ControlSpec(alias="B", tag="B", sdt_id=2, control_type="checkbox"),
        ControlSpec(alias="C", tag="C", sdt_id=3, control_type="group"),
        ControlSpec(alias="D", tag="D", sdt_id=4, control_type="comboBox"),
        ControlSpec(alias="E", tag="E", sdt_id=5, control_type="buildingBlockGallery"),
        ControlSpec(alias="F", tag="F", sdt_id=6, control_type="citation"),
        ControlSpec(alias="G", tag="G", sdt_id=7, control_type="equation"),
        ControlSpec(alias="H", tag="H", sdt_id=8, control_type="repeatingSection"),
        ControlSpec(alias="I", tag="I", sdt_id=9, control_type="customType"),
    )
    scan = scan_docx(build_docx(document_controls=specs), LIMITS)
    by_id = {control.sdt_id_signed: control.control_type for control in scan.controls}
    assert by_id[1] is ControlType.RICH_TEXT
    assert by_id[2] is ControlType.CHECKBOX
    assert by_id[3] is ControlType.GROUP
    assert by_id[4] is ControlType.DROPDOWN
    assert by_id[5] is ControlType.BUILDING_BLOCK
    assert by_id[6] is ControlType.CITATION
    assert by_id[7] is ControlType.EQUATION
    assert by_id[8] is ControlType.REPEATING_SECTION
    assert by_id[9] is ControlType.UNKNOWN


def test_invalid_and_out_of_range_ids_are_kept_without_guessing() -> None:
    specs = (
        ControlSpec(alias="Field", tag="Field", sdt_id="not-a-number"),
        ControlSpec(alias="Field", tag="Field", sdt_id=str(2**32 + 7)),
        ControlSpec(alias="Field", tag="Field", sdt_id=-1),
    )
    scan = scan_docx(build_docx(document_controls=specs), LIMITS)
    assert len(scan.controls) == 3
    assert scan.controls[0].sdt_id_signed is None
    assert scan.controls[0].sdt_id_unsigned is None
    assert scan.controls[1].sdt_id_signed is None
    assert scan.controls[1].sdt_id_unsigned is None
    assert scan.controls[2].sdt_id_signed == -1
    assert scan.controls[2].sdt_id_unsigned == "4294967295"


def test_long_preview_is_bounded() -> None:
    scan = scan_docx(
        build_docx(
            document_controls=(ControlSpec(alias="Field", tag="Field", sdt_id=1, text="x" * 500),)
        ),
        LIMITS,
    )
    assert len(scan.controls[0].text_preview) == LIMITS.max_text_preview
    assert scan.controls[0].text_preview.endswith("…")


def test_unreadable_auxiliary_story_part_is_reported() -> None:
    custom = {"word/header9.xml": b"<not-valid"}
    scan = scan_docx(build_docx(custom_parts=custom), LIMITS)
    assert "word/header9.xml" in scan.parts_skipped
    assert "part_unreadable:word/header9.xml" in scan.warnings


def test_all_supported_story_parts_are_scanned() -> None:
    from tests.reference_fixtures import build_docx, build_story_part

    custom = {
        "word/footnotes.xml": build_story_part(
            "footnotes", (ControlSpec(alias="Label", tag="Label", sdt_id=31),)
        ),
        "word/endnotes.xml": build_story_part(
            "endnotes", (ControlSpec(alias="Label", tag="Label", sdt_id=32),)
        ),
        "word/comments.xml": build_story_part(
            "comments", (ControlSpec(alias="Label", tag="Label", sdt_id=33),)
        ),
        "word/glossary/document.xml": build_story_part(
            "document", (ControlSpec(alias="Label", tag="Label", sdt_id=34),)
        ),
    }
    scan = scan_docx(build_docx(custom_parts=custom), LIMITS)
    stories = {control.story for control in scan.controls}
    assert {
        StoryPart.FOOTNOTE,
        StoryPart.ENDNOTE,
        StoryPart.COMMENT,
        StoryPart.GLOSSARY,
    } <= stories
