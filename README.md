# Docentric Copilot

**Schema-aware template engineering for enterprise document automation.**

Docentric Copilot turns a natural-language requirement plus a DDSP data source package into a
versioned, typed **Template IR**, validates that IR at five levels, and compiles a deterministic
**generic DOCX** document — without Microsoft Word, a Docentric Designer session or a Dynamics 365
environment.

> **Compatibility status: unverified.** This build produces *generic* DOCX documents. It does not
> claim, and must not be read as claiming, compatibility with Docentric AX. The Docentric AX adapter
> is gated and always fails closed (`target_unsupported`, HTTP 409, exit code 4); the validation
> report always records Docentric AX compatibility as `not_tested`. See
> [docs/DOCENTRIC_AX_COMPATIBILITY.md](docs/DOCENTRIC_AX_COMPATIBILITY.md).

---

## The problem

Business documents (quotations, invoices, purchase orders) are usually produced from a typed data
package by a template that is maintained by hand in a graphical designer. Three things go wrong
repeatedly:

1. **Bindings drift from the schema.** A template references a field that the data source no longer
   exposes; nobody notices until a customer receives a broken document.
2. **Templates are opaque.** The artefact is a binary document, so review, diffing and automated
   testing are hard.
3. **AI-generated templates are unaccountable.** A model can produce plausible-looking bindings
   that do not exist, and a document that renders without error is not the same as a document that
   is correct.

## The solution

The project implements a narrow, testable pipeline around one contract — the Template IR:

- **Evidence-based DDSP ingestion.** A DDSP package is parsed as untrusted input (ZIP + XML) with
  hard size, entry, depth and node limits, no DTD/entity processing and no network access. The
  parser records *what it saw* instead of guessing a proprietary layout.
- **Typed intermediate representation.** Every dynamic value is a dotted schema path that the
  validator can resolve. There is no XPath, no code, no raw OOXML in the IR.
- **Deterministic repair.** Whatever a planner produces is post-processed: a binding that does not
  resolve against the schema is removed and reported, never "fixed" by guesswork.
- **Five validation levels.** V1 structural, V2 semantic, V3 logical, V4 visual and V5
  compatibility. `not_tested` is a first-class status and is not an alias for `passed`.
- **Deterministic compilation.** The same IR and sample data always produce a byte-identical DOCX
  package: fixed ZIP timestamps, sorted entries, fixed core properties, no clock and no randomness.
- **Provider-independent planning.** OpenAI, Anthropic and Gemini adapters share one structured
  output contract, plus a deterministic `mock` baseline that needs no API key.

## Status

MVP under active development (version `0.1.0`, Template IR `1.0`). Honest summary:

| Area | State |
| --- | --- |
| DDSP parsing, schema discovery, sample-data extraction | Implemented; exercised only on synthetic packages under `examples/` |
| Template IR + canonical JSON/digest + JSON Schema export | Implemented |
| Deterministic baseline planner (`mock`) | Implemented |
| LLM gateway (OpenAI, Anthropic, Gemini) | Implemented; **no live provider call has been recorded in this repository** |
| Validation V1–V3 | Implemented |
| Validation V4 (visual) | Partial: table-width check only, and only when sample data is supplied |
| Validation V5 (Docentric AX compatibility) | Not implemented; always `not_tested` |
| Generic DOCX compiler | Implemented; byte-identical output verified by repeated runs |
| Docentric AX compiler | Not implemented; gated and fails closed |
| HTML preview | Implemented; content preview only, not a Word-faithful layout |
| HTTP API, CLI, SQLite storage, artifact TTL | Implemented |
| Evaluation harness (`docentric_copilot.evaluation`) | Implemented: metric definitions plus `benchmarks/run_evaluation.py`; only the mock baseline has been measured |
| Benchmarks | Implemented runner (`benchmarks/run_benchmarks.py`); numbers are environment-specific and not an SLO |
| Web UI (`apps/web`) | Implemented and verified: Next.js 15 workspace; `lint`, `typecheck` and `build` pass, and a manual real-browser smoke run passed. No browser E2E suite is committed |
| Docker image (API) | Builds and passes its `/health` check; multi-stage, non-root |
| Docker image (web) | Builds and serves HTTP 200 on port 3000 (`node:22-alpine`, non-root, healthcheck) |
| Makefile and GitHub workflows | Present (`make test`, `make ci`, `make bench`, `make eval`, `make openapi`, …; CI: python, web, docker, security) |

The precise mapping of requirements to code and tests is in [docs/SRS.md](docs/SRS.md).

## Architecture

```mermaid
flowchart LR
  REQ[Requirement text] --> PLAN
  DDSP[DDSP package or XML] --> PARSE[ddsp_parser<br/>safe container + XML ingest]
  PARSE --> SCHEMA[NormalizedSchema]
  SCHEMA --> RESOLVE[schema_resolver<br/>path resolution + candidate search]
  SCHEMA --> PLAN[planner<br/>mock baseline or LLM gateway]
  RESOLVE --> PLAN
  PLAN --> IR[Template IR v1.0<br/>canonical JSON + digest]
  IR --> VALIDATE[template_validator<br/>V1 structural / V2 semantic / V3 logical<br/>V4 visual / V5 compatibility]
  VALIDATE -->|V1-V3 pass| COMPILE[docx_compiler<br/>generic-docx]
  IR --> PREVIEW[preview renderer<br/>independent HTML]
  COMPILE --> DOCX[DOCX package<br/>deterministic bytes]
  VALIDATE --> REPORT[Validation report<br/>JSON + HTML]
  DOCX --> STORE[(SQLite metadata<br/>TTL artifacts)]
  REPORT --> STORE
  PREVIEW --> STORE
```

Layer boundaries, package responsibilities and the determinism strategy are described in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Quick start

### Local (supported)

Requires Python 3.12+.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

docentric-copilot version
# docentric-copilot 0.1.0 (IR 1.0)
```

Start the API (the only optional dependency for the demo is the mock provider, which is always
available):

```bash
uvicorn docentric_copilot.api.main:app --reload --port 8000
```

Interactive OpenAPI UI: <http://localhost:8000/docs>. OpenAPI document: `/openapi.json`.

```bash
curl -s http://localhost:8000/api/v1/health
# {"status":"ok","version":"0.1.0","environment":"development","docentric_ax_adapter_enabled":false}
```

Runtime data (SQLite database and artifacts) is written to `DC_DATA_DIR` (`./.data` by default).
Artifacts expire after `DC_ARTIFACT_TTL_SECONDS` (3600 by default); sources older than the TTL are
removed at startup; template versions and job records are retained until the database is deleted.

### Web UI

The frontend is a Next.js 15 single-page workspace in `apps/web` (React 19, TypeScript strict,
Tailwind). It drives the same API: upload a DDSP package, browse and copy schema paths, write the
requirement, review the mapping and validation report, inspect the sandboxed HTML preview, compile the
DOCX, and load or revise template versions.

```bash
cd apps/web
npm ci
npm run dev          # http://localhost:3000
```

Node 22+ is required. The API must be running at `http://localhost:8000`; the browser uses
`NEXT_PUBLIC_API_BASE_URL` (default `http://localhost:8000`, no trailing slash), which is inlined at
build time. The API's default CORS origin is `http://localhost:3000`. A production build is
`npm run build && npm start` (port 3000 by default).

The UI is English-only. The HTML preview is displayed in a sandboxed iframe (`sandbox=""`, scripts
disabled), and the `not_tested` compatibility status is shown distinctly from `passed`. A manual
real-browser smoke run covered upload → schema → plan → preview → compile → revision; no browser test
suite is committed (see [docs/TEST_PLAN.md](docs/TEST_PLAN.md) and
[apps/web/README.md](apps/web/README.md) for panel-level details).

### Docker

The API image is a multi-stage build on `python:3.12-slim` that runs as an unprivileged user and
declares a healthcheck on `/health`:

```bash
docker build -t docentric-copilot-api:0.1.0 .
docker run --rm -p 8000:8000 \
  -v docentric-data:/data \
  docentric-copilot-api:0.1.0

curl -s http://localhost:8000/health
# {"status":"ok","version":"0.1.0"}
```

`docker-compose.yml` defines an `api` service (port 8000, `DC_DATA_DIR=/data`, named volume,
healthcheck) and a `web` service (port 3000, depends on the API being healthy). Both images build:
the API image above and the frontend image at `apps/web/Dockerfile` (`node:22-alpine`, non-root,
healthcheck on port 3000). `docker compose config` validates; both images were built and run
individually during development (API `/health`, web HTTP 200).

```bash
docker compose up --build -d
# API:  http://localhost:8000
# Web:  http://localhost:3000
```

A full `docker compose up` could not be completed inside the development container because Docker
Compose's Bake path was denied by that environment; the images and compose configuration were
verified separately. The frontend bakes `NEXT_PUBLIC_API_BASE_URL` at build time (default
`http://localhost:8000`); set the build argument if the browser reaches the API at a different URL.

The image sets `DC_DATA_DIR=/data`, which the named volume preserves across container restarts; the
TTL still applies to artifacts. Provider credentials are passed as environment variables and are never
baked into the image; see [docs/API_SPEC.md](docs/API_SPEC.md) and
[docs/THREAT_MODEL.md](docs/THREAT_MODEL.md).

## End-to-end example (quotation)

The repository ships three synthetic packages. `examples/quotation/sales-quotation.ddsp` is a ZIP
containing `manifest.json`, `schema/schema.xsd` and `data/sample.xml`; it contains no third-party or
customer data (see [examples/quotation/README.md](examples/quotation/README.md)).

```bash
mkdir -p out

# 1. Inspect: discover sections, fields, collections and sample data.
docentric-copilot inspect examples/quotation/sales-quotation.ddsp
# Schema: sales_quotation
# Sections: MainData, GeneralData, Parameters
# Fields: 34 nodes · 28 scalars · 1 collections · depth 3
# Sample data: yes
#   [INFO002] info: ZIP container with 3 entries
#   [INFO002] info: Manifest detected: docentric-ax-ddsp (manifest.json)
#   [INFO002] info: Sample data loaded from 'data/sample.xml'

# 2. Plan: requirement -> Template IR (mock baseline; no credentials needed).
docentric-copilot plan \
  --ddsp examples/quotation/sales-quotation.ddsp \
  --prompt-file examples/quotation/prompt.txt \
  --output out/plan.json \
  --mapping out/mapping.json

# 3. Validate: V1-V5 report for the IR.
docentric-copilot validate \
  --ddsp examples/quotation/sales-quotation.ddsp \
  --plan out/plan.json \
  --report out/validation.html \
  --json-report out/validation.json

# 4. Compile: deterministic generic DOCX (no model calls).
docentric-copilot compile \
  --ddsp examples/quotation/sales-quotation.ddsp \
  --plan out/plan.json \
  --output out/quotation.docx

# 5. Optional: independent HTML preview of the data substitution.
docentric-copilot preview \
  --ddsp examples/quotation/sales-quotation.ddsp \
  --plan out/plan.json \
  --output out/preview.html
```

Observed output of step 2 (this build, mock provider):

```text
IR written to out/plan.json (9f8d8ad173de)
Validation: {'structural': 'passed', 'semantic': 'passed', 'logical': 'passed',
             'visual': 'skipped', 'docentric_compatibility': 'not_tested'}
Mapping: {'resolved': 11, 'ambiguous': 0, 'missing': 0, 'invalid': 0}
```

Observed output of step 4:

```text
Compiled out/quotation.docx (39749 bytes)
Validation: {'structural': 'passed', 'semantic': 'passed', 'logical': 'passed',
             'visual': 'passed', 'docentric_compatibility': 'not_tested'}
Docentric AX compatibility: not tested
```

The IR digest and the exact byte count are reproducible for a given compiler version; they change
when the IR or the compiler changes, so treat them as a fingerprint of *this* build rather than a
constant.

To see the compatibility gate in action:

```bash
docentric-copilot compile \
  --ddsp examples/quotation/sales-quotation.ddsp \
  --plan out/plan.json \
  --output out/quotation-ax.docx \
  --target docentric-ax
# error [target_unsupported]: The Docentric AX compiler is not available: ...
# exit code 4
```

The same request over HTTP returns `409` with error code `target_unsupported` (see
[docs/API_SPEC.md](docs/API_SPEC.md)).

## Feature matrix

| Capability | State | Where |
| --- | --- | --- |
| DDSP ZIP container ingestion with limits | Implemented | `packages/ddsp-parser/src/docentric_copilot/ddsp_parser/safety.py` |
| XSD → normalized schema | Implemented | `packages/ddsp-parser/src/docentric_copilot/ddsp_parser/xsd.py` |
| Schema inference from sample XML (`SCHEMA006`) | Implemented | `packages/ddsp-parser/src/docentric_copilot/ddsp_parser/sampledata.py` |
| Sample-data coercion by schema type | Implemented | `packages/ddsp-parser/src/docentric_copilot/ddsp_parser/sampledata.py` |
| Path resolution with repeat-alias scoping | Implemented | `packages/schema-resolver/src/docentric_copilot/schema_resolver/paths.py` |
| Deterministic candidate search / baseline mapping | Implemented | `packages/schema-resolver/src/docentric_copilot/schema_resolver/search.py` |
| Template IR v1.0 + canonical JSON + digest | Implemented | `packages/template-ir/src/docentric_copilot/template_ir/canonical.py` |
| LLM gateway: OpenAI / Anthropic / Gemini / mock | Implemented; live calls unverified | `packages/llm-gateway/src/docentric_copilot/llm/` |
| Deterministic mock planner | Implemented | `packages/planner/src/docentric_copilot/planner/heuristic.py` |
| Deterministic repair of unresolvable bindings | Implemented | `packages/planner/src/docentric_copilot/planner/service.py` |
| Revision diff between IR versions | Implemented | `packages/planner/src/docentric_copilot/planner/revisions.py` |
| V1 structural / V2 semantic / V3 logical validation | Implemented | `packages/template-validator/src/docentric_copilot/template_validator/engine.py` |
| V4 visual validation (table width) | Partial (needs sample data) | same file |
| V5 Docentric AX compatibility | **Not tested** | same file |
| Generic DOCX compiler | Implemented | `packages/docx-compiler/src/docentric_copilot/docx_compiler/generic.py` |
| Deterministic ZIP normalisation | Implemented | `packages/docx-compiler/src/docentric_copilot/docx_compiler/package.py` |
| HTML preview | Implemented (content only) | `packages/renderer/src/docentric_copilot/preview/renderer.py` |
| HTTP API | Implemented | `services/api/src/docentric_copilot/api/` |
| CLI | Implemented | `services/api/src/docentric_copilot/cli/main.py` |
| SQLite storage + artifact TTL | Implemented | `services/api/src/docentric_copilot/storage/store.py` |
| Planner evaluation metrics | Implemented (mock baseline measured) | `packages/evaluation/src/docentric_copilot/evaluation/metrics.py` |
| Latency benchmark runner | Implemented (environment-specific results) | `benchmarks/run_benchmarks.py` |
| Makefile developer workflow | Implemented | `Makefile` |
| CI: lint, types, coverage, reproducibility, OpenAPI, security | Implemented, including both Docker images and the web build | `.github/workflows/ci.yml` |
| Docker image for the API | Implemented; build and `/health` verified | `Dockerfile` |
| Docker image for the web app | Implemented; build and HTTP 200 verified | `apps/web/Dockerfile` |
| PDF export | Not implemented | — |
| Docentric AX compiler | Blocked / not implemented | `packages/docx-compiler/src/docentric_copilot/docx_compiler/generic.py` |
| Web UI (Next.js 15 workspace) | Implemented; manual browser smoke verified, no committed E2E suite | `apps/web/` |
| Authentication / multi-tenancy | Not implemented | — |

## Compatibility matrix

| Target | Compiler available | Compatibility claimed | Evidence |
| --- | --- | --- | --- |
| `generic-docx` (plain OOXML) | Yes | OOXML structure only; not opened in Microsoft Word by the test suite | `inspect_package()` checks required entries, macros, embedded objects, external relationships |
| `docentric-ax` | No | **None** — unverified | Always raises `UnsupportedTargetError`; V5 report status `not_tested` |

The word "verified" appears in the `/api/v1/capabilities` payload with a narrow meaning: it states
whether that compiler target is implemented and internally checked (`generic-docx`), not whether the
output is compatible with any third-party product. For `docentric-ax` both `available` and `verified`
are `false`.

## Project structure

One distribution, several source roots. Each package directory owns exactly one subpackage of the
`docentric_copilot` namespace (configured in [pyproject.toml](pyproject.toml)).

```text
packages/
  core/             docentric_copilot          config, errors, ids, logging, serialization
  ddsp-parser/      docentric_copilot.ddsp_parser
  schema-resolver/  docentric_copilot.schema_resolver
  template-ir/      docentric_copilot.template_ir
  template-validator/ docentric_copilot.template_validator
  docx-compiler/    docentric_copilot.docx_compiler
  llm-gateway/      docentric_copilot.llm
  planner/          docentric_copilot.planner
  renderer/         docentric_copilot.preview
  evaluation/       docentric_copilot.evaluation   (metrics + evaluation harness)
services/
  api/              docentric_copilot.app / .api / .cli / .storage
examples/           synthetic DDSP packages: quotation, invoice, purchase-order
scripts/            build_examples.py (deterministic example generator)
tests/              pytest suite (see docs/TEST_PLAN.md)
apps/web/           Next.js 15 frontend workspace (npm; port 3000)
docs/               product, architecture, API, security and planning documents
```

## Testing and measurement

```bash
make install-dev        # virtualenv + editable install with dev extras
make test               # pytest
make test-cov           # branch coverage with an 85% gate
make lint               # ruff check + ruff format --check
make typecheck          # mypy packages services
make ci                 # lint + typecheck + test-cov (also run by .github/workflows/ci.yml)

make bench              # benchmarks/run_benchmarks.py --runs 100
make eval               # benchmarks/run_evaluation.py (mock baseline)
```

Raw commands are equivalent: `pytest`, `pytest --cov=docentric_copilot`, `ruff check .`,
`mypy packages services`. At the time of writing the suite contains 189 tests and measures 86.23% branch
coverage on the counted modules; the exact numbers change as tests are added, so run the commands
rather than quoting this paragraph.

Markers declared in [pyproject.toml](pyproject.toml): `slow`, `e2e`, `network` (network tests are
expected to be skipped; no test may depend on a real provider).

The web workspace has `lint`, `typecheck` and `build` scripts but **no `test` script**, so `npm test`
is not available; run the individual scripts:

```bash
cd apps/web && npm ci && npm run lint && npm run typecheck && npm run build
```

The frontend was verified with `npm run lint`, `npm run typecheck` and `npm run build`, and a manual
real-browser smoke run (upload, plan, preview, compile, revise) against the live API. That smoke run is
not committed and is not reproducible in CI; there is **no committed Playwright suite**. Browser
end-to-end coverage and layouts below 1024 px remain open (see
[docs/TEST_PLAN.md](docs/TEST_PLAN.md)).

What is and is not covered is listed in [docs/TEST_PLAN.md](docs/TEST_PLAN.md); benchmark results are
in [docs/BENCHMARKS.md](docs/BENCHMARKS.md) and planner metrics in [docs/EVALUATION.md](docs/EVALUATION.md).

## Documentation

| Document | Purpose |
| --- | --- |
| [docs/PRD.md](docs/PRD.md) | Problem, personas, scope, principles, success metrics |
| [docs/SRS.md](docs/SRS.md) | FR-01…FR-10 and NFR-01…NFR-12 with status and evidence |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Layers, data flow, package boundaries, determinism |
| [docs/TEMPLATE_IR.md](docs/TEMPLATE_IR.md) | Every IR entity and field, path/alias/expression/format semantics |
| [docs/API_SPEC.md](docs/API_SPEC.md) | Endpoints, error envelope, artifact lifecycle |
| [docs/DDSP_COMPATIBILITY.md](docs/DDSP_COMPATIBILITY.md) | What is known and unknown about DDSP, diagnostics, limits |
| [docs/DOCENTRIC_AX_COMPATIBILITY.md](docs/DOCENTRIC_AX_COMPATIBILITY.md) | The compatibility gate and explicit non-claims |
| [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) | Assets, actors, threats, mitigations, residual risk |
| [docs/TEST_PLAN.md](docs/TEST_PLAN.md) | Test matrix, how to run, coverage |
| [docs/EVALUATION.md](docs/EVALUATION.md) | Metric definitions, the harness and the baseline/LLM comparison protocol |
| [docs/BENCHMARKS.md](docs/BENCHMARKS.md) | Benchmark methodology, 100-run results and interpretation rules |
| [docs/FEASIBILITY.md](docs/FEASIBILITY.md) | M0 findings and the recorded compatibility decision |
| [docs/ROADMAP.md](docs/ROADMAP.md) | M0–M5 milestones, next steps, blocked items |
| [docs/adr/](docs/adr/) | Architecture decision records |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Development workflow and Definition of Done |
| [SECURITY.md](SECURITY.md) | Vulnerability reporting and supported versions |

## Licence

Apache License 2.0 — see [LICENSE](LICENSE).

## Independence disclaimer

This project is independent. It is **not** affiliated with, endorsed by, sponsored by or supported
by Docentric or Microsoft. "Docentric", "Microsoft", "Dynamics 365" and "Word" are trademarks of
their respective owners and are used here only to describe interoperability questions. No
third-party Docentric asset, template or customer data is included; every example package under
`examples/` is synthetic and generated by
[scripts/build_examples.py](scripts/build_examples.py).
