"""Deterministic requirement decomposition and evidence-backed candidate retrieval.

The v0.10 planner sent the whole normalized schema to the model. Recall was
near 1.0 but precision was 0.18-0.23 because a provider could bind every
plausible field, including fields the brief never requested. This module is the
v0.11 pre-filter: it decomposes the brief into atomic requirements, retrieves
only schema nodes that satisfy the requested entity, attribute, type, collection
scope and condition, and bounds the candidate list that reaches the provider.

Design rules (v0.11 P0, issue #25):

* retrieval only sees :class:`NormalizedSchema` evidence - no prompt-copied
  paths and no gold labels;
* every hard constraint is explicit (type, entity/namespace, collection scope,
  condition, explicit exclusions);
* ranking is deterministic: score, depth, path;
* a weak or tied result is reported as ``ambiguous``/``missing`` instead of
  guessing. The model receives the bounded list and may choose only from it;
* the list is bounded per requirement and in total.

The module does no I/O and makes no model calls.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from docentric_copilot.ddsp_parser.models import NormalizedSchema, SchemaNode
from docentric_copilot.schema_resolver.concept_match import MATCHERS
from docentric_copilot.schema_resolver.search import (
    SYNONYMS,
    expand,
    infer_kind,
    tokenize,
)

#: Upper bound of distinct binding candidates sent to a provider. The long-table
#: case asks for 12 columns; 24 leaves room for alternatives without exposing a
#: whole schema.
MAX_CANDIDATES = 24
#: Upper bound per atomic requirement.
MAX_PER_REQUIREMENT = 4
#: Minimum raw evidence for a candidate to be reportable at all.
MIN_SCORE = 1.1
#: Decomposition is bounded so an adversarial brief cannot create unlimited rows.
_MAX_ATOMS = 24

_PARTY_ENTITIES = ("customer", "vendor", "company")
_STRUCTURAL_ENTITIES = ("line", "task")
_DOCUMENT_TOKENS = frozenset(
    {
        "invoice",
        "quotation",
        "quote",
        "order",
        "document",
        "report",
        "serviceorder",
        "purchaseorder",
        "salesorder",
        "sale",
        "purchase",
    }
)
_PLACEMENT_TOKENS = frozenset({"header", "footer", "page", "first", "firstpage", "title"})
_GENERIC_ATTRIBUTES = frozenset(
    {
        "name",
        "number",
        "no",
        "id",
        "identifier",
        "date",
        "amount",
        "total",
        "description",
        "text",
        "quantity",
        "price",
        "rate",
        "unit",
        "note",
        "value",
        "contact",
        "address",
        "terms",
        "hours",
        "percent",
    }
)
_NO_STRUCTURAL_INHERIT = frozenset(
    {
        "number",
        "id",
        "reference",
        "date",
        "vat_number",
        "name",
        "address",
        "account_number",
        "bank_details",
        "currency",
        "terms",
        "logo",
        "image",
        "contact_email",
    }
)
_NAMESPACE_ATTRIBUTES = frozenset(
    {"number", "date", "total", "amount", "tax", "net", "gross", "reference", "id", "code"}
)
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "for",
        "with",
        "in",
        "on",
        "to",
        "from",
        "create",
        "make",
        "generate",
        "show",
        "include",
        "including",
        "display",
        "put",
        "place",
        "add",
        "use",
        "using",
        "our",
        "their",
        "its",
        "is",
        "are",
        "be",
        "when",
        "if",
        "each",
        "all",
        "every",
        "by",
        "as",
        "at",
        "it",
        "one",
        "way",
        "either",
        "directly",
        "below",
        "top",
        "bottom",
        "left",
        "right",
        "under",
        "nested",
        "beneath",
        "page",
        "document",
        "body",
        "header",
        "footer",
        "table",
        "list",
        "column",
        "columns",
        "row",
        "rows",
        "text",
        "long",
        "wide",
        "enough",
        "must",
        "handle",
        "keep",
        "only",
        "also",
        "then",
        "than",
        "this",
        "that",
        "these",
        "those",
        "can",
        "so",
        "pay",
        "us",
        "please",
        "like",
        "want",
        "need",
        "should",
        "would",
        "could",
        "there",
        "where",
        "which",
        "who",
        "whom",
        "whose",
        "why",
        "how",
        "into",
        "over",
        "per",
        "via",
        "set",
        "new",
        "current",
        "full",
        "internal",
        "showing",
        "appears",
        "alway",
        "final",
        "grand",
        "dan",
        "shown",
        "den",
        "des",
        "die",
        "das",
        "der",
        "im",
        "le",
        "la",
        "les",
        "du",
        "de",
        "son",
        "sa",
        "ses",
        "un",
        "une",
        "avec",
        "dans",
        "pour",
        "sur",
        "au",
        "aux",
        "et",
    }
)

#: Bounded bilingual lexicon for the committed multilingual gold fixtures. It is
#: deliberately small: this is fixture support, not a general translator.
_TRANSLATIONS: tuple[tuple[str, str], ...] = (
    ("bedingungen für die lieferung", "delivery terms"),
    ("conditions de livraison", "delivery terms"),
    ("lieferbedingungen", "delivery terms"),
    ("bestellnummer", "order number"),
    ("bestelldatum", "order date"),
    ("angebotsnummer", "quotation number"),
    ("angebotsdatum", "quotation date"),
    ("firmenname", "company name"),
    ("gesamtbetrag", "total amount"),
    ("lieferanten", "vendor"),
    ("lieferant", "vendor"),
    ("fournisseur", "vendor"),
    ("bestellung", "purchase order"),
    ("angebot", "quotation"),
    ("rechnung", "invoice"),
    ("firmen", "company"),
    ("firma", "company"),
    ("adresse", "address"),
    ("anschrift", "address"),
    ("namen", "name"),
    ("noms", "name"),
    ("nom", "name"),
    ("name", "name"),
    ("nummer", "number"),
    ("menge", "quantity"),
    ("quantität", "quantity"),
    ("quantité", "quantity"),
    ("beschreibung", "description"),
    ("gesamt", "total"),
    ("betrag", "amount"),
    ("montant", "amount"),
    ("preis", "price"),
    ("prix", "price"),
    ("rabatt", "discount"),
    ("remise", "discount"),
    ("stunden", "hours"),
    ("heures", "hours"),
    ("aufgaben", "tasks"),
    ("aufgabe", "task"),
    ("tâches", "tasks"),
    ("tâche", "task"),
    ("einheit", "unit"),
    ("unité", "unit"),
    ("währung", "currency"),
    ("devise", "currency"),
    ("lieferdatum", "delivery date"),
    ("lieferung", "delivery"),
    ("livraison", "delivery"),
    ("dokument", "document"),
    ("corps", "body"),
    ("zeige", "show"),
    ("affichez", "show"),
    ("afficher", "show"),
)

_CLAUSE_SPLIT = re.compile(r"(?:[,;]|\band\b|\bund\b|\bet\b|\.\s|\.$)", re.IGNORECASE)
_EXCLUSION = re.compile(
    r"(?:do not|don't|must not|should not|without|exclude|omit|never use|not the)\b(.+)",
    re.IGNORECASE,
)
_ENTITY_ALIASES: dict[str, tuple[str, ...]] = {
    "customer": ("customer", "client", "buyer", "billto", "soldto", "cust"),
    "vendor": ("vendor", "supplier", "seller", "payee"),
    "company": ("company", "issuer", "organization", "organisation", "firm"),
    "bank": ("bank", "iban", "swift", "bic"),
    "line": ("line", "item", "product", "row", "service", "article"),
    "task": ("task", "subtask"),
    "parameter": ("parameter", "setting", "flag"),
}
_ENTITY_LOOKUP: dict[str, str] = {
    alias: entity for entity, aliases in _ENTITY_ALIASES.items() for alias in aliases
}


@dataclass(frozen=True, slots=True)
class RequirementAtom:
    """One atomic requirement the brief asks for."""

    id: str
    text: str
    concept: str | None
    entities: tuple[str, ...] = ()
    attributes: tuple[str, ...] = ()
    synonyms: tuple[str, ...] = ()
    expected_type: str | None = None
    condition: bool = False
    placement: str | None = None
    collection: bool = False

    @property
    def entity(self) -> str | None:
        return self.entities[0] if self.entities else None

    @property
    def label(self) -> str:
        return self.concept or "-".join(self.attributes) or self.text[:40]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "concept": self.concept,
            "entities": list(self.entities),
            "attributes": list(self.attributes),
            "synonyms": list(self.synonyms),
            "expected_type": self.expected_type,
            "condition": self.condition,
            "placement": self.placement,
            "collection": self.collection,
        }


@dataclass(frozen=True, slots=True)
class CandidateEvidence:
    """One schema-backed candidate for one requirement atom."""

    path: str
    data_type: str
    collection: bool
    requirement_id: str
    score: float
    reasons: tuple[str, ...]
    expected_type: str | None
    scope: str | None
    decision: str
    primary: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "data_type": self.data_type,
            "collection": self.collection,
            "requirement_id": self.requirement_id,
            "score": round(self.score, 4),
            "reasons": list(self.reasons),
            "expected_type": self.expected_type,
            "scope": self.scope,
            "decision": self.decision,
            "primary": self.primary,
        }


@dataclass(frozen=True, slots=True)
class CandidateSet:
    """Bounded, deterministic candidate evidence for one brief."""

    atoms: tuple[RequirementAtom, ...]
    candidates: tuple[CandidateEvidence, ...]
    exclusions: tuple[str, ...] = ()
    fallback: bool = False
    table_hint: str | None = None

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(candidate.path for candidate in self.candidates)

    def for_requirement(self, requirement_id: str) -> tuple[CandidateEvidence, ...]:
        return tuple(
            candidate for candidate in self.candidates if candidate.requirement_id == requirement_id
        )

    def evidence_for(self, path: str) -> CandidateEvidence | None:
        matches = [candidate for candidate in self.candidates if candidate.path == path]
        if not matches:
            return None
        return max(matches, key=lambda candidate: (candidate.score, candidate.primary))

    def decision_for(self, requirement_id: str) -> str:
        matches = self.for_requirement(requirement_id)
        if not matches:
            return "missing"
        return matches[0].decision

    def missing_atoms(self) -> tuple[RequirementAtom, ...]:
        return tuple(
            atom for atom in self.atoms if not atom.collection and not self.for_requirement(atom.id)
        )

    def ambiguous_atoms(self) -> tuple[RequirementAtom, ...]:
        return tuple(atom for atom in self.atoms if self.decision_for(atom.id) == "ambiguous")

    def summary(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "fallback_to_full_schema": self.fallback,
            "requirements": len(self.atoms),
            "candidates": len(self.candidates),
            "exclusions": list(self.exclusions),
            "missing_requirements": [atom.id for atom in self.missing_atoms()],
            "ambiguous_requirements": [atom.id for atom in self.ambiguous_atoms()],
            "max_candidates": MAX_CANDIDATES,
            "table_hint": self.table_hint,
        }

    def format_prompt(self) -> str:
        """Render the bounded candidate table for the provider prompt."""
        lines: list[str] = []
        if self.table_hint:
            lines.append(self.table_hint)
        for atom in self.atoms:
            matches = self.for_requirement(atom.id)
            kind = atom.expected_type or "any"
            context = atom.placement or "body"
            if not matches:
                if atom.collection:
                    # A collection atom is represented by the scope column of
                    # its fields; it does not need a separate missing row.
                    continue
                lines.append(
                    f"- {atom.id} | {atom.label} | {kind} | NO SUPPORTED BINDING "
                    f"| context={context} | omit this requirement; do not invent a path"
                )
                continue
            effective_context = atom.placement or (
                "repeat" if any(candidate.scope for candidate in matches) else "body"
            )
            decision = matches[0].decision
            if decision == "ambiguous":
                options = [candidate for candidate in matches if not candidate.collection] or list(
                    matches
                )
                rendered = " | ".join(
                    f"{candidate.path} ({candidate.data_type})" for candidate in options
                )
                scopes = sorted(
                    {candidate.scope for candidate in matches if candidate.scope is not None}
                )
                scope_text = f" | collections={', '.join(scopes)}" if scopes else ""
                lines.append(
                    f"- {atom.id} | {atom.label} | {kind} | AMBIGUOUS: {rendered} "
                    f"| context={effective_context}{scope_text} "
                    f"| choose exactly one; both are acceptable"
                )
                continue
            for index, candidate in enumerate(matches):
                scope = f"scope={candidate.scope}" if candidate.scope else "scope=document"
                marker = "primary" if index == 0 else "alternative"
                if candidate.collection:
                    lines.append(
                        f"- {atom.id} | {atom.label} | collection | {candidate.path} "
                        f"(collection) | {scope} | context=repeat | collection scope"
                    )
                    continue
                lines.append(
                    f"- {atom.id} | {atom.label} | {kind} | {candidate.path} "
                    f"({candidate.data_type}) | {scope} | context={effective_context} | {marker}"
                )
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Brief understanding
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class _AttributeRule:
    name: str
    triggers: tuple[str, ...]
    aliases: tuple[str, ...]
    expected_type: str | None
    concept: str | None = None
    condition: bool = False


_RULES: tuple[_AttributeRule, ...] = (
    _AttributeRule(
        "reverse_charge",
        ("reverse", "charge"),
        ("reverse", "charge"),
        "boolean",
        "reverse_charge",
        True,
    ),
    _AttributeRule("eu_condition", ("eu",), ("eu", "iseu"), "boolean", "customer_is_eu", True),
    _AttributeRule(
        "vat_notice",
        ("notice",),
        ("notice", "vat", "flag", "eu", "reverse", "charge"),
        "boolean",
        "vat_notice",
        True,
    ),
    _AttributeRule(
        "condition_flag",
        ("enabled",),
        ("flag", "enabled", "reverse", "charge", "eu"),
        "boolean",
        "condition",
        True,
    ),
    _AttributeRule(
        "contact_email",
        ("email",),
        ("email", "mail", "contact"),
        "string",
        "contact_email",
    ),
    _AttributeRule(
        "delivery_date",
        ("delivery", "date"),
        ("delivery", "date"),
        "date",
        "delivery_date",
    ),
    _AttributeRule(
        "valid_until",
        ("valid", "until"),
        ("valid", "until", "expiry"),
        "date",
        "validity_date",
    ),
    _AttributeRule("due_date", ("due", "date"), ("due", "date"), "date", "due_date"),
    _AttributeRule(
        "logo", ("logo",), ("logo", "image", "picture", "brand"), "image", "company_logo"
    ),
    _AttributeRule(
        "image",
        ("image",),
        ("image", "logo", "picture"),
        "image",
        "company_logo",
    ),
    _AttributeRule(
        "product_image",
        ("product", "image"),
        ("product", "image", "picture", "line", "item"),
        "image",
        "product_image",
    ),
    _AttributeRule(
        "product_image",
        ("item", "image"),
        ("product", "image", "picture", "line", "item"),
        "image",
        "product_image",
    ),
    _AttributeRule(
        "bank_details",
        ("iban",),
        ("iban", "bank", "swift", "bic"),
        "string",
        "bank_details",
    ),
    _AttributeRule(
        "bank_details",
        ("bank",),
        ("bank", "iban", "swift", "bic"),
        "string",
        "bank_details",
    ),
    _AttributeRule(
        "account_number",
        ("account",),
        ("account", "accountnum"),
        "string",
        "account_number",
    ),
    _AttributeRule(
        "vat_number",
        ("vat",),
        ("vat", "vatnumber"),
        "string",
        "vat_number",
    ),
    _AttributeRule("address", ("address",), ("address", "addr"), "string", "address"),
    _AttributeRule("currency", ("currency",), ("currency", "ccy"), "string", "currency"),
    _AttributeRule(
        "terms",
        ("term",),
        ("terms", "incoterm", "shipping"),
        "string",
        "terms",
    ),
    _AttributeRule(
        "quantity",
        ("quantity",),
        ("quantity", "qty", "count"),
        "number",
        "quantity",
    ),
    _AttributeRule("quantity", ("qty",), ("quantity", "qty"), "number", "quantity"),
    _AttributeRule(
        "unit_price",
        ("unit", "price"),
        ("unitprice", "price", "unit", "rate"),
        "number",
        "unit_price",
    ),
    _AttributeRule("price", ("price",), ("price", "unitprice", "rate"), "number", "price"),
    _AttributeRule("rate", ("rate",), ("rate", "price", "unitprice"), "number", "rate"),
    _AttributeRule(
        "discount",
        ("discount",),
        ("discount", "pct", "percent"),
        "number",
        "discount",
    ),
    _AttributeRule("tax", ("tax",), ("tax", "vat"), "number", "tax_amount"),
    _AttributeRule("net", ("net",), ("net",), "number", "net_amount"),
    _AttributeRule("gross", ("gross",), ("gross",), "number", "gross_amount"),
    _AttributeRule("total", ("total",), ("total", "gross", "amount"), "number", "total_amount"),
    _AttributeRule("amount", ("amount",), ("amount",), "number", "amount"),
    _AttributeRule("hours", ("hour",), ("hours", "effort"), "number", "hours"),
    _AttributeRule("item", ("item",), ("item", "itemid", "itemnumber"), "string", "line_item"),
    _AttributeRule("unit", ("unit",), ("unit",), "string", "unit"),
    _AttributeRule("note", ("note",), ("note",), "string", "note"),
    _AttributeRule("warehouse", ("warehouse",), ("warehouse",), "string", "warehouse"),
    _AttributeRule(
        "description",
        ("description",),
        ("description", "text"),
        "string",
        "description",
    ),
    _AttributeRule("name", ("name",), ("name",), "string", "name"),
    _AttributeRule(
        "number",
        ("number",),
        ("number", "num", "no", "id", "identifier", "reference"),
        "string",
        "number",
    ),
    _AttributeRule("number", ("no",), ("number", "num", "no", "id"), "string", "number"),
    _AttributeRule("id", ("id",), ("id", "identifier", "number"), "string", "number"),
    _AttributeRule("reference", ("reference",), ("reference", "id", "number"), "string", "number"),
    _AttributeRule("date", ("date",), ("date",), "date", "date"),
)

_RULE_LOOKUP = {rule.name: rule for rule in _RULES}


def _translate(text: str) -> str:
    lowered = text.casefold()
    for source, target in _TRANSLATIONS:
        lowered = re.sub(rf"\b{re.escape(source)}\b", target, lowered)
    return lowered


def _clauses(text: str) -> list[str]:
    clauses: list[str] = []
    for raw in _CLAUSE_SPLIT.split(_translate(text)):
        clause = raw.strip(" .;:-\t*")
        if clause:
            clauses.append(clause)
    return clauses or [text]


def _content_tokens(text: str) -> tuple[str, ...]:
    return tuple(
        token
        for token in tokenize(_translate(text))
        if token not in _STOPWORDS and token not in _GENERIC_ATTRIBUTES
    )


def _detect_entities(tokens: Sequence[str]) -> tuple[str, ...]:
    found: list[str] = []
    for token in tokens:
        entity = _ENTITY_LOOKUP.get(token)
        if entity is not None and entity not in found:
            found.append(entity)
    # A document object is a namespace, not a party; it does not need an entity
    # constraint because the path itself is checked by the attribute evidence.
    return tuple(entity for entity in found if entity != "parameter")


_BUSINESS_HEADER = re.compile(
    r"\b(?:sales|purchase|invoice|quotation|order|document|data|report)\s+header\b",
    re.IGNORECASE,
)


def _detect_placement(text: str) -> str | None:
    lowered = text.casefold()
    if "footer" in lowered or "bottom" in lowered:
        return "footer"
    page_header = (
        "page header" in lowered
        or "letterhead" in lowered
        or "top of the page" in lowered
        or "at the top" in lowered
        or ("header" in lowered and not _BUSINESS_HEADER.search(lowered))
    )
    if page_header:
        return "header"
    if "table" in lowered or "column" in lowered or "row" in lowered:
        return "repeat"
    if "when" in lowered or "only appears" in lowered or "if " in lowered:
        return "conditional"
    return None


def _looks_like_exclusion(clause: str) -> bool:
    lowered = clause.casefold().strip()
    return bool(_EXCLUSION.match(lowered)) or lowered.startswith(("not ", "without ", "excluding "))


def _is_condition_clause(clause: str) -> bool:
    return bool(re.search(r"\b(?:if|when)\b|only appears|enabled|condition", clause.casefold()))


def _excluded_terms(prompt: str) -> tuple[str, ...]:
    """Derive explicit exclusions from a negated clause.

    The text after the exclusion marker is scanned to the end of the brief so a
    list split by commas ("do not add warehouse, discount or line note") keeps
    every excluded column. Entity words are dropped: "do not use the company
    name as the customer" is an entity constraint, not a reason to exclude every
    path with "name". A clause that only names an entity/attribute is likewise
    left to the entity matcher.
    """
    match = _EXCLUSION.search(prompt.casefold())
    if match is None:
        return ()
    body = match.group(1)
    # Stop at a sentence boundary; the exclusion list does not continue into
    # the next independent requirement.
    body = re.split(r"[.;]", body, maxsplit=1)[0]
    structural = frozenset(
        {"column", "columns", "row", "rows", "table", "list", "only", "add", "include", "use"}
    )
    raw = [
        token
        for token in tokenize(_translate(body))
        if token not in _STOPWORDS and token not in structural and token not in _ENTITY_LOOKUP
    ]
    remaining = [token for token in raw if token not in _GENERIC_ATTRIBUTES]
    if remaining:
        return tuple(dict.fromkeys(raw))
    return ()


_GENERIC_RULE_NAMES = frozenset({"number", "id", "reference", "amount", "date"})
_SPECIFIC_NUMBER_RULES = frozenset(
    {
        "account_number",
        "bill_number",
        "bank_details",
        "vat_number",
        "unit_price",
        "quantity",
        "discount",
        "hours",
        "item",
    }
)


def _match_rules(tokens: Sequence[str]) -> list[_AttributeRule]:
    """Match attribute rules, most specific first.

    A clause such as "customer VAT number" must produce one VAT requirement,
    not a VAT requirement plus a generic "number" requirement. Likewise "bank
    account IBAN" produces bank details, not an account-number requirement.
    """
    token_set = set(tokens)
    matched: list[_AttributeRule] = []
    consumed: set[str] = set()
    for rule in _RULES:
        if any(trigger in consumed for trigger in rule.triggers):
            continue
        if all(trigger in token_set for trigger in rule.triggers):
            matched.append(rule)
            consumed.update(rule.triggers)
            if rule.name == "bank_details":
                consumed.update({"account", "accountnumber"})
    names = {rule.name for rule in matched}
    if names & _SPECIFIC_NUMBER_RULES:
        matched = [rule for rule in matched if rule.name not in {"number", "id", "reference"}]
    if names & {"tax", "net", "gross", "total"}:
        matched = [rule for rule in matched if rule.name != "amount"]
    if names & {"valid_until", "due_date", "delivery_date"}:
        matched = [rule for rule in matched if rule.name != "date"]
    if "vat_notice" in names:
        matched = [rule for rule in matched if rule.name != "vat_number"]
    return matched


def _concept_for(rule: _AttributeRule, entities: tuple[str, ...]) -> str:
    """Resolve a rule's generic concept against the atom's entity/scope."""
    line = "line" in entities
    task = "task" in entities
    if rule.name in {"quantity", "description", "amount", "total", "number"}:
        if task:
            return f"task_{rule.name}"
        if line:
            return f"line_{rule.name}"
    if rule.concept == "name" and entities:
        if "company" in entities:
            return "company_name"
        if "vendor" in entities:
            return "vendor_name"
        if "customer" in entities:
            return "customer_name"
    if rule.concept == "address" and entities:
        if "company" in entities:
            return "company_address"
        if "vendor" in entities:
            return "vendor_address"
        if "customer" in entities:
            return "customer_address"
    if rule.concept == "vat_number" and entities:
        if "company" in entities:
            return "company_vat_number"
        if "customer" in entities or "vendor" in entities:
            return "customer_vat_number"
    if (
        rule.concept == "account_number"
        and entities
        and ("customer" in entities or "vendor" in entities)
    ):
        return "customer_account_number"
    return rule.concept or rule.name


_STRUCTURAL_TOKENS = frozenset(
    {
        "line",
        "lines",
        "table",
        "list",
        "row",
        "rows",
        "column",
        "columns",
        "nested",
        "under",
        "each",
        "every",
        "service",
        "order",
        "tasks",
        "task",
    }
)


def _fallback_atom(clause: str, tokens: Sequence[str]) -> RequirementAtom | None:
    content = tuple(token for token in tokens if token not in _STOPWORDS)
    if not content:
        return None
    if all(token in _STRUCTURAL_TOKENS or token in _ENTITY_LOOKUP for token in content):
        return None
    kind = infer_kind(clause)
    expected = {
        "image": "image",
        "date": "date",
        "number": "number",
        "boolean": "boolean",
        "collection": None,
    }.get(kind.value)
    entities = _detect_entities(content)
    concept = None
    if entities and content:
        concept = f"{entities[0]}_{content[-1]}"
    return RequirementAtom(
        id="req",
        text=clause,
        concept=concept,
        entities=entities,
        attributes=content,
        expected_type=expected,
        condition=kind.value == "boolean",
        placement=_detect_placement(clause),
    )


def decompose_requirements(prompt: str) -> tuple[RequirementAtom, ...]:
    """Split a brief into atomic, typed requirements.

    The decomposition is rule-based and transparent: each atom records the
    entity namespace, the attribute tokens, the expected type, a condition flag
    and the requested placement. It does not consult the gold labels.
    """
    clauses = _clauses(prompt)
    exclusions = _excluded_terms(prompt)
    global_placement = _detect_placement(prompt)
    if global_placement not in {"header", "footer"}:
        global_placement = None
    all_tokens = tokenize(_translate(prompt))
    global_entities = _detect_entities(all_tokens)
    has_task = "task" in global_entities
    has_line = "line" in global_entities or any(
        token in {"line", "table", "item", "items", "product", "products", "row", "rows"}
        for token in all_tokens
    )
    default_scope: tuple[str, ...] = ("task",) if has_task else (("line",) if has_line else ())
    default_party: tuple[str, ...] = (
        (global_entities[0],)
        if len([e for e in global_entities if e in _PARTY_ENTITIES]) == 1
        else ()
    )

    atoms: list[RequirementAtom] = []
    counter = 0

    def add(atom: RequirementAtom) -> None:
        nonlocal counter
        placement = atom.placement or global_placement
        atom = atom.__class__(
            id=f"req_{counter:02d}",
            text=atom.text,
            concept=atom.concept,
            entities=atom.entities,
            attributes=atom.attributes,
            synonyms=atom.synonyms,
            expected_type=atom.expected_type,
            condition=atom.condition,
            placement=placement,
            collection=atom.collection,
        )
        counter += 1
        atoms.append(atom)

    for clause in clauses:
        if _looks_like_exclusion(clause):
            continue
        tokens = list(tokenize(clause))
        entities = _detect_entities(tokens)
        placement = _detect_placement(clause)
        condition = _is_condition_clause(clause)
        matched = _match_rules(tokens)
        clause_has_document = bool(set(tokens) & _DOCUMENT_TOKENS)
        if condition:
            condition_rules = {
                "reverse_charge",
                "eu_condition",
                "vat_notice",
                "condition_flag",
            }
            matched = [rule for rule in matched if rule.name in condition_rules]

        for rule in matched:
            atom_entities = entities
            if not atom_entities and default_scope and rule.name not in _NO_STRUCTURAL_INHERIT:
                atom_entities = default_scope
            # A party default is only meaningful for party attributes; it must
            # not turn "invoice number" into "company invoice number".
            if (
                not atom_entities
                and default_party
                and rule.name
                in {
                    "name",
                    "address",
                    "vat_number",
                    "account_number",
                    "logo",
                    "image",
                    "contact_email",
                }
                and not clause_has_document
            ):
                atom_entities = default_party
            if rule.name == "amount" and set(tokens) & {"final", "grand", "total"}:
                atom_entities = entities
            expected = rule.expected_type
            if condition and rule.name in {
                "eu_condition",
                "reverse_charge",
                "condition_flag",
                "vat_notice",
            }:
                expected = "boolean"
            attributes = tuple(dict.fromkeys(rule.triggers))
            synonyms = rule.aliases
            concept = _concept_for(rule, atom_entities)
            if (
                concept == "vat_number"
                and "customer" not in atom_entities
                and "company" not in atom_entities
            ):
                concept = "vat_number"
            add(
                RequirementAtom(
                    id="req",
                    text=clause,
                    concept=concept,
                    entities=atom_entities,
                    attributes=attributes,
                    synonyms=synonyms,
                    expected_type=expected,
                    condition=condition and expected == "boolean",
                    placement="conditional" if condition else placement,
                )
            )

        if not matched:
            atom = _fallback_atom(clause, tokens)
            if atom is None:
                continue
            atom_entities = atom.entities or default_scope
            add(
                RequirementAtom(
                    id="req",
                    text=atom.text,
                    concept=atom.concept,
                    entities=atom_entities,
                    attributes=atom.attributes,
                    expected_type=atom.expected_type,
                    condition=atom.condition,
                    placement=atom.placement,
                )
            )

        # A table/list/each phrase asks for the collection scope itself. The
        # collection ancestor is also added during retrieval for every scoped
        # field, so this atom exists mainly to make the scope explicit.
        lowered = clause.casefold()
        if (
            any(marker in lowered for marker in ("table", "list", "each", "every", "nested"))
            and default_scope
            and not any(atom.collection for atom in atoms)
        ):
            add(
                RequirementAtom(
                    id="req",
                    text=clause,
                    concept=f"{default_scope[0]}_collection",
                    entities=default_scope,
                    attributes=("collection",),
                    expected_type="collection",
                    placement="repeat",
                    collection=True,
                )
            )

    condition_concepts = {
        atom.concept for atom in atoms if atom.expected_type == "boolean" and atom.condition
    }
    if condition_concepts & {"reverse_charge", "customer_is_eu"}:
        atoms = [atom for atom in atoms if atom.concept not in {"vat_notice", "condition"}]
    elif condition_concepts:
        atoms = [
            atom
            for atom in atoms
            if not (atom.concept in {"vat_notice", "condition"} and not atom.condition)
        ]
    # Explicit exclusions are not requirements: "do not add warehouse" must not
    # produce a warehouse atom with a NO SUPPORTED BINDING row.
    if exclusions:
        atoms = [
            atom
            for atom in atoms
            if not (
                (
                    content := tuple(
                        token for token in _content_tokens(atom.text) if token not in _ENTITY_LOOKUP
                    )
                )
                and all(token in exclusions for token in content)
            )
        ]

    # Fallback: a brief with no recognised atom still needs a bounded schema
    # view. Use the content tokens once; retrieval will return nothing if the
    # schema has no evidence, and the caller can then fall back to the full
    # schema deliberately.
    if not atoms:
        atom = _fallback_atom(prompt, all_tokens)
        if atom is not None:
            add(atom)
    deduped: list[RequirementAtom] = []
    seen_atoms: set[tuple[Any, ...]] = set()
    for atom in atoms:
        key = (atom.concept, atom.entities, atom.expected_type)
        if key in seen_atoms:
            continue
        seen_atoms.add(key)
        deduped.append(atom)
    return tuple(deduped[:_MAX_ATOMS])


# --------------------------------------------------------------------------- #
# Retrieval
# --------------------------------------------------------------------------- #
def _path_entity(path: str) -> str | None:
    tokens = set(tokenize(path))
    if "task" in tokens:
        return "task"
    if "bank" in tokens or "iban" in tokens or "swift" in tokens or "bic" in tokens:
        return "bank"
    if "vendor" in tokens or "supplier" in tokens or "seller" in tokens or "payee" in tokens:
        return "vendor"
    if "customer" in tokens or "client" in tokens or "buyer" in tokens:
        return "customer"
    if "company" in tokens or "issuer" in tokens:
        return "company"
    if "line" in tokens or "item" in tokens or "product" in tokens:
        return "line"
    return None


def _has_tokens(path: str, tokens: Iterable[str]) -> bool:
    path_tokens = set(tokenize(path))
    return any(token in path_tokens for token in tokens)


def _entity_compatible(atom: RequirementAtom, path: str) -> bool:
    if not atom.entities:
        return True
    path_entity = _path_entity(path)
    path_tokens = set(tokenize(path))
    for entity in atom.entities:
        if entity in _PARTY_ENTITIES:
            if path_entity == "bank" and entity != "bank":
                return False
            if path_entity != entity:
                return False
        elif entity == "bank":
            if path_entity != "bank":
                return False
        elif entity == "task":
            if "task" not in path_tokens:
                return False
        elif entity == "line":
            if not (path_tokens & {"line", "item", "product", "row"}):
                return False
            if "task" in path_tokens and "task" not in atom.entities:
                return False
    return True


def type_matches(expected: str | None, actual: str | None) -> bool:
    """Public type compatibility used by both retrieval and post-validation."""
    if expected == "image":
        return actual == "image"
    if actual == "image":
        return False
    if expected == "boolean":
        return actual == "boolean"
    if expected == "number":
        return actual == "number"
    if expected == "date":
        return actual in {"date", "string"}
    if expected == "collection":
        return actual == "collection"
    if expected in {"string", "text"}:
        return actual in {"string", "any"}
    if expected is None:
        return actual in {"string", "any", "number", "date", "boolean"}
    return True


def _type_compatible(atom: RequirementAtom, node: SchemaNode) -> bool:
    expected = atom.expected_type
    actual = node.data_type
    if actual == "boolean" and not atom.condition and expected != "boolean":
        return False
    if node.collection:
        return expected == "collection"
    return type_matches(expected, actual)


def _specific_tokens(atom: RequirementAtom) -> set[str]:
    return {
        token
        for token in atom.attributes
        if token not in _GENERIC_ATTRIBUTES
        and token not in _STOPWORDS
        and token not in _ENTITY_LOOKUP
        and token not in _DOCUMENT_TOKENS
    }


def _score(
    atom: RequirementAtom,
    node: SchemaNode,
    *,
    tokens: set[str],
    expanded: set[str],
) -> tuple[float, list[str]]:
    own = set(tokenize(node.name))
    path_tokens = set(tokenize(node.path))
    score = 0.0
    reasons: list[str] = []
    specific = _specific_tokens(atom)
    for token in atom.attributes:
        if token in own:
            score += 2.0
            reasons.append(f"field name contains {token!r}")
        elif token in path_tokens:
            score += 0.45
    for token in expanded:
        if token in own and token not in atom.attributes:
            score += 0.75
        elif token in path_tokens and token not in atom.attributes:
            score += 0.2
    if not atom.attributes:
        for token in tokens:
            if token in own:
                score += 1.0
            elif token in path_tokens:
                score += 0.25
    # A path may only qualify on a specific attribute token in its own name.
    # Without this, "requisition number" would match OrderId through the
    # generic token "number" and invent a binding.
    if specific and not any(token in own for token in specific):
        return 0.0, []
    has_core = any(token in own for token in atom.attributes)
    if not has_core:
        for token in atom.attributes:
            if token not in _GENERIC_ATTRIBUTES:
                continue
            aliases = set(expand((token,)))
            if aliases & own:
                has_core = True
                break
    if not has_core:
        return 0.0, []
    document_tokens = set(tokenize(atom.text)) & _DOCUMENT_TOKENS
    namespace_attribute = bool(set(atom.attributes) & _NAMESPACE_ATTRIBUTES)
    if document_tokens and namespace_attribute:
        if document_tokens & path_tokens:
            score += 0.7
        if not atom.entities and _path_entity(node.path) in _PARTY_ENTITIES:
            score -= 0.9
    if atom.concept and atom.concept in {concept.value for concept in MATCHERS}:
        matcher = MATCHERS[next(concept for concept in MATCHERS if concept.value == atom.concept)]
        if matcher.matches(node):
            score += 1.6
            reasons.append("concept matcher agrees")
    if _entity_compatible(atom, node.path) and atom.entities:
        score += 0.6
    if atom.expected_type and _type_compatible(atom, node):
        score += 0.4
    score -= 0.04 * max(0, node.path.count(".") - 2)
    return max(0.0, score), reasons


def _scope_of(schema: NormalizedSchema, path: str) -> str | None:
    parts = path.split(".")
    for index in range(len(parts) - 1, 0, -1):
        candidate = ".".join(parts[:index])
        node = schema.node(candidate)
        if node is not None and node.collection:
            return candidate
    return None


def _expanded(tokens: Iterable[str]) -> set[str]:
    expanded = expand(tuple(tokens))
    for token, aliases in SYNONYMS.items():
        group = {token, *aliases}
        if set(tokens) & group:
            expanded |= group
    return expanded


def _rank_atom(
    schema: NormalizedSchema,
    atom: RequirementAtom,
    *,
    exclusions: Sequence[str],
    per_requirement: int,
) -> list[CandidateEvidence]:
    tokens = set(tokenize(atom.text))
    expanded = _expanded((*tokens, *atom.attributes, *atom.synonyms))
    schema_tokens = {token for path in schema.paths for token in tokenize(path)}
    unknown = {
        token
        for token in _content_tokens(atom.text)
        if token not in schema_tokens
        and token not in _DOCUMENT_TOKENS
        and token not in _PLACEMENT_TOKENS
        and token not in _ENTITY_LOOKUP
    }
    if atom.expected_type == "boolean" or atom.condition:
        unknown = set()
    if unknown:
        # The brief asks for a concept the schema does not expose at all. Do
        # not substitute a nearby field: report a missing requirement.
        return []
    scored: list[tuple[float, CandidateEvidence]] = []
    for path in schema.paths:
        node = schema.node(path)
        if node is None:
            continue
        if node.children and not node.collection:
            continue
        if any(token in set(tokenize(path)) for token in exclusions):
            continue
        if not _type_compatible(atom, node):
            continue
        if node.collection and not atom.collection:
            continue
        if not _entity_compatible(atom, path):
            continue
        raw, reasons = _score(atom, node, tokens=tokens, expanded=expanded)
        if raw < MIN_SCORE:
            continue
        evidence = CandidateEvidence(
            path=path,
            data_type=node.data_type,
            collection=node.collection,
            requirement_id=atom.id,
            score=round(raw, 6),
            reasons=tuple(reasons),
            expected_type=atom.expected_type,
            scope=_scope_of(schema, path),
            decision="resolved",
            primary=False,
        )
        scored.append((raw, evidence))
    scored.sort(key=lambda item: (-item[0], item[1].path.count("."), item[1].path))
    if not scored:
        return []
    top_score = scored[0][0]
    provisional: list[tuple[float, CandidateEvidence]] = []
    for index, (raw, evidence) in enumerate(scored[:per_requirement]):
        if index > 0 and raw < top_score * 0.95:
            continue
        provisional.append((raw, evidence))
    runner_score = provisional[1][0] if len(provisional) > 1 else 0.0
    gap = top_score - runner_score
    decision = "resolved"
    if runner_score and gap < max(0.2, 0.06 * top_score):
        decision = "ambiguous"
    return [
        CandidateEvidence(
            path=evidence.path,
            data_type=evidence.data_type,
            collection=evidence.collection,
            requirement_id=evidence.requirement_id,
            score=evidence.score,
            reasons=evidence.reasons,
            expected_type=evidence.expected_type,
            scope=evidence.scope,
            decision=decision,
            primary=index == 0,
        )
        for index, (_raw, evidence) in enumerate(provisional)
    ]


def _fallback_retrieval(schema: NormalizedSchema, prompt: str) -> list[CandidateEvidence]:
    """Last-resort lexical retrieval when decomposition found no atom.

    It is still bounded and deterministic, but it is marked as a fallback so
    callers can choose to expose the full schema rather than a weak list.
    """
    tokens = set(tokenize(_translate(prompt)))
    expanded = _expanded(tokens)
    scored: list[tuple[float, str, SchemaNode]] = []
    for path in schema.paths:
        node = schema.node(path)
        if node is None or (node.children and not node.collection):
            continue
        own = set(tokenize(node.name))
        raw = sum(2.0 for token in tokens if token in own) + sum(
            0.2 for token in expanded if token in own and token not in tokens
        )
        if raw <= 0:
            continue
        scored.append((raw, path, node))
    scored.sort(key=lambda item: (-item[0], item[1].count("."), item[1]))
    return [
        CandidateEvidence(
            path=path,
            data_type=node.data_type,
            collection=node.collection,
            requirement_id="req_00",
            score=round(raw, 6),
            reasons=("fallback lexical match",),
            expected_type=None,
            scope=_scope_of(schema, path),
            decision="resolved",
            primary=index == 0,
        )
        for index, (raw, path, node) in enumerate(scored[:MAX_PER_REQUIREMENT])
    ]


def retrieve_candidates(
    schema: NormalizedSchema,
    prompt: str,
    *,
    max_candidates: int = MAX_CANDIDATES,
) -> CandidateSet:
    """Decompose ``prompt`` and return a bounded, deterministic candidate set."""
    exclusions = _excluded_terms(prompt)
    decomposed = decompose_requirements(prompt)
    ranked: dict[str, list[CandidateEvidence]] = {
        atom.id: _rank_atom(
            schema, atom, exclusions=exclusions, per_requirement=MAX_PER_REQUIREMENT
        )
        for atom in decomposed
    }
    atoms = tuple(
        atom
        for atom in decomposed
        if ranked[atom.id]
        or atom.condition
        or (atom.concept is not None and atom.expected_type is not None)
        or atom.concept in {"number", "date", "vat_number"}
        or any(token in _GENERIC_ATTRIBUTES for token in atom.attributes)
    )
    candidates: list[CandidateEvidence] = []
    seen: set[str] = set()
    fallback = False
    for atom in atoms:
        for candidate in ranked[atom.id]:
            if candidate.path in seen:
                continue
            seen.add(candidate.path)
            candidates.append(candidate)
    if not candidates and not atoms:
        fallback_candidates = _fallback_retrieval(schema, prompt)
        if fallback_candidates:
            fallback = True
            candidates = fallback_candidates
    # A collection used by a scoped candidate must be visible to the provider:
    # otherwise it cannot write a table/repeat over the right path.
    scoped = [candidate for candidate in candidates if candidate.scope]
    for candidate in scoped:
        collection_path = candidate.scope
        if collection_path and collection_path not in seen:
            node = schema.node(collection_path)
            if node is not None and node.collection:
                seen.add(collection_path)
                candidates.append(
                    CandidateEvidence(
                        path=collection_path,
                        data_type=node.data_type,
                        collection=True,
                        requirement_id=candidate.requirement_id,
                        score=candidate.score,
                        reasons=("collection scope for a requested field",),
                        expected_type="collection",
                        scope=_scope_of(schema, collection_path),
                        decision="resolved",
                        primary=False,
                    )
                )
    # Bound the total deterministically: keep the first primary per requirement,
    # then fill in original order.
    primaries: list[CandidateEvidence] = []
    rest: list[CandidateEvidence] = []
    for candidate in candidates:
        (primaries if candidate.primary else rest).append(candidate)
    bounded = [*primaries, *rest][:max_candidates]
    bounded_set = {candidate.path for candidate in bounded}
    bounded = [candidate for candidate in candidates if candidate.path in bounded_set][
        :max_candidates
    ]
    table_hint = None
    if "table" in prompt.casefold() and candidates:
        scopes = sorted({candidate.scope for candidate in bounded if candidate.scope is not None})
        outer = [scope for scope in scopes if not scope.endswith(".Task")]
        inner = [scope for scope in scopes if scope.endswith(".Task")]
        if outer:
            table_hint = f"REQUIRED STRUCTURE: use a table block over {outer[0]}"
            if inner:
                table_hint += f"; use a nested repeat over {inner[0]} inside each row"
            table_hint += ". A plain paragraph repeat is not a table."
    return CandidateSet(
        atoms=atoms,
        candidates=tuple(bounded),
        exclusions=exclusions,
        fallback=fallback,
        table_hint=table_hint,
    )


__all__ = [
    "MAX_CANDIDATES",
    "MAX_PER_REQUIREMENT",
    "CandidateEvidence",
    "CandidateSet",
    "RequirementAtom",
    "decompose_requirements",
    "retrieve_candidates",
    "type_matches",
]
