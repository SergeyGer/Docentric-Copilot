"""DDSP upload and schema discovery endpoints (FR-01, FR-09)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile

from docentric_copilot.api.deps import get_settings, get_store
from docentric_copilot.api.routes.common import load_source
from docentric_copilot.api.schemas import SchemaView, SourceView
from docentric_copilot.config import Settings
from docentric_copilot.ddsp_parser import parse_ddsp
from docentric_copilot.errors import UnsupportedInputError
from docentric_copilot.storage import Store

router = APIRouter(prefix="/sources", tags=["sources"])

_ALLOWED_SUFFIXES = (".ddsp", ".xml", ".xsd", ".zip")


@router.post("", response_model=SourceView, status_code=201)
async def upload_source(
    file: UploadFile = File(..., description="DDSP package or XML document"),
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> SourceView:
    """Parse an untrusted DDSP package and register it as a data source."""
    filename = file.filename or "source.ddsp"
    if not filename.lower().endswith(_ALLOWED_SUFFIXES):
        raise UnsupportedInputError(
            "Unsupported file extension",
            code="input_unsupported",
            details={"filename": filename, "allowed": list(_ALLOWED_SUFFIXES)},
        )
    limit = settings.limits.max_ddsp_bytes
    payload = await file.read(limit + 1)
    if len(payload) > limit:
        raise UnsupportedInputError(
            "Uploaded file exceeds the configured maximum size",
            code="DDSP001",
            details={"max_bytes": limit},
        )
    parsed = parse_ddsp(payload, filename=filename, limits=settings.limits)
    schema = parsed.schema
    record = store.create_source(
        filename=filename,
        schema_id=schema.schema_id,
        schema=schema.model_dump(mode="json"),
        sample=parsed.sample_data,
        entry_names=list(parsed.entry_names),
    )
    return SourceView(
        source_id=record.id,
        filename=record.filename,
        schema_id=schema.schema_id,
        sections=schema.section_names,
        stats=schema.stats().model_dump(mode="json"),
        sample_data_available=schema.sample_data_available,
        diagnostics=[item.model_dump(mode="json") for item in schema.diagnostics],
        entry_names=list(parsed.entry_names),
    )


@router.get("/{source_id}/schema", response_model=SchemaView)
def get_schema(source_id: str, store: Store = Depends(get_store)) -> SchemaView:
    """Return the normalized schema discovered for a source."""
    record, schema = load_source(store, source_id)
    return SchemaView(
        source_id=record.id,
        normalized_schema=record.schema_dict(),
        stats=schema.stats().model_dump(mode="json"),
        diagnostics=[item.model_dump(mode="json") for item in schema.diagnostics],
    )


__all__ = ["router"]
