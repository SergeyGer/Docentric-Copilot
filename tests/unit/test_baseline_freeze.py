"""Tests for the frozen v0.11.0 baseline used by the v0.12 release."""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.gold_dataset import load_gold_dataset
from scripts.freeze_baseline import (
    BASELINE_COMMIT,
    BASELINE_TAG,
    DEFAULT_BASELINE,
    main,
    validate_baseline,
)

ROOT = Path(__file__).resolve().parent.parent.parent


def _baseline() -> dict:
    return json.loads(DEFAULT_BASELINE.read_text(encoding="utf-8"))


def test_committed_baseline_is_valid() -> None:
    baseline = _baseline()
    assert validate_baseline(baseline) == []
    assert baseline["git"]["tag"] == BASELINE_TAG
    assert baseline["git"]["commit"] == BASELINE_COMMIT
    assert baseline["git"]["dirty_at_freeze"] is False


def test_baseline_pins_dataset_identity() -> None:
    baseline = _baseline()
    dataset = load_gold_dataset()
    assert baseline["dataset"]["version"] == "2.0.0"
    assert baseline["dataset"]["case_count"] == 32
    assert baseline["dataset"]["sha256"] == dataset.file_sha256
    assert baseline["dataset"]["canonical_sha256"] == dataset.canonical_sha256


def test_baseline_records_the_historical_d365_aggregate() -> None:
    d365 = _baseline()["d365"]
    assert d365["documents"] == 11
    assert d365["bindings"] == 246
    assert d365["resolved_with_evidence"] == 233
    assert d365["unresolved"] == 13
    assert d365["statuses"]["type_mismatch"] == 1
    assert d365["statuses"]["unknown_path"] == 4
    assert d365["statuses"]["unsupported_expression"] == 8
    assert d365["runtime_compatibility"] == "not_tested"


def test_baseline_does_not_leak_private_paths_or_secrets() -> None:
    text = DEFAULT_BASELINE.read_text(encoding="utf-8")
    for marker in (
        "reference-corpus",
        ".tools/",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "sk-proj",
        "sk-ant-",
    ):
        assert marker not in text


def test_baseline_check_cli_passes(capsys) -> None:
    assert main(["--check"]) == 0
    assert "baseline ok" in capsys.readouterr().out


def test_baseline_check_rejects_tampering(tmp_path, capsys) -> None:
    baseline = _baseline()
    baseline["d365"]["documents"] = 10
    tampered = tmp_path / "baseline.json"
    tampered.write_text(json.dumps(baseline), encoding="utf-8")
    assert main(["--check", "--output", str(tampered)]) == 1
    assert "document count" in capsys.readouterr().err
