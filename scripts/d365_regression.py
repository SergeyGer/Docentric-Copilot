#!/usr/bin/env python3
"""Private-corpus regression runner for the D365 ReferenceGraph.

The v0.12 TZ (V012-04) asks for a repeatable check of the graph builder against
11 real D365 DOCX files. Those files are commercial material: they never enter
git, and neither do their hashes, schema paths, labels or graph payloads. The
public repository holds only this runner, synthetic tests and an aggregate
summary that has been reviewed for leaks.

What the runner does, locally:

* expands the private corpus in memory (ZIP/AXPP up to the reference limits);
* requires exactly 11 DOCX files and analyses every one of them;
* extracts the embedded D365 schema and builds the read-only ``ReferenceGraph``;
* records per-document input hash, extractor version, graph digest, node/edge
  counts, resolution statuses and diagnostics under a git-ignored directory;
* repeats the analysis to prove the graph digest is stable;
* compares the binding totals and status distribution with the frozen v0.11
  baseline (246 bindings / 233 resolved / 13 unresolved) and classifies the
  differences without pretending the baseline is a guarantee.

What it writes publicly (only with ``--publish``):

* aggregate counts only: documents, bindings, resolved/unresolved, status
  distribution, graph totals, duplicate links, scope mismatches, digest
  stability, verdict and limitations.

Usage::

    export DOCENTRIC_PRIVATE_CORPUS_DIR=/path/to/private/d365
    python scripts/d365_regression.py
    python scripts/d365_regression.py --publish benchmarks/d365_regression_v012.json
    python scripts/d365_regression.py --json

Exit codes: 0 passed, 1 regression/incomplete, 2 usage or missing corpus.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # pragma: no cover - import bootstrap when run as a script
    sys.path.insert(0, str(ROOT))

from docentric_copilot import __version__  # noqa: E402
from docentric_copilot.errors import CopilotError  # noqa: E402
from docentric_copilot.reference import (  # noqa: E402
    EdgeType,
    ElementKind,
    ReferenceLimits,
    analyze_d365_bytes,
    build_reference_graph,
    graph_json,
    inspect_reference_bytes_bundle,
)
from scripts.assess_d365_corpus import CorpusDocument, collect_documents  # noqa: E402

RUNNER_VERSION: Final = "1.0.0"
SUMMARY_SCHEMA: Final = "d365-regression/v1"
DEFAULT_OUTPUT: Final = ROOT / ".local-artifacts" / "d365-regression"
DEFAULT_BASELINE: Final = ROOT / "benchmarks" / "baseline_v011.json"
DEFAULT_EXPECTED: Final = 11
EXTRACTOR_VERSION: Final = "d365-binding-report/1.0+graph/1.0"
STATUS_KEYS: Final = (
    "resolved",
    "ambiguous",
    "unknown_path",
    "type_mismatch",
    "schema_unavailable",
    "unsupported_expression",
)
_PUBLIC_GENERATED_KEYS: Final = {
    "schema",
    "runner_version",
    "extractor_version",
    "generated_at",
    "app_version",
    "app_commit",
    "expected_documents",
    "documents_discovered",
    "documents_processed",
    "documents_failed",
    "baseline",
    "current",
    "classification",
    "digest_stability",
    "verdict",
    "notes",
    "privacy",
    "limitations",
}


def _git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _counts(report: Any) -> dict[str, int]:
    return {key: int((report.counts.by_status or {}).get(key, 0)) for key in STATUS_KEYS}


def _duplicate_links(graph: Any) -> int:
    seen: Counter[tuple[str, str, str]] = Counter()
    for edge in graph.edges:
        if edge.type is not EdgeType.RESOLVES_TO:
            continue
        seen[(edge.source, edge.target, edge.resolution_status or "")] += 1
    return sum(count - 1 for count in seen.values() if count > 1)


def _scope_mismatches(graph: Any) -> int:
    """Count resolved edges whose list/scalar shape contradicts the schema."""
    nodes = {node.id: node for node in graph.nodes}
    mismatches = 0
    for edge in graph.edges:
        if edge.type is not EdgeType.RESOLVES_TO or edge.status.value != "resolved":
            continue
        source = nodes.get(edge.source)
        target = nodes.get(edge.target)
        if source is None or target is None or target.kind.value != "schema_field":
            continue
        # Group/SummaryField elements legitimately bind a whole collection;
        # only Field/List elements have a scalar-vs-list shape to compare.
        if source.element_kind not in {ElementKind.FIELD, ElementKind.LIST}:
            continue
        source_is_list = source.element_kind is ElementKind.LIST
        if source_is_list != target.collection:
            mismatches += 1
    return mismatches


def analyze_document(
    document: CorpusDocument,
    *,
    limits: ReferenceLimits,
) -> dict[str, Any]:
    """Analyse one private document twice and return private per-document facts."""
    first = _analyze_once(document, limits=limits)
    second = _analyze_once(document, limits=limits)
    first["digest_stable"] = first["graph_digest"] == second["graph_digest"]
    first["graph_json"] = second["graph_json"]
    return first


def _analyze_once(document: CorpusDocument, *, limits: ReferenceLimits) -> dict[str, Any]:
    report = analyze_d365_bytes(
        document.payload,
        filename="corpus-document.docx",
        limits=limits,
    )
    bundle = inspect_reference_bytes_bundle(
        document.payload,
        filename="corpus-document.docx",
        limits=limits,
        max_depth=0,
    )
    graph = build_reference_graph(
        bundle.report,
        d365={report.template_id: report},
        documents=bundle.payloads,
    )
    return {
        "label": document.label,
        "sha256": document.sha256,
        "schema_source": report.schema_source.value,
        "report_version": report.report_version,
        "bindings": report.counts.total,
        "statuses": _counts(report),
        "resolved_with_evidence": report.counts.resolved_with_evidence,
        "resolved_without_evidence": report.counts.resolved_without_evidence,
        "graph_digest": graph.graph_digest,
        "graph_nodes": graph.summary.node_count,
        "graph_edges": graph.summary.edge_count,
        "resolves_to_with_evidence": graph.summary.resolves_to_with_evidence,
        "evidence_coverage_ratio": graph.summary.evidence_coverage_ratio,
        "unresolved_by_status": dict(graph.summary.unresolved_by_status),
        "duplicate_links": _duplicate_links(graph),
        "scope_mismatches": _scope_mismatches(graph),
        "diagnostics": [
            {
                "code": diagnostic.code,
                "severity": diagnostic.severity.value,
                "message": diagnostic.message,
                "part": diagnostic.part,
            }
            for diagnostic in report.diagnostics
        ],
        "graph_json": graph_json(graph),
    }


def _diagnostics_by_code(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for record in records:
        for diagnostic in record.get("diagnostics") or []:
            counts[str(diagnostic.get("code"))] += 1
    return dict(sorted(counts.items()))


def _baseline(baseline_path: Path) -> dict[str, Any]:
    try:
        document = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read the frozen baseline {baseline_path}: {exc}") from exc
    d365 = document.get("d365") if isinstance(document, dict) else None
    if not isinstance(d365, dict):
        raise SystemExit(f"baseline {baseline_path} has no d365 aggregate")
    return d365


def build_summary(
    records: list[dict[str, Any]],
    *,
    discovered: int,
    expected: int,
    baseline: dict[str, Any],
    failures: list[dict[str, str]],
    generated_at: str,
) -> dict[str, Any]:
    status_totals: Counter[str] = Counter()
    for record in records:
        status_totals.update(record["statuses"])
    current = {
        "documents_processed": len(records),
        "unique_document_payloads": len({record["sha256"] for record in records}),
        "bindings": sum(int(record["bindings"]) for record in records),
        "statuses": {key: status_totals.get(key, 0) for key in STATUS_KEYS},
        "resolved_with_evidence": sum(int(record["resolved_with_evidence"]) for record in records),
        "resolved_without_evidence": sum(
            int(record["resolved_without_evidence"]) for record in records
        ),
        "graph_nodes": sum(int(record["graph_nodes"]) for record in records),
        "graph_edges": sum(int(record["graph_edges"]) for record in records),
        "resolves_to_with_evidence": sum(
            int(record["resolves_to_with_evidence"]) for record in records
        ),
        "evidence_coverage_ratio": round(
            (
                sum(float(record["evidence_coverage_ratio"]) for record in records) / len(records)
                if records
                else 0.0
            ),
            4,
        ),
        "duplicate_links": sum(int(record["duplicate_links"]) for record in records),
        "scope_mismatches": sum(int(record["scope_mismatches"]) for record in records),
        "diagnostics_by_code": _diagnostics_by_code(records),
    }
    baseline_resolved = int(baseline.get("resolved_with_evidence", 0))
    baseline_unresolved = int(baseline.get("unresolved", 0))
    baseline_statuses = {
        key: int((baseline.get("statuses") or {}).get(key, 0)) for key in STATUS_KEYS
    }
    current_resolved = int(current["statuses"].get("resolved", 0))
    current_unresolved = sum(
        int(current["statuses"].get(key, 0))
        for key in (
            "ambiguous",
            "unknown_path",
            "type_mismatch",
            "schema_unavailable",
            "unsupported_expression",
        )
    )
    lost_resolved = max(0, baseline_resolved - current_resolved)
    new_unresolved = max(0, current_unresolved - baseline_unresolved)
    status_changes = {
        key: int(current["statuses"].get(key, 0)) - baseline_statuses.get(key, 0)
        for key in STATUS_KEYS
        if int(current["statuses"].get(key, 0)) != baseline_statuses.get(key, 0)
    }
    classification = {
        "baseline_resolved": baseline_resolved,
        "baseline_unresolved": baseline_unresolved,
        "current_resolved": current_resolved,
        "current_unresolved": current_unresolved,
        "lost_resolved": lost_resolved,
        "new_unresolved": new_unresolved,
        "status_deltas": status_changes,
        "previously_unresolved_now": {
            key: int(current["statuses"].get(key, 0))
            for key in (
                "ambiguous",
                "unknown_path",
                "type_mismatch",
                "schema_unavailable",
                "unsupported_expression",
            )
        },
        "note": (
            "The 233/13 baseline is the v0.11 audit observation, not a guarantee. "
            "Counts are aggregate; per-binding baseline details are not public."
        ),
    }
    stable = all(bool(record["digest_stable"]) for record in records) and bool(records)
    digest_stability = {
        "stable": stable,
        "documents_checked": len(records),
        "documents_with_changed_digest": sum(
            1 for record in records if not record["digest_stable"]
        ),
    }
    notes: list[str] = []
    verdict = "passed"
    if discovered != expected:
        verdict = "failed"
        notes.append(f"expected {expected} DOCX, discovered {discovered}")
    if failures:
        verdict = "failed"
        notes.append(f"{len(failures)} document(s) failed extraction")
    if lost_resolved:
        verdict = "failed"
        notes.append(f"{lost_resolved} previously resolved binding(s) are no longer resolved")
    if new_unresolved:
        verdict = "failed"
        notes.append(f"{new_unresolved} additional unresolved binding(s) versus the baseline")
    if not stable:
        verdict = "failed"
        notes.append("the graph digest is not stable across two analyses")
    if status_changes and verdict == "passed":
        notes.append(
            "status distribution changed without losing resolved bindings: "
            + ", ".join(f"{key} {delta:+d}" for key, delta in sorted(status_changes.items()))
        )
    if current["scope_mismatches"]:
        verdict = "failed"
        notes.append(f"{current['scope_mismatches']} scope mismatch(es) detected")
    if current["duplicate_links"]:
        notes.append(f"{current['duplicate_links']} duplicate resolve edge(s) detected")
    if not notes:
        notes.append("all documents processed; aggregate matches or improves on the baseline")

    return {
        "schema": SUMMARY_SCHEMA,
        "runner_version": RUNNER_VERSION,
        "extractor_version": EXTRACTOR_VERSION,
        "generated_at": generated_at,
        "app_version": __version__,
        "app_commit": _git_commit(),
        "expected_documents": expected,
        "documents_discovered": discovered,
        "documents_processed": current["documents_processed"],
        "documents_failed": len(failures),
        "baseline": {
            "documents": int(baseline.get("documents", 0)),
            "bindings": int(baseline.get("bindings", 0)),
            "resolved": baseline_resolved,
            "unresolved": baseline_unresolved,
            "statuses": baseline_statuses,
            "source": "v0.11.0 audit aggregate (frozen in benchmarks/baseline_v011.json)",
        },
        "current": current,
        "classification": classification,
        "digest_stability": digest_stability,
        "verdict": verdict,
        "notes": notes,
        "privacy": {
            "corpus_content_published": False,
            "document_hashes_published": False,
            "schema_paths_published": False,
            "document_labels_published": False,
            "private_output_directory": ".local-artifacts/d365-regression/",
        },
        "limitations": [
            "The 11 files are a local private corpus; this summary proves the run, not their content.",
            "233/13 is a v0.11 baseline observation, not a guarantee.",
            "Docentric AX runtime compatibility remains not_tested.",
            "The aggregate cannot be used to reconstruct a document, schema path or customer name.",
        ],
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def run(
    *,
    corpus: Path,
    output: Path,
    baseline_path: Path = DEFAULT_BASELINE,
    expected: int = DEFAULT_EXPECTED,
    publish: Path | None = None,
    limits: ReferenceLimits | None = None,
) -> dict[str, Any]:
    resolved_limits = limits or ReferenceLimits()
    baseline = _baseline(baseline_path)
    documents = collect_documents(corpus, resolved_limits)
    records: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for index, document in enumerate(documents, start=1):
        try:
            record = analyze_document(document, limits=resolved_limits)
        except (CopilotError, ValueError, OSError) as exc:
            failures.append(
                {
                    "index": str(index),
                    "code": getattr(exc, "code", "analysis_error"),
                }
            )
            continue
        record["index"] = index
        records.append(record)

    output.mkdir(parents=True, exist_ok=True)
    private = output / "private"
    private.mkdir(parents=True, exist_ok=True)
    (private / "graphs").mkdir(exist_ok=True)
    for record in records:
        graph_path = (
            private / "graphs" / f"doc-{int(record['index']):02d}-{record['sha256'][:12]}.json"
        )
        graph_path.write_text(str(record.pop("graph_json")), encoding="utf-8")
    with (private / "documents.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
    _write_json(
        private / "manifest.json",
        {
            "runner_version": RUNNER_VERSION,
            "extractor_version": EXTRACTOR_VERSION,
            "app_version": __version__,
            "app_commit": _git_commit(),
            "generated_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
            "documents": len(records),
            "failures": failures,
            "note": "private corpus material; never commit this directory",
        },
    )

    generated_at = datetime.now(tz=UTC).isoformat(timespec="seconds")
    summary = build_summary(
        records,
        discovered=len(documents),
        expected=expected,
        baseline=baseline,
        failures=failures,
        generated_at=generated_at,
    )
    _write_json(output / "summary.json", summary)
    _write_json(
        output / "private" / "baseline_digests.json",
        {record["sha256"][:12]: record["graph_digest"] for record in records},
    )
    if publish is not None:
        _write_json(publish, summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path(os.environ.get("DOCENTRIC_PRIVATE_CORPUS_DIR", "")).expanduser()
        if os.environ.get("DOCENTRIC_PRIVATE_CORPUS_DIR")
        else None,
        help="Private D365 corpus directory (or DOCENTRIC_PRIVATE_CORPUS_DIR)",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--expected", type=int, default=DEFAULT_EXPECTED)
    parser.add_argument(
        "--publish",
        type=Path,
        default=None,
        help="Write the reviewed, public-safe aggregate summary to this path",
    )
    parser.add_argument("--json", action="store_true", help="Print the public summary")
    args = parser.parse_args(argv)
    if args.corpus is None:
        parser.error("provide --corpus or DOCENTRIC_PRIVATE_CORPUS_DIR")
    if not args.corpus.is_dir():
        print(f"private corpus directory does not exist: {args.corpus}", file=sys.stderr)
        return 2
    summary = run(
        corpus=args.corpus,
        output=args.output,
        baseline_path=args.baseline,
        expected=args.expected,
        publish=args.publish,
    )
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        current = summary["current"]
        print(
            "D365 regression: "
            f"{summary['documents_processed']}/{summary['expected_documents']} documents, "
            f"{current['bindings']} bindings, "
            f"{current['statuses']['resolved']} resolved, "
            f"{sum(current['statuses'][key] for key in STATUS_KEYS if key != 'resolved')} unresolved, "
            f"digest stable={summary['digest_stability']['stable']}, "
            f"verdict={summary['verdict']}"
        )
        for note in summary["notes"]:
            print(f"  - {note}")
    return 0 if summary["verdict"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
