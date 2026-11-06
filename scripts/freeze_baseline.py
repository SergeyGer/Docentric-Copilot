#!/usr/bin/env python3
"""Freeze and verify the v0.11.0 benchmark baseline for the v0.12 release.

The v0.12 TZ requires a fixed baseline before any work starts: the exact tag and
commit, the gold dataset identity, the adjudication artifact, the provider model
IDs, the prompt versions and the historical D365 corpus aggregate. The frozen
file is public-safe: it contains no corpus paths, document hashes or secrets.

Usage::

    python scripts/freeze_baseline.py                 # write the baseline file
    python scripts/freeze_baseline.py --check         # verify it
    python scripts/freeze_baseline.py --json          # machine-readable check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # pragma: no cover - import bootstrap when run as a script
    sys.path.insert(0, str(ROOT))

from benchmarks.gold_audit import benchmark_dataset_snapshot  # noqa: E402
from benchmarks.gold_dataset import load_gold_dataset  # noqa: E402
from benchmarks.versions import COMPACT_PROMPT_VERSION, FULL_PROMPT_VERSION  # noqa: E402
from docentric_copilot import COMPILER_VERSION, IR_VERSION, __version__  # noqa: E402

DEFAULT_BASELINE = ROOT / "benchmarks" / "baseline_v011.json"
DATASET = ROOT / "benchmarks" / "gold_cases.json"
ADJUDICATION = ROOT / "benchmarks" / "adjudication_report.json"
CORPUS_ASSESSMENT = ROOT / ".tools" / "v010" / "corpus-assessment.json"
BASELINE_SCHEMA = "baseline-freeze/v1"
BASELINE_VERSION = "0.11.0"
BASELINE_TAG = "v0.11.0"
BASELINE_COMMIT = "3101c9a422f091a02dccd8a29a79543444c37f49"
FROZEN_AT = "2026-11-06T00:00:00Z"

# The v0.11 audit's public aggregate. 233/13 is a baseline observation, not a
# guarantee about the v0.12 graph builder.
D365_BASELINE: dict[str, Any] = {
    "documents": 11,
    "bindings": 246,
    "resolved_with_evidence": 233,
    "unresolved": 13,
    "resolved_without_evidence": 0,
    "statuses": {
        "ambiguous": 0,
        "resolved": 233,
        "schema_unavailable": 0,
        "type_mismatch": 1,
        "unknown_path": 4,
        "unsupported_expression": 8,
    },
    "runtime_compatibility": "not_tested",
    "source": "v0.11.0 audit (local aggregate only; no corpus content or hashes)",
}

MODELS = {
    "openai": "gpt-6-sol",
    "anthropic": "claude-sonnet-5-5",
    "gemini": "gemini-3.6-flash",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _versions() -> dict[str, Any]:
    versions: dict[str, Any] = {
        "python": platform.python_version(),
        "product_version": __version__,
        "ir_version": IR_VERSION,
        "compiler_version": COMPILER_VERSION,
        "model_runtime": "not_tested",
    }
    try:
        from importlib.metadata import version

        for package in ("pytest", "ruff", "playwright", "mypy"):
            try:
                versions[package] = version(package)
            except Exception:  # pragma: no cover - optional tooling
                versions[package] = None
    except Exception:  # pragma: no cover - importlib is always present on 3.12
        pass
    import shutil

    versions["renderer"] = {
        "libreoffice": shutil.which("soffice") is not None,
        "poppler": shutil.which("pdftoppm") is not None,
    }
    return versions


def _adjudication_summary() -> dict[str, Any]:
    try:
        report = json.loads(ADJUDICATION.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"available": False}
    return {
        "available": True,
        "file": "benchmarks/adjudication_report.json",
        "sha256": _sha256(ADJUDICATION),
        "schema": report.get("schema"),
        "adjudicator_version": report.get("adjudicator_version"),
        "summary": report.get("summary"),
        "at07_status": (report.get("at07") or {}).get("status"),
        "second_human_annotator": (report.get("at07") or {}).get("second_human_annotator"),
    }


def _corpus_aggregate() -> dict[str, Any]:
    """Prefer the local v0.11 assessment; fall back to the frozen aggregate."""
    try:
        report = json.loads(CORPUS_ASSESSMENT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(D365_BASELINE)
    bindings = report.get("bindings") if isinstance(report, dict) else None
    if not isinstance(bindings, dict):
        return dict(D365_BASELINE)
    statuses = bindings.get("statuses") or {}
    aggregate = {
        **D365_BASELINE,
        "documents": report.get("documents", D365_BASELINE["documents"]),
        "bindings": bindings.get("total", D365_BASELINE["bindings"]),
        "resolved_with_evidence": bindings.get(
            "resolved_with_evidence", D365_BASELINE["resolved_with_evidence"]
        ),
        "resolved_without_evidence": bindings.get(
            "resolved_without_evidence", D365_BASELINE["resolved_without_evidence"]
        ),
        "statuses": {
            key: statuses.get(key, 0)
            for key in (
                "ambiguous",
                "resolved",
                "schema_unavailable",
                "type_mismatch",
                "unknown_path",
                "unsupported_expression",
            )
        },
    }
    aggregate["unresolved"] = sum(
        aggregate["statuses"][key]
        for key in ("type_mismatch", "unknown_path", "unsupported_expression", "ambiguous")
    )
    return aggregate


def build_baseline() -> dict[str, Any]:
    dataset = load_gold_dataset(DATASET)
    tag_commit = _git("rev-parse", f"{BASELINE_TAG}^{{commit}}")
    return {
        "schema": BASELINE_SCHEMA,
        "baseline_version": BASELINE_VERSION,
        "frozen_at": FROZEN_AT,
        "git": {
            "tag": BASELINE_TAG,
            "commit": tag_commit or BASELINE_COMMIT,
            "commit_at_freeze": tag_commit or BASELINE_COMMIT,
            "describe": _git("describe", "--tags", "--exact-match"),
            # Observed before the v0.12 branch was created; the baseline is not
            # regenerated with later working-tree state.
            "dirty_at_freeze": False,
        },
        "dataset": benchmark_dataset_snapshot(dataset),
        "adjudication": _adjudication_summary(),
        "prompts": {
            "full": FULL_PROMPT_VERSION,
            "compact": COMPACT_PROMPT_VERSION,
            "candidate_filter": "v0.11.1",
        },
        "models": MODELS,
        "d365": _corpus_aggregate(),
        "tools": _versions(),
        "limitations": [
            "The baseline is a snapshot of the v0.11.0 audit, not a runtime guarantee.",
            "Docentric AX runtime compatibility remains not_tested.",
            "AT-07 is partial: the adjudicator is a deterministic proxy, not a second human.",
        ],
    }


def validate_baseline(baseline: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(baseline, dict):
        return ["baseline must be a JSON object"]
    if baseline.get("schema") != BASELINE_SCHEMA:
        errors.append(f"baseline schema is {baseline.get('schema')!r}")
    if baseline.get("baseline_version") != BASELINE_VERSION:
        errors.append(f"baseline version is {baseline.get('baseline_version')!r}")
    git = baseline.get("git") or {}
    if git.get("tag") != BASELINE_TAG:
        errors.append("baseline git tag must be v0.11.0")
    if not isinstance(git.get("commit"), str) or len(str(git.get("commit"))) != 40:
        errors.append("baseline git commit must be a 40-character SHA")
    dataset = load_gold_dataset(DATASET)
    expected = benchmark_dataset_snapshot(dataset)
    if baseline.get("dataset") != expected:
        errors.append("baseline dataset identity does not match the committed dataset")
    adjudication = baseline.get("adjudication") or {}
    if adjudication.get("available") is not True:
        errors.append("baseline must reference the adjudication artifact")
    if adjudication.get("sha256") != _sha256(ADJUDICATION):
        errors.append("baseline adjudication hash does not match the artifact")
    if adjudication.get("second_human_annotator") is not False:
        errors.append("baseline must record that no second human annotator existed")
    if adjudication.get("at07_status") != "partial":
        errors.append("baseline AT-07 status must be partial")
    d365 = baseline.get("d365") or {}
    if d365.get("documents") != 11:
        errors.append("baseline D365 document count must be 11")
    if d365.get("bindings") != 246:
        errors.append("baseline D365 binding count must be 246")
    if d365.get("resolved_with_evidence") != 233:
        errors.append("baseline D365 resolved count must be 233")
    if d365.get("unresolved") != 13:
        errors.append("baseline D365 unresolved count must be 13")
    if d365.get("runtime_compatibility") != "not_tested":
        errors.append("baseline D365 runtime compatibility must be not_tested")
    models = baseline.get("models") or {}
    if models != MODELS:
        errors.append("baseline model IDs do not match the frozen v0.11 models")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        try:
            baseline = json.loads(args.output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"cannot read baseline {args.output}: {exc}", file=sys.stderr)
            return 1
        errors = validate_baseline(baseline)
        if args.json:
            print(
                json.dumps(
                    {"status": "passed" if not errors else "failed", "errors": errors}, indent=2
                )
            )
        elif errors:
            print(f"baseline is invalid ({len(errors)} problem(s)):", file=sys.stderr)
            for error in errors:
                print(f"  - {error}", file=sys.stderr)
        else:
            print(
                "baseline ok: v0.11.0 @ "
                f"{baseline['git']['commit'][:12]}, dataset "
                f"{baseline['dataset']['version']} "
                f"{baseline['dataset']['sha256'][:12]}, D365 "
                f"{baseline['d365']['documents']} docs / "
                f"{baseline['d365']['resolved_with_evidence']} resolved / "
                f"{baseline['d365']['unresolved']} unresolved"
            )
        return 0 if not errors else 1

    baseline = build_baseline()
    errors = validate_baseline(baseline)
    if errors:
        print("refusing to write an invalid baseline:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(baseline, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.output} at {datetime.now(tz=UTC).isoformat(timespec='seconds')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
