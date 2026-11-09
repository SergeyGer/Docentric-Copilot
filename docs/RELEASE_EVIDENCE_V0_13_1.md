# Release evidence — Docentric Copilot v0.13.1

| Field | Value |
| --- | --- |
| Version | `0.13.1` |
| Status | Released |
| Tag | `v0.13.1` |
| Base feature release | `v0.13.0` |
| Template IR | `1.2` |
| Compatibility | `not_tested` |
| AT-07 | `partial` |

This is a corrective diagnostic release on top of
[v0.13.0](RELEASE_EVIDENCE_V0_13.md). It does not change the planner or the
published benchmark; it makes the remaining v0.13 audit findings explicit and
reproducible.

## 1. Changes

| Area | Evidence |
| --- | --- |
| Nested collection boundary | `packages/reference-inspector/.../import_ir.py`; `tests/unit/test_v013_reference_evaluation.py` |
| Table outcomes and merged-cell refusal | `packages/reference-inspector/.../table_inference.py`; `tests/unit/test_v013_table_inference.py` |
| Reference failure classification | `scripts/reference_evaluation.py`; `benchmarks/reference_evaluation_v013.json` |
| Gemini failure classification | `scripts/gemini_failures.py`; `docs/GEMINI_FAILURES_V013.md` |
| Documentation/IR sync | `docs/FEATURE_COVERAGE_V013.md`, `docs/RELEASE_EVIDENCE_V0_13.md`, `CHANGELOG.md` |
| Deployed demo (T-08) | `docs/DEMO_SMOKE_V013.md`; `scripts/deployed_demo_smoke.py` |
| Word Web kit (T-01) | `docs/media/v013-wordweb/`; user-provided Microsoft Word desktop pages; `docs/WORD_WEB_VALIDATION_V013.md` |
| Video draft kit (T-02/T-03) | `docs/media/demo-v013.mp4`, `technical-v013.mp4`; `scripts/build_v013_videos.py` |

## 2. T-04 — Reference Evaluation pipeline failures

17 documents parsed, 16 reached import, 15 compiled. The two pipeline failures
are classified and tested:

1. `CompilationFailedError` — an unenclosed nested collection is refused instead
   of being bound at document root.
2. `ReferenceImportEmptyError` — the document contains only unsupported
   constructs; the importer reports an empty safe subset.

See [REFERENCE_EVALUATION_V013](REFERENCE_EVALUATION_V013.md#failure-classification).

## 3. T-05 — Table classification

30 observed body tables:

| Class | Count |
| --- | ---: |
| Accepted inferred tables | 15 |
| Deliberately unsupported | 15 |
| Defect | 0 |
| Not evaluable | 0 |

Reasons: `TABLE_COLLECTION_NOT_EVIDENCED` 7, `TABLE_MERGED_OR_RAGGED` 7,
`TABLE_MULTIPLE_REPEATED_ROWS` 4, `TABLE_ROW_EMPTY` 1. The audit baseline 17/30
predates explicit merged-cell rejection.

## 4. T-06 — Gemini failures

10 v0.13 technical failures vs 4 in v0.12; all Gemini compact-v2
`structured_output`. Classes: root-level section keys 5, unknown root `v` 2,
malformed nested cell block 2, wrong nested cell scalar 1. See
[GEMINI_FAILURES_V013](GEMINI_FAILURES_V013.md).

## 5. T-08 — Deployed demo

The Streamlit Cloud app was woken and exercised in Chromium:

- Application `0.13.0`, Git commit `1cbe073239f6`, Template IR `1.2`,
  deterministic demo.
- Sales quotation (confirm `req_09`), tax invoice and purchase order each download
  DOCX.
- Downloaded SHA-256 values match the local deterministic build.

See [DEMO_SMOKE_V013](DEMO_SMOKE_V013.md).

## 6. P0 item closure

| ID | Status | Evidence |
| --- | --- | --- |
| V013-06 / #53 Word for the web | Closed by maintainer decision | Microsoft Word desktop check accepted; Word for the web itself not performed |
| V013-09 / #54 Product Demo | Published | [YouTube](https://youtu.be/HZcP_lrjcrw) · 2:58 |
| V013-10 / #54 Technical Deep-Dive | Published on GitHub | [technical-v013.mp4](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/media/technical-v013.mp4) · 5:11; not uploaded to YouTube |

No P0 item is deferred.

## 7. Verification

- Main CI green: Python lint/types/tests (85% coverage gate), Web, Security,
  CodeQL, E2E, Visual Diff, Docker.
- Release workflow builds the wheel/sdist, installs and inspects the example, and
  builds both images.
- Benchmark metrics are unchanged from v0.13.0; see
  [BENCHMARKS §11](BENCHMARKS.md#11-v013-full-benchmark-v013-08).

## 8. Limitations

- Docentric AX runtime compatibility remains `not_tested`; Word Desktop not tested.
- AT-07 remains `partial`; there is no independent human review of the gold labels.
- The deployed demo was rechecked on main commit `5a173b5` (v0.13.1, IR 1.2).
- v0.13.1 does not claim Word for the web or Docentric AX runtime compatibility.

## 9. Post-release evidence rework

After the v0.13.1 tag, the maintainer supplied a Microsoft Word desktop check
(two pages plus the DOCX) and asked for a video rework. The current repository
therefore contains:

- `docs/media/v013-wordweb/user-word-desktop/` — Word **desktop** evidence,
  explicitly not Word for the web;
- published videos: [Product Demo](https://youtu.be/HZcP_lrjcrw) on YouTube and
  [Technical Deep-Dive](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/media/technical-v013.mp4)
  on GitHub, with SRTs, thumbnails and no spoken/on-screen version numbers;
- Mermaid diagrams rendered from `docs/wiki/Architecture.md` and charts built
  from the committed benchmark/reference JSON.

These additions are on `main` after the v0.13.1 tag and do not change the
release assets. Word for the web itself remains untested; #53 is closed by the
maintainer on the Word desktop evidence, and #54 is closed with the published
YouTube/GitHub links.
