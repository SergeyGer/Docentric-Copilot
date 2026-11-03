# Demo video v2 — what it proves

`docs/media/demo-v2.mp4` · 2:46 · 1920×1080 · 30 fps · English narration and captions.

| Scene | Claim | Evidence |
| --- | --- | --- |
| 1 | A brief becomes a finished document | compiled DOCX from the bundled quotation package |
| 2 | The schema is parsed, not guessed | normalized schema and sample data |
| 3 | Routing selects a provider that actually runs | saved run trace with provider, model, timestamps, usage |
| 4 | Models are compared on one fixed set | `benchmarks/live_report.json`, 6 cases × 3 providers, measured 2026-11-02 |
| 5 | A real DOCX is produced and paginated | LibreOffice rendering of the compiled file (labelled) |
| 6 | A visual defect is detected and repaired | `text_fit` warning → IR diff → after render |
| 7 | Revision is reviewable | V1/V2 diff and rollback |
| 8 | Limits are stated | `Docentric AX compatibility: not_tested` |

## What was live, what was deterministic

- Live provider calls: the benchmark rows for OpenAI (`gpt-6-sol`), Anthropic (`claude-sonnet-5-5`) and
  Gemini (`gemini-3.1-flash-lite`) come from real API runs recorded on 2026-11-02. Estimated spend for
  the benchmark: **$0.48**.
- Deterministic: the document fixtures, compilation, quality checks and optimization use the offline
  provider so the video is reproducible.
- LibreOffice rendering: used for the PDF pages. It is **not** evidence of Microsoft Word or Docentric
  pagination fidelity.
- Cost is shown as `N/A` when the model has no price entry; zero is reserved for the deterministic
  baseline.

## Reproduce

```bash
python benchmarks/live_evaluation.py --limit 6
PLAYWRIGHT_BROWSERS_PATH=.tools/pw-browsers python scripts/build_demo_video_v2.py
```

Compatibility with Docentric AX remains unverified and gated.
