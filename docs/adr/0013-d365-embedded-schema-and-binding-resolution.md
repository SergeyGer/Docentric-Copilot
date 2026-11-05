# ADR-0013 — D365 embedded schema and binding resolution

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-05 |
| Deciders | Project maintainers |
| Related | [Reference Templates](../REFERENCE_TEMPLATES.md), [ADR-0010](0010-reference-inspector.md), [ADR-0011](0011-reference-graph.md), [ADR-0012](0012-reference-diff-and-evaluation.md), [ADR-0005](0005-docentric-compatibility-gate.md), [Docentric AX Compatibility](../DOCENTRIC_AX_COMPATIBILITY.md) |

## Context

REF-01 reads a standalone Docentric DDSP package. The D365 examples in the reference corpus do not
ship one DDSP per document: the schema is embedded inside `customXml` `ProjectData`, as
`DataSources/DataSource/Schema/XsdList/MainXsd` XSD and `PreviewData`. REF-02 resolved content
controls and `ValueBinding` paths, but it only validated paths when an external DDSP was supplied;
without one, every path check was `not_checked`. That made "no DDSP" look like "no evidence" even
when the document carried a complete embedded schema.

The v0.10 P0 requirement is to use the evidence that actually exists, keep provenance for every
fact, and never turn missing or conflicting evidence into a successful binding. A second constraint
is legal: the Docentric example archive is vendor material, so it must stay in the ignored local
corpus and the committed code and tests must be synthetic.

The AX runtime gate is unchanged. Reading an embedded schema is static inspection; it is not a
Docentric AX execution or a compatibility claim.

## Decision

### Read-only extraction (`reference/d365_schema.py`)

- Discover `ProjectData` by root element **and** namespace in `customXml/itemN.xml`. A decoy
  `customXml` part is ignored. A malformed ProjectData part becomes a diagnostic, not a crash.
- Extract only facts that are actually present: `DataSource` declarations, `Schema/Origin`,
  `XsdList/MainXsd` XSD, `XmlNamespaceMappings`, `PreviewData/SampleXml` and `xse:label` /
  `xse:refCode` field metadata.
- Attach three provenance values to every schema fact: the OOXML part, an XPath-like location with
  local names and positional predicates, and a stable source id such as
  `customXml/item1.xml#dataSource[2]`. The path is descriptive; it is never evaluated.
- Build a canonical internal schema of fields, collections, scopes, XSD types, type families,
  namespaces and raw/canonical paths. Collection cardinality is inherited from `choice`/`sequence`
  and from the element's own `maxOccurs`; preview repetitions are recorded as corroborating counts,
  not as proof.
- Classify the document as `schema_source = projectdata | ddsp | unavailable`. Embedded ProjectData
  wins when it has a usable schema; a caller-supplied DDSP is a fallback only; otherwise the status
  is unavailable with explicit diagnostics.
- Accept a DOCX or a ZIP/AXPP that contains exactly one DOCX. A package with several DOCX templates
  is rejected with a clear error instead of silently analysing the first one.

### Binding resolution (`reference/binding_resolver.py`)

- Resolve `Source`/`Path`, `ResultDataType`, element kind and collection scope against the canonical
  schema. The only statuses are the six normative values:
  `resolved`, `ambiguous`, `unknown_path`, `type_mismatch`, `schema_unavailable`,
  `unsupported_expression`.
- `resolved` requires all of the following: an exact source name, an exact canonical path, a
  verified collection scope and a compatible type. Every resolved result carries `source_id` plus an
  OOXML `part#xpath` evidence string. No similarity search, fuzzy match, heuristic path repair or LLM
  call is allowed on the resolved path.
- Duplicate source names, duplicate canonical paths, unresolvable relative contexts, conflicting
  ProjectData parts and unsupported expressions are explicit diagnostics. Duplicates never produce
  `resolved`, even when the duplicate definitions happen to be identical.
- Relative `Source="."` bindings are resolved only through an enclosing `List` with a resolvable
  collection binding. A missing, ambiguous, non-collection or unsupported context is
  `unknown_path` (or the matching explicit status), never a guess.
- Prefixed path segments are accepted only when the prefix is declared in the source's
  `XmlNamespaceMappings` **and** maps to the data namespace. An undeclared or non-data prefix is an
  `unsupported_expression`, because local-name matching alone would silently ignore namespaces.
- The report follows the v0.10 result contract: `template_id`, `platform: D365FO`,
  `schema_source`, `schema_evidence[]`, `binding_results[]` (`element_id`, `status`, `raw_path`,
  `canonical_path`, `source_id`, `evidence`) and `runtime_compatibility: not_tested`. Counts,
  schema summary and diagnostics are additive, stable fields.
- Surface: CLI `docentric-copilot reference d365 PATH --json OUT [--ddsp PATH]` and
  `POST /api/v1/reference/d365` (multipart or a path confined to `DC_REFERENCE_CORPUS_ROOTS`).

### Security and determinism

- Reuse the REF-00 safety layer: bounded ZIP decompression (entry count, uncompressed size,
  compression ratio, encrypted entries, symlinks, path traversal), XML parsing with DTDs, external
  entities and network access disabled, and node/depth limits.
- Bound the adapter itself: number of customXml parts, DataSources, schema fields, collections,
  XSD depth, preview nodes and emitted diagnostics. Every truncation is reported as a warning or
  diagnostic.
- Never execute X++/.axpp, macros, embedded objects or expressions. Input files stay untrusted.
- Sorting and JSON serialization are deterministic; the same input and limits produce the same
  report bytes.

### PR-01 documentation baseline

The release documentation is part of the contract. This decision also freezes the v0.10 baseline:
the package version stays 0.9.0 until release, the changelog carries the work under
`[Unreleased]`, README/ROADMAP state the partial status honestly, and every claimed metric names
its fixture set and command.

## Consequences

Positive:

- D365 documents without a standalone DDSP can be checked with evidence derived from the document
  itself, including the exact OOXML location and data source.
- The six-status taxonomy is machine-readable, exhaustive and testable; no unresolved construction
  is silently dropped.
- `resolved` is conservative: exact names and paths, verified scope, compatible type and provenance
  are all required. Synthetic negative fixtures cover duplicates, wrong context, missing fields,
  type conflicts, corrupted ProjectData, ambiguous sources and unsupported expressions.
- The public test suite stays synthetic and the corpus assessment script writes counts only under
  the ignored `.tools/` directory.
- The AX gate is untouched: every report says `runtime_compatibility: not_tested`.

Negative and open:

- The adapter is intentionally narrower than the Docentric format. Expressions, predicates,
  aggregates, relative contexts without a `List` and data-grouping semantics are not resolved; they
  are reported as `unsupported_expression` or `unknown_path`. Per-document coverage therefore
  includes non-resolved bindings.
- A relative `Source="."` binding under a `Group` without an enclosing `List` stays unresolved even
  when the group itself has a binding. Supporting that scope needs format evidence that is not
  available in this repository.
- The XSD walker supports the common `sequence`/`choice`/`all`, named complex types, groups,
  attributes and simple restrictions. `xs:any`, unresolved groups and other dynamic constructs are
  reported, not interpreted.
- Field metadata is limited to the label/ref-code annotation; it is not a complete Docentric
  Designer metadata model.
- No benchmark, IR projection, visual diff or persistence work is included; those are separate P1
  workstreams.
- The canonical schema is larger than the report exposes. Reports include counts, evidence and
  binding results; the full canonical model is available through the Python API only.

## Alternatives considered

- **Require a standalone DDSP for every D365 document.** Rejected: the corpus demonstrates that the
  embedded schema is the only evidence available, and requiring DDSP would turn every D365 document
  into `schema_unavailable`.
- **Reuse REF-02's path index without a canonical model.** Rejected: the existing index loses
  attribute/type/provenance detail, cannot distinguish duplicate paths, and validates only when a
  DDSP is present.
- **Infer the schema from `PreviewData` alone.** Rejected: sample data shows values, not the full
  schema, types or optional fields. It is corroborating evidence only.
- **Fuzzy-match source and path names to increase coverage.** Rejected: it produces false
  `resolved` results and violates the evidence rule.
- **Treat duplicate sources/paths as resolved when definitions agree.** Rejected: duplicates are a
  provenance conflict; the spec requires diagnostics, not a guess.
- **Let a missing DDSP block the check.** Rejected: embedded schema evidence is sufficient when it
  is present and parsed; absence of DDSP alone is not a failure.
- **Evaluate expressions or Docentric functions.** Rejected: no execution, and the supported subset
  would be unverifiable.

## Follow-up

- PR-04/PR-05: gold dataset and live benchmark, including D365 cases and runtime diagnostics.
- Extend the resolver only with evidence-backed semantics (nested context rules, supported
  expressions) and add fixtures before widening the accepted subset.
- Consider exposing the canonical schema as an opt-in API projection behind a feature flag; the
  default remains the bounded evidence report.
- Licensed AX runtime testing remains the only path to changing `runtime_compatibility`.
