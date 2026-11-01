"""Deterministic baseline planner.

This is **not** a language model. It is a reproducible, explainable planner that
maps schema roles to a conventional business layout. It powers the offline
``mock`` provider, gives the demo a working end-to-end path without credentials,
and acts as the control baseline in the AI evaluation harness: an LLM that cannot
beat this baseline has no product value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from docentric_copilot.ddsp_parser.models import NormalizedSchema, SchemaNode
from docentric_copilot.schema_resolver.search import tokenize
from docentric_copilot.template_ir import (
    Alignment,
    Cell,
    CompileTarget,
    Conditional,
    Document,
    DocumentMetadata,
    Expression,
    ExpressionOperator,
    FieldBinding,
    Heading,
    ImageBinding,
    PageSettings,
    Paragraph,
    Repeat,
    Section,
    Table,
    TableColumn,
    TableRepeat,
    TableStyle,
    TextRun,
    TextStyle,
    ValueFormat,
)

BASELINE_VERSION = "heuristic-baseline-v1"

_DOC_KINDS: dict[str, tuple[str, ...]] = {
    "quotation": ("quotation", "quote", "offer", "proposal", "estimate"),
    "invoice": ("invoice", "bill", "credit note"),
    "purchase_order": ("purchase order", "supplier order", "procurement"),
}

_TITLES = {
    "quotation": "Sales Quotation",
    "invoice": "Tax Invoice",
    "purchase_order": "Purchase Order",
    "document": "Document",
}

_ACCENTS = {
    "modern": "#0F2A54",
    "classic": "#1A1A1A",
    "minimal": "#404040",
}


@dataclass(frozen=True)
class Roles:
    """Semantic roles discovered in a schema, with the evidence path for each."""

    document_kind: str = "document"
    title: str = "Document"
    logo: str | None = None
    company_name: str | None = None
    company_address: str | None = None
    company_vat: str | None = None
    party_label: str = "Customer"
    party_name: str | None = None
    party_address: str | None = None
    party_vat: str | None = None
    party_id: str | None = None
    number: str | None = None
    date: str | None = None
    secondary_date: str | None = None
    secondary_date_label: str = "Valid until"
    currency: str | None = None
    payment_terms: str | None = None
    delivery_terms: str | None = None
    net: str | None = None
    tax: str | None = None
    total: str | None = None
    lines: str | None = None
    line_description: str | None = None
    line_item: str | None = None
    line_quantity: str | None = None
    line_price: str | None = None
    line_amount: str | None = None
    bank_fields: tuple[str, ...] = ()
    vat_flag: str | None = None
    extras: dict[str, str] = field(default_factory=dict)

    @property
    def repeat_alias(self) -> str:
        return "line"


def _path_tokens(path: str) -> set[str]:
    return set(tokenize(path.replace(".", " ")))


def _score(path: str, include: tuple[str, ...], exclude: tuple[str, ...]) -> int:
    """Weight a leaf-name match three times higher than an ancestor match."""
    tokens = _path_tokens(path)
    if any(token in tokens for token in exclude):
        return 0
    name_tokens = set(tokenize(path.rsplit(".", 1)[-1]))
    score = 0
    for token in include:
        if token in name_tokens:
            score += 3
        elif token in tokens:
            score += 1
    return score


def _best(
    schema: NormalizedSchema,
    include: tuple[str, ...],
    *,
    exclude: tuple[str, ...] = (),
    types: set[str] | None = None,
    collection: bool | None = False,
    prefix: str | None = None,
) -> str | None:
    best_path: str | None = None
    best_score = 0
    for path in schema.paths:
        node = schema.node(path)
        if node is None:
            continue
        if collection is not None and node.collection is not collection:
            continue
        if collection is False and node.children:
            continue
        if types is not None and node.data_type not in types:
            continue
        if prefix is not None and not path.startswith(f"{prefix}."):
            continue
        score = _score(path, include, exclude)
        if score <= 0:
            continue
        if score > best_score or (score == best_score and best_path is not None and path < best_path):
            best_path, best_score = path, score
    return best_path


def _lines_collection(schema: NormalizedSchema) -> str | None:
    candidates = [node for node in schema.collections() if _score(node.path, ("line", "item"), ()) > 0]
    if not candidates:
        candidates = schema.collections()
    if not candidates:
        return None
    return sorted(candidates, key=lambda node: (node.path.count("."), node.path))[0].path


def _line_children(schema: NormalizedSchema, lines: str | None) -> list[SchemaNode]:
    if lines is None:
        return []
    node = schema.node(lines)
    if node is None:
        return []
    return [child for child in node.children if not child.children and not child.collection]


def _pick_child(
    children: list[SchemaNode], include: tuple[str, ...], exclude: tuple[str, ...] = ()
) -> str | None:
    best: tuple[int, str] | None = None
    for child in children:
        score = _score(child.path, include, exclude)
        if score <= 0:
            continue
        if best is None or score > best[0] or (score == best[0] and child.path < best[1]):
            best = (score, child.path)
    return best[1] if best else None


def detect_document_kind(requirement: str, schema: NormalizedSchema) -> str:
    lowered = requirement.lower()
    for kind, keywords in _DOC_KINDS.items():
        if any(keyword in lowered for keyword in keywords):
            return kind
    joined = " ".join(schema.section_names + schema.paths[:40]).lower()
    if "invoice" in joined:
        return "invoice"
    if "purchaseorder" in joined:
        return "purchase_order"
    if "quotation" in joined or "quote" in joined:
        return "quotation"
    return "document"


def _text_nodes(schema: NormalizedSchema) -> list[SchemaNode]:
    return [
        node
        for node in (schema.node(path) for path in schema.paths)
        if node is not None and not node.children and not node.collection
    ]


def discover_roles(schema: NormalizedSchema, requirement: str) -> Roles:
    kind = detect_document_kind(requirement, schema)
    leaves = _text_nodes(schema)
    logolf = _best(schema, ("logo", "image", "picture"), types={"image"})

    company_name = _best(schema, ("company", "name"), exclude=("customer", "vendor", "client"))
    company_address = _best(schema, ("company", "address"), exclude=("customer", "vendor"))
    company_vat = _best(schema, ("company", "vat"), exclude=("customer", "vendor"))

    party_tokens: tuple[str, ...] = (
        ("vendor", "supplier") if kind == "purchase_order" else ("customer", "client", "buyer")
    )
    party_name = _best(schema, (*party_tokens, "name"))
    party_address = _best(schema, (*party_tokens, "address"))
    party_vat = _best(schema, (*party_tokens, "vat"))
    party_id = _best(schema, (*party_tokens, "id", "account", "number"), exclude=("name", "vat"))

    lines = _lines_collection(schema)
    children = _line_children(schema, lines)
    line_description = _pick_child(children, ("description", "name"))
    line_item = _pick_child(children, ("item", "id", "code", "number"), exclude=("description",))
    line_quantity = _pick_child(children, ("quantity", "qty", "count"))
    line_price = _pick_child(children, ("price", "rate"), exclude=("amount",))
    line_amount = _pick_child(children, ("amount", "total"), exclude=("price",))

    number = _best(schema, ("quotation", "invoice", "order", "number", "document", "id"))
    if number is None:
        number = _best(
            schema,
            ("id",),
            exclude=("account", "item", "vendor", "customer", "vat", "iban"),
        )
    date = _best(schema, ("date",), types={"date"}, exclude=("due", "valid", "delivery"))
    secondary_date = _best(schema, ("valid", "due", "delivery"), types={"date"})
    currency = _best(schema, ("currency", "ccy"))
    payment_terms = _best(schema, ("payment", "terms"))
    delivery_terms = _best(schema, ("delivery", "terms", "incoterm"))
    net = _best(schema, ("net",), types={"number"})
    tax = _best(schema, ("tax", "vat"), types={"number"})
    total = _best(schema, ("total", "gross"), types={"number"}, exclude=("line",))
    if total is None:
        total = _best(schema, ("amount",), types={"number"}, exclude=("line", "net", "tax"))

    bank_fields = tuple(
        sorted(
            node.path
            for node in leaves
            if _score(node.name, ("bank", "iban", "swift", "bic"), ()) > 0
            or _score(node.path, ("bank", "iban", "swift", "bic"), ()) > 0
        )
    )
    vat_flag = _best(schema, ("eu", "reverse", "charge", "vatnotice", "show"), types={"boolean"})
    secondary_label = "Valid until" if secondary_date and "valid" in secondary_date.lower() else "Due date"

    return Roles(
        document_kind=kind,
        title=_TITLES[kind],
        logo=logolf,
        company_name=company_name,
        company_address=company_address,
        company_vat=company_vat,
        party_label="Vendor" if kind == "purchase_order" else "Customer",
        party_name=party_name,
        party_address=party_address,
        party_vat=party_vat,
        party_id=party_id,
        number=number,
        date=date,
        secondary_date=secondary_date,
        secondary_date_label=secondary_label,
        currency=currency,
        payment_terms=payment_terms,
        delivery_terms=delivery_terms,
        net=net,
        tax=tax,
        total=total,
        lines=lines,
        line_description=line_description,
        line_item=line_item,
        line_quantity=line_quantity,
        line_price=line_price,
        line_amount=line_amount,
        bank_fields=bank_fields,
        vat_flag=vat_flag,
    )


def _style(
    color: str | None = None,
    size: float | None = None,
    bold: bool | None = None,
    italic: bool | None = None,
) -> TextStyle:
    return TextStyle(bold=bold, italic=italic, font_size_pt=size, color=color)


def _label_value(label: str, path: str, *, fmt: ValueFormat | None = None) -> Paragraph:
    return Paragraph(
        runs=[
            TextRun(text=f"{label}: ", style=_style(bold=True)),
            FieldBinding(path=path, format=fmt),
        ]
    )


@dataclass(frozen=True)
class _Column:
    label: str
    path: str
    width_mm: float
    align: Alignment | None = None
    fmt: ValueFormat | None = None
    decimals: int | None = None


def build_document(
    schema: NormalizedSchema,
    requirement: str,
    *,
    design_style: str = "modern",
    language: str = "en",
    target: str = CompileTarget.GENERIC_DOCX.value,
) -> Document:
    """Compose a conventional business document from discovered roles."""
    roles = discover_roles(schema, requirement)
    accent = _ACCENTS.get(design_style, _ACCENTS["modern"])
    body: list = []
    header: list = []
    footer: list = []

    # ---------------------------------------------------------------- header
    if roles.logo:
        header.append(ImageBinding(path=roles.logo, width_mm=42, alt_text="Company logo"))
    if roles.company_name:
        header.append(
            Paragraph(runs=[FieldBinding(path=roles.company_name, style=_style(accent, 14, True))])
        )
    identity_runs: list = []
    if roles.company_address:
        identity_runs.append(FieldBinding(path=roles.company_address, style=_style(size=8.5)))
    if roles.company_vat:
        if identity_runs:
            identity_runs.append(TextRun(text="  ·  ", style=_style(size=8.5)))
        identity_runs.extend([TextRun(text="VAT: ", style=_style(size=8.5))])
        identity_runs.append(FieldBinding(path=roles.company_vat, style=_style(size=8.5)))
    if identity_runs:
        header.append(Paragraph(runs=identity_runs))

    # ------------------------------------------------------------------ body
    body.append(Heading(level=1, runs=[TextRun(text=roles.title)], style=_style(accent, 18, True)))

    meta_runs: list = []
    if roles.number:
        meta_runs.extend([TextRun(text="No.: "), FieldBinding(path=roles.number)])
    if roles.date:
        if meta_runs:
            meta_runs.append(TextRun(text="    "))
        meta_runs.extend(
            [TextRun(text="Date: "), FieldBinding(path=roles.date, format=ValueFormat.DATE_ISO)]
        )
    if roles.secondary_date:
        if meta_runs:
            meta_runs.append(TextRun(text="    "))
        meta_runs.extend(
            [
                TextRun(text=f"{roles.secondary_date_label}: "),
                FieldBinding(path=roles.secondary_date, format=ValueFormat.DATE_ISO),
            ]
        )
    if roles.currency:
        if meta_runs:
            meta_runs.append(TextRun(text="    "))
        meta_runs.extend([TextRun(text="Currency: "), FieldBinding(path=roles.currency)])
    if meta_runs:
        body.append(Paragraph(runs=meta_runs, space_after_pt=10))

    if roles.party_name or roles.party_address:
        body.append(Heading(level=2, runs=[TextRun(text=roles.party_label)], style=_style(accent, 12, True)))
        if roles.party_name:
            body.append(Paragraph(runs=[FieldBinding(path=roles.party_name, style=_style(bold=True))]))
        if roles.party_id:
            body.append(_label_value("Account", roles.party_id))
        if roles.party_address:
            body.append(Paragraph(runs=[FieldBinding(path=roles.party_address, style=_style(size=9.5))]))
        if roles.party_vat:
            body.append(_label_value("VAT number", roles.party_vat))

    # ----------------------------------------------------------------- table
    columns: list[_Column] = []
    if roles.line_description:
        columns.append(_Column("Description", roles.line_description, 70.0))
    elif roles.line_item:
        columns.append(_Column("Item", roles.line_item, 70.0))
    if roles.line_quantity:
        columns.append(_Column("Qty", roles.line_quantity, 16.0, Alignment.RIGHT, ValueFormat.NUMBER, 0))
    if roles.line_price:
        columns.append(_Column("Unit price", roles.line_price, 28.0, Alignment.RIGHT, ValueFormat.NUMBER, 2))
    if roles.line_amount:
        columns.append(_Column("Amount", roles.line_amount, 30.0, Alignment.RIGHT, ValueFormat.NUMBER, 2))

    if roles.lines and columns:
        body.append(Heading(level=2, runs=[TextRun(text="Items")], style=_style(accent, 12, True)))
        alias = roles.repeat_alias
        body.append(
            Table(
                columns=[TableColumn(header=c.label, width_mm=c.width_mm, alignment=c.align) for c in columns],
                repeat=TableRepeat(path=roles.lines, alias=alias),
                row_template=[
                    Cell(
                        blocks=[
                            Paragraph(
                                runs=[
                                    FieldBinding(
                                        path=f"{alias}.{c.path.rsplit('.', 1)[-1]}",
                                        format=c.fmt,
                                        decimals=c.decimals,
                                    )
                                ],
                                style=TextStyle(alignment=c.align),
                            )
                        ]
                    )
                    for c in columns
                ],
                show_header=True,
                style=TableStyle(
                    borders=True, header_background="#EEF2F7", zebra=True, font_size_pt=9.5
                ),
            )
        )

    # ---------------------------------------------------------------- totals
    if roles.net:
        body.append(_label_value("Net", roles.net, fmt=ValueFormat.NUMBER))
    if roles.tax:
        body.append(_label_value("Tax", roles.tax, fmt=ValueFormat.NUMBER))
    if roles.total:
        body.append(
            Paragraph(
                runs=[
                    TextRun(text="Total: ", style=_style(bold=True, size=11)),
                    FieldBinding(
                        path=roles.total,
                        format=ValueFormat.NUMBER,
                        decimals=2,
                        style=_style(bold=True, size=11),
                    ),
                ],
                style=TextStyle(alignment=Alignment.RIGHT),
                space_after_pt=6,
            )
        )
    if roles.payment_terms:
        body.append(_label_value("Payment terms", roles.payment_terms))
    if roles.delivery_terms:
        body.append(_label_value("Delivery terms", roles.delivery_terms))

    # ------------------------------------------------------- conditional VAT
    if roles.vat_flag:
        notice_runs: list = [
            TextRun(
                text=(
                    "VAT notice: this document follows the EU VAT rules applicable to the "
                    "customer tax status."
                )
            )
        ]
        if roles.party_vat:
            notice_runs.extend([TextRun(text=" Customer VAT number: "), FieldBinding(path=roles.party_vat)])
        body.append(
            Conditional(
                condition=Expression(operator=ExpressionOperator.EQUALS, field=roles.vat_flag, value=True),
                then_blocks=[
                    Paragraph(runs=notice_runs, style=TextStyle(italic=True, font_size_pt=9), space_after_pt=8)
                ],
            )
        )

    # ---------------------------------------------------------------- footer
    bank_runs: list = []
    for index, path in enumerate(roles.bank_fields):
        if index:
            bank_runs.append(TextRun(text="  ·  "))
        bank_runs.append(TextRun(text=f"{_humanize(path.rsplit('.', 1)[-1])}: "))
        bank_runs.append(FieldBinding(path=path))
    if bank_runs:
        footer.append(Paragraph(runs=[TextRun(text="Bank details")], style=_style(size=8.5, bold=True)))
        footer.append(Paragraph(runs=bank_runs, style=TextStyle(font_size_pt=8.5)))

    if not body:
        body.append(Paragraph(runs=[TextRun(text="This schema does not expose any fields to bind.")]))

    normalized_language = language.lower()[:2] if re.match(r"^[a-zA-Z]{2}", language) else "en"
    metadata = DocumentMetadata(
        template_name=f"{roles.document_kind}_template",
        source_schema_id=schema.schema_id,
        design_style=design_style if design_style in _ACCENTS else "modern",
        intent=requirement.strip()[:1_000] or None,
        generator=BASELINE_VERSION,
    )

    return Document(
        title=roles.title,
        language=normalized_language,
        target=CompileTarget(target),
        page=PageSettings(),
        metadata=metadata,
        sections=[
            Section(name="Main", body=body, header=header or None, footer=footer or None),
        ],
    )


def _humanize(identifier: str) -> str:
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", identifier)
    return spaced[:40]


__all__ = ["BASELINE_VERSION", "Roles", "build_document", "detect_document_kind", "discover_roles"]
