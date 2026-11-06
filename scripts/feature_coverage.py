#!/usr/bin/env python3
"""Validate and render the v0.13 feature coverage matrix.

The JSON is the machine-readable contract. This script checks that every
feature has five level statuses, evidence that exists in the repository, and a
limitation for every Partial/Unsupported/Not Tested level. It then renders
``docs/FEATURE_COVERAGE_V013.md`` deterministically.

Usage::

    python scripts/feature_coverage.py --check
    python scripts/feature_coverage.py --write
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Final

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "benchmarks" / "feature_coverage.json"
OUTPUT = ROOT / "docs" / "FEATURE_COVERAGE_V013.md"
LEVELS: Final = ("parsing", "reference_graph", "template_ir", "compiler", "validation")
STATUSES: Final = {"supported", "partial", "unsupported", "not_present", "not_tested"}
LEVEL_LABELS: Final = {
    "parsing": "Parsing",
    "reference_graph": "ReferenceGraph",
    "template_ir": "Template IR",
    "compiler": "DOCX Compiler",
    "validation": "Validation",
}


def load() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def validate(data: dict) -> list[str]:
    errors: list[str] = []
    features = data.get("features", [])
    if len(features) < 15:
        errors.append(f"expected at least 15 features, got {len(features)}")
    seen: set[str] = set()
    for feature in features:
        fid = feature.get("id", "")
        if not fid or fid in seen:
            errors.append(f"missing or duplicate feature id: {fid!r}")
        seen.add(fid)
        if not feature.get("name"):
            errors.append(f"{fid}: missing name")
        levels = feature.get("levels", {})
        if set(levels) != set(LEVELS):
            errors.append(f"{fid}: levels must be exactly {list(LEVELS)}")
        for level in LEVELS:
            status = levels.get(level)
            if status not in STATUSES:
                errors.append(f"{fid}.{level}: unknown status {status!r}")
        if any(
            levels.get(level) in {"partial", "unsupported", "not_tested"} for level in LEVELS
        ) and not feature.get("limitations"):
            errors.append(f"{fid}: Partial/Unsupported/Not Tested needs a limitation")
        if not feature.get("evidence"):
            errors.append(f"{fid}: missing evidence")
        for evidence in feature.get("evidence", []):
            path = evidence.split("::", 1)[0]
            if not (ROOT / path).exists():
                errors.append(f"{fid}: evidence path does not exist: {path}")
        if not isinstance(feature.get("present"), int) or feature["present"] < 0:
            errors.append(f"{fid}: present must be a non-negative integer")
    return errors


def render(data: dict) -> str:
    corpus = data["corpus"]
    lines = [
        "# Feature coverage — v0.13",
        "",
        "> Systematic audit of the official Docentric examples that are already present locally.",
        "> Counts are aggregate only; no private document name, path or payload is published.",
        "> GitHub Issues is the source of truth for follow-up work.",
        "",
        "## Corpus accounting",
        "",
        "| Metric | Count |",
        "| --- | ---: |",
        f"| AX 2012 official examples | {corpus['ax2012_examples']} |",
        f"| D365FO official entries | {corpus['d365fo_entries']} |",
        f"| Unique DOCX payloads (SHA-256) | {corpus['distinct_docx']} |",
        f"| DOCX artifacts | {corpus['docx_artifacts']} |",
        f"| All artifacts | {corpus['artifacts']} |",
        f"| Distinct artifacts | {corpus['distinct_artifacts']} |",
        f"| Duplicate groups / occurrences | {corpus['duplicate_groups']} / {corpus['duplicate_occurrences']} |",
        f"| Content controls | {corpus['controls']} |",
        f"| Resolved / unknown controls | {corpus['resolved_controls']} / {corpus['unknown_controls']} |",
        f"| Header / footer controls | {corpus['header_controls']} / {corpus['footer_controls']} |",
        "",
        "The table scan covered "
        f"{corpus['table_scan_documents']} parsed payloads and observed "
        f"{corpus['observed_tables']} tables, {corpus['observed_table_rows']} rows and "
        f"{corpus['observed_nested_tables']} nested table. It is a presence check, not a proof "
        "that every table in the archive is representable.",
        "",
        "## Matrix",
        "",
        "| Docentric feature | Present | Parsing | ReferenceGraph | Template IR | DOCX Compiler | Validation |",
        "| --- | ---: | --- | --- | --- | --- | --- |",
    ]
    for feature in data["features"]:
        levels = feature["levels"]
        cells = " | ".join(levels[level].replace("_", " ").title() for level in LEVELS)
        lines.append(f"| {feature['name']} | {feature['present']} | {cells} |")
    lines += [
        "",
        "Supported means a regression test exists for the claimed level. Partial means the "
        "construct is represented but a listed limitation remains. Unsupported means the "
        "importer/compiler deliberately refuses the construct and lists it in `skipped[]`; "
        "it is never silently dropped.",
        "",
        "## Evidence by feature",
        "",
    ]
    for feature in data["features"]:
        lines.append(f"### {feature['name']}")
        lines.append("")
        lines.append(
            "Status: "
            + ", ".join(f"{LEVEL_LABELS[level]} `{feature['levels'][level]}`" for level in LEVELS)
            + "."
        )
        lines.append("")
        lines.append("Evidence: " + ", ".join(f"`{item}`" for item in feature["evidence"]) + ".")
        if feature.get("limitations"):
            lines.append("")
            lines.append("Limitations:")
            for limitation in feature["limitations"]:
                lines.append(f"- {limitation}")
        lines.append("")
    lines += [
        "## Missing tests",
        "",
        *[f"- {item}" for item in data["missing_tests"]],
        "",
        "## Further work",
        "",
        *[f"- {item}" for item in data["further_work"]],
        "",
        "## Status vocabulary",
        "",
        "| Status | Meaning |",
        "| --- | --- |",
        "| Supported | Implemented and covered by a regression test at this level. |",
        "| Partial | Implemented for a documented subset; the limitation is listed above. |",
        "| Unsupported | Deliberately refused; the construct is reported, never guessed. |",
        "| Not Present | Not found in the audited examples; this is not a support claim. |",
        "| Not Tested | No regression test proves the behaviour; never reported as supported. |",
        "",
        "Generated from [`benchmarks/feature_coverage.json`](https://github.com/SergeyGer/Docentric-Copilot/blob/main/benchmarks/feature_coverage.json) "
        "by `python scripts/feature_coverage.py --write`.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    data = load()
    errors = validate(data)
    if errors:
        for error in errors:
            print(f"error: {error}")
        return 1
    rendered = render(data)
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != rendered:
            print(f"{OUTPUT.relative_to(ROOT)} is out of date; run --write")
            return 1
        print(f"feature coverage is valid: {len(data['features'])} features")
        return 0
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
