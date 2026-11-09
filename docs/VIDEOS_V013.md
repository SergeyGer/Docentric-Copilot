# Demo videos — v0.13 production status

**Status: publish-ready drafts (2:36 and 5:11), not reviewed or published.**

| Video | Target | Draft | Publication |
| --- | --- | --- | --- |
| Product Demo | 2:30–3:00, 1080p, English voiceover + SRT | **2:36** | Awaiting human review and the maintainer's YouTube upload |
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
- The Word desktop screenshots supplied by the maintainer are used as a manual
  Word check. They are **not** Word for the web; the video says so in its limits.

## Assets

| Asset | Duration / role | Path |
| --- | ---: | --- |
| Product Demo | 2:36 | `docs/media/demo-v013.mp4` |
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
| 0:00–0:22 | A brief is not a document | Word desktop pages 1 and 2 side by side |
| 0:22–0:38 | Start with evidence | Live invoice plan, schema excerpt |
| 0:38–0:55 | The schema is the source of truth | Requirements and schema excerpt |
| 0:55–1:08 | The brief becomes typed requirements | Live plan/requirements |
| 1:08–1:25 | Every binding is visible | Mapping review |
| 1:25–1:39 | One structure, two outputs | Preview and Download DOCX |
| 1:39–1:55 | The download is evidence | Preview/download, artifact context |
| 1:55–2:08 | The logo stays on page one | Word page 1 |
| 2:08–2:20 | Later pages keep the identity | Word page 2 |
| 2:20–2:36 | The brief became a checked document | Document output and close |

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
13. Reference pipeline: 17 parsed → 16 imported → 15 compiled.
14. Benchmark: precision 95.1%, semantic pass 98.6%, technical failures separated.
15. Limits: Word for the web pending, videos not published, AT-07 partial, AX runtime `not_tested`.
16. Close.

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

Word for the web remains a separate open item (#53); the supplied Word desktop
evidence does not close it.
