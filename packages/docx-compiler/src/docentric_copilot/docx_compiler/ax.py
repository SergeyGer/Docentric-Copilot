"""Docentric AX adapter interface (Initiative 3, compatibility-gated).

This module defines the contract and the capability matrix for a future AX
compiler. It deliberately does **not** produce AX markup: no supported tagging
format, sample packages or licensed runtime have been verified, so any claim of
AX compatibility would be unfounded.

The adapter fails closed with ``UnsupportedTargetError``; the generic DOCX
compiler remains the only working target.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from docentric_copilot.errors import UnsupportedTargetError
from docentric_copilot.template_ir import Document

EXPERIMENTAL = "experimental"
NOT_TESTED = "not_tested"


@dataclass(frozen=True)
class AXAdapterCapability:
    """One dynamic element and what is actually known about it."""

    name: str
    purpose: str
    status: str = EXPERIMENTAL
    verified: bool = False


AX_CAPABILITIES: tuple[AXAdapterCapability, ...] = (
    AXAdapterCapability("FieldAdapter", "Dynamic fields with validated schema paths"),
    AXAdapterCapability("ListAdapter", "Repeating collections and table rows"),
    AXAdapterCapability("ImageAdapter", "Images from permitted package data"),
    AXAdapterCapability("ConditionalAdapter", "If/Else on typed conditions"),
    AXAdapterCapability("CompatibilityValidator", "Representation and supported version checks"),
    AXAdapterCapability("IntegrationTestHarness", "Execution inside a licensed AX runtime"),
)


def capability_matrix() -> dict[str, Any]:
    """Machine-readable matrix for the API, the UI and the docs."""
    return {
        "target": "docentric-ax",
        "status": NOT_TESTED,
        "adapter": EXPERIMENTAL,
        "verified": False,
        "capabilities": [
            {
                "name": capability.name,
                "purpose": capability.purpose,
                "status": capability.status,
                "verified": capability.verified,
            }
            for capability in AX_CAPABILITIES
        ],
        "blocking_questions": [
            "Which officially supported or legally compatible format may be used to emit AX tagging elements?",
            "Where can licensed AX runtime and reference DDSP/DOCX fixtures be obtained for independent tests?",
            "Which dynamic elements must the runtime execute to consider the adapter verified?",
        ],
        "note": (
            "Generic DOCX is the only supported output. AX compatibility stays not tested until an "
            "independent integration run passes in a licensed environment."
        ),
    }


class AXAdapter:
    """Placeholder adapter that fails closed by design."""

    target = "docentric-ax"
    status = EXPERIMENTAL

    def compile(self, document: Document, *args: Any, **kwargs: Any) -> bytes:
        raise UnsupportedTargetError(
            "Docentric AX output is not implemented; compatibility is not tested",
            details={
                "target": self.target,
                "adapter": self.status,
                "capabilities": [capability.name for capability in AX_CAPABILITIES],
            },
        )


__all__ = [
    "AX_CAPABILITIES",
    "AXAdapter",
    "AXAdapterCapability",
    "capability_matrix",
]
