# Demo video v4 — release notes

This release note accompanies `docs/media/demo-v4.mp4` (9.6 MiB),
`docs/media/demo-v4.srt`, `docs/media/thumbnail-v4.png`, `docs/media/narration-v4.md`,
`docs/media/scene-manifest-v4.json`, `docs/media/auto-plan-response.json` and the live captures
`docs/assets/auto-mode-selected.png` and `docs/assets/auto-routing-result.png`.
Nothing is committed or pushed; the files are in the working tree. It supersedes the v3 video notes;
`demo-v2.mp4`, `demo-v3.mp4` and their sidecars are left untouched.

## What changed from v3

- **New Auto-routing scene (00:40–00:58).** The scene opens on the
  real workspace with routing switched to Auto (before Plan), then shows the real decision card from the
  live plan: complexity, recommendation, executed provider/model, match/fallback and run id. It sits
  between the brief and the benchmark.
- **Benchmark rebuilt for the 20-case report.** The scene reads `benchmarks/live_report.json`
  (20 cases × 2 repeats, 3 providers) and shows exactly three large metrics
  per provider: valid templates, p50 latency and cost per valid template. The report recommends
  **openai**, and that row carries the recommendation badge.
- **Kept from v3.** Six-frame typed-brief animation, 130–155% zoomed document and repair crops with short
  crossfades, general narration (no cents, latency seconds or token counts spoken), the LibreOffice label
  and the closing line "Docentric AX compatibility: not tested". Runtime is 02:46.

## The live Auto capture

The Auto scene is a real, once-only capture from the workspace, not a re-render:

- Run id `run_6c3e5b0fc256424c8549`; one `POST /api/v1/templates/plan` request with `routing: "auto"`, HTTP 200.
- Router complexity: **ambiguous**; recommendation: **anthropic · provider default**; executed:
  **anthropic · claude-sonnet-5-5**; match: **true**; fallback:
  **false**.
- The router's recommended model is `provider default` (the router names the provider, not a model);
  the executed model is the provider default resolved by the gateway and is shown separately.
- The plan returned 12 mapped requirements (9 confirmed, 2 schema-valid, 1 needs review) and passed
  structural, semantic and logical validation; visual is skipped and Docentric compatibility is
  `not_tested`.
- Estimated provider cost for this single plan: **$0.055766** (from the API usage block). No retry was made.
- Raw response: `docs/media/auto-plan-response.json` (credentials excluded); trace:
  `docs/media/runs/run_6c3e5b0fc256424c8549.json`.

Capture assets are 1600×1000 screenshots: `docs/assets/auto-mode-selected.png` (Auto active, before Plan)
and `docs/assets/auto-routing-result.png` (the Routing decision card). The video crops them for legibility;
the card is not redrawn.

## Benchmark values

`benchmarks/live_report.json` was generated 2026-11-03. 20 cases × 2 repeats =
40 runs per provider. The table shows:

| Provider | Model | Valid templates | p50 | Cost / valid template |
| --- | --- | --- | --- | --- |
| openai (recommended) | gpt-6-sol | 40/40 | 16.6 s | $0.0309 |
| anthropic | claude-sonnet-5-5 | 40/40 | 12.2 s | $0.0428 |
| gemini | gemini-3.6-flash · compact v2 | 38/40 | 4.1 s | $0.0035 (estimated) |

The table reads `valid_runs`, `latency_ms.p50` and `cost_per_valid_template_usd` directly from the
report; cost per valid template is not recomputed. Gemini's cost is an **estimated proxy** because its
price is unavailable; the report records two invalid Gemini runs (38/40 valid). The benchmark's own
budget line records `$3.08` total spend across its 120 attempts; that
is benchmark spend, not this video capture.

## What is live, and what is replay

**Live.** The Auto plan described above, captured once on 2026-11-03. The benchmark table is the
recorded live report generated on 2026-11-03.

**Deterministic or recorded (replay).** The prompt panel, schema explorer, revision diff and DOCX
preview are recorded workspace screenshots. The brief typing is a re-render of the recorded prompt panel,
not a screen recording. The DOCX artifact bytes (40,585) come from
`docs/media/demo-session.json`; the two-page count is recorded in `docs/assets/preview-pages.png`.
The LibreOffice before/after pages are the recorded 1241×1754 renders from LibreOffice Writer 25.2 +
`pdftoppm`; this video does not re-render them. The optimize response used for the repair scene was
regenerated from the bundled `quotation-long-items` demo with the deterministic mock planner and is saved
as `docs/media/optimize-response.json`; no provider was called for it.

## Gemini compact v2 caveat

Gemini ran the benchmark through the compact IR v2 path (`compact_version: v2`, auto-selected by the
report). It returned 38 valid templates out of 40; two runs are
schema-invalid. Its p50 is measured, but its cost per valid template is an **estimated** proxy, and the
table labels it "estimated". The footnote states that a dash/na means unavailable; the table has no
invented zero.

## LibreOffice caveat

The page images labelled **LibreOffice rendering** are PDF pages rasterised from LibreOffice Writer
25.2 in the optional `api-pdf` image. They are an independent visual check. They are not Microsoft Word
pagination, and this video makes no Word fidelity claim. LibreOffice may substitute fonts and paginate
differently from Word or Docentric AX.

## Docentric AX compatibility

`Docentric AX compatibility: not tested.` The validation status remains `not_tested`; no licensed
Docentric environment was used. The closing scene uses the exact phrase and the manifest records the
`not_tested` value from the recorded session.

## What the video deliberately does not claim

- No Word fidelity or identical pagination.
- No Docentric AX compatibility.
- No mock run presented as a live provider call.
- No API keys, secret values or local filesystem paths in narration, SRT or on-screen text.
- No re-drawn Auto decision card: the card in the video is a crop of the live 1600×1000 capture.
- No screen-recording label: the typed brief is a re-render, the cursor is a slide annotation, and
  screenshots are labelled by source (live workspace capture, independent preview, LibreOffice rendering).

## Verification

The build script is `scripts/build_demo_video_v4.py`. It renders source slides at 2560×1440 and
downscales to 1920×1080 with ffmpeg. `ffprobe` reports H.264 video, AAC audio, 1920×1080, 30 fps and a
duration of 02:46. File sizes: video 9.6 MiB, SRT
3.5 KiB, thumbnail 370.0 KiB.

Reproduce with:

```bash
PLAYWRIGHT_BROWSERS_PATH=.tools/pw-browsers .venv/bin/python scripts/build_demo_video_v4.py
```
