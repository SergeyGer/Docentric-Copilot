# Demo v3 narration

Duration **02:46** · 1920×1080 · 30 fps · voice `en-US-GuyNeural` · measured data from `benchmarks/live_report.json` (2026-11-03).

The script is English only and deliberately general: no cents or dollars, no latency seconds, no token counts and no per-provider scores are read aloud. All figures appear on screen and are mapped to their sources in `scene-manifest-v3.json`.

The Gemini benchmark row shows its actual result (3 of 6 valid; the rest hit output or API limits). The voiceover does not mention the failure or claim any Gemini quality result.

## 1. Hook — 00:00–00:14

A business brief should become a document a team can review, not a black box. This is Docentric Copilot: a quotation brief in, a reviewable DOCX out, with schema, validation and version history attached.

## 2. Data source and schema — 00:14–00:30

Here is a synthetic package with sample data, parser diagnostics and a normalized field tree. The schema is typed, so every field the document can bind has a type and a source. Nothing is invented from the prompt alone.

## 3. Brief and adaptive routing — 00:30–00:54

The brief is the only input. It says what the document must contain, and the planner maps each requirement to the schema. Routing weighs that brief and recommends a provider, but a recommendation is not execution. The live trace records the model that actually ran, and the validation gate it passed. You do not have to guess which model to use.

## 4. Multi-LLM benchmark — 00:54–01:16

The benchmark runs a fixed set of cases through each provider and records what came back. The table is read straight from the live report: valid templates, latency, and what each valid template cost. Cost is derived from measured spend and valid runs. It is an observation, not a significance claim, and the slide keeps the caveats visible.

## 5. DOCX artifact — 01:16–01:42

Download the document and open it. The preview and the LibreOffice render are independent views of the same file, and each is labelled for what it is. The preview checks content and field binding. The LibreOffice page checks an independent render. This is a LibreOffice rendering, not a Microsoft Word fidelity claim, and not a claim about Docentric AX compatibility.

## 6. Visual defect to repair — 01:42–02:14

Here is the defect. The description column is too narrow, so the text wraps past the line budget, and the checker flags a text-fit warning. Optimize layout applies typed changes to the template: it rebalances the columns, widens the description and adjusts the table font. The panel reruns the checks, and the after render uses fewer lines. The change is reviewable in the diff, not hidden in a binary. This is a LibreOffice rendering, not Word pagination.

## 7. Revision V1/V2 — 02:14–02:31

Every edit creates an immutable version. Compare versions names each changed field, and Restore version brings either revision back into the workspace. The diff and rollback are part of the deliverable, not an afterthought. A reviewer can see exactly what changed and undo it.

## 8. Closing — 02:31–02:46

Docentric Copilot is open source on GitHub under the Apache license. The demo, the benchmark and the evidence are in the repository. Docentric AX compatibility: not tested.
