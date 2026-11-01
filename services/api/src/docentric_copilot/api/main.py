"""ASGI entry point: ``uvicorn docentric_copilot.api.main:app``."""

from __future__ import annotations

from .app import create_app

app = create_app()

__all__ = ["app"]
