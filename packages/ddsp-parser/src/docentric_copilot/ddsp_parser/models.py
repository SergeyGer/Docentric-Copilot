"""Normalized schema model (FR-01).

The normalized schema is an internal, deterministic projection of whatever the
DDSP actually contains. It is *not* a claim about the proprietary DDSP layout:
the parser discovers structure and records the evidence it used.

Path convention: ``Section.Element.Child``. A node with ``collection=True``
describes **one item** of that collection through its children, e.g.
``MainData.QuotationLines.Description`` is a scalar of every line item.
"""

from __future__ import annotations

from typing import Any

from docentric_copilot.serialization import canonical_json, digest
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from .diagnostics import Diagnostic, Severity

JSONScalar = str | float | int | bool | None


class SchemaAttribute(BaseModel):
    """An XML attribute that can be bound like a leaf value."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=120)
    data_type: str = Field(default="string", max_length=20)
    sample_value: JSONScalar = None
    source: str | None = Field(default=None, max_length=400)


class SchemaNode(BaseModel):
    """One node of the normalized field tree."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    path: str = Field(min_length=1, max_length=512)
    data_type: str = Field(default="string", max_length=20)
    collection: bool = False
    required: bool = False
    source: str | None = Field(default=None, max_length=400)
    description: str | None = Field(default=None, max_length=500)
    sample_value: JSONScalar = None
    attributes: list[SchemaAttribute] = Field(default_factory=list, max_length=50)
    children: list[SchemaNode] = Field(default_factory=list, max_length=500)

    @property
    def is_scalar(self) -> bool:
        """True when the node holds a single value (no children, not a list)."""
        return not self.children and not self.collection

    def walk(self) -> list[SchemaNode]:
        nodes = [self]
        for child in self.children:
            nodes.extend(child.walk())
        return nodes


class SchemaSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,79}$")
    nodes: list[SchemaNode] = Field(default_factory=list, max_length=500)
    source: str | None = Field(default=None, max_length=400)


class SchemaStats(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_count: int = 0
    scalar_count: int = 0
    collection_count: int = 0
    attribute_count: int = 0
    max_depth: int = 0


class NormalizedSchema(BaseModel):
    """Deterministic, versioned projection of the source data contract."""

    model_config = ConfigDict(extra="forbid")

    schema_id: str = Field(min_length=1, max_length=120)
    source: str = "docentric-ax-ddsp"
    format_version: str | None = Field(default=None, max_length=40)
    container_format: str = Field(default="unknown", max_length=40)
    sections: list[SchemaSection] = Field(default_factory=list, max_length=20)
    diagnostics: list[Diagnostic] = Field(default_factory=list, max_length=200)
    sample_data_available: bool = False
    locales: list[str] = Field(default_factory=list, max_length=50)

    _index: dict[str, SchemaNode] = PrivateAttr(default_factory=dict)

    # ------------------------------------------------------------------ index
    def model_post_init(self, __context: Any) -> None:
        index: dict[str, SchemaNode] = {}
        for section in self.sections:
            for node in section.nodes:
                for item in node.walk():
                    index[item.path] = item
        self._index = index

    # ------------------------------------------------------------------- api
    def node(self, path: str) -> SchemaNode | None:
        return self._index.get(path)

    def has_path(self, path: str) -> bool:
        return path in self._index

    @property
    def paths(self) -> list[str]:
        return sorted(self._index)

    @property
    def section_names(self) -> list[str]:
        return [section.name for section in self.sections]

    def collections(self) -> list[SchemaNode]:
        return [self._index[path] for path in sorted(self._index) if self._index[path].collection]

    def scalars(self) -> list[SchemaNode]:
        return [self._index[path] for path in sorted(self._index) if not self._index[path].children]

    def section_of(self, path: str) -> SchemaSection | None:
        root = path.split(".", 1)[0]
        for section in self.sections:
            if section.name == root:
                return section
        return None

    def errors(self) -> list[Diagnostic]:
        return [item for item in self.diagnostics if item.severity is Severity.ERROR]

    def stats(self) -> SchemaStats:
        node_count = len(self._index)
        scalar_count = sum(1 for node in self._index.values() if not node.children)
        collection_count = sum(1 for node in self._index.values() if node.collection)
        attribute_count = sum(
            1 for node in self._index.values() for attribute in node.attributes if attribute.name
        )

        def depth(nodes: list[SchemaNode], level: int) -> int:
            if not nodes:
                return level
            return max(depth(node.children, level + 1) for node in nodes)

        max_depth = depth([node for section in self.sections for node in section.nodes], 0)
        return SchemaStats(
            node_count=node_count,
            scalar_count=scalar_count,
            collection_count=collection_count,
            attribute_count=attribute_count,
            max_depth=max_depth,
        )

    def canonical_json(self) -> str:
        return canonical_json(self)

    def digest(self) -> str:
        """Content digest of the schema (diagnostics excluded)."""
        payload = self.model_dump(mode="json")
        payload.pop("diagnostics", None)
        return digest(payload)

    def compact_fragment(self, max_nodes: int = 300) -> list[dict[str, Any]]:
        """Minimal, token-efficient schema projection for LLM prompts (5.3).

        Includes paths, kinds and collection flags only - never sample values,
        which may contain personal data.
        """
        rows: list[dict[str, Any]] = []
        for path in sorted(self._index):
            node = self._index[path]
            if node.children and not node.collection:
                continue
            rows.append(
                {
                    "path": node.path,
                    "type": node.data_type,
                    "collection": node.collection,
                    "required": node.required,
                }
            )
            if len(rows) >= max_nodes:
                break
        return rows


__all__ = [
    "NormalizedSchema",
    "SchemaAttribute",
    "SchemaNode",
    "SchemaSection",
    "SchemaStats",
]
