"""IR revisions: structural diff between template versions (FR-08).

A revision never edits a DOCX. It produces a new IR version; this module makes the
change reviewable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from docentric_copilot.serialization import to_plain
from docentric_copilot.template_ir import Document

_MAX_CHANGES = 200


@dataclass(frozen=True, slots=True)
class Change:
    path: str
    kind: str  # "added" | "removed" | "changed"
    before: Any = None
    after: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "before": self.before,
            "after": self.after,
        }


def _walk(before: Any, after: Any, prefix: str, changes: list[Change]) -> None:
    if len(changes) >= _MAX_CHANGES:
        return
    if type(before) is not type(after):  # noqa: E721 - strict comparison is intended
        changes.append(Change(prefix, "changed", before, after))
        return
    if isinstance(before, dict):
        for key in sorted(set(before) | set(after)):
            child = f"{prefix}.{key}" if prefix else str(key)
            if key not in before:
                changes.append(Change(child, "added", None, after[key]))
            elif key not in after:
                changes.append(Change(child, "removed", before[key], None))
            else:
                _walk(before[key], after[key], child, changes)
        return
    if isinstance(before, list):
        if len(before) != len(after):
            changes.append(Change(f"{prefix}.length", "changed", len(before), len(after)))
        for index, (left, right) in enumerate(zip(before, after, strict=False)):
            _walk(left, right, f"{prefix}[{index}]", changes)
        return
    if before != after:
        changes.append(Change(prefix, "changed", before, after))


def diff_documents(before: Document, after: Document) -> list[Change]:
    """Return a bounded, deterministic list of structural changes."""
    changes: list[Change] = []
    _walk(to_plain(before), to_plain(after), "", changes)
    return changes


def summarize_changes(changes: list[Change]) -> dict[str, Any]:
    counts = {"added": 0, "removed": 0, "changed": 0}
    for change in changes:
        counts[change.kind] = counts.get(change.kind, 0) + 1
    return {
        "total": len(changes),
        "counts": counts,
        "examples": [change.to_dict() for change in changes[:10]],
    }


__all__ = ["Change", "diff_documents", "summarize_changes"]
