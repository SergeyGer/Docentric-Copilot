# Product Requirements Document (PRD)

| Field | Value |
| --- | --- |
| Product | Docentric Copilot |
| Version | 0.2.0 (MVP) |
| Status | Living document; reflects the implementation in this repository |
| Audience | Product, engineering, QA, security review |
| Related | [SRS](SRS.md), [ARCHITECTURE](ARCHITECTURE.md), [ROADMAP](ROADMAP.md) |

This document describes *why* the product exists and *what* the MVP must do. It deliberately contains
no unmeasured benchmark numbers; where a metric is unknown it is marked `TBD` with the measurement
method.

## 1. Problem

Enterprise document automation usually separates two worlds:

- a **typed data contract** — here a DDSP data source package containing XML schema declarations
  and/or sample data — that defines which fields a document may print;
- a **document template** — a Word-style artefact, often maintained in a graphical designer, that
  binds presentation to those fields.

The boundary between the two worlds is maintained by hand. This produces three recurring failures:

### P1 — Silent binding drift

A template references `MainData.Quotation.Customer.Name`. Months later the data package renames or
removes that node. Nothing fails at authoring time; the document either renders an empty area or
fails at run time in production. There is no machine-checkable link between "this template claims to
use field X" and "field X exists with a compatible type".

### P2 — Templates are opaque artefacts

A template is a binary document. Reviewers cannot diff two versions meaningfully, cannot assert
"every binding resolves", and cannot regression-test rendering. Changes are reviewed by opening
documents and eyeballing them, which does not scale and is not reproducible.

### P3 — Generative AI is plausible, not correct

A language model can produce a document that *looks* like a quotation while binding fields that were
never in the schema, inventing totals, or placing a collection value in a scalar context. A document
that opens without an error is not evidence of correctness. Without a typed intermediate
representation and deterministic checks, model output cannot be trusted, repaired transparently, or
audited.

A fourth, product-level problem frames the whole project:

### P4 — Compatibility claims are cheap and dangerous

It is easy to say "this generates Docentric AX templates". It is hard to prove. A false compatibility
claim causes customer-facing failures that are expensive to diagnose. The product therefore treats
compatibility as an evidence-gated status, not a marketing attribute (see
[DOCENTRIC_AX_COMPATIBILITY.md](DOCENTRIC_AX_COMPATIBILITY.md)).

## 2. Goals

1. Convert a natural-language requirement plus a DDSP package into a **typed, versioned Template IR**
   whose every dynamic value is a resolvable schema path.
2. **Validate** the IR deterministically at structural, semantic, logical and visual levels, and
   report compatibility separately as `not_tested`.
3. **Compile** a validated IR into a generic DOCX package with byte-identical output for identical
   input.
4. Make every automated decision **reviewable**: mapping candidates, removed bindings, validation
   findings and revision diffs are data, not log lines.
5. Provide one domain core behind both an HTTP API and a CLI, with stable error codes and exit codes.
6. Never claim Docentric AX compatibility without evidence gathered in a licensed environment.

## 3. Non-goals (MVP)

- Producing Docentric AX-tagged templates, or claiming such output works. The adapter is gated and
  fails closed.
- Acting as a word processor or a pixel-faithful renderer. The HTML preview is a content preview.
- Replacing Docentric Designer or any licensed third-party tool.
- Multi-tenant SaaS concerns: authentication, authorisation, per-tenant isolation, quotas.
- Real-time collaboration, comments, approval workflows.
- Training or fine-tuning models.
- Supporting arbitrary OOXML features (charts, SmartArt, fields, macros, embedded objects).
- Locale-complete formatting; the MVP formats English-style numbers and dates.

## 4. Personas

### PER-1 — Integration developer ("Maya")

Builds the document pipeline for an ERP integration. Wants a programmatic way to turn a data contract
into a document, with JSON artefacts she can store, diff and test in CI. Pains: opaque binaries,
schema drift, no automated verification. Success: a template she can regenerate and assert on.

### PER-2 — Functional consultant ("Tomas")

Knows the business document and the fields, but is not a developer. Wants to describe a document in
natural language and review what the system bound. Pains: designer learning curve, ambiguity about
which field was used. Success: a mapping report he can read and correct in minutes.

### PER-3 — Template maintainer ("Ingrid")

Owns dozens of templates. Wants versioning, a diff between versions, and a report that says which
requirements are unresolved. Pains: regressions discovered by customers. Success: every change has a
machine-readable diff and a validation report.

### PER-4 — Security / platform reviewer ("Sam")

Must approve running the service on untrusted customer data. Wants bounded parsing, no XXE, no
network access from the XML parser, no secrets in logs, TTL on artifacts, and explicit residual risk.
Success: threat model maps every claim to code.

### PER-5 — AI engineer ("Priya")

Wants to compare a deterministic baseline with LLM planners on the same fixtures, and to know the
cost per valid template. Pains: no reproducible evaluation. Success: a harness with defined metrics
and a results table that can be reproduced.

## 5. User journey

```text
 upload DDSP ──▶ inspect schema ──▶ write requirement ──▶ plan (IR + mapping)
      │                │                                        │
      │                └─ diagnostics, sections, sample data    ▼
      │                                              validate V1–V3 (+V4 with sample)
      │                                                         │
      │                        ┌────────────────────────────────┴─────────────┐
      │                        ▼                                              ▼
      │                 failures: fix requirement/IR             pass: compile generic DOCX
      │                        │                                              │
      │                        └──────── revise (new version) ◀───────────────┘
      │                                                                       │
      └──────────────── artifacts (IR, mapping, validation JSON/HTML, preview, DOCX) with TTL
```

The journey is available through the web workspace as well as the API/CLI. The workspace keeps schema
inspection, prompt editing, mapping/validation review, the sandboxed HTML preview, compilation,
downloads and version history on one page; it calls exactly the endpoints below.

1. **Upload** a DDSP package (`POST /api/v1/sources`, the web upload panel, or
   `docentric-copilot inspect`). The system parses untrusted bytes, records diagnostics and stores the
   normalized schema.
2. **Inspect** sections, field paths, collections, types and sample availability. This is the moment
   the user learns whether the package is usable at all.
3. **Describe** the document in natural language (a prompt). The requirement is split into clauses
   for the mapping report.
4. **Plan.** A provider (deterministic `mock` baseline or an LLM) proposes a document. The planner
   validates it against the IR model, removes unresolvable bindings, and produces a mapping report
   with `resolved / ambiguous / missing / invalid` statuses.
5. **Review.** The validation report shows V1–V4 statuses plus V5 `not_tested`. Ambiguous mappings
   are surfaced as requiring a human decision — the system does not silently pick.
6. **Compile** a generic DOCX. Compilation is refused unless V1–V3 pass. The API also validates the
   produced package (required entries, no macros, no embedded objects).
7. **Revise or export.** A revision produces a new IR version plus a structural diff. The IR can be
   exported as canonical JSON and stored in source control.

Failure paths that the journey must make explicit:

- Unsupported container or no XML content → diagnostics and a typed error, never a partial schema.
- Validation failure → the plan/compile request fails with a report body (HTTP 422), not a silent
  empty document.
- Unsupported target (`docentric-ax`) → HTTP 409 / exit code 4, with the gate reason.
- Expired artifact → HTTP 410, not a stale file.

## 6. Product principles

### PP-1 — Correctness over plausibility

A missing field is acceptable; a wrong binding is not. The planner removes what it cannot prove and
reports it. Search candidates are evidence, not answers. The tool would rather ask for clarification
(`ambiguous`) than guess.

### PP-2 — Determinism in the deterministic layer

Parsing, validation and compilation must not depend on wall-clock time, randomness, network access or
dictionary iteration order. Model calls happen only in the planning step, and their output is treated
as an untrusted proposal.

### PP-3 — Fail closed, fail typed

Every expected failure has a stable code, an HTTP status and an exit code. The compatibility gate
raises instead of emitting a document that merely looks compatible.

### PP-4 — Evidence over assumption

The DDSP format is not publicly specified. The parser records what it observed (`manifest.json`,
XSD constructs, sample structure) and never invents a layout. Unsupported XSD types degrade with a
diagnostic rather than a silent guess.

### PP-5 — `not_tested` is a status, not a synonym for "passed"

Validation reports keep five levels separate. Aggregation never converts an untested level into a
pass. The overall verdict is `passed_unverified_compatibility` while V5 is untested.

### PP-6 — No invented business values

The compiler only formats what the sample data contains. If sample data is absent, it renders explicit
placeholders such as `[[MainData.Quotation.QuotationId]]` rather than fabricated content. It never
computes totals or tax.

### PP-7 — Reviewability

Mapping reports, removed bindings, revision diffs and validation findings are first-class JSON
objects returned by the API and written by the CLI.

## 7. MVP scope

### In scope

| Area | MVP behaviour |
| --- | --- |
| Input | ZIP-based DDSP packages and single XML documents; `.ddsp`, `.xml`, `.xsd`, `.zip` uploads |
| Limits | Configurable size/entry/ratio/node/depth limits with typed diagnostics |
| Schema | XSD mapping for a documented subset; inference from sample data when no XSD exists |
| Sample data | Extraction and type coercion against the discovered schema |
| Planning | Deterministic baseline (`mock`) and three HTTP providers with structured output |
| IR | Template IR v1.0 with canonical JSON, digest and JSON Schema export |
| Validation | V1 structural, V2 semantic, V3 logical, V4 table-width visual check, V5 `not_tested` |
| Compilation | `generic-docx` only; deterministic OOXML package |
| Preview | Self-contained HTML content preview |
| Interfaces | FastAPI HTTP API, Typer CLI, Next.js 15 web workspace (`apps/web`), SQLite persistence, TTL artifacts |
| Docs | This document set, including explicit non-claims |

### Out of scope

- Docentric AX output and any compatibility assertion.
- PDF/UA, accessibility certification, print fidelity.
- Word rendering verification (opening the DOCX in Word is not part of the pipeline or test suite).
- Authentication, authorisation, rate limiting, tenancy, audit trail for users.
- Cloud storage, queues, horizontal scaling.
- Image optimisation, font embedding, locale-specific number/date formatting.
- Merging or editing an existing DOCX; revisions only regenerate the IR.

## 8. Success metrics

The MVP evaluation must be based on measurable outcomes. The table defines the metric, the method and
the current state. Measured values, their provenance and their limitations are recorded in
[EVALUATION.md](EVALUATION.md) and [BENCHMARKS.md](BENCHMARKS.md).

| ID | Metric | Definition | Method | Current |
| --- | --- | --- | --- | --- |
| M-01 | Time to first valid generic DOCX | Minutes from a fresh clone to a compiled quotation using the documented quick start | Manual timed run | TBD |
| M-02 | Fixture compilation success rate | Successful `generic-docx` compilations / attempted example packages | Evaluation harness over `examples/` | 3/3 (mock, `059b1bb`) |
| M-03 | Field selection precision | Correctly selected bindings / all selected bindings, against a hand-labelled expected mapping per fixture | `docentric_copilot.evaluation` + `benchmarks/run_evaluation.py` | 1.000 (mock, 3 fixtures) |
| M-04 | Field selection recall | Correctly selected bindings / all expected bindings | same | 0.772 (mock; see the harness limitation in EVALUATION) |
| M-05 | Requirement coverage | Requirement clauses with status `resolved` / all clauses | Mapping report counts | 1.000 (mock) |
| M-06 | Clarification rate | Clauses reported `ambiguous` / all clauses | Mapping report counts | 0.000 (mock) |
| M-07 | Correction rate | Plans with a removed binding or an invalid mapping / plans | `removed_bindings` + mapping counts | 0.000 (mock) |
| M-08 | Cost per valid template | Provider spend / templates that pass V1–V3 and compile | Provider usage telemetry + compile status | $0.000 (mock); hosted providers TBD |
| M-09 | Compatibility rate | Templates proven compatible in a licensed Docentric environment / attempted | Requires the gate in [DOCENTRIC_AX_COMPATIBILITY.md](DOCENTRIC_AX_COMPATIBILITY.md) | 0 (gate not passed; status blocked) |
| M-10 | Validation false-negative rate | Defects found downstream that V1–V3 did not flag / templates compiled | Defect tracking, requires production use | TBD (not measurable in MVP) |

Metric definitions and formulas are normative in [EVALUATION.md](EVALUATION.md); this table only
fixes intent. The mock baseline values are measured over three synthetic fixtures and are not an LLM
comparison; hosted-provider rows remain `TBD`.

## 9. Constraints and dependencies

- **C-1** The DDSP format is not publicly specified. The parser is evidence-based; real-world DDSP
  coverage is unknown until representative packages can be tested.
- **C-2** Docentric AX compatibility cannot be established without a licensed environment and
  authoritative documentation. The MVP therefore ships a generic compiler only.
- **C-3** No Microsoft Word or Dynamics 365 environment is required or used by the pipeline; this also
  means Word rendering fidelity is untested.
- **C-4** LLM calls require provider credentials and network access. The `mock` provider must always
  work without either.
- **C-5** The service is a single process with a SQLite database and a local artifact directory; this
  bounds deployment expectations for the MVP.

## 10. Product risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Real DDSP packages differ from the synthetic layout | Parser produces diagnostics or an incomplete schema | Evidence-based parsing, explicit `SCHEMA_INFERRED`, fixtures tracked in [DDSP_COMPATIBILITY.md](DDSP_COMPATIBILITY.md) |
| A model claims fields that do not exist | Broken documents | Deterministic sanitisation + V2 validation; unmapped requirements surfaced |
| Users read "generic DOCX" as "Docentric-ready" | Wrong expectations, customer impact | Explicit non-claims in README, API description, validation report and DOCX core properties |
| LLM cost or latency is unacceptable | Adoption failure | Budget pre-flight, cost telemetry, deterministic baseline for comparison; numbers TBD in [BENCHMARKS.md](BENCHMARKS.md) |
| Preview mistaken for Word layout | Review misses layout defects | Preview labels itself "layout differs from Word/Docentric pagination"; V4 is explicitly partial |
| Single-process storage loses data | Lost artifacts/versions | TTL is explicit; persistence is documented as local MVP scope |

## 11. MVP acceptance criteria

The MVP is accepted when all of the following are demonstrably true:

1. A fresh environment can install the package and compile the quotation example to a DOCX using only
   the commands in the README, with no API key.
2. The same IR and sample data compile to byte-identical output across repeated runs and across CLI
   and HTTP paths.
3. Every dynamic value in a compiled IR resolves against the source schema; unresolvable values are
   removed and reported.
4. `generic-docx` is the only available target; `docentric-ax` raises a typed error (HTTP 409, exit 4).
5. The validation report contains all five levels, with V5 always `not_tested` and an overall verdict
   that does not imply compatibility.
6. Hostile inputs (DOCTYPE, oversized archive, unsafe entry names, nested archives, encrypted entries)
   are rejected with typed errors and no partial output.
7. The documented tests run and the documented commands are reproducible; known gaps are listed in
   [TEST_PLAN.md](TEST_PLAN.md).
