"""Read-only reference inspection endpoint (v0.6 REF-00 / REF-02).

The endpoint accepts either an uploaded ``.docx``/``.zip``/``.axpp`` file or a
path confined to a configured corpus root. It never writes the template, never
executes macros and applies the same size limits as source uploads.
"""

from __future__ import annotations

import posixpath
from pathlib import Path, PurePosixPath

from docentric_copilot.api.deps import get_settings, get_store
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
    ReferenceIRImport,
    ReferenceLimits,
    ReferenceReport,
    ReferenceReportKind,
    StoredReferenceReport,
    analyze_d365_bytes,
    analyze_d365_path,
    build_reference_diff,
    build_reference_graph,
    inspect_reference,
    inspect_reference_bundle,
    inspect_reference_bytes,
    inspect_reference_bytes_bundle,
    project_to_template_ir,
    render_stored_report_html,
)
from docentric_copilot.storage import ReferenceReportRecord, Store
from fastapi import APIRouter, Depends, File, Query, Response, UploadFile

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
        return build_reference_graph(bundle.report, bundle.schemas, documents=bundle.payloads)
    if ddsp_file is not None:
        raise InvalidInputError(
            "A DDSP upload is only supported together with an uploaded template file"
        )
    target = _resolve_corpus_path(path or "", settings)
    bundle = inspect_reference_bundle(target, limits=limits, max_depth=max_depth)
    return build_reference_graph(bundle.report, bundle.schemas, documents=bundle.payloads)


@router.post("/import-ir", response_model=ReferenceIRImport)
async def import_reference_ir_endpoint(
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
    allow_unsupported: bool = Query(
        default=False,
        description=(
            "Best-effort mode: keep the supported subset and list unsupported or unresolved "
            "constructs in skipped[]. Strict mode (default) refuses the whole import."
        ),
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
) -> ReferenceIRImport:
    """Project resolved reference constructs into Generic Template IR (v0.11 P1).

    This produces a generic DOCX target only; it is not a Docentric AX template
    and makes no runtime compatibility claim.
    """
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
    else:
        if ddsp_file is not None:
            raise InvalidInputError(
                "A DDSP upload is only supported together with an uploaded template file"
            )
        target = _resolve_corpus_path(path or "", settings)
        bundle = inspect_reference_bundle(target, limits=limits, max_depth=max_depth)
    graph = build_reference_graph(bundle.report, bundle.schemas, documents=bundle.payloads)
    docx_payload = (
        payload
        if file is not None
        else bundle.payloads.get(graph.source_sha256) or next(iter(bundle.payloads.values()), None)
    )
    return project_to_template_ir(
        graph,
        allow_unsupported=allow_unsupported,
        docx_payload=docx_payload,
    )


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


def _stored_envelope(record: ReferenceReportRecord) -> StoredReferenceReport:
    payload = record.payload()
    report_payload = payload.get("report")
    graph_payload = payload.get("graph")
    diff_payload = payload.get("diff")
    return StoredReferenceReport(
        id=record.id,
        kind=ReferenceReportKind(record.kind),
        schema_version=record.schema_version,
        created_at=record.created_at,
        expires_at=record.expires_at,
        source_name=record.source_name,
        source_sha256=record.source_sha256,
        report=ReferenceReport.model_validate(report_payload) if report_payload else None,
        graph=ReferenceGraph.model_validate(graph_payload) if graph_payload else None,
        diff=ReferenceDiff.model_validate(diff_payload) if diff_payload else None,
        warnings=list(record.warnings),
    )


@router.post("/reports", response_model=StoredReferenceReport)
async def persist_reference_report_endpoint(
    file: UploadFile | None = File(
        default=None,
        description="Reference DOCX, ZIP or AXPP package",
    ),
    path: str | None = Query(
        default=None,
        max_length=1024,
        description="Path inside a configured reference corpus root",
    ),
    left: UploadFile | None = File(
        default=None,
        description="Left reference for kind=diff",
    ),
    right: UploadFile | None = File(
        default=None,
        description="Right reference for kind=diff",
    ),
    left_path: str | None = Query(
        default=None,
        max_length=1024,
        description="Left corpus path for kind=diff",
    ),
    right_path: str | None = Query(
        default=None,
        max_length=1024,
        description="Right corpus path for kind=diff",
    ),
    ddsp_file: UploadFile | None = File(
        default=None,
        alias="ddsp",
        description="Optional matching DDSP XML schema for binding resolution",
    ),
    kind: ReferenceReportKind = Query(
        default=ReferenceReportKind.INSPECTION,
        description="Persist an inspection report (+graph), a graph, or a structural diff",
    ),
    max_depth: int = Query(
        default=0,
        ge=0,
        le=3,
        description="Nested archive depth (0 keeps public uploads non-recursive)",
    ),
    settings: Settings = Depends(get_settings),
    store: Store = Depends(get_store),
) -> StoredReferenceReport:
    """Persist a read-only reference inspection/graph/diff with a TTL.

    Only serialized evidence is stored; source template bytes are never written
    to the database or to artifact storage.
    """
    limits = ReferenceLimits.from_limits(settings.limits, max_depth=max_depth)
    if kind is ReferenceReportKind.DIFF:
        uploaded = left is not None or right is not None
        pathed = left_path is not None or right_path is not None
        if uploaded and pathed:
            raise InvalidInputError(
                "Provide either two uploaded files or two corpus paths, not both"
            )
        if not uploaded and not pathed:
            raise InvalidInputError("Provide two template files or two corpus paths")
        if uploaded and (left is None or right is None):
            raise InvalidInputError("Both left and right files are required")
        if pathed and (left_path is None or right_path is None):
            raise InvalidInputError("Both left_path and right_path are required")
        if pathed:
            if ddsp_file is not None:
                raise InvalidInputError(
                    "A DDSP upload is only supported together with uploaded templates"
                )
            diff = build_reference_diff(
                _resolve_corpus_path(left_path or "", settings),
                _resolve_corpus_path(right_path or "", settings),
                limits=limits,
                max_depth=max_depth,
            )
        else:
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
                    ddsp_file,
                    limit=settings.limits.max_ddsp_bytes,
                    allowed=_ALLOWED_SCHEMAS,
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
            diff = build_reference_diff(left_bundle, right_bundle)
        record = store.save_reference_report(
            kind=kind.value,
            schema_version=diff.reference_version,
            source_name=f"{diff.left.source_name} vs {diff.right.source_name}"[:300],
            source_sha256=None,
            payload={"diff": diff.model_dump(mode="json")},
            warnings=[],
        )
        return _stored_envelope(record)

    if left is not None or right is not None or left_path or right_path:
        raise InvalidInputError("left/right inputs are only supported with kind=diff")
    if file is not None and path is not None:
        raise InvalidInputError("Provide either an uploaded file or a corpus path, not both")
    if file is None and path is None:
        raise InvalidInputError("Provide a template file or a corpus path")
    if file is not None:
        payload = await _read_upload(
            file, limit=settings.limits.max_ddsp_bytes, allowed=_ALLOWED_INPUTS
        )
        ddsp_data = None
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
    else:
        if ddsp_file is not None:
            raise InvalidInputError(
                "A DDSP upload is only supported together with an uploaded template file"
            )
        bundle = inspect_reference_bundle(
            _resolve_corpus_path(path or "", settings),
            limits=limits,
            max_depth=max_depth,
        )
    graph = build_reference_graph(bundle.report, bundle.schemas, documents=bundle.payloads)
    report_payload = (
        {"report": bundle.report.model_dump(mode="json")}
        if kind is ReferenceReportKind.INSPECTION
        else {}
    )
    source_name = (
        bundle.report.source_name if kind is ReferenceReportKind.INSPECTION else graph.source_name
    )
    source_sha = (
        bundle.report.source_sha256
        if kind is ReferenceReportKind.INSPECTION
        else graph.source_sha256
    )
    record = store.save_reference_report(
        kind=kind.value,
        schema_version=bundle.report.reference_version,
        source_name=source_name,
        source_sha256=source_sha,
        payload={**report_payload, "graph": graph.model_dump(mode="json")},
        warnings=list(bundle.report.warnings),
    )
    return _stored_envelope(record)


@router.get("/reports/{report_id}", response_model=StoredReferenceReport)
async def get_reference_report_endpoint(
    report_id: str,
    store: Store = Depends(get_store),
) -> StoredReferenceReport:
    """Reopen a persisted reference report by id (404 when missing or expired)."""
    return _stored_envelope(store.get_reference_report(report_id))


@router.delete("/reports/{report_id}", status_code=204)
async def delete_reference_report_endpoint(
    report_id: str,
    store: Store = Depends(get_store),
) -> Response:
    """Delete one persisted reference report and its evidence.

    A second delete, a missing id or an expired id returns 404 with the same
    stable ``reference_report_not_found`` code. Deletion is immediate: GET and
    export after a successful delete are 404.
    """
    if not store.delete_reference_report(report_id):
        raise NotFoundError(
            "Reference report not found",
            code="reference_report_not_found",
            details={"report_id": report_id},
        )
    return Response(status_code=204)


@router.get("/reports/{report_id}/export")
async def export_reference_report_endpoint(
    report_id: str,
    format: str = Query(
        default="json",
        pattern=r"^(json|html)$",
        description="Export the persisted report as JSON or safe HTML",
    ),
    store: Store = Depends(get_store),
) -> Response:
    """Export a persisted report. The HTML export contains no source active content."""
    envelope = _stored_envelope(store.get_reference_report(report_id))
    filename = f"reference-report-{envelope.id}"
    if format == "html":
        return Response(
            content=render_stored_report_html(envelope),
            media_type="text/html; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}.html"',
                "X-Content-Type-Options": "nosniff",
            },
        )
    return Response(
        content=envelope.export_json(),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}.json"',
            "X-Content-Type-Options": "nosniff",
        },
    )


__all__ = ["router"]
