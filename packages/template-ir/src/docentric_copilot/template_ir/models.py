"""Template Intermediate Representation (IR) v1.0.

The IR is the only contract between the AI planning layer and the deterministic
execution layer (FR-03, FR-04, FR-05). It is intentionally narrow:

* no executable code, no raw XPath, no raw OOXML;
* every dynamic reference is a schema path that the validator can resolve;
* every optional feature has a defensive size bound so that a hostile or
  hallucinated document cannot exhaust the compiler.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr
from pydantic import field_validator, model_validator

# --------------------------------------------------------------------------- #
# Shared primitives
# --------------------------------------------------------------------------- #

PATH_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$"
ALIAS_PATTERN = r"^[a-z][a-z0-9_]{0,31}$"
HEX_COLOR_PATTERN = r"^#[0-9A-Fa-f]{6}$"

MAX_EXPRESSION_DEPTH = 8


class StrictModel(BaseModel):
    """Base model: unknown keys are rejected so that hallucinations fail loudly."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=False)


class Alignment(str, Enum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    JUSTIFY = "justify"


class DataType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
    IMAGE = "image"
    COLLECTION = "collection"
    ANY = "any"


class ValueFormat(str, Enum):
    PLAIN = "plain"
    UPPERCASE = "uppercase"
    LOWERCASE = "lowercase"
    NUMBER = "number"
    CURRENCY = "currency"
    PERCENT = "percent"
    DATE_SHORT = "date_short"
    DATE_LONG = "date_long"
    DATE_ISO = "date_iso"
    BOOLEAN_YES_NO = "boolean_yes_no"


class CompileTarget(str, Enum):
    GENERIC_DOCX = "generic-docx"
    DOCENTRIC_AX = "docentric-ax"


class DesignStyle(str, Enum):
    CLASSIC = "classic"
    MODERN = "modern"
    MINIMAL = "minimal"


class TextStyle(StrictModel):
    """Character/paragraph formatting. Never carries raw OOXML."""

    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    font_size_pt: float | None = Field(default=None, ge=6, le=72)
    color: str | None = Field(default=None, pattern=HEX_COLOR_PATTERN)
    alignment: Alignment | None = None


class PageSettings(StrictModel):
    size: Literal["A4", "LETTER"] = "A4"
    orientation: Literal["portrait", "landscape"] = "portrait"
    margin_top_mm: float = Field(default=20.0, ge=5, le=60)
    margin_right_mm: float = Field(default=20.0, ge=5, le=60)
    margin_bottom_mm: float = Field(default=20.0, ge=5, le=60)
    margin_left_mm: float = Field(default=20.0, ge=5, le=60)


# --------------------------------------------------------------------------- #
# Typed expressions (FR-04, section 5.4 of the specification)
# --------------------------------------------------------------------------- #

Scalar = Union[StrictBool, StrictInt, StrictFloat, StrictStr]


class ExpressionOperator(str, Enum):
    AND = "and"
    OR = "or"
    NOT = "not"
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    GREATER_THAN = "greater_than"
    GREATER_OR_EQUAL = "greater_or_equal"
    LESS_THAN = "less_than"
    LESS_OR_EQUAL = "less_or_equal"
    NOT_NULL = "not_null"
    IS_NULL = "is_null"
    CONTAINS = "contains"


_LOGICAL = {ExpressionOperator.AND, ExpressionOperator.OR, ExpressionOperator.NOT}
_COMPARISON = {
    ExpressionOperator.EQUALS,
    ExpressionOperator.NOT_EQUALS,
    ExpressionOperator.GREATER_THAN,
    ExpressionOperator.GREATER_OR_EQUAL,
    ExpressionOperator.LESS_THAN,
    ExpressionOperator.LESS_OR_EQUAL,
}


class Expression(StrictModel):
    """A deliberately tiny boolean algebra.

    The LLM never produces XPath: it produces this AST, which the target adapter
    translates into a verified construct. Operators outside this enum simply do
    not exist in the contract.
    """

    operator: ExpressionOperator
    field: str | None = Field(default=None, pattern=PATH_PATTERN, max_length=512)
    value: Scalar | None = None
    operands: list[Expression] | None = Field(default=None, max_length=16)

    @model_validator(mode="after")
    def _check_shape(self) -> Expression:
        op = self.operator
        if op in _LOGICAL:
            if op is ExpressionOperator.NOT:
                if not self.operands or len(self.operands) != 1:
                    raise ValueError("operator 'not' requires exactly one operand")
            elif not self.operands or len(self.operands) < 2:
                raise ValueError(f"operator '{op.value}' requires at least two operands")
            if self.field is not None or self.value is not None:
                raise ValueError(f"operator '{op.value}' must not carry field or value")
        else:
            if self.operands is not None:
                raise ValueError(f"operator '{op.value}' must not carry operands")
            if self.field is None:
                raise ValueError(f"operator '{op.value}' requires a field path")
            if op in _COMPARISON or op is ExpressionOperator.CONTAINS:
                if self.value is None:
                    raise ValueError(f"operator '{op.value}' requires a value")
                if op is ExpressionOperator.CONTAINS and not isinstance(self.value, str):
                    raise ValueError("operator 'contains' requires a string value")
            elif op in {ExpressionOperator.NOT_NULL, ExpressionOperator.IS_NULL}:
                if self.value is not None:
                    raise ValueError(f"operator '{op.value}' must not carry a value")
        if _expression_depth(self) > MAX_EXPRESSION_DEPTH:
            raise ValueError(f"expression nesting exceeds {MAX_EXPRESSION_DEPTH} levels")
        return self


def _expression_depth(expression: Expression, level: int = 0) -> int:
    if not expression.operands:
        return level
    return max(_expression_depth(operand, level + 1) for operand in expression.operands)


# --------------------------------------------------------------------------- #
# Inline content
# --------------------------------------------------------------------------- #


class TextRun(StrictModel):
    kind: Literal["text"] = "text"
    text: str = Field(max_length=20_000)
    style: TextStyle | None = None


class FieldBinding(StrictModel):
    """A dynamic scalar value bound to a normalized schema path."""

    kind: Literal["field"] = "field"
    path: str = Field(pattern=PATH_PATTERN, max_length=512)
    label: str | None = Field(default=None, max_length=200)
    format: ValueFormat | None = None
    date_pattern: str | None = Field(default=None, pattern=r"^[A-Za-z0-9 \-/:.,]{1,40}$")
    currency_code: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    decimals: int | None = Field(default=None, ge=0, le=6)
    style: TextStyle | None = None

    @model_validator(mode="after")
    def _check_format(self) -> FieldBinding:
        if self.format is ValueFormat.CURRENCY and self.currency_code is None:
            raise ValueError("currency format requires currency_code")
        if self.date_pattern is not None and self.format not in {
            ValueFormat.DATE_SHORT,
            ValueFormat.DATE_LONG,
            ValueFormat.DATE_ISO,
            None,
        }:
            raise ValueError("date_pattern is only meaningful for date formats")
        return self


class ImageBinding(StrictModel):
    """A dynamic image. The IR never embeds binary payloads."""

    kind: Literal["image"] = "image"
    path: str = Field(pattern=PATH_PATTERN, max_length=512)
    alt_text: str | None = Field(default=None, max_length=200)
    width_mm: float | None = Field(default=None, ge=5, le=200)
    height_mm: float | None = Field(default=None, ge=5, le=200)
    alignment: Alignment | None = None


InlineContent = Annotated[Union[TextRun, FieldBinding], Field(discriminator="kind")]


# --------------------------------------------------------------------------- #
# Block level content
# --------------------------------------------------------------------------- #


class Paragraph(StrictModel):
    kind: Literal["paragraph"] = "paragraph"
    runs: list[InlineContent] = Field(default_factory=list, max_length=200)
    style: TextStyle | None = None
    space_after_pt: float | None = Field(default=None, ge=0, le=48)


class Heading(StrictModel):
    kind: Literal["heading"] = "heading"
    level: int = Field(default=1, ge=1, le=3)
    runs: list[InlineContent] = Field(min_length=1, max_length=50)
    style: TextStyle | None = None


class Repeat(StrictModel):
    """Iterate a collection.

    ``alias`` introduces an explicit context: bindings inside the block may use
    ``alias.Field`` instead of the full collection path. The validator resolves
    the alias lexically (nearest enclosing repeat wins).
    """

    kind: Literal["repeat"] = "repeat"
    path: str = Field(pattern=PATH_PATTERN, max_length=512)
    alias: str = Field(pattern=ALIAS_PATTERN)
    blocks: list[Block] = Field(min_length=1, max_length=200)
    max_items: int | None = Field(default=None, ge=1, le=1_000)
    empty_message: str | None = Field(default=None, max_length=200)


class Conditional(StrictModel):
    kind: Literal["conditional"] = "conditional"
    condition: Expression
    then_blocks: list[Block] = Field(min_length=1, max_length=200)
    else_blocks: list[Block] | None = Field(default=None, max_length=200)


class TableColumn(StrictModel):
    header: str = Field(max_length=200)
    width_mm: float | None = Field(default=None, ge=5, le=200)
    alignment: Alignment | None = None


class TableStyle(StrictModel):
    borders: bool = True
    header_background: str | None = Field(default=None, pattern=HEX_COLOR_PATTERN)
    zebra: bool = False
    font_size_pt: float | None = Field(default=None, ge=6, le=24)


class Cell(StrictModel):
    blocks: list[Block] = Field(default_factory=list, max_length=20)


class TableRow(StrictModel):
    cells: list[Cell] = Field(min_length=1, max_length=20)


class TableRepeat(StrictModel):
    path: str = Field(pattern=PATH_PATTERN, max_length=512)
    alias: str = Field(pattern=ALIAS_PATTERN)
    max_items: int | None = Field(default=None, ge=1, le=1_000)


class Table(StrictModel):
    kind: Literal["table"] = "table"
    columns: list[TableColumn] = Field(min_length=1, max_length=20)
    rows: list[TableRow] = Field(default_factory=list, max_length=500)
    repeat: TableRepeat | None = None
    row_template: list[Cell] | None = Field(default=None, max_length=20)
    show_header: bool = True
    style: TableStyle | None = None

    @model_validator(mode="after")
    def _check_table(self) -> Table:
        width = len(self.columns)
        for index, row in enumerate(self.rows):
            if len(row.cells) != width:
                raise ValueError(
                    f"table row {index} has {len(row.cells)} cells but {width} columns are declared"
                )
        if self.repeat is not None:
            if self.row_template is None:
                raise ValueError("repeat requires row_template with one cell per column")
            if len(self.row_template) != width:
                raise ValueError(
                    f"row_template has {len(self.row_template)} cells but {width} columns are declared"
                )
        elif self.row_template is not None:
            raise ValueError("row_template is only valid together with repeat")
        return self


Block = Annotated[
    Union[Paragraph, Heading, ImageBinding, Repeat, Conditional, Table],
    Field(discriminator="kind"),
]


# --------------------------------------------------------------------------- #
# Document structure
# --------------------------------------------------------------------------- #


class DocumentMetadata(StrictModel):
    template_name: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9 _\-().]{1,120}$")
    source_schema_id: str = Field(min_length=1, max_length=120)
    design_style: DesignStyle | None = None
    intent: str | None = Field(default=None, max_length=1_000)
    generator: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2_000)


class Section(StrictModel):
    kind: Literal["section"] = "section"
    name: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9 _\-]{1,80}$")
    body: list[Block] = Field(default_factory=list, max_length=500)
    header: list[Block] | None = Field(default=None, max_length=50)
    footer: list[Block] | None = Field(default=None, max_length=50)


class Document(StrictModel):
    """Root of the IR. Serialized canonically, hashed for reproducibility."""

    kind: Literal["document"] = "document"
    ir_version: Literal["1.0"] = "1.0"
    title: str = Field(min_length=1, max_length=200)
    language: str = Field(default="en", pattern=r"^[a-z]{2}(-[A-Z]{2})?$")
    target: CompileTarget = CompileTarget.GENERIC_DOCX
    page: PageSettings = Field(default_factory=PageSettings)
    metadata: DocumentMetadata
    sections: list[Section] = Field(min_length=1, max_length=10)

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be blank")
        return value


# Recursive models: resolve forward references now that every class exists.
for _model in (Cell, Repeat, Conditional, TableRow, Table, Paragraph, Heading, Section, Document):
    _model.model_rebuild()

__all__ = [
    "ALIAS_PATTERN",
    "Alignment",
    "Block",
    "Cell",
    "CompileTarget",
    "Conditional",
    "DataType",
    "DesignStyle",
    "Document",
    "DocumentMetadata",
    "Expression",
    "ExpressionOperator",
    "FieldBinding",
    "Heading",
    "ImageBinding",
    "InlineContent",
    "PageSettings",
    "Paragraph",
    "PATH_PATTERN",
    "Repeat",
    "Section",
    "StrictModel",
    "Table",
    "TableColumn",
    "TableRepeat",
    "TableRow",
    "TableStyle",
    "TextRun",
    "TextStyle",
    "ValueFormat",
]
