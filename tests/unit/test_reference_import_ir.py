"""Safe Reference -> Generic Template IR projection (#27).

All fixtures are synthetic test code; no Docentric corpus content is used.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from docentric_copilot.reference import (
    ImportSkipCode,
    ReferenceImportBlockedError,
    build_reference_graph,
    import_ir_json,
    inspect_reference_bundle,
    project_to_template_ir,
)

from tests.reference_fixtures import (
    ControlSpec,
    ElementSpec,
    EmbeddedDataSourceSpec,
    build_docx,
    build_embedded_project_data,
    project_data_parts,
)


def _docx(
    elements: tuple[ElementSpec, ...],
    *,
    sources: tuple[EmbeddedDataSourceSpec, ...] = (EmbeddedDataSourceSpec(),),
) -> bytes:
    project_data = build_embedded_project_data(elements, sources=sources)
    custom = project_data_parts(project_data, item_index=1)
    controls = tuple(
        ControlSpec(
            alias=element.element_type,
            tag=element.element_type,
            sdt_id=element.element_id,
        )
        for element in elements
    )
    return build_docx(document_controls=controls, custom_parts=custom)


def _supported_docx() -> bytes:
    elements = (
        ElementSpec(1, "Field", "MainData", "@Number", "System.String"),
        ElementSpec(2, "List", "MainData", "Lines/Line", None, child_ids=(3,)),
        ElementSpec(3, "Field", ".", "@ItemId", "System.String"),
        ElementSpec(4, "If", "MainData", "@IsPaid", "System.Boolean", child_ids=(5,)),
        ElementSpec(5, "Field", "MainData", "@Name", "System.String"),
        ElementSpec(6, "Image", "MainData", "@Logo", "System.Byte[]"),
        ElementSpec(
            7,
            "Label",
            "MainData",
            "@Number",
            "System.String",
            properties={"LabelName": "Order number"},
        ),
    )
    return _docx(elements)


def _ambiguous_docx() -> bytes:
    duplicate = (
        EmbeddedDataSourceSpec(name="MainData"),
        EmbeddedDataSourceSpec(name="MainData"),
    )
    elements = (ElementSpec(50, "Field", "MainData", "@Number", "System.String"),)
    return _docx(elements, sources=duplicate)


def _unsupported_docx() -> bytes:
    elements = (
        ElementSpec(60, "Barcode", "MainData", "@Number", "System.String"),
        ElementSpec(61, "Field", "MainData", "@Missing", "System.String"),
    )
    project_data = build_embedded_project_data(elements)
    custom = project_data_parts(project_data, item_index=1)
    controls = (
        ControlSpec(alias="Barcode", tag="Barcode", sdt_id=60),
        ControlSpec(alias="Field", tag="Field", sdt_id=61),
        ControlSpec(alias="Plain", tag="plain", sdt_id=99),
    )
    return build_docx(document_controls=controls, custom_parts=custom)


def _mixed_docx() -> bytes:
    elements = (
        ElementSpec(70, "Field", "MainData", "@Number", "System.String"),
        ElementSpec(71, "Barcode", "MainData", "@Number", "System.String"),
    )
    project_data = build_embedded_project_data(elements)
    custom = project_data_parts(project_data, item_index=1)
    controls = (
        ControlSpec(alias="Field", tag="Field", sdt_id=70),
        ControlSpec(alias="Barcode", tag="Barcode", sdt_id=71),
    )
    return build_docx(document_controls=controls, custom_parts=custom)


def _graph_for(path: Path):
    bundle = inspect_reference_bundle(path)
    return build_reference_graph(bundle.report, bundle.schemas, documents=bundle.payloads), bundle


def _write_all(tmp_path: Path) -> None:
    (tmp_path / "Supported.docx").write_bytes(_supported_docx())
    (tmp_path / "Ambiguous.docx").write_bytes(_ambiguous_docx())
    (tmp_path / "Unsupported.docx").write_bytes(_unsupported_docx())


def test_supported_subset_projects_and_validates(tmp_path: Path) -> None:
    (tmp_path / "Supported.docx").write_bytes(_supported_docx())
    graph, _ = _graph_for(tmp_path)
    result = project_to_template_ir(graph)

    assert result.runtime_compatibility == "not_tested"
    assert result.target == "generic-docx"
    assert result.summary.skipped == 0
    assert result.skipped == []
    assert result.validation["can_compile"] is True
    assert result.validation["statuses"] == {
        "structural": "passed",
        "semantic": "passed",
        "logical": "passed",
        "visual": "skipped",
        "docentric_compatibility": "not_tested",
    }
    assert result.validation["overall"] == "passed_unverified_compatibility"
    assert result.ir.target.value == "generic-docx"

    body = result.ir.sections[0].body
    kinds = [block.kind for block in body]
    assert "repeat" in kinds
    assert "conditional" in kinds
    assert kinds.count("paragraph") >= 2
    assert "image" in kinds
    repeat = next(block for block in body if block.kind == "repeat")
    assert repeat.path == "MainData.Root.Lines.Line"
    assert repeat.alias == "line"
    assert repeat.blocks[0].kind == "paragraph"
    conditional = next(block for block in body if block.kind == "conditional")
    assert conditional.condition.field == "MainData.Root.IsPaid"
    assert conditional.condition.operator.value == "equals"
    assert conditional.condition.value is True
    assert any(block.kind == "image" and block.path.endswith(".Logo") for block in body)
    labels = [
        run.text
        for block in body
        if block.kind == "paragraph"
        for run in block.runs
        if run.kind == "text"
    ]
    assert "Order number" in labels
    # Provenance covers every imported node and keeps the provider evidence.
    assert result.provenance
    field_provenance = [item for item in result.provenance if item.node_kind == "field"]
    assert field_provenance
    assert all(item.ir_path.startswith("sections[") for item in result.provenance)
    assert any(item.evidence_location for item in field_provenance)
    assert any(item.source_id for item in field_provenance)
    assert import_ir_json(result).endswith("\n")


def test_unsupported_and_ambiguous_are_rejected_by_default(tmp_path: Path) -> None:
    _write_all(tmp_path)
    graph, bundle = _graph_for(tmp_path)
    assert bundle.report.counts.controls_total >= 6
    with pytest.raises(ReferenceImportBlockedError) as caught:
        project_to_template_ir(graph)
    details = caught.value.details
    assert details["skipped_total"] >= 1
    codes = {item["code"] for item in details["skipped"]}
    assert {"AMBIGUOUS_BINDING", "UNSUPPORTED_ELEMENT_KIND", "UNKNOWN_PATH"} <= codes
    assert details["allow_unsupported"] is False


def test_allow_unsupported_keeps_subset_and_lists_every_skip(tmp_path: Path) -> None:
    _write_all(tmp_path)
    graph, _ = _graph_for(tmp_path)
    result = project_to_template_ir(graph, allow_unsupported=True)

    assert result.allow_unsupported is True
    assert result.summary.imported >= 1
    assert result.summary.skipped >= 4
    assert result.validation["can_compile"] is True
    codes = {item.code for item in result.skipped}
    assert ImportSkipCode.AMBIGUOUS_BINDING in codes
    assert ImportSkipCode.UNSUPPORTED_ELEMENT_KIND in codes
    assert ImportSkipCode.UNKNOWN_PATH in codes
    assert ImportSkipCode.UNKNOWN_ELEMENT in codes
    assert result.summary.by_skip_code
    for item in result.skipped:
        assert item.reason
        assert item.source_reference_id
    assert any(block.kind == "repeat" for block in result.ir.sections[0].body)


def test_no_reference_construct_is_dropped_silently(tmp_path: Path) -> None:
    _write_all(tmp_path)
    graph, _ = _graph_for(tmp_path)
    result = project_to_template_ir(graph, allow_unsupported=True)

    # Build the expected set from the projection used by the importer itself.
    from docentric_copilot.reference import project_graph

    projection = project_graph(graph)
    expected = {element.id for section in projection.sections for element in section.elements}
    accounted = {item.source_reference_id for item in result.skipped} | {
        item.source_reference_id for item in result.provenance
    }
    assert expected <= accounted
    assert result.summary.references == len(expected)
    assert result.summary.imported + result.summary.skipped >= len(expected)


def test_import_from_reference_document_matches_graph(tmp_path: Path) -> None:
    from docentric_copilot.reference import project_graph

    (tmp_path / "Supported.docx").write_bytes(_supported_docx())
    graph, _ = _graph_for(tmp_path)
    from_graph = project_to_template_ir(graph)
    from_document = project_to_template_ir(project_graph(graph))
    assert import_ir_json(from_graph) == import_ir_json(from_document)


def test_cli_import_ir_supported_and_strict_block(tmp_path: Path) -> None:
    from docentric_copilot.cli.main import app
    from typer.testing import CliRunner

    supported = tmp_path / "Supported.docx"
    supported.write_bytes(_supported_docx())
    mixed = tmp_path / "Mixed.docx"
    mixed.write_bytes(_mixed_docx())
    output = tmp_path / "import.json"

    success = CliRunner().invoke(
        app, ["reference", "import-ir", str(supported), "--json", str(output)]
    )
    assert success.exit_code == 0, success.stdout
    assert "Runtime compatibility: not_tested" in success.stdout
    assert "not compilable" not in success.stdout
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["ir"]["target"] == "generic-docx"
    assert payload["runtime_compatibility"] == "not_tested"
    assert payload["skipped"] == []

    blocked = CliRunner().invoke(app, ["reference", "import-ir", str(mixed), "--json", "-"])
    assert blocked.exit_code == 3, blocked.stdout
    error = json.loads(blocked.stdout.strip())
    assert error["error"]["code"] == "reference_import_blocked"
    assert error["error"]["details"]["skipped_total"] >= 1

    best_effort = CliRunner().invoke(
        app,
        [
            "reference",
            "import-ir",
            str(mixed),
            "--json",
            str(output),
            "--allow-unsupported",
        ],
    )
    assert best_effort.exit_code == 0, best_effort.stdout
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["allow_unsupported"] is True
    assert payload["skipped"]
    assert payload["ir"]["target"] == "generic-docx"


def test_import_json_is_deterministic(tmp_path: Path) -> None:
    (tmp_path / "Supported.docx").write_bytes(_supported_docx())
    graph, _ = _graph_for(tmp_path)
    first = import_ir_json(project_to_template_ir(graph))
    second = import_ir_json(project_to_template_ir(graph))
    assert first == second
    payload = json.loads(first)
    assert {
        "ir",
        "skipped",
        "provenance",
        "validation",
        "runtime_compatibility",
        "target",
        "summary",
    } <= set(payload)
    assert payload["runtime_compatibility"] == "not_tested"
    assert payload["ir"]["target"] == "generic-docx"
    assert payload["skipped"] == []


def test_unsupported_only_document_is_empty(tmp_path: Path) -> None:
    from docentric_copilot.reference import ReferenceImportEmptyError

    (tmp_path / "Unsupported.docx").write_bytes(_unsupported_docx())
    graph, _ = _graph_for(tmp_path)
    with pytest.raises(ReferenceImportEmptyError):
        project_to_template_ir(graph, allow_unsupported=True)
