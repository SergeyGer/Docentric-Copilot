"""CLI tests: behaviour, JSON output and stable exit codes (FR-10)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from docentric_copilot.cli.main import app
from typer.testing import CliRunner

from tests.conftest import EXAMPLES

runner = CliRunner()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.stdout


def test_inspect_text_and_json() -> None:
    package = EXAMPLES / "quotation" / "sales-quotation.ddsp"
    text = runner.invoke(app, ["inspect", str(package)])
    assert text.exit_code == 0
    assert "sales_quotation" in text.stdout
    assert "MainData" in text.stdout

    payload = runner.invoke(app, ["inspect", str(package), "--json"])
    assert payload.exit_code == 0
    data = json.loads(payload.stdout)
    assert data["schema_id"] == "sales_quotation"
    assert data["sample_data_available"] is True


def test_inspect_missing_file_exit_code() -> None:
    result = runner.invoke(app, ["inspect", "does-not-exist.ddsp"])
    assert result.exit_code == 6


def test_inspect_invalid_file_exit_code(tmp_path: Path) -> None:
    invalid = tmp_path / "broken.ddsp"
    invalid.write_bytes(b"this is definitely not a ddsp package")
    result = runner.invoke(app, ["inspect", str(invalid)])
    assert result.exit_code == 3


def test_full_pipeline(tmp_path: Path) -> None:
    package = EXAMPLES / "quotation" / "sales-quotation.ddsp"
    plan_path = tmp_path / "plan.json"
    mapping_path = tmp_path / "mapping.json"
    docx_path = tmp_path / "quotation.docx"
    preview_path = tmp_path / "preview.html"

    plan = runner.invoke(
        app,
        [
            "plan",
            "--ddsp",
            str(package),
            "--prompt-file",
            str(EXAMPLES / "quotation" / "prompt.txt"),
            "--output",
            str(plan_path),
            "--mapping",
            str(mapping_path),
        ],
    )
    assert plan.exit_code == 0, plan.stdout
    assert plan_path.exists() and mapping_path.exists()
    ir = json.loads(plan_path.read_text())
    assert ir["sections"][0]["name"] == "Main"

    validate = runner.invoke(
        app,
        ["validate", "--ddsp", str(package), "--plan", str(plan_path), "--json"],
    )
    assert validate.exit_code == 0
    assert json.loads(validate.stdout)["validation"]["semantic"] == "passed"

    compile_result = runner.invoke(
        app,
        [
            "compile",
            "--ddsp",
            str(package),
            "--plan",
            str(plan_path),
            "--output",
            str(docx_path),
        ],
    )
    assert compile_result.exit_code == 0, compile_result.stdout
    assert docx_path.read_bytes().startswith(b"PK")

    preview = runner.invoke(
        app,
        [
            "preview",
            "--ddsp",
            str(package),
            "--plan",
            str(plan_path),
            "--output",
            str(preview_path),
        ],
    )
    assert preview.exit_code == 0
    assert "Example Customer GmbH" in preview_path.read_text()


def test_compile_rejects_unverified_target(tmp_path: Path) -> None:
    package = EXAMPLES / "quotation" / "sales-quotation.ddsp"
    plan_path = tmp_path / "plan.json"
    runner.invoke(
        app,
        [
            "plan",
            "--ddsp",
            str(package),
            "--prompt-file",
            str(EXAMPLES / "quotation" / "prompt.txt"),
            "--output",
            str(plan_path),
        ],
    )
    result = runner.invoke(
        app,
        [
            "compile",
            "--ddsp",
            str(package),
            "--plan",
            str(plan_path),
            "--target",
            "docentric-ax",
            "--output",
            str(tmp_path / "out.docx"),
        ],
    )
    assert result.exit_code == 4


def test_plan_requires_prompt_file() -> None:
    result = runner.invoke(
        app,
        [
            "plan",
            "--ddsp",
            str(EXAMPLES / "quotation" / "sales-quotation.ddsp"),
            "--prompt-file",
            "missing.txt",
        ],
    )
    assert result.exit_code != 0


def test_providers_lists_mock() -> None:
    result = runner.invoke(app, ["providers"])
    assert result.exit_code == 0
    assert "mock" in result.stdout
    payload = runner.invoke(app, ["providers", "--json"])
    entries = json.loads(payload.stdout)
    mock = next(entry for entry in entries if entry["name"] == "mock")
    assert mock["configured"] is True


def test_ir_schema_output(tmp_path: Path) -> None:
    target = tmp_path / "ir.schema.json"
    result = runner.invoke(app, ["ir-schema", "--output", str(target)])
    assert result.exit_code == 0
    schema = json.loads(target.read_text())
    assert schema["title"].startswith("Template IR")


def test_validate_invalid_ir(tmp_path: Path) -> None:
    plan_path = tmp_path / "bad.json"
    plan_path.write_text('{"title": "x"}', encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "validate",
            "--ddsp",
            str(EXAMPLES / "quotation" / "sales-quotation.ddsp"),
            "--plan",
            str(plan_path),
        ],
    )
    assert result.exit_code == 3
