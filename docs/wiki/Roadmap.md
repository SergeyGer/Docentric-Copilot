# Roadmap

> What is done, what is deliberately deferred, and what is blocked by external evidence.

## Milestones

| Milestone | Scope | Status |
| --- | --- | --- |
| **M0 Feasibility** | Format research, licensing analysis, go/no-go | Done — path B recorded |
| **M1 Schema engine** | Safe DDSP ingestion, normalization, CLI | Done |
| **M2 AI planning** | Template IR, gateway, mapping, expressions, validators | Done |
| **M3 Compilation** | Generic DOCX, preview, golden files | Done |
| **M4 Web + CLI** | API, workspace, jobs, artifacts, Docker | Done |
| **M5 Release** | CI, security scans, docs, benchmarks, release | Done — latest v0.9.0 |
| **v0.10 P0** | D365 embedded schema, canonical binding resolver, gold benchmark, docs baseline | In progress — PR-01…PR-05 done; P1 work remains |

## Open work — tracked in issues

Every item below has an issue; the issue is the source of truth for status and acceptance criteria.

| Issue | Item | Area |
| --- | --- | --- |
| [#12](https://github.com/SergeyGer/Docentric-Copilot/issues/12) | Compound revision: one instruction, several targeted edits | Revision |
| [#13](https://github.com/SergeyGer/Docentric-Copilot/issues/13) | Mapping and validation diffs between versions | Revision |
| [#14](https://github.com/SergeyGer/Docentric-Copilot/issues/14) | Optional LibreOffice DOCX → PDF renderer | Quality |
| [#15](https://github.com/SergeyGer/Docentric-Copilot/issues/15) | Line-item product images | Quality |
| [#16](https://github.com/SergeyGer/Docentric-Copilot/issues/16) | Docs link checks, ADR index and wiki mirror in CI | Docs — delivered, kept for the audit trail |
| [#17](https://github.com/SergeyGer/Docentric-Copilot/issues/17) | Streamlit demo: upload your own DDSP | Demo |
| [#18](https://github.com/SergeyGer/Docentric-Copilot/issues/18) | Refresh screenshots and demo video | Demo — delivered in v0.4.1 |

Closed issues stay visible as evidence that the roadmap item shipped; nothing is deleted from the
list. Proposals that are not yet accepted do not get an issue.

## v0.10 status — Reference Template Intelligence

| Workstream | Status |
| --- | --- |
| PR-01 baseline docs and corpus manifest | Done — version strings and feature matrix aligned; package version not bumped |
| PR-02 D365 embedded schema extraction | Done — static `ProjectData`/XSD/`PreviewData` evidence with OOXML provenance |
| PR-03 canonical schema and binding resolver | Done — six exact statuses; duplicates and conflicts never resolve |
| PR-04 gold semantic dataset | Done — 32 versioned cases, 20/12 calibration/holdout, single-annotator labels (AT-07 partial) |
| PR-05 live benchmark and report | Done — 288/288 runs, $6.8849 verified + $0.2910 estimated, calibration/holdout separated, cost and error taxonomy |
| PR-06…PR-09 (IR projection, visual diff, persistence, hardening) | Implemented as v0.11 P1 (#26–#30), partial — see below |
| Docentric AX runtime | `not_tested` — unchanged |

## v0.11 P1 status — reference workflow (unreleased)

| Item | Status |
| --- | --- |
| #26 D365 evidence in ReferenceGraph | Done — unified `schema_field` provenance and exact `resolves_to` statuses; evidence coverage summary; public tests synthetic, corpus not re-run |
| #27 safe Reference → Generic Template IR | Done — partial subset (Field, Label, List→Repeat, If, Image); explicit `skipped[]`; strict/best-effort; no Table inference |
| #28 visual reference diff | Done — partial; LibreOffice rendering, not Word fidelity; `renderer_unavailable` never pass/fail; no real renderer in CI |
| #29 persistence/reopen/export | Done — partial; local SQLite TTL, JSON/HTML export, web `?id=`; no committed browser E2E |
| #30 hardening/docs | Done for this branch — ADR-0016, CHANGELOG/REFERENCE_TEMPLATES/EVALUATION/wiki/OpenAPI; version stays `0.10.0` under `[Unreleased]` |
| Docentric AX runtime | `not_tested` — unchanged; `target=docentric-ax` fail-closed |

Local D365 corpus (counts only): 11/11 documents with `projectdata` schema evidence; 246 bindings,
233 resolved with evidence, 4 `unknown_path`, 8 `unsupported_expression`, 1 `type_mismatch`, 0
`ambiguous`, 0 `schema_unavailable`. This is static evidence, not a runtime or model-quality claim.

## Now — hardening the MVP

| Item | Status |
| --- | --- |
| Replace `next lint` with the ESLint CLI before Next 16 | Planned |
| Strict Content-Security-Policy with nonces | Planned |
| Standalone Next.js server in the web image | Planned |
| Bump to Next 16 after the lint migration | Planned |
| Broader V4 visual checks | Planned |

## Next — deeper realism

| Item | Why it matters |
| --- | --- |
| Real DDSP fixtures (permitted) | The parser is currently validated on synthetic packages only |
| Hosted-provider evaluation baseline | Turns “works with a model” into a measured claim |
| Locale-aware number and date formatting | Documents are English-formatted today |
| More block kinds (group, summary fields, barcodes) | Expands the expressible layout space |
| PDF preview via a headless renderer | Removes the “HTML only” limitation |

## Blocked — external evidence required

| Item | Blocking condition |
| --- | --- |
| Docentric AX adapter | Permitted format knowledge + licensed verification environment |
| Verified compatibility metric | Independent execution of Field/List/Image/If |
| Word-fidelity pagination | A rendering stack that matches Word |

## Explicitly out of scope

Word add-in, direct D365 F&O connection, SaaS billing, enterprise SSO, collaborative editing,
Kubernetes without measured need.
