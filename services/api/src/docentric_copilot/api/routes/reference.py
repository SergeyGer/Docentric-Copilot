"""Read-only reference inspection endpoint (v0.6 REF-00 / REF-02).

The endpoint accepts either an uploaded ``.docx``/``.zip``/``.axpp`` file or a
path confined to a configured corpus root. It never writes the template, never
executes macros and applies the same size limits as source uploads.
"""

from __future__ import annotations

from pathlib import Path

from docentric_copilot.api.deps import get_settings
from docentric_copilot.config import Settings
from docentric_copilot.errors import (
    InvalidInputError,
    NotFoundError,
    SecurityViolationError,
    UnsupportedInputError,
)
from docentric_copilot.reference import (
    ReferenceLimits,
    ReferenceReport,
    inspect_reference,
    inspect_reference_bytes,
)
from fastapi import APIRouter, Depends, File, Query, UploadFile

router = APIRouter(prefix="/reference", tags=["reference"])

_ALLOWED_INPUTS = (".docx", ".zip", ".axpp")
_ALLOWED_SCHEMAS = (".ddsp", ".xml")


def _resolve_corpus_path(raw: str, settings: Settings) -> Path:
    if not raw.strip():
        raise InvalidInputError("A non-empty corpus path is required")
    roots = [root.expanduser() for root in settings.reference_corpus_roots]
    if not roots:
        raise SecurityViolationError(
            "No reference corpus root is configured",
            code="reference_path_forbidden",
        )
    requested = Path(raw)
    if requested.is_absolute():
        resolved = requested.resolve(strict=False)
        for root in roots:
            root_resolved = root.resolve(strict=False)
            if resolved.is_relative_to(root_resolved):
                if not resolved.exists():
                    raise NotFoundError(
                        "Reference path does not exist",
                        code="reference_path_not_found",
                    )
                return resolved
        raise SecurityViolationError(
            "Reference path is outside the allowed corpus roots",
            code="reference_path_forbidden",
        )
    for root in roots:
        root_resolved = root.resolve(strict=False)
        candidate = (root / requested).resolve(strict=False)
        if not candidate.is_relative_to(root_resolved):
            raise SecurityViolationError(
                "Reference path is outside the allowed corpus roots",
                code="reference_path_forbidden",
            )
        if candidate.exists():
            return candidate
    raise NotFoundError(
        "Reference path does not exist inside any allowed corpus root",
        code="reference_path_not_found",
    )


async def _read_upload(file: UploadFile, *, limit: int, allowed: tuple[str, ...]) -> bytes:
    filename = file.filename or ""
    if not filename.lower().endswith(allowed):
        raise UnsupportedInputError(
            "Unsupported file extension",
            code="input_unsupported",
            details={"filename": filename, "allowed": list(allowed)},
        )
    payload = await file.read(limit + 1)
    if len(payload) > limit:
        raise UnsupportedInputError(
            "Uploaded file exceeds the configured maximum size",
            code="reference_input_too_large",
            details={"max_bytes": limit},
        )
    return payload


@router.post("/inspect", response_model=ReferenceReport)
async def inspect_reference_endpoint(
    file: UploadFile | None = File(
        default=None,
        description="Reference DOCX, ZIP or AXPP package",
    ),
    path: str | None = Query(
        default=None,
        max_length=1024,
        description="Path inside a configured reference corpus root",
    ),
    ddsp_file: UploadFile | None = File(
        default=None,
        alias="ddsp",
        description="Optional matching DDSP XML schema for path validation",
    ),
    max_depth: int = Query(
        default=0,
        ge=0,
        le=3,
        description=(
            "Nested archive depth. Default 0 keeps public uploads non-recursive; "
            "the root container is still enumerated."
        ),
    ),
    settings: Settings = Depends(get_settings),
) -> ReferenceReport:
    """Inspect a reference template without executing or writing it."""
    if file is not None and path is not None:
        raise InvalidInputError("Provide either an uploaded file or a corpus path, not both")
    if file is None and path is None:
        raise InvalidInputError("Provide a template file or a corpus path")
    limits = ReferenceLimits.from_limits(settings.limits, max_depth=max_depth)
    if file is not None:
        payload = await _read_upload(
            file, limit=settings.limits.max_ddsp_bytes, allowed=_ALLOWED_INPUTS
        )
        ddsp_data: bytes | None = None
        ddsp_name = "source.ddsp"
        if ddsp_file is not None:
            ddsp_data = await _read_upload(
                ddsp_file, limit=settings.limits.max_ddsp_bytes, allowed=_ALLOWED_SCHEMAS
            )
            ddsp_name = Path(ddsp_file.filename or "source.ddsp").name
        return inspect_reference_bytes(
            payload,
            filename=Path(file.filename or "upload.docx").name,
            limits=limits,
            max_depth=max_depth,
            ddsp_data=ddsp_data,
            ddsp_name=ddsp_name,
        )
    if ddsp_file is not None:
        raise InvalidInputError(
            "A DDSP upload is only supported together with an uploaded template file"
        )
    target = _resolve_corpus_path(path or "", settings)
    return inspect_reference(target, limits=limits, max_depth=max_depth)


__all__ = ["router"]
