# Demo v2 narration

Duration **02:46** · 1920×1080 · 30 fps · voice `en-US-GuyNeural` · measured data from `benchmarks/live_report.json` (2026-11-03).

The script is English only. Each scene is one paragraph; the SRT follows the same sentences.

## 1. Hook — 00:00–00:12

A business brief should become a document a team can review, not a black box. This is Docentric Copilot: quotation in, two-page DOCX out, with schema, validation and diff attached.

## 2. Data source and schema — 00:12–00:30

Everything starts with the customer's data. Here is a synthetic DDSP package with thirty-four fields across three sections and one repeating collection. Sample data and parser diagnostics are included. The schema is normalized, so every field the document can bind has a type and evidence.

## 3. Live adaptive routing — 00:30–00:55

Routing starts with complexity. The workspace panel calls this quotation brief ambiguous, recommends Anthropic under a thirty-cent budget, and asks for human review. But recommendation is not execution; the panel does not show which model ran. The live trace does: the benchmark's quotation case executed gpt-6-sol, compiled, and passed the validation gate in 19.4 seconds for 3.6 cents.

## 4. Multi-LLM benchmark — 00:55–01:17

Six cases, three providers, one run per case. gpt-6-sol and claude-sonnet-5-5 each produced six valid templates out of six, with p50 latency of 19.0 and 14.2 seconds. Cost per valid template: 3.3 and 4.7 cents. Gemini-3.1-flash-lite produced zero; its latency and cost are unknown, so the slide shows N/A, never zero.

## 5. DOCX artifact — 01:17–01:41

Download the DOCX and open it. The quotation is 40,585 bytes and two pages. On the left is the independent preview; on the right, page one as rendered by LibreOffice. Both are labelled for what they are. This is a LibreOffice rendering, not a Microsoft Word fidelity claim.

## 6. Visual defect to repair — 01:41–02:12

Here is the visual defect. The Description column is 62 millimetres at 9.5 points, and two cells wrap past four estimated lines. Optimize layout applies typed IR changes. Description widens to 88.7 millimetres by rebalancing the other columns, and the table font drops to 9.0 points. Seven IR fields change. The panel reruns the checks: text fit now passes, and the after image uses fewer lines. LibreOffice rendering, not Word pagination.

## 7. Revision V1/V2 — 02:12–02:32

Every edit creates an immutable version. V1 to V2 changed five IR fields, added none and removed none. The comparison names each changed path, and Restore version brings either pane back into the workspace. Diff and rollback, not a silent edit.

## 8. Closing — 02:32–02:46

Docentric Copilot is open source on GitHub under Apache 2.0. The demo, the benchmark and the evidence are in the repository. Docentric AX compatibility: not tested.
