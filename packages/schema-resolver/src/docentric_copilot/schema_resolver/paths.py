"""Typed path resolution against a normalized schema (FR-02, FR-07).

Two rules matter for correctness:

* A path that does not exist in the schema can never become a binding.
* A scalar located inside a collection may only be used inside a repeat context
  whose alias covers that collection.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from docentric_copilot.ddsp_parser.models import NormalizedSchema, SchemaNode


class PathResolutionError(Exception):
    """Structured resolution failure with a stable code."""

    def __init__(self, code: str, message: str, *, path: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path
        self.details = details or {}

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "details": self.details,
        }


@dataclass(frozen=True, slots=True)
class Scope:
    """Lexical alias scope. ``aliases`` maps alias -> absolute collection path."""

    aliases: dict[str, str] = field(default_factory=dict)

    def push(self, alias: str, collection_path: str) -> Scope:
        merged = dict(self.aliases)
        merged[alias] = collection_path
        return Scope(aliases=merged)

    def flattened(self) -> dict[str, str]:
        return dict(self.aliases)


@dataclass(frozen=True, slots=True)
class ResolvedPath:
    requested: str
    absolute: str
    node: SchemaNode
    alias: str | None = None

    @property
    def in_repeat_context(self) -> bool:
        return self.alias is not None


def absolute_path(path: str, scope: Scope | None = None) -> tuple[str, str | None]:
    """Expand a leading alias to its absolute collection path."""
    if scope is not None and scope.aliases:
        head, _, tail = path.partition(".")
        if head in scope.aliases:
            base = scope.aliases[head]
            return (f"{base}.{tail}" if tail else base), head
    return path, None


def _enclosing_collections(schema: NormalizedSchema, absolute: str) -> list[str]:
    """Return every collection node that is an ancestor of ``absolute``."""
    parts = absolute.split(".")
    collections: list[str] = []
    for index in range(1, len(parts)):
        prefix = ".".join(parts[:index])
        node = schema.node(prefix)
        if node is not None and node.collection:
            collections.append(prefix)
    return collections


def _inside_collection(schema: NormalizedSchema, absolute: str, scope: Scope) -> str | None:
    for collection_path in _enclosing_collections(schema, absolute):
        if collection_path not in scope.aliases.values():
            return collection_path
    return None


def resolve_value(schema: NormalizedSchema, path: str, scope: Scope | None = None) -> ResolvedPath:
    """Resolve a scalar binding path, enforcing collection context rules."""
    resolved, alias = absolute_path(path, scope)
    node = schema.node(resolved)
    if node is None:
        raise PathResolutionError(
            "path_not_found",
            f"Field '{path}' does not exist in the schema",
            path=path,
            details={"resolved_path": resolved, "reason": "unknown_path"},
        )
    if node.collection:
        raise PathResolutionError(
            "type_mismatch",
            f"'{path}' is a collection and cannot be used as a scalar value",
            path=path,
            details={"resolved_path": resolved, "expected": "scalar"},
        )
    if node.children:
        raise PathResolutionError(
            "type_mismatch",
            f"'{path}' is a complex object and cannot be used as a scalar value",
            path=path,
            details={"resolved_path": resolved},
        )
    enclosing = _inside_collection(schema, resolved, scope or Scope())
    if enclosing is not None:
        raise PathResolutionError(
            "context_violation",
            f"'{path}' belongs to collection '{enclosing}' and requires an enclosing repeat block",
            path=path,
            details={"resolved_path": resolved, "collection": enclosing},
        )
    return ResolvedPath(requested=path, absolute=resolved, node=node, alias=alias)


def resolve_collection(
    schema: NormalizedSchema, path: str, scope: Scope | None = None
) -> ResolvedPath:
    """Resolve a collection path used by ``Repeat`` / ``Table.repeat``."""
    resolved, alias = absolute_path(path, scope)
    node = schema.node(resolved)
    if node is None:
        raise PathResolutionError(
            "path_not_found",
            f"Collection '{path}' does not exist in the schema",
            path=path,
            details={"resolved_path": resolved},
        )
    if not node.collection:
        raise PathResolutionError(
            "type_mismatch",
            f"'{path}' is not a collection and cannot be iterated",
            path=path,
            details={"resolved_path": resolved},
        )
    enclosing = _inside_collection(schema, resolved, scope or Scope())
    if enclosing is not None and enclosing != resolved:
        raise PathResolutionError(
            "context_violation",
            f"'{path}' is a nested collection and requires an enclosing repeat block",
            path=path,
            details={"resolved_path": resolved, "collection": enclosing},
        )
    return ResolvedPath(requested=path, absolute=resolved, node=node, alias=alias)


TYPE_COMPATIBILITY: dict[str, set[str]] = {
    "string": {"string", "any"},
    "number": {"number", "any"},
    "boolean": {"boolean", "any"},
    "date": {"date", "string", "any"},
    "image": {"image", "any"},
}


def is_type_compatible(expected: str, actual: str) -> bool:
    """True when a value of ``actual`` schema type can fill an ``expected`` slot."""
    if expected == "any" or actual == "any":
        return True
    return actual in TYPE_COMPATIBILITY.get(expected, {expected})


__all__ = [
    "PathResolutionError",
    "ResolvedPath",
    "Scope",
    "absolute_path",
    "is_type_compatible",
    "resolve_collection",
    "resolve_value",
]
