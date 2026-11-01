"""Diagnostic codes and the diagnostic record model.

Diagnostics are part of the public contract: they are returned by the API, shown
in the CLI and embedded in validation reports. Codes are stable.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class DiagnosticCode(str, Enum):
    # Container / transport level
    FILE_TOO_LARGE = "DDSP001"
    UNSUPPORTED_CONTAINER = "DDSP002"
    ZIP_ENTRY_LIMIT = "DDSP003"
    UNCOMPRESSED_SIZE_LIMIT = "DDSP004"
    COMPRESSION_RATIO_LIMIT = "DDSP005"
    ENCRYPTED_ENTRY = "DDSP006"
    UNSAFE_ENTRY_NAME = "DDSP007"
    NO_XML_CONTENT = "DDSP008"
    NESTED_ARCHIVE = "DDSP009"
    ZIP_CRC_ERROR = "DDSP010"
    FILE_TOO_SMALL = "DDSP011"

    # XML level
    DOCTYPE_REJECTED = "XML001"
    XML_PARSE_ERROR = "XML002"
    NODE_LIMIT_EXCEEDED = "XML003"
    DEPTH_LIMIT_EXCEEDED = "XML004"

    # Schema level
    SCHEMA_NOT_FOUND = "SCHEMA001"
    UNSUPPORTED_TYPE = "SCHEMA002"
    DUPLICATE_PATH = "SCHEMA003"
    RECURSIVE_TYPE = "SCHEMA004"
    SCHEMA_NODE_LIMIT = "SCHEMA005"
    SCHEMA_INFERRED = "SCHEMA006"

    # Sample data level
    SAMPLE_PARSE_ERROR = "SAMPLE001"
    SAMPLE_SCHEMA_MISMATCH = "SAMPLE002"
    SAMPLE_VALUE_TRUNCATED = "SAMPLE003"
    SAMPLE_NOT_FOUND = "SAMPLE004"

    # Informational
    SECTIONS_DETECTED = "INFO001"
    FORMAT_DETECTED = "INFO002"
    IMAGE_HEURISTIC = "INFO003"


class Diagnostic(BaseModel):
    """A single structured finding produced while processing input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: DiagnosticCode
    severity: Severity
    message: str = Field(max_length=1_000)
    location: str | None = Field(default=None, max_length=300)

    def as_line(self) -> str:
        prefix = f"[{self.code.value}] {self.severity.value}: "
        suffix = f" ({self.location})" if self.location else ""
        return f"{prefix}{self.message}{suffix}"


def error(code: DiagnosticCode, message: str, location: str | None = None) -> Diagnostic:
    return Diagnostic(code=code, severity=Severity.ERROR, message=message, location=location)


def warning(code: DiagnosticCode, message: str, location: str | None = None) -> Diagnostic:
    return Diagnostic(code=code, severity=Severity.WARNING, message=message, location=location)


def info(code: DiagnosticCode, message: str, location: str | None = None) -> Diagnostic:
    return Diagnostic(code=code, severity=Severity.INFO, message=message, location=location)


__all__ = ["Diagnostic", "DiagnosticCode", "Severity", "error", "info", "warning"]
