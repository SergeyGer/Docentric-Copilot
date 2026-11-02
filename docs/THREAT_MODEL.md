# Threat Model

| Field | Value |
| --- | --- |
| System | Docentric Copilot 0.3.0 (API, CLI, Next.js web workspace, SQLite, local artifacts) |
| Method | Asset/actor inventory, trust boundaries, STRIDE-oriented threat table, residual-risk register |
| Related | [SECURITY.md](../SECURITY.md), [SRS NFR-02…NFR-06](SRS.md#3-non-functional-requirements), [DDSP_COMPATIBILITY](DDSP_COMPATIBILITY.md) |

## 1. Scope and assumptions

This model covers the Python service and its web client in this repository: DDSP ingestion, planning
with hosted providers, validation, DOCX compilation, preview, the HTTP API, the CLI, local storage and
the Next.js workspace in `apps/web`.

Assumptions that materially affect the analysis:

1. **The service is not internet-facing by default.** It ships with no authentication and is intended
   for a trusted network or a single operator workstation. Exposing it publicly is a deployment error,
   not a supported configuration.
2. **DDSP packages and requirement text are attacker-controlled.** They may be malicious, oversized,
   or crafted to influence a model.
3. **The model provider is an external processor.** Prompt content leaves the deployment when a hosted
   provider is used. The mock provider never leaves the process.
4. **The host is trusted.** An attacker with code execution on the host is out of scope; so is a
   malicious operator who can change environment variables or the database.
5. **No multi-tenancy.** One deployment serves one data directory; cross-tenant isolation is not
   implemented.
6. **The browser is assumed to run the shipped frontend code**, not an attacker-modified copy. XSS and
   iframe escape are still considered, because API data reaches the DOM and the preview HTML is
   rendered in the browser.

## 2. Assets

| Asset | Why it matters | Where it lives |
| --- | --- | --- |
| DDSP package bytes | May contain customer business data and personal data | Uploaded over HTTP; held in memory; normalised schema and sample data in SQLite |
| Normalized schema and sample data | Business structure and values; may include PII | `sources.schema_json`, `sources.sample_json` |
| Requirement text | Business intent; may contain PII pasted by a user | Request body, IR `metadata.intent`, job `request_json` |
| Template IR and mapping | Authoritative description of the document; review evidence | `versions` table, IR/mapping artifacts |
| Generated DOCX and reports | Customer-facing output | Artifact directory, TTL |
| Provider API keys | Grant billable access to external models | Environment only; never persisted |
| Service availability | Denial of service blocks document production | Process, SQLite, disk |
| Compatibility claim integrity | A false claim causes customer harm | Documentation, capability/validation payloads |
| Browser-rendered content | Preview HTML and API data are displayed in the user's browser | `apps/web` sandboxed iframe, React-rendered text |
| Frontend build configuration | `NEXT_PUBLIC_API_BASE_URL` decides where browser data is sent | Build-time environment variable, Docker build arg |

## 3. Actors

| Actor | Capability | Motivation |
| --- | --- | --- |
| External uploader | Can submit arbitrary DDSP bytes and prompts | Data exfiltration, DoS, prompt injection |
| Malicious document author | Controls XML content and field names | Inject instructions or hostile structure |
| Mistaken internal user | Pastes sensitive text into a prompt | Accidental disclosure |
| Model provider | Sees prompt content, returns text | Compromise, logging, retention (outside our control) |
| Operator | Configures env vars, data directory, CORS | Misconfiguration |
| Network attacker | Intercepts traffic if TLS is absent | Credential/data theft |
| Supply-chain attacker | Compromises a Python dependency | Code execution, data theft |

## 4. Trust boundaries

```text
[untrusted]                          [boundary 1: HTTP]            [trusted process]
  DDSP bytes, requirement  ─────────▶  FastAPI validation  ───────▶  ddsp_parser / planner
                                                                        │
[boundary 2: model]  prompt ──────────────────────────────────────────▶│ hosted provider
                     response (untrusted) ◀─────────────────────────────┘
                                                                        │
[boundary 3: filesystem]  IR / DOCX / reports ────────────────────────▶│ SQLite + artifacts
                                                                        │
[boundary 4: browser]  HTML preview / artifact view ◀───────────────────┘
```

1. **HTTP boundary** — bytes and JSON enter; only `CopilotError` mappings and typed responses leave.
2. **Model boundary** — prompts leave the process; model output is treated as untrusted input and
   validated against the IR.
3. **Filesystem boundary** — artifacts are written under a generated id; input is never extracted to
   disk.
4. **Browser boundary** — the Next.js workspace renders API JSON and embeds the HTML preview in a
   sandboxed iframe; HTML artifacts are also served directly. Escaping, sandboxing and CSP matter.

## 5. Threats and mitigations

Legend: **S** spoofing, **T** tampering, **R** repudiation, **I** information disclosure, **D** denial
of service, **E** elevation of privilege.

### 5.1 Untrusted input parsing

| ID | STRIDE | Threat | Mitigation | Code | Residual |
| --- | --- | --- | --- | --- | --- |
| T-01 | I/E | XXE: external entity reads local files or makes network calls | Reject any `<!DOCTYPE` / `<!ENTITY` by pattern before parsing; parser has `resolve_entities=False`, `no_network=True`, `load_dtd=False`, `dtd_validation=False`, `huge_tree=False`, `recover=False` | `ddsp_parser/safety.py` | None known for lxml with these flags; pattern is case-insensitive |
| T-02 | D | ZIP bomb / decompression bomb | Input ≤ 10 MiB; declared and actual uncompressed ≤ 64 MiB; per-entry ratio ≤ 120; entry count ≤ 512; shared decompression budget while reading | `safety.py`, `config.Limits` | A crafted archive within all limits can still consume up to 64 MiB per request |
| T-03 | T/E | Zip-slip / path traversal through entry names | Absolute paths, `..`, backslashes, NUL/control characters and names > 300 chars rejected; entries never written to disk | `safety._safe_entry_name`, `read_container` | None known |
| T-04 | D/E | Nested archive or encrypted payload hides a second-stage attack | Nested archive suffixes rejected (`DDSP009`); encrypted entries rejected (`DDSP006`) | `safety.read_container` | A renamed archive (no suffix) would be treated as data and fail XML parsing, not be executed |
| T-05 | D | Deep or wide XML exhausts CPU/memory | `max_xml_nodes` (250k), `max_xml_depth` (64), iterative traversal | `safety.enforce_tree_limits` | lxml's own memory use up to the node cap |
| T-06 | D | Malformed XML crashes the worker | `recover=False`; `XMLSyntaxError` → typed `InvalidInputError`; secondary documents skipped | `safety.parse_xml`, `parser.parse_ddsp` | A parser bug could still surface as `500 internal_error` (no details leaked) |
| T-07 | D | Pathological XSD recursion / huge schema | Recursion detection, depth 32, schema node budget 5,000, `SCHEMA004`/`SCHEMA005` | `ddsp_parser/xsd.py` | Legal but large schemas truncate silently after the diagnostic |
| T-08 | D | Huge upload before parsing | Route reads `limit + 1` bytes and rejects oversize; parser re-checks | `api/routes/sources.py`, `safety.check_file_size` | The route still buffers up to the limit in memory per concurrent request |

### 5.2 Prompt and model boundary

| ID | STRIDE | Threat | Mitigation | Code | Residual |
| --- | --- | --- | --- | --- | --- |
| T-09 | T | Prompt injection: requirement or field names instruct the model to ignore rules, exfiltrate data or invent fields | Requirement and schema are fenced (`<requirement>`, `<schema>`); system prompt states fenced content is data; output must validate against an `extra="forbid"` IR; deterministic sanitiser removes unresolvable references; validator blocks compilation | `planner/prompt.py`, `planner/service.py`, `template_validator/engine.py` | A model can still produce misleading but schema-valid content; no measured injection evaluation exists |
| T-10 | I | PII or confidential business data sent to a third-party provider | Prompts contain schema paths, types, flags and the requirement text only; sample values are excluded by `compact_fragment`; message content is never logged | `ddsp_parser/models.py::compact_fragment`, `planner/prompt.py`, `llm/models.py` | Requirement text is sent verbatim; users can paste PII. No redaction or DLP exists |
| T-11 | I | Provider stores/retains prompts | Deployment choice of provider and contract; no code control | — | Outside the project's control |
| T-12 | I | Provider error echoes sensitive text into API error details | Provider response body truncated to 400 chars and returned as `details.reason`; no prompt content is included by the code | `llm/providers.py::_truncate` | A provider that echoes the prompt in its error body could leak a fragment to the caller |
| T-13 | T | Model returns malformed or unsafe JSON | Structured output requested; JSON extraction; pydantic validation; schema violation → `provider_invalid_output`; planner repair attempt bounded | `llm/gateway.py`, `llm/providers.py` | Model output that is valid IR but semantically poor is a product-quality risk, handled by validation and review |
| T-14 | D | Cost/DoS via expensive generations | Timeout 60 s, retries ≤ 5 (default 2), worst-case budget pre-flight (default $0.50), request size caps | `config.py`, `llm/providers.py` | Unknown models are unpriced, so budget pre-flight does not apply; an authenticated deployment would need quotas |
| T-15 | E | SSRF via user-controlled provider URL | Base URLs come from environment configuration only; no user-supplied URL is fetched | `config._build_providers` | A malicious operator can point a provider at an internal host; operators are trusted |
| T-16 | I | API key leakage through logs, API or errors | Keys live only in `ProviderSettings`; `public_view` and `describe` omit them; logger redacts secret-looking keys and token patterns; CLI never prints them | `config.py`, `logging.py`, `llm/gateway.py` | A key could appear in a provider URL/error not covered by the redaction patterns |

### 5.3 Artifacts and output

| ID | STRIDE | Threat | Mitigation | Code | Residual |
| --- | --- | --- | --- | --- | --- |
| T-17 | T/E | Compiled file contains macros, OLE/ActiveX or external relationships | The compiler emits none; `inspect_package` checks required entries, `vbaproject.bin`, `oleobject`/`activex`, and `TargetMode="External"`; V1-006…V1-009 report findings | `docx_compiler/package.py`, `generic.py`, `template_validator/engine.py` | Inspection is name/relationship-based, not a full OOXML security scanner |
| T-18 | T | Malicious image payload | Base64/`data:` only; 5 MiB cap; PNG/JPEG/GIF/BMP magic bytes required; decoding failures become placeholders | `generic._decode_image` | Decoder (Pillow via python-docx) vulnerabilities remain a dependency risk |
| T-19 | I | Artifact enumeration | Ids are 20 random base36 characters after the prefix (≈103 bits); TTL; expired ids return `410` | `core/ids.py`, `storage/store.py` | There is no authentication: anyone who obtains a URL can download until TTL |
| T-20 | I | Sample data exposed in artifacts | Preview HTML and DOCX contain rendered sample values by design; artifacts expire; download sets `no-store` | `storage/store.py`, `routes/system.py` | Files remain on disk until TTL purge; backups may retain them |
| T-21 | I | Stored data persists beyond expectations | Source rows older than TTL are purged at startup; artifacts deleted on expiry/read | `storage/store.py::purge_expired` | Versions and jobs do not expire; database removal is manual |
| T-22 | T | Path traversal via document name | Artifact path uses a generated id plus the filename suffix only; the original name is metadata | `storage/store.py::save_artifact` | Content-Disposition filename handling is delegated to Starlette |
| T-23 | I | SQL injection | All queries use parameter binding; no string interpolation of user data | `storage/store.py` | None known |
| T-24 | I/X | HTML injection in preview/report (XSS) | User text is HTML-escaped; images limited to validated data URIs; report Jinja environment has autoescaping; preview route sends `nosniff` + restrictive CSP | `preview/renderer.py`, `template_validator/report.py`, `api/routes/templates.py` | The artifact `/view` endpoint serves saved HTML **without** CSP; `data:image/svg+xml` is accepted by the preview image check without content inspection |
| T-25 | I | Artifact `/view` returns arbitrary artifact bytes as HTML | Only `text/html` artifacts are inlined; everything else returns `415` | `routes/system.py::view_artifact` | HTML artifacts contain data-derived content; TTL and unguessable ids are the only access control |

### 5.4 Service and deployment

| ID | STRIDE | Threat | Mitigation | Code | Residual |
| --- | --- | --- | --- | --- | --- |
| T-26 | S/E | No authentication: anyone can use the API | Not implemented; documented as out of scope; CORS restricted to configured origins | `api/app.py`, README, [SRS FR-09](SRS.md) | Critical if deployed publicly; deployment must enforce network policy |
| T-27 | T | CORS misconfiguration | Explicit origin list, methods and headers; credentials disabled | `api/app.py` | `DC_CORS_ORIGINS` can be widened by an operator |
| T-28 | R | No per-user audit trail | Jobs record request/result, not an authenticated actor | `storage/store.py` | Non-repudiation is not provided |
| T-29 | D | Concurrent requests exhaust SQLite/CPU | Single connection + lock; CPU work in threadpool | `storage/store.py`, `routes/templates.py` | No rate limiting, no queue, no backpressure |
| T-30 | D | Disk exhaustion via artifacts | TTL purge; no per-deployment quota | `storage/store.py` | A burst of large compilations can fill the disk before expiry |
| T-31 | I | Secrets in environment visible to process listing? | Keys are environment variables, standard for containers | — | Host-level access is out of scope |
| T-32 | E | Supply-chain compromise (dependency) | Constrained version ranges in `pyproject.toml`; `bandit` and `pip-audit` run in CI | `pyproject.toml`, `.github/workflows/ci.yml` | No Python lockfile is committed and transitive dependencies are not vendored |
| T-33 | I | Unencrypted transport | No TLS in the app; must be terminated by a proxy | — | Credentials and documents travel in clear text without a TLS proxy |
| T-34 | T | Malicious validation-report HTML | Jinja autoescape for `.html`/`.j2`; findings messages contain paths, not raw values | `template_validator/report.py` | Messages may include user-supplied field names; escaping covers markup |

### 5.5 Web client

| ID | STRIDE | Threat | Mitigation | Code | Residual |
| --- | --- | --- | --- | --- | --- |
| T-35 | I/X | XSS: API-provided strings (schema paths, mapping text, validation messages, preview HTML) rendered in the workspace | React escapes text by default; no `dangerouslySetInnerHTML` is used in `apps/web/src`; the HTML preview is shown in a sandboxed iframe (`sandbox=""`) instead of the parent DOM | `apps/web/src/components/workspace/preview-panel.tsx`, `apps/web/src/lib/api.ts` | `next.config.ts` sets baseline headers (nosniff, same-origin framing, referrer and permissions policy) but not a Content-Security-Policy; a future unsafe HTML sink would not be contained by CSP |
| T-36 | X/E | Preview iframe escapes the sandbox or executes script | `sandbox=""` disables scripts, forms, same-origin access, top navigation and downloads inside the frame | preview panel | Relies on browser sandbox correctness; the API's CSP applies when the preview URL is opened directly, not to `srcdoc` content inside the workspace |
| T-37 | I | Misconfigured `NEXT_PUBLIC_API_BASE_URL` sends DDSP data and prompts to an unintended API | Value is set at build time by the operator; the default is `http://localhost:8000`; compose passes `http://localhost:8000` explicitly | `apps/web/src/lib/api.ts`, `apps/web/Dockerfile` | A malicious or careless build configuration is a deployment risk; the browser cannot detect a hostile API |
| T-38 | S/T | Cross-site request abuse against the unauthenticated API | The API has no cookies or credentials and CORS allows only configured origins; browser `fetch` responses are unreadable cross-origin | `api/app.py`, `apps/web/src/lib/api.ts` | Requests can still be sent (no CSRF token, no auth); the impact is limited to consuming the unauthenticated service, which lacks quotas |
| T-39 | T | Downloaded DOCX/report opened by the user contains active content | The compiler emits no macros or embedded objects and the API inspects packages; the frontend only triggers a download | `docx_compiler/package.py`, web download handler | The consumer application (Word/browser) is outside this project's control |
| T-40 | D | Frontend unavailable when the API or its own build is broken | Static Next.js build; API health is surfaced in the UI; container healthcheck on port 3000 | `apps/web/Dockerfile`, workspace components | No offline mode; no service worker; API outage blocks the workspace |

## 6. STRIDE summary

| STRIDE | Main exposure | Strongest controls | Weakest point |
| --- | --- | --- | --- |
| Spoofing | No authentication | Unguessable ids; CORS | No identity at all |
| Tampering | Uploaded DDSP/IR, model output | Typed validation, deterministic sanitiser, package inspection | Model output quality |
| Repudiation | No actor identity | Job records | No authenticated audit trail |
| Information disclosure | PII in prompts/artifacts; key leakage; browser rendering | Data minimisation, redaction, TTL, `no-store`, sandboxed preview | Requirement text verbatim to provider; artifact URLs are bearer tokens; no CSP on the frontend or the HTML artifact view |
| Denial of service | Large inputs, expensive generations | Size/depth/node/time limits, budget | No rate limiting/quotas |
| Elevation of privilege | Prompt injection, parser exploits, browser sandbox escape | Fenced prompts, no code execution, hardened XML, `sandbox=""` preview | Third-party parser/decoder vulnerabilities; browser sandbox relies on browser correctness |

## 7. Residual risk register

| ID | Residual risk | Severity | Next step |
| --- | --- | --- | --- |
| R-01 | API has no authentication or authorisation | High if exposed | Deploy behind an authenticating proxy; implement auth before any shared deployment |
| R-02 | Requirement text is sent verbatim to hosted providers | Medium | Add PII detection/redaction and a provider-selection policy; document data-processing terms |
| R-03 | Prompt injection can influence content (not schema validity) | Medium | Build an injection evaluation suite; add server-side content constraints where possible |
| R-04 | HTML artifact `/view` lacks a Content-Security-Policy | Medium | Add the same CSP/nosniff protections as the preview route; consider serving artifacts as attachments only |
| R-05 | Preview accepts `data:image/svg+xml` without inspection | Low–Medium | Restrict allowed image media types to raster formats and re-validate at render time |
| R-06 | Artifact URLs are bearer capabilities until TTL | Medium | Shorten TTL, add signed URLs or authenticated download |
| R-07 | No quotas/rate limits, single-process SQLite | Medium | Add a reverse-proxy limit and a job queue before multi-user use |
| R-08 | No committed Python lockfile; audit depends on the resolver at CI time | Medium | Add a lockfile and image/dependency scanning (see ROADMAP) |
| R-09 | No TLS inside the app | Medium | Terminate TLS at a trusted proxy; document the requirement |
| R-10 | Image/XML decoder vulnerabilities | Low | Track dependency advisories; keep parsers current |
| R-11 | Versions and jobs never expire | Low | Add retention policy and deletion API |
| R-12 | No independent security review | Medium | Commission a review before production use |
| R-13 | No Content-Security-Policy in the Next.js app | Low-Medium | `next.config.ts` now sets `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` and `Permissions-Policy`; a strict CSP needs nonce plumbing through the App Router |
| R-14 | No committed browser E2E or accessibility tests | Medium | Commit Playwright tests (including sandbox and error states) and an accessibility check |

## 8. Security-relevant tests

| Area | Test file |
| --- | --- |
| DOCTYPE/entity rejection, unsafe names, nested archives, encrypted entries, size/ratio/node/depth limits | [tests/unit/test_ddsp_parser.py](../tests/unit/test_ddsp_parser.py) |
| Error envelope, redaction, secret-free settings view | [tests/unit/test_core.py](../tests/unit/test_core.py) |
| Preview escaping, image handling | [tests/unit/test_preview_and_llm.py](../tests/unit/test_preview_and_llm.py) |
| Macro/OLE/external-relationship detection, package validity | [tests/unit/test_validator_and_compiler.py](../tests/unit/test_validator_and_compiler.py) |
| Hostile upload over HTTP, artifact view sandboxing, error shapes | [tests/integration/test_api.py](../tests/integration/test_api.py) |
| UI manual smoke (not committed) | Playwright/Chromium run: upload, plan, preview, compile, revise, version load; zero console errors — no committed file |
| Frontend static checks | `npm run lint`, `npm run typecheck`, `npm run build` (in `apps/web`) |

These tests demonstrate specific controls. They are not a penetration test and do not cover the
residual risks above.

## 9. Out of scope

- Host compromise, container escape and hypervisor attacks.
- Provider-side security, retention and model behaviour.
- Denial of service by a legitimate authenticated user with quotas removed.
- Cryptographic design: digests are fingerprints, not signatures; there is no signing, encryption at
  rest or key management.
- Multi-tenant isolation, regulatory certification (GDPR/SOC 2) and data-residency guarantees.
- Docentric AX compatibility as a security property: it is unverified (see
  [DOCENTRIC_AX_COMPATIBILITY](DOCENTRIC_AX_COMPATIBILITY.md)).
- Browser, extension and operating-system compromise on the client; a user running attacker-controlled
  JavaScript outside the shipped frontend is out of scope.
- Frontend supply-chain compromise beyond the standard dependency review; no SBOM or signature
  verification is shipped.
