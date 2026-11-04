"""Safe OOXML content-control scanner.

Every ``w:sdt`` found in a supported Word story part becomes one
:class:`DocxControl`. Nothing is dropped silently: controls that carry no
recognizable Docentric marker are returned with ``classification="unknown"``.
The scanner never evaluates binding expressions, resolves external
relationships or executes active content.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Final

from docentric_copilot.errors import InvalidInputError, SecurityViolationError
from docentric_copilot.serialization import digest_bytes
from lxml import etree
from pydantic import BaseModel, ConfigDict, Field

from .safety import ReferenceLimits, local_name, namespace_uri, parse_xml, read_archive, truncated

W_NS: Final = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W: Final = f"{{{W_NS}}}"

_HEADER_PART = re.compile(r"^word/header\d*\.xml$", re.IGNORECASE)
_FOOTER_PART = re.compile(r"^word/footer\d*\.xml$", re.IGNORECASE)
_EXTERNAL_TARGET = re.compile(rb"TargetMode\s*=\s*['\"]External['\"]", re.IGNORECASE)
_HASH_TYPE = re.compile(
    r"#\s*(summary\s*field|summaryfield|sub\s*document|subdocument|barcode|label|"
    r"image|field|list|group|if)\b",
    re.IGNORECASE,
)
_HASH_ANY = re.compile(r"#")

_KIND_BY_LABEL: Final[dict[str, str]] = {
    "field": "field",
    "list": "list",
    "if": "if",
    "image": "image",
    "label": "label",
    "barcode": "barcode",
    "summaryfield": "summary_field",
    "summary": "summary_field",
    "subdocument": "sub_document",
    "subdoc": "sub_document",
    "group": "group",
}
_HASH_KIND_LABEL: Final[dict[str, str]] = {
    "field": "field",
    "list": "list",
    "if": "if",
    "image": "image",
    "label": "label",
    "barcode": "barcode",
    "summaryfield": "summary_field",
    "subdocument": "sub_document",
    "subdoc": "sub_document",
    "group": "group",
}


class StoryPart(str, Enum):
    """Word story part that carries a content control."""

    DOCUMENT = "document"
    HEADER = "header"
    FOOTER = "footer"
    FOOTNOTE = "footnote"
    ENDNOTE = "endnote"
    COMMENT = "comment"
    GLOSSARY = "glossary"
    OTHER = "other"


class ControlType(str, Enum):
    """Word content-control flavour detected from ``w:sdtPr``."""

    TEXT = "text"
    DATE = "date"
    DROPDOWN = "dropdown"
    PICTURE = "picture"
    RICH_TEXT = "rich_text"
    CHECKBOX = "checkbox"
    GROUP = "group"
    BUILDING_BLOCK = "building_block"
    CITATION = "citation"
    EQUATION = "equation"
    REPEATING_SECTION = "repeating_section"
    UNKNOWN = "unknown"


class ElementKind(str, Enum):
    """Docentric element kind inferred from markers, never from execution."""

    FIELD = "field"
    LIST = "list"
    IF = "if"
    IMAGE = "image"
    LABEL = "label"
    BARCODE = "barcode"
    SUMMARY_FIELD = "summary_field"
    SUB_DOCUMENT = "sub_document"
    GROUP = "group"
    UNKNOWN = "unknown"


class Classification(str, Enum):
    """How confidently the scanner recognized a Docentric marker."""

    RECOGNIZED = "recognized"
    AMBIGUOUS = "ambiguous"
    UNKNOWN = "unknown"


class DataBinding(BaseModel):
    """Word ``w:dataBinding`` attributes; never evaluated as an XPath expression."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    xpath: str | None = Field(default=None, max_length=512)
    store_item_id: str | None = Field(default=None, max_length=80)
    prefix_mappings: str | None = Field(default=None, max_length=1024)


class DocxControl(BaseModel):
    """One content-control instance and its full, non-executed location."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    part: str = Field(min_length=1, max_length=240)
    story: StoryPart
    paragraph_index: int = Field(ge=-1)
    ordinal: int = Field(ge=0)
    depth: int = Field(ge=0)
    tag: str | None = Field(default=None, max_length=200)
    alias: str | None = Field(default=None, max_length=200)
    sdt_id_signed: int | None = None
    sdt_id_unsigned: str | None = Field(default=None, pattern=r"^[0-9]+$")
    control_type: ControlType
    placeholder: str | None = Field(default=None, max_length=200)
    data_binding: DataBinding = Field(default_factory=DataBinding)
    text_preview: str = Field(default="", max_length=200)
    has_dc_namespace: bool = False
    dc_namespaces: list[str] = Field(default_factory=list, max_length=20)
    markers: list[str] = Field(default_factory=list, max_length=30)
    element_kind: ElementKind = ElementKind.UNKNOWN
    classification: Classification = Classification.UNKNOWN
    classification_reason: str = Field(default="no_docentric_marker", max_length=80)


class DocxScan(BaseModel):
    """Content-control scan for one DOCX package."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parts_scanned: list[str] = Field(default_factory=list, max_length=64)
    parts_skipped: list[str] = Field(default_factory=list, max_length=64)
    controls: list[DocxControl] = Field(default_factory=list)
    has_macros: bool = False
    has_active_x: bool = False
    has_embedded_objects: bool = False
    has_external_relationships: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=50)

    def counts_by_classification(self) -> dict[str, int]:
        counts = {item.value: 0 for item in Classification}
        for control in self.controls:
            counts[control.classification.value] += 1
        return dict(sorted(counts.items()))

    def counts_by_element_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for control in self.controls:
            key = control.element_kind.value
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items()))

    def counts_by_story(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for control in self.controls:
            key = control.story.value
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items()))


_TYPE_TAGS: Final[dict[str, ControlType]] = {
    "text": ControlType.TEXT,
    "date": ControlType.DATE,
    "dropDownList": ControlType.DROPDOWN,
    "comboBox": ControlType.DROPDOWN,
    "picture": ControlType.PICTURE,
    "richText": ControlType.RICH_TEXT,
    "checkbox": ControlType.CHECKBOX,
    "group": ControlType.GROUP,
    "buildingBlockGallery": ControlType.BUILDING_BLOCK,
    "docPartObj": ControlType.BUILDING_BLOCK,
    "docPartList": ControlType.BUILDING_BLOCK,
    "citation": ControlType.CITATION,
    "equation": ControlType.EQUATION,
    "repeatingSection": ControlType.REPEATING_SECTION,
}


def _normalize_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _hash_marker(value: str) -> tuple[bool, str | None]:
    if not _HASH_ANY.search(value):
        return False, None
    match = _HASH_TYPE.search(value)
    if match is None:
        return True, None
    return True, _HASH_KIND_LABEL.get(_normalize_label(match.group(1)))


def _docentric_namespaces(sdt: etree._Element) -> list[str]:
    found: set[str] = set()
    for element in sdt.iter():
        candidates: list[object] = [element.tag, *element.keys()]
        for candidate in candidates:
            uri = namespace_uri(candidate)
            if uri and "docentric" in uri.casefold():
                found.add(uri)
    return sorted(found)


def _classify(
    *,
    alias: str | None,
    tag: str | None,
    text_preview: str,
    dc_namespaces: list[str],
) -> tuple[ElementKind, Classification, str, list[str]]:
    markers: set[str] = set()
    candidates: dict[ElementKind, list[str]] = {}
    hash_marker = False
    for source, value in (("alias", alias), ("tag", tag)):
        if not value:
            continue
        norm = _normalize_label(value)
        kind_name = _KIND_BY_LABEL.get(norm)
        if kind_name:
            kind = ElementKind(kind_name)
            candidates.setdefault(kind, []).append(f"{source}:{kind.value}")
            markers.add(f"{source}:{kind.value}")
        has_hash, hash_kind = _hash_marker(value)
        if has_hash:
            hash_marker = True
            markers.add("hash_placeholder")
            if hash_kind:
                kind = ElementKind(hash_kind)
                candidates.setdefault(kind, []).append(f"hash:{kind.value}")
                markers.add(f"hash:{kind.value}")
    if text_preview:
        has_hash, hash_kind = _hash_marker(text_preview)
        if has_hash:
            hash_marker = True
            markers.add("hash_placeholder")
            if hash_kind:
                kind = ElementKind(hash_kind)
                candidates.setdefault(kind, []).append(f"text:{kind.value}")
                markers.add(f"text:{kind.value}")
    for uri in dc_namespaces:
        markers.add(f"dc_namespace:{uri}")
    if len(candidates) > 1:
        return (
            ElementKind.UNKNOWN,
            Classification.AMBIGUOUS,
            "conflicting_markers",
            sorted(markers),
        )
    if len(candidates) == 1:
        kind = next(iter(candidates))
        return kind, Classification.RECOGNIZED, "known_marker", sorted(markers)
    if dc_namespaces or hash_marker:
        return (
            ElementKind.UNKNOWN,
            Classification.AMBIGUOUS,
            "docentric_marker_without_type",
            sorted(markers),
        )
    return ElementKind.UNKNOWN, Classification.UNKNOWN, "no_docentric_marker", sorted(markers)


def _control_type(sdt_pr: etree._Element | None) -> ControlType:
    if sdt_pr is None:
        return ControlType.UNKNOWN
    for child in sdt_pr:
        kind = _TYPE_TAGS.get(local_name(child.tag))
        if kind is not None:
            return kind
    return ControlType.UNKNOWN


def _val(element: etree._Element | None) -> str | None:
    if element is None:
        return None
    value = element.get(f"{W}val")
    return value if value else None


def _data_binding(sdt_pr: etree._Element | None) -> DataBinding:
    if sdt_pr is None:
        return DataBinding()
    binding = sdt_pr.find(f"{W}dataBinding")
    if binding is None:
        return DataBinding()
    return DataBinding(
        xpath=truncated(binding.get(f"{W}xpath"), 512),
        store_item_id=truncated(binding.get(f"{W}storeItemID"), 80),
        prefix_mappings=truncated(binding.get(f"{W}prefixMappings"), 1024),
    )


def _placeholder(sdt_pr: etree._Element | None) -> str | None:
    if sdt_pr is None:
        return None
    placeholder = sdt_pr.find(f"{W}placeholder")
    if placeholder is None:
        return None
    doc_part = placeholder.find(f"{W}docPart")
    return truncated(_val(doc_part), 200)


def _signed_id(sdt_pr: etree._Element | None) -> tuple[int | None, str | None]:
    if sdt_pr is None:
        return None, None
    raw = _val(sdt_pr.find(f"{W}id"))
    if raw is None:
        return None, None
    try:
        value = int(raw.strip())
    except (TypeError, ValueError):
        return None, None
    if value < 0:
        return value, str(value % (2**32))
    if value > 0xFFFFFFFF:
        return None, None
    return value, str(value)


def _text_preview(sdt: etree._Element, limit: int) -> str:
    chunks = [node.text or "" for node in sdt.iter(f"{W}t")]
    text = " ".join(" ".join(chunks).split())
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def _paragraph_index(sdt: etree._Element, paragraphs: dict[etree._Element, int]) -> int:
    parent = sdt.getparent()
    while parent is not None:
        if parent.tag == f"{W}p":
            return paragraphs.get(parent, -1)
        parent = parent.getparent()
    return -1


def _depth(sdt: etree._Element) -> int:
    depth = 0
    parent = sdt.getparent()
    while parent is not None:
        if parent.tag == f"{W}sdt":
            depth += 1
        parent = parent.getparent()
    return depth


def _story(part: str) -> StoryPart:
    lowered = part.casefold()
    if lowered == "word/document.xml":
        return StoryPart.DOCUMENT
    if _HEADER_PART.match(part):
        return StoryPart.HEADER
    if _FOOTER_PART.match(part):
        return StoryPart.FOOTER
    if lowered == "word/footnotes.xml":
        return StoryPart.FOOTNOTE
    if lowered == "word/endnotes.xml":
        return StoryPart.ENDNOTE
    if lowered == "word/comments.xml":
        return StoryPart.COMMENT
    if lowered == "word/glossary/document.xml":
        return StoryPart.GLOSSARY
    return StoryPart.OTHER


def _part_rank(part: str) -> tuple[int, int, str]:
    lowered = part.casefold()
    if lowered == "word/document.xml":
        return (0, 0, part)
    if _HEADER_PART.match(part):
        digits = re.search(r"(\d+)", part)
        return (1, int(digits.group(1)) if digits else 0, part)
    if _FOOTER_PART.match(part):
        digits = re.search(r"(\d+)", part)
        return (2, int(digits.group(1)) if digits else 0, part)
    if lowered == "word/footnotes.xml":
        return (3, 0, part)
    if lowered == "word/endnotes.xml":
        return (4, 0, part)
    if lowered == "word/comments.xml":
        return (5, 0, part)
    if lowered == "word/glossary/document.xml":
        return (6, 0, part)
    return (9, 0, part)


def _scanned_parts(names: list[str]) -> list[str]:
    selected: list[str] = []
    for name in names:
        lowered = name.casefold()
        if (
            lowered == "word/document.xml"
            or _HEADER_PART.match(name)
            or _FOOTER_PART.match(name)
            or lowered
            in {
                "word/footnotes.xml",
                "word/endnotes.xml",
                "word/comments.xml",
                "word/glossary/document.xml",
            }
        ):
            selected.append(name)
    return sorted(set(selected), key=_part_rank)


def _scan_part(
    root: etree._Element,
    *,
    part: str,
    limits: ReferenceLimits,
) -> list[DocxControl]:
    story = _story(part)
    paragraphs = {node: index for index, node in enumerate(root.iter(f"{W}p"))}
    controls: list[DocxControl] = []
    for ordinal, sdt in enumerate(root.iter(f"{W}sdt")):
        sdt_pr = sdt.find(f"{W}sdtPr")
        alias = truncated(_val(sdt_pr.find(f"{W}alias")) if sdt_pr is not None else None, 200)
        tag = truncated(_val(sdt_pr.find(f"{W}tag")) if sdt_pr is not None else None, 200)
        signed, unsigned = _signed_id(sdt_pr)
        control_type = _control_type(sdt_pr)
        data_binding = _data_binding(sdt_pr)
        placeholder = _placeholder(sdt_pr)
        preview = _text_preview(sdt, limits.max_text_preview)
        dc_namespaces = _docentric_namespaces(sdt)
        kind, classification, reason, markers = _classify(
            alias=alias,
            tag=tag,
            text_preview=preview,
            dc_namespaces=dc_namespaces,
        )
        controls.append(
            DocxControl(
                part=part,
                story=story,
                paragraph_index=_paragraph_index(sdt, paragraphs),
                ordinal=ordinal,
                depth=_depth(sdt),
                tag=tag,
                alias=alias,
                sdt_id_signed=signed,
                sdt_id_unsigned=unsigned,
                control_type=control_type,
                placeholder=placeholder,
                data_binding=data_binding,
                text_preview=preview,
                has_dc_namespace=bool(dc_namespaces),
                dc_namespaces=dc_namespaces[:20],
                markers=markers[:30],
                element_kind=kind,
                classification=classification,
                classification_reason=reason,
            )
        )
    return controls


def scan_docx(data: bytes, limits: ReferenceLimits) -> DocxScan:
    """Scan every content control in a DOCX package, without executing it."""
    entries = read_archive(data, limits)
    payloads = {entry.name: entry.payload for entry in entries}
    names = sorted(payloads)
    lowered_names = [name.casefold() for name in names]
    if "word/document.xml" not in {name.casefold() for name in names}:
        raise InvalidInputError(
            "DOCX package does not contain word/document.xml",
            code="reference_docx_invalid",
        )
    warnings: set[str] = set()
    has_macros = any(name.endswith("vbaproject.bin") for name in lowered_names)
    has_active_x = any("/activex/" in name for name in lowered_names)
    has_embedded = any("/embeddings/" in name for name in lowered_names)
    external = False
    rel_files = [name for name in names if name.casefold().endswith(".rels")]
    for name in rel_files[:64]:
        payload = payloads[name]
        if len(payload) > 256 * 1024:
            warnings.add(f"relationship_file_skipped:{name}")
            continue
        if _EXTERNAL_TARGET.search(payload):
            external = True
            break
    controls: list[DocxControl] = []
    parts_scanned: list[str] = []
    parts_skipped: list[str] = []
    for part in _scanned_parts(names):
        try:
            root = parse_xml(payloads[part], limits, location=part)
        except InvalidInputError:
            if part.casefold() == "word/document.xml":
                raise
            parts_skipped.append(part)
            warnings.add(f"part_unreadable:{part}")
            continue
        parts_scanned.append(part)
        controls.extend(_scan_part(root, part=part, limits=limits))
        if len(controls) > limits.max_controls:
            raise SecurityViolationError(
                "DOCX contains more content controls than allowed",
                code="reference_control_limit",
                details={"max_controls": limits.max_controls},
            )
    controls.sort(key=lambda item: (_part_rank(item.part), item.ordinal))
    return DocxScan(
        document_sha256=digest_bytes(data),
        parts_scanned=parts_scanned,
        parts_skipped=parts_skipped,
        controls=controls,
        has_macros=has_macros,
        has_active_x=has_active_x,
        has_embedded_objects=has_embedded,
        has_external_relationships=external,
        warnings=sorted(warnings),
    )


__all__ = [
    "Classification",
    "ControlType",
    "DataBinding",
    "DocxControl",
    "DocxScan",
    "ElementKind",
    "StoryPart",
    "scan_docx",
]
