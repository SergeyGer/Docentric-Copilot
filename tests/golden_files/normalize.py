"""Normalized projections used for golden-file comparisons.

A DOCX package contains ZIP timestamps, relationship ids and metadata that are
not semantically meaningful. Comparing a normalized projection (as required by
the SRS) is stricter than it looks while staying stable across environments.
"""

from __future__ import annotations

import io
import zipfile
from typing import Any

from docx import Document as DocxDocument


def _paragraphs(paragraphs) -> list[dict[str, Any]]:
    return [
        {
            "style": paragraph.style.name if paragraph.style is not None else None,
            "text": paragraph.text,
            "alignment": str(paragraph.alignment),
        }
        for paragraph in paragraphs
    ]


def normalize_docx(content: bytes) -> dict[str, Any]:
    document = DocxDocument(io.BytesIO(content))
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        media = sorted(name for name in archive.namelist() if name.startswith("word/media/"))
        entries = sorted(archive.namelist())
    section = document.sections[0]
    return {
        "paragraphs": _paragraphs(document.paragraphs),
        "tables": [
            [[cell.text for cell in row.cells] for row in table.rows] for table in document.tables
        ],
        "header": _paragraphs(section.header.paragraphs),
        "footer": _paragraphs(section.footer.paragraphs),
        "media": media,
        "package": {
            "entry_count": len(entries),
            "has_document": "word/document.xml" in entries,
            "has_styles": "word/styles.xml" in entries,
        },
        "page": {
            "width_mm": round(section.page_width.mm, 1),
            "height_mm": round(section.page_height.mm, 1),
            "top_margin_mm": round(section.top_margin.mm, 1),
            "left_margin_mm": round(section.left_margin.mm, 1),
        },
        "properties": {
            "title": document.core_properties.title,
            "subject": document.core_properties.subject,
            "author": document.core_properties.author,
            "keywords": document.core_properties.keywords,
        },
    }
