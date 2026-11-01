"""Canonical serialization helpers.

Deterministic output is a product requirement (NFR-01, FR-04): identical domain
objects must serialize to identical bytes so that golden files, IR digests and
artifact checksums are meaningful.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel


def to_plain(value: Any) -> Any:
    """Recursively convert pydantic models, tuples and enums to JSON-safe data."""
    if isinstance(value, BaseModel):
        return to_plain(value.model_dump(mode="json", by_alias=False, exclude_none=False))
    if isinstance(value, dict):
        return {str(key): to_plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [to_plain(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if hasattr(value, "value"):  # Enum-like
        return to_plain(value.value)
    return str(value)


def canonical_json(value: Any) -> str:
    """Stable JSON: sorted keys, no insignificant whitespace, UTF-8 text."""
    return json.dumps(
        to_plain(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def pretty_json(value: Any) -> str:
    """Human readable but still deterministic JSON (2-space indent, sorted keys)."""
    return json.dumps(to_plain(value), sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def digest(value: Any) -> str:
    """SHA-256 over the canonical JSON form of ``value``."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def digest_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


__all__ = ["canonical_json", "digest", "digest_bytes", "pretty_json", "to_plain"]
