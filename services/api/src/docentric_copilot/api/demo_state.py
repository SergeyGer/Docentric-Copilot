"""Pure state helpers for the Streamlit live demo.

Keeping the confirmation merge out of the Streamlit script makes the
"Download available / Download blocked / confirmation reruns validation"
behaviour directly testable.
"""

from __future__ import annotations

from collections.abc import Mapping

from docentric_copilot.schema_resolver.mapping import MappingReport, MappingStatus

_CONFIRMABLE = {MappingStatus.NEEDS_REVIEW, MappingStatus.CONFLICT}


def apply_confirmations(report: MappingReport, confirmations: Mapping[str, str]) -> MappingReport:
    """Mark reviewer-confirmed ambiguous mappings as confirmed.

    Only ``needs_review`` and ``conflict`` mappings can be confirmed, and only
    when the reviewer supplied an explicit decision. Missing/invalid mappings
    are never confirmed by this helper: there is no field to confirm.
    """
    if not confirmations:
        return report
    mappings = []
    for mapping in report.mappings:
        note = confirmations.get(mapping.requirement_id)
        if note and mapping.status in _CONFIRMABLE:
            explanation = mapping.explanation
            if note and note not in explanation:
                explanation = f"{explanation} Reviewer: {note}".strip()
            mappings.append(
                mapping.model_copy(
                    update={
                        "status": MappingStatus.CONFIRMED,
                        "explanation": explanation[:1000],
                    }
                )
            )
        else:
            mappings.append(mapping)
    return report.model_copy(update={"mappings": mappings})


def compile_ready(report: MappingReport) -> bool:
    """A DOCX may be compiled only when no mapping still blocks it."""
    return not report.blocking()


__all__ = ["apply_confirmations", "compile_ready"]
