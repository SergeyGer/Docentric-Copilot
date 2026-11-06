# Demo videos — v0.13 status and production plan

**Status: Deferred, not produced.**

The v0.13 specification makes two videos P0 deliverables:

| Video | Target | Status |
| --- | --- | --- |
| Product Demo | 2:30–3:00, 1080p, English voiceover + subtitles | **Not produced** |
| Technical Deep-Dive | 5–7 min, 1080p, English voiceover + subtitles | **Not produced** |

## Why this is deferred

- The existing `docs/media/demo-v4.mp4` is a v0.11/v0.12-era video. Relabelling it
  as a v0.13 product demo would show stale features and benchmark numbers; it is
  not reused.
- Publishing requires a YouTube channel/OAuth session that this environment does
  not have. Uploading is an external action, not a repository operation.
- A 5–7 minute technical video needs a final, reviewed code walkthrough and
  narration; producing it before the V013-03 code is final would create
  the same staleness problem.

The videos are tracked by issue [#54](https://github.com/SergeyGer/Docentric-Copilot/issues/54).
Until they exist, v0.13 must not claim that every P0 deliverable is complete.

## Product Demo — required storyboard

| Time | Scene | Evidence to show |
| --- | --- | --- |
| 0:00–0:15 | Problem | Brief + data source, no Word design session |
| 0:15–0:35 | Upload/inspect | Real DDSP, schema fields, collections |
| 0:35–1:05 | Plan/mapping | Candidate evidence, confidence, abstention |
| 1:05–1:30 | Preview/DOCX | First-page logo, later-page header without logo |
| 1:30–1:55 | Images/table | Product image per row, dynamic table rows |
| 1:55–2:15 | Validation/evidence | V1–V3, compatibility `not_tested` |
| 2:15–2:45 | Reference import | Table inference and explicit skips |
| 2:45–3:00 | Honest limits | Runtime not tested; AT-07 partial; no false claim |

Narration and on-screen numbers must be generated from the **final** release
artifacts, not typed by hand.

## Technical Deep-Dive — required outline

1. Architecture: parser → resolver → planner → validator → compiler → preview.
2. Template IR 1.1: first-page header, image source/fallback, migration.
3. Deterministic guards: no raw XPath, no guessed binding, strict/abstain.
4. Image family: schema/static/collection/fallback/aspect, wrong-scope decoys.
5. Table inference: DOCX geometry + schema evidence; diagnostics and strict mode.
6. First-page header OOXML: `w:titlePg`, `headerReference type="first"`, parts/relationships.
7. Reference Evaluation: definitions/denominators and honest limitations.
8. Quality gates: lint/types/tests/E2E/visual/security; release evidence.
9. What is still not tested: Docentric AX runtime, Word Desktop, Word Web.

## Production contract

- 1920×1080, 30 fps, H.264 MP4, AAC 48 kHz stereo.
- English voiceover, English SRT; no unverified compatibility claim.
- Every benchmark number read from a committed generated artifact.
- Product Demo: 2:30–3:00. Technical Deep-Dive: 5:00–7:00.
- Output files: `docs/media/demo-v013.mp4`, `demo-v013.srt`,
  `technical-v013.mp4`, `technical-v013.srt`.
- README links both; release assets include both; YouTube publication is a
  separate, credentialed step.

## What would change this status

Both MP4/SRT pairs exist, a human has watched them end-to-end, every shown
number matches the release evidence, and the YouTube URLs are recorded in the
README and release notes. Until then the status stays **Deferred**.
