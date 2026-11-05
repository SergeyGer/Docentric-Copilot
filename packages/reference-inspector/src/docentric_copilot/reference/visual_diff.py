"""Visual Reference Diff (v0.11 P1, issue #28).

The visual dimension is deliberately independent from the structural and
semantic diffs in :mod:`docentric_copilot.reference.diff`: it renders both
references through LibreOffice and compares the resulting pages. It is
**LibreOffice rendering, not Word fidelity**, and it never claims that a visual
difference is a defect.

* Rendering uses the existing ``scripts/docx_to_pdf.py`` path (``soffice`` plus
  ``pdftoppm``) when available in the optional ``api-pdf`` image.
* Comparison reports page counts, blank pages, per-page ink/coverage deltas and
  shifted regions, with an explicit tolerance.
* When the renderer (or poppler) is unavailable, the status is
  ``renderer_unavailable`` with a reason. It is never ``passed`` or ``failed``.
* No pixel comparison result is a Word, Docentric AX or runtime compatibility
  claim.

Dependencies stay minimal: PNG decoding and pixel comparison use the standard
library only.
"""

from __future__ import annotations

import html
import importlib.util
import shutil
import struct
import subprocess
import sys
import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final, Literal, Protocol

from docentric_copilot.errors import CopilotError
from docentric_copilot.serialization import digest, digest_bytes
from pydantic import BaseModel, ConfigDict, Field

from .inventory import ArtifactKind, scan_bytes, scan_path
from .safety import ReferenceLimits

VISUAL_DIFF_VERSION: Final[Literal["1.0"]] = "1.0"
REFERENCE_VERSION: Final[Literal["1.0"]] = "1.0"
RUNTIME_COMPATIBILITY: Final[Literal["not_tested"]] = "not_tested"
RENDERER_LABEL: Final = "LibreOffice rendering (not Word fidelity)"
RENDERER_NAME: Final[Literal["libreoffice"]] = "libreoffice"

_DEFAULT_DPI: Final = 150
_DEFAULT_TOLERANCE: Final = 0.005
_BLANK_INK_THRESHOLD: Final = 0.002
_MAX_COARSE_WIDTH: Final = 240
_GRID_COLUMNS: Final = 6
_GRID_ROWS: Final = 8
_SHIFT_STEPS: Final[tuple[int, ...]] = (-8, -4, 0, 4, 8)
_SHIFT_IMPROVEMENT: Final = 0.01
_MAX_SHIFTED_REGIONS: Final = 48


class VisualStatus(str, Enum):
    """The independent visual comparison status. Never a pass/fail verdict."""

    IDENTICAL = "identical"
    DIFFERENT = "different"
    RENDERER_UNAVAILABLE = "renderer_unavailable"


class PageStatus(str, Enum):
    """Per-page comparison status."""

    IDENTICAL = "identical"
    DIFFERENT = "different"
    ONLY_LEFT = "only_left"
    ONLY_RIGHT = "only_right"


class RendererUnavailable(RuntimeError):  # noqa: N818 - contract status name
    """The renderer or its rasteriser cannot produce page images."""


class VisualInputError(CopilotError):
    """The reference input could not be reduced to a DOCX payload."""

    code = "reference_visual_input_invalid"
    http_status = 400
    exit_code = 3


class PageMetrics(BaseModel):
    """Measurable facts for one rendered page."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    page: int = Field(ge=1)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    ink_fraction: float = Field(ge=0.0, le=1.0)
    coverage_fraction: float = Field(ge=0.0, le=1.0)
    blank: bool
    image: str | None = Field(default=None, max_length=500)


class ShiftedRegion(BaseModel):
    """A page region whose best match is a small translation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    row: int = Field(ge=0)
    column: int = Field(ge=0)
    offset_x: int
    offset_y: int
    improvement: float = Field(ge=0.0, le=1.0)


class PageDiff(BaseModel):
    """Comparison result for one page index."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    page: int = Field(ge=1)
    status: PageStatus
    left: PageMetrics | None = None
    right: PageMetrics | None = None
    changed_fraction: float = Field(default=0.0, ge=0.0, le=1.0)
    ink_delta: float = 0.0
    coverage_delta: float = 0.0
    page_size_changed: bool = False
    blank_changed: bool = False
    shifted_regions: list[ShiftedRegion] = Field(
        default_factory=list, max_length=_MAX_SHIFTED_REGIONS
    )


class VisualDiffSummary(BaseModel):
    """Aggregate page-level counts; no pass/fail verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pages_compared: int = Field(ge=0)
    identical_pages: int = Field(ge=0)
    changed_pages: int = Field(ge=0)
    only_left_pages: int = Field(ge=0)
    only_right_pages: int = Field(ge=0)
    blank_pages_left: int = Field(ge=0)
    blank_pages_right: int = Field(ge=0)
    page_count_delta: int
    shifted_regions: int = Field(ge=0)
    max_changed_fraction: float = Field(default=0.0, ge=0.0, le=1.0)


class VisualSide(BaseModel):
    """One rendered side without local absolute paths."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_name: str = Field(min_length=1, max_length=300)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_count: int = Field(ge=0)


class VisualComparisonSettings(BaseModel):
    """Fixed comparison parameters stored with the report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dpi: int = Field(ge=36, le=600)
    tolerance: float = Field(ge=0.0, le=1.0)
    blank_ink_threshold: float = Field(ge=0.0, le=1.0)
    grid_columns: int = Field(ge=1)
    grid_rows: int = Field(ge=1)
    renderer_label: str = Field(default=RENDERER_LABEL, max_length=120)


class VisualDiffReport(BaseModel):
    """The visual Reference Diff contract (v0.11 P1)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    visual_diff_version: Literal["1.0"] = VISUAL_DIFF_VERSION
    reference_version: Literal["1.0"] = REFERENCE_VERSION
    runtime_compatibility: Literal["not_tested"] = RUNTIME_COMPATIBILITY
    ir_kind: Literal["reference"] = "reference"
    compilable: Literal[False] = False
    note: str = Field(
        default=(
            "LibreOffice rendering evidence only; not Word fidelity, not a defect verdict and "
            "not a Docentric AX runtime check."
        ),
        max_length=300,
    )
    renderer: Literal["libreoffice"] = RENDERER_NAME
    renderer_label: str = Field(default=RENDERER_LABEL, max_length=120)
    renderer_version: str = Field(default="", max_length=120)
    renderer_available: bool = False
    reason: str | None = Field(default=None, max_length=500)
    visual_status: VisualStatus
    structural_status: Literal["not_compared"] = "not_compared"
    semantic_status: Literal["not_compared"] = "not_compared"
    pages_compared: int = Field(ge=0)
    left: VisualSide
    right: VisualSide
    pages: list[PageDiff] = Field(default_factory=list, max_length=5_000)
    summary: VisualDiffSummary
    comparison: VisualComparisonSettings
    artifacts: dict[str, str] = Field(default_factory=dict)
    report_digest: str = Field(pattern=r"^[0-9a-f]{64}$", default="0" * 64)


# --------------------------------------------------------------------------- #
# Renderer contract and default LibreOffice implementation
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RenderedPage:
    """One rasterised page (PNG bytes)."""

    page: int
    png: bytes


@dataclass(frozen=True)
class RenderedReference:
    """Everything a renderer produced for one reference."""

    pages: list[RenderedPage]
    pdf: bytes | None = None
    renderer_version: str = ""
    width_mm: float | None = None
    height_mm: float | None = None


class VisualRenderer(Protocol):
    """Renderer seam used by tests and the CLI."""

    @property
    def name(self) -> str: ...

    def render(self, docx: bytes, *, filename: str) -> RenderedReference: ...


def _find_docx_to_pdf() -> Path | None:
    """Locate the existing rendering helper without importing it as a package."""
    import os

    configured = os.environ.get("DC_DOCX_TO_PDF")
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file():
            return candidate
    candidates = [
        Path(__file__).resolve().parents[5] / "scripts" / "docx_to_pdf.py",
        Path.cwd() / "scripts" / "docx_to_pdf.py",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _load_docx_to_pdf():
    path = _find_docx_to_pdf()
    if path is None:
        raise RendererUnavailable(
            "scripts/docx_to_pdf.py was not found; the LibreOffice rendering path is unavailable."
        )
    spec = importlib.util.spec_from_file_location("docentric_docx_to_pdf", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RendererUnavailable("scripts/docx_to_pdf.py could not be loaded.")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("docentric_docx_to_pdf", module)
    spec.loader.exec_module(module)
    return module


def _png_page_number(path: Path) -> int:
    digits = "".join(character for character in path.stem if character.isdigit())
    return int(digits) if digits else 0


def _soffice_version(soffice: str) -> str:
    try:
        completed = subprocess.run(
            [soffice, "--version"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    text = (completed.stdout or completed.stderr or "").strip().splitlines()
    return text[0][:120] if text else ""


class LibreOfficeRenderer:
    """Default renderer: ``soffice --headless --convert-to pdf`` + ``pdftoppm``."""

    def __init__(self, *, dpi: int = _DEFAULT_DPI, timeout: float = 180.0) -> None:
        self._dpi = dpi
        self._timeout = timeout

    @property
    def name(self) -> str:
        return RENDERER_NAME

    def render(self, docx: bytes, *, filename: str) -> RenderedReference:
        module = _load_docx_to_pdf()
        soffice = shutil.which("soffice")
        if soffice is None:
            raise RendererUnavailable(
                "soffice was not found on PATH. Use the optional api-pdf image "
                "(docker build --target api-pdf -t docentric-copilot-api-pdf .)."
            )
        pdftoppm = shutil.which("pdftoppm")
        if pdftoppm is None:
            raise RendererUnavailable(
                "pdftoppm (poppler-utils) was not found on PATH; page images cannot be "
                "produced, so the visual diff is renderer_unavailable."
            )
        version = _soffice_version(soffice)
        import tempfile

        safe_name = re_safe_filename(filename)
        with tempfile.TemporaryDirectory(prefix="reference-visual-diff-") as temporary:
            workspace = Path(temporary)
            docx_path = workspace / safe_name
            docx_path.write_bytes(docx)
            pdf_path = workspace / f"{docx_path.stem}.pdf"
            png_dir = workspace / "pages"
            try:
                module.convert_docx_to_pdf(docx_path, pdf_path, timeout=self._timeout)
                png_paths = module.rasterise_pdf_pages(pdf_path, png_dir, dpi=self._dpi)
            except module.RenderError as exc:
                message = str(exc)
                if "not found on PATH" in message:
                    raise RendererUnavailable(message) from exc
                raise RendererUnavailable(
                    f"LibreOffice rendering failed, so no visual verdict is claimed: {message}"
                ) from exc
            ordered = sorted(png_paths, key=_png_page_number)
            pages = [
                RenderedPage(page=index + 1, png=path.read_bytes())
                for index, path in enumerate(ordered)
            ]
            return RenderedReference(
                pages=pages,
                pdf=pdf_path.read_bytes() if pdf_path.is_file() else None,
                renderer_version=version,
            )


def re_safe_filename(filename: str) -> str:
    cleaned = "".join(
        character if character.isalnum() or character in "._- " else "_" for character in filename
    ).strip()
    cleaned = cleaned[:120] or "document.docx"
    if not cleaned.casefold().endswith(".docx"):
        cleaned = f"{cleaned}.docx"
    return cleaned


# --------------------------------------------------------------------------- #
# Minimal PNG decoder (stdlib only)
# --------------------------------------------------------------------------- #
class PngError(ValueError):
    """The supplied page image is not a supported 8-bit PNG."""


@dataclass(frozen=True)
class GrayImage:
    width: int
    height: int
    pixels: bytes  # one grayscale byte per pixel


def decode_png(payload: bytes) -> GrayImage:
    """Decode an 8-bit non-interlaced PNG into grayscale bytes."""
    if len(payload) < 8 or payload[:8] != b"\x89PNG\r\n\x1a\n":
        raise PngError("not a PNG file")
    position = 8
    width = height = bit_depth = color_type = 0
    compressed = bytearray()
    while position + 8 <= len(payload):
        length = struct.unpack(">I", payload[position : position + 4])[0]
        chunk_type = payload[position + 4 : position + 8]
        start = position + 8
        end = start + length
        if end > len(payload):
            raise PngError("truncated PNG chunk")
        data = payload[start:end]
        position = end + 4  # skip CRC
        if chunk_type == b"IHDR":
            if length < 13:
                raise PngError("invalid IHDR")
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", data[:13]
            )
            if compression != 0 or filtering != 0 or interlace != 0:
                raise PngError("compressed/filtered/interlaced PNG is unsupported")
        elif chunk_type == b"IDAT":
            compressed.extend(data)
        elif chunk_type == b"IEND":
            break
    if width <= 0 or height <= 0:
        raise PngError("PNG has no IHDR")
    if bit_depth != 8 or color_type not in {0, 2, 4, 6}:
        raise PngError(f"unsupported PNG format (bit depth {bit_depth}, colour type {color_type})")
    channels = {0: 1, 2: 3, 4: 2, 6: 4}[color_type]
    stride = width * channels
    try:
        raw = zlib.decompress(bytes(compressed))
    except zlib.error as exc:  # pragma: no cover - defensive
        raise PngError(f"PNG data is not valid zlib: {exc}") from exc
    expected = (stride + 1) * height
    if len(raw) < expected:
        raise PngError("PNG pixel data is truncated")
    pixels = bytearray(width * height)
    previous = bytearray(stride)
    offset = 0
    for row in range(height):
        filter_type = raw[offset]
        offset += 1
        line = bytearray(raw[offset : offset + stride])
        offset += stride
        if filter_type == 0:
            pass
        elif filter_type == 1:  # Sub
            for index in range(channels, stride):
                line[index] = (line[index] + line[index - channels]) & 0xFF
        elif filter_type == 2:  # Up
            for index in range(stride):
                line[index] = (line[index] + previous[index]) & 0xFF
        elif filter_type == 3:  # Average
            for index in range(stride):
                left = line[index - channels] if index >= channels else 0
                line[index] = (line[index] + ((left + previous[index]) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for index in range(stride):
                left = line[index - channels] if index >= channels else 0
                up = previous[index]
                up_left = previous[index - channels] if index >= channels else 0
                estimate = left + up - up_left
                pa = abs(estimate - left)
                pb = abs(estimate - up)
                pc = abs(estimate - up_left)
                predictor = left if pa <= pb and pa <= pc else up if pb <= pc else up_left
                line[index] = (line[index] + predictor) & 0xFF
        else:
            raise PngError(f"unsupported PNG filter type {filter_type}")
        previous = line
        for column in range(width):
            base = column * channels
            if channels == 1 or channels == 2:
                gray = line[base]
            else:
                red, green, blue = line[base], line[base + 1], line[base + 2]
                gray = (red * 299 + green * 587 + blue * 114) // 1000
            pixels[row * width + column] = gray
    return GrayImage(width=width, height=height, pixels=bytes(pixels))


def _downsample(image: GrayImage, max_width: int = _MAX_COARSE_WIDTH) -> GrayImage:
    if image.width <= max_width:
        return image
    scale = image.width / max_width
    width = max_width
    height = max(1, round(image.height / scale))
    pixels = bytearray(width * height)
    source_w = image.width
    for row in range(height):
        source_row = min(image.height - 1, int(row * scale))
        base = source_row * source_w
        out_base = row * width
        for column in range(width):
            pixels[out_base + column] = image.pixels[base + min(source_w - 1, int(column * scale))]
    return GrayImage(width=width, height=height, pixels=bytes(pixels))


def _metrics(image: GrayImage) -> tuple[float, float, bool]:
    total = len(image.pixels)
    if total == 0:  # pragma: no cover - decode prevents this
        return 0.0, 0.0, True
    ink = sum(255 - value for value in image.pixels) / (255 * total)
    covered = sum(1 for value in image.pixels if value < 245) / total
    blank = ink < _BLANK_INK_THRESHOLD and covered < 0.001
    return round(ink, 6), round(covered, 6), blank


def _absolute_difference(left: GrayImage, right: GrayImage) -> float:
    total = min(len(left.pixels), len(right.pixels))
    if total == 0:
        return 0.0
    difference = sum(abs(left.pixels[index] - right.pixels[index]) for index in range(total))
    return round(difference / (255 * total), 6)


def _cell_bounds(row: int, column: int, width: int, height: int) -> tuple[int, int, int, int]:
    left = round(width * column / _GRID_COLUMNS)
    right = round(width * (column + 1) / _GRID_COLUMNS)
    top = round(height * row / _GRID_ROWS)
    bottom = round(height * (row + 1) / _GRID_ROWS)
    return left, top, right, bottom


def _cell_difference(
    left: GrayImage,
    right: GrayImage,
    box: tuple[int, int, int, int],
    *,
    dx: int,
    dy: int,
) -> float:
    left_x, top, right_x, bottom = box
    total = 0
    count = 0
    for y in range(top, bottom, 2):
        for x in range(left_x, right_x, 2):
            target_x = x + dx
            target_y = y + dy
            if 0 <= target_x < right.width and 0 <= target_y < right.height:
                total += abs(
                    left.pixels[y * left.width + x]
                    - right.pixels[target_y * right.width + target_x]
                )
                count += 1
    return total / (255 * count) if count else 0.0


def detect_shifted_regions(left: GrayImage, right: GrayImage) -> list[ShiftedRegion]:
    """Find small translated regions using a coarse grid and bounded offsets."""
    regions: list[ShiftedRegion] = []
    for row in range(_GRID_ROWS):
        for column in range(_GRID_COLUMNS):
            box = _cell_bounds(
                row, column, min(left.width, right.width), min(left.height, right.height)
            )
            base = _cell_difference(left, right, box, dx=0, dy=0)
            best_offset = (0, 0)
            best = base
            for dy in _SHIFT_STEPS:
                for dx in _SHIFT_STEPS:
                    if dx == 0 and dy == 0:
                        continue
                    candidate = _cell_difference(left, right, box, dx=dx, dy=dy)
                    if candidate < best:
                        best = candidate
                        best_offset = (dx, dy)
            if best_offset != (0, 0) and best + _SHIFT_IMPROVEMENT < base:
                regions.append(
                    ShiftedRegion(
                        row=row,
                        column=column,
                        offset_x=best_offset[0],
                        offset_y=best_offset[1],
                        improvement=round(base - best, 6),
                    )
                )
                if len(regions) >= _MAX_SHIFTED_REGIONS:
                    return regions
    return regions


# --------------------------------------------------------------------------- #
# Input loading
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class LoadedReference:
    name: str
    source_sha256: str
    document_sha256: str
    docx: bytes


def load_reference_docx(
    source: str | Path | bytes, *, filename: str | None = None
) -> LoadedReference:
    """Reduce a DOCX/ZIP/AXPP/directory reference to its first DOCX payload."""
    limits = ReferenceLimits()
    if isinstance(source, bytes | bytearray):
        name = filename or "upload.docx"
        scan = scan_bytes(bytes(source), filename=name, limits=limits, max_depth=1)
    else:
        path = Path(source)
        if not path.exists():
            raise VisualInputError("Visual diff input does not exist", details={"name": path.name})
        name = filename or path.name
        scan = scan_path(path, limits=limits, max_depth=1)
    entries = scan.distinct_entries_by_sha(ArtifactKind.DOCX)
    if not entries:
        raise VisualInputError(
            "Visual diff input does not contain a DOCX document",
            details={"name": name},
        )
    entry = entries[0]
    payload = scan.payload_for_sha(entry.sha256)
    if payload is None:  # pragma: no cover - scan contract
        raise VisualInputError("DOCX payload is unavailable", details={"name": name})
    return LoadedReference(
        name=entry.name,
        source_sha256=scan.inventory.source_sha256,
        document_sha256=digest_bytes(payload),
        docx=payload,
    )


# --------------------------------------------------------------------------- #
# Report building
# --------------------------------------------------------------------------- #
def _write_report(
    report: VisualDiffReport,
    output_dir: Path,
    *,
    left_pdf: bytes | None,
    right_pdf: bytes | None,
    left_pages: Sequence[RenderedPage],
    right_pages: Sequence[RenderedPage],
) -> tuple[VisualDiffReport, dict[str, str]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, str] = {}
    if left_pdf is not None:
        (output_dir / "left.pdf").write_bytes(left_pdf)
        artifacts["left_pdf"] = "left.pdf"
    if right_pdf is not None:
        (output_dir / "right.pdf").write_bytes(right_pdf)
        artifacts["right_pdf"] = "right.pdf"
    for label, pages in (("left", left_pages), ("right", right_pages)):
        if not pages:
            continue
        directory = output_dir / f"{label}-pages"
        directory.mkdir(exist_ok=True)
        relative_pages: list[str] = []
        for page in pages:
            target = directory / f"page-{page.page}.png"
            target.write_bytes(page.png)
            relative_pages.append(f"{label}-pages/page-{page.page}.png")
        artifacts[f"{label}_pages"] = ",".join(relative_pages)
    artifacts["report_json"] = "report.json"
    artifacts["report_html"] = "report.html"
    with_artifacts = report.model_copy(update={"artifacts": artifacts})
    report_digest = digest(with_artifacts.model_dump(mode="json", exclude={"report_digest"}))
    updated = with_artifacts.model_copy(update={"report_digest": report_digest})
    (output_dir / "report.json").write_text(visual_diff_json(updated), encoding="utf-8")
    (output_dir / "report.html").write_text(render_visual_diff_html(updated), encoding="utf-8")
    return updated, artifacts


def _unavailable_report(
    *,
    left: LoadedReference,
    right: LoadedReference,
    reason: str,
    renderer_version: str,
    settings: VisualComparisonSettings,
) -> VisualDiffReport:
    summary = VisualDiffSummary(
        pages_compared=0,
        identical_pages=0,
        changed_pages=0,
        only_left_pages=0,
        only_right_pages=0,
        blank_pages_left=0,
        blank_pages_right=0,
        page_count_delta=0,
        shifted_regions=0,
        max_changed_fraction=0.0,
    )
    base = VisualDiffReport(
        renderer_version=renderer_version,
        renderer_available=False,
        reason=reason[:500],
        visual_status=VisualStatus.RENDERER_UNAVAILABLE,
        pages_compared=0,
        left=VisualSide(
            source_name=left.name,
            source_sha256=left.source_sha256,
            document_sha256=left.document_sha256,
            page_count=0,
        ),
        right=VisualSide(
            source_name=right.name,
            source_sha256=right.source_sha256,
            document_sha256=right.document_sha256,
            page_count=0,
        ),
        pages=[],
        summary=summary,
        comparison=settings,
        artifacts={},
    )
    return base.model_copy(
        update={
            "report_digest": digest(
                base.model_dump(mode="json", exclude={"report_digest", "artifacts"})
            )
        }
    )


def _compare_pages(
    left: list[RenderedPage],
    right: list[RenderedPage],
    *,
    tolerance: float,
) -> tuple[list[PageDiff], VisualDiffSummary]:
    page_diffs: list[PageDiff] = []
    for index in range(max(len(left), len(right))):
        page_number = index + 1
        left_page = left[index] if index < len(left) else None
        right_page = right[index] if index < len(right) else None
        left_image = decode_png(left_page.png) if left_page is not None else None
        right_image = decode_png(right_page.png) if right_page is not None else None
        left_metrics = _page_metrics(left_image, page_number) if left_image else None
        right_metrics = _page_metrics(right_image, page_number) if right_image else None
        if left_image is None and right_image is None:  # pragma: no cover - defensive
            continue
        if left_image is None:
            page_diffs.append(
                PageDiff(
                    page=page_number,
                    status=PageStatus.ONLY_RIGHT,
                    right=right_metrics,
                    blank_changed=bool(right_metrics and right_metrics.blank),
                )
            )
            continue
        if right_image is None:
            page_diffs.append(
                PageDiff(
                    page=page_number,
                    status=PageStatus.ONLY_LEFT,
                    left=left_metrics,
                    blank_changed=bool(left_metrics and left_metrics.blank),
                )
            )
            continue
        assert left_metrics is not None and right_metrics is not None
        page_size_changed = (left_image.width, left_image.height) != (
            right_image.width,
            right_image.height,
        )
        left_coarse = _downsample(left_image)
        right_coarse = _downsample(right_image)
        if (left_coarse.width, left_coarse.height) != (right_coarse.width, right_coarse.height):
            width = min(left_coarse.width, right_coarse.width)
            height = min(left_coarse.height, right_coarse.height)
            left_coarse = _crop(left_coarse, width, height)
            right_coarse = _crop(right_coarse, width, height)
        changed = _absolute_difference(left_coarse, right_coarse)
        shifted = detect_shifted_regions(left_coarse, right_coarse)
        blank_changed = left_metrics.blank != right_metrics.blank
        is_different = changed > tolerance or page_size_changed or blank_changed or bool(shifted)
        page_diffs.append(
            PageDiff(
                page=page_number,
                status=PageStatus.DIFFERENT if is_different else PageStatus.IDENTICAL,
                left=left_metrics,
                right=right_metrics,
                changed_fraction=changed,
                ink_delta=round(right_metrics.ink_fraction - left_metrics.ink_fraction, 6),
                coverage_delta=round(
                    right_metrics.coverage_fraction - left_metrics.coverage_fraction, 6
                ),
                page_size_changed=page_size_changed,
                blank_changed=blank_changed,
                shifted_regions=shifted,
            )
        )
    summary = VisualDiffSummary(
        pages_compared=min(len(left), len(right)),
        identical_pages=sum(1 for item in page_diffs if item.status is PageStatus.IDENTICAL),
        changed_pages=sum(1 for item in page_diffs if item.status is PageStatus.DIFFERENT),
        only_left_pages=sum(1 for item in page_diffs if item.status is PageStatus.ONLY_LEFT),
        only_right_pages=sum(1 for item in page_diffs if item.status is PageStatus.ONLY_RIGHT),
        blank_pages_left=sum(1 for item in page_diffs if item.left is not None and item.left.blank),
        blank_pages_right=sum(
            1 for item in page_diffs if item.right is not None and item.right.blank
        ),
        page_count_delta=len(right) - len(left),
        shifted_regions=sum(len(item.shifted_regions) for item in page_diffs),
        max_changed_fraction=max((item.changed_fraction for item in page_diffs), default=0.0),
    )
    return page_diffs, summary


def _crop(image: GrayImage, width: int, height: int) -> GrayImage:
    pixels = bytearray(width * height)
    for row in range(height):
        source = row * image.width
        target = row * width
        pixels[target : target + width] = image.pixels[source : source + width]
    return GrayImage(width=width, height=height, pixels=bytes(pixels))


def _page_metrics(image: GrayImage, page: int) -> PageMetrics:
    ink, coverage, blank = _metrics(image)
    return PageMetrics(
        page=page,
        width=image.width,
        height=image.height,
        ink_fraction=ink,
        coverage_fraction=coverage,
        blank=blank,
    )


def build_visual_diff(
    left: str | Path | bytes,
    right: str | Path | bytes,
    *,
    output_dir: str | Path,
    renderer: VisualRenderer | None = None,
    dpi: int = _DEFAULT_DPI,
    tolerance: float = _DEFAULT_TOLERANCE,
    filename_left: str | None = None,
    filename_right: str | None = None,
) -> VisualDiffReport:
    """Render both references and compare their pages.

    The renderer seam lets tests run without LibreOffice. A
    :class:`RendererUnavailable` failure produces a written report with
    ``visual_status='renderer_unavailable'``; it never becomes a pass/fail.
    """
    if not 0.0 <= tolerance <= 1.0:
        raise VisualInputError("tolerance must be within 0 and 1")
    if not 36 <= dpi <= 600:
        raise VisualInputError("dpi must be within 36 and 600")
    left_reference = load_reference_docx(left, filename=filename_left)
    right_reference = load_reference_docx(right, filename=filename_right)
    target_dir = Path(output_dir)
    settings = VisualComparisonSettings(
        dpi=dpi,
        tolerance=tolerance,
        blank_ink_threshold=_BLANK_INK_THRESHOLD,
        grid_columns=_GRID_COLUMNS,
        grid_rows=_GRID_ROWS,
    )
    active_renderer = renderer or LibreOfficeRenderer(dpi=dpi)
    try:
        left_rendered = active_renderer.render(left_reference.docx, filename=left_reference.name)
        right_rendered = active_renderer.render(right_reference.docx, filename=right_reference.name)
    except RendererUnavailable as exc:
        unavailable = _unavailable_report(
            left=left_reference,
            right=right_reference,
            reason=str(exc),
            renderer_version="",
            settings=settings,
        )
        updated, _artifacts = _write_report(
            unavailable,
            target_dir,
            left_pdf=None,
            right_pdf=None,
            left_pages=[],
            right_pages=[],
        )
        return updated
    if not left_rendered.pages or not right_rendered.pages:
        unavailable = _unavailable_report(
            left=left_reference,
            right=right_reference,
            reason="The renderer produced no page images, so no visual comparison was made.",
            renderer_version=left_rendered.renderer_version or right_rendered.renderer_version,
            settings=settings,
        )
        updated, _artifacts = _write_report(
            unavailable,
            target_dir,
            left_pdf=left_rendered.pdf,
            right_pdf=right_rendered.pdf,
            left_pages=[],
            right_pages=[],
        )
        return updated
    pages, summary = _compare_pages(left_rendered.pages, right_rendered.pages, tolerance=tolerance)
    visual_status = (
        VisualStatus.IDENTICAL
        if summary.changed_pages == 0
        and summary.only_left_pages == 0
        and summary.only_right_pages == 0
        else VisualStatus.DIFFERENT
    )
    base = VisualDiffReport(
        renderer_version=left_rendered.renderer_version or right_rendered.renderer_version,
        renderer_available=True,
        visual_status=visual_status,
        pages_compared=summary.pages_compared,
        left=VisualSide(
            source_name=left_reference.name,
            source_sha256=left_reference.source_sha256,
            document_sha256=left_reference.document_sha256,
            page_count=len(left_rendered.pages),
        ),
        right=VisualSide(
            source_name=right_reference.name,
            source_sha256=right_reference.source_sha256,
            document_sha256=right_reference.document_sha256,
            page_count=len(right_rendered.pages),
        ),
        pages=pages,
        summary=summary,
        comparison=settings,
        artifacts={},
    )
    with_pages = base.model_copy(
        update={
            "pages": [
                page.model_copy(
                    update={
                        "left": page.left.model_copy(
                            update={"image": f"left-pages/page-{page.page}.png"}
                        )
                        if page.left is not None
                        else None,
                        "right": page.right.model_copy(
                            update={"image": f"right-pages/page-{page.page}.png"}
                        )
                        if page.right is not None
                        else None,
                    }
                )
                for page in pages
            ]
        }
    )
    updated, _artifacts = _write_report(
        with_pages,
        target_dir,
        left_pdf=left_rendered.pdf,
        right_pdf=right_rendered.pdf,
        left_pages=left_rendered.pages,
        right_pages=right_rendered.pages,
    )
    return updated


# --------------------------------------------------------------------------- #
# Serialisation
# --------------------------------------------------------------------------- #
def visual_diff_json(report: VisualDiffReport, *, indent: int = 2) -> str:
    """Deterministic JSON text used by the CLI, script and tests."""
    import json

    return (
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            indent=indent,
            sort_keys=True,
        )
        + "\n"
    )


def _status_class(status: str) -> str:
    return {
        "identical": "ok",
        "different": "changed",
        "renderer_unavailable": "unavailable",
        "only_left": "changed",
        "only_right": "changed",
    }.get(status, "unknown")


def render_visual_diff_html(report: VisualDiffReport) -> str:
    """Safe, self-contained HTML report (all values escaped)."""
    rows: list[str] = []
    for page in report.pages:
        left = page.left
        right = page.right
        shifted = (
            ", ".join(
                f"({item.row},{item.column}) {item.offset_x:+d}/{item.offset_y:+d}px"
                for item in page.shifted_regions
            )
            or "—"
        )
        rows.append(
            "<tr>"
            f"<td>{page.page}</td>"
            f'<td><span class="badge {_status_class(page.status.value)}">'
            f"{html.escape(page.status.value)}</span></td>"
            f"<td>{html.escape(f'{left.ink_fraction:.3%}' if left else '—')}</td>"
            f"<td>{html.escape(f'{right.ink_fraction:.3%}' if right else '—')}</td>"
            f"<td>{html.escape(f'{page.ink_delta:+.3%}')}</td>"
            f"<td>{html.escape(f'{page.changed_fraction:.3%}')}</td>"
            f"<td>{html.escape(str(page.blank_changed))}</td>"
            f"<td>{html.escape(shifted)}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="8">No pages were compared.</td></tr>')
    summary = report.summary
    status_reason = (
        f'<p class="reason">Renderer unavailable: {html.escape(report.reason or "")}. '
        "This is not a pass or a fail.</p>"
        if report.visual_status is VisualStatus.RENDERER_UNAVAILABLE
        else ""
    )
    artifacts = "".join(
        f"<li><code>{html.escape(key)}</code>: {html.escape(value)}</li>"
        for key, value in sorted(report.artifacts.items())
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Visual reference diff · LibreOffice rendering</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #1f2937; }}
h1 {{ font-size: 1.35rem; }}
.note {{ background: #f3f4f6; border-left: 4px solid #6b7280; padding: .75rem 1rem; }}
.badge {{ display: inline-block; padding: .1rem .45rem; border-radius: .35rem;
         font-size: .8rem; background: #e5e7eb; }}
.badge.ok {{ background: #dcfce7; color: #166534; }}
.badge.changed {{ background: #fef3c7; color: #92400e; }}
.badge.unavailable {{ background: #e0e7ff; color: #3730a3; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 1rem; }}
th, td {{ border: 1px solid #e5e7eb; padding: .35rem .5rem; text-align: left; font-size: .85rem; }}
.reason {{ color: #3730a3; }}
</style>
</head>
<body>
<h1>Visual reference diff</h1>
<p class="note"><strong>{html.escape(report.renderer_label)}</strong><br>
This compares page images rendered by LibreOffice. It is not Microsoft Word fidelity,
not a Docentric AX runtime check and not a defect verdict.</p>
{status_reason}
<p><strong>Status:</strong> <span class="badge {_status_class(report.visual_status.value)}">
{html.escape(report.visual_status.value)}</span>
&nbsp; <strong>Pages compared:</strong> {report.pages_compared}
&nbsp; <strong>Page count delta:</strong> {summary.page_count_delta:+d}</p>
<p><strong>Left:</strong> {html.escape(report.left.source_name)} ({report.left.page_count} pages)
&nbsp; <strong>Right:</strong> {html.escape(report.right.source_name)} ({report.right.page_count} pages)</p>
<p><strong>Structural:</strong> not compared &nbsp; <strong>Semantic:</strong> not compared
&nbsp; <strong>Runtime compatibility:</strong> {html.escape(report.runtime_compatibility)}</p>
<table>
<thead><tr><th>Page</th><th>Status</th><th>Ink left</th><th>Ink right</th>
<th>Ink delta</th><th>Changed fraction</th><th>Blank changed</th><th>Shifted regions</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table>
<h2>Artifacts</h2>
<ul>{artifacts or "<li>None</li>"}</ul>
<p><small>visual-diff {html.escape(report.visual_diff_version)} ·
renderer {html.escape(report.renderer)} {html.escape(report.renderer_version)} ·
report digest {html.escape(report.report_digest)}</small></p>
</body>
</html>
"""


__all__ = [
    "RENDERER_LABEL",
    "RUNTIME_COMPATIBILITY",
    "VISUAL_DIFF_VERSION",
    "GrayImage",
    "LibreOfficeRenderer",
    "LoadedReference",
    "PageDiff",
    "PageMetrics",
    "PageStatus",
    "PngError",
    "RenderedPage",
    "RenderedReference",
    "RendererUnavailable",
    "ShiftedRegion",
    "VisualComparisonSettings",
    "VisualDiffReport",
    "VisualDiffSummary",
    "VisualInputError",
    "VisualRenderer",
    "VisualSide",
    "VisualStatus",
    "build_visual_diff",
    "decode_png",
    "detect_shifted_regions",
    "load_reference_docx",
    "render_visual_diff_html",
    "visual_diff_json",
]
