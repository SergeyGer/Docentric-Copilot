# v0.13 open-task closure — status

Audit source: `Docentric_Copilot_v0.13_Open_Tasks_RU.pdf` (2026-11-07).
This page records what is actually closed and what remains blocked by external
access. It is not a claim that the v0.13 Definition of Done is complete.

| ID | Task | Priority | Status | Evidence / blocker |
| --- | --- | --- | --- | --- |
| T-01 | Word for the web invoice check | P0 | **Blocked — external** | Local candidate kit in `docs/media/v013-wordweb/`; no Microsoft 365/OneDrive session. Issue #53 |
| T-02 | Product Demo video | P0 | **Blocked — external** | Storyboard/production contract in `docs/VIDEOS_V013.md`; no YouTube/production session. Issue #54 |
| T-03 | Technical Deep-Dive video | P0 | **Blocked — external** | Same as T-02; depends on T-01/T-07. Issue #54 |
| T-04 | Two Reference Evaluation pipeline failures | P1 | **Classified** | `docs/REFERENCE_EVALUATION_V013.md` failure table; tests for both boundaries |
| T-05 | 13 rejected tables | P1 | **Classified** | 30 observed body tables: 15 accepted / 15 deliberately unsupported / 0 defect / 0 not evaluable; reasons in `docs/REFERENCE_EVALUATION_V013.md` |
| T-06 | 10 Gemini structured_output failures | P1 | **Classified** | `docs/GEMINI_FAILURES_V013.md`; all Gemini compact-v2, 10 vs 4 in v0.12 |
| T-07 | Documentation/Template IR/nested-repeat sync | P1 (before video) | **Done** | IR 1.2 aligned in release evidence; feature matrix distinguishes IR/compiler support from automatic reference inference |
| T-08 | Live Demo release consistency | P0 (before video) | **Partial — local pass, deployed blocked** | `docs/DEMO_SMOKE_V013.md`; deployed Streamlit URL returns HTTP 303 auth, cannot be headless-checked |

## T-04 details

17 documents parsed, 16 reached import, 15 compiled. The two pipeline failures are
not semantic misses:

1. `CompilationFailedError` — an unenclosed nested collection is refused at
   document root. Regression: `tests/unit/test_v013_reference_evaluation.py`.
2. `ReferenceImportEmptyError` — every construct is outside the supported
   generic-IR subset. Regression: `tests/unit/test_reference_import_ir.py`.

## T-05 details

The audit baseline was 17/30 accepted and 13 rejected. The current scan rejects
merged/ragged cells explicitly (previously they could be accepted), so it is
15/30 accepted and 15 deliberately unsupported:

| Reason | Count |
| --- | ---: |
| `TABLE_COLLECTION_NOT_EVIDENCED` | 7 |
| `TABLE_MERGED_OR_RAGGED` | 7 |
| `TABLE_MULTIPLE_REPEATED_ROWS` | 4 |
| `TABLE_ROW_EMPTY` | 1 |

Zero defects and zero not-evaluable tables. Accepted is an inference-layer
acceptance count, not visual Word accuracy.

## T-06 details

The 10 failures are all Gemini compact-v2 `structured_output` failures:
`root_level_section_keys` 5, `unknown_root_key_v` 2,
`malformed_nested_cell_block` 2, `wrong_nested_cell_scalar` 1. Six of ten are in
nested-list cases. v0.12 had 4 technical failures. The contract was not relaxed;
corrective prompt/schema changes require a full benchmark rerun.

## What remains for P0

- A human with Microsoft 365/OneDrive must perform the Word for the web checklist
  and attach the Word Web PDF/screenshots.
- A production/YouTube session must record and publish both videos, after T-01
  and T-08 are truly closed.
- The deployed Streamlit revision must be verified interactively or redeployed
  from the release commit.

Docentric AX runtime compatibility remains **`not_tested`**; AT-07 remains
**`partial`**. The existing `v0.13.0` release remains published; these
diagnostic changes do not justify a new compatibility claim.
