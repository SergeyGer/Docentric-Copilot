"""Docentric Copilot — schema-aware AI template engineering.

This package is the shared namespace for every layer of the system:

* :mod:`docentric_copilot.ddsp_parser` — safe DDSP ingestion and schema discovery
* :mod:`docentric_copilot.schema_resolver` — path resolution and semantic mapping
* :mod:`docentric_copilot.template_ir` — the versioned template intermediate representation
* :mod:`docentric_copilot.template_validator` — V1-V5 validation engine
* :mod:`docentric_copilot.docx_compiler` — deterministic DOCX compilation
* :mod:`docentric_copilot.llm` — provider-independent structured generation gateway
* :mod:`docentric_copilot.planner` — AI template planning on top of the gateway
* :mod:`docentric_copilot.preview` — independent HTML preview renderer
* :mod:`docentric_copilot.api` — FastAPI application
* :mod:`docentric_copilot.cli` — command line interface
"""

from __future__ import annotations

__version__ = "0.2.0"

#: Version of the Template IR contract produced by this build.
IR_VERSION = "1.0"

#: Version of the compiler implementation. Changes invalidate golden files.
COMPILER_VERSION = "0.2.0"

__all__ = ["COMPILER_VERSION", "IR_VERSION", "__version__"]
