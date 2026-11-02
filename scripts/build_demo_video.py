"""Build the narrated Docentric Copilot demo video (1920x1080, 30 fps, H.264/AAC).

The video is assembled from the work-item screenshots in ``docs/assets``, the real
demo session in ``docs/media/demo-session.json`` and the measured comparison in
``docs/media/compare-response.json``. Every number shown or spoken comes from one
of those files or is visible in the corresponding screenshot.

Narration is synthesised with Edge TTS, slides are composed in HTML and rendered
with Playwright, and the segments are muxed with imageio-ffmpeg.

Usage::

    PLAYWRIGHT_BROWSERS_PATH=.tools/pw-browsers .venv/bin/python scripts/build_demo_video.py
"""

from __future__ import annotations

import asyncio
import base64
import html
import json
import subprocess
from io import BytesIO
from pathlib import Path

import edge_tts
import imageio_ffmpeg
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "docs" / "assets"
WORK = ROOT / ".tools" / "video-build"
WORK.mkdir(parents=True, exist_ok=True)
OUT = ROOT / "docs" / "media" / "demo.mp4"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
W, H = 1920, 1080
NAVY, ACCENT, INK, MUTED, PAPER = "#0f2a54", "#2563eb", "#1f2937", "#64748b", "#eef2f7"
VOICE = "en-US-GuyNeural"
RATE = "+4%"

demo = json.loads((ROOT / "docs" / "media" / "demo-session.json").read_text(encoding="utf-8"))
compare = json.loads(
    (ROOT / "docs" / "media" / "compare-response.json").read_text(encoding="utf-8")
)
runs = {run["provider"]: run for run in compare["runs"]}
openai_latency = runs["openai"]["latency_ms"] / 1000
anthropic_latency = runs["anthropic"]["latency_ms"] / 1000
openai_tokens = runs["openai"]["tokens"]
anthropic_tokens = runs["anthropic"]["tokens"]
openai_cost = runs["openai"]["cost_usd"] or 0.0
anthropic_cost = runs["anthropic"]["cost_usd"] or 0.0
quality = demo["quality"]
quality_counts = dict.fromkeys(("passed", "warning", "failed"), 0)
for check in quality["checks"]:
    quality_counts[check["status"]] += 1
mapping_rows = demo["mapping"]["mappings"]
mapping_counts = dict.fromkeys(("confirmed", "schema_valid", "needs_review"), 0)
for row in mapping_rows:
    if row["status"] in mapping_counts:
        mapping_counts[row["status"]] += 1

# Visible in docs/assets/quality-optimized.png: "Before: 8 checks (7 passed,
# 1 warning, 0 failed) -> After: 8 checks (8 passed, 0 warning, 0 failed)" and
# three fit_table fixes (374 mm -> 170 mm twice, 209 mm -> 170 mm).
OPTIMIZED_PASSED = 8
OPTIMIZE_FIXES = 3
# Visible in docs/assets/revision-v1-v2.png: "TOTAL CHANGES 5" from v1 to v2.
REVISION_CHANGES = 5

BADGE = {
    "confirmed": ("#dcfce7", "#166534"),
    "schema_valid": ("#dbeafe", "#1e40af"),
    "needs_review": ("#fef3c7", "#92400e"),
    "conflict": ("#fee2e2", "#991b1b"),
    "missing": ("#e2e8f0", "#334155"),
    "invalid": ("#fee2e2", "#991b1b"),
}


def data_uri(path: Path, crop: tuple[int, int, int, int] | None = None) -> tuple[str, int, int]:
    image = Image.open(path).convert("RGB")
    if crop is not None:
        image = image.crop(crop)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}", image.width, image.height


BASE_CSS = f"""
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; width: {W}px; height: {H}px; overflow: hidden; }}
body {{
  font-family: 'DejaVu Sans', Arial, sans-serif;
  color: {INK};
  background: {PAPER};
  -webkit-font-smoothing: antialiased;
}}
.stage {{ position: relative; width: {W}px; height: {H}px; overflow: hidden;
  background:
    radial-gradient(1200px 600px at 85% -10%, rgba(37, 99, 235, .10), transparent 60%),
    radial-gradient(900px 500px at 0% 110%, rgba(15, 42, 84, .08), transparent 60%),
    {PAPER}; }}
header {{ position: relative; height: 88px; display: flex; align-items: center; gap: 20px;
  padding: 0 64px; background: #ffffff; border-bottom: 1px solid #dfe6f0; }}
.num {{ width: 44px; height: 44px; flex: 0 0 44px; border-radius: 12px;
  background: #e8efff; color: {ACCENT}; font-weight: 700; font-size: 20px;
  display: flex; align-items: center; justify-content: center; letter-spacing: .02em; }}
.titles {{ min-width: 0; }}
h1 {{ margin: 0; font-size: 30px; line-height: 34px; color: {NAVY}; letter-spacing: -.01em; }}
.sub {{ margin: 3px 0 0; font-size: 17px; line-height: 22px; color: {MUTED}; }}
.brand {{ margin-left: auto; text-align: right; font-size: 15px; color: #94a3b8; white-space: nowrap; }}
.brand b {{ display: block; color: {NAVY}; font-size: 16px; }}
.progress {{ position: absolute; left: 0; right: 0; bottom: 0; height: 3px; display: flex; gap: 2px; }}
.progress span {{ flex: 1; background: #e6ecf5; }}
.progress span.on {{ background: {ACCENT}; }}
.frame {{ position: absolute; left: 50%; transform: translateX(-50%);
  border-radius: 14px; overflow: hidden; background: #fff;
  border: 1px solid #d7e0eb; box-shadow: 0 22px 60px rgba(15, 42, 84, .20); }}
.frame img {{ display: block; width: 100%; height: 100%; }}
.foot {{ position: absolute; left: 64px; bottom: 26px; font-size: 15px; color: #94a3b8; }}
.foot b {{ color: {MUTED}; font-weight: 600; }}
"""


def progress(number: int) -> str:
    return (
        '<div class="progress">'
        + "".join(
            f'<span class="{"on" if index <= number else ""}"></span>' for index in range(1, 11)
        )
        + "</div>"
    )


def shot_slide(
    number: int,
    title: str,
    subtitle: str,
    image_path: Path,
    *,
    crop: tuple[int, int, int, int] | None = None,
    footer: str = "",
    max_width: int = 1706,
    max_height: int = 924,
) -> str:
    uri, width, height = data_uri(image_path, crop)
    scale = min(max_width / width, max_height / height)
    shown_w, shown_h = round(width * scale), round(height * scale)
    top = 104 + (max_height - shown_h) // 2
    foot = f'<div class="foot">{footer}</div>' if footer else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{BASE_CSS}</style></head>
<body><div class="stage">
<header><div class="num">{number:02d}</div><div class="titles"><h1>{html.escape(title)}</h1>
<p class="sub">{subtitle}</p></div><div class="brand"><b>Docentric Copilot</b>demo video</div></header>
{progress(number)}
<div class="frame" style="top:{top}px;width:{shown_w}px;height:{shown_h}px">
<img src="{uri}" alt=""></div>
{foot}
</div></body></html>"""


def mapping_slide() -> str:
    rows = ""
    for row in mapping_rows:
        background, foreground = BADGE.get(row["status"], ("#e2e8f0", "#334155"))
        confidence = round((row.get("confidence_score") or 0) * 100)
        highlight = " row-review" if row["status"] == "needs_review" else ""
        rows += (
            f'<tr class="body-row{highlight}"><td class="req">{html.escape(row["requirement"])}</td>'
            f'<td><span class="pill" style="background:{background};color:{foreground}">'
            f"{html.escape(row['status'].replace('_', ' '))}</span></td>"
            f'<td class="path">{html.escape(row.get("selected_field_path") or "—")}</td>'
            f'<td class="conf">{confidence}%</td></tr>'
        )
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{BASE_CSS}
main {{ padding: 26px 64px 0; }}
table {{ width: 100%; border-collapse: separate; border-spacing: 0; background: #fff;
  border: 1px solid #dbe3ee; border-radius: 14px; overflow: hidden;
  box-shadow: 0 18px 50px rgba(15, 42, 84, .14); }}
th {{ text-align: left; font-size: 14px; letter-spacing: .09em; text-transform: uppercase;
  color: {MUTED}; padding: 14px 20px; background: #f8fafc; border-bottom: 1px solid #e2e8f0; }}
td {{ padding: 11px 20px; border-bottom: 1px solid #eef2f7; font-size: 17px; vertical-align: middle; }}
tr:last-child td {{ border-bottom: 0; }}
td.req {{ font-weight: 600; width: 40%; }}
td.path {{ font-family: 'DejaVu Sans Mono', monospace; font-size: 14px; color: #334155; width: 34%; }}
td.conf {{ text-align: right; font-weight: 700; color: {NAVY}; width: 9%; }}
.row-review td {{ background: #fffaf0; }}
.pill {{ display: inline-block; padding: 5px 13px; border-radius: 999px; font-size: 13px;
  font-weight: 700; text-transform: capitalize; }}
.kpis {{ position: absolute; left: 64px; right: 64px; bottom: 30px; display: flex; gap: 14px; }}
.kpi {{ background: #fff; border: 1px solid #dbe3ee; border-radius: 12px; padding: 10px 18px;
  font-size: 16px; color: {MUTED}; box-shadow: 0 6px 16px rgba(15, 42, 84, .06); }}
.kpi b {{ color: {NAVY}; font-size: 20px; margin-right: 6px; }}
</style></head><body><div class="stage">
<header><div class="num">05</div><div class="titles"><h1>Mapping review</h1>
<p class="sub">{mapping_counts["confirmed"]} confirmed · {mapping_counts["schema_valid"]} schema-valid · {mapping_counts["needs_review"]} needs review · schema evidence is the authority</p></div>
<div class="brand"><b>Docentric Copilot</b>demo video</div></header>
{progress(5)}
<main><table><thead><tr><th>Requirement</th><th>Status</th><th>Schema field</th><th>Confidence</th></tr></thead>
<tbody>{rows}</tbody></table></main>
<div class="kpis"><div class="kpi"><b>{len(mapping_rows)}</b> requirements</div>
<div class="kpi"><b>{mapping_counts["confirmed"]}</b> confirmed</div>
<div class="kpi"><b>{mapping_counts["schema_valid"]}</b> schema-valid</div>
<div class="kpi"><b>{mapping_counts["needs_review"]}</b> needs review</div></div>
</div></body></html>"""


def intro_slide() -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{BASE_CSS}
body {{ background: #f4f7fb; }}
.stage {{ padding: 0; }}
.hero {{ position: absolute; left: 88px; top: 96px; width: 980px; }}
.kicker {{ display: inline-flex; align-items: center; gap: 10px; font-size: 16px; font-weight: 700;
  letter-spacing: .14em; text-transform: uppercase; color: {ACCENT}; }}
.kicker span {{ display: inline-block; width: 34px; height: 3px; background: {ACCENT}; }}
h1 {{ margin: 22px 0 0; font-size: 64px; line-height: 70px; color: {NAVY}; letter-spacing: -.025em; }}
.lede {{ margin: 24px 0 0; font-size: 24px; line-height: 36px; color: #334155; max-width: 900px; }}
.pillars {{ display: flex; gap: 14px; margin-top: 34px; }}
.pillar {{ background: #fff; border: 1px solid #dbe3ee; border-radius: 12px; padding: 12px 18px;
  font-size: 16px; color: {NAVY}; font-weight: 600; box-shadow: 0 8px 22px rgba(15, 42, 84, .07); }}
.flow {{ position: absolute; right: 88px; top: 176px; width: 640px; display: flex; flex-direction: column; gap: 16px; }}
.step {{ display: flex; align-items: center; gap: 16px; background: #fff; border: 1px solid #dbe3ee;
  border-radius: 14px; padding: 18px 22px; box-shadow: 0 14px 34px rgba(15, 42, 84, .09); }}
.step .dot {{ width: 38px; height: 38px; border-radius: 10px; background: #e8efff; color: {ACCENT};
  font-weight: 700; display: flex; align-items: center; justify-content: center; font-size: 15px; }}
.step b {{ display: block; color: {NAVY}; font-size: 20px; }}
.step span {{ display: block; color: {MUTED}; font-size: 15px; margin-top: 2px; }}
.arrow {{ text-align: center; color: #94a3b8; font-size: 20px; line-height: 10px; }}
.claim {{ position: absolute; left: 88px; bottom: 54px; right: 88px; display: flex;
  justify-content: space-between; align-items: center; font-size: 16px; color: {MUTED}; }}
.claim .ax {{ background: #fffbeb; border: 1px solid #fcd34d; color: #92400e; border-radius: 999px;
  padding: 8px 16px; font-weight: 600; }}
</style></head><body><div class="stage">
<div class="hero"><div class="kicker"><span></span>Docentric Copilot · v0.4.0</div>
<h1>From business brief<br>to validated document</h1>
<p class="lede">A schema-aware template workspace for Docentric AX report packages:
evidence for every field, validation on every run, and a deterministic generic DOCX.</p>
<div class="pillars"><div class="pillar">Adaptive routing</div><div class="pillar">Quality dashboard</div>
<div class="pillar">Live model comparison</div></div></div>
<div class="flow">
<div class="step"><div class="dot">01</div><div><b>Plain-language brief</b><span>One paragraph, no template syntax.</span></div></div>
<div class="arrow">▼</div>
<div class="step"><div class="dot">02</div><div><b>Schema evidence</b><span>Every requirement bound to a real field.</span></div></div>
<div class="arrow">▼</div>
<div class="step"><div class="dot">03</div><div><b>Validated Template IR</b><span>Structural, semantic and logical gates.</span></div></div>
<div class="arrow">▼</div>
<div class="step"><div class="dot">04</div><div><b>Generic DOCX</b><span>Deterministic compile, immutable versions.</span></div></div>
</div>
<div class="claim"><span>Open source · github.com/SergeyGer/Docentric-Copilot</span>
<span class="ax">Docentric AX compatibility: not tested</span></div>
</div></body></html>"""


def closing_slide() -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{BASE_CSS}
body {{ background: {NAVY}; }}
.stage {{ background:
  radial-gradient(1000px 600px at 80% 0%, rgba(37, 99, 235, .45), transparent 60%),
  radial-gradient(900px 600px at 0% 100%, rgba(56, 189, 248, .18), transparent 60%), {NAVY}; }}
.wrap {{ position: absolute; left: 96px; top: 110px; right: 96px; }}
.kicker {{ color: #93c5fd; font-size: 16px; font-weight: 700; letter-spacing: .16em; text-transform: uppercase; }}
h1 {{ margin: 18px 0 0; font-size: 70px; line-height: 76px; color: #fff; letter-spacing: -.03em; }}
.url {{ margin-top: 26px; font-size: 30px; color: #dbeafe; }}
.url b {{ color: #fff; }}
.release {{ display: inline-block; margin-top: 30px; background: rgba(255,255,255,.10);
  border: 1px solid rgba(255,255,255,.24); color: #fff; border-radius: 999px; padding: 10px 20px;
  font-size: 18px; }}
.cards {{ position: absolute; left: 96px; right: 96px; bottom: 96px; display: flex; gap: 18px; }}
.card {{ flex: 1; background: rgba(255,255,255,.07); border: 1px solid rgba(255,255,255,.16);
  border-radius: 14px; padding: 18px 22px; color: #dbeafe; font-size: 16px; line-height: 24px; }}
.card b {{ display: block; color: #fff; font-size: 18px; margin-bottom: 4px; }}
.ax {{ border-color: #fbbf24; background: rgba(251, 191, 36, .12); color: #fde68a; }}
.ax b {{ color: #fef3c7; }}
</style></head><body><div class="stage">
<div class="wrap"><div class="kicker">Open source · try it yourself</div>
<h1>Build the document,<br>keep the evidence.</h1>
<div class="url"><b>github.com/SergeyGer/Docentric-Copilot</b></div>
<div class="release">Release v0.4.0 · routing · quality dashboard · model comparison</div></div>
<div class="cards">
<div class="card"><b>Deterministic by default</b>The offline planner and compiler run without a cloud key.</div>
<div class="card"><b>Measured, not claimed</b>Latency, mapping counts and validation statuses come from the API.</div>
<div class="card ax"><b>Docentric AX compatibility: not tested</b>Output is a generic DOCX. No part of this demo is a compatibility claim.</div>
</div>
</div></body></html>"""


slides: list[tuple[str, str, str]] = []

slides.append(
    (
        "intro",
        intro_slide(),
        "Most business documents begin as a paragraph and end as a template nobody wants to touch. "
        "Docentric Copilot turns the paragraph into a schema-aware template with evidence, validation and "
        "a deterministic Word document.",
    )
)
slides.append(
    (
        "source",
        shot_slide(
            2,
            "Data source and schema",
            f"{demo['stats']['node_count']} fields · {demo['stats']['scalar_count']} scalars · "
            f"{demo['stats']['collection_count']} collection · depth {demo['stats']['max_depth']} · "
            f"{len(demo['sections'])} sections",
            ASSETS / "source-panel.png",
            footer="Bundled DDSP package · parser diagnostics · sample data loaded",
            max_width=1860,
        ),
        "The source is a DDSP package: thirty-four fields, one repeating collection, three sections. The "
        "parser normalises it into a schema the planner can bind against.",
    )
)
slides.append(
    (
        "routing",
        shot_slide(
            3,
            "Routing decides the tier",
            "Ambiguous · anthropic · budget $0.30 · human review",
            ASSETS / "routing-panel.png",
            crop=(0, 112, 1600, 1000),
            footer="Routing is advisory; it never gates planning",
        ),
        "Before planning, the router classifies the brief. This one is ambiguous: a party-scoped VAT "
        "requirement. It recommends Anthropic with a thirty-cent budget and human review.",
    )
)
slides.append(
    (
        "compare",
        shot_slide(
            4,
            "Compare models on the same brief",
            f"openai {openai_latency:.1f} s · {openai_tokens:,} tokens · ${openai_cost:.3f} · "
            f"anthropic {anthropic_latency:.1f} s · {anthropic_tokens:,} tokens · ${anthropic_cost:.2f} · "
            f"recommended: {compare['recommended']}",
            ASSETS / "compare-models.png",
            crop=(0, 10, 1600, 910),
            footer="Live call · may incur provider cost · usage and cost as reported by the API",
        ),
        "Compare models runs the same brief through live providers. OpenAI: forty-four point eight seconds, "
        "eight thousand nine hundred ninety-three tokens, four cents. Anthropic: seventeen point five "
        "seconds, thirteen thousand nine hundred thirty-four tokens, zero reported cost. Anthropic is "
        "recommended. This is a live call and may incur cost.",
    )
)
slides.append(
    (
        "mapping",
        mapping_slide(),
        "Mapping review is where trust is earned. Nine requirements are confirmed, two schema-valid, and one "
        "stays open for a human: the VAT number could come from the customer or the company.",
    )
)
slides.append(
    (
        "quality",
        shot_slide(
            6,
            "Quality dashboard: the defect",
            f"table_layout warning · {quality['checks'][0]['message']} · "
            f"{quality_counts['passed']} passed / {quality_counts['warning']} warning / {quality_counts['failed']} failed",
            ASSETS / "quality-defect.png",
            crop=(0, 112, 1600, 1000),
            footer="Deterministic IR checks · every finding names its IR path",
        ),
        "Quality analysis is deterministic and explainable. Three tables are wider than the text area, so "
        "table layout is a warning, not a pass.",
    )
)
slides.append(
    (
        "optimized",
        shot_slide(
            7,
            "Optimize layout writes a new version",
            f"v2 · {OPTIMIZED_PASSED} passed / 0 warning / 0 failed · {OPTIMIZE_FIXES} tables scaled to 170 mm",
            ASSETS / "quality-optimized.png",
            crop=(0, 112, 1600, 1000),
            footer="Typed fixes · immutable version · before-and-after counts stay visible",
        ),
        "Optimize layout applies typed fixes and writes an immutable version. All three tables are scaled "
        "to a hundred and seventy millimetres. Eight checks pass, zero warnings.",
    )
)
slides.append(
    (
        "preview",
        shot_slide(
            8,
            "Preview and DOCX: two pages",
            f"2 A4 pages · DOCX {demo['docx_artifact_id'][:12]}… · HTML preview, generic DOCX artifact",
            ASSETS / "preview-pages.png",
            footer="Preview is HTML and never claims Word pagination",
        ),
        "The same IR renders two A4 pages: quotation, items, totals, terms, and bank details. The preview "
        "is HTML; the compiled artifact is a generic DOCX.",
    )
)
slides.append(
    (
        "revision",
        shot_slide(
            9,
            "Revision: V1 to V2",
            f"v1 → v2 · {REVISION_CHANGES} changed paths · no overwrite · v1 restorable",
            ASSETS / "revision-v1-v2.png",
            crop=(0, 10, 1600, 910),
            footer="Plain-language instruction · structural diff · immutable versions",
        ),
        "Revision is controlled. A plain-language instruction creates version two with a five-path structural "
        "diff. Version one can be restored.",
    )
)
slides.append(
    (
        "closing",
        closing_slide(),
        "Open source at github dot com slash SergeyGer slash Docentric-Copilot, release v0.4.0. Docentric AX "
        "compatibility remains not tested. Output is generic DOCX; no compatibility claim.",
    )
)


def render_slides(items: list[tuple[str, str]]) -> list[Path]:
    out_dir = WORK / "slides"
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--force-color-profile=srgb"])
        page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        for name, markup in items:
            page.set_content(markup, wait_until="load")
            page.wait_for_function(
                "() => Array.from(document.images).every((image) => image.complete)"
            )
            page.wait_for_timeout(250)
            path = out_dir / f"{name}.png"
            page.screenshot(path=str(path))
            paths.append(path)
            print(f"slide {name}: {path.stat().st_size // 1024} KB", flush=True)
        browser.close()
    return paths


async def speak(text: str, path: Path) -> None:
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            await edge_tts.Communicate(text, VOICE, rate=RATE).save(str(path))
            return
        except Exception as exc:  # pragma: no cover - network retry
            last_error = exc
            print(f"TTS attempt {attempt} failed for {path.name}: {exc}", flush=True)
            await asyncio.sleep(2 * attempt)
    raise RuntimeError(f"Edge TTS failed for {path.name}: {last_error}")


def ffmpeg(args: list[str]) -> None:
    result = subprocess.run(args, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(
            "ffmpeg failed:\n" + result.stderr.decode("utf-8", errors="replace")[-4000:]
        )


def main() -> None:
    slide_images = render_slides([(name, markup) for name, markup, _ in slides])
    audio_dir = WORK / "audio"
    audio_dir.mkdir(exist_ok=True)
    seg_dir = WORK / "segments"
    seg_dir.mkdir(exist_ok=True)
    for old in seg_dir.glob("*.mp4"):
        old.unlink()

    segments: list[Path] = []
    for index, (name, _, narration) in enumerate(slides, start=1):
        audio = audio_dir / f"{index:02d}-{name}.mp3"
        asyncio.run(speak(narration, audio))
        segment = seg_dir / f"{index:02d}-{name}.mp4"
        ffmpeg(
            [
                FFMPEG,
                "-y",
                "-loop",
                "1",
                "-i",
                str(slide_images[index - 1]),
                "-i",
                str(audio),
                "-filter_complex",
                "[1:a]adelay=200:all=1,apad=pad_dur=0.45[a]",
                "-map",
                "0:v",
                "-map",
                "[a]",
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
                str(segment),
            ]
        )
        segments.append(segment)
        print(f"segment {index:02d} {name}: {segment.stat().st_size // 1024} KB", flush=True)

    listing = seg_dir / "list.txt"
    listing.write_text("".join(f"file '{segment}'\n" for segment in segments), encoding="utf-8")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg(
        [
            FFMPEG,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
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
            "-movflags",
            "+faststart",
            str(OUT),
        ]
    )
    print(f"video: {OUT} ({OUT.stat().st_size // 1024} KB)", flush=True)


if __name__ == "__main__":
    main()
