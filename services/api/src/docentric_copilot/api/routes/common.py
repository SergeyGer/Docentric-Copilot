"""Shared route helpers: artifact publishing and document resolution."""

from __future__ import annotations

import json
from typing import Any

from docentric_copilot.api.schemas import ArtifactView
from docentric_copilot.ddsp_parser.models import NormalizedSchema
from docentric_copilot.errors import InvalidInputError, NotFoundError
from docentric_copilot.serialization import canonical_json, digest
from docentric_copilot.storage import ArtifactRecord, Store, SourceRecord
from docentric_copilot.template_ir import Document, canonical_ir_json, load_document

MEDIA_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "ir": "application/json",
    "mapping": "application/json",
    "validation": "application/json",
    "validation_html": "text/html",
    "preview": "text/html",
}


def load_source(store: Store, source_id: str) -> tuple[SourceRecord, NormalizedSchema]:
    record = store.get_source(source_id)
    return record, NormalizedSchema.model_validate(record.schema_dict())


def publish(
    store: Store,
    *,
    kind: str,
    filename: str,
    payload: bytes | str,
    media_type: str,
    job_id: str | None = None,
    template_id: str | None = None,
) -> ArtifactView:
    content = payload.encode("utf-8") if isinstance(payload, str) else payload
    record: ArtifactRecord = store.save_artifact(
        kind=kind,
        filename=filename,
        media_type=media_type,
        content=content,
        digest=digest(content),
        job_id=job_id,
        template_id=template_id,
    )
    return ArtifactView(
        id=record.id,
        kind=record.kind,
        filename=record.filename,
        media_type=record.media_type,
        size_bytes=record.size_bytes,
        digest=record.digest,
        url=f"/api/v1/artifacts/{record.id}",
        expires_at=record.expires_at,
    )


def resolve_document(
    store: Store,
    *,
    template_id: str | None,
    version: int | None,
    inline_ir: dict[str, Any] | None,
    source_id: str,
) -> Document:
    """Load an IR from storage or from an inline payload."""
    if inline_ir is not None:
        return load_document(inline_ir)
    if template_id:
        record = store.get_version(template_id, version)
        return load_document(record.ir())
    raise InvalidInputError(
        "Either template_id or ir must be provided",
        details={"source_id": source_id},
    )


def publish_ir_bundle(
    store: Store,
    *,
    job_id: str,
    template_id: str,
    document: Document,
    mapping: dict[str, Any],
    report_html: str,
    report_json: dict[str, Any],
    preview_html: str | None = None,
) -> list[ArtifactView]:
    artifacts = [
        publish(
            store,
            kind="ir",
            filename=f"{template_id}.ir.json",
            payload=canonical_ir_json(document) + "\n",
            media_type=MEDIA_TYPES["ir"],
            job_id=job_id,
            template_id=template_id,
        ),
        publish(
            store,
            kind="mapping",
            filename=f"{template_id}.mapping.json",
            payload=json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            media_type=MEDIA_TYPES["mapping"],
            job_id=job_id,
            template_id=template_id,
        ),
        publish(
            store,
            kind="validation",
            filename=f"{template_id}.validation.json",
            payload=json.dumps(report_json, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            media_type=MEDIA_TYPES["validation"],
            job_id=job_id,
            template_id=template_id,
        ),
        publish(
            store,
            kind="validation_html",
            filename=f"{template_id}.validation.html",
            payload=report_html,
            media_type=MEDIA_TYPES["validation_html"],
            job_id=job_id,
            template_id=template_id,
        ),
    ]
    if preview_html is not None:
        artifacts.append(
            publish(
                store,
                kind="preview",
                filename=f"{template_id}.preview.html",
                payload=preview_html,
                media_type=MEDIA_TYPES["preview"],
                job_id=job_id,
                template_id=template_id,
            )
        )
    return artifacts


def source_or_404(store: Store, source_id: str) -> SourceRecord:
    try:
        return store.get_source(source_id)
    except NotFoundError:
        raise


__all__ = [
    "MEDIA_TYPES",
    "load_source",
    "publish",
    "publish_ir_bundle",
    "resolve_document",
    "source_or_404",
]
