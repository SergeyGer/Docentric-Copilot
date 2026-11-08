#!/usr/bin/env python3
"""Build draft v0.13 Product Demo and Technical Deep-Dive videos.

This is a reproducible *production kit*, not a publication. It creates 1080p
H.264/AAC videos with English Edge TTS narration and SRT sidecars from committed
evidence/screenshots. Human review and YouTube publication remain external gates;
the manifest says so explicitly.

Usage::

    PLAYWRIGHT_BROWSERS_PATH=.tools/pw-browsers \
      python scripts/build_v013_videos.py --write
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import edge_tts
import imageio_ffmpeg  # type: ignore[import-untyped]
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "docs" / "media"
WORK = ROOT / ".tools" / "video-build" / "v13"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
FFPROBE = (
    ROOT
    / ".tools"
    / "ffprobe-tool"
    / "node_modules"
    / "@ffprobe-installer"
    / "linux-x64"
    / "ffprobe"
)
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_BODY = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
W, H = 1920, 1080
VOICE = "en-US-AriaNeural"


@dataclass(frozen=True)
class Scene:
    key: str
    title: str
    bullets: tuple[str, ...]
    narration: str
    image: str | None = None


PRODUCT: tuple[Scene, ...] = (
    Scene(
        "title",
        "Docentric Copilot v0.13.0",
        (
            "Business brief + DDSP schema → checked generic DOCX",
            "Deterministic validation, not a Word add-in",
            "Docentric AX: not tested",
        ),
        "Docentric Copilot turns a business brief and a data source into a generic Word document. "
        "The planner proposes the structure. Deterministic code validates, compiles and reports evidence. "
        "Docentric AX runtime compatibility is not tested, and this video is a draft production asset.",
    ),
    Scene(
        "brief",
        "From brief to schema",
        ("Real DDSP package", "Typed requirements", "Candidate fields with evidence"),
        "Start with a real DDSP package. The inspector exposes fields, collections and sample data. "
        "The brief is split into typed requirements, and the planner receives only bounded, evidence-backed candidates.",
        image="docs/media/v013-demo/deployed-plan.png",
    ),
    Scene(
        "mapping",
        "Review before compile",
        ("Ambiguity is visible", "A reviewer confirms or rejects", "No silent wrong binding"),
        "The mapping review shows what is confirmed, schema-valid, ambiguous or missing. "
        "A reviewer can confirm the correct field; the confirmation is preserved and the document compiles only when no blocking mapping remains.",
        image="docs/media/v013-demo/deployed-mapping.png",
    ),
    Scene(
        "workflow",
        "Three deterministic steps",
        (
            "1. Understand the brief",
            "2. Review evidence-backed mappings",
            "3. Validate and compile",
        ),
        "The workflow has three steps. First, understand the brief and the available schema evidence. "
        "Second, let a person review ambiguous mappings. Third, validate the typed template and compile the DOCX. "
        "The model never writes OOXML directly.",
    ),
    Scene(
        "preview",
        "Preview and DOCX",
        ("Preview is independent", "Download DOCX with hash evidence", "Sales Quotation fixed"),
        "The preview is built from the same Template IR as the DOCX. "
        "The live demo now exposes the download button after confirmation and records the artifact hash, fixing the earlier Sales Quotation flow.",
        image="docs/media/v013-demo/deployed-preview.png",
    ),
    Scene(
        "first-page",
        "First-page header only",
        ("Logo on page 1", "Company name and VAT later", "Footer page numbers intact"),
        "Template IR 1.2 adds a first-page header. The compiler writes a real title-page header part. "
        "Page one carries the logo, later pages keep the company identity without it, and footer page numbers remain intact.",
        image="docs/media/v013-wordweb/libreoffice-page-1.png",
    ),
    Scene(
        "whats-new",
        "What v0.13 adds",
        (
            "Images: static, schema, collections",
            "Tables: optional cells, footer rows, nested repeat",
            "First-page header and real sections",
        ),
        "Version zero thirteen adds the image family, conservative reference table inference and first-page headers. "
        "It also turns IR sections into real Word sections, fixes the live demo confirmation flow, and adds honest evidence for every remaining limitation.",
    ),
    Scene(
        "images-tables",
        "Images and tables",
        (
            "Static and schema images",
            "Image per line item",
            "Optional cells, footer rows, nested repeats",
        ),
        "The image family supports static assets, schema images, image collections and fallback policy. "
        "Reference table inference produces header and repeated rows, optional cells, footer rows and nested repeat structures, with explicit diagnostics for ambiguous shapes.",
    ),
    Scene(
        "evidence",
        "Benchmark and reference evidence",
        (
            "288 runs: 278 completed, 10 technical",
            "Precision 0.9510, semantic pass 98.56%",
            "30 tables classified",
        ),
        "The final benchmark records two hundred eighty-eight planned runs, with ten Gemini structured-output failures separated from semantics. "
        "Precision is zero point nine five one, semantic pass is ninety-eight point five six percent, and the reference evaluation classifies every observed table, including deliberate refusals.",
    ),
    Scene(
        "limits",
        "Honest limits",
        (
            "Word for the web: not performed",
            "Videos: draft, no human review",
            "AT-07 partial; AX runtime not_tested",
        ),
        "Word for the web validation still requires a human with Microsoft 365. "
        "These videos are drafts without human review or YouTube publication. AT-07 remains partial, and Docentric AX runtime compatibility remains not tested.",
        image="docs/media/v013-wordweb/libreoffice-page-2.png",
    ),
)

TECHNICAL: tuple[Scene, ...] = (
    Scene(
        "title",
        "Technical Deep-Dive — v0.13",
        (
            "Architecture, IR 1.2, images, tables, headers",
            "Evidence-led release",
            "Runtime compatibility not_tested",
        ),
        "This deep-dive explains how Docentric Copilot turns a brief into a checked Word document, "
        "what changed in version zero thirteen, and where the honest boundaries are.",
    ),
    Scene(
        "architecture",
        "Pipeline",
        (
            "DDSP parser → ReferenceGraph → Planner → Validator → Compiler → Preview",
            "Strict types at every boundary",
            "No raw XPath or OOXML from the model",
        ),
        "The pipeline is deliberately boring. The parser normalizes the schema, the reference inspector builds evidence, "
        "the planner emits a typed Template IR, the validator checks structure, semantics and logic, and only then does the compiler produce DOCX.",
    ),
    Scene(
        "schema",
        "Schema evidence",
        ("DDSP controls, types and samples", "Collections are explicit", "Candidates are bounded"),
        "The schema layer is not a prompt dump. The parser records controls, types, collection scope and sample values. "
        "The planner receives bounded candidates with evidence, so a field can be recommended, but only the validator decides whether a path is legal.",
    ),
    Scene(
        "planner",
        "Planner contract",
        (
            "Typed Template IR, not free text",
            "Compact mode is a transport format",
            "Repair is bounded",
        ),
        "The planner emits a typed Template IR or a compact transport representation that expands into it. "
        "Compact mode is not a second document model; it is schema-validated, expanded deterministically, and repaired only within a bounded budget.",
    ),
    Scene(
        "validation",
        "Validation layers",
        ("Structural and schema checks", "Semantic requirements", "Logic and collection scope"),
        "Validation is layered. Structural rules catch malformed blocks, schema rules reject unknown paths, semantic rules check the brief, "
        "and logic rules enforce condition scope, collection nesting and image placement. A report is evidence, not an optimistic score.",
    ),
    Scene(
        "compiler",
        "Compiler and OOXML",
        (
            "Real Word sections and header parts",
            "Relationships and media",
            "Deterministic ZIP output",
        ),
        "The compiler owns OOXML. It writes sections, headers, footers, tables, relationships and media, then packages a deterministic DOCX. "
        "The preview uses the same IR and inheritance rules, so preview and Word output do not drift by design.",
    ),
    Scene(
        "demo",
        "Live demo evidence",
        (
            "Deployed Streamlit: v0.13.0",
            "Commit 1cbe073, IR 1.2",
            "Three downloads match local hashes",
        ),
        "The deployed Streamlit demo was woken and exercised in Chromium. It reports version zero thirteen, commit one c b e zero seven three and IR one point two. "
        "Quotation, invoice and purchase order all download DOCX, and the hashes match the local deterministic build.",
    ),
    Scene(
        "ir",
        "Template IR 1.2",
        (
            "Typed document contract",
            "Migrations 1.0 → 1.1 → 1.2",
            "First-page header, image policy, table footer rows",
        ),
        "Template IR is the contract between AI and deterministic code. Version one point two adds the first-page header, "
        "image source and fallback policy, and table footer rows. Older payloads migrate deterministically; unknown versions are refused.",
    ),
    Scene(
        "images",
        "Image family",
        (
            "Schema or static source",
            "Fallback: placeholder, blank, alt text",
            "Aspect ratio and scope validation",
        ),
        "Images can come from schema data or from reviewed compile assets. Missing images follow an explicit fallback policy. "
        "The validator rejects wrong types and images outside the active collection scope, and the compiler preserves aspect ratio unless stretching is explicit.",
    ),
    Scene(
        "tables",
        "Reference table inference",
        (
            "Static header + repeated data rows",
            "Optional If cells, footer rows, nested repeat",
            "Ambiguous geometry is refused",
        ),
        "Table inference reads bounded DOCX geometry and joins it to schema evidence. It handles static headers, repeated rows, optional conditional cells, "
        "footer rows and a nested repeat under the outer row. Merged, ragged or ambiguous tables are blocking diagnostics, not guesses.",
    ),
    Scene(
        "headers",
        "First-page and multi-section headers",
        (
            "titlePg and first-page header part",
            "None inherits; empty list clears",
            "Preview follows Word semantics",
        ),
        "The first-page header is a real Word header part selected by titlePg. "
        "Each IR section becomes a Word section; a null header inherits the previous section, an empty list clears it, and the preview follows the same inheritance.",
    ),
    Scene(
        "reference",
        "Reference Evaluation",
        ("17 official documents", "16 import, 15 compile", "Two pipeline boundaries classified"),
        "The reference evaluation is separate from the gold semantic benchmark. Seventeen official documents parse, sixteen reach import and fifteen compile. "
        "The two remaining pipeline failures are classified: an unenclosed nested collection and an unsupported-only document.",
    ),
    Scene(
        "benchmark",
        "Final benchmark",
        (
            "288 planned, 278 completed",
            "10 Gemini technical failures",
            "Precision 0.9510; spend $4.1844",
        ),
        "The final benchmark uses thirty-two cases, three providers and three repeats. "
        "Two hundred seventy-eight runs completed, ten Gemini structured-output failures remain technical, and two hundred seventy-four runs pass semantically. "
        "Precision is zero point nine five one and total spend is four dollars eighteen.",
    ),
    Scene(
        "quality",
        "Quality gates",
        (
            "Unit, coverage, E2E, Playwright",
            "Real LibreOffice/Poppler visual diff",
            "CodeQL, security, Docker",
        ),
        "Every change passes lint, typing, unit tests with an eighty-five percent coverage gate, browser E2E, a real LibreOffice visual diff and security analysis. "
        "The release workflow builds and verifies the wheel and the images.",
    ),
    Scene(
        "security",
        "Determinism and security",
        ("No keys in the demo", "Bounded prompts and artifacts", "Logs redact secrets"),
        "The demo runs on a deterministic mock provider and never needs a model key. "
        "Artifact uploads are bounded and signature-checked, provider errors are sanitized, and logs redact credentials. "
        "The benchmark records spend and technical failures separately from semantic quality.",
    ),
    Scene(
        "release",
        "Release evidence",
        ("v0.13.0 artifacts and CI", "T-08 deployed demo verified", "T-01 and videos remain open"),
        "The release is backed by a wheel, source archive, CI, visual diffs and a published evidence page. "
        "The deployed demo is verified, but Word for the web and the final videos remain external open tasks. "
        "Those gaps stay visible instead of being converted into a pass.",
    ),
    Scene(
        "benchmark-limits",
        "Reading the metrics",
        (
            "Technical failures are excluded from semantics",
            "Accepted table is not visual Word accuracy",
            "Runtime compatibility is unproven",
        ),
        "Read the benchmark carefully. Technical failures are excluded from semantic scoring but still reported. "
        "An accepted table means the inference layer produced IR, not that Microsoft Word renders it perfectly. "
        "A semantic pass is not a Docentric AX runtime compatibility proof.",
    ),
    Scene(
        "limits",
        "Boundaries",
        (
            "Word for the web: pending",
            "Videos: draft, no human review",
            "AT-07 partial; Docentric AX not_tested",
        ),
        "The remaining gaps are external or explicit: Word for the web needs a human with Microsoft 365, videos need review and publishing, "
        "AT-07 remains partial, and Docentric AX runtime compatibility remains not tested. No semantic score is a runtime compatibility proof.",
    ),
)


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _slide(scene: Scene, path: Path) -> None:
    if scene.image:
        source = Image.open(ROOT / scene.image).convert("RGB")
        canvas = Image.new("RGB", (W, H), "#0B1220")
        source.thumbnail((W - 160, H - 260))
        x = (W - source.width) // 2
        y = 210 + (H - 260 - source.height) // 2
        canvas.paste(source, (x, y))
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((0, 0, W, 180), fill="#0B1220")
        draw.text((80, 52), scene.title, font=_font(FONT_BOLD, 64), fill="#FFFFFF")
        draw.text(
            (80, 132),
            "Docentric Copilot v0.13.0 · evidence-led draft",
            font=_font(FONT_BODY, 28),
            fill="#94A3B8",
        )
        canvas.save(path)
        return
    canvas = Image.new("RGB", (W, H), "#0B1220")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, 18, H), fill="#2563EB")
    draw.text((100, 130), scene.title, font=_font(FONT_BOLD, 78), fill="#FFFFFF")
    y = 300
    for bullet in scene.bullets:
        draw.ellipse((104, y + 14, 128, y + 38), fill="#38BDF8")
        lines = _wrap(draw, bullet, _font(FONT_BODY, 44), W - 260)
        for line in lines:
            draw.text((156, y), line, font=_font(FONT_BODY, 44), fill="#E2E8F0")
            y += 62
        y += 30
    draw.text(
        (100, H - 100),
        "Docentric Copilot v0.13.0 · Docentric AX runtime not_tested · AT-07 partial",
        font=_font(FONT_BODY, 26),
        fill="#94A3B8",
    )
    canvas.save(path)


async def _tts(text: str, path: Path) -> None:
    last_error: Exception | None = None
    for _ in range(4):
        try:
            communicate = edge_tts.Communicate(text, VOICE)
            await communicate.save(str(path))
            if path.exists() and path.stat().st_size > 0:
                return
        except Exception as exc:  # Edge TTS can return an empty stream transiently
            last_error = exc
        await asyncio.sleep(1)
    raise RuntimeError(f"TTS failed for {path.name}") from last_error


def _duration(path: Path) -> float:
    result = subprocess.run(
        [
            str(FFPROBE),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def _srt_time(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _caption_chunks(text: str, duration: float) -> list[tuple[float, float, str]]:
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    if not sentences:
        return [(0.0, duration, text)]
    total = sum(len(sentence) for sentence in sentences)
    chunks = []
    cursor = 0.0
    for sentence in sentences:
        share = duration * len(sentence) / total
        chunks.append((cursor, cursor + share, sentence))
        cursor += share
    return chunks


def _encode_scene(scene: Scene, slide: Path, audio: Path, target: Path, duration: float) -> None:
    subprocess.run(
        [
            str(FFMPEG),
            "-y",
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(slide),
            "-i",
            str(audio),
            "-t",
            f"{duration:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-shortest",
            str(target),
        ],
        check=True,
        capture_output=True,
    )


def _build(name: str, scenes: tuple[Scene, ...]) -> dict:
    work = WORK / name
    work.mkdir(parents=True, exist_ok=True)
    segments: list[Path] = []
    captions: list[tuple[float, float, str]] = []
    offset = 0.0
    narration_lines = [f"# {name} narration", ""]
    for index, scene in enumerate(scenes):
        slide = work / f"{index:02d}-{scene.key}.png"
        audio = work / f"{index:02d}-{scene.key}.mp3"
        segment = work / f"{index:02d}-{scene.key}.mp4"
        _slide(scene, slide)
        asyncio.run(_tts(scene.narration, audio))
        duration = _duration(audio)
        _encode_scene(scene, slide, audio, segment, duration)
        segments.append(segment)
        for start, end, text in _caption_chunks(scene.narration, duration):
            captions.append((offset + start, offset + end, text))
        narration_lines += [
            f"## {index + 1}. {scene.title} ({duration:.1f}s)",
            "",
            scene.narration,
            "",
        ]
        offset += duration
    concat = work / "concat.txt"
    concat.write_text("\n".join(f"file '{segment.as_posix()}'" for segment in segments) + "\n")
    mp4 = MEDIA / f"{name}-v013.mp4"
    srt = MEDIA / f"{name}-v013.srt"
    subprocess.run(
        [
            str(FFMPEG),
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(mp4),
        ],
        check=True,
        capture_output=True,
    )
    lines = []
    for number, (start, end, text) in enumerate(captions, start=1):
        lines.append(f"{number}\n{_srt_time(start)} --> {_srt_time(end)}\n{text}\n")
    srt.write_text("\n".join(lines), encoding="utf-8")
    (MEDIA / f"{name}-v013-narration.md").write_text("\n".join(narration_lines), encoding="utf-8")
    probe = subprocess.run(
        [
            str(FFPROBE),
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate",
            "-of",
            "json",
            str(mp4),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return {
        "name": name,
        "mp4": str(mp4.relative_to(ROOT)),
        "srt": str(srt.relative_to(ROOT)),
        "narration": str((MEDIA / f"{name}-v013-narration.md").relative_to(ROOT)),
        "duration_seconds": round(offset, 2),
        "sha256": hashlib.sha256(mp4.read_bytes()).hexdigest(),
        "bytes": mp4.stat().st_size,
        "probe": json.loads(probe.stdout),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    if not args.write:
        print(
            json.dumps(
                {"product_scenes": len(PRODUCT), "technical_scenes": len(TECHNICAL)}, indent=2
            )
        )
        return 0
    MEDIA.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "v013-video-kit/v1",
        "status": "draft_production_kit",
        "human_review": False,
        "youtube_published": False,
        "voice": VOICE,
        "fps": 30,
        "resolution": "1920x1080",
        "product": _build("demo", PRODUCT),
        "technical": _build("technical", TECHNICAL),
        "limitations": [
            "Draft assets; no human review and no YouTube publication.",
            "Product Demo uses deployed-demo screenshots and LibreOffice page evidence; Word for the web is still pending.",
            "No Docentric AX runtime claim; AT-07 remains partial.",
        ],
    }
    (MEDIA / "v013-video-kit.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
