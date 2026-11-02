"""Document quality, layout optimisation and routing (Initiatives 1 and 2)."""

from __future__ import annotations

from typing import Any

from docentric_copilot.api.deps import get_service, get_store
from docentric_copilot.api.routes.common import resolve_document
from docentric_copilot.app.service import TemplateService
from docentric_copilot.ddsp_parser.models import NormalizedSchema
from docentric_copilot.errors import InvalidInputError
from docentric_copilot.planner import (
    analyze_quality,
    classify,
    optimize_layout,
    route,
    routing_policy,
)
from docentric_copilot.schema_resolver import parse_requirements
from docentric_copilot.storage import Store
from docentric_copilot.template_ir import ir_digest
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

router = APIRouter(prefix="/templates", tags=["quality"])


class DocumentRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    template_id: str | None = None
    version: int | None = None
    ir: dict[str, Any] | None = None


class QualityResponse(BaseModel):
    report: dict[str, Any]
    ir_digest: str


class OptimizeResponse(BaseModel):
    template_id: str
    version: int
    fixes: list[dict[str, Any]]
    before: dict[str, Any]
    after: dict[str, Any]
    ir: dict[str, Any]
    ir_digest: str
    validation: dict[str, str]


class RouteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    prompt: str = Field(min_length=1, max_length=20_000)


class RouteResponse(BaseModel):
    decision: dict[str, Any]
    policy: dict[str, Any]
    requirements: int


def _load(store: Store, reference: DocumentRef):
    source = store.get_source(reference.source_id)
    schema = NormalizedSchema.model_validate(source.schema_dict())
    document = resolve_document(
        store,
        template_id=reference.template_id,
        version=reference.version,
        inline_ir=reference.ir,
        source_id=reference.source_id,
    )
    return source, schema, document


@router.post("/quality", response_model=QualityResponse)
async def quality(reference: DocumentRef, store: Store = Depends(get_store)) -> QualityResponse:
    source, schema, document = _load(store, reference)
    report = analyze_quality(document, schema, sample_data=source.sample_dict())
    return QualityResponse(report=report.model_dump(mode="json"), ir_digest=ir_digest(document))


@router.post("/optimize", response_model=OptimizeResponse)
async def optimize(
    reference: DocumentRef,
    store: Store = Depends(get_store),
    service: TemplateService = Depends(get_service),
) -> OptimizeResponse:
    if reference.template_id is None:
        raise InvalidInputError("Optimisation creates a version and needs a template_id")
    source, schema, document = _load(store, reference)
    outcome = optimize_layout(document, schema, sample_data=source.sample_dict())
    if not outcome.fixes:
        raise InvalidInputError(
            "The layout already fits; there is nothing to optimise",
            details={"overall": outcome.before.overall.value},
        )
    validation = await run_in_threadpool(
        service.validate, outcome.document, schema, sample_data=source.sample_dict()
    )
    mapping = store.get_version(reference.template_id, reference.version).mapping()
    version = store.add_version(
        reference.template_id,
        ir=outcome.document.model_dump(mode="json"),
        mapping=mapping,
        validation=validation.model_dump(mode="json"),
        provider="layout",
        model=None,
    )
    return OptimizeResponse(
        template_id=reference.template_id,
        version=version,
        fixes=[fix.model_dump(mode="json") for fix in outcome.fixes],
        before=outcome.before.model_dump(mode="json"),
        after=outcome.after.model_dump(mode="json"),
        ir=outcome.document.model_dump(mode="json"),
        ir_digest=ir_digest(outcome.document),
        validation=validation.statuses(),
    )


@router.post("/route", response_model=RouteResponse)
async def decide_route(request: RouteRequest, store: Store = Depends(get_store)) -> RouteResponse:
    source = store.get_source(request.source_id)
    schema = NormalizedSchema.model_validate(source.schema_dict())
    requirements = parse_requirements(request.prompt).requirements
    complexity, reasons = classify(schema, requirements)
    decision = route(complexity, configured={"mock"})
    decision = decision.model_copy(update={"reason": [*reasons, *decision.reason]})
    return RouteResponse(
        decision=decision.model_dump(mode="json"),
        policy=routing_policy(),
        requirements=len(requirements),
    )


__all__ = ["router"]
