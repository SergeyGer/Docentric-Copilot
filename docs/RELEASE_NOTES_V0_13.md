# Docentric Copilot v0.13.0 — images, tables and first-page headers

**Release tag: `v0.13.0`.** **Compatibility: `not_tested`.** This release produces generic DOCX documents. It does not claim
Docentric AX runtime compatibility.

## Highlights

- **Template IR 1.2** with `Section.first_page_header`, image source/fallback/aspect fields, and
  `Table.footer_rows`; 1.0/1.1 payloads migrate automatically.
- **First-page header**: real Word `titlePg`, separate first-page header parts, per-section
  first-page headers and inheritance, matching preview. Multi-section documents are emitted as real
  Word sections.
- **Image family**: static and schema images, images in Repeat/table rows, optional/missing fallback,
  wrong-type/wrong-scope rejection, product-image candidate scoping, aspect-ratio control.
- **Reference table inference**: static header/repeated rows, optional `If` cells, footer rows,
  nested tables (including a nested repeat under the outer row), strict/best-effort diagnostics.
- **Feature Coverage Matrix** and **Reference Evaluation** over the official 17-document corpus.
- **Live demo**: version/execution panel, deterministic confirmation handling that unblocks the
  Sales Quotation DOCX download, AppTest regression.

## V013 status

| ID | Deliverable | Status |
| --- | --- | --- |
| V013-01 | Feature Coverage Matrix | **Passed** |
| V013-02 | Image family | **Passed** |
| V013-03 | Reference-to-IR table inference | **Passed** |
| V013-04 | First-page header + preview consistency | **Passed** |
| V013-05 | Reference Evaluation | **Passed** |
| V013-06 | Word for the web targeted validation | **Deferred** — no Microsoft 365/OneDrive access (#53) |
| V013-07 | Live Demo reliability/UX | **Passed** |
| V013-08 | Final quality benchmark | **Passed** |
| V013-09 | Product Demo video | **Deferred** — no production/YouTube session (#54) |
| V013-10 | Technical Deep-Dive video | **Deferred** — no production/YouTube session (#54) |

`Deferred` is not `Passed`. Docentric AX runtime compatibility remains `not_tested`; AT-07 remains
`partial` because the gold labels were not independently reviewed by a human.

## Evidence

- [Release evidence](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/RELEASE_EVIDENCE_V0_13.md)
- [Feature coverage](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/FEATURE_COVERAGE_V013.md)
- [Reference evaluation](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/REFERENCE_EVALUATION_V013.md)
- [Benchmarks §11](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/BENCHMARKS.md#11-v013-full-benchmark-v013-08)
- [Template IR 1.2](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/TEMPLATE_IR.md)

## Limitations

- Word for the web and the two videos are Deferred; see issues #53/#54.
- Multiple bound table row shapes are diagnosed as ambiguous rather than guessed.
- No Docentric AX runtime execution; no Word Desktop compatibility claim; LibreOffice is not Word.
- AT-07 is partial; labels are owner-authored with a deterministic proxy.
- SQLite storage remains single-process.

The benchmark result and manifest are committed with the release; see the release evidence for
counters, hashes and the exact run commit.
