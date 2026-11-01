"""Safe DDSP ingestion and schema discovery (FR-01)."""

from __future__ import annotations

from .diagnostics import Diagnostic, DiagnosticCode, Severity
from .models import NormalizedSchema, SchemaAttribute, SchemaNode, SchemaSection, SchemaStats
from .parser import ParsedSource, parse_ddsp, parse_xml_string
from .safety import ContainerEntry, classify_container, parse_xml, read_container

__all__ = [
    "ContainerEntry",
    "Diagnostic",
    "DiagnosticCode",
    "NormalizedSchema",
    "ParsedSource",
    "SchemaAttribute",
    "SchemaNode",
    "SchemaSection",
    "SchemaStats",
    "Severity",
    "classify_container",
    "parse_ddsp",
    "parse_xml",
    "parse_xml_string",
    "read_container",
]
