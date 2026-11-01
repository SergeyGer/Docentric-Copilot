# ADR-0001: Use a typed, versioned Template IR

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-01 |
| Deciders | Project maintainers |
| Related | [TEMPLATE_IR](../TEMPLATE_IR.md), [ARCHITECTURE](../ARCHITECTURE.md) |

## Context

The product must turn a natural-language requirement and a data schema into a document that can be
validated, versioned, reviewed and compiled repeatedly. Three implementation styles were considered:

1. **Direct generation.** Ask a model (or a template engine) to emit DOCX/HTML directly.
2. **String/placeholder templates.** Keep a document with `{{field}}` placeholders and substitute text.
3. **A typed intermediate representation.** Model the document as data, validate it, then compile it.

Direct generation makes correctness unverifiable: the artefact is opaque and every model call produces
a different binary. Placeholder templates are reviewable but cannot express typed constraints,
collections, aliases, conditionals or OOXML structure safely, and placeholder strings can appear in
prose accidentally. Both approaches make it hard to answer "does every dynamic value exist in the
schema?" before producing a document.

## Decision

Introduce a **Template IR v1.0**: a pydantic model tree with `extra="forbid"` that describes documents,
sections, blocks, inline content, expressions, formatting and page setup. The IR is the only contract
between planning and execution. It has:

- no XPath, no executable code, no raw OOXML;
- a dotted-path reference for every dynamic value;
- defensive bounds on every string, collection, nesting depth and expression;
- canonical JSON and a SHA-256 digest for versioning and golden tests;
- an explicit version field and a migration registry;
- a generated JSON Schema for provider structured output and external tooling.

## Consequences

**Positive**

- Every binding can be resolved against the schema before compilation (FR-02, FR-07).
- The same document can be validated, previewed, diffed, stored and compiled by independent components.
- Unknown keys and unknown versions fail loudly, which limits the damage a model can do.
- Golden tests and revision diffs become meaningful because the document is data.

**Negative / costs**

- Every new document feature must be designed as a model change and an IR version decision.
- Rich Word features (footnotes, content controls, fields, tracked changes) cannot be represented
  without extending the model, which is deliberately slow.
- The IR is a second schema to maintain alongside the DDSP schema; cross-schema validation (V2/V3) is
  where most defects surface.
- Canonical JSON includes nulls, so adding a defaulted field changes digests and requires golden-file
  updates.

## Alternatives rejected

- **Direct DOCX from the model:** no reliable validation, no determinism, unsafe output.
- **Placeholder templates:** insufficient typing, no collection/alias semantics, ambiguous text
  substitution.
- **HTML as the source of truth:** HTML lacks the OOXML structure needed for a DOCX compiler and
  encourages a layout-first model that cannot be validated against a data schema.

## Follow-up

- Any new block kind or field requires an IR version decision (see
  [TEMPLATE_IR §9](../TEMPLATE_IR.md#9-versioning-and-migration-policy)).
- Keep `extra="forbid"`; do not add a catch-all metadata bag that would let unvalidated data through.
