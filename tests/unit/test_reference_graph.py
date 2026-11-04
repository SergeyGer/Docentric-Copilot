"""Synthetic REF-03 tests for ReferenceGraph and the read-only projection."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from docentric_copilot.reference import (
    EdgeType,
    ElementKind,
    GraphStatus,
    NodeKind,
    ReferenceCapability,
    ReferenceLimits,
    build_reference_graph,
    graph_json,
    inspect_reference_bytes_bundle,
    parse_real_ddsp,
    project_graph,
    projection_json,
)
from docentric_copilot.reference.projection import ReferenceDocument

from tests.reference_fixtures import (
    ControlSpec,
    ElementSpec,
    build_docx,
    build_project_data,
    build_reference_ddsp,
    project_data_parts,
)

LIMITS = ReferenceLimits()


def _bundle():
    elements = (
        ElementSpec(
            1000,
            "List",
            "MainData",
            "Lines/Line",
            child_ids=(1001, 1002, 1003),
        ),
        ElementSpec(1001, "Field", ".", "@Sku"),
        ElementSpec(1002, "If", "MainData", "@IsPaid", child_ids=(1004,)),
        ElementSpec(1003, "Image", "GeneralData", "Company/@Logo"),
        ElementSpec(1004, "Field", "MainData", "@NetAmount"),
        ElementSpec(
            1005,
            "Label",
            "MainData",
            "@Number",
            properties={"LabelName": "Order number", "LabelCode": "@SYN002"},
        ),
        ElementSpec(1006, "Field", "MainData", "@Missing"),
        ElementSpec(1007, "Field", "MainData", "@Number"),
        ElementSpec(1007, "List", "MainData", "Lines/Line"),
    )
    custom = project_data_parts(build_project_data(elements))
    controls = (
        ControlSpec(alias="List", tag="List", sdt_id=1000, text="lines"),
        ControlSpec(alias="Field", tag="Field", sdt_id=1001, text="@Sku"),
        ControlSpec(alias="If", tag="If", sdt_id=1002, text="condition"),
        ControlSpec(alias="Image", tag="Image", sdt_id=1003, text="logo"),
        ControlSpec(alias="Field", tag="Field", sdt_id=1004, text="@NetAmount"),
        ControlSpec(alias="Label", tag="Label", sdt_id=1005, text="Order number"),
        ControlSpec(alias="Field", tag="Field", sdt_id=1006, text="@Missing"),
        ControlSpec(alias="Field", tag="Field", sdt_id=1007, text="@Collision"),
        ControlSpec(alias="Plain", tag="plain", sdt_id=999, text="unknown control"),
    )
    docx = build_docx(document_controls=controls, custom_parts=custom)
    return inspect_reference_bytes_bundle(
        docx,
        filename="Synthetic.Report.docx",
        limits=LIMITS,
        ddsp_data=build_reference_ddsp(),
        ddsp_name="Synthetic.Report.ddsp",
    )


def _has_cycle(graph) -> bool:
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        if edge.type in {EdgeType.ITERATES, EdgeType.CONDITION}:
            adjacency[edge.source].append(edge.target)
    state: dict[str, int] = {}

    def visit(node: str) -> bool:
        state[node] = 1
        for target in adjacency.get(node, []):
            if state.get(target) == 1:
                return True
            if state.get(target, 0) == 0 and visit(target):
                return True
        state[node] = 2
        return False

    return any(state.get(node, 0) == 0 and visit(node) for node in list(adjacency))


def test_graph_has_all_node_and_edge_kinds() -> None:
    bundle = _bundle()
    graph = build_reference_graph(bundle.report, bundle.schemas)

    assert graph.graph_version == "1.0"
    assert graph.reference_version == "1.0"
    assert graph.runtime_compatibility == "not_tested"
    assert graph.ir_kind == "reference"
    assert graph.compilable is False
    assert graph.schema_source.value == "ddsp"
    kinds = {node.kind for node in graph.nodes}
    assert kinds == {
        NodeKind.CONTROL,
        NodeKind.ELEMENT,
        NodeKind.SOURCE,
        NodeKind.SCHEMA_FIELD,
    }
    edge_types = {edge.type for edge in graph.edges}
    assert edge_types == {
        EdgeType.BOUND_TO,
        EdgeType.RESOLVES_TO,
        EdgeType.ITERATES,
        EdgeType.CONDITION,
    }
    statuses = {edge.status for edge in graph.edges}
    assert statuses == {GraphStatus.RESOLVED, GraphStatus.AMBIGUOUS, GraphStatus.UNKNOWN}


def test_graph_counts_controls_and_preserves_unresolved() -> None:
    bundle = _bundle()
    graph = build_reference_graph(bundle.report, bundle.schemas)
    summary = graph.summary
    assert summary.controls_total == 9
    assert summary.controls_resolved + summary.controls_ambiguous + summary.controls_unknown == 9
    assert summary.controls_resolved >= 5
    assert summary.controls_ambiguous >= 1
    assert summary.controls_unknown >= 1
    assert summary.unresolved_total >= 2
    reasons = {item.reason for item in graph.unresolved}
    assert any("unknown" in reason or "missing" in reason for reason in reasons)
    assert any(item.status is GraphStatus.AMBIGUOUS for item in graph.unresolved) or any(
        edge.status is GraphStatus.AMBIGUOUS for edge in graph.edges
    )
    assert all(node.id and node.kind for node in graph.nodes)


def test_iterates_and_condition_edges_connect_children() -> None:
    bundle = _bundle()
    graph = build_reference_graph(bundle.report, bundle.schemas)
    nodes = {node.id: node for node in graph.nodes}
    iterates = [edge for edge in graph.edges if edge.type is EdgeType.ITERATES]
    conditions = [edge for edge in graph.edges if edge.type is EdgeType.CONDITION]
    assert len(iterates) == 3
    assert len(conditions) == 1
    list_edge = next(
        edge for edge in iterates if nodes[edge.source].element_kind is ElementKind.LIST
    )
    assert nodes[list_edge.source].element_id == "1000"
    condition_edge = conditions[0]
    assert nodes[condition_edge.source].element_id == "1002"
    assert nodes[condition_edge.target].element_id == "1004"
    assert graph.structures.lists
    assert graph.structures.conditions
    assert graph.summary.lists_detected == 2
    assert graph.summary.conditions_detected == 1
    assert not _has_cycle(graph)


def test_schema_fields_carry_type_and_collection() -> None:
    bundle = _bundle()
    graph = build_reference_graph(bundle.report, bundle.schemas)
    schema_nodes = {
        node.schema_path: node for node in graph.nodes if node.kind is NodeKind.SCHEMA_FIELD
    }
    assert "MainData.Order.Lines.Line" in schema_nodes
    assert schema_nodes["MainData.Order.Lines.Line"].collection is True
    assert schema_nodes["MainData.Order.@NetAmount"].data_type == "number"
    assert schema_nodes["GeneralData.GeneralData.Company.@Logo"].data_type == "image"
    assert schema_nodes["MainData.Order.@IsPaid"].data_type == "boolean"
    # Unknown paths are preserved as explicit, unresolved schema-field nodes.
    assert any(
        node.kind is NodeKind.SCHEMA_FIELD and node.status is GraphStatus.UNKNOWN
        for node in graph.nodes
    )


def test_graph_serialization_is_stable() -> None:
    bundle = _bundle()
    first = build_reference_graph(bundle.report, bundle.schemas)
    second = build_reference_graph(bundle.report, bundle.schemas)
    assert graph_json(first) == graph_json(second)
    assert first.graph_digest == second.graph_digest
    assert first.graph_digest != "0" * 64
    node_ranks = [
        {"control": 0, "element": 1, "source": 2, "schema_field": 3}[node.kind.value]
        for node in first.nodes
    ]
    assert node_ranks == sorted(node_ranks)


def test_graph_without_schema_keeps_controls_and_no_schema_nodes() -> None:
    bundle = _bundle()
    graph = build_reference_graph(bundle.report)
    assert graph.schema_source.value == "none"
    assert not any(node.kind is NodeKind.SCHEMA_FIELD for node in graph.nodes)
    assert any(edge.type is EdgeType.BOUND_TO for edge in graph.edges)
    assert any(item.code == "graph_schema_not_provided" for item in graph.diagnostics)


def test_graph_fallback_schema_parameter() -> None:
    bundle = _bundle()
    artifact = parse_real_ddsp(build_reference_ddsp(), name="Synthetic.Report.ddsp", limits=LIMITS)
    graph = build_reference_graph(bundle.report, schema=artifact.schema)
    assert any(node.kind is NodeKind.SCHEMA_FIELD for node in graph.nodes)
    assert graph.schema_ids == ["synthetic_report"]


def test_projection_shape_and_capabilities() -> None:
    bundle = _bundle()
    graph = build_reference_graph(bundle.report, bundle.schemas)
    document = project_graph(graph)

    assert isinstance(document, ReferenceDocument)
    assert document.projection_version == "1.0"
    assert document.ir_kind == "reference"
    assert document.compilable is False
    assert document.template_ir_compatible is False
    assert "not Template IR" in document.note
    assert document.runtime_compatibility == "not_tested"
    assert document.graph_digest == graph.graph_digest
    assert document.summary.sections == 1
    assert document.summary.elements == graph.summary.controls_total
    assert document.summary.by_kind["list"] >= 1
    assert document.summary.by_kind["if"] >= 1
    assert document.summary.by_kind["image"] >= 1
    assert document.summary.by_kind["label"] >= 1
    assert document.summary.ambiguous >= 1
    assert document.summary.unknown >= 1
    assert document.summary.importable == 0
    assert document.summary.by_capability["reference_only"] >= 1
    assert document.summary.by_capability["unsupported"] >= 1
    assert "importable" not in {
        element.capability.value for element in document.sections[0].elements
    }


def test_projection_preserves_labels_paths_locations_and_statuses() -> None:
    bundle = _bundle()
    graph = build_reference_graph(bundle.report, bundle.schemas)
    document = project_graph(graph)
    elements = document.sections[0].elements
    by_label = {element.display_label: element for element in elements}
    assert by_label["Order number"].kind is ElementKind.LABEL
    list_element = next(element for element in elements if element.kind is ElementKind.LIST)
    assert list_element.binding_path == "MainData.Order.Lines.Line"
    assert list_element.collection is True
    assert list_element.source_name == "MainData"
    assert list_element.source_location.part.endswith("document.xml")
    assert list_element.source_location.ordinal >= 0
    assert all(element.source_location.part for element in elements)
    assert any(element.status is GraphStatus.AMBIGUOUS for element in elements)
    assert any(element.status is GraphStatus.UNKNOWN for element in elements)
    assert all(element.capability is not ReferenceCapability.IMPORTABLE for element in elements)
    unknown = next(element for element in elements if element.kind is ElementKind.UNKNOWN)
    assert unknown.capability is ReferenceCapability.UNSUPPORTED


def test_projection_is_deterministic_and_json_serialisable() -> None:
    bundle = _bundle()
    first = project_graph(build_reference_graph(bundle.report, bundle.schemas))
    second = project_graph(build_reference_graph(bundle.report, bundle.schemas))
    assert projection_json(first) == projection_json(second)
    assert first.projection_digest == second.projection_digest
    assert first.projection_digest != "0" * 64
    assert projection_json(first).endswith("\n")


def test_cli_graph_writes_graph_and_projection(tmp_path: Path) -> None:
    from docentric_copilot.cli.main import app
    from typer.testing import CliRunner

    elements = (
        ElementSpec(1000, "List", "MainData", "Lines/Line", child_ids=(1001,)),
        ElementSpec(1001, "Field", ".", "@Sku"),
    )
    custom = project_data_parts(build_project_data(elements))
    controls = (
        ControlSpec(alias="List", tag="List", sdt_id=1000),
        ControlSpec(alias="Field", tag="Field", sdt_id=1001),
    )
    docx = build_docx(document_controls=controls, custom_parts=custom)
    source = tmp_path / "Synthetic.Report.docx"
    schema = tmp_path / "Synthetic.Report.ddsp"
    source.write_bytes(docx)
    schema.write_bytes(build_reference_ddsp())
    graph_path = tmp_path / "graph.json"
    projection_path = tmp_path / "reference.json"

    result = CliRunner().invoke(
        app,
        [
            "reference",
            "graph",
            str(source),
            "--ddsp",
            str(schema),
            "--json",
            str(graph_path),
            "--projection",
            str(projection_path),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "ReferenceGraph" in result.stdout
    assert "not compilable" in result.stdout
    graph_payload = graph_path.read_text(encoding="utf-8")
    projection_payload = projection_path.read_text(encoding="utf-8")
    import json

    assert json.loads(graph_payload)["graph_version"] == "1.0"
    assert json.loads(projection_payload)["compilable"] is False
    assert json.loads(projection_payload)["ir_kind"] == "reference"


def test_cli_graph_invalid_input_exit_code(tmp_path: Path) -> None:
    from docentric_copilot.cli.main import app
    from typer.testing import CliRunner

    broken = tmp_path / "broken.docx"
    broken.write_bytes(b"not a docx")
    result = CliRunner().invoke(app, ["reference", "graph", str(broken)])
    assert result.exit_code == 3


def test_child_element_cycle_is_cut_with_a_diagnostic() -> None:
    elements = (
        ElementSpec(2000, "List", "MainData", "Lines/Line", child_ids=(2001,)),
        ElementSpec(2001, "List", "MainData", "Lines/Line", child_ids=(2000,)),
    )
    custom = project_data_parts(build_project_data(elements))
    controls = (
        ControlSpec(alias="List", tag="List", sdt_id=2000),
        ControlSpec(alias="List", tag="List", sdt_id=2001),
    )
    docx = build_docx(document_controls=controls, custom_parts=custom)
    bundle = inspect_reference_bytes_bundle(
        docx,
        filename="Cycle.docx",
        limits=LIMITS,
        ddsp_data=build_reference_ddsp(),
        ddsp_name="Cycle.ddsp",
    )
    graph = build_reference_graph(bundle.report, bundle.schemas)
    assert any(item.code == "graph_child_element_cycle" for item in graph.diagnostics)
    assert not _has_cycle(graph)
    cycle_edges = [edge for edge in graph.edges if edge.type is EdgeType.ITERATES]
    assert len(cycle_edges) == 1


def test_missing_child_reference_becomes_an_explicit_node() -> None:
    elements = (ElementSpec(3000, "List", "MainData", "Lines/Line", child_ids=(424242,)),)
    custom = project_data_parts(build_project_data(elements))
    controls = (ControlSpec(alias="List", tag="List", sdt_id=3000),)
    docx = build_docx(document_controls=controls, custom_parts=custom)
    bundle = inspect_reference_bytes_bundle(
        docx,
        filename="MissingChild.docx",
        limits=LIMITS,
        ddsp_data=build_reference_ddsp(),
        ddsp_name="MissingChild.ddsp",
    )
    graph = build_reference_graph(bundle.report, bundle.schemas)
    placeholder = next(node for node in graph.nodes if node.id.endswith("424242~missing"))
    assert placeholder.kind is NodeKind.ELEMENT
    assert placeholder.status is GraphStatus.UNKNOWN
    assert placeholder.reason == "child_element_missing"
    assert any(
        edge.type is EdgeType.ITERATES and edge.target == placeholder.id for edge in graph.edges
    )
    assert any(item.code == "graph_missing_child_element" for item in graph.diagnostics)
    assert any(item.node_id == placeholder.id for item in graph.unresolved)


def test_label_data_xpath_is_preserved_without_guessing_scope() -> None:
    elements = (
        ElementSpec(
            4000,
            "Label",
            None,
            None,
            properties={
                "LabelName": "Customer label",
                "DataXPath": "Customer/@Name",
                "DataSection": "1",
            },
        ),
    )
    custom = project_data_parts(build_project_data(elements))
    controls = (ControlSpec(alias="Label", tag="Label", sdt_id=4000),)
    docx = build_docx(document_controls=controls, custom_parts=custom)
    bundle = inspect_reference_bytes_bundle(
        docx,
        filename="Label.docx",
        limits=LIMITS,
        ddsp_data=build_reference_ddsp(),
        ddsp_name="Label.ddsp",
    )
    graph = build_reference_graph(bundle.report, bundle.schemas)
    element = next(
        node
        for node in graph.nodes
        if node.kind is NodeKind.ELEMENT and node.element_id == "4000"
    )
    assert element.binding_path == "Customer/@Name"
    assert element.status is GraphStatus.UNKNOWN
    document = project_graph(graph)
    projected = document.sections[0].elements[0]
    assert projected.binding_path == "Customer/@Name"
    assert projected.status is GraphStatus.UNKNOWN


def test_empty_graph_and_projection_are_valid() -> None:
    from tests.reference_fixtures import build_zip

    bundle = inspect_reference_bytes_bundle(
        build_zip({"notes.txt": b"no documents here"}),
        filename="bundle.zip",
        limits=LIMITS,
        max_depth=0,
    )
    graph = build_reference_graph(bundle.report, bundle.schemas)
    assert graph.summary.node_count == 0
    assert graph.summary.edge_count == 0
    assert graph.summary.controls_total == 0
    assert any(item.code == "graph_no_documents" for item in graph.diagnostics)
    document = project_graph(graph)
    assert document.sections == []
    assert document.summary.elements == 0
    assert document.summary.resolved_ratio == 0.0
