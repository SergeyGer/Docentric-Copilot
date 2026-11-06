"""Deterministic repeat-alias conflict resolution (V012-05).

A provider can emit two sibling repeats with the same alias. The IR remains
schema-valid but the compiler and reader become ambiguous. Rather than silently
accepting or failing without an explanation, the planner renames the later
conflict deterministically (``line`` -> ``line_2``) and rewrites every path that
uses the shadowed alias inside that block. Each rename is returned as a typed
repair note.

Mutually exclusive conditional branches and independent table cells are separate
alias scopes (the validator's V3-002 uses the same rule), so a provider that
reuses an alias in two branches is not rewritten and does not fail.
"""

from __future__ import annotations

from typing import Any

from docentric_copilot.template_ir import (
    Block,
    Cell,
    Conditional,
    Document,
    Expression,
    FieldBinding,
    Heading,
    ImageBinding,
    Paragraph,
    Repeat,
    Table,
    TextRun,
)

_MAX_ALIAS = 32


def _rename(path: str | None, old: str, new: str) -> str | None:
    if not path:
        return path
    if path == old:
        return new
    if path.startswith(f"{old}."):
        return new + path[len(old) :]
    return path


def _rewrite_expression(expression: Expression, old: str, new: str) -> Expression:
    updates: dict[str, Any] = {}
    if expression.field is not None:
        rewritten = _rename(expression.field, old, new)
        if rewritten != expression.field:
            updates["field"] = rewritten
    if expression.operands:
        updates["operands"] = [
            _rewrite_expression(operand, old, new) for operand in expression.operands
        ]
    return expression.model_copy(update=updates) if updates else expression


def _rewrite_inline(run: TextRun | FieldBinding, old: str, new: str) -> TextRun | FieldBinding:
    if isinstance(run, FieldBinding):
        rewritten = _rename(run.path, old, new)
        if rewritten != run.path:
            return run.model_copy(update={"path": rewritten})
    return run


def _rewrite_blocks(blocks: list[Block], old: str, new: str, *, inside: bool) -> list[Block]:
    rewritten: list[Block] = []
    for block in blocks:
        if isinstance(block, Paragraph | Heading):
            runs = [_rewrite_inline(run, old, new) if inside else run for run in block.runs]
            rewritten.append(block.model_copy(update={"runs": runs}))
        elif isinstance(block, ImageBinding):
            path = _rename(block.path, old, new) if inside else block.path
            rewritten.append(block.model_copy(update={"path": path}))
        elif isinstance(block, Repeat):
            child_inside = inside or block.alias == old
            alias = new if block.alias == old else block.alias
            path = _rename(block.path, old, new) if inside else block.path
            rewritten.append(
                block.model_copy(
                    update={
                        "path": path,
                        "alias": alias,
                        "blocks": _rewrite_blocks(block.blocks, old, new, inside=child_inside),
                    }
                )
            )
        elif isinstance(block, Conditional):
            condition = (
                _rewrite_expression(block.condition, old, new) if inside else block.condition
            )
            rewritten.append(
                block.model_copy(
                    update={
                        "condition": condition,
                        "then_blocks": _rewrite_blocks(block.then_blocks, old, new, inside=inside),
                        "else_blocks": (
                            _rewrite_blocks(block.else_blocks, old, new, inside=inside)
                            if block.else_blocks
                            else None
                        ),
                    }
                )
            )
        elif isinstance(block, Table):
            repeat = block.repeat
            child_inside = inside
            if repeat is not None:
                child_inside = inside or repeat.alias == old
                repeat = repeat.model_copy(
                    update={
                        "alias": new if repeat.alias == old else repeat.alias,
                        "path": _rename(repeat.path, old, new) if inside else repeat.path,
                    }
                )
            rows = [
                row.model_copy(
                    update={
                        "cells": [
                            cell.model_copy(
                                update={
                                    "blocks": _rewrite_blocks(cell.blocks, old, new, inside=inside)
                                }
                            )
                            for cell in row.cells
                        ]
                    }
                )
                for row in block.rows
            ]
            row_template = [
                cell.model_copy(
                    update={"blocks": _rewrite_blocks(cell.blocks, old, new, inside=child_inside)}
                )
                for cell in block.row_template or []
            ]
            rewritten.append(
                block.model_copy(
                    update={
                        "repeat": repeat,
                        "rows": rows,
                        "row_template": row_template if block.row_template is not None else None,
                    }
                )
            )
        else:
            rewritten.append(block)
    return rewritten


def _unique_alias(alias: str, used: set[str], visible: set[str]) -> str:
    suffix = 2
    while True:
        tail = f"_{suffix}"
        candidate = (alias[: _MAX_ALIAS - len(tail)] + tail)[:_MAX_ALIAS]
        if candidate not in used and candidate not in visible:
            return candidate
        suffix += 1


def resolve_alias_conflicts(document: Document) -> tuple[Document, list[str]]:
    """Return a copy with duplicate sibling aliases renamed deterministically."""
    notes: list[str] = []
    aliases_seen: dict[tuple[tuple[tuple[str, str], ...], tuple[int, ...]], set[str]] = {}

    def visit(
        blocks: list[Block],
        scope: dict[str, str],
        branch: tuple[int, ...],
        prefix: str,
    ) -> list[Block]:
        result: list[Block] = []
        for index, block in enumerate(blocks):
            location = f"{prefix}[{index}]"
            if isinstance(block, Repeat):
                key = (tuple(sorted(scope.items())), branch)
                used = aliases_seen.setdefault(key, set())
                alias = block.alias
                if alias in used:
                    replacement = _unique_alias(alias, used, set(scope))
                    notes.append(
                        "alias_conflict_resolved: code=alias_conflict_resolved "
                        f"location={location} alias={alias!r} replacement={replacement!r}"
                    )
                    block = _rewrite_blocks([block], alias, replacement, inside=False)[0]
                    alias = replacement
                used.add(alias)
                child_scope = {**scope, alias: block.path}
                child_blocks = visit(block.blocks, child_scope, branch, f"{location}.blocks")
                result.append(block.model_copy(update={"blocks": child_blocks}))
            elif isinstance(block, Table):
                repeat = block.repeat
                key = (tuple(sorted(scope.items())), branch)
                used = aliases_seen.setdefault(key, set())
                child_scope = scope
                if repeat is not None:
                    alias = repeat.alias
                    if alias in used:
                        replacement = _unique_alias(alias, used, set(scope))
                        notes.append(
                            "alias_conflict_resolved: code=alias_conflict_resolved "
                            f"location={location} alias={alias!r} replacement={replacement!r}"
                        )
                        block = _rewrite_blocks([block], alias, replacement, inside=False)[0]
                        repeat = block.repeat
                        alias = replacement
                    used.add(alias)
                    child_scope = {**scope, alias: repeat.path}
                rows = [
                    row.model_copy(
                        update={
                            "cells": [
                                cell.model_copy(
                                    update={
                                        "blocks": visit(
                                            cell.blocks,
                                            scope,
                                            (*branch, index, row_index, cell_index),
                                            f"{location}.rows[{row_index}].cells[{cell_index}]",
                                        )
                                    }
                                )
                                for cell_index, cell in enumerate(row.cells)
                            ]
                        }
                    )
                    for row_index, row in enumerate(block.rows)
                ]
                row_template = [
                    Cell(
                        blocks=visit(
                            cell.blocks,
                            child_scope,
                            (*branch, index, -1, cell_index),
                            f"{location}.row_template[{cell_index}]",
                        )
                    )
                    for cell_index, cell in enumerate(block.row_template or [])
                ]
                result.append(
                    block.model_copy(
                        update={
                            "rows": rows,
                            "row_template": row_template
                            if block.row_template is not None
                            else None,
                        }
                    )
                )
            elif isinstance(block, Conditional):
                then_blocks = visit(
                    block.then_blocks,
                    scope,
                    (*branch, index, 1),
                    f"{location}.then",
                )
                else_blocks = (
                    visit(
                        block.else_blocks,
                        scope,
                        (*branch, index, 2),
                        f"{location}.else",
                    )
                    if block.else_blocks
                    else None
                )
                result.append(
                    block.model_copy(
                        update={
                            "then_blocks": then_blocks,
                            "else_blocks": else_blocks,
                        }
                    )
                )
            else:
                result.append(block)
        return result

    sections = []
    for section_index, section in enumerate(document.sections):
        body = visit(section.body, {}, (), f"section[{section_index}].body")
        header = (
            visit(section.header, {}, (), f"section[{section_index}].header")
            if section.header is not None
            else None
        )
        footer = (
            visit(section.footer, {}, (), f"section[{section_index}].footer")
            if section.footer is not None
            else None
        )
        sections.append(
            section.model_copy(
                update={
                    "body": body,
                    "header": header,
                    "footer": footer,
                }
            )
        )
    return document.model_copy(update={"sections": sections}), notes


__all__ = ["resolve_alias_conflicts"]
