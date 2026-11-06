# Feature coverage — v0.13

> Systematic audit of the official Docentric examples that are already present locally.
> Counts are aggregate only; no private document name, path or payload is published.
> GitHub Issues is the source of truth for follow-up work.

## Corpus accounting

| Metric | Count |
| --- | ---: |
| AX 2012 official examples | 6 |
| D365FO official entries | 11 |
| Unique DOCX payloads (SHA-256) | 17 |
| DOCX artifacts | 63 |
| All artifacts | 249 |
| Distinct artifacts | 70 |
| Duplicate groups / occurrences | 37 / 179 |
| Content controls | 672 |
| Resolved / unknown controls | 650 / 22 |
| Header / footer controls | 74 / 122 |

The table scan covered 9 parsed payloads and observed 17 tables, 32 rows and 1 nested table. It is a presence check, not a proof that every table in the archive is representable.

## Matrix

| Docentric feature | Present | Parsing | ReferenceGraph | Template IR | DOCX Compiler | Validation |
| --- | ---: | --- | --- | --- | --- | --- |
| Field / ValueBinding | 534 | Supported | Supported | Supported | Supported | Supported |
| List / Repeat | 26 | Supported | Supported | Supported | Supported | Supported |
| Nested Collections | 4 | Supported | Partial | Supported | Supported | Supported |
| If / Else | 28 | Supported | Supported | Supported | Supported | Supported |
| Images | 14 | Supported | Supported | Supported | Supported | Supported |
| Image Collections | 0 | Partial | Partial | Supported | Supported | Partial |
| Tables | 17 | Partial | Unsupported | Supported | Supported | Supported |
| Repeated Table Rows | 8 | Partial | Unsupported | Supported | Supported | Supported |
| Nested Tables | 1 | Partial | Unsupported | Supported | Supported | Supported |
| SubDocuments | 3 | Supported | Supported | Unsupported | Unsupported | Not Tested |
| Groups | 1 | Supported | Supported | Unsupported | Unsupported | Not Tested |
| Barcode | 15 | Supported | Supported | Unsupported | Unsupported | Not Tested |
| SummaryField | 9 | Supported | Supported | Unsupported | Unsupported | Not Tested |
| Headers / Footers | 196 | Supported | Supported | Supported | Supported | Supported |
| Multiple DataSources | 1 | Supported | Supported | Partial | Supported | Supported |

Supported means a regression test exists for the claimed level. Partial means the construct is represented but a listed limitation remains. Unsupported means the importer/compiler deliberately refuses the construct and lists it in `skipped[]`; it is never silently dropped.

## Evidence by feature

### Field / ValueBinding

Status: Parsing `supported`, ReferenceGraph `supported`, Template IR `supported`, DOCX Compiler `supported`, Validation `supported`.

Evidence: `tests/unit/test_schema_and_ir.py`, `tests/unit/test_validator_and_compiler.py`, `tests/unit/test_reference_graph_d365.py`.

### List / Repeat

Status: Parsing `supported`, ReferenceGraph `supported`, Template IR `supported`, DOCX Compiler `supported`, Validation `supported`.

Evidence: `tests/unit/test_schema_and_ir.py`, `tests/unit/test_validator_and_compiler.py`, `tests/golden_files/expected/nested-list/ir.json`.

### Nested Collections

Status: Parsing `supported`, ReferenceGraph `partial`, Template IR `supported`, DOCX Compiler `supported`, Validation `supported`.

Evidence: `tests/unit/test_v012_regressions.py`, `tests/golden_files/expected/nested-list/ir.json`.

Limitations:
- The graph preserves parent/child element ids; nested collection inference from tables is covered only for the simple table shape.

### If / Else

Status: Parsing `supported`, ReferenceGraph `supported`, Template IR `supported`, DOCX Compiler `supported`, Validation `supported`.

Evidence: `tests/unit/test_validator_and_compiler.py`, `tests/golden_files/expected/conditional-vat/ir.json`.

### Images

Status: Parsing `supported`, ReferenceGraph `supported`, Template IR `supported`, DOCX Compiler `supported`, Validation `supported`.

Evidence: `tests/unit/test_v013_images_headers.py`, `tests/unit/test_reference_import_ir.py`, `tests/golden_files/expected/image-binding/ir.json`.

Limitations:
- All IMG-01…IMG-09 scenarios are proven on synthetic schemas/fixtures; the private corpus has no dedicated product-image family, so corpus-level image correctness remains unmeasured.

### Image Collections

Status: Parsing `partial`, ReferenceGraph `partial`, Template IR `supported`, DOCX Compiler `supported`, Validation `partial`.

Evidence: `tests/unit/test_v013_images_headers.py::test_static_images_expand_inside_repeat`, `tests/unit/test_candidate_filtering.py::test_product_image_candidate_is_scoped_to_the_line_collection`.

Limitations:
- Image controls exist in Repeat and table row templates, but the corpus has no dedicated image-collection case and wrong-scope detection is proven on synthetic schemas only.

### Tables

Status: Parsing `partial`, ReferenceGraph `unsupported`, Template IR `supported`, DOCX Compiler `supported`, Validation `supported`.

Evidence: `packages/reference-inspector/src/docentric_copilot/reference/table_inference.py`, `tests/unit/test_v013_table_inference.py`, `tests/unit/test_validator_and_compiler.py`.

Limitations:
- The graph is control-centric and does not model table geometry. v0.13 adds a DOCX table inference layer; merged/ragged cells and missing collection evidence are diagnosed rather than silently converted. Optional cells and static footer rows are inferred; a nested repeat under an outer repeated row remains unsupported.

### Repeated Table Rows

Status: Parsing `partial`, ReferenceGraph `unsupported`, Template IR `supported`, DOCX Compiler `supported`, Validation `supported`.

Evidence: `tests/unit/test_v013_table_inference.py::test_header_and_repeated_row_become_a_table_repeat`, `tests/unit/test_validator_and_compiler.py::TestCompiler::test_document_content`.

Limitations:
- Header/data-row separation requires one static header row; multiple repeated row shapes are diagnosed as ambiguous rather than guessed.

### Nested Tables

Status: Parsing `partial`, ReferenceGraph `unsupported`, Template IR `supported`, DOCX Compiler `supported`, Validation `supported`.

Evidence: `tests/unit/test_v013_table_inference.py::test_nested_table_is_preserved_in_the_cell`, `tests/unit/test_v012_regressions.py`.

Limitations:
- Static nested tables are preserved. A nested table with its own repeat under an outer repeated row is not inferred; it is listed as unsupported rather than producing a wrong-scope table.

### SubDocuments

Status: Parsing `supported`, ReferenceGraph `supported`, Template IR `unsupported`, DOCX Compiler `unsupported`, Validation `not_tested`.

Evidence: `tests/unit/test_reference_import_ir.py`.

Limitations:
- Sub-documents remain reference-only; the importer lists them in skipped[] and never inlines them.

### Groups

Status: Parsing `supported`, ReferenceGraph `supported`, Template IR `unsupported`, DOCX Compiler `unsupported`, Validation `not_tested`.

Evidence: `tests/unit/test_reference_import_ir.py`.

Limitations:
- Group semantics are not confirmed for generic IR; groups are skipped explicitly.

### Barcode

Status: Parsing `supported`, ReferenceGraph `supported`, Template IR `unsupported`, DOCX Compiler `unsupported`, Validation `not_tested`.

Evidence: `tests/unit/test_reference_import_ir.py`.

Limitations:
- Barcode is reference-only and is never replaced by plain text.

### SummaryField

Status: Parsing `supported`, ReferenceGraph `supported`, Template IR `unsupported`, DOCX Compiler `unsupported`, Validation `not_tested`.

Evidence: `tests/unit/test_reference_import_ir.py`.

Limitations:
- Complex summary expressions are unsupported and preserved as reference data.

### Headers / Footers

Status: Parsing `supported`, ReferenceGraph `supported`, Template IR `supported`, DOCX Compiler `supported`, Validation `supported`.

Evidence: `tests/unit/test_v013_images_headers.py`, `docs/RELEASE_EVIDENCE_V0_12.md`, `docs/RESPONSIVE.md`.

### Multiple DataSources

Status: Parsing `supported`, ReferenceGraph `supported`, Template IR `partial`, DOCX Compiler `supported`, Validation `supported`.

Evidence: `tests/unit/test_reference_graph_d365.py`, `tests/unit/test_reference_import_ir.py`.

Limitations:
- The reference graph resolves multiple D365 DataSources, but an imported document uses a single synthetic schema id and a flat section.

## Missing tests

- Word for the web manual validation evidence

## Further work

- #40 multiple bound row shapes are diagnosed as ambiguous; no silent drop

## Status vocabulary

| Status | Meaning |
| --- | --- |
| Supported | Implemented and covered by a regression test at this level. |
| Partial | Implemented for a documented subset; the limitation is listed above. |
| Unsupported | Deliberately refused; the construct is reported, never guessed. |
| Not Present | Not found in the audited examples; this is not a support claim. |
| Not Tested | No regression test proves the behaviour; never reported as supported. |

Generated from [`benchmarks/feature_coverage.json`](https://github.com/SergeyGer/Docentric-Copilot/blob/main/benchmarks/feature_coverage.json) by `python scripts/feature_coverage.py --write`.
