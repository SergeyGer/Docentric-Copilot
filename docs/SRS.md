# Software Requirements Specification (SRS)

| Field | Value |
| --- | --- |
| Product | Docentric Copilot |
| Version | 0.2.1 |
| IR version | 1.0 |
| Status | Living document; claims map to the implementation in this repository |
| Audience | Engineering, QA, security review, integration partners |

This SRS is a catalogue of **implemented or explicitly gated** requirements. It contains no
aspirational features presented as done. Every requirement has a status, a verification method and
links to the code (and tests, where they exist).

## 1. Scope and conventions

### 1.1 In scope

The requirements below cover the Python core (DDSP ingestion, schema discovery, semantic field
mapping, AI planning, the Template IR, validation, generic DOCX compilation, preview, revisions, the
HTTP API, the CLI and local persistence) and the Next.js frontend that consumes the HTTP API. The
frontend is a client of FR-09; it introduces no additional backend fidelity claims.

### 1.2 Out of scope

Docentric AX output, Word rendering verification, authentication, multi-tenancy, horizontal scaling,
PDF export, pixel-faithful browser rendering of the document preview. See
[PRD §3](PRD.md#3-non-goals-mvp).

### 1.3 Status vocabulary

| Status | Meaning |
| --- | --- |
| **Implemented** | Behaviour exists in code and can be exercised by the documented interface. |
| **Partially implemented** | A defined subset works; missing parts are listed under *Gaps*. |
| **Not verified** | Code exists but the claim has not been demonstrated in this repository (for example live provider calls). |
| **Not implemented** | No behaviour exists. Never described as working. |
| **Blocked** | Deliberately unsupported until an external gate is passed (Docentric AX compatibility). |

`not_tested` is also a **runtime status** in validation reports (V5). It is not a synonym for
`passed`, and no aggregation in this codebase promotes it to one.

## 2. Functional requirements

### FR-01 — Safe DDSP ingestion and schema discovery

**Statement.** The system shall accept an untrusted DDSP package (ZIP container) or a single XML
document, enforce configurable resource limits, and produce a deterministic normalized schema with
diagnostics, without ever guessing a field that the evidence does not support.

**Acceptance criteria.**

1. ZIP magic (`PK\x03\x04`, `PK\x05\x06`, `PK\x07\x08`) and leading `<` classify the container as
   `zip`, `xml` or `unknown`; `unknown` is rejected with `DDSP002`.
2. File size below 16 bytes is rejected (`DDSP011`); above `max_ddsp_bytes` is rejected (`DDSP001`).
3. ZIP archives with more than `max_zip_entries` entries are rejected (`DDSP003`); declared
   uncompressed size above `max_uncompressed_bytes` is rejected (`DDSP004`); per-entry compression
   ratio above `max_compression_ratio` is rejected (`DDSP005`).
4. Entry names that are absolute, contain `..`, backslashes or control characters are rejected
   (`DDSP007`); encrypted entries (`DDSP006`) and nested archives (`DDSP009`) are rejected.
5. XML containing a `DOCTYPE` or `ENTITY` declaration is rejected (`XML001`); the parser has
   `resolve_entities=False`, `no_network=True`, `load_dtd=False`, `recover=False`.
6. Documents deeper than `max_xml_depth` (`XML004`) or with more than `max_xml_nodes` nodes
   (`XML003`) are rejected.
7. A manifest named `manifest.json`, `ddsp.json` or `metadata.json` (≤ 64 KiB, JSON object) is read;
   only `format`, `format_version`, `version`, `name`, `sections`, `locales` are retained. A malformed
   manifest is ignored with `DDSP002` and does not fail the package.
8. An XSD document is converted to sections. Element paths follow `Section.Element.Child`; a node with
   `maxOccurs` missing/`1` is scalar, `unbounded`/`>1` is a collection; `minOccurs > 0` is `required`;
   attributes become `SchemaAttribute` entries; named `complexType`, inline `complexType`,
   `complexContent/extension`, `attributeGroup` and named `simpleType` restrictions are resolved.
9. Unknown XSD builtin types fall back to `string` with `SCHEMA002`; recursion is not expanded and is
   reported (`SCHEMA004`); the schema node budget is enforced (`SCHEMA005`).
10. When no XSD is present, the schema is inferred from the first data document and an explicit
    `SCHEMA006` INFO diagnostic is emitted. Inferred schemas are never presented as declared.
11. When an XSD defines sections, a sample data document is mapped onto them and values are coerced by
    type (`number`, `boolean`, `date`); mismatches are reported as `SAMPLE002` and the text is kept.
12. An empty container or a container with no XML documents is rejected (`DDSP008`). If all XML
    documents fail to parse, the first parse error is re-raised with its original code (`XML002`).
13. Parsing is deterministic: identical bytes produce identical canonical schema JSON and digest.

**Status: Partially implemented.**

**Evidence.**

- `packages/ddsp-parser/src/docentric_copilot/ddsp_parser/safety.py` (container + XML reading)
- `packages/ddsp-parser/src/docentric_copilot/ddsp_parser/parser.py` (orchestration, manifest)
- `packages/ddsp-parser/src/docentric_copilot/ddsp_parser/xsd.py` (XSD mapping)
- `packages/ddsp-parser/src/docentric_copilot/ddsp_parser/sampledata.py` (extraction and inference)
- `packages/ddsp-parser/src/docentric_copilot/ddsp_parser/models.py` (normalized schema)
- `packages/ddsp-parser/src/docentric_copilot/ddsp_parser/diagnostics.py` (stable codes)
- Tests: `tests/unit/test_ddsp_parser.py`

**Gaps.** The DDSP format is not publicly specified; only synthetic packages under `examples/` have
been exercised. XSD support is the documented subset (no substitution groups, wildcards, keys,
notations, identity constraints or multiple schema documents). Multiple XSDs: the first usable one
wins. Locales are recorded but not used for formatting. See
[DDSP_COMPATIBILITY.md](DDSP_COMPATIBILITY.md).

---

### FR-02 — Schema path resolution and semantic field mapping

**Statement.** The system shall resolve every dynamic reference to an absolute schema path, reject
references that are not scalar/collection-compatible in their context, and produce a reviewable
mapping from requirement clauses to candidate fields.

**Acceptance criteria.**

1. Paths match `^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$` and are resolved against the
   normalized schema; unknown paths fail with `path_not_found`.
2. A collection or complex object used as a scalar fails with `type_mismatch`; a scalar iterated as a
   collection fails with `type_mismatch`.
3. A scalar whose ancestor is a collection may only be bound when an enclosing repeat alias maps to
   that collection; otherwise resolution fails with `context_violation`.
4. Alias resolution is lexical: the nearest enclosing repeat/table-repeat alias wins, and aliases are
   expanded to absolute collection paths.
5. Candidate search is deterministic and explainable: tokenisation with stop-words and plural
   folding, one-level synonym expansion, field-name matches weighted above ancestor matches, type
   bonuses applied only after a textual match, depth penalty, score normalised to `0..1` and sorted
   by `(-score, depth, path)`.
6. A candidate list maps to `resolved` only when the top score is ≥ 0.35 **and** beats the runner-up
   by `max(0.03, 0.15 × top_score)`; otherwise `ambiguous`; scores below 0.35 are `missing`.
7. `FieldMapping` validation downgrades to `invalid` when the selected path does not exist or its type
   is incompatible with the declared requirement type. `confidence_score` is recorded but is never
   treated as evidence.
8. A mapping report for a plan is derived from the produced IR and the requirement: a clause bound by
   the plan is `resolved`; a clause satisfied by the document title is `resolved`; a well-matching
   field the plan does not use is `missing`; equally good candidates are `ambiguous`; removed bindings
   are `invalid`.

**Status: Implemented.**

**Evidence.**

- `packages/schema-resolver/src/docentric_copilot/schema_resolver/paths.py`
- `packages/schema-resolver/src/docentric_copilot/schema_resolver/search.py`
- `packages/schema-resolver/src/docentric_copilot/schema_resolver/mapping.py`
- `packages/planner/src/docentric_copilot/planner/service.py` (`build_mapping_report`)
- Tests: `tests/unit/test_schema_and_ir.py`, `tests/unit/test_planner.py`

**Gaps.** The synonym table is a small, domain-specific hand-written list. Search is lexical, not
embedding-based; a vocabulary the table does not cover scores zero. Mapping quality is quantified
only for the mock baseline on synthetic fixtures (see [EVALUATION.md](EVALUATION.md)); no hosted-LLM
comparison has been recorded.

---

### FR-03 — Provider-independent planning with structured output

**Statement.** The system shall turn a requirement plus a normalized schema into a Template IR
proposal through a provider abstraction, validate the proposal against the IR model, and repair it
deterministically, never trusting model output as correct.

**Acceptance criteria.**

1. Providers `openai`, `anthropic`, `gemini` and `mock` implement one `generate_structured` contract
   returning a JSON object validated against a caller-supplied pydantic model.
2. The gateway resolves the model, applies timeout/retry/budget settings, normalises failures to
   `ProviderError` subclasses and rejects output that fails schema validation
   (`provider_invalid_output`).
3. JSON is extracted from bare objects, fenced blocks or prose-wrapped responses; extraction failure
   is a typed provider error.
4. OpenAI uses `response_format=json_schema` with a documented fallback to JSON mode; Anthropic uses
   a forced `tool_use` schema; Gemini uses `responseSchema` after conversion to the supported subset,
   with a documented fallback.
5. The mock provider is deterministic, requires no API key and never performs network I/O.
6. Prompts place the requirement and schema inside `<requirement>`/`<schema>` fences and the system
   prompt states that fenced content is data, not instructions.
7. The planner splits the requirement into at most 12 clauses, calls the provider, validates the IR,
   removes every reference that does not resolve, records removals, builds the mapping report, and
   refuses to continue if no usable section remains.
8. An empty requirement/instruction is rejected with `input_invalid`.
9. A schema-invalid provider response is retried up to `max_repair_attempts` (0–2 via API) with a
   repair message; other provider errors are not retried by the planner.
10. For non-mock providers the IR `metadata.generator` is set to `provider/model`.

**Status: Partially implemented.**

**Evidence.**

- `packages/llm-gateway/src/docentric_copilot/llm/gateway.py`
- `packages/llm-gateway/src/docentric_copilot/llm/providers.py`
- `packages/llm-gateway/src/docentric_copilot/llm/models.py`
- `packages/llm-gateway/src/docentric_copilot/llm/pricing.py`
- `packages/planner/src/docentric_copilot/planner/service.py`
- `packages/planner/src/docentric_copilot/planner/prompt.py`
- `packages/planner/src/docentric_copilot/planner/heuristic.py` (`BASELINE_VERSION`)
- Tests: `tests/unit/test_preview_and_llm.py`, `tests/unit/test_planner.py`

**Gaps.** Live calls against the three hosted providers are **not verified** in this repository; the
adapter tests use mocked HTTP transports. The cost estimate is a static table and is not an invoice;
unknown models are reported as unpriced, so budget pre-flight does not apply to them. Prompt-injection
resistance has a design mitigation but no measured evaluation.

---

### FR-04 — Versioned Template IR with canonical serialization

**Statement.** The system shall define a typed, versioned intermediate representation, reject unknown
keys and versions, and serialize it canonically so that digests, golden files and artifacts are
meaningful.

**Acceptance criteria.**

1. The IR is a pydantic model tree with `extra="forbid"`; unknown keys fail validation.
2. `ir_version` is `"1.0"`; a payload with an unsupported major/minor version fails with
   `ir_version_unsupported`; a migration registry exists and is empty for 1.0.
3. IR loading accepts JSON text, UTF-8 bytes or a mapping, and reports at most 25 validation errors
   with `location`, `message`, `type`.
4. Canonical JSON uses sorted keys, no insignificant whitespace and UTF-8; the digest is SHA-256 over
   that JSON. Identical documents produce identical canonical JSON and digests.
5. Every field carrying text, counts, nesting or expressions has a defensive bound (see
   [TEMPLATE_IR.md](TEMPLATE_IR.md)).
6. A JSON Schema (draft 2020-12) can be exported from the model; the CLI exposes it as
   `docentric-copilot ir-schema`.

**Status: Implemented.**

**Evidence.**

- `packages/template-ir/src/docentric_copilot/template_ir/models.py`
- `packages/template-ir/src/docentric_copilot/template_ir/canonical.py`
- `packages/template-ir/src/docentric_copilot/template_ir/traversal.py`
- `packages/core/src/docentric_copilot/serialization.py`
- `services/api/src/docentric_copilot/cli/main.py` (`ir-schema`)
- Tests: `tests/unit/test_schema_and_ir.py`

**Gaps.** Only one IR version exists; no migration has been exercised. The JSON Schema describes
per-field bounds but not every cross-field invariant enforced by model validators (for example table
row width or expression shape).

---

### FR-05 — Deterministic generic DOCX compilation

**Statement.** The system shall compile a validated IR into a standards-compliant OOXML package,
byte-identically for identical inputs, and shall refuse every target it cannot produce safely.

**Acceptance criteria.**

1. `generic-docx` is supported; any other target is rejected with `target_unsupported`
   (HTTP 409, CLI exit 4). `DocentricAXCompiler` always raises.
2. The compiler performs no network access, no model call, no clock read and no randomness.
3. ZIP entries are sorted, timestamps fixed to `2024-01-01T00:00:00`, permissions `0644`, deflate
   level 9; core properties (`created`, `modified`, `revision`, author, title, subject, comments,
   keywords, category, language) are fixed except for values derived from the IR.
4. Rendering supports paragraph, heading, image, repeat, conditional and table blocks; repeat and
   table-repeat expansion is bounded by `max_items` when set, otherwise by
   `CompileOptions.max_repeat_items` (default 200); both are capped at 1,000.
5. Bindings render sample values when available and explicit `[[path]]` placeholders otherwise; no
   business value is ever invented.
6. Images are accepted only as base64 or `data:` payloads with PNG/JPEG/GIF/BMP magic bytes and
   ≤ 5 MiB; undecodable images become placeholders with a warning.
7. The produced package is inspected for required entries, VBA macros, embedded OLE/ActiveX objects
   and external relationships; an invalid package raises `compilation_failed`.
8. Section headers/footers of secondary sections are not rendered (single Word section output) and a
   warning is recorded.
9. Compilation results expose target, filename, IR digest, `compatibility="not_tested"`, warnings,
   statistics and the package inspection summary.

**Status: Partially implemented** (generic target implemented; Docentric AX not implemented).

**Evidence.**

- `packages/docx-compiler/src/docentric_copilot/docx_compiler/generic.py`
- `packages/docx-compiler/src/docentric_copilot/docx_compiler/package.py`
- `packages/docx-compiler/src/docentric_copilot/docx_compiler/registry.py`
- `packages/docx-compiler/src/docentric_copilot/docx_compiler/context.py`
- `packages/docx-compiler/src/docentric_copilot/docx_compiler/expression.py`
- `packages/docx-compiler/src/docentric_copilot/docx_compiler/formatting.py`
- Tests: `tests/unit/test_validator_and_compiler.py`, `tests/golden_files/`

**Gaps.** The DOCX is not opened in Microsoft Word by any test, so rendering fidelity is unverified.
Headers/footers on secondary sections, footnotes, comments, tracked changes, fields and charts are not
supported. The visual result depends on the fonts available to the consumer.

---

### FR-06 — Independent HTML preview

**Statement.** The system shall render a self-contained HTML preview of the IR against sample data to
support content review, without claiming layout fidelity.

**Acceptance criteria.**

1. The preview renders header, body, footer, tables, repeats, conditionals and images with the same
   formatting and expression semantics as the compiler.
2. User text is HTML-escaped; images are inlined only as validated `data:` URIs; no external resource
   is referenced.
3. Without sample data, bindings render as visible placeholders.
4. The output labels itself as an independent preview whose layout differs from Word/Docentric
   pagination.
5. The API returns the preview as `text/html` with `X-Content-Type-Options: nosniff` and a
   restrictive Content-Security-Policy.

**Status: Implemented**, with an explicit fidelity limitation.

**Evidence.**

- `packages/renderer/src/docentric_copilot/preview/renderer.py`
- `services/api/src/docentric_copilot/api/routes/templates.py` (`POST /templates/preview`)
- Tests: `tests/unit/test_preview_and_llm.py`

**Gaps.** Pagination, page breaks within tables, font metrics, hyphenation and Word-specific layout are
out of scope. "Preview looks right" is not evidence that the DOCX renders the same way.

---

### FR-07 — Five-level validation

**Statement.** The system shall validate an IR at five separate levels, report each check with a
stable code and status, and block compilation unless V1–V3 pass.

**Acceptance criteria.**

1. V1 structural: block count ≤ `max_ir_blocks`, nesting depth ≤ `max_ir_depth`, unique section names,
   non-empty section bodies, text run length ≤ `max_text_length`; when a package is supplied, required
   OOXML entries, macros, embedded objects and external relationships are checked.
2. V2 semantic: every field/image binding resolves to an existing scalar path in the correct repeat
   context; numeric/date/boolean formats match the field data type.
3. V3 logical: repeat targets are collections; repeat aliases are unique per scope; condition fields
   exist; comparison operands are type-correct for ordering, `contains`, and boolean comparisons.
4. V4 visual: with sample data, table column widths that exceed the printable page width produce a
   warning; without sample data the level is `skipped`, never `passed`.
5. V5 compatibility: always emits one check with status `not_tested` and an explanation that a licensed
   environment is required.
6. Statuses are `passed`, `failed`, `warning`, `skipped`, `not_tested`; `ValidationReport.statuses()`
   returns exactly `structural`, `semantic`, `logical`, `visual`, `docentric_compatibility`.
7. `can_compile` is true only when V1, V2 and V3 aggregate to `passed` or `warning`.
8. `overall` is `failed` when not compilable and `passed_unverified_compatibility` while V5 is
   `not_tested`; this build cannot emit `passed`.
9. The report can be rendered as JSON and as a self-contained HTML document.

**Status: Partially implemented** (V1–V4 implemented; V5 not tested by definition).

**Evidence.**

- `packages/template-validator/src/docentric_copilot/template_validator/engine.py`
- `packages/template-validator/src/docentric_copilot/template_validator/models.py`
- `packages/template-validator/src/docentric_copilot/template_validator/report.py`
- Tests: `tests/unit/test_validator_and_compiler.py`

**Gaps.** V4 checks table widths only; overflow, orphan headings and image bleed are not detected.
Package findings `V1-007`–`V1-009` are reported inside the single `V1-006` check. Nested repeat depth
is bounded by the generic IR depth limit, not by a repeat-specific limit.

---

### FR-08 — Revisions, versions and export

**Statement.** The system shall treat a template as a sequence of immutable IR versions and produce a
bounded structural diff for every revision.

**Acceptance criteria.**

1. A plan creates a template and version 1; a revision appends a new version; versions are retrievable
   individually and as a list.
2. A revision merges the previous IR `metadata.intent` with the new instruction (≤ 2,000 characters)
   and re-plans; it never edits the previous version in place.
3. The diff is deterministic, traverses dictionaries in sorted key order, detects added/removed/changed
   values and list-length changes, and is capped at 200 changes.
4. The revision response includes a change summary and at most 50 change records.
5. Export returns the stored IR, mapping and validation JSON plus the canonical IR text.

**Status: Implemented.**

**Evidence.**

- `packages/planner/src/docentric_copilot/planner/revisions.py`
- `packages/planner/src/docentric_copilot/planner/service.py` (`TemplatePlanner.revise`)
- `services/api/src/docentric_copilot/api/routes/templates.py` (`revise`, `versions`, `export`)
- `services/api/src/docentric_copilot/storage/store.py`
- Tests: `tests/integration/test_api.py`, `tests/unit/test_planner.py`

**Gaps.** Revisions regenerate the whole IR; there is no three-way merge, no author attribution and
no retention policy for old versions (they remain until the database is removed).

---

### FR-09 — HTTP API

**Statement.** The system shall expose the pipeline over HTTP with typed request/response models, a
single error envelope, stable status codes, artifact downloads and OpenAPI documentation.

**Acceptance criteria.**

1. Endpoints: source upload and schema retrieval; plan, validate, compile, revise and preview;
   version listing and export; health, providers, capabilities, jobs, artifacts (download and inline
   view); root and `/health` aliases; `/docs`, `/redoc`, `/openapi.json`.
2. Uploads are limited to `.ddsp`, `.xml`, `.xsd`, `.zip` and to `max_ddsp_bytes`; other extensions
   return `415 input_unsupported`.
3. Every expected failure returns `{"error": {"code", "message", "details?}}` with the status defined
   by the error class; request-model validation returns `422 input_invalid` with per-field errors.
4. `strict_validation` (default true) rejects a plan whose V1–V3 do not pass with a validation report
   payload.
5. Compilation re-validates the IR and refuses when `can_compile` is false.
6. Artifacts have a TTL (`DC_ARTIFACT_TTL_SECONDS`, default 3600); expired or missing artifacts return
   `410 artifact_unavailable`; downloads carry `X-Artifact-Digest` (SHA-256 of the served bytes),
   `X-Content-Type-Options: nosniff` and `Cache-Control: no-store`.
7. Jobs record kind, status, timestamps, request and result/error; jobs are retrievable by id.
8. Provider and capability endpoints never expose credentials.
9. CORS is restricted to configured origins with the `GET, POST, OPTIONS` methods and only the
   `Content-Type` request header.

**Status: Implemented.** Authentication and authorisation are explicitly out of scope for the MVP
(see [THREAT_MODEL.md](THREAT_MODEL.md)).

**Evidence.**

- `services/api/src/docentric_copilot/api/app.py`
- `services/api/src/docentric_copilot/api/schemas.py`
- `services/api/src/docentric_copilot/api/routes/{sources,templates,system,common}.py`
- `services/api/src/docentric_copilot/storage/store.py`
- Tests: `tests/integration/test_api.py`
- Contract: [API_SPEC.md](API_SPEC.md)

**Gaps.** Single-process SQLite; no pagination (not needed at MVP scale); no rate limiting; no auth;
no idempotency keys.

---

### FR-10 — Command-line interface

**Statement.** The system shall provide a headless CLI that uses the same application service as the
API and returns stable exit codes.

**Acceptance criteria.**

1. Commands: `version`, `inspect`, `plan`, `validate`, `compile`, `preview`, `providers`, `ir-schema`.
2. `inspect` accepts a path or `-` for stdin; `--json` produces machine-readable output and `--paths`
   lists every field path.
3. `plan` writes IR JSON and optionally a mapping report; it refuses to write an IR when V1–V3 fail.
4. `validate` optionally writes HTML/JSON reports and exits 1 when the IR cannot compile.
5. `compile` writes the DOCX with no model call; `preview` writes HTML.
6. Exit codes: `0` success, `1` validation/processing failure, `2` usage error (CLI framework),
   `3` invalid/unsupported input (including security rejections), `4` unsupported target,
   `5` provider error, `6` not found.
7. Errors are printed as `error [code]: message` on stderr (or as the JSON envelope with `--json`);
   no secret or raw traceback is printed (`pretty_exceptions_enable=False`).

**Status: Implemented.**

**Evidence.**

- `services/api/src/docentric_copilot/cli/main.py`
- `packages/core/src/docentric_copilot/errors.py` (exit codes)
- Tests: `tests/unit/test_cli.py`

**Gaps.** There is no shell completion, no interactive mode and no config file; options are environment
variables and flags only.

## 3. Non-functional requirements

### NFR-01 — Determinism and reproducibility

**Statement.** For identical inputs and compiler version, the deterministic layers shall produce
identical bytes and identical digests.

**Target / verification.** Parse → canonical schema JSON; plan with `mock` → identical IR JSON and
digest; compile → identical DOCX SHA-256. Verified by repeated CLI runs and by tests.

**Status: Implemented.**

**Evidence.** `packages/core/src/docentric_copilot/serialization.py`,
`packages/docx-compiler/src/docentric_copilot/docx_compiler/package.py`,
`packages/template-ir/src/docentric_copilot/template_ir/canonical.py`,
`scripts/build_examples.py` (fixed timestamps), tests under `tests/golden_files/`.

**Limits.** Determinism is guaranteed only for the same build, IR and sample data. Hosted LLM
providers are not deterministic; their output becomes an input to the deterministic repair and
validation layers.

---

### NFR-02 — Untrusted-input safety

**Statement.** Every byte that reaches a parser shall be bounded and every hostile construct in the
documented threat model shall be rejected before use.

**Target / verification.** Size, entry, ratio, node and depth limits; no DTD/entity processing; no
network in the XML parser; unsafe entry names, nested archives and encrypted entries rejected;
failures are typed errors, not crashes.

**Status: Implemented.** Residual risks are documented in [THREAT_MODEL.md](THREAT_MODEL.md).

**Evidence.** `packages/ddsp-parser/src/docentric_copilot/ddsp_parser/safety.py`,
`packages/core/src/docentric_copilot/config.py` (`Limits`), `tests/unit/test_ddsp_parser.py`,
`tests/integration/test_api.py`.

---

### NFR-03 — Data minimisation and privacy

**Statement.** The system shall send the minimum data required to a model provider and shall not log
message content.

**Target / verification.** Prompts contain only field paths, types, collection flags and requirement
text; sample values are excluded from the schema fragment. Logging records provider/model/usage and
never message content. API responses never include raw model text (`raw_text` is excluded from
serialization).

**Status: Partially implemented.**

**Evidence.** `NormalizedSchema.compact_fragment` in
`packages/ddsp-parser/src/docentric_copilot/ddsp_parser/models.py`,
`packages/planner/src/docentric_copilot/planner/prompt.py`,
`packages/llm-gateway/src/docentric_copilot/llm/models.py` (`raw_text` excluded),
`packages/core/src/docentric_copilot/logging.py`.

**Gaps.** The free-text requirement is sent verbatim; if a user pastes personal data into it, that data
leaves the deployment. There is no PII detection or redaction of prompt text. Provider error details
may include up to 400 characters of the provider's response body.

---

### NFR-04 — Secret handling

**Statement.** Secrets shall never be returned by an API, printed by the CLI, written to storage or
emitted in logs.

**Target / verification.** Provider settings expose only `name`, `configured`, `default_model`,
`models`; the logger redacts secret-looking keys and known token formats; HTTP clients receive keys
only in headers.

**Status: Implemented.**

**Evidence.** `packages/core/src/docentric_copilot/config.py` (`public_view`),
`packages/core/src/docentric_copilot/logging.py`,
`packages/llm-gateway/src/docentric_copilot/llm/gateway.py` (`describe`),
`tests/unit/test_core.py`.

---

### NFR-05 — Fail-closed compatibility

**Statement.** An unimplemented or unverified compilation target shall fail with a typed error and
shall never produce a document labelled compatible.

**Target / verification.** `docentric-ax` → `UnsupportedTargetError` (409 / exit 4); capability
report `available=false, verified=false`; validation V5 `not_tested`; DOCX core properties state
`docentric-compatibility=not_tested`; optional stamp states "not verified".

**Status: Implemented.**

**Evidence.** `packages/docx-compiler/src/docentric_copilot/docx_compiler/generic.py`,
`packages/docx-compiler/src/docentric_copilot/docx_compiler/registry.py`,
`packages/template-validator/src/docentric_copilot/template_validator/engine.py`,
`tests/unit/test_validator_and_compiler.py`.

---

### NFR-06 — Cost control and telemetry

**Statement.** Generation shall be bounded by a configurable budget and every call shall report usage
and an estimated cost.

**Target / verification.** Per-call `budget_usd` (default 0.50) with a worst-case pre-flight; retries
bounded (0–5, default 2); usage and `estimated_cost_usd` returned in the generation result; pricing
table explicitly approximate.

**Status: Partially implemented.**

**Evidence.** `packages/llm-gateway/src/docentric_copilot/llm/pricing.py`,
`packages/llm-gateway/src/docentric_copilot/llm/providers.py`,
`packages/core/src/docentric_copilot/config.py`.

**Gaps.** Unknown model identifiers are unpriced, so the pre-flight budget cannot apply. Prices are a
static table and can drift from provider pricing. No aggregate cost accounting across jobs exists.

---

### NFR-07 — Latency and throughput

**Statement.** The system shall have a measured, reproducible latency profile for parsing, planning,
validation and compilation.

**Target.** p50/p95 measured by `benchmarks/run_benchmarks.py` (100 runs per example); no
service-level objective is declared. Results and their environment are recorded in
[BENCHMARKS.md](BENCHMARKS.md).

**Status: Partially implemented.** A 100-run benchmark exists for the three synthetic fixtures
(`benchmarks/run_benchmarks.py`, results in `benchmarks/results.json`), with p50/p95 recorded in
[BENCHMARKS](BENCHMARKS.md). There is no service-level objective, no load/concurrency measurement and
no large-document benchmark; the aggregate percentile is computed over three per-example p95 values.

**Evidence.** `benchmarks/run_benchmarks.py`, `benchmarks/results.json`, [BENCHMARKS](BENCHMARKS.md).

---

### NFR-08 — Concurrency and scalability

**Statement.** The service shall remain correct under concurrent HTTP requests.

**Target.** Correctness is provided by per-request service objects, a lock around SQLite access and a
threadpool for CPU-bound work. Horizontal scaling, queueing and multi-process writers are out of scope.

**Status: Not verified.** Concurrency is structurally supported (SQLite connection with
`check_same_thread=False` and a lock; `run_in_threadpool` for validation/compilation) but no load test
exists.

**Evidence.** `services/api/src/docentric_copilot/storage/store.py`,
`services/api/src/docentric_copilot/api/routes/templates.py`.

---

### NFR-09 — Observability

**Statement.** The system shall emit structured logs and persist job outcomes suitable for debugging.

**Target / verification.** JSON logs with stable keys and redaction; job rows with kind, status,
duration, request and result/error; validation reports as artifacts; startup logs settings through
`public_view()`.

**Status: Implemented** (no metrics endpoint, no distributed tracing).

**Evidence.** `packages/core/src/docentric_copilot/logging.py`,
`services/api/src/docentric_copilot/api/app.py`,
`services/api/src/docentric_copilot/storage/store.py`.

---

### NFR-10 — Portability and installability

**Statement.** The system shall install from source on Python 3.12 with a single `pip install -e .`
and shall not require Word, Dynamics 365 or a Docentric licence.

**Target / verification.** `requires-python = ">=3.12"`; Python-only dependencies installed from
wheels (lxml is the only compiled dependency used at runtime; FastAPI is pinned to
`>=0.162,<0.163` in this build); one distribution with multiple package directories; documented quick
start.

**Status: Implemented.** Source installation is documented; both container images build and run (API
`/health`, web HTTP 200). The frontend requires Node 22+ and a build-time
`NEXT_PUBLIC_API_BASE_URL`.

**Evidence.** `pyproject.toml`, README quick start, `scripts/build_examples.py`, `Dockerfile`,
`apps/web/Dockerfile`.

---

### NFR-11 — Quality gates and maintainability

**Statement.** The project shall enforce formatting/linting, static typing and tests, and shall keep
behaviour traceable to requirements.

**Target / verification.** ruff (line length 100, rule set configured), mypy (`check_untyped_defs`,
`warn_redundant_casts`), pytest with strict markers, branch coverage with an 85% gate. All are
enforced in `.github/workflows/ci.yml`; see [TEST_PLAN.md](TEST_PLAN.md).

**Status: Implemented.** Lint, format check, type checking, coverage-gated tests, example/golden
reproducibility checks, OpenAPI freshness and security scans run in CI; the web workspace has lint,
typecheck and build jobs; the Docker job builds both images. No browser E2E suite is committed.

**Evidence.** `pyproject.toml` (`[tool.ruff]`, `[tool.mypy]`, `[tool.pytest.ini_options]`,
`[tool.coverage.*]`), `tests/`, `apps/web/package.json` (lint/typecheck/build scripts), `.github/workflows/ci.yml`,
`Makefile` (`ci`, `test-cov`).

---

### NFR-12 — Versioning and interface stability

**Statement.** The IR contract, the HTTP API and the CLI shall be versioned, and unsupported versions
shall be rejected explicitly.

**Target / verification.** IR `1.0` with a migration registry; `ir_version_unsupported` for unknown
versions; OpenAPI document published at `/openapi.json`; API version prefix `/api/v1`; stable error
codes and exit codes.

**Status: Implemented** for the mechanism; no backwards-compatibility window has been exercised yet
because only one IR version exists.

**Evidence.** `packages/template-ir/src/docentric_copilot/template_ir/canonical.py`,
`services/api/src/docentric_copilot/api/app.py`,
`services/api/src/docentric_copilot/cli/main.py`.

## 4. Traceability matrix

| Requirement | Primary modules | Primary tests |
| --- | --- | --- |
| FR-01 | `ddsp_parser/*` | `tests/unit/test_ddsp_parser.py` |
| FR-02 | `schema_resolver/*`, `planner/service.py` | `tests/unit/test_schema_and_ir.py`, `tests/unit/test_planner.py` |
| FR-03 | `llm/*`, `planner/*` | `tests/unit/test_preview_and_llm.py`, `tests/unit/test_planner.py` |
| FR-04 | `template_ir/*`, `core/serialization.py` | `tests/unit/test_schema_and_ir.py` |
| FR-05 | `docx_compiler/*` | `tests/unit/test_validator_and_compiler.py`, `tests/golden_files/` |
| FR-06 | `preview/renderer.py` | `tests/unit/test_preview_and_llm.py` |
| FR-07 | `template_validator/*` | `tests/unit/test_validator_and_compiler.py` |
| FR-08 | `planner/revisions.py`, `storage/store.py` | `tests/unit/test_planner.py`, `tests/integration/test_api.py` |
| FR-09 | `api/*`, `app/service.py`, `storage/*` | `tests/integration/test_api.py` |
| FR-10 | `cli/main.py` | `tests/unit/test_cli.py` |
| NFR-01 | `docx_compiler/package.py`, `serialization.py` | `tests/golden_files/`, compiler determinism tests |
| NFR-02 | `ddsp_parser/safety.py`, `config.Limits` | `tests/unit/test_ddsp_parser.py`, `tests/integration/test_api.py` |
| NFR-03/04 | `logging.py`, `config.py`, `llm/models.py` | `tests/unit/test_core.py` |
| NFR-05 | `docx_compiler/registry.py`, validator engine | `tests/unit/test_validator_and_compiler.py`, `tests/unit/test_cli.py` |
| NFR-06 | `llm/pricing.py`, `llm/providers.py` | `tests/unit/test_preview_and_llm.py` |
| NFR-11/12 | `pyproject.toml`, `canonical.py`, `api/app.py` | whole suite |

Tests are being extended continuously; the matrices above name modules, not a frozen count. Run
`pytest --collect-only -q` for the current inventory.

## 5. Definition of Done

A change is done only when all of the following hold:

1. **Behaviour** is covered by at least one automated test (unit, integration or golden) that fails
   without the change, or the PR explains why a test is impossible.
2. **Types and lint** pass (`ruff check .`, `mypy packages services`).
3. **Docs** are updated: this SRS status/evidence, [TEMPLATE_IR.md](TEMPLATE_IR.md) for IR changes,
   [API_SPEC.md](API_SPEC.md) for endpoint/schema changes, and the README feature matrix.
4. **No unverified compatibility claim** is introduced. Any text about Docentric AX must use
   "unverified", "not tested" or "blocked"; the gate behaviour (409 / exit 4 / V5 `not_tested`) must
   remain intact.
5. **No secrets** in code, tests, fixtures or logs; new logging paths go through `redact()`.
6. **Determinism** is preserved for the deterministic layers; new timestamps, randomness or unordered
   iteration in compile/validate/serialize paths are rejected in review.
7. **Error contract** changes update the error class, the HTTP mapping, the exit code and
   [API_SPEC.md](API_SPEC.md) together.

## 6. Change control

- Requirement identifiers are stable. A removed requirement is marked "Withdrawn" with a reason, not
  renumbered.
- Status changes require evidence links; "implemented" without a code path and a test is not accepted.
- New external dependencies must be justified in an ADR when they affect determinism, security or
  deployment.
- Claims about third-party compatibility require an entry in
  [DOCENTRIC_AX_COMPATIBILITY.md](DOCENTRIC_AX_COMPATIBILITY.md) and the evidence described there.
