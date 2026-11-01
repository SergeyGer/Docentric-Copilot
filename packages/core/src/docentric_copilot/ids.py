"""Identifier generation.

Identifiers are opaque, URL safe and prefixed by resource kind so that logs and
artifact names are self-describing. They are not secrets.
"""

from __future__ import annotations

import secrets

SOURCE_PREFIX = "src"
JOB_PREFIX = "job"
ARTIFACT_PREFIX = "art"
TEMPLATE_PREFIX = "tpl"
VERSION_PREFIX = "ver"
SESSION_PREFIX = "ses"

_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"


def new_id(prefix: str) -> str:
    """Return ``<prefix>_<20 random base36 characters>``."""
    if not prefix or not prefix.isalnum():
        raise ValueError("prefix must be a non-empty alphanumeric string")
    body = "".join(secrets.choice(_ALPHABET) for _ in range(20))
    return f"{prefix}_{body}"


def is_valid_id(value: str, prefix: str) -> bool:
    if not value.startswith(f"{prefix}_"):
        return False
    body = value[len(prefix) + 1 :]
    return len(body) == 20 and all(char in _ALPHABET for char in body)


__all__ = [
    "ARTIFACT_PREFIX",
    "JOB_PREFIX",
    "SESSION_PREFIX",
    "SOURCE_PREFIX",
    "TEMPLATE_PREFIX",
    "VERSION_PREFIX",
    "is_valid_id",
    "new_id",
]
