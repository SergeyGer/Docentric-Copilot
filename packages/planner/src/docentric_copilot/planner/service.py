"""Template planning service (FR-02, FR-03, FR-08).

The planner is the only component that talks to a model. Its output is never
trusted: every candidate document passes through a deterministic repair pass that
removes bindings which do not exist in the schema, and a mapping report records
what was accepted, what was dropped and what still needs a human decision.
"""

from __future__ import annotations

import re
from typing import Any

from docentric_copilot.ddsp_parser.models import NormalizedSchema
from docentric_copilot.errors import InvalidInputError, ProviderError
from docentric_copilot.llm.gateway import LLMGateway
from docentric_copilot.llm.models import GenerationResult
from docentric_copilot.schema_resolver.concept_match import matches_kind, paths_for_concept
from docentric_copilot.schema_resolver.mapping import (
    FieldMapping,
    MappingReport,
    MappingStatus,
    RequirementKind,
)
from docentric_copilot.schema_resolver.paths import (
    PathResolutionError,
    Scope,
    resolve_collection,
    resolve_value,
)
from docentric_copilot.schema_resolver.requirements import (
    CONCEPT_QUERY,
    Concept,
    Requirement,
    _match_concept,
    parse_requirements,
    split_clauses,
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
from pydantic import BaseModel, ConfigDict, ValidationError

from .heuristic import BASELINE_VERSION, build_document
from .prompt import build_messages, build_repair_message
from .revision_ops import apply_revision
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
    """Return the reviewable clauses of a brief (interpretation lives in the parser)."""
    parsed = parse_requirements(requirement)
    if parsed.requirements:
        return [item.text for item in parsed.requirements][:limit]
    return [clause[:200] for clause in split_clauses(requirement, limit=limit)]


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
                for expression in iter_expressions(block.condition):
                    if expression.field is None:
                        continue
                    try:
                        used[expression.field] = resolve_value(
                            schema, expression.field, scope
                        ).absolute
                    except PathResolutionError:
                        continue
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


def absolute_bindings(document: Document, schema: NormalizedSchema) -> list[str]:
    """Return every binding as an absolute schema path (aliases resolved)."""
    return sorted(set(_used_paths(document, schema).values()))


def _bound_for_concept(
    schema: NormalizedSchema, concept: Concept, bound_paths: set[str]
) -> list[str]:
    return paths_for_concept(schema, concept, bound_paths)


def _candidates_for(
    schema: NormalizedSchema, requirement: Requirement, limit: int = 4
) -> list[Candidate]:
    query = f"{requirement.text} {CONCEPT_QUERY.get(requirement.concept, '')}".strip()
    candidates = search_candidates(
        schema,
        query,
        kind=requirement.kind,
        limit=limit,
        include_collections=requirement.kind is RequirementKind.COLLECTION,
    )
    return [
        candidate
        for candidate in candidates
        if matches_kind(requirement.kind, schema.node(candidate.path))
    ] or candidates


def _ambiguity(candidates: list[Candidate]) -> bool:
    if len(candidates) < 2:
        return False
    gap = candidates[0].score - candidates[1].score
    return gap < max(0.03, 0.15 * candidates[0].score)


_PARTY_TOKENS = {"customer", "client", "billto", "soldto", "vendor", "supplier", "buyer"}
_COMPANY_TOKENS = {"company", "issuer", "organization", "organisation"}
_LINE_TOKENS = {"line", "item", "product", "row"}


def _disambiguated(requirement: Requirement) -> bool:
    """True when the clause itself names the object the concept belongs to."""
    tokens = set(tokenize(requirement.text))
    groups = {
        Concept.COMPANY_LOGO: _COMPANY_TOKENS | {"logo"},
        Concept.COMPANY_NAME: _COMPANY_TOKENS,
        Concept.COMPANY_ADDRESS: _COMPANY_TOKENS,
        Concept.COMPANY_VAT: _COMPANY_TOKENS,
        Concept.CUSTOMER_NAME: _PARTY_TOKENS,
        Concept.CUSTOMER_ADDRESS: _PARTY_TOKENS,
        Concept.CUSTOMER_VAT: _PARTY_TOKENS,
        Concept.CUSTOMER_ACCOUNT: _PARTY_TOKENS,
        Concept.LINE_QUANTITY: _LINE_TOKENS | {"quantity", "qty"},
        Concept.LINE_PRICE: _LINE_TOKENS | {"price", "unit"},
        Concept.LINE_AMOUNT: _LINE_TOKENS | {"amount"},
    }
    expected = groups.get(requirement.concept)
    if expected is None:
        return True
    return bool(tokens & expected)


def _evidence_score(
    requirement: Requirement,
    bound: list[str],
    schema: NormalizedSchema,
    *,
    disambiguated: bool,
) -> tuple[float, list[str]]:
    """Deterministic semantic confidence for a bound requirement."""
    score = 0.55
    reasons: list[str] = []
    node = schema.node(bound[0])
    name_tokens = set(tokenize(bound[0].rsplit(".", 1)[-1]))
    concept_tokens = set(tokenize(CONCEPT_QUERY.get(requirement.concept, "")))
    if concept_tokens & name_tokens:
        score += 0.2
        reasons.append("the field name matches the requested concept")
    if node is not None and matches_kind(requirement.kind, node):
        score += 0.1
        reasons.append("the value type matches")
    if disambiguated:
        score += 0.1
        reasons.append("the brief names the object explicitly")
    if len(bound) == 1:
        score += 0.05
    return min(0.99, score), reasons


_COUNTERPARTS = {
    Concept.CUSTOMER_NAME: Concept.COMPANY_NAME,
    Concept.CUSTOMER_ADDRESS: Concept.COMPANY_ADDRESS,
    Concept.CUSTOMER_VAT: Concept.COMPANY_VAT,
}


def _counterpart_candidates(
    requirement: Requirement, schema: NormalizedSchema, bound_absolute: set[str]
) -> list[str]:
    """The other object's field when the brief does not say whose field it means."""
    counterpart = _COUNTERPARTS.get(requirement.concept)
    if counterpart is None or _disambiguated(requirement):
        return []
    return _bound_for_concept(schema, counterpart, bound_absolute)


def _conflict_for(
    requirement: Requirement, selected: str, existing: list[FieldMapping]
) -> str | None:
    for mapping in existing:
        if mapping.selected_field_path != selected:
            continue
        if mapping.concept and mapping.concept != requirement.concept.value:
            return mapping.requirement_id
    return None


def _status_for(score: float, *, conflict: bool) -> MappingStatus:
    if conflict:
        return MappingStatus.CONFLICT
    if score >= 0.9:
        return MappingStatus.CONFIRMED
    if score >= 0.8:
        return MappingStatus.SCHEMA_VALID
    return MappingStatus.NEEDS_REVIEW


def _explain(
    status: MappingStatus, requirement: Requirement, bound: list[str], reasons: list[str]
) -> str:
    if status is MappingStatus.NEEDS_REVIEW:
        return (
            "Technically valid, but the evidence is not strong enough to confirm silently: "
            + "; ".join(reasons)
            + "."
        )
    if status is MappingStatus.CONFIRMED:
        detail = f"Bound to {len(bound)} field(s)" if len(bound) > 1 else "Bound"
        return f"{detail}. " + "; ".join(reason.capitalize() for reason in reasons) + "."
    return "Schema-valid binding with partial semantic evidence; review is recommended."


def build_mapping_report(
    schema: NormalizedSchema,
    document: Document,
    requirement: str,
    removed: list[RemovedBinding] | None = None,
) -> MappingReport:
    """Derive a reviewable requirement-to-field report from the produced IR.

    Requirements are interpreted first (concept, value type, requested placement),
    then matched against the paths the template actually binds. A clause is
    ``resolved`` only when a bound path satisfies its concept; a confident
    alternative the plan ignores is reported as ``missing``; two equally good
    alternatives are reported as ``needs_review`` even when one of them is bound.
    """
    used = _used_paths(document, schema)
    bound_absolute = set(used.values())
    parsed = parse_requirements(requirement)
    mappings: list[FieldMapping] = []

    for item in parsed:
        if item.concept is Concept.TITLE:
            mappings.append(
                FieldMapping(
                    requirement_id=item.id,
                    requirement=item.text,
                    concept=item.concept.value,
                    status=MappingStatus.CONFIRMED,
                    confidence_score=1.0,
                    evidence_score=1.0,
                    explanation="Satisfied by the document title and layout.",
                )
            )
            continue
        bound = _bound_for_concept(schema, item.concept, bound_absolute)
        candidates = _candidates_for(schema, item)
        candidate_paths = [candidate.path for candidate in candidates]
        top = candidates[0] if candidates else None
        node = schema.node(bound[0]) if bound else None

        if item.negated:
            if bound:
                mappings.append(
                    FieldMapping(
                        requirement_id=item.id,
                        requirement=item.text,
                        concept=item.concept.value,
                        placement=item.placement.value if item.placement else None,
                        candidate_field_paths=candidate_paths,
                        selected_field_path=bound[0],
                        supporting_field_paths=bound[:10],
                        data_type=node.data_type if node else None,
                        status=MappingStatus.INVALID,
                        confidence_score=1.0,
                        explanation="The brief asks to exclude this content, but the plan still binds it.",
                    )
                )
            else:
                mappings.append(
                    FieldMapping(
                        requirement_id=item.id,
                        requirement=item.text,
                        concept=item.concept.value,
                        placement=item.placement.value if item.placement else None,
                        status=MappingStatus.CONFIRMED,
                        confidence_score=1.0,
                        evidence_score=1.0,
                        explanation="Content is intentionally excluded, as requested.",
                    )
                )
            continue

        if bound:
            competitors = [candidate.path for candidate in candidates[:2]]
            covered = all(path in bound_absolute for path in competitors)
            ambiguous = _ambiguity(candidates) and candidates[0].path not in bound and not covered
            counterparts = _counterpart_candidates(item, schema, bound_absolute)
            score, reasons = _evidence_score(
                item, bound, schema, disambiguated=_disambiguated(item)
            )
            if counterparts:
                score = max(0.0, score - 0.2)
                reasons.append(
                    "both the customer and the company expose this value and the brief does not say which"
                )
                candidate_paths = list(dict.fromkeys([*bound, *counterparts, *candidate_paths]))[:6]
            if ambiguous:
                score = max(0.0, score - 0.3)
                reasons.append("a competing field matches almost as well")
            conflict_with = _conflict_for(item, bound[0], mappings)
            if conflict_with is not None:
                score = max(0.0, score - 0.35)
                reasons.append(f"field already used by {conflict_with}")
            status = _status_for(score, conflict=conflict_with is not None)
            explanation = _explain(status, item, bound, reasons)
            mappings.append(
                FieldMapping(
                    requirement_id=item.id,
                    requirement=item.text,
                    concept=item.concept.value,
                    placement=item.placement.value if item.placement else None,
                    candidate_field_paths=candidate_paths,
                    selected_field_path=bound[0],
                    supporting_field_paths=bound[:10],
                    data_type=node.data_type if node else None,
                    schema_evidence=f"{bound[0]}:{node.data_type if node else 'any'}",
                    status=status,
                    confidence_score=round(score, 3),
                    evidence_score=round(score, 3),
                    conflict=conflict_with is not None,
                    conflicts_with=[conflict_with] if conflict_with else [],
                    explanation=explanation,
                )
            )
            continue

        decision = decide_status(candidates)
        status = MappingStatus.NEEDS_REVIEW if decision == "ambiguous" else MappingStatus.MISSING
        explanation = (
            "Several fields match the requirement equally well; confirm the choice."
            if status is MappingStatus.NEEDS_REVIEW
            else (
                "A matching field exists but the template does not use it; accept the suggestion or refine the brief."
                if decision == "resolved"
                else "No field in the schema satisfies this requirement."
            )
        )
        mappings.append(
            FieldMapping(
                requirement_id=item.id,
                requirement=item.text,
                concept=item.concept.value,
                placement=item.placement.value if item.placement else None,
                candidate_field_paths=candidate_paths,
                selected_field_path=None,
                status=status,
                confidence_score=top.score if top else None,
                explanation=explanation,
            )
        )

    # Clauses the lexicon cannot interpret are still reported, so a user can see
    # that something was asked for and not satisfied.
    recognised_texts = {item.text for item in parsed}
    unrecognised = [
        clause
        for clause in split_clauses(requirement)
        if clause not in recognised_texts and _match_concept(clause, used=set()) is None
    ]
    for index, clause in enumerate(unrecognised):
        kind = infer_kind(clause)
        candidates = search_candidates(schema, clause, kind=kind, limit=4)
        decision = decide_status(candidates)
        status = MappingStatus.NEEDS_REVIEW if decision == "ambiguous" else MappingStatus.MISSING
        mappings.append(
            FieldMapping(
                requirement_id=f"req_x{index:02d}",
                requirement=clause,
                candidate_field_paths=[candidate.path for candidate in candidates],
                status=status,
                confidence_score=candidates[0].score if candidates else None,
                explanation=(
                    "No recognised document concept in this clause; the planner cannot bind it."
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
            removed.append(
                RemovedBinding(path=node.field, reason=exc.message, block_kind="conditional")
            )
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
                removed.append(
                    RemovedBinding(path=run.path, reason=exc.message, block_kind="field")
                )
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
                removed.append(
                    RemovedBinding(path=block.path, reason=exc.message, block_kind="image")
                )
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
                block.model_copy(
                    update={"then_blocks": then_blocks, "else_blocks": else_blocks or None}
                )
            )
        elif isinstance(block, Table):
            table_scope = scope
            updates: dict[str, Any] = {}
            if block.repeat is not None:
                try:
                    collection = resolve_collection(schema, block.repeat.path, scope)
                except PathResolutionError as exc:
                    removed.append(
                        RemovedBinding(
                            path=block.repeat.path, reason=exc.message, block_kind="table"
                        )
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
        budget_usd: float | None = None,
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
            budget_usd=budget_usd,
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
        repairs = (
            [f"Removed {len(removed)} unresolvable reference(s) before compilation"]
            if removed
            else []
        )
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
        """Create a new IR version from a natural-language change request.

        A clear structural instruction is applied as a targeted edit, which keeps
        the diff small and makes no model call. Anything else falls back to
        replanning with the combined intent.
        """
        if not instruction.strip():
            raise InvalidInputError("A revision instruction is required")
        previous_intent = document.metadata.intent or ""
        merged = f"{previous_intent}\nRevision request: {instruction}"[:2_000]

        targeted = apply_revision(document, instruction, schema)
        if targeted is not None:
            sanitized, removed = sanitize_document(targeted.document, schema)
            mapping = build_mapping_report(schema, sanitized, merged, removed)
            changes = diff_documents(document, sanitized)
            return PlanOutcome(
                document=sanitized,
                mapping=mapping,
                generation=None,
                removed_bindings=removed,
                repairs=targeted.notes,
                warnings=[],
                changed=changes,
            )

        outcome = await self.plan(schema, merged, provider=provider, model=model, options=options)
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
        budget_usd: float | None = None,
    ) -> GenerationResult:
        last_error: ProviderError | None = None
        for attempt in range(1, max(1, attempts) + 1):
            try:
                return await self._gateway.generate_structured(
                    provider=provider,
                    model=model,
                    messages=messages,
                    schema=Document,
                    budget_usd=budget_usd,
                )
            except ProviderError as exc:
                last_error = exc
                if attempt >= attempts or exc.code not in {
                    "provider_invalid_output",
                    "plan_invalid",
                }:
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
    "absolute_bindings",
    "build_mapping_report",
    "extract_requirements",
    "sanitize_blocks",
    "sanitize_document",
]
