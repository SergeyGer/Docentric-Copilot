# technical narration

## 1. Technical Deep-Dive — v0.13 (10.2s)

This deep-dive explains how Docentric Copilot turns a brief into a checked Word document, what changed in version zero thirteen, and where the honest boundaries are.

## 2. Pipeline (16.8s)

The pipeline is deliberately boring. The parser normalizes the schema, the reference inspector builds evidence, the planner emits a typed Template IR, the validator checks structure, semantics and logic, and only then does the compiler produce DOCX.

## 3. Schema evidence (17.4s)

The schema layer is not a prompt dump. The parser records controls, types, collection scope and sample values. The planner receives bounded candidates with evidence, so a field can be recommended, but only the validator decides whether a path is legal.

## 4. Planner contract (16.1s)

The planner emits a typed Template IR or a compact transport representation that expands into it. Compact mode is not a second document model; it is schema-validated, expanded deterministically, and repaired only within a bounded budget.

## 5. Validation layers (18.4s)

Validation is layered. Structural rules catch malformed blocks, schema rules reject unknown paths, semantic rules check the brief, and logic rules enforce condition scope, collection nesting and image placement. A report is evidence, not an optimistic score.

## 6. Compiler and OOXML (18.8s)

The compiler owns OOXML. It writes sections, headers, footers, tables, relationships and media, then packages a deterministic DOCX. The preview uses the same IR and inheritance rules, so preview and Word output do not drift by design.

## 7. Live demo evidence (19.6s)

The deployed Streamlit demo was woken and exercised in Chromium. It reports version zero thirteen, commit one c b e zero seven three and IR one point two. Quotation, invoice and purchase order all download DOCX, and the hashes match the local deterministic build.

## 8. Template IR 1.2 (17.4s)

Template IR is the contract between AI and deterministic code. Version one point two adds the first-page header, image source and fallback policy, and table footer rows. Older payloads migrate deterministically; unknown versions are refused.

## 9. Image family (18.5s)

Images can come from schema data or from reviewed compile assets. Missing images follow an explicit fallback policy. The validator rejects wrong types and images outside the active collection scope, and the compiler preserves aspect ratio unless stretching is explicit.

## 10. Reference table inference (20.0s)

Table inference reads bounded DOCX geometry and joins it to schema evidence. It handles static headers, repeated rows, optional conditional cells, footer rows and a nested repeat under the outer row. Merged, ragged or ambiguous tables are blocking diagnostics, not guesses.

## 11. First-page and multi-section headers (15.0s)

The first-page header is a real Word header part selected by titlePg. Each IR section becomes a Word section; a null header inherits the previous section, an empty list clears it, and the preview follows the same inheritance.

## 12. Reference Evaluation (18.2s)

The reference evaluation is separate from the gold semantic benchmark. Seventeen official documents parse, sixteen reach import and fifteen compile. The two remaining pipeline failures are classified: an unenclosed nested collection and an unsupported-only document.

## 13. Final benchmark (20.9s)

The final benchmark uses thirty-two cases, three providers and three repeats. Two hundred seventy-eight runs completed, ten Gemini structured-output failures remain technical, and two hundred seventy-four runs pass semantically. Precision is zero point nine five one and total spend is four dollars eighteen.

## 14. Quality gates (15.7s)

Every change passes lint, typing, unit tests with an eighty-five percent coverage gate, browser E2E, a real LibreOffice visual diff and security analysis. The release workflow builds and verifies the wheel and the images.

## 15. Determinism and security (18.0s)

The demo runs on a deterministic mock provider and never needs a model key. Artifact uploads are bounded and signature-checked, provider errors are sanitized, and logs redact credentials. The benchmark records spend and technical failures separately from semantic quality.

## 16. Release evidence (18.3s)

The release is backed by a wheel, source archive, CI, visual diffs and a published evidence page. The deployed demo is verified, but Word for the web and the final videos remain external open tasks. Those gaps stay visible instead of being converted into a pass.

## 17. Reading the metrics (19.5s)

Read the benchmark carefully. Technical failures are excluded from semantic scoring but still reported. An accepted table means the inference layer produced IR, not that Microsoft Word renders it perfectly. A semantic pass is not a Docentric AX runtime compatibility proof.

## 18. Boundaries (19.6s)

The remaining gaps are external or explicit: Word for the web needs a human with Microsoft 365, videos need review and publishing, AT-07 remains partial, and Docentric AX runtime compatibility remains not tested. No semantic score is a runtime compatibility proof.
