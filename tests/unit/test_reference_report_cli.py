"""Synthetic report-shape, determinism and CLI tests for the reference inspector."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from docentric_copilot.cli.main import app
from docentric_copilot.reference import (
    PlatformHint,
    ReferenceLimits,
    SchemaSource,
    inspect_reference,
    inspect_reference_bytes,
    report_json,
)
from typer.testing import CliRunner

from tests.reference_fixtures import (
    MISSING_STORE_ITEM_ID,
    ControlSpec,
    ElementSpec,
    build_axpp,
    build_ddsp,
    build_docx,
    build_project_data,
    build_zip,
    project_data_parts,
)

runner = CliRunner()
LIMITS = ReferenceLimits()


def _report_fixture() -> tuple[bytes, bytes]:
    elements = (
        ElementSpec(2330169809, "Field", "MainData", "@Number"),
        ElementSpec(777, "Field", "MainData", "@Number"),
        ElementSpec(555, "Field", "MainData", "@Number"),
        ElementSpec(555, "List", "MainData", "Line"),
    )
    custom = project_data_parts(build_project_data(elements))
    controls = (
        ControlSpec(alias="Field", tag="Field", sdt_id=-1964797487, text="@Number"),
        ControlSpec(
            alias="Field",
            tag="Field",
            sdt_id=111,
            store_item_id=MISSING_STORE_ITEM_ID,
            text="@Missing",
        ),
        ControlSpec(alias="Field", tag="Field", sdt_id=999, text="@NoMetadata"),
        ControlSpec(alias="Field", tag="Field", sdt_id=555, text="@Collision"),
        ControlSpec(alias="Plain", tag="plain", sdt_id=777, text="not a Docentric marker"),
    )
    docx = build_docx(document_controls=controls, custom_parts=custom)
    return docx, build_ddsp()


def test_report_shape_counts_and_runtime_status() -> None:
    docx, ddsp = _report_fixture()
    report = inspect_reference_bytes(
        docx,
        filename="Synthetic.Report.docx",
        limits=LIMITS,
        ddsp_data=ddsp,
        ddsp_name="Synthetic.Report.ddsp",
    )

    assert report.reference_version == "1.0"
    assert report.runtime_compatibility == "not_tested"
    assert report.source_type.value == "docx"
    assert report.source_name == "Synthetic.Report.docx"
    assert len(report.documents) == 1
    document = report.documents[0]
    assert document.control_count == 5
    assert document.schema_source is SchemaSource.DDSP
    assert document.schema_sections == ["GeneralData", "MainData"]
    assert document.schema_paths > 0
    assert len(document.controls) == 5
    assert report.counts.controls_total == 5
    assert report.counts.resolved == 2
    assert report.counts.missing_part == 1
    assert report.counts.unknown_path == 1
    assert report.counts.ambiguous == 1
    assert report.counts.joined_by_id == 2
    assert report.counts.coverage_ratio == 0.4
    assert report.counts.join_coverage_ratio == 0.4
    assert report.counts.by_element_kind["field"] == 4
    assert report.counts.by_classification["unknown"] == 1
    assert len(report.report_digest) == 64
    assert report.report_digest != "0" * 64


def test_report_is_deterministic_and_json_serialisable() -> None:
    docx, ddsp = _report_fixture()
    first = inspect_reference_bytes(
        docx,
        filename="Synthetic.Report.docx",
        limits=LIMITS,
        ddsp_data=ddsp,
        ddsp_name="Synthetic.Report.ddsp",
    )
    second = inspect_reference_bytes(
        docx,
        filename="Synthetic.Report.docx",
        limits=LIMITS,
        ddsp_data=ddsp,
        ddsp_name="Synthetic.Report.ddsp",
    )
    assert report_json(first) == report_json(second)
    payload = json.loads(report_json(first))
    assert payload["reference_version"] == "1.0"
    assert payload["runtime_compatibility"] == "not_tested"
    assert payload["counts"]["controls_total"] == 5
    assert payload["documents"][0]["controls"][0]["resolution"]["status"] in {
        "resolved",
        "missing_part",
        "unknown_path",
        "ambiguous",
    }


def test_unresolved_controls_produce_diagnostics_but_are_kept() -> None:
    docx, ddsp = _report_fixture()
    report = inspect_reference_bytes(
        docx,
        filename="Synthetic.Report.docx",
        limits=LIMITS,
        ddsp_data=ddsp,
        ddsp_name="Synthetic.Report.ddsp",
    )
    controls = report.documents[0].controls
    assert len(controls) == 5
    assert all(control.resolution is not None for control in controls)
    codes = {diagnostic.code for diagnostic in report.diagnostics}
    assert "control_missing_part" in codes
    assert "control_unknown_path" in codes
    assert "control_ambiguous" in codes
    assert "control_classification_unknown" in codes


def test_axpp_report_has_backslash_free_paths_and_d365_hint() -> None:
    docx, _ddsp = _report_fixture()
    axpp = build_axpp(docx)
    report = inspect_reference_bytes(axpp, filename="Synthetic.axpp", limits=LIMITS, max_depth=0)

    assert report.source_type.value == "axpp"
    assert report.counts.distinct_docx == 1
    assert report.container.platform is PlatformHint.D365
    assert all(
        entry.kind.value != "docx" or "\\" not in entry.path for entry in report.inventory.entries
    )
    assert report.documents[0].platform is PlatformHint.D365
    assert report.documents[0].schema_source is SchemaSource.NONE


def test_directory_report_deduplicates_documents_but_keeps_provenance(tmp_path: Path) -> None:
    docx, _ddsp = _report_fixture()
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "Synthetic.Report.docx").write_bytes(docx)
    (tmp_path / "b" / "Synthetic.Report.docx").write_bytes(docx)

    report = inspect_reference(tmp_path, limits=LIMITS, max_depth=0)

    assert report.counts.distinct_docx == 1
    assert report.counts.docx_artifacts == 2
    assert report.counts.duplicate_groups == 1
    assert report.counts.duplicate_occurrences == 1
    assert report.documents[0].paths == [
        "a/Synthetic.Report.docx",
        "b/Synthetic.Report.docx",
    ]
    assert report.documents[0].control_count == 5


def test_nested_archive_guard_reported_in_report() -> None:
    from tests.reference_fixtures import build_zip

    docx, _ddsp = _report_fixture()
    nested = build_zip({"inner.zip": build_zip({"Synthetic.Report.docx": docx})})
    report = inspect_reference_bytes(nested, filename="outer.zip", limits=LIMITS, max_depth=0)
    assert report.counts.distinct_docx == 0
    assert report.counts.nested_archives == 1
    assert any(
        "recursion_guard:nested_archive_not_expanded" in entry.warnings
        for entry in report.inventory.entries
    )


def test_cli_writes_json_report(tmp_path: Path) -> None:
    docx, _ddsp = _report_fixture()
    source = tmp_path / "Synthetic.Report.docx"
    output = tmp_path / "report.json"
    source.write_bytes(docx)

    result = runner.invoke(
        app,
        ["reference", "inspect", str(source), "--json", str(output)],
    )

    assert result.exit_code == 0, result.stdout
    assert output.exists()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["counts"]["controls_total"] == 5
    assert payload["runtime_compatibility"] == "not_tested"
    assert "Runtime compatibility: not_tested" in result.stdout


def test_cli_schema_report_shows_real_ddsp_evidence(tmp_path: Path) -> None:
    from tests.reference_fixtures import build_reference_ddsp

    docx, _ddsp = _report_fixture()
    source = tmp_path / "Synthetic.Report.docx"
    schema = tmp_path / "Synthetic.Report.ddsp"
    source.write_bytes(docx)
    schema.write_bytes(build_reference_ddsp())
    result = runner.invoke(
        app,
        [
            "reference",
            "inspect",
            str(source),
            "--ddsp",
            str(schema),
            "--schema-report",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "Schema:" in result.stdout
    assert "Root: dataSourcePackage" in result.stdout
    assert "Sections:" in result.stdout
    assert "Unsupported: xsd:any" in result.stdout


def test_cli_schema_report_is_not_emitted_with_stdout_json(tmp_path: Path) -> None:
    from tests.reference_fixtures import build_reference_ddsp

    docx, _ddsp = _report_fixture()
    source = tmp_path / "Synthetic.Report.docx"
    schema = tmp_path / "Synthetic.Report.ddsp"
    source.write_bytes(docx)
    schema.write_bytes(build_reference_ddsp())
    result = runner.invoke(
        app,
        [
            "reference",
            "inspect",
            str(source),
            "--ddsp",
            str(schema),
            "--schema-report",
            "--json",
            "-",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["documents"][0]["schema_evidence"]["schema_format"] == "bare-ddsp"


def test_cli_json_to_stdout(tmp_path: Path) -> None:
    docx, _ddsp = _report_fixture()
    source = tmp_path / "Synthetic.Report.docx"
    source.write_bytes(docx)
    result = runner.invoke(
        app,
        ["reference", "inspect", str(source), "--json", "-"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["source_name"] == "Synthetic.Report.docx"


def test_cli_invalid_input_and_missing_path_exit_codes(tmp_path: Path) -> None:
    broken = tmp_path / "broken.docx"
    broken.write_bytes(b"not a docx")
    invalid = runner.invoke(app, ["reference", "inspect", str(broken)])
    assert invalid.exit_code == 3
    assert "error" in (invalid.stdout + invalid.stderr).lower()

    missing = runner.invoke(app, ["reference", "inspect", str(tmp_path / "missing.docx")])
    assert missing.exit_code == 6


def test_cli_unsupported_suffix_exits_three(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("text", encoding="utf-8")
    result = runner.invoke(app, ["reference", "inspect", str(source)])
    assert result.exit_code == 3


def test_cli_max_depth_guard(tmp_path: Path) -> None:
    from tests.reference_fixtures import build_zip

    docx, _ddsp = _report_fixture()
    source = tmp_path / "outer.zip"
    source.write_bytes(build_zip({"nested/inner.zip": build_zip({"Synthetic.Report.docx": docx})}))

    shallow = runner.invoke(
        app,
        ["reference", "inspect", str(source), "--max-depth", "0", "--json", "-"],
    )
    assert shallow.exit_code == 0
    assert json.loads(shallow.stdout)["counts"]["distinct_docx"] == 0

    deep = runner.invoke(
        app,
        ["reference", "inspect", str(source), "--max-depth", "1", "--json", "-"],
    )
    assert deep.exit_code == 0
    assert json.loads(deep.stdout)["counts"]["distinct_docx"] == 1


def test_cli_rejects_out_of_range_depth(tmp_path: Path) -> None:
    docx, _ddsp = _report_fixture()
    source = tmp_path / "Synthetic.Report.docx"
    source.write_bytes(docx)
    result = runner.invoke(app, ["reference", "inspect", str(source), "--max-depth", "9"])
    assert result.exit_code == 2


def test_platform_is_derived_from_ax2012_schema() -> None:
    docx, ddsp = _report_fixture()
    report = inspect_reference_bytes(
        docx,
        filename="Synthetic.Report.docx",
        limits=LIMITS,
        ddsp_data=ddsp,
        ddsp_name="Synthetic.Report.ddsp",
    )
    assert report.documents[0].platform is PlatformHint.AX_2012


def test_default_limits_are_used_when_none_are_supplied() -> None:
    docx, _ddsp = _report_fixture()
    report = inspect_reference_bytes(docx, filename="Synthetic.Report.docx")
    assert report.counts.controls_total == 5
    assert report.runtime_compatibility == "not_tested"


def test_explicit_ddsp_unmatched_is_a_warning_for_multiple_docs() -> None:
    docx, _ddsp = _report_fixture()
    second = build_docx(
        document_controls=(ControlSpec(alias="Label", tag="Label", sdt_id=900, text="second"),)
    )
    bundle = build_zip(
        {
            "Alpha.Report.docx": docx,
            "Beta.Report.docx": second,
            "Gamma.ddsp": build_ddsp(),
        }
    )
    report = inspect_reference_bytes(
        bundle,
        filename="bundle.zip",
        limits=LIMITS,
        max_depth=0,
        ddsp_data=build_ddsp(),
        ddsp_name="Gamma.ddsp",
    )
    assert report.counts.distinct_docx == 2
    assert any("explicit_ddsp_unmatched:Gamma.ddsp" in warning for warning in report.warnings)
    assert any(diagnostic.code == "schema_warning" for diagnostic in report.diagnostics)


def test_malformed_sibling_ddsp_is_diagnosed_not_fatal() -> None:
    docx, _ddsp = _report_fixture()
    bundle = build_zip(
        {
            "Synthetic.Report.docx": docx,
            "Synthetic.Report.ddsp": b"<broken",
        }
    )
    report = inspect_reference_bytes(bundle, filename="bundle.zip", limits=LIMITS, max_depth=0)
    assert report.counts.distinct_docx == 1
    assert report.documents[0].schema_source is SchemaSource.NONE
    assert any("ddsp_unreadable:Synthetic.Report.ddsp" in warning for warning in report.warnings)


def test_explicit_malformed_ddsp_is_invalid_input() -> None:
    from docentric_copilot.errors import InvalidInputError

    docx, _ddsp = _report_fixture()
    with pytest.raises(InvalidInputError):
        inspect_reference_bytes(
            docx,
            filename="Synthetic.Report.docx",
            limits=LIMITS,
            ddsp_data=b"<broken",
            ddsp_name="Synthetic.Report.ddsp",
        )


def test_docx_without_controls_has_zero_coverage() -> None:
    empty = build_docx()
    report = inspect_reference_bytes(empty, filename="Empty.docx", limits=LIMITS)
    assert report.counts.controls_total == 0
    assert report.counts.coverage_ratio == 0.0
    assert report.counts.join_coverage_ratio == 0.0
    assert report.documents[0].control_count == 0
    assert report.documents[0].coverage_ratio == 0.0


def test_report_json_is_sorted_and_stable() -> None:
    docx, ddsp = _report_fixture()
    report = inspect_reference_bytes(
        docx,
        filename="Synthetic.Report.docx",
        limits=LIMITS,
        ddsp_data=ddsp,
        ddsp_name="Synthetic.Report.ddsp",
    )
    text = report_json(report)
    payload = json.loads(text)
    assert list(payload)[:4] == sorted(payload)[:4]
    assert text.endswith("\n")
