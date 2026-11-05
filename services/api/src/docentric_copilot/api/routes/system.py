"""System endpoints: providers, jobs, artifacts, health and capabilities (FR-09)."""

from __future__ import annotations

import html

from docentric_copilot import __version__
from docentric_copilot.api.deps import get_service, get_settings, get_store
from docentric_copilot.api.schemas import (
    CapabilitiesView,
    HealthView,
    JobView,
    ProviderView,
)
from docentric_copilot.app.service import TemplateService
from docentric_copilot.config import Settings
from docentric_copilot.docx_compiler import capabilities as compiler_capabilities
from docentric_copilot.storage import Store
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthView)
def health(settings: Settings = Depends(get_settings)) -> HealthView:
    return HealthView(
        status="ok",
        version=__version__,
        environment=settings.environment,
        docentric_ax_adapter_enabled=settings.enable_docentric_ax_adapter,
    )


@router.get("/providers", response_model=list[ProviderView])
def providers(service: TemplateService = Depends(get_service)) -> list[ProviderView]:
    return [ProviderView(**item) for item in service.gateway.describe()]


@router.get("/capabilities", response_model=CapabilitiesView)
def capabilities(
    settings: Settings = Depends(get_settings),
) -> CapabilitiesView:
    return CapabilitiesView(
        compilers=[capability.as_dict() for capability in compiler_capabilities(settings)],
        features={
            "ddsp_parsing": True,
            "schema_explorer": True,
            "semantic_mapping": True,
            "template_ir": True,
            "generic_docx": True,
            "html_preview": True,
            "reference_inspector": True,
            "reference_graph": True,
            "pdf_preview": False,
            "docentric_ax_adapter": False,
            "verified_compatibility": False,
        },
        limits={
            "max_ddsp_bytes": settings.limits.max_ddsp_bytes,
            "max_uncompressed_bytes": settings.limits.max_uncompressed_bytes,
            "max_schema_nodes": settings.limits.max_schema_nodes,
            "artifact_ttl_seconds": settings.artifact_ttl_seconds,
        },
    )


@router.get("/jobs/{job_id}", response_model=JobView)
def get_job(job_id: str, store: Store = Depends(get_store)) -> JobView:
    record = store.get_job(job_id)
    return JobView(
        job_id=record.id,
        kind=record.kind,
        status=record.status,
        duration_ms=record.duration_ms,
        result=record.result,
        error=record.error,
    )


@router.get("/artifacts/{artifact_id}")
def download_artifact(artifact_id: str, store: Store = Depends(get_store)) -> FileResponse:
    record = store.get_artifact(artifact_id)
    return FileResponse(
        path=record.path,
        media_type=record.media_type,
        filename=record.filename,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=0, no-store",
            "X-Artifact-Digest": record.digest,
        },
    )


@router.get("/artifacts/{artifact_id}/view", response_class=HTMLResponse)
def view_artifact(artifact_id: str, store: Store = Depends(get_store)) -> HTMLResponse:
    """Inline view for HTML artifacts (validation report, preview)."""
    record = store.get_artifact(artifact_id)
    if record.media_type != "text/html":
        return HTMLResponse(
            "<!doctype html><p>This artifact is not an HTML document. "
            f'<a href="/api/v1/artifacts/{html.escape(artifact_id)}">Download it instead</a>.</p>',
            status_code=415,
        )
    return HTMLResponse(
        record.path.read_text(encoding="utf-8"),
        headers={"X-Content-Type-Options": "nosniff"},
    )


__all__ = ["router"]
