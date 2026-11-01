"""DOCX package helpers: deterministic normalization and structural inspection.

NFR-01 requires that the same IR and compiler version produce a structurally
equivalent (here: byte identical) document. python-docx is deterministic, but a
ZIP container is not: entry order and timestamps must be normalized.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass, field

from docentric_copilot.errors import CompilationFailedError

FIXED_TIMESTAMP = (2024, 1, 1, 0, 0, 0)
_REQUIRED_ENTRIES = ("[Content_Types].xml", "_rels/.rels", "word/document.xml")
_FORBIDDEN_MARKERS = ("vbaproject.bin", "oleobject", "activex")
_MAX_PACKAGE_BYTES = 80 * 1024 * 1024


@dataclass(frozen=True)
class DocxPackageInfo:
    entries: tuple[str, ...]
    has_macros: bool
    has_embedded_objects: bool
    external_relationships: tuple[str, ...]
    size_bytes: int
    sha256: str
    missing_entries: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_valid(self) -> bool:
        return not self.missing_entries and not self.has_macros and not self.has_embedded_objects

    def as_dict(self) -> dict[str, object]:
        return {
            "entries": list(self.entries),
            "has_macros": self.has_macros,
            "has_embedded_objects": self.has_embedded_objects,
            "external_relationships": list(self.external_relationships),
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "missing_entries": list(self.missing_entries),
        }


def normalize_package(data: bytes, *, compresslevel: int = 9) -> bytes:
    """Rewrite a ZIP package with sorted entries and fixed timestamps."""
    try:
        source = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise CompilationFailedError(
            "Compiled document is not a readable OOXML package",
            details={"reason": str(exc)},
        ) from exc

    buffer = io.BytesIO()
    with (
        source,
        zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=compresslevel) as target,
    ):
        for name in sorted(source.namelist()):
            if name.endswith("/"):
                continue
            payload = source.read(name)
            info = zipfile.ZipInfo(name, date_time=FIXED_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            target.writestr(info, payload)
    return buffer.getvalue()


def inspect_package(data: bytes) -> DocxPackageInfo:
    """Inspect an OOXML package without extracting anything to disk."""
    if len(data) > _MAX_PACKAGE_BYTES:
        raise CompilationFailedError(
            "Document package exceeds the maximum allowed size",
            details={"size_bytes": len(data), "max_bytes": _MAX_PACKAGE_BYTES},
        )
    if not data.startswith(b"PK"):
        return DocxPackageInfo(
            entries=(),
            has_macros=False,
            has_embedded_objects=False,
            external_relationships=(),
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            missing_entries=_REQUIRED_ENTRIES,
        )

    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return DocxPackageInfo(
            entries=(),
            has_macros=False,
            has_embedded_objects=False,
            external_relationships=(),
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            missing_entries=_REQUIRED_ENTRIES,
        )

    with archive:
        names = tuple(sorted(archive.namelist()))
        lowered = [name.lower() for name in names]
        has_macros = any("vbaproject.bin" in name for name in lowered)
        has_objects = any(marker in name for name in lowered for marker in _FORBIDDEN_MARKERS)
        external: list[str] = []
        for name in names:
            if not name.endswith(".rels"):
                continue
            try:
                payload = archive.read(name).decode("utf-8", errors="ignore")
            except (KeyError, OSError):  # pragma: no cover - corrupt archive
                continue
            if 'TargetMode="External"' in payload:
                external.append(name)

    missing = tuple(entry for entry in _REQUIRED_ENTRIES if entry not in names)
    return DocxPackageInfo(
        entries=names,
        has_macros=has_macros,
        has_embedded_objects=has_objects,
        external_relationships=tuple(external),
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        missing_entries=missing,
    )


__all__ = ["DocxPackageInfo", "inspect_package", "normalize_package"]
