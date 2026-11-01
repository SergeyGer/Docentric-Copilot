"""HTML rendering of validation reports (FR-07)."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import ValidationReport

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_environment = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(enabled_extensions=("html", "j2"), default=True),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_report_html(report: ValidationReport) -> str:
    """Render a self-contained HTML report (no external assets)."""
    template = _environment.get_template("report.html.j2")
    return template.render(report=report, counts=report.counts())


def render_report_json(report: ValidationReport) -> str:
    return report.model_dump_json(indent=2, exclude_none=False)


__all__ = ["render_report_html", "render_report_json"]
