"""Dependency wiring for the FastAPI application."""

from __future__ import annotations

from docentric_copilot.app.service import TemplateService
from docentric_copilot.config import Settings
from docentric_copilot.storage import Store
from fastapi import Request


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_store(request: Request) -> Store:
    return request.app.state.store


def get_service(request: Request) -> TemplateService:
    return request.app.state.service


__all__ = ["get_service", "get_settings", "get_store"]
