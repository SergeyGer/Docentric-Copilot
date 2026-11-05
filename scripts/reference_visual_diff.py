#!/usr/bin/env python3
"""Visual Reference Diff through the existing LibreOffice rendering path.

The script renders two DOCX/AXPP references to PDF and PNG with
``scripts/docx_to_pdf.py`` (``soffice`` + ``pdftoppm``, available in the optional
``api-pdf`` image), compares page counts, blank pages, per-page ink/coverage and
shifted regions, and writes ``report.json`` plus ``report.html``.

This is **LibreOffice rendering, not Word fidelity**. A visual difference is not
automatically a defect, and structural/semantic diff statuses are not replaced
by this result. If LibreOffice or poppler is unavailable the status is
``renderer_unavailable`` with a reason — never ``passed`` or ``failed``.

Usage::

    python scripts/reference_visual_diff.py before.docx after.docx --json out/report.json
    python scripts/reference_visual_diff.py before.axpp after.axpp \
        --json out/report.json --output-dir out --dpi 150

Exit codes: 0 when a report was produced (including ``renderer_unavailable``),
1 for invalid input, 2 for a usage error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # pragma: no cover - import bootstrap when run as a script
    sys.path.insert(0, str(ROOT))

from docentric_copilot.errors import CopilotError  # noqa: E402
from docentric_copilot.reference import (  # noqa: E402
    RENDERER_LABEL,
    build_visual_diff,
    visual_diff_json,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare two reference DOCX/AXPP files by LibreOffice-rendered pages "
            "(not Word fidelity; renderer_unavailable is never pass/fail)."
        )
    )
    parser.add_argument("left", type=Path, help="left DOCX, ZIP or AXPP reference")
    parser.add_argument("right", type=Path, help="right DOCX, ZIP or AXPP reference")
    parser.add_argument(
        "--json",
        type=Path,
        help="write the JSON report here (default: <output-dir>/report.json)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="directory for report.json, report.html, PDFs and page images",
    )
    parser.add_argument("--dpi", type=int, default=150, help="rasterisation DPI (default 150)")
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.005,
        help="page difference tolerance 0..1 (default 0.005)",
    )
    args = parser.parse_args(argv)

    json_path: Path = args.json or (args.output_dir or Path("visual-diff")) / "report.json"
    output_dir: Path = args.output_dir or json_path.parent
    print(f"{RENDERER_LABEL}: {args.left} vs {args.right}")
    try:
        report = build_visual_diff(
            args.left,
            args.right,
            output_dir=output_dir,
            dpi=args.dpi,
            tolerance=args.tolerance,
        )
    except CopilotError as exc:
        print(f"error [{exc.code}]: {exc.message}", file=sys.stderr)
        return 1
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(visual_diff_json(report), encoding="utf-8")
    print(f"status: {report.visual_status.value}")
    print(
        f"pages: left {report.left.page_count}, right {report.right.page_count}, "
        f"compared {report.pages_compared}, changed {report.summary.changed_pages}"
    )
    print(f"renderer: {report.renderer_label} ({report.renderer_version or 'unknown version'})")
    if report.reason:
        print(f"reason: {report.reason}")
    print(f"report: {json_path}")
    print("runtime compatibility: not_tested")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
