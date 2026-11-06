"""Single source of the version identifiers pinned by benchmark manifests.

The benchmark tooling is not part of the installed distribution, so it keeps its
own evaluator/runner versions. Prompt and planner versions are imported from the
product code instead of copied, so a manifest cannot silently claim a different
prompt than the one the planner actually sends.
"""

from __future__ import annotations

from docentric_copilot.planner import COMPACT_V2_GENERATOR, PLANNER_VERSION, PROMPT_VERSION

#: Version of the evaluator/scoring rules in ``benchmarks/gold_evaluation.py``.
EVALUATOR_VERSION = "1.0.0"

#: Version of the benchmark runner entry point and its CLI contract.
BENCHMARK_RUNNER_VERSION = "1.0.0"

#: Version of the deterministic gold-label adjudicator.
ADJUDICATOR_VERSION = "1.0.0"

#: Version of the audit trail this repository writes for the gold dataset.
GOLD_AUDIT_VERSION = "1.0.0"

#: Version of the gold-label manifest contract.
GOLD_MANIFEST_VERSION = "1.0.0"

#: Prompt used by the full IR path and the ultra-compact Gemini path.
FULL_PROMPT_VERSION = PROMPT_VERSION
COMPACT_PROMPT_VERSION = COMPACT_V2_GENERATOR

__all__ = [
    "ADJUDICATOR_VERSION",
    "BENCHMARK_RUNNER_VERSION",
    "COMPACT_PROMPT_VERSION",
    "EVALUATOR_VERSION",
    "FULL_PROMPT_VERSION",
    "GOLD_AUDIT_VERSION",
    "GOLD_MANIFEST_VERSION",
    "PLANNER_VERSION",
]
