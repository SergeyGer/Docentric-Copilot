"""Synthetic REF-04 tests for ReferenceDiff v1.0."""

from __future__ import annotations

import json
from pathlib import Path

from docentric_copilot.reference import (
    ChangeType,
    DiffItemKind,
    GraphStatus,
    ReferenceLimits,
    build_reference_diff,
    diff_json,
    inspect_reference_bytes_bundle,
)

from tests.reference_fixtures import (
    ControlSpec,
    ElementSpec,
    build_docx,
    build_project_data,
    build_reference_ddsp,
    project_data_parts,
)

LIMITS = ReferenceLimits()


def _bundles():
    left_elements = (
        ElementSpec(1000, "Field", "MainData", "@Number"),
        ElementSpec(1001, "List", "MainData", "Lines/Line", child_ids=(1002,)),
        ElementSpec(1002, "Field", ".", "@Sku"),
        ElementSpec(1003, "Field", "MainData", "@Number"),
    )
    right_elements = (
        ElementSpec(1000, "Field", "MainData", "@NetAmount"),
        ElementSpec(1001, "List", "MainData", "Lines/Line", child_ids=(1002,)),
        ElementSpec(1002, "Field", ".", "@Sku"),
        ElementSpec(1003, "Field", "MainData", "@Number", result_data_type="System.String"),
        ElementSpec(1003, "Field", "MainData", "@Number", result_data_type="System.Int32"),
        ElementSpec(2000, "Field", "MainData", "@CopyCount"),
    )
    base_controls = (
        ControlSpec(alias="Field", tag="Field", sdt_id=1000, text="number"),
        ControlSpec(alias="List", tag="List", sdt_id=1001, text="lines"),
        ControlSpec(alias="Field", tag="Field", sdt_id=1002, text="sku"),
        ControlSpec(alias="Field", tag="Field", sdt_id=1003, text="ambiguous"),
    )
    left_docx = build_docx(
        document_controls=base_controls,
        custom_parts=project_data_parts(build_project_data(left_elements)),
    )
    right_docx = build_docx(
        document_controls=(
            *base_controls,
            ControlSpec(alias="Field", tag="Field", sdt_id=2000, text="copies"),
        ),
        custom_parts=project_data_parts(build_project_data(right_elements)),
    )
    ddsp = build_reference_ddsp()
    left = inspect_reference_bytes_bundle(
        left_docx,
        filename="Synthetic.Left.docx",
        limits=LIMITS,
        ddsp_data=ddsp,
        ddsp_name="Synthetic.Left.ddsp",
    )
    right = inspect_reference_bytes_bundle(
        right_docx,
        filename="Synthetic.Right.docx",
        limits=LIMITS,
        ddsp_data=ddsp,
        ddsp_name="Synthetic.Right.ddsp",
    )
    return left, right


def _items_by_key(diff):
    return {item.key: item for item in diff.items}


def test_diff_contract_and_classification() -> None:
    left, right = _bundles()
    diff = build_reference_diff(left, right)

    assert diff.diff_version == "1.0"
    assert diff.reference_version == "1.0"
    assert diff.runtime_compatibility == "not_tested"
    assert diff.ir_kind == "reference"
    assert diff.compilable is False
    assert diff.diff_digest != "0" * 64
    assert diff.summary.total == len(diff.items)
    assert diff.structural.total + diff.semantic.total == diff.summary.total
    assert diff.semantic.total >= 2
    assert diff.structural.total >= 2

    items = _items_by_key(diff)
    # One binding path changes; the control and element keys stay stable.
    binding = items["binding:element:customXml/item5.xml:1000"]
    assert binding.change is ChangeType.CHANGED
    assert binding.dimension.value == "semantic"
    assert "binding_path" in binding.fields
    assert binding.before is not None and binding.after is not None
    assert binding.before.binding_path == "MainData.Order.@Number"
    assert binding.after.binding_path == "MainData.Order.@NetAmount"
    assert binding.before.status is GraphStatus.RESOLVED
    assert binding.after.status is GraphStatus.RESOLVED

    control = items["control:word/document.xml:1000"]
    assert control.change is ChangeType.CHANGED
    assert control.dimension.value == "semantic"
    assert "binding_path" in control.fields

    # One control is added: presence changes are structural, not semantic.
    added = items["control:word/document.xml:2000"]
    assert added.change is ChangeType.ADDED
    assert added.kind is DiffItemKind.CONTROL
    assert added.dimension.value == "structural"
    assert added.before is None
    assert added.after is not None
    assert added.after.part == "word/document.xml"
    assert added.key not in diff.semantic.keys

    # One control becomes ambiguous: status is a semantic change.
    ambiguous = items["control:word/document.xml:1003"]
    assert ambiguous.change is ChangeType.CHANGED
    assert ambiguous.dimension.value == "semantic"
    assert ambiguous.before is not None and ambiguous.after is not None
    assert ambiguous.before.status is GraphStatus.RESOLVED
    assert ambiguous.after.status is GraphStatus.AMBIGUOUS
    assert diff.summary.status_transitions["resolved->ambiguous"] >= 1
    assert diff.summary.ambiguous >= 1

    # Structural and semantic partitions carry exactly their own keys.
    assert set(diff.structural.keys).isdisjoint(diff.semantic.keys)
    assert set(diff.structural.keys) | set(diff.semantic.keys) == set(items)


def test_diff_ordering_digest_and_duplicate_runs() -> None:
    left, right = _bundles()
    first = build_reference_diff(left, right)
    second = build_reference_diff(left, right)
    assert diff_json(first) == diff_json(second)
    assert first.diff_digest == second.diff_digest

    payload = json.loads(diff_json(first))
    assert payload["diff_version"] == "1.0"
    assert payload["runtime_compatibility"] == "not_tested"
    assert payload["compilable"] is False
    assert payload["items"] == sorted(
        payload["items"],
        key=lambda item: (
            {"control": 0, "element": 1, "binding": 2, "source": 3, "schema_field": 4}[
                item["kind"]
            ],
            {"added": 0, "removed": 1, "changed": 2}[item["change"]],
            item["key"],
        ),
    )
    assert str(left.report.source_name) not in json.dumps(payload["items"])


def test_diff_counts_coverage_and_unresolved_deltas() -> None:
    left, right = _bundles()
    diff = build_reference_diff(left, right)
    assert diff.counts.controls.left == 4
    assert diff.counts.controls.right == 5
    assert diff.counts.controls.delta == 1
    assert diff.counts.elements.delta >= 2
    assert diff.counts.parts.left == diff.counts.parts.right
    assert 0.0 <= diff.coverage_delta.left_edge_coverage <= 1.0
    assert 0.0 <= diff.coverage_delta.right_edge_coverage <= 1.0
    assert diff.coverage_delta.edge_delta == round(
        diff.coverage_delta.right_edge_coverage - diff.coverage_delta.left_edge_coverage, 4
    )
    assert diff.unresolved_delta == diff.unresolved.right - diff.unresolved.left
    assert diff.unresolved_delta == (
        len(diff.unresolved.added_keys) - len(diff.unresolved.removed_keys)
    )


def test_identical_content_under_different_names_has_no_false_version() -> None:
    left, right = _bundles()
    diff = build_reference_diff(left.report, right.report)
    # Reports without the side-channel schema still produce a valid diff; paths
    # differ because the right graph has no schema fields in this call.
    assert diff.summary.total >= 1

    left_docx = build_docx(
        document_controls=(ControlSpec(alias="Field", tag="Field", sdt_id=1000, text="number"),),
        custom_parts=project_data_parts(
            build_project_data((ElementSpec(1000, "Field", "MainData", "@Number"),))
        ),
    )
    ddsp = build_reference_ddsp()
    first = inspect_reference_bytes_bundle(
        left_docx,
        filename="First.docx",
        limits=LIMITS,
        ddsp_data=ddsp,
    )
    second = inspect_reference_bytes_bundle(
        left_docx,
        filename="Renamed.docx",
        limits=LIMITS,
        ddsp_data=ddsp,
    )
    identical = build_reference_diff(first, second)
    assert identical.summary.total == 0
    assert identical.items == []
    assert identical.diff_digest == build_reference_diff(first, second).diff_digest


def test_diff_paths_and_cli(tmp_path: Path) -> None:
    from docentric_copilot.cli.main import app
    from typer.testing import CliRunner

    left_path = tmp_path / "Synthetic.Left.docx"
    right_path = tmp_path / "Synthetic.Right.docx"
    schema_path = tmp_path / "Synthetic.ddsp"
    left_path.write_bytes(
        build_docx(
            document_controls=(
                ControlSpec(alias="Field", tag="Field", sdt_id=1000, text="number"),
            ),
            custom_parts=project_data_parts(
                build_project_data((ElementSpec(1000, "Field", "MainData", "@Number"),))
            ),
        )
    )
    right_path.write_bytes(
        build_docx(
            document_controls=(
                ControlSpec(alias="Field", tag="Field", sdt_id=1000, text="number"),
                ControlSpec(alias="Field", tag="Field", sdt_id=2000, text="copies"),
            ),
            custom_parts=project_data_parts(
                build_project_data(
                    (
                        ElementSpec(1000, "Field", "MainData", "@Number"),
                        ElementSpec(2000, "Field", "MainData", "@CopyCount"),
                    )
                )
            ),
        )
    )
    schema_path.write_bytes(build_reference_ddsp())
    alias_diff = build_reference_diff(left_path, right_path, ddsp_path=schema_path)
    assert alias_diff.summary.added >= 1
    output = tmp_path / "diff.json"
    result = CliRunner().invoke(
        app,
        [
            "reference",
            "diff",
            str(left_path),
            str(right_path),
            "--ddsp",
            str(schema_path),
            "--json",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "ReferenceDiff" in result.stdout
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["diff_version"] == "1.0"
    assert payload["summary"]["added"] >= 1
    assert payload["runtime_compatibility"] == "not_tested"
    assert str(tmp_path) not in output.read_text(encoding="utf-8")


def test_diff_rejects_missing_path(tmp_path: Path) -> None:
    from docentric_copilot.cli.main import app
    from typer.testing import CliRunner

    missing = tmp_path / "missing.docx"
    result = CliRunner().invoke(app, ["reference", "diff", str(missing), str(missing)])
    assert result.exit_code in {3, 6}
