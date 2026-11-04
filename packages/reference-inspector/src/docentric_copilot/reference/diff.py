"""ReferenceDiff v1.0 (REF-04).

The diff compares two read-only ReferenceGraphs (or two inspection bundles, or
two reference paths) and reports what was added, removed or changed. It is
deliberately a *comparison* contract, not Template IR:

* keys are stable across document hashes: they are derived from part, ProjectData
  element id, schema path and source name, never from the document SHA-256;
* **structural** changes are presence changes (added/removed) and location-only
  changes (part or paragraph). Count and part deltas are reported separately;
* **semantic** changes are binding-path, resolution-status, element-kind, source
  and data-type changes.

Nothing is executed and no expression is evaluated. Raw binding paths remain
untrusted reference data.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import Enum
from pathlib import Path
from typing import Final, Literal

from docentric_copilot.serialization import digest
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .graph import (
    EdgeType,
    GraphNode,
    GraphStatus,
    GraphSummary,
    NodeKind,
    ReferenceGraph,
    build_reference_graph,
)
from .inventory import SourceType
from .metadata import SchemaSource
from .report import ReferenceInspection, ReferenceReport, inspect_reference_bundle
from .safety import ReferenceLimits

DIFF_VERSION: Final[Literal["1.0"]] = "1.0"
READ_ONLY_NOTE: Final = (
    "read-only reference comparison; not Template IR, not compilable and not a runtime check"
)
RUNTIME_COMPATIBILITY: Final[Literal["not_tested"]] = "not_tested"

_MAX_ITEMS: Final = 20_000
_KIND_RANK: Final[dict[str, int]] = {
    "control": 0,
    "element": 1,
    "binding": 2,
    "source": 3,
    "schema_field": 4,
}
_CHANGE_RANK: Final[dict[str, int]] = {"added": 0, "removed": 1, "changed": 2}
_DIMENSION_RANK: Final[dict[str, int]] = {"structural": 0, "semantic": 1}
_SEMANTIC_FIELDS: Final[frozenset[str]] = frozenset(
    {"kind", "binding_path", "status", "source", "data_type", "collection"}
)
_STRUCTURAL_FIELDS: Final[frozenset[str]] = frozenset({"part", "paragraph_index"})


class DiffItemKind(str, Enum):
    """The reference object category a diff item describes."""

    CONTROL = "control"
    ELEMENT = "element"
    BINDING = "binding"
    SOURCE = "source"
    SCHEMA_FIELD = "schema_field"


class ChangeType(str, Enum):
    """Whether a stable key appeared, disappeared or persisted."""

    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"


class ChangeDimension(str, Enum):
    """Structural placement versus semantic meaning."""

    STRUCTURAL = "structural"
    SEMANTIC = "semantic"


class DiffSnapshot(BaseModel):
    """Before/after evidence for one item at one side of the comparison."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str | None = Field(default=None, max_length=80)
    binding_path: str | None = Field(default=None, max_length=512)
    status: GraphStatus
    part: str | None = Field(default=None, max_length=240)
    paragraph_index: int | None = None
    source: str | None = Field(default=None, max_length=120)
    data_type: str | None = Field(default=None, max_length=40)
    collection: bool | None = None


class DiffItem(BaseModel):
    """One added, removed or changed reference item with a stable key."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1, max_length=600)
    kind: DiffItemKind
    change: ChangeType
    dimension: ChangeDimension
    before: DiffSnapshot | None = None
    after: DiffSnapshot | None = None
    fields: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _check_sides(self) -> DiffItem:
        if self.change is ChangeType.ADDED:
            if self.before is not None or self.after is None:
                raise ValueError("an added item must have an after snapshot and no before")
        elif self.change is ChangeType.REMOVED:
            if self.before is None or self.after is not None:
                raise ValueError("a removed item must have a before snapshot and no after")
        elif self.before is None or self.after is None:
            raise ValueError("a changed item must have both before and after snapshots")
        return self


class DiffCountPair(BaseModel):
    """Before/after/delta triple for one structural count."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    left: int = Field(ge=0)
    right: int = Field(ge=0)
    delta: int


class DiffCounts(BaseModel):
    """Structural count deltas between left and right."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    controls: DiffCountPair
    elements: DiffCountPair
    sources: DiffCountPair
    schema_fields: DiffCountPair
    edges: DiffCountPair
    parts: DiffCountPair
    parts_added: list[str] = Field(default_factory=list, max_length=500)
    parts_removed: list[str] = Field(default_factory=list, max_length=500)


class DiffDimension(BaseModel):
    """The structural or semantic partition of the change list."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dimension: ChangeDimension
    added: int = Field(ge=0)
    removed: int = Field(ge=0)
    changed: int = Field(ge=0)
    total: int = Field(ge=0)
    by_kind: dict[str, int] = Field(default_factory=dict)
    keys: list[str] = Field(default_factory=list, max_length=_MAX_ITEMS)


class DiffSummary(BaseModel):
    """Aggregate change counts, independent of the structural/semantic split."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    added: int = Field(ge=0)
    removed: int = Field(ge=0)
    changed: int = Field(ge=0)
    total: int = Field(ge=0)
    ambiguous: int = Field(ge=0)
    structural: int = Field(ge=0)
    semantic: int = Field(ge=0)
    by_kind: dict[str, int] = Field(default_factory=dict)
    by_change: dict[str, int] = Field(default_factory=dict)
    status_transitions: dict[str, int] = Field(default_factory=dict)
    added_keys: list[str] = Field(default_factory=list, max_length=_MAX_ITEMS)
    removed_keys: list[str] = Field(default_factory=list, max_length=_MAX_ITEMS)
    changed_keys: list[str] = Field(default_factory=list, max_length=_MAX_ITEMS)


class CoverageDelta(BaseModel):
    """Coverage ratios before and after, with explicit deltas."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    left_edge_coverage: float = Field(ge=0.0, le=1.0)
    right_edge_coverage: float = Field(ge=0.0, le=1.0)
    edge_delta: float
    #: Primary (edge) coverage delta, duplicated for JSON consumers.
    delta: float

    left_control_coverage: float = Field(ge=0.0, le=1.0)
    right_control_coverage: float = Field(ge=0.0, le=1.0)
    control_delta: float


class UnresolvedDelta(BaseModel):
    """Unresolved-node counts and the stable keys that appeared or disappeared."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    left: int = Field(ge=0)
    right: int = Field(ge=0)
    delta: int
    added_keys: list[str] = Field(default_factory=list, max_length=_MAX_ITEMS)
    removed_keys: list[str] = Field(default_factory=list, max_length=_MAX_ITEMS)


class DiffSide(BaseModel):
    """One side of the comparison, without timestamps or absolute paths."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_type: SourceType
    source_name: str = Field(min_length=1, max_length=300)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    graph_version: Literal["1.0"] = "1.0"
    graph_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_source: SchemaSource = SchemaSource.NONE
    schema_ids: list[str] = Field(default_factory=list, max_length=50)
    summary: GraphSummary


class ReferenceDiff(BaseModel):
    """Read-only ReferenceDiff v1.0 contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    diff_version: Literal["1.0"] = DIFF_VERSION
    reference_version: Literal["1.0"] = "1.0"
    runtime_compatibility: Literal["not_tested"] = RUNTIME_COMPATIBILITY
    ir_kind: Literal["reference"] = "reference"
    compilable: Literal[False] = False
    note: str = Field(default=READ_ONLY_NOTE, max_length=300)
    left: DiffSide
    right: DiffSide
    items: list[DiffItem] = Field(default_factory=list, max_length=_MAX_ITEMS)
    structural: DiffDimension
    semantic: DiffDimension
    summary: DiffSummary
    counts: DiffCounts
    coverage_delta: CoverageDelta
    unresolved_delta: int
    unresolved: UnresolvedDelta
    diff_digest: str = Field(pattern=r"^[0-9a-f]{64}$", default="0" * 64)

    @property
    def added(self) -> list[DiffItem]:
        """Added items in canonical order (convenience view of ``items``)."""
        return [item for item in self.items if item.change is ChangeType.ADDED]

    @property
    def removed(self) -> list[DiffItem]:
        """Removed items in canonical order (convenience view of ``items``)."""
        return [item for item in self.items if item.change is ChangeType.REMOVED]

    @property
    def changed(self) -> list[DiffItem]:
        """Changed items in canonical order (convenience view of ``items``)."""
        return [item for item in self.items if item.change is ChangeType.CHANGED]

    @property
    def structural_items(self) -> list[DiffItem]:
        """Items classified as structural changes."""
        return [item for item in self.items if item.dimension is ChangeDimension.STRUCTURAL]

    @property
    def semantic_items(self) -> list[DiffItem]:
        """Items classified as semantic changes."""
        return [item for item in self.items if item.dimension is ChangeDimension.SEMANTIC]

    @property
    def changes(self) -> list[DiffItem]:
        """Alias for ``items`` used by report consumers."""
        return self.items


# --------------------------------------------------------------------------- #
# Stable keys and snapshots
# --------------------------------------------------------------------------- #
def _scope(graph: ReferenceGraph, node: GraphNode | None) -> str:
    """Prefix for multi-document sources; empty for a single document.

    A directory or AXPP can hold several DOCX payloads. In that case the file
    name is the only stable identity available before parsing; it is not used
    for the common one-document comparison so renaming a file does not relocate
    every key.
    """
    documents = {item.document_sha256 for item in graph.nodes if item.document_sha256}
    if len(documents) <= 1 or node is None:
        return ""
    name = (node.document_name or node.document_sha256 or "").casefold()
    return f"{name}|"


def _with_occurrences(pairs: Iterable[tuple[str, GraphNode]]) -> dict[str, str]:
    """Assign ``#n`` suffixes only when a base key is not unique."""
    grouped: dict[str, list[tuple[str, GraphNode]]] = {}
    for base, node in pairs:
        grouped.setdefault(base, []).append((base, node))
    result: dict[str, str] = {}
    for base, entries in grouped.items():
        if len(entries) == 1:
            result[entries[0][1].id] = base
            continue
        ordered = sorted(
            entries,
            key=lambda item: (
                item[1].document_sha256 or "",
                item[1].part or "",
                item[1].label,
                item[1].id,
            ),
        )
        for index, (_base, node) in enumerate(ordered, start=1):
            result[node.id] = f"{base}#{index}"
    return result


def _control_keys(graph: ReferenceGraph) -> dict[str, str]:
    pairs: list[tuple[str, GraphNode]] = []
    for node in graph.nodes:
        if node.kind is not NodeKind.CONTROL:
            continue
        identity = (
            node.element_id
            if node.element_id
            else f"p{node.paragraph_index if node.paragraph_index is not None else -1}"
            f":o{node.ordinal if node.ordinal is not None else -1}"
        )
        pairs.append((f"control:{_scope(graph, node)}{node.part or '-'}:{identity}", node))
    return _with_occurrences(pairs)


def _element_keys(graph: ReferenceGraph) -> dict[str, str]:
    pairs: list[tuple[str, GraphNode]] = []
    for node in graph.nodes:
        if node.kind is not NodeKind.ELEMENT:
            continue
        identity = node.element_id or node.label
        pairs.append((f"element:{_scope(graph, node)}{node.part or '-'}:{identity}", node))
    return _with_occurrences(pairs)


def _source_keys(graph: ReferenceGraph) -> dict[str, str]:
    pairs: list[tuple[str, GraphNode]] = []
    for node in graph.nodes:
        if node.kind is not NodeKind.SOURCE:
            continue
        pairs.append(
            (
                f"source:{_scope(graph, node)}{node.part or '-'}:{node.source_name or node.label}",
                node,
            )
        )
    return _with_occurrences(pairs)


def _schema_keys(graph: ReferenceGraph) -> dict[str, str]:
    pairs: list[tuple[str, GraphNode]] = []
    for node in graph.nodes:
        if node.kind is not NodeKind.SCHEMA_FIELD:
            continue
        path = node.schema_path or node.normalized_path or node.label
        pairs.append((f"schema_field:{path}", node))
    return _with_occurrences(pairs)


def _binding_keys(graph: ReferenceGraph) -> dict[str, str]:
    """One binding item per element with a data binding, keyed by element key."""
    return _binding_keys_from_nodes(graph, _element_keys(graph))


def _binding_keys_from_nodes(
    graph: ReferenceGraph, element_keys: Mapping[str, str]
) -> dict[str, str]:
    """One binding item per element with a data binding, keyed by element key."""
    nodes = {node.id: node for node in graph.nodes}
    keys: dict[str, str] = {}
    for node_id, key in element_keys.items():
        node = nodes.get(node_id)
        if node is None:
            continue
        if node.binding_path or node.source_name:
            keys[node_id] = f"binding:{key}"
    return keys


def _binding_path(node: GraphNode, schema_node: GraphNode | None) -> str | None:
    if schema_node is not None and schema_node.schema_path:
        return schema_node.schema_path
    return node.binding_path


def _snapshot(
    *,
    kind: str | None,
    binding_path: str | None,
    status: GraphStatus,
    part: str | None,
    paragraph_index: int | None,
    source: str | None,
    data_type: str | None,
    collection: bool | None,
) -> DiffSnapshot:
    return DiffSnapshot(
        kind=kind,
        binding_path=binding_path,
        status=status,
        part=part,
        paragraph_index=paragraph_index,
        source=source,
        data_type=data_type,
        collection=collection,
    )


def _snapshots(graph: ReferenceGraph) -> dict[str, tuple[DiffItemKind, DiffSnapshot]]:
    """Map every stable item key to its kind and snapshot."""
    nodes = {node.id: node for node in graph.nodes}
    control_keys = _control_keys(graph)
    element_keys = _element_keys(graph)
    source_keys = _source_keys(graph)
    schema_keys = _schema_keys(graph)
    binding_keys = _binding_keys(graph)
    bound_element: dict[str, GraphNode] = {}
    for edge in graph.edges:
        if edge.type is not EdgeType.BOUND_TO or not edge.source.startswith("control:"):
            continue
        target = nodes.get(edge.target)
        if target is not None and target.kind is NodeKind.ELEMENT:
            bound_element.setdefault(edge.source, target)
    nodes_by_id = {node.id: node for node in graph.nodes}
    schema_by_element: dict[str, GraphNode] = {}
    for edge in graph.edges:
        if edge.type is not EdgeType.RESOLVES_TO:
            continue
        target = nodes_by_id.get(edge.target)
        if target is not None:
            schema_by_element.setdefault(edge.source, target)
    snapshots: dict[str, tuple[DiffItemKind, DiffSnapshot]] = {}

    for node in graph.nodes:
        if node.kind is NodeKind.CONTROL:
            element = bound_element.get(node.id)
            schema_node = schema_by_element.get(element.id) if element is not None else None
            status = node.status
            if element is not None and element.status is not GraphStatus.RESOLVED:
                status = element.status
            snapshots[control_keys[node.id]] = (
                DiffItemKind.CONTROL,
                _snapshot(
                    kind=node.element_kind.value if node.element_kind else None,
                    binding_path=(
                        _binding_path(element, schema_node)
                        if element is not None
                        else node.binding_path
                    ),
                    status=status,
                    part=node.part,
                    paragraph_index=node.paragraph_index,
                    source=element.source_name if element is not None else None,
                    data_type=schema_node.data_type if schema_node is not None else None,
                    collection=schema_node.collection if schema_node is not None else None,
                ),
            )
        elif node.kind is NodeKind.ELEMENT:
            schema_node = schema_by_element.get(node.id)
            snapshots[element_keys[node.id]] = (
                DiffItemKind.ELEMENT,
                _snapshot(
                    kind=node.element_kind.value if node.element_kind else None,
                    binding_path=_binding_path(node, schema_node),
                    status=node.status,
                    part=node.part,
                    paragraph_index=None,
                    source=node.source_name,
                    data_type=schema_node.data_type if schema_node is not None else None,
                    collection=schema_node.collection if schema_node is not None else None,
                ),
            )
        elif node.kind is NodeKind.SOURCE:
            snapshots[source_keys[node.id]] = (
                DiffItemKind.SOURCE,
                _snapshot(
                    kind="source",
                    binding_path=None,
                    status=node.status,
                    part=node.part,
                    paragraph_index=None,
                    source=node.source_name,
                    data_type=None,
                    collection=None,
                ),
            )
        elif node.kind is NodeKind.SCHEMA_FIELD:
            snapshots[schema_keys[node.id]] = (
                DiffItemKind.SCHEMA_FIELD,
                _snapshot(
                    kind="schema_field",
                    binding_path=node.schema_path or node.normalized_path,
                    status=node.status,
                    part=None,
                    paragraph_index=None,
                    source=None,
                    data_type=node.data_type,
                    collection=node.collection,
                ),
            )

    for element_id, binding_key in binding_keys.items():
        node = nodes[element_id]
        schema_node = schema_by_element.get(element_id)
        snapshots[binding_key] = (
            DiffItemKind.BINDING,
            _snapshot(
                kind=node.element_kind.value if node.element_kind else None,
                binding_path=_binding_path(node, schema_node),
                status=node.status,
                part=node.part,
                paragraph_index=None,
                source=node.source_name,
                data_type=schema_node.data_type if schema_node is not None else None,
                collection=schema_node.collection if schema_node is not None else None,
            ),
        )
    return snapshots


# --------------------------------------------------------------------------- #
# Diff construction
# --------------------------------------------------------------------------- #
def _changed_fields(before: DiffSnapshot, after: DiffSnapshot) -> list[str]:
    return [
        field
        for field in sorted(DiffSnapshot.model_fields)
        if getattr(before, field) != getattr(after, field)
    ]


def _dimension_for_change(fields: Iterable[str]) -> ChangeDimension:
    changed = set(fields)
    return ChangeDimension.SEMANTIC if changed & _SEMANTIC_FIELDS else ChangeDimension.STRUCTURAL


def _status_transition(before: DiffSnapshot | None, after: DiffSnapshot | None) -> str | None:
    if before is None or after is None or before.status is after.status:
        return None
    return f"{before.status.value}->{after.status.value}"


def _item_sort_key(item: DiffItem) -> tuple[int, int, str, int]:
    return (
        _KIND_RANK.get(item.kind.value, 9),
        _CHANGE_RANK.get(item.change.value, 9),
        item.key,
        _DIMENSION_RANK.get(item.dimension.value, 9),
    )


def _partition(dimension: ChangeDimension, items: list[DiffItem]) -> DiffDimension:
    selected = [item for item in items if item.dimension is dimension]
    by_kind: dict[str, int] = {}
    for item in selected:
        by_kind[item.kind.value] = by_kind.get(item.kind.value, 0) + 1
    return DiffDimension(
        dimension=dimension,
        added=sum(1 for item in selected if item.change is ChangeType.ADDED),
        removed=sum(1 for item in selected if item.change is ChangeType.REMOVED),
        changed=sum(1 for item in selected if item.change is ChangeType.CHANGED),
        total=len(selected),
        by_kind=dict(sorted(by_kind.items())),
        keys=[item.key for item in selected],
    )


def _pair(left: int, right: int) -> DiffCountPair:
    return DiffCountPair(left=left, right=right, delta=right - left)


def _parts(graph: ReferenceGraph) -> set[str]:
    return {node.part for node in graph.nodes if node.part}


def _coverage(graph: ReferenceGraph) -> tuple[float, float]:
    summary = graph.summary
    edge_coverage = summary.edge_coverage_ratio
    control_coverage = (
        round(summary.controls_resolved / summary.controls_total, 4)
        if summary.controls_total
        else 0.0
    )
    return edge_coverage, control_coverage


def _key_map(graph: ReferenceGraph) -> dict[str, str]:
    keys: dict[str, str] = {}
    keys.update(_control_keys(graph))
    keys.update(_element_keys(graph))
    keys.update(_source_keys(graph))
    keys.update(_schema_keys(graph))
    return keys


def _unresolved_keys(graph: ReferenceGraph) -> list[str]:
    keys = _key_map(graph)
    result = []
    for item in graph.unresolved:
        key = keys.get(item.node_id)
        if key is None:
            key = f"{item.kind.value}:{item.node_id}"
        result.append(key)
    return sorted(set(result))


def _side(graph: ReferenceGraph) -> DiffSide:
    return DiffSide(
        source_type=graph.source_type,
        source_name=graph.source_name,
        source_sha256=graph.source_sha256,
        graph_digest=graph.graph_digest,
        schema_source=graph.schema_source,
        schema_ids=list(graph.schema_ids),
        summary=graph.summary,
    )


def diff_reference_graphs(left: ReferenceGraph, right: ReferenceGraph) -> ReferenceDiff:
    """Compare two read-only ReferenceGraphs deterministically."""
    left_snapshots = _snapshots(left)
    right_snapshots = _snapshots(right)
    all_keys = sorted(set(left_snapshots) | set(right_snapshots))
    items: list[DiffItem] = []
    for key in all_keys:
        before_entry = left_snapshots.get(key)
        after_entry = right_snapshots.get(key)
        if before_entry is None and after_entry is not None:
            items.append(
                DiffItem(
                    key=key,
                    kind=after_entry[0],
                    change=ChangeType.ADDED,
                    dimension=ChangeDimension.STRUCTURAL,
                    after=after_entry[1],
                )
            )
            continue
        if before_entry is not None and after_entry is None:
            items.append(
                DiffItem(
                    key=key,
                    kind=before_entry[0],
                    change=ChangeType.REMOVED,
                    dimension=ChangeDimension.STRUCTURAL,
                    before=before_entry[1],
                )
            )
            continue
        if before_entry is None or after_entry is None:
            continue
        if before_entry[0] is not after_entry[0]:
            # The same key cannot change item category; keep both sides visible
            # as an explicit removal plus addition.
            items.append(
                DiffItem(
                    key=key,
                    kind=before_entry[0],
                    change=ChangeType.REMOVED,
                    dimension=ChangeDimension.STRUCTURAL,
                    before=before_entry[1],
                )
            )
            items.append(
                DiffItem(
                    key=key,
                    kind=after_entry[0],
                    change=ChangeType.ADDED,
                    dimension=ChangeDimension.STRUCTURAL,
                    after=after_entry[1],
                )
            )
            continue
        fields = _changed_fields(before_entry[1], after_entry[1])
        if not fields:
            continue
        items.append(
            DiffItem(
                key=key,
                kind=after_entry[0],
                change=ChangeType.CHANGED,
                dimension=_dimension_for_change(fields),
                before=before_entry[1],
                after=after_entry[1],
                fields=fields,
            )
        )
    items.sort(key=_item_sort_key)
    items = items[:_MAX_ITEMS]

    structural = _partition(ChangeDimension.STRUCTURAL, items)
    semantic = _partition(ChangeDimension.SEMANTIC, items)
    by_kind: dict[str, int] = {}
    by_change = {change.value: 0 for change in ChangeType}
    transitions: dict[str, int] = {}
    ambiguous = 0
    for item in items:
        by_kind[item.kind.value] = by_kind.get(item.kind.value, 0) + 1
        by_change[item.change.value] += 1
        if item.change is ChangeType.CHANGED:
            transition = _status_transition(item.before, item.after)
            if transition:
                transitions[transition] = transitions.get(transition, 0) + 1
        if any(
            snapshot is not None and snapshot.status is GraphStatus.AMBIGUOUS
            for snapshot in (item.before, item.after)
        ):
            ambiguous += 1
    summary = DiffSummary(
        added=sum(1 for item in items if item.change is ChangeType.ADDED),
        removed=sum(1 for item in items if item.change is ChangeType.REMOVED),
        changed=sum(1 for item in items if item.change is ChangeType.CHANGED),
        total=len(items),
        ambiguous=ambiguous,
        structural=structural.total,
        semantic=semantic.total,
        by_kind=dict(sorted(by_kind.items())),
        by_change=dict(sorted(by_change.items())),
        status_transitions=dict(sorted(transitions.items())),
        added_keys=[item.key for item in items if item.change is ChangeType.ADDED],
        removed_keys=[item.key for item in items if item.change is ChangeType.REMOVED],
        changed_keys=[item.key for item in items if item.change is ChangeType.CHANGED],
    )
    left_summary = left.summary
    right_summary = right.summary
    left_edge_coverage, left_control_coverage = _coverage(left)
    right_edge_coverage, right_control_coverage = _coverage(right)
    left_parts = _parts(left)
    right_parts = _parts(right)
    left_unresolved = _unresolved_keys(left)
    right_unresolved = _unresolved_keys(right)
    unresolved = UnresolvedDelta(
        left=len(left_unresolved),
        right=len(right_unresolved),
        delta=len(right_unresolved) - len(left_unresolved),
        added_keys=sorted(set(right_unresolved) - set(left_unresolved)),
        removed_keys=sorted(set(left_unresolved) - set(right_unresolved)),
    )
    counts = DiffCounts(
        controls=_pair(left_summary.controls_total, right_summary.controls_total),
        elements=_pair(left_summary.elements_total, right_summary.elements_total),
        sources=_pair(left_summary.sources_total, right_summary.sources_total),
        schema_fields=_pair(left_summary.schema_fields_total, right_summary.schema_fields_total),
        edges=_pair(left_summary.edge_count, right_summary.edge_count),
        parts=_pair(len(left_parts), len(right_parts)),
        parts_added=sorted(right_parts - left_parts),
        parts_removed=sorted(left_parts - right_parts),
    )
    coverage = CoverageDelta(
        left_edge_coverage=left_edge_coverage,
        right_edge_coverage=right_edge_coverage,
        edge_delta=round(right_edge_coverage - left_edge_coverage, 4),
        delta=round(right_edge_coverage - left_edge_coverage, 4),
        left_control_coverage=left_control_coverage,
        right_control_coverage=right_control_coverage,
        control_delta=round(right_control_coverage - left_control_coverage, 4),
    )
    base = ReferenceDiff(
        left=_side(left),
        right=_side(right),
        items=items,
        structural=structural,
        semantic=semantic,
        summary=summary,
        counts=counts,
        coverage_delta=coverage,
        unresolved_delta=unresolved.delta,
        unresolved=unresolved,
    )
    diff_digest = digest(base.model_dump(mode="json", exclude={"diff_digest"}))
    return base.model_copy(update={"diff_digest": diff_digest})


ReferenceSource = ReferenceGraph | ReferenceInspection | ReferenceReport | str | Path


def _as_graph(
    source: ReferenceSource,
    *,
    ddsp_path: str | Path | None,
    limits: ReferenceLimits | None,
    max_depth: int,
) -> ReferenceGraph:
    if isinstance(source, ReferenceGraph):
        return source
    if isinstance(source, ReferenceInspection):
        return build_reference_graph(source.report, source.schemas)
    if isinstance(source, ReferenceReport):
        return build_reference_graph(source)
    if isinstance(source, str | Path):
        bundle = inspect_reference_bundle(
            source,
            limits=limits,
            max_depth=max_depth,
            ddsp_path=ddsp_path,
        )
        return build_reference_graph(bundle.report, bundle.schemas)
    raise TypeError(f"Unsupported reference diff input: {type(source).__name__}")


def build_reference_diff(
    left: ReferenceSource,
    right: ReferenceSource,
    *,
    ddsp: str | Path | None = None,
    ddsp_path: str | Path | None = None,
    left_ddsp: str | Path | None = None,
    right_ddsp: str | Path | None = None,
    limits: ReferenceLimits | None = None,
    max_depth: int = 1,
) -> ReferenceDiff:
    """Compare graphs, inspection bundles, reports or two reference paths.

    ``ddsp`` (or its ``ddsp_path`` alias) applies the same schema to both paths;
    ``left_ddsp``/``right_ddsp`` override it per side. Graph and bundle inputs
    already contain their schemas.
    """
    if ddsp is not None and ddsp_path is not None:
        raise ValueError("Provide either ddsp or ddsp_path, not both")
    shared_schema = ddsp if ddsp is not None else ddsp_path
    left_graph = _as_graph(
        left,
        ddsp_path=left_ddsp if left_ddsp is not None else shared_schema,
        limits=limits,
        max_depth=max_depth,
    )
    right_graph = _as_graph(
        right,
        ddsp_path=right_ddsp if right_ddsp is not None else shared_schema,
        limits=limits,
        max_depth=max_depth,
    )
    return diff_reference_graphs(left_graph, right_graph)


def diff_reference_paths(
    left: str | Path,
    right: str | Path,
    *,
    ddsp: str | Path | None = None,
    ddsp_path: str | Path | None = None,
    left_ddsp: str | Path | None = None,
    right_ddsp: str | Path | None = None,
    limits: ReferenceLimits | None = None,
    max_depth: int = 1,
) -> ReferenceDiff:
    """Path-only convenience wrapper around :func:`build_reference_diff`."""
    return build_reference_diff(
        left,
        right,
        ddsp=ddsp,
        ddsp_path=ddsp_path,
        left_ddsp=left_ddsp,
        right_ddsp=right_ddsp,
        limits=limits,
        max_depth=max_depth,
    )


def diff_json(diff: ReferenceDiff, *, indent: int = 2) -> str:
    """Deterministic JSON text used by the CLI and tests."""
    import json

    return (
        json.dumps(
            diff.model_dump(mode="json"),
            ensure_ascii=False,
            indent=indent,
            sort_keys=True,
        )
        + "\n"
    )


def reference_diff_json(diff: ReferenceDiff, *, indent: int = 2) -> str:
    """Alias with the explicit contract name used in documentation."""
    return diff_json(diff, indent=indent)


#: Short aliases used by callers that name the operation rather than the contract.
build_diff = build_reference_diff
diff_graphs = diff_reference_graphs


def diff_payload(diff: ReferenceDiff) -> Mapping[str, object]:
    """Small summary payload for callers that do not need the whole diff."""
    return {
        "diff_version": diff.diff_version,
        "added": diff.summary.added,
        "removed": diff.summary.removed,
        "changed": diff.summary.changed,
        "structural": diff.summary.structural,
        "semantic": diff.summary.semantic,
        "unresolved_delta": diff.unresolved_delta,
        "coverage_delta": diff.coverage_delta.edge_delta,
        "diff_digest": diff.diff_digest,
    }


__all__ = [
    "DIFF_VERSION",
    "READ_ONLY_NOTE",
    "RUNTIME_COMPATIBILITY",
    "ChangeDimension",
    "ChangeType",
    "CoverageDelta",
    "DiffCountPair",
    "DiffCounts",
    "DiffDimension",
    "DiffItem",
    "DiffItemKind",
    "DiffSide",
    "DiffSnapshot",
    "DiffSummary",
    "ReferenceDiff",
    "UnresolvedDelta",
    "build_diff",
    "build_reference_diff",
    "diff_graphs",
    "diff_json",
    "diff_payload",
    "diff_reference_graphs",
    "diff_reference_paths",
    "reference_diff_json",
]
