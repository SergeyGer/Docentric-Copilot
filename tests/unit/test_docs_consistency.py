"""PR-01 documentation baseline: version strings, feature matrix and ADR consistency."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from docentric_copilot import __version__

ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_versions_agree_across_the_distribution_and_docs() -> None:
    pyproject = tomllib.loads(_read("pyproject.toml"))
    assert pyproject["project"]["version"] == __version__ == "0.10.0"
    assert json.loads(_read("apps/web/package.json"))["version"] == __version__

    readme = _read("README.md")
    match = re.search(r"\|\s*\*\*Version\*\*\s*\|\s*([^|]+?)\s*\|", readme)
    assert match is not None
    assert match.group(1) == __version__

    roadmap = _read("docs/ROADMAP.md")
    current = re.search(r"\|\s*Current release\s*\|\s*([^|]+?)\s*\|", roadmap)
    assert current is not None
    assert current.group(1).startswith(__version__)

    for document in (
        "docs/PRD.md",
        "docs/SRS.md",
        "docs/ARCHITECTURE.md",
        "docs/THREAT_MODEL.md",
    ):
        assert __version__ in _read(document), document


def test_changelog_documents_v010_release() -> None:
    changelog = _read("CHANGELOG.md")
    assert "## [Unreleased]" in changelog
    assert "## [0.10.0]" in changelog
    released = changelog.split("## [0.10.0]", 1)[1].split("## [0.9.0]", 1)[0]
    assert "D365 embedded schema" in released
    assert "binding resolver" in released
    assert "gold" in released.lower()
    assert "gold_evaluation" in released
    assert "AT-07" in released
    assert "not_tested" in released


def test_readme_and_roadmap_state_the_partial_v010_scope_truthfully() -> None:
    readme = _read("README.md")
    assert "v0.10 P0 status" in readme
    assert "PR-02 D365 embedded schema extraction" in readme
    assert "PR-03 canonical schema and binding resolver" in readme
    assert "PR-04 gold semantic dataset" in readme
    assert "PR-05 live gold benchmark" in readme
    assert "single-annotator" in readme
    assert "not_tested" in readme
    assert "Not started in this increment" not in readme

    roadmap = _read("docs/ROADMAP.md")
    assert "M6 — Reference Template Intelligence completion (v0.10, in progress)" in roadmap
    assert "PR-02 D365 embedded schema extraction" in roadmap
    assert "PR-04 gold semantic dataset" in roadmap
    assert "PR-05 live benchmark runner and report" in roadmap
    assert "PR-04/PR-05" in roadmap
    assert "AT-07" in roadmap
    assert "not_tested" in roadmap


def test_gold_dataset_labels_are_versioned_and_documented() -> None:
    from benchmarks.gold_dataset import load_gold_dataset

    dataset = load_gold_dataset(ROOT / "benchmarks" / "gold_cases.json")
    guide = _read("docs/GOLD_LABELS.md")
    assert "gold-cases/v2" in guide
    assert "2.0.0" in guide
    assert "adjudicate_labels.py" in guide
    assert "adjudication_report.json" in guide
    assert "20 calibration / 12 holdout" in guide
    assert dataset.canonical_sha256 in guide
    assert "No independent human double review" in guide
    assert "AT-07" in guide
    assert "ADR-0014" in guide
    evaluation = _read("docs/EVALUATION.md")
    assert "image_family" in evaluation or "image-family" in evaluation.casefold()
    assert "Gold semantic benchmark (v0.10 PR-05)" in evaluation
    assert "benchmarks/gold_evaluation.py" in evaluation
    assert "20 calibration / 12 holdout" in evaluation
    assert (
        "observations, not significance"
        in _read("docs/wiki/Benchmarks-and-Evaluation.md").casefold()
    )


def test_adr_0015_is_complete_and_indexed() -> None:
    adr = ROOT / "docs" / "adr" / "0015-label-adjudication-and-candidate-filtering.md"
    assert adr.exists()
    body = adr.read_text(encoding="utf-8")
    for required in ("Status", "Context", "Decision", "Consequences"):
        assert required in body
    assert "AT-07" in body
    assert "deterministic proxy" in body
    assert "candidate" in body.casefold()
    index = _read("docs/adr/README.md")
    assert "0015-label-adjudication-and-candidate-filtering.md" in index


def test_adr_0014_is_complete_and_indexed() -> None:
    adr = ROOT / "docs" / "adr" / "0014-gold-dataset-and-reference-benchmark.md"
    assert adr.exists()
    body = adr.read_text(encoding="utf-8")
    for required in ("Status", "Context", "Decision", "Consequences"):
        assert required in body
    assert "single-annotator" in body or "No independent human double review" in body
    assert "not_tested" in body
    index = _read("docs/adr/README.md")
    assert "0014-gold-dataset-and-reference-benchmark.md" in index


def test_reference_templates_documents_the_d365_adapter_and_taxonomy() -> None:
    document = _read("docs/REFERENCE_TEMPLATES.md")
    assert "D365 embedded schema and binding resolution" in document
    assert "d365_schema.py" in document
    assert "binding_resolver.py" in document
    assert "schema_source" in document
    for status in (
        "resolved",
        "ambiguous",
        "unknown_path",
        "type_mismatch",
        "schema_unavailable",
        "unsupported_expression",
    ):
        assert status in document
    assert "not_tested" in document
    assert "ADR-0013" in document


def test_adr_0013_is_complete_and_indexed() -> None:
    adr = ROOT / "docs" / "adr" / "0013-d365-embedded-schema-and-binding-resolution.md"
    assert adr.exists()
    body = adr.read_text(encoding="utf-8")
    for required in ("Status", "Context", "Decision", "Consequences"):
        assert required in body
    index = _read("docs/adr/README.md")
    assert "0013-d365-embedded-schema-and-binding-resolution.md" in index


def test_cli_and_api_surfaces_are_documented() -> None:
    reference = _read("docs/REFERENCE_TEMPLATES.md")
    assert "docentric-copilot reference d365" in reference
    assert "POST /api/v1/reference/d365" in reference
    assert "POST /api/v1/reference/d365" in _read("docs/API_SPEC.md")
    assert "reference d365" in _read("docs/wiki/CLI-Reference.md")
    assert "/api/v1/reference/d365" in _read("docs/wiki/API-Reference.md")


def test_no_corpus_material_is_referenced_in_committed_docs() -> None:
    """Committed docs may state counts, never corpus paths or file names."""

    reference = _read("docs/REFERENCE_TEMPLATES.md")
    assert "examples/corpus/Word Template Examples" not in reference
    assert "Docentric AX Examples.zip" not in reference
    for name in ("HcmNumberOfWorkersReport", "PurchPurchaseOrder", "RetailLabel"):
        assert name not in reference
