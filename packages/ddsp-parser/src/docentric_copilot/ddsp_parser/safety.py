"""Defensive readers for untrusted containers and XML.

Threat model (see ``docs/THREAT_MODEL.md``): DDSP is attacker controlled. Every
byte that reaches a parser is bounded, and XML is parsed with entity expansion,
DTD loading and network access disabled. The functions here fail closed: they
raise :class:`SecurityViolationError` instead of returning partial data.
"""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from typing import Final

from docentric_copilot.config import Limits
from docentric_copilot.errors import (
    InvalidInputError,
    SecurityViolationError,
    UnsupportedInputError,
)
from lxml import etree

from .diagnostics import Diagnostic, DiagnosticCode, error, info, warning

_ZIP_MAGIC: Final = b"PK\x03\x04"
_ZIP_EMPTY_MAGIC: Final = b"PK\x05\x06"
_ZIP_SPANNED: Final = b"PK\x07\x08"
_DOCTYPE = re.compile(rb"<!(?:DOCTYPE|ENTITY)", re.IGNORECASE)
_XML_DECL = re.compile(rb"^\s*<\?xml", re.IGNORECASE)
_NESTED_ARCHIVE_SUFFIXES: Final = (".zip", ".ddsp", ".7z", ".rar", ".gz", ".tar", ".bz2", ".xz")


@dataclass(frozen=True, slots=True)
class ContainerEntry:
    """One safely extracted member of a DDSP container."""

    name: str
    payload: bytes
    size: int


def classify_container(data: bytes) -> str:
    """Return ``zip``, ``xml`` or ``unknown`` based on magic bytes."""
    if data.startswith((_ZIP_MAGIC, _ZIP_EMPTY_MAGIC, _ZIP_SPANNED)):
        return "zip"
    if data.lstrip().startswith(b"<"):
        return "xml"
    return "unknown"


def check_file_size(data: bytes, limits: Limits, *, minimum: int = 16) -> None:
    if len(data) < minimum:
        raise InvalidInputError(
            "Input file is too small to be a DDSP package",
            code=DiagnosticCode.FILE_TOO_SMALL.value,
            details={"size_bytes": len(data), "minimum_bytes": minimum},
        )
    if len(data) > limits.max_ddsp_bytes:
        raise UnsupportedInputError(
            "Input file exceeds the configured maximum size",
            code=DiagnosticCode.FILE_TOO_LARGE.value,
            details={"size_bytes": len(data), "max_bytes": limits.max_ddsp_bytes},
        )


def _safe_entry_name(name: str) -> bool:
    if not name or len(name) > 300:
        return False
    if name.startswith(("/", "\\")) or ".." in name:
        return False
    if "\\" in name or "\x00" in name:
        return False
    return not any(unicodedata.category(char).startswith("C") for char in name)


def read_container(data: bytes, limits: Limits) -> tuple[list[ContainerEntry], list[Diagnostic]]:
    """Extract every file entry from a DDSP ZIP container with hard limits.

    Raises ``SecurityViolationError`` / ``UnsupportedInputError`` when the archive
    is hostile or exceeds a hard limit. Non-fatal oddities become diagnostics.
    """
    diagnostics: list[Diagnostic] = []
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise InvalidInputError(
            "DDSP container is not a readable ZIP archive",
            code=DiagnosticCode.UNSUPPORTED_CONTAINER.value,
            details={"reason": str(exc)},
        ) from exc

    with archive:
        infos = archive.infolist()
        if len(infos) > limits.max_zip_entries:
            raise SecurityViolationError(
                "DDSP container has too many entries",
                code=DiagnosticCode.ZIP_ENTRY_LIMIT.value,
                details={"entries": len(infos), "max_entries": limits.max_zip_entries},
            )

        declared_total = 0
        for entry in infos:
            if entry.is_dir():
                continue
            if not _safe_entry_name(entry.filename):
                raise SecurityViolationError(
                    "DDSP container contains an unsafe entry name",
                    code=DiagnosticCode.UNSAFE_ENTRY_NAME.value,
                    details={"entry": entry.filename[:120]},
                )
            if entry.flag_bits & 0x1:
                raise SecurityViolationError(
                    "Encrypted DDSP entries are not supported",
                    code=DiagnosticCode.ENCRYPTED_ENTRY.value,
                    details={"entry": entry.filename[:120]},
                )
            if entry.filename.lower().endswith(_NESTED_ARCHIVE_SUFFIXES):
                raise SecurityViolationError(
                    "Nested archives inside a DDSP container are rejected",
                    code=DiagnosticCode.NESTED_ARCHIVE.value,
                    details={"entry": entry.filename[:120]},
                )
            declared_total += entry.file_size
            if declared_total > limits.max_uncompressed_bytes:
                raise SecurityViolationError(
                    "DDSP container expands beyond the configured limit",
                    code=DiagnosticCode.UNCOMPRESSED_SIZE_LIMIT.value,
                    details={
                        "declared_bytes": declared_total,
                        "max_bytes": limits.max_uncompressed_bytes,
                    },
                )
            if entry.compress_size > 0:
                ratio = entry.file_size / entry.compress_size
                if ratio > limits.max_compression_ratio:
                    raise SecurityViolationError(
                        "DDSP container has a suspicious compression ratio",
                        code=DiagnosticCode.COMPRESSION_RATIO_LIMIT.value,
                        details={"entry": entry.filename[:120], "ratio": round(ratio, 1)},
                    )

        entries: list[ContainerEntry] = []
        for entry in infos:
            if entry.is_dir():
                continue
            budget = limits.max_uncompressed_bytes - sum(item.size for item in entries)
            try:
                with archive.open(entry) as handle:
                    payload = handle.read(max(0, budget) + 1)
            except (zipfile.BadZipFile, RuntimeError) as exc:
                raise InvalidInputError(
                    "DDSP entry could not be decompressed",
                    code=DiagnosticCode.ZIP_CRC_ERROR.value,
                    details={"entry": entry.filename[:120], "reason": str(exc)[:200]},
                ) from exc
            if len(payload) > budget:
                raise SecurityViolationError(
                    "DDSP container expands beyond the configured limit",
                    code=DiagnosticCode.UNCOMPRESSED_SIZE_LIMIT.value,
                    details={
                        "entry": entry.filename[:120],
                        "max_bytes": limits.max_uncompressed_bytes,
                    },
                )
            entries.append(ContainerEntry(name=entry.filename, payload=payload, size=len(payload)))

    if not entries:
        raise InvalidInputError(
            "DDSP container is empty",
            code=DiagnosticCode.NO_XML_CONTENT.value,
        )
    diagnostics.append(
        info(
            DiagnosticCode.FORMAT_DETECTED,
            f"ZIP container with {len(entries)} entries",
        )
    )
    return entries, diagnostics


def _looks_like_xml(payload: bytes) -> bool:
    head = payload.lstrip()[:5]
    return head.startswith(b"<") or bool(_XML_DECL.match(payload[:64]))


def xml_payloads(entries: list[ContainerEntry]) -> list[ContainerEntry]:
    """Return the entries that look like XML documents."""
    return [entry for entry in entries if _looks_like_xml(entry.payload)]


def parse_xml(payload: bytes, limits: Limits, *, location: str) -> etree._Element:
    """Parse XML with external entities, DTDs and network access disabled."""
    if _DOCTYPE.search(payload):
        raise SecurityViolationError(
            "Documents with a DOCTYPE or ENTITY declaration are rejected",
            code=DiagnosticCode.DOCTYPE_REJECTED.value,
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
    except etree.XMLSyntaxError as exc:
        raise InvalidInputError(
            "XML document could not be parsed",
            code=DiagnosticCode.XML_PARSE_ERROR.value,
            details={"location": location, "reason": str(exc)[:300]},
        ) from exc
    except ValueError as exc:  # pragma: no cover - lxml raises this for NUL bytes
        raise InvalidInputError(
            "XML document contains invalid characters",
            code=DiagnosticCode.XML_PARSE_ERROR.value,
            details={"location": location, "reason": str(exc)[:300]},
        ) from exc
    enforce_tree_limits(root, limits, location=location)
    return root


def enforce_tree_limits(root: etree._Element, limits: Limits, *, location: str) -> None:
    """Guard against deeply nested or extremely wide documents."""
    stack: list[tuple[etree._Element, int]] = [(root, 1)]
    seen = 0
    while stack:
        node, depth = stack.pop()
        seen += 1
        if depth > limits.max_xml_depth:
            raise SecurityViolationError(
                "XML document is nested deeper than allowed",
                code=DiagnosticCode.DEPTH_LIMIT_EXCEEDED.value,
                location=location,
                details={"max_depth": limits.max_xml_depth},
            )
        if seen > limits.max_xml_nodes:
            raise SecurityViolationError(
                "XML document contains more nodes than allowed",
                code=DiagnosticCode.NODE_LIMIT_EXCEEDED.value,
                location=location,
                details={"max_nodes": limits.max_xml_nodes},
            )
        for child in node:
            stack.append((child, depth + 1))


def local_name(tag: str) -> str:
    """Strip the ``{namespace}`` prefix from an lxml tag."""
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def diagnostics_for_container(entries: list[ContainerEntry]) -> list[Diagnostic]:
    found = [entry.name for entry in entries if _looks_like_xml(entry.payload)]
    if not found:
        return [
            error(
                DiagnosticCode.NO_XML_CONTENT,
                "The container has no XML documents to analyse",
            )
        ]
    if len(found) > 40:
        return [
            warning(
                DiagnosticCode.NO_XML_CONTENT,
                f"Container has many XML documents ({len(found)}); only the first 40 are analysed",
            )
        ]
    return []


__all__ = [
    "ContainerEntry",
    "check_file_size",
    "classify_container",
    "diagnostics_for_container",
    "enforce_tree_limits",
    "local_name",
    "parse_xml",
    "read_container",
    "xml_payloads",
]
