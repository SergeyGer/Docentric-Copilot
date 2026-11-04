"""Synthetic container tests for REF-00 inventory, dedup and recursion guards."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from docentric_copilot.errors import (
    InvalidInputError,
    SecurityViolationError,
    UnsupportedInputError,
)
from docentric_copilot.reference import (
    ArtifactKind,
    PlatformHint,
    ReferenceLimits,
    SourceType,
    inspect_bytes,
    inspect_path,
    scan_bytes,
)

from tests.reference_fixtures import (
    ControlSpec,
    ElementSpec,
    build_axpp,
    build_docx,
    build_project_data,
    build_zip,
    project_data_parts,
)

LIMITS = ReferenceLimits()


def _docx(marker: str = "one") -> bytes:
    return build_docx(
        document_controls=(ControlSpec(alias="Field", tag="Field", sdt_id=1, text=marker),),
        custom_parts=project_data_parts(build_project_data()),
    )


def test_docx_inventory_hashes_and_version_hint() -> None:
    data = _docx()
    inventory = inspect_bytes(data, filename="Synthetic.Report.docx", limits=LIMITS)

    assert inventory.source_type is SourceType.DOCX
    assert len(inventory.entries) == 1
    entry = inventory.entries[0]
    assert entry.kind is ArtifactKind.DOCX
    assert entry.sha256 == hashlib.sha256(data).hexdigest()
    assert entry.size_bytes == len(data)
    assert entry.nested_depth == 0
    assert inventory.container.product_versions == ["3.0.0.998"]
    assert inventory.duplicates == []
    assert inventory.nested_archives == []


def test_directory_detects_exact_duplicates(tmp_path: Path) -> None:
    one = _docx("same")
    two = build_docx(
        document_controls=(ControlSpec(alias="Label", tag="Label", sdt_id=2, text="different"),)
    )
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "same.docx").write_bytes(one)
    (tmp_path / "b" / "same.docx").write_bytes(one)
    (tmp_path / "unique.docx").write_bytes(two)

    inventory = inspect_path(tmp_path, limits=LIMITS, max_depth=0)

    assert inventory.source_type is SourceType.DIRECTORY
    assert len(inventory.entries) == 3
    assert len(inventory.duplicates) == 1
    group = inventory.duplicates[0]
    assert group.occurrences == 2
    assert group.paths == ["a/same.docx", "b/same.docx"]
    assert group.sha256 == hashlib.sha256(one).hexdigest()


def test_axpp_backslash_members_are_normalized_and_classified() -> None:
    payload = build_axpp(_docx())
    inventory = inspect_bytes(payload, filename="Synthetic.axpp", limits=LIMITS, max_depth=0)

    assert inventory.source_type is SourceType.AXPP
    assert all("\\" not in entry.path for entry in inventory.entries)
    kinds = {entry.path: entry.kind for entry in inventory.entries}
    assert kinds["Project/Synthetic.rnrproj"] is ArtifactKind.PROJECT
    assert kinds["ProjectItem/AxResource/Synthetic.Report.xml"] is ArtifactKind.XML
    assert (
        kinds["ProjectItem/AxResource/ResourceContent/Data/Synthetic.Report.docx"]
        is ArtifactKind.DOCX
    )
    assert inventory.container.platform is PlatformHint.D365
    assert "4.0.1.1128" in inventory.container.product_versions
    assert len(inventory.entries) == 4  # root + 3 members
    assert not any(entry.is_archive and entry.nested_depth > 0 for entry in inventory.entries)


def test_nested_archive_depth_guard_and_expansion() -> None:
    docx = _docx()
    inner = build_zip({"Synthetic.Report.docx": docx})
    outer = build_zip({"nested/inner.zip": inner})

    shallow = inspect_bytes(outer, filename="outer.zip", limits=LIMITS, max_depth=0)
    inner_entry = next(entry for entry in shallow.entries if entry.path.endswith("inner.zip"))
    assert inner_entry.is_archive is True
    assert inner_entry.expanded is False
    assert "recursion_guard:nested_archive_not_expanded" in inner_entry.warnings
    assert not shallow.artifacts_of_kind(ArtifactKind.DOCX)

    expanded = inspect_bytes(outer, filename="outer.zip", limits=LIMITS, max_depth=1)
    inner_entry = next(entry for entry in expanded.entries if entry.path.endswith("inner.zip"))
    assert inner_entry.expanded is True
    assert len(expanded.artifacts_of_kind(ArtifactKind.DOCX)) == 1
    assert expanded.nested_archives == ["nested/inner.zip"]


def test_recursion_guard_stops_second_nested_archive() -> None:
    innermost = build_zip({"Synthetic.Report.docx": _docx()})
    middle = build_zip({"deep/inner.zip": innermost})
    outer = build_zip({"middle.zip": middle})

    inventory = inspect_bytes(outer, filename="outer.zip", limits=LIMITS, max_depth=1)

    inner = next(entry for entry in inventory.entries if entry.path.endswith("deep/inner.zip"))
    assert inner.expanded is False
    assert inner.nested_depth == 2
    assert "recursion_guard:nested_archive_not_expanded" in inner.warnings
    assert not inventory.artifacts_of_kind(ArtifactKind.DOCX)


def test_zip_slip_and_drive_paths_are_rejected() -> None:
    hostile = build_zip({"../escape.xml": b"<x/>"})
    with pytest.raises(SecurityViolationError) as trapped:
        scan_bytes(hostile, filename="hostile.zip", limits=LIMITS)
    assert trapped.value.code == "reference_unsafe_path"

    drive = build_zip({"C:\\Windows\\escape.xml": b"<x/>"})
    with pytest.raises(SecurityViolationError) as trapped:
        scan_bytes(drive, filename="drive.zip", limits=LIMITS)
    assert trapped.value.code == "reference_unsafe_path"


def test_malformed_archive_and_unsupported_suffix_are_rejected() -> None:
    with pytest.raises(InvalidInputError):
        scan_bytes(b"this is not a zip archive", filename="bad.zip", limits=LIMITS)
    with pytest.raises(UnsupportedInputError):
        scan_bytes(b"plain text", filename="notes.txt", limits=LIMITS)
    with pytest.raises(UnsupportedInputError):
        inspect_bytes(b"plain text", filename="notes.txt", limits=LIMITS)


def test_file_and_compression_limits_are_enforced() -> None:
    small_limits = ReferenceLimits(max_file_bytes=32)
    with pytest.raises(UnsupportedInputError):
        scan_bytes(_docx(), filename="Synthetic.docx", limits=small_limits)

    zeros = build_zip({"payload.bin": b"\x00" * 200_000})
    compressed_limits = ReferenceLimits(max_compression_ratio=2)
    with pytest.raises(SecurityViolationError) as trapped:
        scan_bytes(zeros, filename="bomb.zip", limits=compressed_limits)
    assert trapped.value.code == "reference_compression_ratio_limit"


def test_macos_are_flagged_in_inventory_without_execution() -> None:
    payload = build_docx(custom_parts={"word/vbaProject.bin": b"macro-bytes"})
    inventory = inspect_bytes(payload, filename="Macro.docx", limits=LIMITS)
    entry = inventory.entries[0]
    assert "macro_present" in entry.warnings


def test_missing_path_is_not_found() -> None:
    with pytest.raises(Exception) as trapped:
        inspect_path("/tmp/definitely-no-such-reference-file.docx", limits=LIMITS)
    assert getattr(trapped.value, "code", None) == "not_found"


def test_directory_with_no_files_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(InvalidInputError):
        inspect_path(tmp_path, limits=LIMITS)


def test_axpp_version_hint_from_member_xml() -> None:
    project_data = build_project_data(
        (ElementSpec(element_id=1, element_type="Field"),),
        product_version="6.0.7.1430",
    )
    payload = build_axpp(_docx(), extra_xml=project_data)
    inventory = inspect_bytes(payload, filename="Synthetic.axpp", limits=LIMITS)
    assert "6.0.7.1430" in inventory.container.product_versions


def test_container_and_name_normalization_helpers() -> None:
    from docentric_copilot.reference.safety import (
        detect_container,
        normalize_member_name,
    )

    assert detect_container(b"PK\x03\x04rest") == "zip"
    assert detect_container(b"\xef\xbb\xbf<?xml version='1.0'?><Root/>") == "xml"
    assert detect_container(b"plain text") == "unknown"
    assert normalize_member_name("a\\b\\c.xml") == "a/b/c.xml"
    assert normalize_member_name("a//b.xml") == "a/b.xml"
    for hostile in ("", ".", "../x.xml", "/etc/passwd", "C:\\x.xml", "bad\x01.xml"):
        with pytest.raises(SecurityViolationError):
            normalize_member_name(hostile)
    with pytest.raises(SecurityViolationError):
        normalize_member_name("x" * 500)


def test_xml_reader_rejects_doctype_nested_and_wide_trees() -> None:
    from docentric_copilot.reference.safety import parse_xml

    with pytest.raises(SecurityViolationError) as trapped:
        parse_xml(
            b'<!DOCTYPE x [<!ENTITY y "z">]><Root>&y;</Root>',
            LIMITS,
            location="evil.xml",
        )
    assert trapped.value.code == "reference_doctype_rejected"

    with pytest.raises(InvalidInputError):
        parse_xml(b"<not-closed>", LIMITS, location="broken.xml")

    deep = ReferenceLimits(max_xml_depth=2)
    with pytest.raises(SecurityViolationError):
        parse_xml(b"<a><b><c/></b></a>", deep, location="deep.xml")

    wide = ReferenceLimits(max_xml_nodes=2)
    with pytest.raises(SecurityViolationError):
        parse_xml(b"<a><b/><c/></a>", wide, location="wide.xml")


def test_archive_hard_limits_and_empty_container() -> None:
    from docentric_copilot.reference.safety import read_archive

    many = build_zip({"a.xml": b"<a/>", "b.xml": b"<b/>"})
    with pytest.raises(SecurityViolationError) as trapped:
        read_archive(many, ReferenceLimits(max_archive_entries=1))
    assert trapped.value.code == "reference_archive_entry_limit"

    with pytest.raises(SecurityViolationError) as trapped:
        read_archive(many, ReferenceLimits(max_uncompressed_bytes=4))
    assert trapped.value.code == "reference_uncompressed_limit"

    with pytest.raises(InvalidInputError):
        read_archive(build_zip({}), LIMITS)

    link_zip = _zip_with_external_attr("link", b"target", (0o120000 | 0o777) << 16)
    with pytest.raises(SecurityViolationError):
        read_archive(link_zip, LIMITS)


def _zip_with_external_attr(name: str, payload: bytes, external_attr: int) -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo(name, date_time=(2024, 1, 1, 0, 0, 0))
        info.external_attr = external_attr
        archive.writestr(info, payload)
    return buffer.getvalue()


def test_directory_limits_and_missing_suffix(tmp_path: Path) -> None:
    (tmp_path / "a.docx").write_bytes(_docx())
    (tmp_path / "b.docx").write_bytes(_docx())
    with pytest.raises(InvalidInputError):
        inspect_path(tmp_path, limits=ReferenceLimits(max_directory_files=1))

    notes = tmp_path / "notes.txt"
    notes.write_text("text", encoding="utf-8")
    with pytest.raises(UnsupportedInputError):
        inspect_path(notes, limits=LIMITS)

    archive = tmp_path / "many.zip"
    archive.write_bytes(build_zip({"a.xml": b"<a/>", "b.xml": b"<b/>"}))
    with pytest.raises(InvalidInputError):
        inspect_path(archive, limits=ReferenceLimits(max_total_artifacts=1))

    inventory = inspect_path(tmp_path, limits=LIMITS)
    assert inventory.distinct_artifacts() == len({entry.sha256 for entry in inventory.entries})
    assert inventory.entry(inventory.entries[0].path) == inventory.entries[0]
    assert inventory.artifacts_of_kind(ArtifactKind.DOCX)


def test_directory_expands_top_level_archives_by_depth(tmp_path: Path) -> None:
    inner = build_zip({"Synthetic.Report.docx": _docx()})
    (tmp_path / "nested.zip").write_bytes(inner)

    shallow = inspect_path(tmp_path, limits=LIMITS, max_depth=0)
    nested_entry = next(entry for entry in shallow.entries if entry.path.endswith("nested.zip"))
    assert nested_entry.expanded is False
    assert not shallow.artifacts_of_kind(ArtifactKind.DOCX)

    deep = inspect_path(tmp_path, limits=LIMITS, max_depth=1)
    nested_entry = next(entry for entry in deep.entries if entry.path.endswith("nested.zip"))
    assert nested_entry.expanded is True
    assert len(deep.artifacts_of_kind(ArtifactKind.DOCX)) == 1


def test_platform_hint_mixed_and_suffixes() -> None:
    from docentric_copilot.reference.inventory import _platform_from_suffix, _platform_from_text

    assert _platform_from_text("MS Dynamics AX 2012 and Dynamics 365") is PlatformHint.MIXED
    assert _platform_from_text("unrelated") is PlatformHint.UNKNOWN
    assert _platform_from_suffix("Class.xpo") is PlatformHint.AX_2012
    assert _platform_from_suffix("Project.rnrproj") is PlatformHint.D365
    assert _platform_from_suffix("unknown.bin") is PlatformHint.UNKNOWN


def test_malformed_member_xml_does_not_abort_inventory() -> None:
    payload = build_zip({"broken.xml": b"<broken", "good.txt": b"text"})
    inventory = inspect_bytes(payload, filename="bundle.zip", limits=LIMITS)
    kinds = {entry.path: entry.kind for entry in inventory.entries}
    assert kinds["broken.xml"] is ArtifactKind.XML
