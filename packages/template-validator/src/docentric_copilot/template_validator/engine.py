"""Validation engine: V1 structural, V2 semantic, V3 logical, V4 visual, V5 gate.

V1-V3 are fully autonomous and deterministic. V4 depends on the renderer and on
sample data, so it degrades to ``skipped`` rather than pretending to pass. V5 can
only be executed inside a licensed Docentric AX environment, therefore it is
always ``not_tested`` in this build.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from docentric_copilot.ddsp_parser.models import NormalizedSchema
from docentric_copilot.schema_resolver.paths import (
    PathResolutionError,
    Scope,
    absolute_path,
    resolve_collection,
    resolve_value,
)
from docentric_copilot.template_ir import (
    Block,
    Conditional,
    Document,
    Expression,
    ExpressionOperator,
    FieldBinding,
    Heading,
    ImageBinding,
    ImageSource,
    Paragraph,
    Repeat,
    Table,
    ValueFormat,
    ir_digest,
    iter_expressions,
)

from .models import CheckResult, CheckStatus, Finding, Level, Severity, ValidationReport

_MAX_REPEAT_DEPTH = 3
_PAGE_WIDTH_MM = {"A4": 210.0, "LETTER": 215.9}
_NUMERIC_FORMATS = {ValueFormat.NUMBER, ValueFormat.CURRENCY, ValueFormat.PERCENT}
_DATE_FORMATS = {ValueFormat.DATE_ISO, ValueFormat.DATE_SHORT, ValueFormat.DATE_LONG}
_COMPARISON_OPERATORS = {
    ExpressionOperator.EQUALS,
    ExpressionOperator.NOT_EQUALS,
    ExpressionOperator.GREATER_THAN,
    ExpressionOperator.GREATER_OR_EQUAL,
    ExpressionOperator.LESS_THAN,
    ExpressionOperator.LESS_OR_EQUAL,
}


def _alias_scope(node: _Node) -> tuple[tuple[tuple[str, str], ...], tuple[int, ...]]:
    """Identity of one alias scope and one mutually exclusive branch."""
    return (tuple(sorted(node.scope.aliases.items())), node.branch)


@dataclass(frozen=True, slots=True)
class _Node:
    block: Block
    scope: Scope
    branch: tuple[int, ...] = ()


def _walk(document: Document, schema: NormalizedSchema) -> list[_Node]:
    """Flatten the IR with the alias scope valid at each block.

    ``branch`` identifies mutually exclusive containers (conditional branches
    and independent table cells). A repeat alias must be unique within one
    lexical scope, but the same alias may appear in two branches that can never
    be active at the same time; V3-002 uses this identity.
    """
    nodes: list[_Node] = []

    def visit(blocks: list[Block], scope: Scope, depth: int, branch: tuple[int, ...]) -> None:
        for block in blocks:
            nodes.append(_Node(block=block, scope=scope, branch=branch))
            if isinstance(block, Repeat):
                try:
                    collection = resolve_collection(schema, block.path, scope)
                    child_scope = scope.push(block.alias, collection.absolute)
                except PathResolutionError:
                    child_scope = scope
                visit(block.blocks, child_scope, depth + 1, branch)
            elif isinstance(block, Conditional):
                visit(block.then_blocks, scope, depth, (*branch, id(block), 1))
                visit(block.else_blocks or [], scope, depth, (*branch, id(block), 2))
            elif isinstance(block, Table):
                row_scope = scope
                if block.repeat is not None:
                    try:
                        collection = resolve_collection(schema, block.repeat.path, scope)
                        row_scope = scope.push(block.repeat.alias, collection.absolute)
                    except PathResolutionError:
                        row_scope = scope
                for row_index, row in enumerate([*block.rows, *block.footer_rows]):
                    for cell_index, cell in enumerate(row.cells):
                        visit(
                            cell.blocks,
                            scope,
                            depth,
                            (*branch, id(block), row_index, cell_index),
                        )
                for cell_index, cell in enumerate(block.row_template or []):
                    visit(
                        cell.blocks,
                        row_scope,
                        depth,
                        (*branch, id(block), -1, cell_index),
                    )

    for section in document.sections:
        visit(section.body, Scope(), 0, ())
        visit(section.header or [], Scope(), 0, ())
        visit(section.first_page_header or [], Scope(), 0, ())
        visit(section.footer or [], Scope(), 0, ())
    return nodes


def _make(
    check_id: str,
    level: Level,
    name: str,
    findings: list[Finding],
    *,
    summary: str = "",
    skipped: bool = False,
    not_tested: bool = False,
) -> CheckResult:
    errors = [finding for finding in findings if finding.severity is Severity.ERROR]
    warnings = [finding for finding in findings if finding.severity is Severity.WARNING]
    if not_tested:
        status = CheckStatus.NOT_TESTED
    elif skipped:
        status = CheckStatus.SKIPPED
    elif errors:
        status = CheckStatus.FAILED
    elif warnings:
        status = CheckStatus.WARNING
    else:
        status = CheckStatus.PASSED
    effective_summary = summary or (
        f"{len(errors)} error(s), {len(warnings)} warning(s)" if findings else "no findings"
    )
    return CheckResult(
        id=check_id,
        level=level,
        name=name,
        status=status,
        summary=effective_summary,
        findings=findings,
    )


class ValidationEngine:
    """Run every validation level against a document."""

    def __init__(
        self, max_blocks: int = 5_000, max_depth: int = 24, max_text_length: int = 20_000
    ) -> None:
        self._max_blocks = max_blocks
        self._max_depth = max_depth
        self._max_text_length = max_text_length

    # ------------------------------------------------------------------ public
    def validate(
        self,
        document: Document,
        schema: NormalizedSchema,
        *,
        sample_data: dict[str, Any] | None = None,
        package: bytes | None = None,
        target: str | None = None,
    ) -> ValidationReport:
        nodes = _walk(document, schema)
        checks: list[CheckResult] = []
        checks.extend(self._structural(document, nodes, package))
        checks.extend(self._semantic(nodes, schema))
        checks.extend(self._logical(nodes, schema))
        checks.extend(self._visual(document, nodes, sample_data))
        checks.append(self._compatibility(target or document.target.value))
        report = ValidationReport(
            schema_id=schema.schema_id,
            target=target or document.target.value,
            ir_digest=ir_digest(document),
            checks=checks,
        )
        if package is not None:
            from docentric_copilot.docx_compiler.package import inspect_package

            report = report.model_copy(update={"package": inspect_package(package).as_dict()})
        return report

    # --------------------------------------------------------------------- V1
    def _structural(
        self, document: Document, nodes: list[_Node], package: bytes | None
    ) -> list[CheckResult]:
        findings: list[Finding] = []
        if len(nodes) > self._max_blocks:
            findings.append(
                Finding(
                    code="V1-001",
                    severity=Severity.ERROR,
                    message=f"IR contains {len(nodes)} blocks, limit is {self._max_blocks}",
                )
            )
        depth = self._depth(document)
        if depth > self._max_depth:
            findings.append(
                Finding(
                    code="V1-002",
                    severity=Severity.ERROR,
                    message=f"IR nesting depth {depth} exceeds the limit of {self._max_depth}",
                )
            )
        names = [section.name for section in document.sections]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        for name in duplicates:
            findings.append(
                Finding(
                    code="V1-003",
                    severity=Severity.ERROR,
                    message=f"Duplicate section name '{name}'",
                    location=name,
                )
            )
        for section in document.sections:
            if not section.body:
                findings.append(
                    Finding(
                        code="V1-004",
                        severity=Severity.ERROR,
                        message=f"Section '{section.name}' has an empty body",
                        location=section.name,
                    )
                )
        for node in nodes:
            block = node.block
            if isinstance(block, Paragraph | Heading):
                for run in block.runs:
                    text = getattr(run, "text", None)
                    if isinstance(text, str) and len(text) > self._max_text_length:
                        findings.append(
                            Finding(
                                code="V1-005",
                                severity=Severity.ERROR,
                                message=(
                                    f"Text run of {len(text)} characters exceeds the limit of "
                                    f"{self._max_text_length}"
                                ),
                            )
                        )
        checks = [
            _make(
                "V1-001",
                Level.STRUCTURAL,
                "IR size limits",
                [finding for finding in findings if finding.code == "V1-001"],
            ),
            _make(
                "V1-002",
                Level.STRUCTURAL,
                "IR nesting depth",
                [finding for finding in findings if finding.code == "V1-002"],
            ),
            _make(
                "V1-003",
                Level.STRUCTURAL,
                "Section uniqueness",
                [finding for finding in findings if finding.code == "V1-003"],
            ),
            _make(
                "V1-004",
                Level.STRUCTURAL,
                "Section content",
                [finding for finding in findings if finding.code == "V1-004"],
            ),
            _make(
                "V1-005",
                Level.STRUCTURAL,
                "Text length",
                [finding for finding in findings if finding.code == "V1-005"],
            ),
        ]
        if package is None:
            checks.append(
                _make(
                    "V1-006",
                    Level.STRUCTURAL,
                    "OOXML package structure",
                    [],
                    summary="no compiled package supplied",
                    skipped=True,
                )
            )
        else:
            checks.append(self._package_check(package))
        return checks

    @staticmethod
    def _depth(document: Document) -> int:
        def depth(blocks: list[Block]) -> int:
            maximum = 0
            for block in blocks:
                if isinstance(block, Repeat):
                    maximum = max(maximum, 1 + depth(block.blocks))
                elif isinstance(block, Conditional):
                    maximum = max(maximum, 1 + depth(block.then_blocks))
                    maximum = max(maximum, 1 + depth(block.else_blocks or []))
                elif isinstance(block, Table):
                    for row in [*block.rows, *block.footer_rows]:
                        for cell in row.cells:
                            maximum = max(maximum, 1 + depth(cell.blocks))
                    for cell in block.row_template or []:
                        maximum = max(maximum, 1 + depth(cell.blocks))
            return maximum

        return max((depth(section.body) for section in document.sections), default=0)

    def _package_check(self, package: bytes) -> CheckResult:
        from docentric_copilot.docx_compiler.package import inspect_package

        info = inspect_package(package)
        findings: list[Finding] = []
        if info.missing_entries:
            findings.append(
                Finding(
                    code="V1-006",
                    severity=Severity.ERROR,
                    message=f"Package is missing required entries: {', '.join(info.missing_entries)}",
                )
            )
        if info.has_macros:
            findings.append(
                Finding(
                    code="V1-007",
                    severity=Severity.ERROR,
                    message="Package contains a VBA macro payload",
                )
            )
        if info.has_embedded_objects:
            findings.append(
                Finding(
                    code="V1-008",
                    severity=Severity.ERROR,
                    message="Package contains embedded OLE/ActiveX objects",
                )
            )
        if info.external_relationships:
            findings.append(
                Finding(
                    code="V1-009",
                    severity=Severity.WARNING,
                    message=(
                        "Package contains external relationships: "
                        f"{', '.join(info.external_relationships[:5])}"
                    ),
                )
            )
        return _make("V1-006", Level.STRUCTURAL, "OOXML package structure", findings)

    # --------------------------------------------------------------------- V2
    def _semantic(self, nodes: list[_Node], schema: NormalizedSchema) -> list[CheckResult]:
        findings: list[Finding] = []
        for node in nodes:
            block = node.block
            bindings: list[FieldBinding | ImageBinding] = []
            if isinstance(block, Paragraph | Heading):
                bindings = [run for run in block.runs if isinstance(run, FieldBinding)]
            elif isinstance(block, ImageBinding) and block.source is ImageSource.SCHEMA:
                bindings = [block]
            for binding in bindings:
                if isinstance(binding, ImageBinding) and node.scope.aliases:
                    absolute, _alias = absolute_path(binding.path, node.scope)
                    if not any(
                        absolute == collection or absolute.startswith(f"{collection}.")
                        for collection in node.scope.aliases.values()
                    ):
                        findings.append(
                            Finding(
                                code="V2-003",
                                severity=Severity.ERROR,
                                message=(
                                    f"Image binding '{binding.path}' is outside the active "
                                    "collection scope"
                                ),
                                location=binding.path,
                            )
                        )
                        continue
                try:
                    resolved = resolve_value(schema, binding.path, node.scope)
                except PathResolutionError as exc:
                    code = {
                        "path_not_found": "V2-001",
                        "type_mismatch": "V2-002",
                        "context_violation": "V2-003",
                    }.get(exc.code, "V2-001")
                    findings.append(
                        Finding(
                            code=code,
                            severity=Severity.ERROR,
                            message=exc.message,
                            location=binding.path,
                        )
                    )
                    continue
                findings.extend(self._binding_format_findings(binding, resolved.node.data_type))

        errors = [finding for finding in findings if finding.severity is Severity.ERROR]
        return [
            _make(
                "V2-001",
                Level.SEMANTIC,
                "Binding paths exist",
                [f for f in errors if f.code == "V2-001"],
            ),
            _make(
                "V2-002",
                Level.SEMANTIC,
                "Binding types are scalar",
                [f for f in errors if f.code == "V2-002"],
            ),
            _make(
                "V2-003",
                Level.SEMANTIC,
                "Collection context is explicit",
                [f for f in errors if f.code == "V2-003"],
            ),
            _make(
                "V2-004",
                Level.SEMANTIC,
                "Format matches data type",
                [f for f in errors if f.code == "V2-004"],
            ),
        ]

    def _binding_format_findings(
        self, binding: FieldBinding | ImageBinding, data_type: str
    ) -> list[Finding]:
        findings: list[Finding] = []
        if isinstance(binding, ImageBinding):
            if data_type not in {"image", "any"}:
                findings.append(
                    Finding(
                        code="V2-002",
                        severity=Severity.ERROR,
                        message=f"Image binding '{binding.path}' points to a '{data_type}' field",
                        location=binding.path,
                    )
                )
            return findings
        if binding.format in _NUMERIC_FORMATS and data_type not in {"number", "any"}:
            findings.append(
                Finding(
                    code="V2-004",
                    severity=Severity.ERROR,
                    message=(
                        f"'{binding.path}' is '{data_type}' but format "
                        f"'{binding.format.value}' requires a number"
                    ),
                    location=binding.path,
                )
            )
        if binding.format in _DATE_FORMATS and data_type not in {"date", "string", "any"}:
            findings.append(
                Finding(
                    code="V2-004",
                    severity=Severity.ERROR,
                    message=(
                        f"'{binding.path}' is '{data_type}' but format "
                        f"'{binding.format.value}' requires a date"
                    ),
                    location=binding.path,
                )
            )
        if binding.format is ValueFormat.BOOLEAN_YES_NO and data_type not in {"boolean", "any"}:
            findings.append(
                Finding(
                    code="V2-004",
                    severity=Severity.ERROR,
                    message=f"'{binding.path}' is '{data_type}' but requires a boolean",
                    location=binding.path,
                )
            )
        return findings

    # --------------------------------------------------------------------- V3
    def _logical(self, nodes: list[_Node], schema: NormalizedSchema) -> list[CheckResult]:
        findings: list[Finding] = []
        aliases_seen: dict[tuple[tuple[tuple[str, str], ...], tuple[int, ...]], set[str]] = {}
        for node in nodes:
            block = node.block
            if isinstance(block, Repeat):
                try:
                    resolve_collection(schema, block.path, node.scope)
                except PathResolutionError as exc:
                    findings.append(
                        Finding(
                            code="V3-001",
                            severity=Severity.ERROR,
                            message=exc.message,
                            location=block.path,
                        )
                    )
                used = aliases_seen.setdefault(_alias_scope(node), set())
                if block.alias in used:
                    findings.append(
                        Finding(
                            code="V3-002",
                            severity=Severity.ERROR,
                            message=f"Duplicate repeat alias '{block.alias}' in the same scope",
                            location=block.path,
                        )
                    )
                used.add(block.alias)
            elif isinstance(block, Table) and block.repeat is not None:
                try:
                    resolve_collection(schema, block.repeat.path, node.scope)
                except PathResolutionError as exc:
                    findings.append(
                        Finding(
                            code="V3-001",
                            severity=Severity.ERROR,
                            message=exc.message,
                            location=block.repeat.path,
                        )
                    )
                used = aliases_seen.setdefault(_alias_scope(node), set())
                if block.repeat.alias in used:
                    findings.append(
                        Finding(
                            code="V3-002",
                            severity=Severity.ERROR,
                            message=(
                                f"Duplicate table repeat alias '{block.repeat.alias}' "
                                "in the same scope"
                            ),
                            location=block.repeat.path,
                        )
                    )
                used.add(block.repeat.alias)
            elif isinstance(block, Conditional):
                findings.extend(self._condition_findings(block.condition, schema, node.scope))
        return [
            _make(
                "V3-001",
                Level.LOGICAL,
                "Repeat targets a collection",
                [f for f in findings if f.code == "V3-001"],
            ),
            _make(
                "V3-002",
                Level.LOGICAL,
                "Repeat aliases are unique",
                [f for f in findings if f.code == "V3-002"],
            ),
            _make(
                "V3-003",
                Level.LOGICAL,
                "Condition operands are type correct",
                [f for f in findings if f.code == "V3-003"],
            ),
            _make(
                "V3-004",
                Level.LOGICAL,
                "Condition fields exist",
                [f for f in findings if f.code == "V3-004"],
            ),
        ]

    def _condition_findings(
        self, expression: Expression, schema: NormalizedSchema, scope: Scope
    ) -> list[Finding]:
        findings: list[Finding] = []
        for node in iter_expressions(expression):
            if node.field is None:
                continue
            try:
                resolved = resolve_value(schema, node.field, scope)
            except PathResolutionError as exc:
                findings.append(
                    Finding(
                        code="V3-004",
                        severity=Severity.ERROR,
                        message=exc.message,
                        location=node.field,
                    )
                )
                continue
            data_type = resolved.node.data_type
            if (
                node.operator in _COMPARISON_OPERATORS
                or node.operator is ExpressionOperator.CONTAINS
            ):
                if isinstance(node.value, bool) and data_type not in {"boolean", "any"}:
                    findings.append(
                        Finding(
                            code="V3-003",
                            severity=Severity.ERROR,
                            message=(
                                f"Condition compares '{node.field}' ({data_type}) with a boolean value"
                            ),
                            location=node.field,
                        )
                    )
                if node.operator in {
                    ExpressionOperator.GREATER_THAN,
                    ExpressionOperator.GREATER_OR_EQUAL,
                    ExpressionOperator.LESS_THAN,
                    ExpressionOperator.LESS_OR_EQUAL,
                } and data_type not in {"number", "date", "string", "any"}:
                    findings.append(
                        Finding(
                            code="V3-003",
                            severity=Severity.ERROR,
                            message=f"Ordering comparison on a '{data_type}' field",
                            location=node.field,
                        )
                    )
                if node.operator is ExpressionOperator.CONTAINS and data_type not in {
                    "string",
                    "any",
                }:
                    findings.append(
                        Finding(
                            code="V3-003",
                            severity=Severity.ERROR,
                            message=f"'contains' requires a string field, got '{data_type}'",
                            location=node.field,
                        )
                    )
        return findings

    # --------------------------------------------------------------------- V4
    def _visual(
        self, document: Document, nodes: list[_Node], sample_data: dict[str, Any] | None
    ) -> list[CheckResult]:
        if sample_data is None:
            return [
                _make(
                    "V4-001",
                    Level.VISUAL,
                    "Layout fits the page",
                    [],
                    summary="visual checks require sample data and a renderer",
                    skipped=True,
                )
            ]
        findings: list[Finding] = []
        available = _PAGE_WIDTH_MM[document.page.size] - (
            document.page.margin_left_mm + document.page.margin_right_mm
        )
        for node in nodes:
            if not isinstance(node.block, Table):
                continue
            widths = [column.width_mm for column in node.block.columns]
            if any(width is None for width in widths):
                continue
            total = sum(width for width in widths if width is not None)
            if total > available + 1.0:
                findings.append(
                    Finding(
                        code="V4-001",
                        severity=Severity.WARNING,
                        message=(
                            f"Table columns sum to {total:.0f} mm but only {available:.0f} mm are available"
                        ),
                    )
                )
        return [_make("V4-001", Level.VISUAL, "Layout fits the page", findings)]

    # --------------------------------------------------------------------- V5
    def _compatibility(self, target: str) -> CheckResult:
        message = (
            "Docentric AX compatibility requires execution inside a licensed Docentric "
            "environment; this build cannot verify it."
        )
        return _make(
            "V5-001",
            Level.COMPATIBILITY,
            "Docentric AX compatibility",
            [
                Finding(
                    code="V5-001",
                    severity=Severity.INFO,
                    message=message,
                )
            ],
            summary=message,
            not_tested=True,
        )


__all__ = ["ValidationEngine"]
