"""Sample-data extraction and schema inference from XML (FR-01).

Two jobs live here:

1. Convert a sample data document into a JSON tree that matches normalized
   schema paths, coercing values by the schema type.
2. When no XSD is present, infer a schema directly from the sample document.
   Inferred schemas are explicitly marked with the ``SCHEMA006`` diagnostic so
   that no caller mistakes them for a declared contract.
"""

from __future__ import annotations

import re
from typing import Any

from docentric_copilot.config import Limits
from lxml import etree

from .diagnostics import Diagnostic, DiagnosticCode, info, warning
from .models import NormalizedSchema, SchemaAttribute, SchemaNode, SchemaSection
from .safety import local_name
from .xsd import KNOWN_SECTIONS, _max_occurs

_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(T[0-9:.+\-Z]{2,})?$")
_BOOLEANS = {"true": True, "false": False, "1": True, "0": False, "yes": True, "no": False}
_IDENTIFIER = re.compile(r"[^A-Za-z0-9_]")
_MAX_SAMPLE_TEXT = 2_000


def _safe_identifier(name: str) -> str:
    candidate = _IDENTIFIER.sub("_", name).strip("_") or "Field"
    if not candidate[0].isalpha():
        candidate = f"F{candidate}"
    return candidate[:120]


def _element_value(element: etree._Element) -> Any:
    """Convert one XML element to a JSON-compatible value."""
    children = [child for child in element if isinstance(child.tag, str)]
    if not children:
        return (element.text or "").strip()
    grouped: dict[str, list[Any]] = {}
    for child in children:
        name = local_name(child.tag)
        grouped.setdefault(name, []).append(_element_value(child))
    result: dict[str, Any] = {}
    for name, values in grouped.items():
        result[_safe_identifier(name)] = values[0] if len(values) == 1 else values
    return result


def _element_attributes(element: etree._Element) -> list[SchemaAttribute]:
    return [
        SchemaAttribute(name=_safe_identifier(name), data_type="string", sample_value=value)
        for name, value in list(element.attrib.items())[:50]
    ]


# --------------------------------------------------------------------------- #
# Sample data extraction for an existing schema
# --------------------------------------------------------------------------- #


def extract_sample_data(
    root: etree._Element, section_names: list[str], limits: Limits
) -> tuple[dict[str, Any], list[Diagnostic]]:
    """Map a data document onto ``{section: tree}`` using detected sections."""
    diagnostics: list[Diagnostic] = []
    root_name = _safe_identifier(local_name(root.tag))
    if root_name in section_names:
        return {root_name: _element_value(root)}, diagnostics

    child_names = {
        _safe_identifier(local_name(child.tag)) for child in root if isinstance(child.tag, str)
    }
    matching = sorted(name for name in child_names if name in section_names)
    if matching:
        data: dict[str, Any] = {}
        for child in root:
            if not isinstance(child.tag, str):
                continue
            name = _safe_identifier(local_name(child.tag))
            if name in section_names:
                data[name] = _element_value(child)
        return data, diagnostics

    if len(section_names) == 1:
        diagnostics.append(
            info(
                DiagnosticCode.SAMPLE_SCHEMA_MISMATCH,
                f"Data root '{root_name}' was mapped to section '{section_names[0]}'",
            )
        )
        return {section_names[0]: _element_value(root)}, diagnostics

    diagnostics.append(
        warning(
            DiagnosticCode.SAMPLE_SCHEMA_MISMATCH,
            "Union of the data document does not match the declared sections: "
            f"{', '.join(section_names)}",
        )
    )
    return {}, diagnostics


def _coerce_scalar(value: Any, node: SchemaNode, diagnostics: list[Diagnostic]) -> Any:
    if not isinstance(value, str):
        return value
    expected = node.data_type
    if expected == "number":
        stripped = value.replace(" ", "").replace("\u00a0", "")
        if _NUMBER.match(stripped):
            return float(stripped) if "." in stripped else int(stripped)
        diagnostics.append(
            warning(
                DiagnosticCode.SAMPLE_SCHEMA_MISMATCH,
                f"Value of '{node.path}' is not numeric; kept as text",
                location=node.path,
            )
        )
        return value
    if expected == "boolean":
        lowered = value.strip().lower()
        if lowered in _BOOLEANS:
            return _BOOLEANS[lowered]
        diagnostics.append(
            warning(
                DiagnosticCode.SAMPLE_SCHEMA_MISMATCH,
                f"Value of '{node.path}' is not boolean; kept as text",
                location=node.path,
            )
        )
        return value
    if expected == "date":
        if _DATE.match(value.strip()):
            return value.strip()
        diagnostics.append(
            warning(
                DiagnosticCode.SAMPLE_SCHEMA_MISMATCH,
                f"Value of '{node.path}' is not an ISO date; kept as text",
                location=node.path,
            )
        )
        return value
    if len(value) > _MAX_SAMPLE_TEXT:
        diagnostics.append(
            info(
                DiagnosticCode.SAMPLE_VALUE_TRUNCATED,
                f"Sample value of '{node.path}' was truncated to {_MAX_SAMPLE_TEXT} characters",
                location=node.path,
            )
        )
        return value[:_MAX_SAMPLE_TEXT]
    return value


def coerce_sample_tree(
    data: Any, schema: NormalizedSchema, diagnostics: list[Diagnostic], path: str = ""
) -> Any:
    """Coerce every leaf of ``data`` according to the matching schema node."""
    if isinstance(data, list):
        return [coerce_sample_tree(item, schema, diagnostics, path) for item in data]
    if isinstance(data, dict):
        coerced: dict[str, Any] = {}
        for key, value in data.items():
            child_path = f"{path}.{key}" if path else str(key)
            node = schema.node(child_path)
            if node is not None and node.children and isinstance(value, str):
                diagnostics.append(
                    warning(
                        DiagnosticCode.SAMPLE_SCHEMA_MISMATCH,
                        f"Schema expects an object at '{child_path}' but the sample has text",
                        location=child_path,
                    )
                )
            child_value = coerce_sample_tree(value, schema, diagnostics, child_path)
            if node is not None and node.collection and not isinstance(child_value, list):
                # A collection with a single item is still a list: the renderer and
                # the repeat semantics must not depend on the sample cardinality.
                child_value = [child_value]
            coerced[key] = child_value
        return coerced
    node = schema.node(path) if path else None
    if node is None:
        return data
    return _coerce_scalar(data, node, diagnostics)


# --------------------------------------------------------------------------- #
# Schema inference without a declared XSD
# --------------------------------------------------------------------------- #


def _infer_scalar_type(values: list[str]) -> str:
    if not values:
        return "string"
    cleaned = [value.strip() for value in values if value.strip()]
    if not cleaned:
        return "string"
    if all(_NUMBER.match(value.replace(" ", "")) for value in cleaned):
        return "number"
    if all(value.lower() in {"true", "false", "yes", "no"} for value in cleaned):
        return "boolean"
    if all(_DATE.match(value) for value in cleaned):
        return "date"
    return "string"


class _Inference:
    def __init__(self, limits: Limits) -> None:
        self._limits = limits
        self._diagnostics: list[Diagnostic] = []
        self._nodes = 0

    @property
    def diagnostics(self) -> list[Diagnostic]:
        return self._diagnostics

    def nodes_for(self, element: etree._Element, parent_path: str, depth: int) -> list[SchemaNode]:
        grouped: dict[str, list[etree._Element]] = {}
        for child in element:
            if not isinstance(child.tag, str):
                continue
            grouped.setdefault(_safe_identifier(local_name(child.tag)), []).append(child)
        nodes: list[SchemaNode] = []
        for name in sorted(grouped):
            occurrences = grouped[name]
            self._nodes += 1
            if self._nodes > self._limits.max_schema_nodes:
                break
            path = f"{parent_path}.{name}"
            node = SchemaNode(
                name=name,
                path=path,
                collection=len(occurrences) > 1,
                required=len(occurrences) >= 1,
                source=f"sample:{path}",
                attributes=_element_attributes(occurrences[0]),
            )
            has_children = any(
                any(isinstance(child.tag, str) for child in occurrence)
                for occurrence in occurrences
            )
            if has_children:
                if depth + 1 > 32:
                    node.data_type = "any"
                    nodes.append(node)
                    continue
                node.children = self.nodes_for(occurrences[0], path, depth + 1)
                node.data_type = "collection" if node.collection else "object"
            else:
                texts = [(occurrence.text or "").strip() for occurrence in occurrences]
                node.data_type = _infer_scalar_type(texts)
                node.sample_value = texts[0] if texts else None
            nodes.append(node)
        return nodes


def infer_sections_from_sample(
    root: etree._Element, limits: Limits
) -> tuple[list[SchemaSection], list[Diagnostic]]:
    """Infer sections and nodes from a data document alone."""
    engine = _Inference(limits=limits)
    root_name = _safe_identifier(local_name(root.tag))
    child_names = {
        _safe_identifier(local_name(child.tag)) for child in root if isinstance(child.tag, str)
    }
    sections: list[SchemaSection] = []
    if root_name in KNOWN_SECTIONS:
        sections.append(
            SchemaSection(
                name=root_name,
                nodes=engine.nodes_for(root, root_name, depth=1),
                source=f"sample:element:{root_name}",
            )
        )
    elif child_names and child_names.issubset(set(KNOWN_SECTIONS)):
        for child in root:
            if not isinstance(child.tag, str):
                continue
            name = _safe_identifier(local_name(child.tag))
            sections.append(
                SchemaSection(
                    name=name,
                    nodes=engine.nodes_for(child, name, depth=1),
                    source=f"sample:element:{name}",
                )
            )
    else:
        sections.append(
            SchemaSection(
                name=root_name,
                nodes=engine.nodes_for(root, root_name, depth=1),
                source=f"sample:element:{root_name}",
            )
        )
    diagnostics = list(engine.diagnostics)
    diagnostics.append(
        info(
            DiagnosticCode.SCHEMA_INFERRED,
            "No XSD found; the schema was inferred from the sample document",
        )
    )
    return sections, diagnostics


__all__ = [
    "_max_occurs",
    "coerce_sample_tree",
    "extract_sample_data",
    "infer_sections_from_sample",
]
