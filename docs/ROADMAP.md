# Roadmap

> The same roadmap is published in the [Wiki](https://github.com/SergeyGer/Docentric-Copilot/wiki/Roadmap).
> Open work is tracked in [GitHub issues](https://github.com/SergeyGer/Docentric-Copilot/issues?q=is%3Aissue+is%3Aopen);
> each roadmap item links to its issue.

| Field | Value |
| --- | --- |
| Current release | 0.10.0 (published); v0.10 in progress (Template IR 1.0) |
| Overall status | M0–M4 implemented to the extent described below; M5 in progress; the AX gate is blocked |
| Related | [PRD](PRD.md), [SRS](SRS.md), [FEASIBILITY](FEASIBILITY.md), [DOCENTRIC_AX_COMPATIBILITY](DOCENTRIC_AX_COMPATIBILITY.md) |

Milestones are cumulative. "Implemented" means the behaviour exists and is documented; it does not mean
all quality gates are met. Items that cannot be completed without external input are listed as
blocked, with the exact unblocking condition.

## M0 — Feasibility and compatibility decision

**Goal:** decide whether the product can honestly build documents for the target ecosystem, and record
the decision.

| Deliverable | Status |
| --- | --- |
| Problem framing and persona definition | Done — [PRD](PRD.md) |
| Research on the DDSP format and the public evidence available | Done to the extent possible — [DDSP_COMPATIBILITY](DDSP_COMPATIBILITY.md) |
| Compatibility paths A/B/C and the decision | Done — path B/C recorded in [DOCENTRIC_AX_COMPATIBILITY](DOCENTRIC_AX_COMPATIBILITY.md) and [ADR-0005](adr/0005-docentric-compatibility-gate.md) |
| Explicit non-claims list | Done — [DOCENTRIC_AX_COMPATIBILITY §9](DOCENTRIC_AX_COMPATIBILITY.md#9-explicit-non-claims) |
| Evidence required to reopen the AX gate | Done — [DOCENTRIC_AX_COMPATIBILITY §7](DOCENTRIC_AX_COMPATIBILITY.md#7-evidence-required-to-change-the-status) |
| Real DDSP package available for study | **Blocked** — no permitted representative package |

**Exit criteria met:** yes. **Caveat:** the feasibility conclusion is "build the generic engine and
defer AX", not "the target format is understood".

## M1 — Deterministic core

**Goal:** prove that a typed IR, deterministic validation and deterministic DOCX compilation are
viable without any AI.

| Deliverable | Status |
| --- | --- |
| Safe DDSP ingestion (ZIP/XML, limits, diagnostics) | Done — `ddsp_parser/` |
| Normalized schema and sample-data coercion | Done |
| Template IR v1.0, canonical JSON, digest, JSON Schema export | Done — `template_ir/` |
| Path resolution and repeat-alias scoping | Done — `schema_resolver/` |
| Validation V1 structural, V2 semantic, V3 logical | Done — `template_validator/` |
| V4 visual (table width only) | Partial — requires sample data |
| V5 Docentric AX compatibility | Not implemented by design — `not_tested` |
| Generic DOCX compiler, deterministic package normalisation | Done — `docx_compiler/` |
| Synthetic examples and deterministic generator | Done — `examples/`, `scripts/build_examples.py` |
| Golden-file regression suite | Done — `tests/golden_files/` |

**Exit criteria met:** yes, for the generic target. The validation level V5 is intentionally out of
scope for this milestone.

## M2 — Planning and provider gateway

**Goal:** turn requirements into IR proposals without letting model output bypass the deterministic
checks.

| Deliverable | Status |
| --- | --- |
| Deterministic baseline planner (`heuristic-baseline-v1`) | Done — `planner/heuristic.py` |
| Provider gateway with OpenAI, Anthropic, Gemini adapters | Done; **live calls unverified** |
| Mock provider for offline demos/tests | Done |
| Structured output, retries, timeouts, cost telemetry, budget pre-flight | Done |
| Prompt fencing and data-minimised schema fragment | Done — `planner/prompt.py` |
| Deterministic sanitiser and removal report | Done — `planner/service.py` |
| Mapping report with resolved/ambiguous/missing/invalid | Done |
| Revision planning and structural diff | Done — `planner/revisions.py` |
| Evaluation harness and baseline metrics | Done — `evaluation/`, `benchmarks/run_evaluation.py` |
| Measured LLM-vs-baseline comparison | **Blocked** — requires provider credentials and a repeatable run protocol |

**Exit criteria met:** partially. The mechanism is complete; the claim "models improve on the baseline"
has not been demonstrated.

## M3 — Validation and compilation hardening

**Goal:** make refusal safe and output reproducible.

| Deliverable | Status |
| --- | --- |
| Package inspection (required entries, macros, OLE/ActiveX, external relationships) | Done |
| Compilation blocked unless V1–V3 pass | Done (API and CLI) |
| Byte-identical DOCX for identical inputs | Done and tested |
| Fixed timestamps, sorted entries, fixed core properties | Done |
| Image payload validation (magic bytes, 5 MiB cap) | Done |
| Independent HTML preview with escaping and CSP | Done |
| Revision/version storage and export | Done |
| Golden fixtures covering eight scenarios | Done |
| Cross-platform verification (Windows/macOS) | Not done |

**Exit criteria met:** yes for Linux/Python 3.12; cross-platform is an open item.

## M4 — Interfaces, operations and documentation

**Goal:** make the engine usable by a developer and deployable locally.

| Deliverable | Status |
| --- | --- |
| FastAPI application with typed schemas and error envelope | Done |
| CLI with stable exit codes | Done |
| SQLite persistence, job records, TTL artifacts | Done |
| Local artifact cleanup and expired-artifact behaviour | Done |
| Dockerfiles (multi-stage, non-root, healthcheck) and compose stack | Done: both API and web images build and run (API `/health`, web HTTP 200); `docker compose config` validates; a full compose run was blocked by a Docker Bake permission in the development environment |
| Makefile developer workflow (`install`, `test`, `test-cov`, `lint`, `typecheck`, `bench`, `eval`, `openapi`, `dev-api`, `dev-web`, `docker-up`, `docker-down`, `ci`) | Done |
| Benchmark runner | Done — [BENCHMARKS](BENCHMARKS.md) |
| Static OpenAPI export (`docs/openapi.json`) | Done — `scripts/export_openapi.py` |
| Documentation set (PRD, SRS, architecture, IR, API, DDSP, AX, threat model, test plan, evaluation, benchmarks, feasibility, ADRs) | Done |
| Web UI (`apps/web`) | Delivered: Next.js 15 workspace; lint, typecheck and build pass; manual real-browser smoke run passed; no committed browser E2E; layouts below 1024 px untested |
| Browser E2E suite | Not committed: a manual Playwright/Chromium smoke run passed, but the scripts and artefacts were temporary and no test suite is in the repository |
| CI workflows (`.github/workflows/`) | Present: `ci.yml` (python, web, docker, security) and `release.yml`; the Docker job builds both images |

**Exit criteria met:** yes, with two explicit gaps: no committed browser E2E suite and no responsive
verification below 1024 px. Both are tracked under M5.

## M5 — Production hardening and scale (in progress)

**Goal:** make the service safe to operate for multiple users and honest at scale.

| Deliverable | Status | Next step |
| --- | --- | --- |
| Authentication/authorisation | Not started | Add an auth layer or document a mandatory authenticating proxy; update [THREAT_MODEL R-01](THREAT_MODEL.md#7-residual-risk-register) |
| Rate limiting, quotas, request budgets | Not started | Add proxy-level limits and per-user token/cost quotas |
| Durable, concurrent storage | Not started | Replace single-process SQLite/file artifacts with a database + object store; define retention |
| Retention and deletion API | Not started | Add explicit delete/export endpoints and a documented retention policy |
| Metrics/tracing | Not started | Export request latency, provider spend, validation outcomes; add tracing |
| Load and soak testing | Not started | Benchmark concurrent plan/compile requests; publish p95 under load |
| Property-based/fuzz testing of parsers | Not started | Add Hypothesis campaigns; run in CI |
| Dependency/static security scanning | Partial: `bandit` and `pip-audit` run in CI | Add container image scanning and pin a Python lockfile |
| Independent security review | Not started | External review against [THREAT_MODEL](THREAT_MODEL.md) |
| Accessibility/localisation | Not started | Locale-aware formatting and localised UI are separate product decisions; the UI is English-only |
| Responsive layouts and committed browser E2E | Not started | Verify < 1024 px viewports, commit a Playwright suite, and run it in CI |
| Frontend delivery optimisation | Not started | Evaluate Next.js standalone output and a slimmer runtime image (currently the full dependency tree is copied because `next.config.ts` is loaded at runtime) |
| Docentric AX adapter | **Blocked** | Complete the evidence in [DOCENTRIC_AX_COMPATIBILITY §7](DOCENTRIC_AX_COMPATIBILITY.md#7-evidence-required-to-change-the-status) |
| Real DDSP compatibility testing | **Blocked** | Obtain a permitted representative package |
| Live provider verification | Done for the gold benchmark (PR-05); model drift remains | Rerun on model updates and record the new dataset/report hashes; no paid calls in CI |
| 100-run benchmark with published environment | Done for the mock provider; hosted-provider latency still open | Record hosted-provider results in [BENCHMARKS §4.1](BENCHMARKS.md#41-reference-run-100-runs) |

## M6 — Reference Template Intelligence completion (v0.10, in progress)

**Goal:** complete the v0.10 P0 evidence work without claiming a Docentric AX runtime. Only the
workstreams below are in scope for this branch; nothing else is presented as done.

| Workstream | What is in the repository | Status |
| --- | --- | --- |
| PR-01 corpus baseline and documentation freeze | Version strings, README/roadmap status, CHANGELOG under `[Unreleased]`, ADR-0013, bounded corpus assessment script | Done (baseline frozen; package version not bumped) |
| PR-02 D365 embedded schema extraction | `ProjectData`/`DataSource`/`Schema`/`PreviewData`/field-metadata extraction with part + XPath + source-id provenance; `schema_source = projectdata \| ddsp \| unavailable` | Done — static, read-only |
| PR-03 canonical schema and binding resolver | Canonical fields/collections/scopes/types; exact six-status taxonomy; evidence on every `resolved`; CLI and API | Done — partial semantics by design |
| PR-04 gold semantic dataset | 32 versioned cases, ten families, annotation guide, 20/12 calibration/holdout split, deterministic rule pass | Done — single-annotator labels; AT-07 partial (no independent human double review) |
| PR-05 live benchmark runner and report | 288 live runs (32 cases × 3 providers × 3 repeats), calibration/holdout, cost and error taxonomy, JSON/CSV/HTML | Done — 288/288 runs, $6.8849 verified + $0.2910 estimated; see [EVALUATION §2.7](EVALUATION.md#27-gold-semantic-benchmark-v010-pr-05) |
| PR-06 safe Reference → generic Template IR | Opt-in projection with no silent loss; strict/best-effort; CLI/API; validation | Done — partial subset (#27): Field/Label/List→Repeat/If/Image; Table not inferred |
| PR-07 visual reference diff | Page-level LibreOffice rendering and failure-safe status (#28) | Done — partial: LibreOffice, not Word fidelity; no real renderer in CI |
| PR-08 report persistence/export and browser E2E | SQLite TTL reports, reopen/export, web `?id=` (#29) | Done — partial: no committed Playwright/browser E2E |
| PR-09 release hardening | Docs, ADR-0016, version/feature consistency, OpenAPI, tests (#30) | Done for this branch — package version stays `0.10.0` under `[Unreleased]` |

**Truthful status for the matrix:** the D365 adapter and resolver are `partial`, not "D365
validation complete". 11 of 11 local D365 DOCX documents yielded embedded `projectdata` schema
evidence; 233 of 246 observed bindings resolved with full evidence, while 4 were `unknown_path`, 8
`unsupported_expression` and 1 `type_mismatch`. Runtime compatibility remains `not_tested`; the AX
gate is unchanged and no native output is produced.

**Exit criteria:** P0 acceptance tests pass and the corpus counts are reproducible with
`python scripts/assess_d365_corpus.py` (outputs stay under the ignored `.tools/`). PR-04/PR-05
are complete for P0: the 32-case dataset and the 288-run report are committed, with calibration and
holdout shown separately. The only open annotation item is independent double review (AT-07 stays
partial); no runtime compatibility is claimed.

## M7 — v0.11 P1 reference workflow (unreleased)

**Goal:** make the read-only reference evidence usable without pretending it is a native Docentric
or Word-fidelity result. The package version remains `0.10.0`; this work is under `[Unreleased]`.

| Item | Status | Notes / partial scope |
| --- | --- | --- |
| #26 D365 evidence in ReferenceGraph | Done | `schema_source`/`source_id`/`part#xpath` on schema nodes; exact resolver status on `resolves_to`; evidence coverage and unresolved-by-status summary. Public tests are synthetic; corpus not re-run. |
| #27 safe Reference → Generic Template IR | Done — partial | Field, Label, List→Repeat, If, Image; skips are explicit; strict/best-effort; no Table inference; generic DOCX only. |
| #28 visual reference diff | Done — partial | LibreOffice rendering, page/blank/ink/shifted-region comparison, `report.json` + safe `report.html`; `renderer_unavailable` never pass/fail; not Word fidelity; no real renderer in CI. |
| #29 persistence/reopen/export | Done — partial | Local SQLite TTL; `POST/GET /reports`; JSON/HTML export; web `?id=`; no committed Playwright E2E. |
| #30 hardening/docs | Done for branch | ADR-0016 (ADR-0015 was already assigned), CHANGELOG/README/REFERENCE_TEMPLATES/EVALUATION/wiki updates, OpenAPI regenerated. |
| Docentric AX runtime compatibility | **Not tested** | Unchanged; `target=docentric-ax` remains fail-closed. |

Remaining gaps tracked: browser E2E, real-renderer CI evidence, Table/Group/SubDocument/Barcode
import, corpus-wide D365 graph re-run, and a durable multi-process report store.

## Next steps (ordered)

### P0 — before anyone else runs this in production

1. Publish the honest deployment constraint (no auth) in the README and the API docs; enforce it with a
   reverse proxy example. *(Documented; proxy configuration still missing.)*
2. ~~Fix the evaluation collector so alias-resolved bindings are counted~~ — done (`absolute_bindings`, precision 0.932, recall 0.965). Remaining:
   [EVALUATION §5.1](EVALUATION.md#51-committed-baseline-run-measured).
3. ~~Provide credentials and a repeatable protocol for the hosted-provider comparison~~ — done for
   the gold benchmark (three providers, three repeats, bounded spend). Remaining: an independent
   label reviewer and a rerun when a provider changes its model id or price.
4. Add a committed browser E2E suite and responsive checks (< 1024 px), and wire them into CI.

### P1 — quality and evidence

5. Add a PII/redaction decision for requirement text before it reaches a hosted provider.
6. Add CSP to HTML artifact viewing and restrict preview image media types (THREAT_MODEL R-04, R-05).
7. Add large-document and concurrency benchmarks with declared budgets.
8. Add IR migration tests with the first real migration.
9. Add provider contract tests against recorded fixtures (not live calls) to catch API drift.

### P2 — scope expansion

10. Locale-aware formatting (dates/numbers) behind an explicit option.
11. Retention/deletion API and a storage backend suitable for multiple processes.
12. Optional PDF export (requires a renderer and a separate fidelity statement).

## Blocked items and unblocking conditions

| Blocked item | Why blocked | Unblocking condition |
| --- | --- | --- |
| Docentric AX adapter and any compatibility claim | No licensed environment, no authoritative specification, no evidence | [DOCENTRIC_AX_COMPATIBILITY §7](DOCENTRIC_AX_COMPATIBILITY.md#7-evidence-required-to-change-the-status) satisfied and reviewed |
| Real DDSP parser validation | No representative permitted package | A synthetic-or-sanitised package with permission, added per [DDSP_COMPATIBILITY §10](DDSP_COMPATIBILITY.md#10-adding-fixtures-how-to-extend-coverage) |
| Live provider comparison | No credentials in the project environment; no network test policy | Credentials and a recorded, repeatable protocol; results in EVALUATION |
| Independent security review | External dependency | Engagement and published findings |

## Out of scope (not planned)

- Becoming a word processor or a pixel-faithful renderer.
- Replacing a licensed designer product.
- Training or fine-tuning models.
- Multi-tenant SaaS billing.
- Claiming compatibility based on the absence of errors.

## Three strategic initiatives

| Initiative | Status | Evidence |
| --- | --- | --- |
| Adaptive multi-LLM architecture | Router, policy, budgets and deterministic fallback implemented; 288-run live gold benchmark recorded | `docs/ROUTING.md`, `benchmarks/gold_report.json`, `tests/unit/test_routing_and_quality.py` |
| AI document quality and visual optimisation | IR-level quality checks and typed optimisation shipped; PDF renderer optional and not enabled | `docs/QUALITY.md`, ADR-0008 |
| Docentric AX compatibility engine | Interface and capability matrix only, gated and `experimental` | ADR-0009, `docs/DOCENTRIC_AX_COMPATIBILITY.md` |

Sequence follows the product brief: measurable AI quality first, then visual quality, with AX
feasibility research in parallel and no compatibility claims before an independent integration run.
