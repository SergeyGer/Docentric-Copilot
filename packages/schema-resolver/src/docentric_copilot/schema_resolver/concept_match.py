"""Match bound document paths against interpreted requirements.

The mapping report answers a single question per clause: *did the produced
template actually bind what the brief asked for?* This module holds the evidence
rules — token sets, forbiddens and value types — used to answer it without a
model.
"""

from __future__ import annotations

from dataclasses import dataclass

from docentric_copilot.ddsp_parser.models import NormalizedSchema, SchemaNode

from .mapping import RequirementKind
from .requirements import Concept
from .search import tokenize


@dataclass(frozen=True, slots=True)
class ConceptMatcher:
    """Evidence rules for one concept.

    ``include`` tokens may appear in the field name or anywhere in the path;
    ``context`` is an any-of group that must appear somewhere in the path (it
    separates a customer's name from a bank's name); ``require_collection``
    restricts a concept to a repeating collection node.
    """

    include: tuple[str, ...]
    exclude: tuple[str, ...] = ()
    types: frozenset[str] = frozenset()
    context: tuple[str, ...] = ()
    require_collection: bool = False
    name_only: bool = False

    def matches(self, node: SchemaNode) -> bool:
        own = set(tokenize(node.name))
        full = set(tokenize(node.path.replace(".", " ")))
        if any(token in full for token in self.exclude):
            return False
        if self.require_collection and not node.collection:
            return False
        if self.context and not any(token in full for token in self.context):
            return False
        haystack = own if self.name_only else (own | full)
        if not any(token in haystack for token in self.include):
            return False
        return not (self.types and node.data_type not in self.types)


_PARTY = ("customer", "client", "billto", "soldto", "vendor", "supplier", "buyer")
_COMPANY = ("company", "issuer", "organization", "organisation")
_LINE = ("line", "item", "product", "row")

MATCHERS: dict[Concept, ConceptMatcher] = {
    Concept.COMPANY_LOGO: ConceptMatcher(
        ("logo", "image", "picture", "brand"), types=frozenset({"image"})
    ),
    Concept.COMPANY_NAME: ConceptMatcher(
        ("name",), ("customer", "client", "vendor", "supplier"), context=_COMPANY
    ),
    Concept.COMPANY_ADDRESS: ConceptMatcher(("address",), context=_COMPANY),
    Concept.COMPANY_VAT: ConceptMatcher(("vat",), context=_COMPANY),
    Concept.CUSTOMER_NAME: ConceptMatcher(("name",), context=_PARTY),
    Concept.CUSTOMER_ADDRESS: ConceptMatcher(("address",), context=_PARTY),
    Concept.CUSTOMER_VAT: ConceptMatcher(("vat",), context=_PARTY),
    Concept.CUSTOMER_ACCOUNT: ConceptMatcher(
        ("account", "accountnum", "customerid"), context=_PARTY
    ),
    Concept.DOCUMENT_NUMBER: ConceptMatcher(
        ("number", "num", "id", "no"),
        ("account", "vat", "item", "line", "currency", "tax"),
        name_only=True,
    ),
    Concept.DOCUMENT_DATE: ConceptMatcher(
        ("date",), ("valid", "due", "delivery"), frozenset({"date", "string"})
    ),
    Concept.VALID_UNTIL: ConceptMatcher(
        ("valid", "due", "expiry"), (), frozenset({"date", "string"})
    ),
    Concept.CURRENCY: ConceptMatcher(("currency", "ccy")),
    Concept.LINE_ITEMS: ConceptMatcher(("line", "item", "product", "row"), require_collection=True),
    Concept.LINE_DESCRIPTION: ConceptMatcher(("description", "product"), context=_LINE),
    Concept.LINE_QUANTITY: ConceptMatcher(
        ("quantity", "qty"), context=_LINE, types=frozenset({"number", "any"})
    ),
    Concept.LINE_PRICE: ConceptMatcher(
        ("price", "rate"), context=_LINE, types=frozenset({"number", "any"})
    ),
    Concept.LINE_AMOUNT: ConceptMatcher(
        ("amount",), ("total", "tax", "net", "gross"), frozenset({"number", "any"}), context=_LINE
    ),
    Concept.TOTAL_AMOUNT: ConceptMatcher(
        ("total", "gross", "amount"), ("line", "tax", "net", "unit"), frozenset({"number", "any"})
    ),
    Concept.NET_AMOUNT: ConceptMatcher(("net",), ("line",), frozenset({"number", "any"})),
    Concept.TAX_AMOUNT: ConceptMatcher(
        ("tax", "vat"), ("number", "notice"), frozenset({"number", "any"})
    ),
    Concept.BANK_DETAILS: ConceptMatcher(("bank", "iban", "swift", "bic")),
    Concept.PAYMENT_TERMS: ConceptMatcher(("payment", "terms")),
    Concept.DELIVERY_TERMS: ConceptMatcher(("delivery", "incoterm", "shipping")),
    Concept.VAT_NOTICE: ConceptMatcher(
        ("iseu", "reverse", "charge", "vatnotice", "eu"), (), frozenset({"boolean", "any"})
    ),
    Concept.TITLE: ConceptMatcher(("title", "name")),
}


def paths_for_concept(
    schema: NormalizedSchema, concept: Concept, bound_paths: set[str]
) -> list[str]:
    """Return bound paths that satisfy ``concept`` (most specific first)."""
    matcher = MATCHERS.get(concept)
    if matcher is None:
        return []
    matched = [
        path
        for path in sorted(bound_paths)
        if (node := schema.node(path)) is not None and matcher.matches(node)
    ]
    # Prefer the shallowest match: "Customer.Name" beats "Customer.Name.Line".
    return sorted(matched, key=lambda path: (path.count("."), path))


def matches_kind(kind: RequirementKind, node: SchemaNode | None) -> bool:
    if node is None:
        return False
    if kind is RequirementKind.ANY:
        return True
    if kind is RequirementKind.COLLECTION:
        return node.collection
    if kind is RequirementKind.IMAGE:
        return node.data_type == "image"
    if kind is RequirementKind.NUMBER:
        return node.data_type in {"number", "any"}
    if kind is RequirementKind.DATE:
        return node.data_type in {"date", "string", "any"}
    if kind is RequirementKind.BOOLEAN:
        return node.data_type in {"boolean", "any"}
    return node.data_type in {"string", "any"}


__all__ = ["MATCHERS", "ConceptMatcher", "matches_kind", "paths_for_concept"]
