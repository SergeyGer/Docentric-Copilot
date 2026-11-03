"""API request and response models (OpenAPI contract)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from docentric_copilot.template_ir import CompileTarget, DesignStyle
from docentric_copilot.template_validator import ValidationReport
from pydantic import BaseModel, ConfigDict, Field


class PlanOptionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: str = Field(default="en", pattern=r"^[a-z]{2}(-[A-Z]{2})?$")
    strict_validation: bool = True
    max_generation_cost_usd: float = Field(default=0.5, ge=0.0, le=50.0)
    max_repair_attempts: int = Field(default=1, ge=0, le=2)


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=4, max_length=60)
    prompt: str = Field(min_length=3, max_length=5_000)
    provider: str = Field(default="mock", min_length=2, max_length=40)
    model: str | None = Field(default=None, max_length=120)
    #: ``explicit`` keeps the historical behaviour (the caller chooses the
    #: provider). ``auto`` classifies the brief, routes against the configured
    #: providers, and returns an execution trace.
    routing: Literal["explicit", "auto"] = "explicit"
    design_style: DesignStyle = DesignStyle.MODERN
    target: CompileTarget = CompileTarget.GENERIC_DOCX
    options: PlanOptionsRequest = Field(default_factory=PlanOptionsRequest)


class CompileOptionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    render_mode: Literal["auto", "sample", "placeholder"] = "auto"
    include_compatibility_stamp: bool = False
    document_name: str = Field(default="document.docx", max_length=120)
    use_sample_data: bool = True


class CompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=4, max_length=60)
    template_id: str | None = Field(default=None, max_length=60)
    version: int | None = Field(default=None, ge=1)
    ir: dict[str, Any] | None = None
    target: CompileTarget = CompileTarget.GENERIC_DOCX
    options: CompileOptionsRequest = Field(default_factory=CompileOptionsRequest)


class ValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=4, max_length=60)
    template_id: str | None = Field(default=None, max_length=60)
    version: int | None = Field(default=None, ge=1)
    ir: dict[str, Any] | None = None
    target: CompileTarget = CompileTarget.GENERIC_DOCX


class RevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=4, max_length=60)
    template_id: str = Field(min_length=4, max_length=60)
    version: int | None = Field(default=None, ge=1)
    instruction: str = Field(min_length=3, max_length=2_000)
    provider: str = Field(default="mock", min_length=2, max_length=40)
    model: str | None = Field(default=None, max_length=120)


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=4, max_length=60)
    template_id: str | None = Field(default=None, max_length=60)
    version: int | None = Field(default=None, ge=1)
    ir: dict[str, Any] | None = None


class ArtifactView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    filename: str
    media_type: str
    size_bytes: int
    digest: str
    url: str
    expires_at: float


class SourceView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    filename: str
    schema_id: str
    sections: list[str]
    stats: dict[str, Any]
    sample_data_available: bool
    diagnostics: list[dict[str, Any]]
    entry_names: list[str]


class SchemaView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    normalized_schema: dict[str, Any]
    stats: dict[str, Any]
    diagnostics: list[dict[str, Any]]


class RoutingExecutionTrace(BaseModel):
    """What auto-routing recommended versus what actually ran."""

    model_config = ConfigDict(extra="forbid")

    decision: dict[str, Any]
    actual_provider: str
    actual_model: str | None = None
    #: True when the router could not use its preferred tier (including the
    #: explicit deterministic-baseline fallback). It is never an error by
    #: itself, but it is always visible.
    fallback: bool = False
    #: True only when the recommended provider equals the executed provider.
    match: bool = False
    run_id: str
    started_at: datetime
    finished_at: datetime
    usage: dict[str, Any] | None = None


class PlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: str
    template_id: str
    version: int
    ir_digest: str
    ir: dict[str, Any]
    mapping: dict[str, Any]
    report: ValidationReport
    validation: dict[str, str]
    warnings: list[str] = Field(default_factory=list)
    removed_bindings: list[dict[str, Any]] = Field(default_factory=list)
    generation: dict[str, Any] | None = None
    routing: RoutingExecutionTrace | None = None
    artifacts: list[ArtifactView] = Field(default_factory=list)


class CompileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: str
    artifact_id: str
    ir_digest: str
    validation: dict[str, str]
    report: ValidationReport
    warnings: list[str] = Field(default_factory=list)
    stats: dict[str, int] = Field(default_factory=dict)
    artifacts: list[ArtifactView] = Field(default_factory=list)


class ValidateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    validation: dict[str, str]
    overall: str
    report: ValidationReport


class RevisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: str
    template_id: str
    version: int
    ir_digest: str
    ir: dict[str, Any]
    mapping: dict[str, Any]
    report: ValidationReport
    validation: dict[str, str]
    change_summary: dict[str, Any]
    changes: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    artifacts: list[ArtifactView] = Field(default_factory=list)


class JobView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    kind: str
    status: str
    duration_ms: int | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class ProviderView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    configured: bool
    default_model: str | None = None
    models: list[str] = Field(default_factory=list)


class HealthView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    version: str
    environment: str
    docentric_ax_adapter_enabled: bool


class CapabilitiesView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    compilers: list[dict[str, Any]]
    features: dict[str, bool]
    limits: dict[str, int]


__all__ = [
    "ArtifactView",
    "CapabilitiesView",
    "CompileOptionsRequest",
    "CompileRequest",
    "CompileResponse",
    "HealthView",
    "JobView",
    "PlanOptionsRequest",
    "PlanRequest",
    "PlanResponse",
    "PreviewRequest",
    "ProviderView",
    "RevisionRequest",
    "RevisionResponse",
    "RoutingExecutionTrace",
    "SchemaView",
    "SourceView",
    "ValidateRequest",
    "ValidateResponse",
]
