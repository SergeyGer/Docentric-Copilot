# Roadmap

> What is released, what is open, and what is blocked by external evidence.
> **GitHub Issues is the source of truth for work state.** This page is synchronized with the issue
> tracker and the repository [`ROADMAP.md`](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/ROADMAP.md);
> see [How this page stays in sync](#how-this-page-stays-in-sync).

| Field | Value |
| --- | --- |
| Current release | **v0.12.0** released; **v0.13.0 implementation candidate** — [v0.13 evidence](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/RELEASE_EVIDENCE_V0_13.md) |
| Status | v0.13 P0 code complete; Word Web and videos Deferred (external access) |
| Open issues | 9 (5 backlog + #37/#40 + #53 Word Web + #54 videos) |
| Honest status | [Honest Status](Honest-Status) |

## Milestones

| Milestone | Scope | Status |
| --- | --- | --- |
| **M0 Feasibility** | Format research, licensing analysis, go/no-go | Done — path B recorded |
| **M1 Schema engine** | Safe DDSP ingestion, normalization, CLI | Done |
| **M2 AI planning** | Template IR, gateway, mapping, expressions, validators | Done |
| **M3 Compilation** | Generic DOCX, preview, golden files | Done |
| **M4 Web + CLI** | API, workspace, jobs, artifacts, Docker | Done |
| **M5 Release** | CI, security scans, docs, benchmarks, release | Done — latest released **v0.12.0**; v0.13 candidate |
| **v0.10 P0** | D365 embedded schema, binding resolver, gold benchmark, docs baseline | Done |
| **v0.11 P1** | ReferenceGraph evidence, safe IR import, visual diff, persistence | Done — released in 0.11.0 |
| **v0.12 reliability** | Audit trail, full benchmark, D365 regression, E2E, real visual CI | **Released** |
| **v0.13** | Image family, table inference, first-page header, coverage/evaluation | **Implementation candidate** — P0 gaps documented |

## v0.13 — implementation candidate status

Full evidence and gaps: [Release Evidence v0.13](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/RELEASE_EVIDENCE_V0_13.md).

| ID | Deliverable | Status | Issue |
| --- | --- | --- | --- |
| V013-01 | Feature Coverage Matrix | **Passed** | — |
| V013-02 | Image family | **Passed** (synthetic scenarios) | [#37](https://github.com/SergeyGer/Docentric-Copilot/issues/37) partially addressed |
| V013-03 | Reference-to-IR table inference | **Passed** | Header/repeated rows, optional/footer cells, nested repeat |
| V013-04 | First-page header | **Passed** — real Word sections, inheritance and per-section first pages | — |
| V013-05 | Reference Evaluation | **Passed** | — |
| V013-06 | Word for the web | **Deferred** | [#53](https://github.com/SergeyGer/Docentric-Copilot/issues/53) |
| V013-07 | Live Demo reliability/UX | **Passed** | — |
| V013-08 | Final quality benchmark | **Passed** — 276/288 completed, 272 semantic passes | — |
| V013-09 | Product Demo video | **Deferred** | [#54](https://github.com/SergeyGer/Docentric-Copilot/issues/54) |
| V013-10 | Technical video | **Deferred** | [#54](https://github.com/SergeyGer/Docentric-Copilot/issues/54) |

`Partial` and `Deferred` are not `Passed`; no v0.13 tag exists yet.

## v0.12 — previous released status

Full evidence and limitations: [Release Evidence v0.12](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/RELEASE_EVIDENCE_V0_12.md).

| ID | Deliverable | Status | Issue |
| --- | --- | --- | --- |
| V012-01 | Gold dataset audit trail, hashes, consistency report | **Passed** — AT-07 `partial` | [#35](https://github.com/SergeyGer/Docentric-Copilot/issues/35) closed |
| V012-02 | Full 32 × 3 × 3 semantic benchmark | **Passed** | [#36](https://github.com/SergeyGer/Docentric-Copilot/issues/36) closed |
| V012-03 | Image-family expansion | **Deferred** to v0.13 | [#37](https://github.com/SergeyGer/Docentric-Copilot/issues/37) open |
| V012-04 | D365 real-corpus regression | **Passed** | [#38](https://github.com/SergeyGer/Docentric-Copilot/issues/38) closed |
| V012-05 | Gemini nested table / Anthropic Repeat alias | **Passed** | [#39](https://github.com/SergeyGer/Docentric-Copilot/issues/39) closed |
| V012-06 | Reference → IR table inference | **Deferred** to v0.13 | [#40](https://github.com/SergeyGer/Docentric-Copilot/issues/40) open |
| V012-07 | Real LibreOffice/Poppler Visual CI | **Passed** | [#41](https://github.com/SergeyGer/Docentric-Copilot/issues/41) closed |
| V012-08 | Playwright E2E | **Passed** | [#42](https://github.com/SergeyGer/Docentric-Copilot/issues/42) closed |
| V012-09 | Report retention/deletion | **Passed** | [#43](https://github.com/SergeyGer/Docentric-Copilot/issues/43) closed |
| V012-10 | Responsive + release documentation | **Passed** | [#44](https://github.com/SergeyGer/Docentric-Copilot/issues/44) closed |

`Deferred` is not `Passed`. Docentric AX runtime compatibility remains **`not_tested`** in every
v0.12 item.

## Open work — from GitHub Issues

Open issues are listed in ascending number. “Planned” means no release target is committed yet.

| Issue | Item | Area | Status |
| --- | --- | --- | --- |
| [#12](https://github.com/SergeyGer/Docentric-Copilot/issues/12) | Compound revision: one instruction, several targeted edits | Revision | Open — planned (P1) |
| [#13](https://github.com/SergeyGer/Docentric-Copilot/issues/13) | Mapping and validation diffs between versions | Revision | Open — planned (P1) |
| [#14](https://github.com/SergeyGer/Docentric-Copilot/issues/14) | Optional LibreOffice DOCX → PDF API renderer | Rendering | Open — planned (P2); renderer helpers exist, API endpoint does not |
| [#15](https://github.com/SergeyGer/Docentric-Copilot/issues/15) | Line-item product images | Quality | Open — planned (P2) |
| [#17](https://github.com/SergeyGer/Docentric-Copilot/issues/17) | Streamlit demo: upload your own DDSP | Demo | Open — planned (P3) |
| [#37](https://github.com/SergeyGer/Docentric-Copilot/issues/37) | Image-family benchmark expansion | Benchmark | **Partial** in v0.13; benchmark expansion open |
| [#40](https://github.com/SergeyGer/Docentric-Copilot/issues/40) | Reference-to-IR table inference and diagnostics | Reference | **Partial** in v0.13; edge cases open |
| [#53](https://github.com/SergeyGer/Docentric-Copilot/issues/53) | Word for the web targeted validation | Validation | **Deferred** — no Microsoft 365 access |
| [#54](https://github.com/SergeyGer/Docentric-Copilot/issues/54) | Product/technical videos | Docs | **Deferred** — no production/YouTube session |

### Deferred from v0.12 — target v0.13

- **#37 Image-family expansion.** The v0.12 dataset is frozen for the reproducible 288-run benchmark;
  adding cases would invalidate that artifact. v0.13 scope: company logo, product image with
  row/collection context, image collection, optional image, missing image, wrong-type decoy,
  static-asset vs dynamic-binding distinction, abstention instead of a false binding, subtype scorecard.
- **#40 Reference-to-IR table inference.** v0.12 deliberately keeps Table/Row/Cell material in
  `skipped[]` and does not claim table inference. v0.13 scope: Table/Row/Cell boundaries, header vs
  repeated rows, Repeat bound to collection scope with schema evidence, provenance, strict mode for
  ambiguous structure, best-effort diagnostics, and fixtures for simple/header+nested/empty tables.

## Delivered and closed

These issues are closed; they are kept here as the shipped record.

### v0.12.0

| Issue | Delivered |
| --- | --- |
| [#35](https://github.com/SergeyGer/Docentric-Copilot/issues/35) | Gold audit trail; AT-07 remains `partial` — no independent human review |
| [#36](https://github.com/SergeyGer/Docentric-Copilot/issues/36) | 288-run full benchmark with manifest, hashes, counters and technical-failure separation |
| [#38](https://github.com/SergeyGer/Docentric-Copilot/issues/38) | D365 11-document private regression; aggregate only |
| [#39](https://github.com/SergeyGer/Docentric-Copilot/issues/39) | Nested-table compact-v2 support, structural validator, repeat-alias scopes |
| [#41](https://github.com/SergeyGer/Docentric-Copilot/issues/41) | Real pinned LibreOffice/Poppler Visual CI |
| [#42](https://github.com/SergeyGer/Docentric-Copilot/issues/42) | Playwright E2E + failure artifacts + responsive checks |
| [#43](https://github.com/SergeyGer/Docentric-Copilot/issues/43) | Report retention TTL and delete API |
| [#44](https://github.com/SergeyGer/Docentric-Copilot/issues/44) | Version/docs alignment and release evidence |

### v0.11.0

| Issue | Delivered |
| --- | --- |
| [#24](https://github.com/SergeyGer/Docentric-Copilot/issues/24) | Deterministic adjudication, image-family adjudication, dataset provenance; no independent human review, AT-07 `partial` |
| [#25](https://github.com/SergeyGer/Docentric-Copilot/issues/25) | Candidate filtering, post-generation review, abstention; v0.12 precision 0.9535 |
| [#27](https://github.com/SergeyGer/Docentric-Copilot/issues/27) | Safe Reference → Generic Template IR; explicit skips; no table inference |
| [#28](https://github.com/SergeyGer/Docentric-Copilot/issues/28) | Independent visual reference diff; real renderer CI added in v0.12 |
| [#29](https://github.com/SergeyGer/Docentric-Copilot/issues/29) | SQLite persistence, reopen/export, delete/retention, browser E2E |
| [#30](https://github.com/SergeyGer/Docentric-Copilot/issues/30) | v0.11 hardening; superseded by V012-10 for v0.12 docs/version alignment |

Earlier delivered: [#16](https://github.com/SergeyGer/Docentric-Copilot/issues/16) docs/CI checks and
[#18](https://github.com/SergeyGer/Docentric-Copilot/issues/18) screenshots/demo video.

## Blocked — external evidence required

| Item | Blocking condition |
| --- | --- |
| Docentric AX adapter | Permitted format knowledge + a licensed verification environment |
| Verified Docentric AX compatibility | Independent execution of Field/List/Image/If inside D365 F&O with the Docentric AX plug-in |
| Word-fidelity pagination | A rendering stack that matches Microsoft Word; LibreOffice is explicitly not that |

## Explicitly out of scope

Word add-in, direct D365 F&O connection, SaaS billing, enterprise SSO, collaborative editing, and
Kubernetes without a measured need.

## How this page stays in sync

- **GitHub Issues is authoritative.** This page was checked against the tracker on **2026-11-06**:
  9 open issues (#12, #13, #14, #15, #17, #37, #40, #53, #54) and the closed v0.12/v0.11 items above.
- On every release and on every issue open/close/retarget, update this page and the repository copy
  [`docs/wiki/Roadmap.md`](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/wiki/Roadmap.md)
  in the same pull request, then publish with `python scripts/sync_wiki.py --push`.
- The repository [`ROADMAP.md`](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/ROADMAP.md)
  holds the engineering milestone view; this wiki page holds the issue-synced public view.
- Do not describe an issue as delivered until its acceptance criteria are met and the issue is closed.
  A deferred item keeps its issue open with a target version.
