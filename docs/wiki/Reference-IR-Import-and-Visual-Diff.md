# Safe IR import and visual diff (v0.11 P1)

> **Status: partial by design.** These features consume read-only reference evidence. They do not
> produce a native Docentric AX template, do not test a Docentric runtime and do not claim Word
> fidelity. `runtime_compatibility` remains `not_tested` and `target=docentric-ax` stays
> fail-closed.

This page summarises the v0.11 P1 reference workflow: D365 evidence in the graph, safe import into
Generic Template IR, an independent visual diff, and report persistence/reopen/export. The full
contract is in [Reference Templates](../REFERENCE_TEMPLATES.md#v011-p1--unified-graph-ir-import-visual-diff-and-persistence)
and [ADR-0016](../adr/0016-ir-import-and-visual-diff.md).

## 1. Unified D365 graph evidence (#26)

`build_reference_graph` can consume a D365 binding report or extract the embedded `ProjectData`
schema read-only from the original DOCX payload. `schema_field` nodes carry the provider
(`ddsp` or `d365_project_data`), source id and `part#xpath` evidence. `resolves_to` edges carry the
exact resolver status; only `resolved` is a resolved edge, while `unknown_path`, `type_mismatch`,
`schema_unavailable` and `unsupported_expression` remain explicit diagnostics.

The graph summary reports evidence coverage and unresolved counts by status. The Inspector Graph tab
shows the node origin, evidence location, edge resolution status and that status breakdown.

## 2. Safe Reference → Generic Template IR (#27)

Only this subset is imported:

| Reference | Generic IR |
| --- | --- |
| Field | `FieldBinding` |
| Label | `TextRun` |
| List | `Repeat` (confirmed collection only) |
| If | `Conditional` (boolean evidence only) |
| Image | `ImageBinding` (confirmed binary/image only) |

Everything else is returned in `skipped[]` with a code and reason. Strict mode refuses the import if
anything is skipped; `--allow-unsupported` keeps the supported subset and still lists every skip.
The produced Document is validated with the existing V1-V3 engine. The result carries
`runtime_compatibility: not_tested` and the target `generic-docx` only.

```bash
docentric-copilot reference import-ir template.docx --json .tools/import-ir.json
docentric-copilot reference import-ir template.docx --allow-unsupported \
  --json .tools/import-ir.json
```

```text
POST /api/v1/reference/import-ir
```

Partial: List→Repeat only (no Table inference); Group/SubDocument/Barcode/SummaryField and complex
expressions stay reference-only; labels are static text; provenance is a sidecar because Template
IR v1.0 is frozen.

## 3. Independent visual diff (#28)

Structural/semantic diff stays in `reference diff`. The visual report renders both references
through the existing LibreOffice path and compares page counts, blank pages, per-page ink/coverage
and shifted regions.

```bash
python scripts/reference_visual_diff.py before.docx after.docx --json out/report.json
docentric-copilot reference visual-diff before.docx after.docx --json out/report.json
```

The report is labelled **LibreOffice rendering (not Word fidelity)**, writes `report.json` plus a
safe `report.html`, and keeps structural/semantic statuses `not_compared`. If `soffice` or
`pdftoppm` is unavailable, the status is `renderer_unavailable` with a reason — never a pass or a
fail. CI has no LibreOffice, so the committed tests exercise the comparison and unavailable path
with a stub renderer.

## 4. Persistence, reopen and export (#29)

Reports are stored in local SQLite under the artifact TTL. The source template bytes are never
stored.

| Method | Path |
| --- | --- |
| `POST` | `/api/v1/reference/reports?kind=inspection\|graph\|diff` |
| `GET` | `/api/v1/reference/reports/{id}` |
| `GET` | `/api/v1/reference/reports/{id}/export?format=json\|html` |

The `/reference` page puts the last report id in `?id=`, reopens it through the API, handles absent
or invalid ids without crashing, and offers an **Export report** action (JSON or safe HTML).

Partial: single-process SQLite with TTL; no explicit delete/retention API and no committed
Playwright browser E2E.

## What remains unverified

- No Docentric AX runtime test, no native template output and no compatibility claim.
- The local 11-DOCX D365 corpus was not re-run for the graph in this branch; public tests are
  synthetic.
- Visual diff is not a Word layout validator; structural/semantic comparison remains separate.

## Related

- [Reference Templates, Diff & Eval](Reference-Templates)
- [CLI Reference](CLI-Reference)
- [API Reference](API-Reference)
- [Docentric AX Compatibility](Docentric-AX-Compatibility)
- [ADR-0016](../adr/0016-ir-import-and-visual-diff.md)
