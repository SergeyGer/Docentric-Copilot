#!/usr/bin/env python3
"""T-06: classify Gemini structured_output failures without publishing payloads."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_V013 = ROOT / "benchmarks" / "gold_manifest_v013.json"
MANIFEST_V012 = ROOT / "benchmarks" / "gold_manifest_v012.json"
RUNS_V013 = ROOT / "benchmarks" / "gold_runs_v013.jsonl"
OUTPUT_JSON = ROOT / "benchmarks" / "gemini_failures_v013.json"
OUTPUT_MD = ROOT / "docs" / "GEMINI_FAILURES_V013.md"


def _classify(message: str) -> str:
    if "unknown key(s) at $.f, $.fh, $.h" in message:
        return "root_level_section_keys"
    if "unknown key(s) at $.v" in message:
        return "unknown_root_key_v"
    if "expected a block array" in message:
        return "malformed_nested_cell_block"
    if "expected a string" in message:
        return "wrong_nested_cell_scalar"
    return "other_contract_violation"


def _case_families(path: Path) -> dict[str, str]:
    cases = json.loads((ROOT / "benchmarks" / "gold_cases.json").read_text(encoding="utf-8"))
    return {case["id"]: case["family"] for case in cases["cases"]}


def _failures(manifest_path: Path, runs_path: Path | None) -> list[dict]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    families = _case_families(manifest_path)
    raw_by_run: dict[str, dict] = {}
    if runs_path and runs_path.exists():
        for line in runs_path.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            raw_by_run[item["run_id"]] = item
    result = []
    for run in manifest["runs"]:
        if not run.get("technical_failure"):
            continue
        raw = raw_by_run.get(run["run_id"], {})
        error = raw.get("error") or {}
        message = str(error.get("message") or run.get("technical_reason") or "")
        result.append(
            {
                "run_id": run["run_id"],
                "case_id": run["case_id"],
                "family": families.get(run["case_id"], "unknown"),
                "category": raw.get("category"),
                "provider": run["provider"],
                "repeat_index": run.get("repeat_index"),
                "model_id": run.get("model_id"),
                "compact_version": run.get("compact_version"),
                "error_code": error.get("code") or run.get("technical_reason"),
                "error_class": _classify(message),
                "error_message": message[:300],
                "repair_attempts": run.get("retries"),
                "gateway_attempts": run.get("gateway_attempts"),
                "latency_ms": run.get("latency_ms"),
                "cost_status": run.get("cost_status"),
            }
        )
    return result


def _summary(items: list[dict], key: str) -> dict[str, int]:
    return dict(sorted(Counter(item[key] for item in items).items()))


def build() -> dict:
    current = _failures(MANIFEST_V013, RUNS_V013)
    previous = _failures(MANIFEST_V012, None)
    v012_manifest = json.loads(MANIFEST_V012.read_text(encoding="utf-8"))
    v013_manifest = json.loads(MANIFEST_V013.read_text(encoding="utf-8"))
    return {
        "schema": "gemini-failures/v1",
        "source_manifest_v013": v013_manifest["manifest_sha256"],
        "source_manifest_v012": v012_manifest["manifest_sha256"],
        "summary": {
            "v013_total_runs": v013_manifest["counters"]["planned_runs"],
            "v013_completed": v013_manifest["counters"]["completed_runs"],
            "v013_technical": len(current),
            "v013_semantic_passes": v013_manifest["counters"]["semantic_pass_runs"],
            "v012_technical": len(previous),
            "delta": len(current) - len(previous),
            "all_gemini": all(item["provider"] == "gemini" for item in current),
            "all_structured_output": all(
                item["error_code"] == "structured_output" for item in current
            ),
            "all_compact_v2": all(item["compact_version"] == "v2" for item in current),
        },
        "by_family": _summary(current, "family"),
        "by_case": _summary(current, "case_id"),
        "by_error_class": _summary(current, "error_class"),
        "v012_by_family": _summary(previous, "family"),
        "v012_by_case": _summary(previous, "case_id"),
        "failures": current,
        "root_cause_hypotheses": {
            "root_level_section_keys": "The model places section header/footer keys (f/fh/h) at the document root instead of inside a section object.",
            "unknown_root_key_v": "The model emits an undocumented root key `v`; the expander correctly rejects it rather than guessing.",
            "malformed_nested_cell_block": "Nested table cell content is not a block array; the model flattens or wraps it incorrectly.",
            "wrong_nested_cell_scalar": "A nested cell position receives a non-string value where a label/string is required.",
        },
        "actions": [
            "Do not relax the compact-v2 unknown-key or block-array validation.",
            "Add contract tests for these exact malformed shapes.",
            "If prompt/schema changes are made, rerun the full 288-run benchmark and update the manifest.",
            "Keep provider/technical failures separate from semantic passes.",
        ],
    }


def render(data: dict) -> str:
    summary = data["summary"]
    lines = [
        "# Gemini structured_output failures — v0.13",
        "",
        "> Diagnostic classification from the committed manifest and sanitized run records.",
        "> No prompts, raw provider output or credentials are published.",
        "",
        "## Counts",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| v0.13 logical runs | {summary['v013_total_runs']} |",
        f"| Completed | {summary['v013_completed']} |",
        f"| Technical failures | {summary['v013_technical']} |",
        f"| Semantic passes | {summary['v013_semantic_passes']} |",
        f"| v0.12 technical failures | {summary['v012_technical']} |",
        f"| Delta | +{summary['delta']} |",
        "",
        "All failures are Gemini, `structured_output` and compact v2; none is a semantic pass.",
        "",
        "## By family (v0.13)",
        "",
        "| Family | Failures | v0.12 |",
        "| --- | ---: | ---: |",
    ]
    for family, count in data["by_family"].items():
        lines.append(f"| `{family}` | {count} | {data['v012_by_family'].get(family, 0)} |")
    lines += [
        "",
        "## By error class",
        "",
        "| Class | Count |",
        "| --- | ---: |",
        *[f"| `{key}` | {value} |" for key, value in data["by_error_class"].items()],
        "",
        "## Root-cause hypotheses",
        "",
        *[f"- **{key}** — {value}" for key, value in data["root_cause_hypotheses"].items()],
        "",
        "## Actions",
        "",
        *[f"- {item}" for item in data["actions"]],
        "",
        "## Limitations",
        "",
        "- The error message is the only diagnostic retained; raw model output is not committed.",
        "- The increase is concentrated in nested-list cases and may combine prompt, schema and provider variance; no single cause is claimed without a controlled rerun.",
        "- Fixing the contract without rerunning would invalidate the benchmark comparison, so this is a documented P1 baseline.",
        "",
        "Generated by `python scripts/gemini_failures.py --write`.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    data = build()
    if args.write:
        OUTPUT_JSON.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        OUTPUT_MD.write_text(render(data), encoding="utf-8")
        print(f"wrote {OUTPUT_JSON.relative_to(ROOT)} and {OUTPUT_MD.relative_to(ROOT)}")
    else:
        print(json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
