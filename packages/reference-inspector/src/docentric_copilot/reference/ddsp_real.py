"""Real Docentric DDSP XML adapter (REF-01).

The real AX 2012 DDSP is a standalone XML document whose root is
``dsp:dataSourcePackage``. Each ``dsp:dataSection`` carries an ``xs:schema``
contract and, optionally, a ``dsp:data`` sample document. This module maps that
layout onto the existing :class:`~docentric_copilot.ddsp_parser.models.NormalizedSchema`
without changing the synthetic DDSP parser API.

Design rules:

* the parser is evidence-driven and never guesses a field that is not declared;
* attributes are exposed as ``@Name`` leaves because Docentric bindings address
  them as XPath attributes (``@SalesId``, ``SalesLine/@Name``);
* every construct that is not mapped is listed in
  :attr:`DdspSchemaEvidence.unsupported_constructs` instead of being dropped;
* malformed or hostile XML fails closed through the shared reference safety
  layer (size, DTD/entity, node and depth limits).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from docentric_copilot.config import Limits
from docentric_copilot.ddsp_parser import (
    Diagnostic,
    DiagnosticCode,
    NormalizedSchema,
    SchemaAttribute,
    SchemaNode,
    SchemaSection,
    SchemaStats,
    Severity,
)
from docentric_copilot.ddsp_parser import (
    parse_ddsp as parse_synthetic_ddsp,
)
from docentric_copilot.ddsp_parser.diagnostics import info, warning
from docentric_copilot.ddsp_parser.xsd import map_builtin_type
from docentric_copilot.errors import InvalidInputError, UnsupportedInputError
from docentric_copilot.serialization import digest_bytes
from lxml import etree
from pydantic import BaseModel, ConfigDict, Field

from .metadata import SchemaIndex
from .metadata import SchemaSection as IndexSchemaSection
from .safety import (
    ReferenceLimits,
    check_input_size,
    detect_container,
    local_name,
    namespace_uri,
    parse_xml,
    truncated,
)

DDSP_NS: Final = "http://schemas.docentric.com/dynamics-ax/data-source-packages"
XSE_NS: Final = "http://schemas.docentric.com/xml-schema-extensions"
XSD_NS: Final = "http://www.w3.org/2001/XMLSchema"

_FORMAT_BARE: Final = "bare-ddsp"
_FORMAT_SYNTHETIC: Final = "synthetic-ddsp"
_FORMAT_XSD: Final = "xsd"
_FORMAT_SAMPLE: Final = "sample-inferred"

_IDENTIFIER = re.compile(r"[^A-Za-z0-9_]")
_FIELD_NAME = re.compile(r"[^A-Za-z0-9_@.\-]")
_MAX_SCHEMA_DEPTH: Final = 32
_MAX_LABELS: Final = 5_000
_MAX_FIELD_TEXT: Final = 160
_MAX_UNSUPPORTED: Final = 50
_MAX_REPEATING: Final = 200
_MAX_DIAGNOSTICS: Final = 200
_IMAGE_TYPES: Final = {"image"}

_GROUP_TAGS: Final = {"sequence", "choice", "all"}
_UNSUPPORTED_XSD_EVIDENCE: Final = {
    "import",
    "include",
    "redefine",
    "notation",
    "unique",
    "key",
    "keyref",
    "selector",
    "field",
}
_SUPPORTED_SCHEMA_TAGS: Final = {
    "schema",
    "annotation",
    "appinfo",
    "element",
    "attribute",
    "complexType",
    "simpleType",
    "sequence",
    "choice",
    "all",
    "restriction",
    "enumeration",
    "pattern",
    "minInclusive",
    "maxInclusive",
    "minLength",
    "maxLength",
    "length",
    "documentation",
}


# --------------------------------------------------------------------------- #
# Evidence models
# --------------------------------------------------------------------------- #
class DdspDataSectionEvidence(BaseModel):
    """One ``dsp:dataSection`` and its contribution to the normalized schema."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=120)
    root_elements: list[str] = Field(default_factory=list, max_length=20)
    field_count: int = Field(default=0, ge=0)
    collection_count: int = Field(default=0, ge=0)
    max_depth: int = Field(default=0, ge=0)
    sample_values_present: bool = False
    schema_present: bool = True


class DdspSchemaEvidence(BaseModel):
    """Non-executing evidence about a parsed DDSP schema contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_format: str = Field(default=_FORMAT_BARE, max_length=40)
    schema_id: str = Field(min_length=1, max_length=120)
    schema_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    root_element: str | None = Field(default=None, max_length=120)
    namespace: str | None = Field(default=None, max_length=200)
    contract_version: str | None = Field(default=None, max_length=80)
    product_version: str | None = Field(default=None, max_length=40)
    flavour: str | None = Field(default=None, max_length=40)
    flavour_label: str | None = Field(default=None, max_length=80)
    language: str | None = Field(default=None, max_length=40)
    template_id: str | None = Field(default=None, max_length=120)
    docu_type_id: str | None = Field(default=None, max_length=120)
    locales: list[str] = Field(default_factory=list, max_length=20)
    sections: list[str] = Field(default_factory=list, max_length=20)
    data_sections: list[DdspDataSectionEvidence] = Field(default_factory=list, max_length=20)
    label_count: int = Field(default=0, ge=0)
    field_count: int = Field(default=0, ge=0)
    collection_count: int = Field(default=0, ge=0)
    repeating_sections: list[str] = Field(default_factory=list, max_length=_MAX_REPEATING)
    sample_values_present: bool = False
    unsupported_constructs: list[str] = Field(default_factory=list, max_length=80)
    stats: SchemaStats = Field(default_factory=SchemaStats)


@dataclass(frozen=True, slots=True)
class SchemaArtifact:
    """A normalized schema plus its evidence and REF-02 path index."""

    schema: NormalizedSchema
    evidence: DdspSchemaEvidence
    index: SchemaIndex
    name: str
    payload_digest: str


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def is_real_ddsp_root(root: etree._Element) -> bool:
    """Return true for the real ``dsp:dataSourcePackage`` contract."""
    return local_name(root.tag) == "dataSourcePackage" and namespace_uri(root.tag) == DDSP_NS


def _attr(element: etree._Element | None, name: str) -> str | None:
    if element is None:
        return None
    wanted = name.casefold()
    for key, value in element.attrib.items():
        if local_name(key).casefold() == wanted:
            return str(value)
    return None


def _children(element: etree._Element | None, name: str) -> list[etree._Element]:
    if element is None:
        return []
    return [
        child for child in element if isinstance(child.tag, str) and local_name(child.tag) == name
    ]


def _first_child(element: etree._Element | None, name: str) -> etree._Element | None:
    for child in _children(element, name):
        return child
    return None


def _xse_label(element: etree._Element, labels: dict[str, str] | None = None) -> str | None:
    """Return the first ``xse:label`` attached directly to a declaration.

    Only direct ``xs:annotation/xs:appinfo/xse:label`` children are considered:
    a parent must never inherit a descendant's label.
    """
    annotation = _first_child(element, "annotation")
    if annotation is None:
        return None
    appinfo = _first_child(annotation, "appinfo")
    if appinfo is None:
        return None
    for node in appinfo:
        if not isinstance(node.tag, str) or local_name(node.tag) != "label":
            continue
        text = truncated(node.get(f"{{{XSE_NS}}}text") or _attr(node, "text"), 500)
        if text:
            return text
        ref_code = truncated(node.get(f"{{{XSE_NS}}}refCode") or _attr(node, "refCode"), 120)
        if ref_code:
            resolved = labels.get(ref_code) if labels is not None else None
            return resolved or ref_code
    return None


def _max_occurs(element: etree._Element) -> int | None:
    raw = element.get("maxOccurs", "1").strip()
    if raw == "unbounded":
        return None
    try:
        value = int(raw)
    except ValueError:
        return 1
    return value


def _repeats(element: etree._Element) -> bool:
    value = _max_occurs(element)
    return value is None or value > 1


def _min_occurs(element: etree._Element) -> int:
    raw = element.get("minOccurs", "1").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 1


def _schema_id_from(name: str) -> str:
    stem = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].rsplit(".", 1)[0]
    candidate = _IDENTIFIER.sub("_", stem.casefold()).strip("_")
    if not candidate:
        candidate = "ddsp"
    if not candidate[0].isalpha():
        candidate = f"ddsp_{candidate}"
    return candidate[:60]


def _safe_section_name(raw: str, used: set[str]) -> str:
    candidate = _IDENTIFIER.sub("_", raw).strip("_") or "Section"
    if not candidate[0].isalpha():
        candidate = f"S{candidate}"
    candidate = candidate[:80]
    if candidate not in used:
        used.add(candidate)
        return candidate
    index = 2
    while f"{candidate}_{index}" in used:
        index += 1
    name = f"{candidate}_{index}"
    used.add(name)
    return name


def _safe_field_name(raw: str) -> str:
    candidate = raw.strip()
    if not candidate:
        candidate = "Field"
    candidate = _FIELD_NAME.sub("_", candidate).strip("_") or "Field"
    if not candidate[0].isalpha() and not candidate.startswith("@"):
        candidate = f"F{candidate}"
    return candidate[:120]


def _safe_path(parent: str, name: str) -> str:
    path = f"{parent}.{name}" if parent else name
    if len(path) <= 512:
        return path
    # Preserve the tail (the field name) rather than silently producing a path
    # longer than the normalized model permits.
    keep = max(1, 512 - len(name) - 1)
    return f"{parent[:keep]}.{name}"


def _sample_scalar(value: str, data_type: str) -> str | float | int | bool | None:
    cleaned = " ".join(value.split())
    if data_type in _IMAGE_TYPES:
        # Binary/base64 values are not useful as evidence and can be large.
        return None
    if len(cleaned) > _MAX_FIELD_TEXT:
        cleaned = cleaned[: _MAX_FIELD_TEXT - 1] + "…"
    if data_type == "boolean":
        lowered = cleaned.casefold()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
        return cleaned
    if data_type == "number":
        stripped = cleaned.replace(" ", "").replace("\u00a0", "")
        try:
            return float(stripped) if "." in stripped else int(stripped)
        except ValueError:
            return cleaned
    return cleaned


def _parser_limits(limits: ReferenceLimits) -> Limits:
    return Limits(
        max_ddsp_bytes=limits.max_file_bytes,
        max_uncompressed_bytes=limits.max_uncompressed_bytes,
        max_compression_ratio=limits.max_compression_ratio,
        max_zip_entries=limits.max_archive_entries,
        max_xml_nodes=limits.max_xml_nodes,
        max_xml_depth=limits.max_xml_depth,
        max_schema_nodes=limits.max_schema_nodes,
    )


# --------------------------------------------------------------------------- #
# XSD -> NormalizedSchema
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class _Catalog:
    complex_types: dict[str, etree._Element]
    simple_types: dict[str, etree._Element]
    groups: dict[str, etree._Element]
    attribute_groups: dict[str, etree._Element]
    elements: dict[str, etree._Element]


def _catalog(schema_el: etree._Element) -> _Catalog:
    catalog = _Catalog({}, {}, {}, {}, {})
    for child in schema_el:
        if not isinstance(child.tag, str) or etree.QName(child).namespace != XSD_NS:
            continue
        name = child.get("name")
        if not name:
            continue
        tag = local_name(child.tag)
        if tag == "complexType":
            catalog.complex_types.setdefault(name, child)
        elif tag == "simpleType":
            catalog.simple_types.setdefault(name, child)
        elif tag == "group":
            catalog.groups.setdefault(name, child)
        elif tag == "attributeGroup":
            catalog.attribute_groups.setdefault(name, child)
        elif tag == "element":
            catalog.elements.setdefault(name, child)
    return catalog


class _RealSchemaBuilder:
    """Convert one ``xs:schema`` into one section of the normalized model."""

    def __init__(
        self,
        *,
        section_name: str,
        limits: ReferenceLimits,
        labels: dict[str, str],
    ) -> None:
        self.section_name = section_name
        self.limits = limits
        self.labels = labels
        self.nodes: list[SchemaNode] = []
        self.diagnostics: list[Diagnostic] = []
        self.unsupported: set[str] = set()
        self.repeating: list[str] = []
        self.sample_paths: dict[str, str] = {}
        self.attribute_owners: dict[str, tuple[SchemaNode, str]] = {}
        self.root_raw_names: dict[str, str] = {}
        self._catalog = _Catalog({}, {}, {}, {}, {})
        self._node_count = 0
        self._budget_exhausted = False
        self._path_seen: dict[str, str] = {}
        self._depth_exceeded = False

    # ------------------------------------------------------------------ public
    def build(self, schema_el: etree._Element) -> SchemaSection | None:
        self._catalog = _catalog(schema_el)
        for node in schema_el.iter():
            if not isinstance(node.tag, str) or etree.QName(node).namespace != XSD_NS:
                continue
            tag = local_name(node.tag)
            if tag in _UNSUPPORTED_XSD_EVIDENCE:
                self._record_unsupported(f"xsd:{tag}")
            elif tag == "element":
                if node.get("substitutionGroup"):
                    self._record_unsupported("xsd:substitutionGroup")
                if (node.get("abstract") or "").casefold() == "true":
                    self._record_unsupported("xsd:abstract")
                if (
                    node.get("ref")
                    and (node.get("ref") or "").split(":")[-1] not in self._catalog.elements
                ):
                    self._record_unsupported("xsd:unresolved-ref")
            elif tag == "complexType" and (node.get("mixed") or "").casefold() == "true":
                self._record_unsupported("xsd:mixed")
            elif tag == "simpleType":
                for child in node:
                    if isinstance(child.tag, str) and local_name(child.tag) in {"union", "list"}:
                        self._record_unsupported(f"xsd:{local_name(child.tag)}")
        roots = _children(schema_el, "element")
        if not roots:
            self.unsupported.add("xsd:no-root-element")
            self.diagnostics.append(
                warning(
                    DiagnosticCode.SCHEMA_NOT_FOUND,
                    "The DDSP schema contains no top-level xs:element declaration",
                )
            )
            return None
        for declaration in roots:
            if self._budget_exhausted:
                break
            node = self._build_element(
                declaration,
                parent_path=self.section_name,
                raw_parent="",
                repeating_scope=False,
                required_scope=True,
                depth=0,
                visited_types=frozenset(),
            )
            if node is None:
                continue
            self.nodes.append(node)
            self.root_raw_names[node.path] = node.name
        if not self.nodes:
            return None
        if self._budget_exhausted:
            self.unsupported.add("schema:node-limit")
            self.diagnostics.append(
                warning(
                    DiagnosticCode.SCHEMA_NODE_LIMIT,
                    f"Schema node limit ({self.limits.max_schema_nodes}) was reached; "
                    "the remainder is listed as unsupported",
                )
            )
        if self._depth_exceeded:
            self.unsupported.add("schema:depth-limit")
        return SchemaSection(
            name=self.section_name,
            nodes=self.nodes,
            source="ddsp:xsd",
        )

    # ----------------------------------------------------------------- helpers
    def _reserve(self) -> bool:
        if self._budget_exhausted:
            return False
        self._node_count += 1
        if self._node_count > self.limits.max_schema_nodes:
            self._budget_exhausted = True
            return False
        return True

    def _unique_name(self, raw: str, parent_path: str) -> str:
        name = _safe_field_name(raw)
        path = _safe_path(parent_path, name)
        if path not in self._path_seen:
            self._path_seen[path] = raw
            return name
        index = 2
        while True:
            candidate_name = f"{name}_{index}"[:120]
            candidate_path = _safe_path(parent_path, candidate_name)
            if candidate_path not in self._path_seen:
                self._path_seen[candidate_path] = raw
                self.diagnostics.append(
                    warning(
                        DiagnosticCode.DUPLICATE_PATH,
                        f"Duplicate declaration '{raw}' under '{parent_path}' "
                        f"was kept as '{candidate_name}'",
                        location=candidate_path,
                    )
                )
                return candidate_name
            index += 1

    def _record_unsupported(self, token: str) -> None:
        if len(self.unsupported) < _MAX_UNSUPPORTED:
            self.unsupported.add(token)

    def _type_node(self, element: etree._Element) -> etree._Element | None:
        inline = _first_child(element, "complexType")
        if inline is not None:
            return inline
        type_name = element.get("type")
        if type_name:
            local = type_name.split(":")[-1]
            resolved = self._catalog.complex_types.get(local)
            if resolved is not None:
                return resolved
        ref = element.get("ref")
        if ref:
            target = self._catalog.elements.get(ref.split(":")[-1])
            if target is not None:
                return self._type_node(target)
        return None

    def _simple_base(self, element: etree._Element, depth: int = 0) -> str | None:
        if depth > 8:
            self._record_unsupported("xsd:simple-type-depth-limit")
            return None
        if local_name(element.tag) == "simpleType":
            return self._simple_type_base(element, depth)
        type_name = element.get("type")
        if type_name:
            local = type_name.split(":")[-1]
            definition = self._catalog.simple_types.get(local)
            if definition is not None:
                return self._simple_base(definition, depth + 1)
            return type_name
        inline = _first_child(element, "simpleType")
        if inline is None:
            return None
        return self._simple_type_base(inline, depth)

    def _simple_type_base(self, simple_type: etree._Element, depth: int) -> str | None:
        """Resolve the base of a named/inline ``simpleType`` definition."""
        for child in simple_type:
            if not isinstance(child.tag, str) or etree.QName(child).namespace != XSD_NS:
                continue
            tag = local_name(child.tag)
            if tag == "restriction":
                base = child.get("base")
                if base:
                    local = base.split(":")[-1]
                    nested = self._catalog.simple_types.get(local)
                    if nested is not None:
                        return self._simple_base(nested, depth + 1)
                    return base
            elif tag == "union":
                self._record_unsupported("xsd:union")
                return child.get("memberTypes", "xs:string").split()[0]
            elif tag == "list":
                self._record_unsupported("xsd:list")
                return child.get("itemType", "xs:string")
        return None

    def _attribute_node(
        self,
        declaration: etree._Element,
        parent_node: SchemaNode,
        raw_parent: str,
        *,
        required: bool,
    ) -> None:
        raw_name = (declaration.get("name") or "").strip()
        if not raw_name:
            self._record_unsupported("xsd:attribute-without-name")
            return
        if not self._reserve():
            return
        name = f"@{raw_name}"[:120]
        path = _safe_path(parent_node.path, name)
        if path in self._path_seen:
            self._record_unsupported("xsd:duplicate-attribute")
            return
        self._path_seen[path] = raw_name
        data_type, diagnostic = self._map_type(declaration, raw_name)
        if diagnostic is not None:
            self.diagnostics.append(diagnostic)
        label = _xse_label(declaration, self.labels)
        node = SchemaNode(
            name=name,
            path=path,
            data_type=data_type,
            collection=False,
            required=required or (declaration.get("use") or "").casefold() == "required",
            source=f"xsd:{_truncate_source(raw_parent + '/@' + raw_name)}",
            description=label,
        )
        parent_node.children.append(node)
        if len(parent_node.attributes) < 50:
            attribute = SchemaAttribute(name=raw_name, data_type=data_type, source=node.source)
            parent_node.attributes.append(attribute)
            self.attribute_owners[path] = (parent_node, raw_name)
        else:
            self._record_unsupported("xsd:attribute-limit")
        self.sample_paths[path] = f"{raw_parent}/@{raw_name}" if raw_parent else f"@{raw_name}"

    def _map_type(
        self, declaration: etree._Element, raw_name: str
    ) -> tuple[str, Diagnostic | None]:
        base = self._simple_base(declaration) or "xs:string"
        data_type, diagnostic = map_builtin_type(base, raw_name)
        if diagnostic is not None:
            self._record_unsupported(f"xsd:type:{base.split(':')[-1]}")
            diagnostic = diagnostic.model_copy(update={"location": raw_name})
        return data_type, diagnostic

    def _build_element(
        self,
        declaration: etree._Element,
        *,
        parent_path: str,
        raw_parent: str,
        repeating_scope: bool,
        required_scope: bool,
        depth: int,
        visited_types: frozenset[str],
    ) -> SchemaNode | None:
        raw_name = (
            declaration.get("name") or (declaration.get("ref") or "").split(":")[-1]
        ).strip()
        if not raw_name:
            self._record_unsupported("xsd:element-without-name")
            return None
        if not self._reserve():
            return None
        if depth > _MAX_SCHEMA_DEPTH or depth >= 32:
            self._depth_exceeded = True
            self._record_unsupported("schema:depth-limit")
        name = self._unique_name(raw_name, parent_path)
        path = _safe_path(parent_path, name)
        collection = repeating_scope or _repeats(declaration)
        required = required_scope and _min_occurs(declaration) > 0
        raw_path = f"{raw_parent}/{raw_name}" if raw_parent else raw_name
        type_name = (declaration.get("type") or "").split(":")[-1]
        recursion_key = f"{type_name}|{id(self._type_node(declaration))}" if type_name else None

        node = SchemaNode(
            name=name,
            path=path,
            collection=collection,
            required=required,
            source=f"xsd:{_truncate_source(raw_path)}",
            description=_xse_label(declaration, self.labels),
        )
        self.sample_paths[path] = raw_path
        if collection and len(self.repeating) < _MAX_REPEATING and path not in self.repeating:
            self.repeating.append(path)

        type_node = self._type_node(declaration)
        if depth >= _MAX_SCHEMA_DEPTH:
            node.data_type = "any"
            node.description = node.description or "Nested deeper than the supported schema depth"
            return node
        if type_node is not None:
            if recursion_key is not None and recursion_key in visited_types:
                node.data_type = "any"
                self.diagnostics.append(
                    warning(
                        DiagnosticCode.RECURSIVE_TYPE,
                        f"Recursive type at '{path}' was not expanded",
                        location=path,
                    )
                )
                self._record_unsupported("xsd:recursive-type")
                return node
            self._build_complex_type(
                type_node,
                node,
                raw_parent=raw_path,
                repeating_scope=False,
                required_scope=True,
                depth=depth + 1,
                visited_types=(
                    visited_types | {recursion_key} if recursion_key is not None else visited_types
                ),
            )
            node.data_type = "collection" if node.collection else "object"
            if not node.children:
                # A complex type with attributes only is still a scalar record;
                # attributes remain addressable as @Name children.
                node.data_type = "string"
            return node

        data_type, diagnostic = self._map_type(declaration, raw_name)
        if diagnostic is not None:
            self.diagnostics.append(diagnostic)
        node.data_type = data_type
        return node

    def _build_complex_type(
        self,
        type_node: etree._Element,
        node: SchemaNode,
        *,
        raw_parent: str,
        repeating_scope: bool,
        required_scope: bool,
        depth: int,
        visited_types: frozenset[str],
    ) -> None:
        for child in type_node:
            if not isinstance(child.tag, str):
                continue
            tag = local_name(child.tag)
            if etree.QName(child).namespace != XSD_NS:
                self._record_unsupported(f"foreign:{tag}")
                continue
            if tag in _GROUP_TAGS or tag == "complexType":
                self._walk_group(
                    child,
                    node,
                    raw_parent=raw_parent,
                    repeating_scope=repeating_scope,
                    required_scope=required_scope,
                    depth=depth,
                    visited_types=visited_types,
                )
            elif tag == "element":
                if len(node.children) >= 500:
                    self._record_unsupported("schema:children-limit")
                    continue
                child_node = self._build_element(
                    child,
                    parent_path=node.path,
                    raw_parent=raw_parent,
                    repeating_scope=repeating_scope,
                    required_scope=required_scope,
                    depth=depth,
                    visited_types=visited_types,
                )
                if child_node is not None:
                    node.children.append(child_node)
            elif tag == "attribute":
                self._attribute_node(
                    child,
                    node,
                    raw_parent,
                    required=required_scope and _min_occurs(child) > 0,
                )
            elif tag == "attributeGroup":
                self._record_unsupported("xsd:attributeGroup")
                self._walk_attribute_group(
                    child,
                    node,
                    raw_parent,
                    required=required_scope,
                    depth=0,
                )
            elif tag == "complexContent":
                self._record_unsupported("xsd:complexContent")
                self._walk_complex_content(
                    child,
                    node,
                    raw_parent=raw_parent,
                    depth=depth,
                    visited_types=visited_types,
                )
            elif tag == "simpleContent":
                self._record_unsupported("xsd:simpleContent")
                self._walk_complex_content(
                    child,
                    node,
                    raw_parent=raw_parent,
                    depth=depth,
                    visited_types=visited_types,
                )
            elif tag == "any":
                self._record_unsupported("xsd:any")
                self.diagnostics.append(
                    warning(
                        DiagnosticCode.SCHEMA_NOT_FOUND,
                        f"Wildcard xs:any at '{node.path}' is not mapped to fields",
                        location=node.path,
                    )
                )
            elif tag == "anyAttribute":
                self._record_unsupported("xsd:anyAttribute")
            elif tag == "annotation":
                continue
            elif tag in _SUPPORTED_SCHEMA_TAGS:
                # e.g. a declaration nested where not expected; keep it visible.
                continue
            else:
                self._record_unsupported(f"xsd:{tag}")

    def _walk_group(
        self,
        group: etree._Element,
        node: SchemaNode,
        *,
        raw_parent: str,
        repeating_scope: bool,
        required_scope: bool,
        depth: int,
        visited_types: frozenset[str],
    ) -> None:
        tag = local_name(group.tag)
        if tag not in _GROUP_TAGS and tag != "complexType":
            self._record_unsupported(f"xsd:{tag}")
        group_repeats = repeating_scope or _repeats(group)
        group_required = required_scope and _min_occurs(group) > 0
        if tag == "choice":
            # Alternatives are mutually exclusive, but a repeating choice still
            # means each produced element is a collection item.
            pass
        for child in group:
            if not isinstance(child.tag, str) or etree.QName(child).namespace != XSD_NS:
                continue
            child_tag = local_name(child.tag)
            if child_tag in _GROUP_TAGS or child_tag == "complexType":
                self._walk_group(
                    child,
                    node,
                    raw_parent=raw_parent,
                    repeating_scope=group_repeats,
                    required_scope=group_required,
                    depth=depth,
                    visited_types=visited_types,
                )
            elif child_tag == "element":
                if len(node.children) >= 500:
                    self._record_unsupported("schema:children-limit")
                    continue
                child_node = self._build_element(
                    child,
                    parent_path=node.path,
                    raw_parent=raw_parent,
                    repeating_scope=group_repeats,
                    required_scope=group_required,
                    depth=depth,
                    visited_types=visited_types,
                )
                if child_node is not None:
                    node.children.append(child_node)
            elif child_tag == "attribute":
                self._attribute_node(
                    child,
                    node,
                    raw_parent,
                    required=group_required and _min_occurs(child) > 0,
                )
            elif child_tag == "attributeGroup":
                self._record_unsupported("xsd:attributeGroup")
                self._walk_attribute_group(
                    child, node, raw_parent, required=group_required, depth=0
                )
            elif child_tag == "group":
                self._record_unsupported("xsd:group")
                ref = (child.get("ref") or "").split(":")[-1]
                target = self._catalog.groups.get(ref)
                if target is not None and depth < _MAX_SCHEMA_DEPTH:
                    self._walk_group(
                        target,
                        node,
                        raw_parent=raw_parent,
                        repeating_scope=group_repeats,
                        required_scope=group_required,
                        depth=depth + 1,
                        visited_types=visited_types,
                    )
            elif child_tag == "any":
                self._record_unsupported("xsd:any")
            elif child_tag == "annotation":
                continue
            else:
                self._record_unsupported(f"xsd:{child_tag}")

    def _walk_attribute_group(
        self,
        declaration: etree._Element,
        node: SchemaNode,
        raw_parent: str,
        *,
        required: bool,
        depth: int,
    ) -> None:
        if depth > 8:
            self._record_unsupported("xsd:attributeGroup-depth-limit")
            return
        ref = (declaration.get("ref") or "").split(":")[-1]
        target = self._catalog.attribute_groups.get(ref) if ref else declaration
        if target is None:
            self._record_unsupported("xsd:unresolved-attributeGroup")
            return
        for child in target:
            if not isinstance(child.tag, str) or etree.QName(child).namespace != XSD_NS:
                continue
            tag = local_name(child.tag)
            if tag == "attribute":
                self._attribute_node(child, node, raw_parent, required=required)
            elif tag == "attributeGroup":
                self._record_unsupported("xsd:attributeGroup")
                self._walk_attribute_group(
                    child, node, raw_parent, required=required, depth=depth + 1
                )

    def _walk_complex_content(
        self,
        content: etree._Element,
        node: SchemaNode,
        *,
        raw_parent: str,
        depth: int,
        visited_types: frozenset[str],
    ) -> None:
        for child in content:
            if not isinstance(child.tag, str) or etree.QName(child).namespace != XSD_NS:
                continue
            tag = local_name(child.tag)
            if tag not in {"extension", "restriction"}:
                continue
            base = (child.get("base") or "").split(":")[-1]
            target = self._catalog.complex_types.get(base) if base else None
            if target is not None and depth < _MAX_SCHEMA_DEPTH:
                self._build_complex_type(
                    target,
                    node,
                    raw_parent=raw_parent,
                    repeating_scope=False,
                    required_scope=True,
                    depth=depth + 1,
                    visited_types=visited_types,
                )
            elif base:
                self._record_unsupported(f"xsd:base:{base}")
            self._build_complex_type(
                child,
                node,
                raw_parent=raw_parent,
                repeating_scope=False,
                required_scope=True,
                depth=depth + 1,
                visited_types=visited_types,
            )

    # ---------------------------------------------------------------- samples
    def apply_sample(self, data: etree._Element) -> bool:
        """Attach first-occurrence sample values to matching schema nodes."""
        values: dict[str, str] = {}
        for child in data:
            if not isinstance(child.tag, str):
                continue
            _collect_sample(child, local_name(child.tag), values, depth=0)
        if not values:
            return False
        found = False
        by_path = {node.path: node for node in self._walk_nodes()}
        for path, raw_path in self.sample_paths.items():
            node = by_path.get(path)
            if node is None:
                continue
            raw_value = values.get(raw_path)
            if raw_value is None:
                continue
            sample = _sample_scalar(raw_value, node.data_type)
            if sample is None:
                continue
            node.sample_value = sample
            owner = self.attribute_owners.get(path)
            if owner is not None:
                parent, attribute_name = owner
                parent.attributes = [
                    attribute.model_copy(update={"sample_value": sample})
                    if attribute.name == attribute_name
                    else attribute
                    for attribute in parent.attributes
                ]
            found = True
        return found

    def _walk_nodes(self) -> list[SchemaNode]:
        nodes: list[SchemaNode] = []
        for root in self.nodes:
            nodes.extend(root.walk())
        return nodes


def _truncate_source(value: str) -> str:
    return value if len(value) <= 400 else value[:399] + "…"


def _collect_sample(element: etree._Element, path: str, out: dict[str, str], *, depth: int) -> None:
    if depth > 64:
        return
    for key, value in element.attrib.items():
        if len(out) < 20_000:
            out.setdefault(f"{path}/@{local_name(key)}", str(value))
    children = [child for child in element if isinstance(child.tag, str)]
    grouped: dict[str, list[etree._Element]] = {}
    for child in children:
        grouped.setdefault(local_name(child.tag), []).append(child)
    for name in sorted(grouped):
        first = grouped[name][0]
        child_path = f"{path}/{name}"
        has_children = any(isinstance(item.tag, str) for item in first)
        if has_children or first.attrib:
            _collect_sample(first, child_path, out, depth=depth + 1)
        else:
            if len(out) < 20_000:
                out.setdefault(child_path, (first.text or "").strip())


# --------------------------------------------------------------------------- #
# Real DDSP document parsing
# --------------------------------------------------------------------------- #
def _parse_label_map(root: etree._Element) -> tuple[dict[str, str], int, set[str]]:
    labels_container = _first_child(root, "labels")
    label_map: dict[str, str] = {}
    count = 0
    languages: set[str] = set()
    for label in _children(labels_container, "label")[:_MAX_LABELS]:
        count += 1
        code = _attr(label, "code")
        name = _attr(label, "name")
        for text in _children(label, "text"):
            language = _attr(text, "language")
            if language:
                languages.add(language)
            value = truncated(_attr(text, "value"), 500)
            if value and code:
                label_map.setdefault(code, value)
            if value and name:
                label_map.setdefault(name, value)
    return label_map, count, languages


def _design_languages(root: etree._Element) -> set[str]:
    languages: set[str] = set()
    design = _first_child(root, "design")
    for container in _children(design, "languages"):
        for language in _children(container, "language"):
            value = truncated(_attr(language, "value"), 40)
            if value:
                languages.add(value)
    return languages


def _parse_real_root(
    root: etree._Element,
    *,
    name: str,
    limits: ReferenceLimits,
) -> tuple[NormalizedSchema, DdspSchemaEvidence]:
    diagnostics: list[Diagnostic] = [
        info(
            DiagnosticCode.FORMAT_DETECTED,
            f"Docentric DDSP detected: {local_name(root.tag)} in {namespace_uri(root.tag)}",
        )
    ]
    unsupported: set[str] = set()

    def record_unsupported(token: str) -> None:
        if len(unsupported) < _MAX_UNSUPPORTED:
            unsupported.add(token)

    label_map, label_count, label_languages = _parse_label_map(root)
    design_languages = _design_languages(root)
    locales = sorted(design_languages | label_languages)

    known_children = {"design", "systemInfo", "labels", "dataSections"}
    for child in root:
        if not isinstance(child.tag, str):
            continue
        tag = local_name(child.tag)
        if tag not in known_children:
            record_unsupported(f"ddsp:{tag}")

    system_info = _first_child(root, "systemInfo")
    product_version = truncated(_attr(system_info, "productVersion"), 40)
    flavour = truncated(_attr(system_info, "flavour"), 40)
    flavour_label = truncated(_attr(system_info, "flavourLabel"), 80)
    language = truncated(_attr(system_info, "language"), 40)
    mail_merge = _first_child(system_info, "mailMerge")
    template_id = truncated(_attr(mail_merge, "templateId"), 120)
    docu_type_id = truncated(_attr(mail_merge, "docuTypeId"), 120)

    data_sections_container = _first_child(root, "dataSections")
    if data_sections_container is None:
        raise UnsupportedInputError(
            "Docentric DDSP does not contain a dsp:dataSections element",
            code="reference_ddsp_unrecognized",
            details={"root_element": local_name(root.tag)},
        )

    used_names: set[str] = set()
    sections: list[SchemaSection] = []
    section_evidence: list[DdspDataSectionEvidence] = []
    repeating_sections: list[str] = []
    sample_values_present = False
    seen_types: set[str] = set()
    for container_child in data_sections_container:
        if (
            isinstance(container_child.tag, str)
            and local_name(container_child.tag) != "dataSection"
        ):
            record_unsupported(f"data-sections-child:{local_name(container_child.tag)}")
    for data_section in _children(data_sections_container, "dataSection"):
        raw_type = truncated(_attr(data_section, "type"), 120) or ""
        schema_holder = _first_child(data_section, "schema")
        schema_el = None
        if schema_holder is not None:
            for node in schema_holder.iter():
                if local_name(node.tag) == "schema" and namespace_uri(node.tag) == XSD_NS:
                    schema_el = node
                    break
        if schema_el is None:
            record_unsupported(f"data-section-without-schema:{raw_type or 'unknown'}")
            diagnostics.append(
                warning(
                    DiagnosticCode.SCHEMA_NOT_FOUND,
                    f"Data section '{raw_type or 'unknown'}' has no XSD schema and was not mapped",
                )
            )
            continue
        if raw_type in seen_types:
            record_unsupported(f"duplicate-data-section:{raw_type}")
        seen_types.add(raw_type)
        section_name = _safe_section_name(raw_type or "Section", used_names)
        builder = _RealSchemaBuilder(section_name=section_name, limits=limits, labels=label_map)
        section = builder.build(schema_el)
        diagnostics.extend(builder.diagnostics)
        unsupported.update(builder.unsupported)
        if section is None:
            record_unsupported(f"data-section-without-root:{raw_type or section_name}")
            continue
        data = _first_child(data_section, "data")
        sample_present = builder.apply_sample(data) if data is not None else False
        if data is None:
            diagnostics.append(
                info(
                    DiagnosticCode.SAMPLE_NOT_FOUND,
                    f"Data section '{section_name}' has no sample data",
                )
            )
        sample_values_present = sample_values_present or sample_present
        sections.append(section)
        repeat_paths = sorted(builder.repeating)
        for path in repeat_paths:
            if len(repeating_sections) < _MAX_REPEATING:
                repeating_sections.append(path)
        section_evidence.append(
            DdspDataSectionEvidence(
                name=section_name,
                root_elements=sorted(builder.root_raw_names.values())[:20],
                field_count=sum(1 for node in builder._walk_nodes() if node.is_scalar),
                collection_count=len(repeat_paths),
                max_depth=_section_depth(section),
                sample_values_present=sample_present,
                schema_present=True,
            )
        )
    if not sections:
        raise UnsupportedInputError(
            "Docentric DDSP does not contain a usable data section with an XSD schema",
            code="reference_ddsp_no_sections",
            details={"data_sections": len(_children(data_sections_container, "dataSection"))},
        )
    if len(sections) > 20:
        unsupported.add("ddsp:section-limit")
        sections = sections[:20]
    diagnostics.append(
        info(
            DiagnosticCode.SECTIONS_DETECTED,
            "DDSP data sections: " + ", ".join(section.name for section in sections),
        )
    )
    if label_count:
        diagnostics.append(
            info(DiagnosticCode.FORMAT_DETECTED, f"DDSP defines {label_count} labels")
        )
    for token in sorted(unsupported):
        if len(diagnostics) >= _MAX_DIAGNOSTICS:
            break
        diagnostics.append(
            warning(
                DiagnosticCode.SCHEMA_NOT_FOUND,
                f"Unsupported construct preserved as evidence: {token}",
            )
        )
    schema_id = _schema_id_from(name)
    schema = NormalizedSchema(
        schema_id=schema_id,
        source="docentric-ax-ddsp",
        format_version=product_version,
        container_format="xml",
        sections=sections,
        diagnostics=diagnostics[:200],
        sample_data_available=sample_values_present,
        locales=locales[:50],
    )
    stats = schema.stats()
    field_count = sum(1 for node in _all_nodes(sections) if node.is_scalar)
    evidence = DdspSchemaEvidence(
        schema_format=_FORMAT_BARE,
        schema_id=schema_id,
        schema_digest=schema.digest(),
        root_element=local_name(root.tag),
        namespace=namespace_uri(root.tag),
        contract_version=product_version,
        product_version=product_version,
        flavour=flavour,
        flavour_label=flavour_label,
        language=language,
        template_id=template_id,
        docu_type_id=docu_type_id,
        locales=locales[:20],
        sections=[section.name for section in sections],
        data_sections=section_evidence,
        label_count=label_count,
        field_count=field_count,
        collection_count=stats.collection_count,
        repeating_sections=repeating_sections,
        sample_values_present=sample_values_present,
        unsupported_constructs=sorted(unsupported)[:80],
        stats=stats,
    )
    return schema, evidence


def _all_nodes(sections: list[SchemaSection]) -> list[SchemaNode]:
    nodes: list[SchemaNode] = []
    for section in sections:
        for root in section.nodes:
            nodes.extend(root.walk())
    return nodes


def _section_depth(section: SchemaSection) -> int:
    def depth(nodes: list[SchemaNode], level: int) -> int:
        if not nodes:
            return level
        return max(depth(node.children, level + 1) for node in nodes)

    return depth(section.nodes, 0)


# --------------------------------------------------------------------------- #
# Schema index and dispatch
# --------------------------------------------------------------------------- #
_MAX_INDEX_PATHS_PER_SECTION: Final = 5_000


def schema_index_from_schema(schema: NormalizedSchema) -> SchemaIndex:
    """Build the REF-02 slash-path index from a normalized schema.

    Attributes are included even when the underlying parser only stored them in
    ``SchemaNode.attributes``; this keeps REF-02 resolution identical for
    synthetic XSD schemas and the real DDSP adapter.
    """
    sections: dict[str, IndexSchemaSection] = {}
    for section in schema.sections:
        index = IndexSchemaSection()
        budget = [_MAX_INDEX_PATHS_PER_SECTION]
        for root_node in section.nodes:
            paths = index.roots.setdefault(root_node.name, set())
            _index_node(root_node, [], paths, budget_holder=budget)
        sections[section.name] = index
    return SchemaIndex(sections=sections, product_version=schema.format_version)


def _index_node(
    node: SchemaNode,
    parts: list[str],
    paths: set[str],
    *,
    budget_holder: list[int],
) -> None:
    if budget_holder[0] <= 0:
        return
    relative = "/".join(parts)
    if relative not in paths:
        paths.add(relative)
        budget_holder[0] -= 1
    for attribute in node.attributes:
        relative_attribute = "/".join([*parts, f"@{attribute.name}"])
        if relative_attribute not in paths:
            paths.add(relative_attribute)
            budget_holder[0] -= 1
    for child in node.children:
        _index_node(child, [*parts, child.name], paths, budget_holder=budget_holder)


def _synthetic_format(payload: bytes, schema: NormalizedSchema) -> str:
    if detect_container(payload) == "zip":
        return _FORMAT_SYNTHETIC
    codes = {item.code for item in schema.diagnostics}
    if DiagnosticCode.SCHEMA_INFERRED in codes:
        return _FORMAT_SAMPLE
    return _FORMAT_XSD


def _fallback_evidence(schema: NormalizedSchema, *, schema_format: str) -> DdspSchemaEvidence:
    stats = schema.stats()
    repeating = [path for path in schema.paths if (node := schema.node(path)) and node.collection]
    return DdspSchemaEvidence(
        schema_format=schema_format,
        schema_id=schema.schema_id,
        schema_digest=schema.digest(),
        root_element=None,
        namespace=None,
        contract_version=schema.format_version,
        product_version=schema.format_version,
        locales=schema.locales[:20],
        sections=schema.section_names[:20],
        data_sections=[
            DdspDataSectionEvidence(
                name=section.name,
                root_elements=[node.name for node in section.nodes][:20],
                field_count=sum(
                    1 for root in section.nodes for node in root.walk() if node.is_scalar
                ),
                collection_count=sum(
                    1 for root in section.nodes for node in root.walk() if node.collection
                ),
                max_depth=_section_depth(section),
                sample_values_present=any(
                    node.sample_value is not None for root in section.nodes for node in root.walk()
                ),
                schema_present=True,
            )
            for section in schema.sections[:20]
        ],
        label_count=0,
        field_count=sum(1 for node in _all_nodes(schema.sections) if node.is_scalar),
        collection_count=stats.collection_count,
        repeating_sections=repeating[:_MAX_REPEATING],
        sample_values_present=schema.sample_data_available,
        unsupported_constructs=sorted(
            {
                f"diagnostic:{item.code.value}"
                for item in schema.diagnostics
                if item.severity is Severity.WARNING
            }
        )[:80],
        stats=stats,
    )


def parse_real_ddsp(
    payload: bytes,
    *,
    name: str = "source.ddsp",
    limits: ReferenceLimits | None = None,
) -> SchemaArtifact:
    """Parse a bare real Docentric DDSP XML document.

    Raises :class:`UnsupportedInputError` when the document is not a real DDSP,
    :class:`InvalidInputError` when XML is malformed, and the safety errors from
    :mod:`docentric_copilot.reference.safety` for hostile input.
    """
    resolved = limits or ReferenceLimits()
    check_input_size(payload, resolved)
    root = parse_xml(payload, resolved, location=name)
    if not is_real_ddsp_root(root):
        raise UnsupportedInputError(
            "XML document is not a Docentric DDSP (expected dsp:dataSourcePackage)",
            code="reference_ddsp_unrecognized",
            details={
                "root_element": local_name(root.tag),
                "namespace": namespace_uri(root.tag) or "",
            },
        )
    schema, evidence = _parse_real_root(root, name=name, limits=resolved)
    index = schema_index_from_schema(schema)
    return SchemaArtifact(
        schema=schema,
        evidence=evidence,
        index=index,
        name=name,
        payload_digest=digest_bytes(payload),
    )


def parse_ddsp_schema(
    payload: bytes,
    *,
    name: str = "source.ddsp",
    limits: ReferenceLimits | None = None,
) -> SchemaArtifact:
    """Parse a real DDSP, a simple XSD or a synthetic DDSP package.

    The real adapter is selected by the ``dsp:dataSourcePackage`` root and its
    namespace, not by the file extension. Everything else is delegated to the
    existing v0.5 synthetic parser so that API compatibility is preserved.
    """
    resolved = limits or ReferenceLimits()
    check_input_size(payload, resolved)
    container = detect_container(payload)
    if container == "xml":
        root = parse_xml(payload, resolved, location=name)
        if local_name(root.tag) == "dataSourcePackage":
            if not is_real_ddsp_root(root):
                raise UnsupportedInputError(
                    "DDSP root uses an unrecognized namespace",
                    code="reference_ddsp_unrecognized",
                    details={"namespace": namespace_uri(root.tag) or ""},
                )
            schema, evidence = _parse_real_root(root, name=name, limits=resolved)
            return SchemaArtifact(
                schema=schema,
                evidence=evidence,
                index=schema_index_from_schema(schema),
                name=name,
                payload_digest=digest_bytes(payload),
            )
    try:
        parsed = parse_synthetic_ddsp(payload, filename=name, limits=_parser_limits(resolved))
    except InvalidInputError:
        raise
    schema = parsed.schema
    schema_format = _synthetic_format(payload, schema)
    evidence = _fallback_evidence(schema, schema_format=schema_format)
    return SchemaArtifact(
        schema=schema,
        evidence=evidence,
        index=schema_index_from_schema(schema),
        name=name,
        payload_digest=digest_bytes(payload),
    )


__all__ = [
    "DDSP_NS",
    "XSD_NS",
    "XSE_NS",
    "DdspDataSectionEvidence",
    "DdspSchemaEvidence",
    "SchemaArtifact",
    "is_real_ddsp_root",
    "parse_ddsp_schema",
    "parse_real_ddsp",
    "schema_index_from_schema",
]
