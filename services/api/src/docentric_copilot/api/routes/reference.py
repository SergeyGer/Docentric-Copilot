"""Read-only reference inspection endpoint (v0.6 REF-00 / REF-02).

The endpoint accepts either an uploaded ``.docx``/``.zip``/``.axpp`` file or a
path confined to a configured corpus root. It never writes the template, never
executes macros and applies the same size limits as source uploads.
"""

from __future__ import annotations

import posixpath
from pathlib import Path, PurePosixPath

from docentric_copilot.api.deps import get_settings
from docentric_copilot.config import Settings
from docentric_copilot.errors import (
    InvalidInputError,
    NotFoundError,
    SecurityViolationError,
    UnsupportedInputError,
)
from docentric_copilot.reference import (
    D365BindingReport,
    ReferenceDiff,
    ReferenceGraph,
    ReferenceLimits,
    ReferenceReport,
    analyze_d365_bytes,
    analyze_d365_path,
    build_reference_diff,
    build_reference_graph,
    inspect_reference,
    inspect_reference_bundle,
    inspect_reference_bytes,
    inspect_reference_bytes_bundle,
)
from fastapi import APIRouter, Depends, File, Query, UploadFile

router = APIRouter(prefix="/reference", tags=["reference"])

_ALLOWED_INPUTS = (".docx", ".zip", ".axpp")
_ALLOWED_SCHEMAS = (".ddsp", ".xml")


def _corpus_index(settings: Settings) -> dict[str, Path]:
    """Map every file under the configured roots to its resolved path once.

    The request supplies a *key* looked up in this index; no path is constructed
    from user input, so traversal and existence-oracle patterns cannot occur.
    """
    index: dict[str, Path] = {}
    for root in settings.reference_corpus_roots:
        root_path = root.expanduser().resolve(strict=False)
        if not root_path.is_dir():
            continue
        for candidate in sorted(root_path.rglob("*")):
            if candidate.is_file():
                index.setdefault(candidate.relative_to(root_path).as_posix(), candidate.resolve())
    return index


def _resolve_corpus_path(raw: str, settings: Settings) -> Path:
    if not raw.strip():
        raise InvalidInputError("A non-empty corpus path is required")
    if not settings.reference_corpus_roots:
        raise SecurityViolationError(
            "No reference corpus root is configured",
            code="reference_path_forbidden",
        )
    requested = posixpath.normpath(raw.strip().replace("\\", "/"))
    parts = PurePosixPath(requested).parts
    if not parts or any(part in {"..", "."} for part in parts):
        raise SecurityViolationError(
            "Reference path is outside the allowed corpus roots",
            code="reference_path_forbidden",
        )
    if requested.startswith("/"):
        relative = None
        for root in settings.reference_corpus_roots:
            root_string = str(root.expanduser().resolve(strict=False))
            if requested == root_string or requested.startswith(root_string.rstrip("/") + "/"):
                relative = requested[len(root_string) :].lstrip("/")
                break
        if relative is None:
            raise SecurityViolationError(
                "Reference path is outside the allowed corpus roots",
                code="reference_path_forbidden",
            )
        requested = relative
    resolved = _corpus_index(settings).get(PurePosixPath(requested).as_posix())
    if resolved is None:
        raise NotFoundError(
            "Reference path does not exist inside any allowed corpus root",
            code="reference_path_not_found",
        )
    return resolved


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


@router.post("/graph", response_model=ReferenceGraph)
async def graph_reference_endpoint(
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
        description="Optional matching DDSP XML schema for binding resolution",
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
) -> ReferenceGraph:
    """Build a read-only ReferenceGraph; nothing is executed or written."""
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
        bundle = inspect_reference_bytes_bundle(
            payload,
            filename=Path(file.filename or "upload.docx").name,
            limits=limits,
            max_depth=max_depth,
            ddsp_data=ddsp_data,
            ddsp_name=ddsp_name,
        )
        return build_reference_graph(bundle.report, bundle.schemas)
    if ddsp_file is not None:
        raise InvalidInputError(
            "A DDSP upload is only supported together with an uploaded template file"
        )
    target = _resolve_corpus_path(path or "", settings)
    bundle = inspect_reference_bundle(target, limits=limits, max_depth=max_depth)
    return build_reference_graph(bundle.report, bundle.schemas)


@router.post("/diff", response_model=ReferenceDiff)
async def diff_reference_endpoint(
    left: UploadFile | None = File(
        default=None,
        description="Left reference DOCX, ZIP or AXPP package",
    ),
    right: UploadFile | None = File(
        default=None,
        description="Right reference DOCX, ZIP or AXPP package",
    ),
    left_path: str | None = Query(
        default=None,
        max_length=1024,
        description="Left path inside a configured reference corpus root",
    ),
    right_path: str | None = Query(
        default=None,
        max_length=1024,
        description="Right path inside a configured reference corpus root",
    ),
    ddsp_file: UploadFile | None = File(
        default=None,
        alias="ddsp",
        description="Optional DDSP schema applied to both uploaded templates",
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
) -> ReferenceDiff:
    """Compare two references read-only (REF-04); nothing is executed or written."""
    uploaded = left is not None or right is not None
    pathed = left_path is not None or right_path is not None
    if uploaded and pathed:
        raise InvalidInputError("Provide either two uploaded files or two corpus paths, not both")
    if not uploaded and not pathed:
        raise InvalidInputError("Provide two template files or two corpus paths")
    if uploaded and (left is None or right is None):
        raise InvalidInputError("Both left and right files are required")
    if pathed and (left_path is None or right_path is None):
        raise InvalidInputError("Both left_path and right_path are required")
    limits = ReferenceLimits.from_limits(settings.limits, max_depth=max_depth)
    if pathed:
        if ddsp_file is not None:
            raise InvalidInputError(
                "A DDSP upload is only supported together with uploaded templates"
            )
        left_target = _resolve_corpus_path(left_path or "", settings)
        right_target = _resolve_corpus_path(right_path or "", settings)
        return build_reference_diff(
            left_target,
            right_target,
            limits=limits,
            max_depth=max_depth,
        )
    assert left is not None and right is not None
    left_payload = await _read_upload(
        left, limit=settings.limits.max_ddsp_bytes, allowed=_ALLOWED_INPUTS
    )
    right_payload = await _read_upload(
        right, limit=settings.limits.max_ddsp_bytes, allowed=_ALLOWED_INPUTS
    )
    ddsp_data: bytes | None = None
    ddsp_name = "source.ddsp"
    if ddsp_file is not None:
        ddsp_data = await _read_upload(
            ddsp_file, limit=settings.limits.max_ddsp_bytes, allowed=_ALLOWED_SCHEMAS
        )
        ddsp_name = Path(ddsp_file.filename or "source.ddsp").name
    left_bundle = inspect_reference_bytes_bundle(
        left_payload,
        filename=Path(left.filename or "left.docx").name,
        limits=limits,
        max_depth=max_depth,
        ddsp_data=ddsp_data,
        ddsp_name=ddsp_name,
    )
    right_bundle = inspect_reference_bytes_bundle(
        right_payload,
        filename=Path(right.filename or "right.docx").name,
        limits=limits,
        max_depth=max_depth,
        ddsp_data=ddsp_data,
        ddsp_name=ddsp_name,
    )
    return build_reference_diff(left_bundle, right_bundle)


@router.post("/d365", response_model=D365BindingReport)
async def d365_reference_endpoint(
    file: UploadFile | None = File(
        default=None,
        description="D365 DOCX or single-template AXPP/ZIP package",
    ),
    path: str | None = Query(
        default=None,
        max_length=1024,
        description="Path inside a configured reference corpus root",
    ),
    ddsp_file: UploadFile | None = File(
        default=None,
        alias="ddsp",
        description="Optional fallback DDSP schema for documents without embedded schema",
    ),
    settings: Settings = Depends(get_settings),
) -> D365BindingReport:
    """Extract the embedded D365 schema and resolve bindings (read-only)."""
    if file is not None and path is not None:
        raise InvalidInputError("Provide either an uploaded file or a corpus path, not both")
    if file is None and path is None:
        raise InvalidInputError("Provide a template file or a corpus path")
    limits = ReferenceLimits.from_limits(settings.limits)
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
        return analyze_d365_bytes(
            payload,
            filename=Path(file.filename or "upload.docx").name,
            limits=limits,
            ddsp_data=ddsp_data,
            ddsp_name=ddsp_name,
        )
    if ddsp_file is not None:
        raise InvalidInputError(
            "A DDSP upload is only supported together with an uploaded template file"
        )
    target = _resolve_corpus_path(path or "", settings)
    return analyze_d365_path(target, limits=limits)


__all__ = ["router"]
