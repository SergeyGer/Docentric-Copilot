"""Semantic field mapping models and validation (FR-02).

A mapping is a *proposal*: the planner suggests a requirement-to-field link and
this module decides whether the proposal is admissible. ``confidence_score`` is
the model's own estimate and is never treated as evidence.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from docentric_copilot.ddsp_parser.models import NormalizedSchema


class MappingStatus(str, Enum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    MISSING = "missing"
    INVALID = "invalid"


class RequirementKind(str, Enum):
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    BOOLEAN = "boolean"
    IMAGE = "image"
    COLLECTION = "collection"
    ANY = "any"


class FieldMapping(BaseModel):
    """Exactly the shape required by FR-02."""

    model_config = ConfigDict(extra="forbid")

    requirement_id: str = Field(pattern=r"^req_[a-z0-9_]{1,40}$")
    requirement: str = Field(min_length=1, max_length=500)
    candidate_field_paths: list[str] = Field(default_factory=list, max_length=10)
    selected_field_path: str | None = Field(default=None, max_length=512)
    data_type: str | None = Field(default=None, max_length=20)
    schema_evidence: str | None = Field(default=None, max_length=500)
    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    status: MappingStatus = MappingStatus.MISSING
    explanation: str = Field(default="", max_length=1_000)

    @property
    def is_blocking(self) -> bool:
        return self.status in {MappingStatus.MISSING, MappingStatus.INVALID}


class MappingReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mappings: list[FieldMapping] = Field(default_factory=list, max_length=200)
    schema_id: str | None = Field(default=None, max_length=120)

    def counts(self) -> dict[str, int]:
        result = {status.value: 0 for status in MappingStatus}
        for mapping in self.mappings:
            result[mapping.status.value] += 1
        return result

    def blocking(self) -> list[FieldMapping]:
        return [mapping for mapping in self.mappings if mapping.is_blocking]

    def unresolved(self) -> list[FieldMapping]:
        return [
            mapping
            for mapping in self.mappings
            if mapping.status in {MappingStatus.AMBIGUOUS, MappingStatus.MISSING}
        ]

    def by_requirement(self) -> dict[str, FieldMapping]:
        return {mapping.requirement_id: mapping for mapping in self.mappings}


def validate_mapping(schema: NormalizedSchema, mapping: FieldMapping) -> FieldMapping:
    """Down-grade a mapping that does not satisfy schema evidence.

    * unknown path -> ``invalid``
    * path exists but is a collection when a scalar was expected -> ``invalid``
    * no selected path -> ``missing``
    * no candidates at all -> ``missing``
    """
    if mapping.selected_field_path is None:
        status = MappingStatus.MISSING if not mapping.candidate_field_paths else mapping.status
        if status is MappingStatus.RESOLVED:
            status = MappingStatus.AMBIGUOUS
        return mapping.model_copy(update={"status": status})

    node = schema.node(mapping.selected_field_path)
    if node is None:
        return mapping.model_copy(
            update={
                "status": MappingStatus.INVALID,
                "explanation": (
                    f"Selected path '{mapping.selected_field_path}' does not exist in the schema"
                ),
            }
        )

    expected = mapping.data_type
    actual = node.data_type
    if expected is not None and expected not in {"any", "collection"}:
        compatible = {
            "string": {"string", "any"},
            "number": {"number", "any"},
            "boolean": {"boolean", "any"},
            "date": {"date", "string", "any"},
            "image": {"image", "any"},
        }.get(expected, {expected, "any"})
        if actual not in compatible:
            return mapping.model_copy(
                update={
                    "status": MappingStatus.INVALID,
                    "explanation": (
                        f"Path '{mapping.selected_field_path}' has type '{actual}' "
                        f"but '{expected}' was required"
                    ),
                }
            )

    evidence = mapping.schema_evidence or f"{node.path}:{node.data_type}"
    return mapping.model_copy(update={"data_type": actual, "schema_evidence": evidence})


def summarize(report: MappingReport) -> str:
    counts = report.counts()
    return (
        f"{counts['resolved']} resolved, {counts['ambiguous']} ambiguous, "
        f"{counts['missing']} missing, {counts['invalid']} invalid"
    )


__all__ = [
    "FieldMapping",
    "MappingReport",
    "MappingStatus",
    "RequirementKind",
    "summarize",
    "validate_mapping",
]
