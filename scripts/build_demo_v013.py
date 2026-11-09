#!/usr/bin/env python3
"""Build the v0.13 product demo in the demo-v4 visual language.

The video is an *extension* of demo-v4: same hook, schema grounding, typed
brief, live Auto routing, benchmark and closing language, with the v0.13 image
family and reference-table evidence added. It uses the recorded live Anthropic
plan/trace from demo-v4 (not the offline Streamlit mock), and never shows the
maintainer's Word screenshots or the page-two logo detail.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import edge_tts
import imageio_ffmpeg  # type: ignore[import-untyped]
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import scripts.build_demo_video_v4 as v4  # noqa: E402

MEDIA = ROOT / "docs" / "media"
ASSETS = ROOT / "docs" / "assets"
FEATURES = MEDIA / "features"
WORK = ROOT / ".tools" / "video-build" / "v13-product"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
FFPROBE = v4.FFPROBE
FPS = 30
W, H = 2560, 1440
OUT_W, OUT_H = 1920, 1080
VOICE = "en-US-GuyNeural"

BRIEF = v4.BRIEF
LIVE = json.loads((MEDIA / "auto-plan-response.json").read_text(encoding="utf-8"))
LIVE_IR = LIVE["ir"]
LIVE_ROUTING = LIVE["routing"]
LIVE_MAPPINGS = LIVE["mapping"]["mappings"]
BENCH = json.loads((ROOT / "benchmarks" / "gold_report_v013.json").read_text(encoding="utf-8"))
AGG = BENCH["aggregate"]
PROVIDERS = {item["provider"]: item for item in BENCH["providers"]}
TEMPLATE_BLOCKS = len(LIVE_IR["sections"][0]["body"])
CONDITIONAL_BLOCKS = sum(
    1 for block in LIVE_IR["sections"][0]["body"] if block.get("kind") == "conditional"
)
TABLE_BLOCK = next(
    block for block in LIVE_IR["sections"][0]["body"] if block.get("kind") == "table"
)
REQUIREMENTS = len(LIVE_MAPPINGS)
CONFIRMED = sum(1 for item in LIVE_MAPPINGS if item["status"] == "confirmed")
SCHEMA_VALID = sum(1 for item in LIVE_MAPPINGS if item["status"] == "schema_valid")
NEEDS_REVIEW = sum(1 for item in LIVE_MAPPINGS if item["status"] == "needs_review")
RUN_ID = LIVE_ROUTING["run_id"]
EXECUTED_MODEL = LIVE_ROUTING["actual_model"]
EXECUTED_PROVIDER = LIVE_ROUTING["actual_provider"]


@dataclass(frozen=True)
class Scene:
    key: str
    title: str
    narration: str
    frames: tuple[str, ...]
    weights: tuple[float, ...]
    claim: str
    dark: bool = False


def top(label: str = "RECORDED LIVE EVIDENCE") -> str:
    return f"""
    <div class="top">
      <div class="brand">
        <div class="mark">D</div>
        <div><div class="brand-name">Docentric Copilot</div><div class="brand-sub">template engineering workspace</div></div>
      </div>
      <div class="topmeta"><span>{label}</span></div>
    </div>"""


def claim(text: str, dark: bool = False) -> str:
    return f'<div class="claim{" dark" if dark else ""}"><div class="cmark">✓</div><div>{v4.esc(text)}</div></div>'


def shell(body: str) -> str:
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><style>{v4.CSS}</style></head><body>{body}</body></html>"""


def uri(path: Path, crop=None) -> str:
    return v4.data_uri(path, crop)


BRIEF_PANELS = v4.build_panel_frames()


def v4_brief(panel: Path) -> str:
    body = v4.scene_3(panel)
    body = body.replace(v4.top(3), top("RECORDED LIVE ANTHROPIC PLAN"))
    return shell(body)


def v4_auto(variant: str) -> str:
    body = v4.scene_auto(variant)
    body = body.replace(v4.top(4), top("LIVE AUTO ROUTING"))
    return shell(body)


def v4_stage(html: str, index: int, label: str) -> str:
    body = html.replace(v4.top(index), top(label))
    return shell(body)


# --------------------------------------------------------------------------- #
# Scene bodies
# --------------------------------------------------------------------------- #


def opening() -> str:
    preview = uri(ASSETS / "preview-pages.png")
    return shell(f"""
    <div class="stage dark">
      {top()}
      <div class="main" style="flex-direction:row; align-items:center; gap:56px; padding-top:26px;">
        <div style="width:1010px; flex:0 0 1010px;">
          <div class="eyebrow">The business problem</div>
          <h1 class="hero-title">From a business brief<br>to a <span class="accent">reviewable DOCX</span>.</h1>
          <p class="lede" style="max-width:940px; font-size:29px;">A quotation brief in. A finished document out — with the schema, validation and routing evidence attached.</p>
          <div style="display:flex; gap:20px; margin-top:34px;">
            <div style="background:rgba(255,255,255,.07); border:1px solid rgba(255,255,255,.16); border-radius:16px; padding:20px 24px; min-width:330px;">
              <div style="font-size:58px; font-weight:700; line-height:1;">274<span style="font-size:32px;color:#9fb0c8"> / 278</span></div>
              <div style="font-size:20px; color:#c7d2e4; margin-top:8px;">semantic passes<br><span style="color:#9fb0c8;">32 cases × 3 providers × 3 repeats</span></div>
            </div>
            <div style="background:rgba(255,255,255,.07); border:1px solid rgba(255,255,255,.16); border-radius:16px; padding:20px 24px; min-width:300px;">
              <div style="font-size:58px; font-weight:700; line-height:1;">2</div>
              <div style="font-size:20px; color:#c7d2e4; margin-top:8px;">pages<br><span style="color:#9fb0c8;">quotation.docx</span></div>
            </div>
          </div>
        </div>
        <div style="position:relative; width:1250px; flex:1;">
          <div class="browser"><div class="bar"><span class="dots"><i></i><i></i><i></i></span><span class="url">quotation.docx · independent preview</span></div>
            <img src="{preview}" alt="Two-page quotation preview"></div>
          <div style="position:absolute; left:-34px; bottom:-26px; display:flex; align-items:center; gap:14px; background:#ffffff; color:#0f2a54; border-radius:14px; padding:14px 20px; box-shadow:0 18px 42px rgba(0,0,0,.28); border:1px solid #dbe3ee;">
            <div style="width:54px; height:54px; border-radius:12px; background:#dbeafe; color:#1d4ed8; display:flex; align-items:center; justify-content:center; font-size:15px; font-weight:700;">DOCX</div>
            <div><div style="font-size:21px; font-weight:700;">quotation.docx</div><div style="font-size:17px; color:#64748b; margin-top:2px;">40,585 bytes · 2 pages</div></div>
          </div>
          {v4.cursor("1%", "85%")}
        </div>
      </div>
      {claim("A real LLM plan, deterministic validation, and a document a team can review.", dark=True)}
    </div>""")


def schema_scene() -> str:
    schema = uri(ASSETS / "schema-explorer.png")
    stats = v4.SCHEMA_STATS
    sections = v4.SCHEMA_SECTIONS
    return shell(f"""
    <div class="stage">
      {top()}
      <div class="main">
        <div class="eyebrow">Data source + schema</div>
        <h1>Grounded in the customer's own schema.</h1>
        <p class="lede" style="max-width:1420px; font-size:26px;">A DDSP package supplies sample data, parser diagnostics and a normalized field tree. Nothing is invented from the prompt alone.</p>
        <div style="display:flex; gap:52px; align-items:flex-start; margin-top:18px;">
          <div style="width:840px; flex:0 0 840px;">
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px;">
              {"".join(f'<div style="background:#fff;border:1px solid #dbe3ee;border-radius:16px;padding:20px 22px;"><div style="font-size:46px;font-weight:700;color:#0f2a54;line-height:1;">{value}</div><div style="font-size:19px;color:#64748b;margin-top:6px;">{label}</div></div>' for value, label in [(stats["node_count"], "fields in the schema"), (len(sections), "root sections"), (stats["collection_count"], "repeating collection"), (stats["max_depth"], "levels deep")])}
            </div>
            <div style="margin-top:20px; display:flex; gap:10px; flex-wrap:wrap;">
              {"".join(f'<span class="pill">{v4.esc(section)}</span>' for section in sections)}
              <span class="pill green">sample data</span><span class="pill amber">{v4.DIAG_COUNT} parser diagnostics</span>
            </div>
            <div style="margin-top:22px; font-size:18px; color:#64748b; line-height:1.5;">Evidence: <span class="mono">docs/media/demo-session.json</span> · {stats["node_count"]} nodes, {stats["collection_count"]} collection, depth {stats["max_depth"]}.</div>
          </div>
          <div style="flex:1; position:relative;"><div class="shotframe"><img src="{schema}" alt="Schema explorer"></div><div class="shotlabel">Workspace schema explorer · typed and searchable</div>{v4.cursor("46%", "61%")}</div>
        </div>
      </div>
      {claim("The schema is the source of truth for every binding.")}
    </div>""")


def prompt_panel(typed: str) -> str:
    return f"""
    <div style="background:#fff; border:1px solid #d6e0ec; border-radius:18px; padding:26px 30px; width:100%; box-shadow:0 18px 40px rgba(15,23,42,.10);">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
        <div style="font-size:17px; letter-spacing:1.6px; text-transform:uppercase; color:#64748b; font-weight:700;">Workspace prompt panel</div>
        <div class="pill" style="font-size:15px; padding:6px 12px;">Document brief</div>
      </div>
      <div style="font-size:21px; font-weight:700; color:#0f2a54;">Prompt &amp; provider</div>
      <div style="font-size:16px; color:#64748b; margin:4px 0 18px;">Describe the document you need. The planner maps each requirement to schema fields.</div>
      <div style="border:1px solid #cbd5e1; border-radius:12px; padding:16px; min-height:220px; font-size:19px; line-height:1.5; color:#16233a; background:#fbfdff;">{v4.esc(typed)}<span style="color:#2563eb;">|</span></div>
      <div style="display:flex; justify-content:space-between; font-size:15px; color:#64748b; margin-top:8px;"><span>{len(typed)} / 5000</span><span>No provider override</span></div>
    </div>"""


def requirements_panel() -> str:
    rows = "".join(
        f'<tr><td style="padding:7px 10px;border-bottom:1px solid #e2e8f0;font-size:16px;">{v4.esc(item["requirement"])}</td>'
        f'<td style="padding:7px 10px;border-bottom:1px solid #e2e8f0;font-family:monospace;font-size:15px;color:#1e3a8a;">{v4.esc(item["selected_field_path"])}</td>'
        f'<td style="padding:7px 10px;border-bottom:1px solid #e2e8f0;"><span class="pill {"green" if item["status"] == "confirmed" else "amber" if item["status"] == "needs_review" else ""}" style="font-size:13px;padding:3px 8px;">{item["status"].replace("_", " ")}</span></td></tr>'
        for item in LIVE_MAPPINGS
    )
    return f"""
    <div style="background:#fff;border:1px solid #d6e0ec;border-radius:18px;padding:22px 24px;flex:1;box-shadow:0 18px 40px rgba(15,23,42,.08);">
      <div style="display:flex;justify-content:space-between;align-items:center;"><div style="font-size:17px;letter-spacing:1.4px;text-transform:uppercase;color:#64748b;font-weight:700;">Typed requirements</div><span class="pill green">{REQUIREMENTS} requirements</span></div>
      <div style="font-size:34px;font-weight:700;color:#0f2a54;margin:6px 0 12px;">One paragraph → {REQUIREMENTS} fields.</div>
      <table style="width:100%;border-collapse:collapse;"> <thead><tr><th style="text-align:left;padding:7px 10px;font-size:14px;color:#64748b;">Requirement</th><th style="text-align:left;padding:7px 10px;font-size:14px;color:#64748b;">Typed field</th><th style="text-align:left;padding:7px 10px;font-size:14px;color:#64748b;">Status</th></tr></thead><tbody>{rows}</tbody></table>
      <div style="display:flex;gap:10px;margin-top:12px;"><span class="pill green">{CONFIRMED} confirmed</span><span class="pill">{SCHEMA_VALID} schema-valid</span><span class="pill amber">{NEEDS_REVIEW} needs review</span></div>
    </div>"""


def ir_tree() -> str:
    rows = []
    for index, block in enumerate(LIVE_IR["sections"][0]["body"]):
        kind = block.get("kind", "block")
        detail = ""
        if kind == "heading":
            runs = block.get("runs", [])
            detail = "".join(run.get("text", "") for run in runs)
        elif kind == "table":
            detail = f"repeat {block['repeat']['path']} · {len(block['columns'])} columns"
        elif kind == "conditional":
            detail = block.get("condition", {}).get("field", "conditional")
        rows.append(
            f'<div style="display:flex;gap:12px;align-items:center;padding:5px 8px;border-left:3px solid {"#2563eb" if kind in ("table", "conditional") else "#cbd5e1"};margin:3px 0;background:{"#eff6ff" if kind in ("table", "conditional") else "transparent"};border-radius:0 8px 8px 0;">'
            f'<span style="font-size:14px;color:#94a3b8;width:22px;">{index:02d}</span><span class="pill" style="font-size:13px;padding:3px 8px;">{kind}</span>'
            f'<span style="font-family:monospace;font-size:14px;color:#334155;">{v4.esc(detail)[:78]}</span></div>'
        )
    return f"""
    <div style="background:#0b1f3a;border:1px solid #1e3a8a;border-radius:18px;padding:22px 24px;flex:1;color:#e2e8f0;box-shadow:0 18px 40px rgba(15,23,42,.18);">
      <div style="display:flex;justify-content:space-between;align-items:center;"><div style="font-size:17px;letter-spacing:1.4px;text-transform:uppercase;color:#7dd3fc;font-weight:700;">Template IR</div><span class="pill slate">section Quotation</span></div>
      <div style="font-size:34px;font-weight:700;color:#f8fafc;margin:6px 0 4px;">{TEMPLATE_BLOCKS} typed blocks. One repeat. No free-form OOXML.</div>
      <div style="font-size:15px;color:#9fb0c8;margin-bottom:12px;">Recorded live Anthropic run · {v4.esc(EXECUTED_MODEL)} · run {v4.esc(RUN_ID)}</div>
      <div style="max-height:610px;overflow:hidden;">{"".join(rows)}</div>
      <div style="display:flex;gap:10px;margin-top:12px;"><span class="pill green">{CONDITIONAL_BLOCKS} conditions</span><span class="pill">{len(TABLE_BLOCK["columns"])} table columns</span><span class="pill amber">real LLM output</span></div>
    </div>"""


def brief_frame(stage: int) -> str:
    if stage == 0:
        typed = ""
        right = """<div style="background:#fff;border:1px solid #d6e0ec;border-radius:18px;padding:28px;"><div style="font-size:17px;letter-spacing:1.4px;text-transform:uppercase;color:#64748b;font-weight:700;">The only input</div><div style="font-size:88px;font-weight:700;color:#0f2a54;line-height:1;margin-top:8px;">281</div><div style="font-size:20px;color:#64748b;">characters of plain language</div></div><div style="margin-top:16px;border-left:4px solid #2563eb;background:#eff6ff;border-radius:0 14px 14px 0;padding:18px 20px;font-size:22px;line-height:1.45;color:#1e3a8a;"><b>No provider override.</b><br>Auto will choose the model after the brief is typed.</div>"""
    elif stage == 1:
        typed = BRIEF[:210]
        right = f"""<div style="background:#fff;border:1px solid #d6e0ec;border-radius:18px;padding:24px;"><div style="font-size:17px;letter-spacing:1.4px;text-transform:uppercase;color:#64748b;font-weight:700;">Mapped in the live plan</div><div style="font-size:54px;font-weight:700;color:#0f2a54;margin-top:8px;">{REQUIREMENTS} requirements</div><div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;"><span class="pill green">{CONFIRMED} confirmed</span><span class="pill">{SCHEMA_VALID} schema-valid</span><span class="pill amber">{NEEDS_REVIEW} needs review</span></div></div><div style="margin-top:16px;border-left:4px solid #2563eb;background:#eff6ff;border-radius:0 14px 14px 0;padding:18px 20px;font-size:21px;line-height:1.45;color:#1e3a8a;">The brief is becoming a typed plan, not a prompt completion.</div>"""
    else:
        typed = BRIEF
        right = f"""<div style="background:#fff;border:1px solid #d6e0ec;border-radius:18px;padding:24px;"><div style="font-size:17px;letter-spacing:1.4px;text-transform:uppercase;color:#64748b;font-weight:700;">Typed requirements out</div><div style="font-size:40px;font-weight:700;color:#0f2a54;margin-top:8px;">{REQUIREMENTS} fields</div><div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;"><span class="pill green">{CONFIRMED} confirmed</span><span class="pill">{SCHEMA_VALID} schema-valid</span><span class="pill amber">{NEEDS_REVIEW} needs review</span></div></div><div style="margin-top:16px;border-left:4px solid #16a34a;background:#f0fdf4;border-radius:0 14px 14px 0;padding:18px 20px;font-size:21px;line-height:1.45;color:#166534;">The next frame opens the resulting Template IR.</div>"""
    return shell(f"""
    <div class="stage">
      {top("RECORDED LIVE ANTHROPIC PLAN")}
      <div class="main" style="justify-content:center;">
        <div class="eyebrow">The brief</div>
        <h1 class="small">One paragraph in. Typed requirements out.</h1>
        <div style="display:flex;gap:46px;align-items:flex-start;margin-top:18px;"><div style="width:1000px;flex:0 0 1000px;">{prompt_panel(typed)}{v4.cursor("62%", "44%")}</div><div style="flex:1;">{right}</div></div>
      </div>
      {claim("A real LLM maps the brief to typed schema fields; code validates the result.")}
    </div>""")


def template_scene() -> str:
    cards = f"""
    <div style="background:#fff;border:1px solid #d6e0ec;border-radius:18px;padding:22px;margin-bottom:14px;">
      <div style="font-size:17px;letter-spacing:1.5px;text-transform:uppercase;color:#64748b;font-weight:700;">The brief</div>
      <div style="font-size:44px;font-weight:700;color:#0f2a54;margin-top:6px;">281 characters</div>
      <div style="font-size:18px;color:#64748b;">plain language only</div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
      <div style="background:#fff;border:1px solid #d6e0ec;border-radius:16px;padding:18px;"><div style="font-size:42px;font-weight:700;color:#0f2a54;">{REQUIREMENTS}</div><div style="font-size:16px;color:#64748b;">typed requirements</div></div>
      <div style="background:#fff;border:1px solid #d6e0ec;border-radius:16px;padding:18px;"><div style="font-size:42px;font-weight:700;color:#0f2a54;">{TEMPLATE_BLOCKS}</div><div style="font-size:16px;color:#64748b;">IR blocks</div></div>
      <div style="background:#fff;border:1px solid #d6e0ec;border-radius:16px;padding:18px;"><div style="font-size:42px;font-weight:700;color:#0f2a54;">{CONDITIONAL_BLOCKS}</div><div style="font-size:16px;color:#64748b;">conditions</div></div>
      <div style="background:#fff;border:1px solid #d6e0ec;border-radius:16px;padding:18px;"><div style="font-size:42px;font-weight:700;color:#0f2a54;">1</div><div style="font-size:16px;color:#64748b;">repeating table</div></div>
    </div>
    <div style="margin-top:14px;background:#0b1f3a;border-left:4px solid #7dd3fc;border-radius:0 14px 14px 0;padding:16px 20px;color:#e2e8f0;"><div style="font-size:14px;letter-spacing:1.4px;text-transform:uppercase;color:#7dd3fc;font-weight:700;">Recorded live run</div><div style="font-size:17px;margin-top:4px;">{v4.esc(EXECUTED_PROVIDER)} · {v4.esc(EXECUTED_MODEL)}</div><div class="mono" style="font-size:14px;color:#94a3b8;margin-top:2px;">{v4.esc(RUN_ID)}</div></div>
    """
    return shell(f"""
    <div class="stage">
      {top("RECORDED LIVE ANTHROPIC PLAN")}
      <div class="main">
        <div class="eyebrow">The template</div>
        <h1 class="small">The brief becomes a typed template.</h1>
        <div style="display:flex;gap:38px;align-items:flex-start;margin-top:14px;"><div style="width:850px;flex:0 0 850px;">{cards}</div>{ir_tree()}</div>
      </div>
      {claim("One paragraph became a section, typed blocks, a repeating line table and conditional notices.")}
    </div>""")


def auto_selected() -> str:
    selected = uri(ASSETS / "auto-mode-selected.png", crop=(0, 0, 1600, 1000))
    return shell(f"""
    <div class="stage">
      {top("LIVE AUTO ROUTING")}
      <div class="main">
        <div class="eyebrow">Auto routing</div>
        <h1>Let the router choose.</h1>
        <p class="lede" style="max-width:1450px;">No model is chosen by hand. Auto classifies the brief, recommends a provider, and then calls it.</p>
        <div style="display:flex;gap:40px;align-items:flex-start;margin-top:16px;"><div style="flex:1;"><div class="shotframe"><img src="{selected}" alt="Auto selected in the workspace"></div><div class="shotlabel">Routing control set to Auto · the next click runs the real plan</div>{v4.cursor("55%", "48%")}</div><div style="width:620px;flex:0 0 620px;"><div style="background:#fff;border:1px solid #d6e0ec;border-radius:18px;padding:26px;"><div style="font-size:17px;letter-spacing:1.5px;text-transform:uppercase;color:#64748b;font-weight:700;">The decision is evidence</div><div style="font-size:56px;font-weight:700;color:#0f2a54;margin-top:8px;">Auto</div><div style="font-size:20px;color:#64748b;line-height:1.5;margin-top:10px;">Complexity, recommendation, execution and the run id are separate recorded facts. A recommendation is not a promise; execution is.</div></div></div></div>
      </div>
      {claim("The router chooses the model; the trace records what actually ran.")}
    </div>""")


def auto_result() -> str:
    result = uri(ASSETS / "auto-routing-result.png")
    return shell(f"""
    <div class="stage">
      {top("LIVE AUTO ROUTING")}
      <div class="main">
        <div class="eyebrow">Auto routing · real decision</div>
        <h1>Auto picked the model. It ran.</h1>
        <p class="lede" style="max-width:1500px;">The router recommended Anthropic and executed {v4.esc(EXECUTED_MODEL)}. Recommendation, execution, match and fallback are separate recorded facts.</p>
        <div style="display:flex;gap:34px;align-items:flex-start;margin-top:12px;"><div style="flex:1;position:relative;"><div class="shotframe"><img src="{result}" alt="Live Auto routing result"></div><div class="shotlabel">Live capture · {v4.esc(EXECUTED_PROVIDER)} · {v4.esc(EXECUTED_MODEL)} · match true · fallback false · run {v4.esc(RUN_ID)}</div></div></div>
      </div>
      {claim("The recorded live run matched the recommendation and executed the model.")}
    </div>""")


def images_scene() -> str:
    image = uri(FEATURES / "product-images.png", crop=(60, 150, 1040, 900))
    return shell(f"""
    <div class="stage">
      {top("FEATURE EVIDENCE")}
      <div class="main">
        <div class="eyebrow">Image family</div>
        <h1>An image per repeated row.</h1>
        <p class="lede" style="max-width:1550px;">Static assets and schema images share one binding model. Inside a repeat, every line item can carry its own image; fallback and aspect ratio are explicit.</p>
        <div style="display:flex;gap:40px;align-items:flex-start;margin-top:12px;"><div style="flex:1;position:relative;"><div class="shotframe"><img src="{image}" alt="Table with product image per repeated row"></div><div class="shotlabel">Compiled DOCX · 3 repeated rows · {3} embedded images</div></div><div style="width:600px;flex:0 0 600px;"><div style="background:#fff;border:1px solid #d6e0ec;border-radius:18px;padding:24px;"><div style="font-size:17px;letter-spacing:1.5px;text-transform:uppercase;color:#64748b;font-weight:700;">Image binding</div><div style="font-size:48px;font-weight:700;color:#0f2a54;margin-top:8px;">schema → row</div><div style="font-size:20px;color:#64748b;line-height:1.5;margin-top:10px;">The image is a typed field, not a URL in prose. Wrong type or wrong collection scope is rejected before compilation.</div></div></div></div>
      </div>
      {claim("The image family is a typed binding, validated before the DOCX is written.")}
    </div>""")


def tables_scene() -> str:
    source = uri(FEATURES / "reference-table-source.png", crop=(60, 80, 1045, 570))
    output = uri(FEATURES / "reference-table-output.png", crop=(60, 80, 1045, 570))
    return shell(f"""
    <div class="stage">
      {top("FEATURE EVIDENCE")}
      <div class="main">
        <div class="eyebrow">Reference table inference</div>
        <h1>A reference table becomes typed IR.</h1>
        <p class="lede" style="max-width:1600px;">Geometry plus schema evidence: header, repeated row, footer total. Ambiguous and merged tables are refused, not guessed.</p>
        <div style="display:flex;gap:24px;align-items:center;margin-top:14px;"><div class="shotframe" style="flex:1;"><img src="{source}" alt="Reference DOCX table"></div><div style="font-size:44px;color:#2563eb;font-weight:700;">→</div><div class="shotframe" style="flex:1;"><img src="{output}" alt="Compiled table inferred from the reference"></div></div>
        <div style="display:flex;gap:12px;margin-top:18px;"><span class="pill green">header</span><span class="pill green">repeated row</span><span class="pill amber">footer total</span><span class="pill">30 tables classified in the reference evaluation</span></div>
      </div>
      {claim("The table is inferred as a typed repeat with a footer row, then compiled again.")}
    </div>""")


def reference_scene() -> str:
    chart = uri(MEDIA / "diagrams" / "chart-reference.png")
    return shell(f"""
    <div class="stage">
      {top("REFERENCE EVALUATION")}
      <div class="main">
        <div class="eyebrow">Reference evaluation</div>
        <h1>Seventeen documents. Three outcomes.</h1>
        <p class="lede" style="max-width:1550px;">A separate corpus, not the semantic benchmark. Seventeen documents parse, sixteen reach import and fifteen compile; the two residual failures are classified.</p>
        <div style="display:flex;gap:40px;align-items:flex-start;margin-top:16px;"><div style="flex:1;"><div class="shotframe"><img src="{chart}" alt="Reference corpus funnel"></div><div class="shotlabel">17 parsed → 16 imported → 15 compiled · 30 tables classified</div></div><div style="width:650px;flex:0 0 650px;"><div style="background:#fff;border:1px solid #d6e0ec;border-radius:18px;padding:24px;"><div style="font-size:17px;letter-spacing:1.5px;text-transform:uppercase;color:#64748b;font-weight:700;">Table outcomes</div><div style="font-size:52px;font-weight:700;color:#0f2a54;margin-top:8px;">15 / 30</div><div style="font-size:19px;color:#64748b;line-height:1.5;">accepted as typed tables; 15 deliberately unsupported with reason codes; 0 defects, 0 unclassified.</div><div style="display:flex;gap:8px;margin-top:14px;flex-wrap:wrap;"><span class="pill green">15 accepted</span><span class="pill amber">15 refused</span><span class="pill">0 silent drops</span></div></div></div></div>
      </div>
      {claim("The reference corpus has its own denominators; nothing is rounded into a semantic pass.")}
    </div>""")


def repair_frames() -> tuple[str, ...]:
    return tuple(
        v4_stage(v4.scene_7(variant), 7, "LAYOUT REPAIR")
        for variant in ("before", "compare", "after")
    )


def version_frames() -> tuple[str, ...]:
    full = v4_stage(v4.scene_8(), 8, "VERSION HISTORY")
    image = uri(ASSETS / "revision-v1-v2.png", crop=(215, 25, 1385, 895))
    chain = shell(f"""
    <div class="stage">
      {top("VERSION HISTORY")}
      <div class="main">
        <div class="eyebrow">Revision + rollback</div>
        <h1>Every edit is a version.</h1>
        <p class="lede" style="max-width:1600px;">V1 is the original. A revision creates V2 with a structural diff. Either version can be restored into the workspace; the history is not an afterthought.</p>
        <div style="display:flex;gap:28px;align-items:flex-start;margin-top:14px;"><div class="shotframe" style="flex:1;"><img src="{image}" alt="Compare V1 and V2 with diff and restore"></div><div style="width:620px;flex:0 0 620px;"><div style="background:#fff;border:1px solid #d6e0ec;border-radius:18px;padding:24px;"><div style="font-size:17px;letter-spacing:1.5px;text-transform:uppercase;color:#64748b;font-weight:700;">Version chain</div><div style="display:flex;gap:12px;align-items:center;margin-top:18px;"><span class="pill">V1 original</span><span style="font-size:28px;color:#2563eb;">→</span><span class="pill green">V2 revision</span></div><div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:18px;"><div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:14px;"><div style="font-size:34px;font-weight:700;color:#0f2a54;">{v4.REVISION_CHANGES}</div><div style="font-size:15px;color:#64748b;">changed fields</div></div><div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:14px;"><div style="font-size:34px;font-weight:700;color:#0f2a54;">0</div><div style="font-size:15px;color:#64748b;">added / removed</div></div></div><div style="margin-top:16px;border-left:4px solid #16a34a;background:#f0fdf4;border-radius:0 12px 12px 0;padding:14px 18px;font-size:20px;line-height:1.4;color:#166534;"><b>Restore version</b><br>loads either V1 or V2 back into the workspace.</div></div></div></div>
      </div>
      {claim("The version history, diff and rollback are part of the deliverable.")}
    </div>""")
    return (full, chain)


def benchmark_scene() -> str:
    def row(provider: str) -> str:
        item = PROVIDERS[provider]
        metric = item["metrics"]
        return f'<tr><td style="padding:12px 10px;border-bottom:1px solid #dbe3ee;font-size:20px;font-weight:700;color:#0f2a54;">{provider}<div style="font-size:14px;color:#64748b;font-weight:400;">{v4.esc(item["model"])}</div></td><td style="padding:12px 10px;border-bottom:1px solid #dbe3ee;font-size:24px;font-weight:700;color:#0f2a54;">{metric["semantic_passes"]}/{metric["runs"]}</td><td style="padding:12px 10px;border-bottom:1px solid #dbe3ee;font-size:24px;font-weight:700;color:#0f2a54;">{metric["precision"] * 100:.1f}%</td><td style="padding:12px 10px;border-bottom:1px solid #dbe3ee;font-size:24px;font-weight:700;color:#0f2a54;">{metric["latency_p50_ms"] / 1000:.1f}s</td><td style="padding:12px 10px;border-bottom:1px solid #dbe3ee;font-size:18px;color:{"#b45309" if item["cost"]["status"] != "verified" else "#0f2a54"};">{item["cost"]["status"]}</td></tr>'

    return shell(f"""
    <div class="stage">
      {top("BENCHMARK · ACTUAL DATA")}
      <div class="main">
        <div class="eyebrow">Multi-LLM benchmark</div>
        <h1>One case set. Three providers. Three repeats.</h1>
        <p class="lede" style="max-width:1600px;">Every run is recorded; technical failures are excluded from semantic scoring but never hidden. The numbers come from the committed report.</p>
        <div style="display:flex;gap:18px;margin-top:18px;"><div style="background:#fff;border:1px solid #d6e0ec;border-radius:16px;padding:18px 24px;"><div style="font-size:52px;font-weight:700;color:#0f2a54;">{AGG["semantic_passes"]}<span style="font-size:28px;color:#64748b;"> / {AGG["semantic_denominator"]}</span></div><div style="font-size:18px;color:#64748b;">semantic passes</div></div><div style="background:#fff;border:1px solid #d6e0ec;border-radius:16px;padding:18px 24px;"><div style="font-size:52px;font-weight:700;color:#0f2a54;">{AGG["precision"] * 100:.1f}%</div><div style="font-size:18px;color:#64748b;">precision</div></div><div style="background:#fff;border:1px solid #d6e0ec;border-radius:16px;padding:18px 24px;"><div style="font-size:52px;font-weight:700;color:#b45309;">{AGG["failed_runs"]}</div><div style="font-size:18px;color:#64748b;">technical failures</div></div></div>
        <div style="background:#fff;border:1px solid #d6e0ec;border-radius:18px;padding:8px 20px;margin-top:20px;"><table style="width:100%;border-collapse:collapse;"><thead><tr><th style="text-align:left;padding:10px;font-size:14px;color:#64748b;">Provider</th><th style="text-align:left;padding:10px;font-size:14px;color:#64748b;">Semantic</th><th style="text-align:left;padding:10px;font-size:14px;color:#64748b;">Precision</th><th style="text-align:left;padding:10px;font-size:14px;color:#64748b;">p50</th><th style="text-align:left;padding:10px;font-size:14px;color:#64748b;">Cost</th></tr></thead><tbody>{row("openai")}{row("anthropic")}{row("gemini")}</tbody></table></div>
      </div>
      {claim("A technical failure is not a semantic pass; the report keeps both visible.")}
    </div>""")


def artifact_scene() -> str:
    preview = uri(ASSETS / "preview-pages.png")
    render = uri(ASSETS / "quality-before-libreoffice.png", crop=(60, 120, 1180, 1640))
    return shell(f"""
    <div class="stage">
      {top("RECORDED ARTIFACT")}
      <div class="main">
        <div class="eyebrow">The artifact</div>
        <h1>Download. Open. Check.</h1>
        <p class="lede" style="max-width:1560px;">The preview and the LibreOffice render are independent views of the same document. Each is labelled for what it proves; neither is a Word fidelity claim.</p>
        <div style="display:flex;gap:30px;align-items:flex-start;margin-top:14px;"><div style="flex:1;"><div class="shotframe"><img src="{preview}" alt="Independent two-page preview"></div><div class="shotlabel">Independent preview · content and bindings</div></div><div style="width:690px;flex:0 0 690px;"><div class="shotframe"><img src="{render}" alt="LibreOffice page render"></div><div class="shotlabel">LibreOffice render · independent page output</div></div></div>
      </div>
      {claim("The document is a real DOCX; the evidence says exactly what each render proves.")}
    </div>""")


def closing() -> str:
    return shell(f"""
    <div class="stage dark">
      {top("OPEN SOURCE · APACHE 2.0")}
      <div class="main" style="justify-content:center; align-items:flex-start; padding-bottom:20px;">
        <div class="eyebrow">Open source · Apache 2.0</div>
        <h1 style="font-size:96px; line-height:1.02; letter-spacing:-3px;">Open source.<br>Evidence first.</h1>
        <div style="margin-top:26px; font-size:48px; font-weight:600; color:#7dd3fc; letter-spacing:-0.6px;">github.com/SergeyGer/Docentric-Copilot</div>
        <div style="display:flex; gap:14px; margin-top:28px; flex-wrap:wrap;"><span class="pill slate">32 cases × 3 repeats × 3 providers</span><span class="pill slate">recorded live Auto run</span><span class="pill slate">images + typed tables</span><span class="pill amber" style="background:rgba(245,158,11,.14); color:#fcd34d;">Docentric AX: not_tested</span></div>
        <div style="margin-top:34px; font-size:38px; font-weight:600; color:#f8fafc;">Docentric AX compatibility: not tested.</div>
        <div style="margin-top:10px; font-size:20px; color:#9fb0c8; max-width:1700px; line-height:1.5;">The video shows recorded LLM evidence, a live Auto decision, a typed template, images, reference tables and a 32-case benchmark. It does not claim Word fidelity or Docentric AX compatibility.</div>
      </div>
      {claim("From a business brief to a checked Word document.", dark=True)}
    </div>""")


SCENES = (
    Scene(
        "opening",
        "Hook",
        "A business brief should become a document a team can review, not a black box. One paragraph in, a reviewable DOCX out, with schema, validation and routing evidence attached. This is not a mock: the next scenes use a recorded live LLM plan and its trace.",
        (opening(),),
        (1.0,),
        "A real LLM plan becomes a reviewed DOCX.",
    ),
    Scene(
        "schema",
        "Schema",
        "Here is a synthetic package with sample data, parser diagnostics and a normalized field tree. The schema is typed, so every field the document can bind has a type and a source. Nothing is invented from the prompt alone.",
        (schema_scene(),),
        (1.0,),
        "The schema bounds every possible field.",
    ),
    Scene(
        "brief",
        "Brief",
        "The brief is the only input: plain language naming the fields, totals, VAT notice and footer. The planner turns each requirement into a typed field. No model is chosen by hand.",
        tuple(v4_brief(panel) for panel in BRIEF_PANELS),
        tuple(1.0 for _ in BRIEF_PANELS),
        "One paragraph becomes typed requirements.",
    ),
    Scene(
        "template",
        "Template",
        "The result is not prose. It is a Template IR: one section, sixteen typed blocks, a repeating line table and conditional notices. The same structure feeds validation, preview and the DOCX compiler.",
        (template_scene(),),
        (1.0,),
        "A typed template, not a completion.",
    ),
    Scene(
        "auto-selected",
        "Auto selected",
        "Auto does the choosing. It classifies the brief, recommends a provider, and sends no manual override. The decision is recorded before the model runs.",
        (v4_auto("selected"),),
        (1.0,),
        "The router chooses from the brief.",
    ),
    Scene(
        "auto-result",
        "Auto result",
        "The live run selected Anthropic and executed Claude Sonnet. Recommendation, execution, match and fallback are separate recorded facts, with a run identifier.",
        (v4_auto("result"),),
        (1.0,),
        "A recommendation is not a promise; execution is.",
    ),
    Scene(
        "images",
        "Images",
        "The image family is typed too. A company logo, a schema image, or one product image per repeated line item use the same binding model, with explicit fallback and aspect ratio.",
        (images_scene(),),
        (1.0,),
        "An image per repeated row.",
    ),
    Scene(
        "tables",
        "Reference tables",
        "Reference tables are read as geometry plus schema evidence: header, repeated row, footer total. Ambiguous and merged tables are refused with diagnostics instead of guessed.",
        (tables_scene(),),
        (1.0,),
        "The reference table becomes typed IR.",
    ),
    Scene(
        "repair",
        "Layout repair",
        "Here is a layout defect: the description column is too narrow, the text wraps past its line budget, and the checker flags a text-fit warning. Optimize layout applies typed changes—rebalanced columns, a wider description and a smaller table font—then reruns the checks. The after render uses fewer lines. The change is reviewable in the diff, not hidden in a binary.",
        repair_frames(),
        (0.22, 0.5, 0.28),
        "A visual defect becomes a typed, reviewable repair.",
    ),
    Scene(
        "versions",
        "Version history",
        "Every revision creates an immutable version. Compare versions names each changed field; restore brings either version back into the workspace. The version history, diff and rollback are part of the deliverable, not an afterthought.",
        version_frames(),
        (0.55, 0.45),
        "V1 and V2 remain reviewable and restorable.",
    ),
    Scene(
        "benchmark",
        "Benchmark",
        "The benchmark runs thirty-two cases across three providers and three repeats. Two hundred seventy-eight runs completed; two hundred seventy-four pass semantically, and ten Gemini technical failures are reported, not counted as passes.",
        (benchmark_scene(),),
        (1.0,),
        "Quality is measured, not asserted.",
    ),
    Scene(
        "artifact",
        "Artifact",
        "Download and open the file. The preview and the LibreOffice render are independent views of the same document, each labelled for what it proves. This is not a Word fidelity claim.",
        (artifact_scene(),),
        (1.0,),
        "A real DOCX with labelled evidence.",
    ),
    Scene(
        "closing",
        "Closing",
        "Docentric Copilot is open source under Apache. The schema, the live decision, the typed template and the evidence are all in the repository. Docentric AX compatibility is not tested.",
        (closing(),),
        (1.0,),
        "Open source. Evidence first.",
        dark=True,
    ),
)


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
    import subprocess

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
    millis = round(seconds * 1000)
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _encode_frames(
    frames: list[Path], durations: list[float], audio: Path, target: Path, total: float
) -> None:
    import subprocess

    concat = WORK / f"{target.stem}.txt"
    lines = []
    for frame, duration in zip(frames, durations, strict=True):
        lines += [f"file '{frame.as_posix()}'", f"duration {duration:.3f}"]
    lines.append(f"file '{frames[-1].as_posix()}'")
    concat.write_text("\n".join(lines) + "\n")
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
            "-i",
            str(audio),
            "-t",
            f"{total:.3f}",
            "-vf",
            f"fps={FPS},scale={OUT_W}:{OUT_H}:flags=lanczos,format=yuv420p",
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


def build() -> dict:
    WORK.mkdir(parents=True, exist_ok=True)
    segments = []
    captions = []
    narration_lines = ["# Product Demo narration", ""]
    offset = 0.0
    for index, scene in enumerate(SCENES):
        audio = WORK / f"{index:02d}-{scene.key}.mp3"
        asyncio.run(_tts(scene.narration, audio))
        duration = _duration(audio)
        frames = []
        for frame_index, html in enumerate(scene.frames):
            path = WORK / f"{index:02d}-{scene.key}-{frame_index}.png"
            v4.render_html(shell(html), path)
            frames.append(path)
        weights = scene.weights
        total_weight = sum(weights)
        durations = [duration * weight / total_weight for weight in weights]
        durations[-1] = duration - sum(durations[:-1])
        segment = WORK / f"{index:02d}-{scene.key}.mp4"
        _encode_frames(frames, durations, audio, segment, duration)
        segments.append(segment)
        sentences = [
            part.strip() for part in re.split(r"(?<=[.!?])\s+", scene.narration) if part.strip()
        ]
        total = sum(len(sentence) for sentence in sentences) or 1
        cursor = 0.0
        for sentence in sentences:
            share = duration * len(sentence) / total
            captions.append((offset + cursor, offset + cursor + share, sentence))
            cursor += share
        narration_lines += [
            f"## {index + 1}. {scene.title} ({duration:.1f}s)",
            "",
            scene.narration,
            "",
        ]
        print(f"  {scene.key}: {duration:.1f}s")
        offset += duration
    concat = WORK / "concat.txt"
    concat.write_text("\n".join(f"file '{segment.as_posix()}'" for segment in segments) + "\n")
    mp4 = MEDIA / "demo-v013.mp4"
    srt = MEDIA / "demo-v013.srt"
    import subprocess

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
    srt_lines = [
        f"{number}\n{_srt_time(start)} --> {_srt_time(end)}\n{text}\n"
        for number, (start, end, text) in enumerate(captions, start=1)
    ]
    srt.write_text("\n".join(srt_lines), encoding="utf-8")
    (MEDIA / "demo-v013-narration.md").write_text("\n".join(narration_lines), encoding="utf-8")
    Image.open(
        segments[0].with_suffix(".png")
        if segments[0].with_suffix(".png").exists()
        else WORK / "00-opening-0.png"
    ).resize((1280, 720), Image.Resampling.LANCZOS).save(MEDIA / "demo-v013-thumb.png")
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
        "schema": "v013-product-video/v1",
        "status": "publish_ready_draft",
        "human_review": False,
        "youtube_published": False,
        "llm_evidence": {
            "provider": EXECUTED_PROVIDER,
            "model": EXECUTED_MODEL,
            "run_id": RUN_ID,
            "match": LIVE_ROUTING["match"],
            "fallback": LIVE_ROUTING["fallback"],
            "source": "docs/media/auto-plan-response.json",
        },
        "content_rules": {
            "spoken_version_numbers": False,
            "on_screen_version_numbers": False,
            "bullet_slides": False,
            "real_llm_evidence": True,
            "no_word_screenshots": True,
        },
        "mp4": str(mp4.relative_to(ROOT)),
        "srt": str(srt.relative_to(ROOT)),
        "narration": str((MEDIA / "demo-v013-narration.md").relative_to(ROOT)),
        "thumbnail": str((MEDIA / "demo-v013-thumb.png").relative_to(ROOT)),
        "duration_seconds": round(offset, 2),
        "sha256": hashlib.sha256(mp4.read_bytes()).hexdigest(),
        "bytes": mp4.stat().st_size,
        "probe": json.loads(probe.stdout),
        "features": [
            "real recorded LLM plan",
            "brief → typed requirements → Template IR",
            "Auto routing",
            "image per repeated row",
            "reference table inference",
            "32-case benchmark",
            "artifact evidence",
        ],
    }


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    data = build()
    (MEDIA / "demo-v013-manifest.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"duration": data["duration_seconds"], "mp4": data["mp4"], "llm": data["llm_evidence"]},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
