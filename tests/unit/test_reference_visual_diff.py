"""Visual Reference Diff (#28) with a stubbed renderer.

The tests never invoke LibreOffice: the deterministic pixel comparison and the
renderer-unavailable contract are verified with synthetic PNG pages.
"""

from __future__ import annotations

import binascii
import json
import struct
import subprocess
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path

from docentric_copilot.reference import (
    PageStatus,
    RenderedPage,
    RenderedReference,
    RendererUnavailable,
    VisualStatus,
    build_visual_diff,
    decode_png,
    visual_diff_json,
)

from tests.reference_fixtures import (
    ControlSpec,
    ElementSpec,
    build_axpp,
    build_docx,
    build_project_data,
    project_data_parts,
)


def _png(width: int, height: int, *, dark: tuple[int, int, int, int] | None = None) -> bytes:
    rows = bytearray()
    for y in range(height):
        rows.append(0)  # filter type
        for x in range(width):
            inside = dark is not None and dark[0] <= x < dark[2] and dark[1] <= y < dark[3]
            rows.append(0 if inside else 255)
    raw = bytes(rows)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(
            b"IHDR",
            struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0),
        )
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _docx(*, field: str = "@Number") -> bytes:
    elements = (ElementSpec(1, "Field", "MainData", field),)
    controls = (ControlSpec(alias="Field", tag="Field", sdt_id=1),)
    custom = project_data_parts(build_project_data(elements))
    return build_docx(document_controls=controls, custom_parts=custom)


@dataclass
class StubRenderer:
    pages: list[bytes]
    version: str = "stub-1.0"

    @property
    def name(self) -> str:
        return "libreoffice"

    def render(self, docx: bytes, *, filename: str) -> RenderedReference:
        return RenderedReference(
            pages=[
                RenderedPage(page=index + 1, png=payload)
                for index, payload in enumerate(self.pages)
            ],
            pdf=b"stub-pdf:" + filename.encode("utf-8", "replace"),
            renderer_version=self.version,
        )


@dataclass
class UnavailableRenderer:
    reason: str = "soffice was not found on PATH"

    @property
    def name(self) -> str:
        return "libreoffice"

    def render(self, docx: bytes, *, filename: str) -> RenderedReference:
        raise RendererUnavailable(self.reason)


def _write_inputs(tmp_path: Path, left_field: str = "@Number") -> tuple[Path, Path]:
    left = tmp_path / "Left.docx"
    right = tmp_path / "Right.docx"
    left.write_bytes(_docx(field=left_field))
    right.write_bytes(_docx(field="@Name"))
    return left, right


def test_identical_pages_are_identical_and_artifacts_are_written(tmp_path: Path) -> None:
    left, right = _write_inputs(tmp_path)
    page = _png(120, 160, dark=(10, 10, 40, 20))
    output = tmp_path / "out"
    report = build_visual_diff(
        left,
        right,
        output_dir=output,
        renderer=StubRenderer([page, _png(120, 160)]),
    )

    assert report.visual_status is VisualStatus.IDENTICAL
    assert report.renderer == "libreoffice"
    assert report.renderer_label == "LibreOffice rendering (not Word fidelity)"
    assert report.renderer_available is True
    assert report.runtime_compatibility == "not_tested"
    assert report.pages_compared == 2
    assert report.summary.changed_pages == 0
    assert report.summary.blank_pages_right == 1
    assert all(page.status is PageStatus.IDENTICAL for page in report.pages)
    assert (output / "report.json").is_file()
    assert (output / "report.html").is_file()
    assert (output / "left-pages" / "page-1.png").is_file()
    assert (output / "right.pdf").is_file()
    assert report.artifacts["report_json"] == "report.json"
    assert json.loads(visual_diff_json(report))["report_digest"] == report.report_digest
    html = (output / "report.html").read_text(encoding="utf-8")
    assert "LibreOffice rendering (not Word fidelity)" in html
    assert "not Microsoft Word fidelity" in html
    assert "runtime" in html.lower()


def test_known_visual_change_is_localized_to_its_page(tmp_path: Path) -> None:
    left, right = _write_inputs(tmp_path)
    left_page_1 = _png(120, 160, dark=(10, 10, 40, 20))
    right_page_1 = _png(120, 160, dark=(60, 80, 90, 90))
    unchanged = _png(120, 160, dark=(5, 5, 20, 20))
    report = build_visual_diff(
        left,
        right,
        output_dir=tmp_path / "out2",
        renderer=_PairRenderer(
            left_pages=[left_page_1, unchanged],
            right_pages=[right_page_1, unchanged],
        ),
    )
    assert report.visual_status is VisualStatus.DIFFERENT
    assert report.pages[0].status is PageStatus.DIFFERENT
    assert report.pages[0].changed_fraction > 0
    assert report.pages[1].status is PageStatus.IDENTICAL
    assert report.summary.changed_pages == 1
    assert report.summary.identical_pages == 1
    assert all(page.left is not None and page.right is not None for page in report.pages)
    assert report.pages[0].left.image == "left-pages/page-1.png"


@dataclass
class _PairRenderer:
    left_pages: list[bytes]
    right_pages: list[bytes]

    @property
    def name(self) -> str:
        return "libreoffice"

    def render(self, docx: bytes, *, filename: str) -> RenderedReference:
        pages = self.left_pages if filename.startswith("Left") else self.right_pages
        return RenderedReference(
            pages=[
                RenderedPage(page=index + 1, png=payload) for index, payload in enumerate(pages)
            ],
            renderer_version="stub-1.0",
        )


def test_page_count_change_is_explicit(tmp_path: Path) -> None:
    left, right = _write_inputs(tmp_path)
    report = build_visual_diff(
        left,
        right,
        output_dir=tmp_path / "out",
        renderer=_PairRenderer(
            left_pages=[_png(80, 100), _png(80, 100, dark=(1, 1, 10, 10))],
            right_pages=[_png(80, 100)],
        ),
    )
    assert report.visual_status is VisualStatus.DIFFERENT
    assert [page.status for page in report.pages] == [PageStatus.IDENTICAL, PageStatus.ONLY_LEFT]
    assert report.summary.only_left_pages == 1
    assert report.summary.page_count_delta == -1


def test_renderer_unavailable_is_never_pass_or_fail(tmp_path: Path) -> None:
    left, right = _write_inputs(tmp_path)
    output = tmp_path / "out"
    report = build_visual_diff(
        left,
        right,
        output_dir=output,
        renderer=UnavailableRenderer("soffice was not found on PATH"),
    )
    assert report.visual_status is VisualStatus.RENDERER_UNAVAILABLE
    assert report.visual_status.value not in {"passed", "failed", "identical", "different"}
    assert report.renderer_available is False
    assert "soffice" in (report.reason or "")
    assert report.pages_compared == 0
    assert report.structural_status == "not_compared"
    assert report.semantic_status == "not_compared"
    assert (output / "report.json").is_file()
    html = (output / "report.html").read_text(encoding="utf-8")
    assert "renderer_unavailable" in html
    assert "not a pass or a fail" in html
    payload = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert payload["visual_status"] == "renderer_unavailable"
    assert payload["runtime_compatibility"] == "not_tested"
    assert payload["report_digest"] == report.report_digest


def test_axpp_input_is_reduced_to_its_docx_payload(tmp_path: Path) -> None:
    package = build_axpp(_docx())
    left = tmp_path / "Left.axpp"
    right = tmp_path / "Right.axpp"
    left.write_bytes(package)
    right.write_bytes(package)
    report = build_visual_diff(
        left,
        right,
        output_dir=tmp_path / "out",
        renderer=StubRenderer([_png(60, 80)]),
    )
    assert report.visual_status is VisualStatus.IDENTICAL
    assert report.left.source_name.endswith(".docx")
    assert report.left.document_sha256 == report.right.document_sha256


def test_png_decoder_and_shifted_regions() -> None:
    page = decode_png(_png(60, 80, dark=(10, 10, 30, 30)))
    assert (page.width, page.height) == (60, 80)
    assert page.pixels[15 * 60 + 15] == 0
    assert page.pixels[0] == 255

    from docentric_copilot.reference import detect_shifted_regions

    base = decode_png(_png(120, 160, dark=(20, 20, 60, 60)))
    shifted = decode_png(_png(120, 160, dark=(24, 24, 64, 64)))
    regions = detect_shifted_regions(base, shifted)
    assert regions
    assert all(abs(item.offset_x) <= 8 and abs(item.offset_y) <= 8 for item in regions)


def test_cli_and_script_write_a_report_even_without_soffice(tmp_path: Path) -> None:
    from docentric_copilot.cli.main import app
    from typer.testing import CliRunner

    left, right = _write_inputs(tmp_path)
    output = tmp_path / "cli-report.json"
    result = CliRunner().invoke(
        app,
        ["reference", "visual-diff", str(left), str(right), "--json", str(output)],
    )
    assert result.exit_code == 0, result.stdout
    assert "Visual diff:" in result.stdout
    assert "LibreOffice rendering (not Word fidelity)" in result.stdout
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert "visual_status" in payload
    assert payload["runtime_compatibility"] == "not_tested"
    assert payload["visual_status"] in {"identical", "different", "renderer_unavailable"}

    script_output = tmp_path / "script-report.json"
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "reference_visual_diff.py"),
            str(left),
            str(right),
            "--json",
            str(script_output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "LibreOffice rendering (not Word fidelity)" in completed.stdout
    assert json.loads(script_output.read_text(encoding="utf-8"))["visual_status"] in {
        "identical",
        "different",
        "renderer_unavailable",
    }
