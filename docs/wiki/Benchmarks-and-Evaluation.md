# Benchmarks & Evaluation

> Measured, reproducible, and honest about what a number does and does not prove.

## Latency benchmark

```bash
make bench
# python benchmarks/run_benchmarks.py --runs 100
```

Measures parse, plan (mock), validate and compile latency over the three example fixtures, 100 runs each,
and writes `benchmarks/results.json`.

### Reference run (100 runs per fixture, mock provider)

| Stage | p50 (ms) | p95 (ms) | max (ms) | Budget (ms) | Within budget |
| --- | --- | --- | --- | --- | --- |
| parse | 1.96 | 3.01 | 5.73 | 2,000 | yes |
| plan (mock) | 44.03 | 64.88 | 102.27 | — | — |
| validate | 2.08 | 3.35 | 4.74 | — | — |
| compile | 72.92 | 95.08 | 110.87 | 5,000 | yes |

Per-example p95 (ms):

| Example | parse | plan | validate | compile |
| --- | --- | --- | --- | --- |
| quotation | 3.16 | 69.54 | 3.40 | 102.97 |
| invoice | 2.89 | 64.88 | 3.43 | 94.16 |
| purchase-order | 2.53 | 57.99 | 2.67 | 91.56 |

Percentiles use linear interpolation over all samples. `plan` measures the deterministic mock planner end
to end; a hosted provider adds network and inference time and must be measured separately.

> These numbers come from a shared 4 vCPU container and are indicative, not an SLO.

## AI evaluation

```bash
make eval
# python benchmarks/run_evaluation.py
```

The harness compares planner output against a hand-written ground truth for the three fixtures and computes:

| Metric | Mock baseline |
| --- | --- |
| Field selection precision | **0.932** |
| Field selection recall | **0.965** |
| Requirement coverage | **1.000** |
| Compilation success rate | **1.000** |
| Clarification rate | 0.000 |
| Correction rate | 0.000 |
| Verified compatibility rate | **0.000** |
| Cost per valid template | $0.000 |

### What the numbers mean

- **Precision 0.932** — almost every bound path is in the ground truth; the extras are legitimate fields the
  document does not strictly require (bank SWIFT, payment terms).
- **Recall 0.965** — the remaining misses are condition-only fields used in expressions rather than as
  scalar bindings.
- **Verified compatibility 0.000** — this is the honest value while the AX gate is blocked. It is not a
  quality signal; it is a status.
- **Cost 0.000** — the baseline is offline. Hosted providers report estimated cost from a pricing table.

## Reference-based evaluation (REF-05)

```bash
.venv/bin/python benchmarks/reference_evaluation.py --provider mock
```

Scores a generated plan against reference template patterns rather than only against a prompt:
Field→scalar, List→collection, If→condition, Image→image and Label→text. The committed synthetic set
has 8 cases and 41 expected concepts; no Docentric corpus content is used.

| Metric | Synthetic mock run |
| --- | --- |
| Precision | **0.891** |
| Recall | **1.000** |
| Coverage | **1.000** |
| Type/context correctness | **1.000** |
| Valid template rate (separate) | **1.000** |
| Cost | verified, $0.00 |

`valid_template_rate` is deliberately reported separately: a plan can be schema-valid and compile
while binding the wrong reference pattern. The report writes JSON, CSV and self-contained HTML with
sample size, provenance, error taxonomy and cost status. `--reference PATH --ddsp PATH` evaluates a
real DOCX/AXPP from the ignored corpus at runtime; those reports stay private. A non-mock provider
requires `--allow-paid`.

## Gold semantic benchmark (v0.10 PR-05)

```bash
.venv/bin/python benchmarks/gold_evaluation.py \
  --providers openai:gpt-6-sol,anthropic:claude-sonnet-5-5,gemini:gemini-3.6-flash \
  --repeats 3 --split all --max-spend 10 --warn-spend 5 --allow-unpriced
```

A versioned set of **32 synthetic cases** with concept-level gold labels:
flat fields, images, collections, nested lists, conditions, missing requirements, ambiguity,
multilingual briefs, long tables and forbidden scope. The split is **20 calibration / 12 holdout**,
fixed before the first live run; both splits contain every family. The dataset hash, split, model
versions, settings and sample sizes are written into every report.

The labels were authored by the implementer and checked by a deterministic rule pass
(`benchmarks/gold_dataset.py --check`). There was **no independent human double review**, so the
annotation criterion is honestly partial. See
[EVALUATION §2.7](../EVALUATION.md#27-gold-semantic-benchmark-v010-pr-05) and
[GOLD_LABELS](../GOLD_LABELS.md) for the rules and the adjudication record.

Semantic precision, recall, F1, requirement coverage, type/context correctness and block coverage
are reported separately from `valid_template_rate`. Calibration and holdout are shown separately, as
are per-provider, per-family and per-case results. Costs are `verified`, `estimated` or `unavailable`;
Gemini is unpriced and is reported as an estimate, never as $0.00. The runner warns at $5 and stops
before a call whose worst case could cross the $10 cap. Per-run records stay in the git-ignored
`benchmarks/gold_runs.jsonl`; only aggregates are committed. The report states explicitly that the
numbers are **observations, not significance**, and it does not declare a single winner.

<!-- GOLD-WIKI-RESULTS -->

## Why two separate metrics

Compilation success and verified compatibility measure different things. A document can compile perfectly
and still not execute in Docentric AX. Collapsing them into one percentage would be the single most
misleading number this project could publish, so they stay separate in the harness, the report and this
page.

## Reproducing

| Requirement | Detail |
| --- | --- |
| Python | 3.12 |
| Data | committed synthetic fixtures and the 32-case gold dataset |
| Provider | `mock` for the deterministic baseline; three hosted providers for the gold report |
| Command | `make bench && make eval`, then `benchmarks/gold_evaluation.py` (see above) |
| Outputs | `benchmarks/results.json`, `benchmarks/evaluation.json`, `benchmarks/reference_report.{json,csv,html}`, `benchmarks/gold_report.{json,csv,html}` |

The three-case hosted-provider comparison is not part of the committed baseline; the committed
hosted run is the gold benchmark. Model versions and network conditions still change, so every
report records the model id, date, dataset hash and pricing version.
