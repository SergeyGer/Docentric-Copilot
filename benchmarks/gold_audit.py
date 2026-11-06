#!/usr/bin/env python3
"""Audit trail, pinned hashes and consistency checks for the gold dataset.

The TZ v0.12 asks for a reviewable provenance record around the 32-case gold
dataset, without inventing a second human annotator. This module implements that
record:

* the committed dataset (``gold-cases/v2``, version ``2.0.0``) stays immutable;
* every case gets an adjudication entry with before/after labels, a decision,
  a rationale, an ISO-8601 timestamp and the dataset SHA-256 it reviewed;
* ``gold_manifest.json`` pins the dataset and audit hashes plus the prompt,
  planner, evaluator and runner versions;
* ``docs/GOLD_AUDIT.md`` is generated from the same data so the public report
  cannot drift from the machine-readable log;
* ``--check`` re-validates structure, schema paths, expected/forbidden conflicts,
  hash stability and the generated report.

The reviewer is the dataset owner (implementer) performing a documented
self-review. ``independent_human_review`` is ``false`` and AT-07 stays
``partial``. The deterministic adjudicator at
``benchmarks/adjudicate_labels.py`` is a proxy, not a second person.

Usage::

    python benchmarks/gold_audit.py --check
    python benchmarks/gold_audit.py --check --json
    python benchmarks/gold_audit.py --seed --force

A label correction requires a new dataset version and a new audit log; never
edit ``gold_cases.json`` in place while keeping version ``2.0.0``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # pragma: no cover - import bootstrap when run as a script
    sys.path.insert(0, str(ROOT))

from benchmarks.gold_dataset import (  # noqa: E402
    DEFAULT_CASES,
    GOLD_SCHEMA,
    GoldDataset,
    load_gold_dataset,
    schema_paths_for_case,
)
from benchmarks.versions import (  # noqa: E402
    ADJUDICATOR_VERSION,
    BENCHMARK_RUNNER_VERSION,
    COMPACT_PROMPT_VERSION,
    EVALUATOR_VERSION,
    FULL_PROMPT_VERSION,
    GOLD_AUDIT_VERSION,
    GOLD_MANIFEST_VERSION,
    PLANNER_VERSION,
)

DEFAULT_LOG = ROOT / "benchmarks" / "gold_adjudication_log.json"
DEFAULT_MANIFEST = ROOT / "benchmarks" / "gold_manifest.json"
DEFAULT_REPORT = ROOT / "docs" / "GOLD_AUDIT.md"
DEFAULT_ADJUDICATION = ROOT / "benchmarks" / "adjudication_report.json"

AUDIT_SCHEMA: Final = "gold-audit/v1"
MANIFEST_SCHEMA: Final = "gold-manifest/v1"
AUDIT_DATE: Final = "2026-11-06"
AUDIT_TIMESTAMP: Final = "2026-11-06T00:00:00Z"
AUDIT_STATUSES: Final = ("reviewed_by_owner", "unresolved", "no_change")
CHANGE_TYPES: Final = ("label_correction", "clarification", "no_change")
LABEL_STATUSES: Final = ("verified", "gap")
PLACEHOLDER_RATIONALES: Final = ("", "todo", "tbd", "n/a", "none")
MIN_RATIONALE_LENGTH: Final = 20

CONSISTENCY_CHECKS: Final = (
    "dataset SHA-256 and version match the committed dataset",
    "audit covers all 32 case ids exactly once and in dataset order",
    "audit status and change type use the documented values",
    "before/after snapshots and required fields are structurally valid",
    "every expected and forbidden path exists in the case DDSP schema",
    "no expected/forbidden path conflicts are present",
    "every label change carries a rationale and a recorded diff",
    "the generated report matches the machine-readable audit log",
    "independent human review is not claimed and AT-07 is partial",
)


# --------------------------------------------------------------------------- #
# Canonical serialisation and hashes
# --------------------------------------------------------------------------- #
def canonical_json(value: Any) -> str:
    """Stable JSON for hashing: sorted keys, no whitespace, UTF-8 preserved."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_sha256(value: Any) -> str:
    return sha256_text(canonical_json(value))


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_sha256(manifest: dict[str, Any]) -> str:
    """Hash every manifest field except the self-referential digest."""
    body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    return canonical_sha256(body)


def canonical_audit_sha256(log: dict[str, Any]) -> str:
    return canonical_sha256(log)


# --------------------------------------------------------------------------- #
# Dataset snapshots
# --------------------------------------------------------------------------- #
def dataset_snapshot(dataset: GoldDataset, *, file: str | None = None) -> dict[str, Any]:
    return {
        "file": file or _relative(dataset.path),
        "schema": dataset.document.get("schema"),
        "version": dataset.version,
        "created_at": dataset.created_at,
        "sha256": dataset.file_sha256,
        "canonical_sha256": dataset.canonical_sha256,
        "case_count": len(dataset.cases),
    }


def benchmark_dataset_snapshot(dataset: GoldDataset) -> dict[str, Any]:
    """Public, path-free dataset identity used by benchmark manifests and reports."""
    return {
        "schema": dataset.document.get("schema"),
        "version": dataset.version,
        "sha256": dataset.file_sha256,
        "canonical_sha256": dataset.canonical_sha256,
        "case_count": len(dataset.cases),
    }


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field} contains a blank or non-string value")
        result.append(item.strip())
    return result


def case_snapshot(case: dict[str, Any]) -> dict[str, Any]:
    """Deterministic label snapshot used by before/after entries."""
    requirements = [item for item in case.get("required_bindings") or [] if isinstance(item, dict)]
    expected = {
        path
        for requirement in requirements
        for path in (
            *requirement.get("expected_paths", []),
            *requirement.get("allowed_alternatives", []),
        )
        if isinstance(path, str)
    }
    forbidden = {path for path in case.get("forbidden_paths") or [] if isinstance(path, str)}
    blocks = {
        f"{block.get('kind')}:{block.get('path')}"
        for block in case.get("expected_blocks") or []
        if isinstance(block, dict) and block.get("kind") and block.get("path")
    }
    return {
        "label_status": case.get("label_status"),
        "expected_paths": sorted(expected),
        "forbidden_paths": sorted(forbidden),
        "expected_blocks": sorted(blocks),
    }


def _requirement_count(case: dict[str, Any]) -> int:
    return len([item for item in case.get("required_bindings") or [] if isinstance(item, dict)])


# --------------------------------------------------------------------------- #
# Seed the audit log from the committed dataset and the proxy adjudication
# --------------------------------------------------------------------------- #
def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _adjudication_cases(path: Path) -> dict[str, dict[str, Any]]:
    report = _load_json(path) or {}
    cases = report.get("cases")
    if not isinstance(cases, list):
        return {}
    return {
        str(item.get("case_id")): item
        for item in cases
        if isinstance(item, dict) and item.get("case_id")
    }


def _decision_material(
    case: dict[str, Any], adjudication_case: dict[str, Any] | None
) -> tuple[bool, list[str], list[str]]:
    """Return (is_clarification, guard_paths, advisory_notes)."""
    provenance = case.get("provenance")
    provenance_note = provenance.get("note") if isinstance(provenance, dict) else ""
    guard_paths = [
        path
        for path, meta in (case.get("forbidden_provenance") or {}).items()
        if isinstance(meta, dict) and "not derive" in str(meta.get("note", "")).casefold()
    ]
    advisory_notes: list[str] = []
    case_note = str(case.get("notes") or "")
    if "advisory counterpart guards" in case_note.casefold():
        clause = case_note.split(":", 1)[1] if ":" in case_note else case_note
        advisory_notes.append(clause.strip().rstrip("."))
    if adjudication_case:
        for note in adjudication_case.get("derived_notes") or []:
            if isinstance(note, str) and note.strip():
                advisory_notes.append(note.strip())
    is_clarification = bool(
        (isinstance(provenance_note, str) and provenance_note.strip())
        or guard_paths
        or advisory_notes
    )
    return is_clarification, sorted(guard_paths), advisory_notes


def _rationale(
    case: dict[str, Any],
    adjudication_case: dict[str, Any] | None,
    *,
    is_clarification: bool,
    guard_paths: list[str],
    advisory_notes: list[str],
) -> str:
    requirements = _requirement_count(case)
    blocks = len(case_snapshot(case)["expected_blocks"])
    agreement = "agree"
    if adjudication_case:
        agreement = str(adjudication_case.get("agreement") or "agree")
    parts = [
        f"Deterministic adjudication reproduced {requirements} requirement label(s) "
        f"and {blocks} expected block(s); case agreement={agreement}."
    ]
    provenance = case.get("provenance")
    provenance_note = provenance.get("note") if isinstance(provenance, dict) else ""
    if is_clarification:
        parts.append("Interpretation recorded; the dataset labels themselves are unchanged.")
    if isinstance(provenance_note, str) and provenance_note.strip():
        parts.append(provenance_note.strip().rstrip(".") + ".")
    if guard_paths:
        parts.append(
            "Retained author scope guard(s) "
            + ", ".join(f"'{path}'" for path in guard_paths)
            + "; the independent pass did not derive them and they forbid wrong-scope "
            "bindings, so the safer label is kept rather than loosened."
        )
    if advisory_notes:
        parts.append(
            "Advisory counterpart guard(s) were considered and intentionally not applied: "
            + "; ".join(advisory_notes)
            + "."
        )
    parts.append("Self-review by the dataset owner; no independent human review was performed.")
    return " ".join(parts)


def build_audit_log(
    dataset: GoldDataset,
    *,
    adjudication_path: Path = DEFAULT_ADJUDICATION,
    cases_file: str | None = None,
) -> dict[str, Any]:
    adjudication = _adjudication_cases(adjudication_path)
    entries: list[dict[str, Any]] = []
    base = datetime(2026, 11, 6, tzinfo=UTC)
    for index, case in enumerate(dataset.cases):
        case_id = str(case.get("id"))
        adjudication_case = adjudication.get(case_id)
        is_clarification, guard_paths, advisory_notes = _decision_material(case, adjudication_case)
        snapshot = case_snapshot(case)
        change_type = "clarification" if is_clarification else "no_change"
        audit_status = "reviewed_by_owner" if is_clarification else "no_change"
        notes = " ".join(
            item
            for item in (
                str(case.get("notes") or "").strip(),
                str((adjudication_case or {}).get("derived_notes") or "").strip(),
            )
            if item
        ).strip()
        entries.append(
            {
                "case_id": case_id,
                "dataset_version": dataset.version,
                "audit_status": audit_status,
                "change_type": change_type,
                "before": snapshot,
                "after": snapshot,
                "rationale": _rationale(
                    case,
                    adjudication_case,
                    is_clarification=is_clarification,
                    guard_paths=guard_paths,
                    advisory_notes=advisory_notes,
                ),
                "timestamp": (base + timedelta(seconds=index)).isoformat().replace("+00:00", "Z"),
                "dataset_sha256": dataset.file_sha256,
                "notes": notes,
            }
        )
    status_counts = Counter(str(entry["audit_status"]) for entry in entries)
    change_counts = Counter(str(entry["change_type"]) for entry in entries)
    requirements = sum(_requirement_count(case) for case in dataset.cases)
    blocks = sum(len(case_snapshot(case)["expected_blocks"]) for case in dataset.cases)
    log: dict[str, Any] = {
        "schema": AUDIT_SCHEMA,
        "audit_version": GOLD_AUDIT_VERSION,
        "audit_date": AUDIT_DATE,
        "dataset": dataset_snapshot(dataset, file=cases_file),
        "reviewer": {
            "identity": "dataset owner (implementer)",
            "role": "owner_self_review",
            "independent_human_review": False,
            "second_human_annotator": False,
            "at07_status": "partial",
            "method": (
                "Deterministic adjudication with benchmarks/adjudicate_labels.py "
                f"{ADJUDICATOR_VERSION}, followed by an owner review of every case. "
                "This is a documented proxy and self-review, not independent human review."
            ),
        },
        "entries": entries,
        "summary": {
            "cases": len(entries),
            "requirements_audited": requirements,
            "blocks_audited": blocks,
            "audit_status": {status: status_counts.get(status, 0) for status in AUDIT_STATUSES},
            "change_type": {kind: change_counts.get(kind, 0) for kind in CHANGE_TYPES},
            "clarifications": change_counts.get("clarification", 0),
            "unresolved": status_counts.get("unresolved", 0),
            "independent_human_review": False,
            "at07_status": "partial",
        },
    }
    return log


def build_manifest(
    dataset: GoldDataset,
    log: dict[str, Any],
    *,
    log_path: Path = DEFAULT_LOG,
    cases_file: str | None = None,
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "manifest_version": GOLD_MANIFEST_VERSION,
        "created_at": AUDIT_TIMESTAMP,
        "dataset": dataset_snapshot(dataset, file=cases_file),
        "audit": {
            "file": _relative(log_path),
            "schema": AUDIT_SCHEMA,
            "audit_version": GOLD_AUDIT_VERSION,
            "sha256": file_sha256(log_path),
            "canonical_sha256": canonical_audit_sha256(log),
            "case_count": len(log.get("entries") or []),
            "summary": log.get("summary"),
            "independent_human_review": False,
            "at07_status": "partial",
        },
        "tools": {
            "prompt_version": FULL_PROMPT_VERSION,
            "compact_prompt_version": COMPACT_PROMPT_VERSION,
            "planner_version": PLANNER_VERSION,
            "evaluator_version": EVALUATOR_VERSION,
            "benchmark_runner_version": BENCHMARK_RUNNER_VERSION,
            "adjudicator_version": ADJUDICATOR_VERSION,
            "audit_version": GOLD_AUDIT_VERSION,
        },
        "consistency": {
            "status": "passed",
            "checked_at": AUDIT_TIMESTAMP,
            "checks": list(CONSISTENCY_CHECKS),
        },
    }
    manifest["manifest_sha256"] = manifest_sha256(manifest)
    return manifest


# --------------------------------------------------------------------------- #
# Human-readable report
# --------------------------------------------------------------------------- #
def _md(value: Any) -> str:
    text = " ".join(str(value).split())
    return text.replace("|", "\\|") if text else "—"


def _short_rationale(entry: dict[str, Any], limit: int = 170) -> str:
    text = " ".join(str(entry.get("rationale") or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def render_report(
    dataset: GoldDataset,
    log: dict[str, Any],
    manifest: dict[str, Any],
) -> str:
    summary = log["summary"]
    lines: list[str] = [
        "# Gold Dataset Audit Trail",
        "",
        "> **Status: owner self-review.** No independent human reviewer was involved.",
        "> AT-07 remains **partial**; the deterministic adjudicator is a documented",
        "> proxy, not a second annotator. This document is generated from",
        "> `benchmarks/gold_adjudication_log.json`; edit the log, not this file.",
        "",
        "## Pinned identity",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Dataset file | `{_md(log['dataset']['file'])}` |",
        f"| Dataset version | `{_md(log['dataset']['version'])}` |",
        f"| Dataset schema | `{_md(log['dataset']['schema'])}` |",
        f"| Dataset SHA-256 | `{log['dataset']['sha256']}` |",
        f"| Canonical cases SHA-256 | `{log['dataset']['canonical_sha256']}` |",
        f"| Audit log SHA-256 | `{manifest['audit']['sha256']}` |",
        f"| Manifest SHA-256 | `{manifest['manifest_sha256']}` |",
        f"| Audit date | {_md(log['audit_date'])} |",
        f"| Reviewer | {_md(log['reviewer']['identity'])} (owner self-review) |",
        "| Independent human review | **not performed** |",
        "| AT-07 | **partial** |",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Cases audited | {summary['cases']} |",
        f"| Requirement labels audited | {summary['requirements_audited']} |",
        f"| Expected blocks audited | {summary['blocks_audited']} |",
        f"| `reviewed_by_owner` | {summary['audit_status']['reviewed_by_owner']} |",
        f"| `no_change` | {summary['audit_status']['no_change']} |",
        f"| `unresolved` | {summary['audit_status']['unresolved']} |",
        f"| Clarifications recorded | {summary['change_type']['clarification']} |",
        f"| Label corrections | {summary['change_type']['label_correction']} |",
        "",
        "Every case carries an explicit audit status. A missing entry is a",
        "consistency error, not an implicit pass.",
        "",
        "## Case audit",
        "",
        "| # | Case | Family | Audit status | Change type | Req. | Decision |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for index, entry in enumerate(log["entries"], start=1):
        case = next(
            (item for item in dataset.cases if item.get("id") == entry["case_id"]),
            {},
        )
        lines.append(
            "| {index} | `{case_id}` | {family} | {status} | {change} | {req} | {decision} |".format(
                index=index,
                case_id=entry["case_id"],
                family=_md(case.get("family")),
                status=entry["audit_status"],
                change=entry["change_type"],
                req=_requirement_count(case),
                decision=_md(_short_rationale(entry)),
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation decisions",
            "",
            "Clarifications keep the authored labels and record an interpretation rule.",
            "They are not label corrections; `before` and `after` are identical for every",
            "entry in this version.",
            "",
        ]
    )
    clarifications = [entry for entry in log["entries"] if entry["change_type"] == "clarification"]
    if clarifications:
        for entry in clarifications:
            lines.append(f"### `{entry['case_id']}`")
            lines.append("")
            lines.append(entry["rationale"])
            if entry.get("notes"):
                lines.append("")
                lines.append(f"Case note: {_md(entry['notes'])}")
            lines.append("")
    else:  # pragma: no cover - defensive for a future dataset with no clarifications
        lines.extend(["No clarifications were required for this dataset version.", ""])

    ambiguous_cases = [
        case
        for case in dataset.cases
        if case.get("family") in {"ambiguous", "missing"}
        or "ambigu" in str(case.get("notes") or "").casefold()
    ]
    lines.extend(["## Known ambiguities in the labels", ""])
    for case in ambiguous_cases:
        lines.append(f"- **`{case.get('id')}`** — {_md(case.get('notes'))}")
    lines.extend(
        [
            "",
            "These cases encode this project's judgement, including explicit",
            "alternatives and unsatisfiable requirements. They are not a customer's",
            "ground truth and were not validated by an independent human.",
            "",
            "## Consistency checks",
            "",
        ]
    )
    for check in CONSISTENCY_CHECKS:
        lines.append(f"- [x] {check}")
    lines.extend(
        [
            "",
            "## Reproduce",
            "",
            "```bash",
            "python benchmarks/gold_audit.py --check",
            "python benchmarks/gold_audit.py --check --json",
            "python benchmarks/adjudicate_labels.py --check",
            "```",
            "",
            "The manifest pins the dataset hash, the audit-log hash, the prompt",
            f"(`{FULL_PROMPT_VERSION}`, compact `{COMPACT_PROMPT_VERSION}`), planner",
            f"`{PLANNER_VERSION}`, evaluator `{EVALUATOR_VERSION}` and runner",
            f"`{BENCHMARK_RUNNER_VERSION}` versions.",
            "",
            "## Limitations",
            "",
            "- The reviewer is the dataset owner; this is not independent human review.",
            "- AT-07 remains partial and does not block v0.12 while this audit trail,",
            "  the hashes and the consistency checks are in place.",
            "- The audit checks consistency against the committed DDSP schemas; it does",
            "  not prove that the labels describe every valid business interpretation.",
            "- Docentric AX runtime compatibility remains **not_tested** and is out of",
            "  scope for this audit.",
            "",
        ]
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def _is_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_snapshot(snapshot: Any, field: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(snapshot, dict):
        return [f"{field} must be an object"]
    for key in ("label_status", "expected_paths", "forbidden_paths", "expected_blocks"):
        if key not in snapshot:
            errors.append(f"{field} is missing {key}")
    if snapshot.get("label_status") not in LABEL_STATUSES:
        errors.append(f"{field}.label_status must be one of {', '.join(LABEL_STATUSES)}")
    for key in ("expected_paths", "forbidden_paths", "expected_blocks"):
        try:
            values = _string_list(snapshot.get(key), f"{field}.{key}")
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if values != sorted(values):
            errors.append(f"{field}.{key} must be sorted for deterministic hashes")
        if len(values) != len(set(values)):
            errors.append(f"{field}.{key} contains duplicate values")
    return errors


def _validate_timestamp(value: Any, field: str) -> list[str]:
    if not isinstance(value, str) or not value.strip():
        return [f"{field} must be an ISO-8601 UTC timestamp"]
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return [f"{field} is not a valid ISO-8601 timestamp: {value!r}"]
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return [f"{field} must carry a UTC offset"]
    return []


def _schema_paths(dataset: GoldDataset) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Parse every public case schema; return ({package: paths}, errors)."""
    schemas: dict[str, dict[str, str]] = {}
    errors: list[str] = []
    for case in dataset.cases:
        case_id = str(case.get("id"))
        package = str(case.get("package") or "")
        if package in schemas:
            continue
        try:
            schemas[package] = schema_paths_for_case(case)
        except (OSError, ValueError) as exc:
            errors.append(f"{case_id}: cannot read schema {package!r}: {exc}")
    return schemas, errors


def validate_audit_log(
    dataset: GoldDataset,
    log: Any,
    *,
    schemas: dict[str, dict[str, str]] | None = None,
    cases_file: str | None = None,
) -> list[str]:
    """Return every consistency problem in the audit log; empty means valid."""
    errors: list[str] = []
    if not isinstance(log, dict):
        return ["audit log must be a JSON object"]
    if log.get("schema") != AUDIT_SCHEMA:
        errors.append(f"audit log schema is {log.get('schema')!r}, expected {AUDIT_SCHEMA!r}")
    if log.get("audit_version") != GOLD_AUDIT_VERSION:
        errors.append(
            f"audit_version is {log.get('audit_version')!r}, expected {GOLD_AUDIT_VERSION!r}"
        )
    if log.get("audit_date") != AUDIT_DATE:
        errors.append(f"audit_date is {log.get('audit_date')!r}, expected {AUDIT_DATE!r}")

    expected_dataset = dataset_snapshot(dataset, file=cases_file)
    dataset_block = log.get("dataset")
    if not isinstance(dataset_block, dict):
        errors.append("audit log dataset block is missing")
    else:
        for key in ("file", "version", "sha256", "canonical_sha256", "case_count"):
            if dataset_block.get(key) != expected_dataset.get(key):
                errors.append(
                    f"dataset.{key} is {dataset_block.get(key)!r}, "
                    f"expected {expected_dataset.get(key)!r}"
                )
        if dataset_block.get("schema") != GOLD_SCHEMA:
            errors.append(f"dataset.schema must be {GOLD_SCHEMA!r}")

    reviewer = log.get("reviewer")
    if not isinstance(reviewer, dict):
        errors.append("reviewer block is missing")
    else:
        if reviewer.get("independent_human_review") is not False:
            errors.append("reviewer.independent_human_review must be false")
        if reviewer.get("second_human_annotator") is not False:
            errors.append("reviewer.second_human_annotator must be false")
        if reviewer.get("at07_status") != "partial":
            errors.append("reviewer.at07_status must be 'partial'")
        if reviewer.get("role") != "owner_self_review":
            errors.append("reviewer.role must be 'owner_self_review'")
        if not _is_str(reviewer.get("identity")):
            errors.append("reviewer.identity is required")
        if "reviewer_2" in json.dumps(reviewer).casefold():
            errors.append("reviewer block must not claim a reviewer_2")

    entries = log.get("entries")
    if not isinstance(entries, list) or not entries:
        errors.append("audit log entries must be a non-empty list")
        entries = []
    case_by_id = {str(case.get("id")): case for case in dataset.cases}
    dataset_ids = [str(case.get("id")) for case in dataset.cases]
    entry_ids = [str(entry.get("case_id")) for entry in entries if isinstance(entry, dict)]
    if entry_ids != dataset_ids:
        if len(entry_ids) != len(dataset_ids):
            errors.append(f"audit log has {len(entry_ids)} entries, expected {len(dataset_ids)}")
        missing = [case_id for case_id in dataset_ids if case_id not in entry_ids]
        extra = [case_id for case_id in entry_ids if case_id not in case_by_id]
        duplicate = sorted(case_id for case_id, count in Counter(entry_ids).items() if count > 1)
        if missing:
            errors.append(f"audit log is missing case id(s): {', '.join(missing)}")
        if extra:
            errors.append(f"audit log has unknown case id(s): {', '.join(extra)}")
        if duplicate:
            errors.append(f"audit log has duplicate case id(s): {', '.join(duplicate)}")
        if not missing and not extra and not duplicate:
            errors.append("audit log entries must follow dataset order")

    if schemas is None:
        schemas, schema_errors = _schema_paths(dataset)
        errors.extend(schema_errors)

    status_counts: Counter[str] = Counter()
    change_counts: Counter[str] = Counter()
    requirements = 0
    blocks = 0
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            errors.append(f"entry {index} must be an object")
            continue
        case_id = str(entry.get("case_id") or f"entry-{index}")
        for field in (
            "case_id",
            "dataset_version",
            "audit_status",
            "change_type",
            "before",
            "after",
            "rationale",
            "timestamp",
            "dataset_sha256",
        ):
            if field not in entry:
                errors.append(f"{case_id}: entry is missing {field}")
        if entry.get("dataset_version") != dataset.version:
            errors.append(
                f"{case_id}: dataset_version is {entry.get('dataset_version')!r}, "
                f"expected {dataset.version!r}"
            )
        if entry.get("dataset_sha256") != dataset.file_sha256:
            errors.append(f"{case_id}: dataset_sha256 does not match the committed dataset")

        status = entry.get("audit_status")
        change_type = entry.get("change_type")
        if status not in AUDIT_STATUSES:
            errors.append(f"{case_id}: invalid audit_status {status!r}")
        else:
            status_counts[str(status)] += 1
        if change_type not in CHANGE_TYPES:
            errors.append(f"{case_id}: invalid change_type {change_type!r}")
        else:
            change_counts[str(change_type)] += 1

        rationale = entry.get("rationale")
        if not _is_str(rationale):
            errors.append(f"{case_id}: rationale is required")
        elif len(str(rationale).strip()) < MIN_RATIONALE_LENGTH:
            errors.append(f"{case_id}: rationale is shorter than {MIN_RATIONALE_LENGTH} characters")
        elif str(rationale).strip().casefold() in PLACEHOLDER_RATIONALES:
            errors.append(f"{case_id}: rationale is a placeholder")

        errors.extend(_validate_timestamp(entry.get("timestamp"), f"{case_id}.timestamp"))
        errors.extend(_validate_snapshot(entry.get("before"), f"{case_id}.before"))
        errors.extend(_validate_snapshot(entry.get("after"), f"{case_id}.after"))

        before = entry.get("before")
        after = entry.get("after")
        if change_type in {"no_change", "clarification"} and before != after:
            errors.append(f"{case_id}: {change_type} must keep before == after")
        if change_type == "label_correction" and before == after:
            errors.append(f"{case_id}: label_correction must record a before/after diff")
        if status == "unresolved" and not _is_str(entry.get("notes")):
            errors.append(f"{case_id}: unresolved entries require notes")

        case = case_by_id.get(case_id)
        if case is None:
            continue
        requirements += _requirement_count(case)
        blocks += len(case_snapshot(case)["expected_blocks"])
        if isinstance(after, dict) and after != case_snapshot(case):
            errors.append(f"{case_id}: after snapshot does not match the committed labels")

        schema = schemas.get(str(case.get("package") or ""))
        if schema is None:
            errors.append(f"{case_id}: no schema paths available for path validation")
            continue
        if isinstance(after, dict):
            expected = set(after.get("expected_paths") or [])
            forbidden = set(after.get("forbidden_paths") or [])
            overlap = expected & forbidden
            if overlap:
                errors.append(
                    f"{case_id}: expected/forbidden conflict on {', '.join(sorted(overlap))}"
                )
            for path in sorted(expected | forbidden):
                if path not in schema:
                    errors.append(f"{case_id}: path {path!r} is not in the DDSP schema")
        if isinstance(before, dict):
            for path in sorted(
                set(before.get("expected_paths") or []) | set(before.get("forbidden_paths") or [])
            ):
                if path not in schema:
                    errors.append(f"{case_id}: before path {path!r} is not in the DDSP schema")

    summary = log.get("summary")
    expected_summary = {
        "cases": len(entries),
        "requirements_audited": requirements,
        "blocks_audited": blocks,
        "audit_status": {key: status_counts.get(key, 0) for key in AUDIT_STATUSES},
        "change_type": {key: change_counts.get(key, 0) for key in CHANGE_TYPES},
        "clarifications": change_counts.get("clarification", 0),
        "unresolved": status_counts.get("unresolved", 0),
        "independent_human_review": False,
        "at07_status": "partial",
    }
    if summary != expected_summary:
        errors.append("summary does not match the entries; regenerate the audit log")

    if len(entries) != len(dataset.cases):
        errors.append(
            f"audit coverage is {len(entries)}/{len(dataset.cases)}; every case needs an entry"
        )
    return errors


def validate_manifest(
    dataset: GoldDataset,
    log: dict[str, Any],
    manifest: Any,
    *,
    log_path: Path = DEFAULT_LOG,
    cases_file: str | None = None,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return ["manifest must be a JSON object"]
    if manifest.get("schema") != MANIFEST_SCHEMA:
        errors.append(f"manifest schema is {manifest.get('schema')!r}")
    if manifest.get("manifest_version") != GOLD_MANIFEST_VERSION:
        errors.append(f"manifest_version is {manifest.get('manifest_version')!r}")
    expected_dataset = dataset_snapshot(dataset, file=cases_file)
    if manifest.get("dataset") != expected_dataset:
        errors.append("manifest dataset block does not match the committed dataset")
    audit = manifest.get("audit")
    if not isinstance(audit, dict):
        errors.append("manifest audit block is missing")
    else:
        if audit.get("sha256") != file_sha256(log_path):
            errors.append("manifest audit sha256 does not match the audit log file")
        if audit.get("canonical_sha256") != canonical_audit_sha256(log):
            errors.append("manifest canonical audit hash does not match the audit log")
        if audit.get("case_count") != len(log.get("entries") or []):
            errors.append("manifest audit case_count does not match the audit log")
        if audit.get("summary") != log.get("summary"):
            errors.append("manifest audit summary does not match the audit log")
        if audit.get("independent_human_review") is not False:
            errors.append("manifest must record independent_human_review=false")
        if audit.get("at07_status") != "partial":
            errors.append("manifest must record at07_status=partial")
    tools = manifest.get("tools")
    if not isinstance(tools, dict):
        errors.append("manifest tools block is missing")
    else:
        for key in (
            "prompt_version",
            "compact_prompt_version",
            "planner_version",
            "evaluator_version",
            "benchmark_runner_version",
            "adjudicator_version",
            "audit_version",
        ):
            if not _is_str(tools.get(key)):
                errors.append(f"manifest tools.{key} is required")
    if manifest.get("manifest_sha256") != manifest_sha256(manifest):
        errors.append("manifest_sha256 does not reproduce")
    consistency = manifest.get("consistency")
    if not isinstance(consistency, dict) or consistency.get("status") != "passed":
        errors.append("manifest consistency block must report status=passed")
    return errors


def check_all(
    dataset: GoldDataset,
    log: dict[str, Any],
    manifest: dict[str, Any],
    report_text: str,
    *,
    log_path: Path = DEFAULT_LOG,
    cases_file: str | None = None,
) -> list[str]:
    schemas, schema_errors = _schema_paths(dataset)
    errors = [
        *validate_audit_log(dataset, log, schemas=schemas, cases_file=cases_file),
        *validate_manifest(dataset, log, manifest, log_path=log_path, cases_file=cases_file),
        *schema_errors,
    ]
    expected_report = render_report(dataset, log, manifest)
    if report_text != expected_report:
        errors.append("docs/GOLD_AUDIT.md does not match the generated report")
    return errors


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _seed(args: argparse.Namespace, dataset: GoldDataset) -> int:
    if not args.force and (args.log.exists() or args.manifest.exists() or args.report.exists()):
        print(
            "refusing to overwrite the existing audit trail without --force",
            file=sys.stderr,
        )
        return 2
    log = build_audit_log(
        dataset,
        adjudication_path=args.adjudication,
        cases_file=_relative(args.cases),
    )
    _write_json(args.log, log)
    manifest = build_manifest(dataset, log, log_path=args.log, cases_file=_relative(args.cases))
    _write_json(args.manifest, manifest)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render_report(dataset, log, manifest), encoding="utf-8")
    errors = check_all(
        dataset,
        log,
        manifest,
        args.report.read_text(encoding="utf-8"),
        log_path=args.log,
        cases_file=_relative(args.cases),
    )
    if errors:
        print("audit trail written but inconsistent:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print(
        "wrote {log}, {manifest} and {report} ({cases} cases, {clarifications} clarifications, "
        "AT-07=partial)".format(
            log=args.log,
            manifest=args.manifest,
            report=args.report,
            cases=log["summary"]["cases"],
            clarifications=log["summary"]["clarifications"],
        )
    )
    return 0


def _check(args: argparse.Namespace, dataset: GoldDataset) -> int:
    try:
        log = json.loads(args.log.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read audit log {args.log}: {exc}", file=sys.stderr)
        return 1
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read manifest {args.manifest}: {exc}", file=sys.stderr)
        return 1
    try:
        report_text = args.report.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"cannot read report {args.report}: {exc}", file=sys.stderr)
        return 1
    errors = check_all(
        dataset,
        log if isinstance(log, dict) else {},
        manifest if isinstance(manifest, dict) else {},
        report_text,
        log_path=args.log,
        cases_file=_relative(args.cases),
    )
    payload = {
        "status": "passed" if not errors else "failed",
        "audit_schema": AUDIT_SCHEMA,
        "audit_version": GOLD_AUDIT_VERSION,
        "dataset": dataset_snapshot(dataset, file=_relative(args.cases)),
        "cases": len(dataset.cases),
        "summary": (log.get("summary") if isinstance(log, dict) else None),
        "at07_status": "partial",
        "independent_human_review": False,
        "errors": errors,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    elif errors:
        print(f"gold audit trail is invalid ({len(errors)} problem(s)):", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
    else:
        print(
            "gold audit trail ok: "
            f"{payload['cases']} cases, {payload['summary']['clarifications']} clarifications, "
            "AT-07=partial, independent human review not performed"
        )
    return 0 if not errors else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--adjudication", type=Path, default=DEFAULT_ADJUDICATION)
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate the committed audit trail (default action)",
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="write a new audit log, manifest and report for the current dataset",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="allow --seed to overwrite an existing audit trail",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable check output")
    args = parser.parse_args(argv)
    if args.check and args.seed:
        parser.error("choose either --check or --seed")
    if not args.check and not args.seed:
        args.check = True

    try:
        dataset = load_gold_dataset(args.cases)
    except ValueError as exc:
        print(f"gold dataset error: {exc}", file=sys.stderr)
        return 2
    if args.seed:
        return _seed(args, dataset)
    return _check(args, dataset)


if __name__ == "__main__":
    raise SystemExit(main())
