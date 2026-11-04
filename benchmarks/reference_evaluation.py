#!/usr/bin/env python3
"""Reference-based semantic evaluation (REF-05).

The evaluator answers a different question from a generic field benchmark: *does
a generated plan reproduce the semantic patterns observed in a reference
template?* It maps inspected reference controls to five concepts:

===========  ===============  ==============================
Reference    Expected concept  Produced plan evidence
===========  ===============  ==============================
Field        scalar            field binding
List         collection        repeat/table collection
If           condition         conditional expression
Image        image             image binding
Label        text              field binding (text role)
===========  ===============  ==============================

Two modes are supported:

``--cases``
    The committed synthetic gold set. Each case has a synthetic DOCX reference,
    a synthetic DDSP and hand-authored expected patterns. No corpus content is
    used and no paid calls are required (the default provider is ``mock``).

``--reference PATH``
    Inspect a DOCX/AXPP at runtime and evaluate a plan against the derived
    patterns. This is the only mode intended for the ignored local corpus.
    Supply ``--plan`` to score an existing IR, or ``--ddsp`` (+ optional
    prompt) to generate a plan with the deterministic or a live provider.

Metrics are separated: semantic precision/recall/coverage and type/context
correctness never absorb ``valid_template_rate`` (validation + compilation),
which is reported on its own. Cost is three-valued: verified, estimated or
unavailable. The mock provider has verified zero cost.

Usage::

    .venv/bin/python benchmarks/reference_evaluation.py --provider mock
    .venv/bin/python benchmarks/reference_evaluation.py \
        --reference .tools/reference-corpus/runtime/Example/Synthetic.docx \
        --ddsp .tools/reference-corpus/runtime/Example/Synthetic.ddsp \
        --provider mock --output-json .tools/reference-corpus/report.json
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import html
import io
import json
import re
import sys
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # pragma: no cover - import bootstrap when run as a script
    sys.path.insert(0, str(ROOT))

from docentric_copilot.config import get_settings  # noqa: E402
from docentric_copilot.ddsp_parser import (  # noqa: E402
    NormalizedSchema,
    ParsedSource,
    parse_ddsp,
)
from docentric_copilot.docx_compiler import CompileOptions, GenericDocxCompiler  # noqa: E402
from docentric_copilot.errors import CopilotError  # noqa: E402
from docentric_copilot.llm import LLMGateway  # noqa: E402
from docentric_copilot.planner import PlanOptions, TemplatePlanner  # noqa: E402
from docentric_copilot.reference import (  # noqa: E402
    EdgeType,
    ElementKind,
    NodeKind,
    ReferenceGraph,
    ReferenceInspection,
    ReferenceLimits,
    build_reference_graph,
    inspect_reference_bundle,
    parse_real_ddsp,
)
from docentric_copilot.template_ir import Document, ir_digest, load_document  # noqa: E402
from docentric_copilot.template_validator import ValidationEngine  # noqa: E402

from benchmarks.semantic_evaluation import (  # noqa: E402
    ERROR_TAXONOMY,
    _usage_cost,
    collect_produced_bindings,
    collect_produced_blocks,
    taxonomy_for_validation_codes,
)
from benchmarks.semantic_scoring import classify_exception  # noqa: E402

DEFAULT_CASES = ROOT / "benchmarks" / "reference_cases.json"
DEFAULT_JSON = ROOT / "benchmarks" / "reference_report.json"
DEFAULT_CSV = ROOT / "benchmarks" / "reference_report.csv"
DEFAULT_HTML = ROOT / "benchmarks" / "reference_report.html"
DEFAULT_PATTERNS = ("field", "list", "if", "image", "label")

MODE_CONCEPTS: Final[dict[ElementKind, tuple[str, str]]] = {
    ElementKind.FIELD: ("scalar", "field"),
    ElementKind.LABEL: ("text", "field"),
    ElementKind.LIST: ("collection", "collection"),
    ElementKind.IF: ("condition", "condition"),
    ElementKind.IMAGE: ("image", "image"),
}
UNSUPPORTED_KINDS: Final[frozenset[ElementKind]] = frozenset(
    {
        ElementKind.BARCODE,
        ElementKind.SUMMARY_FIELD,
        ElementKind.SUB_DOCUMENT,
        ElementKind.GROUP,
        ElementKind.UNKNOWN,
    }
)
_ROLE_FOR_CONCEPT: Final[dict[str, str]] = {
    "scalar": "field",
    "text": "field",
    "collection": "collection",
    "condition": "condition",
    "image": "image",
}
_TYPE_ALIASES: Final[dict[str, str]] = {
    "decimal": "number",
    "integer": "number",
    "long": "number",
    "int": "number",
    "float": "number",
    "double": "number",
    "datetime": "date",
    "dateTime": "date",
    "base64binary": "image",
    "anyuri": "string",
    "string": "string",
    "number": "number",
    "boolean": "boolean",
    "date": "date",
    "image": "image",
    "collection": "collection",
}
_SECRET = re.compile(r"(?i)(api[-_]?key|authorization|bearer)\s*[=:]\s*\S+")


# --------------------------------------------------------------------------- #
# Concepts
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class ReferenceConcept:
    """One expected reference pattern, independent of a planner name."""

    concept: str
    kind: ElementKind
    path: str
    expected_paths: tuple[str, ...] = ()
    expected_type: str | None = None
    contexts: tuple[str, ...] = ("body",)
    required: bool = True
    source: str = "reference"

    @property
    def identifier(self) -> str:
        return f"{self.concept}:{self.path}"

    @property
    def produced_role(self) -> str:
        return _ROLE_FOR_CONCEPT[self.concept]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.identifier,
            "concept": self.concept,
            "kind": self.kind.value,
            "path": self.path,
            "expected_paths": list(self.expected_paths or (self.path,)),
            "expected_type": self.expected_type,
            "contexts": list(self.contexts),
            "required": self.required,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class ConceptInventory:
    """Derived expected concepts plus explicitly excluded reference material."""

    concepts: tuple[ReferenceConcept, ...]
    unsupported: tuple[dict[str, str], ...] = ()
    unbound: tuple[dict[str, str], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "concepts": [concept.as_dict() for concept in self.concepts],
            "concept_count": len(self.concepts),
            "unsupported": list(self.unsupported),
            "unsupported_count": len(self.unsupported),
            "unbound": list(self.unbound),
            "unbound_count": len(self.unbound),
        }


def _story_context(part: str | None) -> str:
    lowered = (part or "").casefold()
    if "header" in lowered:
        return "header"
    if "footer" in lowered:
        return "footer"
    return "body"


def _fallback_path(source: str | None, raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    if cleaned.startswith("MainData.") or cleaned.startswith("GeneralData."):
        return cleaned
    relative = cleaned.lstrip("/").replace("/", ".")
    if relative.startswith("@"):
        relative = relative[1:]
    if source and source not in (".", ""):
        return f"{source}.{relative}" if relative else source
    return relative


def _element_structure(graph: ReferenceGraph) -> dict[str, set[str]]:
    """Map each element node id to its enclosing structure kinds."""
    nodes = {node.id: node for node in graph.nodes}
    ancestors: dict[str, set[str]] = {}
    changed = True
    while changed:
        changed = False
        for edge in graph.edges:
            if edge.type not in {EdgeType.ITERATES, EdgeType.CONDITION}:
                continue
            source = nodes.get(edge.source)
            target = nodes.get(edge.target)
            if source is None or target is None:
                continue
            inherited = set(ancestors.get(source.id, set()))
            if source.element_kind is ElementKind.IF:
                inherited.add("conditional")
            elif source.element_kind in {ElementKind.LIST, ElementKind.GROUP}:
                inherited.add("repeat")
            current = ancestors.setdefault(target.id, set())
            if not inherited.issubset(current):
                current.update(inherited)
                changed = True
    return ancestors


def derive_reference_concepts(graph: ReferenceGraph) -> ConceptInventory:
    """Map inspected controls/elements to the five reference concepts.

    Unsupported element kinds and controls without a resolvable binding are kept
    as explicit inventory entries, not silently dropped.
    """
    nodes = {node.id: node for node in graph.nodes}
    outgoing: dict[str, list[Any]] = {}
    for edge in graph.edges:
        outgoing.setdefault(edge.source, []).append(edge)
    structure = _element_structure(graph)
    concepts: dict[str, ReferenceConcept] = {}
    unsupported: list[dict[str, str]] = []
    unbound: list[dict[str, str]] = []

    for control in graph.nodes:
        if control.kind is not NodeKind.CONTROL:
            continue
        element = None
        for edge in outgoing.get(control.id, []):
            if edge.type is not EdgeType.BOUND_TO:
                continue
            target = nodes.get(edge.target)
            if target is not None and target.kind is NodeKind.ELEMENT:
                element = target
                break
        kind = control.element_kind
        if (kind is None or kind is ElementKind.UNKNOWN) and element is not None:
            kind = element.element_kind or ElementKind.UNKNOWN
        kind = kind or ElementKind.UNKNOWN
        if kind in UNSUPPORTED_KINDS:
            unsupported.append(
                {
                    "kind": kind.value,
                    "status": control.status.value,
                    "reason": "pattern_not_supported_by_ref05",
                }
            )
            continue
        mapping = MODE_CONCEPTS.get(kind)
        if mapping is None:
            unsupported.append(
                {
                    "kind": kind.value,
                    "status": control.status.value,
                    "reason": "pattern_not_supported_by_ref05",
                }
            )
            continue
        schema_node = None
        if element is not None:
            for edge in outgoing.get(element.id, []):
                if edge.type is not EdgeType.RESOLVES_TO:
                    continue
                target = nodes.get(edge.target)
                if target is not None and target.kind is NodeKind.SCHEMA_FIELD:
                    schema_node = target
                    break
        path = (
            schema_node.schema_path
            if schema_node is not None and schema_node.schema_path
            else _fallback_path(
                element.source_name if element is not None else None,
                element.binding_path if element is not None else control.binding_path,
            )
        )
        if not path:
            unbound.append(
                {
                    "kind": kind.value,
                    "status": control.status.value,
                    "reason": "no_resolvable_binding_path",
                }
            )
            continue
        concept, _role = mapping
        contexts: set[str] = {_story_context(control.part)}
        if kind is ElementKind.IF:
            contexts.add("conditional")
        if element is not None:
            contexts.update(structure.get(element.id, set()))
        expected_type = None
        if schema_node is not None:
            expected_type = schema_node.data_type
        elif kind is ElementKind.IMAGE:
            expected_type = "image"
        elif kind is ElementKind.LIST:
            expected_type = "collection"
        elif kind is ElementKind.IF:
            expected_type = "boolean"
        key = f"{concept}:{path}"
        existing = concepts.get(key)
        if existing is None:
            concepts[key] = ReferenceConcept(
                concept=concept,
                kind=kind,
                path=path,
                expected_paths=(path,),
                expected_type=expected_type,
                contexts=tuple(sorted(contexts)),
                required=True,
                source="reference",
            )
        else:
            merged = tuple(sorted(set(existing.contexts) | contexts))
            concepts[key] = ReferenceConcept(
                concept=existing.concept,
                kind=existing.kind,
                path=existing.path,
                expected_paths=existing.expected_paths,
                expected_type=existing.expected_type or expected_type,
                contexts=merged,
                required=existing.required,
                source=existing.source,
            )
    return ConceptInventory(
        concepts=tuple(sorted(concepts.values(), key=lambda item: (item.kind.value, item.path))),
        unsupported=tuple(unsupported),
        unbound=tuple(unbound),
    )


# --------------------------------------------------------------------------- #
# Produced observations
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class ProducedObservation:
    """A field, condition, image or collection observed in a produced plan."""

    path: str
    role: str
    data_type: str | None = None
    contexts: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return f"{self.role}:{self.path}"


@dataclass
class ProducedPlan:
    observations: list[ProducedObservation] = field(default_factory=list)
    mapping_only: int = 0


def collect_produced_observations(
    document: Document, schema: Any, mapping: Any | None = None
) -> ProducedPlan:
    """Collect reference-evaluable observations from a produced Template IR."""
    bindings = collect_produced_bindings(document, schema, mapping)
    blocks = collect_produced_blocks(document, schema)
    merged: dict[str, ProducedObservation] = {}
    mapping_only = 0
    for binding in bindings:
        if binding.role == "mapping":
            mapping_only += 1
            continue
        role = binding.role
        if role not in {"field", "image", "condition"}:
            continue
        key = f"{role}:{binding.path}"
        existing = merged.get(key)
        contexts = tuple(sorted(set(binding.contexts)))
        if existing is None:
            merged[key] = ProducedObservation(
                path=binding.path,
                role=role,
                data_type=binding.data_type,
                contexts=contexts,
            )
        else:
            merged[key] = ProducedObservation(
                path=binding.path,
                role=role,
                data_type=existing.data_type or binding.data_type,
                contexts=tuple(sorted(set(existing.contexts) | set(contexts))),
            )
    for block in blocks:
        if block.kind not in {"repeat", "table"} or not block.path:
            continue
        key = f"collection:{block.path}"
        merged.setdefault(
            key,
            ProducedObservation(path=block.path, role="collection", data_type="collection"),
        )
    return ProducedPlan(
        observations=sorted(merged.values(), key=lambda item: (item.role, item.path)),
        mapping_only=mapping_only,
    )


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class ConceptOutcome:
    concept: ReferenceConcept
    status: str
    matched_path: str | None = None
    matched_role: str | None = None
    path_matched: bool = False
    kind_ok: bool | None = None
    type_ok: bool | None = None
    context_ok: bool | None = None
    type_checked: bool = False
    context_checked: bool = False
    reason: str = ""

    @property
    def matched(self) -> bool:
        return self.status in {"matched", "alternative"}

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.concept.identifier,
            "concept": self.concept.concept,
            "expected_paths": list(self.concept.expected_paths or (self.concept.path,)),
            "status": self.status,
            "matched_path": self.matched_path,
            "matched_role": self.matched_role,
            "kind_ok": self.kind_ok,
            "type_ok": self.type_ok,
            "context_ok": self.context_ok,
            "type_checked": self.type_checked,
            "context_checked": self.context_checked,
            "required": self.concept.required,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ReferenceScore:
    precision: float | None
    recall: float | None
    coverage: float | None
    f1: float | None
    type_context_correctness: float | None
    true_positives: int
    false_positives: int
    false_negatives: int
    matched_required: int
    required_total: int
    matched_concepts: int
    concept_total: int
    type_checks: int
    type_correct: int
    context_checks: int
    context_correct: int
    forbidden_hits: tuple[str, ...]
    extra_paths: tuple[str, ...]
    error_codes: tuple[str, ...]
    semantic_pass: bool
    outcomes: tuple[ConceptOutcome, ...]
    produced_paths: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "precision": self.precision,
            "recall": self.recall,
            "coverage": self.coverage,
            "f1": self.f1,
            "type_context_correctness": self.type_context_correctness,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "matched_required": self.matched_required,
            "required_total": self.required_total,
            "matched_concepts": self.matched_concepts,
            "concept_total": self.concept_total,
            "type_checks": self.type_checks,
            "type_correct": self.type_correct,
            "context_checks": self.context_checks,
            "context_correct": self.context_correct,
            "forbidden_hits": list(self.forbidden_hits),
            "extra_paths": list(self.extra_paths),
            "error_codes": list(self.error_codes),
            "semantic_pass": self.semantic_pass,
            "concepts": [outcome.as_dict() for outcome in self.outcomes],
            "produced_paths": list(self.produced_paths),
        }


def _ratio(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _normalize_type(value: str | None) -> str | None:
    if not value:
        return None
    lowered = value.strip().casefold()
    return _TYPE_ALIASES.get(lowered, lowered)


def _role_matches(concept: str, role: str) -> bool:
    return _ROLE_FOR_CONCEPT.get(concept) == role


def _context_matches(expected: Sequence[str], produced: Sequence[str]) -> bool:
    if not expected:
        return True
    if not produced:
        return False
    return bool(set(expected) & set(produced))


def score_reference_concepts(
    concepts: Sequence[ReferenceConcept],
    produced: Sequence[ProducedObservation],
    *,
    forbidden_paths: Sequence[str] = (),
) -> ReferenceScore:
    """Score produced observations against expected reference patterns."""
    outcomes: list[ConceptOutcome] = []
    matched_observations: set[str] = set()
    matched_required = 0
    matched_concepts = 0
    type_checks = 0
    type_correct = 0
    context_checks = 0
    context_correct = 0
    error_codes: set[str] = set()
    forbidden = set(forbidden_paths)

    for concept in concepts:
        candidates = [item for item in produced if item.path in concept.expected_paths]
        compatible = [item for item in candidates if _role_matches(concept.concept, item.role)]
        if not compatible:
            if candidates:
                # The path exists but the produced role/pattern is wrong.
                outcomes.append(
                    ConceptOutcome(
                        concept=concept,
                        status="wrong_kind",
                        path_matched=True,
                        matched_path=candidates[0].path,
                        matched_role=candidates[0].role,
                        kind_ok=False,
                        reason="path_produced_with_incompatible_role",
                    )
                )
                error_codes.add("wrong_binding")
            else:
                outcomes.append(
                    ConceptOutcome(
                        concept=concept,
                        status="missing",
                        reason="expected_path_not_produced",
                    )
                )
                error_codes.add("missing_field")
            continue
        best = compatible[0]
        context_ok: bool | None = None
        context_checked = False
        if concept.concept != "collection" and concept.contexts:
            context_checked = True
            context_ok = _context_matches(concept.contexts, best.contexts)
        produced_type = _normalize_type(best.data_type)
        expected_type = _normalize_type(concept.expected_type)
        type_ok: bool | None = None
        type_checked = False
        if expected_type and produced_type:
            type_checked = True
            type_ok = expected_type == produced_type
        status = "matched"
        reasons: list[str] = []
        if type_checked:
            type_checks += 1
            if type_ok:
                type_correct += 1
            else:
                reasons.append("type_mismatch")
                error_codes.add("wrong_binding")
        if context_checked:
            context_checks += 1
            if context_ok:
                context_correct += 1
            else:
                reasons.append("context_mismatch")
                error_codes.add("wrong_context")
        if reasons:
            status = "matched_with_issues"
        matched_observations.add(best.key)
        if concept.required:
            matched_required += 1
        matched_concepts += 1
        outcomes.append(
            ConceptOutcome(
                concept=concept,
                status=status,
                matched_path=best.path,
                matched_role=best.role,
                path_matched=True,
                kind_ok=True,
                type_ok=type_ok,
                context_ok=context_ok,
                type_checked=type_checked,
                context_checked=context_checked,
                reason=",".join(reasons),
            )
        )

    forbidden_hits = tuple(sorted(item.path for item in produced if item.path in forbidden))
    if forbidden_hits:
        error_codes.add("wrong_binding")
    extra = tuple(
        sorted(
            item.path
            for item in produced
            if item.key not in matched_observations and item.path not in forbidden
        )
    )
    if extra:
        error_codes.add("wrong_binding")
    required_total = sum(1 for concept in concepts if concept.required)
    concept_total = len(concepts)
    true_positives = len(matched_observations)
    false_positives = len(extra) + len(forbidden_hits)
    false_negatives = required_total - matched_required
    precision = _ratio(true_positives, true_positives + false_positives)
    recall = _ratio(matched_required, required_total)
    coverage = _ratio(matched_concepts, concept_total)
    f1 = (
        round(2 * precision * recall / (precision + recall), 6)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    type_context_correctness = _ratio(type_correct + context_correct, type_checks + context_checks)
    semantic_pass = not error_codes and false_negatives == 0 and concept_total > 0
    return ReferenceScore(
        precision=precision,
        recall=recall,
        coverage=coverage,
        f1=f1,
        type_context_correctness=type_context_correctness,
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        matched_required=matched_required,
        required_total=required_total,
        matched_concepts=matched_concepts,
        concept_total=concept_total,
        type_checks=type_checks,
        type_correct=type_correct,
        context_checks=context_checks,
        context_correct=context_correct,
        forbidden_hits=forbidden_hits,
        extra_paths=extra,
        error_codes=tuple(sorted(error_codes, key=ERROR_TAXONOMY.index)),
        semantic_pass=semantic_pass,
        outcomes=tuple(outcomes),
        produced_paths=tuple(sorted({item.path for item in produced})),
    )


# --------------------------------------------------------------------------- #
# Case loading
# --------------------------------------------------------------------------- #
def _resolve(path: str | Path) -> Path:
    target = Path(path)
    return target if target.is_absolute() else ROOT / target


def load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("The reference case file must contain a non-empty cases list")
    seen: set[str] = set()
    cases: list[dict[str, Any]] = []
    for raw in raw_cases:
        if not isinstance(raw, dict):
            raise ValueError("Each reference case must be an object")
        case_id = str(raw.get("id", "")).strip()
        if not case_id or case_id in seen:
            raise ValueError(f"Reference case id is missing or duplicated: {case_id!r}")
        seen.add(case_id)
        for required in ("prompt", "schema", "reference", "expected"):
            if required not in raw:
                raise ValueError(f"Reference case {case_id!r} is missing {required!r}")
        cases.append(raw)
    return cases


def _concepts_from_case(case: Mapping[str, Any]) -> tuple[ReferenceConcept, ...]:
    concepts: list[ReferenceConcept] = []
    for raw in case["expected"]:
        if not isinstance(raw, dict):
            raise ValueError(f"Case {case['id']!r} has a non-object expected concept")
        concept = str(raw.get("concept", "")).strip()
        path = str(raw.get("path", "")).strip()
        kind_value = str(raw.get("kind", "")).strip()
        if concept not in _ROLE_FOR_CONCEPT:
            raise ValueError(f"Case {case['id']!r} has unsupported concept {concept!r}")
        if not path:
            raise ValueError(f"Case {case['id']!r} has an empty expected path")
        try:
            kind = ElementKind(kind_value)
        except ValueError as exc:
            raise ValueError(f"Case {case['id']!r} has unknown kind {kind_value!r}") from exc
        expected_paths = raw.get("expected_paths") or [path]
        concepts.append(
            ReferenceConcept(
                concept=concept,
                kind=kind,
                path=path,
                expected_paths=tuple(str(item) for item in expected_paths),
                expected_type=(str(raw["expected_type"]) if raw.get("expected_type") else None),
                contexts=tuple(str(item) for item in raw.get("contexts", ["body"])),
                required=bool(raw.get("required", True)),
                source="synthetic",
            )
        )
    return tuple(concepts)


def _concept_consistency(
    expected: Sequence[ReferenceConcept], derived: ConceptInventory
) -> dict[str, Any]:
    expected_ids = {concept.identifier for concept in expected}
    derived_ids = {concept.identifier for concept in derived.concepts}
    return {
        "matches": expected_ids == derived_ids,
        "missing_from_reference": sorted(expected_ids - derived_ids),
        "extra_in_reference": sorted(derived_ids - expected_ids),
        "derived_concept_count": len(derived_ids),
        "unsupported_reference_count": len(derived.unsupported),
        "unbound_reference_count": len(derived.unbound),
    }


# --------------------------------------------------------------------------- #
# Inspection and planning
# --------------------------------------------------------------------------- #
def inspect_and_graph(
    path: Path,
    *,
    ddsp: Path | None,
    limits: ReferenceLimits,
    max_depth: int,
) -> tuple[ReferenceInspection, ReferenceGraph]:
    bundle = inspect_reference_bundle(
        path,
        limits=limits,
        max_depth=max_depth,
        ddsp_path=ddsp,
    )
    return bundle, build_reference_graph(bundle.report, bundle.schemas)


def graph_from_reference(
    path: Path,
    *,
    ddsp: Path | None,
    limits: ReferenceLimits,
    max_depth: int,
) -> ReferenceGraph:
    _bundle, graph = inspect_and_graph(path, ddsp=ddsp, limits=limits, max_depth=max_depth)
    return graph


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_segment(name: str, used: set[str]) -> str:
    base = name[1:] if name.startswith("@") else name
    base = re.sub(r"[^A-Za-z0-9_]", "_", base) or "attribute"
    if base[0].isdigit():
        base = f"attr_{base}"
    candidate = base
    index = 2
    while candidate in used:
        candidate = f"{base}_{index}"
        index += 1
    used.add(candidate)
    return candidate


def ir_compatible_schema(
    schema: NormalizedSchema,
) -> tuple[NormalizedSchema, dict[str, str]]:
    """Return an IR-safe view of a schema and its path mapping.

    Template IR 1.0 deliberately forbids raw XPath/attribute syntax such as
    ``@DeliveryName``. Real AX DDSP contracts expose every XSD attribute in that
    form, so a planner cannot bind them directly. For the *evaluation harness*
    only, attribute and otherwise invalid path segments are renamed to valid IR
    identifiers. Role, type, collection and context are unchanged. The mapping is
    applied to the reference concepts too, so both sides compare the same
    spelling. This does not change Template IR or the reference inspector.
    """
    payload = schema.model_dump(mode="python")
    path_map: dict[str, str] = {}

    def rewrite(nodes: list[dict[str, Any]], parent: str) -> None:
        used: set[str] = set()
        for node in nodes:
            original = str(node["path"])
            safe_name = _safe_segment(str(node["name"]), used)
            safe_path = f"{parent}.{safe_name}" if parent else safe_name
            path_map[original] = safe_path
            node["name"] = safe_name
            node["path"] = safe_path
            rewrite(list(node.get("children", [])), safe_path)

    for section in payload.get("sections", []):
        rewrite(list(section.get("nodes", [])), str(section["name"]))
    changed = {original: mapped for original, mapped in path_map.items() if original != mapped}
    if not changed:
        return schema, {}
    rewritten = NormalizedSchema.model_validate(payload)
    return rewritten, changed


def prepare_schema(path: Path) -> tuple[ParsedSource, dict[str, str]]:
    """Parse a schema and return its IR-safe evaluation view plus path mapping."""
    parsed = parse_schema(path)
    schema, mapping = ir_compatible_schema(parsed.schema)
    if not mapping:
        return parsed, {}
    return (
        ParsedSource(
            schema=schema,
            sample_data=parsed.sample_data,
            entry_names=parsed.entry_names,
        ),
        mapping,
    )


def remap_concepts(inventory: ConceptInventory, path_map: Mapping[str, str]) -> ConceptInventory:
    """Apply the evaluation path mapping to reference-derived concepts."""
    if not path_map:
        return inventory
    concepts: list[ReferenceConcept] = []
    for concept in inventory.concepts:
        mapped_path = path_map.get(concept.path, concept.path)
        concepts.append(
            ReferenceConcept(
                concept=concept.concept,
                kind=concept.kind,
                path=mapped_path,
                expected_paths=tuple(
                    path_map.get(path, path) for path in (concept.expected_paths or (concept.path,))
                ),
                expected_type=concept.expected_type,
                contexts=concept.contexts,
                required=concept.required,
                source=concept.source,
            )
        )
    return ConceptInventory(
        concepts=tuple(concepts),
        unsupported=inventory.unsupported,
        unbound=inventory.unbound,
    )


def parse_schema(path: Path) -> ParsedSource:
    """Parse a synthetic DDSP package or a bare real DDSP XML contract.

    The planner path normally consumes the synthetic ZIP/XSD format. A local
    corpus reference often ships a bare ``dsp:dataSourcePackage`` XML instead;
    the REF-01 adapter already normalizes that format, so fall back to it
    without changing the planner or Template IR.
    """
    payload = path.read_bytes()
    try:
        return parse_ddsp(payload, filename=path.name, limits=get_settings().limits)
    except CopilotError:
        artifact = parse_real_ddsp(
            payload,
            name=path.name,
            limits=ReferenceLimits.from_limits(get_settings().limits),
        )
        return ParsedSource(
            schema=artifact.schema,
            sample_data=None,
            entry_names=(path.name,),
        )


def _load_document(path: Path) -> Document:
    return load_document(path.read_text(encoding="utf-8"))


def _plan(
    parsed: Any,
    prompt: str,
    *,
    provider: str,
    model: str | None,
    language: str,
    repair_attempts: int,
) -> Any:
    planner = TemplatePlanner(LLMGateway())
    return asyncio.run(
        planner.plan(
            parsed.schema,
            prompt,
            provider=provider,
            model=model,
            options=PlanOptions(
                language=language,
                max_repair_attempts=repair_attempts,
            ),
        )
    )


@dataclass
class RunResult:
    run: dict[str, Any]
    score: ReferenceScore | None


def evaluate_one(
    *,
    case_id: str,
    title: str,
    prompt: str,
    parsed: Any,
    document: Document | None,
    provider: str,
    model: str | None,
    language: str,
    repair_attempts: int,
    concepts: Sequence[ReferenceConcept],
    forbidden_paths: Sequence[str] = (),
) -> RunResult:
    """Generate/score one plan and record validation, compilation and cost."""
    started = time.perf_counter()
    record: dict[str, Any] = {
        "case_id": case_id,
        "title": title,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "ok": False,
        "valid_template": False,
        "validation_passed": False,
        "compiled": False,
        "validation": {},
        "validation_codes": [],
        "error": None,
        "error_codes": [],
        "primary_error": None,
        "cost_usd": None,
        "cost_status": "unavailable",
        "ir_digest": None,
        "latency_ms": 0,
        "produced_paths": [],
        "mapping_only": 0,
        "failures": [],
        "actual_provider": None,
        "actual_model": None,
    }
    try:
        if document is None:
            outcome = _plan(
                parsed,
                prompt,
                provider=provider,
                model=model,
                language=language,
                repair_attempts=repair_attempts,
            )
            document = outcome.document
            mapping = outcome.mapping
            generation = outcome.generation
        else:
            mapping = None
            generation = None
        report = ValidationEngine().validate(
            document, parsed.schema, sample_data=parsed.sample_data
        )
        compiled = False
        compile_error = None
        if report.can_compile:
            try:
                result = GenericDocxCompiler().compile(
                    document,
                    parsed.schema,
                    CompileOptions(document_name=f"{case_id}.docx"),
                    sample_data=parsed.sample_data,
                )
                compiled = bool(result.success)
            except Exception as exc:
                compile_error = _redact(f"{type(exc).__name__}: {exc}")
    except Exception as exc:
        code, message = classify_exception(exc)
        record.update(
            {
                "error": {"code": code, "message": message},
                "error_codes": [code],
                "primary_error": code,
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }
        )
        return RunResult(run=record, score=None)

    produced = collect_produced_observations(document, parsed.schema, mapping)
    score = score_reference_concepts(
        concepts, produced.observations, forbidden_paths=forbidden_paths
    )
    validation_codes = sorted({finding.code for finding in report.errors()})
    codes = list(score.error_codes)
    if not report.can_compile:
        codes.extend(taxonomy_for_validation_codes(validation_codes))
    elif not compiled:
        codes.append("compilation")
    ordered = sorted({code for code in codes if code}, key=ERROR_TAXONOMY.index)
    if not report.can_compile:
        primary = next((code for code in ordered if code not in score.error_codes), "harness")
    elif not compiled:
        primary = "compilation"
    elif ordered:
        primary = ordered[0]
    else:
        primary = None
    usage = generation.usage.model_dump(mode="json") if generation is not None else None
    public = generation.public_view() if generation is not None else {}
    cost, cost_status, _proxy = _usage_cost(usage, model or "")
    valid_template = bool(report.can_compile and compiled)
    failures = [
        {
            "concept": outcome.concept.identifier,
            "expected_paths": list(outcome.concept.expected_paths or (outcome.concept.path,)),
            "predicted_paths": list(score.produced_paths[:20]),
            "status": outcome.status,
            "reason": outcome.reason or outcome.status,
        }
        for outcome in score.outcomes
        if not outcome.matched or outcome.reason
    ]
    record.update(
        {
            "ok": True,
            "valid_template": valid_template,
            "validation_passed": report.can_compile,
            "compiled": compiled,
            "validation": report.statuses(),
            "validation_codes": validation_codes,
            "error": (
                None
                if valid_template and score.semantic_pass
                else {
                    "code": primary or "wrong_binding",
                    "message": (
                        "reference patterns unmet: "
                        + ", ".join(
                            outcome.concept.identifier
                            for outcome in score.outcomes
                            if not outcome.matched
                        )
                        if any(not outcome.matched for outcome in score.outcomes)
                        else "reference patterns matched with issues"
                    ),
                }
            ),
            "error_codes": ordered,
            "primary_error": primary,
            "cost_usd": cost,
            "cost_status": cost_status,
            "ir_digest": ir_digest(document),
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "produced_paths": list(score.produced_paths[:80]),
            "mapping_only": produced.mapping_only,
            "failures": failures,
            "score": score.as_dict(),
            "actual_provider": public.get("provider"),
            "actual_model": public.get("model"),
            "compile_error": compile_error,
        }
    )
    return RunResult(run=record, score=score)


def _redact(text: str) -> str:
    return _SECRET.sub("[redacted]", text)[:500]


# --------------------------------------------------------------------------- #
# Aggregates and report
# --------------------------------------------------------------------------- #
def aggregate_runs(
    runs: Sequence[Mapping[str, Any]],
    scores: Sequence[ReferenceScore],
) -> dict[str, Any]:
    planned = [run for run in runs if run.get("ok")]
    valid = [run for run in planned if run.get("valid_template")]
    type_checks = sum(score.type_checks for score in scores)
    type_correct = sum(score.type_correct for score in scores)
    context_checks = sum(score.context_checks for score in scores)
    context_correct = sum(score.context_correct for score in scores)
    tp = sum(score.true_positives for score in scores)
    fp = sum(score.false_positives for score in scores)
    matched_required = sum(score.matched_required for score in scores)
    required_total = sum(score.required_total for score in scores)
    matched_concepts = sum(score.matched_concepts for score in scores)
    concept_total = sum(score.concept_total for score in scores)
    precision = _ratio(tp, tp + fp)
    recall = _ratio(matched_required, required_total)
    coverage = _ratio(matched_concepts, concept_total)
    f1 = (
        round(2 * precision * recall / (precision + recall), 6)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    cost_values = [float(run["cost_usd"]) for run in planned if run.get("cost_usd") is not None]
    if any(run.get("cost_status") == "estimated" for run in planned):
        cost_status = "estimated"
    elif any(run.get("cost_status") == "verified" for run in planned):
        cost_status = "verified"
    else:
        cost_status = "unavailable"
    errors = Counter[str]()
    primary_errors = Counter[str]()
    for run in runs:
        for code in run.get("error_codes", []):
            errors[code] += 1
        if run.get("primary_error"):
            primary_errors[str(run["primary_error"])] += 1
    return {
        "runs": len(runs),
        "completed_runs": len(planned),
        "failed_runs": len(runs) - len(planned),
        "valid_runs": len(valid),
        "valid_template_rate": _ratio(len(valid), len(runs)),
        "validation_pass_rate": _ratio(
            sum(1 for run in planned if run.get("validation_passed")), len(planned)
        ),
        "compilation_success_rate": _ratio(
            sum(1 for run in planned if run.get("compiled")), len(planned)
        ),
        "precision": precision,
        "precision_numerator": tp,
        "precision_denominator": tp + fp,
        "recall": recall,
        "recall_numerator": matched_required,
        "recall_denominator": required_total,
        "coverage": coverage,
        "coverage_numerator": matched_concepts,
        "coverage_denominator": concept_total,
        "f1": f1,
        "type_context_correctness": _ratio(
            type_correct + context_correct, type_checks + context_checks
        ),
        "type_checks": type_checks,
        "type_correct": type_correct,
        "context_checks": context_checks,
        "context_correct": context_correct,
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": sum(score.false_negatives for score in scores),
        "matched_required": matched_required,
        "required_total": required_total,
        "matched_concepts": matched_concepts,
        "concept_total": concept_total,
        "semantic_pass_rate": _ratio(sum(1 for score in scores if score.semantic_pass), len(runs)),
        "forbidden_hits": sorted({path for score in scores for path in score.forbidden_hits}),
        "cost_usd": round(sum(cost_values), 6) if cost_values else None,
        "cost_status": cost_status,
        "error_counts": dict(sorted(errors.items())),
        "primary_error_counts": dict(sorted(primary_errors.items())),
    }


def _dataset_metadata(definitions: Sequence[Mapping[str, Any]], path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    canonical = json.dumps(definitions, sort_keys=True, separators=(",", ":")).encode()
    return {
        "file": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else path.name,
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        "canonical_sha256": hashlib.sha256(canonical).hexdigest(),
        "case_count": len(definitions),
        "families": dict(
            sorted(Counter(str(case.get("family", "unknown")) for case in definitions).items())
        ),
        "patterns": dict(
            sorted(
                Counter(
                    pattern for case in definitions for pattern in case.get("patterns", [])
                ).items()
            )
        ),
    }


def _reference_provenance(
    *,
    kind: str,
    references: Sequence[Mapping[str, Any]],
    notes: Sequence[str],
) -> dict[str, Any]:
    return {
        "kind": kind,
        "committed": kind == "synthetic",
        "references": list(references),
        "corpus_content_included": False,
        "corpus_paths_included": False,
        "notes": list(notes),
    }


def _case_metrics(
    runs: Sequence[Mapping[str, Any]], scores: Sequence[ReferenceScore]
) -> dict[str, Any]:
    return aggregate_runs(runs, scores)


def _cost_metadata(aggregate: Mapping[str, Any], provider: str) -> dict[str, Any]:
    if provider == "mock":
        return {
            "status": "verified",
            "total_usd": 0.0,
            "paid_calls": False,
            "per_semantically_correct_result_usd": 0.0,
            "assumptions": [
                "The deterministic mock provider reports zero token usage and zero cost.",
                "No paid provider call was made for this report.",
            ],
        }
    return {
        "status": aggregate.get("cost_status", "unavailable"),
        "total_usd": aggregate.get("cost_usd"),
        "paid_calls": True,
        "per_semantically_correct_result_usd": None,
        "assumptions": [
            "Cost is verified only when the provider reports token usage and the model has a "
            "versioned price.",
            "Otherwise it is estimated by the documented proxy or reported as unavailable; "
            "unknown is never rendered as $0.00.",
        ],
    }


def build_report(
    *,
    mode: str,
    provider: str,
    model: str | None,
    cases: Sequence[Mapping[str, Any]],
    case_runs: Sequence[Mapping[str, Any]],
    all_runs: Sequence[Mapping[str, Any]],
    all_scores: Sequence[ReferenceScore],
    dataset: Mapping[str, Any],
    provenance: Mapping[str, Any],
    sample: Mapping[str, Any],
    notes: Sequence[str],
    per_case: Sequence[Mapping[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    metrics = aggregate_runs(all_runs, all_scores)
    cost = _cost_metadata(metrics, provider)
    return {
        "schema": "reference-evaluation/v1",
        "generated_at": generated_at,
        "mode": mode,
        "provider": {
            "provider": provider,
            "model": model or ("mock-planner-v1" if provider == "mock" else None),
            "live": provider != "mock",
        },
        "dataset": dict(dataset),
        "provenance": dict(provenance),
        "sample_size": dict(sample),
        "case_count": len(cases),
        "per_case": list(per_case),
        "metrics": metrics,
        "valid_template_rate": metrics["valid_template_rate"],
        "valid_templates": {
            "rate": metrics["valid_template_rate"],
            "valid": metrics["valid_runs"],
            "runs": metrics["runs"],
            "note": (
                "Reported separately from precision/recall/coverage: a schema-valid, "
                "compilable template can still bind the wrong reference pattern."
            ),
        },
        "cost": cost,
        "error_taxonomy": metrics["error_counts"],
        "primary_error_counts": metrics["primary_error_counts"],
        "notes": list(notes),
        "limitations": [
            "The synthetic set is small (8 patterns) and is not a population sample.",
            "The mock provider is a deterministic baseline, not an LLM quality claim.",
            "Static reference inspection cannot prove Docentric runtime compatibility.",
            "AXPP references with several DOCX documents are evaluated as one concept inventory.",
        ],
    }


# --------------------------------------------------------------------------- #
# Report writers
# --------------------------------------------------------------------------- #
def _display_path(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else path.name


def _write_json(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _csv_rows(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    metrics = report["metrics"]
    rows: list[dict[str, Any]] = [
        {
            "scope": "aggregate",
            "case_id": "",
            "provider": report["provider"]["provider"],
            "model": report["provider"].get("model") or "",
            "provenance": report["provenance"]["kind"],
            "case_count": report["case_count"],
            "runs": metrics["runs"],
            "completed_runs": metrics["completed_runs"],
            "valid_runs": metrics["valid_runs"],
            "valid_template_rate": metrics["valid_template_rate"],
            "precision": metrics["precision"],
            "recall": metrics["recall"],
            "coverage": metrics["coverage"],
            "f1": metrics["f1"],
            "type_context_correctness": metrics["type_context_correctness"],
            "semantic_pass_rate": metrics["semantic_pass_rate"],
            "concept_total": metrics["concept_total"],
            "cost_usd": metrics["cost_usd"],
            "cost_status": metrics["cost_status"],
        }
    ]
    for case in report["per_case"]:
        case_metrics = case["metrics"]
        rows.append(
            {
                "scope": "case",
                "case_id": case["case_id"],
                "provider": report["provider"]["provider"],
                "model": report["provider"].get("model") or "",
                "provenance": report["provenance"]["kind"],
                "case_count": 1,
                "runs": case_metrics["runs"],
                "completed_runs": case_metrics["completed_runs"],
                "valid_runs": case_metrics["valid_runs"],
                "valid_template_rate": case_metrics["valid_template_rate"],
                "precision": case_metrics["precision"],
                "recall": case_metrics["recall"],
                "coverage": case_metrics["coverage"],
                "f1": case_metrics["f1"],
                "type_context_correctness": case_metrics["type_context_correctness"],
                "semantic_pass_rate": case_metrics["semantic_pass_rate"],
                "concept_total": case_metrics["concept_total"],
                "cost_usd": case_metrics["cost_usd"],
                "cost_status": case_metrics["cost_status"],
            }
        )
    return rows


def _write_csv(path: Path, report: Mapping[str, Any]) -> None:
    rows = _csv_rows(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(buffer.getvalue(), encoding="utf-8")


def _fmt(value: float | None, digits: int = 3) -> str:
    return "N/A" if value is None else f"{value:.{digits}f}"


def _pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.1%}"


def _write_html(path: Path, report: Mapping[str, Any]) -> None:
    metrics = report["metrics"]
    provenance = report["provenance"]
    sample = report["sample_size"]
    provider = report["provider"]
    rows = []
    for case in report["per_case"]:
        cm = case["metrics"]
        rows.append(
            "<tr>"
            f"<td><strong>{html.escape(case['case_id'])}</strong><br>"
            f"<span class='muted'>{html.escape(', '.join(case.get('patterns', [])))}</span></td>"
            f"<td>{cm['concept_total']}</td>"
            f"<td>{_fmt(cm['precision'])}</td>"
            f"<td>{_fmt(cm['recall'])}</td>"
            f"<td>{_fmt(cm['coverage'])}</td>"
            f"<td>{_fmt(cm['type_context_correctness'])}</td>"
            f"<td>{_pct(cm['semantic_pass_rate'])}</td>"
            f"<td><strong>{_pct(cm['valid_template_rate'])}</strong></td>"
            "</tr>"
        )
    taxonomy = "".join(
        f"<tr><td>{html.escape(code)}</td><td>{count}</td>"
        f"<td>{report['primary_error_counts'].get(code, 0)}</td></tr>"
        for code, count in sorted(
            report["error_taxonomy"].items(), key=lambda item: ERROR_TAXONOMY.index(item[0])
        )
    )
    references = "".join(
        f"<li>{html.escape(str(item.get('name', item.get('kind', 'reference'))))} "
        f"<span class='muted'>{html.escape(str(item.get('sha256', ''))[:16])}</span></li>"
        for item in provenance.get("references", [])
    )
    notes = "".join(f"<li>{html.escape(note)}</li>" for note in report["notes"])
    limitations = "".join(f"<li>{html.escape(item)}</li>" for item in report["limitations"])
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reference-based evaluation</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ margin: 0; padding: 32px 20px 64px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; color: #172033; background: #f5f7fb; line-height: 1.45; }}
  main {{ max-width: 1120px; margin: 0 auto; }}
  h1 {{ font-size: 30px; margin: 0 0 6px; }}
  h2 {{ font-size: 19px; margin: 28px 0 8px; }}
  .muted {{ color: #64748b; font-weight: 400; font-size: 13px; }}
  .note {{ background: #fff7ed; border: 1px solid #fed7aa; border-left: 5px solid #ea580c; padding: 14px 18px; border-radius: 8px; margin: 18px 0; }}
  .card {{ background: #fff; border: 1px solid #dfe5ef; border-radius: 10px; padding: 16px 18px; margin: 14px 0; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #dfe5ef; border-radius: 8px; overflow: hidden; margin: 12px 0 24px; font-size: 13px; }}
  th, td {{ padding: 8px 10px; border-bottom: 1px solid #e8edf5; text-align: left; vertical-align: top; }}
  th {{ background: #f8fafc; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: #475569; }}
  code {{ background: #eef2f7; padding: 1px 5px; border-radius: 4px; }}
  .metric {{ font-size: 26px; font-weight: 700; }}
</style>
</head>
<body>
<main>
  <h1>Reference-based evaluation</h1>
  <p class="muted">Provenance: <strong>{html.escape(provenance["kind"])}</strong> ·
     Mode: <code>{html.escape(report["mode"])}</code> ·
     Provider: <code>{html.escape(str(provider["provider"]))}</code>
     {html.escape(str(provider.get("model") or ""))} · Cases: {sample["cases"]} ·
     Runs: {sample["completed_runs"]}/{sample["runs"]}</p>

  <div class="note">
    <strong>Valid template rate is reported separately.</strong>
    Validation and compilation say the plan is technically usable; they do not say it reproduced
    the reference patterns. Precision, recall and coverage come from the reference comparison.
  </div>

  <section class="card">
    <div class="metric">{_pct(metrics["semantic_pass_rate"])}</div>
    <p class="muted">Semantic pass rate · precision {_fmt(metrics["precision"])} ·
       recall {_fmt(metrics["recall"])} · coverage {_fmt(metrics["coverage"])} ·
       type/context {_fmt(metrics["type_context_correctness"])}</p>
    <p>Valid template rate <strong>{_pct(metrics["valid_template_rate"])}</strong>
       ({metrics["valid_runs"]}/{metrics["runs"]}) — separate from the semantic metrics.</p>
  </section>

  <h2>Sample and provenance</h2>
  <table><tbody>
    <tr><th>Reference concepts</th><td>{sample["reference_concepts"]}</td></tr>
    <tr><th>Unsupported / unbound</th><td>{sample["unsupported_concepts"]} / {sample["unbound_concepts"]}</td></tr>
    <tr><th>Corpus content included</th><td>{"yes" if provenance["corpus_content_included"] else "no"}</td></tr>
    <tr><th>References</th><td><ul>{references}</ul></td></tr>
    <tr><th>Cost</th><td>{html.escape(str(report["cost"]["status"]))} · {html.escape(str(report["cost"]["total_usd"]))} USD</td></tr>
  </tbody></table>

  <h2>Per-case results</h2>
  <table>
    <thead><tr><th>Case / patterns</th><th>Concepts</th><th>Precision</th><th>Recall</th>
      <th>Coverage</th><th>Type/context</th><th>Semantic pass</th><th>Valid template</th></tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table>

  <h2>Error taxonomy</h2>
  <table><thead><tr><th>Code</th><th>Runs with code</th><th>Primary</th></tr></thead>
    <tbody>{taxonomy}</tbody></table>

  <h2>Notes</h2>
  <ul>{notes}</ul>
  <h2>Limitations</h2>
  <ul>{limitations}</ul>
</main>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Modes
# --------------------------------------------------------------------------- #
def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _run_cases_mode(
    *,
    cases_path: Path,
    limit: int | None,
    repeats: int,
    provider: str,
    model: str | None,
    language: str,
    repair_attempts: int,
    limits: ReferenceLimits,
    max_depth: int,
) -> tuple[
    list[Mapping[str, Any]],
    list[Mapping[str, Any]],
    list[ReferenceScore],
    dict[str, Any],
    dict[str, Any],
    list[Mapping[str, Any]],
    dict[str, Any],
    list[str],
]:
    cases = load_cases(cases_path)
    if limit is not None:
        cases = cases[:limit]
    case_runs: list[dict[str, Any]] = []
    all_runs: list[dict[str, Any]] = []
    all_scores: list[ReferenceScore] = []
    per_case: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    inconsistencies: list[str] = []
    for case in cases:
        case_id = str(case["id"])
        schema_path = _resolve(case["schema"])
        reference_path = _resolve(case["reference"])
        parsed = parse_schema(schema_path)
        expected = _concepts_from_case(case)
        graph = graph_from_reference(
            reference_path, ddsp=schema_path, limits=limits, max_depth=max_depth
        )
        derived = derive_reference_concepts(graph)
        consistency = _concept_consistency(expected, derived)
        if not consistency["matches"]:
            inconsistencies.append(
                f"{case_id}: expected {consistency['missing_from_reference'] or 'none'} "
                f"not derived; extra {consistency['extra_in_reference'] or 'none'}"
            )
        references.append(
            {
                "kind": "synthetic",
                "name": reference_path.name,
                "sha256": hashlib.sha256(reference_path.read_bytes()).hexdigest(),
                "schema_sha256": hashlib.sha256(schema_path.read_bytes()).hexdigest(),
            }
        )
        case_results: list[dict[str, Any]] = []
        case_scores: list[ReferenceScore] = []
        for repeat in range(repeats):
            result = evaluate_one(
                case_id=case_id,
                title=str(case.get("title", case_id)),
                prompt=str(case["prompt"]),
                parsed=parsed,
                document=None,
                provider=provider,
                model=model,
                language=language,
                repair_attempts=repair_attempts,
                concepts=expected,
                forbidden_paths=tuple(str(item) for item in case.get("forbidden_paths", [])),
            )
            run = dict(result.run)
            run["repeat"] = repeat
            run["patterns"] = list(case.get("patterns", []))
            run["reference_consistency"] = consistency
            case_results.append(run)
            case_runs.append(run)
            all_runs.append(run)
            if result.score is not None:
                case_scores.append(result.score)
                all_scores.append(result.score)
        case_metrics = aggregate_runs(case_results, case_scores)
        per_case.append(
            {
                "case_id": case_id,
                "title": str(case.get("title", case_id)),
                "family": str(case.get("family", "unknown")),
                "patterns": list(case.get("patterns", [])),
                "concept_total": len(expected),
                "metrics": case_metrics,
                "consistency": consistency,
                "runs": case_results,
            }
        )
    dataset = _dataset_metadata(cases, cases_path)
    provenance = _reference_provenance(
        kind="synthetic",
        references=references,
        notes=[
            "All references and schemas are synthetic fixtures committed with the repository.",
            "No Docentric archive file, fragment, schema, text or screenshot was used.",
        ],
    )
    sample = {
        "cases": len(cases),
        "runs": len(all_runs),
        "completed_runs": sum(1 for run in all_runs if run.get("ok")),
        "reference_concepts": sum(int(case.get("concept_total", 0)) for case in per_case),
        "unsupported_concepts": sum(
            int(case.get("consistency", {}).get("unsupported_reference_count", 0))
            for case in per_case
        ),
        "unbound_concepts": sum(
            int(case.get("consistency", {}).get("unbound_reference_count", 0)) for case in per_case
        ),
    }
    notes = [
        "Synthetic gold set: 8 Field/List/If/Image/Label pattern cases authored in this repository.",
        "Expected bindings were hand-authored; the evaluator also derives concepts from the "
        "reference and reports any consistency gap.",
        "No paid provider calls are needed: the default provider is the deterministic mock.",
        "Semantic metrics and valid_template_rate are reported separately.",
    ]
    if inconsistencies:
        notes.append("Reference/gold consistency gaps: " + "; ".join(inconsistencies))
    return (
        cases,
        case_runs,
        all_scores,
        dataset,
        provenance,
        per_case,
        sample,
        notes,
    )


def _run_reference_mode(
    *,
    reference_path: Path,
    ddsp_path: Path | None,
    plan_path: Path | None,
    prompt: str | None,
    provider: str,
    model: str | None,
    language: str,
    repair_attempts: int,
    limits: ReferenceLimits,
    max_depth: int,
) -> tuple[
    list[Mapping[str, Any]],
    list[Mapping[str, Any]],
    list[ReferenceScore],
    dict[str, Any],
    dict[str, Any],
    list[Mapping[str, Any]],
    dict[str, Any],
    list[str],
]:
    bundle, graph = inspect_and_graph(
        reference_path, ddsp=ddsp_path, limits=limits, max_depth=max_depth
    )
    if ddsp_path is not None:
        parsed, path_map = prepare_schema(ddsp_path)
    else:
        artifacts = sorted(
            bundle.schemas.values(),
            key=lambda artifact: (artifact.name, artifact.schema.schema_id),
        )
        if not artifacts:
            raise ValueError(
                "--reference requires --ddsp, or a ZIP/AXPP reference that embeds a DDSP schema"
            )
        artifact = artifacts[0]
        safe_schema, path_map = ir_compatible_schema(artifact.schema)
        parsed = ParsedSource(
            schema=safe_schema,
            sample_data=None,
            entry_names=(artifact.name,),
        )
    derived = remap_concepts(derive_reference_concepts(graph), path_map)
    document = _load_document(plan_path) if plan_path is not None else None
    selected_prompt = prompt or (
        "Create a business document using the available fields, lists, conditions, "
        "images and labels."
    )
    result = evaluate_one(
        case_id="reference",
        title=reference_path.name,
        prompt=selected_prompt,
        parsed=parsed,
        document=document,
        provider=provider,
        model=model,
        language=language,
        repair_attempts=repair_attempts,
        concepts=derived.concepts,
    )
    run = dict(result.run)
    run["patterns"] = sorted({concept.concept for concept in derived.concepts})
    case_metrics = aggregate_runs([run], [result.score] if result.score is not None else [])
    per_case = [
        {
            "case_id": "reference",
            "title": reference_path.name,
            "family": "local-corpus",
            "patterns": run["patterns"],
            "concept_total": len(derived.concepts),
            "metrics": case_metrics,
            "consistency": {
                "derived_concept_count": len(derived.concepts),
                "unsupported_reference_count": len(derived.unsupported),
                "unbound_reference_count": len(derived.unbound),
            },
            "runs": [run],
        }
    ]
    dataset = {
        "file": reference_path.name,
        "file_sha256": hashlib.sha256(reference_path.read_bytes()).hexdigest(),
        "case_count": 1,
        "families": {"local-corpus": 1},
        "patterns": dict(sorted(Counter(concept.concept for concept in derived.concepts).items())),
        "path_normalization": {
            "applied": bool(path_map),
            "segments_rewritten": len(path_map),
            "reason": (
                "Template IR 1.0 forbids raw attribute/XPath segments; evaluation maps "
                "them to IR-safe identifiers on both sides."
            ),
        },
    }
    provenance = _reference_provenance(
        kind="local-corpus",
        references=[
            {
                "kind": "local-corpus",
                "name": reference_path.name,
                "sha256": hashlib.sha256(reference_path.read_bytes()).hexdigest(),
            }
        ],
        notes=[
            "This report was produced from a runtime-only reference path; do not commit it.",
            "Only aggregate counts and hashes belong in a public report; the source template "
            "content is not redistributed.",
        ],
    )
    sample = {
        "cases": 1,
        "runs": 1,
        "completed_runs": 1 if run.get("ok") else 0,
        "reference_concepts": len(derived.concepts),
        "unsupported_concepts": len(derived.unsupported),
        "unbound_concepts": len(derived.unbound),
    }
    notes = [
        "Reference mode: expected patterns were derived from the inspected reference at runtime.",
        "This mode is intended for the git-ignored local corpus; the output must stay private.",
        "Semantic metrics and valid_template_rate are reported separately.",
    ]
    if path_map:
        notes.append(
            f"Evaluation path normalization applied to {len(path_map)} schema paths "
            "(@Attribute -> Attribute); role, type and context are unchanged."
        )
    return (
        [{"id": "reference", "patterns": run["patterns"]}],
        [run],
        [result.score] if result.score is not None else [],
        dataset,
        provenance,
        per_case,
        sample,
        notes,
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Reference-based semantic evaluation (REF-05). The default uses the "
            "committed synthetic set and the deterministic mock provider."
        )
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES,
        help="Committed synthetic case file (default: benchmarks/reference_cases.json)",
    )
    parser.add_argument(
        "--reference",
        type=Path,
        default=None,
        help="DOCX/AXPP reference to inspect at runtime (local-corpus mode)",
    )
    parser.add_argument("--ddsp", type=Path, default=None, help="Schema for --reference mode")
    parser.add_argument("--plan", type=Path, default=None, help="Score an existing Template IR")
    parser.add_argument("--prompt-file", type=Path, default=None)
    parser.add_argument("--prompt", default=None)
    parser.add_argument("--provider", default="mock", help="Provider id (default: mock)")
    parser.add_argument("--model", default=None)
    parser.add_argument("--language", default="en")
    parser.add_argument("--repeats", type=int, default=1, help="Runs per case (default: 1)")
    parser.add_argument("--repair-attempts", type=int, default=2)
    parser.add_argument("--limit", type=int, default=None, help="Evaluate only the first N cases")
    parser.add_argument("--max-depth", type=int, default=1, choices=(0, 1, 2, 3))
    parser.add_argument("--allow-paid", action="store_true", help="Allow a non-mock provider")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--output-html", type=Path, default=DEFAULT_HTML)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.reference is not None and args.cases != DEFAULT_CASES:
        parser.error("--cases and --reference are mutually exclusive")
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    if args.provider != "mock" and not args.allow_paid:
        parser.error("A non-mock provider may make paid calls; pass --allow-paid to confirm")
    prompt = args.prompt
    if args.prompt_file is not None:
        prompt = _resolve(args.prompt_file).read_text(encoding="utf-8")
    limits = ReferenceLimits.from_limits(get_settings().limits, max_depth=args.max_depth)
    try:
        if args.reference is not None:
            reference_path = _resolve(args.reference)
            ddsp_path = _resolve(args.ddsp) if args.ddsp is not None else None
            plan_path = _resolve(args.plan) if args.plan is not None else None
            outcomes = _run_reference_mode(
                reference_path=reference_path,
                ddsp_path=ddsp_path,
                plan_path=plan_path,
                prompt=prompt,
                provider=args.provider,
                model=args.model,
                language=args.language,
                repair_attempts=args.repair_attempts,
                limits=limits,
                max_depth=args.max_depth,
            )
            mode = "reference"
        else:
            outcomes = _run_cases_mode(
                cases_path=_resolve(args.cases),
                limit=args.limit,
                repeats=args.repeats,
                provider=args.provider,
                model=args.model,
                language=args.language,
                repair_attempts=args.repair_attempts,
                limits=limits,
                max_depth=args.max_depth,
            )
            mode = "cases"
    except (CopilotError, ValueError) as exc:
        message = exc.message if isinstance(exc, CopilotError) else str(exc)
        print(f"reference evaluation failed: {message}", file=sys.stderr)
        return 1
    (
        cases,
        case_runs,
        all_scores,
        dataset,
        provenance,
        per_case,
        sample,
        notes,
    ) = outcomes
    all_runs = [run for case in per_case for run in case["runs"]]
    report = build_report(
        mode=mode,
        provider=args.provider,
        model=args.model,
        cases=cases,
        case_runs=case_runs,
        all_runs=all_runs,
        all_scores=all_scores,
        dataset=dataset,
        provenance=provenance,
        sample=sample,
        notes=notes,
        per_case=per_case,
        generated_at=_utc_now(),
    )
    _write_json(_resolve(args.output_json), report)
    _write_csv(_resolve(args.output_csv), report)
    _write_html(_resolve(args.output_html), report)
    metrics = report["metrics"]
    print(
        "reference evaluation: "
        f"provenance={provenance['kind']} cases={sample['cases']} "
        f"runs={sample['completed_runs']}/{sample['runs']} "
        f"precision={_fmt(metrics['precision'])} recall={_fmt(metrics['recall'])} "
        f"coverage={_fmt(metrics['coverage'])} "
        f"type_context={_fmt(metrics['type_context_correctness'])} "
        f"valid_template_rate={_pct(metrics['valid_template_rate'])} "
        f"cost={_fmt(metrics['cost_usd'])} ({metrics['cost_status']})"
    )
    print(f"wrote {_display_path(_resolve(args.output_json))}")
    print(f"wrote {_display_path(_resolve(args.output_csv))}")
    print(f"wrote {_display_path(_resolve(args.output_html))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
