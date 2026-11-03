#!/usr/bin/env python3
"""Render a DOCX through LibreOffice and optionally rasterise PDF pages.

This is **LibreOffice rendering**, not Word fidelity. LibreOffice substitutes
fonts and applies its own pagination, so the result is useful evidence of page
count, table splitting and overflow - never proof that Microsoft Word or
Docentric AX renders the document identically.

The script is intentionally dependency-free: ``soffice`` performs the conversion
and ``pdftoppm`` (poppler-utils) rasterises pages when asked. Both are installed
in the optional ``api-pdf`` Docker target.

Usage::

    python scripts/docx_to_pdf.py quotation.docx -o quotation.pdf
    python scripts/docx_to_pdf.py quotation.docx --png page1.png --dpi 150
    python scripts/docx_to_pdf.py quotation.docx --png-dir pages/ --dpi 150

Exit codes: 0 on success, 2 when LibreOffice or poppler is missing, 1 on any
other conversion failure.
"""

from __future__ import annotations

import argparse
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

LABEL = "LibreOffice rendering (not Word fidelity)"


class RenderError(RuntimeError):
    """A conversion or rasterisation step failed."""


def _require(tool: str, package_hint: str) -> str:
    executable = shutil.which(tool)
    if executable is None:
        raise RenderError(
            f"{tool} was not found on PATH. Install {package_hint}, or run this script inside "
            "the optional api-pdf Docker target: "
            "docker build --target api-pdf -t docentric-copilot-api-pdf ."
        )
    return executable


def _tail(text: str | None, limit: int = 800) -> str:
    cleaned = (text or "").strip()
    return cleaned[-limit:] if len(cleaned) > limit else cleaned


def convert_docx_to_pdf(docx: Path, pdf: Path, *, timeout: float = 180.0) -> Path:
    """Convert ``docx`` with ``soffice --headless --convert-to pdf``."""
    if not docx.is_file():
        raise RenderError(f"DOCX not found: {docx}")
    soffice = _require("soffice", "libreoffice-writer")
    pdf.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="docx-to-pdf-") as temporary:
        workspace = Path(temporary)
        profile = workspace / "profile"
        outdir = workspace / "out"
        profile.mkdir()
        outdir.mkdir()
        command = [
            soffice,
            "--headless",
            "--norestore",
            "--nolockcheck",
            f"-env:UserInstallation={profile.resolve().as_uri()}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(outdir),
            str(docx.resolve()),
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RenderError(f"LibreOffice timed out after {timeout:.0f}s for {docx}") from exc
        produced = outdir / f"{docx.stem}.pdf"
        if completed.returncode != 0 or not produced.is_file():
            detail = _tail(completed.stderr) or _tail(completed.stdout) or "no output from soffice"
            raise RenderError(f"LibreOffice failed to convert {docx}: {detail}")
        shutil.copyfile(produced, pdf)
    return pdf


def rasterise_pdf(
    pdf: Path,
    png: Path,
    *,
    page: int = 1,
    dpi: int = 150,
) -> Path:
    """Rasterise one PDF page with ``pdftoppm``."""
    if not pdf.is_file():
        raise RenderError(f"PDF not found: {pdf}")
    if page < 1:
        raise RenderError("--page must be at least 1")
    if dpi < 36:
        raise RenderError("--dpi must be at least 36")
    pdftoppm = _require("pdftoppm", "poppler-utils")
    png.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pdf-to-png-") as temporary:
        prefix = Path(temporary) / "page"
        command = [
            pdftoppm,
            "-png",
            "-r",
            str(dpi),
            "-f",
            str(page),
            "-l",
            str(page),
            str(pdf),
            str(prefix),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        pages = sorted(Path(temporary).glob("page*.png"))
        if completed.returncode != 0 or not pages:
            detail = _tail(completed.stderr) or _tail(completed.stdout) or "no output from pdftoppm"
            raise RenderError(f"pdftoppm failed to rasterise {pdf} page {page}: {detail}")
        shutil.copyfile(pages[0], png)
    return png


def rasterise_pdf_pages(pdf: Path, directory: Path, *, dpi: int = 150) -> list[Path]:
    """Rasterise every page of ``pdf`` into ``directory``."""
    if not pdf.is_file():
        raise RenderError(f"PDF not found: {pdf}")
    if dpi < 36:
        raise RenderError("--dpi must be at least 36")
    pdftoppm = _require("pdftoppm", "poppler-utils")
    directory.mkdir(parents=True, exist_ok=True)
    prefix = directory / "page"
    command = [pdftoppm, "-png", "-r", str(dpi), str(pdf), str(prefix)]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    pages = sorted(directory.glob("page-*.png"))
    if completed.returncode != 0 or not pages:
        detail = _tail(completed.stderr) or _tail(completed.stdout) or "no output from pdftoppm"
        raise RenderError(f"pdftoppm failed to rasterise {pdf}: {detail}")
    return pages


def _png_size(path: Path) -> tuple[int, int] | None:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    width, height = struct.unpack(">II", header[16:24])
    return width, height


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Render a DOCX through LibreOffice (labelled LibreOffice rendering, "
            "not Word fidelity) and optionally rasterise PDF pages."
        )
    )
    parser.add_argument("docx", type=Path, help="input .docx file")
    parser.add_argument("-o", "--output", type=Path, help="output PDF (default: next to the DOCX)")
    parser.add_argument("--png", type=Path, help="write one page as a PNG")
    parser.add_argument("--page", type=int, default=1, help="page for --png (default: 1)")
    parser.add_argument("--dpi", type=int, default=150, help="rasterisation DPI (default: 150)")
    parser.add_argument("--png-dir", type=Path, help="rasterise every page into this directory")
    parser.add_argument(
        "--timeout", type=float, default=180.0, help="LibreOffice timeout in seconds"
    )
    args = parser.parse_args(argv)

    output = args.output or args.docx.with_suffix(".pdf")
    print(f"{LABEL}: {args.docx} -> {output}")
    try:
        pdf = convert_docx_to_pdf(args.docx, output, timeout=args.timeout)
        if args.png is not None:
            rasterise_pdf(pdf, args.png, page=args.page, dpi=args.dpi)
            size = _png_size(args.png)
            dimensions = f"{size[0]}x{size[1]}" if size else "unknown dimensions"
            print(f"wrote {args.png} ({dimensions}, page {args.page}, {args.dpi} dpi)")
        if args.png_dir is not None:
            pages = rasterise_pdf_pages(pdf, args.png_dir, dpi=args.dpi)
            print(f"wrote {len(pages)} page image(s) to {args.png_dir}")
    except RenderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2 if "not found on PATH" in str(exc) else 1
    print(f"done: {LABEL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
