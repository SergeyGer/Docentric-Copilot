"""Structural traversal helpers for the Template IR.

The compiler, validator and preview renderer all need to walk the same tree; a
single implementation keeps their notions of "block order" and "depth" aligned.
"""

from __future__ import annotations

from collections.abc import Iterator

from .models import (
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
    Section,
    Table,
)


def iter_expressions(expression: Expression) -> Iterator[Expression]:
    """Yield an expression and all of its nested operands (pre-order)."""
    yield expression
    for operand in expression.operands or []:
        yield from iter_expressions(operand)


def iter_blocks(blocks: list[Block], depth: int = 0) -> Iterator[tuple[Block, int]]:
    """Yield ``(block, depth)`` in document order, descending into containers."""
    for block in blocks:
        yield block, depth
        if isinstance(block, Repeat):
            yield from iter_blocks(block.blocks, depth + 1)
        elif isinstance(block, Conditional):
            yield from iter_blocks(block.then_blocks, depth + 1)
            yield from iter_blocks(list(block.else_blocks or []), depth + 1)
        elif isinstance(block, Table):
            for row in block.rows:
                for cell in row.cells:
                    yield from iter_blocks(cell.blocks, depth + 1)
            for cell in block.row_template or []:
                yield from iter_blocks(cell.blocks, depth + 1)


def iter_section_blocks(section: Section) -> Iterator[tuple[Block, int]]:
    yield from iter_blocks(section.body)
    yield from iter_blocks(list(section.header or []))
    yield from iter_blocks(list(section.footer or []))


def iter_document_blocks(document: Document) -> Iterator[tuple[Block, int]]:
    for section in document.sections:
        yield from iter_section_blocks(section)


def iter_inline(block: Block) -> Iterator[FieldBinding | ImageBinding]:
    """Yield every binding contained directly in a block (not its children)."""
    if isinstance(block, Paragraph | Heading):
        for run in block.runs:
            if isinstance(run, FieldBinding):
                yield run
    elif isinstance(block, ImageBinding):
        yield block


def iter_all_bindings(document: Document) -> Iterator[FieldBinding | ImageBinding]:
    for block, _depth in iter_document_blocks(document):
        yield from iter_inline(block)


def iter_field_bindings(document: Document) -> Iterator[FieldBinding]:
    for binding in iter_all_bindings(document):
        if isinstance(binding, FieldBinding):
            yield binding


def iter_image_bindings(document: Document) -> Iterator[ImageBinding]:
    for binding in iter_all_bindings(document):
        if isinstance(binding, ImageBinding):
            yield binding


def iter_conditions(document: Document) -> Iterator[Expression]:
    for block, _depth in iter_document_blocks(document):
        if isinstance(block, Conditional):
            yield from iter_expressions(block.condition)


def count_blocks(document: Document) -> int:
    return sum(1 for _ in iter_document_blocks(document))


def max_block_depth(document: Document) -> int:
    return max((depth for _block, depth in iter_document_blocks(document)), default=0)


def iter_tables(blocks: list[Block]) -> Iterator[Table]:
    for block, _depth in iter_blocks(blocks):
        if isinstance(block, Table):
            yield block


def table_cell_blocks(table: Table) -> Iterator[Cell]:
    for row in table.rows:
        yield from row.cells
    yield from table.row_template or []


__all__ = [
    "count_blocks",
    "iter_all_bindings",
    "iter_blocks",
    "iter_conditions",
    "iter_document_blocks",
    "iter_expressions",
    "iter_field_bindings",
    "iter_image_bindings",
    "iter_inline",
    "iter_section_blocks",
    "iter_tables",
    "max_block_depth",
    "table_cell_blocks",
]
