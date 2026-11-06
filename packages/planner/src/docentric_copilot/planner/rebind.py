"""Re-point bindings from one schema path to another.

Used when a reviewer accepts or changes a mapping suggestion. The rewrite is
scope-aware: inside a repeat block the new path is expressed relative to the
active alias, so the IR stays valid and readable.
"""

from __future__ import annotations

from docentric_copilot.ddsp_parser.models import NormalizedSchema
from docentric_copilot.schema_resolver.paths import (
    PathResolutionError,
    Scope,
    resolve_collection,
    resolve_value,
)
from docentric_copilot.template_ir import (
    Block,
    Conditional,
    Document,
    FieldBinding,
    ImageBinding,
    Paragraph,
    Repeat,
    Section,
    Table,
)

Binding = FieldBinding | ImageBinding


def _relative(path: str, scope: Scope) -> str:
    for alias, collection in sorted(scope.aliases.items(), key=lambda item: -len(item[1])):
        if path.startswith(f"{collection}."):
            return f"{alias}.{path[len(collection) + 1 :]}"
    return path


def rebind_paths(
    document: Document,
    schema: NormalizedSchema,
    old_absolute: str,
    new_path: str,
) -> tuple[Document, int]:
    """Replace every binding that resolves to ``old_absolute`` with ``new_path``."""
    changed = 0

    def walk_binding(binding: Binding, scope: Scope) -> Binding:
        nonlocal changed
        try:
            resolved = resolve_value(schema, binding.path, scope)
        except PathResolutionError:
            return binding
        if resolved.absolute != old_absolute:
            return binding
        changed += 1
        return binding.model_copy(update={"path": _relative(new_path, scope)})

    def walk(blocks: list[Block], scope: Scope) -> list[Block]:
        result: list[Block] = []
        for block in blocks:
            if isinstance(block, Paragraph):
                runs = [
                    walk_binding(run, scope) if isinstance(run, FieldBinding) else run
                    for run in block.runs
                ]
                block = block.model_copy(update={"runs": runs})
            elif isinstance(block, ImageBinding):
                block = walk_binding(block, scope)  # type: ignore[assignment]
            elif isinstance(block, Repeat):
                try:
                    collection = resolve_collection(schema, block.path, scope)
                    child_scope = scope.push(block.alias, collection.absolute)
                except PathResolutionError:
                    child_scope = scope
                block = block.model_copy(update={"blocks": walk(block.blocks, child_scope)})
            elif isinstance(block, Conditional):
                block = block.model_copy(
                    update={
                        "then_blocks": walk(block.then_blocks, scope),
                        "else_blocks": walk(list(block.else_blocks or []), scope) or None,
                    }
                )
            elif isinstance(block, Table):
                row_scope = scope
                if block.repeat is not None:
                    try:
                        collection = resolve_collection(schema, block.repeat.path, scope)
                        row_scope = scope.push(block.repeat.alias, collection.absolute)
                    except PathResolutionError:
                        row_scope = scope
                rows = [
                    type(row)(
                        cells=[type(cell)(blocks=walk(cell.blocks, scope)) for cell in row.cells]
                    )
                    for row in block.rows
                ]
                template = (
                    [type(cell)(blocks=walk(cell.blocks, row_scope)) for cell in block.row_template]
                    if block.row_template
                    else None
                )
                footer_rows = [
                    type(row)(
                        cells=[type(cell)(blocks=walk(cell.blocks, scope)) for cell in row.cells]
                    )
                    for row in block.footer_rows
                ]
                block = block.model_copy(
                    update={
                        "rows": rows,
                        "row_template": template,
                        "footer_rows": footer_rows,
                    }
                )
            result.append(block)
        return result

    sections: list[Section] = []
    for section in document.sections:
        sections.append(
            section.model_copy(
                update={
                    "body": walk(list(section.body), Scope()),
                    "header": walk(list(section.header or []), Scope()) or None,
                    "first_page_header": (
                        walk(list(section.first_page_header), Scope())
                        if section.first_page_header is not None
                        else None
                    ),
                    "footer": walk(list(section.footer or []), Scope()) or None,
                }
            )
        )
    return document.model_copy(update={"sections": sections}), changed


__all__ = ["rebind_paths"]
