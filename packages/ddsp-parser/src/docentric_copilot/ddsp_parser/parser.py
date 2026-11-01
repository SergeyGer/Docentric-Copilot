"""DDSP parsing orchestration (FR-01).

The parser is deliberately format-tolerant and evidence-driven: a DDSP is a ZIP
container holding XML declarations and/or sample data, and the real-world layout
is not publicly specified (see ``docs/DDSP_COMPATIBILITY.md``). Whatever the
actual layout turns out to be, the parser records what it saw, never guesses a
field that is not present, and fails closed on hostile input.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from docentric_copilot.config import Limits, get_settings
from docentric_copilot.errors import InvalidInputError, UnsupportedInputError
from lxml import etree

from .diagnostics import Diagnostic, DiagnosticCode, error, info, warning
from .models import NormalizedSchema, SchemaSection
from .safety import (
    ContainerEntry,
    check_file_size,
    classify_container,
    parse_xml,
    read_container,
    xml_payloads,
)
from .sampledata import coerce_sample_tree, extract_sample_data, infer_sections_from_sample
from .xsd import XS_NS, build_sections_from_xsd

_MAX_MANIFEST_BYTES = 64 * 1024
_MANIFEST_NAMES = ("manifest.json", "ddsp.json", "metadata.json")
_IDENTIFIER = re.compile(r"[^a-z0-9_]")
_MAX_XML_DOCUMENTS = 40


@dataclass(frozen=True, slots=True)
class ParsedSource:
    """Result of parsing an untrusted DDSP package."""

    schema: NormalizedSchema
    sample_data: dict[str, Any] | None
    entry_names: tuple[str, ...]

    @property
    def sample_data_available(self) -> bool:
        return bool(self.sample_data)


def _schema_id_from(filename: str) -> str:
    stem = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    candidate = _IDENTIFIER.sub("_", stem.lower()).strip("_")
    if not candidate:
        candidate = "source"
    if not candidate[0].isalpha():
        candidate = f"source_{candidate}"
    return candidate[:60]


def _load_manifest(entries: list[ContainerEntry]) -> tuple[dict[str, Any], list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    for entry in entries:
        if entry.name.rsplit("/", 1)[-1].lower() not in _MANIFEST_NAMES:
            continue
        if entry.size > _MAX_MANIFEST_BYTES:
            diagnostics.append(
                warning(
                    DiagnosticCode.UNSUPPORTED_CONTAINER,
                    "Manifest is too large and was ignored",
                    location=entry.name,
                )
            )
            return {}, diagnostics
        try:
            payload = json.loads(entry.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            diagnostics.append(
                warning(
                    DiagnosticCode.UNSUPPORTED_CONTAINER,
                    "Manifest is not valid JSON and was ignored",
                    location=entry.name,
                )
            )
            return {}, diagnostics
        if not isinstance(payload, dict):
            diagnostics.append(
                warning(
                    DiagnosticCode.UNSUPPORTED_CONTAINER,
                    "Manifest root must be an object; it was ignored",
                    location=entry.name,
                )
            )
            return {}, diagnostics
        allowed = {"format", "format_version", "version", "name", "sections", "locales"}
        filtered = {key: payload[key] for key in allowed if key in payload}
        diagnostics.append(
            info(
                DiagnosticCode.FORMAT_DETECTED,
                f"Manifest detected: {filtered.get('format', 'unknown format')}",
                location=entry.name,
            )
        )
        return filtered, diagnostics
    return {}, diagnostics


def _is_schema_document(root: etree._Element) -> bool:
    if root.tag == f"{{{XS_NS}}}schema":
        return True
    return root.find(f".//{{{XS_NS}}}schema") is not None


def _prioritise(entries: list[ContainerEntry]) -> list[ContainerEntry]:
    """Analyse likely sample data first, then everything else, deterministically."""
    hints = ("sample", "data", "example", "demo")
    hinted: list[ContainerEntry] = []
    other: list[ContainerEntry] = []
    for entry in entries:
        lowered = entry.name.lower()
        (hinted if any(hint in lowered for hint in hints) else other).append(entry)
    return [
        *sorted(hinted, key=lambda item: item.name),
        *sorted(other, key=lambda item: item.name),
    ][:_MAX_XML_DOCUMENTS]


def _with_location(diagnostics: list[Diagnostic], location: str) -> list[Diagnostic]:
    return [item.model_copy(update={"location": item.location or location}) for item in diagnostics]


def _select_sections(
    schema_documents: list[tuple[str, etree._Element]],
    data_documents: list[tuple[str, etree._Element]],
    limits: Limits,
) -> tuple[list[SchemaSection], list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    for location, root in schema_documents:
        sections, section_diagnostics = build_sections_from_xsd(root, limits)
        diagnostics.extend(_with_location(section_diagnostics, location))
        if sections:
            if len(schema_documents) > 1:
                diagnostics.append(
                    info(
                        DiagnosticCode.FORMAT_DETECTED,
                        f"Multiple XSD documents found ({len(schema_documents)}); the first was used",
                    )
                )
            return sections, diagnostics
    if data_documents:
        location, root = data_documents[0]
        sections, section_diagnostics = infer_sections_from_sample(root, limits)
        diagnostics.extend(_with_location(section_diagnostics, location))
        return sections, diagnostics
    return [], [
        error(
            DiagnosticCode.SCHEMA_NOT_FOUND,
            "Neither an XSD schema nor a sample data document could be found",
        )
    ]


def parse_ddsp(
    data: bytes,
    filename: str = "source.ddsp",
    limits: Limits | None = None,
) -> ParsedSource:
    """Parse an untrusted DDSP package into a normalized schema and sample data."""
    resolved_limits = limits or get_settings().limits
    check_file_size(data, resolved_limits)
    container_format = classify_container(data)
    diagnostics: list[Diagnostic] = []

    if container_format == "zip":
        entries, container_diagnostics = read_container(data, resolved_limits)
        diagnostics.extend(container_diagnostics)
    elif container_format == "xml":
        entries = [ContainerEntry(name=filename, payload=data, size=len(data))]
        container_format = "xml"
        diagnostics.append(info(DiagnosticCode.FORMAT_DETECTED, "Input is a single XML document"))
    else:
        raise UnsupportedInputError(
            "The file is neither a DDSP ZIP container nor an XML document",
            code=DiagnosticCode.UNSUPPORTED_CONTAINER.value,
            details={"filename": filename},
        )

    manifest, manifest_diagnostics = _load_manifest(entries)
    diagnostics.extend(manifest_diagnostics)

    xml_entries = _prioritise(xml_payloads(entries))
    if not xml_entries:
        raise UnsupportedInputError(
            "No XML documents were found inside the DDSP container",
            code=DiagnosticCode.NO_XML_CONTENT.value,
            details={"entries": [entry.name for entry in entries][:50]},
        )

    schema_documents: list[tuple[str, etree._Element]] = []
    data_documents: list[tuple[str, etree._Element]] = []
    parse_failures: list[InvalidInputError] = []
    for entry in xml_entries:
        try:
            root = parse_xml(entry.payload, resolved_limits, location=entry.name)
        except InvalidInputError as exc:  # non-fatal for secondary documents
            parse_failures.append(exc)
            diagnostics.append(
                warning(
                    DiagnosticCode.XML_PARSE_ERROR,
                    f"Entry was skipped: {exc.message}",
                    location=entry.name,
                )
            )
            continue
        if _is_schema_document(root):
            schema_documents.append((entry.name, root))
        else:
            data_documents.append((entry.name, root))

    if not schema_documents and not data_documents:
        if parse_failures:
            first = parse_failures[0]
            raise InvalidInputError(
                first.message,
                code=first.code,
                details={
                    "location": first.details.get("location"),
                    "failed_documents": len(parse_failures),
                },
            )
        raise UnsupportedInputError(
            "No usable XML documents were found inside the DDSP container",
            code=DiagnosticCode.NO_XML_CONTENT.value,
        )

    sections, section_diagnostics = _select_sections(
        schema_documents, data_documents, resolved_limits
    )
    diagnostics.extend(section_diagnostics)

    schema_id = _IDENTIFIER.sub("_", str(manifest.get("name") or _schema_id_from(filename)).lower())
    schema_id = schema_id.strip("_")[:60] or "source"

    declared_locales = manifest.get("locales")
    locales: list[str] = []
    if isinstance(declared_locales, list):
        locales = [str(item)[:20] for item in declared_locales if str(item).strip()][:20]

    schema = NormalizedSchema(
        schema_id=schema_id,
        source="docentric-ax-ddsp",
        format_version=str(manifest.get("format_version") or manifest.get("version") or "") or None,
        container_format=container_format,
        sections=sections,
        diagnostics=list(diagnostics),
        sample_data_available=False,
        locales=locales,
    )

    sample_data: dict[str, Any] | None = None
    if data_documents and sections:
        data_location, data_root = data_documents[0]
        sample, mapping_diagnostics = extract_sample_data(
            data_root, schema.section_names, resolved_limits
        )
        if sample:
            sample_data = coerce_sample_tree(sample, schema, mapping_diagnostics)
            diagnostics.extend(mapping_diagnostics)
            diagnostics.append(
                info(
                    DiagnosticCode.FORMAT_DETECTED,
                    f"Sample data loaded from '{data_location}'",
                    location=data_location,
                )
            )
        else:
            diagnostics.extend(mapping_diagnostics)
    elif not data_documents:
        diagnostics.append(
            info(DiagnosticCode.SAMPLE_NOT_FOUND, "The package has no sample data document")
        )

    if schema.errors():
        first_error = schema.errors()[0]
        raise UnsupportedInputError(
            f"DDSP could not be normalized: {first_error.message}",
            code=first_error.code.value,
            details={
                "diagnostics": [item.model_dump(mode="json") for item in schema.diagnostics[:50]]
            },
        )

    final_schema = NormalizedSchema(
        schema_id=schema.schema_id,
        source=schema.source,
        format_version=schema.format_version,
        container_format=schema.container_format,
        sections=schema.sections,
        diagnostics=diagnostics,
        sample_data_available=sample_data is not None,
        locales=schema.locales,
    )
    return ParsedSource(
        schema=final_schema,
        sample_data=sample_data,
        entry_names=tuple(entry.name for entry in entries),
    )


def parse_xml_string(text: str, *, filename: str = "source.xml") -> ParsedSource:
    """Convenience wrapper for tests and CLI input from stdin."""
    return parse_ddsp(text.encode("utf-8"), filename=filename)


__all__ = ["ParsedSource", "parse_ddsp", "parse_xml_string"]
