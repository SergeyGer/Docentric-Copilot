"""Bounded, non-executing readers for reference containers and OOXML.

The reference inspector only reads bytes. Nothing from a template is executed,
evaluated or fetched: ZIP members are decompressed into memory under hard
limits, XML is parsed with DTDs, external entities and network access disabled,
and member names are treated as virtual names, never as host filesystem paths.
"""

from __future__ import annotations

import io
import re
import stat
import unicodedata
import zipfile
from dataclasses import dataclass
from typing import Final

from docentric_copilot.config import Limits, get_settings
from docentric_copilot.errors import (
    InvalidInputError,
    SecurityViolationError,
    UnsupportedInputError,
)
from lxml import etree

_ZIP_MAGIC: Final = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_XML_BOMS: Final = (b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")
_DOCTYPE = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)
_DRIVE = re.compile(r"^[A-Za-z]:")
_MAX_NAME_LENGTH: Final = 400


@dataclass(frozen=True, slots=True)
class ReferenceLimits:
    """Hard limits for one reference-inspection run."""

    max_file_bytes: int = 10 * 1024 * 1024
    max_uncompressed_bytes: int = 64 * 1024 * 1024
    max_archive_entries: int = 512
    max_compression_ratio: int = 120
    max_xml_nodes: int = 250_000
    max_xml_depth: int = 64
    max_total_artifacts: int = 4_096
    max_archive_depth: int = 3
    max_directory_files: int = 2_048
    max_text_preview: int = 160
    max_controls: int = 20_000
    max_xml_documents: int = 64

    @classmethod
    def from_limits(
        cls,
        limits: Limits | None = None,
        *,
        max_depth: int | None = None,
    ) -> ReferenceLimits:
        """Derive the inspector limits from the configured application limits."""
        base = limits or get_settings().limits
        values = cls(
            max_file_bytes=base.max_ddsp_bytes,
            max_uncompressed_bytes=base.max_uncompressed_bytes,
            max_archive_entries=base.max_zip_entries,
            max_compression_ratio=base.max_compression_ratio,
            max_xml_nodes=base.max_xml_nodes,
            max_xml_depth=base.max_xml_depth,
        )
        if max_depth is None:
            return values
        return cls(
            max_file_bytes=values.max_file_bytes,
            max_uncompressed_bytes=values.max_uncompressed_bytes,
            max_archive_entries=values.max_archive_entries,
            max_compression_ratio=values.max_compression_ratio,
            max_xml_nodes=values.max_xml_nodes,
            max_xml_depth=values.max_xml_depth,
            max_total_artifacts=values.max_total_artifacts,
            max_archive_depth=min(max(0, max_depth), values.max_archive_depth),
            max_directory_files=values.max_directory_files,
            max_text_preview=values.max_text_preview,
            max_controls=values.max_controls,
            max_xml_documents=values.max_xml_documents,
        )


@dataclass(frozen=True, slots=True)
class SafeEntry:
    """One safely decompressed archive member."""

    name: str
    payload: bytes
    size: int


def detect_container(data: bytes) -> str:
    """Return ``zip``, ``xml`` or ``unknown`` without trusting the extension."""
    if data.startswith(_ZIP_MAGIC):
        return "zip"
    head = data.lstrip(b" \t\r\n")
    for bom in _XML_BOMS:
        if head.startswith(bom):
            head = head[len(bom) :].lstrip(b" \t\r\n")
            break
    if head.startswith(b"<"):
        return "xml"
    return "unknown"


def check_input_size(data: bytes, limits: ReferenceLimits, *, minimum: int = 16) -> None:
    """Reject empty, tiny or oversized input before parsing."""
    if len(data) < minimum:
        raise InvalidInputError(
            "Input is too small to be a usable reference container",
            code="reference_input_too_small",
            details={"size_bytes": len(data), "minimum_bytes": minimum},
        )
    if len(data) > limits.max_file_bytes:
        raise UnsupportedInputError(
            "Input exceeds the configured maximum size",
            code="reference_input_too_large",
            details={"size_bytes": len(data), "max_bytes": limits.max_file_bytes},
        )


def normalize_member_name(name: str) -> str:
    """Normalize an OOXML/AXPP virtual member name without using host paths.

    AXPP stores member names with backslashes; those are virtual separators. The
    returned name is a ``/``-separated relative path that cannot escape the
    package and cannot address an absolute or Windows-drive location.
    """
    if not name or not isinstance(name, str):
        raise SecurityViolationError(
            "Archive member has an empty name",
            code="reference_unsafe_path",
        )
    if "\x00" in name:
        raise SecurityViolationError(
            "Archive member name contains a NUL byte",
            code="reference_unsafe_path",
        )
    normalized = unicodedata.normalize("NFC", name.replace("\\", "/"))
    if len(normalized) > _MAX_NAME_LENGTH:
        raise SecurityViolationError(
            "Archive member name is too long",
            code="reference_unsafe_path",
            details={"length": len(normalized), "max_length": _MAX_NAME_LENGTH},
        )
    if normalized.startswith("/"):
        raise SecurityViolationError(
            "Absolute archive member paths are rejected",
            code="reference_unsafe_path",
            details={"entry": normalized[:160]},
        )
    if _DRIVE.match(normalized):
        raise SecurityViolationError(
            "Windows drive paths are rejected inside archives",
            code="reference_unsafe_path",
            details={"entry": normalized[:160]},
        )
    parts: list[str] = []
    for part in normalized.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise SecurityViolationError(
                "Path traversal inside an archive is rejected",
                code="reference_unsafe_path",
                details={"entry": normalized[:160]},
            )
        if any(unicodedata.category(char).startswith("C") for char in part):
            raise SecurityViolationError(
                "Archive member name contains control characters",
                code="reference_unsafe_path",
                details={"entry": normalized[:160]},
            )
        parts.append(part)
    if not parts:
        raise SecurityViolationError(
            "Archive member name resolves to an empty path",
            code="reference_unsafe_path",
            details={"entry": normalized[:160]},
        )
    return "/".join(parts)


def read_archive(data: bytes, limits: ReferenceLimits) -> list[SafeEntry]:
    """Decompress a ZIP container into memory while enforcing every hard limit."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise InvalidInputError(
            "Reference container is not a readable ZIP archive",
            code="reference_container_invalid",
            details={"reason": str(exc)[:200]},
        ) from exc

    with archive:
        infos = archive.infolist()
        if len(infos) > limits.max_archive_entries:
            raise SecurityViolationError(
                "Archive contains more entries than allowed",
                code="reference_archive_entry_limit",
                details={"entries": len(infos), "max_entries": limits.max_archive_entries},
            )
        declared_total = 0
        normalized: list[tuple[zipfile.ZipInfo, str]] = []
        for entry in infos:
            if entry.is_dir():
                continue
            if entry.flag_bits & 0x1:
                raise SecurityViolationError(
                    "Encrypted archive entries are not supported",
                    code="reference_encrypted_entry",
                    details={"entry": entry.filename[:160]},
                )
            mode = entry.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise SecurityViolationError(
                    "Symbolic links inside archives are rejected",
                    code="reference_unsafe_path",
                    details={"entry": entry.filename[:160]},
                )
            name = normalize_member_name(entry.filename)
            declared_total += entry.file_size
            if declared_total > limits.max_uncompressed_bytes:
                raise SecurityViolationError(
                    "Archive expands beyond the configured limit",
                    code="reference_uncompressed_limit",
                    details={
                        "declared_bytes": declared_total,
                        "max_bytes": limits.max_uncompressed_bytes,
                    },
                )
            if entry.compress_size > 0:
                ratio = entry.file_size / entry.compress_size
                if ratio > limits.max_compression_ratio:
                    raise SecurityViolationError(
                        "Archive has a suspicious compression ratio",
                        code="reference_compression_ratio_limit",
                        details={"entry": entry.filename[:160], "ratio": round(ratio, 1)},
                    )
            normalized.append((entry, name))

        safe_entries: list[SafeEntry] = []
        consumed = 0
        for entry, name in sorted(normalized, key=lambda item: item[1]):
            budget = limits.max_uncompressed_bytes - consumed
            try:
                with archive.open(entry) as handle:
                    payload = handle.read(budget + 1)
            except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
                raise InvalidInputError(
                    "Archive entry could not be decompressed",
                    code="reference_container_invalid",
                    details={"entry": entry.filename[:160], "reason": str(exc)[:200]},
                ) from exc
            if len(payload) > budget:
                raise SecurityViolationError(
                    "Archive expands beyond the configured limit",
                    code="reference_uncompressed_limit",
                    details={
                        "entry": entry.filename[:160],
                        "max_bytes": limits.max_uncompressed_bytes,
                    },
                )
            consumed += len(payload)
            safe_entries.append(SafeEntry(name=name, payload=payload, size=len(payload)))

    if not safe_entries:
        raise InvalidInputError(
            "Archive does not contain any file entries",
            code="reference_container_empty",
        )
    return safe_entries


def parse_xml(
    payload: bytes,
    limits: ReferenceLimits,
    *,
    location: str,
) -> etree._Element:
    """Parse untrusted XML with DTDs, entities and network access disabled."""
    if _DOCTYPE.search(payload):
        raise SecurityViolationError(
            "Documents with a DOCTYPE or ENTITY declaration are rejected",
            code="reference_doctype_rejected",
            location=location,
            details={"reason": "DTD/entity declarations are disabled (XXE protection)"},
        )
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        attribute_defaults=False,
        huge_tree=False,
        recover=False,
        remove_comments=True,
        remove_pis=True,
        collect_ids=False,
    )
    try:
        root = etree.fromstring(payload, parser=parser)
    except (etree.XMLSyntaxError, ValueError) as exc:
        raise InvalidInputError(
            "XML document could not be parsed",
            code="reference_xml_invalid",
            details={"location": location, "reason": str(exc)[:300]},
        ) from exc
    enforce_tree_limits(root, limits, location=location)
    return root


def enforce_tree_limits(root: etree._Element, limits: ReferenceLimits, *, location: str) -> None:
    """Reject XML trees that are too deep or contain too many nodes."""
    stack: list[tuple[etree._Element, int]] = [(root, 1)]
    seen = 0
    while stack:
        node, depth = stack.pop()
        seen += 1
        if depth > limits.max_xml_depth:
            raise SecurityViolationError(
                "XML document is nested deeper than allowed",
                code="reference_xml_depth_limit",
                location=location,
                details={"max_depth": limits.max_xml_depth},
            )
        if seen > limits.max_xml_nodes:
            raise SecurityViolationError(
                "XML document contains more nodes than allowed",
                code="reference_xml_node_limit",
                location=location,
                details={"max_nodes": limits.max_xml_nodes},
            )
        stack.extend((child, depth + 1) for child in node)


def local_name(tag: object) -> str:
    """Return an element or attribute local name for lxml nodes/QNames."""
    if isinstance(tag, str):
        if tag.startswith("{"):
            return tag.split("}", 1)[1]
        return tag
    text = str(tag)
    if "}" in text:
        return text.split("}", 1)[1]
    return text


def namespace_uri(tag: object) -> str | None:
    """Return the namespace URI of an lxml tag/QName, when present."""
    text = str(tag)
    if text.startswith("{") and "}" in text:
        return text[1:].split("}", 1)[0]
    return None


def truncated(value: str | None, limit: int) -> str | None:
    """Trim a metadata string to a bounded, whitespace-normalized value."""
    if value is None:
        return None
    cleaned = " ".join(value.split())
    if not cleaned:
        return None
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…"


__all__ = [
    "ReferenceLimits",
    "SafeEntry",
    "check_input_size",
    "detect_container",
    "enforce_tree_limits",
    "local_name",
    "namespace_uri",
    "normalize_member_name",
    "parse_xml",
    "read_archive",
    "truncated",
]
