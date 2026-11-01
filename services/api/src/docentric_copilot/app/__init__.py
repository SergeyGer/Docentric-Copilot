"""Application layer: use-case orchestration shared by HTTP API and CLI."""

from __future__ import annotations

from .service import RevisionResult, TemplateService

__all__ = ["RevisionResult", "TemplateService"]
