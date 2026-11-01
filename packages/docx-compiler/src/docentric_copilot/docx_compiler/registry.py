"""Compiler registry and capability reporting (FR-05).

The Docentric AX adapter is reported as unavailable until the feasibility gate
documented in ``docs/DOCENTRIC_AX_COMPATIBILITY.md`` is passed. Enabling the
feature flag only changes the explanation, never the outcome: an unverified
compiler must fail closed rather than produce a document that looks compatible.
"""

from __future__ import annotations

from dataclasses import dataclass

from docentric_copilot.config import Settings, get_settings
from docentric_copilot.errors import UnsupportedTargetError
from docentric_copilot.template_ir import CompileTarget

from .generic import CompileOptions, CompilationResult, DocentricAXCompiler, GenericDocxCompiler


@dataclass(frozen=True, slots=True)
class CompilerCapability:
    target: str
    available: bool
    verified: bool
    status: str

    def as_dict(self) -> dict[str, object]:
        return {
            "target": self.target,
            "available": self.available,
            "verified": self.verified,
            "status": self.status,
        }


def capabilities(settings: Settings | None = None) -> list[CompilerCapability]:
    resolved = settings or get_settings()
    ax_status = (
        "blocked: adapter enabled by configuration but compatibility has not been "
        "independently verified"
        if resolved.enable_docentric_ax_adapter
        else "unavailable: Docentric AX compatibility gate not passed"
    )
    return [
        CompilerCapability(
            target=CompileTarget.GENERIC_DOCX.value,
            available=True,
            verified=True,
            status="available: deterministic generic DOCX",
        ),
        CompilerCapability(
            target=CompileTarget.DOCENTRIC_AX.value,
            available=False,
            verified=False,
            status=ax_status,
        ),
    ]


def get_compiler(
    target: str | CompileTarget, settings: Settings | None = None
) -> GenericDocxCompiler | DocentricAXCompiler:
    resolved_target = CompileTarget(target)
    if resolved_target is CompileTarget.GENERIC_DOCX:
        return GenericDocxCompiler()
    if resolved_target is CompileTarget.DOCENTRIC_AX:
        return DocentricAXCompiler()
    raise UnsupportedTargetError(  # pragma: no cover - enum is exhaustive
        f"Unknown compilation target: {resolved_target}",
        details={"target": str(resolved_target)},
    )


def compile_document(
    template,
    schema,
    options: CompileOptions | None = None,
    *,
    sample_data=None,
    settings: Settings | None = None,
) -> CompilationResult:
    compiler = get_compiler(template.target, settings)
    return compiler.compile(template, schema, options, sample_data=sample_data)


__all__ = ["CompilerCapability", "capabilities", "compile_document", "get_compiler"]
