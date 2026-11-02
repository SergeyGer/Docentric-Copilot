# Test Plan

| Field | Value |
| --- | --- |
| Scope | Python core, HTTP API, CLI, golden files, benchmarks, evaluation harness |
| Test runner | pytest 8 (config in [pyproject.toml](../pyproject.toml)) |
| Related | [SRS](SRS.md), [BENCHMARKS](BENCHMARKS.md), [EVALUATION](EVALUATION.md), [CONTRIBUTING](../CONTRIBUTING.md) |

## 1. Objectives

1. Demonstrate the requirements in [SRS](SRS.md) with executable evidence.
2. Protect the deterministic layers (parse, validate, compile) against regressions, including
   byte-level output stability where the contract requires it.
3. Prove that the compatibility gate cannot be bypassed.
4. Prove that hostile DDSP input is rejected with typed errors.
5. Provide a repeatable way to compare the mock baseline with hosted providers (evaluation).

The suite is intentionally **offline**: no test requires an API key or network access. Provider
adapters are tested with injected HTTP transports.

## 2. Test levels and inventory

| Level | Location | Purpose | Pass/fail |
| --- | --- | --- | --- |
| Unit | `tests/unit/` | Pure functions, models, parser, planner, validator, compiler, preview, LLM adapters with mocked transports, CLI via `typer.testing.CliRunner` | Yes |
| Integration | `tests/integration/test_api.py` | FastAPI app through `TestClient`: upload, plan, validate, compile, revise, preview, artifacts, errors | Yes |
| Golden | `tests/unit/test_golden_files.py` + `tests/golden_files/` | Frozen normalized IR/mapping/schema/validation/DOCX projections for eight synthetic fixtures | Yes |
| Edge cases | `tests/unit/test_edge_paths.py` | VAT conditional branch, missing data, malformed inputs, unusual-but-valid documents | Yes |
| Benchmarks | `benchmarks/run_benchmarks.py` | Latency measurement, not an assertion of correctness | No (informational; budgets displayed only) |
| Evaluation | `benchmarks/run_evaluation.py` | Planner quality metrics over the example fixtures | No (produces a report) |
| Web static checks | `apps/web` | `npm run lint`, `npm run typecheck`, `npm run build` | Yes (build must succeed) |
| Browser E2E | — | Manual Playwright/Chromium smoke run only; no committed suite | **Not automated** |
| Network | marker `network` | Tests that would call real providers | **Always skipped by policy** |

### 2.1 What each area covers

| Area | Representative assertions | Files |
| --- | --- | --- |
| Core | Error envelope shape and distinct codes, id format, canonical JSON key-order independence, nested `to_plain`, redaction of secret keys/values, JSON log one-object-per-line, settings defaults and secret-free public view | `tests/unit/test_core.py` |
| DDSP parsing | Quotation schema completeness, sample coercion, parse determinism, manifest `schema_id`, XSD-in-container, single XML/XSD input, inference from repeated values, mismatch diagnostics, DOCTYPE/entity rejection, file/entry/ratio/name/nested/encrypted limits, node/depth limits, malformed XML, unreadable ZIP | `tests/unit/test_ddsp_parser.py` |
| Schema and IR | Absolute/alias resolution, unknown path, object/collection type errors, context violation, collection resolution, type compatibility, candidate ranking, ambiguity, mapping validation, IR roundtrip/digest, unknown key/version, expression shape/depth | `tests/unit/test_schema_and_ir.py` |
| Traversal | Block/expression iteration, inline bindings, table cells, counts/depth | `tests/unit/test_traversal_and_misc.py` |
| Planner | Baseline document structure (heading/table/conditional/image/footer), role discovery, invoice and purchase-order fixtures, baseline determinism, mapping completeness, every binding resolves, sanitizer removal and reporting, repair hints, revisions/diff, prompt assembly | `tests/unit/test_planner.py` |
| Validator and compiler | Five-level statuses, V5 never `passed`, unknown binding blocks compilation, collection context, format/type mismatch, boolean comparison, repeat-on-scalar, table-width warning, V4 skip without data, package required entries/macros, duplicate sections, byte-identical output, content, logo embedding, package validity, deterministic core properties, placeholder mode, conditional branch, invalid image placeholder, AX gate | `tests/unit/test_validator_and_compiler.py` |
| Preview and LLM | Rendering values, HTML escaping, placeholders without data, conditionals, inline logo, landscape, JSON extraction (bare/fenced/prose/invalid), Gemini schema conversion, cost estimate, OpenAI retry/error/missing key/budget, Anthropic tool use, Gemini text JSON, gateway behaviour | `tests/unit/test_preview_and_llm.py` |
| Golden | Eight fixtures × schema, IR, mapping, validation and normalized DOCX projections | `tests/unit/test_golden_files.py` |
| Edge paths | VAT conditional, missing data, unusual documents | `tests/unit/test_edge_paths.py` |
| CLI | Version, inspect text/JSON, missing file exit code, invalid file exit code, full pipeline, AX target rejection, missing prompt file, providers listing, IR schema output, invalid IR | `tests/unit/test_cli.py` |
| API | Health/root, OpenAPI availability, providers, capabilities honesty, upload + schema, extension rejection, hostile XML, unknown source envelope, request-validation shape, full flow, revision flow, AX 409, artifact view sandboxing, missing artifact, unknown provider | `tests/integration/test_api.py` |

Counts are deliberately not frozen here: the suite is growing. Use
`pytest --collect-only -q` for the current inventory.

## 3. How to run

### 3.1 Make targets (recommended)

```bash
make install-dev     # virtualenv + editable install with dev extras
make test            # pytest
make test-cov        # pytest with branch coverage and --cov-fail-under=85
make lint            # ruff check + ruff format --check
make typecheck       # mypy packages services
make ci              # lint + typecheck + test-cov
make bench           # benchmarks/run_benchmarks.py --runs 100
make eval            # benchmarks/run_evaluation.py (mock baseline)
make openapi         # writes docs/openapi.json
```

`make` is a developer convenience only; every target is a thin wrapper around the raw commands
below.

### 3.2 Raw commands

```bash
python -m pytest                                   # all tests
python -m pytest -q tests/unit                     # unit tests only
python -m pytest tests/integration -q              # API integration
python -m pytest -k golden -q                      # golden fixtures
python -m pytest -m "not slow" -q                  # exclude slow marker
python -m pytest --cov=docentric_copilot \
  --cov-report=term-missing --cov-fail-under=85
ruff check . && ruff format --check .
mypy packages services
```

Pytest configuration:

- `testpaths = ["tests"]`, `addopts = "-q --strict-markers"` — an unknown marker fails the run.
- Markers: `slow`, `e2e`, `network` (network tests must be skipped, not silently attempted).
- `filterwarnings = ["error::DeprecationWarning:docentric_copilot.*"]` — deprecations in our own code
  fail the suite.

### 3.3 Web app

`apps/web/package.json` exposes `dev`, `build`, `start`, `lint` and `typecheck`; there is **no `test`
script** and no committed browser E2E suite, so `npm test` is not available. The verified checks are:

```bash
cd apps/web
npm ci
npm run lint          # no warnings
npm run typecheck     # TypeScript strict, clean
npm run build         # static `/` route, ~145 kB first-load JS
npm start             # serves on port 3000; HTTP 200 checked
```

A manual real-browser smoke run (Playwright/Chromium against a live API) exercised upload → schema tree
→ plan → preview → compile/download → revision → version load at 1024 px with zero console errors. The
scripts, browser binaries and screenshots were temporary and are **not** committed; this is evidence of
a one-off verification, not a regression test. Browser E2E and responsive checks below 1024 px remain
open (see §7).

### 3.4 Docker

Both images build and run:

- `docker build -t docentric-copilot-api:0.2.0 .` → API image (multi-stage, non-root, healthcheck on
  `/health`); built and run, `/health` returned `{"status":"ok","version":"0.2.0"}`.
- `docker build -t docentric-copilot-web:0.2.0 apps/web` → frontend image (`node:22-alpine`,
  non-root uid 10001, healthcheck on port 3000); built and run, `GET /` returned HTTP 200.

`docker-compose.yml` validates and defines an `api` service on 8000 and a `web` service on 3000.
A full `docker compose up --build` could not be completed inside the development container because its
Docker/Buildx setup denied a Bake path; the two images and the compose configuration were verified
separately. Docker is not part of `make ci`; CI builds both images.

## 4. Coverage

### 4.1 Targets

| Scope | Target | Enforcement |
| --- | --- | --- |
| Deterministic core (parser, resolver, IR, validator, compiler, llm, planner, preview) | **≥ 85% branch coverage** | `make test-cov` uses `--cov-fail-under=85`; CI is expected to run the same gate |
| API, CLI, storage, evaluation | Not counted in the coverage number | Excluded via `[tool.coverage.run].omit`; exercised by their own tests |
| Golden files | Not coverage-relevant | Presence and exact match asserted |
| Benchmarks/evaluation | Not coverage-relevant | Produce reports |

Coverage configuration uses `branch = true` and omits `*/tests/*`, `*/api/*`, `*/cli/*`,
`*/evaluation/*`, `*/storage/*`. Excluding the interface and storage layers keeps the number focused
on logic that can be unit tested; it does **not** mean those layers are untested.

Current measured coverage (one local run, Python 3.12.3): **86.23%** across the counted modules,
with 189 collected tests passing and the 85% gate satisfied. The weakest measured modules were
`ddsp_parser/xsd.py` (~61%), `docx_compiler/formatting.py` (~75%) and
`llm/providers.py` (~82%). These numbers are a snapshot, not a target: re-run `make test-cov` and
quote the result with the commit when reporting coverage. A coverage number without the command and
commit is not evidence.

### 4.2 Reporting

```bash
make test-cov          # prints term-missing and writes coverage.xml
```

Attach the summary line to a PR when coverage changes materially. Do not lower the gate without an
ADR-level justification.

## 5. Golden files

Golden fixtures live in `tests/golden_files/expected/<fixture>/` with five projections:

| File | Content |
| --- | --- |
| `schema.json` | Normalized schema (canonical JSON) |
| `ir.json` | Template IR (canonical JSON) |
| `mapping.json` | Mapping report |
| `validation.json` | Validation report |
| `docx.json` | Normalized DOCX projection: paragraphs, tables, header, footer, media list, package summary, page geometry, core properties |

The DOCX projection deliberately ignores ZIP timestamps, relationship ids and other structural noise;
byte-identical compilation is asserted separately in the compiler tests. Golden comparison is therefore
stricter about *content* and stable across environments.

Regenerate after an intentional change:

```bash
python -m tests.golden_files.update_golden
git diff tests/golden_files/expected    # review every change before committing
```

`update_golden --check` reports stale files without writing. Fixtures are authored in
`tests/golden_files/fixtures.py` and are synthetic; never add third-party or customer data.

## 6. Determinism and test isolation

- Tests never call the network. Provider adapters use `httpx.MockTransport`.
- `tests/conftest.py` sets `DC_DATA_DIR` to a per-test temporary directory, clears the settings cache
  before and after each test, and lowers the log level.
- The `mock` provider is the only planner used by default; it performs no I/O.
- Golden and compiler tests assert identical bytes/projections across runs; a clock or randomness
  regression will fail them.
- Tests must not depend on execution order; no shared mutable state is used intentionally.

## 7. What is not covered

| Gap | Risk | Mitigation / plan |
| --- | --- | --- |
| Real-world DDSP packages | Parser may not handle unknown layouts | Add fixtures when a permitted package is available; [DDSP_COMPATIBILITY §10](DDSP_COMPATIBILITY.md#10-adding-fixtures-how-to-extend-coverage) |
| Live OpenAI/Anthropic/Gemini calls | Adapter drift from provider APIs; auth/rate-limit behaviour | Adapters are contract-tested with mocked transports; no live call has been recorded. Verification needs credentials and the protocol in [EVALUATION §4](EVALUATION.md#4-mock-baseline-vs-llm-comparison) |
| Microsoft Word rendering | DOCX may look different in Word | Out of scope; V4 is partial and the preview explicitly disclaims layout fidelity |
| Docentric AX | Compatibility unverified | Gate: [DOCENTRIC_AX_COMPATIBILITY](DOCENTRIC_AX_COMPATIBILITY.md) |
| Browser E2E and responsive UI | Web regressions, layouts below 1024 px | Add a committed Playwright suite and viewport checks, and run them in CI; a manual smoke run is not regression coverage |
| Real-LLM UI flows | UI may handle provider errors/usage poorly | Only the mock provider was exercised in the browser; add provider-error state tests when credentials exist |
| Concurrency and load | Race conditions, SQLite contention, latency under load | Add a load test; see [NFR-08](SRS.md#nfr-08--concurrency-and-scalability) |
| Fuzzing / property-based testing | Parser edge cases beyond hand-written cases | Add Hypothesis campaigns for XML and path parsing |
| Security scanning | Dependency and static analysis findings | `pip-audit` and `bandit` run in CI; container image scanning is not configured |
| IR migration | Migration code paths | Only version 1.0 exists; add migration tests with the first migration |
| Large documents | Performance cliffs, memory | Add large-fixture benchmarks with explicit budgets |
| Locale-specific formatting | Non-English expectations | Locale support is out of MVP scope |
| Windows/macOS | Path handling differences | CI matrix planned; paths use `pathlib` |
| PDF/print fidelity | Not generated | Out of scope |

## 8. Benchmark and evaluation runs

These are **not** pass/fail tests and must not be used as correctness evidence:

```bash
make bench                                   # 100 runs per example, writes benchmarks/results.json
make eval                                    # mock baseline, writes benchmarks/evaluation.json
python benchmarks/run_benchmarks.py --runs 20 --provider openai --model gpt-4o-mini  # optional, needs key
python benchmarks/run_evaluation.py --provider anthropic --model claude-3-5-haiku   # optional, needs key
```

`benchmarks/results.json` now holds a 100-run mock measurement (commit `059b1bb`); the numbers are
environment-specific and the aggregate is computed over per-example p95 values. See
[BENCHMARKS](BENCHMARKS.md) and [EVALUATION](EVALUATION.md).

## 9. CI

`make ci` (`lint`, `typecheck`, `test-cov`) is the authoritative local gate.
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs the same Python checks on 3.12 plus:

- examples reproducibility (`scripts/build_examples.py --check`);
- golden-file freshness (`tests.golden_files.update_golden --check`);
- OpenAPI freshness (regenerate and `git diff --exit-code docs/openapi.json`);
- web: `npm ci`, `npm run lint`, `npm run typecheck`, `npm run build`;
- docker: build the API and web images;
- security: `bandit` (medium+) and `pip-audit`.

All jobs are expected to pass on the committed tree; a Docker engine is required for the docker job. A
change is not ready for review until `make ci` passes locally and the documentation obligations in
[CONTRIBUTING](../CONTRIBUTING.md) are met.

## 10. Adding tests

1. Prefer a failing test that reproduces the requirement or bug, then the fix.
2. Use synthetic fixtures only; regenerate deterministically and review binary diffs.
3. Assert on typed errors and their codes, not on message text alone.
4. For compiler changes, assert byte-identical output for the same IR/sample data and update golden
   projections only when the change is intended.
5. For parser changes, add one hostile variant alongside every new supported construct.
6. Never mark a test `network` to make it pass; network-dependent tests must be skipped by design.
7. Keep tests fast: unit tests should run in milliseconds; mark genuinely slow tests `slow` and explain
   why in the test docstring.
8. Do not weaken the compatibility gate tests. A PR that makes `docentric-ax` compile must also provide
   the evidence required by [DOCENTRIC_AX_COMPATIBILITY §7](DOCENTRIC_AX_COMPATIBILITY.md#7-evidence-required-to-change-the-status).
