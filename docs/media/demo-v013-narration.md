# Product Demo narration

## 1. Hook (16.6s)

A business brief should become a document a team can review, not a black box. One paragraph in, a reviewable DOCX out, with schema, validation and routing evidence attached. This is not a mock: the next scenes use a recorded live LLM plan and its trace.

## 2. Schema (14.4s)

Here is a synthetic package with sample data, parser diagnostics and a normalized field tree. The schema is typed, so every field the document can bind has a type and a source. Nothing is invented from the prompt alone.

## 3. Brief (12.6s)

The brief is the only input: plain language naming the fields, totals, VAT notice and footer. The planner turns each requirement into a typed field. No model is chosen by hand.

## 4. Template (13.9s)

The result is not prose. It is a Template IR: one section, sixteen typed blocks, a repeating line table and conditional notices. The same structure feeds validation, preview and the DOCX compiler.

## 5. Auto selected (10.9s)

Auto does the choosing. It classifies the brief, recommends a provider, and sends no manual override. The decision is recorded before the model runs.

## 6. Auto result (10.8s)

The live run selected Anthropic and executed Claude Sonnet. Recommendation, execution, match and fallback are separate recorded facts, with a run identifier.

## 7. Images (11.7s)

The image family is typed too. A company logo, a schema image, or one product image per repeated line item use the same binding model, with explicit fallback and aspect ratio.

## 8. Reference tables (11.3s)

Reference tables are read as geometry plus schema evidence: header, repeated row, footer total. Ambiguous and merged tables are refused with diagnostics instead of guessed.

## 9. Layout repair (22.9s)

Here is a layout defect: the description column is too narrow, the text wraps past its line budget, and the checker flags a text-fit warning. Optimize layout applies typed changes—rebalanced columns, a wider description and a smaller table font—then reruns the checks. The after render uses fewer lines. The change is reviewable in the diff, not hidden in a binary.

## 10. Version history (14.3s)

Every revision creates an immutable version. Compare versions names each changed field; restore brings either version back into the workspace. The version history, diff and rollback are part of the deliverable, not an afterthought.

## 11. Benchmark (14.0s)

The benchmark runs thirty-two cases across three providers and three repeats. Two hundred seventy-eight runs completed; two hundred seventy-four pass semantically, and ten Gemini technical failures are reported, not counted as passes.

## 12. Artifact (12.0s)

Download and open the file. The preview and the LibreOffice render are independent views of the same document, each labelled for what it proves. This is not a Word fidelity claim.

## 13. Closing (13.0s)

Docentric Copilot is open source under Apache. The schema, the live decision, the typed template and the evidence are all in the repository. Docentric AX compatibility is not tested.
