"""Command line interface (FR-10).

Every command uses the same application service as the HTTP API, works headless,
never prints secrets and returns stable exit codes:

===  ==========================================================
0    success
1    validation or processing failure
2    usage error (raised by the CLI framework)
3    invalid or unsupported input file
4    unsupported compilation target
5    provider error (missing key, timeout, invalid output)
6    not found
===  ==========================================================
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from docentric_copilot import __version__
from docentric_copilot.app.service import TemplateService
from docentric_copilot.config import get_settings
from docentric_copilot.ddsp_parser import ParsedSource, parse_ddsp
from docentric_copilot.docx_compiler import CompileOptions
from docentric_copilot.errors import CopilotError, NotFoundError
from docentric_copilot.planner import PlanOptions, TemplatePlanner
from docentric_copilot.reference import (
    ReferenceLimits,
    ReferenceReport,
    inspect_reference,
    report_json,
)
from docentric_copilot.template_ir import (
    CompileTarget,
    document_json_schema,
    ir_digest,
    load_document,
)
from docentric_copilot.template_validator import ValidationEngine, render_report_html

app = typer.Typer(
    name="docentric-copilot",
    help="Schema-aware prompt-to-template engine for enterprise document automation.",
    no_args_is_help=True,
    add_completion=False,
    # Never echo local variables: a traceback could contain sample business data.
    pretty_exceptions_enable=False,
)

reference_app = typer.Typer(
    name="reference",
    help="Read-only inspection of reference DOCX, ZIP, AXPP and directories.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(reference_app, name="reference")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _fail(exc: CopilotError, *, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(exc.to_dict(), ensure_ascii=False))
    else:
        typer.secho(f"error [{exc.code}]: {exc.message}", fg="red", err=True)
        details = exc.details
        if details:
            typer.secho(f"details: {json.dumps(details, ensure_ascii=False)[:800]}", err=True)
    raise typer.Exit(code=exc.exit_code)


def _read_bytes(path: str) -> tuple[bytes, str]:
    if path == "-":
        return sys.stdin.buffer.read(), "stdin.ddsp"
    target = Path(path)
    if not target.exists():
        raise NotFoundError(f"File not found: {path}", details={"path": path})
    return target.read_bytes(), target.name


def _load_source(path: str) -> ParsedSource:
    payload, filename = _read_bytes(path)
    return parse_ddsp(payload, filename=filename, limits=get_settings().limits)


def _service() -> TemplateService:
    return TemplateService()


def _validator() -> ValidationEngine:
    """Build a validator that honours the configured IR limits."""
    limits = get_settings().limits
    return ValidationEngine(
        max_blocks=limits.max_ir_blocks,
        max_depth=limits.max_ir_depth,
        max_text_length=limits.max_text_length,
    )


def _planner() -> TemplatePlanner:
    from docentric_copilot.llm import LLMGateway

    return TemplatePlanner(LLMGateway())


def _emit(payload: dict[str, Any], *, as_json: bool, message: str | None = None) -> None:
    if as_json:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    elif message:
        typer.echo(message)


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
@app.command()
def version() -> None:
    """Print the CLI and IR versions."""
    typer.echo(f"docentric-copilot {__version__} (IR 1.0)")


@app.command()
def inspect(
    ddsp: Annotated[str, typer.Argument(help="Path to a .ddsp package or XML file")],
    as_json: Annotated[bool, typer.Option("--json", help="Machine readable output")] = False,
    show_paths: Annotated[bool, typer.Option("--paths", help="List every field path")] = False,
) -> None:
    """Parse a DDSP package and show the discovered schema."""
    try:
        parsed = _load_source(ddsp)
    except CopilotError as exc:
        _fail(exc, as_json=as_json)
        return
    schema = parsed.schema
    stats = schema.stats()
    if as_json:
        payload = {
            "schema_id": schema.schema_id,
            "sections": schema.section_names,
            "stats": stats.model_dump(mode="json"),
            "sample_data_available": schema.sample_data_available,
            "diagnostics": [item.model_dump(mode="json") for item in schema.diagnostics],
            "schema": schema.model_dump(mode="json"),
        }
        if show_paths:
            payload["paths"] = schema.paths
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    typer.secho(f"Schema: {schema.schema_id}", bold=True)
    typer.echo(f"Sections: {', '.join(schema.section_names) or 'none'}")
    typer.echo(
        f"Fields: {stats.node_count} nodes · {stats.scalar_count} scalars · "
        f"{stats.collection_count} collections · depth {stats.max_depth}"
    )
    typer.echo(f"Sample data: {'yes' if schema.sample_data_available else 'no'}")
    for diagnostic in schema.diagnostics:
        typer.echo(f"  {diagnostic.as_line()}")
    if show_paths:
        typer.echo("")
        for path in schema.paths:
            node = schema.node(path)
            marker = "[]" if node and node.collection else "  "
            typer.echo(f"  {marker} {path}  ({node.data_type if node else '?'})")


def _reference_summary(report: ReferenceReport) -> str:
    counts = report.counts
    lines = [
        f"Reference: {report.source_name} ({report.source_type.value})",
        (
            f"Artifacts: {counts.artifacts} ({counts.distinct_artifacts} distinct, "
            f"{counts.distinct_docx} distinct DOCX)"
        ),
        (
            f"Content controls: {counts.controls_total} "
            f"(recognized {counts.classification_recognized}, "
            f"ambiguous {counts.classification_ambiguous}, "
            f"unknown {counts.classification_unknown})"
        ),
        (
            f"Resolution: resolved {counts.resolved}, missing part {counts.missing_part}, "
            f"unknown path {counts.unknown_path}, ambiguous {counts.ambiguous}"
        ),
        (
            f"ID joins: {counts.joined_by_id}/{counts.controls_total} "
            f"({counts.join_coverage_ratio:.1%}); coverage {counts.coverage_ratio:.1%}"
        ),
        (
            f"Duplicates: {counts.duplicate_groups} groups "
            f"({counts.duplicate_occurrences} extra occurrences); "
            f"nested archives: {counts.nested_archives}"
        ),
        f"Runtime compatibility: {report.runtime_compatibility}",
    ]
    if report.warnings:
        lines.append(f"Warnings: {len(report.warnings)}")
    return "\n".join(lines)


@reference_app.command("inspect")
def reference_inspect(
    path: Annotated[
        str,
        typer.Argument(help="DOCX, ZIP, AXPP or directory to inspect"),
    ],
    json_output: Annotated[
        Path | None,
        typer.Option(
            "--json",
            help="Write the JSON report to this path; use '-' for stdout",
        ),
    ] = None,
    ddsp: Annotated[
        str | None,
        typer.Option("--ddsp", help="Optional matching DDSP XML schema for path validation"),
    ] = None,
    max_depth: Annotated[
        int,
        typer.Option(
            "--max-depth",
            min=0,
            max=3,
            help="Nested archive depth to expand (offline only; default 1)",
        ),
    ] = 1,
) -> None:
    """Inspect reference templates without executing them (REF-00, REF-02)."""
    try:
        limits = ReferenceLimits.from_limits(get_settings().limits, max_depth=max_depth)
        report = inspect_reference(path, limits=limits, max_depth=max_depth, ddsp_path=ddsp)
    except CopilotError as exc:
        _fail(exc, as_json=json_output is not None)
        return
    summary = _reference_summary(report)
    if json_output is None:
        typer.echo(summary)
        return
    if str(json_output) == "-":
        typer.echo(report_json(report), nl=False)
        return
    json_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(report_json(report), encoding="utf-8")
    typer.echo(summary)
    typer.echo(f"Report written to {json_output}")


@app.command()
def plan(
    ddsp: Annotated[str, typer.Option("--ddsp", help="Path to a .ddsp package")],
    prompt_file: Annotated[
        str, typer.Option("--prompt-file", help="File with the requirement text")
    ],
    provider: Annotated[str, typer.Option("--provider", help="LLM provider id")] = "mock",
    model: Annotated[str | None, typer.Option("--model", help="Model identifier")] = None,
    output: Annotated[Path, typer.Option("--output", help="Where to write the IR JSON")] = Path(
        "plan.json"
    ),
    mapping_output: Annotated[
        Path | None, typer.Option("--mapping", help="Where to write the mapping report")
    ] = None,
    design_style: Annotated[str, typer.Option("--design-style")] = "modern",
    language: Annotated[str, typer.Option("--language")] = "en",
    target: Annotated[str, typer.Option("--target")] = "generic-docx",
    as_json: Annotated[bool, typer.Option("--json", help="Machine readable output")] = False,
) -> None:
    """Generate a validated Template IR from a requirement and a schema."""
    import asyncio

    try:
        parsed = _load_source(ddsp)
        requirement = Path(prompt_file).read_text(encoding="utf-8")
        planner = _planner()
        options = PlanOptions(
            language=language,
            design_style=design_style,  # type: ignore[arg-type]
            target=target,  # type: ignore[arg-type]
        )
        outcome = asyncio.run(
            planner.plan(
                parsed.schema, requirement, provider=provider, model=model, options=options
            )
        )
        report = _validator().validate(outcome.document, parsed.schema)
        if not report.can_compile:
            raise CopilotError(
                "Validation failed; IR was not written",
                code="validation_failed",
                details={"validation": report.statuses()},
            )
    except CopilotError as exc:
        _fail(exc, as_json=as_json)
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            outcome.document.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
        )
        + "\n",
        encoding="utf-8",
    )
    if mapping_output is not None:
        mapping_output.parent.mkdir(parents=True, exist_ok=True)
        mapping_output.write_text(
            json.dumps(
                outcome.mapping.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    summary = {
        "status": "completed",
        "output": str(output),
        "ir_digest": ir_digest(outcome.document),
        "validation": report.statuses(),
        "mapping": outcome.mapping.counts(),
        "removed_bindings": [item.path for item in outcome.removed_bindings],
        "warnings": outcome.warnings,
        "generation": outcome.generation.public_view() if outcome.generation else None,
    }
    _emit(
        summary,
        as_json=as_json,
        message=(
            f"IR written to {output} ({str(summary['ir_digest'])[:12]})\n"
            f"Validation: {report.statuses()}\n"
            f"Mapping: {outcome.mapping.counts()}"
        ),
    )


@app.command()
def validate(
    ddsp: Annotated[str, typer.Option("--ddsp", help="Path to a .ddsp package")],
    plan_file: Annotated[Path, typer.Option("--plan", help="IR JSON file")],
    report_output: Annotated[
        Path | None, typer.Option("--report", help="Write an HTML validation report")
    ] = None,
    json_output: Annotated[
        Path | None, typer.Option("--json-report", help="Write a JSON validation report")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Machine readable output")] = False,
) -> None:
    """Validate a Template IR against a source schema (V1-V5)."""
    try:
        parsed = _load_source(ddsp)
        document = load_document(plan_file.read_text(encoding="utf-8"))
        report = ValidationEngine().validate(
            document, parsed.schema, sample_data=parsed.sample_data
        )
    except CopilotError as exc:
        _fail(exc, as_json=as_json)
        return

    if report_output is not None:
        report_output.parent.mkdir(parents=True, exist_ok=True)
        report_output.write_text(render_report_html(report), encoding="utf-8")
    if json_output is not None:
        json_output.parent.mkdir(parents=True, exist_ok=True)
        json_output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")

    payload = {
        "validation": report.statuses(),
        "overall": report.overall,
        "errors": len(report.errors()),
        "report": report.model_dump(mode="json"),
    }
    _emit(
        payload,
        as_json=as_json,
        message=f"Validation: {report.statuses()}\nOverall: {report.overall}",
    )
    if not report.can_compile:
        raise typer.Exit(code=1)


@app.command()
def compile(
    ddsp: Annotated[str, typer.Option("--ddsp", help="Path to a .ddsp package")],
    plan_file: Annotated[Path, typer.Option("--plan", help="IR JSON file")],
    output: Annotated[Path, typer.Option("--output", help="DOCX output path")] = Path(
        "document.docx"
    ),
    target: Annotated[str, typer.Option("--target")] = "generic-docx",
    render_mode: Annotated[str, typer.Option("--render-mode")] = "auto",
    as_json: Annotated[bool, typer.Option("--json", help="Machine readable output")] = False,
) -> None:
    """Compile a validated IR into a DOCX document (no LLM calls)."""
    try:
        parsed = _load_source(ddsp)
        document = load_document(plan_file.read_text(encoding="utf-8"))
        document = document.model_copy(update={"target": CompileTarget(target)})
        service = _service()
        report = service.validate(document, parsed.schema, sample_data=parsed.sample_data)
        if not report.can_compile:
            raise CopilotError(
                "Validation failed; document was not compiled",
                code="validation_failed",
                details={"validation": report.statuses()},
            )
        result = service.compile(
            document,
            parsed.schema,
            sample_data=parsed.sample_data,
            options=CompileOptions(
                target=target,  # type: ignore[arg-type]
                render_mode=render_mode,  # type: ignore[arg-type]
                document_name=output.name,
            ),
        )
        package_report = service.validate(
            document, parsed.schema, sample_data=parsed.sample_data, package=result.content
        )
    except CopilotError as exc:
        _fail(exc, as_json=as_json)
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(result.content)
    payload = {
        "status": "completed",
        "output": str(output),
        "size_bytes": result.size_bytes,
        "ir_digest": result.ir_digest,
        "validation": package_report.statuses(),
        "stats": result.stats,
        "warnings": result.warnings,
    }
    _emit(
        payload,
        as_json=as_json,
        message=(
            f"Compiled {output} ({result.size_bytes} bytes)\n"
            f"Validation: {package_report.statuses()}\n"
            f"Docentric AX compatibility: not tested"
        ),
    )


@app.command()
def preview(
    ddsp: Annotated[str, typer.Option("--ddsp", help="Path to a .ddsp package")],
    plan_file: Annotated[Path, typer.Option("--plan", help="IR JSON file")],
    output: Annotated[Path, typer.Option("--output", help="HTML output path")] = Path(
        "preview.html"
    ),
    as_json: Annotated[bool, typer.Option("--json", help="Machine readable output")] = False,
) -> None:
    """Render the independent HTML preview."""
    try:
        parsed = _load_source(ddsp)
        document = load_document(plan_file.read_text(encoding="utf-8"))
        result = _service().preview(document, parsed.schema, sample_data=parsed.sample_data)
    except CopilotError as exc:
        _fail(exc, as_json=as_json)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result.html, encoding="utf-8")
    _emit(
        {"output": str(output), "stats": result.stats, "warnings": result.warnings},
        as_json=as_json,
        message=f"Preview written to {output}",
    )


@app.command()
def providers(
    as_json: Annotated[bool, typer.Option("--json", help="Machine readable output")] = False,
) -> None:
    """List configured LLM providers (never prints keys)."""
    from docentric_copilot.llm import LLMGateway

    gateway = LLMGateway()
    catalogue = gateway.describe()
    if as_json:
        typer.echo(json.dumps(catalogue, ensure_ascii=False, indent=2, sort_keys=True))
        return
    for entry in catalogue:
        state = "configured" if entry["configured"] else "no API key"
        model = entry["default_model"] or "-"
        typer.echo(f"  {entry['name']:<10} {state:<12} default model: {model}")


@app.command("ir-schema")
def ir_schema(
    output: Annotated[Path | None, typer.Option("--output", help="Write schema to a file")] = None,
) -> None:
    """Print (or write) the JSON Schema of Template IR v1.0."""
    payload = (
        json.dumps(document_json_schema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    if output is None:
        typer.echo(payload, nl=False)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
        typer.echo(f"IR JSON Schema written to {output}")


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
