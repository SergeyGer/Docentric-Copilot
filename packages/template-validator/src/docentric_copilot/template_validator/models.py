"""Validation result models (FR-07).

The five levels are reported separately and never collapsed into one boolean:
``not_tested`` is a first-class status and is *not* an alias for ``passed``.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class CheckStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"
    NOT_TESTED = "not_tested"


class Level(str, Enum):
    STRUCTURAL = "structural"
    SEMANTIC = "semantic"
    LOGICAL = "logical"
    VISUAL = "visual"
    COMPATIBILITY = "compatibility"


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(pattern=r"^V[1-5]-[0-9]{3}$")
    severity: Severity
    message: str = Field(max_length=1_000)
    location: str | None = Field(default=None, max_length=300)


class CheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^V[1-5]-[0-9]{3}$")
    level: Level
    name: str = Field(max_length=120)
    status: CheckStatus
    summary: str = Field(default="", max_length=500)
    findings: list[Finding] = Field(default_factory=list, max_length=200)

    def error_count(self) -> int:
        return sum(1 for finding in self.findings if finding.severity is Severity.ERROR)


class ValidationReport(BaseModel):
    """Machine readable report returned by the API and the CLI."""

    model_config = ConfigDict(extra="forbid")

    schema_id: str | None = Field(default=None, max_length=120)
    target: str = Field(default="generic-docx", max_length=40)
    ir_digest: str = Field(default="", max_length=64)
    checks: list[CheckResult] = Field(default_factory=list, max_length=100)
    package: dict[str, object] | None = None

    # ------------------------------------------------------------------ views
    def level_status(self, level: Level) -> CheckStatus:
        results = [check for check in self.checks if check.level is level]
        if not results:
            return CheckStatus.SKIPPED
        if any(check.status is CheckStatus.FAILED for check in results):
            return CheckStatus.FAILED
        active = [
            check
            for check in results
            if check.status not in {CheckStatus.NOT_TESTED, CheckStatus.SKIPPED}
        ]
        if not active:
            if any(check.status is CheckStatus.NOT_TESTED for check in results):
                return CheckStatus.NOT_TESTED
            return CheckStatus.SKIPPED
        if any(check.status is CheckStatus.WARNING for check in active):
            return CheckStatus.WARNING
        return CheckStatus.PASSED

    def statuses(self) -> dict[str, str]:
        """The exact shape promised by the API specification."""
        return {
            "structural": self.level_status(Level.STRUCTURAL).value,
            "semantic": self.level_status(Level.SEMANTIC).value,
            "logical": self.level_status(Level.LOGICAL).value,
            "visual": self.level_status(Level.VISUAL).value,
            "docentric_compatibility": self.level_status(Level.COMPATIBILITY).value,
        }

    @property
    def can_compile(self) -> bool:
        """Compilation is allowed only when V1-V3 pass."""
        return all(
            self.level_status(level) in {CheckStatus.PASSED, CheckStatus.WARNING}
            for level in (Level.STRUCTURAL, Level.SEMANTIC, Level.LOGICAL)
        )

    @property
    def overall(self) -> str:
        if not self.can_compile:
            return "failed"
        if self.level_status(Level.COMPATIBILITY) is CheckStatus.NOT_TESTED:
            return "passed_unverified_compatibility"
        return "passed"

    def counts(self) -> dict[str, int]:
        errors = sum(check.error_count() for check in self.checks)
        warnings = sum(
            1
            for check in self.checks
            for finding in check.findings
            if finding.severity is Severity.WARNING
        )
        return {"errors": errors, "warnings": warnings, "checks": len(self.checks)}

    def errors(self) -> list[Finding]:
        return [
            finding
            for check in self.checks
            for finding in check.findings
            if finding.severity is Severity.ERROR
        ]


__all__ = [
    "CheckResult",
    "CheckStatus",
    "Finding",
    "Level",
    "Severity",
    "ValidationReport",
]
