#!/usr/bin/env python3
"""Assess the local D365 reference corpus with the embedded-schema adapter.

The script is deliberately corpus-agnostic: it walks any directory, expands
``.zip``/``.axpp`` containers in memory under the standard reference limits and
runs the D365 extraction + binding resolver on every ``.docx`` it finds. Only
counts, hashes and statuses are reported; no file name, template text or schema
fragment is written.

The output belongs in the git-ignored ``.tools/`` directory:

    python scripts/assess_d365_corpus.py \
        --corpus .tools/reference-corpus/examples/corpus \
        --json .tools/v010/corpus-assessment.json

Nothing in the report is a runtime compatibility claim: every document keeps
``runtime_compatibility: not_tested``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from docentric_copilot.errors import CopilotError
from docentric_copilot.reference import (
    D365BindingReport,
    ReferenceLimits,
    analyze_d365_bytes,
)
from docentric_copilot.reference.safety import detect_container, read_archive
from docentric_copilot.serialization import digest_bytes

ASSESSMENT_VERSION: Final = "1.0"
_ALLOWED_SUFFIXES: Final = {".docx", ".zip", ".axpp"}
_MAX_NESTED_DEPTH: Final = 3


@dataclass(slots=True)
class CorpusDocument:
    """One DOCX occurrence found inside the corpus (never written verbatim)."""

    label: str = field(repr=False)
    payload: bytes = field(repr=False)

    @property
    def sha256(self) -> str:
        return digest_bytes(self.payload)


def collect_documents(root: Path, limits: ReferenceLimits) -> list[CorpusDocument]:
    """Discover DOCX documents, expanding each unique package only once."""
    documents: list[CorpusDocument] = []
    seen_packages: set[str] = set()
    skipped: list[str] = []

    def walk_container(data: bytes, label: str, depth: int) -> None:
        if depth > _MAX_NESTED_DEPTH or detect_container(data) != "zip":
            return
        package_hash = digest_bytes(data)
        if package_hash in seen_packages:
            return
        seen_packages.add(package_hash)
        try:
            entries = read_archive(data, limits)
        except CopilotError as exc:
            skipped.append(f"{label}:{exc.code}")
            return
        for entry in entries:
            lowered = entry.name.casefold()
            if lowered.endswith(".docx"):
                documents.append(
                    CorpusDocument(label=f"{label}!{entry.name}", payload=entry.payload)
                )
            elif lowered.endswith((".zip", ".axpp")):
                walk_container(entry.payload, f"{label}!{entry.name}", depth + 1)

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.casefold() not in _ALLOWED_SUFFIXES:
            continue
        suffix = path.suffix.casefold()
        try:
            data = path.read_bytes()
        except OSError:
            skipped.append(f"{path.name}:unreadable")
            continue
        if suffix == ".docx":
            documents.append(CorpusDocument(label=path.name, payload=data))
        else:
            walk_container(data, path.name, 1)
    if skipped:
        print(f"skipped {len(skipped)} unreadable container(s)", file=sys.stderr)
    return documents


def _document_row(
    index: int, document: CorpusDocument, report: D365BindingReport
) -> dict[str, Any]:
    return {
        "index": index,
        "sha256_12": document.sha256[:12],
        "schema_source": report.schema_source.value,
        "schema_evidence": len(report.schema_evidence),
        "project_data_parts": report.schema_summary.project_data_parts,
        "sources": report.schema_summary.sources,
        "fields": report.schema_summary.fields,
        "collections": report.schema_summary.collections,
        "preview_data_sources": report.schema_summary.preview_data_sources,
        "bindings": report.counts.total,
        "statuses": dict(report.counts.by_status),
        "resolved_with_evidence": report.counts.resolved_with_evidence,
        "resolved_without_evidence": report.counts.resolved_without_evidence,
        "diagnostics": len(report.diagnostics),
        "runtime_compatibility": report.runtime_compatibility,
    }


def assess(root: Path, *, limits: ReferenceLimits | None = None) -> dict[str, Any]:
    resolved_limits = limits or ReferenceLimits()
    if not root.is_dir():
        raise SystemExit(f"corpus directory does not exist: {root}")
    documents = collect_documents(root, resolved_limits)
    if not documents:
        raise SystemExit("no .docx documents found in the corpus")

    schema_sources: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    unique_payloads = {document.sha256 for document in documents}
    with_schema = 0
    without_schema = 0
    resolved_with_evidence = 0
    resolved_without_evidence = 0
    binding_total = 0
    for index, document in enumerate(documents, start=1):
        try:
            report = analyze_d365_bytes(
                document.payload,
                filename="corpus-document.docx",
                limits=resolved_limits,
            )
        except CopilotError as exc:
            failures.append({"index": str(index), "code": exc.code})
            schema_sources["analysis_error"] += 1
            continue
        schema_sources[report.schema_source.value] += 1
        statuses.update(report.counts.by_status)
        resolved_with_evidence += report.counts.resolved_with_evidence
        resolved_without_evidence += report.counts.resolved_without_evidence
        binding_total += report.counts.total
        if report.schema_summary.available:
            with_schema += 1
        else:
            without_schema += 1
        rows.append(_document_row(index, document, report))

    rows.sort(key=lambda row: (row["sha256_12"], row["index"]))
    return {
        "assessment_version": ASSESSMENT_VERSION,
        "documents": len(documents),
        "unique_document_payloads": len(unique_payloads),
        "schema_source": dict(sorted(schema_sources.items())),
        "availability": {
            "with_schema": with_schema,
            "without_schema": without_schema,
            "analysis_errors": len(failures),
        },
        "bindings": {
            "total": binding_total,
            "statuses": dict(sorted(statuses.items())),
            "resolved_with_evidence": resolved_with_evidence,
            "resolved_without_evidence": resolved_without_evidence,
        },
        "runtime_compatibility": "not_tested",
        "per_document": rows,
        "failures": failures,
    }


def _print_summary(payload: dict[str, Any]) -> None:
    print(f"D365 corpus documents: {payload['documents']}")
    print(f"Unique payloads: {payload['unique_document_payloads']}")
    print(f"Schema source: {payload['schema_source']}")
    print(f"Availability: {payload['availability']}")
    print(f"Bindings: {payload['bindings']['total']} {payload['bindings']['statuses']}")
    print(
        "Resolved with evidence: "
        f"{payload['bindings']['resolved_with_evidence']} "
        f"(without evidence: {payload['bindings']['resolved_without_evidence']})"
    )
    print(f"Runtime compatibility: {payload['runtime_compatibility']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True, help="Directory to scan")
    parser.add_argument("--json", type=Path, default=None, help="Write the JSON assessment here")
    args = parser.parse_args(argv)
    payload = assess(args.corpus)
    _print_summary(payload)
    if args.json is not None:
        target = args.json
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"Assessment written to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
