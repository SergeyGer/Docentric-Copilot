"""Deterministic value formatting shared by the compiler and the preview.

Formatting is deliberately locale-independent: the MVP renders English-style
numbers and dates so that golden files stay stable. Locale support is tracked in
the roadmap.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from docentric_copilot.template_ir import FieldBinding, ValueFormat

_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def _as_date(value: Any) -> date | None:
    if isinstance(value, date | datetime):
        return value if isinstance(value, date) else value.date()
    if isinstance(value, str):
        text = value.strip()
        for candidate in (text, text.split("T", 1)[0]):
            try:
                return date.fromisoformat(candidate)
            except ValueError:
                continue
    return None


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").replace(" ", ""))
        except ValueError:
            return None
    return None


def _format_date(value: date, pattern: str | None) -> str:
    if not pattern:
        return value.isoformat()
    out = pattern
    replacements = (
        ("YYYY", f"{value.year:04d}"),
        ("YY", f"{value.year % 100:02d}"),
        ("MMMM", _MONTHS[value.month - 1]),
        ("MMM", _MONTHS[value.month - 1][:3]),
        ("MM", f"{value.month:02d}"),
        ("M", str(value.month)),
        ("DD", f"{value.day:02d}"),
        ("D", str(value.day)),
    )
    for token, rendered in replacements:
        out = out.replace(token, rendered)
    return out


def format_value(value: Any, binding: FieldBinding) -> str:
    """Render a value according to the binding format contract."""
    if value is None:
        return ""
    fmt = binding.format
    if fmt is ValueFormat.UPPERCASE:
        return str(value).upper()
    if fmt is ValueFormat.LOWERCASE:
        return str(value).lower()
    if fmt is ValueFormat.BOOLEAN_YES_NO:
        return "Yes" if bool(value) else "No"
    if fmt in {ValueFormat.DATE_ISO, ValueFormat.DATE_SHORT, ValueFormat.DATE_LONG}:
        parsed = _as_date(value)
        if parsed is None:
            return str(value)
        pattern = binding.date_pattern
        if pattern:
            return _format_date(parsed, pattern)
        if fmt is ValueFormat.DATE_ISO:
            return parsed.isoformat()
        if fmt is ValueFormat.DATE_SHORT:
            return f"{parsed.day:02d} {_MONTHS[parsed.month - 1][:3]} {parsed.year}"
        return f"{parsed.day:02d} {_MONTHS[parsed.month - 1]} {parsed.year}"
    if fmt is ValueFormat.PERCENT:
        number = _as_number(value)
        if number is None:
            return str(value)
        decimals = binding.decimals if binding.decimals is not None else 1
        return f"{number * 100:.{decimals}f}%"
    if fmt is ValueFormat.NUMBER or fmt is ValueFormat.CURRENCY:
        number = _as_number(value)
        if number is None:
            return str(value)
        decimals = binding.decimals if binding.decimals is not None else 2
        rendered = f"{number:,.{decimals}f}"
        if fmt is ValueFormat.CURRENCY:
            code = binding.currency_code or ""
            return f"{rendered} {code}".strip()
        return rendered
    if fmt is ValueFormat.PLAIN or fmt is None:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)
    return str(value)  # pragma: no cover - exhaustive enum handling


__all__ = ["format_value"]
