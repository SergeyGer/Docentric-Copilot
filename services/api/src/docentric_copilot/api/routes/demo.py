"""One-click demo sessions.

A demo must be instant, deterministic and offline. This router loads a bundled
synthetic package, runs the complete pipeline with the deterministic provider and
publishes the same artifacts a real session would produce — no model, no typing,
no waiting.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from docentric_copilot.api.deps import get_service, get_store
from docentric_copilot.api.routes.common import MEDIA_TYPES, publish, publish_ir_bundle
from docentric_copilot.api.schemas import ArtifactView
from docentric_copilot.app.service import TemplateService
from docentric_copilot.config import get_settings
from docentric_copilot.ddsp_parser import parse_ddsp
from docentric_copilot.docx_compiler import CompileOptions
from docentric_copilot.errors import NotFoundError
from docentric_copilot.storage import Store
from docentric_copilot.template_ir import ir_digest
from docentric_copilot.template_validator import render_report_html
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

router = APIRouter(prefix="/demo", tags=["demo"])

DEMO_DIR = Path(__file__).parent.parent / "demo"


class DemoCase(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    description: str
    prompt: str
    defect: bool = False


class DemoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(default="quotation", max_length=40)


class DemoTourStep(BaseModel):
    target: str
    title: str
    body: str


class DemoResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case: DemoCase
    source_id: str
    schema_id: str
    sections: list[str]
    stats: dict[str, Any]
    diagnostics: list[dict[str, Any]]
    template_id: str
    version: int
    ir: dict[str, Any]
    ir_digest: str
    mapping: dict[str, Any]
    report: dict[str, Any]
    validation: dict[str, str]
    preview_html: str
    quality: dict[str, Any] | None = None
    docx_artifact_id: str
    artifacts: list[ArtifactView]
    tour: list[DemoTourStep]
    elapsed_ms: int


def _manifest() -> dict[str, Any]:
    path = DEMO_DIR / "manifest.json"
    if not path.exists():  # pragma: no cover - packaging guard
        raise NotFoundError("Demo bundle is not installed")
    return json.loads(path.read_text(encoding="utf-8"))


DEMO_TOUR = [
    DemoTourStep(
        target="#source-panel",
        title="1 · Data source",
        body="A synthetic DDSP package: 34 fields, one repeating collection, sample data and parser diagnostics.",
    ),
    DemoTourStep(
        target="#schema-panel",
        title="2 · Schema explorer",
        body="Every field the document may bind, with its type and the evidence it came from.",
    ),
    DemoTourStep(
        target="#prompt-panel",
        title="3 · Business brief",
        body="One paragraph of plain language. The brief is interpreted into typed requirements.",
    ),
    DemoTourStep(
        target="#mapping-panel",
        title="4 · Mapping review",
        body="Each requirement points at a real field. Confidence never replaces schema evidence.",
    ),
    DemoTourStep(
        target="#validation-panel",
        title="5 · Validation",
        body="Structural, semantic and logical checks pass. Compatibility is reported as not tested.",
    ),
    DemoTourStep(
        target="#preview-panel",
        title="6 · Preview",
        body="Hover any value to see the exact schema field behind it.",
    ),
    DemoTourStep(
        target="#artifacts-panel",
        title="7 · Download",
        body="DOCX, plan, mapping and validation report — the document plus its evidence.",
    ),
]


@router.get("/examples", response_model=list[DemoCase])
def list_examples() -> list[DemoCase]:
    return [DemoCase(**case) for case in _manifest()["cases"]]


@router.post("/sessions", response_model=DemoResponse)
async def create_session(
    request: DemoRequest,
    store: Store = Depends(get_store),
    service: TemplateService = Depends(get_service),
) -> DemoResponse:
    import time

    started = time.perf_counter()
    manifest = _manifest()
    case = next((item for item in manifest["cases"] if item["id"] == request.case_id), None)
    if case is None:
        raise NotFoundError(
            "Unknown demo case",
            details={"case_id": request.case_id, "available": [c["id"] for c in manifest["cases"]]},
        )

    payload = (DEMO_DIR / case["package"]).read_bytes()
    parsed = parse_ddsp(payload, case["package"], limits=get_settings().limits)
    schema = parsed.schema
    source = store.create_source(
        filename=case["package"],
        schema_id=schema.schema_id,
        schema=schema.model_dump(mode="json"),
        sample=parsed.sample_data,
        entry_names=list(parsed.entry_names),
    )

    job_id = store.create_job("demo", {"case_id": request.case_id})
    outcome, report = await service.plan(
        schema,
        case["prompt"],
        provider="mock",
        design_style="modern",
        language="en",
    )
    if case.get("defect"):
        outcome = outcome.model_copy(update={"document": _inject_layout_defect(outcome.document)})

    template_id, _ = store.create_template(source.id)
    version = store.add_version(
        template_id,
        ir=outcome.document.model_dump(mode="json"),
        mapping=outcome.mapping.model_dump(mode="json"),
        validation=report.model_dump(mode="json"),
        provider="mock",
        model="mock-planner-v1",
    )

    from docentric_copilot.planner import analyze_quality

    quality = analyze_quality(outcome.document, schema, sample_data=parsed.sample_data)
    preview = await run_in_threadpool(
        service.preview, outcome.document, schema, sample_data=parsed.sample_data
    )
    compiled = await run_in_threadpool(
        service.compile,
        outcome.document,
        schema,
        sample_data=parsed.sample_data,
        options=CompileOptions(document_name=f"{case['id']}.docx"),
    )
    package_report = await run_in_threadpool(
        service.validate,
        outcome.document,
        schema,
        sample_data=parsed.sample_data,
        package=compiled.content,
    )

    stem = f"{template_id}-v{version}"
    artifacts = publish_ir_bundle(
        store,
        job_id=job_id,
        template_id=stem,
        document=outcome.document,
        mapping=outcome.mapping.model_dump(mode="json"),
        report_html=render_report_html(package_report),
        report_json=package_report.model_dump(mode="json"),
        preview_html=preview.html,
    )
    docx_artifact = publish(
        store,
        kind="docx",
        filename=f"{case['id']}.docx",
        payload=compiled.content,
        media_type=MEDIA_TYPES["docx"],
        job_id=job_id,
    )
    artifacts.insert(0, docx_artifact)

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    store.finish_job(
        job_id,
        {
            "source_id": source.id,
            "template_id": template_id,
            "version": version,
            "ir_digest": ir_digest(outcome.document),
            "elapsed_ms": elapsed_ms,
        },
    )

    return DemoResponse(
        case=DemoCase(**case),
        source_id=source.id,
        schema_id=schema.schema_id,
        sections=schema.section_names,
        stats=schema.stats().model_dump(mode="json"),
        diagnostics=[item.model_dump(mode="json") for item in schema.diagnostics],
        template_id=template_id,
        version=version,
        ir=outcome.document.model_dump(mode="json"),
        ir_digest=ir_digest(outcome.document),
        mapping=outcome.mapping.model_dump(mode="json"),
        report=package_report.model_dump(mode="json"),
        validation=package_report.statuses(),
        preview_html=preview.html,
        quality=quality.model_dump(mode="json"),
        docx_artifact_id=docx_artifact.id,
        artifacts=artifacts,
        tour=DEMO_TOUR,
        elapsed_ms=elapsed_ms,
    )


def _inject_layout_defect(document):
    """Widen the item table so the quality dashboard has something to report."""
    from docentric_copilot.template_ir import Table

    def widen(blocks):
        result = []
        for block in blocks:
            if isinstance(block, Table) and block.columns:
                block = block.model_copy(
                    update={
                        "columns": [
                            column.model_copy(
                                update={
                                    "width_mm": min(
                                        200.0, round((column.width_mm or 30.0) * 2.2, 1)
                                    )
                                }
                            )
                            for column in block.columns
                        ]
                    }
                )
            result.append(block)
        return result

    sections = [
        section.model_copy(update={"body": widen(list(section.body))})
        for section in document.sections
    ]
    return document.model_copy(update={"sections": sections})
