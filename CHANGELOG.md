# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The Template IR has its own
version (`1.0`) independent of the distribution version.

## [Unreleased]

## [0.10.0] - 2026-11-05

### Added
- v0.10 P0 D365 embedded schema adapter (`d365_schema.py`): read-only extraction of
  `customXml/ProjectData` `DataSources`, embedded XSD (`Schema/XsdList/MainXsd`), `PreviewData`
  sample instances and `xse:label`/`xse:refCode` field metadata. Every fact keeps its OOXML part,
  XPath-like location and stable source id; documents are classified as
  `schema_source = projectdata | ddsp | unavailable`.
- Canonical schema model with fields, collections, scopes, XSD types, type families, namespaces and
  raw/canonical paths; a caller-supplied DDSP is a fallback only when the embedded schema is not
  usable.
- Canonical binding resolver (`binding_resolver.py`) with the exact six-status taxonomy
  `resolved | ambiguous | unknown_path | type_mismatch | schema_unavailable |
  unsupported_expression`. Every `resolved` binding carries source, canonical path, collection
  scope, schema type and `part#xpath` evidence; duplicate sources/paths and unsupported expressions
  are diagnostics and never a success.
- CLI `docentric-copilot reference d365 PATH --json OUT [--ddsp PATH]` and
  `POST /api/v1/reference/d365` (multipart or a path confined to the configured corpus roots), plus
  the `reference_d365_bindings` capability flag.
- Synthetic negative fixtures for duplicate sources, wrong context path, missing field, type
  mismatch, corrupted ProjectData, ambiguous source and unsupported expression; each asserts its
  exact status and that no negative fixture becomes `resolved`.
- `scripts/assess_d365_corpus.py` for a bounded local corpus assessment; it writes counts, hashes and
  statuses only under the git-ignored `.tools/` directory.
- ADR-0013 and the D365 section of `docs/REFERENCE_TEMPLATES.md`.
- v0.10 PR-04 gold semantic dataset (`benchmarks/gold_cases.json`, schema `gold-cases/v1`, version
  `1.0.0`): 32 synthetic cases across ten families (flat fields, images, collections, nested lists,
  conditions, missing, ambiguous, multilingual, long tables, forbidden scope) and four specification
  categories. Each case declares concept-level `required_bindings` (expected paths, allowed
  alternatives, required, type/context, satisfiability), `forbidden_paths`, `expected_blocks`,
  `family`, `category`, `difficulty`, `split`, `language` and a rationale. The canonical cases
  SHA-256 is recorded in reports; no Docentric corpus content is used.
- `benchmarks/gold_dataset.py`: deterministic rule pass for the gold dataset (schema paths, types,
  contexts, forbidden scope, block kinds, family invariants, exact 20/12 split and stratified family
  coverage, private-corpus exclusion) plus version/hash/split metadata.
- `benchmarks/gold_evaluation.py`: live gold runner with the requested `--providers`, `--repeats`,
  `--split`, `--max-spend`, `--warn-spend` and `--allow-unpriced` flags; per-case/per-provider
  precision, recall, F1, requirement coverage, type/context correctness, block coverage and a separate
  `valid_template_rate`; error taxonomy; latency p50/p95; token usage; verified/estimated/unavailable
  cost. It writes JSON, CSV and self-contained HTML with dataset hash, split, model versions,
  prompt version, settings, sample sizes and calibration/holdout sections; per-run records go to the
  git-ignored `benchmarks/gold_runs.jsonl`.
- Ambiguous-concept scoring: when a run produces more than one annotated acceptable path for a
  matched requirement, the duplicates are marked used rather than charged as false positives; they
  are not extra true positives and forbidden paths are never exempted.
- `docs/GOLD_LABELS.md` (annotation guide, split policy, versioning, honest single-annotator
  adjudication record), ADR-0014 and the gold benchmark sections of `docs/EVALUATION.md`,
  `docs/BENCHMARKS.md` and the wiki.

### Changed
- Documentation baseline consistency for v0.10: README and ROADMAP state the current release as
  0.9.0 and describe the v0.10 P0 work truthfully; SRS/PRD/ARCHITECTURE/THREAT_MODEL version headers
  and OpenAPI examples were aligned. The package version is intentionally **not** bumped yet; the
  release changelog entry will be written at release time.
- README, ROADMAP, EVALUATION, BENCHMARKS and the wiki now report PR-04/PR-05 as complete and point
  to the committed gold report. The dataset labels remain single-annotator; AT-07 is reported as
  partial, not passed.
- `.gitignore` excludes `benchmarks/gold_runs.jsonl`; only aggregates and the annotation guide are
  committed, never raw provider traces.

### Notes
- Docentric AX runtime compatibility remains `not_tested`. The adapter reads static schema evidence
  only: it does not execute X++/.axpp, macros or expressions, and it makes no native-output claim.
- Local corpus result (counts only): 11/11 D365 DOCX with `projectdata` schema evidence, 246
  bindings — 233 resolved with evidence, 4 `unknown_path`, 8 `unsupported_expression`,
  1 `type_mismatch`, 0 `ambiguous`, 0 `schema_unavailable`. The official archive itself remains
  uncommitted under `.tools/reference-corpus/`.
- Gold benchmark live run (2026-11-05): 288/288 planned runs (32 cases × 3 providers × 3 repeats) on
  dataset `1.0.0` (`c2b1d89c70f96f14884de54792784d0dbd3ffaa71d0700d5f73c5c24e93ece30`).
  Precision / recall / F1 / semantic pass / valid template: OpenAI `gpt-6-sol` 0.226 / 1.000 / 0.368
  / 55.2% / 100%; Anthropic `claude-sonnet-5-5` 0.220 / 0.996 / 0.361 / 69.8% / 100%; Gemini
  `gemini-3.6-flash` 0.184 / 1.000 / 0.311 / 64.6% / 96.9%. Holdout semantic pass was 61.1% /
  66.7% / 66.7% (36 runs per provider), calibration 51.7% / 71.7% / 63.3% (60 runs per provider).
  Spend was **$6.8849 verified + $0.2910 estimated = $7.1759**, under the $10 cap and above the $5
  warning line; three Gemini compact-IR failures have unknown cost and are counted as `unavailable`,
  not $0.00. Error taxonomy: `wrong_binding` 276 runs, `wrong_context` 70, `structured_output` 3,
  `missing_field` 1. AT-08 (three runs per case/model) and AT-09 (precision/recall/F1/coverage and
  class-level errors) are met; AT-07 remains **partial** because the labels are single-annotator with
  no independent human double review. No Docentric corpus content is committed and
  `runtime_compatibility` remains `not_tested`.


## [0.9.0] - 2026-11-04

### Added
- REF-06 reference inspector in the web app: `/reference` with upload of DOCX/ZIP/AXPP and an
  optional DDSP, overview counters, searchable controls table with a detail drawer (unknown and
  ambiguous rows are never hidden), graph view with edge statuses, and a two-file structural /
  semantic diff view. The AX runtime notice is permanently visible.

## [0.8.0] - 2026-11-04

### Added
- REF-04 reference diff: structural and semantic comparison of two reference graphs/templates
  (added/removed/changed controls, elements, bindings, sources), coverage and unresolved deltas,
  deterministic digest; CLI `reference diff` and `POST /api/v1/reference/diff`.
- REF-05 reference-based evaluation: gold set derived from reference element patterns (Field, List,
  If, Image, Label), synthetic committed cases plus a local-corpus mode, precision/recall/coverage
  separate from valid-template rate, JSON/CSV/HTML reports with provenance and cost status.
- ADR-0012, reference documentation and wiki updates.

## [0.7.0] - 2026-11-04

### Added
- REF-01 real DDSP adapter: parses Docentric DDSP XML into the existing NormalizedSchema
  (fields, nested repeating groups, parameters, locales) with explicit unsupported-construct
  diagnostics and bounded, entity-safe parsing.
- REF-03 ReferenceGraph: control → element → source → schema-field graph with `bound_to`,
  `resolves_to`, `iterates` and `condition` edges, resolved/ambiguous/unknown statuses and
  stable serialization.
- Read-only Reference IR projection (`ReferenceDocument`), explicitly separate from Template IR
  and non-compilable; graph coverage report with unresolved reasons.
- CLI `docentric-copilot reference graph PATH [--ddsp] [--json]` and
  `POST /api/v1/reference/graph`; ADR-0011 and documentation updates.

## [0.6.0] - 2026-11-04

### Added
- Reference Template Inspector (milestone A): safe inventory of DOCX/ZIP/AXPP containers,
  SHA-256 deduplication, nested-archive guards, OOXML content-control extraction with
  tag/alias/databinding/part, Docentric element classification (Field, List, If, Image, Label,
  Barcode, SummaryField, SubDocument, Group) and metadata resolution with explicit
  `resolved|ambiguous|unknown` outcomes.
- CLI `docentric-copilot reference inspect` and `POST /api/v1/reference/inspect`, both read-only.
- Reference report with per-kind counts, coverage ratio and `runtime_compatibility: not_tested`;
  ADR-0010, `docs/REFERENCE_TEMPLATES.md` and the wiki page.
- Docentric example archive is processed only from an ignored local corpus; nothing from it is
  stored in the repository.

### Changed
- `docs/media` keeps a single current demo video; obsolete v1–v3 cuts were removed.

## [0.5.0] - 2026-11-04

### Added
- Semantic quality evaluation: 20 labelled cases with gold mappings and forbidden paths,
  precision/recall/coverage computed separately from structural validity, a 9-code error taxonomy,
  and JSON/CSV/HTML reports. Live run: 180 generations, 178 valid, semantic pass 66.7%, recall and
  coverage 1.0, precision 0.21; error taxonomy shows 170 wrong-binding and 26 wrong-context findings.
- Full-document visual regression: LibreOffice rendering of every page before/after optimization for
  four golden cases (long descriptions, 40-row table, empty collection, conditional block), with
  page-level checks, explicit `not_checked` semantics, screenshot artifacts and a summary report.
- Spend transparency: known/estimated/unavailable cost status; the semantic run cost 4.59 USD
  (under the 5 USD warning threshold).

### Changed
- Demo V4 remains the published video; a V5 recording is tracked separately.

## [0.4.1] - 2026-11-02

### Fixed
- Unknown model prices are reported as `—`, not `$0.00`; the deterministic baseline keeps its zero.
- OpenAI adapter retries with `max_completion_tokens` and without `temperature`, as the GPT-6 models require.
- Runtime version string follows the release.

### Changed
- Default OpenAI model is `gpt-6-sol` (GPT-4.1 is being retired).

## [0.4.0] - 2026-11-02

### Added
- Routing panel: complexity, provider, budget, fallback and review state in the workspace.
- Quality dashboard with explainable checks, IR paths and a one-click **Optimize layout** that
  creates a new version and re-validates it.
- **Compare models**: the same brief through two providers, with measured latency, tokens, cost,
  mapping counts, validation and a recommendation.
- `POST /api/v1/templates/compare` and a `quotation-defect` demo case with an overflowing table.
- Demo sessions return the quality report; the providers endpoint always exposes the default model.

### Changed
- `scripts/build_demo_video.py` resolves the repository root from its own location.

## [0.3.0] - 2026-11-02

### Added

- **Adaptive routing** (`docs/ROUTING.md`): complexity classification from observable facts, provider
  tiers with explicit budgets, deterministic fallback and `requires_review` for ambiguous briefs.
  `POST /api/v1/templates/route` returns the decision, its reasons and the policy.
- **Document quality engine** (`docs/QUALITY.md`): IR-level checks for table overflow, image clipping,
  empty sections, header/footer, typography and unbreakable values, plus typed layout optimisation
  that writes a new immutable version and re-validates it. `POST /api/v1/templates/quality` and
  `POST /api/v1/templates/optimize`.
- **AX adapter interface** (`docs/adr/0009-ax-adapter-gate.md`): the capability matrix for Field,
  List, Image, Conditional, validator and integration harness, all `experimental`; the adapter raises
  `UnsupportedTargetError`. Compatibility stays `not_tested`.
- ADR-0007, ADR-0008, ADR-0009 and the documentation policy (link checks, ADR index, wiki mirror).
- `.env.example` with every supported variable, automatic `.env` loading and explicit
  `python-dotenv` dependency.
- Reviewer confirmation endpoint, demo sessions and the Streamlit demo.

### Fixed
- Company roles bind their own field: the logo no longer satisfies the address or VAT role.
- Preview renders borderless tables and page numbers correctly.
- Anthropic adapter: no deprecated `temperature`, fallback when a model rejects forced tool choice.
- OpenAI adapter: truncated output is reported as such instead of a JSON parse error.

### Changed
- Compilation is gated while a mapping still needs review.
- Mapping statuses are `confirmed`, `schema_valid`, `needs_review`, `conflict`, `missing`, `invalid`.

## [0.2.1] - toolchain update

Patch release with dependency updates only. No engine behaviour changed.

### Changed

- GitHub Actions updated to `checkout@v5`, `setup-python@v6`, `setup-node@v7`,
  `upload-artifact@v7`, `setup-buildx@v4`, `build-push@v7` and `action-gh-release@v3`.
- React and React DOM updated to 19.3.1, with matching type packages.
- Allowed `uvicorn <0.55` and `typer <0.28`; verified against Uvicorn 0.54.0 and Typer 0.27.3.

### Notes

- Major web upgrades (Next.js 16, ESLint 10, Tailwind 4, TypeScript 7) are deferred to a dedicated
  migration and declined as blind bumps; the reason is recorded on each Dependabot pull request and in
  the roadmap.

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
