"""Application orchestration shared by the HTTP API and the CLI.

Both interfaces call exactly this service, which is the practical meaning of
"one domain core" in the SRS (FR-09, FR-10).
"""

from __future__ import annotations

from dataclasses import dataclass

from docentric_copilot.config import Settings, get_settings
from docentric_copilot.ddsp_parser.models import NormalizedSchema
from docentric_copilot.docx_compiler import CompilationResult, CompileOptions
from docentric_copilot.docx_compiler import compile_document as compile_with_registry
from docentric_copilot.llm.gateway import LLMGateway
from docentric_copilot.planner import (
    COMPACT_TEMPLATE_NAME,
    PlanOptions,
    PlanOutcome,
    TemplatePlanner,
)
from docentric_copilot.planner.revisions import diff_documents, summarize_changes
from docentric_copilot.preview import PreviewOptions, PreviewResult, render_preview
from docentric_copilot.template_ir import Document
from docentric_copilot.template_validator import ValidationEngine, ValidationReport


@dataclass(frozen=True)
class RevisionResult:
    outcome: PlanOutcome
    changes: list
    summary: dict


class TemplateService:
    """Use-case level facade: plan, validate, compile, revise, preview."""

    def __init__(
        self,
        gateway: LLMGateway | None = None,
        validator: ValidationEngine | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._gateway = gateway or LLMGateway(self._settings)
        self._planner = TemplatePlanner(self._gateway)
        self._validator = validator or ValidationEngine(
            max_blocks=self._settings.limits.max_ir_blocks,
            max_depth=self._settings.limits.max_ir_depth,
            max_text_length=self._settings.limits.max_text_length,
        )

    @property
    def gateway(self) -> LLMGateway:
        return self._gateway

    @property
    def planner(self) -> TemplatePlanner:
        return self._planner

    # ------------------------------------------------------------------- plan
    async def plan(
        self,
        schema: NormalizedSchema,
        prompt: str,
        *,
        provider: str = "mock",
        model: str | None = None,
        design_style: str = "modern",
        language: str = "en",
        target: str = "generic-docx",
        max_repair_attempts: int = 1,
        max_generation_cost_usd: float | None = None,
        compact_ir: bool | None = None,
    ) -> tuple[PlanOutcome, ValidationReport]:
        # None means "auto": Gemini 3.x needs the compact wire format to fit a
        # full plan in its output budget. An explicit False always wins.
        resolved_compact = (provider == "gemini") if compact_ir is None else compact_ir
        options = PlanOptions(
            language=language,
            design_style=design_style,  # type: ignore[arg-type]
            target=target,  # type: ignore[arg-type]
            max_repair_attempts=max_repair_attempts,
            compact_ir=resolved_compact,
        )
        outcome = await self._planner.plan(
            schema,
            prompt,
            provider=provider,
            model=model,
            options=options,
            budget_usd=max_generation_cost_usd,
        )
        report = self._validator.validate(outcome.document, schema)
        return outcome, report

    # --------------------------------------------------------------- validate
    def validate(
        self,
        document: Document,
        schema: NormalizedSchema,
        *,
        sample_data: dict | None = None,
        package: bytes | None = None,
    ) -> ValidationReport:
        return self._validator.validate(document, schema, sample_data=sample_data, package=package)

    # ---------------------------------------------------------------- compile
    def compile(
        self,
        document: Document,
        schema: NormalizedSchema,
        *,
        sample_data: dict | None = None,
        options: CompileOptions | None = None,
    ) -> CompilationResult:
        return compile_with_registry(document, schema, options, sample_data=sample_data)

    # ----------------------------------------------------------------- revise
    async def revise(
        self,
        document: Document,
        schema: NormalizedSchema,
        instruction: str,
        *,
        provider: str = "mock",
        model: str | None = None,
        design_style: str = "modern",
        language: str = "en",
        target: str = "generic-docx",
        compact_ir: bool | None = None,
    ) -> RevisionResult:
        resolved_compact = compact_ir
        if resolved_compact is None:
            resolved_compact = (
                provider == "gemini" or document.metadata.template_name == COMPACT_TEMPLATE_NAME
            )
        options = PlanOptions(
            language=language,
            design_style=design_style,  # type: ignore[arg-type]
            target=target,  # type: ignore[arg-type]
            compact_ir=resolved_compact,
        )
        outcome = await self._planner.revise(
            schema, document, instruction, provider=provider, model=model, options=options
        )
        changes = diff_documents(document, outcome.document)
        return RevisionResult(
            outcome=outcome.model_copy(update={"changed": changes}),
            changes=changes,
            summary=summarize_changes(changes),
        )

    # ---------------------------------------------------------------- preview
    def preview(
        self,
        document: Document,
        schema: NormalizedSchema,
        *,
        sample_data: dict | None = None,
        options: PreviewOptions | None = None,
    ) -> PreviewResult:
        return render_preview(document, schema, sample_data=sample_data, options=options)

    async def aclose(self) -> None:
        await self._gateway.aclose()


__all__ = ["RevisionResult", "TemplateService"]
