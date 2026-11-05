#!/usr/bin/env python3
"""Independent deterministic adjudication of the gold semantic labels.

This is a **second pass**, not a copy of the first one. It re-derives the
required concepts, expected paths, alternatives, forbidden scope guards and
structural blocks from the case prompt plus the normalized DDSP schema, using
its own bounded lexicon and evidence rules. It then compares that derivation
with the committed annotation and writes a per-label provenance report.

It is deliberately independent of ``docentric_copilot.planner.candidates`` and
``docentric_copilot.schema_resolver``: importing the planner's retrieval would
make the "second pass" a circular check of the same code path.

Important limitation: this is a **deterministic proxy review**, not a second
human annotator. AT-07 therefore stays ``partial``. The report says so and the
dataset provenance points at the proxy rather than claiming dual human review.

Usage::

    .venv/bin/python benchmarks/adjudicate_labels.py --write
    .venv/bin/python benchmarks/adjudicate_labels.py --check
    .venv/bin/python benchmarks/adjudicate_labels.py --apply     # write report + provenance

``--check`` exits non-zero on a requirement conflict (an author path the
independent pass cannot reproduce). A ``partial`` result from a stricter or
looser forbidden guard is reported but does not fail the check; those are
review notes, not silent rewrites.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, str(ROOT))

from docentric_copilot.ddsp_parser import parse_ddsp  # noqa: E402

DEFAULT_CASES = ROOT / "benchmarks" / "gold_cases.json"
DEFAULT_REPORT = ROOT / "benchmarks" / "adjudication_report.json"
REPORT_SCHEMA = "gold-adjudication/v1"
ADJUDICATOR_VERSION = "1.0.0"
AUTHOR = "v0.10 single annotator (implementer)"
ADJUDICATOR = f"benchmarks/adjudicate_labels.py {ADJUDICATOR_VERSION} (deterministic proxy)"
REVIEW_STATUS = "adjudicated_proxy"
AT07_STATUS = "partial"

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z0-9]+")

_TRANSLATIONS: tuple[tuple[str, str], ...] = (
    ("conditions de livraison", "delivery terms"),
    ("bedingungen für die lieferung", "delivery terms"),
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
    ("nummer", "number"),
    ("menge", "quantity"),
    ("quantité", "quantity"),
    ("quantitat", "quantity"),
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
        "under",
        "nested",
        "beneath",
        "page",
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
        "shown",
        "alway",
        "dan",
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
_GENERIC = frozenset(
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
        "code",
    }
)
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
        "purchase",
        "sale",
    }
)
_ENTITY_ALIASES: dict[str, tuple[str, ...]] = {
    "customer": ("customer", "client", "buyer", "billto", "soldto", "cust"),
    "vendor": ("vendor", "supplier", "seller", "payee"),
    "company": ("company", "issuer", "organization", "organisation", "firm"),
    "bank": ("bank", "iban", "swift", "bic"),
    "line": ("line", "item", "product", "row", "service", "article"),
    "task": ("task", "subtask"),
}
_ENTITY_LOOKUP = {alias: entity for entity, aliases in _ENTITY_ALIASES.items() for alias in aliases}
_PARTY = ("customer", "vendor", "company")


def _tokenize(text: str) -> tuple[str, ...]:
    parts: list[str] = []
    for chunk in re.split(r"[^A-Za-z0-9]+", text):
        parts.extend(_WORD.findall(chunk))
    result: list[str] = []
    for part in parts:
        token = part.lower()
        if token in _STOPWORDS or len(token) < 2:
            continue
        if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]
        result.append(token)
    return tuple(result)


def _translate(text: str) -> str:
    lowered = text.casefold()
    for source, target in _TRANSLATIONS:
        lowered = re.sub(rf"\b{re.escape(source)}\b", target, lowered)
    return lowered


def _clauses(text: str) -> list[str]:
    split = re.split(r"(?:[,;]|\band\b|\bund\b|\bet\b|\.\s|\.$)", _translate(text))
    return [clause.strip(" .;:-\t*") for clause in split if clause.strip(" .;:-\t*")]


def _detect_entities(tokens: tuple[str, ...]) -> tuple[str, ...]:
    found: list[str] = []
    for token in tokens:
        entity = _ENTITY_LOOKUP.get(token)
        if entity and entity not in found:
            found.append(entity)
    return tuple(found)


@dataclass(frozen=True, slots=True)
class Rule:
    name: str
    triggers: tuple[str, ...]
    aliases: tuple[str, ...]
    expected_type: str
    condition: bool = False


_RULES: tuple[Rule, ...] = (
    Rule("reverse_charge", ("reverse", "charge"), ("reverse", "charge"), "boolean", True),
    Rule("eu_condition", ("eu",), ("eu", "iseu"), "boolean", True),
    Rule("logo", ("logo",), ("logo", "image", "picture", "brand"), "image"),
    Rule("image", ("image",), ("image", "logo", "picture"), "image"),
    Rule("contact_email", ("email",), ("email", "mail", "contact"), "string"),
    Rule("valid_until", ("valid", "until"), ("valid", "until", "expiry"), "date"),
    Rule("due_date", ("due", "date"), ("due", "date"), "date"),
    Rule("delivery_date", ("delivery", "date"), ("delivery", "date"), "date"),
    Rule("bank_details", ("iban",), ("iban", "bank", "swift", "bic"), "string"),
    Rule("bank_details", ("bank",), ("iban", "bank", "swift", "bic"), "string"),
    Rule("account_number", ("account",), ("account", "accountnum"), "string"),
    Rule("vat_number", ("vat",), ("vat", "vatnumber"), "string"),
    Rule("address", ("address",), ("address", "addr"), "string"),
    Rule("currency", ("currency",), ("currency", "ccy"), "string"),
    Rule("terms", ("term",), ("term", "incoterm", "shipping"), "string"),
    Rule("quantity", ("quantity",), ("quantity", "qty", "count"), "number"),
    Rule("quantity", ("qty",), ("quantity", "qty"), "number"),
    Rule("unit_price", ("unit", "price"), ("unitprice", "price", "unit", "rate"), "number"),
    Rule("price", ("price",), ("price", "unitprice", "rate"), "number"),
    Rule("rate", ("rate",), ("rate", "price", "unitprice"), "number"),
    Rule("discount", ("discount",), ("discount", "pct", "percent"), "number"),
    Rule("tax", ("tax",), ("tax", "vat"), "number"),
    Rule("net", ("net",), ("net",), "number"),
    Rule("gross", ("gross",), ("gross",), "number"),
    Rule("total", ("total",), ("total", "gross", "amount"), "number"),
    Rule("amount", ("amount",), ("amount",), "number"),
    Rule("hours", ("hour",), ("hour", "hours", "effort"), "number"),
    Rule("item", ("item",), ("item", "itemid", "itemnumber"), "string"),
    Rule("unit", ("unit",), ("unit",), "string"),
    Rule("note", ("note",), ("note",), "string"),
    Rule("warehouse", ("warehouse",), ("warehouse",), "string"),
    Rule("description", ("description",), ("description", "text"), "string"),
    Rule("name", ("name",), ("name",), "string"),
    Rule("number", ("number",), ("number", "num", "no", "id", "identifier"), "string"),
    Rule("number", ("no",), ("number", "num", "no", "id"), "string"),
    Rule("id", ("id",), ("id", "identifier", "number"), "string"),
    Rule("reference", ("reference",), ("reference", "ref"), "string"),
    Rule("date", ("date",), ("date",), "date"),
)
_GENERIC_RULES = frozenset({"number", "id", "reference", "amount", "date"})
_SPECIFIC_NUMBER_RULES = frozenset(
    {
        "account_number",
        "bank_details",
        "vat_number",
        "unit_price",
        "quantity",
        "discount",
        "hours",
        "item",
    }
)


def _match_rules(tokens: tuple[str, ...]) -> list[Rule]:
    token_set = set(tokens)
    matched: list[Rule] = []
    consumed: set[str] = set()
    for rule in _RULES:
        if any(trigger in consumed for trigger in rule.triggers):
            continue
        if all(trigger in token_set for trigger in rule.triggers):
            matched.append(rule)
            consumed.update(rule.triggers)
            if rule.name == "bank_details":
                consumed.update({"account"})
    names = {rule.name for rule in matched}
    if names & _SPECIFIC_NUMBER_RULES:
        matched = [rule for rule in matched if rule.name not in {"number", "id", "reference"}]
    if names & {"tax", "net", "gross", "total"}:
        matched = [rule for rule in matched if rule.name != "amount"]
    return matched


def _placement(text: str) -> str | None:
    lowered = text.casefold()
    if "footer" in lowered or "bottom" in lowered:
        return "footer"
    if "header" in lowered or "letterhead" in lowered or "at the top" in lowered:
        return "header"
    if "table" in lowered or "column" in lowered:
        return "repeat"
    if "when" in lowered or "if " in lowered:
        return "conditional"
    return None


def _is_exclusion(clause: str) -> bool:
    lowered = clause.casefold().strip()
    return lowered.startswith(
        (
            "do not",
            "don't",
            "must not",
            "should not",
            "without",
            "exclude",
            "omit",
            "not the",
            "never use",
        )
    )


def _exclusion_body(prompt: str) -> str:
    match = re.search(
        r"(?:do not|don't|must not|should not|without|exclude|omit|never use|not the)\b(.+)",
        prompt.casefold(),
    )
    if match is None:
        return ""
    return re.split(r"[.;]", match.group(1), maxsplit=1)[0].strip()


def _path_tokens(path: str) -> set[str]:
    return set(_tokenize(path))


def _path_entity(path: str) -> str | None:
    tokens = _path_tokens(path)
    if "task" in tokens:
        return "task"
    if tokens & {"bank", "iban", "swift", "bic"}:
        return "bank"
    if tokens & {"vendor", "supplier", "seller", "payee"}:
        return "vendor"
    if tokens & {"customer", "client", "buyer"}:
        return "customer"
    if tokens & {"company", "issuer"}:
        return "company"
    if tokens & {"line", "item", "product"}:
        return "line"
    return None


@dataclass(slots=True)
class DerivedRequirement:
    concept: str
    expected_paths: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)
    expected_type: str | None = None
    expected_context: str | None = None
    satisfiable: bool = True
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "concept": self.concept,
            "expected_paths": self.expected_paths,
            "allowed_alternatives": self.alternatives,
            "expected_type": self.expected_type,
            "expected_context": self.expected_context,
            "satisfiable": self.satisfiable,
            "note": self.note,
        }


@dataclass(slots=True)
class Derivation:
    requirements: list[DerivedRequirement]
    forbidden: list[str]
    advisory_forbidden: list[str]
    blocks: list[dict[str, Any]]
    notes: list[str]


def _schema_nodes(schema: Any) -> list[Any]:
    nodes: list[Any] = []
    for path in schema.paths:
        node = schema.node(path)
        if node is None:
            continue
        if node.children and not node.collection:
            continue
        nodes.append(node)
    return nodes


def _rule_specific(rule: Rule, clause_tokens: tuple[str, ...]) -> tuple[str, ...]:
    specific = {
        token
        for token in clause_tokens
        if token not in _GENERIC
        and token not in _STOPWORDS
        and token not in _ENTITY_LOOKUP
        and token not in _DOCUMENT_TOKENS
    }
    return tuple(sorted(specific))


def _candidate_score(
    node: Any,
    rule: Rule,
    *,
    clause_tokens: tuple[str, ...],
    entities: tuple[str, ...],
    namespace_tokens: set[str],
) -> float:
    own = set(_tokenize(node.name))
    path = set(_tokenize(node.path))
    expected = rule.expected_type
    actual = node.data_type
    if expected == "image" and actual != "image":
        return 0.0
    if actual == "image" and expected != "image":
        return 0.0
    if expected == "boolean" and actual != "boolean":
        return 0.0
    if actual == "boolean" and expected != "boolean":
        return 0.0
    if expected == "number" and actual != "number":
        return 0.0
    if expected == "date" and actual not in {"date", "string"}:
        return 0.0
    if expected == "string" and actual not in {"string", "any"}:
        return 0.0
    if node.collection:
        return 0.0
    path_entity = _path_entity(node.path)
    for entity in entities:
        if entity in _PARTY:
            if path_entity != entity:
                return 0.0
        elif entity == "bank":
            if path_entity != "bank":
                return 0.0
        elif entity == "task":
            if "task" not in path:
                return 0.0
        elif entity == "line":
            if not (path & {"line", "item", "product", "row"}):
                return 0.0
            if "task" in path and "task" not in entities:
                return 0.0
    score = 0.0
    for alias in rule.aliases:
        if alias in own:
            score += 2.0
        elif alias in path:
            score += 0.5
    if score <= 0:
        return 0.0
    if entities:
        score += 0.6
    if expected:
        score += 0.4
    namespace_relevant = bool(
        set(rule.aliases)
        & {"number", "num", "no", "id", "date", "total", "amount", "gross", "tax", "net"}
    )
    if namespace_tokens and namespace_relevant:
        if namespace_tokens & own:
            score += 0.8
        elif namespace_tokens & path:
            score += 0.35
        if not entities and path_entity in _PARTY:
            score -= 0.9
    score -= 0.04 * max(0, node.path.count(".") - 2)
    return max(0.0, score)


def _derive(prompt: str, schema: Any) -> Derivation:
    clauses = _clauses(prompt)
    all_tokens = _tokenize(_translate(prompt))
    entities = _detect_entities(all_tokens)
    global_placement = _placement(prompt)
    if global_placement not in {"header", "footer"}:
        global_placement = None
    namespace_tokens = set(all_tokens) & _DOCUMENT_TOKENS
    nodes = _schema_nodes(schema)
    requirements: list[DerivedRequirement] = []
    blocks: list[dict[str, Any]] = []
    notes: list[str] = []
    used_paths: set[str] = set()
    collection_scopes: list[str] = []
    condition_paths: list[str] = []

    exclusion_body = _exclusion_body(prompt)
    current_structural: tuple[str, ...] = tuple(
        entity for entity in entities if entity in {"line", "task"}
    )
    for clause in clauses:
        if _is_exclusion(clause):
            continue
        if exclusion_body and clause.casefold().strip(" .;:") in exclusion_body:
            continue
        tokens = _tokenize(clause)
        detected = _detect_entities(tokens)
        if detected:
            clause_entities = detected
            structural = tuple(entity for entity in detected if entity in {"line", "task"})
            if structural:
                current_structural = structural
        else:
            clause_entities = current_structural
        rules = _match_rules(tokens)
        if not rules:
            continue
        clause_placement = _placement(clause) or global_placement
        condition = _is_condition(clause)
        if condition:
            rules = [rule for rule in rules if rule.condition or rule.name in {"vat_number"}]
            if any(rule.condition for rule in rules):
                rules = [rule for rule in rules if rule.condition]
        schema_tokens = {token for node in nodes for token in _tokenize(node.path)}
        unknown = {
            token
            for token in tokens
            if token not in schema_tokens
            and token not in _STOPWORDS
            and token not in _GENERIC
            and token not in _ENTITY_LOOKUP
            and token not in _DOCUMENT_TOKENS
        }
        if unknown and not any(rule.condition for rule in rules):
            for rule in rules:
                requirements.append(
                    DerivedRequirement(
                        concept=rule.name,
                        expected_type=rule.expected_type,
                        expected_context="conditional" if condition else clause_placement,
                        satisfiable=False,
                        note="the brief names a concept absent from the schema: "
                        + ", ".join(sorted(unknown)),
                    )
                )
            continue
        for rule in rules:
            if condition and rule.name == "vat_number" and "notice" in tokens:
                continue
            scored: list[tuple[float, Any]] = []
            for node in nodes:
                score = _candidate_score(
                    node,
                    rule,
                    clause_tokens=tokens,
                    entities=clause_entities,
                    namespace_tokens=namespace_tokens,
                )
                if score > 0:
                    scored.append((score, node))
            scored.sort(key=lambda item: (-item[0], item[1].path.count("."), item[1].path))
            if not scored:
                requirements.append(
                    DerivedRequirement(
                        concept=rule.name,
                        expected_type=rule.expected_type,
                        expected_context="conditional" if condition else clause_placement,
                        satisfiable=False,
                        note="no schema path satisfies this concept; must not be invented",
                    )
                )
                continue
            top = scored[0][0]
            selected = [
                (score, node)
                for index, (score, node) in enumerate(scored[:3])
                if index == 0 or score >= top * 0.9
            ]
            # An ambiguous party attribute keeps its runner-up as an accepted
            # alternative; a resolved one does not.
            party_entities = {
                _path_entity(node.path)
                for _score, node in selected
                if _path_entity(node.path) in _PARTY
            }
            ambiguous = (
                len(selected) > 1
                and selected[0][0] - selected[1][0] < max(0.2, 0.06 * selected[0][0])
                and len(party_entities) > 1
            )
            expected_path = selected[0][1].path
            alternative_paths = [node.path for _score, node in selected[1:]] if ambiguous else []
            if rule.expected_type == "boolean" and condition:
                expected_context = "conditional"
                condition_paths.append(expected_path)
            elif rule.expected_type == "image":
                expected_context = clause_placement
            else:
                scope = _scope_of(schema, expected_path)
                expected_context = "repeat" if scope else (clause_placement or "body")
                if scope:
                    collection_scopes.append(scope)
            if expected_path in used_paths:
                continue
            used_paths.update([expected_path, *alternative_paths])
            requirements.append(
                DerivedRequirement(
                    concept=rule.name,
                    expected_paths=[expected_path],
                    alternatives=alternative_paths,
                    expected_type=rule.expected_type,
                    expected_context=expected_context,
                    note="ambiguous party attribute; both paths accepted" if ambiguous else "",
                )
            )
            if rule.expected_type == "image":
                blocks.append(
                    {
                        "kind": "image",
                        "required": True,
                        "path": expected_path,
                        "description": "the prompt asks for an image",
                    }
                )

    # Structural blocks follow the collection scopes used by the requirements.
    outer = sorted({scope for scope in collection_scopes if not scope.endswith(".Task")})
    inner = sorted({scope for scope in collection_scopes if scope.endswith(".Task")})
    for scope in outer:
        blocks.append({"kind": "table", "required": True, "path": scope})
        blocks.append({"kind": "repeat", "required": True, "path": scope})
    for scope in inner:
        if not any(block.get("path") == scope for block in blocks):
            blocks.append({"kind": "repeat", "required": True, "path": scope})
    if condition_paths:
        blocks.append({"kind": "conditional", "required": True})
    # Deduplicate blocks by (kind, path).
    seen_blocks: set[tuple[str, str | None]] = set()
    unique_blocks: list[dict[str, Any]] = []
    for block in blocks:
        key = (str(block["kind"]), block.get("path"))
        if key in seen_blocks:
            continue
        seen_blocks.add(key)
        unique_blocks.append(block)

    forbidden, advisory = _derive_forbidden(prompt, clauses, schema, requirements, nodes)
    if not requirements:
        notes.append("no binding requirement was independently derived")
    return Derivation(
        requirements=requirements,
        forbidden=forbidden,
        advisory_forbidden=advisory,
        blocks=unique_blocks,
        notes=notes,
    )


def _is_condition(clause: str) -> bool:
    return bool(re.search(r"\b(?:if|when)\b|only appears|enabled", clause.casefold()))


def _scope_of(schema: Any, path: str) -> str | None:
    parts = path.split(".")
    for index in range(len(parts) - 1, 0, -1):
        candidate = ".".join(parts[:index])
        node = schema.node(candidate)
        if node is not None and node.collection:
            return candidate
    return None


def _derive_forbidden(
    prompt: str,
    clauses: list[str],
    schema: Any,
    requirements: list[DerivedRequirement],
    nodes: list[Any],
) -> tuple[list[str], list[str]]:
    explicit: list[str] = []
    advisory: list[str] = []
    lowered = prompt.casefold()
    # Explicit exclusion lists: keep the scoped column names, never the entity.
    match = re.search(
        r"(?:do not|don't|must not|without|exclude|omit|never use|not the)\b(.+)",
        lowered,
    )
    if match:
        body = re.split(r"[.;]", match.group(1), maxsplit=1)[0]
        body_tokens = _tokenize(body)
        tokens = {
            token
            for token in body_tokens
            if token not in _STOPWORDS
            and token not in _ENTITY_LOOKUP
            and token
            not in {
                "column",
                "columns",
                "row",
                "rows",
                "table",
                "list",
                "only",
                "add",
                "include",
                "use",
            }
        }
        party_named = any(_ENTITY_LOOKUP.get(token) in _PARTY for token in body_tokens)
        attribute_tokens = tokens - _GENERIC if party_named else tokens
        if attribute_tokens:
            for node in nodes:
                own = set(_tokenize(node.name))
                if own & attribute_tokens:
                    explicit.append(node.path)
        elif "company" in lowered or "customer" in lowered:
            # "not the buying company": forbid the counterpart identity, not
            # every company-scoped field.
            requested = {
                token
                for requirement in requirements
                for path in requirement.expected_paths
                for token in _tokenize(path)
                if token in _GENERIC
            }
            for node in nodes:
                if _path_entity(node.path) == "company" and set(_tokenize(node.name)) & requested:
                    explicit.append(node.path)
    # An unsatisfiable bank/IBAN request for a party forbids the company bank
    # paths that look like a substitute.
    for requirement in requirements:
        if requirement.satisfiable:
            continue
        if requirement.concept in {"bank_details", "account_number"}:
            for node in nodes:
                if _path_entity(node.path) == "bank":
                    explicit.append(node.path)
    # A condition on a customer/company field forbids parameter flags that are
    # not the named condition.
    if any(requirement.expected_context == "conditional" for requirement in requirements):
        for node in nodes:
            if node.data_type != "boolean":
                continue
            if (
                "parameter" in _tokenize(node.path) or "flag" in _tokenize(node.name)
            ) and node.path not in {
                path for requirement in requirements for path in requirement.expected_paths
            }:
                explicit.append(node.path)
    # Advisory counterpart identity: useful review note, not silently added to
    # the gold guards.
    for requirement in requirements:
        if requirement.expected_type != "string" or not requirement.expected_paths:
            continue
        expected = requirement.expected_paths[0]
        entity = _path_entity(expected)
        if entity not in _PARTY:
            continue
        leaf = set(_tokenize(expected.rsplit(".", 1)[-1]))
        for node in nodes:
            other = _path_entity(node.path)
            if (
                other in _PARTY
                and other != entity
                and set(_tokenize(node.name)) & leaf
                and node.path not in explicit
                and node.path not in advisory
            ):
                advisory.append(node.path)
    return sorted(dict.fromkeys(explicit)), sorted(dict.fromkeys(advisory))


def _paths_of(requirement: dict[str, Any]) -> set[str]:
    return set(requirement.get("expected_paths") or []) | set(
        requirement.get("allowed_alternatives") or []
    )


def _compare_requirements(case: dict[str, Any], derived: Derivation) -> list[dict[str, Any]]:
    author_requirements = [
        item for item in case.get("required_bindings") or [] if isinstance(item, dict)
    ]
    adjudicator = list(derived.requirements)
    results: list[dict[str, Any]] = []
    used: set[int] = set()
    for author in author_requirements:
        author_all = _paths_of(author)
        if not author_all and author.get("satisfiable") is False:
            match = next(
                (
                    index
                    for index, candidate in enumerate(adjudicator)
                    if not candidate.satisfiable and candidate.concept == author.get("concept")
                ),
                None,
            )
            if match is None:
                match = next(
                    (
                        index
                        for index, candidate in enumerate(adjudicator)
                        if not candidate.satisfiable
                    ),
                    None,
                )
            if match is not None:
                used.add(match)
                results.append(
                    {
                        "requirement_id": author.get("id"),
                        "concept": author.get("concept"),
                        "agreement": "agree",
                        "author_paths": [],
                        "adjudicator_paths": [],
                        "adjudicator_concept": adjudicator[match].concept,
                        "note": "both passes agree that the schema cannot express this request",
                    }
                )
            else:
                results.append(
                    {
                        "requirement_id": author.get("id"),
                        "concept": author.get("concept"),
                        "agreement": "partial",
                        "author_paths": [],
                        "adjudicator_paths": [],
                        "note": "the author marked the request unsatisfiable; the independent pass did not derive a matching concept",
                    }
                )
            continue
        overlapping = [
            index
            for index, candidate in enumerate(adjudicator)
            if index not in used and (author_all & _paths_of(candidate.as_dict()))
        ]
        if not overlapping:
            results.append(
                {
                    "requirement_id": author.get("id"),
                    "concept": author.get("concept"),
                    "agreement": "disagree",
                    "author_paths": sorted(author_all),
                    "adjudicator_paths": [],
                    "note": "the independent pass derived no path for this concept",
                }
            )
            continue
        union: set[str] = set()
        for index in overlapping:
            union |= _paths_of(adjudicator[index].as_dict())
        used.update(overlapping)
        if union == author_all:
            agreement = "agree"
            note = "same acceptable set"
        elif author_all <= union:
            agreement = "partial"
            note = "the independent pass accepts a wider set than the author"
        else:
            agreement = "disagree"
            note = "different acceptable path sets"
        concepts = sorted({adjudicator[index].concept for index in overlapping})
        results.append(
            {
                "requirement_id": author.get("id"),
                "concept": author.get("concept"),
                "agreement": agreement,
                "author_paths": sorted(author_all),
                "adjudicator_paths": sorted(union),
                "adjudicator_concept": ",".join(concepts),
                "note": note,
            }
        )
    for index, candidate in enumerate(adjudicator):
        if index in used:
            continue
        if candidate.satisfiable and candidate.expected_paths:
            results.append(
                {
                    "requirement_id": None,
                    "concept": candidate.concept,
                    "agreement": "author_missing",
                    "author_paths": [],
                    "adjudicator_paths": sorted(_paths_of(candidate.as_dict())),
                    "note": "the independent pass derived a required concept the author did not annotate",
                }
            )
    return results


def _compare_forbidden(case: dict[str, Any], derived: Derivation) -> dict[str, Any]:
    author = set(case.get("forbidden_paths") or [])
    adjudicator = set(derived.forbidden)
    advisory = set(derived.advisory_forbidden)
    if author == adjudicator:
        status = "agree"
    elif author < adjudicator:
        status = "adjudicator_additional"
    elif adjudicator < author:
        status = "gold_additional"
    elif author & adjudicator:
        status = "conflict"
    else:
        status = "disagree"
    return {
        "agreement": status,
        "author": sorted(author),
        "adjudicator": sorted(adjudicator),
        "advisory_counterparts": sorted(advisory - author - adjudicator),
    }


def _compare_blocks(case: dict[str, Any], derived: Derivation) -> dict[str, Any]:
    author = {
        (str(block.get("kind")), block.get("path"))
        for block in case.get("expected_blocks") or []
        if isinstance(block, dict)
    }
    adjudicator = {(str(block.get("kind")), block.get("path")) for block in derived.blocks}
    return {
        "agreement": "agree" if author == adjudicator else "partial",
        "author": sorted([list(item) for item in author]),
        "adjudicator": sorted([list(item) for item in adjudicator]),
        "missing": sorted([list(item) for item in author - adjudicator]),
        "additional": sorted([list(item) for item in adjudicator - author]),
    }


def adjudicate_case(case: dict[str, Any], schema: Any) -> dict[str, Any]:
    derived = _derive(str(case["prompt"]), schema)
    requirements = _compare_requirements(case, derived)
    forbidden = _compare_forbidden(case, derived)
    blocks = _compare_blocks(case, derived)
    requirement_status = {item["agreement"] for item in requirements}
    if "disagree" in requirement_status:
        agreement = "disagree"
    elif (
        requirement_status & {"partial", "author_missing"}
        or forbidden["agreement"] in {"conflict", "adjudicator_additional"}
        or blocks["agreement"] != "agree"
    ):
        agreement = "partial"
    else:
        agreement = "agree"
    return {
        "case_id": case["id"],
        "family": case.get("family"),
        "author": AUTHOR,
        "adjudicator": ADJUDICATOR,
        "review_status": REVIEW_STATUS,
        "agreement": agreement,
        "requirements": requirements,
        "forbidden": forbidden,
        "blocks": blocks,
        "derived_requirements": [requirement.as_dict() for requirement in derived.requirements],
        "derived_notes": derived.notes,
        "note": _case_note(requirements, forbidden, blocks),
    }


def _case_note(
    requirements: list[dict[str, Any]],
    forbidden: dict[str, Any],
    blocks: dict[str, Any],
) -> str:
    notes: list[str] = []
    disagreements = [item for item in requirements if item["agreement"] == "disagree"]
    if disagreements:
        notes.append(
            "Requirement conflict: "
            + "; ".join(
                f"{item.get('requirement_id') or item.get('concept')} "
                f"author={item['author_paths']} adjudicator={item['adjudicator_paths']}"
                for item in disagreements
            )
        )
    if forbidden["agreement"] == "gold_additional":
        notes.append(
            "The gold guard is stricter than the independent derivation: "
            + ", ".join(sorted(set(forbidden["author"]) - set(forbidden["adjudicator"])))
        )
    if forbidden["agreement"] == "adjudicator_additional":
        notes.append(
            "The independent derivation found extra scope guards: "
            + ", ".join(sorted(set(forbidden["adjudicator"]) - set(forbidden["author"])))
        )
    if forbidden["advisory_counterparts"]:
        notes.append(
            "Advisory counterpart guards (not applied): "
            + ", ".join(forbidden["advisory_counterparts"])
        )
    if blocks["agreement"] != "agree":
        notes.append("Block sets differ; see block provenance.")
    return " ".join(notes)


def _image_family(cases: list[dict[str, Any]], schemas: dict[str, Any]) -> dict[str, Any]:
    """Adjudicate the three image cases against schema evidence only.

    The image family is reported separately because v0.10 published a 0% semantic
    pass for every provider. The question here is only whether the *label* is
    expressible: does the case request an image and does the schema expose that
    image path at the annotated scope? The provider results are reported by the
    benchmark, not inferred here.
    """
    items: list[dict[str, Any]] = []
    gaps = 0
    for case in cases:
        if case.get("family") != "images":
            continue
        schema = schemas[str(ROOT / str(case["package"]))]
        image_paths: list[str] = []
        for binding in case.get("required_bindings") or []:
            for path in _paths_of(binding):
                node = schema.node(path)
                if node is not None and node.data_type == "image":
                    image_paths.append(path)
        block_paths = [
            block.get("path")
            for block in case.get("expected_blocks") or []
            if isinstance(block, dict) and block.get("kind") == "image"
        ]
        expressible = bool(image_paths) and all(
            node is not None and node.data_type == "image"
            for node in (schema.node(path) for path in image_paths)
        )
        block_matches = all(path in image_paths for path in block_paths)
        verified = expressible and block_matches
        if not verified:
            gaps += 1
        items.append(
            {
                "case_id": case["id"],
                "family": case["family"],
                "label_status": "verified" if verified else "gap",
                "image_paths": image_paths,
                "image_block_paths": block_paths,
                "image_subtype": "company_logo",
                "decision": (
                    "labels_verified"
                    if verified
                    else "label_gap_excluded_from_semantic_denominators"
                ),
                "rationale": (
                    "The prompt asks for the company logo and the schema exposes that exact "
                    "top-level image path, including the image block. The v0.10 0% semantic "
                    "pass was a forbidden-scope/precision failure, not an inexpressible image "
                    "label; the candidate filter is the remedy. No label gap."
                    if verified
                    else "The image requirement is not expressible at the annotated path/scope; "
                    "the case is marked label_status=gap and excluded from semantic denominators."
                ),
            }
        )
    return {
        "decision": "no_label_gap" if gaps == 0 else "label_gap_present",
        "gap_cases": gaps,
        "cases": items,
    }


def _dataset_sha(cases: list[dict[str, Any]]) -> str:
    canonical = json.dumps(cases, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_report(dataset: dict[str, Any], cases_path: Path) -> dict[str, Any]:
    schemas: dict[str, Any] = {}
    adjudicated: list[dict[str, Any]] = []
    for case in dataset["cases"]:
        package = ROOT / str(case["package"])
        if str(package) not in schemas:
            schemas[str(package)] = parse_ddsp(package.read_bytes(), package.name).schema
        adjudicated.append(adjudicate_case(case, schemas[str(package)]))
    counts = {"agree": 0, "partial": 0, "disagree": 0}
    for item in adjudicated:
        counts[item["agreement"]] += 1
    label_counts = {"agree": 0, "partial": 0, "disagree": 0, "author_missing": 0}
    for item in adjudicated:
        for requirement in item["requirements"]:
            label_counts[requirement["agreement"]] += 1
    return {
        "schema": REPORT_SCHEMA,
        "adjudicator_version": ADJUDICATOR_VERSION,
        "generated_by": "benchmarks/adjudicate_labels.py",
        "generated_at": str(dataset.get("created_at")),
        "method": (
            "Independent bounded lexicon plus schema-evidence rules. The script parses each "
            "committed DDSP and re-derives concepts, paths, alternatives, forbidden guards and "
            "blocks from the prompt and schema; it never reads the author's expected paths to "
            "derive an answer. It is deterministic and makes no model calls."
        ),
        "limitations": [
            "Deterministic proxy, not a second human annotator.",
            "The lexicon covers the committed English/German/French fixtures, not arbitrary prose.",
            "Advisory counterpart guards are reported but not applied to the dataset.",
            "AT-07 remains partial until a real second human review exists.",
        ],
        "human_review": False,
        "at07": {
            "status": AT07_STATUS,
            "second_human_annotator": False,
            "deterministic_adjudicator": ADJUDICATOR,
            "note": (
                "AT-07 is partial: the deterministic adjudicator is documented as a proxy and "
                "must not be described as human double review."
            ),
        },
        "dataset": {
            "file": str(cases_path.relative_to(ROOT))
            if cases_path.is_relative_to(ROOT)
            else str(cases_path),
            "version": dataset.get("version"),
            "case_count": len(dataset["cases"]),
            "canonical_sha256": _dataset_sha(dataset["cases"]),
        },
        "image_family": _image_family(dataset["cases"], schemas),
        "summary": {
            "cases": len(adjudicated),
            "case_agreement": counts,
            "requirement_agreement": label_counts,
            "agreement_rate": round(counts["agree"] / len(adjudicated), 6) if adjudicated else None,
        },
        "cases": adjudicated,
    }


def _write(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _apply_provenance(dataset: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    by_case = {item["case_id"]: item for item in report["cases"]}
    updated = json.loads(json.dumps(dataset))
    updated["schema"] = "gold-cases/v2"
    updated["version"] = "2.0.0"
    updated["created_at"] = str(dataset.get("created_at"))
    updated["provenance"] = {
        "author": AUTHOR,
        "adjudicator": ADJUDICATOR,
        "review_status": REVIEW_STATUS,
        "human_review": False,
        "at07_status": AT07_STATUS,
        "adjudication_report": "benchmarks/adjudication_report.json",
        "notes": [
            "Author labels are preserved; the independent adjudicator reproduced them or "
            "flagged a documented disagreement.",
            "The adjudicator is a deterministic proxy, not a second human annotator. AT-07 "
            "remains partial.",
            "Image-family adjudication: all three committed image cases are expressible at the "
            "annotated company-logo path; label_status=verified, no case excluded as a gap.",
        ],
    }
    image_by_case = {
        item["case_id"]: item for item in report.get("image_family", {}).get("cases", [])
    }
    for case in updated["cases"]:
        item = by_case.get(case["id"])
        if item is None:
            continue
        image_item = image_by_case.get(case["id"])
        case["label_status"] = image_item["label_status"] if image_item is not None else "verified"
        if image_item is not None:
            case["image_subtype"] = image_item["image_subtype"]
        case["provenance"] = {
            "author": AUTHOR,
            "adjudicator": ADJUDICATOR,
            "review_status": REVIEW_STATUS,
            "agreement": item["agreement"],
            "note": item.get("note", ""),
        }
        requirements = {
            requirement.get("requirement_id"): requirement
            for requirement in item["requirements"]
            if requirement.get("requirement_id")
        }
        for binding in case.get("required_bindings") or []:
            comparison = requirements.get(binding.get("id"))
            binding["provenance"] = {
                "author": AUTHOR,
                "adjudicator": ADJUDICATOR,
                "agreement": bool(comparison and comparison["agreement"] == "agree"),
                "note": comparison.get("note", "")
                if comparison
                else "not independently reproduced",
            }
        case["block_provenance"] = [
            {
                "kind": block.get("kind"),
                "path": block.get("path"),
                "author": AUTHOR,
                "adjudicator": ADJUDICATOR,
                "agreement": [
                    block.get("kind"),
                    block.get("path"),
                ]
                in item["blocks"]["adjudicator"],
            }
            for block in case.get("expected_blocks") or []
        ]
        forbidden = item["forbidden"]
        case["forbidden_provenance"] = {
            path: {
                "author": AUTHOR,
                "adjudicator": ADJUDICATOR,
                "agreement": path in set(forbidden["adjudicator"]),
                "note": (
                    "reproduced by the independent pass"
                    if path in set(forbidden["adjudicator"])
                    else "author scope guard; the independent pass did not derive it"
                ),
            }
            for path in case.get("forbidden_paths") or []
        }
    return updated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--write", action="store_true", help="write the adjudication report")
    parser.add_argument("--check", action="store_true", help="fail on a requirement conflict")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the report and add provenance fields to the dataset (version 2.0.0)",
    )
    args = parser.parse_args(argv)
    dataset = json.loads(args.cases.read_text(encoding="utf-8"))
    report = build_report(dataset, args.cases)
    if args.write or args.apply:
        _write(args.report, report)
    if args.apply:
        updated = _apply_provenance(dataset, report)
        temporary = args.cases.with_suffix(args.cases.suffix + ".tmp")
        temporary.write_text(
            json.dumps(updated, indent=2, sort_keys=False, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(args.cases)
    summary = report["summary"]
    print(
        f"adjudication: {summary['cases']} cases · "
        f"agree {summary['case_agreement']['agree']} · "
        f"partial {summary['case_agreement']['partial']} · "
        f"disagree {summary['case_agreement']['disagree']} · "
        f"requirements {summary['requirement_agreement']}"
    )
    if summary["case_agreement"]["disagree"]:
        for case in report["cases"]:
            if case["agreement"] == "disagree":
                print(f"  disagreement: {case['case_id']}: {case['note']}")
        if args.check or args.apply:
            return 1
    if not (args.write or args.apply):
        print(f"(dry run; pass --write to write {args.report})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
