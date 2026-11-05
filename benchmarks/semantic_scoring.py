"""Pure semantic scoring for the prompt-to-template benchmark (P0).

The deterministic evaluator answers a different question from the existing
``live_evaluation.py``: *is the produced template semantically right?* A payload
can be schema-valid and compile successfully while binding the company bank
account where the customer's name was requested. That is a semantic failure and
must reduce the semantic score even though ``valid_template_rate`` stays at 1.0.

The module is deliberately free of I/O, provider clients and compiler calls:
every function takes plain values and returns plain dataclasses. The live runner
(``semantic_evaluation.py``) collects produced bindings/blocks from the IR and
calls :func:`score_run`.

Ground truth model
------------------
Each case declares ``required_bindings``. A requirement has:

* ``expected_paths`` - absolute schema paths that satisfy it;
* ``allowed_alternatives`` - additional paths a domain expert accepts (counted
  as a true positive, with ``matched_via="alternative"``);
* ``required`` - when true, an unmatched requirement is a false negative;
* ``expected_type`` / ``expected_context`` - optional type and placement checks
  (``body``, ``header``, ``footer``, ``repeat``, ``conditional``);
* ``satisfiable`` - false means the schema cannot express the request. Such a
  requirement is excluded from recall and coverage denominators instead of being
  counted as an unavoidable false negative; a model that hallucinates a binding
  for it is still charged with ``wrong_binding``.

A produced binding may also carry ``role``: ``field`` (normal content), ``image``,
``condition`` (a field used by an expression) or ``mapping`` (a planner mapping
that did not survive into the IR). Unused ``condition`` bindings are semantic
plumbing, not content, and are not charged as false positives.

Precision, recall, requirement coverage and type/context correctness are
computed separately from validation/compilation. The report never compares the
semantic score by silently folding in valid-template rate.

Error taxonomy
--------------
Every failed run carries ``error_codes`` from the fixed taxonomy below. A run can
carry several semantic codes (for example a missing field and a forbidden extra
field); the report counts runs per code. Procedural failures carry exactly one
primary code.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from docentric_copilot.errors import (
    CompilationFailedError,
    InvalidInputError,
    PlanInvalidError,
    ProviderError,
    ValidationFailedError,
)

#: Stable taxonomy shared by the scorer and the live runner.
ERROR_TAXONOMY: tuple[str, ...] = (
    "provider_api",
    "quota",
    "timeout",
    "structured_output",
    "missing_field",
    "wrong_binding",
    "wrong_context",
    "unsupported_expression",
    "compilation",
    "renderer",
    "harness",
)

SEMANTIC_ERROR_CODES = frozenset(
    {"missing_field", "wrong_binding", "wrong_context", "unsupported_expression"}
)
PROCEDURAL_ERROR_CODES = frozenset(ERROR_TAXONOMY) - SEMANTIC_ERROR_CODES

VALID_CONTEXTS = frozenset({"body", "header", "footer", "repeat", "conditional"})
VALID_TYPES = frozenset(
    {"string", "number", "boolean", "date", "image", "collection", "object", "any"}
)
VALID_BLOCK_KINDS = frozenset({"repeat", "table", "conditional", "image"})

_SECRET = re.compile(r"(?i)(api[-_]?key|authorization|bearer)\s*[=:]\s*\S+")


@dataclass(frozen=True, slots=True)
class SemanticRequirement:
    """One semantic requirement, independent of how the planner names it."""

    id: str
    concept: str
    expected_paths: tuple[str, ...] = ()
    allowed_alternatives: tuple[str, ...] = ()
    required: bool = True
    expected_type: str | None = None
    expected_context: str | None = None
    satisfiable: bool = True
    note: str = ""


@dataclass(frozen=True, slots=True)
class ProducedBinding:
    """A field, image, condition or mapping observed in one produced run."""

    path: str
    concept: str | None = None
    data_type: str | None = None
    contexts: tuple[str, ...] = ()
    role: str = "field"
    status: str | None = None


@dataclass(frozen=True, slots=True)
class BlockRequirement:
    """A repeat, table, conditional or image block that must be present."""

    kind: str
    path: str | None = None
    required: bool = True
    description: str = ""


@dataclass(frozen=True, slots=True)
class ProducedBlock:
    """A structural block observed in the produced IR."""

    kind: str
    path: str | None = None
    condition_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RequirementOutcome:
    requirement_id: str
    concept: str
    required: bool
    satisfiable: bool
    status: str
    matched_path: str | None = None
    matched_via: str | None = None
    type_ok: bool | None = None
    context_ok: bool | None = None
    type_checked: bool = False
    context_checked: bool = False
    error_codes: tuple[str, ...] = ()

    @property
    def satisfied(self) -> bool:
        return self.status in {"matched", "alternative"}

    def as_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "concept": self.concept,
            "required": self.required,
            "satisfiable": self.satisfiable,
            "status": self.status,
            "satisfied": self.satisfied,
            "matched_path": self.matched_path,
            "matched_via": self.matched_via,
            "type_ok": self.type_ok,
            "context_ok": self.context_ok,
            "type_checked": self.type_checked,
            "context_checked": self.context_checked,
            "error_codes": list(self.error_codes),
        }


@dataclass(frozen=True, slots=True)
class BlockOutcome:
    kind: str
    path: str | None
    required: bool
    satisfied: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "path": self.path,
            "required": self.required,
            "satisfied": self.satisfied,
        }


@dataclass(frozen=True, slots=True)
class SemanticScore:
    precision: float | None
    recall: float | None
    requirement_coverage: float | None
    type_context_correctness: float | None
    block_coverage: float | None
    f1: float | None
    true_positives: int
    false_positives: int
    false_negatives: int
    matched_requirements: int
    matched_required: int
    required_requirements: int
    satisfiable_requirements: int
    unsatisfiable_requirements: int
    type_context_checks: int
    type_context_correct: int
    block_total: int
    block_satisfied: int
    forbidden_hits: tuple[str, ...]
    false_positive_paths: tuple[str, ...]
    error_codes: tuple[str, ...]
    semantic_pass: bool
    outcomes: tuple[RequirementOutcome, ...]
    block_outcomes: tuple[BlockOutcome, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "precision": self.precision,
            "recall": self.recall,
            "requirement_coverage": self.requirement_coverage,
            "type_context_correctness": self.type_context_correctness,
            "block_coverage": self.block_coverage,
            "f1": self.f1,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "matched_requirements": self.matched_requirements,
            "matched_required": self.matched_required,
            "required_requirements": self.required_requirements,
            "satisfiable_requirements": self.satisfiable_requirements,
            "unsatisfiable_requirements": self.unsatisfiable_requirements,
            "type_context_checks": self.type_context_checks,
            "type_context_correct": self.type_context_correct,
            "block_total": self.block_total,
            "block_satisfied": self.block_satisfied,
            "forbidden_hits": list(self.forbidden_hits),
            "false_positive_paths": list(self.false_positive_paths),
            "error_codes": list(self.error_codes),
            "semantic_pass": self.semantic_pass,
            "requirements": [outcome.as_dict() for outcome in self.outcomes],
            "blocks": [outcome.as_dict() for outcome in self.block_outcomes],
        }


# --------------------------------------------------------------------------- #
# Parsing and validation
# --------------------------------------------------------------------------- #
def _string_tuple(value: Any, *, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raise ValueError(f"{field} must be a list of strings, not a string")
    if not isinstance(value, list | tuple):
        raise ValueError(f"{field} must be a list of strings")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field} contains a non-string or blank value")
        result.append(item.strip())
    return tuple(result)


def forbidden_paths_from_case(case: Mapping[str, Any]) -> tuple[str, ...]:
    """Read ``forbidden_paths``; ``{"path": ...}`` objects are accepted too."""
    raw = case.get("forbidden_paths") or []
    if not isinstance(raw, list | tuple):
        raise ValueError("forbidden_paths must be a list")
    paths: list[str] = []
    for item in raw:
        if isinstance(item, str):
            paths.append(item.strip())
        elif isinstance(item, Mapping) and isinstance(item.get("path"), str):
            paths.append(str(item["path"]).strip())
        else:
            raise ValueError("forbidden_paths entries must be strings or {path: ...} objects")
    return tuple(path for path in paths if path)


def requirements_from_case(case: Mapping[str, Any]) -> tuple[SemanticRequirement, ...]:
    raw = case.get("required_bindings")
    if not isinstance(raw, list):
        raise ValueError(f"case {case.get('id')!r} has no required_bindings list")
    requirements: list[SemanticRequirement] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise ValueError(f"required_bindings[{index}] is not an object")
        identifier = str(item.get("id") or "").strip()
        concept = str(item.get("concept") or "").strip()
        if not identifier or not concept:
            raise ValueError(f"required_bindings[{index}] needs id and concept")
        if identifier in seen:
            raise ValueError(f"duplicate requirement id {identifier!r}")
        seen.add(identifier)
        expected = _string_tuple(item.get("expected_paths"), field=f"{identifier}.expected_paths")
        alternatives = _string_tuple(
            item.get("allowed_alternatives"), field=f"{identifier}.allowed_alternatives"
        )
        satisfiable = bool(item.get("satisfiable", True))
        if not satisfiable and (expected or alternatives):
            raise ValueError(f"unsatisfiable requirement {identifier!r} must not declare paths")
        if satisfiable and not expected and not alternatives:
            raise ValueError(f"requirement {identifier!r} declares no acceptable path")
        expected_type = item.get("expected_type")
        if expected_type is not None and expected_type not in VALID_TYPES:
            raise ValueError(f"requirement {identifier!r} has invalid expected_type")
        expected_context = item.get("expected_context")
        if expected_context is not None and expected_context not in VALID_CONTEXTS:
            raise ValueError(f"requirement {identifier!r} has invalid expected_context")
        requirements.append(
            SemanticRequirement(
                id=identifier,
                concept=concept,
                expected_paths=expected,
                allowed_alternatives=alternatives,
                required=bool(item.get("required", True)),
                expected_type=expected_type,
                expected_context=expected_context,
                satisfiable=satisfiable,
                note=str(item.get("note") or ""),
            )
        )
    return tuple(requirements)


def blocks_from_case(case: Mapping[str, Any]) -> tuple[BlockRequirement, ...]:
    raw = case.get("expected_blocks") or []
    if not isinstance(raw, list | tuple):
        raise ValueError("expected_blocks must be a list")
    blocks: list[BlockRequirement] = []
    for index, item in enumerate(raw):
        if isinstance(item, str):
            kind = item
            path = None
            required = True
        elif isinstance(item, Mapping):
            kind = str(item.get("kind") or "")
            path = item.get("path")
            required = bool(item.get("required", True))
            if path is not None and not isinstance(path, str):
                raise ValueError(f"expected_blocks[{index}] path must be a string")
        else:
            raise ValueError(f"expected_blocks[{index}] is not a string or object")
        if kind not in VALID_BLOCK_KINDS:
            raise ValueError(f"expected_blocks[{index}] has invalid kind {kind!r}")
        blocks.append(
            BlockRequirement(
                kind=kind,
                path=path.strip() if isinstance(path, str) and path.strip() else None,
                required=required,
                description=str(item.get("description") or "") if isinstance(item, Mapping) else "",
            )
        )
    return tuple(blocks)


def produced_binding_from_any(value: ProducedBinding | Mapping[str, Any]) -> ProducedBinding | None:
    """Normalize a scorer input. Returns ``None`` when there is no path."""
    if isinstance(value, ProducedBinding):
        return value
    if not isinstance(value, Mapping):
        raise ValueError("produced binding must be a ProducedBinding or a mapping")
    path = value.get("path") or value.get("selected_field_path")
    if not isinstance(path, str) or not path.strip():
        return None
    contexts = value.get("contexts")
    if contexts is None:
        context = value.get("context")
        contexts = (context,) if isinstance(context, str) and context else ()
    data_type = value.get("data_type")
    return ProducedBinding(
        path=path.strip(),
        concept=str(value["concept"]) if value.get("concept") else None,
        data_type=str(data_type) if data_type else None,
        contexts=tuple(str(item) for item in contexts),
        role=str(value.get("role") or "field"),
        status=str(value["status"]) if value.get("status") else None,
    )


def produced_block_from_any(value: ProducedBlock | Mapping[str, Any]) -> ProducedBlock:
    if isinstance(value, ProducedBlock):
        return value
    if not isinstance(value, Mapping):
        raise ValueError("produced block must be a ProducedBlock or a mapping")
    kind = str(value.get("kind") or "")
    path = value.get("path")
    conditions = value.get("condition_paths") or ()
    return ProducedBlock(
        kind=kind,
        path=str(path) if isinstance(path, str) and path else None,
        condition_paths=tuple(str(item) for item in conditions),
    )


def validate_case(
    case: Mapping[str, Any], *, schema_paths: Mapping[str, str] | None = None
) -> list[str]:
    """Return human-readable problems; an empty list means the case is usable."""
    errors: list[str] = []
    case_id = case.get("id")
    if not isinstance(case_id, str) or not case_id.strip():
        errors.append("case id is missing")
        case_id = "<unknown>"
    for key in ("prompt", "package"):
        if not isinstance(case.get(key), str) or not str(case[key]).strip():
            errors.append(f"{case_id}: {key} is missing")
    labels = case.get("labels")
    if (
        not isinstance(labels, list)
        or not labels
        or not all(isinstance(item, str) and item for item in labels)
    ):
        errors.append(f"{case_id}: labels must be a non-empty list of strings")
    try:
        requirements = requirements_from_case(case)
        blocks = blocks_from_case(case)
        forbidden = forbidden_paths_from_case(case)
    except ValueError as exc:
        errors.append(f"{case_id}: {exc}")
        return errors
    if not requirements and not blocks:
        errors.append(f"{case_id}: declare at least one requirement or expected block")

    all_expected: dict[str, str] = {}
    for requirement in requirements:
        for path in (*requirement.expected_paths, *requirement.allowed_alternatives):
            if path in all_expected:
                errors.append(
                    f"{case_id}: path {path!r} is shared by requirements "
                    f"{all_expected[path]!r} and {requirement.id!r}"
                )
            else:
                all_expected[path] = requirement.id
        if schema_paths is not None:
            for path in (*requirement.expected_paths, *requirement.allowed_alternatives):
                if path not in schema_paths:
                    errors.append(f"{case_id}: {requirement.id} path {path!r} is not in the schema")
                elif requirement.expected_type is not None:
                    type_ok, _checked = _type_check(requirement.expected_type, schema_paths[path])
                    if type_ok is False:
                        errors.append(
                            f"{case_id}: {requirement.id} expects {requirement.expected_type} "
                            f"but {path!r} is {schema_paths[path]}"
                        )
    for path in forbidden:
        if path in all_expected:
            errors.append(f"{case_id}: forbidden path {path!r} is also expected")
        if schema_paths is not None and path not in schema_paths:
            errors.append(f"{case_id}: forbidden path {path!r} is not in the schema")
    seen_blocks: set[tuple[str, str | None]] = set()
    for block in blocks:
        key = (block.kind, block.path)
        if key in seen_blocks:
            errors.append(f"{case_id}: duplicate expected block {key}")
        seen_blocks.add(key)
        if block.path is not None and schema_paths is not None and block.path not in schema_paths:
            errors.append(f"{case_id}: block path {block.path!r} is not in the schema")
    return errors


def validate_cases(
    cases: Sequence[Mapping[str, Any]], *, schema_paths: Mapping[str, str] | None = None
) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for case in cases:
        case_id = case.get("id")
        if isinstance(case_id, str):
            if case_id in seen:
                errors.append(f"duplicate case id {case_id!r}")
            seen.add(case_id)
        errors.extend(validate_case(case, schema_paths=schema_paths))
    return errors


# --------------------------------------------------------------------------- #
# Matching helpers
# --------------------------------------------------------------------------- #
def _type_check(expected: str | None, actual: str | None) -> tuple[bool | None, bool]:
    """Return ``(ok, checked)``. Unknown evidence is not a failure."""
    if expected is None or actual is None:
        return None, False
    if expected == "any" or actual == "any":
        return True, True
    if expected == actual:
        return True, True
    if expected == "date" and actual == "string":
        return True, True
    if expected == "string" and actual == "date":
        return True, True
    return False, True


def _context_check(expected: str | None, contexts: tuple[str, ...]) -> tuple[bool | None, bool]:
    """Return ``(ok, checked)`` for placement. Empty evidence is not a failure."""
    if expected is None or not contexts:
        return None, False
    actual = set(contexts)
    if expected == "body":
        return "body" in actual, True
    return expected in actual, True


def _dedupe_bindings(
    values: Iterable[ProducedBinding | Mapping[str, Any]],
) -> list[ProducedBinding]:
    merged: dict[str, ProducedBinding] = {}
    for value in values:
        binding = produced_binding_from_any(value)
        if binding is None:
            continue
        existing = merged.get(binding.path)
        if existing is None:
            merged[binding.path] = binding
            continue
        merged[binding.path] = ProducedBinding(
            path=existing.path,
            concept=existing.concept or binding.concept,
            data_type=existing.data_type or binding.data_type,
            contexts=tuple(dict.fromkeys((*existing.contexts, *binding.contexts))),
            role=existing.role if existing.role != "field" else binding.role,
            status=existing.status or binding.status,
        )
    return list(merged.values())


def _ordered_codes(codes: Iterable[str]) -> tuple[str, ...]:
    unique = {code for code in codes if code}
    unknown = unique - set(ERROR_TAXONOMY)
    if unknown:
        raise ValueError(f"unknown error codes: {sorted(unknown)}")
    return tuple(sorted(unique, key=ERROR_TAXONOMY.index))


def _block_matches(requirement: BlockRequirement, block: ProducedBlock) -> bool:
    if requirement.kind != block.kind:
        return False
    if requirement.path is None:
        return True
    return block.path == requirement.path


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def score_run(
    case: Mapping[str, Any],
    produced_bindings: Sequence[ProducedBinding | Mapping[str, Any]],
    *,
    produced_blocks: Sequence[ProducedBlock | Mapping[str, Any]] = (),
    extra_error_codes: Sequence[str] = (),
) -> SemanticScore:
    """Score one run against one case.

    ``produced_bindings`` should contain every field/image/condition binding the
    run produced (absolute paths), and ``produced_blocks`` every repeat, table,
    conditional and image block. Mapping-only paths may be passed with
    ``role="mapping"``; they are matched but charged as false positives when not
    used, because the planner proposed a field the template did not contain.
    """
    requirements = requirements_from_case(case)
    block_requirements = blocks_from_case(case)
    forbidden = set(forbidden_paths_from_case(case))
    bindings = _dedupe_bindings(produced_bindings)
    blocks = [produced_block_from_any(value) for value in produced_blocks]
    by_path = {binding.path: binding for binding in bindings}
    used: set[str] = set()
    outcomes: list[RequirementOutcome] = []
    codes: list[str] = list(extra_error_codes)
    matched_requirements = 0
    matched_required = 0
    required_requirements = 0
    satisfiable_requirements = 0
    unsatisfiable_requirements = 0
    type_checks = 0
    type_correct = 0

    for requirement in requirements:
        if not requirement.satisfiable:
            unsatisfiable_requirements += 1
            claim = next(
                (
                    binding
                    for binding in bindings
                    if binding.concept
                    and binding.concept.casefold() == requirement.concept.casefold()
                ),
                None,
            )
            if claim is not None:
                codes.append("wrong_binding")
            outcomes.append(
                RequirementOutcome(
                    requirement_id=requirement.id,
                    concept=requirement.concept,
                    required=requirement.required,
                    satisfiable=False,
                    status="unsatisfiable",
                    matched_path=claim.path if claim else None,
                    matched_via="claimed" if claim else None,
                    error_codes=("wrong_binding",) if claim else (),
                )
            )
            continue

        satisfiable_requirements += 1
        if requirement.required:
            required_requirements += 1

        match: ProducedBinding | None = None
        via: str | None = None
        for candidate_path in requirement.expected_paths:
            candidate = by_path.get(candidate_path)
            if (
                candidate is not None
                and candidate.path not in used
                and candidate.path not in forbidden
            ):
                match = candidate
                via = "expected"
                break
        if match is None:
            for candidate_path in requirement.allowed_alternatives:
                candidate = by_path.get(candidate_path)
                if (
                    candidate is not None
                    and candidate.path not in used
                    and candidate.path not in forbidden
                ):
                    match = candidate
                    via = "alternative"
                    break

        if match is not None:
            used.add(match.path)
            # The label deliberately accepts more than one path for an ambiguous
            # concept. Producing two acceptable variants is redundant, not a
            # false positive, so the other annotated paths are marked used too.
            # They are not counted as additional true positives and forbidden
            # paths are never exempted.
            for acceptable_path in (*requirement.expected_paths, *requirement.allowed_alternatives):
                variant = by_path.get(acceptable_path)
                if variant is not None and variant.path not in forbidden:
                    used.add(variant.path)
            matched_requirements += 1
            if requirement.required:
                matched_required += 1
            type_ok, type_checked = _type_check(requirement.expected_type, match.data_type)
            context_ok, context_checked = _context_check(
                requirement.expected_context, match.contexts
            )
            if type_checked:
                type_checks += 1
                type_correct += 1 if type_ok is True else 0
            if context_checked:
                type_checks += 1
                type_correct += 1 if context_ok is True else 0
            outcome_codes: list[str] = []
            if type_ok is False:
                outcome_codes.append(
                    "wrong_context"
                    if match.data_type in {"collection", "object"}
                    or requirement.expected_type in {"collection", "object"}
                    else "wrong_binding"
                )
            if context_ok is False:
                outcome_codes.append("wrong_context")
            codes.extend(outcome_codes)
            outcomes.append(
                RequirementOutcome(
                    requirement_id=requirement.id,
                    concept=requirement.concept,
                    required=requirement.required,
                    satisfiable=True,
                    status="matched" if via == "expected" else "alternative",
                    matched_path=match.path,
                    matched_via=via,
                    type_ok=type_ok,
                    context_ok=context_ok,
                    type_checked=type_checked,
                    context_checked=context_checked,
                    error_codes=_ordered_codes(outcome_codes),
                )
            )
            continue

        # No acceptable path. If the run bound the right concept to the wrong
        # path, evaluate that path's type/context too: an object/collection used
        # where a scalar was requested is exactly the error this metric exists
        # to expose.
        wrong = next(
            (
                binding
                for binding in bindings
                if binding.path not in used
                and binding.path not in forbidden
                and binding.concept
                and binding.concept.casefold() == requirement.concept.casefold()
            ),
            None,
        )
        type_ok = context_ok = None
        type_checked = context_checked = False
        wrong_codes: list[str] = []
        if wrong is not None:
            type_ok, type_checked = _type_check(requirement.expected_type, wrong.data_type)
            context_ok, context_checked = _context_check(
                requirement.expected_context, wrong.contexts
            )
            if type_checked:
                type_checks += 1
                type_correct += 1 if type_ok is True else 0
            if context_checked:
                type_checks += 1
                type_correct += 1 if context_ok is True else 0
            wrong_codes.append(
                "wrong_context"
                if wrong.data_type in {"collection", "object"}
                or requirement.expected_type in {"collection", "object"}
                else "wrong_binding"
            )
            if context_ok is False:
                wrong_codes.append("wrong_context")
        if requirement.required:
            wrong_codes.append("missing_field")
        codes.extend(wrong_codes)
        outcomes.append(
            RequirementOutcome(
                requirement_id=requirement.id,
                concept=requirement.concept,
                required=requirement.required,
                satisfiable=True,
                status="wrong_path"
                if wrong is not None
                else ("missing" if requirement.required else "optional_missing"),
                matched_path=wrong.path if wrong else None,
                matched_via="wrong_path" if wrong else None,
                type_ok=type_ok,
                context_ok=context_ok,
                type_checked=type_checked,
                context_checked=context_checked,
                error_codes=_ordered_codes(wrong_codes),
            )
        )

    # ------------------------------------------------------------------ blocks
    block_outcomes: list[BlockOutcome] = []
    for requirement in block_requirements:
        satisfied = any(_block_matches(requirement, block) for block in blocks)
        if not satisfied and requirement.required:
            codes.append(
                "unsupported_expression" if requirement.kind == "conditional" else "wrong_context"
            )
        block_outcomes.append(
            BlockOutcome(
                kind=requirement.kind,
                path=requirement.path,
                required=requirement.required,
                satisfied=satisfied,
            )
        )

    # ------------------------------------------------------- false positives
    forbidden_hits = tuple(
        sorted({binding.path for binding in bindings if binding.path in forbidden})
    )
    if forbidden_hits:
        codes.append("wrong_binding")
    fp_paths: set[str] = set(forbidden_hits)
    for binding in bindings:
        if binding.path in used or binding.path in forbidden:
            continue
        if binding.role == "condition":
            # A condition field is semantic plumbing, not document content. If
            # it is wrong, the requirement outcome above already charged it.
            continue
        fp_paths.add(binding.path)
        codes.append(
            "wrong_context" if binding.data_type in {"collection", "object"} else "wrong_binding"
        )

    true_positives = matched_requirements
    false_positives = len(fp_paths)
    false_negatives = sum(
        1
        for outcome in outcomes
        if outcome.required and outcome.satisfiable and not outcome.satisfied
    )
    precision = (
        round(true_positives / (true_positives + false_positives), 6)
        if true_positives + false_positives
        else None
    )
    recall = round(matched_required / required_requirements, 6) if required_requirements else None
    coverage = (
        round(matched_requirements / satisfiable_requirements, 6)
        if satisfiable_requirements
        else None
    )
    type_context_correctness = round(type_correct / type_checks, 6) if type_checks else None
    satisfied_blocks = sum(1 for outcome in block_outcomes if outcome.satisfied)
    block_coverage = round(satisfied_blocks / len(block_outcomes), 6) if block_outcomes else None
    if precision is None or recall is None:
        f1 = None
    elif precision + recall == 0:
        f1 = 0.0
    else:
        f1 = round(2 * precision * recall / (precision + recall), 6)

    required_ok = all(
        outcome.satisfied and outcome.type_ok is not False and outcome.context_ok is not False
        for outcome in outcomes
        if outcome.required and outcome.satisfiable
    )
    unsat_claimed = any(
        not outcome.satisfiable and outcome.matched_path is not None for outcome in outcomes
    )
    blocks_ok = all(outcome.satisfied for outcome in block_outcomes if outcome.required)
    semantic_pass = required_ok and not unsat_claimed and blocks_ok and not forbidden_hits

    return SemanticScore(
        precision=precision,
        recall=recall,
        requirement_coverage=coverage,
        type_context_correctness=type_context_correctness,
        block_coverage=block_coverage,
        f1=f1,
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        matched_requirements=matched_requirements,
        matched_required=matched_required,
        required_requirements=required_requirements,
        satisfiable_requirements=satisfiable_requirements,
        unsatisfiable_requirements=unsatisfiable_requirements,
        type_context_checks=type_checks,
        type_context_correct=type_correct,
        block_total=len(block_outcomes),
        block_satisfied=satisfied_blocks,
        forbidden_hits=forbidden_hits,
        false_positive_paths=tuple(sorted(fp_paths)),
        error_codes=_ordered_codes(codes),
        semantic_pass=semantic_pass,
        outcomes=tuple(outcomes),
        block_outcomes=tuple(block_outcomes),
    )


# --------------------------------------------------------------------------- #
# Failure taxonomy
# --------------------------------------------------------------------------- #
_STRUCTURED_MARKERS = (
    "unknown key",
    "unknown block",
    "unknown form",
    "unknown format",
    "unknown operator",
    "expected an array",
    "expected a block",
    "missing required key",
    "mixes forms",
    "invalid json",
    "json",
)
_CONTEXT_MARKERS = (
    "context",
    "collection",
    "type mismatch",
    "does not match",
    "cannot be used as a scalar",
)
_EXPRESSION_MARKERS = ("expression", "condition", "operator", "operand")


def _redact(text: str) -> str:
    return _SECRET.sub("[redacted]", text)[:500]


def classify_exception(exc: BaseException) -> tuple[str, str]:
    """Map an exception to ``(taxonomy_code, safe_message)``."""
    if isinstance(exc, PlanInvalidError):
        message = exc.message.lower()
        if any(marker in message for marker in _EXPRESSION_MARKERS):
            return "unsupported_expression", _redact(exc.message)
        return "structured_output", _redact(exc.message)
    if isinstance(exc, ProviderError):
        details = exc.details or {}
        reason = str(details.get("reason", ""))
        status = details.get("status")
        if reason == "output_truncated" or exc.code == "output_truncated":
            return "structured_output", _redact(exc.message)
        if exc.code == "provider_timeout":
            return "timeout", _redact(exc.message)
        if status == 429 or exc.code in {"quota_exceeded", "rate_limited"}:
            return "quota", _redact(exc.message)
        if exc.code in {"provider_invalid_output", "plan_invalid", "model_required"}:
            return "structured_output", _redact(exc.message)
        return "provider_api", _redact(exc.message)
    if isinstance(exc, CompilationFailedError):
        return "compilation", _redact(exc.message)
    if isinstance(exc, ValidationFailedError):
        message = exc.message.lower()
        if any(marker in message for marker in _EXPRESSION_MARKERS):
            return "unsupported_expression", _redact(exc.message)
        if any(marker in message for marker in _CONTEXT_MARKERS):
            return "wrong_context", _redact(exc.message)
        if "does not exist" in message or "not found" in message:
            return "wrong_binding", _redact(exc.message)
        return "harness", _redact(exc.message)
    if isinstance(exc, TimeoutError):
        return "timeout", "the provider did not respond in time"
    if isinstance(exc, InvalidInputError):
        return "structured_output", _redact(exc.message)
    if type(exc).__name__ == "RenderError":
        return "renderer", _redact(str(exc))
    return "harness", _redact(f"{type(exc).__name__}: {exc}")


def taxonomy_for_validation_codes(codes: Iterable[str]) -> tuple[str, ...]:
    """Map validator finding codes (``V1-001`` ...) to the report taxonomy."""
    mapped: list[str] = []
    for code in codes:
        if code in {"V2-002", "V2-003", "V3-001", "V3-003"}:
            mapped.append("wrong_context")
        elif code in {"V2-001", "V2-004", "V3-004"}:
            mapped.append("wrong_binding")
        elif code in {"V3-002"}:
            mapped.append("unsupported_expression")
        elif code.startswith("V1-"):
            mapped.append("structured_output")
        else:
            mapped.append("harness")
    return _ordered_codes(mapped)


__all__ = [
    "ERROR_TAXONOMY",
    "PROCEDURAL_ERROR_CODES",
    "SEMANTIC_ERROR_CODES",
    "VALID_BLOCK_KINDS",
    "VALID_CONTEXTS",
    "VALID_TYPES",
    "BlockOutcome",
    "BlockRequirement",
    "ProducedBinding",
    "ProducedBlock",
    "RequirementOutcome",
    "SemanticRequirement",
    "SemanticScore",
    "blocks_from_case",
    "classify_exception",
    "forbidden_paths_from_case",
    "produced_binding_from_any",
    "produced_block_from_any",
    "requirements_from_case",
    "score_run",
    "taxonomy_for_validation_codes",
    "validate_case",
    "validate_cases",
]
