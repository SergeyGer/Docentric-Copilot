"""FastAPI application factory.

The application layer composes the deterministic core; the HTTP layer only
validates transport concerns (sizes, media types, error envelopes).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from docentric_copilot import __version__
from docentric_copilot.app.service import TemplateService
from docentric_copilot.config import Settings, get_settings
from docentric_copilot.errors import CopilotError
from docentric_copilot.llm.gateway import LLMGateway
from docentric_copilot.logging import configure_logging, get_logger
from docentric_copilot.storage import Store

logger = get_logger(__name__)


def _error_response(exc: CopilotError) -> JSONResponse:
    return JSONResponse(status_code=exc.http_status, content=exc.to_dict())


def create_app(
    settings: Settings | None = None,
    *,
    store: Store | None = None,
    service: TemplateService | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level, json_output=resolved_settings.log_json)

    resolved_store = store or Store(resolved_settings)
    resolved_service = service or TemplateService(LLMGateway(resolved_settings))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        purged = resolved_store.purge_expired()
        logger.info(
            "api.startup",
            extra={"context": {"settings": resolved_settings.public_view(), "purged": purged}},
        )
        try:
            yield
        finally:
            await resolved_service.aclose()
            resolved_store.close()

    app = FastAPI(
        title="Docentric Copilot API",
        version=__version__,
        description=(
            "Schema-aware prompt-to-template engine. Generates validated Template IR "
            "and deterministic generic DOCX documents from a DDSP data source. "
            "Docentric AX compatibility is unverified and reported as `not_tested`."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.state.settings = resolved_settings
    app.state.store = resolved_store
    app.state.service = resolved_service

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
        expose_headers=["Content-Disposition", "X-Artifact-Digest"],
    )

    @app.exception_handler(CopilotError)
    async def copilot_error_handler(_request: Request, exc: CopilotError) -> JSONResponse:
        logger.info(
            "api.error",
            extra={"context": {"code": exc.code, "status": exc.http_status}},
        )
        return _error_response(exc)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors: list[dict[str, Any]] = [
            {
                "location": ".".join(str(part) for part in error.get("loc", ())),
                "message": error.get("msg", "invalid value"),
                "type": error.get("type", "value_error"),
            }
            for error in exc.errors()[:20]
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "input_invalid",
                    "message": "Request body failed validation",
                    "details": {"errors": errors},
                }
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("api.unhandled", extra={"context": {"error": type(exc).__name__}})
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected error occurred",
                }
            },
        )

    from .routes import sources, system, templates

    api_prefix = "/api/v1"
    app.include_router(sources.router, prefix=api_prefix)
    app.include_router(templates.router, prefix=api_prefix)
    app.include_router(system.router, prefix=api_prefix)

    @app.get("/", tags=["system"])
    def root() -> dict[str, Any]:
        return {
            "name": "Docentric Copilot API",
            "version": __version__,
            "docs": "/docs",
            "openapi": "/openapi.json",
            "api": api_prefix,
            "docentric_ax_compatibility": "not_tested",
        }

    @app.get("/health", tags=["system"])
    def health_alias() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


__all__ = ["create_app"]
