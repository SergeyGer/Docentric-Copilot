"""XSD to normalized schema conversion (FR-01).

Only constructs that map cleanly onto the IR are accepted. Anything else is
reported as a diagnostic instead of being guessed, because a wrong path is worse
than a missing feature (``correctness over plausibility``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

from docentric_copilot.config import Limits
from lxml import etree

from .diagnostics import Diagnostic, DiagnosticCode, error, info, warning
from .models import SchemaAttribute, SchemaNode, SchemaSection
from .safety import local_name

XS_NS: Final = "http://www.w3.org/2001/XMLSchema"
KNOWN_SECTIONS: Final = ("MainData", "Parameters", "GeneralData")
_IMAGE_NAME_HINT = re.compile(r"(logo|image|photo|picture|signature|thumbnail)", re.IGNORECASE)
_IDENTIFIER = re.compile(r"[^A-Za-z0-9_]")

_BUILTIN_TYPES: Final[dict[str, str]] = {
    "string": "string",
    "normalizedString": "string",
    "token": "string",
    "language": "string",
    "anyURI": "string",
    "ID": "string",
    "IDREF": "string",
    "NMTOKEN": "string",
    "Name": "string",
    "QName": "string",
    "decimal": "number",
    "float": "number",
    "double": "number",
    "integer": "number",
    "int": "number",
    "long": "number",
    "short": "number",
    "byte": "number",
    "nonNegativeInteger": "number",
    "positiveInteger": "number",
    "unsignedInt": "number",
    "unsignedLong": "number",
    "unsignedShort": "number",
    "unsignedByte": "number",
    "boolean": "boolean",
    "date": "date",
    "dateTime": "date",
    "time": "date",
    "duration": "string",
    "base64Binary": "image",
    "hexBinary": "string",
}


@dataclass
class XsdCatalog:
    """Named definitions collected from one ``xs:schema`` document."""

    roots: list[etree._Element] = field(default_factory=list)
    elements: dict[str, etree._Element] = field(default_factory=dict)
    complex_types: dict[str, etree._Element] = field(default_factory=dict)
    simple_types: dict[str, etree._Element] = field(default_factory=dict)
    attribute_groups: dict[str, etree._Element] = field(default_factory=dict)
    target_namespace: str | None = None

    def __bool__(self) -> bool:
        return bool(self.roots)


def _is_xs(node: etree._Element, name: str) -> bool:
    namespace = etree.QName(node).namespace if isinstance(node.tag, str) else None
    return namespace == XS_NS and local_name(node.tag) == name


def _iter_xs(node: etree._Element, name: str) -> list[etree._Element]:
    return [child for child in node if _is_xs(child, name)]


def _first_xs(node: etree._Element, name: str) -> etree._Element | None:
    for child in node:
        if _is_xs(child, name):
            return child
    return None


def collect_catalog(root: etree._Element) -> XsdCatalog | None:
    """Return the first ``xs:schema`` definition found in the document."""
    schema = root if _is_xs(root, "schema") else root.find(f".//{{{XS_NS}}}schema")
    if schema is None:
        return None
    catalog = XsdCatalog(target_namespace=schema.get("targetNamespace"))
    for child in schema:
        if not isinstance(child.tag, str):
            continue
        name = local_name(child.tag)
        declared = child.get("name")
        if name == "element" and declared:
            catalog.elements[declared] = child
            if declared and _declares_section(child):
                catalog.roots.append(child)
        elif name == "complexType" and declared:
            catalog.complex_types[declared] = child
        elif name == "simpleType" and declared:
            catalog.simple_types[declared] = child
        elif name == "attributeGroup" and declared:
            catalog.attribute_groups[declared] = child
    if not catalog.roots:
        # No explicit section roots: every top-level element is a candidate.
        catalog.roots = [catalog.elements[name] for name in sorted(catalog.elements)]
    return catalog


def _declares_section(element: etree._Element) -> bool:
    return (element.get("name") or "") in KNOWN_SECTIONS


def _local_type_name(value: str) -> str:
    return value.split(":", 1)[-1]


def _max_occurs(element: etree._Element) -> int | None:
    raw = element.get("maxOccurs", "1")
    if raw == "unbounded":
        return None  # unbounded
    try:
        return int(raw)
    except ValueError:
        return 1


def map_builtin_type(type_name: str, element_name: str) -> tuple[str, Diagnostic | None]:
    """Map an XSD builtin type to an IR data type, with heuristics documented."""
    local = _local_type_name(type_name)
    if local in _BUILTIN_TYPES:
        mapped = _BUILTIN_TYPES[local]
        if mapped == "string" and local == "anyURI" and _IMAGE_NAME_HINT.search(element_name):
            return "image", info(
                DiagnosticCode.IMAGE_HEURISTIC,
                f"Field '{element_name}' is treated as an image because of its name",
            )
        return mapped, None
    return "string", warning(
        DiagnosticCode.UNSUPPORTED_TYPE,
        f"Unsupported XSD type '{type_name}', falling back to string",
    )


@dataclass
class _Budget:
    limits: Limits
    nodes: int = 0
    exhausted: bool = False

    def consume(self) -> bool:
        self.nodes += 1
        if self.nodes > self.limits.max_schema_nodes:
            self.exhausted = True
        return not self.exhausted


class XsdToSchema:
    """Convert one XSD catalog into :class:`SchemaSection` objects."""

    def __init__(self, catalog: XsdCatalog, limits: Limits) -> None:
        self._catalog = catalog
        self._budget = _Budget(limits=limits)
        self._diagnostics: list[Diagnostic] = []
        self._stack: list[str] = []

    # ------------------------------------------------------------------ public
    def build(self) -> tuple[list[SchemaSection], list[Diagnostic]]:
        sections: list[SchemaSection] = []
        used_names: set[str] = set()
        for root_element in self._catalog.roots:
            if self._budget.exhausted:
                break
            name = self._section_name(root_element, used_names)
            nodes = self._children_of_element_type(root_element, name, depth=1, parent_path=name)
            if not nodes:
                # Section root may be a wrapper around known sections.
                nested = self._nested_sections(root_element, used_names)
                if nested:
                    sections.extend(nested)
                    continue
            sections.append(SchemaSection(name=name, nodes=nodes, source=f"xsd:element:{name}"))
            used_names.add(name)
        if self._budget.exhausted:
            self._diagnostics.append(
                error(
                    DiagnosticCode.SCHEMA_NODE_LIMIT,
                    f"Schema has more than {self._budget.limits.max_schema_nodes} nodes; "
                    "the remainder was ignored",
                )
            )
        return sections, self._diagnostics

    # ----------------------------------------------------------------- helpers
    def _section_name(self, element: etree._Element, used: set[str]) -> str:
        raw = element.get("name") or "Data"
        candidate = _IDENTIFIER.sub("_", raw).strip("_") or "Data"
        if not candidate[0].isalpha():
            candidate = f"S{candidate}"
        candidate = candidate[:80]
        if candidate not in used:
            return candidate
        index = 2
        while f"{candidate}_{index}" in used:
            index += 1
        return f"{candidate}_{index}"

    def _nested_sections(
        self, root_element: etree._Element, used_names: set[str]
    ) -> list[SchemaSection]:
        """Handle a single wrapper element that contains the known sections."""
        type_node = self._resolve_type_node(root_element)
        if type_node is None:
            return []
        child_names = [
            child.get("name") for child in self._element_children(type_node) if child.get("name")
        ]
        if not child_names or not set(child_names).issubset(set(KNOWN_SECTIONS)):
            return []
        sections: list[SchemaSection] = []
        for child in self._element_children(type_node):
            name = child.get("name") or ""
            if not self._budget.consume():
                break
            section_name = self._section_name(child, used_names)
            nodes = self._children_of_element_type(
                child, section_name, depth=1, parent_path=section_name
            )
            sections.append(
                SchemaSection(name=section_name, nodes=nodes, source=f"xsd:element:{name}")
            )
            used_names.add(section_name)
        if sections:
            self._diagnostics.append(
                info(
                    DiagnosticCode.SECTIONS_DETECTED,
                    "Sections discovered inside a wrapper element: "
                    + ", ".join(section.name for section in sections),
                )
            )
        return sections

    def _element_children(self, node: etree._Element) -> list[etree._Element]:
        """Return ``xs:element`` declarations inside any grouping construct."""
        found: list[etree._Element] = []
        for child in node:
            if not isinstance(child.tag, str):
                continue
            name = local_name(child.tag)
            if etree.QName(child).namespace != XS_NS:
                continue
            if name == "element":
                found.append(child)
            elif name in {
                "sequence",
                "choice",
                "all",
                "complexType",
                "complexContent",
                "extension",
            }:
                found.extend(self._element_children(child))
        return found

    def _resolve_type_node(self, element: etree._Element) -> etree._Element | None:
        """Return the complexType body that describes ``element``, if any."""
        inline = _first_xs(element, "complexType")
        if inline is not None:
            return inline
        type_name = element.get("type")
        if type_name:
            catalog_type = self._catalog.complex_types.get(_local_type_name(type_name))
            if catalog_type is not None:
                return catalog_type
        ref = element.get("ref")
        if ref:
            target = self._catalog.elements.get(_local_type_name(ref))
            if target is not None:
                return self._resolve_type_node(target)
        return None

    def _attributes_of(self, type_node: etree._Element) -> list[SchemaAttribute]:
        attributes: list[SchemaAttribute] = []
        candidates: list[etree._Element] = []
        for child in type_node:
            if not isinstance(child.tag, str):
                continue
            if _is_xs(child, "attribute"):
                candidates.append(child)
            elif _is_xs(child, "attributeGroup"):
                ref = child.get("ref")
                if ref:
                    group = self._catalog.attribute_groups.get(_local_type_name(ref))
                    if group is not None:
                        candidates.extend(_iter_xs(group, "attribute"))
            elif _is_xs(child, "complexContent"):
                extension = _first_xs(child, "extension")
                if extension is not None:
                    candidates.extend(self._attributes_of(extension))
        for candidate in candidates:
            name = candidate.get("name")
            if not name:
                continue
            data_type, diagnostic = map_builtin_type(candidate.get("type", "xs:string"), name)
            if diagnostic:
                self._diagnostics.append(diagnostic)
            attributes.append(SchemaAttribute(name=name, data_type=data_type))
        return attributes[:50]

    def _base_type_name(self, element: etree._Element) -> str | None:
        """Resolve ``type`` through inline/named simpleType definitions."""
        type_name = element.get("type")
        if type_name:
            local = _local_type_name(type_name)
            if local in self._catalog.simple_types:
                return self._simple_type_base(local, depth=0)
            return type_name
        inline_simple = _first_xs(element, "simpleType")
        if inline_simple is not None:
            restriction = _first_xs(inline_simple, "restriction")
            if restriction is not None:
                return restriction.get("base")
            union = _first_xs(inline_simple, "union")
            if union is not None:
                return union.get("memberTypes", "xs:string").split()[0]
        return None

    def _simple_type_base(self, name: str, depth: int) -> str | None:
        if depth > 8:
            return None
        definition = self._catalog.simple_types.get(name)
        if definition is None:
            return None
        restriction = _first_xs(definition, "restriction")
        if restriction is None:
            return None
        base = restriction.get("base")
        if not base:
            return None
        local = _local_type_name(base)
        if local in self._catalog.simple_types:
            return self._simple_type_base(local, depth + 1)
        return base

    def _children_of_element_type(
        self,
        element: etree._Element,
        section_name: str,
        *,
        depth: int,
        parent_path: str,
    ) -> list[SchemaNode]:
        type_node = self._resolve_type_node(element)
        if type_node is None:
            return []
        return self._build_children(
            type_node,
            parent_path=parent_path,
            depth=depth,
            section_name=section_name,
        )

    def _build_children(
        self,
        type_node: etree._Element,
        *,
        parent_path: str,
        depth: int,
        section_name: str,
    ) -> list[SchemaNode]:
        nodes: list[SchemaNode] = []
        for element in self._element_children(type_node):
            if not self._budget.consume():
                break
            node = self._build_node(
                element,
                parent_path=parent_path,
                depth=depth,
                section_name=section_name,
            )
            if node is None:
                continue
            nodes.append(node)
        return nodes

    def _build_node(
        self,
        element: etree._Element,
        *,
        parent_path: str,
        depth: int,
        section_name: str,
    ) -> SchemaNode | None:
        name = element.get("name") or _local_type_name(element.get("ref", "")) or ""
        if not name:
            self._diagnostics.append(
                warning(DiagnosticCode.UNSUPPORTED_TYPE, "An element without a name was skipped")
            )
            return None
        safe_name = _IDENTIFIER.sub("_", name).strip("_") or "Field"
        path = f"{parent_path}.{safe_name}"
        max_occurs = _max_occurs(element)
        collection = max_occurs is None or max_occurs > 1
        required = element.get("minOccurs", "0") not in {"0"}

        type_node = self._resolve_type_node(element)
        type_key = element.get("type") or ""
        recursion_key = f"{type_key}|{id(type_node)}|{safe_name}" if type_node is not None else None

        node = SchemaNode(
            name=safe_name,
            path=path,
            collection=collection,
            required=required,
            source=f"xsd:element:{name}",
        )

        if type_node is not None and depth < 32:
            if recursion_key and recursion_key in self._stack:
                self._diagnostics.append(
                    warning(
                        DiagnosticCode.RECURSIVE_TYPE,
                        f"Recursive type at '{path}' was not expanded",
                        location=path,
                    )
                )
                node.data_type = "any"
                return node
            self._stack.append(recursion_key or safe_name)
            try:
                node.children = self._build_children(
                    type_node,
                    parent_path=path,
                    depth=depth + 1,
                    section_name=section_name,
                )
            finally:
                self._stack.pop()
            node.attributes = self._attributes_of(type_node)
            if node.children:
                node.data_type = "collection" if collection else "object"
            else:
                node.data_type = "string"
            return node

        base_type = self._base_type_name(element) or "xs:string"
        data_type, diagnostic = map_builtin_type(base_type, name)
        if diagnostic:
            diagnostic = diagnostic.model_copy(update={"location": path})
            self._diagnostics.append(diagnostic)
        node.data_type = data_type
        return node


def build_sections_from_xsd(
    root: etree._Element, limits: Limits
) -> tuple[list[SchemaSection], list[Diagnostic]]:
    """Entry point: convert the first XSD document in ``root`` into sections."""
    catalog = collect_catalog(root)
    if catalog is None or not catalog.roots:
        return [], [error(DiagnosticCode.SCHEMA_NOT_FOUND, "No XSD element declarations found")]
    builder = XsdToSchema(catalog, limits)
    sections, diagnostics = builder.build()
    if not sections:
        diagnostics.append(
            error(DiagnosticCode.SCHEMA_NOT_FOUND, "XSD produced no usable sections")
        )
    return sections, diagnostics


__all__ = [
    "KNOWN_SECTIONS",
    "XS_NS",
    "XsdCatalog",
    "XsdToSchema",
    "build_sections_from_xsd",
    "collect_catalog",
    "map_builtin_type",
]
