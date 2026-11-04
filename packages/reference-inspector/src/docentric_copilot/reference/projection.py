"""Read-only Reference IR projection (REF-03).

The projection is a deliberately separate contract from Template IR 1.0:

* it keeps raw binding paths and OOXML locations as **reference data**;
* it is ``read-only`` and not compilable (``compilable: false``);
* it never weakens Template IR, never emits a compiler target and never claims
  Docentric runtime compatibility;
* ``importable`` is reserved but not emitted: v0.6 has no import mode, so every
  recognized element is projected as ``reference_only`` and unknown elements are
  preserved as ``unsupported`` instead of being dropped.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Final, Literal

from docentric_copilot.serialization import digest
from pydantic import BaseModel, ConfigDict, Field

from .docx_controls import ElementKind
from .graph import (
    EdgeType,
    GraphEdge,
    GraphNode,
    GraphStatus,
    NodeKind,
    ReferenceGraph,
)
from .inventory import PlatformHint, SourceType
from .metadata import SchemaSource
from .report import ReferenceDiagnostic

PROJECTION_VERSION: Final[Literal["1.0"]] = "1.0"
RUNTIME_COMPATIBILITY: Final[Literal["not_tested"]] = "not_tested"
PROJECTION_NOTE: Final = (
    "Read-only reference projection. This is not Template IR 1.0 and cannot be compiled."
)


class ReferenceCapability(str, Enum):
    """What the reference material can safely be used for in v0.6."""

    RECOGNIZED = "recognized"
    RESOLVED = "resolved"
    IMPORTABLE = "importable"
    REFERENCE_ONLY = "reference_only"
    UNSUPPORTED = "unsupported"


class SourceLocation(BaseModel):
    """OOXML location of one projected control."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    part: str = Field(min_length=1, max_length=240)
    ordinal: int = Field(ge=0)
    paragraph_index: int = Field(ge=-1)
    depth: int = Field(default=0, ge=0)


class ProjectionElement(BaseModel):
    """One content control in the read-only reference projection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=600)
    display_label: str = Field(min_length=1, max_length=200)
    kind: ElementKind
    binding_path: str | None = Field(default=None, max_length=512)
    status: GraphStatus
    capability: ReferenceCapability
    source_location: SourceLocation
    source_name: str | None = Field(default=None, max_length=120)
    schema_path: str | None = Field(default=None, max_length=512)
    data_type: str | None = Field(default=None, max_length=40)
    collection: bool = False
    reason: str | None = Field(default=None, max_length=240)


class ProjectionSection(BaseModel):
    """One DOCX document projected into ordered reference elements."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=300)
    document_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    elements: list[ProjectionElement] = Field(default_factory=list, max_length=20_000)


class ProjectionSummary(BaseModel):
    """Coverage and capability summary for the projected reference document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sections: int = Field(ge=0)
    elements: int = Field(ge=0)
    resolved: int = Field(ge=0)
    ambiguous: int = Field(ge=0)
    unknown: int = Field(ge=0)
    resolved_ratio: float = Field(ge=0.0, le=1.0)
    by_kind: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)
    by_capability: dict[str, int] = Field(default_factory=dict)
    lists: int = Field(ge=0)
    conditions: int = Field(ge=0)
    schema_fields: int = Field(ge=0)
    importable: int = Field(default=0, ge=0)


class ReferenceDocument(BaseModel):
    """Read-only Reference IR produced from a :class:`ReferenceGraph`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    projection_version: Literal["1.0"] = PROJECTION_VERSION
    reference_version: Literal["1.0"] = "1.0"
    graph_version: Literal["1.0"] = "1.0"
    runtime_compatibility: Literal["not_tested"] = RUNTIME_COMPATIBILITY
    ir_kind: Literal["reference"] = "reference"
    compilable: Literal[False] = False
    template_ir_compatible: Literal[False] = False
    note: str = Field(default=PROJECTION_NOTE, max_length=300)
    source_type: SourceType
    source_name: str = Field(min_length=1, max_length=300)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    platform: PlatformHint = PlatformHint.UNKNOWN
    schema_source: SchemaSource = SchemaSource.NONE
    schema_ids: list[str] = Field(default_factory=list, max_length=50)
    schema_sections: list[str] = Field(default_factory=list, max_length=50)
    graph_digest: str = Field(pattern=r"^[0-9a-f]{64}$", default="0" * 64)
    sections: list[ProjectionSection] = Field(default_factory=list, max_length=5_000)
    summary: ProjectionSummary
    diagnostics: list[ReferenceDiagnostic] = Field(default_factory=list, max_length=500)
    projection_digest: str = Field(pattern=r"^[0-9a-f]{64}$", default="0" * 64)


def _outgoing(graph: ReferenceGraph) -> dict[str, list[GraphEdge]]:
    grouped: dict[str, list[GraphEdge]] = {}
    for edge in graph.edges:
        grouped.setdefault(edge.source, []).append(edge)
    return grouped


def _capability(kind: ElementKind, status: GraphStatus) -> ReferenceCapability:
    if kind is ElementKind.UNKNOWN:
        return ReferenceCapability.UNSUPPORTED
    if status is GraphStatus.RESOLVED:
        # Import mode is not implemented in v0.6. Field/If/List/Image remain
        # candidates for a later ADR, but every current element is reference-only.
        return ReferenceCapability.REFERENCE_ONLY
    return ReferenceCapability.RECOGNIZED


def _display_label(
    control: GraphNode,
    element: GraphNode | None,
    kind: ElementKind,
) -> str:
    if (
        element is not None
        and kind is ElementKind.LABEL
        and element.label
        and element.label.casefold() not in {"label", "unknown"}
    ):
        return element.label
    for candidate in (control.label, element.label if element is not None else None):
        if candidate and candidate.strip():
            return candidate
    return f"{kind.value.replace('_', ' ').title()} {control.ordinal or 0}"


def _project_control(
    control: GraphNode,
    nodes: dict[str, GraphNode],
    outgoing: dict[str, list[GraphEdge]],
) -> ProjectionElement:
    edges = outgoing.get(control.id, [])
    bound = next(
        (
            edge
            for edge in edges
            if edge.type is EdgeType.BOUND_TO
            and (target := nodes.get(edge.target)) is not None
            and target.kind is NodeKind.ELEMENT
        ),
        None,
    )
    element = nodes.get(bound.target) if bound is not None else None
    kind = control.element_kind
    if (kind is None or kind is ElementKind.UNKNOWN) and element is not None:
        kind = element.element_kind or ElementKind.UNKNOWN
    kind = kind or ElementKind.UNKNOWN
    status = control.status
    if bound is not None:
        status = bound.status
    schema_node = None
    if element is not None:
        for edge in outgoing.get(element.id, []):
            if edge.type is EdgeType.RESOLVES_TO:
                schema_node = nodes.get(edge.target)
                if schema_node is not None:
                    break
    schema_path = schema_node.schema_path if schema_node is not None else None
    binding_path = (
        schema_path
        or (element.binding_path if element is not None else None)
        or (control.binding_path if control.binding_path else None)
    )
    return ProjectionElement(
        id=control.id,
        display_label=_display_label(control, element, kind),
        kind=kind,
        binding_path=binding_path,
        status=status,
        capability=_capability(kind, status),
        source_location=SourceLocation(
            part=control.part or "unknown",
            ordinal=control.ordinal or 0,
            paragraph_index=control.paragraph_index if control.paragraph_index is not None else -1,
            depth=control.depth or 0,
        ),
        source_name=(element.source_name if element is not None and element.source_name else None),
        schema_path=schema_path,
        data_type=schema_node.data_type if schema_node is not None else None,
        collection=bool(schema_node.collection) if schema_node is not None else False,
        reason=control.reason
        if control.status is not GraphStatus.RESOLVED
        else (bound.reason if bound is not None else None),
    )


def project_graph(graph: ReferenceGraph) -> ReferenceDocument:
    """Project a graph into the separate, read-only ReferenceDocument contract."""
    nodes = {node.id: node for node in graph.nodes}
    outgoing = _outgoing(graph)
    sections_by_document: dict[tuple[str, str], ProjectionSection] = {}
    for control in graph.nodes:
        if control.kind is not NodeKind.CONTROL:
            continue
        key = (control.document_sha256 or "", control.document_name or "document")
        section = sections_by_document.get(key)
        if section is None:
            section = ProjectionSection(
                name=control.document_name or "document",
                document_sha256=control.document_sha256,
                elements=[],
            )
            sections_by_document[key] = section
        section.elements.append(_project_control(control, nodes, outgoing))
    sections = [
        section.model_copy(
            update={
                "elements": sorted(
                    section.elements,
                    key=lambda item: (
                        item.source_location.part,
                        item.source_location.ordinal,
                        item.id,
                    ),
                )
            }
        )
        for _key, section in sorted(sections_by_document.items())
    ]
    by_kind: dict[str, int] = {}
    by_status: dict[str, int] = {status.value: 0 for status in GraphStatus}
    by_capability: dict[str, int] = {capability.value: 0 for capability in ReferenceCapability}
    all_elements = [element for section in sections for element in section.elements]
    for element in all_elements:
        by_kind[element.kind.value] = by_kind.get(element.kind.value, 0) + 1
        by_status[element.status.value] += 1
        by_capability[element.capability.value] += 1
    total = len(all_elements)
    resolved = by_status[GraphStatus.RESOLVED.value]
    summary = ProjectionSummary(
        sections=len(sections),
        elements=total,
        resolved=resolved,
        ambiguous=by_status[GraphStatus.AMBIGUOUS.value],
        unknown=by_status[GraphStatus.UNKNOWN.value],
        resolved_ratio=round(resolved / total, 4) if total else 0.0,
        by_kind=dict(sorted(by_kind.items())),
        by_status=dict(sorted(by_status.items())),
        by_capability=dict(sorted(by_capability.items())),
        lists=sum(
            1
            for node in graph.nodes
            if node.kind is NodeKind.ELEMENT and node.element_kind is ElementKind.LIST
        ),
        conditions=sum(
            1
            for node in graph.nodes
            if node.kind is NodeKind.ELEMENT and node.element_kind is ElementKind.IF
        ),
        schema_fields=sum(1 for node in graph.nodes if node.kind is NodeKind.SCHEMA_FIELD),
        importable=by_capability[ReferenceCapability.IMPORTABLE.value],
    )
    base = ReferenceDocument(
        source_type=graph.source_type,
        source_name=graph.source_name,
        source_sha256=graph.source_sha256,
        platform=graph.platform,
        schema_source=graph.schema_source,
        schema_ids=graph.schema_ids,
        schema_sections=graph.schema_sections,
        graph_digest=graph.graph_digest,
        sections=sections,
        summary=summary,
        diagnostics=graph.diagnostics,
    )
    projection_digest = digest(base.model_dump(mode="json", exclude={"projection_digest"}))
    return base.model_copy(update={"projection_digest": projection_digest})


def projection_json(document: ReferenceDocument, *, indent: int = 2) -> str:
    """Deterministic JSON text used by the CLI and tests."""
    return (
        json.dumps(
            document.model_dump(mode="json"),
            ensure_ascii=False,
            indent=indent,
            sort_keys=True,
        )
        + "\n"
    )


__all__ = [
    "PROJECTION_NOTE",
    "PROJECTION_VERSION",
    "ProjectionElement",
    "ProjectionSection",
    "ProjectionSummary",
    "ReferenceCapability",
    "ReferenceDocument",
    "SourceLocation",
    "project_graph",
    "projection_json",
]
