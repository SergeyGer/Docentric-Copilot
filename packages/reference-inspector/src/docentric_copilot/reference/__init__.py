"""Read-only reference template intelligence (v0.6 milestone A).

The package inspects OOXML, AXPP/ZIP containers and Docentric ``ProjectData``
metadata without executing anything. It reports structure, duplicates, joins and
coverage; it does **not** claim Docentric AX runtime compatibility.
"""

from __future__ import annotations

from .docx_controls import (
    Classification,
    ControlType,
    DataBinding,
    DocxControl,
    DocxScan,
    ElementKind,
    StoryPart,
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
    inspect_bytes,
    inspect_path,
    scan_bytes,
    scan_path,
)
from .metadata import (
    ControlResolution,
    LinkStatus,
    PathStatus,
    ProjectDataBundle,
    ProjectDataPart,
    ResolutionStatus,
    SchemaIndex,
    SchemaSource,
    SourceBinding,
    load_project_data,
    normalize_store_item_id,
    resolve_controls,
    schema_from_ddsp,
)
from .report import (
    ControlEvidence,
    DocumentEvidence,
    ReferenceCounts,
    ReferenceDiagnostic,
    ReferenceReport,
    Severity,
    build_report,
    inspect_reference,
    inspect_reference_bytes,
    report_json,
)
from .safety import ReferenceLimits

__all__ = [
    "ArtifactKind",
    "Classification",
    "ControlEvidence",
    "ControlResolution",
    "ControlType",
    "DataBinding",
    "DocumentEvidence",
    "DocxControl",
    "DocxScan",
    "DuplicateGroup",
    "ElementKind",
    "InventoryEntry",
    "InventoryScan",
    "LinkStatus",
    "PathStatus",
    "PlatformHint",
    "ProjectDataBundle",
    "ProjectDataPart",
    "ReferenceCounts",
    "ReferenceDiagnostic",
    "ReferenceInventory",
    "ReferenceLimits",
    "ReferenceReport",
    "ResolutionStatus",
    "SchemaIndex",
    "SchemaSource",
    "Severity",
    "SourceBinding",
    "SourceType",
    "StoryPart",
    "VersionHints",
    "build_report",
    "inspect_bytes",
    "inspect_path",
    "inspect_reference",
    "inspect_reference_bytes",
    "load_project_data",
    "normalize_store_item_id",
    "report_json",
    "resolve_controls",
    "scan_bytes",
    "scan_docx",
    "scan_path",
    "schema_from_ddsp",
]
