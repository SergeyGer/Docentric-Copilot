"""CLI tests for ``docentric-copilot reference d365`` (PR-02/PR-03)."""

from __future__ import annotations

import json
from pathlib import Path

from docentric_copilot.cli.main import app
from typer.testing import CliRunner

from tests.reference_fixtures import (
    ElementSpec,
    build_ddsp,
    build_docx,
    build_embedded_docx,
    build_project_data,
    project_data_parts,
)

runner = CliRunner()


def _elements() -> tuple[ElementSpec, ...]:
    return (
        ElementSpec(1, "Field", "MainData", "@Number", "System.String"),
        ElementSpec(2, "List", "MainData", "Lines/Line", None, child_ids=(3,)),
        ElementSpec(3, "Field", ".", "@ItemId", "System.String"),
    )


def _write_docx(tmp_path: Path) -> Path:
    target = tmp_path / "Synthetic.Report.docx"
    target.write_bytes(build_embedded_docx(_elements()))
    return target


def test_reference_d365_writes_a_stable_json_report(tmp_path: Path) -> None:
    source = _write_docx(tmp_path)
    output = tmp_path / "report.json"
    result = runner.invoke(
        app,
        ["reference", "d365", str(source), "--json", str(output)],
    )
    assert result.exit_code == 0, result.stdout
    assert output.exists()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["platform"] == "D365FO"
    assert payload["schema_source"] == "projectdata"
    assert payload["runtime_compatibility"] == "not_tested"
    assert payload["counts"]["total"] == 3
    assert payload["counts"]["resolved"] == 3
    assert payload["counts"]["resolved_with_evidence"] == 3
    assert "D365 schema: projectdata" in result.stdout
    assert "Runtime compatibility: not_tested" in result.stdout


def test_reference_d365_stdout_mode_is_pure_json(tmp_path: Path) -> None:
    source = _write_docx(tmp_path)
    result = runner.invoke(app, ["reference", "d365", str(source), "--json", "-"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["binding_results"]
    assert all(
        item["status"]
        in {
            "resolved",
            "ambiguous",
            "unknown_path",
            "type_mismatch",
            "schema_unavailable",
            "unsupported_expression",
        }
        for item in payload["binding_results"]
    )


def test_reference_d365_text_mode_prints_a_summary(tmp_path: Path) -> None:
    source = _write_docx(tmp_path)
    result = runner.invoke(app, ["reference", "d365", str(source)])
    assert result.exit_code == 0, result.stdout
    assert "D365 schema: projectdata" in result.stdout
    assert "resolved 3" in result.stdout


def test_reference_d365_uses_a_ddsp_fallback(tmp_path: Path) -> None:
    elements = (ElementSpec(1, "Field", "MainData", "@Number", "System.String"),)
    custom = project_data_parts(build_project_data(elements))
    source = tmp_path / "NoSchema.docx"
    source.write_bytes(build_docx(custom_parts=custom))
    ddsp = tmp_path / "Synthetic.ddsp"
    ddsp.write_bytes(build_ddsp())
    output = tmp_path / "report.json"
    result = runner.invoke(
        app,
        ["reference", "d365", str(source), "--ddsp", str(ddsp), "--json", str(output)],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_source"] == "ddsp"
    assert payload["counts"]["resolved"] == 1
    assert payload["binding_results"][0]["evidence"].startswith("Synthetic.ddsp#")


def test_reference_d365_missing_input_exit_code(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["reference", "d365", str(tmp_path / "missing.docx"), "--json", str(tmp_path / "out.json")],
    )
    assert result.exit_code == 6
    assert "reference_input_missing" in result.output


def test_reference_d365_invalid_input_exit_code(tmp_path: Path) -> None:
    invalid = tmp_path / "broken.docx"
    invalid.write_bytes(b"this is not a zip-based document")
    result = runner.invoke(
        app,
        ["reference", "d365", str(invalid), "--json", str(tmp_path / "out.json")],
    )
    assert result.exit_code == 3
    assert "reference_container_invalid" in result.output
