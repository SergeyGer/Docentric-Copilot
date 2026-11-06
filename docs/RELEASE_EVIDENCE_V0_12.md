# Release Evidence — Docentric Copilot v0.12.0

| Field | Value |
| --- | --- |
| Release | `0.12.0` |
| Date | 2026-11-06 |
| Tag | `v0.12.0` |
| Base | v0.11.0 (`3101c9a422f091a02dccd8a29a79543444c37f49`) |
| Release content | PR-1 `#45`, PR-2 `#48`, PR-3 `#46`, PR-4 `#47`, PR-5 |
| Benchmark dataset | `gold-cases/v2` `2.0.0`, SHA-256 `8489e4c07f9a8c87e76c0e7fa4a7da8c7f9d6ec0ca0b04eb36cfcd4fe003fd4b` |
| Benchmark manifest | [gold_manifest_v012.json](../benchmarks/gold_manifest_v012.json), SHA-256 `b830ed6313955a87576c5bfc110730a35294364c0fc8ae61d2942b0c534ceba3` |
| Gold audit manifest | [gold_manifest.json](../benchmarks/gold_manifest.json), SHA-256 `6fd848e06431981c1d23933e5e769978fe7f2e3ebbe4ce12559ba2b4cfd54bf6` |
| Gold audit log | [gold_adjudication_log.json](../benchmarks/gold_adjudication_log.json), SHA-256 `d7437a63b43252e2391a01d608fdd9ccda262ec6adbeee88c4c56063a2be84b2` |
| D365 safe aggregate | [d365_regression_v012.json](../benchmarks/d365_regression_v012.json), verdict `passed` |
| Runtime compatibility | **`not_tested`** — no Docentric AX execution claim |

The tag target commit is the merge commit of PR-5 on `main`; GitHub records it on
the `v0.12.0` tag and release page. The release content commit is the PR-5 head
that carries this document. The benchmark and D365 artifacts record the commits
they were produced from independently.

## 1. V012 status

| ID | Task | Status | Evidence |
| --- | --- | --- | --- |
| V012-01 | Gold Dataset audit trail | **Passed** | 32/32 cases, 18 `no_change`, 14 clarifications, hashes, consistency checker, generated [GOLD_AUDIT](GOLD_AUDIT.md). AT-07 = `partial`; independent human review **not performed**. |
| V012-02 | Full semantic benchmark | **Passed** | 288 logical runs in [gold_manifest_v012.json](../benchmarks/gold_manifest_v012.json); 284 completed, 4 technical, 0 skipped; 277 semantic passes; [BENCHMARKS §10](BENCHMARKS.md#10-v012-full-benchmark-32--3--3-v012-02). |
| V012-03 | Image-family expansion | **Deferred** | Issue #37; target v0.13. The v0.12 dataset is frozen for the reproducible 288-run benchmark; adding cases would invalidate it. No image subtype is claimed as passed. |
| V012-04 | D365 real-corpus regression | **Passed** | [D365_REGRESSION](D365_REGRESSION.md): 11/11 documents, 246 bindings, 233 resolved, 13 unresolved (4 unknown_path, 8 unsupported_expression, 1 type_mismatch), 0 lost/new/duplicate/scope, 11/11 stable digests. Private files never committed. |
| V012-05 | Gemini nested table / Anthropic alias | **Passed** | [V012-05](V012_05_REGRESSIONS.md): object-column nested table support, typed structural validator, branch/cell alias scopes and deterministic rename. Deterministic tests need no LLM; targeted live subset 23/23 evaluable correct, 4 Gemini `structured_output` technical failures. |
| V012-06 | Reference → IR table inference | **Deferred** | Issue #40; target v0.13. Table/Row/Cell inference is not claimed; unsupported constructs remain explicit skips. |
| V012-07 | Real LibreOffice/Poppler Visual CI | **Passed** | [VISUAL_CI](VISUAL_CI.md); pinned renderer lock, five fixtures, real render, tolerance 0.005, artifacts and fail-closed statuses. Local real-render run passed; the dedicated workflow is part of the release gates. |
| V012-08 | Playwright E2E | **Passed** | [E2E](E2E.md); happy path, five negative paths, trace/screenshot probe, dedicated CI job green on PR-4; responsive tests 1280/768/390. |
| V012-09 | Report retention/deletion | **Passed** | [REPORT_RETENTION](REPORT_RETENTION.md); report-specific TTL, DELETE 204, verified 404 after deletion, tests for TTL/database contents. |
| V012-10 | Responsive + release docs | **Passed** | [RESPONSIVE](RESPONSIVE.md); version/changelog/roadmap/README/OpenAPI aligned to 0.12.0; P1 statuses below. |

No status is represented as a single "percent complete". `Deferred` is not
`Passed`.

### P1 status

| P1 item | Status | Issue / target |
| --- | --- | --- |
| V012-03 image-family expansion | **Deferred** | #37, v0.13 |
| V012-06 reference-to-IR table inference | **Deferred** | #40, v0.13 |
| V012-09 retention/delete | **Passed** | implemented and tested |
| Responsive coverage | **Passed** | 1280/768/390 px; minimum supported width 390; 320 px untested |

## 2. Release gates

| Gate | Status | Evidence |
| --- | --- | --- |
| Baseline commit/dataset frozen | Met | [baseline_v011.json](../benchmarks/baseline_v011.json); dataset hash above |
| AT-07 partial, no simulated human review | Met | GOLD_AUDIT; `independent_human_review: false`, `second_human_annotator: false` |
| 288 benchmark runs and report | Met | manifest counters and hashes; full report committed |
| Technical failures separate from semantic failures | Met | evaluator 1.0.1; 4 technical/284 evaluable; explicit reasons |
| D365 11/11 local, private files not staged | Met | D365 safe aggregate; `.local-artifacts/` git-ignored; no private paths in Git |
| Gemini nested table / Anthropic alias tests | Met | deterministic regression suite + targeted live subset |
| Playwright E2E in CI | Met | E2E job green on PR-4; responsive tests in the same suite |
| Real LibreOffice/Poppler Visual CI | Met | `Visual Diff` workflow; local real-render pass; renderer unavailable is not a pass |
| P1 statuses and deferred issues | Met | table above |
| README/CHANGELOG/ROADMAP/version/OpenAPI consistent | Met | version 0.12.0 in pyproject, package, web, README, ROADMAP, OpenAPI; CHANGELOG 0.12.0 |
| Secret/private artifact scan | Met | key scan reviewed (only documented placeholders and test values); no tracked `.env`, `.git-token`, private corpus or `.local-artifacts` |
| Runtime `not_tested` published | Met | README, benchmark/D365 reports, this document |

## 3. Benchmark evidence

| Metric | Value |
| --- | ---: |
| Logical runs | 288 (32 cases × 3 providers × 3 repeats) |
| Completed / technical / skipped | 284 / 4 / 0 |
| Semantic passes / correct | 277 / 276 |
| Precision / recall / F1 | 0.9535 / 1.0000 / 0.9762 |
| Semantic pass (evaluable) | 97.54% |
| Valid template (completed) | 99.65% |
| Technical failure rate | 1.39% |
| pass@2 | 97.92% |
| Spend | $3.9251 (verified $3.7915 + estimated $0.1336) |
| Latency p50 / p95 | 3637.5 ms / 8379.6 ms |

The full matrix was produced from commit `05bb713` with evaluator `1.0.1`; the
V012-05 fixes landed afterwards and are covered by the separate targeted subset
(27 runs, 23 completed, 23/23 correct, 4 Gemini technical failures, $0.4761).
The two artifacts are shown separately and are not spliced. Details and caveats:
[BENCHMARKS §10](BENCHMARKS.md#10-v012-full-benchmark-32--3--3-v012-02) and
[EVALUATION §2.11](EVALUATION.md#211-v012-05-affected-regression-nested-tables-and-aliases).

## 4. D365 evidence

| Metric | Value |
| --- | ---: |
| Documents processed | 11 / 11 |
| Unique document payloads | 10 |
| Bindings | 246 |
| Resolved with evidence | 233 |
| Unresolved | 13 (`unknown_path` 4, `unsupported_expression` 8, `type_mismatch` 1) |
| Lost resolved / new unresolved | 0 / 0 |
| Duplicate resolve edges / scope mismatches | 0 / 0 |
| Graph nodes / edges | 794 / 862 |
| Evidence coverage | 0.9243 |
| Digest stability | 11/11 stable |
| Verdict | `passed` |

No source DOCX, per-document hash, schema path, diagnostic text or graph payload
is in Git. The public summary is aggregate only; private outputs live under the
git-ignored `.local-artifacts/d365-regression/`.

## 5. Version consistency

| Artifact | Value |
| --- | --- |
| `pyproject.toml` | `0.12.0` |
| `docentric_copilot.__version__` | `0.12.0` |
| `apps/web/package.json` / lock | `0.12.0` |
| README project facts | `0.12.0` |
| ROADMAP current release | `0.12.0` (published) |
| CHANGELOG | `[0.12.0] - 2026-11-06` |
| OpenAPI `info.version` | `0.12.0` |
| Tag | `v0.12.0` |

## 6. Known limitations

- **No independent human review.** AT-07 stays `partial`; the audit reviewer is
  the dataset owner and the deterministic adjudicator is a proxy.
- **Full benchmark precedes the V012-05 fixes.** The 288-run matrix is the
  pre-fix full artifact; the affected nested subset is published separately.
- **Gemini technical failures.** Four `structured_output` failures in the full
  run and four in the targeted subset are technical, not semantic passes.
- **Image subtypes not covered.** Company logo only; product image, image
  collection, optional/missing/wrong-type image are deferred (#37).
- **Table inference not implemented.** Reference → IR Table/Row/Cell inference is
  deferred (#40); explicit skips remain.
- **Private corpus.** The 11 D365 documents cannot be published; the aggregate
  proves the local run, not their content.
- **Runtime not tested.** Docentric AX compatibility remains `not_tested`.
- **Renderer fidelity.** LibreOffice rendering is not Word fidelity.
- **Storage limits.** SQLite is single-process in this build; retention is not a
  certified legal retention programme.
- **Responsive limits.** Chromium functional checks at 390/768/1280 px; 320 px
  and touch gestures are untested.

## 7. Final recommendation

Release **v0.12.0** as a release of provable reliability: the gold dataset has a
verifiable audit trail, the full 288-run benchmark is published with technical
failures classified, the private D365 corpus regression is reproducible and
safe-summarised, the Playwright flow and real LibreOffice/Poppler rendering run
in CI, and the deferred P1 items are labelled honestly with issues and target
versions. The absence of an independent second annotator does not block this
release while AT-07 remains `partial`; Docentric AX runtime compatibility
remains `not_tested` and is out of scope.
