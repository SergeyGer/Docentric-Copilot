"""Typed expression evaluation for rendering and preview (FR-04, FR-06).

Evaluation is total: missing data yields ``None`` and comparisons with ``None``
are false, except for the explicit null operators. No dynamic code execution.
"""

from __future__ import annotations

from typing import Any

from docentric_copilot.template_ir import Expression, ExpressionOperator

from .context import SampleContext


def _to_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _coerce_pair(left: Any, right: Any) -> tuple[Any, Any]:
    left_number, right_number = _to_number(left), _to_number(right)
    if left_number is not None and right_number is not None:
        return left_number, right_number
    if isinstance(left, bool) or isinstance(right, bool):

        def as_bool(value: Any) -> bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.strip().lower() in {"true", "1", "yes"}
            return bool(value)

        return as_bool(left), as_bool(right)
    return ("" if left is None else str(left)), ("" if right is None else str(right))


def _compare(operator: ExpressionOperator, left: Any, right: Any) -> bool:
    if left is None or right is None:
        return False
    left_coerced, right_coerced = _coerce_pair(left, right)
    if operator is ExpressionOperator.EQUALS:
        return bool(left_coerced == right_coerced)
    if operator is ExpressionOperator.NOT_EQUALS:
        return bool(left_coerced != right_coerced)
    if operator is ExpressionOperator.GREATER_THAN:
        return bool(left_coerced > right_coerced)
    if operator is ExpressionOperator.GREATER_OR_EQUAL:
        return bool(left_coerced >= right_coerced)
    if operator is ExpressionOperator.LESS_THAN:
        return bool(left_coerced < right_coerced)
    if operator is ExpressionOperator.LESS_OR_EQUAL:
        return bool(left_coerced <= right_coerced)
    if operator is ExpressionOperator.CONTAINS:
        return str(right_coerced) in str(left_coerced)
    raise ValueError(f"unsupported comparison operator: {operator}")  # pragma: no cover


def evaluate(expression: Expression, context: SampleContext) -> bool:
    """Evaluate a typed expression against the current sample context."""
    operator = expression.operator
    if operator is ExpressionOperator.AND:
        return all(evaluate(operand, context) for operand in expression.operands or [])
    if operator is ExpressionOperator.OR:
        return any(evaluate(operand, context) for operand in expression.operands or [])
    if operator is ExpressionOperator.NOT:
        operands = expression.operands or []
        return not evaluate(operands[0], context) if operands else True
    value = context.value(expression.field) if expression.field else None
    if operator is ExpressionOperator.NOT_NULL:
        return value is not None and value != ""
    if operator is ExpressionOperator.IS_NULL:
        return value is None or value == ""
    return _compare(operator, value, expression.value)


__all__ = ["evaluate"]
