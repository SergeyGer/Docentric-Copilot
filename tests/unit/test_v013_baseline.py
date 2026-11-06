"""Freeze checks for the v0.12.0 baseline used by the v0.13 work."""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.gold_dataset import load_gold_dataset

ROOT = Path(__file__).resolve().parent.parent.parent
BASELINE = ROOT / "benchmarks" / "baseline_v012.json"


def _baseline() -> dict:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def test_v012_baseline_is_present_and_valid() -> None:
    baseline = _baseline()
    assert baseline["schema"] == "baseline-freeze/v1"
    assert baseline["baseline_version"] == "0.12.0"
    assert baseline["target_version"] == "0.13.0"
    assert baseline["git"]["tag"] == "v0.12.0"
    assert baseline["git"]["commit"] == "a4d3eb947ccb6b68f2a146987037f69668acb526"
    assert baseline["git"]["describe"] == "v0.12.0"


def test_baseline_pins_the_gold_dataset_and_v012_evidence() -> None:
    baseline = _baseline()
    dataset = load_gold_dataset()
    assert baseline["dataset"]["version"] == dataset.version == "2.0.0"
    assert baseline["dataset"]["sha256"] == dataset.file_sha256
    assert baseline["dataset"]["canonical_sha256"] == dataset.canonical_sha256
    assert baseline["dataset"]["case_count"] == len(dataset.cases) == 32
    assert baseline["manifests"]["benchmark_sha256"] == (
        "b830ed6313955a87576c5bfc110730a35294364c0fc8ae61d2942b0c534ceba3"
    )
    assert baseline["manifests"]["gold_audit_sha256"] == (
        "6fd848e06431981c1d23933e5e769978fe7f2e3ebbe4ce12559ba2b4cfd54bf6"
    )
    assert baseline["benchmark"]["runs"] == 288
    assert baseline["benchmark"]["completed"] == 284
    assert baseline["benchmark"]["technical_failures"] == 4
    assert baseline["benchmark"]["semantic_passes"] == 277
    assert baseline["d365"]["documents"] == 11
    assert baseline["d365"]["resolved_with_evidence"] == 233
    assert baseline["d365"]["unresolved"] == 13
    assert baseline["versions"]["template_ir"] == "1.0"
    assert baseline["d365"]["runtime_compatibility"] == "not_tested"


def test_baseline_contains_no_private_paths_or_secrets() -> None:
    text = BASELINE.read_text(encoding="utf-8")
    for marker in (
        ".tools/",
        "reference-corpus",
        "sk-proj",
        "sk-ant-",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
    ):
        assert marker not in text
