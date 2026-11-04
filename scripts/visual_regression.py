#!/usr/bin/env python3
"""Full-document visual regression through LibreOffice (P1).

The script compiles a template **before** and **after** ``optimize_layout`` to
DOCX, renders every page through ``scripts/docx_to_pdf.py`` inside the optional
``api-pdf`` Docker image, rasterises the pages, and writes a report plus the
page images under ``docs/media/visual/<case>/``.

Checks are deliberately conservative:

* measured from pixels: blank page, ink outside the left/right text box, ink at
  the page edge, page aspect;
* measured from ``pdftotext -bbox-layout``: header/footer text presence and the
  compiler's ``Page X of Y`` footer;
* measured from the IR: ``text_fit`` and the quality report before/after;
* **not checked**: vertical body overflow. The compiler places running headers
  and footers in the top/bottom margin, so pixel ink in those bands cannot be
  attributed to body overflow without Word-level layout data. The check is
  reported as ``not_checked`` with that reason, never as passed.

The report never claims "all passed" while any check is ``not_checked``. The
global status is ``passed|warning|failed`` for the checks that were performed,
and the verification summary states how many checks were not checked.

This is **LibreOffice rendering**, not Microsoft Word fidelity and not a
Docentric AX proof.

Usage::

    python scripts/visual_regression.py --cases benchmarks/visual_cases.json
    python scripts/visual_regression.py --case quotation-40-rows
    python scripts/visual_regression.py --ir .render/template.json \
        --package benchmarks/fixtures/quotation-40-rows.ddsp --case adhoc

The default image is ``docentric-copilot-api-pdf:local``; it is built from the
``api-pdf`` target when missing. Set ``DC_PDF_IMAGE`` to use another tag.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import html
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # pragma: no cover - import bootstrap when run as a script
    sys.path.insert(0, str(ROOT))

from docentric_copilot.config import get_settings  # noqa: E402
from docentric_copilot.ddsp_parser import parse_ddsp  # noqa: E402
from docentric_copilot.docx_compiler import CompileOptions, GenericDocxCompiler  # noqa: E402
from docentric_copilot.docx_compiler.context import SampleContext  # noqa: E402
from docentric_copilot.docx_compiler.formatting import format_value  # noqa: E402
from docentric_copilot.llm import LLMGateway  # noqa: E402
from docentric_copilot.planner import PlanOptions, TemplatePlanner  # noqa: E402
from docentric_copilot.planner.optimize import optimize_layout  # noqa: E402
from docentric_copilot.planner.quality import QualityReport, analyze_quality  # noqa: E402
from docentric_copilot.schema_resolver.paths import Scope  # noqa: E402
from docentric_copilot.template_ir import (  # noqa: E402
    Document,
    FieldBinding,
    Heading,
    ImageBinding,
    Paragraph,
    ir_digest,
    load_document,
)
from docentric_copilot.template_validator import ValidationEngine  # noqa: E402

DEFAULT_CASES = ROOT / "benchmarks" / "visual_cases.json"
DEFAULT_OUTPUT = ROOT / "docs" / "media" / "visual"
DEFAULT_IMAGE = "docentric-copilot-api-pdf:local"
DEFAULT_DPI = 150
TARGET_WIDTH = 1100
PAGE_SIZES_MM = {"A4": (210.0, 297.0), "LETTER": (215.9, 279.4)}
MARGIN_INK_THRESHOLD = 50
MARGIN_OVERFLOW_FAIL_MM = 5.0
EDGE_INK_THRESHOLD = 20
HEADER_INK_THRESHOLD = 20
FOOTER_INK_THRESHOLD = 20
HEADER_BAND_RATIO = 0.18
FOOTER_BAND_RATIO = 0.18
PAGE_NUMBER = re.compile(r"\bPage\s+\d+\s+of\s+\d+\b", re.IGNORECASE)
LABEL = "LibreOffice rendering (not Word fidelity)"


class VisualError(RuntimeError):
    """The visual pipeline could not produce evidence."""


# --------------------------------------------------------------------------- #
# Observations and pure check logic
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class PageObservation:
    page: int
    image: str
    width: int
    height: int
    ink_fraction: float
    ink_variance: float
    blank: bool
    margin_ink_pixels: int
    max_overflow_mm: float
    edge_ink_pixels: int
    header_ink_pixels: int
    footer_ink_pixels: int
    header_text: str
    footer_text: str
    page_number_present: bool
    text_chars: int
    text_bbox_available: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "image": self.image,
            "width": self.width,
            "height": self.height,
            "ink_fraction": round(self.ink_fraction, 6),
            "ink_variance": round(self.ink_variance, 4),
            "blank": self.blank,
            "margin_ink_pixels": self.margin_ink_pixels,
            "max_overflow_mm": round(self.max_overflow_mm, 3),
            "edge_ink_pixels": self.edge_ink_pixels,
            "header_ink_pixels": self.header_ink_pixels,
            "footer_ink_pixels": self.footer_ink_pixels,
            "header_text": self.header_text[:500],
            "footer_text": self.footer_text[:500],
            "page_number_present": self.page_number_present,
            "text_chars": self.text_chars,
            "text_bbox_available": self.text_bbox_available,
        }


def _check(
    identifier: str,
    status: str,
    message: str,
    *,
    critical: bool = False,
    reason: str | None = None,
    **detail: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": identifier,
        "status": status,
        "message": message,
        "critical": critical,
    }
    if reason is not None:
        payload["reason"] = reason
    if detail:
        payload["detail"] = detail
    return payload


def _fragment_present(fragment: str, haystack: str) -> bool:
    return " ".join(fragment.split()).casefold() in " ".join(haystack.split()).casefold()


def evaluate_page_checks(
    before: PageObservation | None,
    after: PageObservation | None,
    *,
    header_expected: bool = False,
    header_fragments: Sequence[str] = (),
    footer_expected: bool = False,
    footer_fragments: Sequence[str] = (),
    page_number_expected: bool = True,
    expected_size_mm: tuple[float, float] = (210.0, 297.0),
) -> dict[str, dict[str, Any]]:
    """Return the deterministic per-page checks for one before/after page."""
    checks: dict[str, dict[str, Any]] = {}
    if after is None:
        reason = "the after document has no page at this position"
        return {
            identifier: _check(identifier, "not_checked", reason, reason=reason)
            for identifier in (
                "blank_page",
                "horizontal_overflow",
                "page_edge_ink",
                "header_present",
                "footer_present",
                "footer_page_number",
                "page_geometry",
                "vertical_overflow",
            )
        }

    previous_blank = bool(before.blank) if before is not None else None
    checks["blank_page"] = _check(
        "blank_page",
        "failed" if after.blank else "passed",
        (
            "the page is blank (pixel variance and ink below the blank threshold)"
            if after.blank
            else "the page contains ink"
        ),
        critical=True,
        before_blank=previous_blank,
        ink_fraction=round(after.ink_fraction, 6),
        ink_variance=round(after.ink_variance, 4),
    )
    if after.max_overflow_mm <= 1.5:
        overflow_status = "passed"
        overflow_message = "no ink outside the left/right text box"
        overflow_critical = False
    elif after.max_overflow_mm <= MARGIN_OVERFLOW_FAIL_MM:
        overflow_status = "warning"
        overflow_message = (
            f"ink extends {after.max_overflow_mm:.1f} mm outside the left/right text box "
            f"(within the {MARGIN_OVERFLOW_FAIL_MM:.0f} mm table-border tolerance)"
        )
        overflow_critical = False
    else:
        overflow_status = "failed"
        overflow_message = (
            f"ink extends {after.max_overflow_mm:.1f} mm outside the left/right text box"
        )
        overflow_critical = True
    checks["horizontal_overflow"] = _check(
        "horizontal_overflow",
        overflow_status,
        overflow_message,
        critical=overflow_critical,
        ink_pixels=after.margin_ink_pixels,
        max_overflow_mm=round(after.max_overflow_mm, 3),
        threshold_mm=MARGIN_OVERFLOW_FAIL_MM,
        method="pixels outside margin_left/margin_right plus 1.5 mm tolerance",
    )
    checks["page_edge_ink"] = _check(
        "page_edge_ink",
        "failed" if after.edge_ink_pixels > EDGE_INK_THRESHOLD else "passed",
        (
            f"{after.edge_ink_pixels} ink pixel(s) within 2 mm of a page edge"
            if after.edge_ink_pixels > EDGE_INK_THRESHOLD
            else "no ink within 2 mm of a page edge"
        ),
        critical=True,
        ink_pixels=after.edge_ink_pixels,
        threshold=EDGE_INK_THRESHOLD,
    )

    if not header_expected:
        checks["header_present"] = _check(
            "header_present",
            "not_checked",
            "the IR has no header blocks on the rendered section",
            reason="no header blocks to verify",
        )
    elif not after.text_bbox_available:
        checks["header_present"] = _check(
            "header_present",
            "not_checked",
            "pdftotext -bbox-layout produced no positioned text",
            reason="text positioning is unavailable in this render",
        )
    elif header_fragments:
        missing = [
            item for item in header_fragments if not _fragment_present(item, after.header_text)
        ]
        checks["header_present"] = _check(
            "header_present",
            "warning" if missing else "passed",
            (
                "header is missing expected text: " + "; ".join(missing[:3])
                if missing
                else "header text found in the top band"
            ),
            expected=list(header_fragments)[:8],
            method="pdftotext -bbox-layout, top 18% band",
        )
    else:
        checks["header_present"] = _check(
            "header_present",
            "passed" if after.header_ink_pixels > HEADER_INK_THRESHOLD else "warning",
            (
                "header ink found in the top band"
                if after.header_ink_pixels > HEADER_INK_THRESHOLD
                else "no header ink found in the top band"
            ),
            ink_pixels=after.header_ink_pixels,
            method="pixel ink in the top 18% band (image-only header)",
        )

    if not footer_expected:
        checks["footer_present"] = _check(
            "footer_present",
            "not_checked",
            "the IR has no custom footer blocks; the compiler page number is checked separately",
            reason="no custom footer blocks to verify",
        )
    elif not after.text_bbox_available:
        checks["footer_present"] = _check(
            "footer_present",
            "not_checked",
            "pdftotext -bbox-layout produced no positioned text",
            reason="text positioning is unavailable in this render",
        )
    elif footer_fragments:
        missing = [
            item for item in footer_fragments if not _fragment_present(item, after.footer_text)
        ]
        checks["footer_present"] = _check(
            "footer_present",
            "warning" if missing else "passed",
            (
                "footer is missing expected text: " + "; ".join(missing[:3])
                if missing
                else "footer text found in the bottom band"
            ),
            expected=list(footer_fragments)[:8],
            method="pdftotext -bbox-layout, bottom 18% band",
        )
    else:
        checks["footer_present"] = _check(
            "footer_present",
            "passed" if after.footer_ink_pixels > FOOTER_INK_THRESHOLD else "warning",
            (
                "footer ink found in the bottom band"
                if after.footer_ink_pixels > FOOTER_INK_THRESHOLD
                else "no footer ink found in the bottom band"
            ),
            ink_pixels=after.footer_ink_pixels,
            method="pixel ink in the bottom 18% band",
        )

    if not page_number_expected:
        checks["footer_page_number"] = _check(
            "footer_page_number", "not_checked", "page numbers are not expected"
        )
    elif not after.text_bbox_available:
        checks["footer_page_number"] = _check(
            "footer_page_number",
            "not_checked",
            "positioned text is unavailable, so the page number cannot be located",
            reason="text positioning is unavailable in this render",
        )
    else:
        checks["footer_page_number"] = _check(
            "footer_page_number",
            "passed" if after.page_number_present else "failed",
            (
                "the compiler page number is present"
                if after.page_number_present
                else "the compiler page number was not found in the footer band"
            ),
            method="pdftotext text, regex 'Page N of M'",
        )

    width_mm, height_mm = expected_size_mm
    expected_ratio = width_mm / height_mm
    actual_ratio = after.width / after.height if after.height else 0.0
    checks["page_geometry"] = _check(
        "page_geometry",
        "passed" if abs(actual_ratio - expected_ratio) <= 0.03 else "warning",
        (
            f"page aspect {actual_ratio:.3f} matches {width_mm:.0f}×{height_mm:.0f} mm"
            if abs(actual_ratio - expected_ratio) <= 0.03
            else f"page aspect {actual_ratio:.3f} differs from {expected_ratio:.3f}"
        ),
        expected_ratio=round(expected_ratio, 4),
        actual_ratio=round(actual_ratio, 4),
    )
    checks["vertical_overflow"] = _check(
        "vertical_overflow",
        "not_checked",
        "vertical body overflow cannot be separated from running header/footer ink",
        reason=(
            "the compiler places headers and footers in the top/bottom margin; distinguishing "
            "body overflow from running content needs Word-level layout data"
        ),
    )
    return checks


def evaluate_document_checks(
    *,
    before_pages: int,
    after_pages: int,
    before_quality: QualityReport,
    after_quality: QualityReport,
) -> dict[str, dict[str, Any]]:
    """Return page-count and IR-level checks for one case."""
    checks: dict[str, dict[str, Any]] = {}
    changed = before_pages != after_pages
    checks["page_count"] = _check(
        "page_count",
        "warning" if changed else "passed",
        (
            f"page count changed from {before_pages} to {after_pages}"
            if changed
            else f"page count stayed at {before_pages}"
        ),
        before=before_pages,
        after=after_pages,
    )
    before_fit = _quality_check(before_quality, "text_fit")
    after_fit = _quality_check(after_quality, "text_fit")
    before_status = str(before_fit.get("status", "not_checked"))
    after_status = str(after_fit.get("status", "not_checked"))
    if after_status == "passed":
        message = (
            "text_fit improved from warning to passed"
            if before_status == "warning"
            else "text_fit passed before and after"
        )
        status = "passed"
    elif after_status == "failed":
        status = "failed"
        message = str(after_fit.get("message", "text_fit failed"))
    else:
        status = "warning"
        message = str(after_fit.get("message", "text_fit warns after optimisation"))
    checks["text_fit"] = _check(
        "text_fit",
        status,
        message,
        before=before_status,
        after=after_status,
        improved=before_status == "warning" and after_status == "passed",
        method="IR quality analysis (deterministic line estimate)",
    )
    return checks


def evaluate_content_checks(
    *,
    before_text: str,
    after_text: str,
    expected_text: Sequence[str] = (),
    forbidden_text: Sequence[str] = (),
    min_pages_before: int | None = None,
    page_count_before: int | None = None,
    page_count_after: int | None = None,
) -> dict[str, dict[str, Any]]:
    """Case-specific deterministic checks declared in visual_cases.json."""
    checks: dict[str, dict[str, Any]] = {}
    if expected_text:
        missing = [item for item in expected_text if not _fragment_present(item, after_text)]
        checks["expected_text"] = _check(
            "expected_text",
            "warning" if missing else "passed",
            (
                "expected text missing after render: " + "; ".join(missing[:3])
                if missing
                else "expected text found in the rendered pages"
            ),
            expected=list(expected_text),
            method="pdftotext -layout, all pages",
        )
    if forbidden_text:
        found = [item for item in forbidden_text if _fragment_present(item, after_text)]
        checks["forbidden_text"] = _check(
            "forbidden_text",
            "warning" if found else "passed",
            (
                "unexpected text found after render: " + "; ".join(found[:3])
                if found
                else "no forbidden text found in the rendered pages"
            ),
            forbidden=list(forbidden_text),
            method="pdftotext -layout, all pages",
        )
    if min_pages_before is not None:
        total_before = page_count_before if page_count_before is not None else 0
        total_after = page_count_after if page_count_after is not None else 0
        checks["min_pages"] = _check(
            "min_pages",
            "passed"
            if total_before >= min_pages_before and total_after >= min_pages_before
            else "warning",
            (
                f"multi-page expectation met ({total_before} before, {total_after} after; "
                f"minimum {min_pages_before})"
                if total_before >= min_pages_before and total_after >= min_pages_before
                else f"expected at least {min_pages_before} pages before and after, got "
                f"{total_before} and {total_after}"
            ),
            min_pages=min_pages_before,
            before=total_before,
            after=total_after,
        )
    return checks


def _quality_check(report: QualityReport, identifier: str) -> dict[str, Any]:
    for check in report.checks:
        if check.id == identifier:
            return {
                "status": check.status.value,
                "message": check.message,
                "path": check.path,
            }
    return {"status": "not_checked", "message": f"{identifier} check not emitted"}


def derive_status(checks: Iterable[Mapping[str, Any]]) -> str:
    """Collapse checks to ``failed|warning|passed``; ``not_checked`` is not a pass."""
    statuses = [str(check.get("status")) for check in checks]
    if "failed" in statuses:
        return "failed"
    if "warning" in statuses:
        return "warning"
    return "passed"


def summarize_cases(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate case reports into the global status and warning/defect counts."""
    warning_counts: Counter[str] = Counter()
    not_checked: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    new_critical: list[dict[str, Any]] = []
    checked = 0
    for case in cases:
        case_id = str(case.get("case_id", ""))
        for page in case.get("pages", []):
            before_checks = page.get("before_checks", {})
            for identifier, check in page.get("checks", {}).items():
                status = str(check.get("status"))
                if status == "not_checked":
                    not_checked.append(
                        {
                            "case_id": case_id,
                            "page": page.get("page"),
                            "check": identifier,
                            "reason": check.get("reason"),
                        }
                    )
                    continue
                checked += 1
                if status == "warning":
                    warning_counts[identifier] += 1
                elif status == "failed":
                    failed.append(
                        {
                            "case_id": case_id,
                            "page": page.get("page"),
                            "check": identifier,
                            "message": check.get("message"),
                        }
                    )
                    previous = str(before_checks.get(identifier, {}).get("status", "not_checked"))
                    if check.get("critical") and previous != "failed":
                        new_critical.append(
                            {
                                "case_id": case_id,
                                "page": page.get("page"),
                                "check": identifier,
                                "message": check.get("message"),
                            }
                        )
        for identifier, check in case.get("ir_checks", {}).items():
            status = str(check.get("status"))
            if status == "not_checked":
                not_checked.append(
                    {
                        "case_id": case_id,
                        "page": None,
                        "check": identifier,
                        "reason": check.get("reason"),
                    }
                )
                continue
            checked += 1
            if status == "warning":
                warning_counts[identifier] += 1
            elif status == "failed":
                failed.append(
                    {
                        "case_id": case_id,
                        "page": None,
                        "check": identifier,
                        "message": check.get("message"),
                    }
                )

    global_status = derive_status(
        [{"status": case.get("status", "failed")} for case in cases]
        + [{"status": "failed" if new_critical else "passed"}]
    )
    total_not_checked = len(not_checked)
    return {
        "global_status": global_status,
        "case_count": len(cases),
        "cases_passed": sum(1 for case in cases if case.get("status") == "passed"),
        "cases_warning": sum(1 for case in cases if case.get("status") == "warning"),
        "cases_failed": sum(1 for case in cases if case.get("status") == "failed"),
        "unresolved_warning_counts": dict(sorted(warning_counts.items())),
        "unresolved_warnings": sum(warning_counts.values()),
        "failed_checks": failed,
        "new_critical_defects": new_critical,
        "not_checked_checks": not_checked,
        "not_checked_count": total_not_checked,
        "checked_checks": checked,
        "all_checks_passed": global_status == "passed" and total_not_checked == 0,
        "verification_summary": (
            f"{global_status} for {checked} check(s); {total_not_checked} check(s) not checked"
        ),
    }


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def _tail(text: str | None, limit: int = 1200) -> str:
    cleaned = (text or "").strip()
    return cleaned[-limit:] if len(cleaned) > limit else cleaned


def _run(
    command: Sequence[str], *, timeout: float, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command),
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise VisualError(f"command not found: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise VisualError(f"command timed out: {command[0]}") from exc


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def ensure_image(image: str, *, timeout: float = 1800.0) -> None:
    """Verify the api-pdf image exists, building it from the Dockerfile if not."""
    if not _docker_available():
        raise VisualError(
            "docker was not found on PATH; the visual pipeline needs the optional api-pdf image"
        )
    inspect = _run(["docker", "image", "inspect", image], timeout=60.0)
    if inspect.returncode == 0:
        return
    print(f"building {image} from the api-pdf Docker target …", file=sys.stderr)
    build = _run(
        ["docker", "build", "--target", "api-pdf", "-t", image, "."],
        timeout=timeout,
        cwd=ROOT,
    )
    if build.returncode != 0:
        raise VisualError(f"docker build failed for {image}: {_tail(build.stderr)}")


def render_docx(
    docx: Path,
    *,
    image: str,
    dpi: int,
    timeout: float,
) -> dict[str, Any]:
    """Render every page through docx_to_pdf.py inside the api-pdf image."""
    pdf = docx.with_suffix(".pdf")
    text = docx.with_suffix(".txt")
    bbox = docx.with_suffix(".html")
    png_dir = docx.parent / f"{docx.stem}-pages"
    png_dir.mkdir(parents=True, exist_ok=True)
    if not docx.is_file():
        raise VisualError(f"DOCX not found: {docx}")
    relative = {
        "docx": docx.relative_to(ROOT).as_posix(),
        "pdf": pdf.relative_to(ROOT).as_posix(),
        "txt": text.relative_to(ROOT).as_posix(),
        "bbox": bbox.relative_to(ROOT).as_posix(),
        "png": png_dir.relative_to(ROOT).as_posix(),
    }
    command = " && ".join(
        [
            "python scripts/docx_to_pdf.py "
            + " ".join(
                [
                    shlex.quote(relative["docx"]),
                    "-o",
                    shlex.quote(relative["pdf"]),
                    "--png-dir",
                    shlex.quote(relative["png"]),
                    "--dpi",
                    str(dpi),
                ]
            ),
            f"pdftotext -layout {shlex.quote(relative['pdf'])} {shlex.quote(relative['txt'])}",
            f"pdftotext -bbox-layout {shlex.quote(relative['pdf'])} {shlex.quote(relative['bbox'])}",
        ]
    )
    user = f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else "0:0"
    completed = _run(
        [
            "docker",
            "run",
            "--rm",
            "--user",
            user,
            "-v",
            f"{ROOT}:/work",
            "-w",
            "/work",
            image,
            "sh",
            "-c",
            command,
        ],
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise VisualError(
            "LibreOffice render failed: "
            + (_tail(completed.stderr) or _tail(completed.stdout) or "unknown error")
        )
    pages = sorted(png_dir.glob("page-*.png"), key=_page_number)
    if not pages:
        raise VisualError("LibreOffice produced no page images")
    return {
        "pdf": pdf,
        "text": text,
        "bbox": bbox,
        "pages": pages,
        "stdout": _tail(completed.stdout, 500),
    }


def _page_number(path: Path) -> int:
    match = re.search(r"page-(\d+)", path.name)
    return int(match.group(1)) if match else 10_000


def _layout_pages(path: Path) -> list[str]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    pages = text.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


def _bbox_pages(path: Path) -> list[dict[str, Any]] | None:
    if not path.is_file():
        return None
    from xml.etree import ElementTree

    try:
        root = ElementTree.parse(path).getroot()
    except (ElementTree.ParseError, OSError):
        return None
    pages: list[dict[str, Any]] = []
    for page in root.iter():
        if not str(page.tag).endswith("page"):
            continue
        try:
            width = float(page.attrib.get("width", "0"))
            height = float(page.attrib.get("height", "0"))
        except ValueError:
            continue
        words: list[dict[str, Any]] = []
        for word in page.iter():
            if not str(word.tag).endswith("word"):
                continue
            text = (word.text or "").strip()
            if not text:
                continue
            try:
                words.append(
                    {
                        "text": text,
                        "ymin": float(word.attrib.get("yMin", "0")),
                        "ymax": float(word.attrib.get("yMax", "0")),
                    }
                )
            except ValueError:
                continue
        header = " ".join(
            item["text"] for item in words if item["ymax"] <= height * HEADER_BAND_RATIO
        )
        footer = " ".join(
            item["text"] for item in words if item["ymin"] >= height * (1 - FOOTER_BAND_RATIO)
        )
        full = " ".join(item["text"] for item in words)
        pages.append(
            {
                "width": width,
                "height": height,
                "header_text": " ".join(header.split()),
                "footer_text": " ".join(footer.split()),
                "page_number_present": bool(PAGE_NUMBER.search(footer) or PAGE_NUMBER.search(full)),
            }
        )
    return pages or None


def _count_ink(mask: Any, box: tuple[int, int, int, int]) -> int:
    if box[2] <= box[0] or box[3] <= box[1]:
        return 0
    return int(mask.crop(box).histogram()[255])


def inspect_png(
    path: Path,
    *,
    page: int,
    image_label: str,
    page_width_mm: float,
    page_height_mm: float,
    margin_left_mm: float = 20.0,
    margin_right_mm: float = 20.0,
    header_text: str = "",
    footer_text: str = "",
    page_number_present: bool = False,
    text_chars: int = 0,
    text_bbox_available: bool = True,
) -> PageObservation:
    """Measure one page image. Pillow is imported lazily so the pure logic is testable."""
    from PIL import Image, ImageStat

    with Image.open(path) as source:
        gray = source.convert("L")
        width, height = gray.size
        mask = gray.point(lambda value: 255 if value < 245 else 0)
        histogram = mask.histogram()
        ink = int(histogram[255])
        total = max(1, width * height)
        variance = float(ImageStat.Stat(gray).var[0])
        px_per_mm_x = width / page_width_mm
        px_per_mm_y = height / page_height_mm
        margin_left_px = margin_left_mm * px_per_mm_x
        margin_right_px = margin_right_mm * px_per_mm_x
        tolerance_px = 1.5 * px_per_mm_x
        right_boundary = width - margin_right_px
        left_box = (0, 0, max(0, int(margin_left_px - tolerance_px)), height)
        right_box = (min(width, int(right_boundary + tolerance_px)), 0, width, height)
        margin_ink = _count_ink(mask, left_box) + _count_ink(mask, right_box)
        left_bbox = mask.crop(left_box).getbbox() if left_box[2] > 0 else None
        right_bbox = mask.crop(right_box).getbbox() if right_box[2] > right_box[0] else None
        left_overflow = (
            (margin_left_px - left_bbox[0]) / px_per_mm_x if left_bbox is not None else 0.0
        )
        right_overflow = (
            (right_box[0] + right_bbox[2] - right_boundary) / px_per_mm_x
            if right_bbox is not None
            else 0.0
        )
        max_overflow = max(0.0, left_overflow, right_overflow)
        edge_x = max(1, int(2.0 * px_per_mm_x))
        edge_y = max(1, int(2.0 * px_per_mm_y))
        edge_ink = (
            _count_ink(mask, (0, 0, width, edge_y))
            + _count_ink(mask, (0, height - edge_y, width, height))
            + _count_ink(mask, (0, 0, edge_x, height))
            + _count_ink(mask, (width - edge_x, 0, width, height))
        )
        header_ink = _count_ink(mask, (0, 0, width, int(height * HEADER_BAND_RATIO)))
        footer_ink = _count_ink(mask, (0, int(height * (1 - FOOTER_BAND_RATIO)), width, height))
        blank = (ink / total) < 0.0002 and variance < 4.0
    return PageObservation(
        page=page,
        image=image_label,
        width=width,
        height=height,
        ink_fraction=ink / total,
        ink_variance=variance,
        blank=blank,
        margin_ink_pixels=margin_ink,
        max_overflow_mm=max_overflow,
        edge_ink_pixels=edge_ink,
        header_ink_pixels=header_ink,
        footer_ink_pixels=footer_ink,
        header_text=header_text,
        footer_text=footer_text,
        page_number_present=page_number_present,
        text_chars=text_chars,
        text_bbox_available=text_bbox_available,
    )


def _save_page_image(source: Path, destination: Path, *, width: int = TARGET_WIDTH) -> str:
    from PIL import Image

    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        rgb = image.convert("RGB")
        if rgb.width > width:
            height = max(1, round(rgb.height * width / rgb.width))
            rgb = rgb.resize((width, height), Image.Resampling.LANCZOS)
        rgb.save(destination, format="PNG", optimize=True)
    return destination.relative_to(destination.parents[1]).as_posix()


def _quantize_png(path: Path, *, colors: int = 32) -> None:
    """Shrink a committed page image after it has been measured.

    A 32-colour palette keeps the 27 golden images under the 3 MB artefact
    budget while leaving text and table shading readable. Measurement happens
    first, on the downscaled RGB image, so palette quantisation cannot hide a
    faint overflow.
    """
    from PIL import Image

    with Image.open(path) as image:
        rgb = image.convert("RGB")
        palette = rgb.convert("P", palette=Image.Palette.ADAPTIVE, colors=colors)
        palette.save(path, format="PNG", optimize=True)


def _page_image_path(directory: Path, page: int) -> Path:
    return directory / f"page-{page}.png"


# --------------------------------------------------------------------------- #
# IR helpers
# --------------------------------------------------------------------------- #
def _page_size(document: Document) -> tuple[float, float]:
    width, height = PAGE_SIZES_MM[document.page.size]
    if document.page.orientation == "landscape":
        width, height = height, width
    return width, height


def _text_fragments(
    blocks: Sequence[Any] | None,
    schema: Any,
    sample: dict[str, Any] | None,
) -> list[str]:
    """Extract non-trivial visible fragments from header/footer blocks."""
    if not blocks:
        return []
    context = SampleContext(sample=sample or {}, schema=schema, scope=Scope())
    fragments: list[str] = []

    def add(value: str) -> None:
        cleaned = " ".join(value.split())
        if len(cleaned) >= 3 and cleaned not in fragments:
            fragments.append(cleaned)

    def visit(items: Sequence[Any]) -> None:
        for block in items:
            if isinstance(block, Paragraph | Heading):
                parts: list[str] = []
                for run in block.runs:
                    if isinstance(run, FieldBinding):
                        try:
                            parts.append(format_value(context.value(run.path), run))
                        except Exception:
                            parts.append("")
                    else:
                        parts.append(getattr(run, "text", ""))
                text = " ".join(part for part in parts if part)
                add(text)
                # A long paragraph (address + VAT) is also useful as its own
                # fragments, so a partially rendered header is caught.
                for piece in re.split(r"\s*[·|]\s*", text):
                    add(piece)
            elif isinstance(block, ImageBinding):
                continue

    visit(blocks)
    return fragments[:12]


def _quality_summary(report: QualityReport) -> dict[str, Any]:
    counts = report.counts()
    return {
        "overall": report.overall.value,
        "counts": counts,
        "checks": {
            check.id: {
                "label": check.label,
                "status": check.status.value,
                "message": check.message,
                "path": check.path,
            }
            for check in report.checks
        },
        "metrics": report.metrics.model_dump(mode="json"),
    }


def _document_source(case: Mapping[str, Any], parsed: Any, planner: TemplatePlanner) -> Document:
    outcome = asyncio.run(
        planner.plan(
            parsed.schema,
            str(case["prompt"]),
            provider="mock",
            options=PlanOptions(max_repair_attempts=0),
        )
    )
    return outcome.document


# --------------------------------------------------------------------------- #
# Case pipeline
# --------------------------------------------------------------------------- #
def _compile(document: Document, schema: Any, sample: dict[str, Any] | None, path: Path) -> None:
    result = GenericDocxCompiler().compile(
        document,
        schema,
        CompileOptions(document_name=path.name),
        sample_data=sample,
    )
    if not result.success:
        raise VisualError(f"compilation failed for {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(result.content)


def _render_and_copy(
    document: Document,
    schema: Any,
    sample: dict[str, Any] | None,
    *,
    docx_path: Path,
    output_dir: Path,
    image: str,
    dpi: int,
    timeout: float,
) -> dict[str, Any]:
    _compile(document, schema, sample, docx_path)
    rendered = render_docx(docx_path, image=image, dpi=dpi, timeout=timeout)
    layout_pages = _layout_pages(rendered["text"])
    bbox_pages = _bbox_pages(rendered["bbox"])
    observations: list[PageObservation] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    width_mm, height_mm = _page_size(document)
    page_settings = document.page
    for index, source in enumerate(rendered["pages"], start=1):
        destination = _page_image_path(output_dir, index)
        label = _save_page_image(source, destination)
        bbox_page = bbox_pages[index - 1] if bbox_pages and index <= len(bbox_pages) else {}
        layout = layout_pages[index - 1] if index <= len(layout_pages) else ""
        observations.append(
            inspect_png(
                destination,
                page=index,
                image_label=label,
                page_width_mm=width_mm,
                page_height_mm=height_mm,
                margin_left_mm=page_settings.margin_left_mm,
                margin_right_mm=page_settings.margin_right_mm,
                header_text=str(bbox_page.get("header_text", "")),
                footer_text=str(bbox_page.get("footer_text", "")),
                page_number_present=bool(bbox_page.get("page_number_present", False)),
                text_chars=len(layout),
                text_bbox_available=bool(bbox_pages),
            )
        )
        _quantize_png(destination)
    return {
        "docx": docx_path,
        "pdf": rendered["pdf"],
        "pages": observations,
        "page_count": len(observations),
        "text": "\n".join(layout_pages),
    }


def build_case(
    case: Mapping[str, Any],
    *,
    output_root: Path,
    image: str,
    dpi: int,
    timeout: float,
    planner: TemplatePlanner,
    validator: ValidationEngine,
    before_ir: Document | None = None,
) -> dict[str, Any]:
    case_id = str(case["case_id"])
    package = ROOT / str(case["package"])
    parsed = parse_ddsp(package.read_bytes(), package.name)
    work = ROOT / ".visual-work" / case_id
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    output_dir = output_root / case_id
    before_images = output_dir / "before"
    after_images = output_dir / "after"
    for directory in (before_images, after_images):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)

    before = before_ir or _document_source(case, parsed, planner)
    before_report = validator.validate(before, parsed.schema, sample_data=parsed.sample_data)
    if not before_report.can_compile:
        raise VisualError(
            "the before document does not pass V1-V3: "
            + ", ".join(
                name for name, status in before_report.statuses().items() if status == "failed"
            )
        )
    optimization = optimize_layout(before, parsed.schema, sample_data=parsed.sample_data)
    after = optimization.document
    after_report = validator.validate(after, parsed.schema, sample_data=parsed.sample_data)
    if not after_report.can_compile:
        raise VisualError("the after document does not pass V1-V3")
    quality_before = analyze_quality(before, parsed.schema, sample_data=parsed.sample_data)
    quality_after = analyze_quality(after, parsed.schema, sample_data=parsed.sample_data)

    rendered_before = _render_and_copy(
        before,
        parsed.schema,
        parsed.sample_data,
        docx_path=work / "before.docx",
        output_dir=before_images,
        image=image,
        dpi=dpi,
        timeout=timeout,
    )
    rendered_after = _render_and_copy(
        after,
        parsed.schema,
        parsed.sample_data,
        docx_path=work / "after.docx",
        output_dir=after_images,
        image=image,
        dpi=dpi,
        timeout=timeout,
    )

    section = before.sections[0]
    header_expected = bool(section.header)
    footer_expected = bool(section.footer)
    header_fragments = _text_fragments(section.header, parsed.schema, parsed.sample_data)
    footer_fragments = _text_fragments(section.footer, parsed.schema, parsed.sample_data)
    width_mm, height_mm = _page_size(before)

    before_by_page = {item.page: item for item in rendered_before["pages"]}
    after_by_page = {item.page: item for item in rendered_after["pages"]}
    max_pages = max(rendered_before["page_count"], rendered_after["page_count"])
    pages: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        before_observation = before_by_page.get(page)
        after_observation = after_by_page.get(page)
        before_checks = evaluate_page_checks(
            None,
            before_observation,
            header_expected=header_expected,
            header_fragments=header_fragments,
            footer_expected=footer_expected,
            footer_fragments=footer_fragments,
            expected_size_mm=(width_mm, height_mm),
        )
        checks = evaluate_page_checks(
            before_observation,
            after_observation,
            header_expected=header_expected,
            header_fragments=header_fragments,
            footer_expected=footer_expected,
            footer_fragments=footer_fragments,
            expected_size_mm=(width_mm, height_mm),
        )
        page_checks = list(checks.values())
        pages.append(
            {
                "page": page,
                "before": before_observation.as_dict() if before_observation else None,
                "after": after_observation.as_dict() if after_observation else None,
                "before_checks": before_checks,
                "checks": checks,
                "status": (
                    derive_status(page_checks) if after_observation is not None else "warning"
                ),
                "status_note": (
                    None
                    if after_observation is not None
                    else "the after document has no page at this position"
                ),
            }
        )

    ir_checks = evaluate_document_checks(
        before_pages=rendered_before["page_count"],
        after_pages=rendered_after["page_count"],
        before_quality=quality_before,
        after_quality=quality_after,
    )
    ir_checks.update(
        evaluate_content_checks(
            before_text=str(rendered_before.get("text", "")),
            after_text=str(rendered_after.get("text", "")),
            expected_text=list(case.get("expected_text", [])),
            forbidden_text=list(case.get("forbidden_text", [])),
            min_pages_before=case.get("min_pages_before"),
            page_count_before=rendered_before["page_count"],
            page_count_after=rendered_after["page_count"],
        )
    )
    case_checks = [check for page in pages for check in page["checks"].values()] + list(
        ir_checks.values()
    )
    status = derive_status(case_checks)
    report: dict[str, Any] = {
        "schema": "visual-regression/v1",
        "case_id": case_id,
        "family": case.get("family"),
        "package": str(case["package"]),
        "prompt_sha256": hashlib.sha256(str(case["prompt"]).encode("utf-8")).hexdigest(),
        "notes": case.get("notes", ""),
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "renderer": {
            "engine": "LibreOffice",
            "label": LABEL,
            "image": image,
            "dpi": dpi,
            "target_width_px": TARGET_WIDTH,
        },
        "status": status,
        "ir": {
            "before_digest": ir_digest(before),
            "after_digest": ir_digest(after),
            "fixes": [fix.model_dump(mode="json") for fix in optimization.fixes],
            "quality_before": _quality_summary(quality_before),
            "quality_after": _quality_summary(quality_after),
        },
        "page_count": {
            "before": rendered_before["page_count"],
            "after": rendered_after["page_count"],
            "changed": rendered_before["page_count"] != rendered_after["page_count"],
        },
        "header_footer": {
            "header_expected": header_expected,
            "footer_expected": footer_expected,
            "header_fragments": header_fragments,
            "footer_fragments": footer_fragments,
            "page_number_expected": True,
        },
        "pages": pages,
        "ir_checks": ir_checks,
        "warnings_by_type": dict(
            sorted(
                Counter(
                    [
                        identifier
                        for page in pages
                        for identifier, check in page["checks"].items()
                        if check["status"] == "warning"
                    ]
                    + [
                        identifier
                        for identifier, check in ir_checks.items()
                        if check["status"] == "warning"
                    ]
                ).items()
            )
        ),
        "not_checked": [
            {
                "page": page["page"],
                "check": identifier,
                "reason": check.get("reason"),
            }
            for page in pages
            for identifier, check in page["checks"].items()
            if check["status"] == "not_checked"
        ]
        + [
            {
                "page": None,
                "check": identifier,
                "reason": check.get("reason"),
            }
            for identifier, check in ir_checks.items()
            if check["status"] == "not_checked"
        ],
        "limitations": [
            LABEL,
            "Not Microsoft Word fidelity; LibreOffice substitutes fonts and paginates independently.",
            "Not a Docentric AX rendering or compatibility proof.",
            "Vertical body overflow is not checked because running headers/footers occupy the margins.",
            "The header/footer band heuristic is deterministic but approximate.",
        ],
    }
    # Reuse the global aggregator for the per-case counts so the semantics stay
    # identical between a single report and the summary.
    local_summary = summarize_cases([report])
    report["summary"] = local_summary
    report["new_critical_defects"] = local_summary["new_critical_defects"]
    report["verification_summary"] = local_summary["verification_summary"]
    report["all_checks_passed"] = local_summary["all_checks_passed"]
    _write_case_reports(output_dir, report)
    return report


def _write_case_reports(output_dir: Path, report: Mapping[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (output_dir / "report.html").write_text(_case_html(report), encoding="utf-8")


# --------------------------------------------------------------------------- #
# HTML
# --------------------------------------------------------------------------- #
def _status_class(status: str) -> str:
    return {"passed": "ok", "warning": "warn", "failed": "bad"}.get(status, "muted")


def _status_badge(status: str) -> str:
    return f'<span class="badge {_status_class(status)}">{html.escape(status)}</span>'


def _check_table(checks: Mapping[str, Mapping[str, Any]]) -> str:
    rows = []
    for identifier, check in checks.items():
        reason = check.get("reason")
        rows.append(
            "<tr>"
            f"<td>{html.escape(identifier)}</td>"
            f"<td>{_status_badge(str(check.get('status')))}</td>"
            f"<td>{html.escape(str(check.get('message', '')))}"
            + (
                f"<br><span class='muted'>Reason: {html.escape(str(reason))}</span>"
                if reason
                else ""
            )
            + "</td></tr>"
        )
    return (
        "<table><thead><tr><th>Check</th><th>Status</th><th>Observation</th></tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody></table>"
    )


def _page_card(page: Mapping[str, Any]) -> str:
    before = page.get("before")
    after = page.get("after")
    before_img = (
        f"<img src='{html.escape(str(before['image']))}' alt='before page {page['page']}'>"
        if before
        else "<p class='muted'>No page at this position.</p>"
    )
    after_img = (
        f"<img src='{html.escape(str(after['image']))}' alt='after page {page['page']}'>"
        if after
        else "<p class='muted'>No page at this position.</p>"
    )
    return f"""
    <section class="page-card">
      <h3>Page {page["page"]} {_status_badge(str(page.get("status", "failed")))}</h3>
      <div class="page-grid">
        <figure><figcaption>Before — {html.escape(LABEL)}</figcaption>{before_img}</figure>
        <figure><figcaption>After — {html.escape(LABEL)}</figcaption>{after_img}</figure>
      </div>
      {_check_table(page.get("checks", {}))}
    </section>
    """


def _case_html(report: Mapping[str, Any]) -> str:
    pages = "".join(_page_card(page) for page in report.get("pages", []))
    fixes = (
        "".join(
            f"<li><code>{html.escape(str(fix.get('id')))}</code> "
            f"{html.escape(str(fix.get('message', '')))} "
            f"({html.escape(str(fix.get('before')))} → {html.escape(str(fix.get('after')))})</li>"
            for fix in report.get("ir", {}).get("fixes", [])
        )
        or "<li>No layout changes were applied.</li>"
    )
    warnings = report.get("warnings_by_type", {})
    warning_text = ", ".join(f"{name}: {count}" for name, count in warnings.items()) or "none"
    not_checked = report.get("not_checked", [])
    not_checked_text = (
        ", ".join(f"{item['check']} (page {item['page']})" for item in not_checked[:12]) or "none"
    )
    quality_before = report.get("ir", {}).get("quality_before", {})
    quality_after = report.get("ir", {}).get("quality_after", {})
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Visual regression · {html.escape(str(report["case_id"]))}</title>
<style>
  body {{ margin: 0; padding: 30px 18px 60px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; color: #172033; background: #f4f6fa; line-height: 1.45; }}
  main {{ max-width: 1180px; margin: 0 auto; }}
  h1 {{ margin: 0 0 4px; font-size: 27px; }}
  h2 {{ margin: 26px 0 10px; font-size: 19px; }}
  h3 {{ margin: 0 0 10px; font-size: 15px; }}
  .muted {{ color: #64748b; font-size: 13px; }}
  .badge {{ display: inline-block; border-radius: 999px; padding: 2px 9px; font-size: 12px; font-weight: 700; }}
  .ok {{ background: #dcfce7; color: #166534; }}
  .warn {{ background: #fef3c7; color: #92400e; }}
  .bad {{ background: #fee2e2; color: #991b1b; }}
  .muted.badge, .badge.muted {{ background: #e2e8f0; color: #475569; }}
  .note {{ background: #fff7ed; border: 1px solid #fed7aa; border-left: 5px solid #ea580c; padding: 12px 16px; border-radius: 8px; margin: 14px 0; }}
  .card, .page-card {{ background: #fff; border: 1px solid #dfe5ef; border-radius: 10px; padding: 16px; margin: 14px 0; }}
  .page-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
  figure {{ margin: 0; }}
  figcaption {{ font-size: 12px; color: #64748b; margin-bottom: 4px; }}
  img {{ width: 100%; height: auto; border: 1px solid #cbd5e1; border-radius: 4px; background: #fff; }}
  table {{ width: 100%; border-collapse: collapse; margin: 10px 0 0; font-size: 13px; }}
  th, td {{ border-bottom: 1px solid #edf1f7; padding: 7px 9px; text-align: left; vertical-align: top; }}
  th {{ background: #eef3fa; font-size: 12px; text-transform: uppercase; letter-spacing: .03em; color: #475569; }}
  code {{ background: #eef2f7; padding: 1px 4px; border-radius: 3px; }}
  footer {{ color: #64748b; font-size: 12px; margin-top: 24px; }}
  @media (max-width: 760px) {{ .page-grid {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<main>
  <h1>Visual regression · {html.escape(str(report["case_id"]))}</h1>
  <p class="muted">{html.escape(str(report.get("family", "")))} · generated {html.escape(str(report["generated_at"]))}</p>
  <p>{_status_badge(str(report["status"]))} <strong>{html.escape(str(report.get("verification_summary", "")))}</strong></p>
  <p class="muted">New critical defects: {len(report.get("new_critical_defects", []))} · not checked: {len(report.get("not_checked", []))}</p>
  <div class="note"><strong>Scope.</strong> {html.escape(LABEL)}. This is not Microsoft Word fidelity and not a Docentric AX proof.
  Checks marked <span class="badge muted">not_checked</span> were not performed; they are not passes. The report never claims “all passed”.</div>

  <div class="card">
    <h2>Summary</h2>
    <p>Page count: <strong>{report["page_count"]["before"]} → {report["page_count"]["after"]}</strong> · IR digest before <code>{html.escape(report["ir"]["before_digest"][:16])}…</code> · after <code>{html.escape(report["ir"]["after_digest"][:16])}…</code></p>
    <p>Layout fixes: {len(report["ir"]["fixes"])} · unresolved warnings: {html.escape(warning_text)} · new critical defects: {len(report.get("new_critical_defects", []))} · not checked: {html.escape(not_checked_text)}</p>
    <p>Quality before: <strong>{html.escape(str(quality_before.get("overall", "n/a")))}</strong> · after: <strong>{html.escape(str(quality_after.get("overall", "n/a")))}</strong></p>
  </div>

  <div class="card">
    <h2>Layout fixes applied before the after render</h2>
    <ul>{fixes}</ul>
  </div>

  <div class="card">
    <h2>IR-level checks</h2>
    {_check_table(report.get("ir_checks", {}))}
  </div>

  <h2>Pages</h2>
  {pages}

  <div class="card">
    <h2>Limitations</h2>
    <ul>{"".join(f"<li>{html.escape(item)}</li>" for item in report.get("limitations", []))}</ul>
  </div>
  <footer>Generated by scripts/visual_regression.py · images are downscaled to {TARGET_WIDTH} px width.</footer>
</main>
</body>
</html>
"""


def _summary_html(summary: Mapping[str, Any]) -> str:
    rows = []
    for case in summary.get("cases", []):
        rows.append(
            "<tr>"
            f"<td><a href='{html.escape(case['case_id'])}/report.html'>{html.escape(case['case_id'])}</a></td>"
            f"<td>{html.escape(str(case.get('family', '')))}</td>"
            f"<td>{_status_badge(str(case.get('status', 'failed')))}</td>"
            f"<td>{case.get('page_count', {}).get('before', '?')} → {case.get('page_count', {}).get('after', '?')}</td>"
            f"<td>{html.escape(str(case.get('verification_summary', '')))}</td>"
            "</tr>"
        )
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Visual regression summary</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; margin: 0; padding: 30px 18px; background: #f4f6fa; color: #172033; }}
  main {{ max-width: 1000px; margin: 0 auto; }}
  h1 {{ margin: 0 0 6px; }}
  .muted {{ color: #64748b; font-size: 13px; }}
  .badge {{ display: inline-block; border-radius: 999px; padding: 2px 9px; font-size: 12px; font-weight: 700; }}
  .ok {{ background: #dcfce7; color: #166534; }} .warn {{ background: #fef3c7; color: #92400e; }} .bad {{ background: #fee2e2; color: #991b1b; }}
  .note {{ background: #fff7ed; border: 1px solid #fed7aa; border-left: 5px solid #ea580c; padding: 12px 16px; border-radius: 8px; margin: 14px 0; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #dfe5ef; border-radius: 8px; overflow: hidden; }}
  th, td {{ padding: 8px 10px; border-bottom: 1px solid #edf1f7; text-align: left; }}
  th {{ background: #eef3fa; font-size: 12px; text-transform: uppercase; color: #475569; }}
  a {{ color: #1d4ed8; }}
</style></head>
<body><main>
  <h1>Visual regression summary</h1>
  <p class="muted">{html.escape(LABEL)} · generated {html.escape(str(summary.get("generated_at", "")))}</p>
  <p>{_status_badge(str(summary.get("global_status", "failed")))} <strong>{html.escape(str(summary.get("verification_summary", "")))}</strong></p>
  <p class="muted">New critical defects: {len(summary.get("new_critical_defects", []))} · unresolved warnings: {sum(summary.get("unresolved_warning_counts", {}).values())} · not checked: {summary.get("not_checked_count", 0)}</p>
  <div class="note"><strong>Not a Word fidelity proof.</strong> Checks marked not_checked are excluded from passes. New critical defects are blank pages, ink outside the left/right text box, or page-edge ink that appeared after optimisation.</div>
  <table><thead><tr><th>Case</th><th>Family</th><th>Status</th><th>Pages</th><th>Verification</th></tr></thead>
  <tbody>{"".join(rows)}</tbody></table>
</main></body></html>
"""


def _summary_payload(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    summary = summarize_cases(cases)
    return {
        "schema": "visual-regression-summary/v1",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "renderer": {"engine": "LibreOffice", "label": LABEL},
        **summary,
        "cases": [
            {
                "case_id": case["case_id"],
                "family": case.get("family"),
                "status": case.get("status"),
                "page_count": case.get("page_count"),
                "verification_summary": case.get("verification_summary"),
                "new_critical_defects": case.get("new_critical_defects", []),
            }
            for case in cases
        ],
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _load_cases(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.ir is not None:
        if args.package is None:
            raise SystemExit("--ir requires --package (schema and sample data)")
        return [
            {
                "case_id": args.case or "adhoc",
                "family": "adhoc_ir",
                "package": str(args.package),
                "prompt": args.prompt or "Ad-hoc IR supplied on the command line.",
                "notes": "IR supplied with --ir; only optimize_layout is applied.",
            }
        ]
    raw = json.loads(args.cases.read_text(encoding="utf-8"))
    if args.case:
        wanted = {item.strip() for item in args.case.split(",") if item.strip()}
        raw = [case for case in raw if case["case_id"] in wanted]
    if not raw:
        raise SystemExit("No visual cases selected")
    return raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--case", default="", help="comma-separated case ids (default: all)")
    parser.add_argument(
        "--ir", type=Path, default=None, help="use this IR instead of the mock planner"
    )
    parser.add_argument("--package", type=Path, default=None, help="fixture for --ir")
    parser.add_argument("--prompt", default=None, help="prompt for an ad-hoc --ir case")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--image", default=os.environ.get("DC_PDF_IMAGE", DEFAULT_IMAGE))
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args(argv)
    if args.dpi < 72:
        parser.error("--dpi must be at least 72")
    cases = _load_cases(args)
    ensure_image(args.image)
    settings = get_settings()
    planner = TemplatePlanner(LLMGateway(settings))
    validator = ValidationEngine(
        max_blocks=settings.limits.max_ir_blocks,
        max_depth=settings.limits.max_ir_depth,
        max_text_length=settings.limits.max_text_length,
    )
    before_ir = None
    if args.ir is not None:
        before_ir = load_document(args.ir.read_text(encoding="utf-8"))
        if len(cases) != 1:
            raise SystemExit("--ir supports exactly one case")
    built: list[dict[str, Any]] = []
    failures = 0
    for case in cases:
        print(f"visual regression: {case['case_id']}", file=sys.stderr)
        try:
            built.append(
                build_case(
                    case,
                    output_root=args.output,
                    image=args.image,
                    dpi=args.dpi,
                    timeout=args.timeout,
                    planner=planner,
                    validator=validator,
                    before_ir=before_ir,
                )
            )
            print(f"  {built[-1]['status']}: {built[-1]['verification_summary']}", file=sys.stderr)
        except Exception as exc:
            failures += 1
            print(f"  FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
            failure_report = {
                "schema": "visual-regression/v1",
                "case_id": case["case_id"],
                "family": case.get("family"),
                "package": str(case.get("package")),
                "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "renderer": {"engine": "LibreOffice", "label": LABEL, "image": args.image},
                "status": "failed",
                "page_count": {"before": None, "after": None, "changed": None},
                "pages": [],
                "ir_checks": {},
                "ir": {"fixes": [], "quality_before": {}, "quality_after": {}},
                "warnings_by_type": {},
                "not_checked": [],
                "error": {"type": type(exc).__name__, "message": str(exc)[:800]},
                "limitations": [LABEL],
                "verification_summary": "failed before any visual check could run",
            }
            output_dir = args.output / str(case["case_id"])
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "report.json").write_text(
                json.dumps(failure_report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            (output_dir / "report.html").write_text(
                f"<!DOCTYPE html><html><body><h1>{html.escape(str(case['case_id']))} failed</h1>"
                f"<p>{html.escape(str(exc))}</p></body></html>",
                encoding="utf-8",
            )
            built.append(failure_report)
    summary = _summary_payload(built)
    if failures:
        summary["global_status"] = "failed"
        summary["verification_summary"] = (
            f"{summary['verification_summary']}; {failures} case(s) failed before checks"
        )
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.output / "summary.html").write_text(_summary_html(summary), encoding="utf-8")
    print(
        f"summary: {summary['global_status']} · {summary['verification_summary']} · "
        f"new critical defects {len(summary['new_critical_defects'])}"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
