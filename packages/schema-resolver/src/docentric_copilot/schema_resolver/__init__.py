"""Schema path resolution and semantic field mapping (FR-02, FR-07)."""

from __future__ import annotations

from .concept_match import MATCHERS, ConceptMatcher, matches_kind, paths_for_concept
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
from .requirements import (
    Concept,
    Placement,
    Requirement,
    RequirementSet,
    parse_requirements,
    split_clauses,
)
from .search import Candidate, decide_status, infer_kind, search_candidates, tokenize

__all__ = [
    "MATCHERS",
    "Candidate",
    "Concept",
    "ConceptMatcher",
    "FieldMapping",
    "MappingReport",
    "MappingStatus",
    "PathResolutionError",
    "Placement",
    "Requirement",
    "RequirementKind",
    "RequirementSet",
    "ResolvedPath",
    "Scope",
    "absolute_path",
    "decide_status",
    "infer_kind",
    "is_type_compatible",
    "matches_kind",
    "parse_requirements",
    "paths_for_concept",
    "resolve_collection",
    "resolve_value",
    "search_candidates",
    "split_clauses",
    "summarize",
    "tokenize",
    "validate_mapping",
]
