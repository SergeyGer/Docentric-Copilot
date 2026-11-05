# ADR-0016 — Safe Reference → IR import and an independent visual diff

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-05 |
| Deciders | Project maintainers |
| Related | [#26](https://github.com/SergeyGer/Docentric-Copilot/issues/26), [#27](https://github.com/SergeyGer/Docentric-Copilot/issues/27), [#28](https://github.com/SergeyGer/Docentric-Copilot/issues/28), [Reference Templates](../REFERENCE_TEMPLATES.md), [ADR-0011](0011-reference-graph.md), [ADR-0012](0012-reference-diff-and-evaluation.md) |

> **Numbering note.** The v0.11 P1 brief asked for ADR-0015 for this decision. ADR-0015 had already
> been accepted for independent label adjudication in the same v0.11 cycle (#31), and this project
> treats accepted ADRs as immutable. The decision is therefore recorded as ADR-0016 rather than
> reusing a number or rewriting an accepted record.

## Context

The v0.10 reference inspector produces read-only evidence: an inspection report, a ReferenceGraph, a
separate non-compilable Reference IR and a structural/semantic diff. The v0.11 P1 scope asks for
three things the read-only model cannot yet do:

1. Use the D365 embedded schema as graph evidence with the same provenance rules as a standalone
   DDSP, including the exact binding status, so a D365 document is not a second-class graph citizen.
2. Import a small, explicitly supported subset of a reference template into the existing Generic
   Template IR. The goal is not to write a Docentric template; it is to make reference evidence
   useful for generic document generation without silently guessing.
3. Add a visual comparison dimension that is independent of structure and semantics, without
   pretending that LibreOffice rendering is Word layering or a Docentric AX runtime check.

Constraints that shaped the decision:

- No Docentric corpus content or commercial template text may be committed.
- Reference inspection is read-only; any import is opt-in and must not mutate the reference model.
- Template IR v1.0 is frozen. Adding fields to every IR node changes every existing IR digest and
  golden file, so provenance cannot be added to the IR contract in this increment.
- The AX gate stays fail-closed and `runtime_compatibility` stays `not_tested`.
- The repository already has a LibreOffice path (`scripts/docx_to_pdf.py`) and a visual regression
  engine; duplicating a renderer would create two unlabelled fidelity claims.

## Decision

### Safe Reference → Generic Template IR (#27)

- Add an opt-in `project_to_template_ir(reference_document_or_graph, *, allow_unsupported=False)`
  in `reference/import_ir.py`. It copies only fully resolved, schema-evidence-backed constructs:
  Field → `FieldBinding`, Label → `TextRun`, List → `Repeat`, If → `Conditional`, Image →
  `ImageBinding`.
- Treat every other construct as a first-class skip with a stable code, location and reason:
  unknown/unsupported kinds, ambiguous/unknown/type-mismatch/schema-unavailable/unsupported
  bindings, missing paths, unsupported condition types, empty collections and label/image
  semantics that cannot be verified. `skipped[]` is always returned.
- Strict mode is the default: any skip raises `reference_import_blocked` before returning an IR.
  `allow_unsupported=True` keeps the supported subset and returns all skips; it never guesses.
- Import into a new object; `ReferenceDocument` remains immutable. Every imported node keeps its
  source reference id, element id, part/ordinal, raw/canonical path, provider source id and
  `part#xpath` evidence in a **sidecar keyed by IR path**, not inside the frozen IR model.
- Validate the produced Document with the existing deterministic validator (V1-V3) against a
  synthetic schema built only from the imported paths. A validation failure raises
  `reference_import_invalid`; no invalid IR is returned.
- Never set `target=docentric-ax`; the only target is `generic-docx`, and the result carries
  `runtime_compatibility: not_tested`.

### Unified D365 graph evidence (#26)

- Let `build_reference_graph` accept D365 binding reports explicitly or extract the embedded schema
  read-only from the original DOCX payloads.
- Represent D365 schema fields as `schema_field` nodes with `schema_source = d365_project_data`,
  `source_id` and `evidence_location = part#xpath`.
- Put the resolver status on `resolves_to` edges: `resolved | ambiguous | unknown_path |
  type_mismatch | schema_unavailable | unsupported_expression`. Only `resolved` gets a resolved
  edge; `schema_unavailable` is never rewritten as `unknown_path` or `type_mismatch`.
- Report evidence coverage and unresolved statuses in the graph summary, and show the origin in the
  Inspector. Keep the graph deterministic (sorted nodes/edges, bounded details, stable digest).

### Independent visual diff (#28)

- Add a separate `visual_diff.py` and `scripts/reference_visual_diff.py` that render both references
  through the existing `scripts/docx_to_pdf.py` LibreOffice path and compare page counts, blank
  pages, per-page ink/coverage and shifted regions.
- Label every report **LibreOffice rendering (not Word fidelity)**. Keep structural and semantic
  statuses independent (`not_compared` in the visual report rather than reusing another dimension's
  result).
- On missing `soffice`/`pdftoppm` or a render failure, return `renderer_unavailable` with a reason.
  It is never `passed` or `failed`; no comparison is fabricated.
- Write `report.json` and a self-contained, escaped `report.html` with artifact paths.

### Persistence scope (#29)

- Persist the serialized inspection/graph/diff envelope in the existing local SQLite store under the
  artifact TTL; never persist source template bytes.
- Keep the browser change minimal: save the last id in `?id=`, reopen via the API, tolerate absent
  or invalid ids, and expose an explicit export action. A full Playwright workflow is out of scope
  for this ADR.

## Consequences

Positive:

- Reference evidence can now drive generic document generation without turning an unknown
  construct into a plausible but wrong DOCX. A strict failure is explicit and reviewable.
- D365 and AX 2012 DDSP documents share one graph API and one provenance contract.
- Visual differences are reproducible page-level evidence, separate from structural/semantic
  changes, and a missing renderer cannot masquerade as a pass.
- Reports can be reopened and exported with a stable id, making review and support repeatable.

Negative / costs:

- The importer supports only a subset. List→Table inference, Group, SubDocument, Barcode,
  SummaryField, complex expressions and dynamic Docentric labels remain reference-only.
- Provenance lives in a sidecar keyed by an IR path. Consumers must join it; the IR itself does not
  carry it. A future IR major version may absorb it.
- Visual diffing depends on an optional renderer/poppler and fixed fonts. CI cannot run the real
  renderer, so the committed tests use a stub and the `renderer_unavailable` path.
- Persistence is single-process SQLite with a TTL; it is not a durable multi-user report store and
  has no committed browser E2E.
- The `renderer_unavailable` status adds a third outcome that consumers must handle; it deliberately
  cannot be collapsed into pass/fail.

## Alternatives considered

- **Import everything and let the compiler fail later.** Rejected: it can silently produce a wrong
  generic DOCX, which the brief explicitly forbids.
- **Add provenance fields to Template IR v1.0.** Rejected: it changes every IR digest and golden
  file for all existing plans; a sidecar keeps the contract stable.
- **Reuse the structural diff as the visual status.** Rejected: structure and rendered pages are
  different evidence; collapsing them would make both less trustworthy.
- **Treat a missing renderer as a skipped/passed check.** Rejected: absence of evidence is not
  evidence of identity; `renderer_unavailable` must remain distinct.
- **Build a second renderer dedicated to the reference inspector.** Rejected: the existing
  LibreOffice script already owns the fidelity label and the optional image path.

## Follow-up

- Run the 11-document D365 corpus through the unified graph and publish counts (not content) under
  `.tools/`; keep the synthetic tests as the public gate.
- Add a Table mapping when a reference table's columns and collection scope can be established from
  evidence; add a clear skip reason until then.
- Decide whether a future IR major version should carry provenance natively.
- Add a CI-capable renderer image or a recorded renderer fixture for the visual path.
- Commit a Playwright happy-path/negative workflow for persistence/reopen/export.
