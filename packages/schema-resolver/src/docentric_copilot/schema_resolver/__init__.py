"""Schema path resolution and semantic field mapping (FR-02, FR-07)."""

from __future__ import annotations

from .mapping import (
    FieldMapping,
    MappingReport,
    MappingStatus,
    RequirementKind,
    summarize,
    validate_mapping,
)
from .paths import (
    PathResolutionError,
    ResolvedPath,
    Scope,
    absolute_path,
    is_type_compatible,
    resolve_collection,
    resolve_value,
)
from .search import Candidate, decide_status, infer_kind, search_candidates, tokenize

__all__ = [
    "Candidate",
    "FieldMapping",
    "MappingReport",
    "MappingStatus",
    "PathResolutionError",
    "RequirementKind",
    "ResolvedPath",
    "Scope",
    "absolute_path",
    "decide_status",
    "infer_kind",
    "is_type_compatible",
    "resolve_collection",
    "resolve_value",
    "search_candidates",
    "summarize",
    "tokenize",
    "validate_mapping",
]
