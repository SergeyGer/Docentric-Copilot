# Security & Threat Model

> Untrusted input, an external model and generated files: three trust boundaries, each with a named control.

## Assets

| Asset | Why it matters |
| --- | --- |
| DDSP contents and sample data | May contain customer and personal data |
| LLM API keys | Financial and reputational impact if leaked |
| Generated documents and IR | Business deliverables and audit evidence |
| Artifact storage | Shared filesystem, TTL-bound |
| Provider budget | Cost abuse |

## Threats and controls

| # | Threat | Control |
| --- | --- | --- |
| T-01 | XML External Entity (XXE) | `DOCTYPE`/`ENTITY` rejected (`XML001`); `resolve_entities=False`, `no_network=True`, `load_dtd=False` |
| T-02 | ZIP bomb / decompression bomb | ratio, entry-count, uncompressed-size and per-entry read caps |
| T-03 | Path traversal in entries | absolute paths, `..`, backslashes and control characters rejected |
| T-04 | Nested archive smuggling | archives inside a DDSP rejected (`DDSP009`) |
| T-05 | XML depth / node exhaustion | depth and node limits enforced while walking |
| T-06 | Prompt injection in data | instruction/data fences; the system prompt declares fenced content as data; the IR is still validated deterministically |
| T-07 | Hallucinated fields | deterministic repair plus V2 semantic validation; unknown fields cannot reach the compiler |
| T-08 | Key leakage in logs | structured logging with key-value redaction; keys never logged or returned |
| T-09 | PII sent to an LLM | explicit provider selection; minimal schema fragment; sample values not sent by default |
| T-10 | Malicious image payloads | magic-byte checks, size cap, decode failure degrades to a placeholder |
| T-11 | Macro / OLE payload in output | package inspection rejects macros and embedded objects (V1) |
| T-12 | Artifact enumeration | opaque ids, TTL, no directory listing |
| T-13 | Unsafe download handling | `attachment` disposition, `nosniff`, digest header |
| T-14 | XSS via API strings | React escaping, sandboxed iframe for preview HTML, no `dangerouslySetInnerHTML` in the workspace |

## Data minimisation

- Only a compact schema fragment (paths, types, flags) is sent to the model — no sample values.
- Documents and IRs live in a local SQLite database and file store with a TTL.
- Provider cost is bounded by a per-request pre-flight budget and a global cap.

## Residual risks (accepted, tracked)

| ID | Risk | Severity | Note |
| --- | --- | --- | --- |
| R-04 | HTML artifact `/view` has no CSP | Medium | Served with `nosniff`; add a CSP when object storage is introduced |
| R-13 | No strict CSP in the Next.js app | Low–Medium | Baseline headers set; nonce plumbing required for a strict policy |
| R-14 | No authentication / multi-tenancy | Medium | The MVP assumes a trusted local deployment |
| R-15 | LLM output quality is model-dependent | Medium | Mitigated by validation, but not eliminated |

## Deployment guidance

- Run behind a reverse proxy with TLS and authentication before exposing it.
- Keep `DC_CORS_ORIGINS` narrow.
- Set `DC_ARTIFACT_TTL_SECONDS` to the shortest value that supports your workflow.
- Provide provider keys through the platform secret store, never via images or repository files.

## Reporting a vulnerability

Please do not open a public issue. Follow [SECURITY.md](https://github.com/SergeyGer/Docentric-Copilot/blob/main/SECURITY.md):
report privately with a reproduction and impact description; you will receive an acknowledgement and a
coordinated disclosure timeline.
