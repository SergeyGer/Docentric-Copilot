"""Deterministic candidate search over a normalized schema.

This module is the explainable baseline for FR-02. It is used by the offline
``mock`` provider, by the planner as a pre-filter, and by the evaluation harness
to compare an LLM against a reproducible baseline. It performs no I/O and no
model calls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from docentric_copilot.ddsp_parser.models import NormalizedSchema, SchemaNode

from .mapping import RequirementKind

_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "of", "for", "with", "in", "on", "to", "from",
        "create", "make", "generate", "professional", "document", "please", "show",
        "include", "including", "display", "put", "add", "use", "using", "our", "their",
        "is", "are", "be", "when", "if", "each", "all", "by", "as", "at", "it",
    }
)

#: Concept -> additional tokens that should match it. Deliberately small and
#: domain-specific; anything not listed here simply scores zero.
SYNONYMS: dict[str, tuple[str, ...]] = {
    "customer": ("client", "buyer", "billto", "soldto", "cust"),
    "vendor": ("supplier", "seller", "payee"),
    "logo": ("image", "picture", "brand", "mark"),
    "line": ("item", "row", "product", "service", "detail", "lineitem"),
    "quantity": ("qty", "count", "units"),
    "price": ("rate", "unitprice", "cost"),
    "amount": ("total", "sum", "value", "gross", "net", "subtotal"),
    "total": ("totalamount", "gross", "sum", "grandtotal", "amount", "final", "payable"),
    "tax": ("vat", "gst", "salestax", "duty"),
    "vat": ("tax", "iseu", "vatnumber", "taxid"),
    "bank": ("iban", "swift", "bic", "account", "bankdetails"),
    "address": ("addr", "street", "location"),
    "date": ("day", "dt", "issuedate", "documentdate"),
    "number": ("num", "no", "id", "identifier", "reference", "code"),
    "description": ("desc", "text", "name", "title", "label"),
    "currency": ("ccy", "currencycode"),
    "email": ("mail", "contactemail"),
    "company": ("organization", "organisation", "our", "supplier"),
}

_TYPE_KEYWORDS: dict[RequirementKind, tuple[str, ...]] = {
    RequirementKind.IMAGE: ("logo", "image", "photo", "picture", "graphic", "signature"),
    RequirementKind.COLLECTION: ("line", "item", "product", "service", "row", "detail"),
    RequirementKind.DATE: ("date", "day"),
    RequirementKind.NUMBER: ("quantity", "price", "amount", "total", "tax", "net", "gross", "rate"),
    RequirementKind.BOOLEAN: ("flag", "notice", "enabled", "shown", "reverse charge"),
}


def tokenize(text: str) -> tuple[str, ...]:
    """Split identifiers and prose into lowercase concept tokens."""
    parts: list[str] = []
    for chunk in re.split(r"[^A-Za-z0-9]+", text):
        parts.extend(_WORD.findall(chunk))
    tokens = [part.lower() for part in parts if part]
    normalized: list[str] = []
    for token in tokens:
        if token in _STOPWORDS or len(token) < 2:
            continue
        plural = len(token) > 3 and token.endswith("s") and not token.endswith("ss")
        normalized.append(token[:-1] if plural else token)
    return tuple(normalized)


def expand(tokens: tuple[str, ...]) -> set[str]:
    """Add one level of synonyms for the *original* tokens (no transitive closure)."""
    expanded = set(tokens)
    original = set(tokens)
    for concept, aliases in SYNONYMS.items():
        group = {concept, *aliases}
        if original & group:
            expanded |= group
    return expanded


def infer_kind(text: str) -> RequirementKind:
    lowered = text.lower()
    if any(keyword in lowered for keyword in _TYPE_KEYWORDS[RequirementKind.COLLECTION]):
        if any(word in lowered for word in ("lines", "items", "products", "rows", "table")):
            return RequirementKind.COLLECTION
    for kind in (
        RequirementKind.IMAGE,
        RequirementKind.DATE,
        RequirementKind.BOOLEAN,
        RequirementKind.NUMBER,
    ):
        if any(keyword in lowered for keyword in _TYPE_KEYWORDS[kind]):
            return kind
    return RequirementKind.TEXT


@dataclass(frozen=True, slots=True)
class Candidate:
    path: str
    data_type: str
    score: float
    reason: str
    collection: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "data_type": self.data_type,
            "score": round(self.score, 3),
            "reason": self.reason,
            "collection": self.collection,
        }


def _depth(path: str) -> int:
    return path.count(".")


def _node_score(
    node: SchemaNode,
    core_tokens: set[str],
    synonym_tokens: set[str],
    kind: RequirementKind,
) -> float:
    own_tokens = set(tokenize(node.name))
    context_tokens = set(tokenize(node.path.rsplit(".", 1)[0]))
    score = 0.0
    for token in core_tokens:
        if token in own_tokens:
            score += 2.0
        elif token in context_tokens:
            score += 0.6
    # Synonym matches are strictly weaker evidence than literal ones.
    for token in synonym_tokens - core_tokens:
        if token in own_tokens:
            score += 0.8
        elif token in context_tokens:
            score += 0.25
    if kind is RequirementKind.IMAGE and node.data_type == "image":
        score += 1.5
    if kind is RequirementKind.NUMBER and node.data_type == "number":
        score += 0.8
    if kind is RequirementKind.DATE and node.data_type == "date":
        score += 0.8
    if kind is RequirementKind.BOOLEAN and node.data_type == "boolean":
        score += 0.8
    if kind is RequirementKind.COLLECTION and node.collection:
        score += 2.0
    if kind is RequirementKind.TEXT and node.data_type in {"string", "any"}:
        score += 0.2
    # A "Name" field is the most representative text value of a party/company
    # block; without this, siblings tie and the choice becomes arbitrary.
    if kind is RequirementKind.TEXT and "name" in own_tokens:
        score += 0.3
    score -= 0.05 * max(0, _depth(node.path) - 2)
    return max(0.0, score)


def search_candidates(
    schema: NormalizedSchema,
    requirement: str,
    *,
    kind: RequirementKind = RequirementKind.ANY,
    limit: int = 5,
    include_collections: bool = False,
) -> list[Candidate]:
    """Rank schema nodes for a natural-language requirement."""
    core_tokens = tokenize(requirement)
    if not core_tokens:
        return []
    tokens = expand(core_tokens)
    best_raw = 2.0 * len(core_tokens) + 3.0
    core_set = set(core_tokens)
    scored: list[Candidate] = []
    for path in schema.paths:
        node = schema.node(path)
        if node is None:
            continue
        if node.collection and not include_collections:
            continue
        if not node.collection and node.children:
            continue
        if kind is RequirementKind.IMAGE and node.data_type != "image":
            continue
        raw = _node_score(node, core_set, tokens, kind)
        if raw <= 0:
            continue
        scored.append(
            Candidate(
                path=path,
                data_type=node.data_type,
                score=min(1.0, raw / best_raw),
                reason="matched tokens: "
                + ", ".join(sorted(set(core_tokens) & set(tokenize(node.path)))),
                collection=node.collection,
            )
        )
    scored.sort(key=lambda candidate: (-candidate.score, _depth(candidate.path), candidate.path))
    return scored[:limit]


def decide_status(
    candidates: list[Candidate],
    *,
    threshold: float = 0.35,
    relative_margin: float = 0.15,
    min_gap: float = 0.03,
) -> str:
    """Map a ranked candidate list to ``resolved`` / ``ambiguous`` / ``missing``.

    A winner must both clear an absolute threshold and beat the runner-up by a
    relative margin; otherwise the honest answer is "ask the user".
    """
    if not candidates or candidates[0].score < threshold:
        return "missing"
    if len(candidates) > 1:
        gap = candidates[0].score - candidates[1].score
        if gap < max(min_gap, relative_margin * candidates[0].score):
            return "ambiguous"
    return "resolved"


__all__ = [
    "Candidate",
    "SYNONYMS",
    "decide_status",
    "expand",
    "infer_kind",
    "search_candidates",
    "tokenize",
]
