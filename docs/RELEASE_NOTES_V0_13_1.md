# Docentric Copilot v0.13.1 — corrective diagnostics and evidence

**Release tag:** `v0.13.1`. **Compatibility:** `not_tested` with Docentric AX Runtime.
This patch produces generic DOCX documents and does not claim Docentric AX or Word
Desktop compatibility.

v0.13.1 is a corrective patch on top of the v0.13.0 feature release. It makes the
remaining v0.13 audit findings explicit and reproducible. It does **not** close the
P0 Word for the web and video tasks: they remain Deferred external dependencies.

## What changed

- **Reference import boundary:** an unenclosed nested collection is no longer
  emitted at document root; the import records `NESTED_COLLECTION_WITHOUT_PARENT`
  and the compiler refusal is covered by a regression test.
- **Table inference outcomes:** every observed body table gets an outcome
  (accepted / deliberately unsupported / defect / not evaluable) and reason codes.
  Merged/ragged cells are explicitly refused instead of accepted.
- **Empty conditional cells:** a table cell with an `If` control and no supported
  child block is no longer constructed with an empty `then_blocks`.
- **Reference Evaluation:** both pipeline failures are classified with tests; the
  table classification is 30 observed / 15 accepted / 15 deliberately unsupported
  / 0 defects / 0 not evaluable.
- **Gemini failures:** the 10 v0.13 `structured_output` failures are classified
  against the 4 v0.12 failures; no contract was relaxed.
- **Documentation:** Release Evidence now states Template IR 1.2; feature matrix,
  changelog and nested-repeat limitations are aligned.
- **T-08:** the deployed Streamlit demo was woken and verified with Playwright:
  v0.13.0 metadata, commit `1cbe073`, IR 1.2, deterministic mode, three DOCX
  downloads whose hashes match the local build.
- **Evidence kits:** a synthetic Word Web kit (DOCX/LibreOffice PDF/page PNGs) and
  draft Product/Technical videos (publish-ready drafts, 1080p, SRT) are committed.

## Still Deferred

- **V013-06 / #53 — Word for the web:** no Microsoft 365/OneDrive session; the
  local kit is not Word Web evidence.
- **V013-09/V013-10 / #54 — videos:** drafts exist, but there is no human review,
  final polish or YouTube publication; Product Demo still needs T-01.

AT-07 remains `partial`. Docentric AX runtime compatibility remains `not_tested`.

## Verification

- Main CI: Python lint/types/tests, Web, Security, CodeQL, E2E, Visual Diff, Docker.
- Release workflow: builds and verifies the wheel/sdist and both images.
- Benchmark numbers are unchanged from v0.13.0 (the planner did not change);
  reference-evaluation and table diagnostics were rerun on the final code.

## Artifacts

- `docentric_copilot-0.13.1-py3-none-any.whl`
- `docentric_copilot-0.13.1.tar.gz`

Full evidence: [RELEASE_EVIDENCE_V0_13_1](RELEASE_EVIDENCE_V0_13_1.md).
