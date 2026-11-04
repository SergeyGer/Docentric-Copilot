# ADR-0010 — Read-only reference inspector before any Docentric AX writer

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-04 |
| Deciders | Project maintainers |
| Related | [Reference Templates](../REFERENCE_TEMPLATES.md), [ADR-0005](0005-docentric-compatibility-gate.md), [ADR-0009](0009-ax-adapter-gate.md) |

## Context

The v0.5 engine can generate a validated generic DOCX, but it cannot inspect the official
Docentric reference templates that define the real target format. Before writing an AX compiler,
the project needs reproducible evidence about what those packages contain: archive structure,
duplicates, OOXML content controls, ProjectData metadata and binding paths.

The supplied examples are valuable but also impose constraints:

- the archive is vendor material and cannot be redistributed in this public repository;
- a static id join is not semantic validation and says nothing about Docentric runtime behaviour;
- macro, OLE, external-relationship and XPath content is untrusted;
- a public upload endpoint must not become a recursive archive browser or an arbitrary filesystem
  reader.

The v0.6 specification therefore puts REF-00 (inventory/dedup) and REF-02 (metadata resolver)
before REF-03 (ReferenceGraph and safe projection), REF-04 (comparison) and native AX output.

## Decision

Add one read-only bounded context, `docentric_copilot.reference`, implemented in
`packages/reference-inspector/`, with four responsibilities:

1. **REF-00 inventory** (`inventory.py`) — hash every artifact, normalize AXPP virtual names,
   detect exact duplicates, expand nested archives only to an explicit depth and never execute or
   write members.
2. **OOXML scanner** (`docx_controls.py`) — return every `w:sdt` across document/header/footer and
   other supported story parts with location and marker evidence classified as
   `recognized`/`ambiguous`/`unknown`.
3. **REF-02 resolver** (`metadata.py`) — find ProjectData by namespace in any `customXml/itemN.xml`,
   canonicalize signed SDT ids to unsigned Element ids, resolve optional storeItemIDs and validate
   ValueBinding paths against a supplied bare DDSP. Unresolved controls are preserved with
   `missing_part`, `unknown_path` or `ambiguous`, not dropped.
4. **Stable report** (`report.py`) — deterministic JSON with counts, duplicate provenance, coverage
   denominators, diagnostics and `runtime_compatibility: "not_tested"`.

The decision includes these boundaries:

- A public CLI command `docentric-copilot reference inspect` and an HTTP endpoint
  `POST /api/v1/reference/inspect`.
- HTTP uploads default to `max_depth=0`; path input is confined to configured corpus roots and
  checked after symlink resolution.
- Newly required dependencies are limited to the already-pinned `lxml` and `pydantic`; no new
  runtime services or binaries.
- Tests use only synthetic fixtures generated in `tests/reference_fixtures.py`; the official
  archive lives exclusively in the git-ignored `.tools/reference-corpus/`.
- The Docentric AX gate is untouched: `target=docentric-ax` still fails closed, V5 stays
  `not_tested`, and no native writer is introduced.

## Consequences

Positive:

- Reference material can now be inspected reproducibly with hashes and provenance while staying
  outside the repository.
- Unknown and ambiguous controls remain explicit; coverage has honest, documented denominators.
- The resolver establishes an evidence layer for future ReferenceGraph and comparison work without
  weakening Template IR 1.0.
- Security review is localized: no execution, bounded XML/ZIP reading, corpus-root confinement and
  macro/active-content flags.

Negative and open:

- The resolver's id join is technical evidence only; it does not validate expression semantics,
  localization or runtime rendering.
- A bare DDSP path adapter is not implemented; path validation only covers the subset extracted
  from a supplied DDSP. Embedded ProjectData schemas are deliberately not treated as a full REF-01
  schema.
- The local corpus baseline (672 controls, 650 id joins, 22 unresolved) is a snapshot of one
  archive, not a global guarantee. File names and sample values from that archive are not part of
  the repository.
- The report can contain template text previews and metadata; operators must keep real-corpus
  reports private.
- Recursive AXPP/ZIP inspection remains offline-only and depth-capped; the HTTP surface is not a
  general archive explorer.

## Alternatives considered

- **Implement a native Docentric AX writer first.** Rejected: no licensed runtime verification and
  no lawful format evidence; would violate the existing fail-closed gate.
- **Commit the official corpus as fixtures.** Rejected: licensing does not permit redistribution;
  tests must remain synthetic.
- **Only parse `w:alias` or `w:tag`.** Rejected by the specification: aliases are generic and tags
  are not unique keys; the id join plus ProjectData is required.
- **Drop unresolved controls from the report.** Rejected: it would hide exactly the cases the
  inspector is meant to investigate.
- **Open a recursive archive endpoint with no corpus confinement.** Rejected: unnecessary attack
  surface for a public deployment.

## Follow-up

- REF-01: implement a real DDSP adapter and embedded ProjectData schema evidence.
- REF-03: define ReferenceGraph v1 and an inspect-only projection before any import mode.
- REF-04: compare variants and versions using the provenance produced here.
- REF-07: obtain a licensing decision and a licensed Docentric runtime before any AX writer or
  runtime claim. Until then the gate and `not_tested` status remain unchanged.
