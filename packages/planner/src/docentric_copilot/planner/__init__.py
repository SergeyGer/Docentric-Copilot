"""AI template planning on top of the LLM gateway (FR-02, FR-03, FR-08)."""

from __future__ import annotations

from .heuristic import BASELINE_VERSION, Roles, build_document, detect_document_kind, discover_roles
from .optimize import LayoutFix, LayoutOptimization, optimize_layout  # noqa: F401
from .prompt import PROMPT_VERSION, SYSTEM_PROMPT, build_messages, build_repair_message
from .quality import QualityCheck, QualityReport, QualityStatus, analyze_quality  # noqa: F401
from .rebind import rebind_paths
from .revisions import Change, diff_documents, summarize_changes
from .routing import Complexity, RouteDecision, classify, route, routing_policy
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
    "Complexity",
    "PlanOptions",
    "PlanOutcome",
    "QualityReport",
    "QualityStatus",
    "RemovedBinding",
    "Roles",
    "RouteDecision",
    "TemplatePlanner",
    "absolute_bindings",
    "analyze_quality",
    "build_document",
    "build_mapping_report",
    "build_messages",
    "build_repair_message",
    "classify",
    "detect_document_kind",
    "diff_documents",
    "discover_roles",
    "extract_requirements",
    "optimize_layout",
    "rebind_paths",
    "route",
    "routing_policy",
    "sanitize_document",
    "summarize_changes",
]
