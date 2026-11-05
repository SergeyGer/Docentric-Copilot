"""Template planning service (FR-02, FR-03, FR-08).

The planner is the only component that talks to a model. Its output is never
trusted: every candidate document passes through a deterministic repair pass that
removes bindings which do not exist in the schema, and a mapping report records
what was accepted, what was dropped and what still needs a human decision.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from docentric_copilot.ddsp_parser.models import NormalizedSchema
from docentric_copilot.errors import InvalidInputError, PlanInvalidError, ProviderError
from docentric_copilot.llm.gateway import LLMGateway
from docentric_copilot.llm.models import GenerationResult, Message
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

from .candidates import CandidateSet, retrieve_candidates, type_matches
from .compact_ir import (
    COMPACT_GENERATOR,
    COMPACT_TEMPLATE_NAME,
    build_compact_messages,
    compact_schema,
    expand_compact,
)
from .compact_ir_v2 import (
    build_compact_messages_v2,
    compact_schema_v2,
    expand_compact_v2,
)
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
    #: Ask the provider for the compact wire format and expand it deterministically.
    #: Off by default so existing callers keep the full-IR contract.
    compact_ir: bool = False
    #: Wire-format revision used when ``compact_ir`` is on. v2 is the
    #: ultra-compact array format used for Gemini; v1 stays available for
    #: back-compat and for callers that pin the older readable format.
    compact_version: Literal["v1", "v2"] = "v2"
    #: Restrict the provider prompt to evidence-backed candidate bindings.
    #: On by default since v0.11; set False only for a deliberate v0.10 replay.
    candidate_filter: bool = True


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
    candidate_summary: dict[str, Any] = {}
    binding_reviews: list[dict[str, Any]] = []


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
    *,
    candidate_set: CandidateSet | None = None,
    binding_reviews: Sequence[Mapping[str, Any]] | None = None,
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

    if candidate_set is not None:
        reviews = (
            list(binding_reviews)
            if binding_reviews is not None
            else [review.to_dict() for review in review_bindings(document, schema, candidate_set)]
        )
        reviewed_paths = {
            mapping.selected_field_path
            for mapping in mappings
            if mapping.selected_field_path is not None
        }
        for atom in candidate_set.atoms:
            if atom.collection:
                # Collection scope is represented by the produced table/repeat
                # block and by the scope column of its fields; it is not a
                # binding requirement and must not create an abstention row.
                continue
            evidence = candidate_set.for_requirement(atom.id)
            review_bound: str | None = None
            for item in reviews:
                candidate_path = item.get("path")
                if not isinstance(candidate_path, str):
                    continue
                path_evidence = candidate_set.evidence_for(candidate_path)
                if path_evidence is not None and path_evidence.requirement_id == atom.id:
                    review_bound = candidate_path
                    break
            if not evidence:
                mappings.append(
                    FieldMapping(
                        requirement_id=f"req_cand_{atom.id}",
                        requirement=atom.text,
                        concept=atom.concept,
                        placement=atom.placement,
                        candidate_field_paths=[],
                        selected_field_path=None,
                        status=MappingStatus.NEEDS_REVIEW,
                        confidence_score=None,
                        explanation=(
                            "No schema evidence supports this requirement; the planner "
                            "abstained instead of inventing a path."
                        ),
                    )
                )
                continue
            if evidence[0].decision == "ambiguous":
                mappings.append(
                    FieldMapping(
                        requirement_id=f"req_cand_{atom.id}",
                        requirement=atom.text,
                        concept=atom.concept,
                        placement=atom.placement,
                        candidate_field_paths=[candidate.path for candidate in evidence],
                        selected_field_path=review_bound,
                        status=MappingStatus.NEEDS_REVIEW,
                        confidence_score=min(1.0, round(evidence[0].score, 3)),
                        explanation=(
                            "Genuine ambiguity: more than one schema path is defensible; "
                            "confirm the choice."
                        ),
                    )
                )
        for review in reviews:
            if review.get("status") != "needs_review":
                continue
            path = str(review.get("path") or "")
            if not path or path in reviewed_paths:
                continue
            mappings.append(
                FieldMapping(
                    requirement_id=(
                        "req_review_" + hashlib.sha1(path.encode("utf-8")).hexdigest()[:8]
                    ),
                    requirement=f"Unverified binding: {path}",
                    candidate_field_paths=list(review.get("candidate_paths") or []),
                    selected_field_path=path,
                    schema_evidence=f"{path}:{review.get('actual_type') or 'any'}",
                    status=MappingStatus.NEEDS_REVIEW,
                    confidence_score=review.get("score"),
                    explanation=str(review.get("reason") or "needs review"),
                )
            )
            reviewed_paths.add(path)

    return MappingReport(mappings=mappings, schema_id=schema.schema_id)


# --------------------------------------------------------------------------- #
# Post-generation binding review
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class BindingReview:
    """Deterministic verdict for one emitted binding."""

    path: str
    status: str
    reason: str
    requirement_id: str | None
    expected_type: str | None
    actual_type: str | None
    scope: str | None
    contexts: tuple[str, ...] = ()
    candidate_paths: tuple[str, ...] = ()
    score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "status": self.status,
            "reason": self.reason,
            "requirement_id": self.requirement_id,
            "expected_type": self.expected_type,
            "actual_type": self.actual_type,
            "scope": self.scope,
            "contexts": list(self.contexts),
            "candidate_paths": list(self.candidate_paths),
            "score": self.score,
        }


def _binding_contexts(
    document: Document, schema: NormalizedSchema
) -> dict[str, tuple[str | None, set[str]]]:
    """Return ``{absolute_path: (data_type, contexts)}`` for produced bindings."""
    observed: dict[str, tuple[str | None, set[str]]] = {}

    def note(path: str, data_type: str | None, contexts: set[str]) -> None:
        existing = observed.get(path)
        if existing is None:
            observed[path] = (data_type, set(contexts))
        else:
            existing[1].update(contexts)

    def walk(
        blocks: list[Block], scope: Scope, base: str, *, repeat: bool, conditional: bool
    ) -> None:
        contexts = {base}
        if repeat:
            contexts.add("repeat")
        if conditional:
            contexts.add("conditional")
        for block in blocks:
            if isinstance(block, Paragraph | Heading):
                for run in block.runs:
                    if not isinstance(run, FieldBinding):
                        continue
                    try:
                        resolved = resolve_value(schema, run.path, scope).absolute
                    except PathResolutionError:
                        continue
                    resolved_node = schema.node(resolved)
                    note(
                        resolved,
                        resolved_node.data_type if resolved_node is not None else None,
                        contexts,
                    )
            elif isinstance(block, ImageBinding):
                try:
                    resolved = resolve_value(schema, block.path, scope).absolute
                except PathResolutionError:
                    continue
                note(resolved, "image", contexts)
            elif isinstance(block, Repeat):
                try:
                    collection = resolve_collection(schema, block.path, scope)
                except PathResolutionError:
                    continue
                note(collection.absolute, "collection", contexts)
                walk(
                    block.blocks,
                    scope.push(block.alias, collection.absolute),
                    base,
                    repeat=True,
                    conditional=conditional,
                )
            elif isinstance(block, Conditional):
                for expression in iter_expressions(block.condition):
                    if expression.field is None:
                        continue
                    try:
                        resolved = resolve_value(schema, expression.field, scope).absolute
                    except PathResolutionError:
                        continue
                    node = schema.node(resolved)
                    note(resolved, node.data_type if node else None, {*contexts, "conditional"})
                walk(block.then_blocks, scope, base, repeat=repeat, conditional=True)
                walk(block.else_blocks or [], scope, base, repeat=repeat, conditional=True)
            elif isinstance(block, Table):
                table_scope = scope
                if block.repeat is not None:
                    try:
                        collection = resolve_collection(schema, block.repeat.path, scope)
                    except PathResolutionError:
                        collection = None
                    if collection is not None:
                        note(collection.absolute, "collection", contexts)
                        table_scope = scope.push(block.repeat.alias, collection.absolute)
                for row in block.rows:
                    for cell in row.cells:
                        walk(cell.blocks, scope, base, repeat=repeat, conditional=conditional)
                for cell in block.row_template or []:
                    walk(cell.blocks, table_scope, base, repeat=True, conditional=conditional)

    for section in document.sections:
        walk(section.body, Scope(), "body", repeat=False, conditional=False)
        walk(section.header or [], Scope(), "header", repeat=False, conditional=False)
        walk(section.footer or [], Scope(), "footer", repeat=False, conditional=False)
    return observed


def review_bindings(
    document: Document, schema: NormalizedSchema, candidate_set: CandidateSet | None
) -> list[BindingReview]:
    """Re-validate every binding against existence, type and scope evidence.

    A path that resolves but has no candidate evidence is marked ``needs_review``
    instead of being silently accepted as a confirmed binding.
    """
    if candidate_set is None:
        return []
    reviews: list[BindingReview] = []
    for path, (data_type, contexts) in sorted(_binding_contexts(document, schema).items()):
        evidence = candidate_set.evidence_for(path)
        if not schema.has_path(path):
            reviews.append(
                BindingReview(
                    path=path,
                    status="rejected",
                    reason="the path does not exist in the schema",
                    requirement_id=None,
                    expected_type=None,
                    actual_type=data_type,
                    scope=None,
                    contexts=tuple(sorted(contexts)),
                )
            )
            continue
        if evidence is None:
            reviews.append(
                BindingReview(
                    path=path,
                    status="needs_review",
                    reason=(
                        "the path is schema-valid but was not supported by the retrieved "
                        "candidate evidence for this brief"
                    ),
                    requirement_id=None,
                    expected_type=None,
                    actual_type=data_type,
                    scope=None,
                    contexts=tuple(sorted(contexts)),
                )
            )
            continue
        candidates = candidate_set.for_requirement(evidence.requirement_id)
        candidate_paths = tuple(candidate.path for candidate in candidates)
        if not type_matches(evidence.expected_type, data_type):
            reviews.append(
                BindingReview(
                    path=path,
                    status="needs_review",
                    reason=(
                        f"type mismatch: the requirement expects {evidence.expected_type!r}, "
                        f"the binding has {data_type!r}"
                    ),
                    requirement_id=evidence.requirement_id,
                    expected_type=evidence.expected_type,
                    actual_type=data_type,
                    scope=evidence.scope,
                    contexts=tuple(sorted(contexts)),
                    candidate_paths=candidate_paths,
                    score=evidence.score,
                )
            )
            continue
        if evidence.scope and "repeat" not in contexts:
            reviews.append(
                BindingReview(
                    path=path,
                    status="needs_review",
                    reason=(
                        "collection scope mismatch: the path belongs to "
                        f"{evidence.scope!r} but the binding is outside a repeat/table row"
                    ),
                    requirement_id=evidence.requirement_id,
                    expected_type=evidence.expected_type,
                    actual_type=data_type,
                    scope=evidence.scope,
                    contexts=tuple(sorted(contexts)),
                    candidate_paths=candidate_paths,
                    score=evidence.score,
                )
            )
            continue
        reviews.append(
            BindingReview(
                path=path,
                status="accepted",
                reason=(
                    "one of several defensible alternatives"
                    if evidence.decision == "ambiguous"
                    else "exists, type and scope match the retrieved evidence"
                ),
                requirement_id=evidence.requirement_id,
                expected_type=evidence.expected_type,
                actual_type=data_type,
                scope=evidence.scope,
                contexts=tuple(sorted(contexts)),
                candidate_paths=candidate_paths,
                score=evidence.score,
            )
        )
    return reviews


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
        if not body and not header and not footer:
            removed.append(
                RemovedBinding(
                    path=section.name,
                    reason="Section body, header and footer referenced only unknown fields and became empty",
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

        candidate_set = (
            retrieve_candidates(schema, requirement) if resolved_options.candidate_filter else None
        )
        candidate_text = None
        if candidate_set is not None and candidate_set.atoms and not candidate_set.fallback:
            candidate_text = candidate_set.format_prompt()

        if resolved_options.compact_ir:
            build_messages_for_compact = (
                build_compact_messages
                if resolved_options.compact_version == "v1"
                else build_compact_messages_v2
            )
            messages = build_messages_for_compact(
                schema,
                requirement,
                design_style=resolved_options.design_style.value,
                language=resolved_options.language,
                target=resolved_options.target.value,
                candidates=candidate_text,
            )
        else:
            messages = build_messages(
                schema,
                requirement,
                design_style=resolved_options.design_style.value,
                language=resolved_options.language,
                target=resolved_options.target.value,
                candidates=candidate_text,
            )
        if provider == "mock":
            self._install_baseline_responder(schema, requirement, resolved_options)

        result, document = await self._generate_with_repair(
            provider=provider,
            model=model,
            messages=messages,
            attempts=resolved_options.max_repair_attempts + 1,
            budget_usd=budget_usd,
            compact_ir=resolved_options.compact_ir,
            compact_version=resolved_options.compact_version,
            domain_schema=schema,
        )

        document = document.model_copy(update={"target": resolved_options.target})
        sanitized, removed = sanitize_document(document, schema)
        binding_reviews = (
            review_bindings(sanitized, schema, candidate_set) if candidate_set is not None else []
        )
        mapping = build_mapping_report(
            schema,
            sanitized,
            requirement,
            removed,
            candidate_set=candidate_set,
            binding_reviews=[review.to_dict() for review in binding_reviews],
        )
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
            candidate_summary=(
                candidate_set.summary() if candidate_set is not None else {"enabled": False}
            ),
            binding_reviews=[review.to_dict() for review in binding_reviews],
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

        resolved_options = options
        if resolved_options is None and document.metadata.template_name == COMPACT_TEMPLATE_NAME:
            # A document produced by the compact wire format replans through the
            # same format by default: its IR has already lost the compact-only
            # metadata, so this keeps the provider budget predictable.
            resolved_options = PlanOptions(
                language=document.language,
                design_style=document.metadata.design_style or DesignStyle.MODERN,
                target=document.target,
                compact_ir=True,
                # A v1 document replans through v1 so its payload keeps the
                # same wire contract; everything else uses v2.
                compact_version=(
                    "v1" if document.metadata.generator == COMPACT_GENERATOR else "v2"
                ),
            )

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

        outcome = await self.plan(
            schema, merged, provider=provider, model=model, options=resolved_options
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
        messages: list[Message],
        attempts: int,
        budget_usd: float | None = None,
        compact_ir: bool = False,
        compact_version: str = "v2",
        domain_schema: NormalizedSchema | None = None,
    ) -> tuple[GenerationResult, Document]:
        """Generate, validate/expand, and retry repairable failures.

        In compact mode the provider validates against the compact schema and
        the payload is expanded here, so an expansion error is as repairable as a
        JSON-schema error: the next attempt keeps the compact schema and receives
        the offending paths in the repair message.
        """
        last_error: ProviderError | PlanInvalidError | None = None
        current_messages = list(messages)
        expand: Callable[[dict[str, Any], NormalizedSchema], Document] | None = None
        response_schema: type[BaseModel] | dict[str, Any] = Document
        if compact_ir:
            if compact_version == "v2":
                response_schema = compact_schema_v2()
                expand = expand_compact_v2
            else:
                response_schema = compact_schema()
                expand = expand_compact
        # Gemini's structured-output converter cannot express v2's positional
        # arrays without inventing a union that encourages empty objects. The
        # v2 prompt is precise enough on its own, so Gemini gets JSON mode
        # without a responseSchema; the expander remains the validator.
        guided_schema = not (compact_ir and compact_version == "v2" and provider == "gemini")
        for attempt in range(1, max(1, attempts) + 1):
            try:
                result = await self._gateway.generate_structured(
                    provider=provider,
                    model=model,
                    messages=current_messages,
                    schema=response_schema,
                    response_schema=guided_schema,
                    budget_usd=budget_usd,
                )
                if compact_ir:
                    if domain_schema is None or expand is None:  # pragma: no cover
                        raise InvalidInputError("Compact planning requires the normalized schema")
                    document = expand(result.content, domain_schema)
                else:
                    try:
                        document = Document.model_validate(result.content)
                    except ValidationError as exc:
                        raise ProviderError(
                            "The planner returned an invalid Template IR",
                            code="plan_invalid",
                            details={
                                "errors": [
                                    {
                                        "location": ".".join(str(part) for part in error["loc"]),
                                        "message": error["msg"],
                                    }
                                    for error in exc.errors()[:10]
                                ]
                            },
                        ) from exc
                return result, document
            except PlanInvalidError as exc:
                last_error = exc
                if attempt >= attempts:
                    raise
                current_messages = [
                    *current_messages,
                    build_repair_message(exc.details.get("errors") or [exc.message]),
                ]
            except ProviderError as exc:
                last_error = exc
                if attempt >= attempts or exc.code not in {
                    "provider_invalid_output",
                    "plan_invalid",
                }:
                    raise
                current_messages = [
                    *current_messages,
                    build_repair_message(exc.details.get("errors", [])),
                ]
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
    "BindingReview",
    "PlanOptions",
    "PlanOutcome",
    "RemovedBinding",
    "TemplatePlanner",
    "absolute_bindings",
    "build_mapping_report",
    "extract_requirements",
    "review_bindings",
    "sanitize_blocks",
    "sanitize_document",
]
