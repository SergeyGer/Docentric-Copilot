"""Build the narrated Docentric Copilot demo video (1920x1080, 30 fps, H.264/AAC).

Inputs: ``docs/media/demo-session.json`` (a real ``POST /api/v1/demo/sessions`` response)
and the DejaVu fonts. Narration is synthesised with Edge TTS, slides are rendered from
the live preview HTML with Playwright, and segments are muxed with imageio-ffmpeg.

Usage::

    PLAYWRIGHT_BROWSERS_PATH=.tools/pw-browsers python scripts/build_demo_video.py
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import edge_tts
import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / ".tools" / "video"
WORK.mkdir(parents=True, exist_ok=True)
OUT = ROOT / "docs" / "media" / "demo.mp4"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
W, H = 1920, 1080
NAVY, ACCENT, INK, MUTED, PAPER = "#0f2a54", "#2563eb", "#1f2937", "#64748b", "#f6f8fb"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

demo = json.loads((ROOT / "docs" / "media" / "demo-session.json").read_text())
mapping = demo["mapping"]["mappings"]
counts: dict[str, int] = {}
for item in mapping:
    counts[item["status"]] = counts.get(item["status"], 0) + 1


def font(size: int, bold: bool = False):
    return ImageFont.truetype(FONT_B if bold else FONT, size)


def card(path: Path, kicker: str, title: str, body: str, footer: str = "") -> None:
    img = Image.new("RGB", (W, H), "#ffffff")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 14], fill=NAVY)
    d.text((120, 150), kicker.upper(), font=font(28, True), fill=ACCENT)
    y = 220
    for line in title.split("\n"):
        d.text((120, y), line, font=font(76, True), fill=NAVY)
        y += 92
    y += 30
    for line in body.split("\n"):
        d.text((120, y), line, font=font(36), fill=INK)
        y += 54
    if footer:
        d.text((120, H - 110), footer, font=font(28), fill=MUTED)
    d.text((W - 310, H - 110), "Docentric Copilot", font=font(28, True), fill=MUTED)
    img.save(path)


def render(html: str, out: Path) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": W, "height": H})
        page.set_content(html, wait_until="load")
        page.wait_for_timeout(400)
        page.screenshot(path=str(out))
        browser.close()


BADGE = {
    "confirmed": ("#dcfce7", "#166534"),
    "schema_valid": ("#dbeafe", "#1e40af"),
    "needs_review": ("#fef3c7", "#92400e"),
    "conflict": ("#fee2e2", "#991b1b"),
    "missing": ("#e2e8f0", "#334155"),
    "invalid": ("#fee2e2", "#991b1b"),
}
rows = ""
for item in mapping[:10]:
    bg, fg = BADGE.get(item["status"], ("#e2e8f0", "#334155"))
    conf = round((item.get("confidence_score") or 0) * 100)
    rows += (
        f'<tr><td class="req">{item["requirement"][:56]}</td>'
        f'<td><span class="pill" style="background:{bg};color:{fg}">'
        f"{item['status'].replace('_', ' ')}</span></td>"
        f'<td class="path">{item.get("selected_field_path") or "—"}</td>'
        f'<td class="conf">{conf}%</td></tr>'
    )

mapping_html = f"""<!doctype html><html><head><meta charset="utf-8"><style>
body{{margin:0;font-family:'DejaVu Sans',sans-serif;background:{PAPER};color:{INK};width:{W}px;height:{H}px}}
header{{background:{NAVY};color:#fff;padding:32px 64px;display:flex;justify-content:space-between;align-items:center}}
h1{{font-size:34px;margin:0}}span.sub{{opacity:.75;font-size:20px}}
main{{padding:30px 64px}}table{{width:100%;border-collapse:collapse;background:#fff;box-shadow:0 8px 30px rgba(15,42,84,.10);border-radius:10px;overflow:hidden}}
th{{text-align:left;font-size:17px;letter-spacing:.08em;text-transform:uppercase;color:{MUTED};padding:15px 20px;border-bottom:2px solid #e2e8f0}}
td{{padding:13px 20px;border-bottom:1px solid #eef2f7;font-size:19px;vertical-align:top}}
td.req{{font-weight:600;width:37%}}td.path{{font-family:monospace;font-size:16px;color:#334155}}td.conf{{font-weight:700;text-align:right}}
.pill{{padding:6px 14px;border-radius:999px;font-size:15px;font-weight:700;text-transform:capitalize}}
.bar{{display:flex;gap:14px;margin-top:20px}}
.kpi{{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:13px 22px;font-size:19px}}
b{{color:{NAVY}}}</style></head><body>
<header><h1>Mapping review</h1><span class="sub">every requirement, its evidence and its confidence</span></header>
<main><table><tr><th>Requirement</th><th>Status</th><th>Schema field</th><th>Confidence</th></tr>{rows}</table>
<div class="bar"><div class="kpi"><b>{counts.get("confirmed", 0)}</b> confirmed</div>
<div class="kpi"><b>{counts.get("schema_valid", 0)}</b> schema-valid</div>
<div class="kpi"><b>{counts.get("needs_review", 0)}</b> needs review</div>
<div class="kpi"><b>{counts.get("conflict", 0)}</b> conflict</div></div></main></body></html>"""


def preview_slides() -> list[Path]:
    source = WORK / "preview.html"
    source.write_text(demo["preview_html"])
    shots: list[Path] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1300, "height": 1500}, device_scale_factor=1.4)
        page.goto(source.as_uri(), wait_until="load")
        page.wait_for_timeout(600)
        pages = page.locator("section.page")
        for index in range(min(2, pages.count())):
            raw = WORK / f"page{index + 1}.png"
            pages.nth(index).screenshot(path=str(raw))
            canvas = Image.new("RGB", (W, H), "#e9eef5")
            shot = Image.open(raw).convert("RGB")
            ratio = min((H - 80) / shot.height, (W - 260) / shot.width)
            shot = shot.resize((int(shot.width * ratio), int(shot.height * ratio)), Image.LANCZOS)
            canvas.paste(shot, ((W - shot.width) // 2, (H - shot.height) // 2 - 8))
            out = WORK / f"s{3 + index}.png"
            canvas.save(out)
            shots.append(out)
        browser.close()
    return shots


def validation_slide() -> Path:
    html = f"""<!doctype html><html><head><meta charset="utf-8"><style>
body{{margin:0;font-family:'DejaVu Sans',sans-serif;background:{PAPER};width:{W}px;height:{H}px;color:{INK}}}
header{{background:{NAVY};color:#fff;padding:32px 64px}}h1{{margin:0;font-size:34px}}
main{{padding:38px 64px;display:grid;grid-template-columns:1fr 1fr;gap:28px}}
.card{{background:#fff;border-radius:12px;padding:26px 32px;box-shadow:0 8px 30px rgba(15,42,84,.10)}}
h2{{margin:0 0 16px;font-size:24px;color:{NAVY}}}
.row{{display:flex;justify-content:space-between;font-size:21px;padding:9px 0;border-bottom:1px solid #eef2f7}}
.ok{{color:#166534;font-weight:700}}.warn{{color:#92400e;font-weight:700}}
code{{font-family:monospace;font-size:17px}}</style></head><body>
<header><h1>Validation and artifacts</h1></header><main>
<div class="card"><h2>Checks</h2>
<div class="row"><span>Structural</span><span class="ok">passed</span></div>
<div class="row"><span>Semantic</span><span class="ok">passed</span></div>
<div class="row"><span>Logical</span><span class="ok">passed</span></div>
<div class="row"><span>Visual</span><span class="ok">passed</span></div>
<div class="row"><span>Docentric AX compatibility</span><span class="warn">not tested</span></div>
<p style="font-size:18px;color:{MUTED};margin-top:16px">Generic DOCX only. Compatibility with Docentric AX is not verified.</p></div>
<div class="card"><h2>Artifacts</h2>
<div class="row"><span>DOCX document</span><span>{demo["docx_artifact_id"][:10]}…</span></div>
<div class="row"><span>Template IR digest</span><span><code>{demo["ir_digest"][:16]}…</code></span></div>
<div class="row"><span>Mapping report</span><span>JSON</span></div>
<div class="row"><span>Validation report</span><span>JSON + HTML</span></div>
<div class="row"><span>Preview</span><span>HTML</span></div>
<p style="font-size:18px;color:{MUTED};margin-top:16px">Every artifact is content-addressed and reproducible.</p></div>
</main></body></html>"""
    out = WORK / "s5.png"
    render(html, out)
    return out


slides: list[tuple[Path, str]] = []
card(
    WORK / "s1.png",
    "Docentric Copilot",
    "From business brief\nto validated document",
    "Schema-aware templates for Docentric AX report\npackages — generated offline and deterministically.",
    "GitHub · SergeyGer/Docentric-Copilot",
)
slides.append(
    (
        WORK / "s1.png",
        "Docentric Copilot turns a plain-language brief into a Word document, with evidence for every field it uses. The deterministic baseline needs no cloud call.",
    )
)

render(mapping_html, WORK / "s2.png")
slides.append(
    (
        WORK / "s2.png",
        "Every requirement is mapped to a real schema field. Nine bindings are confirmed, two are schema-valid, and one is left for review: the VAT number exists both on the customer and on the company, and the brief does not say which one it means.",
    )
)

preview_cards = preview_slides()
slides.append(
    (
        preview_cards[0],
        "The preview mirrors the document: company branding, customer block, a product table with SKU, quantity, unit price and amount, and a totals block. Every value comes from the source package, never from a model calculation.",
    )
)
slides.append(
    (
        preview_cards[1],
        "Page two carries the commercial terms, the conditional VAT notice and the payment details, with real page numbers in the footer. Hovering any value reveals the exact field behind it.",
    )
)

slides.append(
    (
        validation_slide(),
        "Compilation is gated: while a mapping still needs review, the DOCX button stays locked. After the reviewer confirms the field, the document compiles and validates structurally, semantically and logically. Docentric AX compatibility remains explicitly not tested.",
    )
)

card(
    WORK / "s6.png",
    "Revision",
    "Change the document\nin plain language",
    "Add a SKU column, move bank details to the footer,\nand make the product table more compact.\n\nA targeted edit produces V2 with a small, reviewable diff —\nV1 is never overwritten and can be restored.",
    "Deterministic DOCX · validation on every run · open source",
)
slides.append(
    (
        WORK / "s6.png",
        "Revision is controlled: the instruction becomes a new immutable version with a structural diff, mapping and validation are re-run, and the previous version can be restored at any time.",
    )
)

card(
    WORK / "s7.png",
    "Open source",
    "Try it yourself",
    "github.com/SergeyGer/Docentric-Copilot\n\nDocs, architecture decisions, an evaluation harness\nand a one-click demo are part of the repository.",
    "Generic DOCX · Docentric AX compatibility not verified",
)
slides.append(
    (
        WORK / "s7.png",
        "The project is open source, with documentation, architecture decisions and a reproducible evaluation harness. Compatibility with Docentric AX is deliberately reported as not tested.",
    )
)

seg_dir = WORK / "seg"
seg_dir.mkdir(exist_ok=True)
segments: list[Path] = []


async def speak(text: str, path: Path) -> None:
    await edge_tts.Communicate(text, "en-US-GuyNeural", rate="+4%").save(str(path))


for index, (image, line) in enumerate(slides, start=1):
    audio = seg_dir / f"a{index}.mp3"
    asyncio.run(speak(line, audio))
    segment = seg_dir / f"seg{index}.mp4"
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-loop",
            "1",
            "-i",
            str(image),
            "-i",
            str(audio),
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
            "-shortest",
            str(segment),
        ],
        check=True,
        capture_output=True,
    )
    segments.append(segment)
    print(f"segment {index}: {segment.stat().st_size // 1024} KB")

listing = seg_dir / "list.txt"
listing.write_text("".join(f"file '{segment}'\n" for segment in segments))
OUT.parent.mkdir(parents=True, exist_ok=True)
subprocess.run(
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
        "-movflags",
        "+faststart",
        str(OUT),
    ],
    check=True,
    capture_output=True,
)
print("video:", OUT, OUT.stat().st_size // 1024, "KB")
