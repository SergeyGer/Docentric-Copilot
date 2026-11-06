# Reference report retention and deletion (V012-09)

Reference reports are read-only evidence produced by the inspector. They contain
schema paths, control metadata, graph/diff payloads and the source file name and
SHA-256 — they **never** contain the source DOCX bytes, macros, raw provider
output or API keys. They still deserve a retention policy because schema paths
and template names can be commercially sensitive.

| Field | Value |
| --- | --- |
| Storage | SQLite `reference_reports` table in `DC_DATA_DIR/copilot.db` |
| Default report TTL | `86400` seconds (24 hours) |
| Setting | `DC_REFERENCE_REPORT_TTL_SECONDS` (minimum 60) |
| Artifact TTL | Separate: `DC_ARTIFACT_TTL_SECONDS` (default 3600) |
| Delete API | `DELETE /api/v1/reference/reports/{id}` → `204` |
| Expired/missing | `404` with `reference_report_not_found` |
| Purge | On access (expired row) and on the store's `purge_expired` sweep |
| Tests | `tests/integration/test_reference_persistence_api.py` |

## What is stored

| Stored | Not stored |
| --- | --- |
| Report id, kind, schema version | Source DOCX/ZIP/AXPP bytes |
| Created/expires timestamps | Macros or embedded objects |
| Source file name and SHA-256 | API keys or provider credentials |
| Serialized report and graph/diff JSON | Raw model prompts or completions |
| Warnings and bounded diagnostics | Customer sample data, unless it is already in the report payload |

The source name and schema evidence can identify a template. Treat the SQLite
file as internal evidence, not as a public artifact, and do not ship it in a
release or support bundle.

## Lifetime

```text
expires_at = created_at + reference_report_ttl_seconds
```

- The default is 24 hours for reports, deliberately longer than the one-hour
  artifact TTL because a saved report is review evidence.
- An invalid or expired id returns `404 reference_report_not_found`; an expired
  row is removed when it is accessed.
- `Store.purge_expired()` deletes expired report rows together with expired
  artifacts. The API exposes no public purge endpoint; the application calls the
  store sweep locally.
- There is no background scheduler in v0.12. Expired rows not accessed by
  anyone are cleaned by the next store sweep or by the explicit store call.

## Delete one report

```bash
curl -X DELETE http://127.0.0.1:8000/api/v1/reference/reports/ref_abc123
# HTTP 204, empty body
curl -i http://127.0.0.1:8000/api/v1/reference/reports/ref_abc123
# HTTP 404 {"error":{"code":"reference_report_not_found",...}}
```

Deletion is immediate and applies to the report payload. A second delete, a
missing id or an expired id returns the same stable `404` code. Export after
deletion returns `404`. The UI does not currently expose a delete button; the
API is the supported interface for v0.12.

## Backup and restore

- The database is a single SQLite file. Stop the API (or use SQLite's online
  backup API) before copying `copilot.db`; copying a live WAL connection is not
  a supported backup.
- Restoring an old file restores the reports that existed in it, including rows
  whose `expires_at` has passed. They are deleted on access; run a purge after a
  restore if immediate cleanup is required.
- The schema is created with `CREATE TABLE IF NOT EXISTS`; no migration tool is
  included for v0.12. A future schema change needs an explicit migration.
- Multi-process writers and production-scale storage are out of scope (P2).
  SQLite's single-process connection is intentional in this build.

## Limits and honest status

- No encryption at rest, no per-user authorization and no per-report retention
  override in v0.12.
- Deletion removes the row; SQLite file pages may retain deleted data until
  vacuumed. Use filesystem encryption or `VACUUM` when the threat model requires
  physical erasure.
- The policy is documented and tested; it is not a certified data-retention
  program. Legal retention requirements must be confirmed by the operator.
- Docentric AX runtime compatibility remains `not_tested`; this policy is about
  stored evidence, not template execution.

## Tests

- create → read → export → delete → verified not-found (GET and export);
- second delete and unknown id return `404`;
- the report TTL is independent from the artifact TTL;
- expired rows are removed by the store sweep;
- source template bytes are never written to the database.
