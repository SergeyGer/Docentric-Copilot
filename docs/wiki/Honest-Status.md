# Honest status

> **Docentric AX compatibility is unverified.** This project produces **generic DOCX** documents.
> The engine verifies its own correctness — structure, field bindings, logic and layout — and reports
> Docentric AX compatibility as **`not_tested`**. Compatibility requires independent verification inside a
> licensed Docentric environment that has not been performed.
> [Read what would change this status](Docentric-AX-Compatibility).

This is a deliberate product decision, not a missing feature: a beautiful document built on an unverified
assumption is a liability, not a deliverable.

**This page is the maintained status record.** The README links here; status updates are made here (and
in [`docs/wiki/Honest-Status.md`](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/wiki/Honest-Status.md))
and published with `python scripts/sync_wiki.py --push`.

## At a glance

| Area | Status |
| --- | --- |
| Generic DOCX output | **Delivered** — deterministic, schema-checked |
| Docentric AX runtime compatibility | **`not_tested`** — no execution claim |
| Gold labels annotation | **AT-07 = `partial`** — owner self-review + deterministic proxy; no independent human review |
| v0.12 reliability release | **Released** — [v0.12.0](https://github.com/SergeyGer/Docentric-Copilot/releases/tag/v0.12.0) |
| v0.13 release | **Released `v0.13.0`; corrective `v0.13.1`** — V013-01…05/07/08 Passed; V013-06 closed on Word desktop; V013-09/V013-10 Passed/published |
| Template IR | **`1.2`** — first-page header, image source/fallback and table footer rows; `1.0`/`1.1` migrate |
| Feature coverage | **Published** — [FEATURE_COVERAGE_V013](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/FEATURE_COVERAGE_V013.md) |
| Reference Evaluation | **Published** — [REFERENCE_EVALUATION_V013](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/REFERENCE_EVALUATION_V013.md) |
| v0.13 full benchmark | **Published** — 288 planned / 278 completed / 10 technical / 274 semantic passes |
| D365 private-corpus regression | **11/11 local** — aggregate only, [D365_REGRESSION](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/D365_REGRESSION.md) |
| Open P0 gaps | **None** — #53 and #54 are closed; Word Web itself remains untested |

## v0.13 — implementation candidate

Full evidence: [RELEASE_EVIDENCE_V0_13](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/RELEASE_EVIDENCE_V0_13.md).
The release tags `v0.13.0` and `v0.13.1` are published; the Deferred items below are external dependencies, not passes.

| V013 ID | Workstream | Status | Evidence |
| --- | --- | --- | --- |
| V013-01 | Feature Coverage Matrix | **Passed** | [FEATURE_COVERAGE_V013](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/FEATURE_COVERAGE_V013.md) |
| V013-02 | Image family | **Passed** (synthetic scenarios) | `tests/unit/test_v013_images_headers.py`, `tests/unit/test_candidate_filtering.py` |
| V013-03 | Reference-to-IR table inference | **Passed** | Header/repeated rows, optional cells, footer rows, static/nested tables and nested repeat; ambiguous shapes diagnosed |
| V013-04 | First-page header | **Passed** | `w:titlePg`, first header part, per-section headers and preview inheritance; multi-section tests |
| V013-05 | Reference Evaluation | **Passed** | [REFERENCE_EVALUATION_V013](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/REFERENCE_EVALUATION_V013.md) |
| V013-06 | Word for the web | **Closed by maintainer decision** — Word desktop accepted; Word Web not performed | User-provided Word desktop pages; [#53](https://github.com/SergeyGer/Docentric-Copilot/issues/53) closed; [WORD_WEB_VALIDATION](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/WORD_WEB_VALIDATION_V013.md) |
| V013-07 | Live Demo reliability/UX | **Passed** | Version panel, confirmation gating, download regression |
| V013-08 | Final quality benchmark | **Passed** | 288 planned, 278 completed, 10 technical, 274 semantic passes; [BENCHMARKS §11](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/BENCHMARKS.md#11-v013-full-benchmark-v013-08) |
| V013-09 | Product Demo video | **Passed — published on YouTube** | [watch](https://youtu.be/HZcP_lrjcrw) · [VIDEOS_V013](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/VIDEOS_V013.md) |
| V013-10 | Technical video | **Passed — published on GitHub** | [technical-v013.mp4](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/media/technical-v013.mp4) · [VIDEOS_V013](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/VIDEOS_V013.md) |

## v0.12 — previous release status

v0.12 is a release of **provable reliability**, not new surface area. Full evidence:
[RELEASE_EVIDENCE_V0_12](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/RELEASE_EVIDENCE_V0_12.md).

| V012 ID | Workstream | Status | Evidence |
| --- | --- | --- | --- |
| V012-01 | Gold dataset audit trail, hashes, consistency report | **Passed** | [GOLD_AUDIT](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/GOLD_AUDIT.md); AT-07 `partial` |
| V012-02 | Full 32 × 3 × 3 semantic benchmark | **Passed** | [BENCHMARKS §10](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/BENCHMARKS.md#10-v012-full-benchmark-32--3--3-v012-02); 288 runs, 284 completed, 4 technical, 277 semantic passes |
| V012-03 | Image-family expansion | **Deferred** | Issue [#37](https://github.com/SergeyGer/Docentric-Copilot/issues/37), target v0.13 |
| V012-04 | D365 real-corpus regression | **Passed** | [D365_REGRESSION](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/D365_REGRESSION.md); 11/11, 246 bindings, 233 resolved, 13 unresolved |
| V012-05 | Gemini nested table / Anthropic Repeat alias | **Passed** | [V012-05](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/V012_05_REGRESSIONS.md); targeted subset 23/23 evaluable correct |
| V012-06 | Reference → IR table inference | **Deferred** | Issue [#40](https://github.com/SergeyGer/Docentric-Copilot/issues/40), target v0.13 |
| V012-07 | Real LibreOffice/Poppler Visual CI | **Passed** | [VISUAL_CI](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/VISUAL_CI.md); real renderer, five fixtures, fail-closed statuses |
| V012-08 | Playwright E2E | **Passed** | [E2E](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/E2E.md); happy path, negative paths, trace/screenshot probe |
| V012-09 | Report retention/deletion | **Passed** | [REPORT_RETENTION](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/REPORT_RETENTION.md); 24 h default TTL, DELETE, verified 404 |
| V012-10 | Responsive and release docs | **Passed** | [RESPONSIVE](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/RESPONSIVE.md); 1280/768/390 px, version/docs alignment |

**Benchmark honesty notes.** The full 288-run matrix was produced before the V012-05 fixes on commit
`05bb713`; the affected nested subset is published separately and is not spliced into the full matrix.
Four Gemini `structured_output` failures in the full run and four in the targeted subset are technical
failures, not semantic passes. Precision **0.9535**, recall **1.0000**, semantic pass **97.54%** of
evaluable runs, valid-template **99.65%** of completed runs, spend **$3.9251**.

**D365 honesty notes.** The 11 source DOCX files are private. Only an aggregate is published; no source
document, per-document hash, schema path or graph payload is in Git. Runtime compatibility stays
`not_tested`.

## v0.11 P1 — released in 0.11.0

| Workstream | Status |
| --- | --- |
| #26 D365 evidence in the unified ReferenceGraph | Done — `schema_source`, `source_id`, `part#xpath`, exact binding status; real v0.12 11-document regression |
| #27 safe Reference → Generic Template IR | Partial by design — Field, Label, List→Repeat, If, Image; explicit `skipped[]`; **no Table inference** (deferred #40) |
| #28 independent visual reference diff | Done — LibreOffice rendering, not Word fidelity; real pinned LibreOffice/Poppler CI since v0.12 |
| #29 persistence, reopen and export | Done — report TTL, delete/retention, JSON/HTML export, committed Playwright E2E |
| #30 hardening and docs | Done — superseded by V012-10 for the v0.12 version/docs alignment |
| Docentric AX runtime compatibility | **`not_tested`** — unchanged; `target=docentric-ax` remains fail-closed |

The importer refuses to guess: unknown, ambiguous, type-mismatched, schema-unavailable and unsupported
constructs become `skipped[]` entries instead of a wrong generic document. The visual diff reports
`renderer_unavailable`/`visual_not_checked` rather than a pass or fail when the renderer is missing.
Details: [Reference Templates](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/REFERENCE_TEMPLATES.md#what-is-not-implemented-or-only-partial)
and [ADR-0016](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/adr/0016-ir-import-and-visual-diff.md).

## v0.10 P0 — Reference Template Intelligence

The reference inspector is static analysis, not a Docentric runtime. The v0.10 P0 increment is
deliberately partial and is reported as such:

| Workstream | Status |
| --- | --- |
| PR-01 baseline docs, corpus manifest and consistency | Done — version strings, feature matrix and changelog aligned |
| PR-02 D365 embedded schema extraction | Done — reads `ProjectData` XSD, `PreviewData` and field metadata with OOXML provenance |
| PR-03 canonical schema and binding resolver | Done — six exact statuses; every `resolved` carries source, path, scope, type and evidence |
| PR-04 gold semantic dataset | Done — 32 versioned cases, ten families, 20/12 calibration/holdout; single-annotator labels, no independent human double review |
| PR-05 live gold benchmark | Superseded by the v0.12 full benchmark; the v0.10 report remains historical evidence |
| Reference → generic Template IR, visual diff, persistence | Continued in v0.11/v0.12; partial scopes are listed above |
| Docentric AX runtime compatibility | **`not_tested`** — unchanged |

The v0.10 benchmark is historical: **$6.8849 verified + $0.2910 estimated = $7.1759**, 288/288 planned
calls, precision 0.226/0.220/0.184 and semantic pass 55.2%/69.8%/64.6% for OpenAI/Anthropic/Gemini.
It used dataset `1.0.0` and must not be spliced with the v0.12 result. The v0.11 affected subset
(12 cases × 2 repeats) is also a separate artifact. See
[GOLD_LABELS](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/GOLD_LABELS.md) and
[EVALUATION](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/EVALUATION.md).

## Known limitations

- **No independent human review of the gold labels.** AT-07 stays `partial`; the deterministic
  adjudicator is a proxy, not a second person. The owner is the reviewer.
- **Full benchmark predates the V012-05 fixes.** The affected nested subset is published separately;
  the 288-run matrix is not edited or spliced.
- **Gemini technical failures.** `structured_output` failures are technical, not semantic passes.
- **Image subtypes not covered.** Company logo only; product image, image collection, optional/missing
  and wrong-type images are deferred (#37).
- **No table inference.** Reference → IR Table/Row/Cell inference is deferred (#40); skips remain explicit.
- **Private D365 corpus.** The 11 documents cannot be published; the aggregate proves the local run,
  not their content.
- **Runtime not tested.** Docentric AX compatibility remains `not_tested`.
- **LibreOffice, not Word.** Rendering evidence is LibreOffice output, not Word fidelity.
- **Storage limits.** SQLite is single-process in this build; retention is not a certified legal
  retention programme.
- **Responsive limits.** Functional Chromium checks at 390/768/1280 px; 320 px and touch gestures are
  untested.

## How this page is maintained

- The canonical source is
  [`docs/wiki/Honest-Status.md`](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/wiki/Honest-Status.md)
  in the repository. Change it in a pull request, then publish the wiki with
  `python scripts/sync_wiki.py --push`.
- The README keeps only a short compatibility warning and a link to this page; it is not the detailed
  status record.
- A status moves from `Partial`/`Deferred` to `Passed` only when an artifact exists and the linked
  evidence is merged. `Deferred` is never rewritten as `Passed`.
- Docentric AX runtime compatibility can only change after an independent licensed-environment
  verification; no static analysis, visual diff or browser test can approve it.
