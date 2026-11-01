"""Canonical IR serialization, loading and version migration (FR-04)."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from pydantic import ValidationError

from docentric_copilot.errors import InvalidInputError
from docentric_copilot.serialization import canonical_json, digest, pretty_json, to_plain

from .models import Document

IR_SCHEMA_VERSION = "1.0"
_SUPPORTED_VERSIONS = {"1.0"}

#: Registry of ``from_version -> callable`` that upgrades a payload by one version.
#: A future 1.1 release adds ``{"1.0": migrate_1_0_to_1_1}``; nothing else changes.
MIGRATIONS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}


class IRMigrationError(InvalidInputError):
    code = "ir_version_unsupported"


def _format_validation_errors(error: ValidationError) -> list[dict[str, Any]]:
    formatted: list[dict[str, Any]] = []
    for item in error.errors()[:25]:
        formatted.append(
            {
                "location": ".".join(str(part) for part in item.get("loc", ())),
                "message": item.get("msg", "invalid value"),
                "type": item.get("type", "value_error"),
            }
        )
    return formatted


def load_document(payload: Mapping[str, Any] | str | bytes) -> Document:
    """Parse and validate an IR payload from JSON text, bytes or a mapping."""
    if isinstance(payload, bytes | bytearray):
        try:
            text = bytes(payload).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InvalidInputError("IR payload must be UTF-8 JSON") from exc
        return load_document(text)

    if isinstance(payload, str):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise InvalidInputError(
                "IR payload is not valid JSON",
                details={"position": exc.pos, "reason": exc.msg},
            ) from exc
    else:
        data = dict(payload)

    if not isinstance(data, dict):
        raise InvalidInputError("IR payload must be a JSON object")

    version = data.get("ir_version", IR_SCHEMA_VERSION)
    if not isinstance(version, str):
        raise IRMigrationError("ir_version must be a string")
    data = migrate(data, version)

    try:
        return Document.model_validate(data)
    except ValidationError as exc:
        raise InvalidInputError(
            "IR failed schema validation",
            details={"errors": _format_validation_errors(exc)},
        ) from exc


def migrate(payload: dict[str, Any], version: str | None = None) -> dict[str, Any]:
    """Upgrade ``payload`` to the current IR version, rejecting unknown versions."""
    current_version = version or str(payload.get("ir_version", IR_SCHEMA_VERSION))
    major_minor = ".".join(current_version.split(".")[:2])
    if major_minor not in _SUPPORTED_VERSIONS:
        raise IRMigrationError(
            f"IR version {current_version!r} is not supported by this build",
            details={"supported_versions": sorted(_SUPPORTED_VERSIONS)},
        )
    working = dict(payload)
    steps = 0
    while "ir_version" in working and working["ir_version"] != IR_SCHEMA_VERSION:
        step = MIGRATIONS.get(str(working["ir_version"]))
        if step is None:
            raise IRMigrationError(
                f"no migration path from IR version {working['ir_version']!r}",
            )
        working = step(working)
        steps += 1
        if steps > 16:  # pragma: no cover - defensive against cyclic migrations
            raise IRMigrationError("migration chain is cyclic")
    working["ir_version"] = IR_SCHEMA_VERSION
    return working


def dump_document(document: Document) -> dict[str, Any]:
    """Plain ``dict`` projection with every key present (stable shape)."""
    return to_plain(document)


def canonical_ir_json(document: Document) -> str:
    """Deterministic JSON used for digests, storage and golden files."""
    return canonical_json(document)


def pretty_ir_json(document: Document) -> str:
    return pretty_json(document)


def ir_digest(document: Document) -> str:
    """Stable content digest; identical semantics produce identical digests."""
    return digest(document)


def document_json_schema() -> dict[str, Any]:
    """JSON Schema (draft 2020-12) for external tooling and documentation."""
    schema = Document.model_json_schema(mode="validation")
    schema.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")
    schema["$id"] = f"https://docentric-copilot.dev/schemas/template-ir-v{IR_SCHEMA_VERSION}.json"
    schema["title"] = f"Template IR v{IR_SCHEMA_VERSION}"
    return schema


__all__ = [
    "IR_SCHEMA_VERSION",
    "MIGRATIONS",
    "IRMigrationError",
    "canonical_ir_json",
    "document_json_schema",
    "dump_document",
    "ir_digest",
    "load_document",
    "migrate",
    "pretty_ir_json",
]
