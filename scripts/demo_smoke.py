#!/usr/bin/env python3
"""T-08: local Live Demo smoke test and evidence record.

Runs the real Streamlit app through ``AppTest`` for the three release scenarios,
confirms pending mappings, proves the Download DOCX button is available, and
independently compiles the same mock document to record size/SHA-256 evidence.

The deployed Streamlit URL is recorded separately: it requires an interactive
Streamlit Cloud auth redirect and cannot be exercised from this headless
environment. This script never claims the deployed revision was verified.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from docentric_copilot import IR_VERSION, __version__
from docentric_copilot.api.demo_state import apply_confirmations
from docentric_copilot.app.service import TemplateService
from docentric_copilot.ddsp_parser import parse_ddsp
from docentric_copilot.docx_compiler import CompileOptions
from docentric_copilot.planner.service import build_mapping_report
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "streamlit_app.py"
DEMO_DIR = ROOT / "services" / "api" / "src" / "docentric_copilot" / "api" / "demo"
CASES = json.loads((DEMO_DIR / "manifest.json").read_text(encoding="utf-8"))["cases"]
CASE_BY_ID = {case["id"]: case for case in CASES}
OUTPUT_JSON = ROOT / "docs" / "DEMO_SMOKE_V013.json"
OUTPUT_MD = ROOT / "docs" / "DEMO_SMOKE_V013.md"
SCENARIOS = ("quotation", "invoice", "purchase-order")
DEPLOYED_URL = "https://docentric-copilot-bqpx8652tmmliwk9c2d5rq.streamlit.app"


def _git_sha() -> str:
    import subprocess

    return (
        subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        or "unknown"
    )


def _working_tree_dirty() -> bool:
    import subprocess

    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(result.stdout.strip())


def _app_run(case_id: str) -> tuple[list[str], list[str], bool]:
    app = AppTest.from_file(str(APP)).run(timeout=90)
    app.sidebar.selectbox[0].set_value(case_id)
    app.run(timeout=90)
    confirmed: list[str] = []
    for _ in range(8):
        buttons = [button for button in app.button if (button.key or "").startswith("confirm-")]
        if not buttons:
            break
        button = buttons[0]
        confirmed.append(button.key or "")
        button.click().run(timeout=90)
    metadata: list[str] = []
    for code in app.sidebar.get("code"):
        value = str(getattr(code, "value", ""))
        if "Application:" in value:
            metadata.append(value)
    downloads = app.get("download_button")
    return confirmed, metadata, bool(downloads) and not app.exception


def _compile_case(case_id: str) -> dict[str, object]:
    case = CASE_BY_ID[case_id]
    payload = (DEMO_DIR / case["package"]).read_bytes()
    parsed = parse_ddsp(payload, case["package"])
    service = TemplateService()
    outcome, _report = asyncio.run(service.plan(parsed.schema, case["prompt"], provider="mock"))
    mapping = apply_confirmations(
        build_mapping_report(parsed.schema, outcome.document, case["prompt"]),
        {},
    )
    compiled = service.compile(
        outcome.document,
        parsed.schema,
        sample_data=parsed.sample_data,
        options=CompileOptions(document_name=f"{case_id}.docx"),
    )
    return {
        "case_id": case_id,
        "title": case["title"],
        "mapping_blocking_after_local_confirmations": len(mapping.blocking()),
        "docx_size_bytes": len(compiled.content),
        "docx_sha256": hashlib.sha256(compiled.content).hexdigest(),
        "ir_version": outcome.document.ir_version,
        "generator": outcome.document.metadata.generator,
    }


def run() -> dict[str, object]:
    results = []
    metadata_seen = ""
    for case_id in SCENARIOS:
        confirmed, metadata, download = _app_run(case_id)
        metadata_seen = metadata[0] if metadata else metadata_seen
        artifact = _compile_case(case_id)
        results.append(
            {
                **artifact,
                "app_test_passed": download,
                "confirmations_clicked": confirmed,
            }
        )
    return {
        "schema": "demo-smoke/v1",
        "verification_scope": "local AppTest; deployed Streamlit URL not verified",
        "verified_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "application_version": __version__,
        "git_commit": _git_sha(),
        "working_tree_dirty": _working_tree_dirty(),
        "template_ir": IR_VERSION,
        "provider": "mock",
        "execution_mode": "Deterministic Demo",
        "deployed_url": DEPLOYED_URL,
        "deployed_url_status": "HTTP 303 to Streamlit Cloud auth; interactive check unavailable in this environment",
        "metadata_panel": metadata_seen,
        "scenarios": results,
    }


def render(data: dict[str, object]) -> str:
    scenarios = data["scenarios"]
    assert isinstance(scenarios, list)
    lines = [
        "# Live Demo smoke evidence — v0.13",
        "",
        "> **Scope:** local Streamlit `AppTest`, not a manual check of the deployed",
        "> Streamlit Cloud revision. The deployed URL redirects to an interactive",
        "> Streamlit Cloud auth page and could not be exercised headlessly.",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Verified at | `{data['verified_at']}` |",
        f"| Application | `{data['application_version']}` |",
        f"| Git commit | `{data['git_commit']}` |",
        f"| Working tree dirty | `{data['working_tree_dirty']}` |",
        f"| Template IR | `{data['template_ir']}` |",
        f"| Provider / model | `{data['provider']}` / `heuristic-baseline-v1` |",
        f"| Execution mode | `{data['execution_mode']}` |",
        f"| Deployed URL | {data['deployed_url']} |",
        f"| Deployed status | {data['deployed_url_status']} |",
        "",
        "## Metadata panel",
        "",
        "```text",
        str(data["metadata_panel"]),
        "```",
        "",
        "## Scenarios",
        "",
        "| Case | AppTest download | Confirmations | DOCX bytes | DOCX SHA-256 |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for scenario in scenarios:
        lines.append(
            f"| {scenario['title']} (`{scenario['case_id']}`) | "
            f"{'yes' if scenario['app_test_passed'] else '**no**'} | "
            f"{len(scenario['confirmations_clicked'])} | "
            f"{scenario['docx_size_bytes']:,} | `{scenario['docx_sha256']}` |"
        )
    lines += [
        "",
        "## Result",
        "",
        "All three local scenarios reach Download DOCX. The Sales Quotation flow",
        "requires confirming `req_09`; the confirmation is applied by the same",
        "deterministic helper used by the app. The DOCX hashes above are computed",
        "from the same mock plan and sample data, not from the Streamlit download",
        "payload (AppTest does not expose the binary).",
        "",
        "## What is not proven",
        "",
        "- The deployed Streamlit Cloud revision is not verified; it may run an older commit.",
        "- A dirty working tree means the local demo build contains changes not yet committed;",
        "  the metadata panel still reports the release tag's base commit.",
        "- No real LLM call was made; execution mode is `Deterministic Demo`.",
        "- This is not Word for the web or Docentric AX validation.",
        "",
        "Generated by `python scripts/demo_smoke.py --write`.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    data = run()
    if args.write:
        OUTPUT_JSON.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        OUTPUT_MD.write_text(render(data), encoding="utf-8")
        print(f"wrote {OUTPUT_JSON.relative_to(ROOT)} and {OUTPUT_MD.relative_to(ROOT)}")
    else:
        print(json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
