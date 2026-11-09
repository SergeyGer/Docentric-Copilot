#!/usr/bin/env python3
"""Build the dark evidence charts used by the technical video (Pillow only)."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "media" / "diagrams"
BG = "#0B1220"
PANEL = "#0F172A"
INK = "#E2E8F0"
MUTED = "#94A3B8"
BLUE = "#38BDF8"
GREEN = "#34D399"
AMBER = "#FBBF24"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
BODY = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _canvas(width: int, height: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (width, height), BG)
    return image, ImageDraw.Draw(image)


def _title(draw: ImageDraw.ImageDraw, text: str, subtitle: str) -> None:
    draw.text((100, 70), text, font=_font(BOLD, 54), fill=INK)
    draw.text((100, 140), subtitle, font=_font(BODY, 27), fill=MUTED)


def benchmark_chart() -> None:
    data = json.loads((ROOT / "benchmarks" / "gold_report_v013.json").read_text(encoding="utf-8"))
    aggregate = data["aggregate"]
    rows = [
        ("Precision", aggregate["precision"] * 100, BLUE),
        ("Recall", aggregate["recall"] * 100, BLUE),
        ("F1", aggregate["f1"] * 100, BLUE),
        ("Semantic pass", aggregate["semantic_pass_rate"] * 100, GREEN),
    ]
    image, draw = _canvas(2400, 1200)
    _title(
        draw,
        "Quality is measured, not asserted",
        "Completed templates and semantic evaluation, not an aggregate claim",
    )
    left, top, width = 520, 300, 1600
    for index, (label, value, color) in enumerate(rows):
        y = top + index * 190
        draw.text((100, y + 20), label, font=_font(BOLD, 38), fill=INK)
        draw.rounded_rectangle((left, y, left + width, y + 96), radius=18, fill=PANEL)
        draw.rounded_rectangle((left, y, left + width * value / 100, y + 96), radius=18, fill=color)
        draw.text(
            (left + width * value / 100 + 28, y + 20),
            f"{value:.1f}%",
            font=_font(BOLD, 38),
            fill=INK,
        )
    draw.text(
        (100, 1080),
        "10 technical failures are excluded from semantic scoring and reported separately.",
        font=_font(BODY, 26),
        fill=MUTED,
    )
    image.save(OUT / "chart-benchmark.png")


def reference_chart() -> None:
    data = json.loads(
        (ROOT / "benchmarks" / "reference_evaluation_v013.json").read_text(encoding="utf-8")
    )
    values = [
        ("Parsed", data["corpus"]["documents"], BLUE),
        ("Imported", 16, BLUE),
        ("Compiled", 15, GREEN),
    ]
    image, draw = _canvas(2400, 1100)
    _title(
        draw, "Reference corpus: 17 → 16 → 15", "Every residual failure is classified, not hidden"
    )
    baseline, width, gap = 900, 430, 80
    max_value = 17
    for index, (label, value, color) in enumerate(values):
        x = 260 + index * (width + gap)
        height = int(560 * value / max_value)
        draw.rounded_rectangle((x, baseline - height, x + width, baseline), radius=22, fill=color)
        draw.text(
            (x + width / 2 - 20, baseline - height - 70), str(value), font=_font(BOLD, 54), fill=INK
        )
        draw.text((x + width / 2 - 80, baseline + 28), label, font=_font(BOLD, 34), fill=INK)
    draw.line((200, baseline, 2240, baseline), fill="#1E293B", width=3)
    draw.text(
        (260, 1010),
        "Two pipeline boundaries: an unenclosed nested collection and an unsupported-only document.",
        font=_font(BODY, 26),
        fill=MUTED,
    )
    image.save(OUT / "chart-reference.png")


def table_chart() -> None:
    data = json.loads(
        (ROOT / "benchmarks" / "reference_evaluation_v013.json").read_text(encoding="utf-8")
    )
    classification = data["table_classification"]
    accepted = classification["accepted"]
    unsupported = classification["deliberately_unsupported"]
    reasons = classification["rejected_by_reason"]
    image, draw = _canvas(2400, 1200)
    _title(
        draw,
        "30 observed tables, classified",
        "Accepted inference and deliberate refusals; no silent drops",
    )
    draw.text((100, 310), "30 observed", font=_font(BOLD, 34), fill=INK)
    total_width = 1900
    draw.rounded_rectangle((100, 380, 100 + total_width, 500), radius=24, fill=PANEL)
    green_width = int(total_width * accepted / 30)
    draw.rounded_rectangle((100, 380, 100 + green_width, 500), radius=24, fill=GREEN)
    draw.rounded_rectangle((100 + green_width, 380, 100 + total_width, 500), radius=24, fill=AMBER)
    draw.text((130, 412), f"Accepted {accepted}", font=_font(BOLD, 32), fill="#052E16")
    draw.text(
        (100 + green_width + 30, 412),
        f"Unsupported {unsupported}",
        font=_font(BOLD, 32),
        fill="#451A03",
    )
    draw.text((100, 590), "Unsupported by reason", font=_font(BOLD, 34), fill=INK)
    for index, (key, value) in enumerate(reasons.items()):
        y = 680 + index * 92
        label = key.replace("TABLE_", "").replace("_", " ").title()
        draw.text((100, y), label, font=_font(BODY, 30), fill=MUTED)
        draw.rounded_rectangle((850, y + 4, 850 + value * 95, y + 44), radius=12, fill=AMBER)
        draw.text((870 + value * 95, y), str(value), font=_font(BOLD, 30), fill=INK)
    draw.text(
        (100, 1110),
        "Merged/ragged, ambiguous collection evidence and multiple bound rows are refused explicitly.",
        font=_font(BODY, 25),
        fill=MUTED,
    )
    image.save(OUT / "chart-tables.png")


def docx_package_chart() -> None:
    from zipfile import ZipFile

    docx = (
        ROOT / "docs" / "media" / "v013-wordweb" / "user-word-desktop" / "invoice-work-desktop.docx"
    )
    with ZipFile(docx) as archive:
        all_entries = {item.filename: item.file_size for item in archive.infolist()}
    selected = [
        "[Content_Types].xml",
        "_rels/.rels",
        "word/_rels/document.xml.rels",
        "word/document.xml",
        "word/header1.xml",
        "word/header2.xml",
        "word/footer1.xml",
        "word/footer2.xml",
        "word/media/image1.png",
        "word/styles.xml",
    ]
    entries = [(name, all_entries[name]) for name in selected]
    image, draw = _canvas(2400, 1200)
    _title(draw, "A DOCX is a package, not a blob", "Actual parts from the user-checked invoice")
    panel = (90, 260, 2310, 1090)
    draw.rounded_rectangle(panel, radius=20, fill="#050A14", outline="#1E293B", width=3)
    draw.text((130, 290), "invoice-work-desktop.docx", font=_font(BOLD, 30), fill=INK)
    draw.text((1940, 290), "size", font=_font(BODY, 24), fill=MUTED)
    y = 360
    for name, size in entries:
        highlight = any(
            token in name for token in ("header", "footer", "document.xml", "media/image")
        )
        color = GREEN if highlight else INK
        draw.text((130, y), name, font=_font(BODY, 25), fill=color)
        draw.text((1960, y), f"{size:,}", font=_font(BODY, 24), fill=MUTED)
        if highlight:
            draw.rectangle((116, y - 4, 120, y + 30), fill=GREEN)
        y += 37
    draw.text(
        (100, 1140),
        "Two headers, two footers and one media image are visible in the package.",
        font=_font(BODY, 25),
        fill=MUTED,
    )
    image.save(OUT / "docx-package.png")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    benchmark_chart()
    reference_chart()
    table_chart()
    docx_package_chart()
    print("wrote", sorted(path.name for path in OUT.glob("chart-*.png")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
