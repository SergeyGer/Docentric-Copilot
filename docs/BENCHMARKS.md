# Benchmarks

| Field | Value |
| --- | --- |
| Runner | [benchmarks/run_benchmarks.py](../benchmarks/run_benchmarks.py) |
| Output | `benchmarks/results.json` (default) |
| Default runs | 100 per example per stage |
| Provider | `mock` by default; `--provider`/`--model` for a hosted provider |
| Fixtures | The three synthetic packages under `examples/` |
| Related | [EVALUATION](EVALUATION.md), [TEST_PLAN](TEST_PLAN.md), [SRS NFR-07](SRS.md#nfr-07--latency-and-throughput) |

Latency numbers are **environment-specific**. This document therefore states the methodology, records
one reproducible 100-run result set with its environment, and keeps a separate template for
hosted-provider measurements.

## 1. What the benchmark measures

For each example package (quotation, invoice, purchase-order), the runner executes the deterministic
pipeline stages and records wall-clock latency per iteration:

| Stage | Measured work |
| --- | --- |
| `parse` | `parse_ddsp()` on the package bytes (ZIP read, XML/XSD mapping, sample extraction) |
| `plan` | `TemplatePlanner.plan()` with the selected provider. With `mock` this is prompt assembly + the deterministic heuristic + sanitisation + mapping report; it is **not** an LLM latency measurement |
| `validate` | `ValidationEngine.validate()` with sample data (V1–V4; V5 is a constant check) |
| `compile` | `GenericDocxCompiler.compile()` including ZIP normalisation and package inspection |

Not measured: HTTP overhead, JSON serialisation of API responses, artifact storage, preview rendering,
SQLite writes, concurrent load, cold-start import time. Those are outside the runner's scope.

## 2. How to run

```bash
make bench
# equivalent to:
python benchmarks/run_benchmarks.py --runs 100
```

Options (from the runner's argparse):

| Option | Default | Meaning |
| --- | --- | --- |
| `--runs N` | `100` | Iterations per example per stage |
| `--provider` | `mock` | Provider passed to the planner |
| `--model` | `None` | Model identifier for a hosted provider |
| `--output PATH` | `benchmarks/results.json` | Where to write JSON |
| `--json` | off | Print the full JSON payload to stdout instead of the table |

Hosted-provider example (requires credentials; results are not comparable with the mock):

```bash
python benchmarks/run_benchmarks.py --runs 20 --provider openai --model gpt-4o-mini
```

The runner writes JSON even when printing a table. The JSON payload contains:

```text
generated_by, python, platform, runs_per_example, provider, model,
aggregate: { parse, plan, validate, compile } -> Stats,
per_example: { quotation, invoice, purchase-order } -> { stage -> Stats }
```

`Stats` = `{name, runs, min_ms, mean_ms, p50_ms, p95_ms, max_ms, budget_ms}`. Budgets are displayed for
`parse` (2000 ms) and `compile` (5000 ms); the `within_budget` property exists on `Stats` but the
runner prints the budget column rather than failing on it. Other stages have no budget.

## 3. Methodology

1. **Fixtures are fixed.** The three synthetic packages and their prompts are read from `examples/`.
   They are regenerated deterministically by `scripts/build_examples.py`.
2. **Warm-up is implicit.** The runner parses and plans once per example before the timed loop. There
   is no explicit warm-up iterations beyond that, and no process isolation between stages.
3. **Timing** uses `time.perf_counter()` around each call. Each iteration re-parses the package and
   re-runs the planner; validation and compilation reuse the document produced before the loop.
4. **Percentiles** are computed by linear interpolation over the sorted samples:
   `position = (n - 1) × fraction`, interpolating between the two nearest samples. `p50` and `p95` are
   therefore exact for the sample, not histogram estimates.
5. **Per-example statistics** (`per_example.*`) are computed over all runs for that stage and example.
6. **Aggregate statistics** are computed over the three **per-example p95 values** (one per example),
   not over all `3 × runs` samples. This described the first version of the runner; it now
   aggregates over every sample (`all_samples`). The historical note is kept because the numbers in
   older commits were produced with the old method. The old method made the aggregate a
   summary of worst-case behaviour per fixture, with only three data points. Do not interpret the
   aggregate `runs` field (`3`) as the iteration count; read `runs_per_example` for that.
7. **Throughput is not computed** by the runner. Derive it manually only if needed:
   `1000 / mean_ms` calls per second per stage, single-threaded, excluding overheads listed in §1.

### 3.1 Reproducibility checklist

Record with any published number:

- command line and `runs_per_example`;
- `python` and `platform` from the JSON;
- provider and model;
- machine class (CPU, memory), because the runner does not capture it;
- commit hash;
- whether the machine was otherwise idle.

## 4. Results

### 4.1 Reference run (100 runs)

Produced with `make bench` (`python benchmarks/run_benchmarks.py --runs 100`), provider `mock`,
Python 3.12.3, `Linux-6.8.0-147-generic-x86_64-with-glibc2.39`, on a shared 4 vCPU-class container.
Aggregates are computed over **all** `3 × runs` samples per stage (the runner was fixed after the
first draft of this document, which aggregated the three per-example p95 values).

| Stage | p50 (ms) | p95 (ms) | max (ms) | Budget (ms) | Within budget |
| --- | --- | --- | --- | --- | --- |
| parse | 1.96 | 3.01 | 5.73 | 2000 | yes |
| plan (mock) | 44.03 | 64.88 | 102.27 | — | — |
| validate | 2.08 | 3.35 | 4.74 | — | — |
| compile | 72.92 | 95.08 | 110.87 | 5000 | yes |

Per-example breakdown (p95 values, from `per_example`):

| Example | parse p95 | plan p95 | validate p95 | compile p95 |
| --- | --- | --- | --- | --- |
| quotation | 3.16 | 69.54 | 3.40 | 102.97 |
| invoice | 2.89 | 64.88 | 3.43 | 94.16 |
| purchase-order | 2.53 | 57.99 | 2.67 | 91.56 |

Percentiles use linear interpolation over the sorted samples. `plan` measures the deterministic mock
planner end to end (prompt assembly, gateway, IR validation, repair pass); a hosted provider adds
network and model latency and must be measured separately.

Hosted-provider plan latency: not measured in this repository. The table below is the template to
fill when a key is available; do not infer numbers from the mock baseline.

| Provider / model | Runs | p50 (ms) | p95 (ms) | Error rate | Commit |
| --- | --- | --- | --- | --- | --- |
| — | — | — | — | — | — |

### 4.2 Reproducing and reading the committed run

`benchmarks/results.json` is the source of the §4.1 table (`runs_per_example = 100`, provider `mock`).
It is regenerated with `make bench`; re-running on another machine will change the milliseconds while
leaving the methodology unchanged. Treat a regenerated file as a *new* measurement: record its
environment and commit, and do not splice old and new values into one table.

Reading the numbers:

- parse and validation are single-digit milliseconds on this fixture set;
- compilation is tens of milliseconds, dominated by `python-docx` generation and ZIP normalisation;
- the mock planner costs tens of milliseconds because it assembles a prompt, derives roles, builds the
  document and produces the mapping report — not because a model is called;
- none of these values say anything about hosted LLM latency, which is measured separately with
  `--provider`/`--model` and includes network and provider variance.

## 5. Interpretation rules

- **Never compare across machines** without stating the environment; absolute milliseconds are not a
  product claim.
- **`plan (mock)` is a baseline, not an AI metric.** For AI latency, use the hosted-provider table with
  the model identifier and error rate.
- **Budgets are guard rails**, not service-level objectives. A budget breach is worth investigating;
  passing it is not evidence of good performance.
- **A single run is an anecdote.** Publish p50/p95 with the number of runs and the commit.
- **Do not infer correctness from speed.** A fast compiler that emits invalid packages fails the
  validator and the golden tests, not the benchmark.

## 6. Known limitations

1. Aggregate p50/p95 are computed over per-example p95 values, not over all samples (§3.6).
2. No warm-up phase and no process isolation; JIT/import caching and GC can affect the first runs.
3. Only three small synthetic fixtures; large schemas, deep repeats and image-heavy documents are not
   represented.
4. No concurrency or throughput test; the API's threadpool and SQLite locking are not exercised.
5. Memory usage is not measured.
6. The runner's sys.path manipulation assumes the editable install is present; a clean-checkout run
   must install dependencies first.
7. Hosted-provider measurements include network variance and provider throttling; they are not
   comparable between runs without the model version and time window.
8. `budget_ms` values (2000/5000) are hard-coded in the runner, not product requirements.

## 7. Reporting template

When adding results to a PR or release note, use:

```text
command:      python benchmarks/run_benchmarks.py --runs 100 [--provider ... --model ...]
commit:       <sha>
environment:  <CPU / RAM / OS / Python>
provider:     <mock | provider/model>
results:      parse p95=<ms>, plan p95=<ms>, validate p95=<ms>, compile p95=<ms>
budgets:      parse 2000 ms (pass/fail), compile 5000 ms (pass/fail)
caveats:      <any of §6 that apply>
artifact:     benchmarks/results.json (or path)
```

## 8. Gold semantic benchmark (v0.10 PR-05)

The performance benchmark above (100 runs per fixture) measures latency. The gold benchmark measures
**semantic correctness** on a versioned set of business requests and reports cost separately.

| Item | Value |
| --- | --- |
| Dataset | [benchmarks/gold_cases.json](../benchmarks/gold_cases.json) — 32 cases, version `1.0.0`, `gold-cases/v1` |
| Guide | [GOLD_LABELS.md](GOLD_LABELS.md) |
| Runner | [benchmarks/gold_evaluation.py](../benchmarks/gold_evaluation.py) |
| Reports | [gold_report.json](../benchmarks/gold_report.json), `.csv`, `.html` |
| Raw per-run file | `benchmarks/gold_runs.jsonl` (git-ignored) |
| Split | 20 calibration / 12 holdout, fixed before the first live run |
| Providers | OpenAI `gpt-6-sol`, Anthropic `claude-sonnet-5-5`, Gemini `gemini-3.6-flash` |
| Settings | Gemini compact v2 / repairs 2; other providers full IR / repairs 1; temperature 0 |
| Budget | `--max-spend 10`, `--warn-spend 5`; unknown cost is never `$0.00` |

Command:

```bash
.venv/bin/python benchmarks/gold_evaluation.py \
  --providers openai:gpt-6-sol,anthropic:claude-sonnet-5-5,gemini:gemini-3.6-flash \
  --repeats 3 --split all --max-spend 10 --warn-spend 5 --allow-unpriced
```

The report is not a latency load test: each observation is one provider call (plus allowed repairs)
at temperature 0. It reports p50/p95 for context, not as an SLO. Compilation success is kept
separate from semantic pass; a schema-valid template can still bind the wrong concept.

The labels are single-annotator and validated by a deterministic rule pass; see
[GOLD_LABELS](GOLD_LABELS.md). There is no independent human double review, so AT-07 is partial.
Docentric AX runtime compatibility is `not_tested` and is not measured here.

### Committed run (2026-11-05)

288/288 planned runs completed. Dataset `1.0.0`, canonical SHA-256
`c2b1d89c70f96f14884de54792784d0dbd3ffaa71d0700d5f73c5c24e93ece30`.

| Provider | Model | Runs | Precision | Recall | F1 | Coverage | Type/context | Blocks | Semantic pass | Valid template | p50 / p95 | Spend | Cost/correct |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| OpenAI | `gpt-6-sol` | 96 | **0.226** | 1.000 | **0.368** | 1.000 | 0.995 | 0.851 | 55.2% | 100.0% | 15.5 / 20.0 s | **$2.9754 verified** | **$0.0561 verified** |
| Anthropic | `claude-sonnet-5-5` | 96 | 0.220 | 0.996 | 0.361 | 0.996 | **0.998** | **0.943** | **69.8%** | 100.0% | 10.7 / 20.6 s | $3.9096 verified | $0.0584 verified |
| Gemini | `gemini-3.6-flash` | 96 attempted / 93 planned | 0.184 | 1.000 | 0.311 | 1.000 | 0.998 | 0.911 | 64.6% | 96.9% | **4.1 / 10.2 s** | **$0.2910 estimated** | N/A (3 unknown runs) |

Holdout (36 runs per provider) semantic pass: OpenAI 61.1%, Anthropic 66.7%, Gemini 66.7%.
Calibration (60 runs per provider): 51.7%, 71.7%, 63.3%. Precision is lower on holdout for all
three. These are observations from 12 holdout cases, not significance.

Spend: **$6.8849 verified + $0.2910 estimated = $7.1759**, under the $10 cap; the $5 warning line
fired. Three Gemini compact-IR responses were rejected (`structured_output`) and have unknown cost;
they are counted as `unavailable`, not as $0.00. Error taxonomy: `wrong_binding` 276 runs,
`wrong_context` 70, `structured_output` 3, `missing_field` 1. Recall and coverage saturated; the
separation is precision and block coverage. The images family is 0% semantic pass for all providers
because every model over-binds scope-guarded paths; that is a scope-adherence observation and a
future label-design question, not an image-recognition result.

Raw per-run records are in the git-ignored `benchmarks/gold_runs.jsonl`; the committed reports are
aggregates only. Verified Docentric AX compatibility remains `not_tested`.


## 9. v0.11 affected subset (#24/#25)

The v0.11 P0 work did not rerun the full 288-run matrix. It reran the affected 12 cases — the three
image cases plus nine hard/adversarial cases covering ambiguity, missing fields, nested lists and
forbidden scope — with 3 providers and 2 repeats: **72 planned runs**, budget cap **$4**, warning
line **$3**. Gemini used compact v2 with two repair calls; the priced providers used one.

The goal was a controlled before/after check on the families that drove the v0.10 result, not a new
ranking. The v0.10 full report is retained as a historical artifact for dataset `1.0.0`; the v0.11
subset report is [gold_report_v011_subset.json](../benchmarks/gold_report_v011_subset.json).

What the subset adds beyond the v0.10 table:

- `counters` with explicit planned/executed/skipped/succeeded/failed invariants;
- `pass@k` per provider, plus per-family semantic pass;
- `abstention_rate` and `review_rate`, derived from the mapping report's `needs_review` rows;
- a separate `image_family` scorecard with per-case label status and image-binding presence;
- `governance.at07_status: partial` and `second_human_annotator: false`;
- `settings.candidate_filter` and the candidate-list bounds.

The committed subset result: **72/72 executed**, 70 valid templates, 69 semantic passes,
precision **0.141 → 0.962** on the affected cases with recall 1.000, semantic pass **44.4% →
95.8%**, image family **0% → 100%**, abstention **25.0%**, `pass@2` **97.2%**, spend **$0.9387**
(below the $3 warning line and $4 cap). The three Gemini nested-list misses are a compact-v2
wire-format limitation (outer table plus nested repeat is not expressible), not a label change.
The detailed table and caveats are in
[EVALUATION §2.8](EVALUATION.md#28-v011-semantic-precision-and-adjudicated-labels-2425), generated
from the committed JSON rather than retyped.

The dataset to quote with these numbers is `2.0.0`, canonical SHA-256
`a36cf286c0c8cad59a4e770927488f6d5a931d2d2423740277d5c7a3c77943ed`. Do not combine this 72-run
subset with the 288-run v0.10 aggregate.

## 10. v0.12 full benchmark (32 × 3 × 3, V012-02)

This is the full-matrix semantic benchmark required for the v0.12 release. It is
**not** spliced with the v0.10 full report or the v0.11 affected subset.

| Field | Value |
| --- | --- |
| Dataset | `gold-cases/v2` version `2.0.0`, 32 cases |
| Dataset SHA-256 | `8489e4c07f9a8c87e76c0e7fa4a7da8c7f9d6ec0ca0b04eb36cfcd4fe003fd4b` |
| Manifest | [benchmarks/gold_manifest_v012.json](../benchmarks/gold_manifest_v012.json) |
| Manifest SHA-256 | `b830ed6313955a87576c5bfc110730a35294364c0fc8ae61d2942b0c534ceba3` |
| Runs file | [benchmarks/gold_runs_v012.jsonl](../benchmarks/gold_runs_v012.jsonl) (sanitized records) |
| Aggregate report | [gold_report_v012.json](../benchmarks/gold_report_v012.json) · [HTML](../benchmarks/gold_report_v012.html) · [CSV](../benchmarks/gold_report_v012.csv) |
| Providers | `gpt-6-sol`, `claude-sonnet-5-5`, `gemini-3.6-flash` (observed ids pinned in the manifest) |
| Repeats | 3 per case/provider |
| Planned logical runs | 288 (96 per provider) |
| Temperature / output cap | `0.0` / `16000` tokens |
| Repair attempts | OpenAI/Anthropic 1, Gemini 2 (compact v2) |
| Candidate filter | v0.11.1 |
| Application commit | `05bb71325e10720b3c47822e1dec31610edeab02` |
| Evaluator / planner version | `1.0.1` / `0.12.0` |
| Run timestamp | 2026-11-06 (see `generated_at` in the report) |
| Spend | **$3.9251** (`$3.7915` verified + `$0.1336` estimated Gemini proxy) |

The run was produced before the V012-05 alias/table fixes. Those fixes are a
separate planner change and are covered by the targeted regression described in
`docs/EVALUATION.md`; the full 288-run matrix above remains the V012-02 artifact
and is not edited or spliced.

### 10.1 Counters

| Counter | Value |
| --- | ---: |
| Planned logical runs | 288 |
| Completed (schema-valid attempt) | 284 |
| Technical failures (`structured_output`) | 4 |
| Skipped / blocked | 0 / 0 |
| Valid templates | 283 |
| Semantic passes | 277 |
| Correct (valid + semantic) | 276 |
| Semantic failures among completed | 7 |

`completed + technical + skipped = planned` and `executed = succeeded + failed`.
A technical failure is **not** a semantic failure: the semantic-pass denominator
is 284 completed runs. The technical-failure rate is reported separately
(4/288 = 1.39%).

### 10.2 Aggregate metrics

| Metric | Value |
| --- | ---: |
| Semantic precision | **0.9535** (841 correct / 882 predicted bindings) |
| Semantic recall | **1.0000** |
| F1 | **0.9762** |
| Requirement coverage | 1.0000 |
| Semantic pass rate (evaluable) | **97.54%** (277/284) |
| Valid template rate (completed) | **99.65%** (283/284) |
| Valid template rate (all executed) | 98.26% (283/288) |
| Technical failure rate | 1.39% (4/288) |
| Abstention rate | 12.68% (36/284) |
| Review rate | 25.35% (72/284) |
| pass@1 / pass@2 / pass@3 | 96.88% / 97.92% / 97.92% |
| Latency p50 / p95 | 3637.5 ms / 8379.6 ms |
| Cost per completed run | $0.013821 |
| Cost per semantic pass | $0.014170 |

### 10.3 Per provider

| Provider | Runs | Valid | Correct | Precision | Recall | Semantic pass | Technical | p50 | Cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| OpenAI `gpt-6-sol` | 96 | 96 | 96 | 0.950 | 1.000 | **100.0%** | 0 | 4639.5 ms | $1.2996 verified |
| Anthropic `claude-sonnet-5-5` | 96 | 95 | 95 | 0.950 | 1.000 | **100.0%** | 0 | 3751.5 ms | $2.4918 verified |
| Gemini `gemini-3.6-flash` | 96 | 92 | 85 | 0.961 | 1.000 | **92.4%** | 4 | 1333.0 ms | $0.1336 estimated |

### 10.4 Error and family breakdown

- Primary error codes: `wrong_context` 48, `structured_output` 4,
  `unsupported_expression` 1. An error code counts a run; it is not a measure
  of how many fields were wrong.
- Every non-nested family passes 100% semantically for all three providers:
  flat fields, images, collections, conditions, missing, ambiguous,
  multilingual, long tables and forbidden scope.
- The Gemini **nested-list** family is the known compact-v2 limitation:
  2/9 semantic passes. The model often emits an outer `rep` with an inner
  `tbl` instead of the requested outer table, and four Gemini runs fail
  structured output. The labels are correct; this is the wire-format gap that
  V012-05 addresses in a later commit. No label was loosened to hide it.
- Anthropic's single valid-template miss is a V3-002 duplicate-alias event in
  `cc-nested-task-effort`; its semantics were still correct. The same V012-05
  change makes that alias conflict deterministic.
- Split results: calibration OpenAI/Anthropic 100%, Gemini 93.2%; holdout
  OpenAI 100%, Anthropic 97.2%, Gemini 90.9%. The holdout is not used for
  tuning.

### 10.5 Comparison with v0.10 and v0.11 (not spliced)

| Artifact | Dataset | Cases | Repeats | Runs | Precision | Semantic pass |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| v0.10 full | `1.0.0` | 32 | 3 | 288 | 0.2087 | 63.19% |
| v0.11 affected subset | `2.0.0` | 12 | 2 | 72 | 0.9615 | 95.83% |
| **v0.12 full** | **`2.0.0`** | **32** | **3** | **288** | **0.9535** | **97.54%** |

The comparison is descriptive. The v0.10 dataset and prompt differ, the v0.11
artifact is a 12-case subset, and the v0.12 evaluator separates technical
failures. The reports are shown side by side and are not combined into one
aggregate. See `comparison.differences` in the manifest for the exact statement.

### 10.6 Limits

- The labels are this project's judgement on synthetic fixtures, not absolute
  truth. No independent human review was performed; AT-07 stays `partial`.
- Three repeats show run-to-run variation; they are not a population sample.
- Provider models and prices change; the manifest pins the requested/observed
  model ids and the pricing table version.
- A technical failure is visible in the manifest with its reason and is excluded
  from the semantic denominator, never silently dropped or counted as a semantic
  failure.
- Docentric AX runtime compatibility remains **not_tested**. A semantic pass is
  not a Docentric AX execution proof.

### 10.7 V012-05 affected subset (separate artifact)

After the alias/table fixes, the three nested cases were re-run on all providers
(27 logical runs): 23 completed, 4 Gemini `structured_output` technical
failures, 23/23 correct among completed, precision/recall/semantic pass 100% of
evaluable runs, spend $0.4761. The result is deliberately kept separate from the
288-run table above (which predates the fixes) and is documented in
[EVALUATION §2.11](EVALUATION.md#211-v012-05-affected-regression-nested-tables-and-aliases).
