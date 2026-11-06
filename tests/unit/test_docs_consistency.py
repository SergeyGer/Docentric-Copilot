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
    assert pyproject["project"]["version"] == __version__ == "0.12.0"
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
    assert "## [0.11.0]" in changelog
    released = changelog.split("## [0.10.0]", 1)[1].split("## [0.9.0]", 1)[0]
    assert "D365 embedded schema" in released
    assert "binding resolver" in released
    assert "gold" in released.lower()
    assert "gold_evaluation" in released
    assert "AT-07" in released
    assert "not_tested" in released


def test_readme_links_to_the_canonical_wiki_status_and_roadmap_is_truthful() -> None:
    readme = _read("README.md")
    assert "## Honest status" in readme
    assert "wiki/Honest-Status" in readme
    assert "Docentric AX compatibility is unverified" in readme
    assert "not_tested" in readme
    # The detailed status tables moved to the wiki; README keeps a pointer only.
    assert "| V012 ID | Workstream | Status |" not in readme
    assert "PR-02 D365 embedded schema extraction" not in readme
    assert "Not started in this increment" not in readme

    honest = _read("docs/wiki/Honest-Status.md")
    for marker in (
        "v0.10 P0",
        "PR-02 D365 embedded schema extraction",
        "PR-03 canonical schema and binding resolver",
        "PR-04 gold semantic dataset",
        "PR-05 live gold benchmark",
        "single-annotator",
        "not_tested",
        "This page is the maintained status record",
    ):
        assert marker in honest
    assert "Not started in this increment" not in honest

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


def test_v011_p1_docs_state_the_partial_scope_and_version_consistency() -> None:
    changelog = _read("CHANGELOG.md")
    unreleased = changelog.split("## [0.11.0]", 1)[1].split("## [0.10.0]", 1)[0]
    for marker in ("#26", "#27", "#28", "#29", "#30"):
        assert marker in unreleased
    assert "partial" in unreleased.casefold()
    assert "not_tested" in unreleased
    assert "ADR-0016" in unreleased

    reference = _read("docs/REFERENCE_TEMPLATES.md")
    for surface in (
        "reference import-ir",
        "reference visual-diff",
        "/api/v1/reference/import-ir",
        "/api/v1/reference/reports",
        "LibreOffice rendering (not Word fidelity)",
        "renderer_unavailable",
        "ADR-0016",
        "What is not implemented or only partial",
    ):
        assert surface in reference
    assert "planned p1" not in reference.casefold()

    readme = _read("README.md")
    assert "wiki/Honest-Status" in readme
    assert "not_tested" in readme

    honest = _read("docs/wiki/Honest-Status.md")
    assert "v0.11 P1 — released in 0.11.0" in honest
    assert "Docentric AX runtime compatibility" in honest
    assert "`not_tested`" in honest
    assert "ADR-0016" in honest
    assert "0.11.0" in honest

    roadmap = _read("docs/ROADMAP.md")
    assert "M7 — v0.11 P1 reference workflow (released in 0.11.0)" in roadmap
    assert "PR-06 safe Reference → generic Template IR" in roadmap

    evaluation = _read("docs/EVALUATION.md")
    assert "v0.11 P1 reference workflow is not a benchmark result" in evaluation

    adr = ROOT / "docs" / "adr" / "0016-ir-import-and-visual-diff.md"
    assert adr.exists()
    body = adr.read_text(encoding="utf-8")
    for required in ("Status", "Context", "Decision", "Consequences"):
        assert required in body
    assert "ADR-0015 had already" in body
    assert "renderer_unavailable" in body
    assert "runtime_compatibility" in body
    assert "0016-ir-import-and-visual-diff.md" in _read("docs/adr/README.md")


def test_v011_p1_wiki_page_and_cli_api_surfaces_are_indexed() -> None:
    page = ROOT / "docs" / "wiki" / "Reference-IR-Import-and-Visual-Diff.md"
    assert page.exists()
    body = page.read_text(encoding="utf-8")
    for marker in ("#26", "#27", "#28", "#29", "renderer_unavailable", "not_tested"):
        assert marker in body
    sidebar = _read("docs/wiki/_Sidebar.md")
    assert "Reference-IR-Import-and-Visual-Diff" in sidebar
    assert "reference import-ir" in _read("docs/wiki/CLI-Reference.md")
    assert "reference visual-diff" in _read("docs/wiki/CLI-Reference.md")
    assert "/api/v1/reference/reports" in _read("docs/wiki/API-Reference.md")
    assert "/api/v1/reference/import-ir" in _read("docs/wiki/API-Reference.md")
    assert "/api/v1/reference/import-ir" in _read("docs/API_SPEC.md")
    assert "/api/v1/reference/reports" in _read("docs/API_SPEC.md")


def test_no_corpus_material_is_referenced_in_committed_docs() -> None:
    """Committed docs may state counts, never corpus paths or file names."""

    reference = _read("docs/REFERENCE_TEMPLATES.md")
    assert "examples/corpus/Word Template Examples" not in reference
    assert "Docentric AX Examples.zip" not in reference
    for name in ("HcmNumberOfWorkersReport", "PurchPurchaseOrder", "RetailLabel"):
        assert name not in reference


def test_v012_release_evidence_and_version_alignment() -> None:
    changelog = _read("CHANGELOG.md")
    assert "## [0.12.0] - 2026-11-06" in changelog
    assert "## [Unreleased]" in changelog
    evidence = _read("docs/RELEASE_EVIDENCE_V0_12.md")
    for v012 in (
        "V012-01",
        "V012-02",
        "V012-03",
        "V012-04",
        "V012-05",
        "V012-06",
        "V012-07",
        "V012-08",
        "V012-09",
        "V012-10",
    ):
        assert v012 in evidence
    for marker in (
        "AT-07",
        "partial",
        "not_tested",
        "Deferred",
        "Passed",
        "independent human review",
        "v0.12.0",
    ):
        assert marker in evidence

    readme = _read("README.md")
    assert "Honest-Status" in readme
    assert "0.12.0" in readme
    assert "not_tested" in readme
    assert "AT-07" in readme
    assert "| V012 ID | Workstream | Status |" not in readme

    honest = _read("docs/wiki/Honest-Status.md")
    for v012 in (
        "V012-01",
        "V012-02",
        "V012-03",
        "V012-04",
        "V012-05",
        "V012-06",
        "V012-07",
        "V012-08",
        "V012-09",
        "V012-10",
    ):
        assert v012 in honest
    for marker in ("Passed", "Deferred", "AT-07", "partial", "not_tested", "v0.13"):
        assert marker in honest

    roadmap = _read("docs/ROADMAP.md")
    assert "M8 — v0.12 reliability release" in roadmap
    assert "Current release | 0.12.0" in roadmap

    openapi = json.loads(_read("docs/openapi.json"))
    assert openapi["info"]["version"] == __version__ == "0.12.0"


def test_v012_p1_items_have_honest_status_and_targets() -> None:
    evidence = _read("docs/RELEASE_EVIDENCE_V0_12.md")
    assert "V012-03 | Image-family expansion | **Deferred**" in evidence
    assert "V012-06 | Reference → IR table inference | **Deferred**" in evidence
    assert "#37" in evidence and "#40" in evidence
    assert "v0.13" in evidence
    assert "V012-09 | Report retention/deletion | **Passed**" in evidence
    assert "V012-10 | Responsive + release docs | **Passed**" in evidence
    assert "No status is represented as a single" in evidence

    honest = _read("docs/wiki/Honest-Status.md")
    assert "V012-03 | Image-family expansion | **Deferred**" in honest
    assert "V012-06 | Reference → IR table inference | **Deferred**" in honest
    assert "#37" in honest and "#40" in honest
    assert "v0.13" in honest


def test_wiki_honest_status_is_canonical_and_in_the_sidebar() -> None:
    page = ROOT / "docs" / "wiki" / "Honest-Status.md"
    assert page.exists()
    body = page.read_text(encoding="utf-8")
    assert "This page is the maintained status record" in body
    assert "AT-07" in body and "partial" in body
    assert "not_tested" in body
    assert "docs/wiki/Honest-Status.md" in body
    assert "Honest-Status" in _read("docs/wiki/_Sidebar.md")
    assert "[Honest Status](Honest-Status)" in _read("docs/wiki/Home.md")
    assert "Honest-Status" in _read("README.md")


def test_wiki_roadmap_is_synchronized_with_github_issues() -> None:
    roadmap = _read("docs/wiki/Roadmap.md")
    assert "GitHub Issues is the source of truth" in roadmap
    assert "7 open issues" in roadmap
    for number in ("#12", "#13", "#14", "#15", "#17", "#37", "#40"):
        assert number in roadmap, number
    for number in (
        "#24",
        "#25",
        "#27",
        "#28",
        "#29",
        "#30",
        "#35",
        "#36",
        "#38",
        "#39",
        "#41",
        "#42",
        "#43",
        "#44",
    ):
        assert number in roadmap, number
    assert "Deferred from v0.12 — target v0.13" in roadmap
    assert "python scripts/sync_wiki.py --push" in roadmap


def test_e2e_visual_and_retention_docs_are_present() -> None:
    for path in (
        "docs/E2E.md",
        "docs/VISUAL_CI.md",
        "docs/V012_05_REGRESSIONS.md",
        "docs/REPORT_RETENTION.md",
        "docs/RESPONSIVE.md",
        "docs/D365_REGRESSION.md",
        "docs/GOLD_AUDIT.md",
        "benchmarks/visual_renderer_lock.json",
    ):
        assert (ROOT / path).exists(), path
    e2e = _read("docs/E2E.md")
    assert "trace.zip" in e2e and "failure.png" in e2e
    visual = _read("docs/VISUAL_CI.md")
    assert "visual_not_checked" in visual
    assert "LibreOffice" in visual and "Poppler" in visual
    retention = _read("docs/REPORT_RETENTION.md")
    assert "DELETE /api/v1/reference/reports/{id}" in retention
    assert "DC_REFERENCE_REPORT_TTL_SECONDS" in retention
