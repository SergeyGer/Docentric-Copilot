# Reference Templates

> **Static inspection only.** The inspector reads reference DOCX, ZIP, AXPP and DDSP packages. It
> never executes macros, Docentric Designer, X++ or AX output, and it always reports
> `runtime_compatibility: "not_tested"`.

## Why this exists

Generic DOCX is not the same thing as a Docentric AX template. Before writing an AX compiler, the
project needs reproducible evidence about the real reference material: archive structure, duplicate
payloads, content controls, ProjectData metadata, real DDSP schemas and bindings. The **Reference
Inspector** provides that evidence as a read-only report, a graph and a projection.

It implements REF-00 inventory/deduplication, REF-01 real DDSP schema evidence, REF-02 metadata
resolution, REF-03 ReferenceGraph/read-only Reference IR, REF-04 reference diff and REF-05
reference-based evaluation. The v0.10 P0 increment adds a D365 embedded-schema adapter and a
canonical binding resolver, so a document with an embedded `ProjectData` schema does not need a
standalone DDSP.

## What you can inspect

| Input | What is reported |
| --- | --- |
| `.docx` | Every content control across document, headers, footers and other story parts |
| `.zip` | Members, hashes, duplicates and nested archives up to the selected depth |
| `.axpp` | AXPP members with backslashes normalized to virtual `/` paths |
| Directory | The same manifest for every file, with duplicate groups |
| `.ddsp` | Real DDSP root/version/locales/labels, per-section fields, types, collections and unsupported constructs |
| Optional `.ddsp` with a DOCX | ValueBinding paths validated against the DDSP schema |
| D365 DOCX / single-template AXPP | Embedded `ProjectData` schema, field metadata, canonical binding statuses |

The report distinguishes:

- **recognized** — a known Docentric marker was found;
- **ambiguous** — markers conflict or a Docentric marker has no identifiable type;
- **unknown** — no recognizable Docentric marker; the control is preserved anyway;
- **resolved / missing_part / unknown_path / ambiguous** — metadata and path resolution outcomes.

Nothing is silently dropped. Unresolved controls stay in the report with part, paragraph, ordinal,
signed/unsigned id and diagnostic codes.

## Real DDSP evidence (REF-01)

The real adapter recognises `dsp:dataSourcePackage` by namespace and maps each data section to a
separate normalized section. XSD attributes become path-addressable `@Name` leaves; nested
repeating groups keep their collection flags; labels, locales, ProductVersion, sample values and
unsupported constructs are reported explicitly. Malformed XML, DTD/entity input and oversized or
deep documents are rejected by the shared safety layer.

`reference inspect ... --schema-report` prints the evidence. The same statistics are embedded in
`documents[*].schema_evidence` in the JSON report.

## D365 embedded schema (v0.10 P0)

D365 templates embed the schema in `customXml/itemN.xml` under Docentric `ProjectData`:
`DataSources/DataSource/Schema/XsdList/MainXsd` plus `PreviewData`. The adapter reads those parts
read-only and records the OOXML part, an XPath-like location and a source id for every fact. It also
reads the `Elements/Element/ValueBinding` facts so the canonical resolver can check source, path,
type and collection scope.

The document is classified as `schema_source = projectdata | ddsp | unavailable`. A supplied DDSP
is only a fallback; absence of a DDSP is not itself a failure.

### Binding statuses

| Status | Meaning |
| --- | --- |
| `resolved` | Exact source, path, scope and type verified; `source_id` + `part#xpath` evidence stored |
| `ambiguous` | Duplicate source/path or more than one admissible binding |
| `unknown_path` | Schema present, but path/source/scope absent or invalid in this context |
| `type_mismatch` | Path found, but declared result type or element role conflicts with the schema |
| `schema_unavailable` | Neither embedded schema nor a usable DDSP is present |
| `unsupported_expression` | Functions, comparisons, predicates, aggregates or unverified namespace prefixes |

Duplicates and conflicts are diagnostics, never `resolved`. Relative `Source="."` needs an enclosing
`List` with a resolvable collection binding. Every `resolved` result carries reproducible evidence,
so no success depends on similarity, a fuzzy match or an LLM call.

```bash
docentric-copilot reference d365 template.docx --json .tools/d365.json
docentric-copilot reference d365 template.docx --ddsp fallback.ddsp --json .tools/d365.json
```

```text
POST /api/v1/reference/d365
```

The endpoint accepts a multipart `file` (plus optional `ddsp`) or a confined `?path=`. A package
with several DOCX templates is rejected instead of partially analysed.

On the maintainer's local 11-document D365 corpus (counts only): 11/11 had embedded `projectdata`
schema evidence, 246 bindings were found, 233 resolved with full evidence, 4 were `unknown_path`,
8 `unsupported_expression`, 1 `type_mismatch`, 0 `ambiguous`, 0 `schema_unavailable`. Runtime
compatibility stays `not_tested`. See
[Reference Templates — D365](../REFERENCE_TEMPLATES.md#d365-embedded-schema-and-binding-resolution-v010-p0)
and [ADR-0013](../adr/0013-d365-embedded-schema-and-binding-resolution.md).

## ReferenceGraph and projection (REF-03)

The graph connects:

```
control --bound_to--> element --resolves_to--> schema_field
                         |  \
                         |   \--iterates / condition--> element
                         \--bound_to--> source (ProjectData part + data source)
```

Every node and edge is `resolved`, `ambiguous` or `unknown`. Lists, conditionals, sources and
schema fields become explicit; unknown paths and stale child references get placeholder nodes and a
reason; child-element cycles are cut with a diagnostic. The graph is sorted, timestamp-free and has
a `graph_digest`, so two runs over the same files are byte-identical.

`ReferenceDocument` is a separate read-only Reference IR. It groups controls into document sections
with display label, kind, binding path, status, source location and capability. It declares
`ir_kind: "reference"`, `compilable: false` and `template_ir_compatible: false`; it is not Template
IR 1.0. Import mode is not implemented, so `importable` is never emitted.

## Reference diff (REF-04)

`reference diff` compares two graphs with stable keys that do not contain the document SHA-256:
control, element, binding, source and schema-field items are reported as added, removed or changed,
with before/after snapshots (kind, binding path, status, part, paragraph, source, data type and
collection). Structural changes cover presence, parts and canonical counts; semantic changes cover
binding path, resolution status, element kind, source and type. The report also gives coverage and
unresolved deltas, status transitions and a deterministic `diff_digest`.

```bash
docentric-copilot reference diff left.docx right.docx --json .tools/diff.json
docentric-copilot reference diff older.docx newer.docx --ddsp schema.ddsp --json .tools/diff.json
```

`POST /api/v1/reference/diff` accepts two multipart files (`left`, `right`, optional shared `ddsp`)
or two corpus-confined `left_path`/`right_path` parameters.

## Reference-based evaluation (REF-05)

`benchmarks/reference_evaluation.py` maps reference controls to expected patterns (Field→scalar,
List→collection, If→condition, Image→image, Label→text) and scores a generated or supplied plan
with precision, recall, coverage, F1 and type/context correctness. `valid_template_rate` is reported
separately. The committed synthetic gold set has eight cases and 41 expected concepts; no Docentric
corpus content is used. `--reference PATH --ddsp PATH` evaluates against a real reference at runtime
and keeps the report private. The default `mock` provider makes no paid calls; a non-mock provider
requires `--allow-paid`.

The synthetic CI run gives precision 0.891, recall/coverage 1.000, type/context 1.000 and valid
template rate 1.000. Two local-corpus AX 2012 references were evaluated with counts only (22 and 39
concepts; recall 0.500 and 0.333); no paths or content are published. Real AX DDSP attribute paths
are normalized to IR-safe identifiers for evaluation only, with the normalization recorded in the
report.

## CLI

```bash
docentric-copilot reference inspect template.docx --json report.json
docentric-copilot reference inspect .tools/reference-corpus/examples/corpus \
  --max-depth 2 --json report.json
docentric-copilot reference inspect template.docx \
  --ddsp schema.ddsp --schema-report --json report.json
docentric-copilot reference graph template.docx \
  --ddsp schema.ddsp --json graph.json --projection reference.json
docentric-copilot reference diff left.docx right.docx --json diff.json
```

`--max-depth` is offline-only and capped at 3. Exit codes follow the normal CLI contract: `0`
success, `3` invalid input, `6` missing input.

## API

```
POST /api/v1/reference/inspect
POST /api/v1/reference/graph
POST /api/v1/reference/d365
POST /api/v1/reference/diff
```

Upload a multipart `file` (with optional `ddsp`), or use `?path=` inside a configured corpus root.
The D365 endpoint uses the same source rules.
The endpoints never execute or write the template. Public HTTP inspection defaults to
`max_depth=0`, so nested archives are recorded but not expanded.

```bash
curl -s -F "file=@template.docx" http://localhost:8000/api/v1/reference/inspect
curl -s -F "file=@template.docx" -F "ddsp=@template.ddsp" \
  http://localhost:8000/api/v1/reference/graph
curl -s -F "left=@left.docx" -F "right=@right.docx" \
  http://localhost:8000/api/v1/reference/diff
```

Corpus roots come from `DC_REFERENCE_CORPUS_ROOTS`. Paths are resolved and checked against those
roots; traversal and symlink escapes are rejected.

## Licensing and privacy

The official Docentric example archive is **not** in this repository. It may only be copied to the
git-ignored `.tools/reference-corpus/` directory. Public tests use synthetic fixtures generated by
test code, never the real corpus. Reports, graphs and projections from real templates can contain
business-shaped text and metadata; keep them private and do not commit them.

## v0.11 P1 workflow (partial)

The v0.11 P1 increment adds:

- **#26 D365 evidence in the unified ReferenceGraph**: `schema_field` nodes carry provider, source
  id and `part#xpath` evidence; `resolves_to` edges carry the exact resolver status, and the graph
  summary reports evidence coverage and unresolved statuses.
- **#27 safe Reference → Generic Template IR**: Field, Label, List→Repeat, If and Image only.
  Everything else is listed in `skipped[]`; strict mode refuses the import and
  `--allow-unsupported` keeps the supported subset without guessing.
- **#28 independent visual diff**: LibreOffice-rendered pages compared for page counts, blank
  pages, ink/coverage and shifted regions. Labelled **LibreOffice rendering (not Word fidelity)**;
  `renderer_unavailable` is never pass/fail.
- **#29 persistence/reopen/export**: local SQLite with the artifact TTL,
  `GET /api/v1/reference/reports/{id}`, JSON/HTML export and a `/reference?id=` reopen flow.

The detailed partial list is on
[Safe IR import and visual diff](Reference-IR-Import-and-Visual-Diff).

## What remains unverified

- The web inspector renders the report and graph, and can reopen/export a saved report; diff and
  evaluation panels remain Python/CLI/API-only. Licensed runtime testing (REF-07) remains out of
  scope.
- The REF-05 synthetic set is small and uses the deterministic mock; it is a pattern-regression
  fixture, not a model-quality claim.
- D365 documents without a standalone DDSP are checked by the D365 adapter and, from v0.11 P1, can
  contribute `resolves_to` edges directly; a standalone DDSP is still required for DDSP path
  validation. Expressions, aggregates and relative contexts without an enclosing `List` remain
  non-resolved and are listed explicitly.
- Docentric AX runtime behaviour and native output are not tested. `target=docentric-ax` remains
  fail-closed with HTTP `409`, and compatibility is still `not_tested`.

Full details: [Reference Template Intelligence](../REFERENCE_TEMPLATES.md) ·
[ADR-0013](../adr/0013-d365-embedded-schema-and-binding-resolution.md) ·
[ADR-0012](../adr/0012-reference-diff-and-evaluation.md) ·
[ADR-0011](../adr/0011-reference-graph.md) · [ADR-0010](../adr/0010-reference-inspector.md).
