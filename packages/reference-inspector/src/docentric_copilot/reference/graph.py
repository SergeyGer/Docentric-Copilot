"""ReferenceGraph v1.0 (REF-03).

The graph is a read-only, deterministic evidence structure built from the
inspector report (OOXML controls + Docentric ``ProjectData``) and, when
available, the normalized DDSP schema:

    control --bound_to--> element --resolves_to--> schema_field
                             |  \\
                             |   \\--iterates/condition--> element
                             \\--bound_to--> source (ProjectData part + data source)

Edges carry an explicit ``resolved | ambiguous | unknown`` status. Unresolved
material is never dropped: controls that cannot be joined, schema paths that do
not match and stale child references all remain visible as nodes, edges or
diagnostics with a reason.

This is **not** Template IR. Raw binding paths are stored as untrusted reference
data and are never evaluated.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from enum import Enum
from typing import Final, Literal

from docentric_copilot.ddsp_parser import NormalizedSchema
from docentric_copilot.serialization import digest
from pydantic import BaseModel, ConfigDict, Field

from .ddsp_real import SchemaArtifact, schema_index_from_schema
from .docx_controls import ElementKind
from .inventory import PlatformHint, SourceType
from .metadata import (
    PathStatus,
    ResolutionStatus,
    SchemaIndex,
    SchemaSource,
    SourceBinding,
    looks_like_expression,
)
from .report import (
    ControlEvidence,
    DocumentEvidence,
    ElementEvidence,
    ReferenceDiagnostic,
    ReferenceReport,
    Severity,
)

GRAPH_VERSION: Final[Literal["1.0"]] = "1.0"
RUNTIME_COMPATIBILITY: Final[Literal["not_tested"]] = "not_tested"
READ_ONLY_NOTE: Final = "read-only reference graph; not Template IR and not compilable"

_NODE_RANK: Final[dict[str, int]] = {
    "control": 0,
    "element": 1,
    "source": 2,
    "schema_field": 3,
}
_MAX_EVIDENCE_VALUE: Final = 200
_MAX_UNRESOLVED: Final = 500
_MAX_DIAGNOSTICS: Final = 500
_MAX_STRUCTURES: Final = 1_000
_STRUCTURE_KINDS: Final = {ElementKind.LIST, ElementKind.GROUP, ElementKind.IF}


class NodeKind(str, Enum):
    """ReferenceGraph node category."""

    CONTROL = "control"
    ELEMENT = "element"
    SOURCE = "source"
    SCHEMA_FIELD = "schema_field"


class EdgeType(str, Enum):
    """ReferenceGraph edge category."""

    BOUND_TO = "bound_to"
    RESOLVES_TO = "resolves_to"
    ITERATES = "iterates"
    CONDITION = "condition"


class GraphStatus(str, Enum):
    """Resolution status shared by nodes and edges."""

    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNKNOWN = "unknown"


class GraphNode(BaseModel):
    """One control, metadata element, data source or schema field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=600)
    kind: NodeKind
    label: str = Field(min_length=1, max_length=200)
    status: GraphStatus
    document_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    document_name: str | None = Field(default=None, max_length=300)
    part: str | None = Field(default=None, max_length=240)
    ordinal: int | None = Field(default=None, ge=0)
    paragraph_index: int | None = None
    depth: int | None = Field(default=None, ge=0)
    element_id: str | None = Field(default=None, pattern=r"^[0-9]+$", max_length=20)
    element_kind: ElementKind | None = None
    source_name: str | None = Field(default=None, max_length=120)
    binding_path: str | None = Field(default=None, max_length=512)
    normalized_path: str | None = Field(default=None, max_length=512)
    schema_path: str | None = Field(default=None, max_length=512)
    data_type: str | None = Field(default=None, max_length=40)
    collection: bool = False
    origin: str | None = Field(default=None, max_length=80)
    reason: str | None = Field(default=None, max_length=240)
    evidence: dict[str, str] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    """One typed, directed relation between two graph nodes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=900)
    type: EdgeType
    source: str = Field(min_length=1, max_length=600)
    target: str = Field(min_length=1, max_length=600)
    status: GraphStatus
    reason: str | None = Field(default=None, max_length=240)
    evidence: dict[str, str] = Field(default_factory=dict)


class GraphStructure(BaseModel):
    """A detected list, group or conditional with its child targets."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str = Field(min_length=1, max_length=600)
    kind: ElementKind
    label: str = Field(min_length=1, max_length=200)
    binding_path: str | None = Field(default=None, max_length=512)
    source_name: str | None = Field(default=None, max_length=120)
    target_count: int = Field(default=0, ge=0)
    status: GraphStatus
    detail: str | None = Field(default=None, max_length=240)


class GraphStructures(BaseModel):
    """All detected list/group and conditional structures."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    lists: list[GraphStructure] = Field(default_factory=list, max_length=_MAX_STRUCTURES)
    conditions: list[GraphStructure] = Field(default_factory=list, max_length=_MAX_STRUCTURES)


class GraphUnresolved(BaseModel):
    """An unresolved node with its explicit reason."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str = Field(min_length=1, max_length=600)
    kind: NodeKind
    label: str = Field(min_length=1, max_length=200)
    status: GraphStatus
    reason: str = Field(min_length=1, max_length=240)


class GraphSummary(BaseModel):
    """Deterministic aggregate counts with explicit denominators."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    by_node_kind: dict[str, int] = Field(default_factory=dict)
    by_node_status: dict[str, int] = Field(default_factory=dict)
    by_edge_type: dict[str, int] = Field(default_factory=dict)
    by_edge_status: dict[str, int] = Field(default_factory=dict)
    resolved_edges: int = Field(ge=0)
    ambiguous_edges: int = Field(ge=0)
    unknown_edges: int = Field(ge=0)
    edge_coverage_ratio: float = Field(ge=0.0, le=1.0)
    controls_total: int = Field(ge=0)
    controls_resolved: int = Field(ge=0)
    controls_ambiguous: int = Field(ge=0)
    controls_unknown: int = Field(ge=0)
    controls_bound: int = Field(ge=0)
    elements_total: int = Field(ge=0)
    sources_total: int = Field(ge=0)
    schema_fields_total: int = Field(ge=0)
    schema_fields_resolved: int = Field(ge=0)
    lists_detected: int = Field(ge=0)
    conditions_detected: int = Field(ge=0)
    unresolved_total: int = Field(ge=0)


class ReferenceGraph(BaseModel):
    """Read-only ReferenceGraph v1.0 contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    graph_version: Literal["1.0"] = GRAPH_VERSION
    reference_version: Literal["1.0"] = "1.0"
    runtime_compatibility: Literal["not_tested"] = RUNTIME_COMPATIBILITY
    ir_kind: Literal["reference"] = "reference"
    compilable: Literal[False] = False
    note: str = Field(default=READ_ONLY_NOTE, max_length=300)
    source_type: SourceType
    source_name: str = Field(min_length=1, max_length=300)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    platform: PlatformHint = PlatformHint.UNKNOWN
    schema_source: SchemaSource = SchemaSource.NONE
    schema_ids: list[str] = Field(default_factory=list, max_length=50)
    schema_sections: list[str] = Field(default_factory=list, max_length=50)
    schema_digests: list[str] = Field(default_factory=list, max_length=50)
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    structures: GraphStructures = Field(default_factory=GraphStructures)
    unresolved: list[GraphUnresolved] = Field(default_factory=list, max_length=_MAX_UNRESOLVED)
    summary: GraphSummary
    diagnostics: list[ReferenceDiagnostic] = Field(
        default_factory=list, max_length=_MAX_DIAGNOSTICS
    )
    graph_digest: str = Field(pattern=r"^[0-9a-f]{64}$", default="0" * 64)


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _bounded(value: str | None, limit: int = _MAX_EVIDENCE_VALUE) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    if not cleaned:
        return None
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…"


def _evidence(values: Mapping[str, str | int | bool | None]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key in sorted(values):
        value = values[key]
        if value is None:
            continue
        text = _bounded(str(value))
        if text:
            result[key] = text
    return result


def _short_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _status_from_resolution(status: ResolutionStatus) -> GraphStatus:
    if status is ResolutionStatus.RESOLVED:
        return GraphStatus.RESOLVED
    if status is ResolutionStatus.AMBIGUOUS:
        return GraphStatus.AMBIGUOUS
    return GraphStatus.UNKNOWN


def _status_from_path(status: PathStatus) -> GraphStatus:
    if status is PathStatus.MATCHED:
        return GraphStatus.RESOLVED
    if status is PathStatus.AMBIGUOUS:
        return GraphStatus.AMBIGUOUS
    return GraphStatus.UNKNOWN


def _control_label(control: ControlEvidence) -> str:
    for candidate in (control.alias, control.tag, control.placeholder):
        if candidate and candidate.strip():
            return _bounded(candidate) or f"Control {control.ordinal}"
    return f"Control {control.ordinal}"


def _element_label(element: ElementEvidence) -> str:
    for candidate in (
        element.properties.get("LabelName"),
        element.properties.get("LabelCode"),
        element.properties.get("DataXPath"),
    ):
        if candidate and candidate.strip():
            return _bounded(candidate) or element.element_type
    return element.element_type


def _element_schema_key(element: ElementEvidence) -> tuple[str, str, str]:
    binding = element.effective_binding or element.source_binding
    source = binding.source if binding is not None and binding.source else ""
    path = binding.path if binding is not None and binding.path else ""
    return (element.element_type.casefold(), source, path)


def _schema_value(
    schema: NormalizedSchema,
    schema_path: str,
) -> tuple[str | None, bool, str | None, bool]:
    """Return ``(data_type, collection, description, exists)`` for a path."""
    node = schema.node(schema_path)
    if node is not None:
        return node.data_type, node.collection, node.description, True
    if ".@" in schema_path:
        parent_path, attribute_name = schema_path.rsplit(".", 1)
        parent = schema.node(parent_path)
        if parent is not None:
            for attribute in parent.attributes:
                if f"@{attribute.name}" == attribute_name:
                    return attribute.data_type, False, None, True
    return None, False, None, False


def _artifact_schema(
    artifact: SchemaArtifact,
) -> tuple[NormalizedSchema, SchemaIndex, str, str]:
    return artifact.schema, artifact.index, artifact.schema.schema_id, artifact.schema.digest()


def _index_from_schema(schema: NormalizedSchema) -> SchemaIndex:
    return schema_index_from_schema(schema)


class _DocContext:
    """Graph-building state for one distinct DOCX payload."""

    def __init__(
        self,
        document: DocumentEvidence,
        *,
        schema: NormalizedSchema | None,
        index: SchemaIndex | None,
        schema_id: str | None,
        schema_digest: str | None,
    ) -> None:
        self.document = document
        self.schema = schema
        self.index = index
        self.schema_id = schema_id
        self.schema_digest = schema_digest
        self.nodes: dict[str, GraphNode] = {}
        self.edges: dict[str, GraphEdge] = {}
        self.unresolved: dict[str, GraphUnresolved] = {}
        self.diagnostics: list[ReferenceDiagnostic] = []
        self.records: dict[str, list[GraphNode]] = {}
        self.record_evidence: dict[str, ElementEvidence] = {}
        self.control_nodes: list[GraphNode] = []
        self.structures: list[GraphStructure] = []
        self.structure_targets: dict[str, int] = {}

    # ---------------------------------------------------------------- nodes
    def add_node(self, node: GraphNode) -> None:
        self.nodes.setdefault(node.id, node)

    def add_edge(
        self,
        edge_type: EdgeType,
        source: str,
        target: str,
        status: GraphStatus,
        *,
        reason: str | None = None,
        evidence: Mapping[str, str | int | bool | None] | None = None,
    ) -> None:
        edge_id = f"{edge_type.value}:{source}->{target}"
        self.edges.setdefault(
            edge_id,
            GraphEdge(
                id=edge_id,
                type=edge_type,
                source=source,
                target=target,
                status=status,
                reason=_bounded(reason, 240),
                evidence=_evidence(evidence or {}),
            ),
        )

    def unresolved_node(self, node: GraphNode, reason: str) -> None:
        current = self.nodes.get(node.id, node)
        self.unresolved.setdefault(
            node.id,
            GraphUnresolved(
                node_id=current.id,
                kind=current.kind,
                label=current.label,
                status=current.status,
                reason=_bounded(reason, 240) or "unresolved",
            ),
        )

    # ------------------------------------------------------------- controls
    def build_controls(self) -> None:
        for control in sorted(
            self.document.controls,
            key=lambda item: (_part_rank(item.part), item.part, item.ordinal),
        ):
            node_id = f"control:{self.document.sha256}:{control.part}:{control.ordinal}"
            status = _status_from_resolution(control.resolution.status)
            node = GraphNode(
                id=node_id,
                kind=NodeKind.CONTROL,
                label=_control_label(control),
                status=status,
                document_sha256=self.document.sha256,
                document_name=self.document.filename,
                part=control.part,
                ordinal=control.ordinal,
                paragraph_index=control.paragraph_index,
                depth=control.depth,
                element_kind=control.element_kind,
                element_id=control.resolution.element_id_unsigned,
                binding_path=control.resolution.source_binding.path
                if control.resolution.source_binding
                else control.data_binding.xpath,
                origin="ooxml",
                reason=None
                if status is GraphStatus.RESOLVED
                else control.resolution.link_status.value,
                evidence=_evidence(
                    {
                        "story": control.story.value,
                        "classification": control.classification.value,
                        "sdt_id_signed": control.sdt_id_signed,
                        "control_type": control.control_type.value,
                        "link_status": control.resolution.link_status.value,
                        "path_status": control.resolution.path_status.value,
                        "diagnostics": ",".join(control.resolution.diagnostic_codes),
                    }
                ),
            )
            self.add_node(node)
            self.control_nodes.append(node)
            target, target_status, reason = self._control_target(control)
            if target is None:
                self.unresolved_node(
                    node,
                    f"{control.resolution.link_status.value}:"
                    + ",".join(control.resolution.diagnostic_codes or ["no_element"]),
                )
                self.diagnostics.append(
                    ReferenceDiagnostic(
                        code="graph_control_unresolved",
                        severity=Severity.WARNING,
                        message=(
                            f"{self.document.filename}: control {control.ordinal} in "
                            f"{control.part} has no metadata element target"
                        ),
                        document_sha256=self.document.sha256,
                        part=control.part,
                        ordinal=control.ordinal,
                        details=_evidence(
                            {
                                "link_status": control.resolution.link_status.value,
                                "reasons": ",".join(control.resolution.diagnostic_codes),
                                "sdt_id": control.sdt_id_signed,
                            }
                        ),
                    )
                )
                continue
            self.add_edge(
                EdgeType.BOUND_TO,
                node.id,
                target.id,
                target_status,
                reason=reason,
                evidence={
                    "sdt_id_signed": control.sdt_id_signed,
                    "element_id": control.resolution.element_id_unsigned,
                    "link_status": control.resolution.link_status.value,
                    "path_status": control.resolution.path_status.value,
                },
            )

    def _control_target(
        self, control: ControlEvidence
    ) -> tuple[GraphNode | None, GraphStatus, str | None]:
        element_id = control.resolution.element_id_unsigned
        if element_id is None:
            return None, GraphStatus.UNKNOWN, control.resolution.link_status.value
        candidates = self.records.get(element_id, [])
        if not candidates:
            return None, GraphStatus.UNKNOWN, control.resolution.link_status.value
        status = _status_from_resolution(control.resolution.status)
        if len(candidates) == 1:
            return candidates[0], status, None
        # Prefer the candidate whose metadata matches the resolution evidence.
        binding = control.resolution.source_binding
        matches = [
            candidate
            for candidate in candidates
            if self._record_matches(candidate, control.resolution.element_type, binding)
        ]
        if len(matches) == 1:
            return matches[0], status, "duplicate_element_id_shared_metadata"
        return candidates[0], GraphStatus.AMBIGUOUS, "duplicate_element_id_collision"

    def _record_matches(
        self,
        node: GraphNode,
        element_type: str | None,
        binding: object,
    ) -> bool:
        evidence = self.record_evidence.get(node.id)
        if evidence is None:
            return False
        if element_type and evidence.element_type.casefold() != element_type.casefold():
            return False
        if binding is None:
            return True
        return repr(evidence.effective_binding or evidence.source_binding) == repr(binding)

    # -------------------------------------------------------------- elements
    def build_elements(self) -> None:
        counts: dict[tuple[str, str], int] = {}
        for element in sorted(
            self.document.metadata_elements,
            key=lambda item: (
                item.project_data_part,
                int(item.element_id_unsigned),
                _element_schema_key(item),
            ),
        ):
            key = (element.project_data_part, element.element_id_unsigned)
            occurrence = counts.get(key, 0)
            counts[key] = occurrence + 1
            suffix = "" if occurrence == 0 else f"#{occurrence}"
            node_id = (
                f"element:{self.document.sha256}:{element.project_data_part}:"
                f"{element.element_id_unsigned}{suffix}"
            )
            binding, binding_notes = self._effective(element)
            status = GraphStatus.RESOLVED
            node = GraphNode(
                id=node_id,
                kind=NodeKind.ELEMENT,
                label=_element_label(element),
                status=status,
                document_sha256=self.document.sha256,
                document_name=self.document.filename,
                part=element.project_data_part,
                element_id=element.element_id_unsigned,
                element_kind=element.element_kind,
                source_name=binding.source if binding is not None else None,
                binding_path=binding.path if binding is not None else None,
                origin="project_data",
                evidence=_evidence(
                    {
                        "element_type": element.element_type,
                        "occurrence": occurrence,
                        "binding_notes": ",".join(binding_notes),
                        "children": len(element.child_element_ids),
                        "attributes": ",".join(sorted(element.attributes)[:10]),
                        "properties": ",".join(sorted(element.properties)[:10]),
                    }
                ),
            )
            data_path = element.properties.get("DataXPath")
            if binding is None and data_path:
                node = node.model_copy(
                    update={
                        "binding_path": data_path,
                        "status": GraphStatus.UNKNOWN,
                        "reason": "label_data_section_unresolved",
                    }
                )
                self.unresolved_node(node, "label_data_section_unresolved")
            self.add_node(node)
            self.records.setdefault(element.element_id_unsigned, []).append(node)
            self.record_evidence[node.id] = element
            self._build_source(node, element, binding, binding_notes)
            self._build_schema_target(node, element, binding)

    def _effective(self, element: ElementEvidence) -> tuple[SourceBinding | None, list[str]]:
        if element.effective_binding is not None:
            return element.effective_binding, element.binding_notes
        return element.source_binding, element.binding_notes

    # ---------------------------------------------------------------- source
    def _build_source(
        self,
        node: GraphNode,
        element: ElementEvidence,
        binding: object,
        binding_notes: list[str],
    ) -> None:
        source_name = getattr(binding, "source", None)
        if not source_name or source_name == ".":
            if binding is not None and getattr(binding, "path", None):
                self._mark_unknown(
                    node,
                    "binding_source_unresolved" if binding_notes else "binding_scope_relative",
                )
            return
        source_id = f"source:{self.document.sha256}:{element.project_data_part}:{_bounded(source_name, 120)}"
        source_node = GraphNode(
            id=source_id,
            kind=NodeKind.SOURCE,
            label=_bounded(source_name, 120) or "source",
            status=GraphStatus.RESOLVED,
            document_sha256=self.document.sha256,
            document_name=self.document.filename,
            part=element.project_data_part,
            source_name=source_name,
            origin="project_data_source",
            evidence=_evidence({"project_data_part": element.project_data_part}),
        )
        self.add_node(source_node)
        self.add_edge(
            EdgeType.BOUND_TO,
            node.id,
            source_node.id,
            GraphStatus.RESOLVED,
            evidence={"source": source_name},
        )

    # ----------------------------------------------------------- schema field
    def _build_schema_target(
        self,
        node: GraphNode,
        element: ElementEvidence,
        binding: object,
    ) -> None:
        path = getattr(binding, "path", None)
        source = getattr(binding, "source", None)
        if not path:
            return
        if self.schema is None or self.index is None or self.schema_id is None:
            return
        if looks_like_expression(path):
            self._mark_unknown(node, "binding_expression_not_validated")
            self.diagnostics.append(
                ReferenceDiagnostic(
                    code="graph_binding_expression_not_validated",
                    severity=Severity.INFO,
                    message=(
                        f"{self.document.filename}: element {node.element_id} has an "
                        "expression binding; it was not evaluated"
                    ),
                    document_sha256=self.document.sha256,
                    part=node.part,
                    details=_evidence({"path": path}),
                )
            )
            return
        match = self.index.match(source, path)
        if match.status is PathStatus.MATCHED and match.normalized_path:
            data_type, collection, description, exists = _schema_value(
                self.schema, match.normalized_path
            )
            schema_node_id = self._schema_node_id(match.normalized_path)
            schema_node = GraphNode(
                id=schema_node_id,
                kind=NodeKind.SCHEMA_FIELD,
                label=_bounded(description or match.normalized_path.rsplit(".", 1)[-1], 200)
                or match.normalized_path,
                status=GraphStatus.RESOLVED if exists else GraphStatus.UNKNOWN,
                schema_path=match.normalized_path,
                normalized_path=match.normalized_path,
                data_type=data_type,
                collection=collection,
                origin="ddsp",
                reason=None if exists else "schema_node_missing",
                evidence=_evidence(
                    {"schema_id": self.schema_id, "schema_path": match.normalized_path}
                ),
            )
            self.add_node(schema_node)
            if not exists:
                self._mark_unknown(node, "schema_node_missing")
            status = GraphStatus.RESOLVED if exists else GraphStatus.UNKNOWN
            self.add_edge(
                EdgeType.RESOLVES_TO,
                node.id,
                schema_node.id,
                status,
                reason=None if exists else "schema_node_missing",
                evidence={
                    "source": source,
                    "raw_path": path,
                    "normalized_path": match.normalized_path,
                },
            )
            if node.status is GraphStatus.RESOLVED and status is GraphStatus.UNKNOWN:
                self._replace_status(node.id, GraphStatus.UNKNOWN)
            return

        if match.status is PathStatus.AMBIGUOUS:
            placeholder = self._schema_placeholder(path, source, "ambiguous")
            self.add_edge(
                EdgeType.RESOLVES_TO,
                node.id,
                placeholder.id,
                GraphStatus.AMBIGUOUS,
                reason="binding_path_ambiguous",
                evidence={"source": source, "raw_path": path},
            )
            self._replace_status(node.id, GraphStatus.AMBIGUOUS)
            self.unresolved_node(node, "binding_path_ambiguous")
            self.diagnostics.append(
                ReferenceDiagnostic(
                    code="graph_schema_ambiguous",
                    severity=Severity.WARNING,
                    message=(
                        f"{self.document.filename}: binding of element {node.element_id} "
                        "matches more than one schema path"
                    ),
                    document_sha256=self.document.sha256,
                    part=node.part,
                    details=_evidence({"source": source, "path": path}),
                )
            )
            return
        reason = (
            "binding_section_missing"
            if match.status is PathStatus.SECTION_MISSING
            else "binding_path_unknown"
        )
        placeholder = self._schema_placeholder(path, source, "unknown")
        self.add_edge(
            EdgeType.RESOLVES_TO,
            node.id,
            placeholder.id,
            GraphStatus.UNKNOWN,
            reason=reason,
            evidence={"source": source, "raw_path": path},
        )
        self._mark_unknown(node, reason)
        self.diagnostics.append(
            ReferenceDiagnostic(
                code="graph_schema_unknown",
                severity=Severity.WARNING,
                message=(
                    f"{self.document.filename}: binding of element {node.element_id} "
                    f"does not resolve ({reason})"
                ),
                document_sha256=self.document.sha256,
                part=node.part,
                details=_evidence({"source": source, "path": path, "reason": reason}),
            )
        )

    def _schema_node_id(self, path: str) -> str:
        digest_value = self.schema_digest or "0" * 64
        return f"schema:{digest_value[:16]}:{path}"

    def _schema_placeholder(self, path: str, source: str | None, status: str) -> GraphNode:
        digest_value = self.schema_digest or "0" * 64
        node_id = f"schema:{digest_value[:16]}:unresolved:{hashlib.sha256(path.encode()).hexdigest()[:12]}"
        graph_status = GraphStatus.AMBIGUOUS if status == "ambiguous" else GraphStatus.UNKNOWN
        node = GraphNode(
            id=node_id,
            kind=NodeKind.SCHEMA_FIELD,
            label=_bounded(path, 200) or path,
            status=graph_status,
            normalized_path=path,
            schema_path=path,
            origin="binding_reference_only",
            reason=status,
            evidence=_evidence(
                {
                    "raw_path": path,
                    "source": source,
                    "schema_id": self.schema_id,
                }
            ),
        )
        self.add_node(node)
        return node

    def _mark_unknown(self, node: GraphNode, reason: str) -> None:
        self._replace_status(node.id, GraphStatus.UNKNOWN)
        self.unresolved_node(node, reason)

    def _replace_status(self, node_id: str, status: GraphStatus) -> None:
        node = self.nodes.get(node_id)
        if node is None or node.status is status:
            return
        updated = node.model_copy(update={"status": status, "reason": node.reason or status.value})
        self.nodes[node_id] = updated
        for index, candidate in enumerate(self.control_nodes):
            if candidate.id == node_id:
                self.control_nodes[index] = updated
                break
        for records in self.records.values():
            for index, candidate in enumerate(records):
                if candidate.id == node_id:
                    records[index] = updated
                    break

    # ------------------------------------------------------ structures/edges
    def build_structure_edges(self) -> None:
        candidate_edges: list[
            tuple[EdgeType, str, GraphNode, GraphStatus, str | None, dict[str, str]]
        ] = []
        for node_id in sorted(self.records):
            for parent in self.records[node_id]:
                evidence = self.record_evidence.get(parent.id)
                if evidence is None or evidence.element_kind not in _STRUCTURE_KINDS:
                    continue
                edge_type = (
                    EdgeType.CONDITION
                    if evidence.element_kind is ElementKind.IF
                    else EdgeType.ITERATES
                )
                condition_binding = evidence.effective_binding or evidence.source_binding
                condition = condition_binding if evidence.element_kind is ElementKind.IF else None
                structure_status = (
                    GraphStatus.UNKNOWN
                    if parent.status is GraphStatus.UNKNOWN
                    else GraphStatus.AMBIGUOUS
                    if parent.status is GraphStatus.AMBIGUOUS
                    else GraphStatus.RESOLVED
                )
                targets = 0
                for child_id in evidence.child_element_ids:
                    child_candidates = self.records.get(child_id, [])
                    if not child_candidates:
                        placeholder = self._missing_element_node(evidence, child_id)
                        target = placeholder
                        status = GraphStatus.UNKNOWN
                    else:
                        target = child_candidates[0]
                        status = GraphStatus.RESOLVED
                        if len(child_candidates) > 1:
                            status = GraphStatus.AMBIGUOUS
                    targets += 1
                    if status is not GraphStatus.RESOLVED:
                        structure_status = (
                            GraphStatus.AMBIGUOUS
                            if status is GraphStatus.AMBIGUOUS
                            else GraphStatus.UNKNOWN
                        )
                    candidate_edges.append(
                        (
                            edge_type,
                            parent.id,
                            target,
                            status,
                            None
                            if status is GraphStatus.RESOLVED
                            else "child_element_missing"
                            if status is GraphStatus.UNKNOWN
                            else "duplicate_element_id",
                            {
                                "parent_kind": evidence.element_kind.value,
                                "raw_path": (
                                    condition.path
                                    if condition is not None
                                    else evidence.properties.get("DataXPath")
                                    or condition_binding.path
                                    if condition_binding is not None
                                    else ""
                                )
                                or "",
                                "child_id": child_id,
                            },
                        )
                    )
                structure = GraphStructure(
                    node_id=parent.id,
                    kind=evidence.element_kind,
                    label=parent.label,
                    binding_path=condition_binding.path if condition_binding is not None else None,
                    source_name=condition_binding.source if condition_binding is not None else None,
                    target_count=targets,
                    status=structure_status,
                    detail=_bounded(condition.path if condition is not None else None, 240),
                )
                if len(self.structures) < _MAX_STRUCTURES:
                    self.structures.append(structure)
                self.structure_targets[parent.id] = targets
        self._add_acyclic_edges(candidate_edges)

    def _missing_element_node(self, evidence: ElementEvidence, child_id: str) -> GraphNode:
        node_id = f"element:{self.document.sha256}:{evidence.project_data_part}:{child_id}~missing"
        existing = self.nodes.get(node_id)
        if existing is not None:
            return existing
        node = GraphNode(
            id=node_id,
            kind=NodeKind.ELEMENT,
            label=f"Missing element {child_id}",
            status=GraphStatus.UNKNOWN,
            document_sha256=self.document.sha256,
            document_name=self.document.filename,
            part=evidence.project_data_part,
            element_id=child_id,
            origin="missing_child_reference",
            reason="child_element_missing",
            evidence=_evidence({"parent_element_id": evidence.element_id_unsigned}),
        )
        self.add_node(node)
        self.unresolved_node(node, "child_element_missing")
        self.diagnostics.append(
            ReferenceDiagnostic(
                code="graph_missing_child_element",
                severity=Severity.WARNING,
                message=(
                    f"{self.document.filename}: element {evidence.element_id_unsigned} "
                    f"references missing child {child_id}"
                ),
                document_sha256=self.document.sha256,
                part=evidence.project_data_part,
                details=_evidence({"child_id": child_id}),
            )
        )
        return node

    def _add_acyclic_edges(
        self,
        candidates: Iterable[
            tuple[EdgeType, str, GraphNode, GraphStatus, str | None, dict[str, str]]
        ],
    ) -> None:
        ordered = sorted(
            candidates,
            key=lambda item: (item[0].value, item[1], item[2].id),
        )
        adjacency: dict[str, list[str]] = {}
        for _edge_type, source, target, _status, _reason, _evidence in ordered:
            adjacency.setdefault(source, []).append(target.id)
        state: dict[str, int] = {}

        def visit(node_id: str) -> None:
            state[node_id] = 1
            for target_id in adjacency.get(node_id, []):
                if state.get(target_id) == 1:
                    self.diagnostics.append(
                        ReferenceDiagnostic(
                            code="graph_child_element_cycle",
                            severity=Severity.WARNING,
                            message=(
                                f"{self.document.filename}: child element cycle at "
                                f"{target_id} was cut during serialization"
                            ),
                            document_sha256=self.document.sha256,
                        )
                    )
                    adjacency[node_id] = [item for item in adjacency[node_id] if item != target_id]
                    continue
                if state.get(target_id, 0) == 0:
                    visit(target_id)
            state[node_id] = 2

        for node_id in sorted(adjacency):
            if state.get(node_id, 0) == 0:
                visit(node_id)

        allowed = {(source, target) for source, targets in adjacency.items() for target in targets}
        for edge_type, source, target, status, reason, evidence in ordered:
            if (source, target.id) not in allowed:
                continue
            self.add_edge(
                edge_type,
                source,
                target.id,
                status,
                reason=reason,
                evidence=evidence,
            )


def _part_rank(part: str) -> tuple[int, str]:
    lowered = part.casefold()
    if lowered == "word/document.xml":
        return (0, part)
    if "header" in lowered:
        return (1, part)
    if "footer" in lowered:
        return (2, part)
    return (3, part)


def _resolve_schema_context(
    document: DocumentEvidence,
    schemas: Mapping[str, SchemaArtifact] | None,
    fallback: NormalizedSchema | None,
) -> tuple[NormalizedSchema | None, SchemaIndex | None, str | None, str | None]:
    artifact = schemas.get(document.sha256) if schemas is not None else None
    if artifact is not None:
        schema, index, schema_id, schema_digest = _artifact_schema(artifact)
        return schema, index, schema_id, schema_digest
    if fallback is not None:
        return (
            fallback,
            _index_from_schema(fallback),
            fallback.schema_id,
            fallback.digest(),
        )
    return None, None, None, None


def _summary(
    *,
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    structures: GraphStructures,
    unresolved: list[GraphUnresolved],
    unresolved_total: int,
    controls_total: int,
) -> GraphSummary:
    by_node_kind = {kind.value: 0 for kind in NodeKind}
    by_node_status = {status.value: 0 for status in GraphStatus}
    for node in nodes:
        by_node_kind[node.kind.value] += 1
        by_node_status[node.status.value] += 1
    by_edge_type = {edge_type.value: 0 for edge_type in EdgeType}
    by_edge_status = {status.value: 0 for status in GraphStatus}
    for edge in edges:
        by_edge_type[edge.type.value] += 1
        by_edge_status[edge.status.value] += 1
    resolved_edges = by_edge_status[GraphStatus.RESOLVED.value]
    ambiguous_edges = by_edge_status[GraphStatus.AMBIGUOUS.value]
    unknown_edges = by_edge_status[GraphStatus.UNKNOWN.value]
    total_edges = len(edges)
    control_statuses: dict[str, int] = {status.value: 0 for status in GraphStatus}
    for edge in edges:
        if edge.type is EdgeType.BOUND_TO and edge.source.startswith("control:"):
            control_statuses[edge.status.value] += 1
    controls_resolved = control_statuses[GraphStatus.RESOLVED.value]
    controls_ambiguous = control_statuses[GraphStatus.AMBIGUOUS.value]
    controls_unknown = max(0, controls_total - controls_resolved - controls_ambiguous)
    schema_fields = sum(1 for node in nodes if node.kind is NodeKind.SCHEMA_FIELD)
    schema_fields_resolved = sum(
        1
        for node in nodes
        if node.kind is NodeKind.SCHEMA_FIELD and node.status is GraphStatus.RESOLVED
    )
    return GraphSummary(
        node_count=len(nodes),
        edge_count=total_edges,
        by_node_kind=dict(sorted(by_node_kind.items())),
        by_node_status=dict(sorted(by_node_status.items())),
        by_edge_type=dict(sorted(by_edge_type.items())),
        by_edge_status=dict(sorted(by_edge_status.items())),
        resolved_edges=resolved_edges,
        ambiguous_edges=ambiguous_edges,
        unknown_edges=unknown_edges,
        edge_coverage_ratio=round(resolved_edges / total_edges, 4) if total_edges else 0.0,
        controls_total=controls_total,
        controls_resolved=controls_resolved,
        controls_ambiguous=controls_ambiguous,
        controls_unknown=controls_unknown,
        controls_bound=controls_resolved + controls_ambiguous,
        elements_total=by_node_kind[NodeKind.ELEMENT.value],
        sources_total=by_node_kind[NodeKind.SOURCE.value],
        schema_fields_total=schema_fields,
        schema_fields_resolved=schema_fields_resolved,
        lists_detected=len(structures.lists),
        conditions_detected=len(structures.conditions),
        unresolved_total=unresolved_total,
    )


def _sort_nodes(nodes: Iterable[GraphNode]) -> list[GraphNode]:
    return sorted(
        nodes,
        key=lambda node: (
            _NODE_RANK.get(node.kind.value, 9),
            node.document_sha256 or "",
            node.part or "",
            node.ordinal if node.ordinal is not None else -1,
            node.id,
        ),
    )


def _sort_edges(edges: Iterable[GraphEdge]) -> list[GraphEdge]:
    return sorted(edges, key=lambda edge: (edge.type.value, edge.source, edge.target, edge.id))


def build_reference_graph(
    report: ReferenceReport,
    schemas: Mapping[str, SchemaArtifact] | None = None,
    *,
    schema: NormalizedSchema | None = None,
) -> ReferenceGraph:
    """Build a deterministic, read-only ReferenceGraph from an inspection report.

    ``schemas`` maps a document SHA-256 to the schema artifact that was used for
    that document (see :func:`inspect_reference_bundle`). ``schema`` is an
    optional fallback normalized schema for callers that only have a report and
    one schema.
    """
    documents = sorted(
        report.documents,
        key=lambda item: (item.paths[0], item.sha256),
    )
    all_nodes: list[GraphNode] = []
    all_edges: list[GraphEdge] = []
    all_unresolved: list[GraphUnresolved] = []
    all_structures: list[GraphStructure] = []
    diagnostics: list[ReferenceDiagnostic] = []
    schema_ids: set[str] = set()
    schema_sections: set[str] = set()
    schema_digests: set[str] = set()
    schema_source = SchemaSource.NONE
    for document in documents:
        resolved_schema, index, schema_id, schema_digest = _resolve_schema_context(
            document, schemas, schema
        )
        if resolved_schema is not None:
            schema_source = SchemaSource.DDSP
            schema_ids.add(schema_id or resolved_schema.schema_id)
            schema_sections.update(resolved_schema.section_names)
            schema_digests.add(schema_digest or resolved_schema.digest())
        context = _DocContext(
            document,
            schema=resolved_schema,
            index=index,
            schema_id=schema_id,
            schema_digest=schema_digest,
        )
        context.build_elements()
        context.build_controls()
        context.build_structure_edges()
        all_nodes.extend(context.nodes.values())
        all_edges.extend(context.edges.values())
        all_unresolved.extend(context.unresolved.values())
        all_structures.extend(context.structures)
        diagnostics.extend(context.diagnostics)
        if resolved_schema is None:
            diagnostics.append(
                ReferenceDiagnostic(
                    code="graph_schema_not_provided",
                    severity=Severity.INFO,
                    message=(
                        f"{document.filename}: no DDSP schema was available; bindings are "
                        "kept as reference data"
                    ),
                    document_sha256=document.sha256,
                )
            )
    if not documents:
        diagnostics.append(
            ReferenceDiagnostic(
                code="graph_no_documents",
                severity=Severity.INFO,
                message="The inspected source does not contain a DOCX document",
            )
        )
    nodes = _sort_nodes(_unique_nodes(all_nodes))
    edges = _sort_edges(_unique_edges(all_edges))
    unresolved_all = sorted(
        {item.node_id: item for item in all_unresolved}.values(),
        key=lambda item: (item.kind.value, item.node_id),
    )
    unresolved = unresolved_all[:_MAX_UNRESOLVED]
    lists = sorted(
        (item for item in all_structures if item.kind is not ElementKind.IF),
        key=lambda item: (item.node_id, item.kind.value),
    )[:_MAX_STRUCTURES]
    conditions = sorted(
        (item for item in all_structures if item.kind is ElementKind.IF),
        key=lambda item: (item.node_id, item.kind.value),
    )[:_MAX_STRUCTURES]
    structures = GraphStructures(lists=lists, conditions=conditions)
    diagnostics = sorted(
        {item.model_dump_json(): item for item in diagnostics}.values(),
        key=lambda item: (
            item.document_sha256 or "",
            item.part or "",
            item.ordinal if item.ordinal is not None else -1,
            item.code,
            item.message,
        ),
    )[:_MAX_DIAGNOSTICS]
    summary = _summary(
        nodes=nodes,
        edges=edges,
        structures=structures,
        unresolved=unresolved,
        unresolved_total=len(unresolved_all),
        controls_total=report.counts.controls_total,
    )
    base = ReferenceGraph(
        source_type=report.source_type,
        source_name=report.source_name,
        source_sha256=report.source_sha256,
        platform=report.container.platform,
        schema_source=schema_source,
        schema_ids=sorted(schema_ids),
        schema_sections=sorted(schema_sections),
        schema_digests=sorted(schema_digests),
        nodes=nodes,
        edges=edges,
        structures=structures,
        unresolved=unresolved,
        summary=summary,
        diagnostics=diagnostics,
    )
    graph_digest = digest(base.model_dump(mode="json", exclude={"graph_digest"}))
    return base.model_copy(update={"graph_digest": graph_digest})


def _unique_nodes(nodes: Iterable[GraphNode]) -> list[GraphNode]:
    unique: dict[str, GraphNode] = {}
    for node in nodes:
        unique.setdefault(node.id, node)
    return list(unique.values())


def _unique_edges(edges: Iterable[GraphEdge]) -> list[GraphEdge]:
    unique: dict[str, GraphEdge] = {}
    for edge in edges:
        unique.setdefault(edge.id, edge)
    return list(unique.values())


def graph_json(graph: ReferenceGraph, *, indent: int = 2) -> str:
    """Deterministic JSON text used by the CLI and tests."""
    import json

    return (
        json.dumps(
            graph.model_dump(mode="json"),
            ensure_ascii=False,
            indent=indent,
            sort_keys=True,
        )
        + "\n"
    )


__all__ = [
    "GRAPH_VERSION",
    "READ_ONLY_NOTE",
    "RUNTIME_COMPATIBILITY",
    "EdgeType",
    "GraphEdge",
    "GraphNode",
    "GraphStatus",
    "GraphStructure",
    "GraphStructures",
    "GraphSummary",
    "GraphUnresolved",
    "NodeKind",
    "ReferenceGraph",
    "build_reference_graph",
    "graph_json",
]
