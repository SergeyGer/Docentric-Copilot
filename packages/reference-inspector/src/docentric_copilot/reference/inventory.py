"""Read-only inventory of reference templates and their containers.

The inspector never executes, imports, deploys or renders any part of a
reference package. It hashes every artifact, follows nested archives only up to
an explicit depth, normalizes virtual AXPP member names and records exact
duplicates as provenance rather than as new test cases.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Final

from docentric_copilot.errors import InvalidInputError, NotFoundError, UnsupportedInputError
from docentric_copilot.serialization import digest, digest_bytes
from pydantic import BaseModel, ConfigDict, Field

from .safety import (
    ReferenceLimits,
    detect_container,
    local_name,
    parse_xml,
    read_archive,
    truncated,
)

_VERSION_SCAN_BYTES: Final = 2 * 1024 * 1024


class SourceType(str, Enum):
    """Kind of the root input."""

    DOCX = "docx"
    ZIP = "zip"
    AXPP = "axpp"
    DIRECTORY = "directory"


class PlatformHint(str, Enum):
    """Detected Docentric/Dynamics platform family."""

    AX_2012 = "ax2012"
    D365 = "d365"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class ArtifactKind(str, Enum):
    """Kind of one inventory artifact."""

    DOCX = "docx"
    DDSP = "ddsp"
    XML = "xml"
    XSD = "xsd"
    AXPP = "axpp"
    ZIP = "zip"
    XPO = "xpo"
    PROJECT = "project"
    TEXT = "text"
    OTHER = "other"


class VersionHints(BaseModel):
    """Version/platform evidence collected for the whole container."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    platform: PlatformHint = PlatformHint.UNKNOWN
    product_versions: list[str] = Field(default_factory=list, max_length=32)
    evidence: list[str] = Field(default_factory=list, max_length=24)


class InventoryEntry(BaseModel):
    """One hashed artifact inside the inspected source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1, max_length=600)
    name: str = Field(min_length=1, max_length=300)
    parent: str | None = Field(default=None, max_length=600)
    kind: ArtifactKind
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    nested_depth: int = Field(ge=0, le=8)
    is_archive: bool = False
    expanded: bool = False
    platform_hint: PlatformHint = PlatformHint.UNKNOWN
    product_version: str | None = Field(default=None, max_length=40)
    warnings: list[str] = Field(default_factory=list, max_length=20)


class DuplicateGroup(BaseModel):
    """Byte-identical artifacts; one logical payload, several occurrences."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: ArtifactKind
    occurrences: int = Field(ge=2)
    paths: list[str] = Field(min_length=2, max_length=4096)


class ReferenceInventory(BaseModel):
    """JSON-serialisable inventory of one file or directory."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_type: SourceType
    source_name: str = Field(min_length=1, max_length=300)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_size_bytes: int = Field(ge=0)
    container: VersionHints
    entries: list[InventoryEntry] = Field(default_factory=list)
    duplicates: list[DuplicateGroup] = Field(default_factory=list)
    nested_archives: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list, max_length=100)

    def distinct_artifacts(self) -> int:
        return len({entry.sha256 for entry in self.entries})

    def artifacts_of_kind(self, kind: ArtifactKind) -> list[InventoryEntry]:
        return [entry for entry in self.entries if entry.kind is kind]

    def entry(self, path: str) -> InventoryEntry | None:
        for item in self.entries:
            if item.path == path:
                return item
        return None


@dataclass(slots=True)
class InventoryScan:
    """Inventory plus the bounded payloads the report builder needs."""

    inventory: ReferenceInventory
    payloads: dict[str, bytes] = field(default_factory=dict)
    paths_by_sha: dict[str, list[str]] = field(default_factory=dict)

    def payload_for_sha(self, sha256: str) -> bytes | None:
        return self.payloads.get(sha256)

    def distinct_entries_by_sha(self, kind: ArtifactKind) -> list[InventoryEntry]:
        seen: set[str] = set()
        selected: list[InventoryEntry] = []
        ordered = sorted(self.inventory.entries, key=lambda item: (item.path, item.sha256))
        for entry in ordered:
            if entry.kind is not kind or entry.sha256 in seen:
                continue
            seen.add(entry.sha256)
            selected.append(entry)
        return selected


def _artifact_kind(name: str) -> ArtifactKind:
    suffix = Path(name).suffix.lower()
    if suffix == ".docx":
        return ArtifactKind.DOCX
    if suffix == ".ddsp":
        return ArtifactKind.DDSP
    if suffix == ".xml":
        return ArtifactKind.XML
    if suffix == ".xsd":
        return ArtifactKind.XSD
    if suffix == ".axpp":
        return ArtifactKind.AXPP
    if suffix == ".zip":
        return ArtifactKind.ZIP
    if suffix == ".xpo":
        return ArtifactKind.XPO
    if suffix in {".rnrproj", ".csproj", ".sln"}:
        return ArtifactKind.PROJECT
    if suffix in {".txt", ".md", ".json", ".csv", ".rels"}:
        return ArtifactKind.TEXT
    return ArtifactKind.OTHER


def _platform_from_text(text: str) -> PlatformHint:
    lowered = text.casefold()
    candidates: set[PlatformHint] = set()
    if "dynamics 365" in lowered or "finance and operations" in lowered or "f&o" in lowered:
        candidates.add(PlatformHint.D365)
    if "dynamics ax 2012" in lowered or "ax 2012" in lowered:
        candidates.add(PlatformHint.AX_2012)
    if len(candidates) == 1:
        return next(iter(candidates))
    if len(candidates) > 1:
        return PlatformHint.MIXED
    return PlatformHint.UNKNOWN


def _platform_from_suffix(name: str) -> PlatformHint:
    suffix = Path(name).suffix.lower()
    if suffix in {".axpp", ".rnrproj"}:
        return PlatformHint.D365
    if suffix == ".xpo":
        return PlatformHint.AX_2012
    return PlatformHint.UNKNOWN


def _combine_platforms(values: list[PlatformHint]) -> PlatformHint:
    concrete = {value for value in values if value is not PlatformHint.UNKNOWN}
    if not concrete:
        return PlatformHint.UNKNOWN
    if len(concrete) == 1:
        return next(iter(concrete))
    return PlatformHint.MIXED


def _probe_archive_xml(
    payload: bytes, limits: ReferenceLimits
) -> tuple[PlatformHint, str | None, str | None]:
    """Return platform, product version and evidence for one XML member."""
    if not payload.lstrip().startswith(b"<") or len(payload) > _VERSION_SCAN_BYTES:
        return PlatformHint.UNKNOWN, None, None
    try:
        root = parse_xml(payload, limits, location="member")
    except Exception:
        # Auxiliary metadata must not abort the whole inventory; the malformed
        # member remains visible as an artifact with its hash.
        return PlatformHint.UNKNOWN, None, None
    name = local_name(root.tag)
    version: str | None = None
    platform = PlatformHint.UNKNOWN
    evidence: str | None = None
    if name == "dataSourcePackage":
        platform = PlatformHint.AX_2012
        evidence = "dataSourcePackage"
        for node in root.iter():
            if local_name(node.tag) != "systemInfo":
                continue
            for key, value in node.attrib.items():
                if local_name(key).casefold() == "productversion":
                    version = truncated(str(value), 40)
                    break
            break
    elif name == "ProjectData":
        evidence = "ProjectData"
        for key, value in root.attrib.items():
            if local_name(key).casefold() == "productversion":
                version = truncated(str(value), 40)
                break
    return platform, version, evidence


def _probe_docx(
    payload: bytes, limits: ReferenceLimits
) -> tuple[PlatformHint, str | None, list[str]]:
    """Read only small OOXML metadata; never execute or render the document."""
    warnings: set[str] = set()
    version: str | None = None
    if len(payload) > limits.max_uncompressed_bytes:
        return PlatformHint.UNKNOWN, None, ["document_too_large_for_metadata_probe"]
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = archive.namelist()
            if len(names) > limits.max_archive_entries:
                return PlatformHint.UNKNOWN, None, ["docx_entry_limit"]
            lowered_names = [name.casefold() for name in names]
            if any(name.endswith("vbaproject.bin") for name in lowered_names):
                warnings.add("macro_present")
            if any("/activex/" in name for name in lowered_names):
                warnings.add("activex_present")
            if any("/embeddings/" in name for name in lowered_names):
                warnings.add("embedded_object_present")
            for name in sorted(names):
                if not name.casefold().endswith(".rels"):
                    continue
                info = archive.getinfo(name)
                if info.file_size > 256 * 1024:
                    continue
                body = archive.read(name)
                if b'TargetMode="External"' in body or b"TargetMode='External'" in body:
                    warnings.add("external_relationship_present")
                    break
            for name in sorted(names):
                lowered_name = name.casefold()
                if (
                    not lowered_name.startswith("customxml/item")
                    or not lowered_name.endswith(".xml")
                    or lowered_name.endswith(".rels")
                ):
                    continue
                info = archive.getinfo(name)
                if info.file_size > _VERSION_SCAN_BYTES:
                    continue
                try:
                    root = parse_xml(archive.read(name), limits, location=name)
                except Exception:
                    continue
                if local_name(root.tag) != "ProjectData":
                    continue
                for key, value in root.attrib.items():
                    if local_name(key).casefold() == "productversion":
                        version = truncated(str(value), 40)
                        break
                break
    except (zipfile.BadZipFile, RuntimeError):
        return PlatformHint.UNKNOWN, None, ["docx_unreadable"]
    return PlatformHint.UNKNOWN, version, sorted(warnings)


def _suffix_source_type(name: str) -> SourceType | None:
    suffix = Path(name).suffix.lower()
    if suffix == ".docx":
        return SourceType.DOCX
    if suffix == ".axpp":
        return SourceType.AXPP
    if suffix == ".zip":
        return SourceType.ZIP
    return None


class _InventoryBuilder:
    def __init__(
        self,
        *,
        source_name: str,
        limits: ReferenceLimits,
        max_depth: int,
    ) -> None:
        self.source_name = source_name
        self.limits = limits
        self.max_depth = min(max(0, max_depth), limits.max_archive_depth)
        self.entries: list[InventoryEntry] = []
        self.payloads: dict[str, bytes] = {}
        self.paths_by_sha: dict[str, list[str]] = {}
        self.warnings: set[str] = set()
        self._artifact_count = 0

    def add(
        self,
        *,
        path: str,
        kind: ArtifactKind,
        payload: bytes,
        depth: int,
        platform: PlatformHint,
        product_version: str | None,
        warnings: list[str] | None = None,
        is_archive: bool = False,
        expanded: bool = False,
    ) -> InventoryEntry:
        self._artifact_count += 1
        if self._artifact_count > self.limits.max_total_artifacts:
            raise InvalidInputError(
                "Reference input contains more artifacts than allowed",
                code="reference_artifact_limit",
                details={"max_artifacts": self.limits.max_total_artifacts},
            )
        sha256 = digest_bytes(payload)
        entry = InventoryEntry(
            path=path,
            name=path.rsplit("/", 1)[-1],
            parent=path.rpartition("/")[0] or None,
            kind=kind,
            size_bytes=len(payload),
            sha256=sha256,
            nested_depth=depth,
            is_archive=is_archive,
            expanded=expanded,
            platform_hint=platform,
            product_version=product_version,
            warnings=sorted(set(warnings or [])),
        )
        self.entries.append(entry)
        self.paths_by_sha.setdefault(sha256, []).append(path)
        if kind in {ArtifactKind.DOCX, ArtifactKind.DDSP}:
            self.payloads.setdefault(sha256, payload)
        return entry

    def walk_archive(
        self,
        data: bytes,
        *,
        prefix: str,
        depth: int,
        context_platform: PlatformHint,
    ) -> None:
        entries = read_archive(data, self.limits)
        for member in entries:
            member_path = f"{prefix}/{member.name}" if prefix else member.name
            kind = _artifact_kind(member.name)
            own_platform, own_version, evidence = _probe_archive_xml(member.payload, self.limits)
            path_platform = _platform_from_text(member_path)
            if path_platform is PlatformHint.UNKNOWN:
                path_platform = _platform_from_suffix(member.name)
            platform = _combine_platforms([context_platform, own_platform, path_platform])
            warnings: list[str] = []
            if path_platform is not PlatformHint.UNKNOWN:
                warnings.append(f"version_evidence:path:{path_platform.value}")
            if evidence:
                warnings.append(f"version_evidence:{evidence}")
            if kind is ArtifactKind.DOCX:
                docx_platform, version, docx_warnings = _probe_docx(member.payload, self.limits)
                own_version = own_version or version
                platform = _combine_platforms([platform, docx_platform])
                warnings.extend(docx_warnings)
            is_archive = kind in {ArtifactKind.ZIP, ArtifactKind.AXPP}
            expand = is_archive and depth <= self.max_depth
            if is_archive and not expand:
                warnings.append("recursion_guard:nested_archive_not_expanded")
            entry = self.add(
                path=member_path,
                kind=kind,
                payload=member.payload,
                depth=depth,
                platform=platform,
                product_version=own_version,
                warnings=warnings,
                is_archive=is_archive,
                expanded=expand,
            )
            if expand:
                self.walk_archive(
                    member.payload,
                    prefix=entry.path,
                    depth=depth + 1,
                    context_platform=platform,
                )

    def walk_docx(self, data: bytes, *, path: str, depth: int, platform: PlatformHint) -> None:
        docx_platform, version, warnings = _probe_docx(data, self.limits)
        if platform is not PlatformHint.UNKNOWN:
            warnings.append(f"version_evidence:path:{platform.value}")
        self.add(
            path=path,
            kind=ArtifactKind.DOCX,
            payload=data,
            depth=depth,
            platform=_combine_platforms([platform, docx_platform]),
            product_version=version,
            warnings=warnings,
        )

    def inventory(
        self, *, source_type: SourceType, source_sha256: str, source_size_bytes: int
    ) -> ReferenceInventory:
        ordered = sorted(self.entries, key=lambda item: (item.path, item.sha256))
        duplicates: list[DuplicateGroup] = []
        for sha256, paths in self.paths_by_sha.items():
            unique_paths = sorted(set(paths))
            if len(unique_paths) < 2:
                continue
            kind = next(entry.kind for entry in ordered if entry.sha256 == sha256)
            duplicates.append(
                DuplicateGroup(
                    sha256=sha256,
                    kind=kind,
                    occurrences=len(unique_paths),
                    paths=unique_paths[:256],
                )
            )
        duplicates.sort(key=lambda group: (group.paths[0], group.sha256))
        nested_archives = sorted(
            entry.path for entry in ordered if entry.is_archive and entry.nested_depth > 0
        )
        versions = sorted({entry.product_version for entry in ordered if entry.product_version})
        evidence = sorted(
            {
                warning.removeprefix("version_evidence:")
                for entry in ordered
                for warning in entry.warnings
                if warning.startswith("version_evidence:")
            }
        )
        return ReferenceInventory(
            source_type=source_type,
            source_name=self.source_name,
            source_sha256=source_sha256,
            source_size_bytes=source_size_bytes,
            container=VersionHints(
                platform=_combine_platforms([entry.platform_hint for entry in ordered]),
                product_versions=versions[:32],
                evidence=evidence[:24],
            ),
            entries=ordered,
            duplicates=duplicates,
            nested_archives=nested_archives,
            warnings=sorted(self.warnings)[:100],
        )


def _read_file(path: Path, limits: ReferenceLimits) -> bytes:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise NotFoundError(
            f"Reference input cannot be read: {path.name}",
            details={"reason": str(exc)[:200]},
        ) from exc
    if size > limits.max_file_bytes:
        raise UnsupportedInputError(
            "Reference input exceeds the configured maximum size",
            code="reference_input_too_large",
            details={"size_bytes": size, "max_bytes": limits.max_file_bytes},
        )
    try:
        return path.read_bytes()
    except OSError as exc:
        raise NotFoundError(
            f"Reference input cannot be read: {path.name}",
            details={"reason": str(exc)[:200]},
        ) from exc


def _scan_single_file(
    data: bytes,
    *,
    name: str,
    source_type: SourceType,
    limits: ReferenceLimits,
    max_depth: int,
) -> InventoryScan:
    builder = _InventoryBuilder(source_name=name, limits=limits, max_depth=max_depth)
    source_sha256 = digest_bytes(data)
    path_platform = _platform_from_text(name)
    if path_platform is PlatformHint.UNKNOWN:
        path_platform = _platform_from_suffix(name)
    if source_type is SourceType.DOCX:
        builder.walk_docx(data, path=name, depth=0, platform=path_platform)
    else:
        platform = path_platform
        if source_type is SourceType.AXPP:
            platform = _combine_platforms([platform, PlatformHint.D365])
        container_evidence = (
            f"version_evidence:container:{source_type.value}"
            if platform is not PlatformHint.UNKNOWN
            else None
        )
        builder.add(
            path=name,
            kind=ArtifactKind.AXPP if source_type is SourceType.AXPP else ArtifactKind.ZIP,
            payload=data,
            depth=0,
            platform=platform,
            product_version=None,
            is_archive=True,
            expanded=True,
            warnings=[container_evidence] if container_evidence else [],
        )
        builder.walk_archive(data, prefix="", depth=1, context_platform=platform)
    return InventoryScan(
        inventory=builder.inventory(
            source_type=source_type,
            source_sha256=source_sha256,
            source_size_bytes=len(data),
        ),
        payloads=builder.payloads,
        paths_by_sha={key: sorted(value) for key, value in builder.paths_by_sha.items()},
    )


def _directory_files(root: Path, limits: ReferenceLimits) -> list[Path]:
    files: list[Path] = []
    for candidate in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if candidate.is_symlink():
            continue
        if candidate.is_file():
            files.append(candidate)
            if len(files) > limits.max_directory_files:
                raise InvalidInputError(
                    "Reference directory contains too many files",
                    code="reference_directory_limit",
                    details={"max_files": limits.max_directory_files},
                )
    if not files:
        raise InvalidInputError(
            "Reference directory does not contain any files",
            code="reference_directory_empty",
        )
    return files


def _scan_directory(root: Path, limits: ReferenceLimits, max_depth: int) -> InventoryScan:
    builder = _InventoryBuilder(
        source_name=root.name or "corpus",
        limits=limits,
        max_depth=max_depth,
    )
    files = _directory_files(root, limits)
    manifest: list[dict[str, object]] = []
    total_size = 0
    for candidate in files:
        relative = candidate.relative_to(root).as_posix()
        data = _read_file(candidate, limits)
        total_size += len(data)
        source_type = _suffix_source_type(relative)
        path_platform = _platform_from_text(relative)
        if path_platform is PlatformHint.UNKNOWN:
            path_platform = _platform_from_suffix(relative)
        if source_type is SourceType.DOCX:
            builder.walk_docx(data, path=relative, depth=1, platform=path_platform)
        elif source_type in {SourceType.ZIP, SourceType.AXPP}:
            kind = ArtifactKind.AXPP if source_type is SourceType.AXPP else ArtifactKind.ZIP
            platform = path_platform
            if source_type is SourceType.AXPP:
                platform = _combine_platforms([platform, PlatformHint.D365])
            expand = max_depth >= 1
            archive_warnings: list[str] = []
            if platform is not PlatformHint.UNKNOWN:
                archive_warnings.append(f"version_evidence:path:{platform.value}")
            if not expand:
                archive_warnings.append("recursion_guard:nested_archive_not_expanded")
            builder.add(
                path=relative,
                kind=kind,
                payload=data,
                depth=1,
                platform=platform,
                product_version=None,
                is_archive=True,
                expanded=expand,
                warnings=archive_warnings,
            )
            if expand:
                builder.walk_archive(data, prefix=relative, depth=2, context_platform=platform)
        else:
            own_platform, version, evidence = _probe_archive_xml(data, limits)
            builder.add(
                path=relative,
                kind=_artifact_kind(relative),
                payload=data,
                depth=1,
                platform=_combine_platforms([path_platform, own_platform]),
                product_version=version,
                warnings=[f"version_evidence:{evidence}"] if evidence else [],
            )
        manifest.append({"path": relative, "sha256": digest_bytes(data), "size": len(data)})
    return InventoryScan(
        inventory=builder.inventory(
            source_type=SourceType.DIRECTORY,
            source_sha256=digest(sorted(manifest, key=lambda item: str(item["path"]))),
            source_size_bytes=total_size,
        ),
        payloads=builder.payloads,
        paths_by_sha={key: sorted(value) for key, value in builder.paths_by_sha.items()},
    )


def scan_path(
    path: str | Path,
    *,
    limits: ReferenceLimits | None = None,
    max_depth: int = 1,
) -> InventoryScan:
    """Inspect a file or directory and return the inventory plus bounded payloads."""
    target = Path(path).expanduser()
    if not target.exists():
        raise NotFoundError("Reference input does not exist", details={"path": target.name})
    resolved_limits = limits or ReferenceLimits.from_limits(max_depth=max_depth)
    if target.is_dir():
        return _scan_directory(target, resolved_limits, max_depth)
    source_type = _suffix_source_type(target.name)
    if source_type is None:
        raise UnsupportedInputError(
            "Unsupported reference input; expected .docx, .zip, .axpp or a directory",
            code="reference_input_unsupported",
            details={"suffix": target.suffix[:20]},
        )
    data = _read_file(target, resolved_limits)
    if detect_container(data) != "zip":
        raise InvalidInputError(
            "Reference input is not a readable ZIP-based document or package",
            code="reference_container_invalid",
        )
    return _scan_single_file(
        data,
        name=target.name,
        source_type=source_type,
        limits=resolved_limits,
        max_depth=max_depth,
    )


def scan_bytes(
    data: bytes,
    *,
    filename: str,
    limits: ReferenceLimits | None = None,
    max_depth: int = 1,
) -> InventoryScan:
    """Inspect an uploaded byte payload without touching the filesystem."""
    clean_name = Path(filename.replace("\\", "/")).name or "upload.docx"
    source_type = _suffix_source_type(clean_name)
    if source_type is None:
        raise UnsupportedInputError(
            "Unsupported reference input; expected .docx, .zip or .axpp",
            code="reference_input_unsupported",
            details={"suffix": Path(clean_name).suffix[:20]},
        )
    resolved_limits = limits or ReferenceLimits.from_limits(max_depth=max_depth)
    if len(data) > resolved_limits.max_file_bytes:
        raise UnsupportedInputError(
            "Reference input exceeds the configured maximum size",
            code="reference_input_too_large",
            details={"size_bytes": len(data), "max_bytes": resolved_limits.max_file_bytes},
        )
    if detect_container(data) != "zip":
        raise InvalidInputError(
            "Reference input is not a readable ZIP-based document or package",
            code="reference_container_invalid",
        )
    return _scan_single_file(
        data,
        name=clean_name,
        source_type=source_type,
        limits=resolved_limits,
        max_depth=max_depth,
    )


def inspect_path(
    path: str | Path,
    *,
    limits: ReferenceLimits | None = None,
    max_depth: int = 1,
) -> ReferenceInventory:
    """Return only the JSON-serialisable inventory for a file or directory."""
    return scan_path(path, limits=limits, max_depth=max_depth).inventory


def inspect_bytes(
    data: bytes,
    *,
    filename: str,
    limits: ReferenceLimits | None = None,
    max_depth: int = 1,
) -> ReferenceInventory:
    """Return only the JSON-serialisable inventory for uploaded bytes."""
    return scan_bytes(data, filename=filename, limits=limits, max_depth=max_depth).inventory


__all__ = [
    "ArtifactKind",
    "DuplicateGroup",
    "InventoryEntry",
    "InventoryScan",
    "PlatformHint",
    "ReferenceInventory",
    "SourceType",
    "VersionHints",
    "inspect_bytes",
    "inspect_path",
    "scan_bytes",
    "scan_path",
]
