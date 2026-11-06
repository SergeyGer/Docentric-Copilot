"""V013-07: Streamlit demo confirmation and download regression."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent.parent


def test_confirmation_unlocks_docx_download() -> None:
    app = AppTest.from_file(str(ROOT / "streamlit_app.py")).run(timeout=90)
    assert not app.exception
    assert any(button.key == "confirm-req_09" for button in app.button)
    assert not app.get("download_button")
    confirm = next(button for button in app.button if button.key == "confirm-req_09")
    confirm.click().run(timeout=90)
    assert not app.exception
    downloads = app.get("download_button")
    assert downloads
    assert downloads[0].label == "⬇ Download DOCX"
