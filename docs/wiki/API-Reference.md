# API Reference

> REST API v1 · OpenAPI 3.1 · base URL `http://localhost:8000`

The interactive contract is served at [`/docs`](http://localhost:8000/docs) and the machine-readable
document at [`/openapi.json`](http://localhost:8000/openapi.json). A snapshot is committed as
[`docs/openapi.json`](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/openapi.json).

## Endpoint overview

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/sources` | Upload a DDSP package (multipart) |
| `GET` | `/api/v1/sources/{id}/schema` | Normalized schema for a source |
| `POST` | `/api/v1/templates/plan` | Brief → validated Template IR |
| `POST` | `/api/v1/templates/validate` | Validate an IR (V1–V5) |
| `POST` | `/api/v1/templates/compile` | IR → DOCX artifact |
| `POST` | `/api/v1/templates/revise` | New IR version from an instruction |
| `POST` | `/api/v1/templates/preview` | HTML preview |
| `GET` | `/api/v1/templates/{id}/versions` | Version history |
| `GET` | `/api/v1/templates/{id}/export/{version}` | Export a version's IR and reports |
| `GET` | `/api/v1/jobs/{id}` | Job record |
| `GET` | `/api/v1/artifacts/{id}` | Download an artifact |
| `GET` | `/api/v1/artifacts/{id}/view` | Inline view for HTML artifacts |
| `GET` | `/api/v1/providers` | Provider catalogue and configuration state |
| `GET` | `/api/v1/capabilities` | Compilers, features and limits |
| `GET` | `/api/v1/health` | Service health |

## Error envelope

Every expected failure uses one shape:

```json
{
  "error": {
    "code": "validation_failed",
    "message": "The template failed validation",
    "details": { "validation": { "semantic": "failed" } }
  }
}
```

| HTTP | Code | Meaning |
| --- | --- | --- |
| 400 | `input_invalid`, `security_violation`, `XML001` | Malformed or hostile input |
| 404 | `not_found` | Unknown source, template or job |
| 409 | `target_unsupported` | Gated Docentric AX target |
| 410 | `artifact_unavailable` | Artifact expired or missing |
| 415 | `input_unsupported` | Wrong file type |
| 422 | `validation_failed` | Validation rejected the plan |
| 502/503 | `provider_error`, `provider_not_configured` | LLM provider problems |

## Typical flow

### 1. Upload

```bash
curl -s -F "file=@examples/quotation/sales-quotation.ddsp" \
  http://localhost:8000/api/v1/sources
```

```json
{
  "source_id": "src_1mxsqvj9cxf4lm3qoav2",
  "schema_id": "sales_quotation",
  "sections": ["MainData", "GeneralData", "Parameters"],
  "stats": { "node_count": 34, "scalar_count": 28, "collection_count": 1, "max_depth": 3 },
  "sample_data_available": true,
  "diagnostics": [{ "code": "INFO002", "severity": "info", "message": "ZIP container with 3 entries" }]
}
```

### 2. Plan

```bash
curl -s -X POST http://localhost:8000/api/v1/templates/plan \
  -H "Content-Type: application/json" \
  -d '{"source_id":"src_…","prompt":"Create a professional sales quotation","provider":"mock"}'
```

Response highlights:

```json
{
  "job_id": "job_…",
  "template_id": "tpl_…",
  "version": 1,
  "ir_digest": "9f8d8ad1…",
  "validation": {
    "structural": "passed", "semantic": "passed", "logical": "passed",
    "visual": "passed", "docentric_compatibility": "not_tested"
  },
  "artifacts": [{ "kind": "ir", "url": "/api/v1/artifacts/art_…" }]
}
```

`templates/plan` writes a version, publishes artifacts and records a job. It is synchronous; the job record
exists for auditability.

### 3. Compile

```bash
curl -s -X POST http://localhost:8000/api/v1/templates/compile \
  -H "Content-Type: application/json" \
  -d '{"source_id":"src_…","template_id":"tpl_…","options":{"document_name":"quotation.docx"}}'
```

Then `GET /api/v1/artifacts/{artifact_id}` returns the DOCX with
`Content-Disposition: attachment`, `X-Content-Type-Options: nosniff` and `X-Artifact-Digest` (SHA-256 of the
served bytes).

### 4. Revise

```bash
curl -s -X POST http://localhost:8000/api/v1/templates/revise \
  -H "Content-Type: application/json" \
  -d '{"source_id":"src_…","template_id":"tpl_…","instruction":"Move bank details to the footer."}'
```

Returns `version: 2`, a structural `change_summary` and the new artifact bundle. The previous version stays
exportable.

## Request options worth knowing

| Field | Default | Effect |
| --- | --- | --- |
| `provider` | `mock` | `mock`, `openai`, `anthropic`, `gemini` |
| `model` | provider default | Model identifier |
| `design_style` | `modern` | `modern`, `classic`, `minimal` |
| `target` | `generic-docx` | `docentric-ax` is gated and returns 409 |
| `options.strict_validation` | `true` | Reject plans that fail V1–V3 |
| `options.max_generation_cost_usd` | `0.50` | Pre-flight budget ceiling |
| `options.max_repair_attempts` | `1` | Automatic repair attempts on invalid output |

## Artifact lifecycle

| Property | Value |
| --- | --- |
| TTL | `DC_ARTIFACT_TTL_SECONDS` (3600 by default) |
| Storage | Local file store, metadata in SQLite |
| Download | `attachment` disposition, digest header |
| Inline view | HTML only (`/view`), otherwise `415` |
| Cleanup | Expired artifacts removed on startup and on access |

## Rate limits and size limits

| Limit | Default | Variable |
| --- | --- | --- |
| Upload size | 10 MB | `DC_MAX_DDSP_BYTES` |
| Uncompressed content | 64 MB | `DC_MAX_UNCOMPRESSED_BYTES` |
| ZIP entries | 512 | `DC_MAX_ZIP_ENTRIES` |
| Schema nodes | 5,000 | `DC_MAX_SCHEMA_NODES` |
| IR blocks | 5,000 | `DC_MAX_IR_BLOCKS` |

No application-level rate limiting is implemented in the MVP; put the API behind your gateway if it is
exposed beyond localhost.
