# Demo v4 narration

Duration **02:46** · 1920×1080 · 30 fps · voice `en-US-GuyNeural` · benchmark data from `benchmarks/live_report.json` (2026-11-03).

The script is English only and deliberately general: no cents or dollars, no latency seconds, no token counts and no per-provider scores are read aloud. All figures appear on screen and are mapped to their sources in `scene-manifest-v4.json`.

The Auto scene is the one live plan captured for this video. It shows the recorded routing decision: complexity, recommendation, executed provider/model, match/fallback and run id. The narration says that Auto chooses and executes; it does not read out prices, latency or token counts.

The benchmark scene renders the 20-case, 2-repeat, 3-provider report. Gemini ran the compact v2 path and its cost per valid template is an estimated proxy; the table labels it and the footnote defines dash/na as unavailable.

## 1. Hook — 00:00–00:13

A business brief should become a document a team can review, not a black box. This is Docentric Copilot: a quotation brief in, a reviewable DOCX out, with schema, validation and version history attached.

## 2. Data source and schema — 00:13–00:28

Here is a synthetic package with sample data, parser diagnostics and a normalized field tree. The schema is typed, so every field the document can bind has a type and a source. Nothing is invented from the prompt alone.

## 3. Brief — 00:28–00:41

The brief is the only input: plain language naming the fields, the totals, the VAT notice and the footer. The planner turns each requirement into a typed field. No model is chosen by hand.

## 4. Auto routing — 00:41–00:57

Auto does the choosing. It classifies the brief, recommends a provider, and then calls it. The decision card records the recommendation, the model that ran, whether they matched, and the run identifier. A recommendation is not a promise; execution is.

## 5. Multi-LLM benchmark — 00:57–01:20

The benchmark runs one fixed case set through every configured provider, twice. Each row reports valid templates, median latency and the cost of a valid template. The numbers are read straight from the report, and the recommendation follows the report's own policy. These are observations, not a significance claim.

## 6. DOCX artifact — 01:20–01:44

Download the document and open it. The preview and the LibreOffice render are independent views of the same file, and each is labelled for what it is. The preview checks content and field binding; the LibreOffice page checks an independent render. This is not a Microsoft Word fidelity claim, and not a claim about Docentric AX compatibility.

## 7. Visual defect to repair — 01:44–02:15

Here is the defect. The description column is too narrow, so the text wraps past the line budget, and the checker flags a text-fit warning. Optimize layout applies typed changes to the template: it rebalances the columns, widens the description and adjusts the table font. The panel reruns the checks, and the after render uses fewer lines. The change is reviewable in the diff, not hidden in a binary. This is a LibreOffice rendering, not Word pagination.

## 8. Revision V1/V2 — 02:15–02:32

Every edit creates an immutable version. Compare versions names each changed field, and Restore version brings either revision back into the workspace. The diff and rollback are part of the deliverable, not an afterthought. A reviewer can see exactly what changed and undo it.

## 9. Closing — 02:32–02:46

Docentric Copilot is open source on GitHub under the Apache license. The demo, the live Auto decision, the benchmark and the evidence are in the repository. Docentric AX compatibility: not tested.
