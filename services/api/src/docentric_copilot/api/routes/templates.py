"""Template planning, validation, compilation, revision and preview endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool

from docentric_copilot.api.deps import get_service, get_store
from docentric_copilot.api.routes.common import (
    MEDIA_TYPES,
    load_source,
    publish,
    publish_ir_bundle,
    resolve_document,
)
from docentric_copilot.api.schemas import (
    CompileRequest,
    CompileResponse,
    PlanRequest,
    PlanResponse,
    PreviewRequest,
    RevisionRequest,
    RevisionResponse,
    ValidateRequest,
    ValidateResponse,
)
from docentric_copilot.app.service import TemplateService
from docentric_copilot.docx_compiler import CompileOptions
from docentric_copilot.errors import CopilotError, ValidationFailedError
from docentric_copilot.storage import Store
from docentric_copilot.template_ir import canonical_ir_json, ir_digest
from docentric_copilot.template_validator import render_report_html

router = APIRouter(prefix="/templates", tags=["templates"])


def _validation_failure(report) -> ValidationFailedError:
    return ValidationFailedError(
        "The template failed validation",
        details={
            "validation": report.statuses(),
            "overall": report.overall,
            "report": report.model_dump(mode="json"),
        },
    )


@router.post("/plan", response_model=PlanResponse)
async def plan_template(
    request: PlanRequest,
    store: Store = Depends(get_store),
    service: TemplateService = Depends(get_service),
) -> PlanResponse:
    """Turn a natural language requirement into a validated Template IR."""
    record, schema = load_source(store, request.source_id)
    job_id = store.create_job("plan", request.model_dump(mode="json"))
    try:
        outcome, report = await service.plan(
            schema,
            request.prompt,
            provider=request.provider,
            model=request.model,
            design_style=request.design_style.value,
            language=request.options.language,
            target=request.target.value,
            max_repair_attempts=request.options.max_repair_attempts,
        )
        if request.options.strict_validation and not report.can_compile:
            raise _validation_failure(report)

        template_id, _ = store.create_template(record.id)
        version = store.add_version(
            template_id,
            ir=outcome.document.model_dump(mode="json"),
            mapping=outcome.mapping.model_dump(mode="json"),
            validation=report.model_dump(mode="json"),
            provider=request.provider,
            model=request.model,
        )
        stem = f"{template_id}-v{version}"
        preview = await run_in_threadpool(
            service.preview, outcome.document, schema, sample_data=record.sample_dict()
        )
        artifacts = publish_ir_bundle(
            store,
            job_id=job_id,
            template_id=stem,
            document=outcome.document,
            mapping=outcome.mapping.model_dump(mode="json"),
            report_html=render_report_html(report),
            report_json=report.model_dump(mode="json"),
            preview_html=preview.html,
        )
        response = PlanResponse(
            job_id=job_id,
            status="completed",
            template_id=template_id,
            version=version,
            ir_digest=ir_digest(outcome.document),
            ir=outcome.document.model_dump(mode="json"),
            mapping=outcome.mapping.model_dump(mode="json"),
            report=report,
            validation=report.statuses(),
            warnings=[*outcome.warnings, *preview.warnings],
            removed_bindings=[item.model_dump(mode="json") for item in outcome.removed_bindings],
            generation=outcome.generation.public_view() if outcome.generation else None,
            artifacts=artifacts,
        )
        store.finish_job(
            job_id,
            {
                "template_id": template_id,
                "version": version,
                "ir_digest": response.ir_digest,
                "validation": response.validation,
                "artifacts": [artifact.id for artifact in artifacts],
            },
        )
        return response
    except CopilotError as exc:
        store.fail_job(job_id, exc.to_dict())
        raise


@router.post("/validate", response_model=ValidateResponse)
async def validate_template(
    request: ValidateRequest,
    store: Store = Depends(get_store),
    service: TemplateService = Depends(get_service),
) -> ValidateResponse:
    """Validate an IR against a source schema (V1-V5)."""
    record, schema = load_source(store, request.source_id)
    document = resolve_document(
        store,
        template_id=request.template_id,
        version=request.version,
        inline_ir=request.ir,
        source_id=request.source_id,
    )
    report = await run_in_threadpool(
        service.validate, document, schema, sample_data=record.sample_dict()
    )
    return ValidateResponse(
        validation=report.statuses(), overall=report.overall, report=report
    )


@router.post("/compile", response_model=CompileResponse)
async def compile_template(
    request: CompileRequest,
    store: Store = Depends(get_store),
    service: TemplateService = Depends(get_service),
) -> CompileResponse:
    """Compile a validated IR into a DOCX artifact (deterministic, no LLM)."""
    record, schema = load_source(store, request.source_id)
    job_id = store.create_job("compile", request.model_dump(mode="json"))
    try:
        document = resolve_document(
            store,
            template_id=request.template_id,
            version=request.version,
            inline_ir=request.ir,
            source_id=request.source_id,
        )
        document = document.model_copy(update={"target": request.target})
        sample = record.sample_dict() if request.options.use_sample_data else None
        report = await run_in_threadpool(
            service.validate, document, schema, sample_data=sample
        )
        if not report.can_compile:
            raise _validation_failure(report)

        options = CompileOptions(
            target=request.target,
            render_mode=request.options.render_mode,
            include_compatibility_stamp=request.options.include_compatibility_stamp,
            document_name=request.options.document_name,
        )
        result = await run_in_threadpool(
            service.compile, document, schema, sample_data=sample, options=options
        )
        report = await run_in_threadpool(
            service.validate, document, schema, sample_data=sample, package=result.content
        )
        docx_artifact = publish(
            store,
            kind="docx",
            filename=request.options.document_name,
            payload=result.content,
            media_type=MEDIA_TYPES["docx"],
            job_id=job_id,
        )
        extra_artifacts = [
            publish(
                store,
                kind="validation",
                filename=f"{document.metadata.template_name}.validation.json",
                payload=report.model_dump_json(indent=2) + "\n",
                media_type=MEDIA_TYPES["validation"],
                job_id=job_id,
            ),
            publish(
                store,
                kind="validation_html",
                filename=f"{document.metadata.template_name}.validation.html",
                payload=render_report_html(report),
                media_type=MEDIA_TYPES["validation_html"],
                job_id=job_id,
            ),
        ]
        response = CompileResponse(
            job_id=job_id,
            status="completed",
            artifact_id=docx_artifact.id,
            ir_digest=result.ir_digest,
            validation=report.statuses(),
            report=report,
            warnings=result.warnings,
            stats=result.stats,
            artifacts=[docx_artifact, *extra_artifacts],
        )
        store.finish_job(
            job_id,
            {
                "artifact_id": docx_artifact.id,
                "ir_digest": result.ir_digest,
                "validation": response.validation,
            },
        )
        return response
    except CopilotError as exc:
        store.fail_job(job_id, exc.to_dict())
        raise


@router.post("/revise", response_model=RevisionResponse)
async def revise_template(
    request: RevisionRequest,
    store: Store = Depends(get_store),
    service: TemplateService = Depends(get_service),
) -> RevisionResponse:
    """Create a new IR version from a natural language change request."""
    record, schema = load_source(store, request.source_id)
    previous = store.get_version(request.template_id, request.version)
    from docentric_copilot.template_ir import load_document

    document = load_document(previous.ir())
    job_id = store.create_job("revise", request.model_dump(mode="json"))
    try:
        revision = await service.revise(
            document,
            schema,
            request.instruction,
            provider=request.provider,
            model=request.model,
            design_style=(
                document.metadata.design_style.value
                if document.metadata.design_style
                else "modern"
            ),
            language=document.language,
            target=document.target.value,
        )
        outcome = revision.outcome
        report = await run_in_threadpool(
            service.validate, outcome.document, schema, sample_data=record.sample_dict()
        )
        new_version = store.add_version(
            request.template_id,
            ir=outcome.document.model_dump(mode="json"),
            mapping=outcome.mapping.model_dump(mode="json"),
            validation=report.model_dump(mode="json"),
            provider=request.provider,
            model=request.model,
        )
        stem = f"{request.template_id}-v{new_version}"
        preview = await run_in_threadpool(
            service.preview, outcome.document, schema, sample_data=record.sample_dict()
        )
        artifacts = publish_ir_bundle(
            store,
            job_id=job_id,
            template_id=stem,
            document=outcome.document,
            mapping=outcome.mapping.model_dump(mode="json"),
            report_html=render_report_html(report),
            report_json=report.model_dump(mode="json"),
            preview_html=preview.html,
        )
        response = RevisionResponse(
            job_id=job_id,
            status="completed",
            template_id=request.template_id,
            version=new_version,
            ir_digest=ir_digest(outcome.document),
            ir=outcome.document.model_dump(mode="json"),
            mapping=outcome.mapping.model_dump(mode="json"),
            report=report,
            validation=report.statuses(),
            change_summary=revision.summary,
            changes=[change.to_dict() for change in revision.changes[:50]],
            warnings=outcome.warnings,
            artifacts=artifacts,
        )
        store.finish_job(
            job_id,
            {
                "template_id": request.template_id,
                "version": new_version,
                "changes": revision.summary,
            },
        )
        return response
    except CopilotError as exc:
        store.fail_job(job_id, exc.to_dict())
        raise


@router.post("/preview", response_class=HTMLResponse)
async def preview_template(
    request: PreviewRequest,
    store: Store = Depends(get_store),
    service: TemplateService = Depends(get_service),
) -> HTMLResponse:
    """Render the independent HTML preview of a template."""
    record, schema = load_source(store, request.source_id)
    document = resolve_document(
        store,
        template_id=request.template_id,
        version=request.version,
        inline_ir=request.ir,
        source_id=request.source_id,
    )
    preview = await run_in_threadpool(
        service.preview, document, schema, sample_data=record.sample_dict()
    )
    return HTMLResponse(
        preview.html,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
                "base-uri 'none'; form-action 'none'"
            ),
        },
    )


@router.get("/{template_id}/versions")
def list_versions(template_id: str, store: Store = Depends(get_store)) -> dict:
    return {"template_id": template_id, "versions": store.list_versions(template_id)}


@router.get("/{template_id}/export/{version}")
def export_version(
    template_id: str, version: int, store: Store = Depends(get_store)
) -> dict:
    record = store.get_version(template_id, version)
    from docentric_copilot.template_ir import load_document

    document = load_document(record.ir())
    return {
        "template_id": template_id,
        "version": version,
        "ir_digest": ir_digest(document),
        "ir": record.ir(),
        "mapping": record.mapping(),
        "validation": record.validation(),
        "canonical_ir": canonical_ir_json(document),
    }


__all__ = ["router"]
