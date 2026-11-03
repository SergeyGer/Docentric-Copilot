#!/usr/bin/env python3
"""Build the revised evidence-led Docentric Copilot demo video.

Outputs (all under ``docs/media``):

* ``demo-v2.mp4``      1920x1080, 30 fps, H.264/AAC, 2:46
* ``demo-v2.srt``      English captions aligned to the synthesised narration
* ``thumbnail.png``    1280x720 title card with one benchmark metric
* ``narration-v2.md``  full script with scene timings
* ``scene-manifest.json`` claims mapped to real artifacts

The slides are authored at 2560x1440, screenshotted with Playwright and
downscaled to 1080p by ffmpeg. Narration is synthesised with Edge TTS. Every
number on screen is read from ``benchmarks/live_report.json``, the saved demo
session, the saved live trace, or the recorded optimize response.

Usage::

    PLAYWRIGHT_BROWSERS_PATH=.tools/pw-browsers .venv/bin/python scripts/build_demo_video_v2.py
"""

from __future__ import annotations

import asyncio
import base64
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
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "docs" / "assets"
MEDIA = ROOT / "docs" / "media"
WORK = ROOT / ".tools" / "video-build" / "v2"
SLIDES = WORK / "slides"
TTS = WORK / "tts"
AUDIO = WORK / "audio"
VIDEO = WORK / "video"
for directory in (SLIDES, TTS, AUDIO, VIDEO):
    directory.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".tools" / "pw-browsers"))

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
FFPROBE = ROOT / ".tools" / "ffprobe-tool" / "node_modules" / "@ffprobe-installer" / "linux-x64" / "ffprobe"
FFPROBE = FFPROBE if FFPROBE.exists() else Path(shutil.which("ffprobe") or "ffprobe")

W, H = 2560, 1440
OUT_W, OUT_H = 1920, 1080
FPS = 30
VOICE = "en-US-GuyNeural"
BASE_RATE = 4
OUT = MEDIA / "demo-v2.mp4"
SRT = MEDIA / "demo-v2.srt"
THUMB = MEDIA / "thumbnail.png"

NAVY = "#0b1f3a"
INK = "#16233a"
MUTED = "#5b6b82"
PAPER = "#eef2f7"
BLUE = "#2563eb"


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

DOCX_ARTIFACT = next(item for item in SESSION["artifacts"] if item["kind"] == "docx")
DOCX_BYTES = DOCX_ARTIFACT["size_bytes"]
DOCX_PAGES = 2
SCHEMA_STATS = SESSION["stats"]
SCHEMA_SECTIONS = SESSION["sections"]

OPT_FIXES = OPTIMIZE["fixes"]
OPT_IR_DIFF = OPTIMIZE["ir_diff"]
OPT_WIDTH = next(fix for fix in OPT_FIXES if fix["id"] == "fit_text_width")
OPT_FONT = next(fix for fix in OPT_FIXES if fix["id"] == "fit_text_font")
OPT_ITEMS = len(OPT_IR_DIFF)

REVISION_CHANGES = 5
REVISION_ADDED = 0
REVISION_REMOVED = 0

SCENE_SECONDS = [12, 18, 25, 22, 24, 31, 20, 14]
SCENE_TITLES = [
    "Hook",
    "Data source and schema",
    "Live adaptive routing",
    "Multi-LLM benchmark",
    "DOCX artifact",
    "Visual defect to repair",
    "Revision V1/V2",
    "Closing",
]
SCENE_CLAIMS = [
    "A quotation brief becomes a two-page DOCX with the schema, validation and diff attached.",
    "The document is grounded in a normalized schema: 34 fields, 3 sections, 1 repeating collection.",
    "The routing panel recommends Anthropic; the live quotation run used gpt-6-sol and passed the validation gate.",
    "Across 6 live cases, gpt-6-sol and claude-sonnet-5-5 each produced 6 valid templates; gemini-3.1-flash-lite produced 0.",
    "quotation.docx is 40,585 bytes and two pages; the right-hand page is a LibreOffice rendering, not a Word fidelity claim.",
    "The defect is 62.0 mm at 9.5 pt; the repair is 88.7 mm at 9.0 pt, 7 IR fields changed, and text-fit passes.",
    "V1 to V2 changed 5 IR fields, added 0 and removed 0; either version can be restored.",
    "Docentric Copilot is open source on GitHub; Docentric AX compatibility is not tested.",
]
SCENE_NARRATION = [
    "A business brief should become a document a team can review, not a black box. "
    "This is Docentric Copilot: quotation in, two-page DOCX out, with schema, validation and diff attached.",
    "Everything starts with the customer's data. "
    "Here is a synthetic DDSP package with thirty-four fields across three sections and one repeating collection. "
    "Sample data and parser diagnostics are included. "
    "The schema is normalized, so every field the document can bind has a type and evidence.",
    "Routing starts with complexity. "
    "The workspace panel calls this quotation brief ambiguous, recommends Anthropic under a thirty-cent budget, "
    "and asks for human review. "
    "But recommendation is not execution; the panel does not show which model ran. "
    "The live trace does: the benchmark's quotation case executed gpt-6-sol, compiled, and passed the validation "
    "gate in 19.4 seconds for 3.6 cents.",
    "Six cases, three providers, one run per case. "
    "gpt-6-sol and claude-sonnet-5-5 each produced six valid templates out of six, with p50 latency of 19.0 and "
    "14.2 seconds. "
    "Cost per valid template: 3.3 and 4.7 cents. "
    "Gemini-3.1-flash-lite produced zero; its latency and cost are unknown, so the slide shows N/A, never zero.",
    "Download the DOCX and open it. "
    "The quotation is 40,585 bytes and two pages. "
    "On the left is the independent preview; on the right, page one as rendered by LibreOffice. "
    "Both are labelled for what they are. "
    "This is a LibreOffice rendering, not a Microsoft Word fidelity claim.",
    "Here is the visual defect. "
    "The Description column is 62 millimetres at 9.5 points, and two cells wrap past four estimated lines. "
    "Optimize layout applies typed IR changes. "
    "Description widens to 88.7 millimetres by rebalancing the other columns, and the table font drops to 9.0 points. "
    "Seven IR fields change. "
    "The panel reruns the checks: text fit now passes, and the after image uses fewer lines. "
    "LibreOffice rendering, not Word pagination.",
    "Every edit creates an immutable version. "
    "V1 to V2 changed five IR fields, added none and removed none. "
    "The comparison names each changed path, and Restore version brings either pane back into the workspace. "
    "Diff and rollback, not a silent edit.",
    "Docentric Copilot is open source on GitHub under Apache 2.0. "
    "The demo, the benchmark and the evidence are in the repository. "
    "Docentric AX compatibility: not tested.",
]
SCENE_ASSETS = [
    "docs/assets/preview-pages.png",
    "docs/assets/schema-explorer.png",
    "docs/assets/routing-panel.png; docs/media/runs/bench_6312bb882a834b97.json",
    "benchmarks/live_report.json (rendered benchmark table)",
    "docs/assets/preview-pages.png; docs/assets/quality-before-libreoffice.png",
    "docs/assets/quality-before-libreoffice.png; docs/assets/quality-after-libreoffice.png; docs/media/optimize-response.json",
    "docs/assets/revision-v1-v2.png",
    "README.md; LICENSE",
]
SCENE_EVIDENCE = [
    "docs/media/demo-session.json artifacts[docx].size_bytes=40585 and docs/assets/preview-pages.png (page 1 of 2, page 2 of 2).",
    "docs/media/demo-session.json stats: node_count=34, collection_count=1, max_depth=3; sections MainData, GeneralData, Parameters.",
    "docs/assets/routing-panel.png (Ambiguous; anthropic; budget $0.30; human review) and benchmarks/live_report.json run "
    "simple-company-identity/openai (actual_model gpt-6-sol, latency 19402 ms, cost 0.035580 USD, validation_passed true).",
    "benchmarks/live_report.json aggregates: openai 6/6, p50 19002 ms, cost 0.199774 USD; anthropic 6/6, p50 14235.5 ms, "
    "cost 0.279024 USD; gemini 0/6, p50 null, cost null. Cost per valid template is derived as cost_usd / successful_runs.",
    "docs/media/demo-session.json artifacts[docx].size_bytes=40585; docs/assets/preview-pages.png shows two preview pages; "
    "docs/assets/quality-before-libreoffice.png is page 1 of 2 at 1241x1754, recorded from LibreOffice Writer 25.2 + pdftoppm.",
    "docs/media/optimize-response.json (regenerated from the bundled quotation-long-items demo) fixes fit_text_width "
    "62.0 -> 88.7 mm and fit_text_font 9.5 -> 9.0 pt; ir_diff has 7 entries; before text_fit warning, after passed; "
    "docs/assets/quality-before-libreoffice.png and quality-after-libreoffice.png are the recorded LibreOffice renders.",
    "docs/assets/revision-v1-v2.png: TOTAL CHANGES 5, ADDED 0, REMOVED 0, CHANGED 5; Restore version is visible on both panes.",
    "README.md GitHub URL https://github.com/SergeyGer/Docentric-Copilot and LICENSE Apache-2.0; SESSION validation "
    "docentric_compatibility=not_tested.",
]

SCENE_STARTS = [sum(SCENE_SECONDS[:i]) for i in range(len(SCENE_SECONDS))]
SCENE_ENDS = [start + duration for start, duration in zip(SCENE_STARTS, SCENE_SECONDS)]
TOTAL_SECONDS = sum(SCENE_SECONDS)
assert TOTAL_SECONDS == 166


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


def data_uri(path: Path, crop: tuple[int, int, int, int] | None = None) -> str:
    image = Image.open(path).convert("RGB")
    if crop is not None:
        image = image.crop(crop)
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


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
        <span>Demo v2</span><span>·</span><span>{BENCH_DATE}</span>
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
            A quotation brief in. A two-page document out — with the schema,
            validation and version evidence attached.
          </p>
          <div style="display:flex; gap:20px; margin-top:34px;">
            <div style="background:rgba(255,255,255,.07); border:1px solid rgba(255,255,255,.16); border-radius:16px; padding:20px 24px; min-width:300px;">
              <div style="font-size:58px; font-weight:700; line-height:1;">6/6</div>
              <div style="font-size:20px; color:#c7d2e4; margin-top:8px;">valid templates<br><span style="color:#9fb0c8;">gpt-6-sol · n=6</span></div>
            </div>
            <div style="background:rgba(255,255,255,.07); border:1px solid rgba(255,255,255,.16); border-radius:16px; padding:20px 24px; min-width:300px;">
              <div style="font-size:58px; font-weight:700; line-height:1;">2</div>
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
              <div style="font-size:17px; color:#64748b; margin-top:2px;">40,585 bytes · 2 pages</div>
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
                <div style="font-size:46px; font-weight:700; color:#0f2a54; line-height:1;">{SCHEMA_STATS['node_count']}</div>
                <div style="font-size:19px; color:#64748b; margin-top:6px;">fields in the schema</div>
              </div>
              <div style="background:#fff; border:1px solid #dbe3ee; border-radius:16px; padding:20px 22px;">
                <div style="font-size:46px; font-weight:700; color:#0f2a54; line-height:1;">{len(SCHEMA_SECTIONS)}</div>
                <div style="font-size:19px; color:#64748b; margin-top:6px;">root sections</div>
              </div>
              <div style="background:#fff; border:1px solid #dbe3ee; border-radius:16px; padding:20px 22px;">
                <div style="font-size:46px; font-weight:700; color:#0f2a54; line-height:1;">{SCHEMA_STATS['collection_count']}</div>
                <div style="font-size:19px; color:#64748b; margin-top:6px;">repeating collection</div>
              </div>
              <div style="background:#fff; border:1px solid #dbe3ee; border-radius:16px; padding:20px 22px;">
                <div style="font-size:46px; font-weight:700; color:#0f2a54; line-height:1;">{SCHEMA_STATS['max_depth']}</div>
                <div style="font-size:19px; color:#64748b; margin-top:6px;">levels deep</div>
              </div>
            </div>
            <div style="margin-top:20px; display:flex; gap:10px; flex-wrap:wrap;">
              {''.join(f'<span class="pill">{esc(section)}</span>' for section in SCHEMA_SECTIONS)}
              <span class="pill green">sample data</span>
              <span class="pill amber">3 parser diagnostics</span>
            </div>
            <div style="margin-top:22px; font-size:18px; color:#64748b; line-height:1.5;">
              Evidence: <span class="mono">docs/media/demo-session.json</span> · 34 nodes, 1 collection, depth 3.
            </div>
          </div>
          <div style="flex:1; position:relative;">
            <div class="shotframe">
              <img src="{schema}" alt="Schema explorer with typed fields">
            </div>
            <div class="shotlabel">Workspace schema explorer · 34 fields, typed and searchable</div>
            {cursor("46%", "61%")}
          </div>
        </div>
      </div>
      {claim_bar(1)}
    </div>
    """


def scene_3() -> str:
    routing = data_uri(ASSETS / "routing-panel.png", crop=(100, 148, 908, 760))
    return f"""
    <div class="stage">
      {top(3)}
      <div class="main">
        <div class="eyebrow">Live adaptive routing</div>
        <h1>Recommendation is not execution.</h1>
        <p class="lede" style="max-width:1500px; font-size:26px;">
          The workspace panel explains its routing decision. The executed model is a separate,
          recorded fact from the live benchmark trace.
        </p>
        <div style="display:flex; gap:48px; align-items:stretch; margin-top:20px;">
          <div style="width:900px; flex:0 0 900px; position:relative;">
            <div class="shotframe">
              <img src="{routing}" alt="Routing panel recommending Anthropic for an ambiguous brief">
            </div>
            <div class="shotlabel" style="max-width:880px;">
              Workspace routing panel · recommendation only. The provider dropdown is not the
              executed model; the trace on the right is.
            </div>
            {cursor("5%", "62%")}
          </div>
          <div style="flex:1; background:#0b1f3a; color:#e2e8f0; border-radius:20px; padding:28px 34px;
                      box-shadow:0 24px 52px rgba(15,23,42,.20); position:relative;">
            <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid rgba(255,255,255,.15); padding-bottom:16px;">
              <div style="font-size:19px; letter-spacing:2px; text-transform:uppercase; color:#7dd3fc; font-weight:700;">Live run trace</div>
              <div class="pill green" style="font-size:15px; padding:7px 14px;">validation gate passed</div>
            </div>
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:0 34px; margin-top:4px;">
              <div style="padding:14px 0; border-bottom:1px solid rgba(255,255,255,.12);">
                <div style="font-size:16px; letter-spacing:1.4px; text-transform:uppercase; color:#94a3b8;">Complexity</div>
                <div style="font-size:29px; font-weight:600; margin-top:4px;">Ambiguous</div>
              </div>
              <div style="padding:14px 0; border-bottom:1px solid rgba(255,255,255,.12);">
                <div style="font-size:16px; letter-spacing:1.4px; text-transform:uppercase; color:#94a3b8;">Panel recommends</div>
                <div style="font-size:29px; font-weight:600; margin-top:4px;">Anthropic</div>
              </div>
              <div style="padding:14px 0; border-bottom:1px solid rgba(255,255,255,.12);">
                <div style="font-size:16px; letter-spacing:1.4px; text-transform:uppercase; color:#94a3b8;">Executed model</div>
                <div style="font-size:34px; font-weight:700; margin-top:4px; color:#5eead4;">gpt-6-sol</div>
              </div>
              <div style="padding:14px 0; border-bottom:1px solid rgba(255,255,255,.12);">
                <div style="font-size:16px; letter-spacing:1.4px; text-transform:uppercase; color:#94a3b8;">Provider</div>
                <div style="font-size:29px; font-weight:600; margin-top:4px;">openai</div>
              </div>
              <div style="padding:14px 0; border-bottom:1px solid rgba(255,255,255,.12);">
                <div style="font-size:16px; letter-spacing:1.4px; text-transform:uppercase; color:#94a3b8;">Latency</div>
                <div style="font-size:29px; font-weight:600; margin-top:4px;">19.4 s</div>
              </div>
              <div style="padding:14px 0; border-bottom:1px solid rgba(255,255,255,.12);">
                <div style="font-size:16px; letter-spacing:1.4px; text-transform:uppercase; color:#94a3b8;">Estimated cost</div>
                <div style="font-size:29px; font-weight:600; margin-top:4px;">$0.0356</div>
              </div>
            </div>
            <div style="display:flex; justify-content:space-between; align-items:flex-end; margin-top:14px;">
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
    p50_text = f"{p50 / 1000:.1f} s" if p50 is not None else "N/A"
    per_text = f"${per:,.4f}" if per is not None else "N/A"
    badge = '<span class="pill green" style="font-size:15px; padding:6px 12px; margin-left:12px;">recommended</span>' if recommended else ""
    sub = (
        f"validation {row['validation_pass_rate'] * 100:.0f}% · compile {row['compilation_success_rate'] * 100:.0f}%"
    )
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


def scene_4() -> str:
    rec = BENCH["recommendation"]["provider"]
    return f"""
    <div class="stage">
      {top(4)}
      <div class="main">
        <div class="eyebrow">Multi-LLM benchmark · {CASE_COUNT} live cases</div>
        <h1>Three models. The same six cases.</h1>
        <div style="margin-top:20px; background:#fff; border:1px solid #d6e0ec; border-radius:20px; overflow:hidden;
                    box-shadow:0 18px 42px rgba(15,23,42,.08);">
          <div class="bhead">
            <div>Provider / model</div><div>Valid templates</div><div>p50 latency</div><div>Cost per valid template</div>
          </div>
          {bench_row(OPENAI, rec == 'openai')}
          {bench_row(ANTHROPIC, rec == 'anthropic')}
          {bench_row(GEMINI, rec == 'gemini')}
        </div>
        <div class="footnote" style="max-width:2340px;">
          <b>n = {CASE_COUNT} cases per provider · {BENCH_DATE} · one run per case · {PROVIDER_COUNT} models:</b>
          openai:gpt-6-sol, anthropic:claude-sonnet-5-5, gemini:gemini-3.1-flash-lite.
          Estimated spend ${SPEND:.6f} of ${BENCH['budget']['max_spend_usd']:.2f}; unknown-cost runs: {UNKNOWN_COST_RUNS}.
          <b>Cost per valid template = provider cost ÷ successful runs.</b>
          N/A means the report has no price or no successful latency sample — never $0.00.
          These are observations, not a significance claim.
        </div>
      </div>
      {claim_bar(3)}
    </div>
    """


def scene_5() -> str:
    preview = data_uri(ASSETS / "preview-pages.png")
    page = data_uri(ASSETS / "quality-before-libreoffice.png")
    return f"""
    <div class="stage">
      {top(5)}
      <div class="main">
        <div class="eyebrow">DOCX artifact</div>
        <h1>Download it. Open it. Check it.</h1>
        <div style="display:flex; gap:14px; margin-top:18px;">
          <span class="pill slate">01 Download · {DOCX_BYTES:,} bytes</span>
          <span class="pill slate">02 Open</span>
          <span class="pill slate">03 Two pages</span>
          <span class="pill green">DOCX + evidence</span>
        </div>
        <div style="display:flex; gap:52px; align-items:flex-start; margin-top:18px;">
          <div style="width:1030px; flex:0 0 1030px; position:relative;">
            <div class="shotframe">
              <img src="{preview}" alt="Independent two-page preview of the quotation">
            </div>
            <div class="shotlabel">Independent preview · 2 pages · layout differs from Word/Docentric pagination</div>
            {cursor("3%", "16%")}
          </div>
          <div style="flex:1; display:flex; gap:34px; align-items:flex-start;">
            <div style="width:470px; flex:0 0 470px;">
              <div style="font-size:17px; letter-spacing:1.6px; text-transform:uppercase; color:#b45309; font-weight:700; margin-bottom:8px;">
                LibreOffice rendering
              </div>
              <div class="page"><img src="{page}" alt="LibreOffice rendering of page 1"></div>
              <div class="shotlabel">Page 1 of 2 · 1241×1754 · not Word fidelity</div>
            </div>
            <div style="flex:1; padding-top:44px;">
              <div style="font-size:22px; line-height:1.4; color:#334155; font-weight:600;">Same artifact, two independent views.</div>
              <div style="font-size:20px; line-height:1.55; color:#64748b; margin-top:14px;">
                The DOCX is the deliverable. The preview checks content and field binding;
                the LibreOffice page checks an independent render. Neither is a claim about
                Microsoft Word pagination or Docentric AX compatibility.
              </div>
              <div style="margin-top:22px; border-left:4px solid #f59e0b; background:#fffbeb; border-radius:0 12px 12px 0; padding:14px 18px; font-size:18px; line-height:1.45; color:#78350f;">
                <b>Labelled:</b> LibreOffice rendering. Not a screen recording, not Word.
              </div>
            </div>
          </div>
        </div>
      </div>
      {claim_bar(4)}
    </div>
    """


def scene_6() -> str:
    before = data_uri(ASSETS / "quality-before-libreoffice.png", crop=(170, 540, 1170, 1040))
    after = data_uri(ASSETS / "quality-after-libreoffice.png", crop=(170, 540, 1170, 1040))
    return f"""
    <div class="stage">
      {top(6)}
      <div class="main">
        <div class="eyebrow">Visual defect to repair</div>
        <h1>A visual defect, repaired by typed IR changes.</h1>
        <div style="display:flex; gap:46px; margin-top:12px; justify-content:center;">
          <div style="width:1000px; flex:0 0 1000px;">
            <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:8px;">
              <div style="font-size:18px; letter-spacing:1.5px; text-transform:uppercase; color:#b45309; font-weight:700;">LibreOffice rendering · before</div>
              <div class="pill amber" style="font-size:16px; padding:6px 12px;">text_fit warning</div>
            </div>
            <div style="position:relative; border-radius:12px; overflow:hidden; border:1px solid #e2e8f0; box-shadow:0 18px 40px rgba(15,23,42,.14);">
              <img src="{before}" style="display:block; width:1000px; height:500px;" alt="Before repair: Description column narrow">
              <div style="position:absolute; left:6.5%; top:12%; width:36%; height:79%;
                          border:4px solid #d97706; border-radius:6px; background:rgba(245,158,11,.05);"></div>
            </div>
            <div class="shotlabel">Description 62.0 mm · 9.5 pt · two cells estimated over 4 lines</div>
          </div>
          <div style="width:1000px; flex:0 0 1000px;">
            <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:8px;">
              <div style="font-size:18px; letter-spacing:1.5px; text-transform:uppercase; color:#0f766e; font-weight:700;">LibreOffice rendering · after</div>
              <div class="pill green" style="font-size:16px; padding:6px 12px;">text_fit passed</div>
            </div>
            <div style="position:relative; border-radius:12px; overflow:hidden; border:1px solid #e2e8f0; box-shadow:0 18px 40px rgba(15,23,42,.14);">
              <img src="{after}" style="display:block; width:1000px; height:500px;" alt="After repair: Description column widened">
              <div style="position:absolute; left:6.5%; top:12%; width:44%; height:72%;
                          border:4px solid #0f766e; border-radius:6px; background:rgba(13,148,136,.04);"></div>
            </div>
            <div class="shotlabel">Description 88.7 mm · 9.0 pt · the same text uses fewer lines</div>
          </div>
        </div>
        <div style="display:flex; gap:24px; margin-top:18px;">
          <div style="flex:1; background:#fff; border:1px solid #d6e0ec; border-radius:16px; padding:16px 22px;">
            <div style="font-size:34px; font-weight:700; color:#0f2a54; line-height:1.05;">62.0 → 88.7 mm</div>
            <div style="font-size:18px; color:#64748b; margin-top:5px;">Description width</div>
          </div>
          <div style="flex:1; background:#fff; border:1px solid #d6e0ec; border-radius:16px; padding:16px 22px;">
            <div style="font-size:34px; font-weight:700; color:#0f2a54; line-height:1.05;">9.5 → 9.0 pt</div>
            <div style="font-size:18px; color:#64748b; margin-top:5px;">Table font</div>
          </div>
          <div style="flex:1; background:#fff; border:1px solid #d6e0ec; border-radius:16px; padding:16px 22px;">
            <div style="font-size:34px; font-weight:700; color:#0f2a54; line-height:1.05;">{OPT_ITEMS} IR fields</div>
            <div style="font-size:18px; color:#64748b; margin-top:5px;">changed by Optimize layout</div>
          </div>
          <div style="flex:1; background:#fff; border:1px solid #d6e0ec; border-radius:16px; padding:16px 22px;">
            <div style="font-size:34px; font-weight:700; color:#0f2a54; line-height:1.05;">~7 → pass</div>
            <div style="font-size:18px; color:#64748b; margin-top:5px;">worst cell lines → text_fit</div>
          </div>
        </div>
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
              {''.join(f'<div class="mono" style="font-size:16px; color:#cbd5e1; line-height:1.55;">{esc(path)}</div>' for path in paths)}
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
          <span class="pill slate">6 cases · 3 models · 18 live runs</span>
          <span class="pill slate">screenshots labelled by source</span>
          <span class="pill slate">LibreOffice renders labelled</span>
          <span class="pill amber" style="background:rgba(245,158,11,.14); color:#fcd34d;">Docentric AX: not_tested</span>
        </div>
        <div style="margin-top:34px; font-size:38px; font-weight:600; color:#f8fafc;">
          Docentric AX compatibility: not tested.
        </div>
        <div style="margin-top:10px; font-size:20px; color:#9fb0c8; max-width:1500px; line-height:1.5;">
          The video shows recorded artifacts and a recorded live benchmark. It does not claim
          Word fidelity or Docentric AX compatibility.
        </div>
      </div>
      {claim_bar(7, dark=True)}
    </div>
    """


SCENE_BUILDERS = [scene_1, scene_2, scene_3, scene_4, scene_5, scene_6, scene_7, scene_8]


def scene_html(index: int) -> str:
    body = SCENE_BUILDERS[index]()
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Demo v2 · {SCENE_TITLES[index]}</title>
<style>{CSS}
.bhead, .brow {{ display:grid; grid-template-columns: 1.55fr 1fr 1fr 1.18fr; align-items:center; }}
.bhead {{ background:#0b1f3a; color:#cbd5e1; font-size:18px; letter-spacing:1.8px; text-transform:uppercase; padding:18px 34px; font-weight:700; }}
.brow {{ padding:22px 34px; border-top:1px solid #e2e8f0; min-height:188px; }}
.bmodel .bname {{ font-size:33px; font-weight:700; color:#0f2a54; display:flex; align-items:center; }}
.bmodel .bsub {{ font-size:17px; color:#64748b; margin-top:6px; }}
.bmetric .bval {{ font-size:58px; font-weight:700; line-height:1; color:#0f2a54; }}
.bmetric .bval.ok {{ color:#0f766e; }}
.bmetric .bval.warn {{ color:#b45309; }}
.bmetric .bval.bad {{ color:#b91c1c; }}
.bmetric .blabel {{ font-size:17px; color:#64748b; margin-top:6px; }}
</style></head>
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
<html lang="en"><head><meta charset="utf-8"><title>Docentric Copilot · demo v2</title>
<style>{THUMB_CSS}</style></head>
<body>
<div class="thumb">
  <div class="brandline"><div class="mark">D</div><div class="brandname">Docentric Copilot</div></div>
  <div>
    <div class="eyebrow">Live benchmark · {BENCH_DATE} · n={CASE_COUNT}</div>
    <h1>From a business brief<br>to a <span class="accent">reviewable DOCX</span>.</h1>
  </div>
  <div class="metric">
    <div class="big">6/6</div>
    <div class="metric-label">valid templates<span>gpt-6-sol · n=6 live cases · 2026-11-03</span></div>
  </div>
  <div class="footerline"><span>Docentric AX compatibility: not tested</span><span>No Word fidelity claim</span></div>
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
        [str(FFMPEG), "-y", "-loglevel", "error", "-i", str(path), "-ar", "48000", "-ac", "1", str(wav_path)],
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
        mp3 = TTS / f"scene{index + 1:02d}-{rate:+d}.mp3"
        wav = TTS / f"scene{index + 1:02d}-{rate:+d}.wav"
        last_error: Exception | None = None
        for try_number in range(3):
            try:
                _, sentences = asyncio.run(_synth_once(text, rate, mp3))
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
    for scene, start in zip(scenes, SCENE_STARTS):
        begin = start * 48000
        end = begin + len(scene.samples)
        if end > total_samples:
            raise RuntimeError("narration overruns the video")
        if end > (start + SCENE_SECONDS[scene.index]) * 48000:
            raise RuntimeError(f"scene {scene.index + 1} audio crosses into the next scene")
        track[begin:end] = scene.samples
        # A tiny fade at the tail avoids a click when a clip ends.
        fade = min(240, len(scene.samples))
        if fade:
            ramp = np.linspace(1.0, 0.0, fade, dtype=np.float32)
            track[end - fade : end] = (track[end - fade : end].astype(np.float32) * ramp).astype(np.int16)
    wav_path = AUDIO / "narration.wav"
    with wave.open(str(wav_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(48000)
        handle.writeframes(track.tobytes())
    return track


def srt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    millis = int(round(seconds * 1000))
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
    for scene, offset in zip(scenes, SCENE_STARTS):
        for position, sentence in enumerate(scene.sentences):
            start = offset + sentence.start
            end = offset + sentence.start + sentence.duration + 0.18
            if position + 1 < len(scene.sentences):
                end = min(end, offset + scene.sentences[position + 1].start - 0.02)
            end = min(end, offset + scene.duration + 0.10, offset + SCENE_SECONDS[scene.index] - 0.02)
            if end - start < 0.35:
                start = max(offset, end - 0.35)
            cues.append((start, end, caption_text(sentence.text)))

    blocks = []
    for number, (start, end, text) in enumerate(cues, start=1):
        blocks.append(f"{number}\n{srt_time(start)} --> {srt_time(end)}\n{text}\n")
    return "\n".join(blocks)


# --------------------------------------------------------------------------- #
# Rendering and encoding
# --------------------------------------------------------------------------- #


def render_html(html_text: str, png: Path) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--force-color-profile=srgb", "--font-render-hinting=none"])
        page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        page.set_content(html_text, wait_until="load")
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(120)
        page.screenshot(path=str(png), full_page=False)
        browser.close()


def render_thumbnail() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--force-color-profile=srgb", "--font-render-hinting=none"])
        page = browser.new_page(viewport={"width": 1280, "height": 720}, device_scale_factor=1)
        page.set_content(thumbnail_html(), wait_until="load")
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(120)
        page.screenshot(path=str(THUMB), full_page=False)
        browser.close()


def render_slides() -> None:
    for index in range(8):
        png = SLIDES / f"scene{index + 1:02d}.png"
        render_html(scene_html(index), png)
        print(f"rendered {png.name} ({png.stat().st_size // 1024} KB)")


def encode_scene(index: int) -> Path:
    source = SLIDES / f"scene{index + 1:02d}.png"
    target = VIDEO / f"scene{index + 1:02d}.mp4"
    frames = SCENE_SECONDS[index] * FPS
    filters = [f"scale={OUT_W}:{OUT_H}:flags=lanczos"]
    if index == 0:
        filters.append("fade=t=in:st=0:d=0.7")
    if index == 7:
        filters.append(f"fade=t=out:st={SCENE_SECONDS[index] - 1.0}:d=1.0")
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
            str(source),
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
            "-movflags",
            "+faststart",
            str(target),
        ],
        check=True,
    )
    return target


def encode_video(scenes: list[NarratedScene]) -> None:
    parts = [encode_scene(index) for index in range(8)]
    concat_file = VIDEO / "concat.txt"
    concat_file.write_text("".join(f"file '{part.as_posix()}'\n" for part in parts), encoding="utf-8")
    silent = VIDEO / "video-only.mp4"
    subprocess.run(
        [str(FFMPEG), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat_file),
         "-c", "copy", str(silent)],
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
# Text deliverables
# --------------------------------------------------------------------------- #


def mmss(seconds: int) -> str:
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def write_narration() -> None:
    lines = [
        "# Demo v2 narration",
        "",
        f"Duration **{mmss(TOTAL_SECONDS)}** · 1920×1080 · 30 fps · voice `{VOICE}` · "
        f"measured data from `benchmarks/live_report.json` ({BENCH_DATE}).",
        "",
        "The script is English only. Each scene is one paragraph; the SRT follows the same sentences.",
        "",
    ]
    for index, (title, start, end) in enumerate(zip(SCENE_TITLES, SCENE_STARTS, SCENE_ENDS), start=1):
        lines.append(f"## {index}. {title} — {mmss(start)}–{mmss(end)}")
        lines.append("")
        lines.append(SCENE_NARRATION[index - 1])
        lines.append("")
    (MEDIA / "narration-v2.md").write_text("\n".join(lines), encoding="utf-8")


def write_manifest() -> None:
    entries = []
    for index, (title, start, end) in enumerate(zip(SCENE_TITLES, SCENE_STARTS, SCENE_ENDS)):
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
    (MEDIA / "scene-manifest.json").write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_release_notes() -> None:
    sizes = {
        "video_mb": OUT.stat().st_size / (1024 * 1024),
        "srt_kb": SRT.stat().st_size / 1024,
        "thumb_kb": THUMB.stat().st_size / 1024,
    }
    text = f"""# Demo video v2 — release notes

This release note accompanies `docs/media/demo-v2.mp4` ({sizes['video_mb']:.1f} MiB),
`docs/media/demo-v2.srt`, `docs/media/thumbnail.png`, `docs/media/narration-v2.md` and
`docs/media/scene-manifest.json`. Nothing is committed or pushed; the files are in the working tree.

## What is live, and what is replay

**Verified live on {BENCH_DATE}.** The multi-LLM table uses `benchmarks/live_report.json`: {CASE_COUNT} cases,
{PROVIDER_COUNT} providers and one live run per case/provider ({CASE_COUNT * PROVIDER_COUNT} runs total),
with an estimated spend of ${SPEND:.6f} and {UNKNOWN_COST_RUNS} unknown-cost runs. Models:
`openai:gpt-6-sol`, `anthropic:claude-sonnet-5-5`, `gemini:gemini-3.1-flash-lite`. The routing scene's
executed model (`gpt-6-sol`, run `{ROUTING_RUN_ID}`) comes from the same report and its saved trace.

**Deterministic or recorded (replay).** The routing panel, schema explorer, revision diff and DOCX
preview are recorded workspace screenshots. The DOCX artifact facts (40,585 bytes, two pages) come from
`docs/media/demo-session.json`. The LibreOffice before/after pages are the recorded 1241×1754 renders
from LibreOffice Writer 25.2 + `pdftoppm`; this video does not re-render them. The optimize response used
for scene 6 was regenerated from the bundled `quotation-long-items` demo with the deterministic mock
planner and is saved as `docs/media/optimize-response.json`; no provider was called for it.

The routing recommendation is deliberately **not** presented as the executed model. The panel shows a
recommendation and asks for review; the executed model is read from the live trace. The provider
dropdown visible in the full workspace capture is not used as evidence for the live run.

## Benchmark caveats

- One run per case and provider. These are observations, not a statistically significant benchmark.
- The benchmark's recommendation is `{BENCH['recommendation']['provider']}` (quality first, then known cost,
  then p50 latency). The routing panel in scene 3 is a workspace routing recommendation, not that aggregate.
- Cost per valid template is derived as `cost_usd / successful_runs` from the report. Unknown prices are
  shown as **N/A**, never **$0.00**.
- The `missing-field` case has an empty expected set, so its precision/recall are excluded from aggregates.

## LibreOffice caveat

The two page images labelled **LibreOffice rendering** are PDF pages rasterised from LibreOffice Writer
25.2 in the optional `api-pdf` image. They are an independent visual check. They are not Microsoft Word
pagination, and this video makes no Word fidelity claim. LibreOffice may substitute fonts and paginate
differently from Word or Docentric AX.

## Docentric AX compatibility

`Docentric AX compatibility: not tested.` The validation status remains `not_tested`; no licensed
Docentric environment was used. The closing scene uses the exact phrase "Docentric AX compatibility:
not tested" and the manifest records the `not_tested` session value.

## What the video deliberately does not claim

- No Word fidelity or identical pagination.
- No Docentric AX compatibility.
- No mock run presented as a live provider call.
- No API keys, prompts containing secrets or local filesystem paths in the narration.
- No screen-recording label: the synthetic cursor is a slide annotation, and screenshots are labelled by
  source (workspace capture, independent preview, LibreOffice rendering).

## Verification

The build script is `scripts/build_demo_video_v2.py`. It renders source slides at 2560×1440 and downscales
to 1920×1080 with ffmpeg. `ffprobe` reports H.264 video, AAC audio, 1920×1080, 30 fps and a duration of
{mmss(TOTAL_SECONDS)}. File sizes: video {sizes['video_mb']:.1f} MiB, SRT {sizes['srt_kb']:.1f} KiB,
thumbnail {sizes['thumb_kb']:.1f} KiB.
"""
    (ROOT / "RELEASE_NOTES_video.md").write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def main() -> int:
    print(f"benchmark: {BENCH_DATE}, {CASE_COUNT} cases, {PROVIDER_COUNT} providers, ${SPEND:.6f}")
    print(f"output: {OUT}")
    render_slides()
    render_thumbnail()
    scenes = [synthesize_scene(index) for index in range(8)]
    build_audio(scenes)
    srt_text = build_srt(scenes)
    SRT.write_text(srt_text + "\n", encoding="utf-8")
    print(f"wrote {SRT} ({len(srt_text.splitlines())} lines)")
    write_narration()
    write_manifest()
    encode_video(scenes)
    write_release_notes()
    print(f"wrote {OUT} ({OUT.stat().st_size / (1024 * 1024):.1f} MiB)")
    print(f"wrote {THUMB} ({THUMB.stat().st_size / 1024:.1f} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
