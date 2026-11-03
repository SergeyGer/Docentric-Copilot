#!/usr/bin/env python3
"""Build the third, review-driven evidence-led Docentric Copilot demo video.

Outputs (all under ``docs/media``):

* ``demo-v3.mp4``          1920x1080, 30 fps, H.264/AAC, 02:46
* ``demo-v3.srt``          English captions aligned to the synthesised narration
* ``thumbnail-v3.png``     1280x720 title card with one benchmark metric
* ``narration-v3.md``      full script with scene timings and the voiceover rule
* ``scene-manifest-v3.json`` claims mapped to real artifacts

Changes from v2: the brief is typed frame-by-frame, the voiceover carries no
small numeric details, the document scenes use zoomed crops with short
crossfades, and the Gemini benchmark row states the current API-quota
condition instead of a quality result.

The slides are authored at 2560x1440, screenshotted with Playwright and
downscaled to 1080p by ffmpeg. Narration is synthesised with Edge TTS. Every
number on screen is read from ``benchmarks/live_report.json``, the saved demo
session, the saved live trace, the recorded optimize response, or a recorded asset.

Usage::

    PLAYWRIGHT_BROWSERS_PATH=.tools/pw-browsers .venv/bin/python scripts/build_demo_video_v3.py
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import textwrap
import wave
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import edge_tts
import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "docs" / "assets"
MEDIA = ROOT / "docs" / "media"
WORK = ROOT / ".tools" / "video-build" / "v3"
SLIDES = WORK / "slides"
TTS = WORK / "tts"
AUDIO = WORK / "audio"
VIDEO = WORK / "video"
PANELS = WORK / "panels"
CROPS = WORK / "crops"
for directory in (SLIDES, TTS, AUDIO, VIDEO, PANELS, CROPS):
    directory.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".tools" / "pw-browsers"))

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
FFPROBE = FFPROBE if FFPROBE.exists() else Path(shutil.which("ffprobe") or "ffprobe")

W, H = 2560, 1440
OUT_W, OUT_H = 1920, 1080
FPS = 30
VOICE = "en-US-GuyNeural"
BASE_RATE = 4
OUT = MEDIA / "demo-v3.mp4"
SRT = MEDIA / "demo-v3.srt"
THUMB = MEDIA / "thumbnail-v3.png"

NAVY = "#0b1f3a"
INK = "#16233a"
MUTED = "#5b6b82"
PAPER = "#eef2f7"
BLUE = "#2563eb"

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
)
FONT_REGULAR = next((candidate for candidate in FONT_CANDIDATES if Path(candidate).exists()), None)
if FONT_REGULAR is None:
    raise RuntimeError("No usable sans-serif font found for the typed brief panel")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


BENCH = load_json(ROOT / "benchmarks" / "live_report.json")
SESSION = load_json(MEDIA / "demo-session.json")
OPTIMIZE = load_json(MEDIA / "optimize-response.json")
CASES = load_json(ROOT / "benchmarks" / "live_cases.json")

AGG = {row["provider"]: row for row in BENCH["aggregates"]}
OPENAI = AGG["openai"]
ANTHROPIC = AGG["anthropic"]
GEMINI = AGG["gemini"]

BENCH_DATE = BENCH["generated_at"][:10]
CASE_COUNT = BENCH["case_count"]
SPEND = BENCH["budget"]["estimated_spend_usd"]
MAX_SPEND = BENCH["budget"]["max_spend_usd"]
UNKNOWN_COST_RUNS = BENCH["budget"]["unknown_cost_runs"]
PROVIDER_COUNT = len(BENCH["providers"])

COST_PER_VALID = {}
for key, row in AGG.items():
    cost = row["cost_usd"]
    successful = row["successful_runs"]
    COST_PER_VALID[key] = cost / successful if cost is not None and successful else None

OPENAI_VALID = OPENAI["successful_runs"]
ANTHROPIC_VALID = ANTHROPIC["successful_runs"]
GEMINI_VALID = GEMINI["successful_runs"]
OPENAI_RUNS = OPENAI["runs"]
ANTHROPIC_RUNS = ANTHROPIC["runs"]
GEMINI_RUNS = GEMINI["runs"]

OPENAI_P50 = OPENAI["latency_ms"]["p50"]
ANTHROPIC_P50 = ANTHROPIC["latency_ms"]["p50"]
OPENAI_COST_PER = COST_PER_VALID["openai"]
ANTHROPIC_COST_PER = COST_PER_VALID["anthropic"]

ROUTING_ROW = next(
    row
    for row in BENCH["runs"]
    if row["case_id"] == "simple-company-identity" and row["provider"] == "openai"
)
ROUTING_RUN_ID = ROUTING_ROW["run_id"]
ROUTING_TRACE = load_json(MEDIA / "runs" / f"{ROUTING_RUN_ID}.json")
ROUTING_LATENCY = ROUTING_ROW["latency_ms"] / 1000
ROUTING_COST = ROUTING_ROW["cost_usd"]

DOCX_ARTIFACT = next(item for item in SESSION["artifacts"] if item["kind"] == "docx")
DOCX_BYTES = DOCX_ARTIFACT["size_bytes"]
DOCX_PAGES = 2
SCHEMA_STATS = SESSION["stats"]
SCHEMA_SECTIONS = SESSION["sections"]
DIAG_COUNT = len(SESSION["diagnostics"])

OPT_FIXES = OPTIMIZE["fixes"]
OPT_IR_DIFF = OPTIMIZE["ir_diff"]
OPT_WIDTH = next(fix for fix in OPT_FIXES if fix["id"] == "fit_text_width")
OPT_FONT = next(fix for fix in OPT_FIXES if fix["id"] == "fit_text_font")
OPT_ITEMS = len(OPT_IR_DIFF)

BEFORE_FIT = next(c for c in OPTIMIZE["before"]["checks"] if c["id"] == "text_fit")
AFTER_FIT = next(c for c in OPTIMIZE["after"]["checks"] if c["id"] == "text_fit")
BEFORE_CELLS = int(re.search(r"(\d+) table cell", BEFORE_FIT["message"]).group(1))
BEFORE_LINES = int(re.search(r"(\d+) estimated lines", BEFORE_FIT["message"]).group(1))
BEFORE_WORST = int(re.search(r"~(\d+) lines", BEFORE_FIT["message"]).group(1))

REVISION_CHANGES = 5
REVISION_ADDED = 0
REVISION_REMOVED = 0

# The brief is the recorded text in docs/assets/routing-panel.png.  It is
# re-typed in the animation, and its length (281 characters) matches the
# panel's recorded 281/5000 counter.
BRIEF = (
    "Create a professional sales quotation with the company logo, customer details, quotation "
    "number and date, product lines with quantities and unit prices, line amounts, the final "
    "amount, the VAT number, bank details in the footer, and an EU VAT notice when the customer "
    "is in the EU."
)
BRIEF_CHARS = len(BRIEF)

SCENE_SECONDS = [14, 16, 24, 22, 26, 32, 17, 15]
SCENE_TITLES = [
    "Hook",
    "Data source and schema",
    "Brief and adaptive routing",
    "Multi-LLM benchmark",
    "DOCX artifact",
    "Visual defect to repair",
    "Revision V1/V2",
    "Closing",
]
SCENE_CLAIMS = [
    "A quotation brief becomes a two-page DOCX with the schema, validation and diff attached.",
    "The document is grounded in a normalized schema: 34 fields, 3 sections, 1 repeating collection.",
    "The prompt panel recommends Anthropic; the live quotation run used gpt-6-sol and passed the validation gate.",
    "Across 6 live cases, gpt-6-sol and claude-sonnet-5-5 each produced 6 valid templates; Gemini has no valid run (API quota exceeded).",
    "quotation.docx is 40,585 bytes and two pages; the zoomed views are an independent preview and a LibreOffice rendering, not a Word fidelity claim.",
    "The defect is 62.0 mm at 9.5 pt; the repair is 88.7 mm at 9.0 pt, 7 IR fields changed, and text-fit passes.",
    "V1 to V2 changed 5 IR fields, added 0 and removed 0; either version can be restored.",
    "Docentric Copilot is open source on GitHub; Docentric AX compatibility is not tested.",
]
SCENE_NARRATION = [
    "A business brief should become a document a team can review, not a black box. "
    "This is Docentric Copilot: a quotation brief in, a reviewable DOCX out, with schema, validation "
    "and version history attached.",
    "Here is a synthetic package with sample data, parser diagnostics and a normalized field tree. "
    "The schema is typed, so every field the document can bind has a type and a source. Nothing is "
    "invented from the prompt alone.",
    "The brief is the only input. It says what the document must contain, and the planner maps each "
    "requirement to the schema. Routing weighs that brief and recommends a provider, but a "
    "recommendation is not execution. The live trace records the model that actually ran, and the "
    "validation gate it passed. You do not have to guess which model to use.",
    "The benchmark runs a fixed set of cases through each provider and records what came back. The "
    "table is read straight from the live report: valid templates, latency, and what each valid "
    "template cost. Cost is derived from measured spend and valid runs. It is an observation, not a "
    "significance claim, and the slide keeps the caveats visible.",
    "Download the document and open it. The preview and the LibreOffice render are independent views "
    "of the same file, and each is labelled for what it is. The preview checks content and field "
    "binding. The LibreOffice page checks an independent render. This is a LibreOffice rendering, "
    "not a Microsoft Word fidelity claim, and not a claim about Docentric AX compatibility.",
    "Here is the defect. The description column is too narrow, so the text wraps past the line "
    "budget, and the checker flags a text-fit warning. Optimize layout applies typed changes to the "
    "template: it rebalances the columns, widens the description and adjusts the table font. The "
    "panel reruns the checks, and the after render uses fewer lines. The change is reviewable in the "
    "diff, not hidden in a binary. This is a LibreOffice rendering, not Word pagination.",
    "Every edit creates an immutable version. Compare versions names each changed field, and Restore "
    "version brings either revision back into the workspace. The diff and rollback are part of the "
    "deliverable, not an afterthought. A reviewer can see exactly what changed and undo it.",
    "Docentric Copilot is open source on GitHub under the Apache license. The demo, the benchmark and "
    "the evidence are in the repository. Docentric AX compatibility: not tested.",
]
SCENE_ASSETS = [
    "docs/assets/preview-pages.png",
    "docs/assets/schema-explorer.png",
    "docs/assets/routing-panel.png (recorded prompt panel, re-typed for the animation); "
    "docs/media/runs/bench_6312bb882a834b97.json",
    "benchmarks/live_report.json (rendered benchmark table)",
    "docs/assets/preview-pages.png; docs/assets/quality-before-libreoffice.png",
    "docs/assets/quality-before-libreoffice.png; docs/assets/quality-after-libreoffice.png; "
    "docs/media/optimize-response.json",
    "docs/assets/revision-v1-v2.png",
    "README.md; LICENSE",
]
SCENE_EVIDENCE = [
    "docs/media/demo-session.json artifacts[docx].size_bytes=40585 and docs/assets/preview-pages.png "
    "(page 1 of 2, page 2 of 2).",
    "docs/media/demo-session.json stats: node_count=34, collection_count=1, max_depth=3; sections "
    "MainData, GeneralData, Parameters; diagnostics length=3.",
    "docs/assets/routing-panel.png (Ambiguous; anthropic; budget $0.30; human review; 281/5000 brief) "
    "and benchmarks/live_report.json run simple-company-identity/openai (actual_model gpt-6-sol, "
    "latency 19402 ms, cost 0.035580 USD, validation_passed true). The animation re-types the recorded "
    "281-character brief; the routing result and live trace are recorded, not re-run.",
    "benchmarks/live_report.json aggregates: openai 6/6, p50 19002 ms, cost 0.199774 USD; anthropic "
    "6/6, p50 14235.5 ms, cost 0.279024 USD; gemini successful_runs=0, runs=6, latency/cost null. "
    "Gemini row is a status category, not a quality result: the review reports the Gemini key returns "
    "HTTP 429 quota exceeded, and no Gemini quality, latency or cost figure is claimed. Cost per valid "
    "template is derived as cost_usd / successful_runs.",
    "docs/media/demo-session.json artifacts[docx].size_bytes=40585; docs/assets/preview-pages.png shows "
    "two preview pages at 1600x1000; docs/assets/quality-before-libreoffice.png is page 1 of 2 at "
    "1241x1754, recorded from LibreOffice Writer 25.2 + pdftoppm. Video uses 130-155% crops centred on "
    "the items table and totals.",
    "docs/media/optimize-response.json fixes fit_text_width 62.0 -> 88.7 mm and fit_text_font 9.5 -> "
    "9.0 pt; ir_diff has 7 entries; before text_fit warning (2 table cells over 4 estimated lines, "
    "worst Description ~7 lines), after passed; quality-before/after-libreoffice.png are the recorded "
    "LibreOffice renders. Video uses 130-155% crops centred on the Description column.",
    "docs/assets/revision-v1-v2.png: TOTAL CHANGES 5, ADDED 0, REMOVED 0, CHANGED 5; Restore version is "
    "visible on both panes.",
    "README.md GitHub URL https://github.com/SergeyGer/Docentric-Copilot and LICENSE Apache-2.0; "
    "SESSION validation docentric_compatibility=not_tested.",
]

SCENE_STARTS = [sum(SCENE_SECONDS[:i]) for i in range(len(SCENE_SECONDS))]
SCENE_ENDS = [
    start + duration for start, duration in zip(SCENE_STARTS, SCENE_SECONDS, strict=False)
]
TOTAL_SECONDS = sum(SCENE_SECONDS)
assert TOTAL_SECONDS == 166
assert len(BRIEF) == 281


@dataclass
class Sentence:
    text: str
    start: float
    duration: float


@dataclass
class NarratedScene:
    index: int
    audio_path: Path
    duration: float
    samples: np.ndarray
    sentences: list[Sentence]
    rate: int


# --------------------------------------------------------------------------- #
# Images and slide shell
# --------------------------------------------------------------------------- #


def image_uri(image: Image.Image) -> str:
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def data_uri(path: Path, crop: tuple[int, int, int, int] | None = None) -> str:
    image = Image.open(path).convert("RGB")
    if crop is not None:
        image = image.crop(crop)
    return image_uri(image)


def crop_uri(
    path: Path, box: tuple[int, int, int, int], size: tuple[int, int]
) -> str:
    image = Image.open(path).convert("RGB").crop(box).resize(size, Image.LANCZOS)
    return image_uri(image)


def relative_rect(
    rect: tuple[int, int, int, int], crop: tuple[int, int, int, int]
) -> str:
    cx0, cy0, cx1, cy1 = crop
    x0, y0, x1, y1 = rect
    x0, y0 = max(x0, cx0), max(y0, cy0)
    x1, y1 = min(x1, cx1), min(y1, cy1)
    width = max(1, cx1 - cx0)
    height = max(1, cy1 - cy0)
    left = (x0 - cx0) / width * 100
    top = (y0 - cy0) / height * 100
    box_w = (x1 - x0) / width * 100
    box_h = (y1 - y0) / height * 100
    return f"left:{left:.2f}%; top:{top:.2f}%; width:{box_w:.2f}%; height:{box_h:.2f}%;"


def esc(value: object) -> str:
    return html.escape(str(value), quote=False)


CSS = """
* { box-sizing: border-box; }
html, body { margin: 0; width: 2560px; height: 1440px; overflow: hidden; }
body {
  font-family: 'DejaVu Sans', Arial, sans-serif;
  color: #16233a;
  background: #eef2f7;
  -webkit-font-smoothing: antialiased;
}
.stage {
  position: relative;
  width: 2560px;
  height: 1440px;
  padding: 54px 96px 44px;
  display: flex;
  flex-direction: column;
  background:
    radial-gradient(1200px 720px at 92% -8%, rgba(37, 99, 235, 0.10), transparent 60%),
    linear-gradient(155deg, #f9fbfd 0%, #eef3f9 52%, #e7eef7 100%);
  overflow: hidden;
}
.stage.dark {
  color: #f8fafc;
  background:
    radial-gradient(1300px 800px at 84% 2%, #1b4174 0%, rgba(27, 65, 116, 0.0) 62%),
    linear-gradient(150deg, #0d2342 0%, #0b1f3a 56%, #07162a 100%);
}
.stage.dark:before {
  content: '';
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255,255,255,0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.035) 1px, transparent 1px);
  background-size: 96px 96px;
  mask-image: radial-gradient(1100px 760px at 78% 22%, #000 0%, transparent 78%);
  pointer-events: none;
}
.top { display: flex; justify-content: space-between; align-items: center; height: 52px; position: relative; z-index: 2; }
.brand { display: flex; align-items: center; gap: 16px; }
.mark {
  width: 46px; height: 46px; border-radius: 12px;
  background: linear-gradient(145deg, #3b82f6, #1d4ed8);
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-weight: 700; font-size: 27px;
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.28);
}
.brand-name { font-size: 25px; font-weight: 700; letter-spacing: -0.3px; line-height: 1.05; }
.brand-sub { font-size: 17px; color: #64748b; margin-top: 3px; }
.dark .brand-sub { color: #9fb0c8; }
.topmeta { display: flex; align-items: center; gap: 12px; font-size: 17px; letter-spacing: 1.5px; color: #64748b; text-transform: uppercase; }
.dark .topmeta { color: #9fb0c8; }
.topmeta .scene-no { margin-left: 12px; color: #2563eb; font-weight: 700; }
.dark .topmeta .scene-no { color: #7dd3fc; }
.main { flex: 1; display: flex; flex-direction: column; padding-top: 30px; position: relative; z-index: 2; }
.eyebrow { font-size: 20px; font-weight: 700; letter-spacing: 2.6px; text-transform: uppercase; color: #2563eb; margin-bottom: 14px; }
.dark .eyebrow { color: #7dd3fc; }
h1 { margin: 0; font-size: 64px; line-height: 1.04; letter-spacing: -1.4px; font-weight: 700; color: #0f2a54; }
.dark h1 { color: #f8fafc; }
h1.hero-title { font-size: 78px; line-height: 1.02; letter-spacing: -2.2px; }
h1.small { font-size: 56px; }
.accent { color: #2563eb; }
.dark .accent { color: #7dd3fc; }
.lede { font-size: 27px; line-height: 1.42; color: #475569; margin: 18px 0 0; }
.dark .lede { color: #c7d2e4; }
.claim {
  margin-top: 18px; min-height: 82px; border-radius: 16px;
  background: #ffffff; border: 1px solid #d6e0ec;
  display: flex; align-items: center; gap: 18px;
  padding: 16px 26px 16px 20px;
  font-size: 26px; line-height: 1.28; color: #0f2a54; font-weight: 600;
  box-shadow: 0 10px 26px rgba(15, 23, 42, 0.06);
  position: relative; z-index: 2;
}
.claim .cmark {
  flex: 0 0 44px; width: 44px; height: 44px; border-radius: 50%;
  background: #dcfce7; color: #15803d; display: flex; align-items: center; justify-content: center;
  font-size: 24px; font-weight: 700;
}
.dark .claim { background: rgba(255,255,255,0.08); border-color: rgba(255,255,255,0.18); color: #e2e8f0; box-shadow: none; }
.dark .claim .cmark { background: rgba(45, 212, 191, 0.16); color: #5eead4; }
.browser {
  background: #fff; border-radius: 18px; overflow: hidden;
  border: 1px solid rgba(15, 23, 42, 0.12);
  box-shadow: 0 30px 60px rgba(15, 23, 42, 0.23);
}
.browser .bar {
  height: 46px; background: #f1f5f9; border-bottom: 1px solid #e2e8f0;
  display: flex; align-items: center; gap: 14px; padding: 0 18px;
}
.dots { display: flex; gap: 7px; }
.dots i { width: 10px; height: 10px; border-radius: 50%; background: #cbd5e1; display: block; }
.dots i:first-child { background: #fca5a5; }
.dots i:nth-child(2) { background: #fcd34d; }
.dots i:nth-child(3) { background: #86efac; }
.url { font-size: 16px; color: #64748b; letter-spacing: 0.2px; }
.browser img { display: block; width: 100%; height: auto; }
.shotframe {
  background: #fff; border-radius: 16px; overflow: hidden;
  border: 1px solid rgba(15, 23, 42, 0.12);
  box-shadow: 0 22px 48px rgba(15, 23, 42, 0.16);
}
.shotframe img { display: block; width: 100%; height: auto; }
.shotlabel { font-size: 17px; color: #64748b; margin-top: 12px; letter-spacing: 0.2px; }
.dark .shotlabel { color: #9fb0c8; }
.page {
  background: #fff; border-radius: 6px; overflow: hidden;
  border: 1px solid rgba(15, 23, 42, 0.16);
  box-shadow: 0 24px 54px rgba(15, 23, 42, 0.22);
}
.page img { display: block; width: 100%; height: auto; }
.cursor {
  position: absolute; width: 34px; height: 46px; z-index: 8;
  filter: drop-shadow(0 5px 7px rgba(15, 23, 42, 0.35));
  transform: translate(-3px, -3px);
}
.cursor svg { width: 100%; height: 100%; display: block; }
.pill {
  display: inline-flex; align-items: center; gap: 10px;
  border-radius: 999px; padding: 9px 18px; font-size: 18px; font-weight: 600;
  background: #e0ecff; color: #1d4ed8; letter-spacing: 0.2px;
}
.pill.green { background: #dcfce7; color: #166534; }
.pill.amber { background: #fef3c7; color: #92400e; }
.pill.red { background: #fee2e2; color: #991b1b; }
.pill.slate { background: #e2e8f0; color: #334155; }
.dark .pill.slate { background: rgba(255,255,255,0.10); color: #cbd5e1; }
.footnote { font-size: 18px; line-height: 1.45; color: #64748b; margin-top: 14px; }
.footnote b { color: #334155; }
.mono { font-family: 'DejaVu Sans Mono', monospace; }
.zoom-wrap {
  position: relative; border-radius: 14px; overflow: hidden;
  border: 1px solid #d6e0ec; background: #fff;
  box-shadow: 0 18px 40px rgba(15, 23, 42, 0.14);
}
.zoom-wrap img { display: block; width: 100%; height: 100%; object-fit: cover; }
.zoom-badge {
  position: absolute; top: 12px; right: 12px;
  background: rgba(15, 23, 42, .82); color: #fff;
  font-size: 15px; font-weight: 600; padding: 6px 12px;
  border-radius: 999px; letter-spacing: .3px;
}
.callout {
  position: absolute; border: 4px solid #d97706; border-bottom: 0; border-radius: 6px;
  background: rgba(245, 158, 11, .06); pointer-events: none;
}
.callout.green { border-color: #0f766e; background: rgba(13, 148, 136, .05); }
.metric-card { flex: 1; background: #fff; border: 1px solid #d6e0ec; border-radius: 16px; padding: 16px 22px; }
.metric-card .mv { font-size: 34px; font-weight: 700; color: #0f2a54; line-height: 1.05; }
.metric-card .ml { font-size: 18px; color: #64748b; margin-top: 5px; }
.bhead, .brow { display: grid; grid-template-columns: 1.55fr 1fr 1fr 1.18fr; align-items: center; }
.bhead {
  background: #0b1f3a; color: #cbd5e1; font-size: 18px; letter-spacing: 1.8px;
  text-transform: uppercase; padding: 18px 34px; font-weight: 700;
}
.brow { padding: 22px 34px; border-top: 1px solid #e2e8f0; min-height: 188px; }
.bmodel .bname { font-size: 33px; font-weight: 700; color: #0f2a54; display: flex; align-items: center; }
.bmodel .bsub { font-size: 17px; color: #64748b; margin-top: 6px; }
.bmetric .bval { font-size: 58px; font-weight: 700; line-height: 1; color: #0f2a54; }
.bmetric .bval.ok { color: #0f766e; }
.bmetric .bval.warn { color: #b45309; }
.bmetric .bval.bad { color: #b91c1c; }
.bmetric .bval.muted { color: #94a3b8; }
.bmetric .blabel { font-size: 17px; color: #64748b; margin-top: 6px; }
.brow.excluded { background: #fff7ed; }
.brow.excluded .bname { color: #9a3412; font-size: 26px; line-height: 1.16; }
.brow.excluded .bmetric .bval { font-size: 36px; }
"""


def top(n: int) -> str:
    return f"""
    <div class="top">
      <div class="brand">
        <div class="mark">D</div>
        <div>
          <div class="brand-name">Docentric Copilot</div>
          <div class="brand-sub">template engineering workspace</div>
        </div>
      </div>
      <div class="topmeta">
        <span>Demo v3</span><span>·</span><span>{BENCH_DATE}</span>
        <span class="scene-no">{n:02d} / 08</span>
      </div>
    </div>
    """


def claim_bar(index: int, dark: bool = False) -> str:
    return (
        f'<div class="claim{" dark" if dark else ""}">'
        '<div class="cmark">✓</div>'
        f"<div>{esc(SCENE_CLAIMS[index])}</div>"
        "</div>"
    )


def cursor(left: str, top: str) -> str:
    return f"""
    <div class="cursor" style="left:{left}; top:{top}">
      <svg viewBox="0 0 24 32" xmlns="http://www.w3.org/2000/svg">
        <path d="M3.2 2.1 20.8 15.2l-7.5 1.5 4.6 10.1-4.7 2.1-4.4-10.2-5.6 5.2Z"
              fill="#0f172a" stroke="#ffffff" stroke-width="1.7" stroke-linejoin="round"/>
      </svg>
    </div>
    """


# --------------------------------------------------------------------------- #
# Typed prompt panel
# --------------------------------------------------------------------------- #


def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: float) -> list[str]:
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if font.getlength(candidate) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def render_brief_panel(progress: float, path: Path) -> None:
    """Re-render the recorded prompt panel with a partially typed brief.

    Only the textarea text and the character counter are replaced; the rest
    of the panel is the recorded screenshot in docs/assets/routing-panel.png.
    """
    base = Image.open(ASSETS / "routing-panel.png").convert("RGB").crop((100, 148, 908, 760))
    draw = ImageDraw.Draw(base)
    font = ImageFont.truetype(FONT_REGULAR, 16)
    small = ImageFont.truetype(FONT_REGULAR, 12)
    lines = wrap_text(BRIEF, font, 745)

    # Clear the recorded brief and counter, keeping the textarea border and
    # the small resize grip at the bottom right.
    draw.rectangle((40, 128, 790, 320), fill="#ffffff")
    draw.rectangle((728, 90, 800, 114), fill="#ffffff")

    visible = int(BRIEF_CHARS * progress + 1e-6)
    draw.text((797, 94), f"{visible}/5000", font=small, fill="#6b7280", anchor="ra")

    left, top, line_height = 47, 140, 24
    remaining = visible
    last_position: tuple[float, float] | None = None
    for index, line in enumerate(lines):
        if remaining <= 0:
            break
        take = min(len(line), remaining)
        y = top + index * line_height
        draw.text((left, y), line[:take], font=font, fill="#1f2937", anchor="la")
        remaining -= take
        last_position = (left + font.getlength(line[:take]), y)

    if last_position is None:
        caret_x, caret_y = left, top
    else:
        caret_x, caret_y = last_position
    draw.rectangle((caret_x + 1, caret_y + 2, caret_x + 2, caret_y + 18), fill="#1f2937")
    base.save(path)


def build_panel_frames() -> list[Path]:
    panel_paths: list[Path] = []
    for _index, progress in enumerate((0.0, 0.2, 0.4, 0.6, 0.8, 1.0)):
        path = PANELS / f"panel_{progress * 100:03.0f}.png"
        render_brief_panel(progress, path)
        panel_paths.append(path)
    return panel_paths


# --------------------------------------------------------------------------- #
# Slide markup
# --------------------------------------------------------------------------- #


def scene_1() -> str:
    preview = data_uri(ASSETS / "preview-pages.png")
    return f"""
    <div class="stage dark">
      {top(1)}
      <div class="main" style="flex-direction:row; align-items:center; gap:56px; padding-top:26px;">
        <div style="width:1010px; flex:0 0 1010px;">
          <div class="eyebrow">The business problem</div>
          <h1 class="hero-title">From a business brief<br>to a <span class="accent">reviewable DOCX</span>.</h1>
          <p class="lede" style="max-width:940px; font-size:29px;">
            A quotation brief in. A finished document out — with the schema,
            validation and version evidence attached.
          </p>
          <div style="display:flex; gap:20px; margin-top:34px;">
            <div style="background:rgba(255,255,255,.07); border:1px solid rgba(255,255,255,.16); border-radius:16px; padding:20px 24px; min-width:300px;">
              <div style="font-size:58px; font-weight:700; line-height:1;">{OPENAI_VALID}/{OPENAI_RUNS}</div>
              <div style="font-size:20px; color:#c7d2e4; margin-top:8px;">valid templates<br><span style="color:#9fb0c8;">gpt-6-sol · n={OPENAI_RUNS}</span></div>
            </div>
            <div style="background:rgba(255,255,255,.07); border:1px solid rgba(255,255,255,.16); border-radius:16px; padding:20px 24px; min-width:300px;">
              <div style="font-size:58px; font-weight:700; line-height:1;">{DOCX_PAGES}</div>
              <div style="font-size:20px; color:#c7d2e4; margin-top:8px;">pages<br><span style="color:#9fb0c8;">quotation.docx</span></div>
            </div>
          </div>
        </div>
        <div style="position:relative; width:1250px; flex:1;">
          <div class="browser">
            <div class="bar">
              <span class="dots"><i></i><i></i><i></i></span>
              <span class="url">quotation.docx · independent preview</span>
            </div>
            <img src="{preview}" alt="Two-page quotation preview">
          </div>
          <div style="position:absolute; left:-34px; bottom:-26px; display:flex; align-items:center; gap:14px;
                      background:#ffffff; color:#0f2a54; border-radius:14px; padding:14px 20px;
                      box-shadow:0 18px 42px rgba(0,0,0,.28); border:1px solid #dbe3ee;">
            <div style="width:54px; height:54px; border-radius:12px; background:#dbeafe; color:#1d4ed8;
                        display:flex; align-items:center; justify-content:center; font-size:15px; font-weight:700; letter-spacing:.5px;">DOCX</div>
            <div>
              <div style="font-size:21px; font-weight:700;">quotation.docx</div>
              <div style="font-size:17px; color:#64748b; margin-top:2px;">{DOCX_BYTES:,} bytes · {DOCX_PAGES} pages</div>
            </div>
          </div>
          {cursor("1%", "85%")}
        </div>
      </div>
      {claim_bar(0, dark=True)}
    </div>
    """


def scene_2() -> str:
    schema = data_uri(ASSETS / "schema-explorer.png")
    return f"""
    <div class="stage">
      {top(2)}
      <div class="main">
        <div class="eyebrow">Data source + schema</div>
        <h1>Grounded in the customer's own schema.</h1>
        <p class="lede" style="max-width:1420px; font-size:26px;">
          A synthetic DDSP package supplies sample data, parser diagnostics and a normalized
          field tree. Nothing in the document is invented from a prompt alone.
        </p>
        <div style="display:flex; gap:52px; align-items:flex-start; margin-top:22px;">
          <div style="width:840px; flex:0 0 840px;">
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px;">
              <div style="background:#fff; border:1px solid #dbe3ee; border-radius:16px; padding:20px 22px;">
                <div style="font-size:46px; font-weight:700; color:#0f2a54; line-height:1;">{SCHEMA_STATS["node_count"]}</div>
                <div style="font-size:19px; color:#64748b; margin-top:6px;">fields in the schema</div>
              </div>
              <div style="background:#fff; border:1px solid #dbe3ee; border-radius:16px; padding:20px 22px;">
                <div style="font-size:46px; font-weight:700; color:#0f2a54; line-height:1;">{len(SCHEMA_SECTIONS)}</div>
                <div style="font-size:19px; color:#64748b; margin-top:6px;">root sections</div>
              </div>
              <div style="background:#fff; border:1px solid #dbe3ee; border-radius:16px; padding:20px 22px;">
                <div style="font-size:46px; font-weight:700; color:#0f2a54; line-height:1;">{SCHEMA_STATS["collection_count"]}</div>
                <div style="font-size:19px; color:#64748b; margin-top:6px;">repeating collection</div>
              </div>
              <div style="background:#fff; border:1px solid #dbe3ee; border-radius:16px; padding:20px 22px;">
                <div style="font-size:46px; font-weight:700; color:#0f2a54; line-height:1;">{SCHEMA_STATS["max_depth"]}</div>
                <div style="font-size:19px; color:#64748b; margin-top:6px;">levels deep</div>
              </div>
            </div>
            <div style="margin-top:20px; display:flex; gap:10px; flex-wrap:wrap;">
              {"".join(f'<span class="pill">{esc(section)}</span>' for section in SCHEMA_SECTIONS)}
              <span class="pill green">sample data</span>
              <span class="pill amber">{DIAG_COUNT} parser diagnostics</span>
            </div>
            <div style="margin-top:22px; font-size:18px; color:#64748b; line-height:1.5;">
              Evidence: <span class="mono">docs/media/demo-session.json</span> · {SCHEMA_STATS["node_count"]} nodes, {SCHEMA_STATS["collection_count"]} collection, depth {SCHEMA_STATS["max_depth"]}.
            </div>
          </div>
          <div style="flex:1; position:relative;">
            <div class="shotframe">
              <img src="{schema}" alt="Schema explorer with typed fields">
            </div>
            <div class="shotlabel">Workspace schema explorer · {SCHEMA_STATS["node_count"]} fields, typed and searchable</div>
            {cursor("46%", "61%")}
          </div>
        </div>
      </div>
      {claim_bar(1)}
    </div>
    """


def scene_3(panel: Path) -> str:
    panel_uri = data_uri(panel)
    return f"""
    <div class="stage">
      {top(3)}
      <div class="main">
        <div class="eyebrow">Prompt + live adaptive routing</div>
        <h1 class="small">The brief, then the decision.</h1>
        <p class="lede" style="max-width:1540px; font-size:25px;">
          The brief is typed in the recorded workspace panel. The recommendation and the executed
          model are separate facts; the live trace records which model actually ran.
        </p>
        <div style="display:flex; gap:40px; align-items:stretch; margin-top:16px;">
          <div style="width:1000px; flex:0 0 1000px; position:relative;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
              <div style="font-size:17px; letter-spacing:1.6px; text-transform:uppercase; color:#64748b; font-weight:700;">
                Workspace prompt panel
              </div>
              <div class="pill" style="font-size:15px; padding:6px 12px;">Document brief</div>
            </div>
            <div class="shotframe" style="border-radius:16px;">
              <img src="{panel_uri}" style="display:block; width:1000px; height:757px;" alt="Prompt panel with the brief being typed">
            </div>
            <div class="shotlabel" style="max-width:980px;">
              Brief typed for this animation · routing result and live trace are recorded.
            </div>
          </div>
          <div style="flex:1; background:#0b1f3a; color:#e2e8f0; border-radius:20px; padding:26px 32px;
                      box-shadow:0 24px 52px rgba(15,23,42,.20); position:relative;">
            <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid rgba(255,255,255,.15); padding-bottom:14px;">
              <div style="font-size:19px; letter-spacing:2px; text-transform:uppercase; color:#7dd3fc; font-weight:700;">Live run trace</div>
              <div class="pill green" style="font-size:15px; padding:7px 14px;">validation gate passed</div>
            </div>
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:0 34px; margin-top:2px;">
              <div style="padding:12px 0; border-bottom:1px solid rgba(255,255,255,.12);">
                <div style="font-size:16px; letter-spacing:1.4px; text-transform:uppercase; color:#94a3b8;">Complexity</div>
                <div style="font-size:29px; font-weight:600; margin-top:4px;">Ambiguous</div>
              </div>
              <div style="padding:12px 0; border-bottom:1px solid rgba(255,255,255,.12);">
                <div style="font-size:16px; letter-spacing:1.4px; text-transform:uppercase; color:#94a3b8;">Panel recommends</div>
                <div style="font-size:29px; font-weight:600; margin-top:4px;">Anthropic</div>
              </div>
              <div style="padding:12px 0; border-bottom:1px solid rgba(255,255,255,.12);">
                <div style="font-size:16px; letter-spacing:1.4px; text-transform:uppercase; color:#94a3b8;">Executed model</div>
                <div style="font-size:34px; font-weight:700; margin-top:4px; color:#5eead4;">{esc(ROUTING_ROW["actual_model"])}</div>
              </div>
              <div style="padding:12px 0; border-bottom:1px solid rgba(255,255,255,.12);">
                <div style="font-size:16px; letter-spacing:1.4px; text-transform:uppercase; color:#94a3b8;">Provider</div>
                <div style="font-size:29px; font-weight:600; margin-top:4px;">openai</div>
              </div>
              <div style="padding:12px 0; border-bottom:1px solid rgba(255,255,255,.12);">
                <div style="font-size:16px; letter-spacing:1.4px; text-transform:uppercase; color:#94a3b8;">Latency</div>
                <div style="font-size:29px; font-weight:600; margin-top:4px;">{ROUTING_LATENCY:.1f} s</div>
              </div>
              <div style="padding:12px 0; border-bottom:1px solid rgba(255,255,255,.12);">
                <div style="font-size:16px; letter-spacing:1.4px; text-transform:uppercase; color:#94a3b8;">Estimated cost</div>
                <div style="font-size:29px; font-weight:600; margin-top:4px;">${ROUTING_COST:.4f}</div>
              </div>
            </div>
            <div style="display:flex; justify-content:space-between; align-items:flex-end; margin-top:12px;">
              <div style="font-size:17px; color:#94a3b8; line-height:1.45;">
                Case: <span class="mono" style="color:#cbd5e1;">simple-company-identity</span><br>
                V1–V3 passed · V4 visual warning · V5 not_tested
              </div>
              <div style="font-size:15px; color:#7f93ad; text-align:right; line-height:1.45;">
                run_id <span class="mono" style="color:#cbd5e1;">{ROUTING_RUN_ID}</span><br>
                benchmark row + saved trace
              </div>
            </div>
          </div>
        </div>
      </div>
      {claim_bar(2)}
    </div>
    """


def bench_row(row: dict, recommended: bool) -> str:
    provider = row["provider"]
    model = row["model"]
    valid = row["successful_runs"]
    runs = row["runs"]
    p50 = row["latency_ms"]["p50"]
    per = COST_PER_VALID[provider]
    valid_class = "ok" if valid == runs else ("warn" if valid else "bad")
    p50_text = f"{p50 / 1000:.1f} s" if p50 is not None else "—"
    per_text = f"${per:,.4f}" if per is not None else "—"
    badge = (
        '<span class="pill green" style="font-size:15px; padding:6px 12px; margin-left:12px;">recommended</span>'
        if recommended
        else ""
    )
    sub = f"validation {row['validation_pass_rate'] * 100:.0f}% · compile {row['compilation_success_rate'] * 100:.0f}%"
    return f"""
      <div class="brow">
        <div class="bmodel">
          <div class="bname">{esc(model)}{badge}</div>
          <div class="bsub">{esc(provider)} · {sub}</div>
        </div>
        <div class="bmetric">
          <div class="bval {valid_class}">{valid}/{runs}</div>
          <div class="blabel">valid templates</div>
        </div>
        <div class="bmetric">
          <div class="bval">{p50_text}</div>
          <div class="blabel">p50 latency</div>
        </div>
        <div class="bmetric">
          <div class="bval">{per_text}</div>
          <div class="blabel">cost / valid template</div>
        </div>
      </div>
    """


def gemini_row() -> str:
    return f"""
      <div class="brow excluded">
        <div class="bmodel">
          <div class="bname">Gemini — API quota exceeded; no valid run</div>
          <div class="bsub">{esc(GEMINI["model"])} · {GEMINI_RUNS} attempts · excluded from quality, latency and cost</div>
        </div>
        <div class="bmetric">
          <div class="bval muted">—</div>
          <div class="blabel">valid templates</div>
        </div>
        <div class="bmetric">
          <div class="bval muted">—</div>
          <div class="blabel">p50 latency</div>
        </div>
        <div class="bmetric">
          <div class="bval muted">—</div>
          <div class="blabel">cost / valid template</div>
        </div>
      </div>
    """


def scene_4() -> str:
    rec = BENCH["recommendation"]["provider"]
    return f"""
    <div class="stage">
      {top(4)}
      <div class="main">
        <div class="eyebrow">Multi-LLM benchmark · {CASE_COUNT} live cases</div>
        <h1>One fixed case set. Measured results.</h1>
        <p class="lede" style="max-width:1500px; font-size:24px; margin-top:10px;">
          The table is read from the live report. Gemini is shown as a status category, not a
          quality result: the API quota was exceeded and no valid run completed.
        </p>
        <div style="margin-top:16px; background:#fff; border:1px solid #d6e0ec; border-radius:20px; overflow:hidden;
                    box-shadow:0 18px 42px rgba(15,23,42,.08);">
          <div class="bhead">
            <div>Provider / model</div><div>Valid templates</div><div>p50 latency</div><div>Cost per valid template</div>
          </div>
          {bench_row(OPENAI, rec == "openai")}
          {bench_row(ANTHROPIC, rec == "anthropic")}
          {gemini_row()}
        </div>
        <div class="footnote" style="max-width:2340px;">
          <b>n = {CASE_COUNT} cases per provider · {BENCH_DATE} · one run per case · {PROVIDER_COUNT} models configured:</b>
          openai:gpt-6-sol, anthropic:claude-sonnet-5-5, gemini:{esc(GEMINI["model"])}.
          Estimated spend ${SPEND:.6f} of ${MAX_SPEND:.2f}; unknown-cost runs: {UNKNOWN_COST_RUNS}.
          <b>Cost per valid template = provider cost ÷ successful runs.</b>
          <b>Gemini:</b> the API quota was exceeded on the provider key; {GEMINI_RUNS} attempts produced
          {GEMINI_VALID} valid runs, so no Gemini quality, latency or cost result is claimed. A dash is not $0.00.
          These are observations, not a significance claim.
        </div>
      </div>
      {claim_bar(3)}
    </div>
    """


def callout_style(rect: tuple[int, int, int, int], crop: tuple[int, int, int, int]) -> str:
    return relative_rect(rect, crop)


# --------------------------------------------------------------------------- #
# Zoom crops for the document scenes
# --------------------------------------------------------------------------- #

PREVIEW_BOXES = {
    "wide": (200, 372, 770, 694),
    "mid": (215, 370, 755, 675),
    "tight": (220, 380, 750, 713),
}
LIBRE_BOXES = {
    "wide": (17, 484, 1232, 1170),
    "mid": (80, 520, 1170, 1135),
    "tight": (100, 590, 1200, 1281),
}
SINGLE_BOX = (90, 590, 1120, 1384)
COMPARE_BOX = (90, 590, 1120, 1234)
DESCRIPTION_BEFORE = (245, 654, 620, 1130)
DESCRIPTION_AFTER = (205, 654, 740, 990)


def scene_5(variant: str) -> str:
    pills = f"""
      <div style="display:flex; gap:14px; margin-top:14px; flex-wrap:wrap;">
        <span class="pill slate">01 Download · {DOCX_BYTES:,} bytes</span>
        <span class="pill slate">02 Open</span>
        <span class="pill slate">03 {DOCX_PAGES} pages</span>
        <span class="pill green">DOCX + evidence</span>
      </div>
    """
    if variant == "preview":
        preview = crop_uri(ASSETS / "preview-pages.png", PREVIEW_BOXES["wide"], (1400, 790))
        return f"""
        <div class="stage">
          {top(5)}
          <div class="main">
            <div class="eyebrow">DOCX artifact · independent preview</div>
            <h1>Download it. Open it. Check it.</h1>
            <p class="lede" style="max-width:1520px; font-size:25px;">
              The document is the deliverable. This is a zoom on the independent preview, centred on
              the items table and totals.
            </p>
            {pills}
            <div style="display:flex; gap:44px; align-items:flex-start; margin-top:18px;">
              <div style="width:1400px; flex:0 0 1400px; position:relative;">
                <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:8px;">
                  <div style="font-size:18px; letter-spacing:1.5px; text-transform:uppercase; color:#1d4ed8; font-weight:700;">
                    Independent preview · items and totals
                  </div>
                  <div class="pill" style="font-size:15px; padding:6px 12px;">zoom 130%</div>
                </div>
                <div class="zoom-wrap" style="width:1400px; height:790px;">
                  <img src="{preview}" alt="Zoomed independent preview of the items table and totals">
                </div>
                <div class="shotlabel">Preview layout differs from Word/Docentric pagination · content and field binding check</div>
              </div>
              <div style="flex:1; padding-top:34px;">
                <div style="font-size:22px; line-height:1.4; color:#334155; font-weight:600;">A real file, not a screenshot of an idea.</div>
                <div style="font-size:20px; line-height:1.55; color:#64748b; margin-top:14px;">
                  The DOCX is the deliverable. The preview checks content and field binding; the
                  LibreOffice page checks an independent render. Each view is labelled for what it is.
                </div>
                <div style="margin-top:24px; background:#fff; border:1px solid #d6e0ec; border-radius:16px; padding:20px 24px;">
                  <div style="font-size:46px; font-weight:700; color:#0f2a54; line-height:1;">{DOCX_BYTES:,}</div>
                  <div style="font-size:18px; color:#64748b; margin-top:6px;">bytes in the compiled DOCX</div>
                  <div style="font-size:18px; color:#0f2a54; font-weight:600; margin-top:14px;">{DOCX_PAGES} pages · quotation.docx</div>
                </div>
                <div style="margin-top:20px; border-left:4px solid #2563eb; background:#eff6ff; border-radius:0 12px 12px 0; padding:14px 18px; font-size:18px; line-height:1.45; color:#1e3a8a;">
                  <b>Zoomed for review.</b> Full-page layout is not the claim; the table and totals are.
                </div>
              </div>
            </div>
          </div>
          {claim_bar(4)}
        </div>
        """
    if variant == "zoom":
        preview = crop_uri(ASSETS / "preview-pages.png", PREVIEW_BOXES["mid"], (1120, 632))
        libre = crop_uri(ASSETS / "quality-before-libreoffice.png", LIBRE_BOXES["mid"], (1120, 632))
        return f"""
        <div class="stage">
          {top(5)}
          <div class="main">
            <div class="eyebrow">DOCX artifact · independent views</div>
            <h1 class="small">Same file. Independent views.</h1>
            <p class="lede" style="max-width:1540px; font-size:24px;">
              Zoomed on the items table. The preview checks content; the LibreOffice page checks an
              independent render. Neither is a Word pagination claim.
            </p>
            {pills}
            <div style="display:flex; gap:40px; align-items:flex-start; justify-content:center; margin-top:16px;">
              <div style="width:1120px; flex:0 0 1120px;">
                <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:8px;">
                  <div style="font-size:17px; letter-spacing:1.5px; text-transform:uppercase; color:#1d4ed8; font-weight:700;">Independent preview</div>
                  <div class="pill" style="font-size:15px; padding:6px 12px;">zoom 145%</div>
                </div>
                <div class="zoom-wrap" style="width:1120px; height:632px;">
                  <img src="{preview}" alt="Independent preview zoomed on the items table">
                </div>
                <div class="shotlabel">Items and totals · content and field binding</div>
              </div>
              <div style="width:1120px; flex:0 0 1120px;">
                <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:8px;">
                  <div style="font-size:17px; letter-spacing:1.5px; text-transform:uppercase; color:#b45309; font-weight:700;">LibreOffice rendering</div>
                  <div class="pill amber" style="font-size:15px; padding:6px 12px;">not Word fidelity</div>
                </div>
                <div class="zoom-wrap" style="width:1120px; height:632px;">
                  <img src="{libre}" alt="LibreOffice rendering of page 1 zoomed on the items table">
                </div>
                <div class="shotlabel">Page 1 of 2 · 1241×1754 render · independent check</div>
              </div>
            </div>
          </div>
          {claim_bar(4)}
        </div>
        """
    preview = crop_uri(ASSETS / "preview-pages.png", PREVIEW_BOXES["tight"], (1120, 704))
    libre = crop_uri(ASSETS / "quality-before-libreoffice.png", LIBRE_BOXES["tight"], (1120, 704))
    return f"""
    <div class="stage">
      {top(5)}
      <div class="main">
        <div class="eyebrow">DOCX artifact · totals</div>
        <h1 class="small">The totals, up close.</h1>
        <p class="lede" style="max-width:1540px; font-size:24px;">
          The same file, read through two independent views. The LibreOffice page is labelled as a
          render, not as Microsoft Word pagination.
        </p>
        {pills}
        <div style="display:flex; gap:40px; align-items:flex-start; justify-content:center; margin-top:16px;">
          <div style="width:1120px; flex:0 0 1120px;">
            <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:8px;">
              <div style="font-size:17px; letter-spacing:1.5px; text-transform:uppercase; color:#1d4ed8; font-weight:700;">Independent preview · totals</div>
              <div class="pill" style="font-size:15px; padding:6px 12px;">zoom 155%</div>
            </div>
            <div class="zoom-wrap" style="width:1120px; height:704px;">
              <img src="{preview}" alt="Independent preview zoomed on the totals">
            </div>
          </div>
          <div style="width:1120px; flex:0 0 1120px;">
            <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:8px;">
              <div style="font-size:17px; letter-spacing:1.5px; text-transform:uppercase; color:#b45309; font-weight:700;">LibreOffice rendering · totals</div>
              <div class="pill amber" style="font-size:15px; padding:6px 12px;">labelled render</div>
            </div>
            <div class="zoom-wrap" style="width:1120px; height:704px;">
              <img src="{libre}" alt="LibreOffice rendering zoomed on the totals">
            </div>
          </div>
        </div>
        <div style="margin-top:16px; border-left:4px solid #f59e0b; background:#fffbeb; border-radius:0 12px 12px 0; padding:12px 18px; font-size:17px; line-height:1.45; color:#78350f; max-width:2300px;">
          <b>LibreOffice rendering.</b> Not a screen recording, not Microsoft Word, and not a Docentric AX compatibility claim.
        </div>
      </div>
      {claim_bar(4)}
    </div>
    """


def metric_cards() -> str:
    return f"""
      <div style="display:flex; gap:18px; margin-top:18px;">
        <div class="metric-card">
          <div class="mv">{OPT_WIDTH["before"]:.1f} → {OPT_WIDTH["after"]:.1f} mm</div>
          <div class="ml">Description width</div>
        </div>
        <div class="metric-card">
          <div class="mv">{OPT_FONT["before"]:.1f} → {OPT_FONT["after"]:.1f} pt</div>
          <div class="ml">Table font</div>
        </div>
        <div class="metric-card">
          <div class="mv">{OPT_ITEMS} IR fields</div>
          <div class="ml">changed by Optimize layout</div>
        </div>
        <div class="metric-card">
          <div class="mv">~{BEFORE_WORST} → pass</div>
          <div class="ml">worst cell lines → text_fit</div>
        </div>
      </div>
    """


def scene_6(variant: str) -> str:
    if variant == "before":
        before = crop_uri(ASSETS / "quality-before-libreoffice.png", SINGLE_BOX, (1120, 864))
        callout = callout_style(DESCRIPTION_BEFORE, SINGLE_BOX)
        return f"""
        <div class="stage">
          {top(6)}
          <div class="main">
            <div class="eyebrow">Visual defect · before</div>
            <h1 class="small">A visual defect, caught by the checker.</h1>
            <p class="lede" style="max-width:1520px; font-size:24px;">
              The Description column is narrow, so the text wraps past the line budget. This is the
              recorded LibreOffice render, zoomed on the defect area.
            </p>
            <div style="display:flex; gap:44px; align-items:flex-start; margin-top:14px;">
              <div style="width:1120px; flex:0 0 1120px;">
                <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:8px;">
                  <div style="font-size:18px; letter-spacing:1.5px; text-transform:uppercase; color:#b45309; font-weight:700;">LibreOffice rendering · before</div>
                  <div style="display:flex; align-items:center; gap:10px;">
                    <span style="font-size:15px; color:#64748b;">zoom 145%</span>
                    <div class="pill amber" style="font-size:16px; padding:6px 12px;">text_fit warning</div>
                  </div>
                </div>
                <div class="zoom-wrap" style="width:1120px; height:864px;">
                  <img src="{before}" alt="Before repair: zoom on the narrow Description column">
                  <div class="callout" style="{callout}"></div>
                </div>
                <div class="shotlabel">Description {OPT_WIDTH["before"]:.1f} mm · {OPT_FONT["before"]:.1f} pt · {BEFORE_CELLS} cells estimated over {BEFORE_LINES} lines</div>
              </div>
              <div style="flex:1; padding-top:26px;">
                <div style="font-size:20px; line-height:1.55; color:#475569;">
                  The panel does not just flag a warning. It saves the typed IR, applies focused layout
                  changes, and reruns the checks.
                </div>
                <div style="margin-top:22px; background:#fff; border:1px solid #d6e0ec; border-radius:16px; padding:18px 22px;">
                  <div style="font-size:16px; letter-spacing:1.4px; text-transform:uppercase; color:#b45309; font-weight:700;">Worst cell</div>
                  <div style="font-size:34px; font-weight:700; color:#0f2a54; margin-top:8px;">~{BEFORE_WORST} lines</div>
                  <div style="font-size:17px; color:#64748b; margin-top:4px;">Description at {OPT_WIDTH["before"]:.1f} mm / {OPT_FONT["before"]:.1f} pt</div>
                </div>
                <div style="margin-top:18px; border-left:4px solid #f59e0b; background:#fffbeb; border-radius:0 12px 12px 0; padding:14px 18px; font-size:17px; line-height:1.45; color:#78350f;">
                  <b>Recorded check:</b> {esc(BEFORE_CELLS)} table cells exceed {BEFORE_LINES} estimated lines.
                </div>
                <div style="margin-top:18px; background:#0b1f3a; color:#e2e8f0; border-radius:16px; padding:18px 22px;">
                  <div style="font-size:16px; letter-spacing:1.4px; text-transform:uppercase; color:#7dd3fc; font-weight:700; margin-bottom:10px;">What Optimize layout does</div>
                  <div style="font-size:18px; line-height:1.6;">Widen the Description column.<br>Rebalance the other columns.<br>Adjust the table font.</div>
                </div>
              </div>
            </div>
          </div>
          {claim_bar(5)}
        </div>
        """
    if variant == "after":
        after = crop_uri(ASSETS / "quality-after-libreoffice.png", SINGLE_BOX, (1120, 864))
        callout = callout_style(DESCRIPTION_AFTER, SINGLE_BOX)
        return f"""
        <div class="stage">
          {top(6)}
          <div class="main">
            <div class="eyebrow">Visual defect · after</div>
            <h1 class="small">The checks pass. The lines drop.</h1>
            <p class="lede" style="max-width:1520px; font-size:24px;">
              Optimize layout widens the Description column, rebalances the others and adjusts the
              table font. The zoom shows the repaired area.
            </p>
            <div style="display:flex; gap:44px; align-items:flex-start; margin-top:14px;">
              <div style="width:1120px; flex:0 0 1120px;">
                <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:8px;">
                  <div style="font-size:18px; letter-spacing:1.5px; text-transform:uppercase; color:#0f766e; font-weight:700;">LibreOffice rendering · after</div>
                  <div style="display:flex; align-items:center; gap:10px;">
                    <span style="font-size:15px; color:#64748b;">zoom 145%</span>
                    <div class="pill green" style="font-size:16px; padding:6px 12px;">text_fit passed</div>
                  </div>
                </div>
                <div class="zoom-wrap" style="width:1120px; height:864px;">
                  <img src="{after}" alt="After repair: zoom on the widened Description column">
                  <div class="callout green" style="{callout}"></div>
                </div>
                <div class="shotlabel">Description {OPT_WIDTH["after"]:.1f} mm · {OPT_FONT["after"]:.1f} pt · the same text uses fewer lines</div>
              </div>
              <div style="flex:1; padding-top:26px;">
                <div style="font-size:20px; line-height:1.55; color:#475569;">
                  The after render is a recorded LibreOffice page, not a Word pagination claim. The
                  typed diff is what makes the change reviewable.
                </div>
                <div style="margin-top:22px; background:#fff; border:1px solid #d6e0ec; border-radius:16px; padding:18px 22px;">
                  <div style="font-size:16px; letter-spacing:1.4px; text-transform:uppercase; color:#0f766e; font-weight:700;">Text fit</div>
                  <div style="font-size:34px; font-weight:700; color:#0f2a54; margin-top:8px;">passed</div>
                  <div style="font-size:17px; color:#64748b; margin-top:4px;">no table cell exceeds the line budget</div>
                </div>
                <div style="margin-top:18px; background:#0b1f3a; color:#e2e8f0; border-radius:16px; padding:16px 20px;">
                  <div style="font-size:16px; letter-spacing:1.4px; text-transform:uppercase; color:#7dd3fc; font-weight:700; margin-bottom:6px;">Applied changes</div>
                  <div style="font-size:17px; line-height:1.5;">{OPT_ITEMS} IR fields · width {OPT_WIDTH["before"]:.1f} → {OPT_WIDTH["after"]:.1f} mm · font {OPT_FONT["before"]:.1f} → {OPT_FONT["after"]:.1f} pt</div>
                </div>
              </div>
            </div>
          </div>
          {claim_bar(5)}
        </div>
        """
    before = crop_uri(ASSETS / "quality-before-libreoffice.png", COMPARE_BOX, (1120, 700))
    after = crop_uri(ASSETS / "quality-after-libreoffice.png", COMPARE_BOX, (1120, 700))
    before_callout = callout_style(DESCRIPTION_BEFORE, COMPARE_BOX)
    after_callout = callout_style(DESCRIPTION_AFTER, COMPARE_BOX)
    return f"""
    <div class="stage">
      {top(6)}
      <div class="main">
        <div class="eyebrow">Visual defect to repair</div>
        <h1 class="small">Typed changes. Rerun checks. Fewer lines.</h1>
        <p class="lede" style="max-width:1540px; font-size:24px;">
          Optimize layout applies typed IR changes to the template and reruns the checks. Both pages
          are recorded LibreOffice renders, zoomed on the changed area.
        </p>
        <div style="display:flex; gap:40px; margin-top:14px; justify-content:center;">
          <div style="width:1120px; flex:0 0 1120px;">
            <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:8px;">
              <div style="font-size:17px; letter-spacing:1.5px; text-transform:uppercase; color:#b45309; font-weight:700;">LibreOffice rendering · before</div>
              <div style="display:flex; align-items:center; gap:10px;">
                    <span style="font-size:15px; color:#64748b;">zoom 145%</span>
                    <div class="pill amber" style="font-size:16px; padding:6px 12px;">text_fit warning</div>
                  </div>
            </div>
            <div class="zoom-wrap" style="width:1120px; height:700px;">
              <img src="{before}" alt="Before repair: zoom on the narrow Description column">
              <div class="callout" style="{before_callout}"></div>
            </div>
            <div class="shotlabel">{OPT_WIDTH["before"]:.1f} mm · {OPT_FONT["before"]:.1f} pt · {esc(BEFORE_CELLS)} cells over {BEFORE_LINES} lines</div>
          </div>
          <div style="width:1120px; flex:0 0 1120px;">
            <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:8px;">
              <div style="font-size:17px; letter-spacing:1.5px; text-transform:uppercase; color:#0f766e; font-weight:700;">LibreOffice rendering · after</div>
              <div style="display:flex; align-items:center; gap:10px;">
                    <span style="font-size:15px; color:#64748b;">zoom 145%</span>
                    <div class="pill green" style="font-size:16px; padding:6px 12px;">text_fit passed</div>
                  </div>
            </div>
            <div class="zoom-wrap" style="width:1120px; height:700px;">
              <img src="{after}" alt="After repair: zoom on the widened Description column">
              <div class="callout green" style="{after_callout}"></div>
            </div>
            <div class="shotlabel">{OPT_WIDTH["after"]:.1f} mm · {OPT_FONT["after"]:.1f} pt · fewer lines</div>
          </div>
        </div>
        {metric_cards()}
      </div>
      {claim_bar(5)}
    </div>
    """


def scene_7() -> str:
    revision = data_uri(ASSETS / "revision-v1-v2.png", crop=(215, 25, 1385, 895))
    paths = [
        "sections[0].body.length",
        "sections[0].body[11].runs.length",
        "sections[0].body[11].runs[0].text",
        "sections[0].body[11].space_after_pt",
        "sections[0].footer.length",
    ]
    return f"""
    <div class="stage">
      {top(7)}
      <div class="main">
        <div class="eyebrow">Revision + rollback</div>
        <h1>Versioned edits, with diff and rollback.</h1>
        <div style="display:flex; gap:46px; align-items:flex-start; margin-top:18px;">
          <div style="width:1080px; flex:0 0 1080px; position:relative;">
            <div class="shotframe">
              <img src="{revision}" alt="Compare versions V1 to V2 with restore buttons">
            </div>
            <div class="shotlabel">Compare versions · V1 → V2 · every change is an immutable IR diff</div>
            {cursor("39%", "21%")}
          </div>
          <div style="flex:1;">
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:14px;">
              <div style="background:#fff; border:1px solid #d6e0ec; border-radius:16px; padding:16px 20px;">
                <div style="font-size:42px; font-weight:700; line-height:1;">{REVISION_CHANGES}</div>
                <div style="font-size:18px; color:#64748b; margin-top:5px;">total changes</div>
              </div>
              <div style="background:#fff; border:1px solid #d6e0ec; border-radius:16px; padding:16px 20px;">
                <div style="font-size:42px; font-weight:700; line-height:1;">{REVISION_ADDED}</div>
                <div style="font-size:18px; color:#64748b; margin-top:5px;">added</div>
              </div>
              <div style="background:#fff; border:1px solid #d6e0ec; border-radius:16px; padding:16px 20px;">
                <div style="font-size:42px; font-weight:700; line-height:1;">{REVISION_REMOVED}</div>
                <div style="font-size:18px; color:#64748b; margin-top:5px;">removed</div>
              </div>
              <div style="background:#fff; border:1px solid #d6e0ec; border-radius:16px; padding:16px 20px;">
                <div style="font-size:42px; font-weight:700; line-height:1;">{REVISION_CHANGES}</div>
                <div style="font-size:18px; color:#64748b; margin-top:5px;">changed</div>
              </div>
            </div>
            <div style="margin-top:18px; background:#0b1f3a; color:#e2e8f0; border-radius:16px; padding:16px 20px;">
              <div style="font-size:16px; letter-spacing:1.4px; text-transform:uppercase; color:#7dd3fc; font-weight:700; margin-bottom:8px;">Changed IR paths</div>
              {"".join(f'<div class="mono" style="font-size:16px; color:#cbd5e1; line-height:1.55;">{esc(path)}</div>' for path in paths)}
            </div>
            <div style="margin-top:14px; display:flex; gap:12px; align-items:center;">
              <span class="pill green">Restore version</span>
              <span style="font-size:18px; color:#475569; line-height:1.4;">replaces IR, mapping, validation and preview panes</span>
            </div>
          </div>
        </div>
      </div>
      {claim_bar(6)}
    </div>
    """


def scene_8() -> str:
    return f"""
    <div class="stage dark">
      {top(8)}
      <div class="main" style="justify-content:center; align-items:flex-start; padding-bottom:20px;">
        <div class="eyebrow">Open source · Apache 2.0</div>
        <h1 style="font-size:96px; line-height:1.02; letter-spacing:-3px;">Open source.<br>Evidence first.</h1>
        <div style="margin-top:26px; font-size:48px; font-weight:600; color:#7dd3fc; letter-spacing:-0.6px;">
          github.com/SergeyGer/Docentric-Copilot
        </div>
        <div style="display:flex; gap:14px; margin-top:28px; flex-wrap:wrap;">
          <span class="pill slate">{CASE_COUNT} cases · {OPENAI_VALID + ANTHROPIC_VALID} valid live runs</span>
          <span class="pill slate">screenshots labelled by source</span>
          <span class="pill slate">LibreOffice renders labelled</span>
          <span class="pill amber" style="background:rgba(245,158,11,.14); color:#fcd34d;">Docentric AX: not_tested</span>
        </div>
        <div style="margin-top:34px; font-size:38px; font-weight:600; color:#f8fafc;">
          Docentric AX compatibility: not tested.
        </div>
        <div style="margin-top:10px; font-size:20px; color:#9fb0c8; max-width:1700px; line-height:1.5;">
          The video shows recorded artifacts and a recorded live benchmark. It does not claim Word fidelity
          or Docentric AX compatibility. Gemini: API quota exceeded; no valid run, so no Gemini quality
          result is claimed.
        </div>
      </div>
      {claim_bar(7, dark=True)}
    </div>
    """


def scene_html(index: int, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Demo v3 · {SCENE_TITLES[index]}</title>
<style>{CSS}</style></head>
<body>{body}</body></html>"""


THUMB_CSS = """
* { box-sizing: border-box; }
html, body { margin: 0; width: 1280px; height: 720px; overflow: hidden; }
body { font-family: 'DejaVu Sans', Arial, sans-serif; color: #f8fafc; }
.thumb {
  width: 1280px; height: 720px; padding: 58px 70px;
  display: flex; flex-direction: column; justify-content: space-between;
  background:
    radial-gradient(820px 520px at 86% 4%, #214d86 0%, rgba(33,77,134,0) 62%),
    linear-gradient(145deg, #0d2342 0%, #0b1f3a 58%, #07162a 100%);
  position: relative; overflow: hidden;
}
.thumb:before {
  content: ''; position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(255,255,255,.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,.04) 1px, transparent 1px);
  background-size: 64px 64px;
  mask-image: radial-gradient(800px 560px at 78% 18%, #000 0%, transparent 80%);
}
.brandline { display: flex; align-items: center; gap: 12px; position: relative; z-index: 2; }
.mark { width: 34px; height: 34px; border-radius: 9px; background: linear-gradient(145deg,#3b82f6,#1d4ed8);
        display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 20px; }
.brandname { font-size: 19px; font-weight: 700; letter-spacing: .2px; }
.eyebrow { font-size: 14px; letter-spacing: 2.2px; text-transform: uppercase; color: #7dd3fc; font-weight: 700; margin-bottom: 10px; position: relative; z-index: 2; }
h1 { position: relative; z-index: 2; margin: 0; font-size: 68px; line-height: 1.03; letter-spacing: -2px; font-weight: 700; }
.accent { color: #7dd3fc; }
.metric { position: relative; z-index: 2; display: flex; align-items: flex-end; gap: 18px; }
.big { font-size: 118px; line-height: .9; font-weight: 700; letter-spacing: -4px; color: #5eead4; }
.metric-label { font-size: 27px; line-height: 1.2; font-weight: 600; padding-bottom: 10px; }
.metric-label span { display: block; font-size: 18px; color: #9fb0c8; font-weight: 400; margin-top: 6px; letter-spacing: .2px; }
.footerline { position: relative; z-index: 2; display: flex; justify-content: space-between; font-size: 15px; color: #9fb0c8; letter-spacing: .4px; }
"""


def thumbnail_html() -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Docentric Copilot · demo v3</title>
<style>{THUMB_CSS}</style></head>
<body>
<div class="thumb">
  <div class="brandline"><div class="mark">D</div><div class="brandname">Docentric Copilot</div></div>
  <div>
    <div class="eyebrow">Live benchmark · {BENCH_DATE} · n={CASE_COUNT}</div>
    <h1>From a business brief<br>to a <span class="accent">reviewable DOCX</span>.</h1>
  </div>
  <div class="metric">
    <div class="big">{OPENAI_VALID}/{OPENAI_RUNS}</div>
    <div class="metric-label">valid templates<span>gpt-6-sol · n={OPENAI_RUNS} live cases · {BENCH_DATE}</span></div>
  </div>
  <div class="footerline"><span>Docentric AX compatibility: not tested</span><span>Gemini: quota exceeded · no valid run</span></div>
</div>
</body></html>"""


# --------------------------------------------------------------------------- #
# Narration
# --------------------------------------------------------------------------- #


async def _synth_once(text: str, rate: int, path: Path) -> tuple[bytes, list[Sentence]]:
    communicate = edge_tts.Communicate(
        text,
        VOICE,
        rate=f"{rate:+d}%",
        boundary="SentenceBoundary",
        connect_timeout=20,
        receive_timeout=120,
    )
    audio = bytearray()
    sentences: list[Sentence] = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
        elif chunk["type"] == "SentenceBoundary":
            sentences.append(
                Sentence(
                    text=str(chunk["text"]).strip(),
                    start=float(chunk["offset"]) / 1e7,
                    duration=float(chunk["duration"]) / 1e7,
                )
            )
    if not audio:
        raise RuntimeError("Edge TTS returned no audio")
    path.write_bytes(bytes(audio))
    return bytes(audio), sentences


def decode_mp3(path: Path, wav_path: Path) -> np.ndarray:
    subprocess.run(
        [
            str(FFMPEG),
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-ar",
            "48000",
            "-ac",
            "1",
            str(wav_path),
        ],
        check=True,
    )
    with wave.open(str(wav_path), "rb") as handle:
        assert handle.getframerate() == 48000
        frames = handle.readframes(handle.getnframes())
    return np.frombuffer(frames, dtype=np.int16).copy()


def synthesize_scene(index: int) -> NarratedScene:
    text = SCENE_NARRATION[index]
    slot = SCENE_SECONDS[index]
    limit = slot - 0.30
    target = slot - 0.75
    chosen: tuple[int, Path, np.ndarray, list[Sentence]] | None = None

    def attempt(rate: int) -> tuple[int, Path, np.ndarray, list[Sentence]]:
        digest = hashlib.sha1(f"{VOICE}|{rate}|{text}".encode()).hexdigest()[:10]
        mp3 = TTS / f"scene{index + 1:02d}-{digest}-{rate:+d}.mp3"
        meta = mp3.with_suffix(".json")
        wav = mp3.with_suffix(".wav")
        if mp3.exists() and meta.exists():
            try:
                sentences = [Sentence(**item) for item in json.loads(meta.read_text())]
                samples = decode_mp3(mp3, wav)
                if sentences:
                    return rate, mp3, samples, sentences
            except Exception:
                mp3.unlink(missing_ok=True)
                meta.unlink(missing_ok=True)
        last_error: Exception | None = None
        for try_number in range(3):
            try:
                _, sentences = asyncio.run(_synth_once(text, rate, mp3))
                meta.write_text(
                    json.dumps([sentence.__dict__ for sentence in sentences]), encoding="utf-8"
                )
                samples = decode_mp3(mp3, wav)
                return rate, mp3, samples, sentences
            except Exception as exc:  # pragma: no cover - network variance
                last_error = exc
                if try_number == 2:
                    raise
                asyncio.run(asyncio.sleep(1.5 * (try_number + 1)))
        raise RuntimeError(str(last_error))

    candidate = attempt(BASE_RATE)
    chosen = candidate
    duration = len(candidate[2]) / 48000
    if duration > limit:
        for rate in (BASE_RATE + 4, BASE_RATE + 8, BASE_RATE + 12, BASE_RATE + 16):
            candidate = attempt(rate)
            duration = len(candidate[2]) / 48000
            chosen = candidate
            if duration <= limit:
                break
    elif duration < target:
        for rate in (0, -4, -8):
            candidate = attempt(rate)
            candidate_duration = len(candidate[2]) / 48000
            if candidate_duration <= limit and abs(candidate_duration - target) < abs(
                len(chosen[2]) / 48000 - target
            ):
                chosen = candidate
            if candidate_duration >= target:
                break

    rate, mp3, samples, sentences = chosen
    duration = len(samples) / 48000
    if duration > limit:
        print(
            f"scene {index + 1}: narration {duration:.2f}s exceeds the {slot}s slot by "
            f"{duration - slot:.2f}s; the scene will be extended"
        )
    if not sentences:
        raise RuntimeError(f"Scene {index + 1} has no sentence boundaries")
    print(
        f"scene {index + 1}: {duration:5.2f}s / {slot}s at {rate:+d}%  "
        f"({len(text.split())} words, {len(sentences)} cues)"
    )
    return NarratedScene(index, mp3, duration, samples, sentences, rate)


def build_audio(scenes: list[NarratedScene]) -> np.ndarray:
    total_samples = TOTAL_SECONDS * 48000
    track = np.zeros(total_samples, dtype=np.int16)
    for scene, start in zip(scenes, SCENE_STARTS, strict=False):
        begin = start * 48000
        end = begin + len(scene.samples)
        if end > total_samples:
            raise RuntimeError("narration overruns the video")
        if end > (start + SCENE_SECONDS[scene.index]) * 48000:
            raise RuntimeError(f"scene {scene.index + 1} audio crosses into the next scene")
        track[begin:end] = scene.samples
        fade = min(240, len(scene.samples))
        if fade:
            ramp = np.linspace(1.0, 0.0, fade, dtype=np.float32)
            track[end - fade : end] = (track[end - fade : end].astype(np.float32) * ramp).astype(
                np.int16
            )
    wav_path = AUDIO / "narration.wav"
    with wave.open(str(wav_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(48000)
        handle.writeframes(track.tobytes())
    return track


# --------------------------------------------------------------------------- #
# Rendering and encoding
# --------------------------------------------------------------------------- #


def render_html(html_text: str, png: Path) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            args=["--force-color-profile=srgb", "--font-render-hinting=none"]
        )
        page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        page.set_content(html_text, wait_until="load")
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(120)
        page.screenshot(path=str(png), full_page=False)
        browser.close()


def render_thumbnail() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            args=["--force-color-profile=srgb", "--font-render-hinting=none"]
        )
        page = browser.new_page(viewport={"width": 1280, "height": 720}, device_scale_factor=1)
        page.set_content(thumbnail_html(), wait_until="load")
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(120)
        page.screenshot(path=str(THUMB), full_page=False)
        browser.close()


def scene_slides(panel_paths: list[Path]) -> list[tuple[list[str], list[float], int]]:
    """Return (html variants, duration weights, transition frames) per scene."""
    return [
        ([scene_1()], [1.0], 0),
        ([scene_2()], [1.0], 0),
        ([scene_3(path) for path in panel_paths], [1.0] * len(panel_paths), 0),
        ([scene_4()], [1.0], 0),
        ([scene_5("preview"), scene_5("zoom"), scene_5("totals")], [5.0, 16.0, 5.0], 3),
        ([scene_6("before"), scene_6("compare"), scene_6("after")], [7.0, 18.0, 7.0], 3),
        ([scene_7()], [1.0], 0),
        ([scene_8()], [1.0], 0),
    ]


def allocate_frames(total: int, weights: list[float], transition_frames: int) -> list[int]:
    count = len(weights)
    solo = total - transition_frames * (count - 1)
    raw = [solo * weight / sum(weights) for weight in weights]
    frames = [round(value) for value in raw]
    frames[-1] += solo - sum(frames)
    return frames


def render_slides(
    specs: list[tuple[list[str], list[float], int]],
) -> list[tuple[list[Path], list[int], int]]:
    rendered: list[tuple[list[Path], list[int], int]] = []
    for scene_index, (html_variants, weights, transition_frames) in enumerate(specs):
        total = SCENE_SECONDS[scene_index] * FPS
        frames = allocate_frames(total, weights, transition_frames)
        paths: list[Path] = []
        for shot_index, html_text in enumerate(html_variants):
            png = SLIDES / f"scene{scene_index + 1:02d}_shot{shot_index + 1:02d}.png"
            render_html(scene_html(scene_index, html_text), png)
            paths.append(png)
            print(f"rendered {png.name} ({png.stat().st_size // 1024} KB)")
        rendered.append((paths, frames, transition_frames))
    return rendered


def encode_still(png: Path, frames: int, target: Path, fade: str | None = None) -> None:
    filters = [f"scale={OUT_W}:{OUT_H}:flags=lanczos"]
    if fade == "in":
        filters.append("fade=t=in:st=0:d=0.7")
    elif fade == "out":
        filters.append(f"fade=t=out:st={max(0.0, frames / FPS - 1.0):.3f}:d=1.0")
    filters.append("format=yuv420p")
    subprocess.run(
        [
            str(FFMPEG),
            "-y",
            "-loglevel",
            "error",
            "-loop",
            "1",
            "-framerate",
            str(FPS),
            "-i",
            str(png),
            "-frames:v",
            str(frames),
            "-vf",
            ",".join(filters),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "19",
            "-profile:v",
            "high",
            "-level",
            "4.1",
            "-r",
            str(FPS),
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(target),
        ],
        check=True,
    )


def encode_transition(frames: list[Path], target: Path) -> None:
    first = frames[0]
    pattern = first.with_name(first.name.replace("_001", "_%03d"))
    filters = [f"scale={OUT_W}:{OUT_H}:flags=lanczos", "format=yuv420p"]
    subprocess.run(
        [
            str(FFMPEG),
            "-y",
            "-loglevel",
            "error",
            "-framerate",
            str(FPS),
            "-i",
            str(pattern),
            "-frames:v",
            str(len(frames)),
            "-vf",
            ",".join(filters),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "19",
            "-profile:v",
            "high",
            "-level",
            "4.1",
            "-r",
            str(FPS),
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(target),
        ],
        check=True,
    )


def make_transition(
    scene_index: int,
    shot_index: int,
    first: Path,
    second: Path,
    count: int,
) -> list[Path]:
    base_a = Image.open(first).convert("RGB")
    base_b = Image.open(second).convert("RGB")
    paths: list[Path] = []
    for step in range(1, count + 1):
        alpha = step / (count + 1)
        blended = Image.blend(base_a, base_b, alpha)
        path = WORK / "video" / f"scene{scene_index + 1:02d}_trans{shot_index + 1:02d}_{step:03d}.png"
        blended.save(path)
        paths.append(path)
    return paths


def encode_scenes(
    rendered: list[tuple[list[Path], list[int], int]],
) -> list[Path]:
    scene_files: list[Path] = []
    for scene_index, (paths, frames, transition_frames) in enumerate(rendered):
        parts: list[Path] = []
        for shot_index, (png, frame_count) in enumerate(zip(paths, frames, strict=False)):
            fade = None
            if scene_index == 0 and shot_index == 0:
                fade = "in"
            if scene_index == 7 and shot_index == len(paths) - 1:
                fade = "out"
            part = VIDEO / f"scene{scene_index + 1:02d}_part{shot_index + 1:02d}.mp4"
            encode_still(png, frame_count, part, fade=fade)
            parts.append(part)
            if shot_index + 1 < len(paths) and transition_frames:
                blends = make_transition(
                    scene_index, shot_index, png, paths[shot_index + 1], transition_frames
                )
                trans_part = VIDEO / f"scene{scene_index + 1:02d}_trans{shot_index + 1:02d}.mp4"
                encode_transition(blends, trans_part)
                parts.append(trans_part)
        concat_file = VIDEO / f"scene{scene_index + 1:02d}_concat.txt"
        concat_file.write_text(
            "".join(f"file '{part.as_posix()}'\n" for part in parts), encoding="utf-8"
        )
        scene_file = VIDEO / f"scene{scene_index + 1:02d}.mp4"
        subprocess.run(
            [
                str(FFMPEG),
                "-y",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-c",
                "copy",
                str(scene_file),
            ],
            check=True,
        )
        scene_files.append(scene_file)
    return scene_files


def encode_video(scene_files: list[Path]) -> None:
    concat_file = VIDEO / "concat.txt"
    concat_file.write_text(
        "".join(f"file '{part.as_posix()}'\n" for part in scene_files), encoding="utf-8"
    )
    silent = VIDEO / "video-only.mp4"
    subprocess.run(
        [
            str(FFMPEG),
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            str(silent),
        ],
        check=True,
    )
    wav = AUDIO / "narration.wav"
    subprocess.run(
        [
            str(FFMPEG),
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(silent),
            "-i",
            str(wav),
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-shortest",
            "-movflags",
            "+faststart",
            str(OUT),
        ],
        check=True,
    )


# --------------------------------------------------------------------------- #
# SRD / text deliverables
# --------------------------------------------------------------------------- #


def srt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    millis = round(seconds * 1000)
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def caption_text(text: str) -> str:
    clean = " ".join(text.split())
    lines = textwrap.wrap(clean, width=44)
    if len(lines) > 2:
        lines = textwrap.wrap(clean, width=58)[:3]
    return "\n".join(lines[:3])


def build_srt(scenes: list[NarratedScene]) -> str:
    cues: list[tuple[float, float, str]] = []
    for scene, offset in zip(scenes, SCENE_STARTS, strict=False):
        for position, sentence in enumerate(scene.sentences):
            start = offset + sentence.start
            end = offset + sentence.start + sentence.duration + 0.18
            if position + 1 < len(scene.sentences):
                end = min(end, offset + scene.sentences[position + 1].start - 0.02)
            end = min(
                end, offset + scene.duration + 0.10, offset + SCENE_SECONDS[scene.index] - 0.02
            )
            if end - start < 0.35:
                start = max(offset, end - 0.35)
            cues.append((start, end, caption_text(sentence.text)))

    blocks = []
    for number, (start, end, text) in enumerate(cues, start=1):
        blocks.append(f"{number}\n{srt_time(start)} --> {srt_time(end)}\n{text}\n")
    return "\n".join(blocks)


def mmss(seconds: int) -> str:
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def write_narration() -> None:
    lines = [
        "# Demo v3 narration",
        "",
        f"Duration **{mmss(TOTAL_SECONDS)}** · 1920×1080 · 30 fps · voice `{VOICE}` · "
        f"measured data from `benchmarks/live_report.json` ({BENCH_DATE}).",
        "",
        "The script is English only and deliberately general: no cents or dollars, no latency "
        "seconds, no token counts and no per-provider scores are read aloud. All figures appear on "
        "screen and are mapped to their sources in `scene-manifest-v3.json`.",
        "",
        "The Gemini benchmark row is a status category on screen (API quota exceeded; no valid run). "
        "The voiceover does not mention the failure or claim any Gemini quality result.",
        "",
    ]
    for index, (title, start, end) in enumerate(
        zip(SCENE_TITLES, SCENE_STARTS, SCENE_ENDS, strict=False), start=1
    ):
        lines.append(f"## {index}. {title} — {mmss(start)}–{mmss(end)}")
        lines.append("")
        lines.append(SCENE_NARRATION[index - 1])
        lines.append("")
    (MEDIA / "narration-v3.md").write_text("\n".join(lines), encoding="utf-8")


def write_manifest() -> None:
    entries = []
    for index, (title, start, end) in enumerate(
        zip(SCENE_TITLES, SCENE_STARTS, SCENE_ENDS, strict=False)
    ):
        entries.append(
            {
                "scene": f"{index + 1:02d} {title}",
                "start": mmss(start),
                "end": mmss(end),
                "asset": SCENE_ASSETS[index],
                "claim": SCENE_CLAIMS[index],
                "evidence": SCENE_EVIDENCE[index],
            }
        )
    (MEDIA / "scene-manifest-v3.json").write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def write_release_notes() -> None:
    sizes = {
        "video_mb": OUT.stat().st_size / (1024 * 1024),
        "srt_kb": SRT.stat().st_size / 1024,
        "thumb_kb": THUMB.stat().st_size / 1024,
    }
    text = f"""# Demo video v3 — release notes

This release note accompanies `docs/media/demo-v3.mp4` ({sizes["video_mb"]:.1f} MiB),
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
  Total runtime is {mmss(TOTAL_SECONDS)}.
- **Zoomed document views.** The finished-document and before/after repair scenes use 130–155% crops
  centred on the items table, totals and Description column, with three-frame crossfades between
  zoom levels. They are not shown as full-page evidence.
- **Benchmark truthfulness.** The Gemini row is now the explicit category
  "Gemini — API quota exceeded; no valid run". No Gemini quality, latency or cost result is claimed.
  The OpenAI and Anthropic rows keep the measured `benchmarks/live_report.json` values.
- **Labels kept.** The closing line is still "Docentric AX compatibility: not tested", and every
  LibreOffice image is still labelled "LibreOffice rendering".

## What is live, and what is replay

**Verified live on {BENCH_DATE}.** The multi-LLM table uses `benchmarks/live_report.json`: {CASE_COUNT}
cases, {PROVIDER_COUNT} providers and one live run per case/provider ({CASE_COUNT * PROVIDER_COUNT}
attempts total), with an estimated spend of ${SPEND:.6f} and {UNKNOWN_COST_RUNS} unknown-cost runs.
Models: `openai:gpt-6-sol`, `anthropic:claude-sonnet-5-5`, `gemini:gemini-3.1-flash-lite`. The routing
scene's executed model (`gpt-6-sol`, run `{ROUTING_RUN_ID}`) comes from the same report and its saved
trace.

**Deterministic or recorded (replay).** The prompt panel, schema explorer, revision diff and DOCX
preview are recorded workspace screenshots. The brief typing is a re-render of the recorded prompt
panel, not a screen recording. The DOCX artifact bytes ({DOCX_BYTES:,}) come from
`docs/media/demo-session.json`; the two-page count is recorded in
`docs/assets/preview-pages.png`. The LibreOffice before/after pages are the recorded 1241×1754
renders from LibreOffice Writer 25.2 + `pdftoppm`; this video does not re-render them. The optimize response
used for scene 6 was regenerated from the bundled `quotation-long-items` demo with the deterministic
mock planner and is saved as `docs/media/optimize-response.json`; no provider was called for it.

## Gemini quota caveat

`benchmarks/live_report.json` records {GEMINI_RUNS} Gemini attempts, {GEMINI_VALID} valid runs, null
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
duration of {mmss(TOTAL_SECONDS)}. File sizes: video {sizes["video_mb"]:.1f} MiB, SRT
{sizes["srt_kb"]:.1f} KiB, thumbnail {sizes["thumb_kb"]:.1f} KiB.

Reproduce with:

```bash
PLAYWRIGHT_BROWSERS_PATH=.tools/pw-browsers .venv/bin/python scripts/build_demo_video_v3.py
```
"""
    (ROOT / "RELEASE_NOTES_video.md").write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def main() -> int:
    print(f"benchmark: {BENCH_DATE}, {CASE_COUNT} cases, {PROVIDER_COUNT} providers, ${SPEND:.6f}")
    print(f"brief: {BRIEF_CHARS} chars")
    print(f"output: {OUT}")
    panel_paths = build_panel_frames()
    print(f"panels: {len(panel_paths)} frames")
    specs = scene_slides(panel_paths)
    rendered = render_slides(specs)
    render_thumbnail()
    scenes = [synthesize_scene(index) for index in range(8)]
    build_audio(scenes)
    srt_text = build_srt(scenes)
    SRT.write_text(srt_text + "\n", encoding="utf-8")
    print(f"wrote {SRT} ({len(srt_text.splitlines())} lines)")
    write_narration()
    write_manifest()
    scene_files = encode_scenes(rendered)
    encode_video(scene_files)
    write_release_notes()
    print(f"wrote {OUT} ({OUT.stat().st_size / (1024 * 1024):.1f} MiB)")
    print(f"wrote {THUMB} ({THUMB.stat().st_size / 1024:.1f} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
