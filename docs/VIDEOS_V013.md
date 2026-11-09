# Demo videos — v0.13 production status

**Status: publish-ready drafts (2:58 and 5:11), not reviewed or published.**

| Video | Target | Draft | Publication |
| --- | --- | --- | --- |
| Product Demo | 2:30–3:00, 1080p, English voiceover + SRT | **2:58** | Awaiting human review and the maintainer's YouTube upload |
| Technical Deep-Dive | 5–7 min, 1080p, English voiceover + SRT | **5:11** | Same |

The maintainer will publish both videos to YouTube and provide the links. This
repository prepares the encoded assets, narration, SRT and thumbnails; it does
not perform the upload.

## Content rules applied

- No spoken version numbers and no version numbers on screen.
- No bullet-point slides and no narration that reads a bullet list.
- Real UI screenshots, real Word document pages, real DOCX package evidence.
- Product story is problem → solution: a brief is not a document; the demo shows
  the plan, review, preview, download and the resulting pages in Word.
- Technical story uses professional Mermaid diagrams rendered from
  `docs/wiki/Architecture.md`: planning path, compilation path, request
  lifecycle, Template IR contract, block taxonomy and validation ladder. Charts
  use the committed benchmark/reference JSON, not hand-typed numbers.
- The maintainer's Word desktop evidence is documented separately; the product
  video deliberately does **not** use those screenshots or mention the
  page-two logo detail.

## Assets

| Asset | Duration / role | Path |
| --- | ---: | --- |
| Product Demo | 2:58 | `docs/media/demo-v013.mp4` |
| Technical Deep-Dive | 5:11 | `docs/media/technical-v013.mp4` |
| Product SRT | — | `docs/media/demo-v013.srt` |
| Technical SRT | — | `docs/media/technical-v013.srt` |
| Product narration | — | `docs/media/demo-v013-narration.md` |
| Technical narration | — | `docs/media/technical-v013-narration.md` |
| Product thumbnail | 1280×720 | `docs/media/demo-v013-thumb.png` |
| Technical thumbnail | 1280×720 | `docs/media/technical-v013-thumb.png` |
| Manifest / hashes | — | `docs/media/v013-video-kit.json` |
| Upload checklist | — | `docs/VIDEO_PUBLISH_CHECKLIST_V013.md` |

Rebuild:

```bash
PLAYWRIGHT_BROWSERS_PATH=.tools/pw-browsers \
  python scripts/build_v013_videos.py --write
```

The builder also renders the Wiki diagrams with
`scripts/render_wiki_diagrams.py` and the evidence charts with
`scripts/build_v013_charts.py`.

## Product Demo — actual sequence

| Time (approx.) | Scene | Visual |
| --- | --- | --- |
| 0:00–0:17 | Hook / business problem | Two-page quotation preview, 274/278 semantic passes, 32×3×3 |
| 0:17–0:31 | Grounded schema | Live schema explorer, typed fields and sample data |
| 0:31–0:44 | Brief typing | Recorded live prompt panel, 281 characters typed visibly |
| 0:44–0:58 | Typed template | 12 requirements, 16 IR blocks, repeating table, conditions |
| 0:58–1:08 | Auto selected | "Let the router choose", no provider override |
| 1:08–1:19 | Auto decision | "Auto picked the model. It ran." Router match, fallback false |
| 1:19–1:31 | Image family | Product image per repeated row |
| 1:31–1:42 | Reference tables | Source table → typed inferred table with footer |
| 1:42–2:05 | Layout repair | Before/after LibreOffice render, text-fit warning → pass |
| 2:05–2:19 | Version history | V1/V2 diff, changed IR paths, restore |
| 2:19–2:33 | Benchmark | 32 cases × 3 × 3, 274/278 semantic, 95.1% precision |
| 2:33–2:45 | Artifact | Independent preview and LibreOffice render |
| 2:45–2:58 | Closing | Open source, evidence first, AX not tested |

The brief/template and Auto scenes use the **recorded live Anthropic plan** in
`docs/media/auto-plan-response.json` (run `run_6c3e5b0fc256424c8549`), not the
offline Streamlit mock. A **new live call** is provided separately:
`docs/media/live-v013/live-call.mp4` (21 s, run `run_e056896782cf4fb2b96d`).

## Separate live LLM call

A new paid live Auto call was recorded separately from the main product cut:

| Field | Value |
| --- | --- |
| File | `docs/media/live-v013/live-call.mp4` (21 s, 1600×940, silent screen capture) |
| Run | `run_e056896782cf4fb2b96d` |
| Model | `claude-sonnet-5-5` (Anthropic), match / no fallback |
| Result | structural, semantic and logical validation passed; visual skipped; AX `not_tested` |
| Elapsed | 11.24 s model call |
| Evidence | `docs/media/live-v013/manifest.json`, `plan-response.json`, `live-result.png` |

It shows the real web workspace from the empty state through Auto selection, Plan,
the routing spinner and the decision card. It has no narration and is optional as
a separate insert; it is not claimed to be part of the 2:58 cut.

## Technical Deep-Dive — actual sequence

1. Architecture: planning path with the narrow AI boundary.
2. Architecture: compilation path, validation and independent preview.
3. Parser and normalized schema.
4. Request lifecycle sequence diagram.
5. Live plan and candidate evidence.
6. Preview renderer.
7. Template IR contract: document → section → block → table/repeat/condition/image.
8. Block taxonomy.
9. Validation ladder: V1–V3 block compilation; V4 sample-data visual check; V5 compatibility remains `not_tested`.
10. DOCX package: real headers, footers and media parts.
11. First-page header in the Word desktop check.
12. Table classification: 30 observed, 15 accepted, 15 deliberately unsupported.
13. Layout repair: text-fit warning → typed changes → pass.
14. Version history: V1/V2 diff and restore.
15. Benchmark: precision 95.1%, semantic pass 98.6%, technical failures separated.
16. Limits: videos not published, AT-07 partial, AX runtime `not_tested`; Word Web itself was not performed (the Word desktop check is separate).
17. Close.

## Production contract

- 1920×1080, 30 fps, H.264 MP4, AAC 48 kHz stereo.
- English Edge TTS voiceover and English SRT.
- Product Demo: 2:30–3:00. Technical Deep-Dive: 5:00–7:00.
- Every shown number comes from a committed generated artifact.
- No compatibility claim beyond the evidence.

## Publication gate

The drafts are ready for the maintainer's review. T-02/T-03 become **Passed** only
after a human watches them end-to-end and the YouTube links are recorded in the
README, release notes and issue [#54](https://github.com/SergeyGer/Docentric-Copilot/issues/54).
The manifest records `human_review: false` and `youtube_published: false`.

Word for the web itself remains untested; #53 was closed by the maintainer on
the supplied Word desktop evidence.
