"""Typed D365 binding resolution (v0.10 PR-03).

The resolver matches the ``Source``/``Path``/``ResultDataType`` facts extracted
from Docentric ``ProjectData`` against the canonical schema built by
:mod:`docentric_copilot.reference.d365_schema`.

Resolution is exact and deterministic. There is no similarity search, fuzzy
matching or LLM call anywhere on the ``resolved`` path: a binding resolves only
when the source exists exactly once, the path exists exactly once in that
source, the collection scope is valid and the declared result type is
compatible with the schema type. Everything else gets one of the five explicit
non-success statuses. Suggestions are diagnostics only and never change a
status.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from .d365_schema import (
    CanonicalField,
    CanonicalSource,
    D365DocumentSchema,
    DiagnosticSeverity,
    ProjectElementFact,
    SchemaDiagnostic,
    SchemaSourceKind,
    extract_d365_schema,
    extract_d365_schema_path,
)
from .safety import ReferenceLimits

REPORT_VERSION: Final[Literal["1.0"]] = "1.0"
RUNTIME_COMPATIBILITY: Final[Literal["not_tested"]] = "not_tested"
_PLATFORM: Final[Literal["D365FO"]] = "D365FO"

_MAX_BINDING_RESULTS: Final = 10_000
_MAX_DIAGNOSTICS: Final = 1_000
_MAX_WARNINGS: Final = 100
_MAX_SUGGESTIONS: Final = 5
_MAX_CONTEXT_DEPTH: Final = 10

_SOURCE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*$")
_SEGMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*$")
_UNSUPPORTED_PATH_CHARS = frozenset("()[],=<>!&|+*'\"{}?;#$%~^` \t\r\n")
_XML_WHITESPACE = frozenset(" \t\r\n")

#: ``System.*`` result type -> canonical family.
_RESULT_FAMILIES: Final[dict[str, str]] = {
    "system.string": "text",
    "system.char": "text",
    "system.guid": "text",
    "system.object": "unknown",
    "system.decimal": "number",
    "system.double": "number",
    "system.single": "number",
    "system.float": "number",
    "system.int16": "number",
    "system.int32": "number",
    "system.int64": "number",
    "system.uint16": "number",
    "system.uint32": "number",
    "system.uint64": "number",
    "system.byte": "number",
    "system.sbyte": "number",
    "system.intptr": "number",
    "system.uintptr": "number",
    "system.datetime": "temporal",
    "system.datetimeoffset": "temporal",
    "system.date": "temporal",
    "system.time": "temporal",
    "system.timespan": "temporal",
    "system.boolean": "boolean",
    "system.byte[]": "binary",
}


class BindingStatus(str, Enum):
    """The normative v0.10 binding status taxonomy (exactly six values)."""

    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNKNOWN_PATH = "unknown_path"
    TYPE_MISMATCH = "type_mismatch"
    SCHEMA_UNAVAILABLE = "schema_unavailable"
    UNSUPPORTED_EXPRESSION = "unsupported_expression"


class BindingKind(str, Enum):
    """Which ProjectData fact produced a binding request."""

    VALUE = "value_binding"
    LABEL = "label_data_path"


class BindingResult(BaseModel):
    """One binding request and its exact resolution outcome."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    element_id: str = Field(pattern=r"^[0-9]+$", max_length=20)
    element_type: str = Field(min_length=1, max_length=80)
    element_part: str = Field(min_length=1, max_length=240)
    binding_kind: BindingKind
    status: BindingStatus
    raw_source: str | None = Field(default=None, max_length=120)
    raw_path: str | None = Field(default=None, max_length=512)
    canonical_path: str | None = Field(default=None, max_length=1_800)
    source_id: str | None = Field(default=None, max_length=300)
    evidence: str | None = Field(default=None, max_length=2_000)
    schema_type: str | None = Field(default=None, max_length=120)
    result_data_type: str | None = Field(default=None, max_length=120)
    collection_scope: str | None = Field(default=None, max_length=1_800)
    diagnostic_codes: list[str] = Field(default_factory=list, max_length=20)
    suggestions: list[str] = Field(default_factory=list, max_length=_MAX_SUGGESTIONS)


class BindingCounts(BaseModel):
    """Deterministic aggregate counts; every request is counted once."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    total: int = Field(ge=0)
    resolved: int = Field(ge=0)
    ambiguous: int = Field(ge=0)
    unknown_path: int = Field(ge=0)
    type_mismatch: int = Field(ge=0)
    schema_unavailable: int = Field(ge=0)
    unsupported_expression: int = Field(ge=0)
    by_status: dict[str, int] = Field(default_factory=dict)
    resolved_with_evidence: int = Field(ge=0)
    resolved_without_evidence: int = Field(ge=0)


class SchemaSummary(BaseModel):
    """Bounded size/availability summary of the canonical schema."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_data_parts: int = Field(ge=0)
    sources: int = Field(ge=0)
    fields: int = Field(ge=0)
    collections: int = Field(ge=0)
    preview_data_sources: int = Field(ge=0)
    namespaces: list[str] = Field(default_factory=list, max_length=40)
    available: bool = False


class D365BindingReport(BaseModel):
    """The v0.10 result contract for one D365 template (spec §3.3)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    report_version: Literal["1.0"] = REPORT_VERSION
    template_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    platform: Literal["D365FO"] = _PLATFORM
    schema_source: SchemaSourceKind
    schema_evidence: list[str] = Field(default_factory=list, max_length=64)
    binding_results: list[BindingResult] = Field(
        default_factory=list, max_length=_MAX_BINDING_RESULTS
    )
    runtime_compatibility: Literal["not_tested"] = RUNTIME_COMPATIBILITY
    counts: BindingCounts
    schema_summary: SchemaSummary
    diagnostics: list[SchemaDiagnostic] = Field(default_factory=list, max_length=_MAX_DIAGNOSTICS)
    warnings: list[str] = Field(default_factory=list, max_length=_MAX_WARNINGS)


@dataclass(frozen=True, slots=True)
class _Path:
    """Parsed, still unevaluated binding path."""

    segments: tuple[str, ...]
    absolute: bool
    prefixes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _PathFailure:
    code: str


@dataclass(frozen=True, slots=True)
class _Request:
    fact: ProjectElementFact
    kind: BindingKind
    source: str | None
    path: str | None
    data_section: str | None


@dataclass(slots=True)
class _Resolution:
    status: BindingStatus
    codes: set[str]
    field: CanonicalField | None = None
    suggestions: tuple[str, ...] = ()


def _normalize_type(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _result_family(value: str | None) -> str | None:
    if value is None:
        return None
    key = value.strip().casefold().replace(" ", "")
    family = _RESULT_FAMILIES.get(key)
    if family == "unknown":
        return None
    return family


def _parse_path(raw: str | None) -> _Path | _PathFailure | None:
    """Parse the supported Docentric path subset without evaluating it."""
    if raw is None:
        return None
    text = raw.strip().strip('"').strip("'")
    if not text:
        return None
    text = text.replace("\\", "/")
    if "/" not in text and "." in text and not text.startswith(("@", ".")) and text != ".":
        text = text.replace(".", "/")
    if any(char in _UNSUPPORTED_PATH_CHARS for char in text):
        return _PathFailure("unsupported_path_expression")
    absolute = text.startswith("/")
    body = text.strip("/")
    if not body:
        return None
    segments = body.split("/")
    if any(not segment for segment in segments):
        return _PathFailure("empty_path_segment")
    parsed: list[str] = []
    prefixes: set[str] = set()
    for index, segment in enumerate(segments):
        if segment in {".", ".."}:
            parsed.append(segment)
            continue
        if segment.startswith("@"):
            name = segment[1:]
            if ":" in name:
                prefix, name = name.split(":", 1)
                if prefix:
                    prefixes.add(prefix)
            if not _SEGMENT_NAME.match(name):
                return _PathFailure("unsupported_path_segment")
            parsed.append(f"@{name}")
            if index != len(segments) - 1:
                return _PathFailure("attribute_not_terminal")
            continue
        if ":" in segment:
            prefix, segment = segment.split(":", 1)
            if prefix:
                prefixes.add(prefix)
        if not _SEGMENT_NAME.match(segment):
            return _PathFailure("unsupported_path_segment")
        parsed.append(segment)
    if not parsed:
        return None
    return _Path(segments=tuple(parsed), absolute=absolute, prefixes=tuple(sorted(prefixes)))


def _apply_segments(
    base: tuple[str, ...],
    segments: tuple[str, ...],
    *,
    absolute: bool,
) -> tuple[str, ...] | None:
    parts: list[str] = [] if absolute else list(base)
    for segment in segments:
        if segment == ".":
            continue
        if segment == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(segment)
    return tuple(parts) if parts else None


def _candidate_raw_paths(source_roots: Iterable[str], relative: tuple[str, ...]) -> list[str]:
    joined = "/".join(relative)
    candidates: list[str] = []
    roots = sorted(set(source_roots))
    if not roots:
        return []
    for root in roots:
        if joined == root or joined.startswith(f"{root}/"):
            candidates.append(joined)
        else:
            candidates.append(f"{root}/{joined}" if joined else root)
    return candidates


class _Resolver:
    def __init__(self, document: D365DocumentSchema) -> None:
        self.document = document
        self.canonical = document.canonical
        self.fields = list(self.canonical.fields)
        self.has_schema = self.canonical.is_available() and bool(self.fields)
        self.sources_by_name: dict[str, list[CanonicalSource]] = {}
        self.sources_by_id: dict[str, CanonicalSource] = {}
        self.fields_by_source: dict[str, dict[str, list[CanonicalField]]] = {}
        for source in self.canonical.sources:
            self.sources_by_name.setdefault(source.name, []).append(source)
            self.sources_by_id[source.source_id] = source
        for field in self.fields:
            self.fields_by_source.setdefault(field.source_id, {}).setdefault(
                field.raw_path, []
            ).append(field)
        self.children_of: dict[tuple[str, str], list[ProjectElementFact]] = {}
        for fact in document.elements:
            for child_id in fact.child_ids:
                self.children_of.setdefault((fact.part, child_id), []).append(fact)
        self._request_cache: dict[tuple[str, str], _Resolution] = {}

    # -- helpers --------------------------------------------------------
    def _parents_of(self, fact: ProjectElementFact) -> list[ProjectElementFact]:
        return self.children_of.get((fact.part, fact.element_id), [])

    def _source(self, field: CanonicalField) -> CanonicalSource:
        return self.sources_by_id[field.source_id]

    def _suggestions_for_source(self, source_name: str) -> tuple[str, ...]:
        names = sorted(self.sources_by_name)
        return tuple(names[:_MAX_SUGGESTIONS])

    def _suggestions_for_path(self, source_id: str, first: str) -> tuple[str, ...]:
        index = self.fields_by_source.get(source_id, {})
        paths = sorted(index)
        if not first:
            return tuple(paths[:_MAX_SUGGESTIONS])
        same_root = [path for path in paths if path.split("/", 1)[0] == first]
        if same_root:
            return tuple(same_root[:_MAX_SUGGESTIONS])
        partial = [path for path in paths if first in path]
        return tuple((partial or paths)[:_MAX_SUGGESTIONS])

    def _validate_prefixes(self, source: CanonicalSource, parsed: _Path) -> _Resolution | None:
        """Reject prefixed paths unless the prefix maps to the data namespace.

        A local-name-only match would silently ignore XML namespaces, so a
        prefix that is undeclared or maps to a non-data namespace is reported as
        an unsupported expression instead of being resolved.
        """
        if not parsed.prefixes:
            return None
        mappings = source.namespace_mappings
        data_namespace = (source.namespace or "").rstrip("/")
        for prefix in parsed.prefixes:
            uri = mappings.get(prefix)
            if uri is None:
                return _Resolution(
                    BindingStatus.UNSUPPORTED_EXPRESSION,
                    {"namespace_prefix_unresolved"},
                )
            if (uri or "").rstrip("/") != data_namespace:
                return _Resolution(
                    BindingStatus.UNSUPPORTED_EXPRESSION,
                    {"namespace_prefix_mismatch"},
                )
        return None

    # -- resolution -----------------------------------------------------
    def resolve(self, request: _Request) -> _Resolution:
        if not self.has_schema:
            return _Resolution(BindingStatus.SCHEMA_UNAVAILABLE, {"schema_unavailable"})
        parsed = _parse_path(request.path)
        if isinstance(parsed, _PathFailure):
            return _Resolution(BindingStatus.UNSUPPORTED_EXPRESSION, {parsed.code})
        if parsed is None:
            return _Resolution(BindingStatus.UNKNOWN_PATH, {"binding_path_missing"})

        if request.kind is BindingKind.LABEL:
            source_result = self._source_from_data_section(request)
            if isinstance(source_result, _Resolution):
                return source_result
            source = source_result
        else:
            raw_source = request.source
            if raw_source is None or not raw_source.strip():
                return _Resolution(BindingStatus.UNKNOWN_PATH, {"binding_source_missing"})
            raw_source = raw_source.strip()
            if raw_source == ".":
                return self._resolve_relative(request, parsed)
            if not _SOURCE_NAME.match(raw_source):
                return _Resolution(
                    BindingStatus.UNSUPPORTED_EXPRESSION,
                    {"unsupported_source_expression"},
                )
            matches = self.sources_by_name.get(raw_source, [])
            if not matches:
                return _Resolution(
                    BindingStatus.UNKNOWN_PATH,
                    {"source_not_found"},
                    suggestions=self._suggestions_for_source(raw_source),
                )
            if len(matches) > 1:
                return _Resolution(BindingStatus.AMBIGUOUS, {"duplicate_source_name"})
            source = matches[0]

        return self._resolve_absolute(source, parsed, request)

    def _source_from_data_section(self, request: _Request) -> CanonicalSource | _Resolution:
        section = (request.data_section or "").strip()
        if not section:
            return _Resolution(BindingStatus.UNKNOWN_PATH, {"data_section_missing"})
        matches = [
            source
            for source in self.canonical.sources
            if (source.data_section_type or "").strip() == section
        ]
        if not matches:
            return _Resolution(BindingStatus.UNKNOWN_PATH, {"data_section_source_missing"})
        if len(matches) > 1:
            return _Resolution(BindingStatus.AMBIGUOUS, {"data_section_source_ambiguous"})
        return matches[0]

    def _resolve_absolute(
        self, source: CanonicalSource, parsed: _Path, request: _Request
    ) -> _Resolution:
        if not source.has_schema:
            return _Resolution(BindingStatus.UNKNOWN_PATH, {"source_schema_missing"})
        if not source.root_names:
            return _Resolution(BindingStatus.UNKNOWN_PATH, {"source_root_missing"})
        prefix_failure = self._validate_prefixes(source, parsed)
        if prefix_failure is not None:
            return prefix_failure
        relative = _apply_segments((), parsed.segments, absolute=True)
        if relative is None:
            return _Resolution(BindingStatus.UNKNOWN_PATH, {"path_navigation_invalid"})
        candidates = _candidate_raw_paths(source.root_names, relative)
        return self._lookup(source, candidates, parsed, request)

    def _resolve_relative(self, request: _Request, parsed: _Path) -> _Resolution:
        context = self._relative_context(request.fact, frozenset())
        if isinstance(context, _Resolution):
            return context
        field, source = context
        if not field.is_collection:
            return _Resolution(
                BindingStatus.UNKNOWN_PATH,
                {"relative_context_not_collection"},
            )
        prefix_failure = self._validate_prefixes(source, parsed)
        if prefix_failure is not None:
            return prefix_failure
        base = tuple(field.raw_path.split("/"))
        relative = _apply_segments(base, parsed.segments, absolute=parsed.absolute)
        if relative is None:
            return _Resolution(BindingStatus.UNKNOWN_PATH, {"path_navigation_invalid"})
        if parsed.absolute:
            candidates = _candidate_raw_paths(source.root_names, relative)
        else:
            candidates = ["/".join(relative)]
        return self._lookup(source, candidates, parsed, request)

    def _relative_context(
        self,
        fact: ProjectElementFact,
        stack: frozenset[tuple[str, str]],
    ) -> tuple[CanonicalField, CanonicalSource] | _Resolution:
        key = (fact.part, fact.element_id)
        cached = self._request_cache.get(key)
        if cached is not None:
            if cached.status is not BindingStatus.RESOLVED or cached.field is None:
                return cached
            return cached.field, self._source(cached.field)
        if key in stack:
            return _Resolution(BindingStatus.UNKNOWN_PATH, {"relative_binding_cycle"})
        parents = self._parents_of(fact)
        if not parents:
            return _Resolution(BindingStatus.UNKNOWN_PATH, {"relative_binding_without_context"})
        results: list[_Resolution] = []
        for parent in parents:
            outcome = self._nearest_list_context(parent, stack | {key})
            if isinstance(outcome, _Resolution):
                results.append(outcome)
            else:
                field, _source = outcome
                results.append(_Resolution(BindingStatus.RESOLVED, set(), field=field))
        if not results:
            return _Resolution(BindingStatus.UNKNOWN_PATH, {"relative_binding_without_context"})
        failures = [item for item in results if item.status is not BindingStatus.RESOLVED]
        if failures:
            statuses = {item.status for item in failures}
            codes = set().union(*(item.codes for item in failures))
            if BindingStatus.AMBIGUOUS in statuses:
                return _Resolution(BindingStatus.AMBIGUOUS, codes | {"relative_context_ambiguous"})
            if BindingStatus.SCHEMA_UNAVAILABLE in statuses:
                return _Resolution(
                    BindingStatus.SCHEMA_UNAVAILABLE,
                    codes | {"relative_context_schema_unavailable"},
                )
            if BindingStatus.UNSUPPORTED_EXPRESSION in statuses:
                return _Resolution(
                    BindingStatus.UNSUPPORTED_EXPRESSION,
                    codes | {"relative_context_unsupported"},
                )
            return _Resolution(BindingStatus.UNKNOWN_PATH, codes | {"relative_context_unresolved"})
        resolved_fields = {
            item.field.canonical_path: item.field for item in results if item.field is not None
        }
        if len(resolved_fields) > 1:
            return _Resolution(BindingStatus.AMBIGUOUS, {"multiple_relative_contexts"})
        field = next(iter(resolved_fields.values()))
        if field is None:  # pragma: no cover - defensive
            return _Resolution(BindingStatus.UNKNOWN_PATH, {"relative_binding_without_context"})
        resolution = _Resolution(BindingStatus.RESOLVED, set(), field=field)
        self._request_cache[key] = resolution
        return field, self._source(field)

    def _nearest_list_context(
        self,
        fact: ProjectElementFact,
        stack: frozenset[tuple[str, str]],
    ) -> tuple[CanonicalField, CanonicalSource] | _Resolution:
        key = (fact.part, fact.element_id)
        if key in stack:
            return _Resolution(BindingStatus.UNKNOWN_PATH, {"relative_binding_cycle"})
        is_list = _normalize_type(fact.element_type) == "list"
        has_binding = fact.path is not None or fact.data_xpath is not None
        if is_list:
            if not has_binding:
                return _Resolution(
                    BindingStatus.UNKNOWN_PATH,
                    {"relative_context_without_binding"},
                )
            kind = (
                BindingKind.VALUE
                if fact.path is not None or fact.source is not None
                else BindingKind.LABEL
            )
            request = _Request(
                fact=fact,
                kind=kind,
                source=fact.source,
                path=fact.path if kind is BindingKind.VALUE else fact.data_xpath,
                data_section=fact.data_section,
            )
            outcome = self.resolve(request)
            if outcome.status is not BindingStatus.RESOLVED or outcome.field is None:
                return outcome
            return outcome.field, self._source(outcome.field)
        parents = self._parents_of(fact)
        if not parents:
            return _Resolution(BindingStatus.UNKNOWN_PATH, {"relative_binding_without_context"})
        results: list[tuple[CanonicalField, CanonicalSource] | _Resolution] = []
        for parent in parents:
            parent_outcome = self._nearest_list_context(parent, stack | {key})
            results.append(parent_outcome)
        resolved = [item for item in results if not isinstance(item, _Resolution)]
        failures = [item for item in results if isinstance(item, _Resolution)]
        if resolved:
            unique = {item[0].canonical_path: item for item in resolved}
            if len(unique) > 1:
                return _Resolution(BindingStatus.AMBIGUOUS, {"multiple_relative_contexts"})
            return next(iter(unique.values()))
        if failures:
            return failures[0]
        return _Resolution(BindingStatus.UNKNOWN_PATH, {"relative_binding_without_context"})

    def _lookup(
        self,
        source: CanonicalSource,
        candidates: list[str],
        parsed: _Path,
        request: _Request,
    ) -> _Resolution:
        index = self.fields_by_source.get(source.source_id, {})
        found: list[CanonicalField] = []
        seen: set[tuple[str, str]] = set()
        for candidate in candidates:
            for field in index.get(candidate, []):
                marker = (field.canonical_path, field.provenance.xpath)
                if marker in seen:
                    continue
                seen.add(marker)
                found.append(field)
        if not found:
            first = parsed.segments[0] if parsed.segments else ""
            if first in {".", ".."}:
                first = parsed.segments[-1] if parsed.segments else ""
            first = first.lstrip("@")
            return _Resolution(
                BindingStatus.UNKNOWN_PATH,
                {"path_not_found"},
                suggestions=self._suggestions_for_path(source.source_id, first),
            )
        if len(found) > 1:
            return _Resolution(BindingStatus.AMBIGUOUS, {"duplicate_schema_path"})
        field = found[0]
        mismatch = self._type_check(field, request)
        if mismatch is not None:
            return mismatch
        return _Resolution(BindingStatus.RESOLVED, set(), field=field)

    def _type_check(self, field: CanonicalField, request: _Request) -> _Resolution | None:
        schema_family = field.type_family
        if schema_family == "unknown":
            return _Resolution(
                BindingStatus.UNSUPPORTED_EXPRESSION,
                {"schema_type_unresolved"},
                field=field,
            )
        result_family = _result_family(request.fact.result_data_type)
        if result_family is not None and schema_family not in {"unknown", "any"}:
            compatible = result_family == schema_family
            if not compatible and schema_family == "enum" and result_family == "text":
                compatible = True
            if not compatible:
                return _Resolution(
                    BindingStatus.TYPE_MISMATCH,
                    {"result_type_conflict"},
                    field=field,
                )
        element_kind = _normalize_type(request.fact.element_type)
        if element_kind == "if" and schema_family not in {"boolean", "unknown", "any"}:
            return _Resolution(
                BindingStatus.TYPE_MISMATCH,
                {"if_requires_boolean"},
                field=field,
            )
        if element_kind == "list" and not field.is_collection:
            return _Resolution(
                BindingStatus.TYPE_MISMATCH,
                {"list_requires_collection"},
                field=field,
            )
        if element_kind in {"field", "label", "barcode"}:
            if field.is_collection:
                return _Resolution(
                    BindingStatus.TYPE_MISMATCH,
                    {"scalar_binding_to_collection"},
                    field=field,
                )
            if field.node_kind == "complex" and schema_family != "enum":
                return _Resolution(
                    BindingStatus.TYPE_MISMATCH,
                    {"complex_node_not_scalar"},
                    field=field,
                )
        if (
            element_kind == "image"
            and result_family == "binary"
            and schema_family not in {"binary", "unknown", "any"}
        ):
            return _Resolution(
                BindingStatus.TYPE_MISMATCH,
                {"image_requires_binary"},
                field=field,
            )
        return None


def _requests(document: D365DocumentSchema) -> list[_Request]:
    requests: list[_Request] = []
    for fact in document.elements:
        if fact.path is not None or fact.source is not None:
            requests.append(
                _Request(
                    fact=fact,
                    kind=BindingKind.VALUE,
                    source=fact.source,
                    path=fact.path,
                    data_section=None,
                )
            )
        elif fact.data_xpath is not None or fact.data_section is not None:
            requests.append(
                _Request(
                    fact=fact,
                    kind=BindingKind.LABEL,
                    source=None,
                    path=fact.data_xpath,
                    data_section=fact.data_section,
                )
            )
    requests.sort(
        key=lambda item: (
            item.fact.part,
            int(item.fact.element_id),
            item.kind.value,
            item.fact.xpath,
        )
    )
    return requests[:_MAX_BINDING_RESULTS]


def _status_from_resolution(resolution: _Resolution, request: _Request) -> BindingResult:
    fact = request.fact
    field = resolution.field
    codes = set(resolution.codes)
    if resolution.status is not BindingStatus.RESOLVED:
        codes.add(resolution.status.value)
    ordered_codes = sorted(codes)
    return BindingResult(
        element_id=fact.element_id,
        element_type=fact.element_type,
        element_part=fact.part,
        binding_kind=request.kind,
        status=resolution.status,
        raw_source=request.source,
        raw_path=request.path,
        canonical_path=field.canonical_path if field is not None else None,
        source_id=field.source_id if field is not None else None,
        evidence=(
            f"{field.provenance.part}#{field.provenance.xpath}" if field is not None else None
        ),
        schema_type=((field.xsd_type or field.type_family) if field is not None else None),
        result_data_type=fact.result_data_type,
        collection_scope=(
            (field.canonical_path if field.is_collection else field.collection_scope)
            if field is not None
            else None
        ),
        diagnostic_codes=ordered_codes,
        suggestions=list(resolution.suggestions),
    )


def _binding_diagnostic(result: BindingResult, fact: ProjectElementFact) -> SchemaDiagnostic | None:
    if result.status is BindingStatus.RESOLVED:
        return None
    return SchemaDiagnostic(
        code=f"binding_{result.status.value}",
        severity=DiagnosticSeverity.WARNING,
        message=(
            f"Element {result.element_id} ({result.element_type}) is "
            f"{result.status.value}: "
            + ", ".join(code for code in result.diagnostic_codes if code != result.status.value)
        ),
        part=result.element_part,
        xpath=fact.xpath,
        source_id=result.source_id,
        details={
            "status": result.status.value,
            "raw_source": result.raw_source or "",
            "raw_path": result.raw_path or "",
            "reasons": ",".join(result.diagnostic_codes),
        },
    )


def _counts(results: list[BindingResult]) -> BindingCounts:
    values = {status.value: 0 for status in BindingStatus}
    for item in results:
        values[item.status.value] += 1
    resolved_with_evidence = sum(
        1
        for item in results
        if item.status is BindingStatus.RESOLVED
        and item.source_id is not None
        and item.canonical_path is not None
        and item.evidence is not None
    )
    resolved_total = values[BindingStatus.RESOLVED.value]
    return BindingCounts(
        total=len(results),
        resolved=resolved_total,
        ambiguous=values[BindingStatus.AMBIGUOUS.value],
        unknown_path=values[BindingStatus.UNKNOWN_PATH.value],
        type_mismatch=values[BindingStatus.TYPE_MISMATCH.value],
        schema_unavailable=values[BindingStatus.SCHEMA_UNAVAILABLE.value],
        unsupported_expression=values[BindingStatus.UNSUPPORTED_EXPRESSION.value],
        by_status=dict(sorted(values.items())),
        resolved_with_evidence=resolved_with_evidence,
        resolved_without_evidence=resolved_total - resolved_with_evidence,
    )


def _schema_summary(document: D365DocumentSchema) -> SchemaSummary:
    schema = document.canonical
    namespaces = sorted({field.namespace for field in schema.fields if field.namespace})
    return SchemaSummary(
        project_data_parts=len(document.project_data_parts),
        sources=len(schema.sources),
        fields=len(schema.fields),
        collections=len(schema.collections),
        preview_data_sources=sum(1 for source in schema.sources if source.has_preview_data),
        namespaces=namespaces[:40],
        available=schema.is_available(),
    )


def build_binding_report(document: D365DocumentSchema) -> D365BindingReport:
    """Resolve every ProjectData binding against one extracted schema."""
    resolver = _Resolver(document)
    requests = _requests(document)
    pairs = [
        (request, _status_from_resolution(resolver.resolve(request), request))
        for request in requests
    ]
    pairs.sort(
        key=lambda pair: (
            pair[0].fact.part,
            int(pair[0].fact.element_id),
            pair[0].kind.value,
            pair[0].fact.xpath,
        )
    )
    results = [result for _, result in pairs]
    diagnostics: list[SchemaDiagnostic] = list(document.diagnostics)
    for request, result in pairs:
        diagnostic = _binding_diagnostic(result, request.fact)
        if diagnostic is not None:
            diagnostics.append(diagnostic)
    if not requests:
        diagnostics.append(
            SchemaDiagnostic(
                code="no_bindings_to_resolve",
                severity=DiagnosticSeverity.INFO,
                message=(
                    "No ProjectData binding facts were found; "
                    + (
                        "schema is unavailable"
                        if document.schema_source is SchemaSourceKind.UNAVAILABLE
                        else "schema is available"
                    )
                ),
            )
        )
    diagnostics = _deduplicate_diagnostics(diagnostics)
    diagnostics.sort(
        key=lambda item: (
            item.part or "",
            item.xpath or "",
            item.code,
            item.message,
        )
    )
    if len(diagnostics) > _MAX_DIAGNOSTICS:
        diagnostics = diagnostics[:_MAX_DIAGNOSTICS]
    return D365BindingReport(
        template_id=document.template_id,
        platform=_PLATFORM,
        schema_source=document.schema_source,
        schema_evidence=list(document.schema_evidence),
        binding_results=results,
        runtime_compatibility=RUNTIME_COMPATIBILITY,
        counts=_counts(results),
        schema_summary=_schema_summary(document),
        diagnostics=diagnostics,
        warnings=sorted(set(document.warnings))[:_MAX_WARNINGS],
    )


def _deduplicate_diagnostics(items: list[SchemaDiagnostic]) -> list[SchemaDiagnostic]:
    seen: set[tuple[str, str, str, str]] = set()
    result: list[SchemaDiagnostic] = []
    for item in items:
        key = (item.code, item.part or "", item.xpath or "", item.message)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def binding_report_json(report: D365BindingReport, *, indent: int = 2) -> str:
    """Deterministic JSON text used by the CLI, API tests and corpus report."""
    return (
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            indent=indent,
            sort_keys=True,
        )
        + "\n"
    )


def analyze_d365_bytes(
    data: bytes,
    *,
    filename: str = "document.docx",
    limits: ReferenceLimits | None = None,
    ddsp_data: bytes | None = None,
    ddsp_name: str = "source.ddsp",
) -> D365BindingReport:
    """Extract and resolve one uploaded D365 template payload."""
    document = extract_d365_schema(
        data,
        filename=filename,
        limits=limits,
        ddsp_data=ddsp_data,
        ddsp_name=ddsp_name,
    )
    return build_binding_report(document)


def analyze_d365_path(
    path: str | Path,
    *,
    limits: ReferenceLimits | None = None,
    ddsp_path: str | Path | None = None,
) -> D365BindingReport:
    """Extract and resolve one local D365 template (read-only)."""
    document = extract_d365_schema_path(path, limits=limits, ddsp_path=ddsp_path)
    return build_binding_report(document)


__all__ = [
    "REPORT_VERSION",
    "RUNTIME_COMPATIBILITY",
    "BindingCounts",
    "BindingKind",
    "BindingResult",
    "BindingStatus",
    "D365BindingReport",
    "SchemaSummary",
    "analyze_d365_bytes",
    "analyze_d365_path",
    "binding_report_json",
    "build_binding_report",
]
