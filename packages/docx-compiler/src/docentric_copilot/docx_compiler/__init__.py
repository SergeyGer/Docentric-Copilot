"""Deterministic DOCX compilation (FR-05)."""

from __future__ import annotations

from .context import SampleContext
from .expression import evaluate
from .formatting import format_value
from .generic import CompilationResult, CompileOptions, DocentricAXCompiler, GenericDocxCompiler
from .package import DocxPackageInfo, inspect_package, normalize_package
from .registry import CompilerCapability, capabilities, compile_document, get_compiler

__all__ = [
    "CompilationResult",
    "CompileOptions",
    "CompilerCapability",
    "DocentricAXCompiler",
    "DocxPackageInfo",
    "GenericDocxCompiler",
    "SampleContext",
    "capabilities",
    "compile_document",
    "evaluate",
    "format_value",
    "get_compiler",
    "inspect_package",
    "normalize_package",
]
