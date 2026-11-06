#!/usr/bin/env python3
"""Real LibreOffice/Poppler visual-diff gate for v0.12 (V012-07).

This script is the CI evidence, not a mock. It:

* checks that a real ``soffice`` and ``pdftoppm`` are on PATH and that their
  versions match ``benchmarks/visual_renderer_lock.json``;
* generates deterministic synthetic DOCX fixture pairs with ``python-docx``:
  identical, page-break shift, table-width change, image displacement and a
  missing-font substitution case;
* renders each pair through LibreOffice and poppler and compares the pages with
  the existing :func:`build_visual_diff`;
* writes per-case PDFs, page PNGs, ``report.json``/``report.html`` and a
  machine-readable ``summary.json`` (renderer, poppler, font and locale
  versions, flags, tolerance);
* fails when the renderer is unavailable, when versions drift, when identical
  pages differ, or when a positive fixture is not detected. A renderer failure
  is never ``visual_pass``.

The status vocabulary is explicit: ``visual_pass``/``visual_different`` for a
completed comparison, ``visual_not_checked`` when no real renderer was used.
This is LibreOffice rendering, not Microsoft Word fidelity.

Usage::

    python scripts/visual_ci.py --output-dir visual-ci
    python scripts/visual_ci.py --output-dir visual-ci --json
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import zlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # pragma: no cover - import bootstrap when run as a script
    sys.path.insert(0, str(ROOT))

from docentric_copilot.reference import (  # noqa: E402
    VisualStatus,
    build_visual_diff,
    visual_diff_json,
)
from docx import Document  # noqa: E402
from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402
from docx.shared import Mm, Pt  # noqa: E402

LOCK_PATH: Final = ROOT / "benchmarks" / "visual_renderer_lock.json"
SUMMARY_SCHEMA: Final = "visual-ci/v1"
RENDERER_LABEL: Final = "LibreOffice rendering (not Word fidelity)"
DEFAULT_DPI: Final = 150
DEFAULT_TOLERANCE: Final = 0.005
RUNTIME_COMPATIBILITY: Final = "not_tested"
FIXTURE_NAMES: Final = (
    "identical",
    "page_break_shift",
    "table_width_change",
    "image_displacement",
    "missing_font",
)
POSITIVE_FIXTURES: Final = {
    "page_break_shift",
    "table_width_change",
    "image_displacement",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _png_bytes(width: int = 24, height: int = 24) -> bytes:
    """A deterministic black PNG, built without Pillow."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(
            b"IHDR",
            struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0),
        )
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _base_document(
    *,
    page_break_after: int = 3,
    table_width_mm: float = 80.0,
    image_right: bool = False,
    font_name: str = "DejaVu Sans",
) -> bytes:
    """Build one deterministic DOCX with a heading, paragraphs, table and image."""
    document = Document()
    section = document.sections[0]
    section.top_margin = Mm(18)
    section.bottom_margin = Mm(18)
    section.left_margin = Mm(18)
    section.right_margin = Mm(18)

    heading = document.add_heading("Visual diff fixture", level=1)
    for run in heading.runs:
        run.font.name = font_name
        run.font.size = Pt(18)

    for index in range(1, 7):
        paragraph = document.add_paragraph(
            f"Paragraph {index}: the same text is used in both fixture sides so only the "
            "intended layout difference can trigger a page change."
        )
        for run in paragraph.runs:
            run.font.name = font_name
            run.font.size = Pt(10.5)
        if index == page_break_after:
            document.add_page_break()

    table = document.add_table(rows=3, cols=3)
    table.style = "Table Grid"
    table.autofit = False
    table.allow_autofit = False
    for column in table.columns:
        column.width = Mm(table_width_mm / 3.0)
    for row_index, row in enumerate(table.rows):
        for column_index, cell in enumerate(row.cells):
            cell.width = Mm(table_width_mm / 3.0)
            cell.text = (
                f"R{row_index + 1}C{column_index + 1} long cell text for a fixed-width table"
            )
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.font.name = font_name
                    run.font.size = Pt(9)

    picture_paragraph = document.add_paragraph()
    picture_paragraph.alignment = (
        WD_ALIGN_PARAGRAPH.RIGHT if image_right else WD_ALIGN_PARAGRAPH.LEFT
    )
    picture_paragraph.add_run().add_picture(io.BytesIO(_png_bytes()), width=Mm(22))

    footer = section.footer.paragraphs[0]
    footer.text = "Docentric Copilot visual fixture · LibreOffice rendering, not Word fidelity"
    for run in footer.runs:
        run.font.name = "DejaVu Sans"
        run.font.size = Pt(8)

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def build_fixture_pairs(directory: Path) -> dict[str, tuple[Path, Path]]:
    """Write the five fixture pairs and return their paths."""
    directory.mkdir(parents=True, exist_ok=True)
    pairs: dict[str, tuple[Path, Path]] = {}

    identical = directory / "identical.docx"
    identical.write_bytes(_base_document())
    identical_right = directory / "identical-right.docx"
    identical_right.write_bytes(identical.read_bytes())
    pairs["identical"] = (identical, identical_right)

    page_left = directory / "page-break-shift-left.docx"
    page_left.write_bytes(_base_document(page_break_after=3))
    page_right = directory / "page-break-shift-right.docx"
    page_right.write_bytes(_base_document(page_break_after=6))
    pairs["page_break_shift"] = (page_left, page_right)

    table_left = directory / "table-width-left.docx"
    table_left.write_bytes(_base_document(table_width_mm=60.0))
    table_right = directory / "table-width-right.docx"
    table_right.write_bytes(_base_document(table_width_mm=130.0))
    pairs["table_width_change"] = (table_left, table_right)

    image_left = directory / "image-displacement-left.docx"
    image_left.write_bytes(_base_document(image_right=False))
    image_right_path = directory / "image-displacement-right.docx"
    image_right_path.write_bytes(_base_document(image_right=True))
    pairs["image_displacement"] = (image_left, image_right_path)

    font_left = directory / "missing-font-left.docx"
    font_left.write_bytes(_base_document(font_name="DejaVu Sans"))
    font_right = directory / "missing-font-right.docx"
    font_right.write_bytes(_base_document(font_name="DefinitelyMissingFontForVisualCI"))
    pairs["missing_font"] = (font_left, font_right)
    return pairs


def _command_output(command: list[str], *, env: dict[str, str] | None = None) -> str:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (completed.stdout or completed.stderr or "").strip()


def renderer_identity(env: dict[str, str]) -> dict[str, Any]:
    soffice = shutil.which("soffice")
    pdftoppm = shutil.which("pdftoppm")
    fc_match = shutil.which("fc-match")
    return {
        "libreoffice_path": soffice,
        "poppler_path": pdftoppm,
        "libreoffice": _command_output([soffice, "--version"], env=env) if soffice else None,
        "poppler": _command_output([pdftoppm, "-v"], env=env) if pdftoppm else None,
        "font_match": _command_output([fc_match, "DejaVu Sans"], env=env) if fc_match else None,
        "missing_font_match": (
            _command_output([fc_match, "DefinitelyMissingFontForVisualCI"], env=env)
            if fc_match
            else None
        ),
        "locale": env.get("LC_ALL"),
        "flags": {
            "libreoffice": [
                "--headless",
                "--norestore",
                "--nolockcheck",
                "-env:UserInstallation=<temporary profile>",
                "--convert-to",
                "pdf",
            ],
            "poppler": ["-png", "-r", str(DEFAULT_DPI)],
        },
    }


def _load_lock(path: Path = LOCK_PATH) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read renderer lock {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"renderer lock {path} must be a JSON object")
    return value


def _version_errors(identity: dict[str, Any], lock: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    libreoffice = str(identity.get("libreoffice") or "")
    poppler = str(identity.get("poppler") or "")
    font_match = str(identity.get("font_match") or "")
    expected_libreoffice = str(lock.get("libreoffice") or "")
    expected_poppler = str(lock.get("poppler") or "")
    expected_font = str(lock.get("font_family") or "")
    if expected_libreoffice and expected_libreoffice not in libreoffice:
        errors.append(
            f"LibreOffice version drift: expected {expected_libreoffice!r}, got {libreoffice!r}"
        )
    if expected_poppler and expected_poppler not in poppler:
        errors.append(f"Poppler version drift: expected {expected_poppler!r}, got {poppler!r}")
    if expected_font and expected_font.casefold() not in font_match.casefold():
        errors.append(f"font drift: expected {expected_font!r}, fc-match reported {font_match!r}")
    return errors


def _status_name(status: VisualStatus) -> str:
    return {
        VisualStatus.IDENTICAL: "visual_pass",
        VisualStatus.DIFFERENT: "visual_different",
        VisualStatus.RENDERER_UNAVAILABLE: "visual_not_checked",
    }[status]


def run_suite(output_dir: Path, *, tolerance: float = DEFAULT_TOLERANCE) -> dict[str, Any]:
    """Render the fixtures and return the summary. No mock renderer here."""
    output_dir.mkdir(parents=True, exist_ok=True)
    home = output_dir / "home"
    home.mkdir(exist_ok=True)
    env = {
        **os.environ,
        "HOME": str(home),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
    }
    identity = renderer_identity(env)
    lock = _load_lock()
    version_errors = _version_errors(identity, lock)
    fixtures = build_fixture_pairs(output_dir / "fixtures")
    generated_at = datetime.now(tz=UTC).isoformat(timespec="seconds")
    results: list[dict[str, Any]] = []
    failures: list[str] = []
    if not identity["libreoffice_path"] or not identity["poppler_path"]:
        failures.append(
            "real renderer unavailable: soffice and pdftoppm are both required; "
            "no visual pass is claimed"
        )
        summary = _summary(
            output_dir,
            identity,
            generated_at,
            status="visual_not_checked",
            results=[],
            failures=failures,
            tolerance=tolerance,
            version_errors=version_errors,
        )
        _write_summary(output_dir, summary)
        return summary
    if version_errors:
        failures.extend(version_errors)
        summary = _summary(
            output_dir,
            identity,
            generated_at,
            status="failed",
            results=[],
            failures=failures,
            tolerance=tolerance,
            version_errors=version_errors,
        )
        _write_summary(output_dir, summary)
        return summary

    environment = {
        **os.environ,
        "HOME": str(home),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "LC_ALL": env["LC_ALL"],
        "LANG": env["LANG"],
    }
    previous = {key: os.environ.get(key) for key in ("HOME", "XDG_CACHE_HOME", "LC_ALL", "LANG")}
    os.environ.update({key: environment[key] for key in environment})
    try:
        for name in FIXTURE_NAMES:
            left, right = fixtures[name]
            case_dir = output_dir / "fixtures" / name
            case_dir.mkdir(parents=True, exist_ok=True)
            report = build_visual_diff(
                left,
                right,
                output_dir=case_dir,
                dpi=DEFAULT_DPI,
                tolerance=tolerance,
            )
            (case_dir / "report.json").write_text(visual_diff_json(report), encoding="utf-8")
            status = _status_name(report.visual_status)
            passed = True
            if report.visual_status is VisualStatus.RENDERER_UNAVAILABLE:
                passed = False
                failures.append(f"{name}: renderer became unavailable: {report.reason}")
            elif name == "identical":
                passed = report.visual_status is VisualStatus.IDENTICAL
            elif name in POSITIVE_FIXTURES:
                passed = (
                    report.visual_status is VisualStatus.DIFFERENT
                    and report.summary.changed_pages >= 1
                )
            else:
                passed = report.visual_status in {
                    VisualStatus.IDENTICAL,
                    VisualStatus.DIFFERENT,
                }
            if not passed:
                failures.append(
                    f"{name}: expected a detectable visual change, got {status} "
                    f"({report.summary.changed_pages} changed page(s))"
                )
            results.append(
                {
                    "fixture": name,
                    "expected": (
                        "identical"
                        if name == "identical"
                        else "different"
                        if name in POSITIVE_FIXTURES
                        else "recorded"
                    ),
                    "actual": status,
                    "passed": passed,
                    "changed_pages": report.summary.changed_pages,
                    "pages_compared": report.pages_compared,
                    "renderer_version": report.renderer_version,
                    "report": f"fixtures/{name}/report.json",
                    "artifacts": report.artifacts,
                }
            )
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    status = "passed" if not failures else "failed"
    summary = _summary(
        output_dir,
        identity,
        generated_at,
        status=status,
        results=results,
        failures=failures,
        tolerance=tolerance,
        version_errors=[],
    )
    _write_summary(output_dir, summary)
    return summary


def _summary(
    output_dir: Path,
    identity: dict[str, Any],
    generated_at: str,
    *,
    status: str,
    results: list[dict[str, Any]],
    failures: list[str],
    tolerance: float,
    version_errors: list[str],
) -> dict[str, Any]:
    return {
        "schema": SUMMARY_SCHEMA,
        "status": status,
        "visual_status": ("visual_not_checked" if status == "visual_not_checked" else status),
        "generated_at": generated_at,
        "renderer": {
            **identity,
            "label": RENDERER_LABEL,
            "dpi": DEFAULT_DPI,
            "tolerance": tolerance,
            "locked": _load_lock(),
        },
        "version_errors": version_errors,
        "fixtures": results,
        "failures": failures,
        "runtime_compatibility": RUNTIME_COMPATIBILITY,
        "limitations": [
            "LibreOffice rendering is not Microsoft Word fidelity and not a Docentric AX runtime test.",
            "Identical fixture pages must match within the documented pixel tolerance.",
            "Renderer unavailable or version drift is failed/not_checked, never a visual pass.",
            "Visual differences are evidence of change, not automatically defects.",
        ],
        "output_dir": str(output_dir),
    }


def _write_summary(output_dir: Path, summary: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "visual-ci")
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    summary = run_suite(args.output_dir, tolerance=args.tolerance)
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        renderer = summary["renderer"]
        print(
            f"Visual CI: {summary['status']} · "
            f"{renderer.get('libreoffice') or 'LibreOffice unavailable'} · "
            f"{renderer.get('poppler') or 'Poppler unavailable'}"
        )
        for result in summary["fixtures"]:
            print(
                f"  {result['fixture']:<24} {result['actual']:<18} "
                f"changed_pages={result['changed_pages']} passed={result['passed']}"
            )
        for failure in summary["failures"]:
            print(f"  FAIL {failure}", file=sys.stderr)
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
