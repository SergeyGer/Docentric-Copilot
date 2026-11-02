"""Human review actions on a mapping: confirm or change a binding (FR-02).

A planner suggestion is a proposal. This router records the reviewer's decision
as a new immutable IR version, re-runs validation, and returns the updated
mapping so the workspace can show ``confirmed`` with a human signature.
"""

from __future__ import annotations

from typing import Any

from docentric_copilot.api.deps import get_service, get_store
from docentric_copilot.app.service import TemplateService
from docentric_copilot.ddsp_parser.models import NormalizedSchema
from docentric_copilot.errors import InvalidInputError, NotFoundError
from docentric_copilot.planner import rebind_paths
from docentric_copilot.planner.service import build_mapping_report
from docentric_copilot.schema_resolver import MappingStatus
from docentric_copilot.storage import Store
from docentric_copilot.template_ir import ir_digest, load_document
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

router = APIRouter(prefix="/templates", tags=["review"])


class ConfirmMappingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_field_path: str | None = Field(default=None, max_length=512)
    note: str | None = Field(default=None, max_length=500)


class ConfirmMappingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: str
    version: int
    requirement_id: str
    selected_field_path: str | None
    mapping: dict[str, Any]
    report: dict[str, Any]
    validation: dict[str, str]
    ir: dict[str, Any]
    ir_digest: str
    rebind_count: int


@router.post(
    "/{template_id}/versions/{version}/mappings/{requirement_id}/confirm",
    response_model=ConfirmMappingResponse,
)
async def confirm_mapping(
    template_id: str,
    version: int,
    requirement_id: str,
    request: ConfirmMappingRequest,
    store: Store = Depends(get_store),
    service: TemplateService = Depends(get_service),
) -> ConfirmMappingResponse:
    record = store.get_version(template_id, version)
    source_id = store.template_source(template_id)
    source, schema = _load_source(store, source_id)
    document = load_document(record.ir())
    intent = document.metadata.intent or ""

    report = build_mapping_report(schema, document, intent)
    mapping = next(
        (item for item in report.mappings if item.requirement_id == requirement_id), None
    )
    if mapping is None:
        raise NotFoundError(
            "Requirement not found in this version",
            details={
                "template_id": template_id,
                "version": version,
                "requirement_id": requirement_id,
            },
        )

    target = request.selected_field_path or mapping.selected_field_path
    rebind_count = 0
    if target is not None:
        node = schema.node(target)
        if node is None:
            raise InvalidInputError(
                "The selected field does not exist in the schema",
                details={"path": target},
            )
        if node.collection or node.children:
            raise InvalidInputError(
                "A scalar field is required for a value binding",
                details={"path": target, "reason": "not_scalar"},
            )
        if mapping.selected_field_path and mapping.selected_field_path != target:
            document, rebind_count = rebind_paths(
                document, schema, mapping.selected_field_path, target
            )

    report = build_mapping_report(schema, document, intent)
    report = report.model_copy(
        update={
            "mappings": [
                item.model_copy(
                    update={
                        "status": MappingStatus.CONFIRMED,
                        "confidence_score": 1.0,
                        "evidence_score": 1.0,
                        "conflict": False,
                        "conflicts_with": [],
                        "selected_field_path": target or item.selected_field_path,
                        "explanation": (
                            request.note.strip()
                            if request.note and request.note.strip()
                            else "Confirmed by a reviewer."
                        ),
                    }
                )
                if item.requirement_id == requirement_id
                else item
                for item in report.mappings
            ]
        }
    )

    validation = await run_in_threadpool(
        service.validate, document, schema, sample_data=source.sample_dict()
    )
    new_version = store.add_version(
        template_id,
        ir=document.model_dump(mode="json"),
        mapping=report.model_dump(mode="json"),
        validation=validation.model_dump(mode="json"),
        provider="review",
        model=None,
    )
    return ConfirmMappingResponse(
        template_id=template_id,
        version=new_version,
        requirement_id=requirement_id,
        selected_field_path=target,
        mapping=report.model_dump(mode="json"),
        report=validation.model_dump(mode="json"),
        validation=validation.statuses(),
        ir=document.model_dump(mode="json"),
        ir_digest=ir_digest(document),
        rebind_count=rebind_count,
    )


def _load_source(store: Store, source_id: str):
    record = store.get_source(source_id)
    return record, NormalizedSchema.model_validate(record.schema_dict())


__all__ = ["ConfirmMappingRequest", "ConfirmMappingResponse", "router"]
