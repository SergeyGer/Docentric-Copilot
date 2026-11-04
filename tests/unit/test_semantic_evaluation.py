"""End-to-end test of the semantic report writer with the offline baseline."""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.semantic_evaluation import main


def test_mock_report_is_written_and_self_describing(tmp_path: Path, capsys) -> None:
    json_path = tmp_path / "report.json"
    csv_path = tmp_path / "report.csv"
    html_path = tmp_path / "report.html"
    runs_path = tmp_path / "runs.jsonl"
    exit_code = main(
        [
            "--providers",
            "mock:mock-planner-v1",
            "--repeats",
            "1",
            "--limit",
            "2",
            "--max-spend",
            "1",
            "--output-json",
            str(json_path),
            "--output-csv",
            str(csv_path),
            "--output-html",
            str(html_path),
            "--runs-file",
            str(runs_path),
        ]
    )
    assert exit_code == 0
    report = json.loads(json_path.read_text(encoding="utf-8"))
    assert report["schema"] == "semantic-report/v1"
    assert report["dataset"]["case_count"] == 2
    assert len(report["dataset"]["canonical_sha256"]) == 64
    assert report["sample_size"]["completed_runs"] == 2
    assert report["providers"][0]["metrics"]["runs"] == 2
    assert report["providers"][0]["metrics"]["valid_template_rate"] == 1.0
    assert report["cost"]["status"] == "verified"
    assert report["notes"]
    assert report["leaders"]
    assert "statistical significance" in report["observations_not_significance"]
    runs = [json.loads(line) for line in runs_path.read_text(encoding="utf-8").splitlines()]
    assert len(runs) == 2
    assert "api_key" not in runs_path.read_text(encoding="utf-8").casefold()
    assert csv_path.read_text(encoding="utf-8").startswith("scope,provider,model")
    page = html_path.read_text(encoding="utf-8")
    assert "Observations, not significance" in page
    assert "no single winner" in page.casefold()
    captured = capsys.readouterr()
    assert "semantic evaluation" in captured.out
