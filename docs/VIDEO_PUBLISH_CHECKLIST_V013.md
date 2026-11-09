# Video upload checklist

The maintainer publishes both videos. After uploading, send the two YouTube URLs
so they can be recorded in the README, release notes, `VIDEOS_V013.md` and
issue [#54](https://github.com/SergeyGer/Docentric-Copilot/issues/54).

## Files

| Upload | File | Thumbnail | Captions |
| --- | --- | --- | --- |
| Product Demo | `docs/media/demo-v013.mp4` | `docs/media/demo-v013-thumb.png` | `docs/media/demo-v013.srt` |
| Technical Deep-Dive | `docs/media/technical-v013.mp4` | `docs/media/technical-v013-thumb.png` | `docs/media/technical-v013.srt` |

1920×1080, H.264/AAC, 30 fps. Product Demo 2:37; Technical Deep-Dive 5:11.

## Suggested YouTube titles

- `Docentric Copilot — from a business brief to a checked Word document`
- `Docentric Copilot — technical deep-dive: typed IR, validation and DOCX`

No program version in the title or narration.

## Suggested description (Product Demo)

```text
A business brief and a DDSP data source become a reviewed, validated Word
document. The demo shows the plan, binding review, preview, download and the
resulting invoice pages in Microsoft Word.

Generic DOCX output only. Docentric AX runtime compatibility is not tested.
Microsoft Word desktop was used for the manual page check; Word for the web is
not claimed.

Docs: https://github.com/SergeyGer/Docentric-Copilot
```

## Suggested description (Technical Deep-Dive)

```text
Architecture and implementation walkthrough: deterministic core, narrow AI
boundary, typed Template IR, validation levels, OOXML compilation, linked
tables, first-page headers, reference evaluation and benchmark evidence.

Generic DOCX output only. Docentric AX runtime compatibility is not tested;
AT-07 remains partial. The diagrams are rendered from the repository Wiki.

Docs: https://github.com/SergeyGer/Docentric-Copilot
```

## Chapters

Product Demo:

```text
00:00 From a business brief to a reviewable DOCX
00:17 Grounded in the customer's own schema
00:31 One paragraph in. Typed requirements out.
00:44 The brief becomes a typed template
00:58 Let the router choose
01:08 Auto picked the model. It ran.
01:19 An image per repeated row
01:31 A reference table becomes typed IR
01:42 Seventeen documents. Three outcomes.
01:58 One case set. Three providers. Three repeats.
02:12 Download. Open. Check.
02:24 Open source. Evidence first.
```

Technical Deep-Dive:

```text
00:00 One deterministic core
00:19 The contract has two paths
00:35 The parser turns a package into a schema
00:53 A request is a chain of contracts
01:12 Evidence before generation
01:26 The preview is an independent rendering
01:41 A small typed document model
01:57 Every block has one legal shape
02:18 The gate is explicit
02:41 Compile only after the gate
02:58 The compiler owns OOXML
03:14 First-page headers are real parts
03:30 Tables are inferred, or refused
03:51 Seventeen documents, three outcomes
04:18 Quality is measured, not asserted
04:44 The proof stops where the evidence stops
05:03 One deterministic core. A narrow AI boundary.
```

## After upload

1. Add both URLs to `docs/VIDEOS_V013.md`.
2. Add them to README and the release notes.
3. Comment on issue #54 with the URLs.
4. Move T-02/T-03 to **Passed** only after human review and the links exist.
5. Do not change the Docentric AX `not_tested` or AT-07 `partial` status.

Word for the web (#53) remains separate; the supplied Microsoft Word desktop
screenshots do not close it.
