#!/usr/bin/env python3
"""Render the Architecture Wiki Mermaid diagrams for the technical video.

The Mermaid source is read directly from ``docs/wiki/Architecture.md``; the
video renderer imports these PNGs, so the video cannot silently drift from the
Wiki. Uses the vendored Mermaid 11.4.2 build and Playwright Chromium.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "docs" / "wiki" / "Architecture.md"
OUT = ROOT / "docs" / "media" / "diagrams"
MERMAID = ROOT / "docs" / "assets" / "vendor" / "mermaid-11.4.2.min.js"
NAMES = (
    "architecture-data-flow",
    "request-lifecycle",
    "template-ir-contract",
    "validation-ladder",
    "planning-path",
    "compilation-path",
    "ir-block-taxonomy",
    "validation-blocking",
    "validation-compatibility",
    "ir-document-structure",
)


def _blocks() -> list[str]:
    text = WIKI.read_text(encoding="utf-8")
    return re.findall(r"```mermaid\n(.*?)```", text, flags=re.DOTALL)


def _html(source: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<style>
  html, body {{ margin: 0; background: #0B1220; }}
  #wrap {{ padding: 48px; width: 2300px; box-sizing: border-box; background: #0B1220; }}
  .mermaid {{ font-family: Inter, Arial, sans-serif; }}
  .mermaid svg {{ max-width: none !important; width: 100% !important; height: auto !important; }}
</style>
<script src="file://{MERMAID.as_posix()}"></script>
</head><body>
<div id="wrap"><pre class="mermaid">{html.escape(source)}</pre></div>
<script>
mermaid.initialize({{
  startOnLoad: true,
  theme: 'base',
  securityLevel: 'loose',
  themeVariables: {{
    darkMode: true,
    background: '#0B1220',
    primaryColor: '#0F172A',
    primaryTextColor: '#E2E8F0',
    primaryBorderColor: '#38BDF8',
    lineColor: '#7DD3FC',
    secondaryColor: '#172554',
    tertiaryColor: '#0B1220',
    fontFamily: 'Inter, Arial, sans-serif',
    fontSize: '22px',
    actorBkg: '#0F172A',
    actorBorder: '#38BDF8',
    actorTextColor: '#E2E8F0',
    signalColor: '#7DD3FC',
    signalTextColor: '#E2E8F0',
    labelBoxBkgColor: '#0B1220',
    labelBoxBorderColor: '#38BDF8',
    labelTextColor: '#E2E8F0',
    noteBkgColor: '#172554',
    noteTextColor: '#E2E8F0',
    noteBorderColor: '#818CF8',
    activationBkgColor: '#1E3A8A',
    activationBorderColor: '#93C5FD',
  }},
  sequence: {{ diagramMarginX: 20, diagramMarginY: 20, actorMargin: 45, width: 190, height: 58, boxMargin: 8, mirrorActors: false, messageAlign: 'center' }},
  flowchart: {{ curve: 'basis', nodeSpacing: 45, rankSpacing: 60, padding: 18, htmlLabels: true }},
}});
</script></body></html>"""


def render() -> list[dict[str, object]]:
    OUT.mkdir(parents=True, exist_ok=True)
    blocks = _blocks()
    if len(blocks) < len(NAMES):
        raise SystemExit(f"expected {len(NAMES)} Mermaid diagrams, found {len(blocks)}")
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for name, source in zip(NAMES, blocks, strict=False):
            page = browser.new_page(viewport={"width": 2400, "height": 1400}, device_scale_factor=2)
            html_path = OUT / f".{name}.html"
            html_path.write_text(_html(source), encoding="utf-8")
            page.goto(html_path.as_uri(), wait_until="load")
            page.wait_for_selector(".mermaid svg", timeout=30000)
            page.wait_for_timeout(1200)
            target = OUT / f"{name}.png"
            page.locator("#wrap").screenshot(path=str(target), omit_background=False)
            page.close()
            html_path.unlink(missing_ok=True)
            results.append(
                {
                    "name": name,
                    "path": str(target.relative_to(ROOT)),
                    "bytes": target.stat().st_size,
                }
            )
        browser.close()
    print(results)
    return results


if __name__ == "__main__":
    render()
