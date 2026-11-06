"""Tests for the real-renderer visual CI gate (V012-07).

The unit tests only assert fixture construction and fail-closed behaviour. The
real LibreOffice/Poppler run is `scripts/visual_ci.py`, executed by the
`Visual Diff` GitHub Actions job; when the tools are installed locally, the
lock-version test also runs here.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from docentric_copilot.reference import VisualStatus
from scripts.visual_ci import (
    FIXTURE_NAMES,
    LOCK_PATH,
    _png_bytes,
    _status_name,
    _version_errors,
    build_fixture_pairs,
    main,
    renderer_identity,
    run_suite,
)


def test_fixture_pairs_are_valid_and_isolated(tmp_path: Path) -> None:
    pairs = build_fixture_pairs(tmp_path / "fixtures")
    assert set(pairs) == set(FIXTURE_NAMES)
    for name, (left, right) in pairs.items():
        assert left.exists() and right.exists()
        assert left.read_bytes().startswith(b"PK")
        assert right.read_bytes().startswith(b"PK")
        if name == "identical":
            assert left.read_bytes() == right.read_bytes()
        else:
            assert left.read_bytes() != right.read_bytes()
        assert left.with_suffix(".docx").parent == right.parent


def test_png_helper_produces_a_valid_png() -> None:
    payload = _png_bytes(4, 5)
    assert payload.startswith(b"\x89PNG\r\n\x1a\n")
    assert b"IHDR" in payload and b"IEND" in payload


def test_status_names_are_explicit() -> None:
    assert _status_name(VisualStatus.IDENTICAL) == "visual_pass"
    assert _status_name(VisualStatus.DIFFERENT) == "visual_different"
    assert _status_name(VisualStatus.RENDERER_UNAVAILABLE) == "visual_not_checked"


def test_version_lock_reports_drift() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    good = {
        "libreoffice": lock["libreoffice"],
        "poppler": f"pdftoppm version {lock['poppler']}",
        "font_match": 'DejaVuSans.ttf: "DejaVu Sans" "Book"',
    }
    assert _version_errors(good, lock) == []
    bad = {
        "libreoffice": "LibreOffice 99.9",
        "poppler": "pdftoppm version 0.0.1",
        "font_match": "SomeOther.ttf",
    }
    errors = _version_errors(bad, lock)
    assert len(errors) == 3
    assert any("LibreOffice version drift" in error for error in errors)
    assert any("Poppler version drift" in error for error in errors)
    assert any("font drift" in error for error in errors)


def test_missing_renderer_is_not_checked_and_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    (tmp_path / "empty-bin").mkdir()
    output = tmp_path / "visual-ci"
    summary = run_suite(output, tolerance=0.005)
    assert summary["status"] == "visual_not_checked"
    assert summary["visual_status"] == "visual_not_checked"
    assert summary["fixtures"] == []
    assert any("real renderer unavailable" in failure for failure in summary["failures"])
    assert (output / "summary.json").exists()
    assert summary["runtime_compatibility"] == "not_tested"
    assert summary["renderer"]["libreoffice_path"] is None


def test_missing_renderer_cli_exit_code(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    (tmp_path / "empty-bin").mkdir()
    assert main(["--output-dir", str(tmp_path / "out")]) == 1
    summary = json.loads((tmp_path / "out" / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "visual_not_checked"
    assert summary["visual_status"] == "visual_not_checked"
    assert summary["failures"]


@pytest.mark.skipif(
    shutil.which("soffice") is None or shutil.which("pdftoppm") is None,
    reason="real LibreOffice/Poppler not installed",
)
def test_local_renderer_matches_the_lock() -> None:
    identity = renderer_identity(
        {
            **os.environ,
            "LC_ALL": "C.UTF-8",
            "LANG": "C.UTF-8",
        }
    )
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert _version_errors(identity, lock) == []
    assert "LibreOffice" in str(identity["libreoffice"])
    assert lock["poppler"] in str(identity["poppler"])
