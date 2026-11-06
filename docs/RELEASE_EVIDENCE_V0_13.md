# Release Evidence — Docentric Copilot v0.13.0 (implementation candidate)

| Field | Value |
| --- | --- |
| Base release | `0.12.0` (tag `v0.12.0`, commit `a4d3eb9`) |
| Candidate version | `0.13.0` |
| Template IR | `1.1` (migration from `1.0`) |
| Status | **Implementation candidate — not tagged** |
| Compatibility | Docentric AX runtime **`not_tested`**; AT-07 **`partial`** |

> V013-01…V013-05, V013-07 and V013-08 are Passed. V013-06 (Word for the web) and
> V013-09/V013-10 (videos) are Deferred because the required external access and
> production session are not available in this environment; they are not reported
> as passed. See the honest status table below.

## 1. What was implemented

### V013-01 — Feature Coverage Matrix (Passed)

- `benchmarks/feature_coverage.json` and generated `docs/FEATURE_COVERAGE_V013.md`.
- 15 Docentric feature families across Parsing, ReferenceGraph, Template IR, DOCX Compiler and Validation.
- Corpus accounting: 6 AX 2012 examples + 11 D365FO entries = **17 unique DOCX**, 63 DOCX artifacts,
  249 artifacts, 37 duplicate groups/179 duplicate occurrences, 672 controls, 650 resolved, 22 unknown.
- Every Supported claim links to a regression test; Partial/Unsupported/Not Tested entries state limitations.
- Checker: `python scripts/feature_coverage.py --check`.

### V013-02 — Image family (Passed for the synthetic scenarios)

IR 1.1 extends `ImageBinding` with:

- `source: schema | static`, `static_asset` (reviewed compile asset key, never a path);
- `fallback: placeholder | blank | alt_text`;
- `preserve_aspect` (default true, no uncontrolled stretching);
- width/height/alignment retained.

Compiler and validator support:

- static assets via `CompileOptions.static_assets`, keyed lookup, 5 MiB + magic-byte validation;
- dynamic schema images, optional/missing images and fallback policy;
- images inside Repeat and table row templates (image per line item);
- wrong-type rejection (V2-002) and wrong-scope image rejection (V2-003);
- product-image candidate scoping so a company logo cannot satisfy a line-item product image;
- OOXML package remains valid; aspect ratio preserved unless explicitly stretched.

Tests: `tests/unit/test_v013_images_headers.py`, `tests/unit/test_candidate_filtering.py`.

### V013-03 — Reference-to-IR table inference (Passed)

New deterministic `table_inference.py` reads bounded DOCX table geometry and joins content-control
ordinals to the projected schema evidence. It supports:

- static tables and static header rows;
- repeated data rows backed by a schema collection (never inferred from similar names alone);
- alias-relative field paths and image cells;
- nested static tables;
- optional cells with an `If` control become `Conditional` cells;
- static rows after the repeated row become `footer_rows`, rendered after the repeat;
- a nested table with its own repeat under the outer row alias is inferred with a relative
  Repeat path and relative row fields;
- explicit blocking diagnostics for merged/ragged cells, ambiguous headers and missing collection
  evidence;
- strict mode refuses on diagnostics; best-effort returns the supported subset with `skipped[]`.

The ambiguous cases (merged/ragged cells, multiple bound row shapes, a nested table outside the
outer collection) are explicit blocking diagnostics in strict mode and `skipped[]` entries in
best-effort mode. No row or table is silently dropped.

### V013-04 — First-page header (Passed)

- `Section.first_page_header` in IR 1.1 (`None` = normal header, `[]` = blank first-page header).
- Compiler emits `w:titlePg`, a first-page header part and `headerReference w:type="first"`;
  the default header has no logo; the first-page footer keeps PAGE/NUMPAGES fields.
- Preview renders the first-page header only on page 1 and the default header on later pages.
- The planner (heuristic, compact v1 and compact v2 `fh`) can place the logo on the first page only.
Multi-section support is now real: each IR section becomes a Word section (`WD_SECTION.NEW_PAGE`),
`None` headers/footers inherit from the previous section, an explicit empty list suppresses the
first-page header, and each section can have its own `titlePg`/first-page header. Preview applies the
same inheritance and selects the first-page header only on the first page of each section.

Tests cover one-page, multi-page, blank first header, footer page fields, two-section inheritance,
per-section first-page headers, preview vs DOCX and page numbering.

### V013-05 — Reference Evaluation (Passed)

`benchmarks/reference_evaluation_v013.json` and `docs/REFERENCE_EVALUATION_V013.md` publish separate
metrics over the 17 official documents, with explicit denominators. It is **not** merged with the Gold
Dataset Semantic Benchmark. See the report for definitions and limitations; binding evidence is not
independent correctness.

### V013-07 — Live Demo reliability/UX (Passed)

- Version panel: application, git SHA, IR version, provider, model, execution mode
  (`Deterministic Demo`), build timestamp and compatibility `not tested`.
- Confirmation state is applied deterministically; a confirmed needs-review/conflict mapping
  unblocks compilation; missing/invalid mappings cannot be confirmed.
- The DOCX download is available after confirmation, shows byte/SHA evidence, and is covered by a
  Streamlit `AppTest` regression.
- The previous Sales Quotation failure was reproduced as the unresolved `req_09` mapping; the demo
  now preserves the reviewer decision across reruns and reruns mapping/validation before export.

### V013-06/V013-09/V013-10 — Deferred

- [Word for the web validation](WORD_WEB_VALIDATION_V013.md): not performed; no Microsoft 365/OneDrive
  session. Issue #53.
- [Demo videos](VIDEOS_V013.md): not produced; no YouTube credentials/publishing session and the
  existing v0.11 video is not relabelled. Issue #54.

## 2. V013 status table

| ID | Deliverable | Status | Evidence |
| --- | --- | --- | --- |
| V013-01 | Feature Coverage Matrix | **Passed** | [FEATURE_COVERAGE_V013](FEATURE_COVERAGE_V013.md), `benchmarks/feature_coverage.json` |
| V013-02 | Image family | **Passed** (synthetic scenarios) | `tests/unit/test_v013_images_headers.py`, `tests/unit/test_candidate_filtering.py` |
| V013-03 | Table inference | **Passed** | `table_inference.py`, `tests/unit/test_v013_table_inference.py`; ambiguous cases diagnosed |
| V013-04 | First-page header | **Passed** | `tests/unit/test_v013_images_headers.py`; multi-section inheritance tested |
| V013-05 | Reference Evaluation | **Passed** | [REFERENCE_EVALUATION_V013](REFERENCE_EVALUATION_V013.md) |
| V013-06 | Word for the web | **Deferred** | [WORD_WEB_VALIDATION_V013](WORD_WEB_VALIDATION_V013.md), #53 |
| V013-07 | Live Demo | **Passed** | `tests/unit/test_v013_demo_state.py`, `tests/unit/test_v013_demo_app.py` |
| V013-08 | Final quality benchmark | **Passed** | §4: 288 planned, 278 completed, 10 technical, 274 semantic passes |
| V013-09 | Product Demo video | **Deferred** | [VIDEOS_V013](VIDEOS_V013.md), #54 |
| V013-10 | Technical video | **Deferred** | [VIDEOS_V013](VIDEOS_V013.md), #54 |

## 3. Baseline freeze

`benchmarks/baseline_v012.json` pins the v0.12.0 baseline: tag commit
`a4d3eb947ccb6b68f2a146987037f69668acb526`, Gold dataset `2.0.0`
(`8489e4c0…`), benchmark manifest `b830ed63…`, audit manifest `6fd848e0…`, 288/284/4/277 counters,
D365 11/246/233/13 and tool versions. Checked by `tests/unit/test_v013_baseline.py`.

## 4. Final quality benchmark

Full 32 × 3 × 3 run on the frozen `gold-cases/v2` `2.0.0` dataset (SHA-256 `8489e4c0…`).
Artifacts: `benchmarks/gold_report_v013.json`, `.csv`, `.html`, `benchmarks/gold_runs_v013.jsonl`,
`benchmarks/gold_manifest_v013.json` (manifest SHA-256
`e7f13c96771a80e5e3810047c1bbd7e2b6c6b62f782f903a900f976145a4728e`).

| Counter | Value |
| --- | ---: |
| Planned logical runs | 288 |
| Completed | 278 |
| Technical failures | 10 (all Gemini `structured_output`) |
| Skipped | 0 |
| Semantic passes | 274 |
| Correct runs | 274 |
| Valid-template runs | 278 |

| Metric | Value |
| --- | ---: |
| Precision | 0.9510 (816/858) |
| Recall | 0.9976 (816/818) |
| F1 | 0.9737 |
| Semantic pass rate (completed) | 98.56% (274/278) |
| Valid-template rate (completed) | 100% (278/278) |
| Technical-failure rate | 3.47% (10/288) |
| pass@1 / pass@2 / pass@3 | 93.75% / 95.83% / 97.92% |
| p50 / p95 latency | 3.554 s / 8.058 s |
| Spend | $4.1844 = $4.0463 verified + $0.1381 estimated |

The 10 Gemini failures are technical (`structured_output`), not semantic passes. The run was made
from clean commit `b1c07cf` recorded in the manifest; it is a
separate artifact from the v0.12 288-run matrix and must not be spliced with it. AT-07 remains
`partial`: the labels are owner-authored with a deterministic proxy, not independent human review.

## 5. Known limitations

- **Videos and Word for the web are Deferred.** V013-06/V013-09/V013-10 are not passes; the external access is documented.
- **Docentric AX runtime compatibility remains `not_tested`.** No execution in a licensed environment.
- **AT-07 remains `partial`.** No independent human review of the gold labels.
- **Table inference is deliberately conservative.** It refuses merged/ragged tables, ambiguous
  headers, missing collection evidence and nested-repeat structures instead of guessing.
- **Images are synthetic-tested.** The private D365 corpus has no dedicated product-image family.
- **Word for the web not tested.** The manual checklist and fixture command exist; no pass is claimed.
- **No videos.** Storyboard/outline exist; no MP4/YouTube claim.
- **Reference Evaluation is evidence, not correctness truth.** Binding evidence rate is not an
  independent annotation score.

## 6. Verification commands

```bash
python scripts/feature_coverage.py --check
python scripts/reference_evaluation.py --check
.venv/bin/pytest tests/unit -q
.venv/bin/pytest tests/e2e --e2e -q
ruff check . && ruff format --check .
mypy packages services
python scripts/check_docs_links.py
```
