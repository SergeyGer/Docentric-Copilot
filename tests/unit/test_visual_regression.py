"""Tests for visual-regression aggregation and ``not_checked`` semantics (P1)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from docentric_copilot.planner.quality import (
    QualityCheck,
    QualityMetrics,
    QualityReport,
    QualityStatus,
)

ROOT = Path(__file__).resolve().parent.parent.parent


def _load_visual_module():
    path = ROOT / "scripts" / "visual_regression.py"
    spec = importlib.util.spec_from_file_location("visual_regression_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def visual():
    return _load_visual_module()


def _observation(visual, **overrides):
    values = {
        "page": 1,
        "image": "before/page-1.png",
        "width": 1100,
        "height": 1555,
        "ink_fraction": 0.05,
        "ink_variance": 900.0,
        "blank": False,
        "margin_ink_pixels": 0,
        "max_overflow_mm": 0.0,
        "edge_ink_pixels": 0,
        "header_ink_pixels": 100,
        "footer_ink_pixels": 100,
        "header_text": "Contoso Consulting AG",
        "footer_text": "Page 1 of 2",
        "page_number_present": True,
        "text_chars": 500,
        "text_bbox_available": True,
    }
    values.update(overrides)
    return visual.PageObservation(**values)


def _quality(text_fit: str = "passed") -> QualityReport:
    status = QualityStatus(text_fit)
    return QualityReport(
        overall=status,
        checks=[
            QualityCheck(
                id="text_fit",
                label="Text fit",
                status=status,
                message="text fit fixture",
            )
        ],
        metrics=QualityMetrics(page="A4", text_width_mm=170.0, tables=1, images=0, blocks=10),
    )


def test_derive_status_ignores_not_checked_but_never_calls_it_passed(visual) -> None:
    assert visual.derive_status([{"status": "passed"}, {"status": "not_checked"}]) == "passed"
    assert visual.derive_status([{"status": "passed"}, {"status": "warning"}]) == "warning"
    assert visual.derive_status([{"status": "warning"}, {"status": "failed"}]) == "failed"


def test_not_checked_is_not_a_pass_in_summary(visual) -> None:
    observation = _observation(visual)
    checks = visual.evaluate_page_checks(
        None,
        observation,
        header_expected=False,
        footer_expected=False,
    )
    assert checks["header_present"]["status"] == "not_checked"
    assert checks["footer_present"]["status"] == "not_checked"
    assert checks["vertical_overflow"]["status"] == "not_checked"
    case = {
        "case_id": "synthetic",
        "status": "passed",
        "pages": [{"page": 1, "before_checks": {}, "checks": checks}],
        "ir_checks": {},
    }
    summary = visual.summarize_cases([case])
    assert summary["global_status"] == "passed"
    assert summary["not_checked_count"] >= 3
    assert summary["all_checks_passed"] is False
    assert "not checked" in summary["verification_summary"]


def test_blank_page_is_a_critical_failure(visual) -> None:
    before = _observation(visual)
    after = _observation(visual, blank=True, ink_fraction=0.00001, ink_variance=0.5)
    checks = visual.evaluate_page_checks(before, after)
    assert checks["blank_page"]["status"] == "failed"
    assert checks["blank_page"]["critical"] is True


def test_horizontal_overflow_has_a_documented_warning_band(visual) -> None:
    before = _observation(visual)
    small = visual.evaluate_page_checks(before, _observation(visual, max_overflow_mm=2.0))
    assert small["horizontal_overflow"]["status"] == "warning"
    assert small["horizontal_overflow"]["critical"] is False
    large = visual.evaluate_page_checks(before, _observation(visual, max_overflow_mm=8.0))
    assert large["horizontal_overflow"]["status"] == "failed"
    assert large["horizontal_overflow"]["critical"] is True
    clean = visual.evaluate_page_checks(before, _observation(visual, max_overflow_mm=1.0))
    assert clean["horizontal_overflow"]["status"] == "passed"


def test_missing_header_text_is_a_warning_not_a_crash(visual) -> None:
    checks = visual.evaluate_page_checks(
        _observation(visual),
        _observation(visual, header_text=""),
        header_expected=True,
        header_fragments=["Contoso Consulting AG"],
    )
    assert checks["header_present"]["status"] == "warning"
    assert "missing expected text" in checks["header_present"]["message"]


def test_missing_page_number_fails(visual) -> None:
    checks = visual.evaluate_page_checks(
        _observation(visual),
        _observation(visual, page_number_present=False, footer_text=""),
    )
    assert checks["footer_page_number"]["status"] == "failed"


def test_page_count_change_is_a_warning(visual) -> None:
    checks = visual.evaluate_document_checks(
        before_pages=2,
        after_pages=3,
        before_quality=_quality(),
        after_quality=_quality(),
    )
    assert checks["page_count"]["status"] == "warning"
    assert checks["page_count"]["detail"]["before"] == 2
    assert checks["page_count"]["detail"]["after"] == 3


def test_text_fit_improvement_is_recorded(visual) -> None:
    checks = visual.evaluate_document_checks(
        before_pages=2,
        after_pages=2,
        before_quality=_quality("warning"),
        after_quality=_quality("passed"),
    )
    assert checks["text_fit"]["status"] == "passed"
    assert checks["text_fit"]["detail"]["improved"] is True
    assert checks["text_fit"]["detail"]["before"] == "warning"


def test_new_critical_defects_compare_before_and_after(visual) -> None:
    passing = _observation(visual)
    blank = _observation(visual, blank=True)
    checks_before = visual.evaluate_page_checks(None, passing)
    checks_after = visual.evaluate_page_checks(passing, blank)
    case = {
        "case_id": "synthetic",
        "status": "failed",
        "pages": [
            {
                "page": 1,
                "before_checks": checks_before,
                "checks": checks_after,
            }
        ],
        "ir_checks": {},
    }
    summary = visual.summarize_cases([case])
    assert summary["global_status"] == "failed"
    assert any(item["check"] == "blank_page" for item in summary["new_critical_defects"])
    assert summary["unresolved_warning_counts"] == {}


def test_warning_counts_are_per_check_type(visual) -> None:
    checks = {
        "horizontal_overflow": {"status": "warning", "critical": False},
        "vertical_overflow": {"status": "not_checked", "reason": "unsupported"},
    }
    case = {
        "case_id": "synthetic",
        "status": "warning",
        "pages": [{"page": 1, "before_checks": {}, "checks": checks}],
        "ir_checks": {},
    }
    summary = visual.summarize_cases([case])
    assert summary["unresolved_warning_counts"] == {"horizontal_overflow": 1}
    assert summary["not_checked_count"] == 1


def test_content_checks_cover_conditional_and_empty_collection(visual) -> None:
    passed = visual.evaluate_content_checks(
        before_text="page",
        after_text="VAT notice: this document follows the EU VAT rules",
        expected_text=["VAT notice"],
        forbidden_text=["ITEM-"],
        min_pages_before=2,
        page_count_before=2,
        page_count_after=2,
    )
    assert passed["expected_text"]["status"] == "passed"
    assert passed["forbidden_text"]["status"] == "passed"
    assert passed["min_pages"]["status"] == "passed"

    warned = visual.evaluate_content_checks(
        before_text="",
        after_text="ITEM-001",
        expected_text=["VAT notice"],
        forbidden_text=["ITEM-"],
        min_pages_before=4,
        page_count_before=1,
        page_count_after=1,
    )
    assert warned["expected_text"]["status"] == "warning"
    assert warned["forbidden_text"]["status"] == "warning"
    assert warned["min_pages"]["status"] == "warning"


def test_page_observations_serialize(visual) -> None:
    payload = _observation(visual).as_dict()
    assert payload["max_overflow_mm"] == 0.0
    assert payload["page_number_present"] is True


def test_visual_fixtures_are_reproducible() -> None:
    from benchmarks.build_visual_fixtures import build

    fixtures = ROOT / "benchmarks" / "fixtures"
    for name, content in build().items():
        path = fixtures / name
        assert path.is_file(), name
        assert path.read_bytes() == content, name


def test_visual_cases_cover_four_families() -> None:
    import json

    cases = json.loads((ROOT / "benchmarks" / "visual_cases.json").read_text(encoding="utf-8"))
    families = {case["family"] for case in cases}
    assert len(cases) == 4
    assert families == {
        "long_descriptions",
        "multi_page_table",
        "empty_collection",
        "conditional_block",
    }
    for case in cases:
        assert (ROOT / case["package"]).is_file()


def test_inspect_png_measures_blank_and_margin_overflow(visual, tmp_path) -> None:
    pytest.importorskip("PIL")
    from PIL import Image, ImageDraw

    blank_path = tmp_path / "blank.png"
    Image.new("RGB", (1100, 1555), "white").save(blank_path)
    blank = visual.inspect_png(
        blank_path,
        page=1,
        image_label="blank.png",
        page_width_mm=210.0,
        page_height_mm=297.0,
        margin_left_mm=20.0,
        margin_right_mm=20.0,
    )
    assert blank.blank is True
    assert blank.max_overflow_mm == 0.0

    overflow_path = tmp_path / "overflow.png"
    image = Image.new("RGB", (1100, 1555), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 500, 60, 700), fill="black")
    image.save(overflow_path)
    overflow = visual.inspect_png(
        overflow_path,
        page=1,
        image_label="overflow.png",
        page_width_mm=210.0,
        page_height_mm=297.0,
        margin_left_mm=20.0,
        margin_right_mm=20.0,
    )
    assert overflow.blank is False
    assert overflow.max_overflow_mm > 5.0
    checks = visual.evaluate_page_checks(None, overflow)
    assert checks["horizontal_overflow"]["status"] == "failed"
