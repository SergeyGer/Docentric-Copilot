"""Stable, JSON-serialisable reference inspection report.

The report combines the container inventory, the OOXML content-control scan and
the REF-02 metadata resolution. It always reports ``runtime_compatibility:
"not_tested"``: static inspection cannot prove that Docentric AX will execute a
template.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Final, Literal

from docentric_copilot.errors import CopilotError, InvalidInputError, UnsupportedInputError
from docentric_copilot.serialization import digest, digest_bytes
from pydantic import BaseModel, ConfigDict, Field

from .ddsp_real import DdspSchemaEvidence, SchemaArtifact, parse_ddsp_schema
from .docx_controls import (
    Classification,
    DocxControl,
    DocxScan,
    ElementKind,
    scan_docx,
)
from .inventory import (
    ArtifactKind,
    DuplicateGroup,
    InventoryEntry,
    InventoryScan,
    PlatformHint,
    ReferenceInventory,
    SourceType,
    VersionHints,
    scan_bytes,
    scan_path,
)
from .metadata import (
    ControlResolution,
    LinkStatus,
    ParsedProjectData,
    PathStatus,
    ProjectDataBundle,
    ProjectDataPart,
    ProjectElement,
    ResolutionStatus,
    SchemaIndex,
    SchemaSource,
    SourceBinding,
    effective_binding,
    element_kind_from_type,
    load_project_data,
    resolve_controls,
)
from .safety import ReferenceLimits

REFERENCE_VERSION: Final[Literal["1.0"]] = "1.0"
RUNTIME_COMPATIBILITY: Final[Literal["not_tested"]] = "not_tested"
_INSPECTOR = "reference-inspector/1.0"


class Severity(str, Enum):
    """Diagnostic severity; unresolved is not necessarily an error."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ReferenceDiagnostic(BaseModel):
    """One explicit, machine-readable inspection finding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1, max_length=80)
    severity: Severity
    message: str = Field(min_length=1, max_length=300)
    document_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    part: str | None = Field(default=None, max_length=240)
    ordinal: int | None = Field(default=None, ge=0)
    details: dict[str, str] = Field(default_factory=dict)


class ReferenceCounts(BaseModel):
    """Deterministic aggregate counts with explicit denominators."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifacts: int = Field(ge=0)
    distinct_artifacts: int = Field(ge=0)
    docx_artifacts: int = Field(ge=0)
    distinct_docx: int = Field(ge=0)
    controls_total: int = Field(ge=0)
    by_element_kind: dict[str, int] = Field(default_factory=dict)
    by_classification: dict[str, int] = Field(default_factory=dict)
    by_resolution: dict[str, int] = Field(default_factory=dict)
    by_link_status: dict[str, int] = Field(default_factory=dict)
    by_path_status: dict[str, int] = Field(default_factory=dict)
    by_part: dict[str, int] = Field(default_factory=dict)
    by_story: dict[str, int] = Field(default_factory=dict)
    classification_recognized: int = Field(ge=0)
    classification_ambiguous: int = Field(ge=0)
    classification_unknown: int = Field(ge=0)
    resolved: int = Field(ge=0)
    missing_part: int = Field(ge=0)
    unknown_path: int = Field(ge=0)
    ambiguous: int = Field(ge=0)
    joined_by_id: int = Field(ge=0)
    join_coverage_ratio: float = Field(ge=0.0, le=1.0)
    duplicate_groups: int = Field(ge=0)
    duplicate_occurrences: int = Field(ge=0)
    nested_archives: int = Field(ge=0)
    coverage_ratio: float = Field(ge=0.0, le=1.0)


class ElementEvidence(BaseModel):
    """One Docentric ProjectData element, preserved as reference evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    element_id_unsigned: str = Field(pattern=r"^[0-9]+$", max_length=20)
    element_type: str = Field(min_length=1, max_length=80)
    element_kind: ElementKind
    project_data_part: str = Field(min_length=1, max_length=240)
    source_binding: SourceBinding | None = None
    effective_binding: SourceBinding | None = None
    binding_notes: list[str] = Field(default_factory=list, max_length=20)
    child_element_ids: list[str] = Field(default_factory=list, max_length=500)
    parent_element_ids: list[str] = Field(default_factory=list, max_length=50)
    attributes: dict[str, str] = Field(default_factory=dict)
    properties: dict[str, str] = Field(default_factory=dict)


class ControlEvidence(DocxControl):
    """A content control plus its REF-02 resolution evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    resolution: ControlResolution


class DocumentEvidence(BaseModel):
    """Evidence collected for one distinct DOCX payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    paths: list[str] = Field(min_length=1, max_length=4096)
    filename: str = Field(min_length=1, max_length=300)
    size_bytes: int = Field(ge=0)
    platform: PlatformHint = PlatformHint.UNKNOWN
    product_version: str | None = Field(default=None, max_length=40)
    project_data: list[ProjectDataPart] = Field(default_factory=list)
    schema_source: SchemaSource = SchemaSource.NONE
    schema_sections: list[str] = Field(default_factory=list, max_length=20)
    schema_paths: int = Field(default=0, ge=0)
    schema_evidence: DdspSchemaEvidence | None = None
    metadata_elements: list[ElementEvidence] = Field(default_factory=list, max_length=5_000)
    control_count: int = Field(ge=0)
    classification_counts: dict[str, int] = Field(default_factory=dict)
    resolution_counts: dict[str, int] = Field(default_factory=dict)
    link_status_counts: dict[str, int] = Field(default_factory=dict)
    path_status_counts: dict[str, int] = Field(default_factory=dict)
    joined_count: int = Field(ge=0)
    join_coverage_ratio: float = Field(ge=0.0, le=1.0)
    coverage_ratio: float = Field(ge=0.0, le=1.0)
    has_macros: bool = False
    has_active_x: bool = False
    has_embedded_objects: bool = False
    has_external_relationships: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=100)
    controls: list[ControlEvidence] = Field(default_factory=list)


class ReferenceReport(BaseModel):
    """The complete reference inspection report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reference_version: Literal["1.0"] = "1.0"
    inspector: str = _INSPECTOR
    runtime_compatibility: Literal["not_tested"] = "not_tested"
    source_type: SourceType
    source_name: str = Field(min_length=1, max_length=300)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    container: VersionHints
    counts: ReferenceCounts
    duplicates: list[DuplicateGroup] = Field(default_factory=list)
    nested_archives: list[str] = Field(default_factory=list)
    documents: list[DocumentEvidence] = Field(default_factory=list)
    diagnostics: list[ReferenceDiagnostic] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list, max_length=100)
    inventory: ReferenceInventory
    report_digest: str = Field(pattern=r"^[0-9a-f]{64}$", default="0" * 64)


def _empty_counts() -> dict[str, int]:
    return {kind.value: 0 for kind in ElementKind}


def _classification_counts(controls: list[ControlEvidence]) -> dict[str, int]:
    counts = {item.value: 0 for item in Classification}
    for control in controls:
        counts[control.classification.value] += 1
    return dict(sorted(counts.items()))


def _resolution_counts(controls: list[ControlEvidence]) -> dict[str, int]:
    counts = {item.value: 0 for item in ResolutionStatus}
    for control in controls:
        counts[control.resolution.status.value] += 1
    return dict(sorted(counts.items()))


def _kind_counts(controls: list[ControlEvidence]) -> dict[str, int]:
    counts = _empty_counts()
    for control in controls:
        counts[control.element_kind.value] += 1
    return dict(sorted(counts.items()))


def _link_counts(controls: list[ControlEvidence]) -> dict[str, int]:
    counts = {item.value: 0 for item in LinkStatus}
    for control in controls:
        counts[control.resolution.link_status.value] += 1
    return dict(sorted(counts.items()))


def _path_counts(controls: list[ControlEvidence]) -> dict[str, int]:
    counts = {item.value: 0 for item in PathStatus}
    for control in controls:
        counts[control.resolution.path_status.value] += 1
    return dict(sorted(counts.items()))


def _joined(controls: list[ControlEvidence]) -> int:
    return sum(
        1
        for control in controls
        if control.resolution.link_status
        in {LinkStatus.RESOLVED_BY_ID, LinkStatus.RESOLVED_BY_ID_SHARED}
    )


def _join_coverage(controls: list[ControlEvidence]) -> float:
    if not controls:
        return 0.0
    return round(_joined(controls) / len(controls), 4)


def _part_counts(controls: list[ControlEvidence]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for control in controls:
        counts[control.part] = counts.get(control.part, 0) + 1
    return dict(sorted(counts.items()))


def _story_counts(controls: list[ControlEvidence]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for control in controls:
        counts[control.story.value] = counts.get(control.story.value, 0) + 1
    return dict(sorted(counts.items()))


def _coverage(controls: list[ControlEvidence]) -> float:
    if not controls:
        return 0.0
    resolved = sum(
        1 for control in controls if control.resolution.status is ResolutionStatus.RESOLVED
    )
    return round(resolved / len(controls), 4)


def _parse_schema(
    payload: bytes,
    *,
    name: str,
    limits: ReferenceLimits,
    explicit: bool,
    warnings: set[str],
) -> SchemaArtifact | None:
    try:
        artifact = parse_ddsp_schema(payload, name=name, limits=limits)
    except CopilotError:
        if explicit:
            raise
        warnings.add(f"ddsp_unreadable:{name}")
        return None
    if artifact.index.is_empty:
        warnings.add(f"ddsp_schema_unrecognized:{name}")
        return None
    return artifact


def _stems_match(document_name: str, schema_name: str) -> bool:
    document_stem = Path(document_name).stem.casefold()
    schema_stem = Path(schema_name).stem.casefold()
    if not document_stem or not schema_stem:
        return False
    return (
        document_stem == schema_stem
        or document_stem.startswith(f"{schema_stem}.")
        or schema_stem.startswith(f"{document_stem}.")
    )


def _sibling_schema_entries(
    document: InventoryEntry, entries: list[InventoryEntry]
) -> list[InventoryEntry]:
    parent = document.parent
    return [
        entry
        for entry in entries
        if entry.kind is ArtifactKind.DDSP
        and entry.parent == parent
        and _stems_match(document.name, entry.name)
    ]


def _select_schema(
    *,
    document: InventoryEntry,
    scan: InventoryScan,
    explicit_ddsp: tuple[bytes, str] | None,
    schema_cache: dict[str, SchemaArtifact | None],
    limits: ReferenceLimits,
    warnings: set[str],
) -> SchemaArtifact | None:
    entries = scan.inventory.entries
    candidates: list[tuple[bytes, str, bool]] = []
    if explicit_ddsp is not None:
        explicit_payload, explicit_name = explicit_ddsp
        distinct_docx = {entry.sha256 for entry in entries if entry.kind is ArtifactKind.DOCX}
        if _stems_match(document.name, explicit_name) or len(distinct_docx) == 1:
            candidates.append((explicit_payload, explicit_name, True))
        else:
            warnings.add(f"explicit_ddsp_unmatched:{explicit_name}")
    for sibling in _sibling_schema_entries(document, entries):
        payload = scan.payloads.get(sibling.sha256)
        if payload is None:
            continue
        if any(sibling.sha256 == digest_bytes(candidate[0]) for candidate in candidates):
            continue
        candidates.append((payload, sibling.name, False))
    if not candidates:
        return None
    payload, name, explicit = candidates[0]
    key = digest_bytes(payload)
    if key not in schema_cache:
        schema_cache[key] = _parse_schema(
            payload, name=name, limits=limits, explicit=explicit, warnings=warnings
        )
    return schema_cache[key]


def _document_diagnostics(
    document: DocumentEvidence,
    bundle: ProjectDataBundle,
    docx_scan: DocxScan,
) -> list[ReferenceDiagnostic]:
    diagnostics: list[ReferenceDiagnostic] = []
    for control in document.controls:
        resolution = control.resolution
        if resolution.status is not ResolutionStatus.RESOLVED:
            codes = resolution.diagnostic_codes or [resolution.status.value]
            diagnostics.append(
                ReferenceDiagnostic(
                    code=f"control_{resolution.status.value}",
                    severity=Severity.WARNING,
                    message=(
                        f"{document.filename}: control {control.ordinal} in {control.part} "
                        f"is {resolution.status.value} ({', '.join(codes)})"
                    ),
                    document_sha256=document.sha256,
                    part=control.part,
                    ordinal=control.ordinal,
                    details={
                        "sdt_id": (
                            "" if control.sdt_id_signed is None else str(control.sdt_id_signed)
                        ),
                        "element_id": resolution.element_id_unsigned or "",
                        "link_status": resolution.link_status.value,
                        "path_status": resolution.path_status.value,
                        "reasons": ",".join(codes),
                        "suggestions": ",".join(resolution.path_suggestions),
                    },
                )
            )
        if control.classification is Classification.AMBIGUOUS:
            diagnostics.append(
                ReferenceDiagnostic(
                    code="control_classification_ambiguous",
                    severity=Severity.WARNING,
                    message=(
                        f"{document.filename}: control {control.ordinal} has conflicting "
                        f"Docentric markers ({control.classification_reason})"
                    ),
                    document_sha256=document.sha256,
                    part=control.part,
                    ordinal=control.ordinal,
                    details={"markers": ",".join(control.markers)},
                )
            )
        elif control.classification is Classification.UNKNOWN:
            diagnostics.append(
                ReferenceDiagnostic(
                    code="control_classification_unknown",
                    severity=Severity.INFO,
                    message=(
                        f"{document.filename}: control {control.ordinal} carries no recognizable "
                        "Docentric marker; it is preserved as unknown"
                    ),
                    document_sha256=document.sha256,
                    part=control.part,
                    ordinal=control.ordinal,
                    details={},
                )
            )
    for warning in bundle.warnings:
        diagnostics.append(
            ReferenceDiagnostic(
                code="project_data_warning",
                severity=Severity.INFO,
                message=f"{document.filename}: {warning}",
                document_sha256=document.sha256,
                details={"warning": warning},
            )
        )
    for warning in docx_scan.warnings:
        diagnostics.append(
            ReferenceDiagnostic(
                code="docx_scan_warning",
                severity=Severity.WARNING,
                message=f"{document.filename}: {warning}",
                document_sha256=document.sha256,
                details={"warning": warning},
            )
        )
    return diagnostics


def _build_metadata_elements(bundle: ProjectDataBundle) -> list[ElementEvidence]:
    """Flatten ProjectData elements into bounded, deterministic evidence."""
    elements: list[ElementEvidence] = []
    seen: set[tuple[str, str, str]] = set()
    for part in sorted(bundle.parts, key=lambda item: item.summary.part):
        for element_id in sorted(part.by_id, key=lambda value: (int(value), value)):
            for element in sorted(part.by_id[element_id], key=_element_sort_key):
                key = (part.summary.part, element_id, repr(_element_sort_key(element)))
                if key in seen:
                    continue
                seen.add(key)
                elements.append(_element_evidence(part.summary.part, element, bundle, part))
                if len(elements) >= 5_000:
                    return elements
    return elements


def _element_sort_key(element: ProjectElement) -> tuple[str, str, str, str, str]:
    binding = element.value_binding
    return (
        element.element_type,
        binding.source if binding and binding.source else "",
        binding.path if binding and binding.path else "",
        binding.result_data_type if binding and binding.result_data_type else "",
        ",".join(element.child_ids),
    )


def _bounded_mapping(values: dict[str, str], limit: int = 20) -> dict[str, str]:
    return {key: values[key] for key in sorted(values)[:limit]}


def _element_evidence(
    part_name: str,
    element: ProjectElement,
    bundle: ProjectDataBundle,
    part: ParsedProjectData,
) -> ElementEvidence:
    binding, notes = effective_binding(part, element)
    parents = sorted(part.parent_ids.get(element.id_unsigned, []), key=int)
    return ElementEvidence(
        element_id_unsigned=element.id_unsigned,
        element_type=element.element_type,
        element_kind=element_kind_from_type(element.element_type),
        project_data_part=part_name,
        source_binding=element.value_binding,
        effective_binding=binding,
        binding_notes=sorted(set(notes)),
        child_element_ids=list(element.child_ids)[:500],
        parent_element_ids=parents[:50],
        attributes=_bounded_mapping(element.attributes),
        properties=_bounded_mapping(element.properties),
    )


def _build_document(
    *,
    sha256: str,
    paths: list[str],
    entry: InventoryEntry,
    data: bytes,
    artifact: SchemaArtifact | None,
    limits: ReferenceLimits,
) -> tuple[DocumentEvidence, ProjectDataBundle, DocxScan]:
    docx_scan = scan_docx(data, limits)
    bundle = load_project_data(data, limits)
    schema: SchemaIndex | None = artifact.index if artifact is not None else None
    resolutions = resolve_controls(docx_scan.controls, bundle, schema)
    controls = [
        ControlEvidence.model_validate(
            {
                **control.model_dump(mode="python"),
                "resolution": resolution.model_dump(mode="python"),
            }
        )
        for control, resolution in zip(docx_scan.controls, resolutions, strict=True)
    ]
    schema_sections = artifact.schema.section_names if artifact is not None else []
    schema_paths = artifact.index.path_count() if artifact is not None else 0
    product_version = entry.product_version
    for part in bundle.parts:
        if part.summary.product_version:
            product_version = product_version or part.summary.product_version
    contract_version = artifact.evidence.product_version if artifact is not None else None
    product_version = product_version or contract_version
    platform = entry.platform_hint
    if platform is PlatformHint.UNKNOWN and contract_version and contract_version.startswith("1.4"):
        platform = PlatformHint.AX_2012
    document = DocumentEvidence(
        sha256=sha256,
        paths=sorted(set(paths)),
        filename=Path(paths[0]).name,
        size_bytes=entry.size_bytes,
        platform=platform,
        product_version=product_version,
        project_data=[part.summary for part in bundle.parts],
        schema_source=SchemaSource.DDSP if schema is not None else SchemaSource.NONE,
        schema_sections=schema_sections,
        schema_paths=schema_paths,
        schema_evidence=artifact.evidence if artifact is not None else None,
        metadata_elements=_build_metadata_elements(bundle),
        control_count=len(controls),
        classification_counts=_classification_counts(controls),
        resolution_counts=_resolution_counts(controls),
        link_status_counts=_link_counts(controls),
        path_status_counts=_path_counts(controls),
        joined_count=_joined(controls),
        join_coverage_ratio=_join_coverage(controls),
        coverage_ratio=_coverage(controls),
        has_macros=docx_scan.has_macros,
        has_active_x=docx_scan.has_active_x,
        has_embedded_objects=docx_scan.has_embedded_objects,
        has_external_relationships=docx_scan.has_external_relationships,
        warnings=sorted(set(docx_scan.warnings) | set(bundle.warnings))[:100],
        controls=controls,
    )
    return document, bundle, docx_scan


@dataclass(frozen=True, slots=True)
class ReferenceInspection:
    """The report plus the per-document schema artifacts used to build it.

    The graph and projection need the normalized schema, while the public JSON
    report intentionally stores only bounded evidence. Keeping the artifacts in
    this side-channel avoids embedding a 5,000-node schema in every report.
    """

    report: ReferenceReport
    schemas: dict[str, SchemaArtifact] = field(default_factory=dict)
    #: DOCX payloads keyed by document SHA-256. An internal side-channel used by
    #: the graph builder to extract D365 embedded-schema evidence without
    #: re-reading the source; it is never serialised into the public report.
    payloads: dict[str, bytes] = field(default_factory=dict)


def build_inspection(
    scan: InventoryScan,
    *,
    limits: ReferenceLimits,
    explicit_ddsp: tuple[bytes, str] | None = None,
) -> ReferenceInspection:
    """Build the report and schema artifacts from a bounded inventory scan."""
    inventory = scan.inventory
    warnings: set[str] = set(inventory.warnings)
    schema_cache: dict[str, SchemaArtifact | None] = {}
    schemas_by_sha: dict[str, SchemaArtifact] = {}
    payloads_by_sha: dict[str, bytes] = {}
    documents: list[DocumentEvidence] = []
    all_controls: list[ControlEvidence] = []
    diagnostics: list[ReferenceDiagnostic] = []
    distinct_entries = scan.distinct_entries_by_sha(ArtifactKind.DOCX)
    for entry in distinct_entries:
        data = scan.payload_for_sha(entry.sha256)
        if data is None:
            warnings.add(f"docx_payload_missing:{entry.sha256[:12]}")
            continue
        paths = scan.paths_by_sha.get(entry.sha256, [entry.path])
        schema_artifact = _select_schema(
            document=entry,
            scan=scan,
            explicit_ddsp=explicit_ddsp,
            schema_cache=schema_cache,
            limits=limits,
            warnings=warnings,
        )
        document, bundle, docx_scan = _build_document(
            sha256=entry.sha256,
            paths=paths,
            entry=entry,
            data=data,
            artifact=schema_artifact,
            limits=limits,
        )
        documents.append(document)
        payloads_by_sha[entry.sha256] = data
        if schema_artifact is not None:
            schemas_by_sha[entry.sha256] = schema_artifact
        all_controls.extend(document.controls)
        diagnostics.extend(_document_diagnostics(document, bundle, docx_scan))
    documents.sort(key=lambda item: (item.paths[0], item.sha256))
    for warning in inventory.warnings:
        diagnostics.append(
            ReferenceDiagnostic(
                code="inventory_warning",
                severity=Severity.INFO,
                message=warning,
                details={"warning": warning},
            )
        )
    for warning in sorted(warnings):
        if warning.startswith(
            ("explicit_ddsp_unmatched:", "ddsp_schema_unrecognized:", "ddsp_unreadable:")
        ):
            diagnostics.append(
                ReferenceDiagnostic(
                    code="schema_warning",
                    severity=Severity.WARNING,
                    message=warning,
                    details={"warning": warning},
                )
            )
    diagnostics.sort(
        key=lambda item: (
            item.document_sha256 or "",
            item.part or "",
            item.ordinal if item.ordinal is not None else -1,
            item.code,
        )
    )
    by_kind = _kind_counts(all_controls)
    by_classification = _classification_counts(all_controls)
    by_resolution = _resolution_counts(all_controls)
    by_link_status = _link_counts(all_controls)
    by_path_status = _path_counts(all_controls)
    counts = ReferenceCounts(
        artifacts=len(inventory.entries),
        distinct_artifacts=inventory.distinct_artifacts(),
        docx_artifacts=len(inventory.artifacts_of_kind(ArtifactKind.DOCX)),
        distinct_docx=len(documents),
        controls_total=len(all_controls),
        by_element_kind=by_kind,
        by_classification=by_classification,
        by_resolution=by_resolution,
        by_link_status=by_link_status,
        by_path_status=by_path_status,
        by_part=_part_counts(all_controls),
        by_story=_story_counts(all_controls),
        classification_recognized=by_classification[Classification.RECOGNIZED.value],
        classification_ambiguous=by_classification[Classification.AMBIGUOUS.value],
        classification_unknown=by_classification[Classification.UNKNOWN.value],
        resolved=by_resolution[ResolutionStatus.RESOLVED.value],
        missing_part=by_resolution[ResolutionStatus.MISSING_PART.value],
        unknown_path=by_resolution[ResolutionStatus.UNKNOWN_PATH.value],
        ambiguous=by_resolution[ResolutionStatus.AMBIGUOUS.value],
        joined_by_id=_joined(all_controls),
        join_coverage_ratio=_join_coverage(all_controls),
        duplicate_groups=len(inventory.duplicates),
        duplicate_occurrences=sum(group.occurrences - 1 for group in inventory.duplicates),
        nested_archives=len(inventory.nested_archives),
        coverage_ratio=_coverage(all_controls),
    )
    base = ReferenceReport(
        reference_version=REFERENCE_VERSION,
        runtime_compatibility=RUNTIME_COMPATIBILITY,
        source_type=inventory.source_type,
        source_name=inventory.source_name,
        source_sha256=inventory.source_sha256,
        container=inventory.container,
        counts=counts,
        duplicates=list(inventory.duplicates),
        nested_archives=list(inventory.nested_archives),
        documents=documents,
        diagnostics=diagnostics,
        warnings=sorted(warnings)[:100],
        inventory=inventory,
    )
    report_digest = digest(base.model_dump(mode="json", exclude={"report_digest"}))
    report = base.model_copy(update={"report_digest": report_digest})
    return ReferenceInspection(report=report, schemas=schemas_by_sha, payloads=payloads_by_sha)


def build_report(
    scan: InventoryScan,
    *,
    limits: ReferenceLimits,
    explicit_ddsp: tuple[bytes, str] | None = None,
) -> ReferenceReport:
    """Build the report from an already bounded inventory scan."""
    return build_inspection(scan, limits=limits, explicit_ddsp=explicit_ddsp).report


def report_json(report: ReferenceReport, *, indent: int = 2) -> str:
    """Deterministic JSON text used by the CLI and tests."""
    return (
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            indent=indent,
            sort_keys=True,
        )
        + "\n"
    )


def _limits_for(limits: ReferenceLimits | None, max_depth: int) -> ReferenceLimits:
    return limits or ReferenceLimits.from_limits(max_depth=max_depth)


def inspect_reference_bundle(
    source: str | Path,
    *,
    limits: ReferenceLimits | None = None,
    max_depth: int = 1,
    ddsp_path: str | Path | None = None,
) -> ReferenceInspection:
    """Inspect locally and keep the parsed schema artifacts for graph building."""
    resolved_limits = _limits_for(limits, max_depth)
    scan = scan_path(source, limits=resolved_limits, max_depth=max_depth)
    explicit: tuple[bytes, str] | None = None
    if ddsp_path is not None:
        ddsp_target = Path(ddsp_path)
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
        explicit = (ddsp_target.read_bytes(), ddsp_target.name)
    return build_inspection(scan, limits=resolved_limits, explicit_ddsp=explicit)


def inspect_reference(
    source: str | Path,
    *,
    limits: ReferenceLimits | None = None,
    max_depth: int = 1,
    ddsp_path: str | Path | None = None,
) -> ReferenceReport:
    """Inspect a local DOCX/ZIP/AXPP/directory entirely in memory."""
    return inspect_reference_bundle(
        source, limits=limits, max_depth=max_depth, ddsp_path=ddsp_path
    ).report


def inspect_reference_bytes_bundle(
    data: bytes,
    *,
    filename: str,
    limits: ReferenceLimits | None = None,
    max_depth: int = 1,
    ddsp_data: bytes | None = None,
    ddsp_name: str = "source.ddsp",
) -> ReferenceInspection:
    """Inspect an uploaded payload and keep the schema artifacts."""
    resolved_limits = _limits_for(limits, max_depth)
    if ddsp_data is not None and len(ddsp_data) > resolved_limits.max_file_bytes:
        raise UnsupportedInputError(
            "Supplied DDSP schema exceeds the configured maximum size",
            code="reference_input_too_large",
        )
    scan = scan_bytes(data, filename=filename, limits=resolved_limits, max_depth=max_depth)
    explicit = (ddsp_data, ddsp_name) if ddsp_data is not None else None
    return build_inspection(scan, limits=resolved_limits, explicit_ddsp=explicit)


def inspect_reference_bytes(
    data: bytes,
    *,
    filename: str,
    limits: ReferenceLimits | None = None,
    max_depth: int = 1,
    ddsp_data: bytes | None = None,
    ddsp_name: str = "source.ddsp",
) -> ReferenceReport:
    """Inspect an uploaded payload without writing it to disk."""
    return inspect_reference_bytes_bundle(
        data,
        filename=filename,
        limits=limits,
        max_depth=max_depth,
        ddsp_data=ddsp_data,
        ddsp_name=ddsp_name,
    ).report


__all__ = [
    "REFERENCE_VERSION",
    "RUNTIME_COMPATIBILITY",
    "ControlEvidence",
    "DocumentEvidence",
    "ElementEvidence",
    "ReferenceCounts",
    "ReferenceDiagnostic",
    "ReferenceInspection",
    "ReferenceReport",
    "Severity",
    "build_inspection",
    "build_report",
    "inspect_reference",
    "inspect_reference_bundle",
    "inspect_reference_bytes",
    "inspect_reference_bytes_bundle",
    "report_json",
]
