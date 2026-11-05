"""D365 embedded schema extraction (v0.10 PR-02).

The adapter reads ``customXml`` ``ProjectData`` parts of a Docentric D365
template and reconstructs the schema that is actually embedded there:
``DataSource`` declarations, their XSD (``Schema/XsdList/MainXsd``),
``PreviewData`` sample instances and the ``xse:label``/``xse:refCode`` field
metadata. It also collects the typed ``ValueBinding`` facts from
``ProjectData/Elements`` so a separate resolver can check them.

Every extracted fact keeps three pieces of provenance:

* an OOXML part name (``customXml/itemN.xml``),
* an XPath-like location inside that part,
* a stable source id (one canonical data source).

The adapter never evaluates XPath, never executes anything, never opens the
network, and only decompresses the container through
:mod:`docentric_copilot.reference.safety`, which enforces ZIP/XML limits.

If neither embedded schema nor a caller-supplied DDSP carries enough data, the
document is classified as ``schema_unavailable``; absence of evidence is never
turned into a successful binding later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Final, Literal

from docentric_copilot.errors import (
    CopilotError,
    InvalidInputError,
    NotFoundError,
    UnsupportedInputError,
)
from docentric_copilot.serialization import digest_bytes
from lxml import etree
from pydantic import BaseModel, ConfigDict, Field

from .metadata import PROJECT_DATA_NS
from .safety import (
    ReferenceLimits,
    check_input_size,
    detect_container,
    local_name,
    namespace_uri,
    parse_xml,
    read_archive,
    truncated,
)

XSD_NS: Final = "http://www.w3.org/2001/XMLSchema"
XSE_NS: Final = "http://schemas.docentric.com/xml-schema-extensions"
DC_TEMPLATES_NS: Final = "http://schemas.docentric.com/dynamics-ax/templates"

D365_PLATFORM: Final[Literal["D365FO"]] = "D365FO"
SCHEMA_FORMAT: Final[Literal["d365-embedded-schema/1.0"]] = "d365-embedded-schema/1.0"
_SCHEMA_VERSION: Final[Literal["1.0"]] = "1.0"

_MAX_DATA_SOURCES: Final = 64
_MAX_SCHEMA_DEPTH: Final = 24
_MAX_PREVIEW_PATH_ENTRIES: Final = 200
_MAX_DIAGNOSTICS: Final = 500
_MAX_WARNINGS: Final = 100
_MAX_METADATA_TEXT: Final = 200
_MAX_EVIDENCE_ITEMS: Final = 64
_CUSTOM_XML_ITEM: Final = re.compile(r"^customxml/item(\d+)\.xml$", re.IGNORECASE)
_XML_NAME: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*$")

#: XSD local type name -> stable type family used for compatibility checks.
_XSD_TYPE_FAMILY: Final[dict[str, str]] = {
    "string": "text",
    "normalizedString": "text",
    "token": "text",
    "language": "text",
    "Name": "text",
    "NCName": "text",
    "NMTOKEN": "text",
    "ID": "text",
    "IDREF": "text",
    "ENTITY": "text",
    "anyURI": "text",
    "QName": "text",
    "NOTATION": "text",
    "decimal": "number",
    "integer": "number",
    "int": "number",
    "long": "number",
    "short": "number",
    "byte": "number",
    "double": "number",
    "float": "number",
    "unsignedLong": "number",
    "unsignedInt": "number",
    "unsignedShort": "number",
    "unsignedByte": "number",
    "nonNegativeInteger": "number",
    "positiveInteger": "number",
    "nonPositiveInteger": "number",
    "negativeInteger": "number",
    "date": "temporal",
    "dateTime": "temporal",
    "dateTimeStamp": "temporal",
    "time": "temporal",
    "boolean": "boolean",
    "base64Binary": "binary",
    "hexBinary": "binary",
    "anyType": "any",
    "anySimpleType": "any",
    "duration": "text",
    "gYear": "text",
    "gYearMonth": "text",
    "gMonthDay": "text",
}


class SchemaSourceKind(str, Enum):
    """How the canonical schema was obtained for one template."""

    PROJECTDATA = "projectdata"
    DDSP = "ddsp"
    UNAVAILABLE = "unavailable"


class DiagnosticSeverity(str, Enum):
    """Severity of one extraction/resolution diagnostic."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ProvenanceKind(str, Enum):
    """Kind of the OOXML/XML node a fact came from."""

    PROJECTDATA_SCHEMA = "projectdata_schema"
    PROJECTDATA_FIELD = "projectdata_field"
    PROJECTDATA_PREVIEW = "projectdata_preview"
    DDSP_SECTION = "ddsp_section"
    DDSP_FIELD = "ddsp_field"


class SchemaProvenance(BaseModel):
    """Exact location of one schema fact inside a part.

    ``part`` is a virtual OOXML member name (``customXml/item1.xml``) or the
    DDSP file name. ``xpath`` is an XPath-like location built from local names
    and positional predicates; prefixes are not resolved and no XPath is ever
    evaluated. ``source_id`` identifies the canonical data source this fact
    belongs to.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    part: str = Field(min_length=1, max_length=240)
    xpath: str = Field(min_length=1, max_length=2_000)
    source_id: str = Field(min_length=1, max_length=300)
    kind: ProvenanceKind


class FieldMetadata(BaseModel):
    """Docentric field metadata attached to an XSD node."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str | None = Field(default=None, max_length=_MAX_METADATA_TEXT)
    reference_code: str | None = Field(default=None, max_length=_MAX_METADATA_TEXT)


class CanonicalField(BaseModel):
    """One addressable schema field in canonical form.

    ``raw_path`` is the path as defined by the schema, relative to the data
    source root and including the root element (``Root/Line/@Amount``).
    ``canonical_path`` adds the data-source name so a path is unambiguous across
    sections (``MainData/Root/Line/@Amount``).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1, max_length=300)
    source_name: str = Field(min_length=1, max_length=120)
    raw_path: str = Field(min_length=1, max_length=1_500)
    canonical_path: str = Field(min_length=1, max_length=1_800)
    node_kind: Literal["element", "attribute", "complex"]
    xsd_type: str | None = Field(default=None, max_length=120)
    type_family: str = Field(min_length=1, max_length=20)
    namespace: str = Field(default="", max_length=300)
    is_collection: bool = False
    collection_scope: str | None = Field(default=None, max_length=1_800)
    field_metadata: FieldMetadata | None = None
    provenance: SchemaProvenance


class CanonicalCollection(BaseModel):
    """One repeated element in the canonical schema."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1, max_length=300)
    source_name: str = Field(min_length=1, max_length=120)
    raw_path: str = Field(min_length=1, max_length=1_500)
    canonical_path: str = Field(min_length=1, max_length=1_800)
    element_name: str = Field(min_length=1, max_length=120)
    scope: str | None = Field(default=None, max_length=1_800)
    observed_occurrences: int | None = Field(default=None, ge=0)
    provenance: SchemaProvenance


class PreviewEvidence(BaseModel):
    """Bounded facts extracted from ``Schema/PreviewData`` or ``dsp:data``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    root_name: str | None = Field(default=None, max_length=120)
    node_count: int = Field(ge=0)
    repeated_paths: dict[str, int] = Field(default_factory=dict)
    truncated: bool = False
    provenance: SchemaProvenance


class CanonicalSource(BaseModel):
    """One DataSource/DDSP section with its extracted schema facts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1, max_length=300)
    name: str = Field(min_length=1, max_length=120)
    part: str = Field(min_length=1, max_length=240)
    namespace: str = Field(default="", max_length=300)
    namespace_mappings: dict[str, str] = Field(default_factory=dict)
    root_names: list[str] = Field(default_factory=list, max_length=32)
    origin: str | None = Field(default=None, max_length=40)
    data_kind: str | None = Field(default=None, max_length=40)
    data_section_type: str | None = Field(default=None, max_length=40)
    has_schema: bool = False
    has_preview_data: bool = False
    field_count: int = Field(default=0, ge=0)
    collection_count: int = Field(default=0, ge=0)
    schema_evidence: str | None = Field(default=None, max_length=2_000)
    provenance: SchemaProvenance
    preview: PreviewEvidence | None = None
    unsupported_constructs: list[str] = Field(default_factory=list, max_length=40)


class CanonicalSchema(BaseModel):
    """Document-wide canonical schema derived from evidence only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = _SCHEMA_VERSION
    sources: list[CanonicalSource] = Field(default_factory=list)
    fields: list[CanonicalField] = Field(default_factory=list)
    collections: list[CanonicalCollection] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list, max_length=_MAX_WARNINGS)

    def is_available(self) -> bool:
        return any(source.has_schema for source in self.sources)

    def field_count(self) -> int:
        return len(self.fields)

    def collection_count(self) -> int:
        return len(self.collections)

    def source_names(self) -> list[str]:
        return sorted({source.name for source in self.sources})


class ProjectElementFact(BaseModel):
    """One ProjectData ``Element`` and its typed binding facts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    part: str = Field(min_length=1, max_length=240)
    xpath: str = Field(min_length=1, max_length=2_000)
    element_id: str = Field(pattern=r"^[0-9]+$", max_length=20)
    element_type: str = Field(min_length=1, max_length=80)
    source: str | None = Field(default=None, max_length=120)
    path: str | None = Field(default=None, max_length=512)
    result_data_type: str | None = Field(default=None, max_length=120)
    data_kind: str | None = Field(default=None, max_length=20)
    data_section: str | None = Field(default=None, max_length=20)
    data_xpath: str | None = Field(default=None, max_length=512)
    child_ids: list[str] = Field(default_factory=list, max_length=500)
    parent_ids: list[str] = Field(default_factory=list, max_length=50)
    binding_evidence: str | None = Field(default=None, max_length=2_000)


class ProjectDataPartEvidence(BaseModel):
    """Bounded evidence for one ProjectData part."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    part: str = Field(min_length=1, max_length=240)
    xpath: str = Field(min_length=1, max_length=2_000)
    product_id: str | None = Field(default=None, max_length=40)
    product_version: str | None = Field(default=None, max_length=40)
    namespace: str = Field(default="", max_length=300)
    data_source_names: list[str] = Field(default_factory=list, max_length=_MAX_DATA_SOURCES)
    element_count: int = Field(ge=0)
    duplicate_element_ids: int = Field(ge=0)
    has_schema: bool = False
    has_preview_data: bool = False


class SchemaDiagnostic(BaseModel):
    """One explicit extraction/resolution observation; never silently dropped."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1, max_length=120)
    severity: DiagnosticSeverity
    message: str = Field(min_length=1, max_length=400)
    part: str | None = Field(default=None, max_length=240)
    xpath: str | None = Field(default=None, max_length=2_000)
    source_id: str | None = Field(default=None, max_length=300)
    details: dict[str, str] = Field(default_factory=dict)


class D365DocumentSchema(BaseModel):
    """Result of read-only extraction for one DOCX template."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_format: Literal["d365-embedded-schema/1.0"] = SCHEMA_FORMAT
    template_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    filename: str = Field(min_length=1, max_length=300)
    platform: Literal["D365FO"] = D365_PLATFORM
    schema_source: SchemaSourceKind
    schema_evidence: list[str] = Field(default_factory=list, max_length=_MAX_EVIDENCE_ITEMS)
    container: str | None = Field(default=None, max_length=1_000)
    contract_version: str | None = Field(default=None, max_length=40)
    project_data_parts: list[ProjectDataPartEvidence] = Field(default_factory=list)
    canonical: CanonicalSchema
    elements: list[ProjectElementFact] = Field(default_factory=list, max_length=10_000)
    warnings: list[str] = Field(default_factory=list, max_length=_MAX_WARNINGS)
    diagnostics: list[SchemaDiagnostic] = Field(default_factory=list, max_length=_MAX_DIAGNOSTICS)

    def has_schema(self) -> bool:
        return self.schema_source is not SchemaSourceKind.UNAVAILABLE and (
            self.canonical.is_available()
        )


@dataclass(slots=True)
class _Collected:
    """Mutable accumulator for one XSD walk."""

    fields: list[CanonicalField] = field(default_factory=list)
    collections: list[CanonicalCollection] = field(default_factory=list)
    roots: list[str] = field(default_factory=list)
    warnings: set[str] = field(default_factory=set)
    unsupported: set[str] = field(default_factory=set)
    namespaces: set[str] = field(default_factory=set)
    truncated: bool = False


def _xpath(element: etree._Element) -> str:
    """Build a deterministic, XPath-like location using local names only."""
    parts: list[str] = []
    node: etree._Element | None = element
    while node is not None and isinstance(node.tag, str):
        name = local_name(node.tag)
        parent = node.getparent()
        if parent is None:
            parts.append(name)
            break
        same = [
            child
            for child in parent
            if isinstance(child.tag, str) and local_name(child.tag) == name
        ]
        if len(same) > 1:
            try:
                position = same.index(node) + 1
            except ValueError:  # pragma: no cover - defensive
                position = 1
            parts.append(f"{name}[{position}]")
        else:
            parts.append(name)
        node = parent
    return "/" + "/".join(reversed(parts))


def _attr(element: etree._Element | None, name: str) -> str | None:
    if element is None:
        return None
    wanted = name.casefold()
    for key, value in element.attrib.items():
        if local_name(key).casefold() == wanted:
            return str(value)
    return None


def _children(element: etree._Element, name: str) -> list[etree._Element]:
    return [child for child in element if local_name(child.tag) == name]


def _first_child(element: etree._Element, name: str) -> etree._Element | None:
    for child in element:
        if local_name(child.tag) == name:
            return child
    return None


def _normalize_namespace(value: str) -> str:
    return value.strip().rstrip("/").casefold()


def _is_project_data_root(root: etree._Element) -> bool:
    if local_name(root.tag) != "ProjectData":
        return False
    namespace = namespace_uri(root.tag) or ""
    return _normalize_namespace(namespace) == _normalize_namespace(PROJECT_DATA_NS)


def _type_local(type_name: str | None) -> str | None:
    if not type_name:
        return None
    return type_name.split(":")[-1].strip() or None


def _type_family(type_name: str | None, *, named_complex: bool = False) -> str:
    local = _type_local(type_name)
    if local is None:
        return "unknown"
    if local.casefold() == "enum":
        return "enum"
    if named_complex:
        return "complex"
    return _XSD_TYPE_FAMILY.get(local, "unknown")


def _max_occurs(element: etree._Element) -> int:
    raw = element.get("maxOccurs")
    if raw is None:
        return 1
    text = raw.strip()
    if text.casefold() == "unbounded":
        return 2**31 - 1
    try:
        value = int(text)
    except ValueError:
        return 1
    return max(1, value)


def _base_simple_type(element: etree._Element) -> str | None:
    """Return the first ``base`` type found under a simpleType/restriction."""
    for node in element.iter():
        name = local_name(node.tag)
        if name in {"restriction", "extension", "list"}:
            base = node.get("base") or node.get("itemType")
            if base:
                return base
    return None


def _field_metadata(element: etree._Element) -> FieldMetadata | None:
    """Read the element's **own** ``xse:label/@xse:text`` and ``xse:refCode``.

    Only a direct ``xs:annotation`` child is inspected: a nested element's label
    belongs to that nested element, never to its parent.
    """
    label: str | None = None
    reference_code: str | None = None
    for annotation in element:
        if local_name(annotation.tag) != "annotation":
            continue
        for node in annotation.iter():
            if local_name(node.tag) != "label":
                continue
            namespace = namespace_uri(node.tag) or ""
            if namespace.rstrip("/") != XSE_NS.rstrip("/"):
                continue
            label = truncated(_attr(node, "text"), _MAX_METADATA_TEXT) or label
            reference_code = truncated(_attr(node, "refCode"), _MAX_METADATA_TEXT) or reference_code
            if label is not None and reference_code is not None:
                break
    if label is None and reference_code is None:
        return None
    return FieldMetadata(label=label, reference_code=reference_code)


def _provenance(
    element: etree._Element,
    *,
    part: str,
    source_id: str,
    kind: ProvenanceKind,
) -> SchemaProvenance:
    return SchemaProvenance(part=part, xpath=_xpath(element), source_id=source_id, kind=kind)


class _SchemaWalker:
    """Bounded XSD walker producing canonical fields and collections."""

    def __init__(
        self,
        *,
        part: str,
        source_id: str,
        source_name: str,
        limits: ReferenceLimits,
        provenance_kind: ProvenanceKind,
    ) -> None:
        self.part = part
        self.source_id = source_id
        self.source_name = source_name
        self.limits = limits
        self.provenance_kind = provenance_kind
        self.collected = _Collected()
        self._max_fields = max(1, limits.max_schema_nodes)
        self._named_types: dict[str, etree._Element] = {}
        self._named_groups: dict[str, etree._Element] = {}
        self._named_elements: dict[str, etree._Element] = {}
        self._namespace = ""

    # -- public ---------------------------------------------------------
    def walk(self, xsd_root: etree._Element) -> _Collected:
        self._namespace = xsd_root.get("targetNamespace") or ""
        self.collected.namespaces.add(self._namespace)
        for node in xsd_root.iter():
            name = local_name(node.tag)
            if name == "complexType" and node.get("name"):
                self._named_types.setdefault(node.get("name") or "", node)
            elif name == "group" and node.get("name") and node.getparent() is xsd_root:
                self._named_groups.setdefault(node.get("name") or "", node)
            elif name == "element" and node.get("name") and node.getparent() is xsd_root:
                self._named_elements.setdefault(node.get("name") or "", node)
        for root in xsd_root:
            if local_name(root.tag) != "element":
                continue
            if self.collected.truncated:
                break
            root_name = root.get("name") or _type_local(root.get("ref"))
            if root_name:
                self.collected.roots.append(root_name)
            self._element(
                root,
                parent_raw="",
                inherited_repeating=False,
                collection_scope=None,
                depth=1,
                visited_types=frozenset(),
            )
        return self.collected

    # -- fields ---------------------------------------------------------
    def _add_field(
        self,
        element: etree._Element,
        *,
        raw_path: str,
        node_kind: Literal["element", "attribute", "complex"],
        xsd_type: str | None,
        type_family: str,
        is_collection: bool,
        collection_scope: str | None,
        metadata: FieldMetadata | None = None,
    ) -> CanonicalField | None:
        if len(self.collected.fields) >= self._max_fields:
            self.collected.truncated = True
            self.collected.warnings.add("schema_node_limit")
            return None
        field = CanonicalField(
            source_id=self.source_id,
            source_name=self.source_name,
            raw_path=raw_path,
            canonical_path=f"{self.source_name}/{raw_path}",
            node_kind=node_kind,
            xsd_type=xsd_type,
            type_family=type_family,
            namespace=self._namespace,
            is_collection=is_collection,
            collection_scope=collection_scope,
            field_metadata=metadata,
            provenance=_provenance(
                element,
                part=self.part,
                source_id=self.source_id,
                kind=self.provenance_kind,
            ),
        )
        self.collected.fields.append(field)
        return field

    def _add_collection(
        self,
        element: etree._Element,
        *,
        raw_path: str,
        element_name: str,
        scope: str | None,
    ) -> None:
        if len(self.collected.collections) >= self._max_fields:
            self.collected.warnings.add("schema_collection_limit")
            return
        self.collected.collections.append(
            CanonicalCollection(
                source_id=self.source_id,
                source_name=self.source_name,
                raw_path=raw_path,
                canonical_path=f"{self.source_name}/{raw_path}",
                element_name=element_name,
                scope=scope,
                provenance=_provenance(
                    element,
                    part=self.part,
                    source_id=self.source_id,
                    kind=self.provenance_kind,
                ),
            )
        )

    # -- traversal ------------------------------------------------------
    def _element(
        self,
        element: etree._Element,
        *,
        parent_raw: str,
        inherited_repeating: bool,
        collection_scope: str | None,
        depth: int,
        visited_types: frozenset[str],
    ) -> None:
        if self.collected.truncated:
            return
        if depth > _MAX_SCHEMA_DEPTH:
            self.collected.warnings.add("schema_depth_limit")
            return
        name = element.get("name") or _type_local(element.get("ref"))
        if not name or not _XML_NAME.match(name):
            self.collected.warnings.add("schema_element_name_invalid")
            return
        raw_path = f"{parent_raw}/{name}" if parent_raw else name
        repeating = inherited_repeating or _max_occurs(element) > 1
        type_name = element.get("type")
        inline_complex = _first_child(element, "complexType")
        inline_simple = _first_child(element, "simpleType")
        resolved_type = _type_local(type_name)
        named_complex = resolved_type in self._named_types if resolved_type else False

        if inline_complex is not None:
            node_kind: Literal["element", "attribute", "complex"] = "complex"
            family = "complex"
        elif type_name is not None:
            node_kind = "complex" if named_complex else "element"
            family = _type_family(type_name, named_complex=named_complex)
        elif inline_simple is not None:
            node_kind = "element"
            base = _base_simple_type(inline_simple)
            type_name = base
            family = _type_family(base)
        else:
            node_kind = "element"
            family = "unknown"

        self._add_field(
            element,
            raw_path=raw_path,
            node_kind=node_kind,
            xsd_type=type_name
            if type_name is not None
            else ("(complexType)" if node_kind == "complex" else None),
            type_family=family,
            is_collection=repeating,
            collection_scope=collection_scope,
            metadata=_field_metadata(element),
        )
        if repeating:
            self._add_collection(
                element,
                raw_path=raw_path,
                element_name=name,
                scope=collection_scope,
            )
        child_scope = f"{self.source_name}/{raw_path}" if repeating else collection_scope

        if inline_complex is not None:
            self._complex_type(
                inline_complex,
                parent_raw=raw_path,
                collection_scope=child_scope,
                depth=depth + 1,
                visited_types=visited_types,
                node_type_name=None,
            )
        elif named_complex and resolved_type is not None:
            if resolved_type in visited_types:
                self.collected.warnings.add("recursive_schema_type")
                return
            self._complex_type(
                self._named_types[resolved_type],
                parent_raw=raw_path,
                collection_scope=child_scope,
                depth=depth + 1,
                visited_types=visited_types | {resolved_type},
                node_type_name=resolved_type,
            )
        elif inline_simple is None and type_name is None:
            # No declared type: XSD may still carry direct children.
            for child in element:
                child_name = local_name(child.tag)
                if child_name == "complexType":
                    self._complex_type(
                        child,
                        parent_raw=raw_path,
                        collection_scope=child_scope,
                        depth=depth + 1,
                        visited_types=visited_types,
                        node_type_name=None,
                    )
                elif child_name == "attribute":
                    self._attribute(child, parent_raw=raw_path, collection_scope=child_scope)
                elif child_name in {"sequence", "choice", "all", "group"}:
                    self._container(
                        child,
                        parent_raw=raw_path,
                        collection_scope=child_scope,
                        depth=depth + 1,
                        visited_types=visited_types,
                        inherited_repeating=False,
                    )

    def _complex_type(
        self,
        complex_type: etree._Element,
        *,
        parent_raw: str,
        collection_scope: str | None,
        depth: int,
        visited_types: frozenset[str],
        node_type_name: str | None,
    ) -> None:
        if depth > _MAX_SCHEMA_DEPTH:
            self.collected.warnings.add("schema_depth_limit")
            return
        for child in complex_type:
            name = local_name(child.tag)
            if name == "attribute":
                self._attribute(child, parent_raw=parent_raw, collection_scope=collection_scope)
            elif name in {"sequence", "choice", "all"}:
                self._container(
                    child,
                    parent_raw=parent_raw,
                    collection_scope=collection_scope,
                    depth=depth + 1,
                    visited_types=visited_types,
                    inherited_repeating=False,
                )
            elif name == "element":
                self._element(
                    child,
                    parent_raw=parent_raw,
                    inherited_repeating=False,
                    collection_scope=collection_scope,
                    depth=depth + 1,
                    visited_types=visited_types,
                )
            elif name == "group":
                self._group(
                    child,
                    parent_raw=parent_raw,
                    collection_scope=collection_scope,
                    depth=depth + 1,
                    visited_types=visited_types,
                )
            elif name in {"complexContent", "simpleContent"}:
                self._content(
                    child,
                    parent_raw=parent_raw,
                    collection_scope=collection_scope,
                    depth=depth + 1,
                    visited_types=visited_types,
                )
            elif name == "anyAttribute":
                self.collected.unsupported.add("xsd_any_attribute_not_supported")

    def _content(
        self,
        content: etree._Element,
        *,
        parent_raw: str,
        collection_scope: str | None,
        depth: int,
        visited_types: frozenset[str],
    ) -> None:
        for child in content:
            name = local_name(child.tag)
            if name not in {"extension", "restriction"}:
                continue
            base = _type_local(child.get("base"))
            if base and base in self._named_types and base not in visited_types:
                self._complex_type(
                    self._named_types[base],
                    parent_raw=parent_raw,
                    collection_scope=collection_scope,
                    depth=depth + 1,
                    visited_types=visited_types | {base},
                    node_type_name=base,
                )
            for node in child:
                node_name = local_name(node.tag)
                if node_name == "attribute":
                    self._attribute(node, parent_raw=parent_raw, collection_scope=collection_scope)
                elif node_name in {"sequence", "choice", "all"}:
                    self._container(
                        node,
                        parent_raw=parent_raw,
                        collection_scope=collection_scope,
                        depth=depth + 1,
                        visited_types=visited_types,
                        inherited_repeating=False,
                    )
                elif node_name == "element":
                    self._element(
                        node,
                        parent_raw=parent_raw,
                        inherited_repeating=False,
                        collection_scope=collection_scope,
                        depth=depth + 1,
                        visited_types=visited_types,
                    )

    def _container(
        self,
        container: etree._Element,
        *,
        parent_raw: str,
        collection_scope: str | None,
        depth: int,
        visited_types: frozenset[str],
        inherited_repeating: bool,
    ) -> None:
        if depth > _MAX_SCHEMA_DEPTH:
            self.collected.warnings.add("schema_depth_limit")
            return
        repeating = inherited_repeating or _max_occurs(container) > 1
        for child in container:
            name = local_name(child.tag)
            if name == "element":
                self._element(
                    child,
                    parent_raw=parent_raw,
                    inherited_repeating=repeating,
                    collection_scope=collection_scope,
                    depth=depth + 1,
                    visited_types=visited_types,
                )
            elif name == "attribute":
                self._attribute(child, parent_raw=parent_raw, collection_scope=collection_scope)
            elif name in {"sequence", "choice", "all"}:
                self._container(
                    child,
                    parent_raw=parent_raw,
                    collection_scope=collection_scope,
                    depth=depth + 1,
                    visited_types=visited_types,
                    inherited_repeating=repeating,
                )
            elif name == "group":
                self._group(
                    child,
                    parent_raw=parent_raw,
                    collection_scope=collection_scope,
                    depth=depth + 1,
                    visited_types=visited_types,
                    inherited_repeating=repeating,
                )
            elif name in {"complexContent", "simpleContent"}:
                self._content(
                    child,
                    parent_raw=parent_raw,
                    collection_scope=collection_scope,
                    depth=depth + 1,
                    visited_types=visited_types,
                )
            elif name == "any":
                self.collected.unsupported.add("xsd_any_not_supported")

    def _group(
        self,
        group: etree._Element,
        *,
        parent_raw: str,
        collection_scope: str | None,
        depth: int,
        visited_types: frozenset[str],
        inherited_repeating: bool = False,
    ) -> None:
        reference = _type_local(group.get("ref"))
        definition = self._named_groups.get(reference) if reference else None
        if definition is None:
            if reference:
                self.collected.unsupported.add("xsd_group_unresolved")
            return
        repeating = inherited_repeating or _max_occurs(group) > 1
        for child in definition:
            name = local_name(child.tag)
            if name in {"sequence", "choice", "all"}:
                self._container(
                    child,
                    parent_raw=parent_raw,
                    collection_scope=collection_scope,
                    depth=depth + 1,
                    visited_types=visited_types,
                    inherited_repeating=repeating,
                )
            elif name == "element":
                self._element(
                    child,
                    parent_raw=parent_raw,
                    inherited_repeating=repeating,
                    collection_scope=collection_scope,
                    depth=depth + 1,
                    visited_types=visited_types,
                )

    def _attribute(
        self,
        attribute: etree._Element,
        *,
        parent_raw: str,
        collection_scope: str | None,
    ) -> None:
        name = attribute.get("name") or _type_local(attribute.get("ref"))
        if not name or not _XML_NAME.match(name):
            self.collected.warnings.add("schema_attribute_name_invalid")
            return
        type_name = attribute.get("type")
        simple = _first_child(attribute, "simpleType")
        if type_name is None and simple is not None:
            type_name = _base_simple_type(simple)
        raw_path = f"{parent_raw}/@{name}" if parent_raw else f"@{name}"
        self._add_field(
            attribute,
            raw_path=raw_path,
            node_kind="attribute",
            xsd_type=type_name,
            type_family=_type_family(type_name),
            is_collection=False,
            collection_scope=collection_scope,
            metadata=_field_metadata(attribute),
        )


def _deduplicate_fields(collected: _Collected) -> set[str]:
    """Detect duplicate canonical paths; duplicates stay in the model."""
    seen: dict[str, CanonicalField] = {}
    warnings: set[str] = set()
    for item in collected.fields:
        previous = seen.get(item.canonical_path)
        if previous is None:
            seen[item.canonical_path] = item
            continue
        warnings.add("duplicate_schema_path")
        if (
            previous.node_kind != item.node_kind
            or previous.xsd_type != item.xsd_type
            or previous.is_collection != item.is_collection
        ):
            warnings.add("duplicate_schema_path_conflict")
    return warnings


def _find_xsd_root(container: etree._Element) -> etree._Element | None:
    for node in container.iter():
        if local_name(node.tag) == "schema" and (namespace_uri(node.tag) or "") == XSD_NS:
            return node
    return None


def _preview_evidence(
    container: etree._Element,
    *,
    part: str,
    source_id: str,
    provenance_kind: ProvenanceKind,
    limits: ReferenceLimits,
) -> PreviewEvidence | None:
    """Extract the sample root and repeated paths from a PreviewData/data node."""
    sample_root: etree._Element | None = None
    for child in container:
        if isinstance(child.tag, str):
            sample_root = child
            break
    if sample_root is None:
        return None
    # ProjectData wraps the instance in ``PreviewData/SampleXml``; DDSP stores
    # it directly under ``data``. Descend through wrapper elements only.
    while local_name(sample_root.tag) == "SampleXml":
        nested = next((child for child in sample_root if isinstance(child.tag, str)), None)
        if nested is None:
            break
        sample_root = nested

    repeated: dict[str, int] = {}
    node_count = 0
    preview_truncated = False
    pending: list[tuple[etree._Element, str, int]] = [(sample_root, local_name(sample_root.tag), 1)]
    while pending:
        node, raw_path, depth = pending.pop()
        node_count += 1
        if node_count > limits.max_xml_nodes or depth > _MAX_SCHEMA_DEPTH:
            preview_truncated = True
            break
        counts: dict[str, int] = {}
        for child in node:
            if not isinstance(child.tag, str):
                continue
            name = local_name(child.tag)
            counts[name] = counts.get(name, 0) + 1
        for name, count in sorted(counts.items()):
            if count > 1 and len(repeated) < _MAX_PREVIEW_PATH_ENTRIES:
                repeated[f"{raw_path}/{name}"] = count
        for child in node:
            if not isinstance(child.tag, str):
                continue
            pending.append((child, f"{raw_path}/{local_name(child.tag)}", depth + 1))
    return PreviewEvidence(
        root_name=local_name(sample_root.tag),
        node_count=node_count,
        repeated_paths=dict(sorted(repeated.items())),
        truncated=preview_truncated,
        provenance=_provenance(
            sample_root,
            part=part,
            source_id=source_id,
            kind=provenance_kind,
        ),
    )


def _apply_preview_occurrences(
    collections: list[CanonicalCollection],
    preview: PreviewEvidence | None,
) -> list[CanonicalCollection]:
    if preview is None or not preview.repeated_paths:
        return collections
    updated: list[CanonicalCollection] = []
    for item in collections:
        occurrences = preview.repeated_paths.get(item.raw_path)
        updated.append(
            item.model_copy(update={"observed_occurrences": occurrences})
            if occurrences is not None
            else item
        )
    return updated


@dataclass(slots=True)
class _SourceBuild:
    source: CanonicalSource
    fields: list[CanonicalField]
    collections: list[CanonicalCollection]
    diagnostics: list[SchemaDiagnostic] = field(default_factory=list)
    warnings: set[str] = field(default_factory=set)


def _build_project_data_source(
    data_source: etree._Element,
    *,
    part: str,
    ordinal: int,
    limits: ReferenceLimits,
) -> _SourceBuild:
    diagnostics: list[SchemaDiagnostic] = []
    warnings: set[str] = set()
    raw_name = truncated(_attr(data_source, "Name"), 120)
    name = raw_name or f"DataSource{ordinal}"
    if raw_name is None:
        warnings.add("data_source_name_missing")
        diagnostics.append(
            SchemaDiagnostic(
                code="data_source_name_missing",
                severity=DiagnosticSeverity.WARNING,
                message="A ProjectData DataSource has no Name attribute",
                part=part,
                xpath=_xpath(data_source),
                source_id=f"{part}#dataSource[{ordinal}]",
                details={"ordinal": str(ordinal)},
            )
        )
    source_id = f"{part}#dataSource[{ordinal}]"
    schema_el = _first_child(data_source, "Schema")
    origin = truncated(_attr(schema_el, "Origin"), 40)
    data_kind = truncated(_attr(data_source, "DataKind"), 40)
    section_type = truncated(_attr(data_source, "dataSectionType"), 40)
    namespace_mappings: dict[str, str] = {}
    if schema_el is not None:
        for mapping in schema_el.iter():
            if local_name(mapping.tag) != "XmlNamespaceMapping":
                continue
            prefix = truncated(_attr(mapping, "Prefix"), 40)
            uri = truncated(_attr(mapping, "Name"), 300)
            if prefix and uri and len(namespace_mappings) < 32:
                namespace_mappings[prefix] = uri
    preview_el = _first_child(data_source, "PreviewData")
    preview = (
        _preview_evidence(
            preview_el,
            part=part,
            source_id=source_id,
            provenance_kind=ProvenanceKind.PROJECTDATA_PREVIEW,
            limits=limits,
        )
        if preview_el is not None
        else None
    )

    collected = _Collected()
    namespaces: set[str] = set()
    xsd_evidence: str | None = None
    xsd_count = 0
    xsd_list = _first_child(schema_el, "XsdList") if schema_el is not None else None
    if xsd_list is not None:
        for candidate in xsd_list:
            if not isinstance(candidate.tag, str):
                continue
            xsd_root = _find_xsd_root(candidate)
            if xsd_root is None:
                continue
            xsd_count += 1
            walker = _SchemaWalker(
                part=part,
                source_id=source_id,
                source_name=name,
                limits=limits,
                provenance_kind=ProvenanceKind.PROJECTDATA_FIELD,
            )
            walked = walker.walk(xsd_root)
            collected.fields.extend(walked.fields)
            collected.collections.extend(walked.collections)
            collected.roots.extend(walked.roots)
            collected.warnings.update(walked.warnings)
            collected.unsupported.update(walked.unsupported)
            collected.namespaces.update(walked.namespaces)
            collected.truncated = collected.truncated or walked.truncated
            namespaces.update(walked.namespaces)
            if xsd_evidence is None:
                xsd_evidence = f"{part}#{_xpath(xsd_root)}"
    if xsd_count == 0:
        warnings.add("data_source_schema_missing")
        diagnostics.append(
            SchemaDiagnostic(
                code="data_source_schema_missing",
                severity=DiagnosticSeverity.WARNING,
                message=f"DataSource {name!r} has no embedded XSD schema",
                part=part,
                xpath=_xpath(data_source),
                source_id=source_id,
                details={"source": name},
            )
        )
    if len(namespaces) > 1:
        warnings.add("schema_namespace_conflict")
    duplicate_warnings = _deduplicate_fields(collected)
    collected.warnings.update(duplicate_warnings)
    if duplicate_warnings:
        diagnostics.append(
            SchemaDiagnostic(
                code="duplicate_schema_path",
                severity=DiagnosticSeverity.WARNING,
                message=f"DataSource {name!r} defines duplicate canonical schema paths",
                part=part,
                xpath=_xpath(data_source),
                source_id=source_id,
                details={"source": name},
            )
        )
    for code in sorted(collected.unsupported):
        diagnostics.append(
            SchemaDiagnostic(
                code=code,
                severity=DiagnosticSeverity.WARNING,
                message=f"Unsupported XSD construct in DataSource {name!r}",
                part=part,
                xpath=_xpath(data_source),
                source_id=source_id,
                details={"source": name},
            )
        )
    if preview is not None and preview.truncated:
        collected.warnings.add("preview_data_truncated")
    collections = _apply_preview_occurrences(collected.collections, preview)
    source = CanonicalSource(
        source_id=source_id,
        name=name,
        part=part,
        namespace=next(iter(sorted(namespaces)), ""),
        namespace_mappings=dict(sorted(namespace_mappings.items())),
        root_names=sorted(set(collected.roots)),
        origin=origin,
        data_kind=data_kind,
        data_section_type=section_type,
        has_schema=xsd_count > 0 and bool(collected.fields),
        has_preview_data=preview is not None,
        field_count=len(collected.fields),
        collection_count=len(collections),
        schema_evidence=xsd_evidence,
        provenance=_provenance(
            data_source,
            part=part,
            source_id=source_id,
            kind=ProvenanceKind.PROJECTDATA_SCHEMA,
        ),
        preview=preview,
        unsupported_constructs=sorted(collected.unsupported),
    )
    return _SourceBuild(
        source=source,
        fields=collected.fields,
        collections=collections,
        diagnostics=diagnostics,
        warnings=collected.warnings,
    )


def _parse_project_elements(
    root: etree._Element,
    *,
    part: str,
    limits: ReferenceLimits,
) -> tuple[list[ProjectElementFact], int, bool]:
    elements: list[ProjectElementFact] = []
    duplicate_ids = 0
    elements_truncated = False
    seen_ids: set[str] = set()
    containers = [node for node in root.iter() if local_name(node.tag) == "Elements"]
    for container in containers[:1]:
        for element in container:
            if local_name(element.tag) != "Element":
                continue
            raw_id = _attr(element, "Id")
            if raw_id is None:
                continue
            try:
                canonical = str(int(raw_id.strip()) % (2**32))
            except (TypeError, ValueError):
                continue
            if canonical in seen_ids:
                duplicate_ids += 1
            seen_ids.add(canonical)
            value_binding = _first_child(element, "ValueBinding")
            value = _first_child(element, "Value")
            child_ids: list[str] = []
            child_container = _first_child(element, "ChildElements")
            if child_container is not None:
                for reference in child_container:
                    if local_name(reference.tag) != "ElementRef":
                        continue
                    raw_child = _attr(reference, "Id")
                    if raw_child is None:
                        continue
                    try:
                        child_ids.append(str(int(raw_child.strip()) % (2**32)))
                    except (TypeError, ValueError):
                        continue
            binding_evidence = (
                f"{part}#{_xpath(value_binding)}" if value_binding is not None else None
            )
            elements.append(
                ProjectElementFact(
                    part=part,
                    xpath=_xpath(element),
                    element_id=canonical,
                    element_type=truncated(_attr(element, "Type"), 80) or "Unknown",
                    source=truncated(_attr(value_binding, "Source"), 120),
                    path=truncated(_attr(value_binding, "Path"), 512),
                    result_data_type=truncated(_attr(value_binding, "ResultDataType"), 120),
                    data_kind=truncated(_attr(value_binding, "DataKind"), 20),
                    data_section=truncated(_attr(value, "DataSection"), 20),
                    data_xpath=truncated(_attr(value, "DataXPath"), 512),
                    child_ids=child_ids[:500],
                    parent_ids=[],
                    binding_evidence=binding_evidence,
                )
            )
            if len(elements) >= limits.max_schema_nodes:
                elements_truncated = True
                break
    return elements, duplicate_ids, elements_truncated


def _data_source_elements(root: etree._Element) -> list[etree._Element]:
    found: list[etree._Element] = []
    for container in root.iter():
        if local_name(container.tag) != "DataSources":
            continue
        for source in container:
            if local_name(source.tag) == "DataSource":
                found.append(source)
        break
    return found


def _parent_index(elements: list[ProjectElementFact]) -> list[ProjectElementFact]:
    parents: dict[tuple[str, str], set[str]] = {}
    for element in elements:
        for child_id in element.child_ids:
            parents.setdefault((element.part, child_id), set()).add(element.element_id)
    updated: list[ProjectElementFact] = []
    for element in elements:
        parent_ids = sorted(parents.get((element.part, element.element_id), set()), key=int)
        updated.append(
            element.model_copy(update={"parent_ids": parent_ids[:50]}) if parent_ids else element
        )
    return updated


def _parse_project_data_document(
    root: etree._Element,
    *,
    part: str,
    limits: ReferenceLimits,
) -> tuple[
    list[_SourceBuild], list[ProjectElementFact], ProjectDataPartEvidence, list[SchemaDiagnostic]
]:
    diagnostics: list[SchemaDiagnostic] = []
    sources: list[_SourceBuild] = []
    all_data_source_elements = _data_source_elements(root)
    data_source_elements = all_data_source_elements[:_MAX_DATA_SOURCES]
    if len(all_data_source_elements) > _MAX_DATA_SOURCES:
        diagnostics.append(
            SchemaDiagnostic(
                code="data_source_limit",
                severity=DiagnosticSeverity.WARNING,
                message="ProjectData contains more DataSources than the adapter can index",
                part=part,
                xpath=_xpath(root),
                details={
                    "kept": str(_MAX_DATA_SOURCES),
                    "found": str(len(all_data_source_elements)),
                },
            )
        )
    if not data_source_elements:
        diagnostics.append(
            SchemaDiagnostic(
                code="project_data_no_data_sources",
                severity=DiagnosticSeverity.WARNING,
                message="ProjectData contains no DataSource declarations",
                part=part,
                xpath=_xpath(root),
            )
        )
    for ordinal, data_source in enumerate(data_source_elements, start=1):
        sources.append(
            _build_project_data_source(
                data_source,
                part=part,
                ordinal=ordinal,
                limits=limits,
            )
        )
    elements, duplicate_ids, elements_truncated = _parse_project_elements(
        root, part=part, limits=limits
    )
    elements = _parent_index(elements)
    if elements_truncated:
        diagnostics.append(
            SchemaDiagnostic(
                code="project_data_element_limit",
                severity=DiagnosticSeverity.WARNING,
                message="ProjectData contains more Elements than the adapter can index",
                part=part,
                xpath=_xpath(root),
                details={"max_elements": str(limits.max_schema_nodes)},
            )
        )
    if duplicate_ids:
        diagnostics.append(
            SchemaDiagnostic(
                code="duplicate_element_id",
                severity=DiagnosticSeverity.WARNING,
                message="ProjectData contains duplicate Element ids",
                part=part,
                xpath=_xpath(root),
                details={"duplicate_ids": str(duplicate_ids)},
            )
        )
    data_source_names = sorted({item.source.name for item in sources})
    duplicates = {
        name
        for name in data_source_names
        if sum(1 for item in sources if item.source.name == name) > 1
    }
    if duplicates:
        diagnostics.append(
            SchemaDiagnostic(
                code="duplicate_data_source_name",
                severity=DiagnosticSeverity.WARNING,
                message="ProjectData declares more than one DataSource with the same name",
                part=part,
                xpath=_xpath(root),
                details={"sources": ",".join(sorted(duplicates))},
            )
        )
    evidence = ProjectDataPartEvidence(
        part=part,
        xpath=_xpath(root),
        product_id=truncated(_attr(root, "ProductId"), 40),
        product_version=truncated(_attr(root, "ProductVersion"), 40),
        namespace=namespace_uri(root.tag) or "",
        data_source_names=data_source_names[:_MAX_DATA_SOURCES],
        element_count=len(elements),
        duplicate_element_ids=duplicate_ids,
        has_schema=any(item.source.has_schema for item in sources),
        has_preview_data=any(item.source.has_preview_data for item in sources),
    )
    return sources, elements, evidence, diagnostics


def _ddsp_sources(
    root: etree._Element,
    *,
    part: str,
    limits: ReferenceLimits,
) -> tuple[list[_SourceBuild], list[SchemaDiagnostic], str | None, list[str]]:
    diagnostics: list[SchemaDiagnostic] = []
    sources: list[_SourceBuild] = []
    warnings: set[str] = set()
    sections: list[etree._Element] = []
    for node in root.iter():
        if local_name(node.tag) != "dataSections":
            continue
        for section in node:
            if local_name(section.tag) == "dataSection":
                sections.append(section)
        break
    if not sections:
        warnings.add("ddsp_no_data_sections")
        diagnostics.append(
            SchemaDiagnostic(
                code="ddsp_no_data_sections",
                severity=DiagnosticSeverity.WARNING,
                message="DDSP contains no data sections",
                part=part,
                xpath=_xpath(root),
            )
        )
    for ordinal, section in enumerate(sections[:_MAX_DATA_SOURCES], start=1):
        name = truncated(_attr(section, "type"), 120) or f"Section{ordinal}"
        source_id = f"{part}#dataSection[{ordinal}]"
        xsd_root: etree._Element | None = None
        for node in section.iter():
            if local_name(node.tag) == "schema" and (namespace_uri(node.tag) or "") == XSD_NS:
                xsd_root = node
                break
            if local_name(node.tag) == "schema":
                xsd_root = _find_xsd_root(node)
                if xsd_root is not None:
                    break
        collected = _Collected()
        if xsd_root is not None:
            walker = _SchemaWalker(
                part=part,
                source_id=source_id,
                source_name=name,
                limits=limits,
                provenance_kind=ProvenanceKind.DDSP_FIELD,
            )
            collected = walker.walk(xsd_root)
        else:
            warnings.add("data_section_schema_missing")
            diagnostics.append(
                SchemaDiagnostic(
                    code="data_section_schema_missing",
                    severity=DiagnosticSeverity.WARNING,
                    message=f"DDSP data section {name!r} has no XSD schema",
                    part=part,
                    xpath=_xpath(section),
                    source_id=source_id,
                    details={"source": name},
                )
            )
        preview: PreviewEvidence | None = None
        data_el = _first_child(section, "data")
        if data_el is not None:
            preview = _preview_evidence(
                data_el,
                part=part,
                source_id=source_id,
                provenance_kind=ProvenanceKind.DDSP_SECTION,
                limits=limits,
            )
        duplicate_warnings = _deduplicate_fields(collected)
        collected.warnings.update(duplicate_warnings)
        if duplicate_warnings:
            diagnostics.append(
                SchemaDiagnostic(
                    code="duplicate_schema_path",
                    severity=DiagnosticSeverity.WARNING,
                    message=f"DDSP section {name!r} defines duplicate canonical schema paths",
                    part=part,
                    xpath=_xpath(section),
                    source_id=source_id,
                    details={"source": name},
                )
            )
        for code in sorted(collected.unsupported):
            diagnostics.append(
                SchemaDiagnostic(
                    code=code,
                    severity=DiagnosticSeverity.WARNING,
                    message=f"Unsupported XSD construct in DDSP section {name!r}",
                    part=part,
                    xpath=_xpath(section),
                    source_id=source_id,
                    details={"source": name},
                )
            )
        if preview is not None and preview.truncated:
            collected.warnings.add("preview_data_truncated")
        collections = _apply_preview_occurrences(collected.collections, preview)
        source = CanonicalSource(
            source_id=source_id,
            name=name,
            part=part,
            namespace=next(iter(sorted(collected.namespaces)), ""),
            namespace_mappings={},
            root_names=sorted(set(collected.roots)),
            origin=None,
            data_kind=None,
            data_section_type=name,
            has_schema=xsd_root is not None and bool(collected.fields),
            has_preview_data=preview is not None,
            field_count=len(collected.fields),
            collection_count=len(collections),
            schema_evidence=f"{part}#{_xpath(xsd_root)}" if xsd_root is not None else None,
            provenance=_provenance(
                section,
                part=part,
                source_id=source_id,
                kind=ProvenanceKind.DDSP_SECTION,
            ),
            preview=preview,
            unsupported_constructs=sorted(collected.unsupported),
        )
        sources.append(
            _SourceBuild(
                source=source,
                fields=collected.fields,
                collections=collections,
                diagnostics=[],
                warnings=collected.warnings,
            )
        )
    product_version: str | None = None
    for node in root.iter():
        if local_name(node.tag) != "systemInfo":
            continue
        product_version = truncated(_attr(node, "productVersion"), 40)
        break
    return sources, diagnostics, product_version, sorted(warnings)


def _select_document_payload(
    data: bytes,
    *,
    filename: str,
    limits: ReferenceLimits,
) -> tuple[bytes, str, str | None]:
    """Return document payload, natural filename and container member name.

    A DOCX is used directly. A ZIP/AXPP is accepted only when it contains
    exactly one DOCX; a package with several templates is rejected instead of
    silently analysing the first one.
    """
    check_input_size(data, limits)
    if detect_container(data) != "zip":
        raise InvalidInputError(
            "D365 schema input is not a readable ZIP-based document or package",
            code="reference_container_invalid",
            details={"filename": filename},
        )
    entries = read_archive(data, limits)
    names = {entry.name.casefold(): entry.name for entry in entries}
    if any(name.startswith("customxml/") for name in names) or any(
        "/customxml/" in name for name in names
    ):
        return data, filename, None
    documents = [
        entry
        for entry in entries
        if entry.name.casefold().endswith(".docx")
        and "/customxml/" not in f"/{entry.name.casefold()}"
    ]
    if not documents:
        raise InvalidInputError(
            "D365 schema input contains no DOCX template or customXml part",
            code="reference_d365_no_document",
            details={"filename": filename},
        )
    if len(documents) > 1:
        raise UnsupportedInputError(
            "D365 package contains several DOCX templates; pass one DOCX document",
            code="reference_d365_multiple_documents",
            details={"documents": len(documents)},
        )
    member = documents[0]
    return member.payload, Path(member.name).name or filename, member.name


def _extract_document(
    data: bytes,
    *,
    filename: str,
    limits: ReferenceLimits,
    ddsp_data: bytes | None,
    ddsp_name: str,
    container: str | None = None,
) -> D365DocumentSchema:
    warnings: set[str] = set()
    diagnostics: list[SchemaDiagnostic] = []
    sources: list[_SourceBuild] = []
    elements: list[ProjectElementFact] = []
    project_data_parts: list[ProjectDataPartEvidence] = []

    try:
        entries = read_archive(data, limits)
    except CopilotError:
        raise
    custom_parts = [entry for entry in entries if _CUSTOM_XML_ITEM.match(entry.name) is not None]
    custom_parts.sort(key=lambda entry: int(_CUSTOM_XML_ITEM.match(entry.name).group(1)))  # type: ignore[union-attr]
    if len(custom_parts) > limits.max_xml_documents:
        warnings.add("custom_xml_document_limit")
        custom_parts = custom_parts[: limits.max_xml_documents]
    project_data_found = False
    for entry in custom_parts:
        try:
            root = parse_xml(entry.payload, limits, location=entry.name)
        except CopilotError as exc:
            warnings.add(f"custom_xml_unreadable:{entry.name}")
            diagnostics.append(
                SchemaDiagnostic(
                    code="custom_xml_unreadable",
                    severity=DiagnosticSeverity.WARNING,
                    message=f"customXml part cannot be parsed ({exc.code})",
                    part=entry.name,
                    details={"reason": exc.code},
                )
            )
            continue
        if local_name(root.tag) != "ProjectData":
            continue
        if not _is_project_data_root(root):
            warnings.add(f"project_data_namespace_unexpected:{entry.name}")
            diagnostics.append(
                SchemaDiagnostic(
                    code="project_data_namespace_unexpected",
                    severity=DiagnosticSeverity.WARNING,
                    message="ProjectData part uses an unexpected namespace",
                    part=entry.name,
                    xpath=_xpath(root),
                    details={"namespace": namespace_uri(root.tag) or ""},
                )
            )
            continue
        project_data_found = True
        try:
            part_sources, part_elements, part_evidence, part_diagnostics = (
                _parse_project_data_document(root, part=entry.name, limits=limits)
            )
        except (CopilotError, ValueError, TypeError) as exc:
            warnings.add(f"project_data_parse_failed:{entry.name}")
            diagnostics.append(
                SchemaDiagnostic(
                    code="project_data_parse_failed",
                    severity=DiagnosticSeverity.WARNING,
                    message="ProjectData structure could not be interpreted",
                    part=entry.name,
                    details={"reason": str(exc)[:200]},
                )
            )
            continue
        sources.extend(part_sources)
        elements.extend(part_elements)
        project_data_parts.append(part_evidence)
        diagnostics.extend(part_diagnostics)
        for item in part_sources:
            warnings.update(item.warnings)
            diagnostics.extend(item.diagnostics)

    if not project_data_found:
        warnings.add("no_project_data_part")
        diagnostics.append(
            SchemaDiagnostic(
                code="no_project_data_part",
                severity=DiagnosticSeverity.INFO,
                message="No Docentric ProjectData part was found in customXml",
            )
        )

    embedded_fields = [item for item in sources if item.source.has_schema]
    ddsp_version: str | None = None
    use_ddsp = False
    ddsp_sources: list[_SourceBuild] = []
    if ddsp_data is not None:
        ddsp_root = parse_xml(ddsp_data, limits, location=ddsp_name)
        if local_name(ddsp_root.tag) != "dataSourcePackage":
            raise UnsupportedInputError(
                "Supplied DDSP schema is not a Docentric dataSourcePackage",
                code="reference_ddsp_unrecognized",
                details={"filename": ddsp_name},
            )
        ddsp_sources, ddsp_diagnostics, ddsp_version, ddsp_warnings = _ddsp_sources(
            ddsp_root, part=ddsp_name, limits=limits
        )
        if not embedded_fields and any(item.source.has_schema for item in ddsp_sources):
            sources = ddsp_sources
            use_ddsp = True
            diagnostics.extend(ddsp_diagnostics)
            warnings.update(ddsp_warnings)
            diagnostics.append(
                SchemaDiagnostic(
                    code="schema_source_ddsp",
                    severity=DiagnosticSeverity.INFO,
                    message="No usable embedded schema; DDSP schema evidence is used",
                    part=ddsp_name,
                )
            )
        elif not embedded_fields:
            # The caller supplied a DDSP but it did not yield a usable schema.
            # Keep its diagnostics: absence of evidence must stay visible.
            diagnostics.extend(ddsp_diagnostics)
            warnings.update(ddsp_warnings)
            warnings.add("ddsp_schema_unusable")
            diagnostics.append(
                SchemaDiagnostic(
                    code="ddsp_schema_unusable",
                    severity=DiagnosticSeverity.WARNING,
                    message="A DDSP schema was supplied but contains no usable section schema",
                    part=ddsp_name,
                )
            )
        elif embedded_fields:
            diagnostics.append(
                SchemaDiagnostic(
                    code="ddsp_supplied_but_embedded_schema_used",
                    severity=DiagnosticSeverity.INFO,
                    message="A DDSP schema was supplied, but the embedded ProjectData schema is primary",
                )
            )

    canonical_sources = [item.source for item in sources]
    fields = [field for item in sources for field in item.fields]
    collections = [collection for item in sources for collection in item.collections]
    duplicate_names = sorted(
        {
            source.name
            for source in canonical_sources
            if sum(1 for other in canonical_sources if other.name == source.name) > 1
        }
    )
    if duplicate_names:
        warnings.add("duplicate_source_name")
        diagnostics.append(
            SchemaDiagnostic(
                code="duplicate_source_name",
                severity=DiagnosticSeverity.WARNING,
                message="Several canonical data sources share a name; bindings cannot be resolved unambiguously",
                details={"sources": ",".join(duplicate_names)},
            )
        )
    duplicate_paths = sorted(
        {
            item.canonical_path
            for item in fields
            if sum(1 for other in fields if other.canonical_path == item.canonical_path) > 1
        }
    )
    if duplicate_paths:
        warnings.add("duplicate_schema_path")
        diagnostics.append(
            SchemaDiagnostic(
                code="duplicate_schema_path",
                severity=DiagnosticSeverity.WARNING,
                message="Canonical schema contains duplicate paths; affected bindings are ambiguous",
                details={"paths": ",".join(duplicate_paths[:10])},
            )
        )
    for item in sources:
        warnings.update(item.warnings)

    if embedded_fields:
        schema_source = SchemaSourceKind.PROJECTDATA
    elif use_ddsp:
        schema_source = SchemaSourceKind.DDSP
    else:
        schema_source = SchemaSourceKind.UNAVAILABLE
        diagnostics.append(
            SchemaDiagnostic(
                code="schema_unavailable",
                severity=DiagnosticSeverity.WARNING,
                message="No usable embedded schema and no usable DDSP schema",
                details={"embedded_sources": str(len(canonical_sources))},
            )
        )
    evidence = sorted(
        {
            source.schema_evidence
            for source in canonical_sources
            if source.has_schema and source.schema_evidence
        }
    )[:_MAX_EVIDENCE_ITEMS]
    if schema_source is SchemaSourceKind.UNAVAILABLE:
        evidence = []
    contract_version = ddsp_version
    for part in project_data_parts:
        contract_version = contract_version or part.product_version
    canonical = CanonicalSchema(
        sources=canonical_sources,
        fields=fields,
        collections=collections,
        warnings=sorted(warnings)[:_MAX_WARNINGS],
    )
    diagnostics = _deduplicate_diagnostics(diagnostics)
    diagnostics.sort(
        key=lambda item: (item.code, item.part or "", item.xpath or "", item.source_id or "")
    )
    if len(diagnostics) > _MAX_DIAGNOSTICS:
        diagnostics = diagnostics[:_MAX_DIAGNOSTICS]
        warnings.add("diagnostic_limit")
    return D365DocumentSchema(
        template_id=digest_bytes(data),
        filename=Path(filename.replace("\\", "/")).name or "document.docx",
        schema_source=schema_source,
        schema_evidence=evidence,
        container=container,
        contract_version=contract_version,
        project_data_parts=project_data_parts,
        canonical=canonical,
        elements=sorted(elements, key=lambda item: (item.part, int(item.element_id), item.xpath)),
        warnings=sorted(warnings)[:_MAX_WARNINGS],
        diagnostics=diagnostics,
    )


def _deduplicate_diagnostics(items: list[SchemaDiagnostic]) -> list[SchemaDiagnostic]:
    seen: set[tuple[str, str, str, str]] = set()
    result: list[SchemaDiagnostic] = []
    for item in items:
        key = (item.code, item.part or "", item.xpath or "", item.source_id or "")
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _limits_for(limits: ReferenceLimits | None) -> ReferenceLimits:
    return limits or ReferenceLimits()


def extract_d365_schema(
    data: bytes,
    *,
    filename: str = "document.docx",
    limits: ReferenceLimits | None = None,
    ddsp_data: bytes | None = None,
    ddsp_name: str = "source.ddsp",
) -> D365DocumentSchema:
    """Extract the canonical embedded schema of one D365 DOCX/AXPP payload.

    ``ddsp_data`` is an optional fallback schema. It is used only when the
    document contains no usable embedded schema; an explicit malformed DDSP
    raises a typed error instead of degrading silently.
    """
    resolved_limits = _limits_for(limits)
    payload, natural_name, container = _select_document_payload(
        data, filename=filename, limits=resolved_limits
    )
    return _extract_document(
        payload,
        filename=natural_name,
        limits=resolved_limits,
        ddsp_data=ddsp_data,
        ddsp_name=ddsp_name,
        container=container,
    )


def extract_d365_schema_path(
    path: str | Path,
    *,
    limits: ReferenceLimits | None = None,
    ddsp_path: str | Path | None = None,
) -> D365DocumentSchema:
    """Read one local DOCX/AXPP and extract its embedded schema (read-only)."""
    resolved_limits = _limits_for(limits)
    target = Path(path).expanduser()
    if not target.exists() or not target.is_file():
        raise NotFoundError(
            "D365 schema input does not exist or is not a file",
            code="reference_input_missing",
            details={"name": target.name},
        )
    size = target.stat().st_size
    if size > resolved_limits.max_file_bytes:
        raise UnsupportedInputError(
            "D365 schema input exceeds the configured maximum size",
            code="reference_input_too_large",
            details={"size_bytes": size, "max_bytes": resolved_limits.max_file_bytes},
        )
    payload = target.read_bytes()
    ddsp_data: bytes | None = None
    ddsp_name = "source.ddsp"
    if ddsp_path is not None:
        ddsp_target = Path(ddsp_path).expanduser()
        if not ddsp_target.exists() or not ddsp_target.is_file():
            raise InvalidInputError(
                "Supplied DDSP schema does not exist or is not a file",
                code="reference_schema_missing",
                details={"name": ddsp_target.name},
            )
        if ddsp_target.stat().st_size > resolved_limits.max_file_bytes:
            raise UnsupportedInputError(
                "Supplied DDSP schema exceeds the configured maximum size",
                code="reference_input_too_large",
            )
        ddsp_data = ddsp_target.read_bytes()
        ddsp_name = ddsp_target.name
    return extract_d365_schema(
        payload,
        filename=target.name,
        limits=resolved_limits,
        ddsp_data=ddsp_data,
        ddsp_name=ddsp_name,
    )


__all__ = [
    "D365_PLATFORM",
    "PROJECT_DATA_NS",
    "SCHEMA_FORMAT",
    "XSD_NS",
    "XSE_NS",
    "CanonicalCollection",
    "CanonicalField",
    "CanonicalSchema",
    "CanonicalSource",
    "D365DocumentSchema",
    "DiagnosticSeverity",
    "FieldMetadata",
    "PreviewEvidence",
    "ProjectDataPartEvidence",
    "ProjectElementFact",
    "ProvenanceKind",
    "SchemaDiagnostic",
    "SchemaProvenance",
    "SchemaSourceKind",
    "extract_d365_schema",
    "extract_d365_schema_path",
]
