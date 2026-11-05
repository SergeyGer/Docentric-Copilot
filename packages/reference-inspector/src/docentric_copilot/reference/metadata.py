"""Docentric metadata resolver (REF-02).

The resolver joins two independent evidence sources:

* the OOXML location and signed ``w:id`` of every content control, and
* the Docentric ``ProjectData`` customXml part whose ``Element/@Id`` is the
  unsigned 32-bit form of that id.

A successful id join is reported as a technical match only. It is not a claim
that the binding is semantically correct, and it never implies runtime
compatibility.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Final

from lxml import etree
from pydantic import BaseModel, ConfigDict, Field

from .docx_controls import Classification, DocxControl, ElementKind
from .safety import ReferenceLimits, local_name, namespace_uri, parse_xml, read_archive, truncated

PROJECT_DATA_NS: Final = "http://docentric.org/projectdata.xml"
XSD_NS: Final = "http://www.w3.org/2001/XMLSchema"
_MAX_SCHEMA_PATHS_PER_SECTION: Final = 5_000
_MAX_SCHEMA_DEPTH: Final = 24
_CUSTOM_XML_ITEM = re.compile(r"^customxml/item(\d+)\.xml$", re.IGNORECASE)
_CUSTOM_XML_PROPS = re.compile(r"^customxml/itemprops(\d+)\.xml$", re.IGNORECASE)
_EXPRESSION = re.compile(r"(!=|==|<>|>=|<=|&&|\|\||[<>\[\]()=]|\s+and\s+|\s+or\s+)", re.IGNORECASE)


class ResolutionStatus(str, Enum):
    """Overall REF-02 resolution outcome."""

    RESOLVED = "resolved"
    MISSING_PART = "missing_part"
    UNKNOWN_PATH = "unknown_path"
    AMBIGUOUS = "ambiguous"


class LinkStatus(str, Enum):
    """How the OOXML control was linked to ProjectData metadata."""

    RESOLVED_BY_ID = "resolved_by_id"
    RESOLVED_BY_ID_SHARED = "resolved_by_id_shared"
    NO_SDT_ID = "no_sdt_id"
    NO_PROJECT_DATA = "no_project_data"
    MISSING_STORE_ITEM = "missing_store_item"
    STORE_ITEM_NOT_PROJECT_DATA = "store_item_not_project_data"
    NO_ELEMENT_FOR_ID = "no_element_for_id"
    DUPLICATE_ID_COLLISION = "duplicate_id_collision"
    MULTIPLE_PROJECT_DATA_PARTS = "multiple_project_data_parts"
    TYPE_MISMATCH = "type_mismatch"


class PathStatus(str, Enum):
    """How a binding path matched the supplied DDSP schema."""

    MATCHED = "matched"
    NOT_CHECKED = "not_checked"
    UNKNOWN = "unknown"
    SECTION_MISSING = "section_missing"
    AMBIGUOUS = "ambiguous"


class SchemaSource(str, Enum):
    """Where the optional schema came from."""

    DDSP = "ddsp"
    #: D365 embedded ``ProjectData`` schema.
    PROJECT_DATA = "d365_project_data"
    #: Both providers were used across the inspected documents.
    MIXED = "mixed"
    NONE = "none"


class SourceBinding(BaseModel):
    """One typed ``ValueBinding`` from Docentric metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str | None = Field(default=None, max_length=120)
    path: str | None = Field(default=None, max_length=512)
    result_data_type: str | None = Field(default=None, max_length=120)
    data_kind: str | None = Field(default=None, max_length=20)


class ProjectDataPart(BaseModel):
    """Summary of one ProjectData part; raw metadata stays internal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    part: str = Field(min_length=1, max_length=240)
    store_item_id: str | None = Field(default=None, max_length=80)
    product_id: str | None = Field(default=None, max_length=40)
    product_version: str | None = Field(default=None, max_length=40)
    data_sources: list[str] = Field(default_factory=list, max_length=20)
    element_count: int = Field(ge=0)
    duplicate_element_ids: int = Field(ge=0)


class ControlResolution(BaseModel):
    """Result of resolving one content control against ProjectData and a schema."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: ResolutionStatus
    link_status: LinkStatus
    path_status: PathStatus = PathStatus.NOT_CHECKED
    element_id_unsigned: str | None = Field(default=None, pattern=r"^[0-9]+$")
    element_type: str | None = Field(default=None, max_length=80)
    source_binding: SourceBinding | None = None
    source_binding_raw: SourceBinding | None = None
    normalized_path: str | None = Field(default=None, max_length=512)
    schema_section: str | None = Field(default=None, max_length=120)
    schema_source: SchemaSource = SchemaSource.NONE
    diagnostic_codes: list[str] = Field(default_factory=list, max_length=20)
    path_suggestions: list[str] = Field(default_factory=list, max_length=5)


@dataclass(frozen=True, slots=True)
class ProjectElement:
    """Internal typed metadata element."""

    id_unsigned: str
    element_type: str
    value_binding: SourceBinding | None
    child_ids: tuple[str, ...]
    attributes: dict[str, str]
    #: Typed child facts such as ``Value/LabelName``, ``AggregateBinding/Path``
    #: and ``GroupByBinding/Path``. These are evidence, never evaluated.
    properties: dict[str, str] = field(default_factory=dict)

    def fingerprint(self) -> tuple[object, ...]:
        binding = self.value_binding
        return (
            self.element_type,
            binding.source if binding else None,
            binding.path if binding else None,
            binding.result_data_type if binding else None,
            self.child_ids,
        )


@dataclass(slots=True)
class ParsedProjectData:
    """ProjectData summary plus the id index used for joining."""

    summary: ProjectDataPart
    by_id: dict[str, list[ProjectElement]] = field(default_factory=dict)
    parent_ids: dict[str, list[str]] = field(default_factory=dict)


@dataclass(slots=True)
class ProjectDataBundle:
    """All ProjectData parts and the customXml store-item mapping of one DOCX."""

    parts: list[ParsedProjectData]
    store_items: dict[str, list[str]]
    warnings: list[str] = field(default_factory=list)

    def by_part(self) -> dict[str, ParsedProjectData]:
        return {part.summary.part: part for part in self.parts}

    def is_empty(self) -> bool:
        return not self.parts


@dataclass(frozen=True, slots=True)
class SchemaMatch:
    """Outcome of matching one raw binding path against a section schema."""

    status: PathStatus
    section: str | None
    normalized_path: str | None
    suggestions: tuple[str, ...] = ()


@dataclass(slots=True)
class SchemaSection:
    """One DDSP data section with XSD roots and relative paths."""

    roots: dict[str, set[str]] = field(default_factory=dict)


class SchemaIndex:
    """Read-only index of DDSP paths used for REF-02 path validation."""

    def __init__(
        self,
        *,
        sections: dict[str, SchemaSection],
        product_version: str | None = None,
    ) -> None:
        self.sections = sections
        self.product_version = product_version

    @property
    def section_names(self) -> list[str]:
        return sorted(self.sections)

    @property
    def is_empty(self) -> bool:
        return not self.sections

    def path_count(self) -> int:
        return sum(
            len(paths) for section in self.sections.values() for paths in section.roots.values()
        )

    def match(self, section: str | None, raw_path: str | None) -> SchemaMatch:
        if not self.sections:
            return SchemaMatch(PathStatus.SECTION_MISSING, section, None)
        selected = section
        if selected is None and len(self.sections) == 1:
            selected = next(iter(self.sections))
        if selected is None or selected not in self.sections:
            return SchemaMatch(PathStatus.SECTION_MISSING, selected, None)
        normalized = _normalize_binding_path(raw_path)
        if normalized is None:
            return SchemaMatch(PathStatus.UNKNOWN, selected, None)
        matches: list[tuple[str, str]] = []
        schema_section = self.sections[selected]
        for root, paths in schema_section.roots.items():
            for candidate in _path_candidates(selected, root, normalized):
                if candidate in paths:
                    matches.append((root, candidate))
        unique = sorted(set(matches))
        if not unique:
            suggestions: list[str] = []
            first = normalized.split("/", 1)[0]
            for root, paths in schema_section.roots.items():
                for path in sorted(paths):
                    if path.split("/", 1)[0] == first and path:
                        suggestions.append(_display_path(selected, root, path))
            return SchemaMatch(PathStatus.UNKNOWN, selected, None, tuple(suggestions[:5]))
        if len(unique) > 1:
            return SchemaMatch(PathStatus.AMBIGUOUS, selected, None)
        root, candidate = unique[0]
        return SchemaMatch(PathStatus.MATCHED, selected, _display_path(selected, root, candidate))


def _display_path(section: str, root: str, relative: str) -> str:
    parts = [section, root]
    if relative:
        parts.append(relative.replace("/", "."))
    return ".".join(parts)


def _normalize_binding_path(raw_path: str | None) -> str | None:
    if raw_path is None:
        return None
    text = raw_path.strip().strip('"').strip("'")
    if not text:
        return None
    text = text.replace("\\", "/")
    if "/" not in text and "." in text and not text.startswith("@"):
        text = text.replace(".", "/")
    text = text.lstrip("/")
    parts: list[str] = []
    for chunk in text.split("/"):
        segment = chunk.strip()
        if not segment:
            continue
        if segment.startswith("@"):
            name = segment[1:]
            segment = "@" + (name.split(":", 1)[-1] if ":" in name else name)
        else:
            segment = segment.split(":", 1)[-1]
        if segment:
            parts.append(segment)
    return "/".join(parts) if parts else None


def _path_candidates(section: str, root: str, normalized: str) -> set[str]:
    forms: set[str] = {normalized}
    if section and normalized == section:
        forms.add("")
    prefix = f"{section}/"
    if section and normalized.startswith(prefix):
        forms.add(normalized[len(prefix) :])
    expanded = set(forms)
    for form in expanded:
        if not form:
            continue
        if form == root:
            forms.add("")
        root_prefix = f"{root}/"
        if form.startswith(root_prefix):
            forms.add(form[len(root_prefix) :])
    return forms


def _attr(element: etree._Element | None, name: str) -> str | None:
    if element is None:
        return None
    wanted = name.casefold()
    for key, value in element.attrib.items():
        if local_name(key).casefold() == wanted:
            return str(value)
    return None


def _direct_children(element: etree._Element, name: str) -> list[etree._Element]:
    return [child for child in element if local_name(child.tag) == name]


def _parse_value_binding(element: etree._Element | None) -> SourceBinding | None:
    if element is None:
        return None
    return SourceBinding(
        source=truncated(_attr(element, "Source"), 120),
        path=truncated(_attr(element, "Path"), 512),
        result_data_type=truncated(_attr(element, "ResultDataType"), 120),
        data_kind=truncated(_attr(element, "DataKind"), 20),
    )


def _parse_project_element(element: etree._Element) -> ProjectElement | None:
    raw_id = _attr(element, "Id")
    if raw_id is None:
        return None
    try:
        canonical = int(raw_id.strip()) % (2**32)
    except (TypeError, ValueError):
        return None
    value_binding = None
    for child in element:
        if local_name(child.tag) == "ValueBinding":
            value_binding = _parse_value_binding(child)
            break
    child_ids: list[str] = []
    for child in element:
        if local_name(child.tag) != "ChildElements":
            continue
        for ref in child:
            if local_name(ref.tag) != "ElementRef":
                continue
            ref_id = _attr(ref, "Id")
            if ref_id is None:
                continue
            try:
                child_ids.append(str(int(ref_id.strip()) % (2**32)))
            except (TypeError, ValueError):
                continue
        break
    attributes: dict[str, str] = {}
    for key, value in sorted(element.attrib.items(), key=lambda item: local_name(item[0])):
        name = local_name(key)
        if name.casefold() in {"id", "type"}:
            continue
        attributes[name] = str(value)[:200]
    properties: dict[str, str] = {}
    for child in element:
        child_tag = local_name(child.tag)
        if child_tag == "Value":
            for key, value in sorted(child.attrib.items(), key=lambda item: local_name(item[0])):
                properties[local_name(key)] = str(value)[:200]
        elif child_tag in {"AggregateBinding", "GroupByBinding", "SortDescriptor"}:
            for key, value in sorted(child.attrib.items(), key=lambda item: local_name(item[0])):
                properties[f"{child_tag}.{local_name(key)}"] = str(value)[:200]
    return ProjectElement(
        id_unsigned=str(canonical),
        element_type=truncated(_attr(element, "Type"), 80) or "Unknown",
        value_binding=value_binding,
        child_ids=tuple(child_ids),
        attributes=attributes,
        properties=properties,
    )


def _parse_project_data(
    root: etree._Element, *, part: str
) -> tuple[ProjectDataPart, dict[str, list[ProjectElement]], list[str]]:
    warnings: list[str] = []
    by_id: dict[str, list[ProjectElement]] = {}
    for container in root.iter():
        if local_name(container.tag) != "Elements":
            continue
        for element in container:
            if local_name(element.tag) != "Element":
                continue
            parsed = _parse_project_element(element)
            if parsed is None:
                warnings.append(f"invalid_element_metadata:{part}")
                continue
            by_id.setdefault(parsed.id_unsigned, []).append(parsed)
        break
    data_sources: list[str] = []
    for container in root.iter():
        if local_name(container.tag) != "DataSources":
            continue
        for source in container:
            if local_name(source.tag) != "DataSource":
                continue
            name = truncated(_attr(source, "Name"), 120)
            if name:
                data_sources.append(name)
        break
    summary = ProjectDataPart(
        part=part,
        store_item_id=None,
        product_id=truncated(_attr(root, "ProductId"), 40),
        product_version=truncated(_attr(root, "ProductVersion"), 40),
        data_sources=sorted(set(data_sources))[:20],
        element_count=sum(len(items) for items in by_id.values()),
        duplicate_element_ids=sum(1 for items in by_id.values() if len(items) > 1),
    )
    return summary, by_id, sorted(set(warnings))


def _store_item_props(payloads: dict[str, bytes], limits: ReferenceLimits) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for name, payload in sorted(payloads.items()):
        match = _CUSTOM_XML_PROPS.match(name)
        if match is None:
            continue
        try:
            root = parse_xml(payload, limits, location=name)
        except Exception:
            continue
        item_id = None
        for key, value in root.attrib.items():
            if local_name(key).casefold() == "itemid":
                item_id = normalize_store_item_id(str(value))
                break
        if item_id is None:
            continue
        mapping[int(match.group(1))] = item_id
    return mapping


def _props_relationships(payloads: dict[str, bytes], limits: ReferenceLimits) -> dict[int, int]:
    """Map a customXml item index to its related itemProps index, when declared."""
    mapping: dict[int, int] = {}
    for name, payload in sorted(payloads.items()):
        match = re.match(r"^customxml/_rels/item(\d+)\.xml\.rels$", name, re.IGNORECASE)
        if match is None:
            continue
        try:
            root = parse_xml(payload, limits, location=name)
        except Exception:
            continue
        for relationship in root.iter():
            if local_name(relationship.tag) != "Relationship":
                continue
            relation_type = _attr(relationship, "Type") or ""
            if not relation_type.casefold().endswith("customxmlprops"):
                continue
            target = _attr(relationship, "Target") or ""
            target_match = re.search(r"itemprops(\d+)\.xml", target, re.IGNORECASE)
            if target_match is not None:
                mapping[int(match.group(1))] = int(target_match.group(1))
                break
    return mapping


def normalize_store_item_id(value: str | None) -> str | None:
    """Normalize a Word ``storeItemID`` for case-insensitive GUID comparison."""
    if not value:
        return None
    text = value.strip().upper()
    if not text:
        return None
    if not text.startswith("{"):
        text = "{" + text
    if not text.endswith("}"):
        text = text + "}"
    return text


def load_project_data(data: bytes, limits: ReferenceLimits) -> ProjectDataBundle:
    """Find ProjectData by root/namespace in any ``customXml/itemN.xml`` part."""
    entries = read_archive(data, limits)
    payloads = {entry.name: entry.payload for entry in entries}
    props = _store_item_props(payloads, limits)
    props_targets = _props_relationships(payloads, limits)
    parts: list[ParsedProjectData] = []
    warnings: list[str] = []
    for name in sorted(payloads):
        match = _CUSTOM_XML_ITEM.match(name)
        if match is None:
            continue
        try:
            root = parse_xml(payloads[name], limits, location=name)
        except Exception:
            warnings.append(f"custom_xml_unreadable:{name}")
            continue
        if local_name(root.tag) != "ProjectData":
            continue
        namespace = (namespace_uri(root.tag) or "").casefold()
        if namespace.rstrip("/") != PROJECT_DATA_NS.rstrip("/"):
            warnings.append(f"project_data_namespace_unexpected:{name}")
            continue
        summary, by_id, part_warnings = _parse_project_data(root, part=name)
        index = int(match.group(1))
        props_index = props_targets.get(index, index)
        summary = summary.model_copy(update={"store_item_id": props.get(props_index)})
        parent_ids: dict[str, list[str]] = {}
        for elements in by_id.values():
            for element in elements:
                for child_id in element.child_ids:
                    parent_ids.setdefault(child_id, []).append(element.id_unsigned)
        parts.append(
            ParsedProjectData(
                summary=summary,
                by_id=by_id,
                parent_ids={key: sorted(set(value)) for key, value in parent_ids.items()},
            )
        )
        warnings.extend(part_warnings)
    store_items: dict[str, list[str]] = {}
    for part in parts:
        if part.summary.store_item_id:
            store_items.setdefault(part.summary.store_item_id, []).append(part.summary.part)
    parts.sort(key=lambda part: part.summary.part)
    if not parts and not warnings:
        warnings.append("no_project_data_part")
    return ProjectDataBundle(parts=parts, store_items=store_items, warnings=sorted(set(warnings)))


# --------------------------------------------------------------------------- #
# DDSP schema index
# --------------------------------------------------------------------------- #
def _build_schema_section(schema_el: etree._Element) -> SchemaSection:
    named_types: dict[str, etree._Element] = {}
    for node in schema_el.iter():
        if local_name(node.tag) != "complexType":
            continue
        name = node.get("name")
        if name:
            named_types.setdefault(name, node)
    section = SchemaSection()
    path_budget = _MAX_SCHEMA_PATHS_PER_SECTION

    def add_path(root: str, relative: str) -> None:
        nonlocal path_budget
        paths = section.roots[root]
        if relative in paths:
            return
        if path_budget <= 0:
            return
        paths.add(relative)
        path_budget -= 1

    def visit_container(
        container: etree._Element,
        root: str,
        prefix: str,
        depth: int,
        visited_types: frozenset[str],
    ) -> None:
        if depth > _MAX_SCHEMA_DEPTH:
            return
        for child in container:
            name = local_name(child.tag)
            if name == "element":
                visit_element(child, root, prefix, depth + 1, visited_types)
            elif name == "attribute":
                attribute = child.get("name")
                if attribute:
                    add_path(root, f"{prefix}/@{attribute}" if prefix else f"@{attribute}")
            elif name in {
                "complexType",
                "sequence",
                "choice",
                "all",
                "group",
                "complexContent",
                "simpleContent",
                "extension",
                "restriction",
            }:
                visit_container(child, root, prefix, depth + 1, visited_types)

    def visit_element(
        element: etree._Element,
        root: str,
        prefix: str,
        depth: int,
        visited_types: frozenset[str],
    ) -> None:
        if depth > _MAX_SCHEMA_DEPTH:
            return
        name = element.get("name") or (element.get("ref") or "").split(":")[-1]
        if not name:
            return
        relative = f"{prefix}/{name}" if prefix else name
        add_path(root, relative)
        for attribute in element:
            if local_name(attribute.tag) == "attribute":
                attribute_name = attribute.get("name")
                if attribute_name:
                    add_path(root, f"{relative}/@{attribute_name}")
        type_name = element.get("type") or ""
        if type_name:
            resolved_type = named_types.get(type_name.split(":")[-1])
            if resolved_type is not None and type_name not in visited_types:
                visit_complex_type(
                    resolved_type,
                    root,
                    relative,
                    depth + 1,
                    visited_types | {type_name},
                )
        for child in element:
            if local_name(child.tag) == "complexType":
                visit_complex_type(child, root, relative, depth + 1, visited_types)

    def visit_complex_type(
        complex_type: etree._Element,
        root: str,
        prefix: str,
        depth: int,
        visited_types: frozenset[str],
    ) -> None:
        if depth > _MAX_SCHEMA_DEPTH:
            return
        for child in complex_type:
            name = local_name(child.tag)
            if name == "attribute":
                attribute_name = child.get("name")
                if attribute_name:
                    add_path(
                        root, f"{prefix}/@{attribute_name}" if prefix else f"@{attribute_name}"
                    )
            elif name in {
                "sequence",
                "choice",
                "all",
                "complexContent",
                "simpleContent",
                "group",
                "extension",
                "restriction",
            }:
                visit_container(child, root, prefix, depth + 1, visited_types)
            elif name == "element":
                visit_element(child, root, prefix, depth + 1, visited_types)

    for root_element in _direct_children(schema_el, "element"):
        root_name = root_element.get("name")
        if not root_name:
            continue
        section.roots.setdefault(root_name, set())
        # Binding paths inside Docentric ValueBinding are relative to the
        # section root element, so the root itself maps to the empty path and
        # its attributes map to "@/Name".
        add_path(root_name, "")
        for child in root_element:
            name = local_name(child.tag)
            if name == "attribute":
                attribute_name = child.get("name")
                if attribute_name:
                    add_path(root_name, f"@{attribute_name}")
            elif name == "complexType":
                visit_complex_type(child, root_name, "", 2, frozenset())
            elif name in {
                "sequence",
                "choice",
                "all",
                "group",
                "complexContent",
                "simpleContent",
                "extension",
                "restriction",
            }:
                visit_container(child, root_name, "", 2, frozenset())
            elif name == "element":
                visit_element(child, root_name, "", 2, frozenset())
        type_name = root_element.get("type") or ""
        if type_name:
            resolved_type = named_types.get(type_name.split(":")[-1])
            if resolved_type is not None:
                visit_complex_type(resolved_type, root_name, "", 2, frozenset({type_name}))
    return section


def schema_from_ddsp(
    payload: bytes,
    *,
    name: str = "source.ddsp",
    limits: ReferenceLimits,
) -> SchemaIndex | None:
    """Build a path index from a bare DDSP XML (REF-02 scope only)."""
    root = parse_xml(payload, limits, location=name)
    if local_name(root.tag) != "dataSourcePackage":
        return None
    sections: dict[str, SchemaSection] = {}
    for data_section in root.iter():
        if local_name(data_section.tag) != "dataSection":
            continue
        section_name = truncated(_attr(data_section, "type"), 120)
        if not section_name:
            section_name = f"Section{len(sections) + 1}"
        xsd = None
        for node in data_section.iter():
            if local_name(node.tag) == "schema" and namespace_uri(node.tag) == XSD_NS:
                xsd = node
                break
        if xsd is None:
            continue
        sections[section_name] = _build_schema_section(xsd)
    product_version = None
    for node in root.iter():
        if local_name(node.tag) != "systemInfo":
            continue
        product_version = truncated(_attr(node, "productVersion"), 40)
        break
    if sections:
        return SchemaIndex(sections=sections, product_version=product_version)
    return None


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #
_ELEMENT_KIND_BY_TYPE: Final[dict[str, ElementKind]] = {
    "field": ElementKind.FIELD,
    "list": ElementKind.LIST,
    "if": ElementKind.IF,
    "image": ElementKind.IMAGE,
    "label": ElementKind.LABEL,
    "barcode": ElementKind.BARCODE,
    "summaryfield": ElementKind.SUMMARY_FIELD,
    "subdocument": ElementKind.SUB_DOCUMENT,
    "group": ElementKind.GROUP,
}


def _looks_like_expression(path: str | None) -> bool:
    return bool(path and _EXPRESSION.search(path))


def _effective_binding(
    part: ParsedProjectData,
    element: ProjectElement,
    *,
    visited: frozenset[str] = frozenset(),
    depth: int = 0,
) -> tuple[SourceBinding | None, list[str]]:
    """Resolve ``Source="."`` bindings against the enclosing List element."""
    binding = element.value_binding
    if binding is None or not binding.path or binding.source != ".":
        return binding, []
    if depth >= 10:
        return binding, ["relative_binding_depth_limit"]
    if element.id_unsigned in visited:
        return binding, ["relative_binding_cycle"]
    parents = part.parent_ids.get(element.id_unsigned, [])
    if not parents:
        return binding, ["relative_binding_without_parent"]
    candidates: set[tuple[str, str]] = set()
    notes: set[str] = {"binding_relative_to_parent"}
    for parent_id in parents:
        for parent in part.by_id.get(parent_id, []):
            parent_binding, parent_notes = _effective_binding(
                part,
                parent,
                visited=visited | {element.id_unsigned},
                depth=depth + 1,
            )
            if (
                parent_binding is None
                or not parent_binding.path
                or parent_binding.source in (None, ".")
            ):
                continue
            combined = f"{parent_binding.path.rstrip('/')}/{binding.path.lstrip('/')}"
            candidates.add((parent_binding.source, combined))
            notes.update(parent_notes)
    if not candidates:
        return binding, ["relative_binding_unresolved"]
    if len(candidates) > 1:
        return binding, ["relative_binding_ambiguous"]
    source, path = next(iter(candidates))
    return (
        SourceBinding(
            source=source,
            path=path,
            result_data_type=binding.result_data_type,
            data_kind=binding.data_kind,
        ),
        sorted(notes),
    )


def _element_kind(element_type: str | None) -> ElementKind:
    if element_type is None:
        return ElementKind.UNKNOWN
    return _ELEMENT_KIND_BY_TYPE.get(
        re.sub(r"[^a-z0-9]", "", element_type.casefold()), ElementKind.UNKNOWN
    )


def _missing(
    status: ResolutionStatus,
    link: LinkStatus,
    *codes: str,
    element_id: str | None = None,
    element_type: str | None = None,
    source_binding: SourceBinding | None = None,
    schema_source: SchemaSource = SchemaSource.NONE,
) -> ControlResolution:
    return ControlResolution(
        status=status,
        link_status=link,
        element_id_unsigned=element_id,
        element_type=element_type,
        source_binding=source_binding,
        schema_source=schema_source,
        diagnostic_codes=sorted(set(codes)),
    )


def _resolve_one(
    control: DocxControl,
    bundle: ProjectDataBundle,
    schema: SchemaIndex | None,
) -> ControlResolution:
    codes: set[str] = set()
    schema_source = SchemaSource.DDSP if schema is not None else SchemaSource.NONE
    selected: ParsedProjectData | None = None
    store_id = normalize_store_item_id(control.data_binding.store_item_id)
    if store_id is not None:
        part_names = bundle.store_items.get(store_id, [])
        if not part_names:
            return _missing(
                ResolutionStatus.MISSING_PART,
                LinkStatus.MISSING_STORE_ITEM,
                "store_item_part_missing",
                schema_source=schema_source,
            )
        if len(part_names) > 1:
            return _missing(
                ResolutionStatus.AMBIGUOUS,
                LinkStatus.MULTIPLE_PROJECT_DATA_PARTS,
                "store_item_mapped_to_multiple_parts",
                schema_source=schema_source,
            )
        by_part = bundle.by_part()
        selected = by_part.get(part_names[0])
        if selected is None:
            return _missing(
                ResolutionStatus.MISSING_PART,
                LinkStatus.STORE_ITEM_NOT_PROJECT_DATA,
                "store_item_not_project_data",
                schema_source=schema_source,
            )
    else:
        if not bundle.parts:
            return _missing(
                ResolutionStatus.MISSING_PART,
                LinkStatus.NO_PROJECT_DATA,
                "no_project_data_part",
                schema_source=schema_source,
            )
        if len(bundle.parts) == 1:
            selected = bundle.parts[0]
        else:
            canonical = control.sdt_id_unsigned
            matching = [
                part for part in bundle.parts if canonical is not None and canonical in part.by_id
            ]
            if len(matching) == 1:
                selected = matching[0]
                codes.add("multiple_project_data_selected_by_id")
            elif len(matching) > 1:
                return _missing(
                    ResolutionStatus.AMBIGUOUS,
                    LinkStatus.MULTIPLE_PROJECT_DATA_PARTS,
                    "multiple_project_data_parts",
                    schema_source=schema_source,
                )
            else:
                return _missing(
                    ResolutionStatus.UNKNOWN_PATH,
                    LinkStatus.NO_ELEMENT_FOR_ID,
                    "no_element_for_id",
                    schema_source=schema_source,
                )

    canonical = control.sdt_id_unsigned
    if canonical is None:
        return _missing(
            ResolutionStatus.UNKNOWN_PATH,
            LinkStatus.NO_SDT_ID,
            "sdt_id_missing",
            schema_source=schema_source,
        )
    elements = selected.by_id.get(canonical, [])
    if not elements:
        return _missing(
            ResolutionStatus.UNKNOWN_PATH,
            LinkStatus.NO_ELEMENT_FOR_ID,
            "no_element_for_id",
            element_id=canonical,
            schema_source=schema_source,
        )
    fingerprints = {element.fingerprint() for element in elements}
    if len(fingerprints) > 1:
        return _missing(
            ResolutionStatus.AMBIGUOUS,
            LinkStatus.DUPLICATE_ID_COLLISION,
            "duplicate_element_id_conflict",
            element_id=canonical,
            schema_source=schema_source,
        )
    element = elements[0]
    link = LinkStatus.RESOLVED_BY_ID_SHARED if len(elements) > 1 else LinkStatus.RESOLVED_BY_ID
    if len(elements) > 1:
        codes.add("duplicate_sdt_id_shared_metadata")
    inferred_kind = control.element_kind
    if (
        control.classification is Classification.RECOGNIZED
        and inferred_kind is not ElementKind.UNKNOWN
    ):
        metadata_kind = _element_kind(element.element_type)
        if metadata_kind is not ElementKind.UNKNOWN and metadata_kind is not inferred_kind:
            return _missing(
                ResolutionStatus.AMBIGUOUS,
                LinkStatus.TYPE_MISMATCH,
                "alias_metadata_type_mismatch",
                element_id=canonical,
                element_type=element.element_type,
                source_binding=element.value_binding,
                schema_source=schema_source,
            )
    raw_binding = element.value_binding
    binding, binding_notes = _effective_binding(selected, element)
    codes.update(binding_notes)
    if schema is None:
        codes.add("schema_not_provided")
        return ControlResolution(
            status=ResolutionStatus.RESOLVED,
            link_status=link,
            path_status=PathStatus.NOT_CHECKED,
            element_id_unsigned=canonical,
            element_type=element.element_type,
            source_binding=binding,
            source_binding_raw=raw_binding,
            schema_source=SchemaSource.NONE,
            diagnostic_codes=sorted(codes),
        )

    if binding is not None and _looks_like_expression(binding.path):
        codes.add("expression_not_validated")
        return ControlResolution(
            status=ResolutionStatus.RESOLVED,
            link_status=link,
            path_status=PathStatus.NOT_CHECKED,
            element_id_unsigned=canonical,
            element_type=element.element_type,
            source_binding=binding,
            source_binding_raw=raw_binding,
            schema_source=schema_source,
            diagnostic_codes=sorted(codes),
        )

    direct_match = None
    direct_xpath = control.data_binding.xpath
    section_hint = binding.source if binding is not None else None
    if direct_xpath:
        direct_match = schema.match(section_hint, direct_xpath)
        if direct_match.status is not PathStatus.MATCHED:
            codes.add("direct_xpath_unresolved")
    if binding is None or not binding.path:
        if direct_match is not None and direct_match.status is PathStatus.MATCHED:
            codes.add("path_resolved_from_word_binding")
            return ControlResolution(
                status=ResolutionStatus.RESOLVED,
                link_status=link,
                path_status=PathStatus.MATCHED,
                element_id_unsigned=canonical,
                element_type=element.element_type,
                source_binding=binding,
                source_binding_raw=raw_binding,
                normalized_path=direct_match.normalized_path,
                schema_section=direct_match.section,
                schema_source=schema_source,
                diagnostic_codes=sorted(codes),
            )
        return ControlResolution(
            status=ResolutionStatus.UNKNOWN_PATH,
            link_status=link,
            path_status=PathStatus.UNKNOWN,
            element_id_unsigned=canonical,
            element_type=element.element_type,
            source_binding=binding,
            source_binding_raw=raw_binding,
            schema_source=schema_source,
            diagnostic_codes=sorted(codes | {"value_binding_missing"}),
        )
    match = schema.match(binding.source, binding.path)
    if match.status is PathStatus.MATCHED:
        if (
            direct_match is not None
            and direct_match.status is PathStatus.MATCHED
            and direct_match.normalized_path != match.normalized_path
        ):
            return ControlResolution(
                status=ResolutionStatus.AMBIGUOUS,
                link_status=link,
                path_status=PathStatus.AMBIGUOUS,
                element_id_unsigned=canonical,
                element_type=element.element_type,
                source_binding=binding,
                source_binding_raw=raw_binding,
                normalized_path=match.normalized_path,
                schema_section=match.section,
                schema_source=schema_source,
                diagnostic_codes=sorted(codes | {"conflicting_bindings"}),
            )
        return ControlResolution(
            status=ResolutionStatus.RESOLVED,
            link_status=link,
            path_status=PathStatus.MATCHED,
            element_id_unsigned=canonical,
            element_type=element.element_type,
            source_binding=binding,
            source_binding_raw=raw_binding,
            normalized_path=match.normalized_path,
            schema_section=match.section,
            schema_source=schema_source,
            diagnostic_codes=sorted(codes),
        )
    if match.status is PathStatus.AMBIGUOUS:
        return ControlResolution(
            status=ResolutionStatus.AMBIGUOUS,
            link_status=link,
            path_status=PathStatus.AMBIGUOUS,
            element_id_unsigned=canonical,
            element_type=element.element_type,
            source_binding=binding,
            source_binding_raw=raw_binding,
            schema_section=match.section,
            schema_source=schema_source,
            diagnostic_codes=sorted(codes | {"binding_path_ambiguous"}),
        )
    path_status = (
        PathStatus.SECTION_MISSING
        if match.status is PathStatus.SECTION_MISSING
        else PathStatus.UNKNOWN
    )
    return ControlResolution(
        status=ResolutionStatus.UNKNOWN_PATH,
        link_status=link,
        path_status=path_status,
        element_id_unsigned=canonical,
        element_type=element.element_type,
        source_binding=binding,
        source_binding_raw=raw_binding,
        schema_section=match.section,
        schema_source=schema_source,
        diagnostic_codes=sorted(
            codes
            | {
                "binding_section_missing"
                if path_status is PathStatus.SECTION_MISSING
                else "binding_path_unknown"
            }
        ),
        path_suggestions=list(match.suggestions),
    )


def resolve_controls(
    controls: list[DocxControl],
    bundle: ProjectDataBundle,
    schema: SchemaIndex | None,
) -> list[ControlResolution]:
    """Resolve each control independently; never drop an unresolved instance."""
    return [_resolve_one(control, bundle, schema) for control in controls]


def effective_binding(
    part: ParsedProjectData, element: ProjectElement
) -> tuple[SourceBinding | None, list[str]]:
    """Return the binding after resolving list-relative ``Source="."`` scopes."""
    return _effective_binding(part, element)


def element_kind_from_type(element_type: str | None) -> ElementKind:
    """Map a ProjectData ``Type`` string onto the public element-kind enum."""
    return _element_kind(element_type)


def looks_like_expression(path: str | None) -> bool:
    """True when a binding path contains expression syntax that is not evaluated."""
    return _looks_like_expression(path)


__all__ = [
    "ControlResolution",
    "LinkStatus",
    "PathStatus",
    "ProjectDataBundle",
    "ProjectDataPart",
    "ProjectElement",
    "ResolutionStatus",
    "SchemaIndex",
    "SchemaMatch",
    "SchemaSource",
    "SourceBinding",
    "effective_binding",
    "element_kind_from_type",
    "load_project_data",
    "looks_like_expression",
    "normalize_store_item_id",
    "resolve_controls",
    "schema_from_ddsp",
]
