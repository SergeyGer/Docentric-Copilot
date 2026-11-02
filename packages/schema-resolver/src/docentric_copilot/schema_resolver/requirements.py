"""Requirement understanding for the deterministic planner.

A business brief is prose. Before any field can be chosen, the planner needs to
know *what* was asked for: which concept, which value type and where it should
appear. This module turns a free-form brief into a small list of typed
requirements using an explicit, auditable lexicon.

Nothing here calls a model. The lexicon is deliberately explicit: every concept
lists the phrases that map to it, so a wrong decision can be traced to a rule
instead of a probability.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from .mapping import RequirementKind

_CLAUSE_SPLIT = re.compile(r"(?:[,;\n]|\band\b|\.\s|\.$)", re.IGNORECASE)
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9'-]*")


class Placement(str, Enum):
    """Where the brief asks for the content to live."""

    HEADER = "header"
    FOOTER = "footer"
    BODY = "body"
    TABLE = "table"
    TOTALS = "totals"


class Concept(str, Enum):
    """Concepts the baseline planner can satisfy deterministically."""

    COMPANY_LOGO = "company_logo"
    COMPANY_NAME = "company_name"
    COMPANY_ADDRESS = "company_address"
    COMPANY_VAT = "company_vat"
    CUSTOMER_NAME = "customer_name"
    CUSTOMER_ADDRESS = "customer_address"
    CUSTOMER_VAT = "customer_vat"
    CUSTOMER_ACCOUNT = "customer_account"
    DOCUMENT_NUMBER = "document_number"
    DOCUMENT_DATE = "document_date"
    VALID_UNTIL = "valid_until"
    CURRENCY = "currency"
    LINE_ITEMS = "line_items"
    LINE_DESCRIPTION = "line_description"
    LINE_QUANTITY = "line_quantity"
    LINE_PRICE = "line_price"
    LINE_AMOUNT = "line_amount"
    TOTAL_AMOUNT = "total_amount"
    NET_AMOUNT = "net_amount"
    TAX_AMOUNT = "tax_amount"
    BANK_DETAILS = "bank_details"
    PAYMENT_TERMS = "payment_terms"
    DELIVERY_TERMS = "delivery_terms"
    VAT_NOTICE = "vat_notice"
    TITLE = "title"


#: Concept -> phrases that select it. Longer phrases are matched first so that
#: "unit price" wins over "price" and "customer name" over "name".
LEXICON: dict[Concept, tuple[str, ...]] = {
    Concept.COMPANY_LOGO: ("company logo", "our logo", "logo", "brand mark", "letterhead image"),
    Concept.COMPANY_NAME: ("company name", "our company", "supplier name", "issuer name"),
    Concept.COMPANY_ADDRESS: ("company address", "our address", "issuer address"),
    Concept.COMPANY_VAT: ("company vat", "our vat number", "issuer vat"),
    Concept.CUSTOMER_NAME: (
        "customer name",
        "customer information",
        "customer details",
        "client name",
        "bill to",
        "bill-to",
        "bill-to customer",
        "sold to",
        "vendor name",
        "supplier name",
    ),
    Concept.CUSTOMER_ADDRESS: (
        "customer address",
        "billing address",
        "client address",
        "vendor address",
        "supplier address",
    ),
    Concept.CUSTOMER_VAT: (
        "customer vat number",
        "customer vat",
        "client vat number",
        "vendor vat",
        "supplier vat",
        "vat number",
    ),
    Concept.CUSTOMER_ACCOUNT: (
        "customer account",
        "account number",
        "customer number",
        "account id",
        "vendor account",
    ),
    Concept.DOCUMENT_NUMBER: (
        "quotation number",
        "order number",
        "invoice number",
        "document number",
        "quotation id",
        "reference number",
        "document id",
        "invoice no",
        "order no",
        "quotation no",
    ),
    Concept.DOCUMENT_DATE: (
        "quotation date",
        "invoice date",
        "order date",
        "document date",
        "issue date",
        "dates",
        "date",
    ),
    Concept.VALID_UNTIL: ("valid until", "validity", "expiry date", "due date", "payment due"),
    Concept.CURRENCY: ("currency", "currency code"),
    Concept.LINE_ITEMS: (
        "product lines",
        "line items",
        "items",
        "products",
        "rows",
        "positions",
        "line table",
        "item table",
        "table of services",
        "services table",
        "ordered items",
        "table of items",
        "table of products",
        "list of items",
    ),
    Concept.LINE_DESCRIPTION: ("description", "product name", "item description", "service name"),
    Concept.LINE_QUANTITY: ("quantity", "quantities", "qty", "units", "pieces", "count"),
    Concept.LINE_PRICE: ("unit price", "price per unit", "rate", "unit rate"),
    Concept.LINE_AMOUNT: ("line amount", "line total", "amount per line"),
    Concept.TOTAL_AMOUNT: ("total amount", "final amount", "grand total", "amount due", "total"),
    Concept.NET_AMOUNT: ("net amount", "net total", "subtotal", "net"),
    Concept.TAX_AMOUNT: ("tax amount", "vat amount", "tax total", "vat total", "sales tax", "tax"),
    Concept.BANK_DETAILS: (
        "bank details",
        "bank information",
        "iban",
        "swift",
        "payment details",
        "bank account",
    ),
    Concept.PAYMENT_TERMS: ("payment terms", "payment term", "payment condition"),
    Concept.DELIVERY_TERMS: ("delivery terms", "delivery term", "incoterm", "shipping terms"),
    Concept.VAT_NOTICE: (
        "vat notice",
        "eu vat",
        "reverse charge note",
        "reverse-charge",
        "reverse charge",
        "tax notice",
        "vat exemption",
    ),
    Concept.TITLE: ("professional", "document", "quotation", "invoice", "purchase order"),
}

#: Expected value type per concept. Used to reject candidates of the wrong type.
CONCEPT_KIND: dict[Concept, RequirementKind] = {
    Concept.COMPANY_LOGO: RequirementKind.IMAGE,
    Concept.COMPANY_NAME: RequirementKind.TEXT,
    Concept.COMPANY_ADDRESS: RequirementKind.TEXT,
    Concept.COMPANY_VAT: RequirementKind.TEXT,
    Concept.CUSTOMER_NAME: RequirementKind.TEXT,
    Concept.CUSTOMER_ADDRESS: RequirementKind.TEXT,
    Concept.CUSTOMER_VAT: RequirementKind.TEXT,
    Concept.CUSTOMER_ACCOUNT: RequirementKind.TEXT,
    Concept.DOCUMENT_NUMBER: RequirementKind.TEXT,
    Concept.DOCUMENT_DATE: RequirementKind.DATE,
    Concept.VALID_UNTIL: RequirementKind.DATE,
    Concept.CURRENCY: RequirementKind.TEXT,
    Concept.LINE_ITEMS: RequirementKind.COLLECTION,
    Concept.LINE_DESCRIPTION: RequirementKind.TEXT,
    Concept.LINE_QUANTITY: RequirementKind.NUMBER,
    Concept.LINE_PRICE: RequirementKind.NUMBER,
    Concept.LINE_AMOUNT: RequirementKind.NUMBER,
    Concept.TOTAL_AMOUNT: RequirementKind.NUMBER,
    Concept.NET_AMOUNT: RequirementKind.NUMBER,
    Concept.TAX_AMOUNT: RequirementKind.NUMBER,
    Concept.BANK_DETAILS: RequirementKind.TEXT,
    Concept.PAYMENT_TERMS: RequirementKind.TEXT,
    Concept.DELIVERY_TERMS: RequirementKind.TEXT,
    Concept.VAT_NOTICE: RequirementKind.BOOLEAN,
    Concept.TITLE: RequirementKind.TEXT,
}

#: Canonical phrase per concept, appended to the clause when ranking candidates.
#: "has a VAT number" alone is ambiguous; "has a VAT number (customer vat number)"
#: ranks the customer field first.
CONCEPT_QUERY: dict[Concept, str] = {
    Concept.COMPANY_LOGO: "company logo",
    Concept.COMPANY_NAME: "company name",
    Concept.COMPANY_ADDRESS: "company address",
    Concept.COMPANY_VAT: "company vat number",
    Concept.CUSTOMER_NAME: "customer name",
    Concept.CUSTOMER_ADDRESS: "customer address",
    Concept.CUSTOMER_VAT: "customer vat number",
    Concept.CUSTOMER_ACCOUNT: "customer account number",
    Concept.DOCUMENT_NUMBER: "document number",
    Concept.DOCUMENT_DATE: "document date",
    Concept.VALID_UNTIL: "valid until date",
    Concept.CURRENCY: "currency code",
    Concept.LINE_ITEMS: "line items collection",
    Concept.LINE_DESCRIPTION: "line description",
    Concept.LINE_QUANTITY: "line quantity",
    Concept.LINE_PRICE: "unit price",
    Concept.LINE_AMOUNT: "line amount",
    Concept.TOTAL_AMOUNT: "total amount",
    Concept.NET_AMOUNT: "net amount",
    Concept.TAX_AMOUNT: "tax amount",
    Concept.BANK_DETAILS: "bank details",
    Concept.PAYMENT_TERMS: "payment terms",
    Concept.DELIVERY_TERMS: "delivery terms",
    Concept.VAT_NOTICE: "vat notice",
    Concept.TITLE: "document title",
}

_PLACEMENT_PATTERNS: tuple[tuple[Placement, tuple[str, ...]], ...] = (
    (Placement.FOOTER, ("footer", "at the bottom", "page bottom", "in the foot")),
    (Placement.HEADER, ("header", "letterhead", "at the top", "top of the page", "masthead")),
    (Placement.TABLE, ("table", "columns", "rows")),
    (Placement.TOTALS, ("totals", "summary block", "amount block")),
)

_NEGATIONS = ("without", "no ", "exclude", "omit", "should not include", "do not include", "never")


@dataclass(frozen=True)
class Requirement:
    """One interpreted clause of a business brief."""

    id: str
    text: str
    concept: Concept
    kind: RequirementKind
    placement: Placement | None = None
    negated: bool = False

    @property
    def is_block(self) -> bool:
        """True for concepts satisfied by a group of fields."""
        return self.concept in {Concept.BANK_DETAILS, Concept.LINE_ITEMS, Concept.TITLE}


@dataclass
class RequirementSet:
    requirements: list[Requirement] = field(default_factory=list)

    def __iter__(self):
        return iter(self.requirements)

    def __len__(self) -> int:
        return len(self.requirements)

    def by_concept(self, concept: Concept) -> Requirement | None:
        for requirement in self.requirements:
            if requirement.concept is concept:
                return requirement
        return None

    def has(self, concept: Concept) -> bool:
        return self.by_concept(concept) is not None

    def placement_of(self, concept: Concept) -> Placement | None:
        requirement = self.by_concept(concept)
        return requirement.placement if requirement else None

    def concepts(self) -> set[Concept]:
        return {requirement.concept for requirement in self.requirements}


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _looks_like_title(clause: str) -> bool:
    words = _WORD.findall(clause)
    if len(words) > 9:
        return False
    lowered = _normalise(clause)
    if any(marker in lowered for marker in ("when", "unless", "if ")):
        return False
    return any(
        word in lowered for word in ("quotation", "invoice", "purchase order", "document", "order")
    )


def _match_concept(
    clause: str, *, used: set[Concept], include_title: bool = True
) -> Concept | None:
    """Pick the most specific lexicon phrase contained in the clause."""
    normalised = _normalise(clause)
    best: tuple[int, Concept] | None = None
    for concept, phrases in LEXICON.items():
        if concept in used:
            continue
        if concept is Concept.TITLE and not include_title:
            continue
        for phrase in phrases:
            if phrase not in normalised:
                continue
            score = len(phrase.split())
            if (
                best is None
                or score > best[0]
                or (score == best[0] and concept.value < best[1].value)
            ):
                best = (score, concept)
    return best[1] if best else None


def _placement_of(clause: str) -> Placement | None:
    normalised = _normalise(clause)
    for placement, phrases in _PLACEMENT_PATTERNS:
        if any(phrase in normalised for phrase in phrases):
            return placement
    return None


def _is_negated(clause: str) -> bool:
    normalised = _normalise(clause)
    return any(phrase in normalised for phrase in _NEGATIONS)


def split_clauses(brief: str, *, limit: int = 16) -> list[str]:
    """Split a brief into reviewable clauses, preserving order."""
    seen: set[str] = set()
    clauses: list[str] = []
    for raw in _CLAUSE_SPLIT.split(brief):
        clause = raw.strip(" .;:-\t*")
        if not _WORD.findall(clause):
            continue
        key = _normalise(clause)
        if key in seen:
            continue
        seen.add(key)
        clauses.append(clause[:240])
        if len(clauses) >= limit:
            break
    return clauses


def _phrase_for(clause: str, concept: Concept) -> str | None:
    normalised = _normalise(clause)
    matches = [phrase for phrase in LEXICON.get(concept, ()) if phrase in normalised]
    return max(matches, key=len) if matches else None


def _secondary_concepts(clause: str, used: set[Concept], limit: int = 2) -> list[Concept]:
    """Recover additional concepts named in the same clause.

    "product lines with quantities" mentions both the collection and the quantity
    field; "totals and bank details" mentions two blocks. The primary concept is
    removed from the sentence before the next pass so the most specific phrase
    wins each time.
    """
    found: list[Concept] = []
    remaining = _normalise(clause)
    for _ in range(limit):
        concept = _match_concept(remaining, used=used | set(found))
        if concept is None or concept is Concept.TITLE:
            break
        phrase = _phrase_for(remaining, concept)
        if phrase is None:
            break
        found.append(concept)
        remaining = remaining.replace(phrase, " ", 1)
    return found


def parse_requirements(brief: str) -> RequirementSet:
    """Interpret a brief into typed requirements.

    Each clause yields one primary concept plus up to two additional concepts
    named in the same sentence, so "items with quantities" produces both the
    collection and the quantity requirement rather than silently dropping one.
    A clause only becomes a title requirement when no other concept applies.
    """
    requirements: list[Requirement] = []
    used: set[Concept] = set()
    counter = 0

    def add(clause: str, concept: Concept, placement: Placement | None, negated: bool) -> None:
        nonlocal counter
        if concept in used:
            return
        used.add(concept)
        requirements.append(
            Requirement(
                id=f"req_{counter:02d}",
                text=clause,
                concept=concept,
                kind=CONCEPT_KIND.get(concept, RequirementKind.TEXT),
                placement=placement,
                negated=negated,
            )
        )
        counter += 1

    for clause in split_clauses(brief):
        placement = _placement_of(clause)
        negated = _is_negated(clause)
        primary = _match_concept(clause, used=used, include_title=False)
        if primary is None:
            if _looks_like_title(clause) and _match_concept(clause, used=set()) is Concept.TITLE:
                add(clause, Concept.TITLE, placement, negated)
            continue

        add(clause, primary, placement, negated)
        remaining = _normalise(clause)
        phrase = _phrase_for(remaining, primary)
        if phrase:
            remaining = remaining.replace(phrase, " ", 1)
        for _ in range(2):
            secondary = _match_concept(remaining, used=used, include_title=False)
            if secondary is None:
                break
            add(clause, secondary, placement, negated)
            phrase = _phrase_for(remaining, secondary)
            if phrase is None:
                break
            remaining = remaining.replace(phrase, " ", 1)

    return RequirementSet(requirements=requirements)


__all__ = [
    "CONCEPT_KIND",
    "LEXICON",
    "Concept",
    "Placement",
    "Requirement",
    "RequirementSet",
    "parse_requirements",
    "split_clauses",
]
