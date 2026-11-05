"""The corpus assessment script reports counts only and stays deterministic."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.reference_fixtures import ElementSpec, build_axpp, build_embedded_docx

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "assess_d365_corpus.py"


def test_assessment_script_reports_counts_without_file_names(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    standalone = build_embedded_docx((ElementSpec(1, "Field", "MainData", "@Number"),))
    (corpus / "Standalone.docx").write_bytes(standalone)
    package = build_axpp(build_embedded_docx((ElementSpec(2, "Field", "MainData", "@Number"),)))
    (corpus / "Package.axpp").write_bytes(package)
    # The same package under a second file name must be analysed only once.
    (corpus / "Duplicate.axpp").write_bytes(package)
    output = tmp_path / "assessment.json"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--corpus",
            str(corpus),
            "--json",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "D365 corpus documents: 2" in result.stdout
    assert output.exists()
    serialized = output.read_text(encoding="utf-8")
    payload = json.loads(serialized)
    assert payload["assessment_version"] == "1.0"
    assert payload["documents"] == 2
    assert payload["unique_document_payloads"] == 2
    assert payload["schema_source"] == {"projectdata": 2}
    assert payload["availability"] == {
        "with_schema": 2,
        "without_schema": 0,
        "analysis_errors": 0,
    }
    assert payload["bindings"]["total"] == 2
    assert payload["bindings"]["statuses"]["resolved"] == 2
    assert payload["bindings"]["resolved_without_evidence"] == 0
    assert payload["runtime_compatibility"] == "not_tested"
    assert payload["failures"] == []
    assert len(payload["per_document"]) == 2
    for row in payload["per_document"]:
        assert len(row["sha256_12"]) == 12
        assert row["runtime_compatibility"] == "not_tested"
        assert "label" not in row
        assert "path" not in row
    assert "Standalone.docx" not in serialized
    assert "Package.axpp" not in serialized
    assert str(corpus) not in serialized
