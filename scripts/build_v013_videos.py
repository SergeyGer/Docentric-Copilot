#!/usr/bin/env python3
"""Build the publish-ready Docentric Copilot product and technical videos.

Design rules from the maintainer review:

* no spoken version numbers, no version numbers on slides;
* no bullet-point narration or bullet slides;
* real UI screenshots and real document pages, problem -> solution;
* the technical video uses professional Mermaid diagrams rendered directly
  from ``docs/wiki/Architecture.md`` and actual benchmark/reference evidence.

The output is silent about publication: human review and YouTube upload remain
outside this repository. The manifest records that explicitly.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import edge_tts
import imageio_ffmpeg  # type: ignore[import-untyped]
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "docs" / "media"
WORK = ROOT / ".tools" / "video-build" / "v13-final"
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
W, H = 2560, 1440
OUT_W, OUT_H = 1920, 1080
FPS = 30
VOICE = "en-US-GuyNeural"
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".tools" / "pw-browsers"))
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
BODY = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


@dataclass(frozen=True)
class Scene:
    key: str
    chapter: str
    title: str
    subtitle: str
    source: str
    narration: str
    takeaway: str
    image: str | None = None
    crop: tuple[int, int, int, int] | None = None
    split: tuple[str, str] | None = None
    split_labels: tuple[str, str] = ("", "")


PRODUCT: tuple[Scene, ...] = (
    Scene(
        "problem",
        "THE PROBLEM",
        "A brief is not a document.",
        "The real file must survive page rules, field rules and Word itself.",
        "MICROSOFT WORD · MANUAL CHECK",
        "A business brief looks simple: a logo, customer and supplier details, line items, totals, payment terms. "
        "The hard part is turning it into a Word document that survives the real file. "
        "The logo must stay on the first page. Later pages need the company identity, but not the logo again. "
        "And every number must come from the right field.",
        "Logo on page one. Identity and page numbers on page two.",
        split=(
            "docs/media/v013-wordweb/user-word-desktop/invoice-page-1.png",
            "docs/media/v013-wordweb/user-word-desktop/invoice-page-2.png",
        ),
        split_labels=("PAGE 1", "PAGE 2"),
    ),
    Scene(
        "brief",
        "THE FLOW",
        "Start with evidence, not a blank prompt.",
        "The brief and the data source are separate, inspectable inputs.",
        "LIVE DEMO · PLAN",
        "Here is the same brief in the live demo. The data source is a DDSP package: typed fields, collections and sample values. "
        "The planner is not allowed to invent a field. It can only choose from schema evidence.",
        "A bounded schema is what makes the plan reviewable.",
        image="docs/media/v013-demo/deployed-invoice-plan.png",
    ),
    Scene(
        "schema",
        "THE FLOW",
        "The schema is the source of truth.",
        "Types, collections and sample data bound the plan.",
        "LIVE DEMO · SCHEMA",
        "The schema is the source of truth. Fields have types, collections have scope, and sample data shows how values are shaped. "
        "The planner can search those candidates, but the resolver decides whether a path is legal. "
        "That is why a confident sentence cannot become a wrong binding.",
        "Evidence bounds the candidate set.",
        image="docs/media/v013-demo/deployed-invoice-plan.png",
        crop=(300, 900, 1500, 1200),
    ),
    Scene(
        "requirements",
        "THE FLOW",
        "The brief becomes typed requirements.",
        "Every requirement points to a real field with a type and a scope.",
        "LIVE DEMO · PLAN",
        "Generate the document and the brief becomes concrete requirements. Each requirement points to a candidate field, "
        "with its type and scope visible. That is the difference between a prompt and a reviewable plan.",
        "A requirement is a contract between the brief and the schema.",
        image="docs/media/v013-demo/deployed-invoice-plan.png",
        crop=(300, 340, 1500, 900),
    ),
    Scene(
        "mapping",
        "THE FLOW",
        "Every binding is visible.",
        "A reviewer can confirm or resolve before compilation.",
        "LIVE DEMO · REVIEW",
        "The mapping review separates confirmed bindings from ambiguous or missing ones. When a choice is ambiguous, "
        "a reviewer can confirm the correct field. The decision is recorded, and a blocking mapping stops compilation. "
        "Nothing silently falls through.",
        "A human confirms. Deterministic code enforces.",
        image="docs/media/v013-demo/deployed-invoice-mapping.png",
        crop=(350, 300, 1500, 1000),
    ),
    Scene(
        "preview",
        "THE FLOW",
        "One structure, two outputs.",
        "The preview and the Word file are built from the same template contract.",
        "LIVE DEMO · PREVIEW",
        "The preview and the Word file are built from the same template structure, so headers and layout follow the same rules. "
        "When the mapping is ready, download the document. The demo also records the artifact hash for verification.",
        "Preview and DOCX cannot drift by design.",
        split=(
            "docs/media/v013-demo/deployed-invoice-preview.png",
            "docs/media/v013-wordweb/user-word-desktop/invoice-page-1.png",
        ),
        split_labels=("LIVE PREVIEW", "WORD OUTPUT"),
    ),
    Scene(
        "artifact",
        "THE FLOW",
        "The download is evidence, not a trick.",
        "The artifact hash is reproducible outside the demo.",
        "LIVE DEMO · ARTIFACT",
        "The demo does not stop at pixels. Downloading the file records its size and SHA-256. "
        "The same hash is reproduced by the deterministic local build, so a reviewer can verify that the demo and the evidence "
        "describe the same artifact.",
        "A file hash is a small, checkable receipt.",
        image="docs/media/v013-demo/deployed-invoice-preview.png",
        crop=(300, 0, 1500, 700),
    ),
    Scene(
        "result-one",
        "THE RESULT",
        "The logo stays on page one.",
        "The document opens in Word with the expected image, table and totals.",
        "MICROSOFT WORD · MANUAL CHECK",
        "Open the result in Word. The logo appears only on the first page. The invoice number, customer and supplier details, "
        "items and totals are all there, and the table stays aligned.",
        "A real DOCX, not a rendered mock-up.",
        image="docs/media/v013-wordweb/user-word-desktop/invoice-page-1.png",
    ),
    Scene(
        "result-two",
        "THE RESULT",
        "Later pages keep the identity, not the logo.",
        "The default header carries company name and VAT; the footer keeps page numbers.",
        "MICROSOFT WORD · MANUAL CHECK",
        "Page two keeps the company name and VAT in the header, without repeating the logo. The footer keeps its page numbers. "
        "That is the first-page header rule working in a real document.",
        "The page rule survives the hand-off to Word.",
        image="docs/media/v013-wordweb/user-word-desktop/invoice-page-2.png",
    ),
    Scene(
        "outcome",
        "THE RESULT",
        "The brief became a checked document.",
        "Typed plan, validated structure, deterministic output.",
        "DOCUMENT OUTPUT",
        "The brief became a typed plan, the plan became a validated document, and every binding has evidence. "
        "The same pipeline covers quotations, invoices and purchase orders. "
        "Docentric Copilot is a narrow AI boundary around a deterministic document engine.",
        "Evidence at every step, not just a plausible file.",
        image="docs/media/v013-wordweb/libreoffice-page-1.png",
    ),
)

TECHNICAL: tuple[Scene, ...] = (
    Scene(
        "arch-overview",
        "ARCHITECTURE",
        "One deterministic core.",
        "The model proposes a typed document; code validates and compiles it.",
        "WIKI / MERMAID",
        "The system is built around one deterministic core. A business brief and a DDSP package enter. "
        "The parser normalizes the schema. The planner, and only the planner, is inside the narrow AI boundary. "
        "It produces a typed document contract, never OOXML.",
        "The AI boundary is narrow on purpose.",
        image="docs/media/diagrams/planning-path.png",
        crop=None,
    ),
    Scene(
        "arch-output",
        "ARCHITECTURE",
        "The contract has two paths.",
        "Validation blocks bad structure; preview and compilation share the same IR.",
        "WIKI / MERMAID",
        "The contract then takes two paths: validation and preview. If structural, semantic and logical checks pass, "
        "the compiler writes a deterministic DOCX. Preview and DOCX share the same structure, so they cannot drift by design.",
        "Validation and rendering are separate concerns.",
        image="docs/media/diagrams/compilation-path.png",
        crop=None,
    ),
    Scene(
        "parser",
        "THE CORE",
        "The parser turns a package into a schema.",
        "Controls, types, collections and sample data are normalized once.",
        "WIKI / MERMAID",
        "The parser reads the DDSP package, validates its XML boundaries and normalizes controls into a schema. "
        "Types, collection scope and sample values become explicit. Every later stage sees the same normalized view, "
        "so a path cannot mean one thing to the planner and another to the compiler.",
        "One normalized schema, one meaning for every path.",
        image="docs/media/diagrams/planning-path.png",
        crop=(0, 0, 2800, 838),
    ),
    Scene(
        "lifecycle",
        "ARCHITECTURE",
        "A request is a chain of contracts.",
        "The API, planner, validator and compiler exchange typed data, not prose.",
        "WIKI / MERMAID",
        "A request is a sequence of narrow contracts. The web app, CLI or API calls TemplateService. "
        "Planning gets schema evidence and the brief; validation gets the typed template; compilation gets only a validated template "
        "and sample data. A blocking report returns without a document.",
        "Nothing reaches the compiler without passing the gate.",
        image="docs/media/diagrams/request-lifecycle.png",
        crop=None,
    ),
    Scene(
        "plan",
        "PLANNING",
        "Evidence before generation.",
        "Requirements, candidates and scope are visible before a document exists.",
        "LIVE DEMO · PLAN",
        "In the live demo, the brief is split into requirements. Candidate fields carry type and scope; "
        "the reviewer sees confirmed, ambiguous and missing bindings. The planner cannot bind arbitrary strings.",
        "The model chooses from evidence; it does not invent the schema.",
        image="docs/media/v013-demo/deployed-invoice-plan.png",
    ),
    Scene(
        "preview",
        "THE CORE",
        "The preview is an independent rendering.",
        "Same template contract, different renderer, visible mismatches.",
        "LIVE DEMO · PREVIEW",
        "The preview is not a screenshot of Word. It is an independent renderer that consumes the same template structure. "
        "That gives the reviewer a fast, visible check of order, hierarchy and conditional content before downloading the DOCX.",
        "Two renderers agree because they share the contract.",
        image="docs/media/v013-demo/deployed-invoice-preview.png",
    ),
    Scene(
        "ir-top",
        "THE CONTRACT",
        "A small typed document model.",
        "Document, sections and blocks; no free-form OOXML.",
        "WIKI / MERMAID",
        "The contract is a small typed model: document, sections, blocks. "
        "Tables carry repeated rows, row templates and footer rows. Repeats carry a path and alias; "
        "conditions carry typed expressions; images carry source and fallback policy.",
        "The model is deliberately smaller than Word.",
        image="docs/media/diagrams/ir-document-structure.png",
        crop=None,
    ),
    Scene(
        "ir-blocks",
        "THE CONTRACT",
        "Every block has one legal shape.",
        "Paragraphs, headings, tables, repeats, conditions and images.",
        "WIKI / MERMAID",
        "Every block has one legal shape. Paragraphs and headings carry runs. Tables own their rows and optional footer rows. "
        "Repeats and conditions own nested blocks. Images carry source, fallback and aspect-ratio policy. "
        "The validator can check those rules because they are types, not conventions.",
        "Typed blocks make deterministic validation possible.",
        image="docs/media/diagrams/ir-block-taxonomy.png",
        crop=None,
    ),
    Scene(
        "validation",
        "VALIDATION",
        "The gate is explicit.",
        "Structural, semantic and logical checks block compilation.",
        "WIKI / MERMAID",
        "Validation is layered. Structural checks reject malformed IR. Semantic checks reject unknown or incompatible paths. "
        "Logical checks enforce collection scope, condition types and image placement. V1 to V3 block compilation. "
        "Visual checks use sample data; compatibility with Docentric AX remains a separate untreated gate.",
        "A report is evidence, not an optimistic score.",
        image="docs/media/diagrams/validation-blocking.png",
        crop=None,
    ),
    Scene(
        "validation-right",
        "VALIDATION",
        "Compile only after the gate.",
        "Visual checks may skip; runtime compatibility is not claimed.",
        "WIKI / MERMAID",
        "After the blocking gate, the visual check uses sample data when it is available. "
        "The compatibility level is separate and remains not tested. That distinction matters: a valid generic DOCX is not a claim "
        "that the document will run inside a third-party reporting runtime.",
        "Compatibility is a named, separate claim.",
        image="docs/media/diagrams/validation-compatibility.png",
        crop=None,
    ),
    Scene(
        "docx",
        "THE COMPILER",
        "The compiler owns OOXML.",
        "Real sections, headers, footers, media and deterministic packaging.",
        "ACTUAL DOCX PACKAGE",
        "The compiler owns OOXML. It resolves relationships, writes real sections, headers and footers, embeds media and normalizes the ZIP. "
        "The output has stable ordering and fixed timestamps, so the same inputs produce the same bytes.",
        "The package itself is part of the evidence.",
        image="docs/media/diagrams/docx-package.png",
    ),
    Scene(
        "header",
        "THE COMPILER",
        "First-page headers are real parts.",
        "The logo appears once because the package contains two headers.",
        "MICROSOFT WORD · MANUAL CHECK",
        "First-page headers are real Word parts. The section sets titlePg and points to a first-page header. "
        "Later sections can inherit a header or clear it. That is why the logo appears once, while the company identity stays in the default header.",
        "Inheritance is explicit in the package.",
        image="docs/media/v013-wordweb/user-word-desktop/invoice-page-2.png",
    ),
    Scene(
        "tables",
        "REFERENCE INTELLIGENCE",
        "Tables are inferred, or refused.",
        "Accepted tables are not a claim of visual Word accuracy.",
        "REFERENCE EVALUATION · ACTUAL DATA",
        "Table inference reads bounded geometry and joins it to schema evidence. It handles static headers, repeated rows, "
        "optional conditional cells, footer rows and a tested nested repeat. Merged or ambiguous tables are refused with diagnostics. "
        "Images support schema data, static assets, fallback and aspect ratio.",
        "Ambiguity becomes a diagnostic, not a guess.",
        image="docs/media/diagrams/chart-tables.png",
    ),
    Scene(
        "reference",
        "REFERENCE INTELLIGENCE",
        "Seventeen documents, three outcomes.",
        "Parsed, imported, compiled; residual failures are classified.",
        "REFERENCE EVALUATION · ACTUAL DATA",
        "Reference evaluation is separate from semantic quality. Seventeen official documents parse, sixteen import and fifteen compile. "
        "The two residual failures are an unenclosed nested collection and an unsupported-only document. "
        "Thirty observed tables are classified: fifteen accepted, fifteen deliberately unsupported, zero silently dropped. "
        "The pipeline counts are deliberately separate from the semantic benchmark.",
        "The denominator is part of the result.",
        image="docs/media/diagrams/chart-reference.png",
    ),
    Scene(
        "benchmark",
        "EVIDENCE",
        "Quality is measured, not asserted.",
        "Technical failures are separated from semantic passes.",
        "BENCHMARK · ACTUAL DATA",
        "The semantic benchmark runs thirty-two cases across three providers and three repeats, with technical failures separated. "
        "Two hundred seventy-four runs pass semantically. Precision is ninety-five percent; recall and F1 are higher; "
        "ten Gemini structured-output failures remain technical, not semantic. "
        "The report keeps the technical and semantic views separate, so a missing structured response cannot inflate quality.",
        "A technical failure is never a silent semantic pass.",
        image="docs/media/diagrams/chart-benchmark.png",
        crop=(0, 150, 2400, 1200),
    ),
    Scene(
        "limits",
        "BOUNDARIES",
        "The proof stops where the evidence stops.",
        "No runtime compatibility claim; human review remains external.",
        "HONEST STATUS",
        "The honest limits: Word for the web still needs a manual browser check; the videos are drafts; "
        "AT-07 remains partial because the gold labels lack independent human review; and Docentric AX runtime compatibility is not tested. "
        "A deterministic document engine can prove the document, not somebody else's runtime.",
        "A deterministic document, not a compatibility claim.",
        image="docs/media/v013-wordweb/user-word-desktop/invoice-page-1.png",
    ),
    Scene(
        "close",
        "CLOSE",
        "One deterministic core. A narrow AI boundary.",
        "Evidence at every step.",
        "Docentric Copilot",
        "One deterministic core, a narrow AI boundary, and evidence at every step. That is Docentric Copilot.",
        "From a business brief to a checked Word document.",
        image="docs/media/v013-wordweb/libreoffice-page-1.png",
    ),
)


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _data_uri(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def _clean_app_screenshot(path: Path) -> Image.Image:
    image = Image.open(path).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((14, 300, 296, 520), radius=14, fill="#0B1220")
    draw.text((30, 320), "LIVE DEMO", font=_font(BOLD, 19), fill="#38BDF8")
    draw.text((30, 352), "schema-aware", font=_font(BODY, 16), fill="#94A3B8")
    draw.text((30, 380), "deterministic", font=_font(BODY, 16), fill="#94A3B8")
    draw.text((30, 408), "no model key", font=_font(BODY, 16), fill="#94A3B8")
    return image


def _fit_image(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    scale = min(size[0] / image.width, size[1] / image.height)
    image = image.resize(
        (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
        Image.Resampling.LANCZOS,
    )
    panel = Image.new("RGB", size, "#0B1220")
    panel.paste(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
    return panel


def _fitted(
    path: Path, crop: tuple[int, int, int, int] | None, size: tuple[int, int]
) -> Image.Image:
    image = Image.open(path).convert("RGB")
    if crop:
        image = image.crop(crop)
    return _fit_image(image, size)


def _html(scene: Scene, tag: str) -> str:
    visual_size = (2280, 940)
    if scene.split:
        panes = []
        for path in scene.split:
            source_image = (
                _clean_app_screenshot(ROOT / path)
                if "v013-demo" in path
                else Image.open(ROOT / path).convert("RGB")
            )
            panes.append(_fit_image(source_image, (1110, 860)))
        left, right = panes
        visual = (
            '<div class="split">'
            f'<figure><img src="{_data_uri(left)}"><figcaption>{scene.split_labels[0]}</figcaption></figure>'
            f'<figure><img src="{_data_uri(right)}"><figcaption>{scene.split_labels[1]}</figcaption></figure>'
            "</div>"
        )
    elif scene.image:
        source = ROOT / scene.image
        if "v013-demo" in scene.image and scene.crop is None:
            image = _clean_app_screenshot(source)
            visual = f'<img class="single" src="{_data_uri(image)}">'
        else:
            image = _fitted(source, scene.crop, visual_size)
            visual = f'<img class="single" src="{_data_uri(image)}">'
    else:
        visual = ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; width: {W}px; height: {H}px; background: #0B1220; color: #E2E8F0; font-family: 'DejaVu Sans', Arial, sans-serif; }}
  body {{ background:
      radial-gradient(1000px 600px at 85% 8%, rgba(37,99,235,.16), transparent 65%),
      radial-gradient(900px 500px at 8% 95%, rgba(14,165,233,.10), transparent 65%),
      #0B1220; }}
  .grid {{ position: absolute; inset: 0; background-image: linear-gradient(rgba(148,163,184,.045) 1px, transparent 1px), linear-gradient(90deg, rgba(148,163,184,.045) 1px, transparent 1px); background-size: 80px 80px; }}
  header {{ position: absolute; left: 84px; right: 84px; top: 54px; display: flex; justify-content: space-between; align-items: center; }}
  .brand {{ display: flex; gap: 18px; align-items: center; }}
  .mark {{ width: 58px; height: 58px; border-radius: 14px; background: #2563EB; color: white; font-weight: 700; font-size: 38px; display: flex; align-items: center; justify-content: center; }}
  .name {{ font-size: 30px; font-weight: 700; letter-spacing: -.3px; }}
  .tag {{ font-size: 19px; color: #7DD3FC; letter-spacing: 3px; font-weight: 700; }}
  main {{ position: absolute; left: 84px; right: 84px; top: 150px; }}
  .chapter {{ color: #7DD3FC; letter-spacing: 4px; font-size: 19px; font-weight: 700; margin-bottom: 14px; }}
  h1 {{ margin: 0; font-size: 68px; line-height: 1.04; letter-spacing: -1.6px; max-width: 2100px; }}
  .sub {{ margin: 16px 0 0; color: #AFC0D6; font-size: 30px; line-height: 1.28; max-width: 2050px; }}
  .visual-wrap {{ position: absolute; left: 84px; right: 84px; top: 365px; height: 930px; border-radius: 24px; background: #0F172A; border: 1px solid rgba(125,211,252,.22); box-shadow: 0 30px 90px rgba(0,0,0,.35); padding: 20px; }}
  .source {{ position: absolute; top: -35px; left: 10px; color: #7DD3FC; letter-spacing: 2.5px; font-size: 15px; font-weight: 700; }}
  img.single {{ width: 100%; height: 100%; object-fit: contain; border-radius: 14px; display: block; }}
  .split {{ display: grid; grid-template-columns: 1fr 1fr; gap: 22px; height: 100%; }}
  .split figure {{ margin: 0; position: relative; background: #0B1220; border-radius: 14px; overflow: hidden; }}
  .split img {{ width: 100%; height: 100%; object-fit: contain; }}
  .split figcaption {{ position: absolute; left: 16px; bottom: 14px; background: rgba(11,18,32,.9); border: 1px solid rgba(125,211,252,.3); color: #7DD3FC; font-size: 15px; letter-spacing: 2px; padding: 8px 12px; border-radius: 8px; }}
  .takeaway {{ position: absolute; left: 84px; right: 84px; bottom: 48px; height: 82px; display: flex; align-items: center; gap: 20px; background: rgba(15,23,42,.75); border: 1px solid rgba(148,163,184,.18); border-radius: 16px; padding: 0 28px; }}
  .check {{ width: 42px; height: 42px; border-radius: 50%; background: #064E3B; border: 1px solid #34D399; color: #A7F3D0; display: flex; align-items: center; justify-content: center; font-size: 24px; }}
  .takeaway p {{ margin: 0; font-size: 27px; color: #DCE7F5; }}
</style></head><body>
<div class="grid"></div>
<header><div class="brand"><div class="mark">D</div><div><div class="name">Docentric Copilot</div><div style="font-size:17px;color:#94A3B8;margin-top:4px">template engineering workspace</div></div></div><div class="tag">{tag}</div></header>
<main><div class="chapter">{scene.chapter}</div><h1>{scene.title}</h1><p class="sub">{scene.subtitle}</p></main>
<div class="visual-wrap"><div class="source">{scene.source}</div>{visual}</div>
<div class="takeaway"><div class="check">✓</div><p>{scene.takeaway}</p></div>
</body></html>"""


async def _tts(text: str, path: Path) -> None:
    last_error: Exception | None = None
    for _ in range(4):
        try:
            communicate = edge_tts.Communicate(text, VOICE)
            await communicate.save(str(path))
            if path.exists() and path.stat().st_size > 0:
                return
        except Exception as exc:
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


def _chunks(text: str, duration: float) -> list[tuple[float, float, str]]:
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    total = sum(len(sentence) for sentence in sentences) or 1
    chunks: list[tuple[float, float, str]] = []
    cursor = 0.0
    for sentence in sentences:
        share = duration * len(sentence) / total
        chunks.append((cursor, cursor + share, sentence))
        cursor += share
    return chunks


def _render_scene(scene: Scene, path: Path, tag: str) -> None:
    from playwright.sync_api import sync_playwright

    html_path = WORK / f"{scene.key}.html"
    html_path.write_text(_html(scene, tag), encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        page.goto(html_path.as_uri(), wait_until="load")
        page.screenshot(path=str(path))
        browser.close()


def _encode_scene(frame: Path, audio: Path, target: Path, duration: float) -> None:
    subprocess.run(
        [
            str(FFMPEG),
            "-y",
            "-loop",
            "1",
            "-i",
            str(frame),
            "-i",
            str(audio),
            "-t",
            f"{duration:.3f}",
            "-filter_complex",
            f"[0:v]scale={W}:{H},zoompan=z='min(1.0+0.035*on/({FPS}*{duration}),1.05)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={OUT_W}x{OUT_H}:fps={FPS},fade=t=in:st=0:d=0.35,fade=t=out:st={max(duration - 0.35, 0):.3f}:d=0.35,format=yuv420p[v]",
            "-map",
            "[v]",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "19",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
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


def _build(name: str, scenes: tuple[Scene, ...], tag: str) -> dict:
    work = WORK / name
    work.mkdir(parents=True, exist_ok=True)
    segments: list[Path] = []
    captions: list[tuple[float, float, str]] = []
    narration_lines = [f"# {name} narration", ""]
    offset = 0.0
    for index, scene in enumerate(scenes):
        frame = work / f"{index:02d}-{scene.key}.png"
        audio = work / f"{index:02d}-{scene.key}.mp3"
        segment = work / f"{index:02d}-{scene.key}.mp4"
        _render_scene(scene, frame, tag)
        asyncio.run(_tts(scene.narration, audio))
        duration = _duration(audio)
        _encode_scene(frame, audio, segment, duration)
        segments.append(segment)
        for start, end, text in _chunks(scene.narration, duration):
            captions.append((offset + start, offset + end, text))
        narration_lines += [
            f"## {index + 1}. {scene.title} ({duration:.1f}s)",
            "",
            scene.narration,
            "",
        ]
        offset += duration
        print(f"  {scene.key}: {duration:.1f}s")
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
    lines = [
        f"{number}\n{_srt_time(start)} --> {_srt_time(end)}\n{text}\n"
        for number, (start, end, text) in enumerate(captions, start=1)
    ]
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
    thumb = MEDIA / f"{name}-v013-thumb.png"
    Image.open(segments[0].with_suffix(".png")).resize((1280, 720), Image.Resampling.LANCZOS).save(
        thumb
    )
    return {
        "name": name,
        "mp4": str(mp4.relative_to(ROOT)),
        "srt": str(srt.relative_to(ROOT)),
        "narration": str((MEDIA / f"{name}-v013-narration.md").relative_to(ROOT)),
        "thumbnail": str(thumb.relative_to(ROOT)),
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
                {
                    "product_scenes": len(PRODUCT),
                    "technical_scenes": len(TECHNICAL),
                    "voice": VOICE,
                },
                indent=2,
            )
        )
        return 0
    WORK.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "schema": "v013-video-kit/v2",
        "status": "publish_ready_draft",
        "human_review": False,
        "youtube_published": False,
        "voice": VOICE,
        "fps": FPS,
        "resolution": "1920x1080",
        "narration_rule": "No spoken version numbers, no bullet-point narration.",
        "content_rules": {
            "spoken_version_numbers": False,
            "on_screen_version_numbers": False,
            "bullet_slides": False,
            "real_ui_screenshots": True,
            "wiki_mermaid_diagrams": True,
        },
        "diagrams": [
            "docs/media/diagrams/architecture-data-flow.png",
            "docs/media/diagrams/request-lifecycle.png",
            "docs/media/diagrams/template-ir-contract.png",
            "docs/media/diagrams/validation-ladder.png",
            "docs/media/diagrams/planning-path.png",
            "docs/media/diagrams/compilation-path.png",
            "docs/media/diagrams/ir-block-taxonomy.png",
            "docs/media/diagrams/validation-blocking.png",
            "docs/media/diagrams/validation-compatibility.png",
            "docs/media/diagrams/ir-document-structure.png",
        ],
        "diagram_sources": ["docs/wiki/Architecture.md"],
        "word_desktop_evidence": "docs/media/v013-wordweb/user-word-desktop/manifest.json",
        "word_web_pending": True,
        "product": _build("demo", PRODUCT, "PRODUCT DEMO"),
        "technical": _build("technical", TECHNICAL, "TECHNICAL DEEP-DIVE"),
        "limitations": [
            "Draft for maintainer review; no YouTube publication.",
            "Word for the web remains an external manual step; the Word desktop check is separate.",
            "No Docentric AX runtime claim.",
        ],
    }
    (MEDIA / "v013-video-kit.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    product = manifest["product"]
    technical = manifest["technical"]
    assert isinstance(product, dict) and isinstance(technical, dict)
    print(
        json.dumps(
            {
                "product": product["duration_seconds"],
                "technical": technical["duration_seconds"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
