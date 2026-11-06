"""Shared pytest fixtures.

Tests are synchronous by design: async entry points are driven with
``asyncio.run`` so that the suite has no plugin dependency and behaves the same
in CI and locally.
"""

from __future__ import annotations

import os

os.environ.setdefault("DC_ENV", "test")

import io
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from docentric_copilot.config import get_settings
from docentric_copilot.ddsp_parser import ParsedSource, parse_ddsp
from docentric_copilot.docx_compiler import CompilationResult, CompileOptions, GenericDocxCompiler
from docentric_copilot.llm import LLMGateway
from docentric_copilot.planner import PlanOutcome, TemplatePlanner
from docentric_copilot.template_validator import ValidationEngine

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
FIXED_TIME = (2024, 1, 1, 0, 0, 0)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--e2e",
        action="store_true",
        default=False,
        help="run the Playwright browser end-to-end suite (skipped by default)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--e2e"):
        return
    skip = pytest.mark.skip(reason="E2E browser tests run with --e2e")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip)


def build_zip(files: dict[str, bytes], *, compresslevel: int = 9) -> bytes:
    """Deterministic ZIP helper used by parser tests."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=compresslevel) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[name])
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep every test away from the developer's real data directory."""
    monkeypatch.setenv("DC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DC_LOG_LEVEL", "CRITICAL")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def quotation_path() -> Path:
    return EXAMPLES / "quotation" / "sales-quotation.ddsp"


@pytest.fixture
def quotation_request() -> str:
    return (EXAMPLES / "quotation" / "prompt.txt").read_text(encoding="utf-8")


@pytest.fixture
def quotation_source(quotation_path: Path) -> ParsedSource:
    return parse_ddsp(quotation_path.read_bytes(), quotation_path.name)


@pytest.fixture
def schema(quotation_source: ParsedSource):
    return quotation_source.schema


@pytest.fixture
def sample_data(quotation_source: ParsedSource) -> dict:
    assert quotation_source.sample_data is not None
    return quotation_source.sample_data


@pytest.fixture
def gateway() -> LLMGateway:
    return LLMGateway()


@pytest.fixture
def planner(gateway: LLMGateway) -> TemplatePlanner:
    return TemplatePlanner(gateway)


@pytest.fixture
def planned(
    planner: TemplatePlanner, quotation_source: ParsedSource, quotation_request: str
) -> PlanOutcome:
    import asyncio

    return asyncio.run(planner.plan(quotation_source.schema, quotation_request, provider="mock"))


@pytest.fixture
def compiled(planned: PlanOutcome, schema, sample_data) -> CompilationResult:
    compiler = GenericDocxCompiler()
    return compiler.compile(
        planned.document,
        schema,
        CompileOptions(document_name="quotation.docx"),
        sample_data=sample_data,
    )


@pytest.fixture
def validation(planned: PlanOutcome, schema, sample_data, compiled) -> object:
    return ValidationEngine().validate(
        planned.document, schema, sample_data=sample_data, package=compiled.content
    )
