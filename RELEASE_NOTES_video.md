# Demo video v3 — release notes

This release note accompanies `docs/media/demo-v3.mp4` (9.0 MiB),
`docs/media/demo-v3.srt`, `docs/media/thumbnail-v3.png`, `docs/media/narration-v3.md` and
`docs/media/scene-manifest-v3.json`. Nothing is committed or pushed; the files are in the working tree.
It supersedes the v2 video notes; `demo-v2.mp4` and its sidecars are left untouched.

## What changed from v2

- **Typed brief.** The routing scene now renders six frames of the recorded prompt panel, with the
  brief growing from an empty focused field to the full recorded 281-character text. The final typed frame
  holds the full brief for about four seconds. The routing result and the live trace are recorded,
  not re-run; the panel is labelled as re-typed for the animation.
- **General voiceover.** The narration no longer reads cents, dollars, latency seconds, token counts,
  per-provider scores or "6 of 6". Every figure is on screen and mapped to a source in the manifest.
  Total runtime is 02:46.
- **Zoomed document views.** The finished-document and before/after repair scenes use 130–155% crops
  centred on the items table, totals and Description column, with three-frame crossfades between
  zoom levels. They are not shown as full-page evidence.
- **Benchmark truthfulness.** The Gemini row is now the explicit category
  "Gemini — API quota exceeded; no valid run". No Gemini quality, latency or cost result is claimed.
  The OpenAI and Anthropic rows keep the measured `benchmarks/live_report.json` values.
- **Labels kept.** The closing line is still "Docentric AX compatibility: not tested", and every
  LibreOffice image is still labelled "LibreOffice rendering".

## What is live, and what is replay

**Verified live on 2026-11-03.** The multi-LLM table uses `benchmarks/live_report.json`: 6
cases, 3 providers and one live run per case/provider (18
attempts total), with an estimated spend of $0.478798 and 0 unknown-cost runs.
Models: `openai:gpt-6-sol`, `anthropic:claude-sonnet-5-5`, `gemini:gemini-3.1-flash-lite`. The routing
scene's executed model (`gpt-6-sol`, run `bench_6312bb882a834b97`) comes from the same report and its saved
trace.

**Deterministic or recorded (replay).** The prompt panel, schema explorer, revision diff and DOCX
preview are recorded workspace screenshots. The brief typing is a re-render of the recorded prompt
panel, not a screen recording. The DOCX artifact bytes (40,585) come from
`docs/media/demo-session.json`; the two-page count is recorded in
`docs/assets/preview-pages.png`. The LibreOffice before/after pages are the recorded 1241×1754
renders from LibreOffice Writer 25.2 + `pdftoppm`; this video does not re-render them. The optimize response
used for scene 6 was regenerated from the bundled `quotation-long-items` demo with the deterministic
mock planner and is saved as `docs/media/optimize-response.json`; no provider was called for it.

## Gemini quota caveat

`benchmarks/live_report.json` records 6 Gemini attempts, 0 valid runs, null
latency and null cost. The Gemini key is currently returning **HTTP 429 quota exceeded**, so the v3
table does not present Gemini as a quality result. The row says
"Gemini — API quota exceeded; no valid run", its metrics are dashes, and the footnote states that no
Gemini quality, latency or cost result is claimed. The narration does not mention Gemini or the
failure at all; it stays on the general comparison method. The other two provider rows are the real
measured values from the report. A dash is not $0.00.

## LibreOffice caveat

The page images labelled **LibreOffice rendering** are PDF pages rasterised from LibreOffice Writer
25.2 in the optional `api-pdf` image. They are an independent visual check. They are not Microsoft Word
pagination, and this video makes no Word fidelity claim. LibreOffice may substitute fonts and paginate
differently from Word or Docentric AX.

## Docentric AX compatibility

`Docentric AX compatibility: not tested.` The validation status remains `not_tested`; no licensed
Docentric environment was used. The closing scene uses the exact phrase "Docentric AX compatibility:
not tested" and the manifest records the `not_tested` session value.

## What the video deliberately does not claim

- No Gemini quality result, latency or cost while its API returns quota errors.
- No Word fidelity or identical pagination.
- No Docentric AX compatibility.
- No mock run presented as a live provider call.
- No API keys, prompts containing secrets or local filesystem paths in the narration or on screen.
- No screen-recording label: the typed brief is a re-render of a recorded panel, the cursor is a
  slide annotation, and screenshots are labelled by source (workspace capture, independent preview,
  LibreOffice rendering).

## Verification

The build script is `scripts/build_demo_video_v3.py`. It renders source slides at 2560×1440 and
downscales to 1920×1080 with ffmpeg. `ffprobe` reports H.264 video, AAC audio, 1920×1080, 30 fps and a
duration of 02:46. File sizes: video 9.0 MiB, SRT
3.4 KiB, thumbnail 364.2 KiB.

Reproduce with:

```bash
PLAYWRIGHT_BROWSERS_PATH=.tools/pw-browsers .venv/bin/python scripts/build_demo_video_v3.py
```
