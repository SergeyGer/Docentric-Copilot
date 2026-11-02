# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The Template IR has its own
version (`1.0`) independent of the distribution version.

## [Unreleased]

No changes yet after the 0.2.0 release. Planned work is tracked in [docs/ROADMAP.md](docs/ROADMAP.md);
plans are not changelog entries.

## [0.2.0] - documentation and hardening release

A presentation and hardening release. The engine behaviour is unchanged from 0.1.0; the product is
easier to evaluate, and the dependency tree is clean.

### Added

- Full project Wiki with a navigation sidebar, interface screenshots and 22 pages covering the product,
  the architecture, the API, the CLI, validation, security, benchmarks and the roadmap.
- Interface screenshots captured from a real browser run (`docs/assets/`).
- Social preview image and curated repository topics.
- Dependabot configuration with grouped weekly updates for npm, pip and GitHub Actions.
- Baseline security headers for the web workspace (`X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`, `Permissions-Policy`).

### Changed

- `README.md` rewritten for a non-technical audience; engineering detail moved to the Wiki.
- Per-request `max_generation_cost_usd` now reaches the gateway as a pre-flight budget.
- Evaluation harness resolves repeat aliases through the planner's scope walker, re-baselining recall
  from 0.772 to 0.965 (the earlier value understated table bindings).
- Benchmark aggregates are computed over every sample rather than over per-fixture p95 values.
- CLI `plan` and `validate` honour the configured IR limits.

### Fixed

- `postcss` and `minimatch` advisories in the web dependency tree via npm overrides
  (`npm audit` reports 0 vulnerabilities).
- Artifact digests and the `X-Artifact-Digest` header are the SHA-256 of the served bytes.

### Compatibility

Unchanged: generic DOCX only. Docentric AX remains gated and reported as `not_tested`.

## [0.1.0] - unreleased

The first MVP milestone. It is **not** a compatibility release: Docentric AX output is unavailable and
unverified.

### Added

- Safe DDSP ingestion: ZIP/single-XML containers, manifest hints, XSD-to-schema mapping, sample-data
  extraction and schema inference, with stable diagnostic codes (`DDSP001`–`DDSP011`, `XML001`–`XML004`,
  `SCHEMA001`–`SCHEMA006`, `SAMPLE001`–`SAMPLE004`, `INFO001`–`INFO003`).
- Normalized schema model with deterministic canonical JSON and digest.
- Template IR v1.0: typed documents, sections, blocks, expressions, formatting, page settings,
  canonical serialization, SHA-256 digest, JSON Schema export (`docentric-copilot ir-schema`) and an
  empty migration registry.
- Schema path resolution with lexical repeat aliases and collection-context enforcement.
- Deterministic candidate search and a reviewable mapping report with
  `resolved`/`ambiguous`/`missing`/`invalid` statuses.
- Deterministic baseline planner (`heuristic-baseline-v1`) that requires no credentials.
- LLM gateway with OpenAI, Anthropic and Gemini adapters (structured output, retries, timeouts,
  cost telemetry and a worst-case budget pre-flight that applies only to models with known pricing)
  and a deterministic `mock` provider.
- Planner repair pass that removes unresolvable references and records them, plus revision planning
  with a bounded structural diff.
- Validation engine with five separate levels: V1 structural, V2 semantic, V3 logical, V4 visual
  (table width), V5 compatibility (`not_tested`).
- Deterministic generic DOCX compiler with fixed ZIP timestamps, sorted entries, fixed core
  properties, placeholder rendering without sample data, image payload validation and package
  inspection (required entries, macros, OLE/ActiveX, external relationships).
- Independent HTML preview with escaping, `data:` images and an explicit layout disclaimer.
- Next.js 15 web workspace (`apps/web`): upload, schema explorer, prompt editor, mapping and
  validation review, sandboxed preview, compilation/download, version history and revision flow.
  Verified with `npm run lint`, `npm run typecheck`, `npm run build` and a manual real-browser smoke
  run; no browser test suite is committed.
- FastAPI application with a single error envelope, typed request/response models, artifact TTL,
  job records and OpenAPI at `/openapi.json`.
- Typer CLI (`version`, `inspect`, `plan`, `validate`, `compile`, `preview`, `providers`, `ir-schema`)
  with exit codes 0–6.
- SQLite persistence for sources, templates, versions, jobs and artifacts, with startup purge of
  expired artifacts and old sources.
- Synthetic, deterministically generated example packages (quotation, invoice, purchase order) and
  the generator `scripts/build_examples.py --check`.
- Test suite: unit tests for core/parser/IR/planner/validator/compiler/preview/LLM/CLI, API
  integration tests, and golden fixtures with normalized schema/IR/mapping/validation/DOCX
  projections.
- Benchmark runner (`benchmarks/run_benchmarks.py`, default 100 runs) and planner evaluation harness
  (`packages/evaluation`, `benchmarks/run_evaluation.py`).
- Developer tooling: `Makefile` (`install`, `install-dev`, `install-web`, `test`, `test-cov`,
  `lint`, `typecheck`, `format`, `bench`, `eval`, `openapi`, `dev-api`, `dev-web`, `docker-up`,
  `docker-down`, `ci`), multi-stage `Dockerfile` for the API, `apps/web/Dockerfile` for the frontend,
  `docker-compose.yml`, `scripts/export_openapi.py` and GitHub workflows (`ci.yml`: python, web,
  docker, security; `release.yml`).
- Documentation set: PRD, SRS, architecture, Template IR, API specification, DDSP compatibility,
  Docentric AX compatibility gate, threat model, test plan, evaluation, benchmarks, feasibility,
  roadmap and six ADRs; project policies (`CONTRIBUTING`, `SECURITY`, `CODE_OF_CONDUCT`).

### Changed

- Nothing yet; 0.1.0 is the initial milestone.

### Deprecated

- Nothing.

### Removed

- Nothing.

### Fixed

- Nothing yet; 0.1.0 is the initial milestone.

### Security

- XXE and entity expansion rejected; XML parsed with DTD/entity/network access disabled.
- ZIP protections: entry-count, uncompressed-size and compression-ratio limits; unsafe entry names,
  nested archives and encrypted entries rejected; no extraction to disk.
- XML node and depth limits; XSD recursion and schema-node budgets.
- Secret redaction in structured logs; provider settings exposed only as a credential-free view;
  provider error bodies truncated to 400 characters.
- Compiled packages inspected for macros, embedded OLE/ActiveX objects and external relationships
  before being returned.
- Artifacts addressed by random ids, `nosniff`/`no-store` download headers, TTL and lazy expiry.
- Docentric AX compatibility fails closed: HTTP 409 / CLI exit 4, validation V5 `not_tested`,
  capability flags `available=false, verified=false`, DOCX metadata states the non-claim.

### Known limitations

- **Docentric AX compatibility is unverified.** The AX compiler is not implemented and always fails
  closed. Do not describe output as Docentric AX compatible.
- Real-world DDSP packages have not been tested; parsing is evidence-based and exercised on synthetic
  fixtures only.
- Live OpenAI/Anthropic/Gemini calls are not verified in this repository; adapters are contract-tested
  with mocked transports.
- V4 visual validation only checks declared table widths against the page width, and only when sample
  data is supplied.
- The HTML preview is a content preview, not a Word-faithful layout simulation.
- No authentication, authorisation, rate limiting or multi-tenancy; the service is intended for a
  trusted network.
- Single-process SQLite and local artifact files; no horizontal scaling.
- Benchmark results are one local 100-run mock measurement; they are environment-specific, and no
  hosted-provider latency has been measured.
- The evaluation harness has known accounting limitations for alias-resolved bindings (see
  [docs/EVALUATION.md](docs/EVALUATION.md)).
- Browser E2E tests are not committed: a manual Playwright/Chromium smoke run passed, but no test
  suite or browser configuration is in the repository. Layouts below 1024 px and real (non-mock)
  provider flows are not verified in the UI.
- The frontend has no Content-Security-Policy or other security headers configured; see
  [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) (R-13).
- Both container images build and run; a full `docker compose up` was not completed in the development
  environment because of a Docker/Buildx permission, though the compose configuration validates.

[Unreleased]: https://github.com/SergeyGer/Docentric-Copilot/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/SergeyGer/Docentric-Copilot/releases/tag/v0.1.0
