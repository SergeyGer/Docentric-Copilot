# Roadmap

> The same roadmap is published in the [Wiki](https://github.com/SergeyGer/Docentric-Copilot/wiki/Roadmap).
> Open work is tracked in [GitHub issues](https://github.com/SergeyGer/Docentric-Copilot/issues?q=is%3Aissue+is%3Aopen);
> each roadmap item links to its issue.

| Field | Value |
| --- | --- |
| Current release | 0.4.1 (Template IR 1.0) |
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
| Live provider verification | **Blocked** | Provide credentials and a repeatable test protocol; record results in [EVALUATION](EVALUATION.md) |
| 100-run benchmark with published environment | Done for the mock provider; hosted-provider latency still open | Record hosted-provider results in [BENCHMARKS §4.1](BENCHMARKS.md#41-reference-run-100-runs) |

## Next steps (ordered)

### P0 — before anyone else runs this in production

1. Publish the honest deployment constraint (no auth) in the README and the API docs; enforce it with a
   reverse proxy example. *(Documented; proxy configuration still missing.)*
2. ~~Fix the evaluation collector so alias-resolved bindings are counted~~ — done (`absolute_bindings`, precision 0.932, recall 0.965). Remaining:
   [EVALUATION §5.1](EVALUATION.md#51-committed-baseline-run-measured).
3. Provide credentials and a repeatable protocol for the hosted-provider comparison (currently no
   LLM result is recorded).
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
| Adaptive multi-LLM architecture | Router, policy, budgets and deterministic fallback implemented; live per-provider benchmark pending | `docs/ROUTING.md`, `tests/unit/test_routing_and_quality.py` |
| AI document quality and visual optimisation | IR-level quality checks and typed optimisation shipped; PDF renderer optional and not enabled | `docs/QUALITY.md`, ADR-0008 |
| Docentric AX compatibility engine | Interface and capability matrix only, gated and `experimental` | ADR-0009, `docs/DOCENTRIC_AX_COMPATIBILITY.md` |

Sequence follows the product brief: measurable AI quality first, then visual quality, with AX
feasibility research in parallel and no compatibility claims before an independent integration run.
