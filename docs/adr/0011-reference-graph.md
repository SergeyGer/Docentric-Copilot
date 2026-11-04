# ADR-0011 — ReferenceGraph and a separate read-only Reference IR

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-04 |
| Deciders | Project maintainers |
| Related | [Reference Templates](../REFERENCE_TEMPLATES.md), [ADR-0010](0010-reference-inspector.md), [ADR-0001](0001-template-ir.md), [ADR-0005](0005-docentric-compatibility-gate.md) |

## Context

Milestone A produced a flat inspection report: artifacts, content controls, ProjectData joins and
path resolution. That report answers "what is in this file", but not "how do the controls, typed
Docentric elements, data sources and schema fields relate to each other". REF-03 requires a
relational view, including repeating lists, conditional sections, unresolved bindings and the
distinction between a technical id join and a resolved schema path.

Two existing contracts constrain the solution:

- Template IR 1.0 deliberately forbids raw XPath and raw OOXML. Weakening it to carry imported
  Docentric bindings would invalidate the compiler, validator and golden files, and would imply
  semantic guarantees that static inspection cannot make.
- The Docentric AX gate is fail-closed. Nothing in the reference path may enable
  `target=docentric-ax`, emit a native template or claim runtime compatibility.

A graph also needs a stable, inspectable product. An untyped adjacency map would be hard to test,
version and consume. It must not grow cycles from untrusted `ChildElements` references, and every
unresolved item must stay visible with a reason.

## Decision

Introduce two separate, versioned, read-only contracts in `docentric_copilot.reference`:

1. **`ReferenceGraph` v1.0** (`graph.py`) built deterministically from the inspector report plus
   optional normalized schemas. It has four node kinds (`control`, `element`, `source`,
   `schema_field`) and four directed edge types (`bound_to`, `resolves_to`, `iterates`,
   `condition`). Every edge and every node carries `resolved`, `ambiguous` or `unknown`.
   `ChildElements` traversal is cycle-cut with a diagnostic; unresolved controls, unknown schema
   paths and stale child references remain in `unresolved` with reasons. The graph records counts
   by kind and status plus explicit denominators for controls and edge coverage.
2. **`ReferenceDocument`** (`projection.py`) as the read-only Reference IR. It groups projected
   controls into document sections with a display label, kind, binding path, status, source
   location and capability. It declares `ir_kind: "reference"`, `compilable: false` and
   `template_ir_compatible: false`, and carries `runtime_compatibility: "not_tested"`.

The real DDSP adapter (`ddsp_real.py`) supplies the schema side of the graph. It parses the
`dsp:dataSourcePackage` document into the existing `NormalizedSchema`, preserving `GeneralData` and
`MainData` as distinct sections, exposing XSD attributes as `@Name` paths, and reporting
unsupported constructs explicitly. The existing synthetic DDSP/XSD/sample parser remains the
fallback by format detection, not by file extension.

The decision includes these boundaries:

- Python APIs `build_reference_graph` and `project_graph`; CLI
  `docentric-copilot reference graph PATH --json OUT [--ddsp PATH] [--projection OUT]`; HTTP
  `POST /api/v1/reference/graph` (upload or corpus-confined path).
- No import mode. `importable` is reserved in the capability vocabulary but nothing is emitted as
  importable in v0.6; recognized elements are `reference_only`, unknown elements `unsupported`.
- Raw XPath and raw OOXML remain untrusted reference data. They are never evaluated, resolved as
  filesystem paths or copied into Template IR.
- Serialization is canonical: sorted nodes/edges, no timestamps, hostnames or absolute paths, and
  a content digest. Two runs over the same inputs produce identical JSON.
- The AX gate is not touched: `target=docentric-ax` still returns `409`, V5 remains `not_tested`,
  and no AXPP/DLL/macro is executed.

## Consequences

Positive:

- Lists, conditions, sources and schema fields are now queryable relations rather than a flat
  control list, without changing Template IR 1.0.
- Unresolved and ambiguous material has a first-class representation, so coverage cannot be
  inflated by dropping it.
- The projection gives UI and evaluation work a stable, explicitly non-compilable contract.
- The real DDSP adapter turns six real AX 2012 contracts into one normalized model with stable
  paths, types, collections, labels and evidence.

Negative and open:

- The graph is a static evidence model. It does not prove XPath semantics, localization,
  aggregation or runtime rendering.
- D365 DOCX files without a standalone DDSP have no schema fields; their controls are still
  graphed, but binding validation remains `not_checked`.
- The graph and report can contain binding paths and metadata from licensed material. Operators
  must keep real-corpus outputs private; tests remain synthetic only.
- `ChildElements` cycles are cut rather than represented as cycles; the diagnostic preserves the
  fact instead of hiding it.
- `NormalizedSchema.attributes` is capped at 50 per node by the existing model. Attribute leaves
  stay path-addressable, and the cap is listed as an explicit unsupported construct where reached.

## Alternatives considered

- **Extend Template IR with raw bindings.** Rejected: weakens the validated compiler contract and
  requires a migration ADR; the specification explicitly asks for a separate Reference IR.
- **Use an untyped adjacency map.** Rejected: no stable OpenAPI schema, no status/denominator
  contract, harder determinism and testing.
- **Project only resolved elements.** Rejected: contradicts REF-03 and hides exactly the cases an
  inspector must report.
- **Implement import-supported mode now.** Rejected: no semantic-loss analysis or licensed runtime
  evidence; the fail-closed default stays reference-only.
- **Reuse the metadata resolver's flat structure as the graph.** Rejected: it has no schema-field
  nodes, no list/condition edges and no source grouping.

## Follow-up

- REF-04: provenance and semantic/structural diff over the stable graph.
- REF-05: reference-based semantic evaluation using projected elements and statuses.
- REF-06: inspector UI over `ReferenceDocument`; it must display, not compile.
- REF-07: licensed runtime testing before any import or native AX decision.
- A future import ADR must define semantic-loss checks and may promote Field/If/List/Image to
  `importable` only with that evidence.
