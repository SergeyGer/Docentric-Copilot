"""AI template planning on top of the LLM gateway (FR-02, FR-03, FR-08)."""

from __future__ import annotations

from .compact_ir import (
    COMPACT_SYSTEM_PROMPT,
    COMPACT_TEMPLATE_NAME,
    build_compact_messages,
    compact_schema,
    expand_compact,
)
from .compact_ir_v2 import (
    COMPACT_V2_GENERATOR,
    COMPACT_V2_SCHEMA_TITLE,
    COMPACT_V2_SYSTEM_PROMPT,
    build_compact_messages_v2,
    compact_schema_v2,
    expand_compact_v2,
)
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

#: Version of the planner behaviour that produced a benchmark plan. Bump when
#: prompts, post-processing or repair behaviour can change the generated IR;
#: benchmark manifests pin this value.
PLANNER_VERSION = "0.13.0"

__all__ = [
    "BASELINE_VERSION",
    "COMPACT_SYSTEM_PROMPT",
    "COMPACT_TEMPLATE_NAME",
    "COMPACT_V2_GENERATOR",
    "COMPACT_V2_SCHEMA_TITLE",
    "COMPACT_V2_SYSTEM_PROMPT",
    "PLANNER_VERSION",
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
    "build_compact_messages",
    "build_compact_messages_v2",
    "build_document",
    "build_mapping_report",
    "build_messages",
    "build_repair_message",
    "classify",
    "compact_schema",
    "compact_schema_v2",
    "detect_document_kind",
    "diff_documents",
    "discover_roles",
    "expand_compact",
    "expand_compact_v2",
    "extract_requirements",
    "optimize_layout",
    "rebind_paths",
    "route",
    "routing_policy",
    "sanitize_document",
    "summarize_changes",
]
