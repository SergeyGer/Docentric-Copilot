"""Sample-data context used for rendering and conditional evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from docentric_copilot.ddsp_parser.models import NormalizedSchema
from docentric_copilot.schema_resolver.paths import (
    PathResolutionError,
    Scope,
    resolve_collection,
    resolve_value,
)


@dataclass(frozen=True)
class SampleContext:
    """Immutable view over sample data with alias and repeat frames resolved."""

    sample: dict[str, Any]
    schema: NormalizedSchema | None = None
    scope: Scope = field(default_factory=Scope)
    frames: dict[str, dict[str, Any]] = field(default_factory=dict)

    # ---------------------------------------------------------------- scoping
    def child(self, alias: str, collection_path: str, item: dict[str, Any]) -> SampleContext:
        frames = dict(self.frames)
        frames[collection_path] = item
        return SampleContext(
            sample=self.sample,
            schema=self.schema,
            scope=self.scope.push(alias, collection_path),
            frames=frames,
        )

    # -------------------------------------------------------------- accessors
    def absolute(self, path: str) -> str | None:
        """Resolve a scalar or collection path to its absolute form."""
        if self.schema is None:
            return path
        try:
            return resolve_value(self.schema, path, self.scope).absolute
        except PathResolutionError:
            try:
                return resolve_collection(self.schema, path, self.scope).absolute
            except PathResolutionError:
                return None

    def _from_frames(self, absolute: str) -> tuple[bool, Any]:
        for prefix in sorted(self.frames, key=len, reverse=True):
            if absolute == prefix:
                return True, self.frames[prefix]
            if absolute.startswith(f"{prefix}."):
                remainder = absolute[len(prefix) + 1 :]
                return True, _traverse(self.frames[prefix], remainder)
        return False, None

    def value(self, path: str | None) -> Any:
        if not path:
            return None
        absolute = self.absolute(path)
        if absolute is None:
            return None
        found, framed = self._from_frames(absolute)
        if found:
            return framed
        return _traverse(self.sample, absolute)

    def collection(self, path: str) -> list[dict[str, Any]]:
        value = self.value(path)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        return []


def _traverse(data: Any, dotted: str) -> Any:
    current = data
    for segment in dotted.split("."):
        if isinstance(current, dict):
            if segment not in current:
                return None
            current = current[segment]
        elif isinstance(current, list):
            # A list is a leaf value in the normalized sample: descending into it
            # requires an explicit repeat frame.
            return None
        else:
            return None
    return current


__all__ = ["SampleContext"]
