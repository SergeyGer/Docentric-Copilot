"""Safe Reference -> Generic Template IR projection (v0.11 P1, issue #27).

This is deliberately **not** a Docentric AX writer. The importer copies only the
constructs whose binding is unambiguous and backed by schema evidence into the
existing Generic Template IR:

===========  ==========================================================
Reference     Generic IR
===========  ==========================================================
Field         ``FieldBinding`` inside a ``Paragraph``
Label         ``TextRun`` (static reference label text)
List          ``Repeat`` when the collection scope is confirmed
If            ``Conditional`` only for a boolean evidence-backed field
Image         ``ImageBinding`` only for a confirmed binary/image source
===========  ==========================================================

Everything else (barcode, group, sub-document, summary field, unknown kinds,
ambiguous/unknown/type-mismatched/schema-unavailable bindings) becomes an
explicit item in ``skipped[]``. Nothing is silently converted or dropped.

The importer never mutates the reference document, never evaluates a raw path,
and never sets a Docentric AX target or runtime claim. The produced Document is
validated with the existing deterministic validator against a synthetic schema
built only from the imported, evidence-backed paths; strict mode refuses the
whole import when any construct is skipped.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import Final, Literal

from docentric_copilot.ddsp_parser import NormalizedSchema, SchemaNode, SchemaSection
from docentric_copilot.errors import UnsupportedInputError, ValidationFailedError
from docentric_copilot.template_ir import (
    Block,
    Conditional,
    Document,
    DocumentMetadata,
    Expression,
    ExpressionOperator,
    FieldBinding,
    ImageBinding,
    Paragraph,
    Repeat,
    Section,
    TextRun,
    ValueFormat,
    iter_blocks,
)
from docentric_copilot.template_validator import ValidationEngine
from pydantic import BaseModel, ConfigDict, Field

from .docx_controls import ElementKind
from .graph import GraphStatus, NodeKind, ReferenceGraph
from .projection import ProjectionElement, ReferenceDocument, project_graph
from .table_inference import InferredTable, infer_tables

IMPORT_VERSION: Final[Literal["1.0"]] = "1.0"
RUNTIME_COMPATIBILITY: Final[Literal["not_tested"]] = "not_tested"
IMPORT_NOTE: Final = (
    "Safe reference-to-generic-IR import. Produces generic DOCX only; "
    "Docentric AX runtime compatibility is not tested."
)

_MAX_SKIPPED: Final = 5_000
_MAX_PROVENANCE: Final = 20_000
_MAX_PATH: Final = 500

_PATH_SPLIT = re.compile(r"[./\\]+")
_INVALID_SEGMENT = re.compile(r"[^A-Za-z0-9_]+")
_INVALID_SECTION = re.compile(r"[^A-Za-z0-9 _\-]+")
_INVALID_TEMPLATE = re.compile(r"[^A-Za-z0-9 _\-().]+")

_TEXT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "string",
        "text",
        "enum",
        "guid",
        "anyuri",
        "char",
        "normalizedstring",
        "token",
        "ncname",
        "name",
        "id",
        "idref",
    }
)
_NUMBER_TYPES: Final[frozenset[str]] = frozenset(
    {
        "number",
        "decimal",
        "integer",
        "int",
        "long",
        "short",
        "byte",
        "double",
        "float",
        "currency",
        "percent",
    }
)
_DATE_TYPES: Final[frozenset[str]] = frozenset(
    {"date", "datetime", "datetimeoffset", "time", "timespan", "temporal"}
)
_IMAGE_TYPES: Final[frozenset[str]] = frozenset({"image", "binary", "base64binary", "hexbinary"})
_BOOLEAN_TYPES: Final[frozenset[str]] = frozenset({"boolean", "bool"})
_IR_TYPES: Final[frozenset[str]] = frozenset(
    {"string", "number", "boolean", "date", "image", "any"}
)

_FORMAT_BY_FAMILY: Final[dict[str, ValueFormat]] = {
    "string": ValueFormat.PLAIN,
    "number": ValueFormat.NUMBER,
    "date": ValueFormat.DATE_SHORT,
    "boolean": ValueFormat.BOOLEAN_YES_NO,
}

_SUPPORTED_INLINE: Final[frozenset[ElementKind]] = frozenset(
    {ElementKind.FIELD, ElementKind.IMAGE, ElementKind.LABEL}
)
_SUPPORTED_CONTAINER: Final[frozenset[ElementKind]] = frozenset({ElementKind.LIST, ElementKind.IF})
_REFERENCE_ONLY_KINDS: Final[dict[ElementKind, str]] = {
    ElementKind.BARCODE: "Barcode is reference-only; it is never replaced by plain text.",
    ElementKind.GROUP: "Group semantics are not confirmed for generic IR; kept reference-only.",
    ElementKind.SUB_DOCUMENT: "Sub-document keeps its reference and diagnostics; it is not inlined.",
    ElementKind.SUMMARY_FIELD: (
        "SummaryField/complex expression is unsupported and preserved as reference data."
    ),
}

_BINDING_SKIP_CODES: Final[dict[str, str]] = {
    "ambiguous": "AMBIGUOUS_BINDING",
    "unknown_path": "UNKNOWN_PATH",
    "type_mismatch": "TYPE_MISMATCH",
    "schema_unavailable": "SCHEMA_UNAVAILABLE",
    "unsupported_expression": "UNSUPPORTED_EXPRESSION",
}


class ImportSkipCode(str, Enum):
    """Stable diagnostic codes listed in ``skipped[]``."""

    UNKNOWN_ELEMENT = "UNKNOWN_ELEMENT"
    UNSUPPORTED_ELEMENT_KIND = "UNSUPPORTED_ELEMENT_KIND"
    AMBIGUOUS_BINDING = "AMBIGUOUS_BINDING"
    UNKNOWN_PATH = "UNKNOWN_PATH"
    TYPE_MISMATCH = "TYPE_MISMATCH"
    SCHEMA_UNAVAILABLE = "SCHEMA_UNAVAILABLE"
    UNSUPPORTED_EXPRESSION = "UNSUPPORTED_EXPRESSION"
    UNRESOLVED_BINDING = "UNRESOLVED_BINDING"
    MISSING_SCHEMA_PATH = "MISSING_SCHEMA_PATH"
    UNSUPPORTED_CONDITION_TYPE = "UNSUPPORTED_CONDITION_TYPE"
    EMPTY_COLLECTION = "EMPTY_COLLECTION"
    LABEL_TEXT_UNAVAILABLE = "LABEL_TEXT_UNAVAILABLE"
    IMAGE_SOURCE_UNVERIFIED = "IMAGE_SOURCE_UNVERIFIED"
    TABLE_DIAGNOSTIC = "TABLE_DIAGNOSTIC"
    PARENT_SKIPPED = "PARENT_SKIPPED"
    EMPTY_DOCUMENT = "EMPTY_DOCUMENT"


class ReferenceImportBlockedError(UnsupportedInputError):
    """Strict import refused because at least one construct was skipped."""

    code = "reference_import_blocked"
    http_status = 422


class ReferenceImportInvalidError(ValidationFailedError):
    """The produced document did not pass the existing validator."""

    code = "reference_import_invalid"


class ReferenceImportEmptyError(UnsupportedInputError):
    """No construct in the reference could be safely imported."""

    code = "reference_import_empty"
    http_status = 422


class ImportSkipped(BaseModel):
    """One construct that was not imported, with a stable code and reason."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_reference_id: str = Field(min_length=1, max_length=600)
    kind: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=200)
    code: ImportSkipCode
    reason: str = Field(min_length=1, max_length=400)
    part: str | None = Field(default=None, max_length=240)
    ordinal: int | None = Field(default=None, ge=0)
    element_id: str | None = Field(default=None, max_length=20)
    binding_status: str | None = Field(default=None, max_length=40)
    schema_path: str | None = Field(default=None, max_length=512)


class ImportProvenance(BaseModel):
    """Where one produced IR node came from.

    Template IR v1.0 is frozen (adding fields would change every existing IR
    digest), so provenance is carried in this sidecar keyed by a stable IR path.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    ir_path: str = Field(min_length=1, max_length=600)
    node_kind: str = Field(min_length=1, max_length=40)
    source_reference_id: str = Field(min_length=1, max_length=600)
    document_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    element_id: str | None = Field(default=None, max_length=20)
    reference_kind: str = Field(min_length=1, max_length=40)
    part: str | None = Field(default=None, max_length=240)
    ordinal: int | None = Field(default=None, ge=0)
    reference_path: str | None = Field(default=None, max_length=512)
    schema_path: str | None = Field(default=None, max_length=512)
    schema_source: str | None = Field(default=None, max_length=40)
    source_id: str | None = Field(default=None, max_length=300)
    evidence_location: str | None = Field(default=None, max_length=2_000)
    binding_status: str | None = Field(default=None, max_length=40)


class ImportSummary(BaseModel):
    """Deterministic counts for one import."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    references: int = Field(ge=0)
    imported: int = Field(ge=0)
    skipped: int = Field(ge=0)
    by_kind: dict[str, int] = Field(default_factory=dict)
    by_skip_code: dict[str, int] = Field(default_factory=dict)
    fields: int = Field(ge=0)
    labels: int = Field(ge=0)
    lists: int = Field(ge=0)
    conditions: int = Field(ge=0)
    images: int = Field(ge=0)


class ReferenceIRImport(BaseModel):
    """The v0.11 safe import contract consumed by the CLI and the API."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    import_version: Literal["1.0"] = IMPORT_VERSION
    reference_version: Literal["1.0"] = "1.0"
    runtime_compatibility: Literal["not_tested"] = RUNTIME_COMPATIBILITY
    target: Literal["generic-docx"] = "generic-docx"
    note: str = Field(default=IMPORT_NOTE, max_length=300)
    source_name: str = Field(min_length=1, max_length=300)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    allow_unsupported: bool = False
    ir: Document
    skipped: list[ImportSkipped] = Field(default_factory=list, max_length=_MAX_SKIPPED)
    provenance: list[ImportProvenance] = Field(default_factory=list, max_length=_MAX_PROVENANCE)
    validation: dict[str, object] = Field(default_factory=dict)
    summary: ImportSummary

    @property
    def document(self) -> Document:
        """Alias for callers that expect the produced Document."""
        return self.ir

    def skipped_json(self) -> list[dict[str, object]]:
        return [item.model_dump(mode="json") for item in self.skipped]


# --------------------------------------------------------------------------- #
# Paths, types and identifiers
# --------------------------------------------------------------------------- #
def _type_family(value: str | None) -> str:
    """Map provider/XSD type spellings to the validator type families."""
    if not value:
        return "any"
    text = value.strip().casefold()
    if ":" in text:
        text = text.rsplit(":", 1)[-1]
    if text.startswith("system."):
        text = text.split(".", 1)[1]
    normalized = text.replace(" ", "")
    if normalized in _TEXT_TYPES:
        return "string"
    if normalized in _NUMBER_TYPES or normalized.startswith(("int", "uint")):
        return "number"
    if normalized in _DATE_TYPES or normalized.startswith(("date", "time")):
        return "date"
    if normalized in _IMAGE_TYPES:
        return "image"
    if normalized in _BOOLEAN_TYPES:
        return "boolean"
    if normalized in {"any", "anytype", "anysimpletype", "object"}:
        return "any"
    return "string"


def _format_for_family(family: str) -> ValueFormat | None:
    return _FORMAT_BY_FAMILY.get(family)


class _PathMapper:
    """Deterministic, collision-free mapping from provider paths to IR paths."""

    def __init__(self) -> None:
        self._segments: dict[str, str] = {}
        self._used: dict[str, str] = {}

    def _segment(self, raw: str, *, terminal_attribute: bool = False) -> str:
        cleaned = raw.strip()
        if terminal_attribute and cleaned.startswith("@"):
            cleaned = cleaned[1:]
        cleaned = _INVALID_SEGMENT.sub("_", cleaned).strip("_")
        if not cleaned:
            cleaned = "field"
        if not (cleaned[0].isalpha() or cleaned[0] == "_"):
            cleaned = f"_{cleaned}"
        key = cleaned.casefold()
        existing = self._segments.get(key)
        if existing is not None:
            return existing
        candidate = cleaned
        suffix = 2
        while candidate.casefold() in self._used:
            candidate = f"{cleaned}_{suffix}"
            suffix += 1
        self._segments[key] = candidate
        self._used[candidate.casefold()] = candidate
        return candidate

    def convert(self, reference_path: str | None) -> str | None:
        if not reference_path or not reference_path.strip():
            return None
        raw_segments = [item for item in _PATH_SPLIT.split(reference_path.strip()) if item]
        if not raw_segments:
            return None
        converted = [
            self._segment(raw, terminal_attribute=index == len(raw_segments) - 1)
            for index, raw in enumerate(raw_segments)
        ]
        path = ".".join(converted)
        return path if len(path) <= _MAX_PATH else None


def _identifier(value: str, *, limit: int, fallback: str) -> str:
    cleaned = " ".join(_INVALID_TEMPLATE.sub(" ", value).split())
    return (cleaned or fallback)[:limit]


def _section_name(value: str, *, index: int, used: set[str]) -> str:
    cleaned = " ".join(_INVALID_SECTION.sub(" ", value).split()) or "Reference"
    candidate = cleaned[:70]
    if candidate.casefold() in used:
        candidate = f"{candidate[:67]} {index + 1}"
    suffix = 2
    while candidate.casefold() in used:
        candidate = f"{cleaned[:64]} {suffix}"
        suffix += 1
    used.add(candidate.casefold())
    return candidate


def _alias(value: str, *, used: set[str]) -> str:
    last = value.rsplit(".", 1)[-1].casefold()
    cleaned = re.sub(r"[^a-z0-9_]", "", last) or "item"
    if not cleaned[0].isalpha():
        cleaned = f"item_{cleaned}"
    if len(cleaned) > 28:
        cleaned = cleaned[:28]
    candidate = cleaned
    suffix = 2
    while candidate in used:
        candidate = f"{cleaned[:26]}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


# --------------------------------------------------------------------------- #
# Synthetic validation schema
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class _SchemaEntry:
    path: str
    data_type: str
    collection: bool = False


@dataclass
class _SchemaTree:
    children: dict[str, _SchemaTree] = field(default_factory=dict)
    data_type: str = "any"
    collection: bool = False


def _schema_from_import(
    *,
    schema_id: str,
    entries: Iterable[_SchemaEntry],
) -> NormalizedSchema:
    """Build a minimal normalized schema containing exactly the imported paths.

    This is validation scaffolding, not a new schema claim: it contains only
    paths that the reference evidence confirmed and that the produced IR binds.
    It lets V1-V3 exercise path existence, scalar/collection rules, enclosing
    repeat context and format/type compatibility.
    """
    roots: dict[str, _SchemaTree] = {}
    for entry in entries:
        segments = entry.path.split(".")
        if not segments or any(not segment for segment in segments):
            continue
        root = roots.setdefault(segments[0], _SchemaTree())
        cursor = root
        for segment in segments[1:]:
            cursor = cursor.children.setdefault(segment, _SchemaTree())
        cursor.data_type = entry.data_type if entry.data_type in _IR_TYPES else "string"
        cursor.collection = entry.collection

    def build(name: str, full_path: str, tree: _SchemaTree) -> SchemaNode:
        children = [
            build(child_name, f"{full_path}.{child_name}", tree.children[child_name])
            for child_name in sorted(tree.children)
        ]
        return SchemaNode(
            name=name,
            path=full_path,
            data_type=tree.data_type if tree.data_type in _IR_TYPES else "any",
            collection=tree.collection,
            children=children,
        )

    nodes = [build(name, name, roots[name]) for name in sorted(roots)]
    sections = [
        SchemaSection(name=node.name, nodes=[node])
        for node in nodes
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]{0,79}$", node.name)
    ]
    return NormalizedSchema(schema_id=schema_id[:120] or "reference-import", sections=sections)


# --------------------------------------------------------------------------- #
# Projection
# --------------------------------------------------------------------------- #
@dataclass
class _Context:
    mapper: _PathMapper
    lookup: dict[str, list[ProjectionElement]]
    skipped: list[ImportSkipped] = field(default_factory=list)
    provenance: list[ImportProvenance] = field(default_factory=list)
    schema_entries: dict[str, _SchemaEntry] = field(default_factory=dict)
    imported: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)
    by_skip_code: dict[str, int] = field(default_factory=dict)
    _skipped_ids: set[str] = field(default_factory=set)
    _recorded: set[str] = field(default_factory=set)

    # ------------------------------------------------------------- helpers
    def children(self, element: ProjectionElement) -> list[ProjectionElement]:
        children: list[ProjectionElement] = []
        seen: set[str] = set()
        for child_id in element.child_element_ids:
            if child_id in seen:
                continue
            seen.add(child_id)
            for candidate in self.lookup.get(child_id, []):
                if candidate.id != element.id:
                    children.append(candidate)
        return sorted(children, key=_element_sort_key)

    def skip(self, element: ProjectionElement, code: ImportSkipCode, reason: str) -> None:
        if element.id in self._skipped_ids or len(self.skipped) >= _MAX_SKIPPED:
            return
        self._skipped_ids.add(element.id)
        self.skipped.append(
            ImportSkipped(
                source_reference_id=element.id,
                kind=element.kind.value,
                label=element.display_label[:200],
                code=code,
                reason=reason[:400],
                part=element.source_location.part,
                ordinal=element.source_location.ordinal,
                element_id=element.element_id,
                binding_status=element.binding_status,
                schema_path=element.schema_path,
            )
        )
        self.by_skip_code[code.value] = self.by_skip_code.get(code.value, 0) + 1

    def skip_subtree(
        self, element: ProjectionElement, reason: str, *, include_self: bool = False
    ) -> None:
        if include_self:
            self.skip(element, ImportSkipCode.PARENT_SKIPPED, reason)
        for child in self.children(element):
            self.skip(child, ImportSkipCode.PARENT_SKIPPED, f"Skipped because {reason}.")
            self.skip_subtree(child, reason)

    def record(
        self,
        element: ProjectionElement,
        *,
        ir_path: str,
        node_kind: str,
        reference_path: str | None,
        schema_path: str | None,
    ) -> None:
        marker = f"{element.id}|{ir_path}"
        if marker in self._recorded or len(self.provenance) >= _MAX_PROVENANCE:
            return
        self._recorded.add(marker)
        self.provenance.append(
            ImportProvenance(
                ir_path=ir_path,
                node_kind=node_kind,
                source_reference_id=element.id,
                document_sha256=_document_sha_from_id(element.id),
                element_id=element.element_id,
                reference_kind=element.kind.value,
                part=element.source_location.part,
                ordinal=element.source_location.ordinal,
                reference_path=reference_path,
                schema_path=schema_path,
                schema_source=element.schema_source,
                source_id=element.source_id,
                evidence_location=element.evidence_location,
                binding_status=element.binding_status,
            )
        )

    def count_imported(self, element: ProjectionElement, node_kind: str) -> None:
        self.imported += 1
        self.by_kind[element.kind.value] = self.by_kind.get(element.kind.value, 0) + 1


def _document_sha_from_id(identifier: str) -> str | None:
    match = re.match(r"control:([0-9a-f]{64}):", identifier)
    return match.group(1) if match else None


def _skip_reason_for_status(element: ProjectionElement) -> tuple[ImportSkipCode, str] | None:
    status = element.binding_status
    if status == "resolved" and element.status is GraphStatus.RESOLVED:
        return None
    if element.status is GraphStatus.AMBIGUOUS:
        return (
            ImportSkipCode.AMBIGUOUS_BINDING,
            "Binding is ambiguous; review is required before generic import.",
        )
    if status in _BINDING_SKIP_CODES:
        return (
            ImportSkipCode(_BINDING_SKIP_CODES[status]),
            f"Binding resolver status is {status}; it is not safe to import.",
        )
    return (
        ImportSkipCode.UNRESOLVED_BINDING,
        f"Binding status is {element.status.value}; review is required before import.",
    )


def _reference_path(element: ProjectionElement) -> str | None:
    return element.schema_path or element.binding_path


def _add_schema(context: _Context, path: str, data_type: str, *, collection: bool = False) -> None:
    context.schema_entries[path] = _SchemaEntry(
        path=path, data_type=data_type, collection=collection
    )


def _project_inline(
    element: ProjectionElement,
    *,
    ir_path: str,
    context: _Context,
) -> TextRun | FieldBinding | ImageBinding | None:
    # A Label is static reference text: it needs a resolved element, not a
    # schema data path. Anything unresolved still blocks strict import.
    if element.kind is ElementKind.LABEL and element.status is GraphStatus.RESOLVED:
        label = element.display_label.strip()
        if not label or label.startswith(("@", "/")):
            context.skip(
                element,
                ImportSkipCode.LABEL_TEXT_UNAVAILABLE,
                "No static label text was captured; the label data path is reference-only.",
            )
            context.skip_subtree(element, "the label text was unavailable")
            return None
        context.record(
            element,
            ir_path=ir_path,
            node_kind="text",
            reference_path=_reference_path(element),
            schema_path=element.schema_path,
        )
        context.count_imported(element, "text")
        return TextRun(text=label[:20_000])

    reason = _skip_reason_for_status(element)
    if reason is not None:
        context.skip(element, *reason)
        context.skip_subtree(element, "the enclosing construct was skipped")
        return None

    if element.kind not in {ElementKind.FIELD, ElementKind.IMAGE}:
        return None
    reference_path = _reference_path(element)
    ir_path_value = context.mapper.convert(reference_path)
    if ir_path_value is None:
        context.skip(
            element,
            ImportSkipCode.MISSING_SCHEMA_PATH,
            "The element has no schema path that survived normalization.",
        )
        context.skip_subtree(element, "the enclosing construct had no schema path")
        return None
    family = _type_family(element.data_type)
    if element.kind is ElementKind.FIELD:
        if element.collection:
            context.skip(
                element,
                ImportSkipCode.TYPE_MISMATCH,
                "Field control resolves to a collection; inspect the reference kind mismatch.",
            )
            context.skip_subtree(element, "the field resolved to a collection")
            return None
        _add_schema(context, ir_path_value, family)
        field_binding = FieldBinding(
            path=ir_path_value,
            label=element.display_label[:200],
            format=_format_for_family(family),
        )
        context.record(
            element,
            ir_path=ir_path,
            node_kind="field",
            reference_path=reference_path,
            schema_path=element.schema_path,
        )
        context.count_imported(element, "field")
        return field_binding
    # Image
    if family != "image":
        context.skip(
            element,
            ImportSkipCode.IMAGE_SOURCE_UNVERIFIED,
            (
                f"Image source type is '{element.data_type or 'unknown'}', not a "
                "confirmed binary/image field."
            ),
        )
        context.skip_subtree(element, "the image source was not verified")
        return None
    if element.collection:
        context.skip(
            element,
            ImportSkipCode.TYPE_MISMATCH,
            "Image control resolves to a collection; no image collection semantics are verified.",
        )
        context.skip_subtree(element, "the image resolved to a collection")
        return None
    _add_schema(context, ir_path_value, "image")
    image_binding = ImageBinding(path=ir_path_value, alt_text=element.display_label[:200])
    context.record(
        element,
        ir_path=ir_path,
        node_kind="image",
        reference_path=reference_path,
        schema_path=element.schema_path,
    )
    context.count_imported(element, "image")
    return image_binding


def _project_children(
    children: list[ProjectionElement],
    *,
    ir_prefix: str,
    context: _Context,
    alias_budget: set[str],
) -> list[Block]:
    blocks: list[Block] = []
    for child in children:
        block = _project_element(
            child,
            ir_path=f"{ir_prefix}[{len(blocks)}]",
            context=context,
            alias_budget=alias_budget,
        )
        if block is not None:
            blocks.append(block)
    return blocks


def _project_container(
    element: ProjectionElement,
    *,
    ir_path: str,
    context: _Context,
    alias_budget: set[str],
) -> Repeat | Conditional | None:
    reason = _skip_reason_for_status(element)
    if reason is not None:
        context.skip(element, *reason)
        context.skip_subtree(element, "the enclosing construct was skipped")
        return None
    reference_path = _reference_path(element)
    ir_path_value = context.mapper.convert(reference_path)
    if ir_path_value is None:
        context.skip(
            element,
            ImportSkipCode.MISSING_SCHEMA_PATH,
            "The construct has no schema path that survived normalization.",
        )
        context.skip_subtree(element, "the enclosing construct had no schema path")
        return None
    children = context.children(element)

    if element.kind is ElementKind.LIST:
        if not element.collection:
            context.skip(
                element,
                ImportSkipCode.EMPTY_COLLECTION,
                "The list binding is not a confirmed collection in the schema evidence.",
            )
            context.skip_subtree(element, "the collection scope was not confirmed")
            return None
        blocks = _project_children(
            children,
            ir_prefix=f"{ir_path}.blocks",
            context=context,
            alias_budget=alias_budget,
        )
        if not blocks:
            context.skip(
                element,
                ImportSkipCode.EMPTY_COLLECTION,
                "No supported child construct remained inside the collection.",
            )
            return None
        _add_schema(context, ir_path_value, "any", collection=True)
        repeat = Repeat(
            path=ir_path_value,
            alias=_alias(ir_path_value, used=alias_budget),
            blocks=blocks,
        )
        context.record(
            element,
            ir_path=ir_path,
            node_kind="repeat",
            reference_path=reference_path,
            schema_path=element.schema_path,
        )
        context.count_imported(element, "repeat")
        return repeat

    # Conditional
    family = _type_family(element.data_type)
    if family != "boolean":
        context.skip(
            element,
            ImportSkipCode.UNSUPPORTED_CONDITION_TYPE,
            f"Condition type is '{element.data_type or 'unknown'}', not boolean.",
        )
        context.skip_subtree(element, "the enclosing conditional was skipped")
        return None
    blocks = _project_children(
        children,
        ir_prefix=f"{ir_path}.then_blocks",
        context=context,
        alias_budget=alias_budget,
    )
    if not blocks:
        context.skip(
            element,
            ImportSkipCode.UNSUPPORTED_CONDITION_TYPE,
            "The conditional has no supported child construct.",
        )
        return None
    _add_schema(context, ir_path_value, "boolean")
    conditional = Conditional(
        condition=Expression(
            operator=ExpressionOperator.EQUALS,
            field=ir_path_value,
            value=True,
        ),
        then_blocks=blocks,
    )
    context.record(
        element,
        ir_path=ir_path,
        node_kind="conditional",
        reference_path=reference_path,
        schema_path=element.schema_path,
    )
    context.count_imported(element, "conditional")
    return conditional


def _project_element(
    element: ProjectionElement,
    *,
    ir_path: str,
    context: _Context,
    alias_budget: set[str],
) -> Block | None:
    if element.kind in _SUPPORTED_CONTAINER:
        return _project_container(
            element,
            ir_path=ir_path,
            context=context,
            alias_budget=alias_budget,
        )
    if element.kind in _SUPPORTED_INLINE:
        is_image = element.kind is ElementKind.IMAGE
        inline = _project_inline(
            element,
            ir_path=ir_path if is_image else f"{ir_path}.runs[0]",
            context=context,
        )
        if inline is None:
            return None
        # ImageBinding is a block in Template IR; FieldBinding/TextRun live in a
        # paragraph run.
        if isinstance(inline, ImageBinding):
            return inline
        return Paragraph(runs=[inline])
    message = _REFERENCE_ONLY_KINDS.get(element.kind)
    if message is not None:
        context.skip(element, ImportSkipCode.UNSUPPORTED_ELEMENT_KIND, message)
    elif element.kind is ElementKind.UNKNOWN:
        context.skip(
            element,
            ImportSkipCode.UNKNOWN_ELEMENT,
            "Element kind is unknown; no safe generic mapping exists.",
        )
    else:
        context.skip(
            element,
            ImportSkipCode.UNSUPPORTED_ELEMENT_KIND,
            f"Element kind '{element.kind.value}' is not in the v0.11 supported subset.",
        )
    context.skip_subtree(element, "the enclosing construct is reference-only")
    return None


def _element_sort_key(element: ProjectionElement) -> tuple[str, int, int, str]:
    return (
        element.source_location.part,
        element.source_location.paragraph_index,
        element.source_location.ordinal,
        element.id,
    )


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def _as_reference_document(
    reference_document_or_graph: ReferenceDocument | ReferenceGraph,
) -> ReferenceDocument:
    if isinstance(reference_document_or_graph, ReferenceGraph):
        return project_graph(reference_document_or_graph)
    if isinstance(reference_document_or_graph, ReferenceDocument):
        return reference_document_or_graph
    raise TypeError("project_to_template_ir expects a ReferenceDocument or a ReferenceGraph")


def _collection_paths(source: ReferenceDocument | ReferenceGraph) -> set[str]:
    if isinstance(source, ReferenceGraph):
        return {
            node.schema_path
            for node in source.nodes
            if node.kind is NodeKind.SCHEMA_FIELD and node.collection and node.schema_path
        }
    return {
        element.schema_path
        for section in source.sections
        for element in section.elements
        if element.collection and element.schema_path
    }


def _add_table_schema(context: _Context, inferred: InferredTable) -> None:
    table = inferred.table
    repeat = table.repeat
    if repeat is None:
        return
    context.schema_entries[repeat.path] = _SchemaEntry(
        repeat.path, data_type="any", collection=True
    )
    cells = list(table.row_template or [])
    for row in table.footer_rows:
        cells.extend(row.cells)
    for cell in cells:
        for block, _depth in iter_blocks(cell.blocks):
            for binding in _inline_bindings(block):
                path = binding.path
                if path.startswith(f"{repeat.alias}."):
                    full = f"{repeat.path}.{path[len(repeat.alias) + 1 :]}"
                else:
                    full = path
                data_type = "image" if isinstance(binding, ImageBinding) else "string"
                context.schema_entries[full] = _SchemaEntry(full, data_type=data_type)


def _inline_bindings(block: Block) -> Iterable[FieldBinding | ImageBinding]:
    if isinstance(block, Paragraph):
        return (run for run in block.runs if isinstance(run, FieldBinding | ImageBinding))
    if isinstance(block, ImageBinding):
        return (block,)
    return ()


def _record_table(
    context: _Context,
    inferred: InferredTable,
    *,
    index: int,
    source_sha256: str,
    source_name: str,
) -> None:
    table = inferred.table
    repeat = table.repeat
    context.imported += 1
    context.by_kind["table"] = context.by_kind.get("table", 0) + 1
    context.provenance.append(
        ImportProvenance(
            ir_path=f"sections[0].body[{index}]",
            node_kind="table",
            source_reference_id=f"table:{source_sha256[:12]}:{index}",
            document_sha256=source_sha256,
            reference_kind="table",
            schema_path=repeat.path if repeat is not None else None,
            binding_status="inferred",
        )
    )
    for offset, cell in enumerate(table.row_template or []):
        for block in cell.blocks:
            if isinstance(block, ImageBinding):
                context.provenance.append(
                    ImportProvenance(
                        ir_path=f"sections[0].body[{index}].row_template[{offset}]",
                        node_kind="image",
                        source_reference_id=f"table:{source_sha256[:12]}:{index}",
                        document_sha256=source_sha256,
                        reference_kind="table",
                        schema_path=repeat.path if repeat is not None else None,
                        binding_status="inferred",
                    )
                )
    if source_name:
        context.by_kind.setdefault("table_source", 0)


def _table_skips(
    context: _Context,
    result,
    *,
    source_sha256: str,
) -> None:
    for diagnostic in result.diagnostics:
        if len(context.skipped) >= _MAX_SKIPPED:
            break
        context.skipped.append(
            ImportSkipped(
                source_reference_id=(f"table:{source_sha256[:12]}:{diagnostic.table_ordinal or 0}"),
                kind="table",
                label=f"Table {diagnostic.table_ordinal or 0}",
                code=ImportSkipCode.TABLE_DIAGNOSTIC,
                reason=f"{diagnostic.code}: {diagnostic.message}"[:400],
                part=diagnostic.part,
                ordinal=diagnostic.table_ordinal,
            )
        )
        context.by_skip_code[ImportSkipCode.TABLE_DIAGNOSTIC.value] = (
            context.by_skip_code.get(ImportSkipCode.TABLE_DIAGNOSTIC.value, 0) + 1
        )


def project_to_template_ir(
    reference_document_or_graph: ReferenceDocument | ReferenceGraph,
    *,
    allow_unsupported: bool = False,
    docx_payload: bytes | None = None,
) -> ReferenceIRImport:
    """Project the fully resolved reference subset into Generic Template IR.

    Strict mode (default) raises :class:`ReferenceImportBlockedError` when any
    construct is skipped. ``allow_unsupported=True`` keeps the supported subset
    and returns every skip in ``skipped[]``; it never converts an unsupported
    construct into a guess. The produced Document is validated with the existing
    ``ValidationEngine`` and must pass V1-V3.
    """
    reference = _as_reference_document(reference_document_or_graph)
    all_elements = [element for section in reference.sections for element in section.elements]
    collection_paths = _collection_paths(reference_document_or_graph)
    table_result = (
        infer_tables(docx_payload, all_elements, collection_paths=collection_paths)
        if docx_payload
        else None
    )
    table_ordinals = table_result.ordinals if table_result is not None else set()
    lookup: dict[str, list[ProjectionElement]] = {}
    for element in all_elements:
        if element.element_id:
            lookup.setdefault(element.element_id, []).append(element)
    context = _Context(mapper=_PathMapper(), lookup=lookup)
    used_section_names: set[str] = set()
    sections: list[Section] = []

    for index, section in enumerate(reference.sections):
        section_elements = list(section.elements)
        context.lookup = {}
        for element in section_elements:
            if element.element_id:
                context.lookup.setdefault(element.element_id, []).append(element)
        local_children = {
            child_id for element in section_elements for child_id in element.child_element_ids
        }
        top_level = sorted(
            (
                element
                for element in section_elements
                if not element.element_id or element.element_id not in local_children
            ),
            key=_element_sort_key,
        )
        alias_budget: set[str] = set()
        blocks: list[Block] = []
        if not top_level:
            for element in sorted(section.elements, key=_element_sort_key):
                context.skip(
                    element,
                    ImportSkipCode.EMPTY_DOCUMENT,
                    "No top-level, supported construct was available in this document.",
                )
                context.skip_subtree(element, "the document had no top-level supported construct")
        for element in top_level:
            if (
                element.source_location.part,
                element.source_location.ordinal,
            ) in table_ordinals:
                continue
            block = _project_element(
                element,
                ir_path=f"sections[{index}].body[{len(blocks)}]",
                context=context,
                alias_budget=alias_budget,
            )
            if block is not None:
                blocks.append(block)
        if not blocks:
            continue
        sections.append(
            Section(
                name=_section_name(
                    section.name or f"Reference {index + 1}",
                    index=index,
                    used=used_section_names,
                ),
                body=blocks,
            )
        )

    if table_result is not None and table_result.tables:
        if not sections:
            sections.append(Section(name="Reference", body=[]))
        for inferred in table_result.tables:
            sections[0].body.append(inferred.table)
            _add_table_schema(context, inferred)
            _record_table(
                context,
                inferred,
                index=len(sections[0].body) - 1,
                source_sha256=reference.source_sha256,
                source_name=reference.source_name,
            )
    if table_result is not None and table_result.diagnostics:
        _table_skips(context, table_result, source_sha256=reference.source_sha256)

    if not sections:
        raise ReferenceImportEmptyError(
            (
                "Every reference construct was unsupported or unresolved; strict-safe import "
                "cannot produce a non-empty Generic Template IR."
            ),
            details={
                "skipped": [item.model_dump(mode="json") for item in context.skipped[:100]],
                "skipped_total": len(context.skipped),
            },
        )

    if context.skipped and not allow_unsupported:
        raise ReferenceImportBlockedError(
            (
                f"Strict import refused: {len(context.skipped)} reference construct(s) are "
                "unsupported, ambiguous or unresolved. Nothing was dropped silently; review "
                "skipped[] or pass allow_unsupported=True."
            ),
            details={
                "skipped": [item.model_dump(mode="json") for item in context.skipped[:100]],
                "skipped_total": len(context.skipped),
                "allow_unsupported": False,
            },
        )

    title = (reference.source_name or "Reference template").replace("\\", "/")
    title = title.rsplit("/", 1)[-1][:200].strip() or "Reference template"
    template_name = _identifier(title.rsplit(".", 1)[0], limit=120, fallback="Reference import")
    schema_id = (
        reference.schema_ids[0]
        if reference.schema_ids
        else f"reference-{reference.source_sha256[:12]}"
    )
    imported_document = Document(
        title=title,
        language="en",
        metadata=DocumentMetadata(
            template_name=template_name,
            source_schema_id=schema_id[:120],
            design_style=None,
            intent="Imported from a read-only reference template (v0.11 P1).",
            generator="reference-import/1.0",
            notes="Generic DOCX only. Docentric AX runtime compatibility is not tested.",
        ),
        sections=sections,
    )
    schema = _schema_from_import(
        schema_id=schema_id,
        entries=context.schema_entries.values(),
    )
    report = ValidationEngine().validate(imported_document, schema)
    if not report.can_compile:
        raise ReferenceImportInvalidError(
            (
                "The projected Generic Template IR did not pass structural, semantic and "
                "logical validation."
            ),
            details={
                "validation": report.statuses(),
                "findings": [
                    {
                        "code": finding.code,
                        "message": finding.message,
                        "location": finding.location,
                    }
                    for finding in report.errors()[:20]
                ],
                "skipped": [item.model_dump(mode="json") for item in context.skipped[:100]],
            },
        )
    summary = ImportSummary(
        references=len(all_elements),
        imported=context.imported,
        skipped=len(context.skipped),
        by_kind=dict(sorted(context.by_kind.items())),
        by_skip_code=dict(sorted(context.by_skip_code.items())),
        fields=sum(1 for item in context.provenance if item.node_kind == "field"),
        labels=sum(1 for item in context.provenance if item.node_kind == "text"),
        lists=sum(1 for item in context.provenance if item.node_kind == "repeat"),
        conditions=sum(1 for item in context.provenance if item.node_kind == "conditional"),
        images=sum(1 for item in context.provenance if item.node_kind == "image"),
    )
    return ReferenceIRImport(
        source_name=reference.source_name,
        source_sha256=reference.source_sha256,
        allow_unsupported=allow_unsupported,
        ir=imported_document,
        skipped=context.skipped[:_MAX_SKIPPED],
        provenance=context.provenance[:_MAX_PROVENANCE],
        validation={
            "statuses": report.statuses(),
            "overall": report.overall,
            "can_compile": report.can_compile,
            "target": imported_document.target.value,
        },
        summary=summary,
    )


def import_ir_json(result: ReferenceIRImport, *, indent: int = 2) -> str:
    """Deterministic JSON text used by the CLI and tests."""
    return (
        json.dumps(
            result.model_dump(mode="json"),
            ensure_ascii=False,
            indent=indent,
            sort_keys=True,
        )
        + "\n"
    )


def import_summary_lines(result: ReferenceIRImport) -> list[str]:
    """Human-readable CLI summary, always ending with the runtime disclaimer."""
    validation = result.validation
    skipped_counts = ", ".join(
        f"{key} {value}" for key, value in result.summary.by_skip_code.items()
    )
    return [
        f"Generic IR import: {result.source_name}",
        (
            f"Imported: {result.summary.imported}/{result.summary.references} reference "
            f"construct(s) ({result.summary.fields} field, {result.summary.labels} label, "
            f"{result.summary.lists} list, {result.summary.conditions} conditional, "
            f"{result.summary.images} image)"
        ),
        f"Skipped: {result.summary.skipped} ({skipped_counts or 'none'})",
        f"Validation: {validation.get('statuses', {})}",
        f"Target: {result.target} (generic DOCX; no Docentric AX claim)",
        f"Runtime compatibility: {result.runtime_compatibility}",
    ]


__all__ = [
    "IMPORT_NOTE",
    "IMPORT_VERSION",
    "ImportProvenance",
    "ImportSkipCode",
    "ImportSkipped",
    "ImportSummary",
    "ReferenceIRImport",
    "ReferenceImportBlockedError",
    "ReferenceImportEmptyError",
    "ReferenceImportInvalidError",
    "import_ir_json",
    "import_summary_lines",
    "project_to_template_ir",
]
