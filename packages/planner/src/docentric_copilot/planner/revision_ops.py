"""Targeted revision operations (FR-08).

Re-planning a whole document to move one paragraph produces a noisy diff and an
unnecessary model call. This module applies small, deterministic structural edits
when the instruction clearly maps to one, and returns ``None`` otherwise so the
caller can fall back to replanning.

Every operation is auditable: it reports what it changed, and the resulting IR is
still validated and diffed like any other version.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from docentric_copilot.ddsp_parser.models import NormalizedSchema
from docentric_copilot.schema_resolver.search import tokenize
from docentric_copilot.template_ir import (
    Block,
    Cell,
    Conditional,
    Document,
    FieldBinding,
    Heading,
    ImageBinding,
    Paragraph,
    Repeat,
    Section,
    Table,
    TableColumn,
    TableStyle,
    TextRun,
)

_LANGUAGE_NAMES = {
    "english": "en",
    "german": "de",
    "french": "fr",
    "spanish": "es",
    "italian": "it",
    "dutch": "nl",
    "polish": "pl",
    "russian": "ru",
}

_STOPWORDS = {
    "move",
    "put",
    "place",
    "the",
    "to",
    "into",
    "in",
    "at",
    "of",
    "a",
    "an",
    "and",
    "make",
    "more",
    "compact",
    "narrower",
    "denser",
    "smaller",
    "remove",
    "delete",
    "drop",
    "hide",
    "show",
    "only",
    "when",
    "add",
    "new",
    "column",
    "for",
    "with",
    "please",
    "details",
    "section",
    "block",
    "table",
    "footer",
    "header",
    "page",
}


@dataclass
class RevisionOutcome:
    """Result of a targeted revision."""

    document: Document
    operations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _humanize(identifier: str) -> str:
    import re as _re

    return _re.sub(r"(?<!^)(?=[A-Z])", " ", identifier)[:40]


def _subject_tokens(text: str) -> set[str]:
    return {token for token in tokenize(text) if token not in _STOPWORDS}


def _block_tokens(block: Block) -> set[str]:
    """Tokens describing what a block is about."""
    tokens: set[str] = set()
    if isinstance(block, Paragraph):
        for run in block.runs:
            if isinstance(run, FieldBinding):
                tokens |= set(tokenize(run.path.replace(".", " ")))
            else:
                tokens |= set(tokenize(run.text))
    elif isinstance(block, Heading):
        for run in block.runs:
            tokens |= set(tokenize(getattr(run, "text", "") or ""))
    elif isinstance(block, ImageBinding):
        tokens |= set(tokenize(block.path.replace(".", " ")))
    elif isinstance(block, Table):
        for column in block.columns:
            tokens |= set(tokenize(column.header))
        if block.repeat is not None:
            tokens |= set(tokenize(block.repeat.path.replace(".", " ")))
    elif isinstance(block, Conditional):
        for child in block.then_blocks:
            tokens |= _block_tokens(child)
    elif isinstance(block, Repeat):
        for child in block.blocks:
            tokens |= _block_tokens(child)
    return tokens


def _matches(block: Block, subject: set[str]) -> bool:
    if not subject:
        return False
    overlap = _block_tokens(block) & subject
    if isinstance(block, Heading):
        # A short heading is moved together with its content.
        return bool(overlap)
    return len(overlap) >= min(2, len(subject))


def _split_blocks(blocks: list[Block], subject: set[str]) -> tuple[list[Block], list[Block]]:
    """Split into (kept, matched), removing a directly preceding matching heading."""
    kept: list[Block] = []
    matched: list[Block] = []
    for block in blocks:
        if _matches(block, subject):
            if kept and isinstance(kept[-1], Heading) and _matches(kept[-1], subject):
                matched.append(kept.pop())
            matched.append(block)
        else:
            kept.append(block)
    return kept, matched


def _move(blocks: list[Block], subject: set[str], target: str) -> tuple[list[Block], list[Block]]:
    return _split_blocks(blocks, subject)


def _rebuild(document: Document, sections: list[Section]) -> Document:
    return document.model_copy(update={"sections": sections})


def _replace_sections(document: Document, transform) -> Document:
    return _rebuild(document, [transform(section) for section in document.sections])


# --------------------------------------------------------------------------- #
# Operations
# --------------------------------------------------------------------------- #
def _move_blocks(document: Document, instruction: str) -> RevisionOutcome | None:
    match = re.search(
        r"\b(?:move|put|place)\b(.*?)\b(?:to|into|in)\s+the\s+(footer|header)\b", instruction, re.I
    )
    if not match:
        return None
    subject = _subject_tokens(match.group(1))
    target = match.group(2).lower()
    moved_blocks: list[int] = []

    def transform(section: Section) -> Section:
        body, moved = _move(list(section.body), subject, target)
        if not moved:
            return section
        moved_blocks.extend(range(len(moved)))
        if target == "footer":
            footer = [*(section.footer or []), *moved]
            return section.model_copy(update={"body": body, "footer": footer})
        header = [*(section.header or []), *moved]
        return section.model_copy(update={"body": body, "header": header})

    updated = _replace_sections(document, transform)
    if not moved_blocks:
        return None
    return RevisionOutcome(
        document=updated,
        operations=["move_blocks"],
        notes=[f"Moved {len(moved_blocks)} block(s) to the {target}."],
    )


def _compact_tables(document: Document, instruction: str) -> RevisionOutcome | None:
    if not re.search(r"\b(compact|narrower|denser|tighter|smaller)\b", instruction, re.I):
        return None
    if not re.search(r"\btable\b|\bcolumns?\b|\bitems?\b", instruction, re.I):
        return None
    changed = 0

    def compact(blocks: list[Block]) -> list[Block]:
        nonlocal changed
        result: list[Block] = []
        for block in blocks:
            if isinstance(block, Table):
                style = block.style or TableStyle()
                style = style.model_copy(
                    update={
                        "font_size_pt": max(8.0, (style.font_size_pt or 9.5) - 1.0),
                        "zebra": True,
                    }
                )
                columns = [
                    column.model_copy(
                        update={
                            "width_mm": round((column.width_mm or 25.0) * 0.9, 1),
                        }
                    )
                    for column in block.columns
                ]
                block = block.model_copy(update={"style": style, "columns": columns})
                changed += 1
            elif isinstance(block, Repeat):
                block = block.model_copy(update={"blocks": compact(block.blocks)})
            elif isinstance(block, Conditional):
                block = block.model_copy(
                    update={
                        "then_blocks": compact(block.then_blocks),
                        "else_blocks": compact(list(block.else_blocks or [])) or None,
                    }
                )
            result.append(block)
        return result

    updated = _replace_sections(
        document,
        lambda section: section.model_copy(
            update={
                "body": compact(list(section.body)),
                "footer": compact(list(section.footer or [])),
            }
        ),
    )
    if not changed:
        return None
    return RevisionOutcome(
        document=updated,
        operations=["compact_tables"],
        notes=[f"Compacted {changed} table(s): smaller type, tighter columns, zebra rows."],
    )


def _remove_blocks(document: Document, instruction: str) -> RevisionOutcome | None:
    match = re.search(r"\b(?:remove|delete|drop|without|hide)\b(.*)", instruction, re.I)
    if not match:
        return None
    subject = _subject_tokens(match.group(1))
    if not subject:
        return None
    removed = 0

    def transform(section: Section) -> Section:
        nonlocal removed
        body, matched = _split_blocks(list(section.body), subject)
        removed += len(matched)
        if not matched:
            return section
        return section.model_copy(update={"body": body})

    updated = _replace_sections(document, transform)
    if not removed:
        return None
    return RevisionOutcome(
        document=updated, operations=["remove_blocks"], notes=[f"Removed {removed} block(s)."]
    )


def _set_language(document: Document, instruction: str) -> RevisionOutcome | None:
    lowered = instruction.lower()
    for name, code in _LANGUAGE_NAMES.items():
        if re.search(rf"\b(?:in|to|into)\s+{name}\b", lowered):
            return RevisionOutcome(
                document=document.model_copy(update={"language": code}),
                operations=["set_language"],
                notes=[f"Document language set to '{code}'."],
            )
    return None


def _add_column(
    document: Document, instruction: str, schema: NormalizedSchema | None
) -> RevisionOutcome | None:
    match = re.search(
        r"\badd\s+(?:a\s+)?(?:new\s+)?column\s+(?:for|with)\s+(.+)", instruction, re.I
    )
    if not match or schema is None:
        return None
    subject = _subject_tokens(match.group(1))
    if not subject:
        return None
    added: list[str] = []

    def extend(table: Table) -> Table:
        if table.repeat is None or table.row_template is None:
            return table
        node = schema.node(table.repeat.path)
        if node is None:
            return table
        candidates = [
            child
            for child in node.children
            if not child.children and (set(tokenize(child.name)) & subject)
        ]
        if not candidates:
            return table
        field = sorted(
            candidates, key=lambda child: (-len(set(tokenize(child.name)) & subject), child.path)
        )[0]
        if any(column.header == field.name for column in table.columns):
            return table
        added.append(field.name)
        return table.model_copy(
            update={
                "columns": [
                    *table.columns,
                    TableColumn(header=_humanize(field.name), width_mm=20.0),
                ],
                "row_template": [
                    *table.row_template,
                    Cell(
                        blocks=[
                            Paragraph(
                                runs=[FieldBinding(path=f"{table.repeat.alias}.{field.name}")]
                            )
                        ]
                    ),
                ],
                "footer_rows": [
                    row.model_copy(update={"cells": [*row.cells, Cell(blocks=[])]})
                    for row in table.footer_rows
                ],
            }
        )

    def transform(section: Section) -> Section:
        return section.model_copy(
            update={
                "body": [
                    extend(block) if isinstance(block, Table) else block for block in section.body
                ]
            }
        )

    updated = _replace_sections(document, transform)
    if not added:
        return None
    return RevisionOutcome(
        document=updated,
        operations=["add_column"],
        notes=[f"Added column '{_humanize(added[0])}' bound to the collection item."],
    )


def _rename(document: Document, instruction: str) -> RevisionOutcome | None:
    match = re.search(r'\b(?:rename|title)\b.*?"([^"]{3,120})"', instruction, re.I)
    if not match:
        return None
    new_title = match.group(1).strip()
    if not new_title:
        return None

    def transform(section: Section) -> Section:
        body: list[Block] = []
        for block in section.body:
            if isinstance(block, Heading) and block.level == 1 and not body:
                block = block.model_copy(update={"runs": [TextRun(text=new_title)]})
            body.append(block)
        return section.model_copy(update={"body": body})

    return RevisionOutcome(
        document=_replace_sections(document, transform).model_copy(update={"title": new_title}),
        operations=["rename_title"],
        notes=[f"Document title set to '{new_title}'."],
    )


#: Order matters: the first operation that applies wins. ``add_column`` is the
#: only one that needs the schema (to resolve the collection item's fields).
def apply_revision(
    document: Document, instruction: str, schema: NormalizedSchema | None = None
) -> RevisionOutcome | None:
    """Apply a targeted structural edit, or return ``None`` to replan."""
    if not instruction.strip():
        return None
    for operation in (_move_blocks, _remove_blocks, _compact_tables):
        outcome = operation(document, instruction)
        if outcome is not None:
            return outcome
    if schema is not None:
        outcome = _add_column(document, instruction, schema)
        if outcome is not None:
            return outcome
    for operation in (_set_language, _rename):
        outcome = operation(document, instruction)
        if outcome is not None:
            return outcome
    return None


__all__ = ["RevisionOutcome", "apply_revision"]
