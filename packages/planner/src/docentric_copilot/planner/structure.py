"""Deterministic structural assertions for a generated plan (V012-05).

Schema validation is necessary but not sufficient for a business requirement
such as "create a table with nested task rows". This module checks the shape the
request explicitly asked for and returns typed findings instead of silently
accepting a nested list:

* a requirement that asks for a table must have an outer, repeating table;
* a repeat may not wrap a table over the same collection (the "nested list
  instead of table" failure seen with Gemini compact v2);
* a repeating table must carry cell blocks for its rows.

The planner feeds these findings into its repair loop. If the provider cannot
produce the requested hierarchy, the run fails before compile/export with a
``PlanInvalidError`` carrying the location and code.
"""

from __future__ import annotations

import re
from typing import Final

from docentric_copilot.template_ir import Block, Conditional, Document, Repeat, Table

TABLE_WORDS: Final = re.compile(
    r"\b(table|tabelle|tableau|grid)\b",
    re.IGNORECASE,
)
TABLE_OF_CONTENTS: Final = re.compile(r"table\s+of\s+contents", re.IGNORECASE)


def requirement_expects_table(requirement: str) -> bool:
    """Conservative detection of an explicit table request in EN/DE/FR."""
    text = requirement.strip()
    if not text or TABLE_OF_CONTENTS.search(text):
        return False
    return bool(TABLE_WORDS.search(text))


def _finding(code: str, location: str, message: str, *, severity: str = "error") -> dict[str, str]:
    return {
        "code": code,
        "severity": severity,
        "location": location,
        "message": message,
    }


def _tables_in(blocks: list[Block]) -> list[Table]:
    tables: list[Table] = []

    def walk(items: list[Block]) -> None:
        for block in items:
            if isinstance(block, Table):
                tables.append(block)
                for row in block.rows:
                    for cell in row.cells:
                        walk(cell.blocks)
                for cell in block.row_template or []:
                    walk(cell.blocks)
            elif isinstance(block, Repeat):
                walk(block.blocks)
            elif isinstance(block, Conditional):
                walk(block.then_blocks)
                walk(block.else_blocks or [])

    walk(blocks)
    return tables


def structural_findings(document: Document, requirement: str) -> list[dict[str, str]]:
    """Return typed structural findings for a generated document."""
    findings: list[dict[str, str]] = []
    expects_table = requirement_expects_table(requirement)
    outer_tables: list[Table] = []

    def visit(
        blocks: list[Block],
        *,
        prefix: str,
        in_repeat: bool,
        in_table: bool,
    ) -> None:
        for index, block in enumerate(blocks):
            location = f"{prefix}[{index}]"
            if isinstance(block, Table):
                if block.repeat is not None and not block.row_template:
                    findings.append(
                        _finding(
                            "plan_table_without_rows",
                            location,
                            "a repeating table needs a row template with cell blocks",
                        )
                    )
                if not in_repeat and not in_table and block.repeat is not None:
                    outer_tables.append(block)
                for row_index, row in enumerate(block.rows):
                    for cell_index, cell in enumerate(row.cells):
                        visit(
                            cell.blocks,
                            prefix=f"{location}.rows[{row_index}].cells[{cell_index}]",
                            in_repeat=in_repeat,
                            in_table=True,
                        )
                for cell_index, cell in enumerate(block.row_template or []):
                    visit(
                        cell.blocks,
                        prefix=f"{location}.row_template[{cell_index}]",
                        in_repeat=in_repeat,
                        in_table=True,
                    )
            elif isinstance(block, Repeat):
                nested_tables = _tables_in(block.blocks)
                for nested in nested_tables:
                    if nested.repeat is not None and nested.repeat.path == block.path:
                        findings.append(
                            _finding(
                                "plan_nested_table_wrapper",
                                location,
                                (
                                    f"repeat over {block.path!r} wraps a table over the "
                                    "same collection; emit an outer table instead"
                                ),
                            )
                        )
                        break
                visit(
                    block.blocks,
                    prefix=f"{location}.blocks",
                    in_repeat=True,
                    in_table=in_table,
                )
            elif isinstance(block, Conditional):
                visit(
                    block.then_blocks,
                    prefix=f"{location}.then",
                    in_repeat=in_repeat,
                    in_table=in_table,
                )
                visit(
                    block.else_blocks or [],
                    prefix=f"{location}.else",
                    in_repeat=in_repeat,
                    in_table=in_table,
                )

    for section_index, section in enumerate(document.sections):
        visit(
            section.body,
            prefix=f"section[{section_index}].body",
            in_repeat=False,
            in_table=False,
        )
        visit(
            section.header or [],
            prefix=f"section[{section_index}].header",
            in_repeat=False,
            in_table=False,
        )
        visit(
            section.footer or [],
            prefix=f"section[{section_index}].footer",
            in_repeat=False,
            in_table=False,
        )

    if expects_table and not outer_tables:
        findings.append(
            _finding(
                "plan_table_hierarchy",
                "document",
                (
                    "the requirement asks for a table, but the plan has no outer, "
                    "repeating table (a nested list, a static table or a table only "
                    "inside a repeat does not satisfy it)"
                ),
            )
        )
    return findings
