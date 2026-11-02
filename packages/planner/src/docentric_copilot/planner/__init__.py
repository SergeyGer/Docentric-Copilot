"""AI template planning on top of the LLM gateway (FR-02, FR-03, FR-08)."""

from __future__ import annotations

from .heuristic import BASELINE_VERSION, Roles, build_document, detect_document_kind, discover_roles
from .prompt import PROMPT_VERSION, SYSTEM_PROMPT, build_messages, build_repair_message
from .rebind import rebind_paths
from .revisions import Change, diff_documents, summarize_changes
from .service import (
    PlanOptions,
    PlanOutcome,
    RemovedBinding,
    TemplatePlanner,
    absolute_bindings,
    build_mapping_report,
    extract_requirements,
    sanitize_document,
)

__all__ = [
    "BASELINE_VERSION",
    "PROMPT_VERSION",
    "SYSTEM_PROMPT",
    "Change",
    "PlanOptions",
    "PlanOutcome",
    "RemovedBinding",
    "Roles",
    "TemplatePlanner",
    "absolute_bindings",
    "build_document",
    "build_mapping_report",
    "build_messages",
    "build_repair_message",
    "detect_document_kind",
    "diff_documents",
    "discover_roles",
    "extract_requirements",
    "rebind_paths",
    "sanitize_document",
    "summarize_changes",
]
