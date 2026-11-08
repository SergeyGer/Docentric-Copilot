#!/usr/bin/env python3
"""T-01: build the local Invoice evidence kit for a manual Word Web check.

Produces a synthetic multi-page invoice DOCX, a LibreOffice PDF (explicitly not
Word Web), page PNGs and a manifest. It never claims Word Web validation; the
manual checklist in docs/WORD_WEB_VALIDATION_V013.md remains the gate.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from pathlib import Path

from docentric_copilot import IR_VERSION, __version__
from docentric_copilot.app.service import TemplateService
from docentric_copilot.ddsp_parser import parse_ddsp
from docentric_copilot.docx_compiler import CompileOptions
from docentric_copilot.template_ir import Heading, PageBreak, Paragraph, TextRun

ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = ROOT / "services" / "api" / "src" / "docentric_copilot" / "api" / "demo"
OUT = ROOT / "docs" / "media" / "v013-wordweb"
CASES = json.loads((DEMO_DIR / "manifest.json").read_text(encoding="utf-8"))["cases"]


def _git_sha() -> str:
    return (
        subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        or "unknown"
    )


def build() -> dict[str, object]:
    OUT.mkdir(parents=True, exist_ok=True)
    case = next(item for item in CASES if item["id"] == "invoice")
    payload = (DEMO_DIR / case["package"]).read_bytes()
    parsed = parse_ddsp(payload, case["package"])
    service = TemplateService()
    outcome, _report = asyncio.run(service.plan(parsed.schema, case["prompt"], provider="mock"))
    document = outcome.document.model_copy(deep=True)
    document.sections[0].body.extend(
        [
            PageBreak(),
            Heading(level=2, runs=[TextRun(text="Terms and conditions")]),
            Paragraph(
                runs=[
                    TextRun(
                        text=(
                            "Synthetic multi-page fixture for the Word for the web "
                            "spot-check. No customer or private data is included."
                        )
                    )
                ]
            ),
        ]
    )
    compiled = service.compile(
        document,
        parsed.schema,
        sample_data=parsed.sample_data,
        options=CompileOptions(document_name="invoice-first-page.docx"),
    )
    docx_path = OUT / "invoice-first-page.docx"
    docx_path.write_bytes(compiled.content)
    subprocess.run(
        [
            "soffice",
            "--headless",
            "-env:UserInstallation=file:///tmp/dc-wordweb-lo",
            "--convert-to",
            "pdf",
            "--outdir",
            str(OUT),
            str(docx_path),
        ],
        check=True,
        capture_output=True,
    )
    pdf_path = OUT / "invoice-first-page.pdf"
    info = subprocess.run(["pdfinfo", str(pdf_path)], capture_output=True, text=True, check=True)
    pages = next(
        (
            int(line.split(":", 1)[1].strip())
            for line in info.stdout.splitlines()
            if line.startswith("Pages:")
        ),
        0,
    )
    for page in (1, 2):
        if page <= pages:
            subprocess.run(
                [
                    "pdftoppm",
                    "-f",
                    str(page),
                    "-l",
                    str(page),
                    "-png",
                    "-r",
                    "110",
                    str(pdf_path),
                    str(OUT / "libreoffice-page"),
                ],
                check=True,
                capture_output=True,
            )
    return {
        "schema": "wordweb-evidence/v1",
        "status": "local_candidate_only",
        "word_web_performed": False,
        "word_web_pdf": None,
        "word_web_screenshots": [],
        "application_version": __version__,
        "template_ir": IR_VERSION,
        "git_commit": _git_sha(),
        "provider": "mock",
        "execution_mode": "Deterministic Demo",
        "docx": docx_path.name,
        "docx_sha256": hashlib.sha256(compiled.content).hexdigest(),
        "docx_bytes": len(compiled.content),
        "libreoffice_pdf": pdf_path.name,
        "libreoffice_pdf_pages": pages,
        "page_images": sorted(path.name for path in OUT.glob("libreoffice-page-*.png")),
        "note": (
            "The DOCX/PDF/PNGs are synthetic local evidence. Word for the web PDF, "
            "Word Web screenshots and the completed checklist are still required."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    data = build() if args.write else {"dry_run": True}
    if args.write:
        (OUT / "manifest.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
