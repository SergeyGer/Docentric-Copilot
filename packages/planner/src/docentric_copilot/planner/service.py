"""Template planning service (FR-02, FR-03, FR-08).

The planner is the only component that talks to a model. Its output is never
trusted: every candidate document passes through a deterministic repair pass that
removes bindings which do not exist in the schema, and a mapping report records
what was accepted, what was dropped and what still needs a human decision.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from docentric_copilot.ddsp_parser.models import NormalizedSchema
from docentric_copilot.errors import InvalidInputError, ProviderError
from docentric_copilot.llm.gateway import LLMGateway
from docentric_copilot.llm.models import GenerationResult
from docentric_copilot.schema_resolver.mapping import (
    FieldMapping,
    MappingReport,
    MappingStatus,
    RequirementKind,
    validate_mapping,
)
from docentric_copilot.schema_resolver.paths import (
    PathResolutionError,
    Scope,
    resolve_collection,
    resolve_value,
)
from docentric_copilot.schema_resolver.search import (
    Candidate,
    decide_status,
    infer_kind,
    search_candidates,
    tokenize,
)
from docentric_copilot.template_ir import (
    Block,
    Cell,
    CompileTarget,
    Conditional,
    DesignStyle,
    Document,
    Expression,
    FieldBinding,
    Heading,
    ImageBinding,
    InlineContent,
    Paragraph,
    Repeat,
    Section,
    Table,
    iter_expressions,
)

from .heuristic import BASELINE_VERSION, build_document
from .prompt import build_messages, build_repair_message
from .revisions import Change, diff_documents, summarize_changes

_MAX_REQUIREMENTS = 12
_CLAUSE_SPLIT = re.compile(r"(?:[,;\n]|\band\b|\.\s)", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Request / response models
# --------------------------------------------------------------------------- #
class PlanOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    language: str = "en"
    design_style: DesignStyle = DesignStyle.MODERN
    target: CompileTarget = CompileTarget.GENERIC_DOCX
    max_repair_attempts: int = 1


class RemovedBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    reason: str
    block_kind: str


class PlanOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: Document
    mapping: MappingReport
    generation: GenerationResult | None = None
    removed_bindings: list[RemovedBinding] = []
    repairs: list[str] = []
    warnings: list[str] = []
    changed: list[Change] = []


# --------------------------------------------------------------------------- #
# Requirement extraction and mapping report
# --------------------------------------------------------------------------- #
def extract_requirements(requirement: str, *, limit: int = _MAX_REQUIREMENTS) -> list[str]:
    """Split a free-form requirement into reviewable clauses."""
    seen: set[str] = set()
    clauses: list[str] = []
    for raw in _CLAUSE_SPLIT.split(requirement):
        clause = raw.strip(" .;:-*\t")
        if len(clause.split()) < 2:
            continue
        lowered = clause.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        clauses.append(clause[:200])
        if len(clauses) >= limit:
            break
    return clauses


def _used_paths(document: Document, schema: NormalizedSchema) -> dict[str, str]:
    """Collect absolute paths referenced by the plan (aliases resolved)."""
    used: dict[str, str] = {}

    def walk(blocks: list[Block], scope: Scope) -> None:
        for block in blocks:
            if isinstance(block, Paragraph | Heading):
                for run in block.runs:
                    if isinstance(run, FieldBinding):
                        try:
                            used[run.path] = resolve_value(schema, run.path, scope).absolute
                        except PathResolutionError:
                            continue
            elif isinstance(block, ImageBinding):
                try:
                    used[block.path] = resolve_value(schema, block.path, scope).absolute
                except PathResolutionError:
                    continue
            elif isinstance(block, Repeat):
                try:
                    collection = resolve_collection(schema, block.path, scope)
                except PathResolutionError:
                    continue
                used[block.path] = collection.absolute
                walk(block.blocks, scope.push(block.alias, collection.absolute))
            elif isinstance(block, Conditional):
                walk(block.then_blocks, scope)
                walk(block.else_blocks or [], scope)
            elif isinstance(block, Table):
                row_scope = scope
                if block.repeat is not None:
                    try:
                        collection = resolve_collection(schema, block.repeat.path, scope)
                    except PathResolutionError:
                        collection = None
                    if collection is not None:
                        used[block.repeat.path] = collection.absolute
                        row_scope = scope.push(block.repeat.alias, collection.absolute)
                for row in block.rows:
                    for cell in row.cells:
                        walk(cell.blocks, scope)
                for cell in block.row_template or []:
                    walk(cell.blocks, row_scope)

    for section in document.sections:
        walk(section.body, Scope())
        walk(section.header or [], Scope())
        walk(section.footer or [], Scope())
    return used


def build_mapping_report(
    schema: NormalizedSchema,
    document: Document,
    requirement: str,
    removed: list[RemovedBinding] | None = None,
) -> MappingReport:
    """Derive a reviewable requirement-to-field report from the produced IR.

    The report is intentionally conservative: a clause is ``resolved`` only when
    the plan actually binds the best matching field. A confident candidate that
    the plan does not use is reported as ``missing`` so a human can accept it,
    while genuinely close alternatives are reported as ``ambiguous``.
    """
    used = _used_paths(document, schema)
    used_absolute = set(used.values())
    mappings: list[FieldMapping] = []

    for index, clause in enumerate(extract_requirements(requirement)):
        requirement_id = f"req_{index:02d}"
        kind: RequirementKind = infer_kind(clause)
        candidates: list[Candidate] = search_candidates(
            schema,
            clause,
            kind=kind,
            limit=4,
            include_collections=kind is RequirementKind.COLLECTION,
        )
        candidate_paths = [candidate.path for candidate in candidates]
        top = candidates[0] if candidates else None
        clause_tokens = set(tokenize(clause))
        title_tokens = set(tokenize(document.title))

        if clause_tokens and clause_tokens <= title_tokens:
            mappings.append(
                FieldMapping(
                    requirement_id=requirement_id,
                    requirement=clause,
                    candidate_field_paths=[],
                    selected_field_path=None,
                    status=MappingStatus.RESOLVED,
                    confidence_score=1.0,
                    explanation="Satisfied by the document title.",
                )
            )
            continue

        used_candidate = next(
            (candidate for candidate in candidates if candidate.path in used_absolute), None
        )
        if used_candidate is not None:
            offset = candidate_paths.index(used_candidate.path)
            mappings.append(
                validate_mapping(
                    schema,
                    FieldMapping(
                        requirement_id=requirement_id,
                        requirement=clause,
                        candidate_field_paths=candidate_paths,
                        selected_field_path=used_candidate.path,
                        status=MappingStatus.RESOLVED,
                        confidence_score=min(1.0, max(0.05, used_candidate.score - 0.05 * offset)),
                        explanation="The plan binds the best matching field for this requirement.",
                    ),
                )
            )
            continue

        decision = decide_status(candidates)
        if decision == "ambiguous":
            status = MappingStatus.AMBIGUOUS
            explanation = "Several fields match equally well; a human decision is required."
        elif decision == "resolved":
            status = MappingStatus.MISSING
            explanation = (
                "A matching field exists but the plan does not use it; "
                "accept the suggested field or refine the requirement."
            )
        else:
            status = MappingStatus.MISSING
            explanation = "No field in the schema satisfies this requirement."
        mappings.append(
            validate_mapping(
                schema,
                FieldMapping(
                    requirement_id=requirement_id,
                    requirement=clause,
                    candidate_field_paths=candidate_paths,
                    selected_field_path=None,
                    status=status,
                    confidence_score=top.score if top else None,
                    explanation=explanation,
                ),
            )
        )

    for removed_binding in removed or []:
        mappings.append(
            FieldMapping(
                requirement_id=f"req_rm_{len(mappings):02d}",
                requirement=f"Rejected binding: {removed_binding.path}",
                candidate_field_paths=[],
                selected_field_path=removed_binding.path,
                status=MappingStatus.INVALID,
                explanation=removed_binding.reason,
            )
        )

    return MappingReport(mappings=mappings, schema_id=schema.schema_id)


# --------------------------------------------------------------------------- #
# Deterministic repair
# --------------------------------------------------------------------------- #
def _check_expression(
    expression: Expression, schema: NormalizedSchema, scope: Scope, removed: list[RemovedBinding]
) -> bool:
    ok = True
    for node in iter_expressions(expression):
        if node.field is None:
            continue
        try:
            resolve_value(schema, node.field, scope)
        except PathResolutionError as exc:
            removed.append(RemovedBinding(path=node.field, reason=exc.message, block_kind="conditional"))
            ok = False
    return ok


def _sanitize_inline(
    runs: list[InlineContent], schema: NormalizedSchema, scope: Scope, removed: list[RemovedBinding]
) -> list[InlineContent]:
    kept: list[InlineContent] = []
    for run in runs:
        if isinstance(run, FieldBinding):
            try:
                resolve_value(schema, run.path, scope)
            except PathResolutionError as exc:
                removed.append(RemovedBinding(path=run.path, reason=exc.message, block_kind="field"))
                continue
        kept.append(run)
    return kept


def sanitize_blocks(
    blocks: list[Block], schema: NormalizedSchema, scope: Scope, removed: list[RemovedBinding]
) -> list[Block]:
    """Drop every reference that cannot be resolved; never guess a replacement."""
    kept: list[Block] = []
    for block in blocks:
        if isinstance(block, Paragraph):
            runs = _sanitize_inline(block.runs, schema, scope, removed)
            if not runs and block.runs:
                continue
            kept.append(block.model_copy(update={"runs": runs}))
        elif isinstance(block, Heading):
            runs = _sanitize_inline(block.runs, schema, scope, removed)
            if not runs:
                continue
            kept.append(block.model_copy(update={"runs": runs}))
        elif isinstance(block, ImageBinding):
            try:
                resolve_value(schema, block.path, scope)
            except PathResolutionError as exc:
                removed.append(RemovedBinding(path=block.path, reason=exc.message, block_kind="image"))
                continue
            kept.append(block)
        elif isinstance(block, Repeat):
            try:
                collection = resolve_collection(schema, block.path, scope)
            except PathResolutionError as exc:
                removed.append(
                    RemovedBinding(path=block.path, reason=exc.message, block_kind="repeat")
                )
                continue
            child_scope = scope.push(block.alias, collection.absolute)
            children = sanitize_blocks(block.blocks, schema, child_scope, removed)
            if not children:
                continue
            kept.append(block.model_copy(update={"blocks": children}))
        elif isinstance(block, Conditional):
            if not _check_expression(block.condition, schema, scope, removed):
                continue
            then_blocks = sanitize_blocks(block.then_blocks, schema, scope, removed)
            if not then_blocks:
                continue
            else_blocks = sanitize_blocks(block.else_blocks or [], schema, scope, removed)
            kept.append(
                block.model_copy(update={"then_blocks": then_blocks, "else_blocks": else_blocks or None})
            )
        elif isinstance(block, Table):
            table_scope = scope
            updates: dict[str, Any] = {}
            if block.repeat is not None:
                try:
                    collection = resolve_collection(schema, block.repeat.path, scope)
                except PathResolutionError as exc:
                    removed.append(
                        RemovedBinding(path=block.repeat.path, reason=exc.message, block_kind="table")
                    )
                    continue
                table_scope = scope.push(block.repeat.alias, collection.absolute)
            if block.row_template is not None:
                updates["row_template"] = [
                    Cell(blocks=sanitize_blocks(cell.blocks, schema, table_scope, removed))
                    for cell in block.row_template
                ]
            updates["rows"] = [
                type(row)(
                    cells=[
                        Cell(blocks=sanitize_blocks(cell.blocks, schema, scope, removed))
                        for cell in row.cells
                    ]
                )
                for row in block.rows
            ]
            kept.append(block.model_copy(update=updates))
        else:  # pragma: no cover - defensive against future block kinds
            kept.append(block)
    return kept


def sanitize_document(
    document: Document, schema: NormalizedSchema
) -> tuple[Document, list[RemovedBinding]]:
    removed: list[RemovedBinding] = []
    sections: list[Section] = []
    root_scope = Scope()
    for section in document.sections:
        body = sanitize_blocks(section.body, schema, root_scope, removed)
        header = sanitize_blocks(section.header or [], schema, root_scope, removed)
        footer = sanitize_blocks(section.footer or [], schema, root_scope, removed)
        if not body:
            removed.append(
                RemovedBinding(
                    path=section.name,
                    reason="Section body referenced only unknown fields and became empty",
                    block_kind="section",
                )
            )
            continue
        sections.append(
            section.model_copy(
                update={"body": body, "header": header or None, "footer": footer or None}
            )
        )
    if not sections:
        raise InvalidInputError(
            "The plan contained no usable content",
            details={"removed_bindings": [item.model_dump() for item in removed[:20]]},
        )
    return document.model_copy(update={"sections": sections}), removed


# --------------------------------------------------------------------------- #
# Planner
# --------------------------------------------------------------------------- #
class TemplatePlanner:
    """Provider-agnostic planning with deterministic post-processing."""

    def __init__(self, gateway: LLMGateway) -> None:
        self._gateway = gateway

    async def plan(
        self,
        schema: NormalizedSchema,
        requirement: str,
        *,
        provider: str = "mock",
        model: str | None = None,
        options: PlanOptions | None = None,
    ) -> PlanOutcome:
        resolved_options = options or PlanOptions()
        if not requirement.strip():
            raise InvalidInputError("A requirement prompt is required")

        messages = build_messages(
            schema,
            requirement,
            design_style=resolved_options.design_style.value,
            language=resolved_options.language,
            target=resolved_options.target.value,
        )
        if provider == "mock":
            self._install_baseline_responder(schema, requirement, resolved_options)

        result = await self._generate_with_repair(
            provider=provider,
            model=model,
            messages=messages,
            attempts=resolved_options.max_repair_attempts + 1,
        )
        try:
            document = Document.model_validate(result.content)
        except ValidationError as exc:  # pragma: no cover - gateway already validates
            raise ProviderError(
                "The planner returned an invalid Template IR",
                code="plan_invalid",
                details={"errors": exc.error_count()},
            ) from exc

        document = document.model_copy(update={"target": resolved_options.target})
        sanitized, removed = sanitize_document(document, schema)
        mapping = build_mapping_report(schema, sanitized, requirement, removed)
        repairs = [
            f"Removed {len(removed)} unresolvable reference(s) before compilation"
        ] if removed else []
        warnings: list[str] = []
        if provider != "mock" and sanitized.metadata.generator != BASELINE_VERSION:
            sanitized = sanitized.model_copy(
                update={
                    "metadata": sanitized.metadata.model_copy(
                        update={"generator": f"{provider}/{result.model}"}
                    )
                }
            )
        if mapping.blocking():
            warnings.append(
                f"{len(mapping.blocking())} requirement(s) need review before compilation"
            )
        return PlanOutcome(
            document=sanitized,
            mapping=mapping,
            generation=result,
            removed_bindings=removed,
            repairs=repairs,
            warnings=warnings,
        )

    async def revise(
        self,
        schema: NormalizedSchema,
        document: Document,
        instruction: str,
        *,
        provider: str = "mock",
        model: str | None = None,
        options: PlanOptions | None = None,
    ) -> PlanOutcome:
        """Create a new IR version from a natural-language change request."""
        if not instruction.strip():
            raise InvalidInputError("A revision instruction is required")
        previous_intent = document.metadata.intent or ""
        merged = f"{previous_intent}\nRevision request: {instruction}"[:2_000]
        outcome = await self.plan(
            schema, merged, provider=provider, model=model, options=options
        )
        changes = diff_documents(document, outcome.document)
        return outcome.model_copy(update={"changed": changes})

    def change_summary(self, outcome: PlanOutcome) -> dict[str, Any]:
        return summarize_changes(outcome.changed)

    # ------------------------------------------------------------- internals
    async def _generate_with_repair(
        self,
        *,
        provider: str,
        model: str | None,
        messages: list,
        attempts: int,
    ) -> GenerationResult:
        last_error: ProviderError | None = None
        for attempt in range(1, max(1, attempts) + 1):
            try:
                return await self._gateway.generate_structured(
                    provider=provider, model=model, messages=messages, schema=Document
                )
            except ProviderError as exc:
                last_error = exc
                if attempt >= attempts or exc.code not in {"provider_invalid_output", "plan_invalid"}:
                    raise
                messages = [*messages, build_repair_message(exc.details.get("errors", []))]
        raise last_error or ProviderError(  # pragma: no cover - defensive
            "The provider produced no usable output",
            details={"provider": provider},
        )

    def _install_baseline_responder(
        self, schema: NormalizedSchema, requirement: str, options: PlanOptions
    ) -> None:
        def respond(_messages: list, _schema: dict) -> dict[str, Any]:
            document = build_document(
                schema,
                requirement,
                design_style=options.design_style.value,
                language=options.language,
                target=options.target.value,
            )
            return document.model_dump(mode="json")

        self._gateway.mock.set_responder(respond)


__all__ = [
    "PlanOptions",
    "PlanOutcome",
    "RemovedBinding",
    "TemplatePlanner",
    "build_mapping_report",
    "extract_requirements",
    "sanitize_blocks",
    "sanitize_document",
]
