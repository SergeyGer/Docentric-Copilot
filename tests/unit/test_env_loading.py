"""The .env convenience must load values without overriding the real environment."""

from __future__ import annotations

import os

from docentric_copilot.config import _load_local_env


def test_dotenv_is_loaded_from_the_working_directory(tmp_path, monkeypatch) -> None:
    (tmp_path / ".env").write_text("DC_TEST_MARKER=from-dotenv\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DC_TEST_MARKER", raising=False)
    _load_local_env()
    assert os.environ["DC_TEST_MARKER"] == "from-dotenv"
    monkeypatch.delenv("DC_TEST_MARKER", raising=False)


def test_real_environment_wins_over_dotenv(tmp_path, monkeypatch) -> None:
    (tmp_path / ".env").write_text("DC_TEST_MARKER=from-dotenv\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DC_TEST_MARKER", "from-shell")
    _load_local_env()
    assert os.environ["DC_TEST_MARKER"] == "from-shell"
    monkeypatch.delenv("DC_TEST_MARKER", raising=False)
